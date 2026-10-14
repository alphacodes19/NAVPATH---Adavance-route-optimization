"""Tests for the grid/geographic coordinate conversion utilities."""

import pytest

from src.engine.coord_convert import (
    grid_to_latitude,
    grid_to_longitude,
    latitude_to_grid,
    longitude_to_grid,
)


@pytest.mark.parametrize(
    "grid_x, grid_y",
    [(16, 9), (20, 20), (50, 50), (70, 75), (100, 100), (121, 135)],
)
def test_grid_to_latlon_and_back_round_trip(grid_x, grid_y):
    latitude = grid_to_latitude(grid_y)
    longitude = grid_to_longitude(grid_x)

    assert latitude_to_grid(latitude) == grid_y
    assert longitude_to_grid(longitude) == grid_x


def test_grid_coordinates_convert_to_finite_geographic_values():
    latitude = grid_to_latitude(75)
    longitude = grid_to_longitude(70)

    assert -90 <= latitude <= 90
    assert -180 <= longitude <= 180
    assert latitude == pytest.approx(22.0)
    assert longitude == pytest.approx(83.125)
