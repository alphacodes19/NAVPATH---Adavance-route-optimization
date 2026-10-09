"""
Visual data layers (Phase 3A) — wind-direction arrows, current-direction
arrows, and three heatmap overlays (depth, fuel efficiency, routing
heuristic/weather cost). Each layer toggles independently with keys 1-5
and layers draw on top of each other if more than one is active.

Call handle_key_toggle(event.key) from main.py's KEYDOWN handling, and
draw_all() + draw_legend() once per frame, right after drawGrid() and
before the explored-cell/route drawing (so routes stay visible on top
of any active overlay).

Has a pygame dependency (drawing), same as ui_elements.py/route_panel.py —
lives in src/app/, not src/engine/.
"""

import math

import pygame

from src.engine import router as route_engine
from src.engine.coord_convert import (
    grid_to_latitude, grid_to_longitude, round_latitude, round_longitude,
)
from src.app.ui_elements import get_font
from src import config

_GRID_COLS = route_engine.GRID_COLS
_GRID_ROWS = route_engine.GRID_ROWS
_MAP_W, _MAP_H = 550, 600  # same map dimensions used throughout src/app/main.py

# ---------------------------------------------------------------------------
# Toggle state — one independent bool per layer
# ---------------------------------------------------------------------------
show_wind_arrows = False
show_current_arrows = False
show_depth_heat = False
show_fuel_heat = False
show_heuristic_heat = False

_KEY_TOGGLE_MAP = {
    pygame.K_1: "show_wind_arrows",
    pygame.K_2: "show_current_arrows",
    pygame.K_3: "show_depth_heat",
    pygame.K_4: "show_fuel_heat",
    pygame.K_5: "show_heuristic_heat",
}


def handle_key_toggle(key) -> bool:
    """
    Flip the layer bound to this key (1-5).
    Returns True if the key was one of the layer toggles, so main.py's
    KEYDOWN handling knows it was consumed; False for any other key
    (harmless no-op — main.py doesn't need to check before calling this).
    """
    attr = _KEY_TOGGLE_MAP.get(key)
    if attr is None:
        return False
    globals()[attr] = not globals()[attr]
    return True


# ---------------------------------------------------------------------------
# Wind / current arrows
# ---------------------------------------------------------------------------
# One arrow every N grid cells, not one per cell — the grid is 137x150
# cells at 4px each; an arrow per cell would be ~20,000 arrows in a
# 550x600px area, each under a pixel apart and unreadable. Every 8th cell
# (32px spacing) gives a legible vector field instead.
ARROW_STRIDE_CELLS = 8
_ARROW_LEN = 12  # px

WIND_ARROW_COLOR = (80, 220, 255)
CURRENT_ARROW_COLOR = (255, 170, 60)


def _draw_arrow(screen, cx, cy, angle_deg, color, length=_ARROW_LEN):
    """Draw one small directional arrow centred at (cx, cy)."""
    rad = math.radians(angle_deg)
    # Compass/met convention: 0=N, 90=E, measured clockwise. Screen y grows
    # downward, so "north" (up on screen) is -y.
    dx = math.sin(rad) * length
    dy = -math.cos(rad) * length
    tip = (cx + dx, cy + dy)
    tail = (cx - dx * 0.4, cy - dy * 0.4)
    pygame.draw.line(screen, color, tail, tip, 2)
    head_angle = math.atan2(-dy, dx)
    for sign in (-1, 1):
        a = head_angle + sign * math.radians(150)
        hx = tip[0] + math.cos(a) * 5
        hy = tip[1] + math.sin(a) * 5
        pygame.draw.line(screen, color, tip, (hx, hy), 2)


def _draw_wind_arrows(screen, map_position, grid_size, land_cells):
    for gx in range(0, _GRID_COLS, ARROW_STRIDE_CELLS):
        for gy in range(0, _GRID_ROWS, ARROW_STRIDE_CELLS):
            if (gx, gy) in land_cells:
                continue
            lat = round_latitude(grid_to_latitude(gy))
            lon = round_longitude(grid_to_longitude(gx))
            direction = route_engine._wind_retriever.retrieve_wind_direction(lon, lat)
            cx = map_position[0] + gx * grid_size + grid_size // 2
            cy = map_position[1] + gy * grid_size + grid_size // 2
            _draw_arrow(screen, cx, cy, direction, WIND_ARROW_COLOR)


def _draw_current_arrows(screen, map_position, grid_size, land_cells):
    for gx in range(0, _GRID_COLS, ARROW_STRIDE_CELLS):
        for gy in range(0, _GRID_ROWS, ARROW_STRIDE_CELLS):
            if (gx, gy) in land_cells:
                continue
            lat = round_latitude(grid_to_latitude(gy))
            lon = round_longitude(grid_to_longitude(gx))
            angle = route_engine._current_retriever.retrieve_angle(lon, lat)
            cx = map_position[0] + gx * grid_size + grid_size // 2
            cy = map_position[1] + gy * grid_size + grid_size // 2
            _draw_arrow(screen, cx, cy, angle, CURRENT_ARROW_COLOR)


# ---------------------------------------------------------------------------
# Heatmaps (depth / fuel / heuristic cost)
# ---------------------------------------------------------------------------
# Each heatmap is built once (full grid scan, ~20k cells — a few ms, cheap
# as a one-off) into a normalised {(gx,gy): [0,1]} dict, rendered onto an
# off-screen translucent Surface once, then just re-blitted every frame
# while the layer is on. Nothing is recomputed per-frame unless the
# underlying data changes (the heuristic layer, below, depends on the
# historical-date selection, so it's the one layer that can go stale).

