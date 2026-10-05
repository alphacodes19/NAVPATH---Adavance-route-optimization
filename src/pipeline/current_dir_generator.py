import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np

from src import config

def filter_csv_by_date_with_angle(input_file, output_file, target_date):
    """
    Filter CSV file for a specific date, compute the angle, and save filtered columns to a pickle file.

    Args:
    input_file (str): Path to input CSV file.
    output_file (str): Path to output pickle file.
    target_date (str): Date to filter in the format 'YYYY-MM-DD'.
    """
    # Read the CSV file
    df = pd.read_csv(input_file)

    # Filter rows for the specific date
    df_filtered = df[df['Date'] == target_date]

    # Ensure no division by zero and compute the angle in degrees
    df_filtered['Angle'] = np.degrees(np.arctan2(df_filtered['V_Current'], df_filtered['U_Current']))
    
    # Normalize angle to range [0, 360)
    df_filtered['Angle'] = (df_filtered['Angle'] + 360) % 360

    # Select only relevant columns
    columns_to_save = ['Latitude', 'Longitude', 'Angle', 'U_Current', 'V_Current']
    df_result = df_filtered[columns_to_save]

    # Save filtered data to a pickle file
    df_result.to_pickle(output_file)

    print(f"Filtered data with angles for {target_date} saved to {output_file}")
    print(f"Number of rows saved: {len(df_result)}")

def main():
    input_file = str(config.PROCESSED_DIR / "merged_data_20241211_20241216.csv")
    output_file = config.CURRENT_PKL
    target_date = '2024-12-11'

    filter_csv_by_date_with_angle(input_file, output_file, target_date)

if __name__ == '__main__':
    main()
