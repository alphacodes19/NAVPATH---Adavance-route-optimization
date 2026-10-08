"""
Static database of common vessel profiles, for the ship-dimension
auto-fill selector (Phase 2D). Selecting one fills the existing L/B/H/Eff
boxes in src/app/ui_elements.py — "H" is filled with draft, matching how
src/app/main.py.get_min_depth_for_vessel() already treats that box as a
draft proxy.

speed_kn isn't read by anything yet (get_ship_size_factor() has no speed
term) — kept here for when Phase 3 vessel-speed-aware ETA work wants it,
same spirit as the workplan's own VESSELS sketch.
"""

VESSELS = [
    {"name": "Cargo Ship",   "L": 180, "B": 25, "draft": 8,  "speed_kn": 14, "eff": 1.0},
    {"name": "Tanker",       "L": 250, "B": 40, "draft": 12, "speed_kn": 12, "eff": 0.8},
    {"name": "Container",    "L": 300, "B": 45, "draft": 14, "speed_kn": 18, "eff": 0.9},
    {"name": "Passenger",    "L": 200, "B": 28, "draft": 7,  "speed_kn": 20, "eff": 1.1},
    {"name": "Small Vessel", "L": 50,  "B": 10, "draft": 3,  "speed_kn": 10, "eff": 1.3},
]