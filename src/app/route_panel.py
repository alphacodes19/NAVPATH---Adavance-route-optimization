"""
Route statistics panel — drawn on the right side of the screen after a
route is found. Shows distance, ETA, fuel index, minimum depth, and
mode used. No pygame dependency on the engine — receives a pre-computed
stats dict from router.compute_route_stats().
"""

import pygame

from src.app.ui_elements import get_font

# Colours — keeping them consistent with ui_elements.py
PANEL_BG = (20, 28, 40)
PANEL_BORDER = (60, 90, 130)
TITLE_COLOUR = (140, 200, 255)
LABEL_COLOUR = (160, 160, 180)
VALUE_COLOUR = (240, 240, 240)
GOOD_COLOUR = (80, 200, 120)    # green — good depth, low fuel
WARN_COLOUR = (255, 200, 60)    # yellow — marginal
BAD_COLOUR = (220, 80, 80)      # red — shallow / high fuel
WHITE = (255, 255, 255)


def _depth_colour(depth_m):
    if depth_m is None:
        return LABEL_COLOUR
    if depth_m < -40:
        return GOOD_COLOUR
    if depth_m < -15:
        return WARN_COLOUR
    return BAD_COLOUR


def _fuel_colour(fuel_index):
    """fuel_index is a normalised score [0, 1] — lower is more efficient."""
    if fuel_index < 0.35:
        return GOOD_COLOUR
    if fuel_index < 0.65:
        return WARN_COLOUR
    return BAD_COLOUR


def draw_route_panel(screen, stats: dict, mode: str, vessel_speed_knots: float = 12.0):
    """
    Draw the route statistics panel.

    Args:
        screen:              pygame display surface
        stats:               dict from router.compute_route_stats()
        mode:                routing mode string ("cargo", "speed", etc.)
        vessel_speed_knots:  used to compute ETA; defaults to 12 knots
                             (typical coastal cargo speed)
    """
    if not stats:
        return

    # Panel geometry — positioned to the right of the map
    # Map ends at x = 100 + 550 = 650. Panel starts at 670, below weather boxes.
    panel_x = 670
    panel_y = 550     # below weather boxes which sit at y~510
    panel_w = 560
    panel_h = 220

    # Background
    pygame.draw.rect(screen, PANEL_BORDER,
                      (panel_x - 2, panel_y - 2, panel_w + 4, panel_h + 4),
                      border_radius=10)
    pygame.draw.rect(screen, PANEL_BG,
                      (panel_x, panel_y, panel_w, panel_h),
                      border_radius=10)

    font_title = get_font(28)
    font_label = get_font(24)
    font_value = get_font(30)
    font_small = get_font(22)

    # Title
    title = font_title.render(f"ROUTE ANALYSIS  ·  {mode.upper()} MODE", True, TITLE_COLOUR)
    screen.blit(title, (panel_x + 12, panel_y + 12))

    # Divider
    pygame.draw.line(screen, PANEL_BORDER,
                      (panel_x + 10, panel_y + 36),
                      (panel_x + panel_w - 10, panel_y + 36))

    # --- Stats grid (two columns) ---
    distance_nm = stats.get("distance_nm")
    fuel_index = stats.get("fuel_index")
    min_depth = stats.get("min_depth_m")
    cell_count = stats.get("cell_count", 0)

    # ETA calculation
    eta_str = "—"
    if distance_nm and vessel_speed_knots > 0:
        eta_hours = distance_nm / vessel_speed_knots
        eta_h = int(eta_hours)
        eta_m = int((eta_hours - eta_h) * 60)
        eta_str = f"{eta_h}h {eta_m:02d}m"

    # Column layout
    col1_x = panel_x + 16
    col2_x = panel_x + panel_w // 2 + 10
    row_start = panel_y + 48
    row_gap = 42

    def draw_stat(x, y, label, value, colour=VALUE_COLOUR, unit=""):
        lbl = font_label.render(label, True, LABEL_COLOUR)
        screen.blit(lbl, (x, y))
        val_text = f"{value}  {unit}".strip() if value is not None else "—"
        val = font_value.render(str(val_text), True, colour)
        screen.blit(val, (x, y + 18))

    # Row 0
    draw_stat(col1_x, row_start,
              "DISTANCE",
              f"{distance_nm}" if distance_nm else "—",
              VALUE_COLOUR, "nm")

    draw_stat(col2_x, row_start,
              "ETA  (@ 12 kn)",
              eta_str)

    # Row 1
    draw_stat(col1_x, row_start + row_gap,
              "MIN DEPTH",
              f"{min_depth}" if min_depth is not None else "no data",
              _depth_colour(min_depth), "m")

    draw_stat(col2_x, row_start + row_gap,
              "FUEL EFFICIENCY INDEX",
              f"{fuel_index:.3f}" if fuel_index else "—",
              _fuel_colour(fuel_index) if fuel_index else VALUE_COLOUR)

    # Row 2
    draw_stat(col1_x, row_start + row_gap * 2,
              "WAYPOINTS",
              str(cell_count))

    # Depth safety label
    if min_depth is not None:
        if min_depth < -40:
            safety = "Deep water  ✓"
            sc = GOOD_COLOUR
        elif min_depth < -15:
            safety = "Moderate depth  ⚠"
            sc = WARN_COLOUR
        else:
            safety = "Shallow section  ✗"
            sc = BAD_COLOUR
        sl = font_small.render(safety, True, sc)
        screen.blit(sl, (col2_x, row_start + row_gap * 2 + 18))

    # Bottom note
    note = font_small.render(
        "Depth colour: green >40m · yellow 15–40m · red <15m   |   "
        "Fuel index: lower = more efficient",
        True, (100, 100, 120))
    screen.blit(note, (panel_x + 12, panel_y + panel_h - 22))


