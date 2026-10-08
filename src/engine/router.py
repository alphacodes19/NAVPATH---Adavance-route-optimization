"""
Core A* routing engine — no pygame dependency.

All pathfinding logic lives here. The UI (src/app/main.py) calls
run_astar() and receives results via a progress_callback, so it can
update the screen without this module ever importing pygame.
"""

import math
import logging
import copy
from queue import PriorityQueue
from typing import Callable, Optional

from src.engine.coord_convert import (
    grid_to_latitude, grid_to_longitude,
    round_latitude, round_longitude,
)
from src.engine.heuristic_retriever import HeuristicRetriever
from src.engine import wind_retriever as wind_retriever_module
from src.engine import current_retriever as current_retriever_module
from src.engine import fuel_retriever as fuel_retriever_module
from src.engine import storage
from src.engine import snapshot_heuristics
from src import config

# ---------------------------------------------------------------------------
# Module-level retrievers — loaded once, shared across all route calculations
# ---------------------------------------------------------------------------
_heuristic_retriever = HeuristicRetriever()
_wind_retriever = wind_retriever_module.WindDirectionRetriever()
_current_retriever = current_retriever_module.OceanCurrentRetriever()
_fuel_retriever = fuel_retriever_module.FuelEfficiencyRetriever()


# ---------------------------------------------------------------------------
# Grid constants
# ---------------------------------------------------------------------------
GRID_SIZE = 4       # pixels per cell
GRID_W = 550        # total pixel width of map
GRID_H = 600        # total pixel height of map
GRID_COLS = GRID_W // GRID_SIZE   # 137 columns
GRID_ROWS = GRID_H // GRID_SIZE   # 150 rows

_DIRECTIONS = [(0, 1), (1, 0), (0, -1), (-1, 0),
               (1, 1), (-1, -1), (1, -1), (-1, 1)]


# ---------------------------------------------------------------------------
# Routing parameters dataclass
# ---------------------------------------------------------------------------
class RouteParams:
    """
    All the inputs that define one route calculation.
    Pass this to run_astar() instead of a long argument list.
    """
    def __init__(
        self,
        start: tuple,
        end: tuple,
        mode: str = "speed",          # "cargo" | "passenger" | "fuel" | "speed" | "comfort"
        land_cells: set = None,
        depth_grid: dict = None,
        ship_size_factor: float = 1.0,
        min_depth: float = -10.0,
        heuristic_override: dict = None,
    ):
        self.start = start
        self.end = end
        self.mode = mode
        self.land_cells = land_cells or set()
        self.depth_grid = depth_grid or {}
        self.ship_size_factor = ship_size_factor
        self.min_depth = min_depth
        # Phase 2C: when set, A* reads heuristic values from this
        # {(lon, lat): float} dict (one day's weather snapshot) instead
        # of the trained heuristics_data.pkl — see snapshot_heuristics.py.
        self.heuristic_override = heuristic_override


# ---------------------------------------------------------------------------
# Alignment scoring (continuous cosine-based)
# ---------------------------------------------------------------------------
def _wind_alignment(long: float, lat: float, dx: int, dy: int) -> float:
    """Returns [0, 1]: 1.0 = tailwind, 0.5 = cross, 0.0 = headwind."""
    geo_lat = round_latitude(grid_to_latitude(lat))
    geo_lon = round_longitude(grid_to_longitude(long))
    wind_dir = _wind_retriever.retrieve_wind_direction(geo_lon, geo_lat)
    move_angle = math.degrees(math.atan2(dy, dx)) % 360
    diff = math.radians((move_angle - wind_dir + 180) % 360 - 180)
    return (1 + math.cos(diff)) / 2


def _current_alignment(long: float, lat: float, dx: int, dy: int) -> float:
    """Returns [0, 1]: 1.0 = with current, 0.5 = cross, 0.0 = against."""
    geo_lat = round_latitude(grid_to_latitude(lat))
    geo_lon = round_longitude(grid_to_longitude(long))
    current_dir = _current_retriever.retrieve_angle(geo_lon, geo_lat)
    move_angle = math.degrees(math.atan2(dy, dx)) % 360
    diff = math.radians((move_angle - current_dir + 180) % 360 - 180)
    return (1 + math.cos(diff)) / 2


