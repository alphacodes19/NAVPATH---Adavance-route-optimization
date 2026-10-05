import openmeteo_requests
import requests_cache
import pandas as pd
import numpy as np
from retry_requests import retry
import itertools
import matplotlib.pyplot as plt
import time
from datetime import datetime
import asyncio
import aiohttp
import json
from typing import List, Tuple
import math
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import config

from shapely.geometry import Point, Polygon
import numpy as np
import itertools

def generate_coordinates(
    bottom_right=(5.060000, 88.760000),
    top_right=(21.3, 88.76),
    top_left=(21.195000, 68.570000),
    bottom_left=(5.060000, 68.570000),
    step=0.25,
): 
    """
    Generate all coordinates inside a quadrilateral with a given step size.

    Args:
        bottom_right (tuple): Bottom-right corner of the quadrilateral (lat, lon).
        top_right (tuple): Top-right corner of the quadrilateral (lat, lon).
        top_left (tuple): Top-left corner of the quadrilateral (lat, lon).
        bottom_left (tuple): Bottom-left corner of the quadrilateral (lat, lon).
        step (float): Step size for the grid.

    Returns:
        list: List of (latitude, longitude) tuples inside the quadrilateral.
    """
    # Define the quadrilateral polygon
    polygon = Polygon([bottom_left, bottom_right, top_right, top_left])

    # Determine the bounding box of the quadrilateral
    min_lat = min(bottom_left[0], bottom_right[0], top_left[0], top_right[0])
    max_lat = max(bottom_left[0], bottom_right[0], top_left[0], top_right[0])
    min_lon = min(bottom_left[1], bottom_right[1], top_left[1], top_right[1])
    max_lon = max(bottom_left[1], bottom_right[1], top_left[1], top_right[1])

    # Generate the grid of points
    lats = np.arange(min_lat, max_lat + step, step)
    lons = np.arange(min_lon, max_lon + step, step)
    grid_points = itertools.product(lats, lons)

    # Filter points inside the quadrilateral
    coordinates = [
        (lat, lon)
        for lat, lon in grid_points
        if polygon.contains(Point(lat, lon))
    ]

    print(f"Generated {len(coordinates)} coordinate pairs inside the quadrilateral.")
    return coordinates


async def process_batch(
    session: aiohttp.ClientSession,
    batch_coords: List[Tuple],
    batch_number: int,
    total_batches: int,
    log_filename: str,
) -> Tuple[List[pd.DataFrame], List[pd.DataFrame]]:
    """Process a single batch of coordinates asynchronously."""
    batch_lats, batch_lons = zip(*batch_coords)

    log_message = (
        f"\nStarting batch {batch_number} of {total_batches} at {datetime.now()}"
    )
    print(log_message)
    with open(log_filename, "a") as log_file:
        log_file.write(log_message + "\n")

    params = {
        "latitude": list(batch_lats),
        "longitude": list(batch_lons),
        "hourly": "pressure_msl",
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "wind_direction_10m_dominant",
        ],
        "timezone": "Asia/Singapore",
        "past_days": 3,
        "forecast_days": 3,
    }

    url = "https://api.open-meteo.com/v1/forecast"
    max_retries = 5
    retry_count = 0

    while retry_count < max_retries:
        try:
            async with session.get(url, params=params) as response:
                if response.status == 429:  # Too Many Requests
                    retry_count += 1
                    wait_time = min(60 * retry_count, 300)
                    await asyncio.sleep(wait_time)
                    continue

                data = await response.json()

                hourly_data_list = []
                daily_data_list = []

                for item in data:
                    # Process hourly data
                    hourly = pd.DataFrame(
                        {
                            "date": pd.date_range(
                                start=pd.to_datetime(item["hourly"]["time"][0]),
                                periods=len(item["hourly"]["time"]),
                                freq="H",
                            ),
                            "latitude": item["latitude"],
                            "longitude": item["longitude"],
                            "pressure_msl": item["hourly"]["pressure_msl"],
                        }
                    )
                    hourly_data_list.append(hourly)

                    # Process daily data
                    daily = pd.DataFrame(
                        {
                            "date": pd.date_range(
                                start=pd.to_datetime(item["daily"]["time"][0]),
                                periods=len(item["daily"]["time"]),
                                freq="D",
                            ),
                            "latitude": item["latitude"],
                            "longitude": item["longitude"],
                            "temperature_2m_max": item["daily"]["temperature_2m_max"],
                            "temperature_2m_min": item["daily"]["temperature_2m_min"],
                            "precipitation_probability_max": item["daily"][
                                "precipitation_probability_max"
                            ],
                            "wind_direction_10m_dominant": item["daily"][
                                "wind_direction_10m_dominant"
                            ],
                        }
                    )
                    daily_data_list.append(daily)

                log_message = f"Successfully processed batch {batch_number}"
                print(log_message)
                with open(log_filename, "a") as log_file:
                    log_file.write(log_message + "\n")

                return hourly_data_list, daily_data_list

        except Exception as e:
            retry_count += 1
            wait_time = min(60 * retry_count, 300)
            log_message = f"Error in batch {batch_number} (attempt {retry_count}): {str(e)}. Waiting {wait_time} seconds..."
            print(log_message)
            with open(log_filename, "a") as log_file:
                log_file.write(log_message + "\n")

            await asyncio.sleep(wait_time)

    return [], []