def _normalize(values: dict) -> dict:
    if not values:
        return {}
    vals = values.values()
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


_HEAT_STOPS = [
    (0.0, (40, 60, 200)),    # blue   — low
    (0.33, (40, 200, 200)),  # cyan
    (0.66, (230, 220, 40)),  # yellow
    (1.0, (220, 40, 40)),    # red    — high
]


def _color_for(v: float) -> tuple:
    v = max(0.0, min(1.0, v))
    for i in range(len(_HEAT_STOPS) - 1):
        t0, c0 = _HEAT_STOPS[i]
        t1, c1 = _HEAT_STOPS[i + 1]
        if t0 <= v <= t1:
            f = (v - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(c0[j] + (c1[j] - c0[j]) * f) for j in range(3))
    return _HEAT_STOPS[-1][1]


def _render_heat_surface(values01: dict, grid_size: int) -> "pygame.Surface":
    surf = pygame.Surface((_MAP_W, _MAP_H), pygame.SRCALPHA)
    for (gx, gy), v in values01.items():
        color = _color_for(v) + (140,)  # alpha
        surf.fill(color, (gx * grid_size, gy * grid_size, grid_size, grid_size))
    return surf


def _depth_heat_values(depth_grid: dict) -> dict:
    # DEPTH_GRID in main.py is already keyed by (grid_x, grid_y) directly.
    return dict(depth_grid)


def _fuel_heat_values(land_cells: set) -> dict:
    values = {}
    for gx in range(_GRID_COLS):
        for gy in range(_GRID_ROWS):
            if (gx, gy) in land_cells:
                continue
            lat = round_latitude(grid_to_latitude(gy))
            lon = round_longitude(grid_to_longitude(gx))
            values[(gx, gy)] = route_engine._fuel_retriever.retrieve_fuel_efficiency(lon, lat)
    return values


def _heuristic_heat_values(land_cells: set, heuristic_override: dict = None) -> dict:
    values = {}
    for gx in range(_GRID_COLS):
        for gy in range(_GRID_ROWS):
            if (gx, gy) in land_cells:
                continue
            lat = round_latitude(grid_to_latitude(gy))
            lon = round_longitude(grid_to_longitude(gx))
            if heuristic_override:
                values[(gx, gy)] = heuristic_override.get((lon, lat), 0.5)
            else:
                values[(gx, gy)] = route_engine._heuristic_retriever.get_heuristic_value(
                    lat, lon, config.HEURISTICS_PKL
                )
    return values


# Cached rendered Surfaces — rebuilt only when their layer is toggled on
# with no existing cache (depth/fuel: data never changes mid-session) or
# when the heuristic layer's input (heuristic_override) changes.
_depth_heat_surface = None
_fuel_heat_surface = None
_heuristic_heat_surface = None
_UNSET = object()  # sentinel distinct from a real cache key of None (= "no override selected")
_heuristic_heat_surface_key = _UNSET  # id(heuristic_override) the cache was built from


def draw_all(screen, map_position, grid_size, land_cells, depth_grid, heuristic_override=None):
    """
    Draw every currently-active layer. Call once per frame, right after
    drawGrid() and before the persistent route/explored-cell drawing.
    """
    global _depth_heat_surface, _fuel_heat_surface
    global _heuristic_heat_surface, _heuristic_heat_surface_key

    if show_depth_heat:
        if _depth_heat_surface is None:
            _depth_heat_surface = _render_heat_surface(
                _normalize(_depth_heat_values(depth_grid)), grid_size
            )
        screen.blit(_depth_heat_surface, map_position)

    if show_fuel_heat:
        if _fuel_heat_surface is None:
            _fuel_heat_surface = _render_heat_surface(
                _normalize(_fuel_heat_values(land_cells)), grid_size
            )
        screen.blit(_fuel_heat_surface, map_position)

    if show_heuristic_heat:
        key = id(heuristic_override) if heuristic_override is not None else None
        if _heuristic_heat_surface_key != key:
            _heuristic_heat_surface = _render_heat_surface(
                _normalize(_heuristic_heat_values(land_cells, heuristic_override)), grid_size
            )
            _heuristic_heat_surface_key = key
        screen.blit(_heuristic_heat_surface, map_position)

    if show_wind_arrows:
        _draw_wind_arrows(screen, map_position, grid_size, land_cells)

    if show_current_arrows:
        _draw_current_arrows(screen, map_position, grid_size, land_cells)


# ---------------------------------------------------------------------------
# Legend — shows which keys map to which layer, highlighting active ones
# ---------------------------------------------------------------------------
_LAYERS_INFO = [
    ("1", "Wind", "show_wind_arrows", WIND_ARROW_COLOR),
    ("2", "Current", "show_current_arrows", CURRENT_ARROW_COLOR),
    ("3", "Depth", "show_depth_heat", (80, 160, 255)),
    ("4", "Fuel", "show_fuel_heat", (255, 200, 80)),
    ("5", "Heuristic", "show_heuristic_heat", (255, 120, 120)),
]
_LEGEND_INACTIVE_COLOR = (90, 90, 100)


def draw_legend(screen, map_position):
    """Small "[1] Wind  [2] Current ..." strip, drawn just below the map."""
    font = get_font(18, bold=True)
    x = map_position[0]
    y = map_position[1] + _MAP_H + 6
    for key_label, name, attr, color in _LAYERS_INFO:
        active = globals()[attr]
        text = f"[{key_label}] {name}"
        surf = font.render(text, True, color if active else _LEGEND_INACTIVE_COLOR)
        screen.blit(surf, (x, y))
        x += surf.get_width() + 18