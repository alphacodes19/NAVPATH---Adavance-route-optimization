import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import config
from src.pipeline.data_training import WeatherHeuristicTrainer
from datetime import datetime

def save_heuristics(heuristics_dict, wind_deviation_dict, filename=None):
    """Save the heuristics and wind deviation dictionaries to a file using pickle"""
    filename = filename or config.HEURISTICS_PKL
    with open(filename, "wb") as f:
        pickle.dump({"heuristics": heuristics_dict, "wind_deviation": wind_deviation_dict}, f)

def load_heuristics(filename=None):
    filename = filename or config.HEURISTICS_PKL
    """Load the heuristics and wind deviation dictionaries from a pickle file"""
    try:
        with open(filename, "rb") as f:
            data = pickle.load(f)
            return data["heuristics"], data["wind_deviation"]
    except FileNotFoundError:
        print("No saved heuristics data found.")
        return None, None

def main():
    # Check if heuristics are already saved
    heuristics_dict, wind_deviation_dict = load_heuristics()

    if heuristics_dict is None or wind_deviation_dict is None:
        # If no saved data, process and generate heuristics
        # NOTE: process_all_days() reads combined_<date>.csv files from base_path
        # (default "./"). Nothing in this repo currently produces files with that
        # exact name — see docs/architecture.md "Known gaps" before running this.
        trainer = WeatherHeuristicTrainer()
        # Modify the date range if the training files dates are changed
        start_date = datetime(2024, 8, 29)
        end_date = datetime(2024, 9, 3)
        heuristics_dict, wind_deviation_dict = trainer.process_all_days(start_date, end_date)
        
        # Save the new data
        save_heuristics(heuristics_dict, wind_deviation_dict)
        print("New heuristics data processed and saved.")

    # Print the stored heuristics dictionary
    print("Stored Heuristics Dictionary:")
    print(heuristics_dict)
    print("\nStored Wind Deviation Dictionary:")
    print(wind_deviation_dict)

if __name__ == "__main__":
    main()