def save_to_final_file(data_frames: List[pd.DataFrame], filename: str, mode: str = "w"):
    """Save data frames to a final CSV file with proper handling of headers."""
    if not data_frames:
        return

    combined_df = pd.concat(data_frames, ignore_index=True)

    if mode == "w" or not os.path.exists(filename):
        combined_df.to_csv(filename, index=False)
    else:
        combined_df.to_csv(filename, mode="a", header=False, index=False)


async def process_weather_data_async(
    coordinates: List[Tuple], batch_size: int = 50, concurrent_batches: int = 10
):
    """Process weather data for given coordinates with concurrent batch processing."""
    # Initialize final file names
    final_hourly_file = str(config.PROCESSED_DIR / "weather_hourly_data_final.csv")
    final_daily_file = str(config.PROCESSED_DIR / "weather_daily_data_final.csv")

    # Remove existing final files if they exist
    for file in [final_hourly_file, final_daily_file]:
        if os.path.exists(file):
            os.remove(file)

    # Calculate total number of batches
    total_batches = math.ceil(len(coordinates) / batch_size)

    # Create batches of coordinates
    coordinate_batches = [
        coordinates[i : i + batch_size] for i in range(0, len(coordinates), batch_size)
    ]

    # Create a log file for tracking progress
    log_filename = (
        f'weather_processing_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    )

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(coordinate_batches), concurrent_batches):
            batch_group = coordinate_batches[i : i + concurrent_batches]
            tasks = []

            for j, batch in enumerate(batch_group):
                batch_number = i + j + 1
                task = asyncio.create_task(
                    process_batch(
                        session, batch, batch_number, total_batches, log_filename
                    )
                )
                tasks.append(task)

            # Wait for all tasks in the current group to complete
            results = await asyncio.gather(*tasks)

            # Process and save results
            hourly_to_save = []
            daily_to_save = []

            for hourly_list, daily_list in results:
                if hourly_list:
                    hourly_to_save.extend(hourly_list)
                if daily_list:
                    daily_to_save.extend(daily_list)

            # Save to final files
            if hourly_to_save:
                save_to_final_file(
                    hourly_to_save,
                    final_hourly_file,
                    mode="a" if os.path.exists(final_hourly_file) else "w",
                )
            if daily_to_save:
                save_to_final_file(
                    daily_to_save,
                    final_daily_file,
                    mode="a" if os.path.exists(final_daily_file) else "w",
                )

            # Add a small delay between batch groups to avoid overwhelming the API
            await asyncio.sleep(5)

    # Verify and report final file sizes
    hourly_size = (
        os.path.getsize(final_hourly_file) if os.path.exists(final_hourly_file) else 0
    )
    daily_size = (
        os.path.getsize(final_daily_file) if os.path.exists(final_daily_file) else 0
    )

    print(f"\nFinal file sizes:")
    print(f"Hourly data: {hourly_size/1024/1024:.2f} MB")
    print(f"Daily data: {daily_size/1024/1024:.2f} MB")

    # Return the file paths
    return final_hourly_file, final_daily_file


def fix_hourly_data(input_file, output_file):
    """
    Convert hourly weather data to daily averages while preserving date and coordinate information.
    Args:
    input_file (str): Path to the input CSV file with hourly data
    output_file (str): Path to save the output CSV file with daily averages
    Returns:
    str: Path to the output file
    """
    # Load the CSV file
    data = pd.read_csv(input_file)
    
    # Convert the date column to datetime and extract the date part
    data['date'] = pd.to_datetime(data['date']).dt.date
    
    # Group by date, latitude, and longitude to calculate daily averages
    daily_data = data.groupby(['date', 'latitude', 'longitude']).agg({
        'pressure_msl': 'mean'  # Calculate daily average of pressure
    }).reset_index()
    
    # Save the daily average data to a new CSV
    daily_data.to_csv(output_file, index=False)
    
    print(f"Daily average data saved to {output_file}")
    return output_file

