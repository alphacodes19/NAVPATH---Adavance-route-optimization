"""
Algorithm benchmark (Phase 3C) — runs Dijkstra, Greedy Best-First, and a
textbook A* against the same start/end/vessel, all three sharing the
*same* per-step edge-cost function, so the comparison measures the
search strategies themselves rather than three different cost models.

This is intentionally a separate, self-contained implementation from
router.run_astar(). That function's calculate_fscore() blends g (cost so
far) and h (heuristic) together per routing "mode" (cargo/fuel/speed/
comfort/pareto) — a deliberate per-mode weighting, not a clean g+h split,
and g_score there is accumulated straight-line distance only (environmental
factors live in the priority, not in g itself). Reusing it here would make
Dijkstra/Greedy/A* not directly comparable, and risks destabilising the
already-validated primary routing engine for what is otherwise a side
benchmarking feature. Here g and h are kept strictly separate, so
"A* priority = Dijkstra's g + Greedy's h" is literally true — which is the
whole point of the exercise.

Reuses get_neighbors() from router.py (land/black-cell/draft filtering,
wind/current alignment) so all three algorithms see exactly the same
valid moves as the main app's own A*.
"""

import time
import logging
from queue import PriorityQueue

from src.engine.router import (
    RouteParams, get_neighbors, _euclidean, _depth_penalty, _heuristic_value,
    _fuel_retriever, _heuristic_retriever, compute_route_stats,
)
from src import config


def _edge_cost(current: tuple, neighbor: tuple, wind_align: float, current_align: float,
                params: RouteParams) -> float:
    """
    The real cost of moving from current to neighbor — the 'g' component,
    shared by all three algorithms so they rank the exact same move costs
    and differ only in search strategy. Mirrors the environmental factors
    router.calculate_fscore() applies (depth penalty, ship size, wind/
    current alignment) but keeps them entirely separate from any
    estimate of remaining distance to the goal.
    """
    depth_pen = _depth_penalty(neighbor, params.depth_grid, params.min_depth)
    step = _euclidean(current, neighbor)
    cost = (step + depth_pen) * params.ship_size_factor
    cost *= (1.15 - 0.30 * wind_align)
    cost *= (1.15 - 0.30 * current_align)
    return cost


def _heuristic_cost(cell: tuple, end: tuple, heuristic_override: dict = None) -> float:
    """
    Estimated remaining cost from cell to end — the 'h' component.
    Straight-line distance, nudged by the trained/snapshot weather-cost
    data (same source _heuristic_value() reads elsewhere), kept small
    relative to the distance term so h stays a plausible distance
    estimate rather than swamping it.
    """
    euclid = _euclidean(cell, end)
    weather = _heuristic_value(cell, config.HEURISTICS_PKL, heuristic_override)
    return euclid + weather * 5.0


def _search(params: RouteParams, use_g: bool, use_h: bool) -> tuple:
    """
    Shared best-first search loop. priority = (use_g * g) + (use_h * h):
        A*:       use_g=True,  use_h=True
        Dijkstra: use_g=True,  use_h=False
        Greedy:   use_g=False, use_h=True

    Returns (path, nodes_explored, elapsed_seconds). path is None if no
    route was found (elapsed_seconds still reflects the full failed search).
    """
    start, end = params.start, params.end
    t0 = time.perf_counter()

    open_set = PriorityQueue()
    open_set.put((0.0, start))
    came_from = {}
    g_score = {start: 0.0}
    visited = set()
    nodes_explored = 0

    while not open_set.empty():
        _, current = open_set.get()
        if current in visited:
            continue
        visited.add(current)

        if current != start and current != end:
            nodes_explored += 1

        if current == end:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            elapsed = time.perf_counter() - t0
            return path, nodes_explored, elapsed

        for neighbor, wind_align, current_align in get_neighbors(current, params):
            step_cost = _edge_cost(current, neighbor, wind_align, current_align, params)
            tentative_g = g_score[current] + step_cost
            if neighbor not in g_score or tentative_g < g_score[neighbor]:
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                priority = 0.0
                if use_g:
                    priority += tentative_g
                if use_h:
                    priority += _heuristic_cost(neighbor, end, params.heuristic_override)
                open_set.put((priority, neighbor))

    elapsed = time.perf_counter() - t0
    logging.warning(f"benchmark _search(use_g={use_g}, use_h={use_h}): no path found")
    return None, nodes_explored, elapsed


_ALGORITHMS = {
    "dijkstra": (True, False),
    "greedy": (False, True),
    "astar": (True, True),
}


def run_benchmark(params_base: RouteParams) -> dict:
    """
    Run Dijkstra, Greedy Best-First, and A* on the same start/end/vessel.

    Returns:
        {
          'dijkstra': {'path':[...] or None, 'stats':{...}, 'nodes_explored':int, 'time_s':float},
          'greedy':   {...},
          'astar':    {...},
        }
    stats come from router.compute_route_stats() — same distance_nm/
    fuel_index/min_depth_m fields as every other panel in the app, so
    they're directly comparable.
    """
    # Pre-warm the heuristic PKL before any algorithm is timed. HeuristicRetriever
    # lazy-loads+caches per filename on first get_heuristic_value() call (unlike
    # the wind/current/fuel retrievers, which load eagerly at import time) — so
    # whichever algorithm happened to call it first would otherwise absorb a
    # one-time multi-second deserialization cost that has nothing to do with its
    # search strategy, making time_s not actually comparable across the three.
    # Dijkstra never calls it at all (use_h=False), so without this, a cold-start
    # benchmark run would make Greedy or A* look artificially — and randomly,
    # depending on dict ordering — much slower than the other.
    _heuristic_retriever.load_file(config.HEURISTICS_PKL)

    results = {}
    for key, (use_g, use_h) in _ALGORITHMS.items():
        path, nodes_explored, elapsed = _search(params_base, use_g, use_h)
        if path:
            stats = compute_route_stats(path, params_base.depth_grid, _fuel_retriever._index)
        else:
            stats = {}
        results[key] = {
            "path": path,
            "stats": stats,
            "nodes_explored": nodes_explored,
            "time_s": round(elapsed, 4),
        }
    return results