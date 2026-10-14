"""Regression tests for the shared engine land mask."""

from unittest.mock import patch

from src.engine.land_data import LAND_CELLS
from src.engine.router import RouteParams, get_neighbors


def test_land_mask_contains_known_land_and_open_water_cells():
    # Stable reference cells from the checked-in India map/overlay assets.
    assert (50, 50) in LAND_CELLS
    assert (10, 10) not in LAND_CELLS
    assert all(
        0 <= x < 550 // 4 and 0 <= y < 600 // 4
        for x, y in LAND_CELLS
    )


def test_route_params_default_to_the_canonical_land_mask():
    params = RouteParams(start=(10, 10), end=(13, 13))
    assert params.land_cells is LAND_CELLS


def test_default_routing_blocks_a_canonical_land_cell():
    params = RouteParams(start=(49, 50), end=(49, 51))
    with patch("src.engine.router._wind_alignment", return_value=0.5), patch(
        "src.engine.router._current_alignment", return_value=0.5
    ):
        neighbors = {item[0] for item in get_neighbors((49, 50), params)}

    assert (50, 50) in LAND_CELLS
    assert (50, 50) not in neighbors
