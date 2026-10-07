# AFTER
import pickle
import logging
from src import config


class WindDirectionRetriever:
    def __init__(self, pkl_file=None):
        pkl_file = pkl_file or config.WIND_PKL
        with open(pkl_file, 'rb') as f:
            data = pickle.load(f)
        # Build O(1) lookup dict at load time. The DataFrame has 6-12 rows per
        # coordinate (multiple date snapshots) — we take the first value per
        # coordinate, which is what the original code did via .values[0].
        # A future improvement would store keyed by (date, lon, lat) instead.
        self._index = {}
        for _, row in data.iterrows():
            key = (round(row['longitude'], 3), round(row['latitude'], 3))
            if key not in self._index:  # keep first occurrence, consistent with old behaviour
                self._index[key] = row['wind_direction_10m_dominant']
        logging.info(f"WindDirectionRetriever: indexed {len(self._index)} coordinates")

    def retrieve_wind_direction(self, longitude, latitude):
        key = (round(longitude, 3), round(latitude, 3))
        return self._index.get(key, 0)

if __name__ == "__main__":
    retriever = WindDirectionRetriever()
    print(retriever.retrieve_wind_direction(68.875, 12.25))
