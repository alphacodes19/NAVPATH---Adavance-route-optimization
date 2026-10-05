def grid_to_latitude(grid_y):
    northernmost_latitude = 37.1
    northernmost_grid_y = 9
    southernmost_latitude = 8.1
    southernmost_grid_y = 135
    latitude_per_cell = (northernmost_latitude - southernmost_latitude) / (northernmost_grid_y - southernmost_grid_y)
    latitude = northernmost_latitude + (grid_y - northernmost_grid_y) * latitude_per_cell
    latitude = round(latitude / 0.250) * 0.250
    return round(latitude, 3) 

def grid_to_longitude(grid_x):
    westernmost_longitude = 68.1167
    easternmost_longitude = 97.4167
    westernmost_grid_x = 16
    easternmost_grid_x = 121
    longitude_per_cell = (easternmost_longitude - westernmost_longitude) / (easternmost_grid_x - westernmost_grid_x)
    longitude = westernmost_longitude + (grid_x - westernmost_grid_x) * longitude_per_cell
    # Modify rounding for longitude to nearest multiple of 0.250 starting from 0.125
    longitude = round((longitude - 0.125) / 0.250) * 0.250 + 0.125
    return round(longitude, 3) 

def latitude_to_grid(latitude):
    northernmost_latitude = 37.1
    northernmost_grid_y = 9
    southernmost_latitude = 8.1
    southernmost_grid_y = 135
    latitude_per_cell = (northernmost_latitude - southernmost_latitude) / (northernmost_grid_y - southernmost_grid_y)
    grid_y = northernmost_grid_y + (latitude - northernmost_latitude) / latitude_per_cell
    grid_y = round(grid_y)
    return grid_y

def longitude_to_grid(longitude):
    westernmost_longitude = 68.1167
    easternmost_longitude = 97.4167
    westernmost_grid_x = 16
    easternmost_grid_x = 121
    longitude_per_cell = (easternmost_longitude - westernmost_longitude) / (easternmost_grid_x - westernmost_grid_x)
    grid_x = westernmost_grid_x + (longitude - westernmost_longitude) / longitude_per_cell
    grid_x = round(grid_x)
    return grid_x

def round_latitude(latitude):
    """
    Rounds a latitude to the nearest multiple of 0.250.
    """
    rounded_latitude = round(latitude / 0.250) * 0.250
    return round(rounded_latitude, 3)  

def round_longitude(longitude):
    """
    Rounds a longitude to the nearest multiple of 0.250, starting from 0.125.
    """
    rounded_longitude = round((longitude - 0.125) / 0.250) * 0.250 + 0.125
    return round(rounded_longitude, 3)   

running = True

# while running:
#     # Testing grid to latitude and longitude
#     print("Latitude = ", grid_to_latitude(123))
#     print("Longitude = ", grid_to_longitude(103))

#     # Testing latitude and longitude to grid
#     print("Grid Y for latitude =", latitude_to_grid(10.80))
#     print("Grid X for longitude = ", longitude_to_grid(92.41))
    
#     # Testing rounding functions
#     print(round_latitude(101.134))
#     print(round_longitude(101.134))
#     running = False