# ---------------------------------------------------------------------------
# F-score calculation
# ---------------------------------------------------------------------------
def _euclidean(a: tuple, b: tuple) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _depth_penalty(cell: tuple, depth_grid: dict, min_depth: float) -> float:
    depth = depth_grid.get(cell)
    if depth is None:
        return 0.0
    if depth > -5:
        return 5.0   # very shallow — strong avoidance
    if depth > min_depth:
        return 2.0   # shallower than vessel draft — moderate penalty
    return 0.0


def _heuristic_value(cell: tuple, pkl_path: str, heuristic_override: dict = None) -> float:
    gx, gy = cell
    lat = round_latitude(grid_to_latitude(gy))
    lon = round_longitude(grid_to_longitude(gx))
    if heuristic_override:
        # Phase 2C: a snapshot override replaces the PKL entirely for this
        # lookup — same (lon, lat) key convention as HeuristicRetriever,
        # same 0.5 neutral fallback when the cell isn't in the snapshot.
        return heuristic_override.get((lon, lat), 0.5)
    return _heuristic_retriever.get_heuristic_value(lat, lon, pkl_path)


def calculate_fscore(
    g: float,
    neighbor: tuple,
    end: tuple,
    mode: str,
    wind_align: float,
    current_align: float,
    fuel_score: float,
    depth_pen: float,
    ship_factor: float,
    heuristic_override: dict = None,
) -> float:
    """
    Compute the A* f-score for a neighbor cell.

    All environmental factors (wind, current, depth, fuel) are included.
    The mode selects which weight combination to use. heuristic_override,
    when given, redirects every _heuristic_value() lookup below to a
    snapshot-day dict instead of the trained PKL (Phase 2C).
    """
    euclid = _euclidean(neighbor, end)

    if mode == "cargo":
        f = 0.3 * g + 0.7 * euclid + 0.1 * _heuristic_value(neighbor, config.CARGO_PKL, heuristic_override)
    elif mode == "passenger":
        f = 0.3 * g + 0.2 * euclid + 1.0 * _heuristic_value(neighbor, config.PASSENGER_PKL, heuristic_override)
    elif mode == "fuel":
        f = 0.4 * g + 0.2 * euclid + 0.1 * _heuristic_value(neighbor, config.HEURISTICS_PKL, heuristic_override)
        f *= (1 - 0.1 * fuel_score)
    elif mode == "speed":
        f = 0.3 * g + 0.7 * euclid + 0.1 * _heuristic_value(neighbor, config.HEURISTICS_PKL, heuristic_override)
    elif mode == "comfort":
        f = 0.3 * g + 0.2 * euclid + 1.0 * _heuristic_value(neighbor, config.HEURISTICS_PKL, heuristic_override)
    else:
        # Default: speed-like balanced formula
        f = 0.3 * g + 0.7 * euclid + 0.1 * _heuristic_value(neighbor, config.HEURISTICS_PKL, heuristic_override)

    # Depth penalty (additive — makes shallow cells more expensive)
    f += depth_pen

    # Ship size factor (bigger/less efficient ships pay more per cell)
    f *= ship_factor

    # Wind and current: continuous discount/penalty
    # factor = 1.15 - 0.30 * alignment
    #   alignment=1.0 (tailwind)  → factor=0.85 (15% cheaper)
    #   alignment=0.5 (cross)     → factor=1.00 (neutral)
    #   alignment=0.0 (headwind)  → factor=1.15 (15% more expensive)
    f *= (1.15 - 0.30 * wind_align)
    f *= (1.15 - 0.30 * current_align)

    return f


# ---------------------------------------------------------------------------
# Neighbour generation
# ---------------------------------------------------------------------------
def get_neighbors(pos: tuple, params: RouteParams):
    """
    Returns list of (neighbor_cell, wind_align, current_align) for all
    valid 8-directional moves from pos.
    """
    results = []
    px, py = pos
    for dx, dy in _DIRECTIONS:
        nx, ny = px + dx, py + dy
        if not (0 <= nx < GRID_COLS and 0 <= ny < GRID_ROWS):
            continue
        if (nx, ny) in params.land_cells:
            continue
        if (nx, ny) in storage.Backup_black_cells:
            continue
        wa = _wind_alignment(nx, ny, dx, dy)
        ca = _current_alignment(nx, ny, dx, dy)
        results.append(((nx, ny), wa, ca))
    return results


