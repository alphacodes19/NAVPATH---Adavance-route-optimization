import csv
import pickle
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import config
# latitude_to_grid / longitude_to_grid / round_latitude / round_longitude used to be
# redefined here, duplicating coord_convert.py exactly. Importing them instead so
# there's one definition of the grid <-> geo conversion to keep in sync.
from src.engine.coord_convert import (
    latitude_to_grid, longitude_to_grid, round_latitude, round_longitude,
)

# Function to process the CSV and filter by depth, storing results persistently in a pickle file
def process_csv(file_path, storage_file=None):
    storage_file = storage_file or str(config.PROCESSED_DIR / "lat_long_data.pkl")
    # Check if the data is already saved in the pickle file
    if os.path.exists(storage_file):
        # Load the pre-calculated data from the pickle file
        with open(storage_file, 'rb') as file:
            lat_long_dict = pickle.load(file)
        print("Loaded data from pickle file.")
    else:
        # Initialize a dictionary to store the latitude and longitude
        lat_long_dict = {}

        # Open the CSV file and read its contents
        with open(file_path, mode='r') as file:
            reader = csv.reader(file)
            next(reader)  # Skip the header line

            # Iterate through the rows in the CSV file
            for row in reader:
                latitude = float(row[0])  # Convert latitude to float
                longitude = float(row[1])  # Convert longitude to float
                depth = float(row[2])  # Convert depth to float

                # If depth is greater than -40, store the lat/long in the dictionary
                if depth > -40:
                    # Round and convert latitude and longitude to grid coordinates
                    rounded_lat = round_latitude(latitude)
                    rounded_long = round_longitude(longitude)

                    grid_y = latitude_to_grid(rounded_lat)
                    grid_x = longitude_to_grid(rounded_long)

                    # Create a unique key using grid coordinates
                    coordinate_key = f"{grid_x},{grid_y}"

                    # Store the depth in the dictionary using grid coordinates as the key
                    lat_long_dict[coordinate_key] = depth

        # After processing, save the data to a pickle file for future use
        with open(storage_file, 'wb') as file:
            pickle.dump(lat_long_dict, file)
        print("Data processed and saved to pickle file.")

    return lat_long_dict

# Retriever function: Get the depth for a specific grid coordinate
def retrieve_depth(grid_x, grid_y, storage_file=None):
    storage_file = storage_file or str(config.PROCESSED_DIR / "lat_long_data.pkl")
    # Check if the data is available in the pickle file
    if os.path.exists(storage_file):
        with open(storage_file, 'rb') as file:
            lat_long_dict = pickle.load(file)
        
        # Create the key for the coordinate
        coordinate_key = f"{grid_x},{grid_y}"
        
        # Retrieve the depth for the specified coordinates
        if coordinate_key in lat_long_dict:
            return lat_long_dict[coordinate_key]
        else:
            return -50  # No depth data found for the coordinate
    else:
        print("No data found. Please process the CSV first.")
        return -50

if __name__ == "__main__":
    # NOTE: this whole module is not currently wired into src/app/main.py's
    # pathfinding — see docs/architecture.md for details. It's kept so the
    # depth feature can be finished later.
    file_path = str(config.PROCESSED_DIR / "output_depth_data.csv")
    lat_long_dict = process_csv(file_path)

    grid_x = 56
    grid_y = 125
    depth_value = retrieve_depth(grid_x, grid_y)

    if depth_value is not None:
        print(f"Depth at ({grid_x}, {grid_y}): {depth_value}")
    else:
        print(f"No depth data found for grid coordinates ({grid_x}, {grid_y})")
