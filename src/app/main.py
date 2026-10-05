import sys
import math
from pathlib import Path
from queue import PriorityQueue

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

LAND_CELLS = build_land_mask()

 
def is_aligned_with_wind(long, lat, dx, dy):
    """
    Determines if the movement direction (dx, dy) aligns with the wind direction.
    
    :param dx: Movement in the x-direction (grid coordinates)
    :param dy: Movement in the y-direction (grid coordinates)
    :return: 1 if aligned within a 12.5° range, 0 otherwise
    """
    
    # Convert grid coordinates to geographical coordinates
    geo_latitude = round_latitude(grid_to_latitude(lat))
    geo_longitude = round_longitude(grid_to_longitude(long))
    
     
    # Instantiate WindDirectionRetriever and retrieve wind direction for the given geographical location
    wind_direction = wind_direction_retriever.retrieve_wind_direction(geo_longitude, geo_latitude)
     
    # Calculate and normalize the movement angle
    movement_angle = round(math.degrees(math.atan2(dy, dx))) % 360

    # Define the alignment range (±25° around the wind direction)
    lower_bound = (wind_direction - 25) % 360
    upper_bound = (wind_direction + 25) % 360
    
    

    # Check if the movement angle is within the alignment range
    if (lower_bound <= movement_angle <= upper_bound) or (lower_bound > upper_bound and (movement_angle >= lower_bound or movement_angle <= upper_bound)):
        print(geo_longitude, geo_latitude, 1, wind_direction, movement_angle)
        return 1
    else:
        print(geo_longitude, geo_latitude, 0, wind_direction, movement_angle)
        return 0


def is_aligned_with_current(long, lat, dx, dy):
    """
    Determines if the movement direction (dx, dy) aligns with the ocean current direction.
    
    :param long: Longitude in grid coordinates
    :param lat: Latitude in grid coordinates
    :param dx: Movement in the x-direction (grid coordinates)
    :param dy: Movement in the y-direction (grid coordinates)
    :return: 1 if aligned within a 25° range, 0 otherwise
    """
    
    # Convert grid coordinates to geographical coordinates
    geo_latitude = round_latitude(grid_to_latitude(lat))
    geo_longitude = round_longitude(grid_to_longitude(long))
    
    # Instantiate CurrentRetriever and retrieve current direction for the given geographical location
    current_direction = ocean_current_retriever.retrieve_angle(geo_longitude, geo_latitude)
    
    # Calculate and normalizing the movement angle
    movement_angle = round(math.degrees(math.atan2(dy, dx))) % 360

    # Alignment range (±25° around the current direction)
    lower_bound = (current_direction - 25) % 360
    upper_bound = (current_direction + 25) % 360
    
    # Checking if the movement angle is within the alignment range
    if (lower_bound <= movement_angle <= upper_bound) or (lower_bound > upper_bound and (movement_angle >= lower_bound or movement_angle <= upper_bound)):
        print(geo_longitude, geo_latitude, 1, current_direction, movement_angle)
        return 1
    else:
        print(geo_longitude, geo_latitude, 0, current_direction, movement_angle)
        return 0


    
# A* Algorithm with new heuristic integration
def euclidean(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)
 
def h2_heuristic(node):
    grid_x, grid_y = node
    latitude = round_latitude(grid_to_latitude(grid_y))
    longitude = round_longitude(grid_to_longitude(grid_x))
    
    heuristic_value = heuristic_retriever.get_heuristic_value(latitude, longitude, config.HEURISTICS_PKL)
    print("h2:", heuristic_value)
    return heuristic_value

def h3_heuristic(node):
    grid_x, grid_y = node
    latitude = round_latitude(grid_to_latitude(grid_y))
    longitude = round_longitude(grid_to_longitude(grid_x))
    
    heuristic_value = heuristic_retriever.get_heuristic_value(latitude, longitude,config.CARGO_PKL)
    print("h3:", heuristic_value)
    return heuristic_value

