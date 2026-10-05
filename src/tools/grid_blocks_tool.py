import pygame
import sys
from pathlib import Path
import numpy as np  # Import numpy for pixel array manipulation

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import config
from src.engine import storage
from src.engine.coord_convert import grid_to_latitude, grid_to_longitude
# The local grid_to_latitude/grid_to_longitude that used to live here were a
# third, slightly different copy of the same math in coord_convert.py (this
# one skipped the 0.25-degree rounding step). They were only ever used for
# the illustrative print()s at the bottom of this file — findBlackCells()
# below works directly on pixel data and never used them — so switching to
# the shared version removes the duplicate without changing this tool's
# actual behavior (finding black cells).

# Initialize Pygame
pygame.init()

# Set up the display
info = pygame.display.Info()  # Get display information
screen_width, screen_height = info.current_w, info.current_h
screen = pygame.display.set_mode((screen_width, screen_height), pygame.FULLSCREEN)
pygame.display.set_caption("Ship Navigation Algo")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (0, 0, 200)
GREEN = (0, 150, 0)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)  # Color for marking black cells

# Grid properties
grid_size = 4  # Size of each grid cell in pixels
grid_width, grid_height = 550 // grid_size, 600 // grid_size  # Number of cells in each dimension

# Background image positions
map_position = (100, 70)

# Function to draw background
def background():
    image = pygame.image.load(config.INDIA_MAP_IMG)
    image = pygame.transform.scale(image, (550, 600))
    screen.blit(image, map_position)
    return image

# Function to draw foreground (overlay image)
def foreground():
    # IndiaFore.png is unused by the live app; kept in archive/unused/ since this
    # tool still references it.
    image = pygame.image.load(str(config.PROJECT_ROOT / "archive" / "unused" / "IndiaFore.png"))
    image = pygame.transform.scale(image, (550, 600))
    screen.blit(image, map_position)

# Function to draw grid over the background
def drawGrid():
    for x in range(map_position[0], map_position[0] + 550, grid_size):
        pygame.draw.line(screen, BLUE, (x, map_position[1]), (x, map_position[1] + 600))
    for y in range(map_position[1], map_position[1] + 600, grid_size):
        pygame.draw.line(screen, BLUE, (map_position[0], y), (map_position[0] + 550, y))
        
# (grid_to_latitude / grid_to_longitude now imported from coord_convert.py — see top of file)
 
# Function to detect black cells and store only the grid coordinates
def findBlackCells(image):
    block = set()  # Set to store the grid coordinates of black cells
    image_data = np.array(pygame.surfarray.pixels3d(image))  # Convert the image to a numpy array

    # Loop through each cell in the grid
    for x in range(grid_width):
        for y in range(grid_height):
            # Calculate pixel bounds for the current cell
            cell_x_start = map_position[0] + x * grid_size
            cell_y_start = map_position[1] + y * grid_size
            cell_x_end = cell_x_start + grid_size
            cell_y_end = cell_y_start + grid_size

            # Ensure pixel bounds are within image data bounds
            if cell_x_end - map_position[0] <= image_data.shape[1] and cell_y_end - map_position[1] <= image_data.shape[0]:
                # Extract the portion of the image that corresponds to the current grid cell
                cell_pixels = image_data[cell_x_start - map_position[0]:cell_x_end - map_position[0],
                                         cell_y_start - map_position[1]:cell_y_end - map_position[1]]

                # Check if any pixel in this cell is black
                if np.any(np.all(cell_pixels == [0, 0, 0], axis=-1)):
                    block.add((x, y))  # Add the grid coordinates to the set

    return block

# Main game loop
running = True
image = background()  # Load the background image
black_cells = findBlackCells(image)  # Find black cells and store them

print("Black cells found:", black_cells)  # Print the coordinates of black cells

# Define the target cell (grid coordinates) to be marked in green
target_cell = (86,78) # Replace this with the desired coordinates

while running:
    # Handle events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Draw everything
    screen.fill(WHITE)  # Clear the screen with a white background
    background()        # Draw the background image
    drawGrid()           # Draw the grid
    foreground()         # Draw the foreground image

    # Draw a colored rectangle on each black cell found
    for cell_coords in storage.Backup_black_cells:
        x, y = cell_coords
        # Draw a rectangle where the black cells are
        rect_x = map_position[0] + x * grid_size
        rect_y = map_position[1] + y * grid_size
        pygame.draw.rect(screen, YELLOW, (rect_x, rect_y, grid_size, grid_size))

    # Mark the target cell in green
    if target_cell:
        target_x, target_y = target_cell
        rect_x = map_position[0] + target_x * grid_size
        rect_y = map_position[1] + target_y * grid_size
        pygame.draw.rect(screen, GREEN, (rect_x, rect_y, grid_size, grid_size))

    pygame.display.update()  # Update the display

    # Set the frame rate
    pygame.time.Clock().tick(60)  # 60 frames per second
    
    # Example usage of coordinate converter for y axis:
    grid_y = 56  # Example grid y-coordinate
    latitude = grid_to_latitude(grid_y)
    print(f"Geographical latitude for grid y = {grid_y}: {latitude}°")
    
    print("Coordinate:  ", grid_to_longitude(56))

# Quit Pygame
pygame.quit()
sys.exit()
