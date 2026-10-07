# AFTER
import pickle
import logging
from src import config


class OceanCurrentRetriever:
    def __init__(self, pkl_file=None):
        pkl_file = pkl_file or config.CURRENT_PKL
        with open(pkl_file, 'rb') as f:
            data = pickle.load(f)
        self._index = {
            (round(row['Longitude'], 3), round(row['Latitude'], 3)): row['Angle']
            for _, row in data.iterrows()
        }
        logging.info(f"OceanCurrentRetriever: indexed {len(self._index)} coordinates")

    def retrieve_angle(self, longitude, latitude):
        key = (round(longitude, 3), round(latitude, 3))
        return self._index.get(key, 0) # Default value

if __name__ == "__main__":
    ocean_retriever = OceanCurrentRetriever()
    longitude = 68.5
    latitude = 5.0
    angle = ocean_retriever.retrieve_angle(longitude, latitude)
    print(f"Angle for Longitude: {longitude}, Latitude: {latitude}: {angle}°")
