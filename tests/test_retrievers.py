"""Retriever tests use tiny temporary datasets and do not need network access."""

import pickle

import pandas as pd
import pytest

from src.engine.current_retriever import OceanCurrentRetriever
from src.engine.fuel_retriever import FuelEfficiencyRetriever
from src.engine.heuristic_retriever import HeuristicRetriever
from src.engine.wind_retriever import WindDirectionRetriever


def _write_pickle(path, value):
    with open(path, "wb") as handle:
        pickle.dump(value, handle)
    return str(path)


def test_wind_retriever_known_key_and_missing_key(tmp_path):
    data = pd.DataFrame(
        [{"longitude": 70.125, "latitude": 12.25, "wind_direction_10m_dominant": 135.0}]
    )
    retriever = WindDirectionRetriever(_write_pickle(tmp_path / "wind.pkl", data))

    assert retriever.retrieve_wind_direction(70.1251, 12.2501) == pytest.approx(135.0)
    assert retriever.retrieve_wind_direction(80.0, 20.0) == 0


def test_current_retriever_known_key_and_missing_key(tmp_path):
    data = pd.DataFrame([{"Longitude": 70.125, "Latitude": 12.25, "Angle": 220.0}])
    retriever = OceanCurrentRetriever(_write_pickle(tmp_path / "current.pkl", data))

    assert retriever.retrieve_angle(70.125, 12.25) == pytest.approx(220.0)
    assert retriever.retrieve_angle(80.0, 20.0) == 0


def test_fuel_retriever_known_key_and_missing_key(tmp_path):
    data = pd.DataFrame(
        [{"Longitude": 70.125, "Latitude": 12.25, "fuel_efficiency": 0.83}]
    )
    retriever = FuelEfficiencyRetriever(_write_pickle(tmp_path / "fuel.pkl", data))

    assert retriever.retrieve_fuel_efficiency(70.125, 12.25) == pytest.approx(0.83)
    assert retriever.retrieve_fuel_efficiency(80.0, 20.0) == 0


def test_heuristic_retriever_unwraps_saved_heuristics_and_uses_default(tmp_path):
    filename = _write_pickle(
        tmp_path / "heuristics.pkl",
        {"heuristics": {(70.125, 12.25): 0.91}, "wind_deviation": {}},
    )
    retriever = HeuristicRetriever()

    assert retriever.get_heuristic_value(12.25, 70.125, filename) == pytest.approx(0.91)
    assert retriever.get_heuristic_value(99.0, 99.0, filename) == pytest.approx(0.5)


def test_heuristic_retriever_missing_file_returns_default(tmp_path):
    retriever = HeuristicRetriever()
    assert retriever.get_heuristic_value(1.0, 2.0, str(tmp_path / "missing.pkl")) == pytest.approx(0.5)
