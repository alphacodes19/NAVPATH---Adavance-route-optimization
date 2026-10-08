"""
Historical voyage simulation (Phase 2C) — build a temporary heuristic
override from one of the dated weather snapshots under
data/snapshots/split_by_date/ (data_<date>.csv, one row per grid cell),
instead of using the trained heuristics_data.pkl.

No pygame dependency — this is engine-layer, same as the rest of
src/engine/.

NOTE on accuracy: the real heuristic PKL comes from sequential XGBoost
training across several days (see src/pipeline/data_training.py,
WeatherHeuristicTrainer.process_all_days()) — each day's prediction
depends on the previous day's heuristic and wind-direction deviation.
A single snapshot, viewed in isolation, has neither of those. This
module computes a lightweight stand-in: the same weighted-feature shape
as calculate_weighted_features() in data_training.py, using only the
terms a lone snapshot actually has (pressure, temperature variation,
precipitation, wave period), with weights renormalised across whichever
of those columns are present. Good enough to show "this date's weather
pushed the route one way or the other" — not a substitute for retraining
the model on that date if exact parity with the PKL numbers is needed.
"""

import logging
import re

import pandas as pd

from src import config
from src.engine.coord_convert import round_latitude, round_longitude

_SNAPSHOT_DIR = config.SNAPSHOTS_DIR / "split_by_date"
_FILENAME_RE = re.compile(r"^data_(.+)\.csv$")

_heuristic_cache = {}   # date_str -> {(lon, lat): float}
_dates_cache = None     # sorted list of date_str, cached after first directory scan


def list_available_dates() -> list:
    """Scan data/snapshots/split_by_date/ for data_<date>.csv files, sorted."""
    global _dates_cache
    if _dates_cache is not None:
        return _dates_cache

    dates = []
    if _SNAPSHOT_DIR.is_dir():
        for path in _SNAPSHOT_DIR.glob("data_*.csv"):
            m = _FILENAME_RE.match(path.name)
            if m:
                dates.append(m.group(1))
    dates.sort()
    _dates_cache = dates
    return dates


def _weighted_score(row) -> float:
    """
    [0, 1] weather-severity score for one snapshot row — higher means a
    costlier cell, matching the convention of the trained heuristic
    (0.5 = neutral default, same as HeuristicRetriever's fallback).
    """
    terms = []  # list of (weight, contribution in [0, 1])

    if "pressure_msl" in row and pd.notna(row["pressure_msl"]):
        terms.append((0.3, max(0.0, min(1.0, (1000 - row["pressure_msl"]) / 50))))

    if "temperature_2m_max" in row and "temperature_2m_min" in row:
        tmax, tmin = row["temperature_2m_max"], row["temperature_2m_min"]
        if pd.notna(tmax) and pd.notna(tmin):
            terms.append((0.3, max(0.0, min(1.0, (tmax - tmin) / 30))))

    if "precipitation_probability_max" in row and pd.notna(row["precipitation_probability_max"]):
        terms.append((0.2, max(0.0, min(1.0, row["precipitation_probability_max"] / 100))))

    if "TP" in row and pd.notna(row["TP"]):
        tp = row["TP"]
        tp_deviation = max(8 - tp, tp - 12, 0)  # optimal wave period: 8-12s
        terms.append((0.2, max(0.0, min(1.0, (tp_deviation / 4) ** 2))))

    if not terms:
        return 0.5  # no usable columns — neutral, matches the PKL retriever's own fallback

    weight_sum = sum(w for w, _ in terms)
    return sum(w * v for w, v in terms) / weight_sum


def _build_heuristic_dict(df: "pd.DataFrame") -> dict:
    lon_col = "longitude" if "longitude" in df.columns else "Longitude"
    lat_col = "latitude" if "latitude" in df.columns else "Latitude"
    if lon_col not in df.columns or lat_col not in df.columns:
        logging.warning("Snapshot CSV has no longitude/latitude columns — override unavailable")
        return {}

    out = {}
    for _, row in df.iterrows():
        try:
            lon = round_longitude(float(row[lon_col]))
            lat = round_latitude(float(row[lat_col]))
        except (TypeError, ValueError):
            continue
        out[(lon, lat)] = _weighted_score(row)
    return out


def load_snapshot_heuristic(date_str: str) -> dict:
    """
    Return {(lon, lat): float} for the given snapshot date, cached after
    the first load. Empty dict (→ every A* lookup falls back to the
    default 0.5, i.e. behaves like a flat/neutral day) if the date isn't
    found or the file can't be parsed.
    """
    if date_str in _heuristic_cache:
        return _heuristic_cache[date_str]

    path = _SNAPSHOT_DIR / f"data_{date_str}.csv"
    try:
        df = pd.read_csv(path)
        heuristic = _build_heuristic_dict(df)
    except (FileNotFoundError, pd.errors.EmptyDataError, OSError) as e:
        logging.warning(f"Could not load snapshot '{date_str}': {e}")
        heuristic = {}

    _heuristic_cache[date_str] = heuristic
    return heuristic