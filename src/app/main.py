import sys
import threading
import queue
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

# allow running this file directly (`python src/app/main.py`) as well as
# as a module (`python -m src.app.main`) from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pygame

from src import config
from src.app import ui_elements
from src.app import weather_display
from src.app import route_panel
from src.app.intro_animation import play_intro_animation
from src.engine.coord_convert import (
    grid_to_latitude, grid_to_longitude, latitude_to_grid, longitude_to_grid,
    round_longitude, round_latitude,
)
from src.engine import storage  # For the map boundary
from src.engine import depth_cells
from src.engine import router as route_engine
from src.engine import snapshot_heuristics
from src.engine.router import (
    RouteParams, run_astar, run_multi_route, run_date_comparison,
    compute_route_stats, explain_route,
)
from src.engine.exporter import export_csv, export_gpx

clock = pygame.time.Clock()

# Initialize Pygame
pygame.init()
intro_video_path = config.INTRO_VIDEO

# Set up the display
info = pygame.display.Info()  # Get display information
screen_width, screen_height = info.current_w, info.current_h
screen = pygame.display.set_mode((screen_width, screen_height), pygame.FULLSCREEN)
pygame.display.set_caption("Ship Navigation Algo")

play_intro_animation(screen, intro_video_path, screen_width, screen_height)
background_image = pygame.image.load(config.BACKGROUND_IMG)  # Replace with your image path
background_image = pygame.transform.scale(background_image, (screen_width, screen_height))

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (0, 0, 200)
GREEN = (0, 150, 0)
RED = (255, 0, 0)

# Border Tips
NORTH = (40, 9)
SOUTH = (49, 135)
WEST = (16, 71)
EAST = (121, 51)

# Grid properties
grid_size = 4  # Size of each grid cell in pixels
grid_width, grid_height = 550, 600  # Number of cells in each dimension

# Background image positions
map_position = (100, 70)

# --- Images loaded once, not on every frame ------------------------------
# The original background()/foreground() reloaded these files from disk and
# rescaled them on *every single frame* (up to 60x/sec). Loading once here
# and just blitting the cached Surface each frame is both much cheaper and
# removes a pointless disk-I/O bottleneck from the render loop.
_india_map_surface = pygame.transform.scale(pygame.image.load(config.INDIA_MAP_IMG), (550, 600))
_india_overlay_surface = pygame.transform.scale(pygame.image.load(config.INDIA_FOREGROUND_IMG), (550, 600))


def background():
    screen.blit(_india_map_surface, map_position)


def foreground():
    # No longer drawn during normal play — see build_land_mask() below.
    # Kept so a debug view can still show the raw land/sea mask on request.
    screen.blit(_india_overlay_surface, map_position)


# Function to draw grid over the background
def drawGrid():
    for x in range(map_position[0], map_position[0] + 550, grid_size):
        pygame.draw.line(screen, BLUE, (x, map_position[1]), (x, map_position[1] + 600))
    for y in range(map_position[1], map_position[1] + 600, grid_size):
        if y > 350:
            pygame.draw.line(screen, BLUE, (map_position[0], y), (map_position[0] + 550, y))


