"""Regression tests for the standardized historical snapshot filenames."""

import pandas as pd
import pytest

from src.engine import snapshot_heuristics


def test_list_available_dates_only_returns_standardized_snapshot_names(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_heuristics, "_SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(snapshot_heuristics, "_dates_cache", None)

    (tmp_path / "voyage_snapshot_2024-11-27.csv").write_text("longitude,latitude\n70.125,12.25\n")
    (tmp_path / "voyage_snapshot_2024-11-26.csv").write_text("longitude,latitude\n70.125,12.25\n")
    (tmp_path / "data_2024-11-25.csv").write_text("longitude,latitude\n70.125,12.25\n")
    (tmp_path / "predictions_2024-11-24.csv").write_text("longitude,latitude\n70.125,12.25\n")
    (tmp_path / "voyage_snapshot_not-a-date.csv").write_text("longitude,latitude\n70.125,12.25\n")

    assert snapshot_heuristics.list_available_dates() == ["2024-11-26", "2024-11-27"]


def test_load_snapshot_heuristic_uses_standardized_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_heuristics, "_SNAPSHOT_DIR", tmp_path)
    snapshot_heuristics._heuristic_cache.clear()
    pd.DataFrame(
        [{
            "longitude": 70.125,
            "latitude": 12.25,
            "pressure_msl": 1000.0,
            "temperature_2m_max": 30.0,
            "temperature_2m_min": 20.0,
            "precipitation_probability_max": 50.0,
            "TP": 10.0,
        }]
    ).to_csv(tmp_path / "voyage_snapshot_2024-11-26.csv", index=False)

    result = snapshot_heuristics.load_snapshot_heuristic("2024-11-26")

    assert (70.125, 12.25) in result
    assert result[(70.125, 12.25)] == pytest.approx(0.2)
