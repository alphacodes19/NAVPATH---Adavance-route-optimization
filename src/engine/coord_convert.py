# Named constants for the grid-to-geography mapping.
# These four values appear in four functions — centralising them means
# changing the grid bounds only needs to happen in one place.
NORTH_LAT = 37.1
NORTH_GRID_Y = 9
SOUTH_LAT = 8.1
SOUTH_GRID_Y = 135

WEST_LON = 68.1167
EAST_LON = 97.4167
WEST_GRID_X = 16
EAST_GRID_X = 121

_LAT_PER_CELL = (NORTH_LAT - SOUTH_LAT) / (NORTH_GRID_Y - SOUTH_GRID_Y)
_LON_PER_CELL = (EAST_LON - WEST_LON) / (EAST_GRID_X - WEST_GRID_X)


def grid_to_latitude(grid_y):
    latitude = NORTH_LAT + (grid_y - NORTH_GRID_Y) * _LAT_PER_CELL
    return round(round(latitude / 0.250) * 0.250, 3)


def grid_to_longitude(grid_x):
    longitude = WEST_LON + (grid_x - WEST_GRID_X) * _LON_PER_CELL
    return round(round((longitude - 0.125) / 0.250) * 0.250 + 0.125, 3)


def latitude_to_grid(latitude):
    return round(NORTH_GRID_Y + (latitude - NORTH_LAT) / _LAT_PER_CELL)


def longitude_to_grid(longitude):
    return round(WEST_GRID_X + (longitude - WEST_LON) / _LON_PER_CELL)


def round_latitude(latitude):
    return round(round(latitude / 0.250) * 0.250, 3)


def round_longitude(longitude):
    return round(round((longitude - 0.125) / 0.250) * 0.250 + 0.125, 3)