def build_land_mask():
    """
    Precompute which grid cells are land, once at startup, instead of
    reading pixel colors off the *live displayed screen* on every single
    A* neighbor check (the original is_black_pixel() did screen.get_at()).

    That had two problems: it was slow (a screen read per neighbor, every
    step of the search), and it meant the ugly black land/sea overlay
    (IndiaFore3.png) had to actually be drawn on screen for pathfinding to
    work at all — that overlay is what made the map look broken.

    This builds the same composite off-screen once, sniffs out which grid
    cells are black, and after this the visible screen never needs the
    overlay drawn on it again.
    """
    mask_surface = pygame.Surface((550, 600))
    mask_surface.blit(_india_map_surface, (0, 0))
    mask_surface.blit(_india_overlay_surface, (0, 0))

    land_cells = set()
    for gx in range(grid_width // grid_size):
        for gy in range(grid_height // grid_size):
            px = gx * grid_size + grid_size // 2
            py = gy * grid_size + grid_size // 2
            if mask_surface.get_at((px, py))[:3] == BLACK:
                land_cells.add((gx, gy))
    return land_cells


LAND_CELLS = build_land_mask()

# --- Depth index (preloaded for O(1) lookup during A*) ---
# depth_cells.process_csv() returns a dict keyed by "grid_x,grid_y" → depth (metres, negative = below sea level)
# We convert to a (int, int) keyed dict for cleaner access.
_DEPTH_CSV = str(config.PROCESSED_DIR / "output_depth_data.csv")
_raw_depth = depth_cells.process_csv(_DEPTH_CSV) if Path(_DEPTH_CSV).exists() else {}
DEPTH_GRID = {
    (int(k.split(',')[0]), int(k.split(',')[1])): v
    for k, v in _raw_depth.items()
}
logging.info(f"Depth grid loaded: {len(DEPTH_GRID)} cells")

# Default minimum safe depth (metres). Vessel draft increases this via get_ship_size_factor().
# A typical coastal cargo ship has a draft of ~6-8m; we add a 2m safety margin.
MIN_SAFE_DEPTH = -10.0  # -10m means at least 10m below sea level


def get_ship_size_factor():
    """
    The L/B/H/Eff ship-dimension boxes (src/app/ui_elements.py) accepted
    typed input but were never read by anything — pure decoration. Using
    them here as a simple size/efficiency multiplier on route cost: a
    bigger ship costs more to move per cell, and a higher stated engine
    efficiency offsets that. Leaving any box blank (or non-numeric) falls
    back to a neutral 1.0 factor, so this changes nothing for anyone who
    doesn't fill them in.
    """
    try:
        length = float(ui_elements.button_values[0])
        beam = float(ui_elements.button_values[1])
        height = float(ui_elements.button_values[2])
        efficiency = float(ui_elements.button_values[3])
    except ValueError:
        return 1.0

    if length <= 0 or beam <= 0 or height <= 0 or efficiency <= 0:
        return 1.0

    # Crude displacement proxy (L x B x H), normalized against a mid-size
    # cargo ship as a "neutral" reference so typical inputs land near 1.0.
    reference_volume = 200 * 30 * 15
    size_ratio = (length * beam * height) / reference_volume
    return size_ratio / efficiency


def get_min_depth_for_vessel():
    """
    Derive minimum required depth from vessel dimensions if entered.
    Draft is not directly in the L/B/H/Eff inputs, so we approximate:
      - H (height) of the vessel is used as a proxy for draft (conservative estimate)
      - If no H entered, fall back to MIN_SAFE_DEPTH constant
    A future improvement: add a dedicated Draft input box.
    """
    try:
        height = float(ui_elements.button_values[2])
        if height > 0:
            safety_margin = 2.0
            return -(height + safety_margin)  # negative = below sea level
    except (ValueError, IndexError):
        pass
    return MIN_SAFE_DEPTH


def get_vessel_draft():
    """
    Raw draft value (metres) from the H box, for the hard forbidden-cell
    filtering added in router.get_neighbors() (Phase 2D-3). Distinct from
    get_min_depth_for_vessel() above, which already folds the same +2m
    margin into a *soft* f-score penalty (min_depth) — this instead feeds
    RouteParams.draft, which get_neighbors() uses to exclude cells
    outright. Returns None when the box is blank/invalid, matching
    get_min_depth_for_vessel()'s own fallback (no vessel entered -> no
    hard filtering, same as before Phase 2D).
    """
    try:
        height = float(ui_elements.button_values[2])
        if height > 0:
            return height
    except (ValueError, IndexError):
        pass
    return None


def _get_individual_mode():
    """Read Fuel/Speed/Comfort button state and return mode string."""
    if ui_elements.horizontal_buttons[0]:
        return "fuel"
    elif ui_elements.horizontal_buttons[1]:
        return "speed"
    elif ui_elements.horizontal_buttons[2]:
        return "comfort"
    return "speed"  # default


# Function to check if a pixel is black — now a fast lookup against the
# mask built once at startup (see build_land_mask()) instead of reading the
# actual displayed pixels off the screen on every call.
def is_black_pixel(x, y):
    return (x, y) in LAND_CELLS


def _date_diff_thread_worker(params_base: RouteParams, date_a: str, date_b: str, result_queue: queue.Queue):
    """
    Runs run_date_comparison() (Phase 2C-3) on a background thread.
    Never touches pygame directly.
    """
    def on_cell_explored(cell):
        result_queue.put({"type": "explored", "cell": cell})

    try:
        results = run_date_comparison(params_base, date_a, date_b, progress_callback=on_cell_explored)
        result_queue.put({"type": "date_diff_done", "results": results})
    except Exception as e:
        logging.exception("Date comparison thread failed")
        result_queue.put({"type": "error", "msg": str(e)})


def _draw_date_diff_routes(screen):
    """Draw both historical-date routes on the map — A first, then B on top."""
    colours = {"a": ROUTE_COLOR_DATE_A, "b": ROUTE_COLOR_DATE_B}
    for key in ("a", "b"):
        path = _date_diff_results.get(key, {}).get("path")
        if not path:
            continue
        colour = colours[key]
        for cell in path:
            pygame.draw.rect(
                screen, colour,
                (map_position[0] + cell[0] * grid_size,
                 map_position[1] + cell[1] * grid_size,
                 grid_size, grid_size),
            )


# Main loop state
running = True
path_found = False  # True once a route has been found
show_input_boxes = False  # Flag to control input box visibility
start_button_clicked = False  # Flag to check if the start button is clicked
compare_button_clicked = False  # Flag to check if the Compare Routes button is clicked
exploration_done = False  # Flag to prevent multiple explorations
selected_start = None  # To store the start point : interactive click
selected_end = None  # To store the end point : interactive click
start_x = None
start_y = None
end_x = None
end_y = None

# On-screen status message — the original code only ever printed things
# like "invalid coordinate" or "path not found" to the terminal, which is
# easy to miss during a live demo/viva. This surfaces the same messages on
# the screen itself, for a few seconds each.
status_message = ""
status_message_time = 0
STATUS_MESSAGE_SECONDS = 4


def set_status(message):
    global status_message, status_message_time
    print(message)
    status_message = message
    status_message_time = pygame.time.get_ticks()


def draw_status_message(screen):
    if status_message and pygame.time.get_ticks() - status_message_time < STATUS_MESSAGE_SECONDS * 1000:
        font = ui_elements.get_font(30)
        text = font.render(status_message, True, (255, 255, 255))
        box = text.get_rect()
        box.topleft = (map_position[0], map_position[1] - 35)
        bg_rect = box.inflate(16, 10)
        pygame.draw.rect(screen, (180, 0, 0), bg_rect, border_radius=6)
        screen.blit(text, box)


# --- Threading: A* runs on a background thread so the UI stays responsive ---
_route_queue = queue.Queue()   # communication channel from A* thread to main thread
_route_thread = None           # reference to the running thread (None when idle)
_is_searching = False          # True while A* thread is alive
_current_path = None           # the last successfully found path (single-route mode)
_explored_cells = []           # cells to draw red (accumulated from queue)
_route_stats = {}              # stats dict returned by compute_route_stats()
_route_explanation = ""        # human-readable summary of the last route
_show_fuel_detail = False      # whether the fuel-estimation overlay is open

# --- Multi-route comparison state (Phase 2A) ---
_multi_routes = {}             # {'speed': {'path':[], 'stats':{}}, 'fuel':..., 'safe':...}
_selected_route_key = 'speed'  # which comparison route is highlighted / bold on the map
_compare_mode_active = False   # True → draw comparison panel + 3 paths instead of single-route panel
_comparison_header_rects = {}  # last-drawn column rects from draw_comparison_panel(), for click hit-testing

ROUTE_COLOR_SPEED = (0, 120, 255)
ROUTE_COLOR_FUEL = (0, 200, 80)
ROUTE_COLOR_SAFE = (255, 200, 0)
_ROUTE_COLORS = {"speed": ROUTE_COLOR_SPEED, "fuel": ROUTE_COLOR_FUEL, "safe": ROUTE_COLOR_SAFE}

# --- Historical date-diff state (Phase 2C-3) ---
_date_diff_results = {}        # {'a': {'date':..., 'path':..., 'stats':...}, 'b': {...}}
_date_diff_active = False      # True → draw both dated routes + diff panel instead of single/compare-mode
date_diff_button_clicked = False

ROUTE_COLOR_DATE_A = (0, 200, 255)   # cyan
ROUTE_COLOR_DATE_B = (255, 120, 0)   # orange


def _astar_thread_worker(params: RouteParams, result_queue: queue.Queue):
    """
    Runs A* on a background thread.
    Sends progress and results back to the main thread via result_queue.
    Never touches pygame directly.
    """
    def on_cell_explored(cell):
        result_queue.put({"type": "explored", "cell": cell})

    try:
        path, explored = run_astar(params, progress_callback=on_cell_explored)

        if path:
            stats = compute_route_stats(
                path,
                params.depth_grid,
                route_engine._fuel_retriever._index,
            )
            result_queue.put({
                "type": "done",
                "path": path,
                "explored": explored,
                "stats": stats,
            })
        else:
            result_queue.put({"type": "error", "msg": "No path found"})

    except Exception as e:
        logging.exception("A* thread failed")
        result_queue.put({"type": "error", "msg": str(e)})


def _multi_route_thread_worker(params_base: RouteParams, result_queue: queue.Queue):
    """
    Runs run_multi_route() (speed/fuel/safe) on a background thread.
    Never touches pygame directly. Explored-cell progress from all three
    runs is merged into one shared callback — see run_multi_route()'s
    docstring if per-mode progress bars are wanted later.
    """
    def on_cell_explored(cell):
        result_queue.put({"type": "explored", "cell": cell})

    try:
        results = run_multi_route(params_base, progress_callback=on_cell_explored)
        result_queue.put({"type": "multi_done", "results": results})
    except Exception as e:
        logging.exception("Multi-route thread failed")
        result_queue.put({"type": "error", "msg": str(e)})


def _draw_multi_routes(screen):
    """
    Draw all three comparison routes on the map. The non-selected routes
    are drawn first at normal width, then the selected route is drawn
    last (so it sits on top) brighter and 3px wide.
    """
    for key, data in _multi_routes.items():
        if key == _selected_route_key:
            continue
        path = data.get("path")
        if not path:
            continue
        color = _ROUTE_COLORS.get(key, WHITE)
        for cell in path:
            pygame.draw.rect(
                screen, color,
                (map_position[0] + cell[0] * grid_size,
                 map_position[1] + cell[1] * grid_size,
                 grid_size, grid_size),
            )

    selected = _multi_routes.get(_selected_route_key)
    if selected and selected.get("path"):
        color = _ROUTE_COLORS.get(_selected_route_key, WHITE)
        bright = tuple(min(255, c + 60) for c in color)
        width = grid_size * 3
        offset = (width - grid_size) // 2
        for cell in selected["path"]:
            pygame.draw.rect(
                screen, bright,
                (map_position[0] + cell[0] * grid_size - offset,
                 map_position[1] + cell[1] * grid_size - offset,
                 width, width),
            )


while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            running = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            # --- Button clicks ---
            if ui_elements.draw_button(screen, show_input_boxes).collidepoint(event.pos):
                show_input_boxes = not show_input_boxes

            if ui_elements.draw_start_button(screen).collidepoint(event.pos):
                start_button_clicked = True
                exploration_done = False

            if ui_elements.draw_compare_routes_button(screen, _compare_mode_active).collidepoint(event.pos):
                compare_button_clicked = True
                exploration_done = False

            if ui_elements.draw_reset_button(screen).collidepoint(event.pos):
                # Reset all route state
                selected_start = None
                selected_end = None
                _current_path = None
                _explored_cells.clear()
                _route_stats = {}
                _route_explanation = ""
                _show_fuel_detail = False
                _multi_routes = {}
                _compare_mode_active = False
                _selected_route_key = 'speed'
                _comparison_header_rects = {}
                _date_diff_results = {}
                _date_diff_active = False
                path_found = False
                exploration_done = False
                start_button_clicked = False
                compare_button_clicked = False
                _is_searching = False
                background()
                drawGrid()
                set_status("Route cleared")

            if ui_elements.draw_path_coordinates_button(screen).collidepoint(event.pos):
                if _current_path and _route_stats:
                    cargo_sel, passenger_sel = ui_elements.new_input_boxes[0], ui_elements.new_input_boxes[1]
                    current_mode = "cargo" if cargo_sel else ("passenger" if passenger_sel else _get_individual_mode())
                    try:
                        csv_path = export_csv(_current_path, _route_stats, current_mode,
                                               output_dir="exports")
                        gpx_path = export_gpx(_current_path, _route_stats, current_mode,
                                               output_dir="exports")
                        set_status(f"Exported → exports/{current_mode}_*.csv + .gpx")
                        logging.info(f"Exported CSV: {csv_path}")
                        logging.info(f"Exported GPX: {gpx_path}")
                    except Exception as e:
                        set_status(f"Export failed: {e}")
                        logging.exception("Export failed")
                else:
                    set_status("Calculate a route first before exporting")

            if ui_elements.draw_fuel_estimation_button(screen).collidepoint(event.pos):
                _show_fuel_detail = not _show_fuel_detail  # toggle

            # --- Date selector arrows / Compare Dates button (Phase 2C) ---
            if ui_elements.handle_date_selector_click(event):
                pass  # consumed — cycled a date arrow
            elif ui_elements.draw_date_selectors(screen).collidepoint(event.pos):
                date_diff_button_clicked = True
                exploration_done = False

            # --- Comparison panel column clicks (uses last-drawn header rects) ---
            if _compare_mode_active:
                for key, rect in _comparison_header_rects.items():
                    if rect.collidepoint(event.pos):
                        _selected_route_key = key
                        break

            # --- Port selector arrows (only live while input boxes are shown) ---
            # --- Vessel selector arrows (always live, like the dim boxes themselves) ---
            if show_input_boxes and ui_elements.handle_port_selector_click(event):
                pass  # consumed — skip the coordinate-box hit-testing below
            elif ui_elements.handle_vessel_selector_click(event):
                pass  # consumed — cycled a vessel arrow
            else:
                ui_elements.handle_mouse_click(event)

            # --- Map clicks ---
            mouse_x, mouse_y = event.pos
            if (map_position[0] <= mouse_x < map_position[0] + 550 and
                    map_position[1] <= mouse_y < map_position[1] + 600):
                grid_x = (mouse_x - map_position[0]) // grid_size
                grid_y = (mouse_y - map_position[1]) // grid_size

                if selected_start is None:
                    if not is_black_pixel(grid_x, grid_y) and grid_y > 78:
                        selected_start = (grid_x, grid_y)
                    else:
                        set_status("The selected coordinate is invalid, please try again!")
                elif selected_end is None:
                    if not is_black_pixel(grid_x, grid_y) and grid_y > 78:
                        selected_end = (grid_x, grid_y)
                    else:
                        set_status("The selected coordinate is invalid, please try again!")
                else:
                    selected_start, selected_end = None, None

        if show_input_boxes:
            ui_elements.handle_input(event)
            ui_elements.handle_dir_input(event)

    # -----------------------------------------------------------------------
    # Drain the route queue — process messages from the A*/multi-route thread
    #
    # NOTE: this section only updates *state* now. All drawing of the path,
    # explored cells, and comparison routes happens once per frame in the
    # persistent render section below (after background()/drawGrid()).
    # Previously the final path/explored cells were drawn here directly,
    # but every frame — including this same one — the unconditional
    # `screen.blit(background_image, ...); background(); drawGrid()` call
    # further down ran *after* this and immediately erased them, so the
    # route never stayed visible. Driving the drawing from state instead
    # of from the arrival of a queue message fixes that for both
    # single-route and multi-route (comparison) results.
    # -----------------------------------------------------------------------
    while not _route_queue.empty():
        try:
            msg = _route_queue.get_nowait()
        except queue.Empty:
            break

        if msg["type"] == "explored":
            _explored_cells.append(msg["cell"])

        elif msg["type"] == "done":
            _is_searching = False
            exploration_done = True
            path_found = True
            _compare_mode_active = False
            _date_diff_active = False
            _current_path = msg["path"]
            _route_stats = msg.get("stats", {})

            dist = _route_stats.get("distance_nm", "?")
            depth = _route_stats.get("min_depth_m", "?")
            set_status(f"Route found — {dist} nm · min depth {depth} m")
            logging.info(f"Route stats: {_route_stats}")

            # Generate and store the route explanation
            _route_explanation = explain_route(
                _current_path,
                DEPTH_GRID,
                route_engine._fuel_retriever._index,
                LAND_CELLS,
            )
            logging.info(f"Route explanation: {_route_explanation}")

        elif msg["type"] == "multi_done":
            _is_searching = False
            exploration_done = True
            path_found = False
            _compare_mode_active = True
            _date_diff_active = False
            _multi_routes = msg["results"]
            _selected_route_key = 'speed'

            if any(r.get("path") for r in _multi_routes.values()):
                set_status("Comparison ready — click a column to highlight that route")
            else:
                set_status("No route found for any mode")

        elif msg["type"] == "date_diff_done":
            _is_searching = False
            exploration_done = True
            path_found = False
            _compare_mode_active = False
            _date_diff_active = True
            _date_diff_results = msg["results"]

            if any(r.get("path") for r in _date_diff_results.values()):
                set_status("Date comparison ready — cyan = Date A, orange = Date B")
            else:
                set_status("No route found for either date")

        elif msg["type"] == "error":
            _is_searching = False
            exploration_done = True
            set_status(msg["msg"])

    screen.blit(background_image, (0, 0))  # Draw the background image

    # Draw background and grid
    background()
    drawGrid()
    # foreground() no longer drawn here — see build_land_mask() above.

    # --- Persistent route drawing (driven by state, not by queue arrival) ---
    for cell in _explored_cells:
        pygame.draw.rect(
            screen, RED,
            (map_position[0] + cell[0] * grid_size,
             map_position[1] + cell[1] * grid_size,
             grid_size, grid_size),
        )

    if _compare_mode_active:
        _draw_multi_routes(screen)
    elif _date_diff_active:
        _draw_date_diff_routes(screen)
    elif _current_path:
        for cell in _current_path:
            pygame.draw.rect(
                screen, GREEN,
                (map_position[0] + cell[0] * grid_size,
                 map_position[1] + cell[1] * grid_size,
                 grid_size, grid_size),
            )

    if start_x and start_y:
        weather_display.weather(screen, start_y, start_x)
    else:
        weather_display.draw_weather_placeholder(screen, 700, 550, 240, 180, "Departure")

    if end_x and end_y:
        weather_display.weatherTwo(screen, end_y, end_x)
    else:
        weather_display.draw_weather_placeholder(screen, 970, 550, 240, 180, "Destination")

    ui_elements.draw_fuel_estimation_button(screen)
    ui_elements.draw_image_analysis_button(screen)
    ui_elements.draw_retrain_model_button(screen)
    ui_elements.draw_path_coordinates_button(screen)
    ui_elements.draw_dim_boxes(screen)
    ui_elements.draw_vessel_selector(screen)
    ui_elements.draw_reset_button(screen)
    ui_elements.draw_compare_routes_button(screen, _compare_mode_active)
    ui_elements.draw_date_selectors(screen)

    # Draw the "Calculate" button
    ui_elements.draw_start_button(screen)

    # Draw "Click on Map" / "Type Coordinates" button
    ui_elements.draw_button(screen, show_input_boxes)

    # Display input boxes if show_input_boxes is active
    if show_input_boxes:
        ui_elements.draw_port_selectors(screen)
        ui_elements.draw_input_boxes(screen)

    ui_elements.draw_new_input_boxes(screen)
    draw_status_message(screen)

    cargo, passenger = ui_elements.new_input_boxes[0], ui_elements.new_input_boxes[1]

    # -----------------------------------------------------------------------
    # Launch A* (single route) in a background thread when Calculate is clicked
    # -----------------------------------------------------------------------
    if start_button_clicked and not exploration_done and not _is_searching:
        start_button_clicked = False  # consume the click

        # Resolve start/end grid coordinates from whichever input method is active
        coords_ok = False
        try:
            if all(ui_elements.input_boxes):
                start_longitude = float(ui_elements.input_boxes[0])
                start_latitude = float(ui_elements.input_boxes[1])
                end_longitude = float(ui_elements.input_boxes[2])
                end_latitude = float(ui_elements.input_boxes[3])
                start = (longitude_to_grid(start_longitude), latitude_to_grid(start_latitude))
                end = (longitude_to_grid(end_longitude), latitude_to_grid(end_latitude))
                if (0 <= start[0] < grid_width and 0 <= start[1] < grid_height and
                        0 <= end[0] < grid_width and 0 <= end[1] < grid_height):
                    start_x = start_longitude
                    start_y = start_latitude
                    end_x = end_longitude
                    end_y = end_latitude
                    coords_ok = True
                else:
                    set_status("Invalid start or end coordinates")
            elif selected_start is not None and selected_end is not None:
                start = selected_start
                end = selected_end
                start_y = grid_to_latitude(start[1])
                start_x = grid_to_longitude(start[0])
                end_y = grid_to_latitude(end[1])
                end_x = grid_to_longitude(end[0])
                coords_ok = True
            else:
                set_status("Please select start and end points")

        except ValueError:
            set_status("Please enter valid numbers for coordinates")

        if coords_ok:
            # Determine mode from UI state
            if cargo:
                mode = "cargo"
            elif passenger:
                mode = "passenger"
            else:
                mode = _get_individual_mode()

            # Phase 2C-1/2C-2: if a historical date is selected (not "Default
            # (PKL)"), swap in that day's snapshot heuristic instead of the
            # trained PKL for this calculation.
            heuristic_override = None
            if ui_elements.date_selection != -1:
                _dates = snapshot_heuristics.list_available_dates()
                if ui_elements.date_selection < len(_dates):
                    heuristic_override = snapshot_heuristics.load_snapshot_heuristic(
                        _dates[ui_elements.date_selection]
                    )

            params = RouteParams(
                start=start,
                end=end,
                mode=mode,
                land_cells=LAND_CELLS,
                depth_grid=DEPTH_GRID,
                ship_size_factor=get_ship_size_factor(),
                min_depth=get_min_depth_for_vessel(),
                heuristic_override=heuristic_override,
                draft=get_vessel_draft(),
            )

            # Clear previous results
            _explored_cells.clear()
            _current_path = None
            _route_stats = {}
            _route_explanation = ""
            _multi_routes = {}
            _compare_mode_active = False
            _date_diff_results = {}
            _date_diff_active = False
            path_found = False
            exploration_done = False
            _is_searching = True

            set_status(f"Calculating {mode} route...")

            # Kick off the search thread
            _route_thread = threading.Thread(
                target=_astar_thread_worker,
                args=(params, _route_queue),
                daemon=True,   # thread dies if main window closes
            )
            _route_thread.start()

    # -----------------------------------------------------------------------
    # Launch multi-route comparison (speed/fuel/safe) when Compare Routes is clicked
    # -----------------------------------------------------------------------
    if compare_button_clicked and not exploration_done and not _is_searching:
        compare_button_clicked = False  # consume the click

        coords_ok = False
        try:
            if all(ui_elements.input_boxes):
                start_longitude = float(ui_elements.input_boxes[0])
                start_latitude = float(ui_elements.input_boxes[1])
                end_longitude = float(ui_elements.input_boxes[2])
                end_latitude = float(ui_elements.input_boxes[3])
                start = (longitude_to_grid(start_longitude), latitude_to_grid(start_latitude))
                end = (longitude_to_grid(end_longitude), latitude_to_grid(end_latitude))
                if (0 <= start[0] < grid_width and 0 <= start[1] < grid_height and
                        0 <= end[0] < grid_width and 0 <= end[1] < grid_height):
                    start_x = start_longitude
                    start_y = start_latitude
                    end_x = end_longitude
                    end_y = end_latitude
                    coords_ok = True
                else:
                    set_status("Invalid start or end coordinates")
            elif selected_start is not None and selected_end is not None:
                start = selected_start
                end = selected_end
                start_y = grid_to_latitude(start[1])
                start_x = grid_to_longitude(start[0])
                end_y = grid_to_latitude(end[1])
                end_x = grid_to_longitude(end[0])
                coords_ok = True
            else:
                set_status("Please select start and end points")

        except ValueError:
            set_status("Please enter valid numbers for coordinates")

        if coords_ok:
            # mode is overridden per-key inside run_multi_route(); "speed" here
            # is just a placeholder so RouteParams has a valid default.
            params_base = RouteParams(
                start=start,
                end=end,
                mode="speed",
                land_cells=LAND_CELLS,
                depth_grid=DEPTH_GRID,
                ship_size_factor=get_ship_size_factor(),
                min_depth=get_min_depth_for_vessel(),
                draft=get_vessel_draft(),
            )

            # Clear previous results
            _explored_cells.clear()
            _current_path = None
            _route_stats = {}
            _route_explanation = ""
            _multi_routes = {}
            _compare_mode_active = False
            _date_diff_results = {}
            _date_diff_active = False
            path_found = False
            exploration_done = False
            _is_searching = True

            set_status("Comparing speed / fuel / safe routes...")

            _route_thread = threading.Thread(
                target=_multi_route_thread_worker,
                args=(params_base, _route_queue),
                daemon=True,
            )
            _route_thread.start()

    # -----------------------------------------------------------------------
    # Launch historical date-diff comparison (Phase 2C-3) when Compare Dates clicked
    # -----------------------------------------------------------------------
    if date_diff_button_clicked and not exploration_done and not _is_searching:
        date_diff_button_clicked = False  # consume the click

        available_dates = snapshot_heuristics.list_available_dates()
        date_a_idx, date_b_idx = ui_elements.date_selection, ui_elements.date_b_selection

        if not available_dates:
            set_status("No historical snapshots found under data/snapshots/split_by_date/")
        elif date_a_idx == -1 or date_b_idx == -1:
            set_status("Pick two historical dates (not 'Default (PKL)') to compare")
        else:
            date_a = available_dates[date_a_idx]
            date_b = available_dates[date_b_idx]

            coords_ok = False
            try:
                if all(ui_elements.input_boxes):
                    start_longitude = float(ui_elements.input_boxes[0])
                    start_latitude = float(ui_elements.input_boxes[1])
                    end_longitude = float(ui_elements.input_boxes[2])
                    end_latitude = float(ui_elements.input_boxes[3])
                    start = (longitude_to_grid(start_longitude), latitude_to_grid(start_latitude))
                    end = (longitude_to_grid(end_longitude), latitude_to_grid(end_latitude))
                    if (0 <= start[0] < grid_width and 0 <= start[1] < grid_height and
                            0 <= end[0] < grid_width and 0 <= end[1] < grid_height):
                        start_x = start_longitude
                        start_y = start_latitude
                        end_x = end_longitude
                        end_y = end_latitude
                        coords_ok = True
                    else:
                        set_status("Invalid start or end coordinates")
                elif selected_start is not None and selected_end is not None:
                    start = selected_start
                    end = selected_end
                    start_y = grid_to_latitude(start[1])
                    start_x = grid_to_longitude(start[0])
                    end_y = grid_to_latitude(end[1])
                    end_x = grid_to_longitude(end[0])
                    coords_ok = True
                else:
                    set_status("Please select start and end points")

            except ValueError:
                set_status("Please enter valid numbers for coordinates")

            if coords_ok:
                mode = "cargo" if cargo else ("passenger" if passenger else _get_individual_mode())

                params_base = RouteParams(
                    start=start,
                    end=end,
                    mode=mode,
                    land_cells=LAND_CELLS,
                    depth_grid=DEPTH_GRID,
                    ship_size_factor=get_ship_size_factor(),
                    min_depth=get_min_depth_for_vessel(),
                    draft=get_vessel_draft(),
                )

                # Clear previous results
                _explored_cells.clear()
                _current_path = None
                _route_stats = {}
                _route_explanation = ""
                _multi_routes = {}
                _compare_mode_active = False
                _date_diff_results = {}
                _date_diff_active = False
                path_found = False
                exploration_done = False
                _is_searching = True

                set_status(f"Comparing {date_a} vs {date_b}...")

                _route_thread = threading.Thread(
                    target=_date_diff_thread_worker,
                    args=(params_base, date_a, date_b, _route_queue),
                    daemon=True,
                )
                _route_thread.start()

    # Draw comparison panel (multi-route), date-diff panel, or single-route panel + explanation
    if _compare_mode_active and _multi_routes:
        _comparison_header_rects = route_panel.draw_comparison_panel(
            screen, _multi_routes, _selected_route_key
        )
    elif _date_diff_active and _date_diff_results:
        route_panel.draw_date_diff_panel(screen, _date_diff_results)
    elif path_found and _route_stats:
        current_mode = "cargo" if cargo else ("passenger" if passenger else _get_individual_mode())
        route_panel.draw_route_panel(screen, _route_stats, current_mode)

    if path_found and _route_explanation and not _compare_mode_active:
        font_exp = ui_elements.get_font(22)
        # Word-wrap to fit panel width (560px)
        words = _route_explanation.split()
        lines = []
        current_line = ""
        for word in words:
            test = current_line + (" " if current_line else "") + word
            if font_exp.size(test)[0] > 540:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test
        if current_line:
            lines.append(current_line)

        exp_y = 780  # below the stats panel (panel ends at 550 + 220 = 770)
        for line in lines[:3]:  # max 3 lines
            surf = font_exp.render(line, True, (160, 160, 180))
            screen.blit(surf, (670, exp_y))
            exp_y += 20

    if _show_fuel_detail and _route_stats:
        route_panel.draw_fuel_detail(screen, _route_stats, get_ship_size_factor())

    # Show "Searching..." spinner while A* thread is alive
    if _is_searching:
        font = ui_elements.get_font(28)
        elapsed_ms = pygame.time.get_ticks()
        dots = "." * ((elapsed_ms // 500) % 4)  # cycles 0→1→2→3 dots every 500ms
        searching_text = font.render(f"Searching{dots}", True, (255, 255, 100))
        screen.blit(searching_text, (map_position[0], map_position[1] - 35))

    pygame.display.flip()
    clock.tick(30)