def h4_heuristic(node):
    grid_x, grid_y = node
    latitude = round_latitude(grid_to_latitude(grid_y))
    longitude = round_longitude(grid_to_longitude(grid_x))
    
    heuristic_value = heuristic_retriever.get_heuristic_value(latitude, longitude,config.PASSENGER_PKL)
    print("h4:", heuristic_value)
    return heuristic_value

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


#adjust this on the day of hackathon
def calculate_fscore(g_score, current, neighbor, end, is_first_box_green, is_second_box_green, wind_alignment, current_alignment):
    
    f_score = 0
    fuel_score = fuel_retriever.retrieve_fuel_efficiency(neighbor[0], neighbor[1])
    print(fuel_score)
    
    # print(fuel_retriever(68.125, 8.5))
    
    if is_first_box_green:  # cargo
        f_score = 0.3 * g_score + 0.7 * euclidean(neighbor, end) + 0.1 * h3_heuristic(neighbor)

    elif is_second_box_green:  # passenger
        f_score = 0.3 * g_score + 0.2 * euclidean(neighbor, end) + 1 * h4_heuristic(neighbor)
         #combined 
    
    else: #individual optimisation
        if horizontal_buttons[0]:  # Fuel
            # BUG FIX: this used to multiply fuel_score into f_score before
            # f_score had been set to anything (it was still 0 here), then
            # immediately overwrite it on the next line — so fuel_score was
            # silently never actually used. Applying it after f_score is
            # computed instead: higher fuel efficiency modestly discounts
            # cost, mirroring how wind/current alignment do below.
            f_score = 0.4 * g_score + 0.2 * euclidean(neighbor, end) + 0.1 * h2_heuristic(neighbor)
            f_score *= (1 - 0.1 * fuel_score)
            
        elif horizontal_buttons[1]:  # Speed
            f_score = 0.3 * g_score + 0.7 * euclidean(neighbor, end) + 0.1 * h2_heuristic(neighbor)
            
        elif horizontal_buttons[2]:  # Comfort
            f_score = 0.3 * g_score + 0.2 * euclidean(neighbor, end) + 1 * h2_heuristic(neighbor)
            
        else:
            # BUG FIX: this used to leave f_score at 0 for every node when
            # Individual mode was active (or just the default state) but no
            # Fuel/Speed/Comfort button had been picked yet — meaning A*
            # couldn't distinguish any neighbor from any other and the
            # search degenerated into an arbitrary, unguided crawl. Falling
            # back to the same balanced formula Speed uses keeps the search
            # meaningful even before a sub-priority is chosen.
            f_score = 0.3 * g_score + 0.7 * euclidean(neighbor, end) + 0.1 * h2_heuristic(neighbor)

    f_score *= get_ship_size_factor()

    if wind_alignment == 1:
        f_score *= 0.9
        
    if current_alignment ==1:
        f_score *= 0.9
        
    
    return f_score


