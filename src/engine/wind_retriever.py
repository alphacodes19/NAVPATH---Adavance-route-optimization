import pickle
import pandas as pd

from src import config


class WindDirectionRetriever:
    def __init__(self, pkl_file=None):
        pkl_file = pkl_file or config.WIND_PKL
        # Load the data once during initialization
        with open(pkl_file, 'rb') as f:
            self.data = pickle.load(f)

    def retrieve_wind_direction(self, longitude, latitude):
        # Filter the data based on the provided longitude and latitude
        result = self.data[(self.data['longitude'] == longitude) & (self.data['latitude'] == latitude)]

        # Return the wind direction or the default value of 0
        if not result.empty:
            return result['wind_direction_10m_dominant'].values[0]
        else:
            return 0  # Default value

if __name__ == "__main__":
    retriever = WindDirectionRetriever()
    print(retriever.retrieve_wind_direction(68.875, 12.25))