# ---------------------------------------------------------------------------
# A* search
# ---------------------------------------------------------------------------
def run_astar(
    params: RouteParams,
    progress_callback: Optional[Callable] = None,
) -> tuple:
    """
    Run A* from params.start to params.end.

    Args:
        params:            RouteParams describing the search.
        progress_callback: Optional function called with each explored cell
                           so the UI can visualise progress without this
                           module touching pygame directly.
                           Signature: callback(cell: tuple) → None

    Returns:
        (path, explored_nodes) where path is a list of (x, y) grid cells
        from start to end (exclusive of start), or None if no path found.
    """
    start, end = params.start, params.end
    open_set = PriorityQueue()
    open_set.put((0, start))
    came_from = {}
    g_score = {start: 0.0}
    f_score = {start: 0.0}
    explored = []

    while not open_set.empty():
        _, current = open_set.get()

        if current != start and current != end:
            explored.append(current)
            if progress_callback:
                progress_callback(current)

        if current == end:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            logging.info(f"A* found path: {len(path)} cells, {len(explored)} explored")
            return path, explored

        for neighbor, wind_align, current_align in get_neighbors(current, params):
            fuel_score = _fuel_retriever.retrieve_fuel_efficiency(
                neighbor[0], neighbor[1]
            )
            depth_pen = _depth_penalty(
                neighbor, params.depth_grid, params.min_depth
            )
            tentative_g = g_score[current] + _euclidean(current, neighbor)
            tentative_f = calculate_fscore(
                tentative_g, neighbor, end,
                params.mode, wind_align, current_align,
                fuel_score, depth_pen, params.ship_size_factor,
                heuristic_override=params.heuristic_override,
            )

            if neighbor not in g_score or tentative_g < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f_score[neighbor] = tentative_f
                open_set.put((tentative_f, neighbor))

    logging.warning(f"A* found no path from {start} to {end}")
    return None, explored


# ---------------------------------------------------------------------------
# Multi-route comparison (Phase 2A)
# ---------------------------------------------------------------------------
def run_multi_route(params_base: RouteParams, progress_callback: Optional[Callable] = None) -> dict:
    """
    Run A* three times from the same start/end — speed, fuel, and safe
    modes — and return all three results for side-by-side comparison.

    NOTE: there's no dedicated 'safe' entry in calculate_fscore() yet.
    'safe' is mapped to the existing 'comfort' formula (heaviest
    heuristic weight, lightest euclidean pull) as the closest stand-in
    for a risk-averse route. Swap the mode_for_key mapping below if you'd
    rather define a true 'safe' weighting (e.g. heavier depth_pen weighting)
    instead of reusing comfort.

    Returns:
        {
          'speed': {'path': [...] or None, 'stats': {...}},
          'fuel':  {'path': [...] or None, 'stats': {...}},
          'safe':  {'path': [...] or None, 'stats': {...}},
        }
    """
    mode_for_key = {
        "speed": "speed",
        "fuel": "fuel",
        "safe": "comfort",
    }

    results = {}
    for key, mode in mode_for_key.items():
        params = copy.copy(params_base)
        params.mode = mode

        path, explored = run_astar(params, progress_callback=progress_callback)

        if path:
            stats = compute_route_stats(path, params.depth_grid, _fuel_retriever._index)
        else:
            stats = {}
            logging.warning(f"run_multi_route: no path found for mode '{mode}' (key '{key}')")

        results[key] = {"path": path, "stats": stats}

    return results


