"""Exporter tests ensure CSV and GPX outputs can be parsed by standard tools."""

import csv
import xml.etree.ElementTree as ET

from src.engine.exporter import export_csv, export_gpx, path_to_latlon


SAMPLE_PATH = [(50, 50), (51, 50), (52, 51)]
SAMPLE_STATS = {"distance_nm": 36.2, "min_depth_m": -12.0, "fuel_index": 0.7}


def test_export_csv_contains_parseable_waypoint_rows(tmp_path):
    output_path = export_csv(SAMPLE_PATH, SAMPLE_STATS, "speed", str(tmp_path))

    with open(output_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    header_index = next(i for i, row in enumerate(rows) if row and row[0] == "waypoint")
    header = rows[header_index]
    data = rows[header_index + 1 :]

    assert header == [
        "waypoint", "latitude", "longitude", "cumulative_distance_nm", "grid_x", "grid_y"
    ]
    assert len(data) == len(SAMPLE_PATH)
    assert [int(row[0]) for row in data] == [1, 2, 3]
    assert [(int(row[4]), int(row[5])) for row in data] == SAMPLE_PATH
    assert float(data[-1][3]) > 0


def test_export_gpx_is_well_formed_and_contains_route_points(tmp_path):
    output_path = export_gpx(SAMPLE_PATH, SAMPLE_STATS, "speed", str(tmp_path))
    root = ET.parse(output_path).getroot()

    namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}
    route_points = root.findall(".//gpx:rtept", namespace)
    expected_coordinates = path_to_latlon(SAMPLE_PATH)

    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"
    assert len(route_points) == len(SAMPLE_PATH)
    for node, (latitude, longitude) in zip(route_points, expected_coordinates):
        assert float(node.attrib["lat"]) == round(latitude, 6)
        assert float(node.attrib["lon"]) == round(longitude, 6)
