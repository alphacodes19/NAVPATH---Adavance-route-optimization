"""Engine-level regression tests for routing behavior (no pygame dependency)."""

from unittest.mock import patch

import pytest

from src.engine import router


def test_astar_finds_path_between_known_open_water_points():
    start, end = (10, 10), (13, 13)
    params = router.RouteParams(start=start, end=end, mode="speed")

    path, explored = router.run_astar(params)

    assert path is not None
    assert path  # current run_astar contract excludes the start from path
    assert path[-1] == end
    assert start not in path
    assert isinstance(explored, list)


def test_astar_cannot_enter_a_land_target():
    start, end = (50, 50), (51, 50)
    params = router.RouteParams(start=start, end=end, land_cells={end})

    with patch.object(router, "_wind_alignment", return_value=0.5), patch.object(
        router, "_current_alignment", return_value=0.5
    ):
        candidates = {item[0] for item in router.get_neighbors(start, params)}

    assert end not in candidates

    # Keep this unreachable-target test local and deterministic: A* must not
    # receive a graph edge into the land target.
    with patch.object(router, "get_neighbors", return_value=[]):
        path, _ = router.run_astar(params)
    assert path is None


def test_calculate_fscore_prefers_tailwind_to_headwind():
    args = dict(
        g=1.0,
        neighbor=(1, 0),
        end=(2, 0),
        mode="speed",
        current_align=0.5,
        fuel_score=0.0,
        depth_pen=0.0,
        ship_factor=1.0,
    )
    with patch.object(router, "_heuristic_value", return_value=0.0):
        tailwind = router.calculate_fscore(**args, wind_align=1.0)
        headwind = router.calculate_fscore(**args, wind_align=0.0)
    assert tailwind < headwind


def test_calculate_fscore_environment_scales_are_respected():
    args = dict(
        g=1.0,
        neighbor=(1, 0),
        end=(2, 0),
        mode="speed",
        wind_align=1.0,
        current_align=0.5,
        fuel_score=0.0,
        depth_pen=0.0,
        ship_factor=1.0,
    )
    with patch.object(router, "_heuristic_value", return_value=0.0):
        baseline = router.calculate_fscore(**args)
        no_wind = router.calculate_fscore(**args, wind_scale=0.0)
        doubled_wind = router.calculate_fscore(**args, wind_scale=2.0)
    assert baseline == pytest.approx(0.85)
    assert no_wind == pytest.approx(1.0)
    assert doubled_wind == pytest.approx(0.70)


def test_run_multi_route_returns_speed_fuel_and_safe_results():
    base = router.RouteParams(start=(10, 10), end=(11, 10), mode="speed")
    seen_modes = []

    def fake_astar(params, progress_callback=None):
        seen_modes.append(params.mode)
        return ([(11, 10)], [])

    with patch.object(router, "run_astar", side_effect=fake_astar), patch.object(
        router, "compute_route_stats", return_value={"distance_nm": 15.0}
    ):
        result = router.run_multi_route(base)

    assert set(result) == {"speed", "fuel", "safe"}
    assert seen_modes == ["speed", "fuel", "comfort"]
    assert all(result[key]["path"] == [(11, 10)] for key in result)
    assert all(result[key]["stats"]["distance_nm"] == 15.0 for key in result)
    assert base.mode == "speed"  # comparison should not mutate caller params


def test_run_astar_whatif_does_not_mutate_base_params():
    base = router.RouteParams(
        start=(1, 1), end=(2, 2), wind_scale=1.0, current_scale=1.0
    )
    with patch.object(router, "run_astar", return_value=([(2, 2)], [])) as mocked:
        result = router.run_astar_whatif(base, wind_mult=0.0, current_mult=2.0)

    assert result == ([(2, 2)], [])
    assert base.wind_scale == 1.0
    assert base.current_scale == 1.0
    passed_params = mocked.call_args.args[0]
    assert passed_params is not base
    assert passed_params.wind_scale == 0.0
    assert passed_params.current_scale == 2.0


def test_route_params_clamps_environment_scales():
    params = router.RouteParams(
        start=(1, 1), end=(2, 2), wind_scale=5, current_scale=-1
    )
    assert params.wind_scale == 2.0
    assert params.current_scale == 0.0


def test_get_neighbors_excludes_no_go_land_and_shallow_cells():
    start = (50, 50)
    params = router.RouteParams(
        start=start,
        end=(55, 55),
        land_cells={(50, 51)},
        nogo_cells={(51, 50)},
        depth_grid={(49, 50): -3.0},
        draft=5.0,
    )
    with patch.object(router, "_wind_alignment", return_value=0.5), patch.object(
        router, "_current_alignment", return_value=0.5
    ):
        neighbors = router.get_neighbors(start, params)

    cells = {entry[0] for entry in neighbors}
    assert (51, 50) not in cells
    assert (50, 51) not in cells
    assert (49, 50) not in cells
    assert (50, 49) in cells


def test_voyage_timeline_is_monotonic_and_has_expected_distance():
    path = [(0, 0), (1, 0), (2, 1), (2, 2)]
    timeline = router.build_voyage_timeline(path, {"speed_kn": 14}, 14)

    assert timeline[0]["nm_covered"] == 0
    distances = [entry["nm_covered"] for entry in timeline]
    assert distances == sorted(distances)
    assert distances[-1] == pytest.approx(2 * 15.0 + 15.0 * (2 ** 0.5))


def test_voyage_timeline_handles_empty_path_and_zero_speed():
    assert router.build_voyage_timeline([], {}, 12) == []
    timeline = router.build_voyage_timeline([(1, 1), (2, 1)], {}, 0)
    assert timeline[-1]["nm_covered"] == pytest.approx(15.0)
    assert timeline[-1]["hours_elapsed"] == 0.0


def test_estimate_fuel_cost_uses_calibration_factor():
    assert router.estimate_fuel_cost({"fuel_index": 2.0}, 100) == pytest.approx(500.0)
    assert router.estimate_fuel_cost({}, 100) == pytest.approx(0.0)


def test_estimate_fuel_cost_rejects_negative_inputs():
    with pytest.raises(ValueError):
        router.estimate_fuel_cost({"fuel_index": 1.0}, -1)
    with pytest.raises(ValueError):
        router.estimate_fuel_cost({"fuel_index": 1.0}, 100, -2)
