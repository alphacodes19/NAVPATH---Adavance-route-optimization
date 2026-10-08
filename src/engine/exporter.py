"""
Route export utilities.
Converts a path (list of grid cells) to lat/lon and writes to CSV or GPX.
No pygame dependency.
"""

import csv
import math
from pathlib import Path
from datetime import datetime

from src.engine.coord_convert import grid_to_latitude, grid_to_longitude


def path_to_latlon(path: list) -> list:
    """
    Convert a list of (grid_x, grid_y) cells to (lat, lon) pairs.
    Returns list of (lat, lon) floats.
    """
    return [
        (grid_to_latitude(cell[1]), grid_to_longitude(cell[0]))
        for cell in path
    ]


def export_csv(path: list, stats: dict, mode: str, output_dir: str = ".") -> str:
    """
    Export route as CSV with lat, lon, waypoint index, and cumulative distance.

    Returns the output file path as a string.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_dir / f"navpath_route_{mode}_{timestamp}.csv"

    waypoints = path_to_latlon(path)

    NM_STRAIGHT = 15.0
    NM_DIAGONAL = NM_STRAIGHT * math.sqrt(2)

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)

        # Header block with route metadata
        writer.writerow(["# NAVPATH Route Export"])
        writer.writerow(["# Generated", datetime.now().isoformat()])
        writer.writerow(["# Mode", mode])
        writer.writerow(["# Total distance (nm)", stats.get("distance_nm", "?")])
        writer.writerow(["# Minimum depth (m)", stats.get("min_depth_m", "no data")])
        writer.writerow(["# Fuel efficiency index", stats.get("fuel_index", "?")])
        writer.writerow(["# Waypoints", len(waypoints)])
        writer.writerow([])  # blank line

        # Column headers
        writer.writerow(["waypoint", "latitude", "longitude",
                          "cumulative_distance_nm", "grid_x", "grid_y"])

        cumulative = 0.0
        for i, (cell, (lat, lon)) in enumerate(zip(path, waypoints)):
            if i > 0:
                prev = path[i - 1]
                dx = abs(cell[0] - prev[0])
                dy = abs(cell[1] - prev[1])
                step_nm = NM_DIAGONAL if (dx == 1 and dy == 1) else NM_STRAIGHT
                cumulative += step_nm

            writer.writerow([
                i + 1,
                round(lat, 4),
                round(lon, 4),
                round(cumulative, 2),
                cell[0],
                cell[1],
            ])

    return str(filename)


def export_gpx(path: list, stats: dict, mode: str, output_dir: str = ".") -> str:
    """
    Export route as GPX (GPS Exchange Format).
    Compatible with Google Earth, chartplotters, and most marine navigation software.

    Returns the output file path as a string.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_dir / f"navpath_route_{mode}_{timestamp}.gpx"

    waypoints = path_to_latlon(path)

    gpx_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="NAVPATH"',
        '     xmlns="http://www.topografix.com/GPX/1/1">',
        f'  <metadata>',
        f'    <name>NAVPATH {mode.upper()} Route</name>',
        f'    <desc>Mode: {mode} | Distance: {stats.get("distance_nm", "?")} nm | '
        f'Min depth: {stats.get("min_depth_m", "no data")} m</desc>',
        f'    <time>{datetime.now().isoformat()}</time>',
        f'  </metadata>',
        f'  <rte>',
        f'    <name>NAVPATH {mode.upper()} Route</name>',
    ]

    for i, (lat, lon) in enumerate(waypoints):
        gpx_lines.append(
            f'    <rtept lat="{round(lat, 6)}" lon="{round(lon, 6)}">'
            f'<name>WP{i+1:04d}</name></rtept>'
        )

    gpx_lines += [
        '  </rte>',
        '</gpx>',
    ]

    with open(filename, "w") as f:
        f.write("\n".join(gpx_lines))

    return str(filename)
