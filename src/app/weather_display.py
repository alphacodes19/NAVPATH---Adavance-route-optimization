import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pygame
import requests
import os
from dotenv import load_dotenv

from src import config
from src.app.ui_elements import get_font

# Initialize Pygame
pygame.init()

# Constants
WHITE = (255, 255, 255)
TEXT_COLOR = WHITE
BACKGROUND_COLOR = (30, 30, 30)
BORDER_COLOR = (128, 128, 128)
DIM_COLOR = (90, 90, 110)
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
BLACK = (0, 0, 0)

# Load API Key
load_dotenv(config.PROJECT_ROOT / ".env")
API_KEY = os.getenv("api_key")

# weather()/weatherTwo() are called every single frame from the main render
# loop (30-60 times a second), and originally each one hit the network with
# no caching — two blocking HTTP calls per frame. On a slow/unavailable
# network that made the whole app appear to freeze for seconds at a time.
# Caching per-coordinate for a few minutes fixes that; the weather isn't
# changing meaningfully within a single session anyway.
_weather_cache = {}
_CACHE_TTL_SECONDS = 300

# Function to fetch weather data
def get_weather_data(latitude, longitude):
    cache_key = (round(latitude, 2), round(longitude, 2))
    cached = _weather_cache.get(cache_key)
    if cached is not None and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f"http://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={API_KEY}&units=metric"
    try:
        # Timeout still matters for the first call (or once the cache
        # expires) — without it a hung request could block the app
        # indefinitely.
        response = requests.get(url, timeout=5)
    except requests.exceptions.RequestException:
        result = {"error": "Unable to fetch weather data"}
        _weather_cache[cache_key] = (time.time(), result)
        return result

    if response.status_code == 200:
        data = response.json()
        result = {
            "temperature": f"{data['main']['temp']}°C",
            "feels_like": f"{data['main']['feels_like']}°C",
            "humidity": f"{data['main']['humidity']}%",
            "wind_speed": f"{data['wind']['speed']} m/s",
            "description": data['weather'][0]['description'].capitalize().split()[0]
        }
    else:
        result = {"error": "Unable to fetch weather data"}

    _weather_cache[cache_key] = (time.time(), result)
    return result


def draw_weather_placeholder(screen, box_x: int, box_y: int,
                              box_w: int, box_h: int, label: str):
    """
    Draw an empty weather box with a prompt instead of fetching
    irrelevant weather data when no route endpoint is selected.
    """
    pygame.draw.rect(screen, BORDER_COLOR,
                      (box_x - 2, box_y - 2, box_w + 4, box_h + 4),
                      border_radius=10)
    pygame.draw.rect(screen, BACKGROUND_COLOR,
                      (box_x, box_y, box_w, box_h),
                      border_radius=10)

    label_font = get_font(28, bold=True)
    hint_font = get_font(22)

    lbl = label_font.render(label, True, (200, 200, 220))
    screen.blit(lbl, (box_x + box_w // 2 - lbl.get_width() // 2,
                       box_y + 14))

    hint = hint_font.render("Select a route endpoint", True, DIM_COLOR)
    screen.blit(hint, (box_x + box_w // 2 - hint.get_width() // 2,
                        box_y + 50))

    hint2 = hint_font.render("to see live weather", True, DIM_COLOR)
    screen.blit(hint2, (box_x + box_w // 2 - hint2.get_width() // 2,
                         box_y + 72))


# Function to display weather for the first location (departure)
def weather(screen, latitude, longitude):
    # Fetch weather data
    weather_data = get_weather_data(latitude, longitude)

    # Set up font and positioning
    weather_font = get_font(24)
    label_font = get_font(32)

    # Box properties
    box_width, box_height = 240, 180

    # text to display
    departure_label = label_font.render("Pref. Ship:", True, BLACK)
    screen.blit(departure_label, (700, 310))

    departure_label = label_font.render("Parameters:", True, BLACK)
    screen.blit(departure_label, (680, 380))

    departure_label = label_font.render("Ship dim:", True, BLACK)
    screen.blit(departure_label, (680, 450))

    # Draw "Departure" label
    departure_label = label_font.render("Departure", True, BLACK)
    screen.blit(departure_label, (760, 510))

    # Draw the weather box with a grey border
    pygame.draw.rect(screen, BORDER_COLOR, (700 - 2, 550 - 2, box_width + 4, box_height + 4), border_radius=10)
    pygame.draw.rect(screen, BACKGROUND_COLOR, (700, 550, box_width, box_height), border_radius=10)

    # Render weather data
    if "error" not in weather_data:
        weather_text = [
            f"Temperature: {weather_data['temperature']}",
            f"Feels Like: {weather_data['feels_like']}",
            f"Humidity: {weather_data['humidity']}",
            f"Wind Speed: {weather_data['wind_speed']}",
            f"Description: {weather_data['description'].split()[0]}"
        ]
    else:
        weather_text = [weather_data["error"]]

    # Display weather information
    for i, text in enumerate(weather_text):
        label = weather_font.render(text, True, TEXT_COLOR)
        screen.blit(label, (700 + 10, 550 + 20 + (i * 30)))  # Adjust line spacing


# Function to display weather for the second location (destination)
def weatherTwo(screen, latitude, longitude):
    # Fetch weather data
    weather_data = get_weather_data(latitude, longitude)

    # Set up font and positioning
    weather_font = get_font(24)
    label_font = get_font(32)
    x_position = 970  # Shift right by 240 pixels
    y_position = 550  # Adjust Y position for quadrant

    # Box properties
    box_width, box_height = 240, 180

    # Draw "Destination" label
    destination_label = label_font.render("Destination", True, BLACK)
    screen.blit(destination_label, (x_position + (box_width // 2 - destination_label.get_width() // 2), y_position - 40))

    # Draw the weather box with a grey border
    pygame.draw.rect(screen, BORDER_COLOR, (x_position - 2, y_position - 2, box_width + 4, box_height + 4), border_radius=10)
    pygame.draw.rect(screen, BACKGROUND_COLOR, (x_position, y_position, box_width, box_height), border_radius=10)

    # Render weather data
    if "error" not in weather_data:
        weather_text = [
            f"Temperature: {weather_data['temperature']}",
            f"Feels Like: {weather_data['feels_like']}",
            f"Humidity: {weather_data['humidity']}",
            f"Wind Speed: {weather_data['wind_speed']}",
            f"Description: {weather_data['description']}"
        ]
    else:
        weather_text = [weather_data["error"]]

    # Display weather information
    for i, text in enumerate(weather_text):
        label = weather_font.render(text, True, TEXT_COLOR)
        screen.blit(label, (x_position + 10, y_position + 20 + (i * 30)))  # Adjust line spacing
