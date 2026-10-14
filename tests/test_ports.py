"""Tests for nearest-port ranking in the routing engine."""

import pytest

from src.data.ports import PORTS
from src.engine.router import _haversine_nm, find_nearest_ports


def test_find_nearest_ports_returns_sorted_distances():
    reference = PORTS[0]

    results = find_nearest_ports(reference["lat"], reference["lon"], n=5)

    assert len(results) == 5
    distances = [distance for _, distance in results]
    assert distances == sorted(distances)
    assert results[0][0]["name"] == reference["name"]
    assert results[0][1] == pytest.approx(0.0)
    for port, distance in results:
        assert distance == pytest.approx(
            _haversine_nm(reference["lat"], reference["lon"], port["lat"], port["lon"])
        )


def test_find_nearest_ports_respects_requested_count():
    assert len(find_nearest_ports(18.93, 72.84, n=3)) == 3
