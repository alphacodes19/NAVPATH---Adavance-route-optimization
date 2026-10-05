"""
Central location for every path the project uses.

Every module should import from here instead of hardcoding a filename like
"heuristics_data.pkl" — that only worked before because every script assumed
it was being run from the project root with all files dumped next to it.
Now that files live in data/, assets/, etc., this is the single source of
truth for where things actually are.
"""

from pathlib import Path

# NAVPATH/src/config.py -> parents[1] is the project root (NAVPATH/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- data ---
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = DATA_DIR / "models"          # .pkl files the running app reads
RAW_DIR = DATA_DIR / "raw"                # source datasets (e.g. GEBCO .nc)
PROCESSED_DIR = DATA_DIR / "processed"    # intermediate CSVs from the pipeline
SNAPSHOTS_DIR = DATA_DIR / "snapshots"    # historical run artifacts (not read by the app)

# --- assets ---
ASSETS_DIR = PROJECT_ROOT / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
VIDEO_DIR = ASSETS_DIR / "video"

# --- frequently used files (as strings, since pygame/pandas/pickle want str/Path either way) ---
HEURISTICS_PKL = str(MODELS_DIR / "heuristics_data.pkl")
CARGO_PKL = str(MODELS_DIR / "Cargo.pkl")
PASSENGER_PKL = str(MODELS_DIR / "passenger.pkl")
WIND_PKL = str(MODELS_DIR / "longitude_latitude_wind_direction.pkl")
CURRENT_PKL = str(MODELS_DIR / "filtered_data_with_angle.pkl")
FUEL_PKL = str(MODELS_DIR / "latitude_longitude_fuel_efficiency.pkl")

INDIA_MAP_IMG = str(IMAGES_DIR / "India.jpeg")
INDIA_FOREGROUND_IMG = str(IMAGES_DIR / "IndiaFore3.png")
BACKGROUND_IMG = str(IMAGES_DIR / "background.jpg")
INTRO_VIDEO = str(VIDEO_DIR / "Countdown1.mp4")
