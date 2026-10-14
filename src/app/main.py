import sys
import json
import copy
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
from src.app import visual_layers
from src.app.intro_animation import play_intro_animation
from src.engine.coord_convert import (
    grid_to_latitude, grid_to_longitude, latitude_to_grid, longitude_to_grid,
    round_longitude, round_latitude,
)
from src.engine import depth_cells
from src.engine.land_data import LAND_CELLS
from src.engine import router as route_engine
from src.engine import snapshot_heuristics
from src.engine.router import (
    RouteParams, run_astar, run_multi_route, run_date_comparison, run_pareto_sweep,
    build_voyage_timeline, compute_route_stats, estimate_fuel_cost, explain_route,
)
from src.data.vessels import VESSELS
from src.engine.benchmark import run_benchmark
from src.engine.exporter import export_csv, export_gpx


class _FallbackSlider:
    """Small Pygame slider fallback for projects whose ui_elements lacks Slider."""

    def __init__(self, x, y, w, min_val, max_val, start_val, label, unit="", prefix=""):
        if max_val <= min_val:
            raise ValueError("max_val must be greater than min_val")
        self.rect = pygame.Rect(int(x), int(y), int(w), 20)
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.value = max(self.min_val, min(self.max_val, float(start_val)))
        self.label = label
        self.unit = unit
        self.prefix = prefix
        self.dragging = False
        self.just_released = False
        self.handle_radius = 8

    def _set_value_from_x(self, mouse_x):
        fraction = (mouse_x - self.rect.x) / self.rect.w
        fraction = max(0.0, min(1.0, fraction))
        self.value = self.min_val + fraction * (self.max_val - self.min_val)

    def handle_event(self, event):
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.inflate(0, 20).collidepoint(event.pos)):
            self.dragging = True
            self.just_released = False
            self._set_value_from_x(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self._set_value_from_x(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.dragging:
            self._set_value_from_x(event.pos[0])
            self.dragging = False
            self.just_released = True

    def draw(self, target_screen, font=None):
        font = font or ui_elements.get_font(20)
        center_y = self.rect.centery
        pygame.draw.line(target_screen, (100, 100, 100),
                         (self.rect.left, center_y), (self.rect.right, center_y), 5)
        fraction = (self.value - self.min_val) / (self.max_val - self.min_val)
        handle_x = int(self.rect.x + fraction * self.rect.w)
        pygame.draw.circle(target_screen, (0, 150, 255),
                           (handle_x, center_y), self.handle_radius)
        pygame.draw.circle(target_screen, (255, 255, 255),
                           (handle_x, center_y), self.handle_radius, 2)
        text = font.render(
            f"{self.label}: {self.prefix}{self.value:.1f}{self.unit}",
            True, (255, 255, 255),
        )
        target_screen.blit(text, (self.rect.x, self.rect.y - 24))


_Slider = getattr(ui_elements, "Slider", _FallbackSlider)

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
    # No longer drawn during normal play — see src.engine.land_data.
    # Kept so a debug view can still show the raw land/sea mask on request.
    screen.blit(_india_overlay_surface, map_position)


# Function to draw grid over the background
def drawGrid():
    for x in range(map_position[0], map_position[0] + 550, grid_size):
        pygame.draw.line(screen, BLUE, (x, map_position[1]), (x, map_position[1] + 600))
    for y in range(map_position[1], map_position[1] + 600, grid_size):
        if y > 350:
            pygame.draw.line(screen, BLUE, (map_position[0], y), (map_position[0] + 550, y))


# LAND_CELLS is computed in src.engine.land_data so the engine and UI use
# one canonical mask without importing pygame into the routing engine.

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


def get_selected_heuristic_override():
    """
    The historical-date override currently selected via the "Historical
    Date" selector (Phase 2C) — None when "Default (PKL)" is selected.
    Shared by the Calculate launch block below and the heuristic-cost
    heatmap layer (Phase 3A, src/app/visual_layers.py) so both always
    agree on what's being shown. snapshot_heuristics.load_snapshot_heuristic()
    caches by date internally, so calling this every frame for the
    heatmap is cheap.
    """
    if ui_elements.date_selection == -1:
        return None
    dates = snapshot_heuristics.list_available_dates()
    if ui_elements.date_selection < len(dates):
        return snapshot_heuristics.load_snapshot_heuristic(dates[ui_elements.date_selection])
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


def _pareto_thread_worker(params_base: RouteParams, n: int, result_queue: queue.Queue):
    """
    Runs run_pareto_sweep() (Phase 3B) on a background thread. No per-cell
    progress is sent (see run_pareto_sweep's docstring) — instead a
    "pareto_progress" message is queued after each of the n runs so
    main.py can show "Pareto sweep: run i/n...".
    """
    def on_run_done(i, total):
        result_queue.put({"type": "pareto_progress", "i": i, "n": total})

    try:
        results = run_pareto_sweep(params_base, n=n, run_progress_callback=on_run_done)
        result_queue.put({"type": "pareto_done", "results": results})
    except Exception as e:
        logging.exception("Pareto sweep thread failed")
        result_queue.put({"type": "error", "msg": str(e)})


def _draw_pareto_route(screen):
    """Draw only the currently-selected Pareto-sweep run's route on the map."""
    if not (0 <= _selected_pareto_index < len(_pareto_results)):
        return
    path = _pareto_results[_selected_pareto_index].get("path")
    if not path:
        return
    for cell in path:
        pygame.draw.rect(
            screen, ROUTE_COLOR_PARETO,
            (map_position[0] + cell[0] * grid_size,
             map_position[1] + cell[1] * grid_size,
             grid_size, grid_size),
        )


def _benchmark_thread_worker(params_base: RouteParams, result_queue: queue.Queue):
    """
    Runs benchmark.run_benchmark() (Phase 3C: Dijkstra/Greedy/A*) on a
    background thread. No progress messages — each of the three full
    searches here is comparable in cost to a single Calculate click, so
    the existing "Searching..." spinner covers it without a cell-level
    progress feed.
    """
    try:
        results = run_benchmark(params_base)
        result_queue.put({"type": "benchmark_done", "results": results})
    except Exception as e:
        logging.exception("Benchmark thread failed")
        result_queue.put({"type": "error", "msg": str(e)})


def _draw_benchmark_route(screen):
    """Draw only the currently-selected benchmark algorithm's route on the map."""
    data = _benchmark_results.get(_selected_benchmark_key)
    if not data:
        return
    path = data.get("path")
    if not path:
        return
    color = _BENCHMARK_ROUTE_COLORS.get(_selected_benchmark_key, WHITE)
    for cell in path:
        pygame.draw.rect(
            screen, color,
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

# --- Emergency Routing (Phase 3F) ---
_emergency_result = None
_emergency_running = False
_emergency_request_id = 0
_last_params_base = None

# --- No-go zones (Phase 3G) ---
_nogo_cells = set()          # Grid cells forbidden for future route calculations
_painting_nogo = False       # True while right mouse button is held
_erasing_nogo = False        # Shift + right-click erases cells
_nogo_dirty = False          # Unsaved no-go-zone edits

# --- Fuel Price Slider (Phase 3E) ---
fuel_price_slider = _Slider(
    x=1250,
    y=635,
    w=230,
    min_val=50,
    max_val=150,
    start_val=100,
    label="Fuel Price",
    unit="/L",
    prefix="₹",
)

# --- What-if sliders (Phase 3H) ---
wind_slider = _Slider(
    x=1250, y=755, w=230,
    min_val=0.0, max_val=2.0, start_val=1.0,
    label="Wind Impact", unit="x",
)
current_slider = _Slider(
    x=1250, y=815, w=230,
    min_val=0.0, max_val=2.0, start_val=1.0,
    label="Current Impact", unit="x",
)
draft_slider = _Slider(
    x=1250, y=875, w=230,
    min_val=2.0, max_val=20.0, start_val=8.0,
    label="Draft", unit=" m",
)
_whatif_dirty = False
_whatif_running = False
_whatif_request_id = 0

# --- Voyage simulation state (Phase 3D) ---
_voyage_timeline = []
_voyage_active = False
_voyage_paused = False
_voyage_idx = 0.0
_voyage_elapsed_hours = 0.0
_voyage_speed_mult = 50.0
_VOYAGE_SPEED_STEPS = (10.0, 50.0, 200.0, 1000.0)
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

# --- Pareto sweep state (Phase 3B) ---
_pareto_results = []           # list from run_pareto_sweep(): [{'t','path','stats','pareto_optimal'}, ...]
_pareto_active = False         # True → draw the scatter panel + selected run's route instead of other panels
_selected_pareto_index = 0     # index into _pareto_results currently highlighted on the map
_pareto_point_rects = {}       # last-drawn scatter-point rects from draw_pareto_panel(), for click hit-testing
pareto_button_clicked = False

PARETO_SWEEP_N = 20            # per the workplan's run_pareto_sweep(params, n=20)
ROUTE_COLOR_PARETO = (230, 200, 60)   # gold — matches the frontier colour in draw_pareto_panel

# --- Algorithm benchmark state (Phase 3C) ---
_benchmark_results = {}        # {'dijkstra': {...}, 'greedy': {...}, 'astar': {...}} from benchmark.run_benchmark()
_benchmark_active = False      # True → draw the benchmark table + selected algorithm's route instead of other panels
_selected_benchmark_key = 'astar'  # which algorithm's route is highlighted on the map
_benchmark_header_rects = {}   # last-drawn column rects from draw_benchmark_panel(), for click hit-testing
benchmark_button_clicked = False

_BENCHMARK_ROUTE_COLORS = {
    "dijkstra": (120, 180, 255),
    "greedy": (255, 150, 100),
    "astar": (120, 230, 150),
}


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


def _whatif_thread_worker(params_base, wind_mult, current_mult, draft_m, request_id):
    """Recalculate a single route with the selected what-if overrides."""
    try:
        params = copy.copy(params_base)
        params.draft = float(draft_m)
        params.wind_scale = float(wind_mult)
        params.current_scale = float(current_mult)
        # Snapshot user-painted forbidden cells for this specific search.
        params.nogo_cells = set(getattr(params_base, "nogo_cells", None) or set())

        path, explored = route_engine.run_astar_whatif(
            params,
            wind_mult=wind_mult,
            current_mult=current_mult,
            progress_callback=None,
        )

        stats = {}
        if path:
            stats = compute_route_stats(
                path,
                params.depth_grid,
                route_engine._fuel_retriever._index,
            )

        _route_queue.put({
            "type": "whatif_done",
            "request_id": request_id,
            "path": path,
            "stats": stats,
            "params": params,
            "explored": explored,
        })
    except Exception as exc:
        logging.exception("What-if route recalculation failed")
        _route_queue.put({
            "type": "whatif_error",
            "request_id": request_id,
            "msg": str(exc),
        })


def _maybe_start_whatif_recalculation():
    """Launch at most one what-if A* job; slider changes are coalesced."""
    global _whatif_dirty, _whatif_running, _whatif_request_id, _is_searching

    if not _whatif_dirty or _whatif_running or _is_searching or _emergency_running:
        return
    if not _current_path or _last_params_base is None:
        # Keep the dirty flag until a base route exists, e.g. sliders moved
        # while the first normal search was still running.
        return

    _whatif_dirty = False
    _whatif_running = True
    _is_searching = True
    _whatif_request_id += 1
    request_id = _whatif_request_id

    params_snapshot = copy.copy(_last_params_base)
    params_snapshot.nogo_cells = set(_nogo_cells)
    wind_value = float(wind_slider.value)
    current_value = float(current_slider.value)
    draft_value = float(draft_slider.value)

    set_status("Recalculating route with what-if settings...")
    threading.Thread(
        target=_whatif_thread_worker,
        args=(params_snapshot, wind_value, current_value, draft_value, request_id),
        daemon=True,
    ).start()


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


# ---------------------------------------------------------------------------
# Voyage Simulation (Phase 3D)
# ---------------------------------------------------------------------------
def _get_voyage_speed_kn():
    """Get the selected vessel speed; Manual defaults to 14 knots."""
    selected = getattr(ui_elements, "vessel_selection", -1)
    if isinstance(selected, int) and 0 <= selected < len(VESSELS):
        return float(VESSELS[selected].get("speed_kn", 14.0))
    return 14.0


def _reset_voyage():
    """Clear simulation state when the route is cleared or recalculated."""
    global _voyage_timeline, _voyage_active, _voyage_paused
    global _voyage_idx, _voyage_elapsed_hours
    _voyage_timeline = []
    _voyage_active = False
    _voyage_paused = False
    _voyage_idx = 0.0
    _voyage_elapsed_hours = 0.0


def start_voyage():
    """Start or restart a simulation for the currently computed route."""
    global _voyage_timeline, _voyage_active, _voyage_paused
    global _voyage_idx, _voyage_elapsed_hours

    if not _current_path:
        set_status("Calculate a route before starting the voyage")
        return False

    speed_kn = _get_voyage_speed_kn()
    _voyage_timeline = build_voyage_timeline(
        _current_path, _route_stats, speed_kn
    )

    if not _voyage_timeline:
        set_status("Cannot simulate an empty route")
        return False

    _voyage_idx = 0.0
    _voyage_elapsed_hours = 0.0
    _voyage_active = True
    _voyage_paused = False
    set_status(
        f"Voyage started at {speed_kn:.1f} knots "
        f"({ _voyage_speed_mult:.0f}x simulation speed)"
    )
    return True


def update_voyage(dt_seconds):
    """Advance the simulation clock and interpolate the position by time."""
    global _voyage_idx, _voyage_elapsed_hours
    global _voyage_active, _voyage_paused

    if not _voyage_active or _voyage_paused or not _voyage_timeline:
        return
    if dt_seconds <= 0:
        return

    last_idx = len(_voyage_timeline) - 1
    total_hours = _voyage_timeline[-1]["hours_elapsed"]

    if last_idx == 0 or total_hours <= 0:
        _voyage_idx = float(last_idx)
        _voyage_active = False
        _voyage_paused = False
        set_status("Voyage completed — destination reached")
        return

    _voyage_elapsed_hours += dt_seconds * _voyage_speed_mult / 3600.0

    if _voyage_elapsed_hours >= total_hours:
        _voyage_elapsed_hours = total_hours
        _voyage_idx = float(last_idx)
        _voyage_active = False
        _voyage_paused = False
        set_status("Voyage completed — destination reached")
        return

    # Locate the path segment containing the current simulated time.
    i0 = min(int(_voyage_idx), last_idx - 1)
    while (
        i0 < last_idx - 1
        and _voyage_timeline[i0 + 1]["hours_elapsed"] < _voyage_elapsed_hours
    ):
        i0 += 1

    h0 = _voyage_timeline[i0]["hours_elapsed"]
    h1 = _voyage_timeline[i0 + 1]["hours_elapsed"]
    segment_hours = h1 - h0

    if segment_hours > 0:
        fraction = (_voyage_elapsed_hours - h0) / segment_hours
        fraction = max(0.0, min(1.0, fraction))
    else:
        fraction = 0.0

    _voyage_idx = i0 + fraction


def _get_voyage_display_state():
    """Return the interpolated map position and live voyage statistics."""
    if not _voyage_timeline:
        return None

    last_idx = len(_voyage_timeline) - 1
    idx = max(0.0, min(_voyage_idx, float(last_idx)))
    i0 = int(idx)
    i1 = min(i0 + 1, last_idx)
    fraction = idx - i0
    first = _voyage_timeline[i0]
    second = _voyage_timeline[i1]

    x0, y0 = first["pos"]
    x1, y1 = second["pos"]

    def interpolate(key):
        return first[key] + (second[key] - first[key]) * fraction

    return {
        "x": x0 + (x1 - x0) * fraction,
        "y": y0 + (y1 - y0) * fraction,
        "nm_covered": interpolate("nm_covered"),
        "hours_elapsed": interpolate("hours_elapsed"),
        "total_nm": _voyage_timeline[-1]["nm_covered"],
        "total_hours": _voyage_timeline[-1]["hours_elapsed"],
    }


def draw_voyage_ship(target_screen):
    """Draw the ship marker at its interpolated grid position."""
    state = _get_voyage_display_state()
    if state is None:
        return

    screen_x = map_position[0] + (state["x"] + 0.5) * grid_size
    screen_y = map_position[1] + (state["y"] + 0.5) * grid_size
    center = (int(screen_x), int(screen_y))

    pygame.draw.circle(target_screen, (255, 255, 255), center, 7)
    pygame.draw.circle(target_screen, (0, 150, 255), center, 7, 2)


def draw_voyage_hud(target_screen):
    """Display current voyage progress in a small top-right HUD."""
    state = _get_voyage_display_state()
    if state is None:
        return

    total_nm = state["total_nm"]
    covered_nm = state["nm_covered"]
    elapsed_hours = state["hours_elapsed"]
    total_hours = state["total_hours"]
    percentage = covered_nm / total_nm * 100.0 if total_nm > 0 else 100.0
    remaining_hours = max(0.0, total_hours - elapsed_hours)

    if _voyage_paused:
        voyage_status = "Paused"
    elif _voyage_active:
        voyage_status = "In progress"
    else:
        voyage_status = "Complete"

    lines = [
        f"Voyage: {voyage_status}",
        f"Progress: {percentage:.1f}%",
        f"Distance: {covered_nm:.1f} / {total_nm:.1f} nm",
        f"Elapsed: {elapsed_hours:.2f} hrs",
        f"ETA remaining: {remaining_hours:.2f} hrs",
        f"Simulation speed: {_voyage_speed_mult:.0f}x",
    ]

    # fuel_index is a relative route score, not a measured burn rate.
    fuel_index = _route_stats.get("fuel_index")
    if isinstance(fuel_index, (int, float)):
        lines.append(f"Relative fuel index: {fuel_index:.3f}")

    line_height = 24
    panel_width = 310
    panel_height = len(lines) * line_height + 16
    panel_x = max(20, target_screen.get_width() - panel_width - 20)
    panel_y = 20

    panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
    panel.fill((15, 25, 40, 210))
    target_screen.blit(panel, (panel_x, panel_y))

    font = ui_elements.get_font(20)
    for index, line in enumerate(lines):
        text_surface = font.render(line, True, (255, 255, 255))
        target_screen.blit(
            text_surface,
            (panel_x + 10, panel_y + 8 + index * line_height),
        )


# ---------------------------------------------------------------------------
# Emergency Routing (Phase 3F)
# ---------------------------------------------------------------------------
def _emergency_thread_worker(current_pos, params_base, request_id):
    """Run emergency routing in a background thread without touching pygame."""
    try:
        result = route_engine.run_emergency_route(
            current_pos,
            params_base,
            progress_callback=lambda cell: _route_queue.put({
                "type": "explored",
                "cell": cell,
            }),
        )
        _route_queue.put({
            "type": "emergency_done",
            "result": result,
            "request_id": request_id,
        })
    except Exception as exc:
        logging.exception("Emergency routing failed")
        _route_queue.put({
            "type": "emergency_error",
            "msg": str(exc),
            "request_id": request_id,
        })


def trigger_emergency_route():
    """Request a route from the current vessel position to a reachable port."""
    global _emergency_running, _emergency_result, _emergency_request_id

    if _is_searching:
        set_status("Wait for the current route calculation to finish")
        return

    if _emergency_running:
        set_status("Emergency routing is already running")
        return

    if _last_params_base is None:
        set_status("Calculate a route before requesting emergency routing")
        return

    # Prefer the interpolated voyage position while a voyage is underway.
    voyage_state = _get_voyage_display_state()
    if voyage_state is not None and _voyage_active:
        current_pos = (
            int(round(voyage_state["x"])),
            int(round(voyage_state["y"])),
        )
    elif _current_path:
        # The route parameters preserve the original start position.
        current_pos = _last_params_base.start
    else:
        set_status("No valid starting position for emergency routing")
        return

    _emergency_request_id += 1
    request_id = _emergency_request_id
    _emergency_result = None
    _emergency_running = True

    # Copy before the worker changes start/end/mode for emergency routing.
    emergency_params = copy.copy(_last_params_base)
    set_status("Finding the nearest reachable emergency port...")

    threading.Thread(
        target=_emergency_thread_worker,
        args=(current_pos, emergency_params, request_id),
        daemon=True,
    ).start()


def draw_emergency_route(target_screen, result):
    """Draw the emergency route above normal map layers and label its port."""
    if not result:
        return

    path = result.get("path") or []
    if not path:
        return

    # Convert route grid cells to pixel centres on the existing map.
    points = [
        (
            int(map_position[0] + (cell[0] + 0.5) * grid_size),
            int(map_position[1] + (cell[1] + 0.5) * grid_size),
        )
        for cell in path
    ]

    emergency_red = (255, 55, 55)
    if len(points) >= 2:
        pygame.draw.lines(target_screen, emergency_red, False, points, 4)
    elif points:
        pygame.draw.circle(target_screen, emergency_red, points[0], 5)

    # Mark the current position and the destination port.
    if points:
        pygame.draw.circle(target_screen, (255, 255, 255), points[0], 5)
        pygame.draw.circle(target_screen, emergency_red, points[0], 5, 2)
        pygame.draw.circle(target_screen, emergency_red, points[-1], 7)
        pygame.draw.circle(target_screen, (255, 255, 255), points[-1], 7, 2)

    port = result.get("port") or {}
    port_name = port.get("name") or port.get("port_name") or "Nearest reachable port"
    stats = result.get("stats") or {}
    distance = stats.get("distance_nm", result.get("great_circle_nm", 0.0))
    try:
        distance_text = f"{float(distance):.1f} nm"
    except (TypeError, ValueError):
        distance_text = "distance unavailable"

    label = f"EMERGENCY ROUTE  |  {port_name}  |  {distance_text}"
    font = ui_elements.get_font(20)
    label_surface = font.render(label, True, (255, 255, 255))

    # Keep the label within the map width, truncating very long port names.
    max_label_width = 530
    if label_surface.get_width() > max_label_width:
        while port_name and font.size(
            f"EMERGENCY ROUTE  |  {port_name}...  |  {distance_text}"
        )[0] > max_label_width:
            port_name = port_name[:-1]
        label = f"EMERGENCY ROUTE  |  {port_name}...  |  {distance_text}"
        label_surface = font.render(label, True, (255, 255, 255))

    label_rect = label_surface.get_rect(
        topleft=(map_position[0] + 6, map_position[1] + 6)
    )
    panel_rect = label_rect.inflate(16, 10)
    panel = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
    panel.fill((110, 0, 0, 225))
    target_screen.blit(panel, panel_rect.topleft)
    target_screen.blit(label_surface, label_rect)


# ---------------------------------------------------------------------------
# No-go Zones (Phase 3G): right-click to paint, Shift+right-click to erase
# ---------------------------------------------------------------------------
def screen_to_grid(screen_pos):
    """Convert a screen pixel position to a grid cell, or None outside the map."""
    screen_x, screen_y = screen_pos
    map_left, map_top = map_position
    map_right = map_left + 550
    map_bottom = map_top + 600

    if not (map_left <= screen_x < map_right and map_top <= screen_y < map_bottom):
        return None

    grid_x = int((screen_x - map_left) // grid_size)
    grid_y = int((screen_y - map_top) // grid_size)

    if not (0 <= grid_x < grid_width // grid_size and
            0 <= grid_y < grid_height // grid_size):
        return None

    return grid_x, grid_y


def _paint_nogo_cell_at(screen_pos, screen_to_grid_fn):
    """Paint or erase the cell under the pointer, but only inside the map."""
    global _nogo_dirty

    cell = screen_to_grid_fn(screen_pos)
    if cell is None:
        return

    if _erasing_nogo:
        if cell in _nogo_cells:
            _nogo_cells.discard(cell)
            _nogo_dirty = True
    else:
        if cell not in _nogo_cells:
            _nogo_cells.add(cell)
            _nogo_dirty = True


def handle_nogo_event(event, screen_to_grid_fn):
    """Handle right-button painting and Shift+right-button erasing."""
    global _painting_nogo, _erasing_nogo, _nogo_dirty

    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
        _painting_nogo = True
        _erasing_nogo = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        _paint_nogo_cell_at(event.pos, screen_to_grid_fn)

    elif event.type == pygame.MOUSEMOTION and _painting_nogo:
        _paint_nogo_cell_at(event.pos, screen_to_grid_fn)

    elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
        _painting_nogo = False
        _erasing_nogo = False
        if _nogo_dirty and save_nogo_zones():
            _nogo_dirty = False


def draw_nogo_zones(target_screen, nogo_cells):
    """Draw translucent red no-go cells above map layers and below route lines."""
    if not nogo_cells:
        return

    overlay = pygame.Surface((550, 600), pygame.SRCALPHA)
    overlay_cell = pygame.Surface((grid_size, grid_size), pygame.SRCALPHA)
    overlay_cell.fill((255, 35, 35, 115))

    for grid_x, grid_y in nogo_cells:
        if (0 <= grid_x < grid_width // grid_size and
                0 <= grid_y < grid_height // grid_size):
            overlay.blit(
                overlay_cell,
                (grid_x * grid_size, grid_y * grid_size),
            )

    target_screen.blit(overlay, map_position)


# Store zones in the project data directory so they survive application restarts.
NOGO_ZONES_FILE = Path(__file__).resolve().parents[2] / "data" / "nogo_zones.json"


def save_nogo_zones():
    """Persist painted no-go cells; return True only when the save succeeds."""
    try:
        NOGO_ZONES_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = sorted([int(x), int(y)] for x, y in _nogo_cells)
        temp_file = NOGO_ZONES_FILE.with_suffix(".json.tmp")
        with temp_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        temp_file.replace(NOGO_ZONES_FILE)
        return True
    except (OSError, TypeError, ValueError):
        logging.exception("Unable to save no-go zones to %s", NOGO_ZONES_FILE)
        return False


def load_nogo_zones():
    """Load saved no-go cells, ignoring malformed or out-of-map entries."""
    global _nogo_cells

    try:
        with NOGO_ZONES_FILE.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError:
        _nogo_cells = set()
        return
    except (OSError, json.JSONDecodeError):
        logging.exception("Unable to load no-go zones from %s", NOGO_ZONES_FILE)
        _nogo_cells = set()
        return

    loaded = set()
    if isinstance(payload, list):
        max_x = grid_width // grid_size
        max_y = grid_height // grid_size
        for item in payload:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            x, y = item
            # Avoid silently accepting floats, strings, or booleans as grid indices.
            if isinstance(x, bool) or isinstance(y, bool):
                continue
            if not isinstance(x, int) or not isinstance(y, int):
                continue
            if 0 <= x < max_x and 0 <= y < max_y:
                loaded.add((x, y))

    _nogo_cells = loaded
    logging.info("Loaded %d saved no-go cells", len(_nogo_cells))


def clear_nogo_zones():
    """Clear all no-go zones and persist the empty set."""
    global _nogo_dirty

    if not _nogo_cells:
        set_status("No-go zones are already clear")
        return

    _nogo_cells.clear()
    _nogo_dirty = True
    if save_nogo_zones():
        _nogo_dirty = False
        set_status("All no-go zones cleared and saved")
    else:
        set_status("No-go zones cleared, but saving failed")


# Restore previously painted zones once, before entering the event loop.
load_nogo_zones()


while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            running = False
            
        # Phase 3E: fuel-price slider interaction
        fuel_price_slider.handle_event(event)

        # Phase 3H: what-if sliders mark one recalculation on mouse release.
        _whatif_sliders = (wind_slider, current_slider, draft_slider)
        for whatif_slider in _whatif_sliders:
            whatif_slider.handle_event(event)
        if any(slider.just_released for slider in _whatif_sliders):
            for slider in _whatif_sliders:
                slider.just_released = False
            _whatif_dirty = True

        # No-go painting continues while the pointer moves and ends on right-button release.
        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):
            handle_nogo_event(event, screen_to_grid)

        # --- Visual layer toggles (Phase 3A) — keys 1-5 ---
        # Only live when no coordinate/dimension input box is focused for
        # typing, so "1".."5" still type into those boxes as digits when
        # the user is actually entering a coordinate or ship dimension.
        if (event.type == pygame.KEYDOWN and event.key != pygame.K_ESCAPE
                and ui_elements.active_box is None and ui_elements.active_box2 is None):
            visual_layers.handle_key_toggle(event.key)

            # Phase 3G: press C to clear every painted no-go zone.
            if event.key == pygame.K_c:
                clear_nogo_zones()
            # Temporary keyboard start until the dedicated UI button is wired.
            elif event.key == pygame.K_v:
                start_voyage()
            elif event.key == pygame.K_SPACE:
                if _voyage_active and _voyage_timeline:
                    _voyage_paused = not _voyage_paused
                    set_status("Voyage paused" if _voyage_paused else "Voyage resumed")
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                current_speed_index = min(
                    range(len(_VOYAGE_SPEED_STEPS)),
                    key=lambda i: abs(_VOYAGE_SPEED_STEPS[i] - _voyage_speed_mult),
                )
                next_speed_index = min(current_speed_index + 1, len(_VOYAGE_SPEED_STEPS) - 1)
                _voyage_speed_mult = _VOYAGE_SPEED_STEPS[next_speed_index]
                set_status(f"Simulation speed: {_voyage_speed_mult:.0f}x")
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                current_speed_index = min(
                    range(len(_VOYAGE_SPEED_STEPS)),
                    key=lambda i: abs(_VOYAGE_SPEED_STEPS[i] - _voyage_speed_mult),
                )
                next_speed_index = max(current_speed_index - 1, 0)
                _voyage_speed_mult = _VOYAGE_SPEED_STEPS[next_speed_index]
                set_status(f"Simulation speed: {_voyage_speed_mult:.0f}x")
            elif event.key == pygame.K_e:
                trigger_emergency_route()

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

            if ui_elements.draw_pareto_button(screen, _pareto_active).collidepoint(event.pos):
                pareto_button_clicked = True
                exploration_done = False

            if ui_elements.draw_benchmark_button(screen, _benchmark_active).collidepoint(event.pos):
                benchmark_button_clicked = True
                exploration_done = False

            if ui_elements.draw_voyage_button(
                screen, enabled=bool(_current_path), is_active=_voyage_active
            ).collidepoint(event.pos):
                if _current_path:
                    start_voyage()
                else:
                    set_status("Calculate a route before starting the voyage")

            if ui_elements.draw_reset_button(screen).collidepoint(event.pos):
                # Reset all route state
                selected_start = None
                selected_end = None
                _current_path = None
                _reset_voyage()
                _emergency_request_id += 1
                _emergency_result = None
                _emergency_running = False
                _last_params_base = None
                _whatif_request_id += 1
                _whatif_dirty = False
                _whatif_running = False
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
                _pareto_results = []
                _pareto_active = False
                _selected_pareto_index = 0
                _pareto_point_rects = {}
                _benchmark_results = {}
                _benchmark_active = False
                _selected_benchmark_key = 'astar'
                _benchmark_header_rects = {}
                path_found = False
                exploration_done = False
                start_button_clicked = False
                compare_button_clicked = False
                pareto_button_clicked = False
                benchmark_button_clicked = False
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

            # --- Pareto scatter-point clicks (uses last-drawn point rects) ---
            if _pareto_active:
                for idx, rect in _pareto_point_rects.items():
                    if rect.collidepoint(event.pos):
                        _selected_pareto_index = idx
                        break

            # --- Benchmark panel column clicks (uses last-drawn header rects) ---
            if _benchmark_active:
                for key, rect in _benchmark_header_rects.items():
                    if rect.collidepoint(event.pos):
                        _selected_benchmark_key = key
                        break

            # --- Port selector arrows (only live while input boxes are shown) ---
            # --- Vessel selector arrows (always live, like the dim boxes themselves) ---
            if show_input_boxes and ui_elements.handle_port_selector_click(event):
                pass  # consumed — skip the coordinate-box hit-testing below
            elif ui_elements.handle_vessel_selector_click(event):
                pass  # consumed — cycled a vessel arrow
            else:
                ui_elements.handle_mouse_click(event)

            # Process right-click painting after existing UI hit-testing so controls retain priority.
            if event.button == 3:
                handle_nogo_event(event, screen_to_grid)

            # --- Map clicks ---
            # Only left-clicks select route start/end points; right-clicks paint no-go cells.
            if event.button == 1:
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

    # Advance voyage time once per frame, using the previous frame duration.
    update_voyage(clock.get_time() / 1000.0)

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
            _pareto_active = False
            _benchmark_active = False
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
            _pareto_active = False
            _benchmark_active = False
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
            _pareto_active = False
            _benchmark_active = False
            _date_diff_results = msg["results"]

            if any(r.get("path") for r in _date_diff_results.values()):
                set_status("Date comparison ready — cyan = Date A, orange = Date B")
            else:
                set_status("No route found for either date")

        elif msg["type"] == "pareto_progress":
            set_status(f"Pareto sweep: run {msg['i']}/{msg['n']}...")

        elif msg["type"] == "pareto_done":
            _is_searching = False
            exploration_done = True
            path_found = False
            _compare_mode_active = False
            _date_diff_active = False
            _pareto_active = True
            _benchmark_active = False
            _pareto_results = msg["results"]

            # Default the selection to the first frontier point if any were
            # found, else just the first run that found a path at all.
            frontier_indices = [i for i, r in enumerate(_pareto_results) if r.get("pareto_optimal")]
            valid_indices = [i for i, r in enumerate(_pareto_results) if r.get("path")]
            if frontier_indices:
                _selected_pareto_index = frontier_indices[0]
            elif valid_indices:
                _selected_pareto_index = valid_indices[0]
            else:
                _selected_pareto_index = 0

            if valid_indices:
                set_status(f"Pareto sweep ready — {len(frontier_indices)} frontier points, click one to compare")
            else:
                set_status("Pareto sweep found no valid routes")

        elif msg["type"] == "benchmark_done":
            _is_searching = False
            exploration_done = True
            path_found = False
            _compare_mode_active = False
            _date_diff_active = False
            _pareto_active = False
            _benchmark_active = True
            _benchmark_results = msg["results"]
            _selected_benchmark_key = 'astar'

            if any(r.get("path") for r in _benchmark_results.values()):
                set_status("Benchmark ready — click a column to compare Dijkstra/Greedy/A*")
            else:
                set_status("Benchmark found no valid routes for any algorithm")

        elif msg["type"] == "whatif_done":
            if msg.get("request_id") == _whatif_request_id:
                _whatif_running = False
                _is_searching = False
                exploration_done = True
                new_path = msg.get("path")

                if new_path:
                    _current_path = new_path
                    _route_stats = msg.get("stats", {})
                    _last_params_base = msg.get("params")
                    _explored_cells.clear()
                    _route_explanation = explain_route(
                        _current_path,
                        DEPTH_GRID,
                        route_engine._fuel_retriever._index,
                        LAND_CELLS,
                    )
                    path_found = True
                    _reset_voyage()
                    _emergency_request_id += 1
                    _emergency_result = None
                    _emergency_running = False
                    set_status(
                        "What-if route updated — "
                        f"{_route_stats.get('distance_nm', '?')} nm"
                    )
                else:
                    # Retain the last valid route so a restrictive what-if
                    # setting does not blank the map or lose the prior result.
                    set_status(
                        "No route found for these what-if settings; "
                        "previous route retained"
                    )

        elif msg["type"] == "whatif_error":
            if msg.get("request_id") == _whatif_request_id:
                _whatif_running = False
                _is_searching = False
                set_status(f"What-if recalculation failed: {msg.get('msg', 'Unknown error')}")

        elif msg["type"] == "emergency_done":
            # Ignore results from an older request after a reset or new route.
            if msg.get("request_id") == _emergency_request_id:
                _emergency_running = False
                _emergency_result = msg.get("result")

                if _emergency_result:
                    port = _emergency_result["port"]
                    distance = _emergency_result["stats"].get("distance_nm", "unknown")
                    set_status(
                        f"Emergency route ready: {port.get('name', 'Nearest port')} "
                        f"· {distance} nm"
                    )
                else:
                    set_status("No reachable emergency port was found")

        elif msg["type"] == "emergency_error":
            if msg.get("request_id") == _emergency_request_id:
                _emergency_running = False
                _emergency_result = None
                set_status(f"Emergency routing failed: {msg.get('msg', 'Unknown error')}")

        elif msg["type"] == "error":
            _is_searching = False
            exploration_done = True
            set_status(msg["msg"])

    # Launch a pending what-if recalculation after any active search result
    # has been processed. Several slider releases collapse into one latest run.
    _maybe_start_whatif_recalculation()

    screen.blit(background_image, (0, 0))  # Draw the background image

    # Draw background and grid
    background()
    drawGrid()
    # foreground() no longer drawn here — see src.engine.land_data.

    # --- Visual d