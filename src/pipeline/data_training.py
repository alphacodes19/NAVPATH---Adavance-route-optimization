import pandas as pd
import numpy as np
import os

print("Current working directory:", os.getcwd())
from datetime import datetime, timedelta
import xgboost as xgb
from sklearn.preprocessing import StandardScaler
import matplotlib.pyplot as plt


class WeatherHeuristicTrainer:

    def calculate_wind_direction_deviation(self, current_direction, prev_direction=None):
        """
        Calculate wind direction deviation

        Args:
            current_direction (float or Series): Current day's wind direction in degrees
            prev_direction (float or Series, optional): Previous day's wind direction

        Returns:
            float or Series: Deviation in wind direction
        """
        # First iteration case
        if prev_direction is None:
            return np.zeros_like(current_direction) if hasattr(current_direction, '__len__') else 0.0

        # Calculate circular deviation
        deviation = np.abs(current_direction - prev_direction)

        # Handle wrap-around at 360 degrees
        if hasattr(deviation, '__len__'):
            # For Series/array input
            return np.minimum(deviation, 360 - deviation)
        else:
            # For scalar input
            return min(deviation, 360 - deviation)

    #before changing weight and demonstrating make sure to first delete the existing heuristics_data.pkl before calling the heuristics generator.
    #modify weight->call the generator -> show the difference in the graph and also the retrieved heuristic data using heur_retriever function.
    def __init__(self,prev_heuristics=0.4,TP=0.1,pressure_msl=0.1,temp_variation=0.15,precipitation=0.1,wind=0.1):
        self.feature_weights = {
            "prev_heuristic": prev_heuristics,  # 40% weight for previous heuristic
            "TP": TP, # 10% for peak wave period
            "pressure_msl": pressure_msl,  # 15% for pressure
            "temp_variation": temp_variation,  # 15% for temperature variation
            "precipitation": precipitation,  # 10% for precipitation
            "wind": wind,  # 10% for wind components
        }
        self.scaler = StandardScaler()

    def convert_wind_direction(self, degrees):
        """Convert wind direction from degrees to sine and cosine components"""
        radians = np.deg2rad(degrees)
        return np.sin(radians), np.cos(radians)

    def prepare_features(self, df, prev_heuristics=None, prev_wind_direction=None):
        """Prepare features for model training/prediction"""
        # Ensure all required columns exist
        required_columns = [
            'temperature_2m_max', 'temperature_2m_min',
            'wind_direction_10m_dominant', 'precipitation_probability_max',
            'Latitude', 'Longitude', 'pressure_msl','TP'
        ]
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Calculate wind direction deviation
        wind_dir_deviation = self.calculate_wind_direction_deviation(
            df["wind_direction_10m_dominant"], prev_wind_direction
        )

        # Calculate temperature variation
        temp_variation = df["temperature_2m_max"] - df["temperature_2m_min"]

        # Create feature dictionary
        features = {
            "wind_dir_deviation": wind_dir_deviation,
            "Longitude": df["Longitude"],
            "Latitude": df["Latitude"],
            "pressure_msl": df["pressure_msl"],
            "temp_variation": temp_variation,
            "precipitation_probability_max": df["precipitation_probability_max"],
            "TP":df["TP"]
        }

        # Add previous heuristics if available
        if prev_heuristics is not None and len(prev_heuristics) > 0:
            # Ensure prev_heuristics matches the number of rows
            if len(prev_heuristics) != len(df):
                # If lengths don't match, pad or truncate
                if len(prev_heuristics) > len(df):
                    prev_heuristics = prev_heuristics[:len(df)]
                else:
                    prev_heuristics = np.pad(prev_heuristics,
                                             (0, len(df) - len(prev_heuristics)),
                                             mode='constant',
                                             constant_values=0)
            features["prev_heuristic"] = prev_heuristics

        # Prepare features DataFrame
        X = pd.DataFrame(features)
        
        # Drop latitude and longitude
        X.drop(columns=["Latitude", "Longitude"], inplace=True, errors="ignore")

        # Fill NaN values with mean
        X.fillna(X.mean(), inplace=True)

        return X, df["wind_direction_10m_dominant"]

    def create_model(self):
        """Create and configure XGBoost model"""
        params = {
            "objective": "reg:squarederror",
            "max_depth": 6,
            "learning_rate": 0.1,
            "n_estimators": 100,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
        }
        return xgb.XGBRegressor(**params)

    def calculate_weighted_features(self, X):
        """Calculate weighted contribution of each feature."""
        weighted_sum = np.zeros(len(X))

        # Apply weights to each feature
        if "prev_heuristic" in X.columns:
            weighted_sum += self.feature_weights["prev_heuristic"] * X["prev_heuristic"]

        # Normalize pressure (assuming typical range 950-1050 hPa)
        pressure_contrib = (1000 - X["pressure_msl"]) / 50
        weighted_sum += self.feature_weights["pressure_msl"] * pressure_contrib

        # Temperature variation contribution (normalized)
        temp_contrib = X["temp_variation"] / 30  # Assuming max variation of 30°C
        weighted_sum += self.feature_weights["temp_variation"] * temp_contrib

        # Precipitation contribution (already 0-100)
        precip_contrib = X["precipitation_probability_max"] / 100
        weighted_sum += self.feature_weights["precipitation"] * precip_contrib

        # Wind contribution (using wind direction deviation)
        wind_dev_contrib = (X["wind_dir_deviation"] / 180) ** 2  # Quadratic scaling
        weighted_sum += self.feature_weights["wind"] * wind_dev_contrib

        # Peak Wave Period (TP) contribution
        # Optimal range is 8–12 seconds
        tp_contrib = np.zeros(len(X))
        tp_optimal_min = 8
        tp_optimal_max = 12
        tp_deviation = np.where(
            X["TP"] < tp_optimal_min, tp_optimal_min - X["TP"],  # Below optimal range
            np.where(X["TP"] > tp_optimal_max, X["TP"] - tp_optimal_max, 0)  # Above optimal range
        )
        tp_contrib = (tp_deviation / (tp_optimal_max - tp_optimal_min)) ** 2  # Quadratic scaling
        weighted_sum += self.feature_weights["TP"] * tp_contrib

        return np.clip(weighted_sum, 0, 1)

    def process_single_day(
        self, date_str, prev_heuristics=None, prev_wind_direction=None, base_path="./"
    ):
        """Process data for a single day"""
        print(f"Processing {date_str}")

        # Load data
        filename = f"combined_{date_str}.csv"
        df = pd.read_csv(os.path.join(base_path, filename))

        # Prepare features
        X, current_wind_direction = self.prepare_features(
            df, prev_heuristics, prev_wind_direction
        )

        if prev_heuristics is None or len(prev_heuristics) == 0:
            # First day: initialize all heuristics to 0
            y_pred = np.zeros(len(df))
        else:
            # Scale features
            X_scaled = self.scaler.fit_transform(X)

            # Calculate weighted feature contributions
            weighted_features = self.calculate_weighted_features(X)

            # Create and train model
            model = self.create_model()

            # Train model using weighted features
            model.fit(X_scaled, weighted_features)

            # Generate predictions
            y_pred = model.predict(X_scaled)

            # Plot feature importance
            self.plot_feature_importance(model, X.columns, date_str)

            # Ensure predictions are between 0 and 1
            y_pred = np.clip(y_pred, 0, 1)

        # Save predictions
        output_df = df.copy()
        output_df["heuristic"] = y_pred
        output_filename = f"predictions_{date_str}.csv"
        output_df.to_csv(os.path.join(base_path, output_filename), index=False)

        return y_pred, current_wind_direction

    def plot_feature_importance(self, model, feature_names, date_str):
        """Plot and save feature importance"""
        importance = model.feature_importances_
        plt.figure(figsize=(10, 6))
        plt.bar(range(len(importance)), importance)
        plt.xticks(range(len(importance)), feature_names, rotation=45)
        plt.title(f"Feature Importance for {date_str}")
        plt.tight_layout()
        plt.savefig(f"feature_importance_{date_str}.png")
        plt.close()

    def process_all_days(self, start_date, end_date, base_path="./"):
        """Process all days sequentially and return heuristics and wind deviation dictionaries"""
        current_date = start_date
        prev_heuristics = None
        prev_wind_direction = None

        # Dictionaries to store final results
        heuristics_dict = {}
        wind_deviation_dict = {}

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")

            # Load data for current day
            filename = f"combined_{date_str}.csv"
            df = pd.read_csv(os.path.join(base_path, filename))

            # Process current day
            prev_heuristics, prev_wind_direction = self.process_single_day(
                date_str, prev_heuristics, prev_wind_direction
            )

            # Create dictionaries using longitude and latitude as keys
            for row, heuristic in zip(df.to_dict('records'), prev_heuristics):
                # Add heuristic to dictionary
                heuristics_dict[(row['Longitude'], row['Latitude'])] = heuristic

                # Calculate wind deviation
                wind_deviation = self.calculate_wind_direction_deviation(
                    row['wind_direction_10m_dominant'], prev_wind_direction
                )
                wind_deviation_dict[(row['Longitude'], row['Latitude'])] = wind_deviation

            # Move to next day
            current_date += timedelta(days=1)

        return heuristics_dict, wind_deviation_dict


# Main execution
if __name__ == "__main__":
    trainer = WeatherHeuristicTrainer()

    # Set date range
    start_date = datetime(2024, 12,11 )
    end_date = datetime(2024, 12, 16 )

    # Process all days and get dictionaries
    heuristics_dict, wind_deviation_dict = trainer.process_all_days(start_date, end_date)

    # Optional: Print the dictionaries
    print("Heuristics Dictionary:")
    print(heuristics_dict)
    print("\nWind Deviation Dictionary:")
    # print(wind_deviation_dict)