def a_star(start, end, is_first_box_green, is_second_box_green):
    open_set = PriorityQueue()
    open_set.put((0, start))
    came_from = {}
    g_score = {start: 0}
    f_score = {start: calculate_fscore(g_score[start], start, start, end, is_first_box_green, is_second_box_green, 0, 0)}  # Initial alignment is 0 (not used yet)
    explored_nodes = []

    while not open_set.empty():
        _, current = open_set.get()

        # Visualize exploration
        if current != start and current != end:
            explored_nodes.append(current)
            pygame.draw.rect(screen, RED, (map_position[0] + current[0] * grid_size,
                                           map_position[1] + current[1] * grid_size,
                                           grid_size, grid_size))
            pygame.display.flip()
            pygame.time.delay(20)  # Slow down to visualize
        
        if current == end:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            
            # Reconstructing the green path
            background()
            drawGrid()
            # foreground() removed here — it was only ever needed to draw the
            # black land/sea mask so is_black_pixel() could read it back off
            # the screen. Now that build_land_mask() precomputes that once,
            # the visible map no longer needs the ugly overlay on it.
            weather_display.weather(screen, 28.6139, 77.2090)
            weather_display.weatherTwo(screen, 35.00, 45.2090)
            ui_elements.draw_fuel_estimation_button(screen)
            ui_elements.draw_image_analysis_button(screen)
            ui_elements.draw_retrain_model_button(screen)
            ui_elements.draw_path_coordinates_button(screen)
            ui_elements.draw_dim_boxes(screen)
            
            pygame.display.flip()
            pygame.time.delay(500) 
            
            # Draw path on screen
            for cell in path:
                pygame.draw.rect(screen, GREEN, (map_position[0] + cell[0] * grid_size,
                                                 map_position[1] + cell[1] * grid_size,
                                                 grid_size, grid_size))
                pygame.display.flip()
                pygame.time.delay(200)
                print("Path:", cell)
                
            pygame.time.delay(5000)
            
            return path, explored_nodes

        neighbors = get_neighbors(current)
        for neighbor, wind_alignment, current_alignment in neighbors:
            tentative_g_score = g_score[current] + euclidean(current, neighbor)
            tentative_f_score = calculate_fscore(tentative_g_score, current, neighbor, end, is_first_box_green, is_second_box_green, wind_alignment, current_alignment)
            
            if neighbor not in g_score or tentative_g_score < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g_score
                f_score[neighbor] = tentative_f_score
                open_set.put((f_score[neighbor], neighbor))

    return None, explored_nodes

blocks = storage.Backup_black_cells #remove if changing the map

# Get neighbors for A* (8-way movement)
def get_neighbors(position):
    neighbors = []
    directions = [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]
    
    for dx, dy in directions:
        nx, ny = position[0] + dx, position[1] + dy
        if 0 <= nx < grid_width/grid_size and 0 <= ny < grid_height/grid_size:
            if not is_black_pixel(nx, ny) and (nx, ny) not in blocks:
                # Check if the movement is aligned with the wind
                wind_alignment = is_aligned_with_wind(position[0]+dx, position[1]+dy, dx, dy)
                current_alignment = is_aligned_with_current(position[0]+dx, position[1]+dy, dx, dy)
                # Append the neighbor along with the wind alignment value
                neighbors.append(((nx, ny), wind_alignment, current_alignment))
    return neighbors


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
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if ui_elements.draw_button(screen, show_input_boxes).collidepoint(event.pos):
                show_input_boxes = not show_input_boxes
            if ui_elements.draw_start_button(screen).collidepoint(event.pos):  # Check if Start button is clicked
                start_button_clicked = True  # Set the flag when the start button is clicked
                exploration_done = False  # Reset exploration_done to allow a new search
            ui_elements.handle_mouse_click(event)
        
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_x, mouse_y = event.pos
            
            if(map_position[0]<=mouse_x<map_position[0]+550 and map_position[1]<=mouse_y<map_position[1]+600):
                grid_x = (mouse_x - map_position[0]) // grid_size
                grid_y = (mouse_y - map_position[1]) // grid_size
                
                if selected_start is None:
                    if not is_black_pixel(grid_x, grid_y) and grid_y>78:  # Check the grid_x, grid_y pixel
                        selected_start = (grid_x, grid_y)
                    else:
                        set_status("The selected coordinate is invalid, please try again!")
                        

                elif selected_end is None:
                    if not is_black_pixel(grid_x, grid_y) and grid_y>78:  # Check the grid_x, grid_y pixel
                        selected_end = (grid_x, grid_y)
                    else:
                        set_status("The selected coordinate is invalid, please try again!")

                else:
                    selected_start, selected_end = None, None
                
        if selected_start:
            pygame.draw.rect(screen, GREEN, (map_position[0] + selected_start[0] * grid_size,
                                         map_position[1] + selected_start[1] * grid_size,
                                         grid_size, grid_size))
            
        if selected_end:
            pygame.draw.rect(screen, RED, (map_position[0] + selected_end[0] * grid_size,
                                       map_position[1] + selected_end[1] * grid_size,
                                       grid_size, grid_size))
        
        pygame.display.flip()


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
                print(start,end)
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