# AFTER
import pickle
import logging
from src import config


class FuelEfficiencyRetriever:
    def __init__(self, pkl_file=None):
        pkl_file = pkl_file or config.FUEL_PKL
        with open(pkl_file, 'rb') as f:
            data = pickle.load(f)
        self._index = {
            (round(row['Longitude'], 3), round(row['Latitude'], 3)): row['fuel_efficiency']
            for _, row in data.iterrows()
        }
        logging.info(f"FuelEfficiencyRetriever: indexed {len(self._index)} coordinates")

    def retrieve_fuel_efficiency(self, longitude, latitude):
        key = (round(longitude, 3), round(latitude, 3))
        return self._index.get(key, 0)  # Default value if coordinates are not found

if __name__ == "__main__":
    retriever = FuelEfficiencyRetriever()
    fuel_efficiency_score = retriever.retrieve_fuel_efficiency(68.875, 12.25)  # Example coordinates
    print("Fuel Efficiency Score:", fuel_efficiency_score)