# ---------------------------------------------------------------------------
# Historical voyage simulation — two-date overlay (Phase 2C-3)
# ---------------------------------------------------------------------------
def run_date_comparison(
    params_base: RouteParams,
    date_a: str,
    date_b: str,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Run the same start/end/mode route twice, once under each snapshot
    date's weather conditions (see src/engine/snapshot_heuristics.py),
    so the two can be drawn as an overlay with a stat-diff panel.

    params_base.heuristic_override is ignored here — each run gets its
    own override built from date_a / date_b respectively.

    Returns:
        {
          'a': {'date': date_a, 'path': [...] or None, 'stats': {...}},
          'b': {'date': date_b, 'path': [...] or None, 'stats': {...}},
        }
    """
    results = {}
    for key, date_str in (("a", date_a), ("b", date_b)):
        params = copy.copy(params_base)
        params.heuristic_override = snapshot_heuristics.load_snapshot_heuristic(date_str)

        path, explored = run_astar(params, progress_callback=progress_callback)

        if path:
            stats = compute_route_stats(path, params.depth_grid, _fuel_retriever._index)
        else:
            stats = {}
            logging.warning(f"run_date_comparison: no path found for date '{date_str}' (key '{key}')")

        results[key] = {"date": date_str, "path": path, "stats": stats}

    return results


# ---------------------------------------------------------------------------
# Route statistics
# ---------------------------------------------------------------------------
# Nautical miles per grid cell (approximate, based on ~0.25° resolution)
# 1° latitude ≈ 60 nautical miles → 0.25° ≈ 15 nm per cell
# Diagonal cells: 15 * sqrt(2) ≈ 21.2 nm
NM_PER_CELL_STRAIGHT = 15.0
NM_PER_CELL_DIAGONAL = NM_PER_CELL_STRAIGHT * math.sqrt(2)


def compute_route_stats(path: list, depth_grid: dict, fuel_grid: dict) -> dict:
    """
    Compute summary statistics for a completed route.

    Returns a dict with:
        distance_nm    — total distance in nautical miles
        fuel_index     — relative fuel cost index (lower = more efficient)
        min_depth_m    — shallowest point along the route (metres, negative)
        cell_count     — number of cells in path
        wind_avg       — placeholder (requires re-running alignment, skipped for speed)
    """
    if not path or len(path) < 2:
        return {}

    distance_nm = 0.0
    fuel_index = 0.0
    min_depth = None  # will track shallowest (least negative) depth

    for i in range(1, len(path)):
        prev = path[i - 1]
        curr = path[i]
        dx = abs(curr[0] - prev[0])
        dy = abs(curr[1] - prev[1])
        is_diagonal = (dx == 1 and dy == 1)
        distance_nm += NM_PER_CELL_DIAGONAL if is_diagonal else NM_PER_CELL_STRAIGHT

        # Fuel index accumulation
        fs = fuel_grid.get((curr[0], curr[1]), 0.5)
        fuel_index += fs

        # Depth tracking
        d = depth_grid.get((curr[0], curr[1]))
        if d is not None:
            if min_depth is None or d > min_depth:
                min_depth = d

    return {
        "distance_nm": round(distance_nm, 1),
        "fuel_index": round(fuel_index / len(path), 3),
        "min_depth_m": round(min_depth, 1) if min_depth is not None else None,
        "cell_count": len(path),
    }

# ---------------------------------------------------------------------------
# Route explanation (human-readable summary of what shaped the route)
# ---------------------------------------------------------------------------
def explain_route(path: list, depth_grid: dict, fuel_grid: dict,
                   land_cells: set) -> str:
    """
    Generate a one-paragraph explanation of what shaped this route.
    Used in the UI status area and the export file.
    """
    if not path or len(path) < 2:
        return "No route to explain."

    total = len(path)
    shallow_cells = 0
    high_fuel_cells = 0
    low_fuel_cells = 0

    for cell in path:
        d = depth_grid.get(cell)
        if d is not None and d > -15:
            shallow_cells += 1

        fs = fuel_grid.get(cell, 0.5)
        if fs < 0.35:
            low_fuel_cells += 1
        elif fs > 0.65:
            high_fuel_cells += 1

    parts = []

    if shallow_cells == 0:
        parts.append("stayed in deep water throughout")
    elif shallow_cells < total * 0.1:
        parts.append(f"briefly crossed shallow water ({shallow_cells} cells)")
    else:
        parts.append(f"passed through shallow sections ({shallow_cells} cells — consider a larger draft margin)")

    fuel_pct = low_fuel_cells / total * 100
    if fuel_pct > 60:
        parts.append(f"{fuel_pct:.0f}% of the route used fuel-efficient cells")
    elif high_fuel_cells > total * 0.3:
        parts.append("significant portion of route passed through fuel-heavy zones")

    stats = compute_route_stats(path, depth_grid, fuel_grid)
    dist = stats.get("distance_nm", 0)
    # Straight-line distance (approximate)
    start, end = path[0], path[-1]
    straight_cells = _euclidean(start, end)
    straight_nm = straight_cells * NM_PER_CELL_STRAIGHT
    if straight_nm > 0:
        detour_pct = (dist - straight_nm) / straight_nm * 100
        if detour_pct > 5:
            parts.append(
                f"route is {detour_pct:.0f}% longer than the straight-line distance "
                f"({dist:.0f} nm vs {straight_nm:.0f} nm direct) — detour is intentional to avoid obstacles or optimise cost"
            )
        else:
            parts.append(f"route closely follows the direct line ({dist:.0f} nm)")

    if not parts:
        return f"Route found: {dist:.0f} nm, {total} waypoints."

    return "Route summary: " + " · ".join(parts) + "."