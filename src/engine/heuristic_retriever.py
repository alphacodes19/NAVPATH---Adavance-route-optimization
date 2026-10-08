import pickle
import logging


class HeuristicRetriever:
    def __init__(self):
        # Store references to loaded files
        self.loaded_files = {}

    def load_file(self, filename):
        if filename not in self.loaded_files:
            try:
                with open(filename, "rb") as f:
                    raw = pickle.load(f)
                # The PKL is saved as {'heuristics': {(lon,lat): float}, 'wind_deviation': {...}}
                # We only need the inner heuristics dict. Without this unwrap, every lookup
                # searched the outer wrapper and always returned the default 0.5 — silencing
                # the XGBoost model entirely.
                if isinstance(raw, dict) and "heuristics" in raw:
                    self.loaded_files[filename] = raw["heuristics"]
                else:
                    self.loaded_files[filename] = raw
            except FileNotFoundError:
                logging.warning(f"No saved data found at {filename}. Please ensure the file exists.")
                self.loaded_files[filename] = {}
        return self.loaded_files[filename]

    def get_heuristic_value(self, latitude, longitude, filename):
        """
        Retrieve the heuristic value for a given latitude and longitude.

        Args:
            latitude (float): Latitude of the coordinate.
            longitude (float): Longitude of the coordinate.
            filename (str): The name of the file to load the heuristic data from.

        Returns:
            float: Heuristic value or a default value of 0.5 if not found.
        """
        data = self.load_file(filename)

        # Directly search for the coordinate
        coordinate = (longitude, latitude)
        if coordinate in data:
            return data[coordinate]
        else:
            logging.debug(f"No heuristic value found for ({latitude}, {longitude}). Returning default value.")
            return 0.5  # Default value if the coordinate is not found