def combine_csv_files(file1_path, file2_path, output_path):
    """
    Combine two CSV files with different columns, avoiding duplicate columns.
    If the number of rows differs, fill the missing rows with column mean values for numeric columns,
    but keep date, longitude, and latitude values from the side with extra rows.

    Args:
    file1_path (str): Path to the first CSV file
    file2_path (str): Path to the second CSV file
    output_path (str): Path to save the combined CSV file
    """
    try:
        # Read the CSV files
        df1 = pd.read_csv(file1_path)
        df2 = pd.read_csv(file2_path)

        # Determine the max number of rows
        max_rows = max(len(df1), len(df2))

        # Separate columns into types
        date_cols = ['date', 'longitude', 'latitude']
        numeric_cols1 = df1.select_dtypes(include="number").columns
        numeric_cols2 = df2.select_dtypes(include="number").columns

        # Extend df1 if it's shorter
        if len(df1) < max_rows:
            # Calculate mean values for numeric columns (except date, longitude, latitude)
            means = {col: df1[col].mean() for col in numeric_cols1 if col not in date_cols}
            missing_rows = pd.DataFrame([means] * (max_rows - len(df1)))

            # Fill date, longitude, latitude columns with values from df2 (if df2 has more rows)
            for col in date_cols:
                if col in df2.columns:
                    missing_rows[col] = df2[col].iloc[:max_rows - len(df1)].values
                else:
                    missing_rows[col] = df1[col].iloc[0]  # or any default value

            df1 = pd.concat([df1, missing_rows], ignore_index=True)

        # Extend df2 if it's shorter (using the same logic)
        if len(df2) < max_rows:
            # Calculate mean values for numeric columns (except date, longitude, latitude)
            means = {col: df2[col].mean() for col in numeric_cols2 if col not in date_cols}
            missing_rows = pd.DataFrame([means] * (max_rows - len(df2)))

            # Fill date, longitude, latitude columns with values from df1 (if df1 has more rows)
            for col in date_cols:
                if col in df1.columns:
                    missing_rows[col] = df1[col].iloc[:max_rows - len(df2)].values
                else:
                    missing_rows[col] = df2[col].iloc[0]  # or any default value

            df2 = pd.concat([df2, missing_rows], ignore_index=True)

        # Identify unique columns from both dataframes
        unique_columns1 = set(df1.columns)
        unique_columns2 = set(df2.columns)

        # Create a new dataframe with combined columns
        combined_df = df1.copy()

        # Add columns from df2 that are not in df1
        for col in unique_columns2 - unique_columns1:
            combined_df[col] = df2[col]

        # Reorder columns to have a clean, organized output
        all_columns = list(unique_columns1.union(unique_columns2))
        combined_df = combined_df[all_columns]

        # Save the combined CSV
        combined_df.to_csv(output_path, index=False)

        print(f"Combined CSV saved to {output_path}")
        print(f"Total rows: {len(combined_df)}")
        print(f"Total columns: {len(all_columns)}")

    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
    except pd.errors.EmptyDataError:
        print("Error: One of the CSV files is empty")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def split_data_evenly(input_file, output_dir):
    """
    Split the combined data file into an equal number of rows across specified splits.
    
    Args:
        input_file (str): Path to the input combined CSV file.
        output_dir (str): Directory to save the split CSV files.
        num_splits (int): Number of splits required.
    
    Returns:
        str: Path to the output directory.
    """
    # Read the data
    data = pd.read_csv(input_file)
    
    unique_dates = data['date'].unique()
    output_dir = 'split_by_date'
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(exist_ok=True)

    for date in unique_dates:
        date_data = data[data['date'] == date].drop(columns=['date'])
        
        output_file = output_dir_path / f"data_{date}.csv"
        date_data.to_csv(output_file, index=False)
    return output_dir

def main():
    print("Starting Comprehensive Weather Data Processing...")

    # Step 1: Generate and fetch weather data
    print("\n--- Step 1: Generating and Fetching Weather Data ---")
    coordinates = generate_coordinates()
    hourly_file, daily_file = asyncio.run(process_weather_data_async(coordinates))

    # Step 2: Fix hourly data
    print("\n--- Step 2: Fixing Hourly Data ---")
    daily_avg_file = str(config.PROCESSED_DIR / "daily_average_weather_data.csv")
    fix_hourly_data(hourly_file, daily_avg_file)
    # daily_file="weather_daily_data_final.csv"

    # # Step 3: Combine data files
    print("\n--- Step 3: Combining Data Files ---")
    combined_file = str(config.PROCESSED_DIR / "final.csv")
    combine_csv_files(daily_avg_file, daily_file, combined_file)

    # Step 4: Split data by date    
    print("\n--- Step 4: Splitting Data by Date ---")
    # NOTE: the data shipped with this repo under data/snapshots/split_by_date/
    # was produced by a run of this step — pointing here so re-runs land in the
    # same place instead of a fresh "split_data_outputs" folder.
    output_dir = str(config.SNAPSHOTS_DIR / "split_by_date")
    split_data_evenly(combined_file, output_dir)

    print("\nWeather Data Processing Complete!")


if __name__ == "__main__":
    main()
