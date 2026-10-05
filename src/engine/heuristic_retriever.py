import pickle

class HeuristicRetriever:
    def __init__(self):
        # Store references to loaded files
        self.loaded_files = {}

    def load_file(self, filename):
        """
        Load the data from a specific pickle file.

        Args:
            filename (str): The name of the pickle file to load.

        Returns:
            dict: The loaded data from the pickle file.
        """
        if filename not in self.loaded_files:
            try:
                with open(filename, "rb") as f:
                    self.loaded_files[filename] = pickle.load(f)
            except FileNotFoundError:
                print(f"No saved data found at {filename}. Please ensure the file exists.")
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
            print(f"No heuristic value found for ({latitude}, {longitude}). Returning default value.")
            return 0.5  # Default value if the coordinate is not found
