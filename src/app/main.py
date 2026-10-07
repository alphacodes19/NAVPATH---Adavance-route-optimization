import sys
import math
import threading
import queue
from pathlib import Path
from queue import PriorityQueue
import logging
logging.basicConfig(level = logging.WARNING)
from src.engine import depth_cells
from src.engine import router as route_engine
from src.engine.router import RouteParams, run_astar, compute_route_stats

# allow running this file directly (`python src/app/main.py`) as well as
# as a module (`python -m src.app.main`) from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pygame

from src import config
from src.app import ui_elements
from src.app.ui_elements import horizontal_buttons
from src.app import weather_display
from src.app.intro_animation import play_intro_animation
from src.engine.coord_convert import (
    grid_to_latitude, grid_to_longitude, latitude_to_grid, longitude_to_grid,
    round_longitude, round_latitude,
)
from src.engine import storage  # For the map boundary
from src.engine.heuristic_retriever import HeuristicRetriever
from src.engine import wind_retriever
from src.engine import current_retriever
from src.engine import fuel_retriever as fuel_retriever_lib

clock = pygame.time.Clock()

# Initialize Pygame
pygame.init()
heuristic_retriever = HeuristicRetriever()
fuel_retriever = fuel_retriever_lib.FuelEfficiencyRetriever()
# Loaded once and reused — the original code re-instantiated (and re-read the
# pickle file from disk) on every single A* neighbor check, which is very
# slow once the search space grows.
wind_direction_retriever = wind_retriever.WindDirectionRetriever()
ocean_current_retriever = current_retriever.OceanCurrentRetriever()
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
        if(y>350):
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

LAND_CELLS = build_land_mask():
    # --- Depth index (preloaded for O(1) lookup during A*) ---
# depth_cells.process_csv() returns a dict keyed by "grid_x,grid_y" → depth (metres, negative = below sea level)
# We convert to a (int, int) keyed dict for cleaner access.
_DEPTH_CSV = str(config.PROCESSED_DIR / "output_depth_data.csv")
_raw_depth = depth_cells.process_csv(_DEPTH_CSV) if __import__('os').path.exists(_DEPTH_CSV) else {}
DEPTH_GRID = {
    (int(k.split(',')[0]), int(k.split(',')[1])): v
    for k, v in _raw_depth.items()
}
logging.info(f"Depth grid loaded: {len(DEPTH_GRID)} cells")

# Default minimum safe depth (metres). Vessel draft increases this via get_ship_size_factor().
# A typical coastal cargo ship has a draft of ~6-8m; we add a 2m safety margin.
MIN_SAFE_DEPTH = -10.0  # -10m means at least 10m below sea level

 
# AFTER — is_aligned_with_wind

    
# A* Algorithm with new heuristic integration


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


#adjust this on the day of hackathon
# In calculate_fscore, add this at the very top of the function, before anything else:

# Get neighbors for A* (8-way movement)


# Function to check if a pixel is black — now a fast lookup against the
# mask built once at startup (see build_land_mask()) instead of reading the
# actual displayed pixels off the screen on every call.
def is_black_pixel(x, y):
    return (x, y) in LAND_CELLS

# Main loop
running = True
path_found = False  # New flag to check if the path has been found
show_input_boxes = False  # Flag to control input box visibility
start_button_clicked = False  # Flag to check if the start button is clicked
exploration_done = False  # Flag to prevent multiple explorations
selected_start = None # To store the start point : interactive click
selected_end = None # To store the end point : interactive click
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
        font = pygame.font.Font(None, 30)
        text = font.render(status_message, True, (255, 255, 255))
        box = text.get_rect()
        box.topleft = (map_position[0], map_position[1] - 35)
        bg_rect = box.inflate(16, 10)
        pygame.draw.rect(screen, (180, 0, 0), bg_rect, border_radius=6)
        screen.blit(text, box)

while running:
    # AFTER (correctly merged)
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

    screen.blit(background_image, (0, 0))  # Draw the background image

    # Draw background and grid
    background()
    drawGrid()
    # foreground() no longer drawn here — see build_land_mask() above.
  
    if start_x and start_y and end_x and end_y:
        weather_display.weather(screen,  start_y,  start_x )
        weather_display.weatherTwo(screen,  end_y,  end_x )
    else:
        weather_display.weather(screen, 28.6139, 77.2090)
        weather_display.weatherTwo(screen, 35.00, 45.2090)
    ui_elements.draw_fuel_estimation_button(screen)
    ui_elements.draw_image_analysis_button(screen)
    ui_elements.draw_retrain_model_button(screen)
    ui_elements.draw_path_coordinates_button(screen)
    ui_elements.draw_dim_boxes(screen)
    
    # Draw the "Start" button
    ui_elements.draw_start_button(screen)  # Ensure the "Start" button is drawn

    # Draw "Automatic" / "Manual" button
    ui_elements.draw_button(screen, show_input_boxes)

    # Display input boxes if show_input_boxes is active
    if show_input_boxes:
        ui_elements.draw_input_boxes(screen) 

    ui_elements.draw_new_input_boxes(screen)
    draw_status_message(screen)
    
    cargo, passenger = ui_elements.new_input_boxes[0], ui_elements.new_input_boxes[1]
    

    # If the start button is clicked and coordinates are provided
    if start_button_clicked and ((all(ui_elements.input_boxes)) or (selected_start != None and selected_end != None)) and not exploration_done:
        try:
            if all(ui_elements.input_boxes):
                # Convert input latitudes and longitudes to grid coordinates
                start_longitude = float(ui_elements.input_boxes[0])
                start_latitude = float(ui_elements.input_boxes[1])
                end_longitude = float(ui_elements.input_boxes[2])
                end_latitude = float(ui_elements.input_boxes[3])
                
                # Use CoordConv functions to convert to grid coordinates
                start = (longitude_to_grid(start_longitude), latitude_to_grid(start_latitude))
                end = (longitude_to_grid(end_longitude), latitude_to_grid(end_latitude))
                logging.info(f"A* start={start} end={end}")
                # Validate the grid coordinates
                if 0 <= start[0] < grid_width and 0 <= start[1] < grid_height and \
                0 <= end[0] < grid_width and 0 <= end[1] < grid_height:
                    # Call A* algorithm
                    path, explored_nodes = a_star(start, end, cargo, passenger)
                    if path:
                        path_found = True  # Mark that the path is found
                        pygame.display.flip()  # Update the screen after drawing the path
                    else:
                        set_status("Path not found")
                    exploration_done = True  # Set the flag to prevent further exploration
                else:
                    set_status("Invalid start or end coordinates")
                    
            else:
                start = selected_start
                start_y = grid_to_latitude(start[1])
                start_x = grid_to_longitude(start[0])
                end = selected_end
                end_y = grid_to_latitude(end[1])
                end_x = grid_to_longitude(end[0])
                path, explored_nodes = a_star(start,end, cargo, passenger)
                if path:
                    path_found = True
                    pygame.display.flip()
                else:
                    set_status("Path not found")
                
                exploration_done = True                
                
        except ValueError:
            set_status("Please enter valid integers for coordinates")

    pygame.display.flip()
    clock.tick(30)