def draw_comparison_panel(screen, multi_routes: dict, selected_key: str,
                           vessel_speed_knots: float = 12.0) -> dict:
    """
    Side-by-side table for the three router.run_multi_route() results.
    Reuses the same screen region as draw_route_panel() — the two are
    mutually exclusive (compare mode vs single-route mode).

    Args:
        screen:         pygame display surface
        multi_routes:   {'speed': {'path':..., 'stats':...}, 'fuel':..., 'safe':...}
        selected_key:   which column is currently highlighted
        vessel_speed_knots: used for the ETA row

    Returns:
        {key: pygame.Rect} for each column header, so main.py can
        hit-test clicks against the *just-drawn* rects to change the
        selected/highlighted route on the next event.
    """
    if not multi_routes:
        return {}

    panel_x, panel_y, panel_w, panel_h = 670, 550, 560, 220

    pygame.draw.rect(screen, PANEL_BORDER,
                      (panel_x - 2, panel_y - 2, panel_w + 4, panel_h + 4),
                      border_radius=10)
    pygame.draw.rect(screen, PANEL_BG,
                      (panel_x, panel_y, panel_w, panel_h),
                      border_radius=10)

    font_title = get_font(26)
    font_label = get_font(20)
    font_value = get_font(22)

    title = font_title.render("ROUTE COMPARISON", True, TITLE_COLOUR)
    screen.blit(title, (panel_x + 12, panel_y + 10))
    pygame.draw.line(screen, PANEL_BORDER,
                      (panel_x + 10, panel_y + 36),
                      (panel_x + panel_w - 10, panel_y + 36))

    keys = ["speed", "fuel", "safe"]
    display_names = {"speed": "SPEED", "fuel": "FUEL", "safe": "SAFE"}
    key_colours = {"speed": (0, 120, 255), "fuel": (0, 200, 80), "safe": (255, 200, 0)}

    label_col_w = 140
    col_w = (panel_w - label_col_w - 16) // 3
    col_x = {key: panel_x + 16 + label_col_w + i * col_w for i, key in enumerate(keys)}

    header_y = panel_y + 44
    header_rects = {}

    for key in keys:
        rect = pygame.Rect(col_x[key], header_y, col_w - 8, 30)
        header_rects[key] = rect
        colour = key_colours[key]
        if key == selected_key:
            pygame.draw.rect(screen, colour, rect, border_radius=6)
            text_colour = (10, 10, 10)
        else:
            pygame.draw.rect(screen, colour, rect, 2, border_radius=6)
            text_colour = colour
        lbl = font_label.render(display_names[key], True, text_colour)
        screen.blit(lbl, (rect.centerx - lbl.get_width() // 2, rect.centery - lbl.get_height() // 2))

    row_labels = ["Distance", "ETA", "Fuel Index", "Min Depth"]
    row_y_start = header_y + 40
    row_gap = 34

    for ri, row_label in enumerate(row_labels):
        ly = row_y_start + ri * row_gap
        lbl = font_label.render(row_label, True, LABEL_COLOUR)
        screen.blit(lbl, (panel_x + 16, ly))

        for key in keys:
            data = multi_routes.get(key, {})
            stats = data.get("stats") or {}
            path = data.get("path")

            if not path:
                val_text, colour = "no route", BAD_COLOUR
            elif row_label == "Distance":
                d = stats.get("distance_nm")
                val_text, colour = (f"{d} nm" if d is not None else "—"), VALUE_COLOUR
            elif row_label == "ETA":
                d = stats.get("distance_nm")
                if d and vessel_speed_knots > 0:
                    eta_h = int(d / vessel_speed_knots)
                    eta_m = int(((d / vessel_speed_knots) - eta_h) * 60)
                    val_text = f"{eta_h}h {eta_m:02d}m"
                else:
                    val_text = "—"
                colour = VALUE_COLOUR
            elif row_label == "Fuel Index":
                f = stats.get("fuel_index")
                val_text = f"{f:.3f}" if f is not None else "—"
                colour = _fuel_colour(f) if f is not None else VALUE_COLOUR
            else:  # Min Depth
                m = stats.get("min_depth_m")
                val_text, colour = (f"{m} m" if m is not None else "no data"), _depth_colour(m)

            val = font_value.render(val_text, True, colour)
            screen.blit(val, (col_x[key] + (col_w - 8 - val.get_width()) // 2, ly))

    note = font_label.render("Click a column to highlight that route on the map",
                              True, (100, 100, 120))
    screen.blit(note, (panel_x + 12, panel_y + panel_h - 26))

    return header_rects


def draw_fuel_detail(screen, stats: dict, ship_factor: float):
    """
    Overlay panel showing fuel estimation breakdown.
    Toggled by the Fuel Estimation button.
    """
    if not stats:
        return

    overlay_x, overlay_y = 200, 150
    overlay_w, overlay_h = 400, 280

    # Semi-transparent background
    overlay_surf = pygame.Surface((overlay_w, overlay_h), pygame.SRCALPHA)
    overlay_surf.fill((10, 18, 30, 220))
    screen.blit(overlay_surf, (overlay_x, overlay_y))
    pygame.draw.rect(screen, PANEL_BORDER,
                      (overlay_x, overlay_y, overlay_w, overlay_h),
                      2, border_radius=10)

    font_t = get_font(28)
    font_l = get_font(24)
    font_v = get_font(30)
    font_n = get_font(20)

    title = font_t.render("FUEL ESTIMATION", True, TITLE_COLOUR)
    screen.blit(title, (overlay_x + 16, overlay_y + 14))
    pygame.draw.line(screen, PANEL_BORDER,
                      (overlay_x + 10, overlay_y + 38),
                      (overlay_x + overlay_w - 10, overlay_y + 38))

    fuel_index = stats.get("fuel_index", 0.5)
    distance = stats.get("distance_nm", 0)

    # Relative fuel cost: index × distance × ship_factor × reference_consumption
    # Reference: ~20 units per nm for a mid-size cargo ship (arbitrary but consistent)
    REFERENCE_CONSUMPTION = 20.0
    relative_fuel = fuel_index * distance * ship_factor * REFERENCE_CONSUMPTION

    rows = [
        ("Fuel efficiency index", f"{fuel_index:.3f}", "lower = better"),
        ("Route distance", f"{distance} nm", ""),
        ("Ship size factor", f"{ship_factor:.2f}×", "from L/B/H/Eff inputs"),
        ("Relative fuel cost", f"{relative_fuel:.0f} units", "relative estimate"),
        ("", "", ""),
        ("Note: values are relative proxies,", "", ""),
        ("not absolute litres.", "", ""),
    ]

    y = overlay_y + 50
    for label, value, note in rows:
        if label:
            lbl = font_l.render(label, True, LABEL_COLOUR)
            screen.blit(lbl, (overlay_x + 16, y))
        if value:
            val = font_v.render(value, True, VALUE_COLOUR)
            screen.blit(val, (overlay_x + 260, y - 2))
        if note:
            n = font_n.render(note, True, (100, 100, 120))
            screen.blit(n, (overlay_x + 16, y + 18))
        y += 36 if (label or value) else 10

    close = font_l.render("[ click Fuel Estimation again to close ]",
                           True, (100, 100, 120))
    screen.blit(close, (overlay_x + 16, overlay_y + overlay_h - 26))