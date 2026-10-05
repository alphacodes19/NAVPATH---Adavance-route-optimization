import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import netCDF4 as nc
import pandas as pd
import numpy as np

from src import config

def netcdf_to_csv(nc_file, csv_file):
    # Open the NetCDF file
    dataset = nc.Dataset(nc_file)

    # Check the dataset structure
    print("Dataset Variables:", dataset.variables.keys())

    # Extract latitude, longitude, and depth (elevation)
    latitudes = dataset.variables['lat'][:]  # Ensure 'lat' exists
    longitudes = dataset.variables['lon'][:]  # Ensure 'lon' exists
    depth = dataset.variables['elevation'][:]  # Ensure 'elevation' exists

    # Print the shapes of the data to ensure they are being loaded correctly
    print(f"Latitudes shape: {latitudes.shape}")
    print(f"Longitudes shape: {longitudes.shape}")
    print(f"Depth shape: {depth.shape}")

    # Create a grid for latitude and longitude
    latitudes_grid, longitudes_grid = np.meshgrid(latitudes, longitudes, indexing="ij")

    # Flatten the arrays to get 1D data for CSV
    latitudes_flat = latitudes_grid.flatten()
    longitudes_flat = longitudes_grid.flatten()
    depth_flat = depth.flatten()

    # Create a DataFrame to store the data
    df = pd.DataFrame({
        'Latitude': latitudes_flat,
        'Longitude': longitudes_flat,
        'Depth': depth_flat,
    })

    # Save the DataFrame to a CSV file
    df.to_csv(csv_file, index=False)
    print(f"CSV file saved to: {csv_file}")


if __name__ == "__main__":
    nc_file = config.RAW_DIR / "gebco_2024_n20.632_s10.437_w79.321_e86.616.nc"
    csv_file = config.PROCESSED_DIR / "output_depth_data.csv"
    netcdf_to_csv(str(nc_file), str(csv_file))
