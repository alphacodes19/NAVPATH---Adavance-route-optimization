import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import pickle

from src import config

if __name__ == "__main__":
    # Load the CSV file into a DataFrame
    df = pd.read_csv(config.PROCESSED_DIR / "final2_with_fuel_efficiency.csv")

    # Extract the required columns (Latitude, Longitude, and Fuel Efficiency Score)
    data_to_save = df[["Latitude", "Longitude", "fuel_efficiency"]]

    # Save the extracted columns to a .pkl file
    with open(config.FUEL_PKL, "wb") as f:
        pickle.dump(data_to_save, f)

    print(f"Data has been saved to {config.FUEL_PKL}")
