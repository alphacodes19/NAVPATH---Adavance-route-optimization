import os
from pathlib import Path

import pygame

from src.data.ports import PORTS
from src.data.vessels import VESSELS
from src.engine.snapshot_heuristics import list_available_dates

# --- Font loading -----------------------------------------------------
# Roboto, loaded once per size and cached, instead of the scattered
# pygame.font.Font(None, size) bitmap-default calls used everywhere before.
_FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FONT_REGULAR = str(_FONT_DIR / "Roboto-Regular.ttf")
_FONT_BOLD = str(_FONT_DIR / "Roboto-Bold.ttf")

_font_cache = {}


def get_font(size: int, bold: bool = False) -> "pygame.font.Font":
    """
    Return a cached Roboto font at the given size.
    Falls back to pygame's default font if the TTF file is missing.
    """
    key = (size, bold)
    if key not in _font_cache:
        path = _FONT_BOLD if bold else _FONT_REGULAR
        try:
            _font_cache[key] = pygame.font.Font(path, size)
        except (FileNotFoundError, pygame.error):
            _font_cache[key] = pygame.font.Font(None, size)
    return _font_cache[key]


# Colors
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
INPUT_BOX_COLOR = (0, 0, 255)
LABEL_COLOR = (0, 0, 0)
MANUAL_COLOR_TOP = (255, 100, 100)
MANUAL_COLOR_BOTTOM = (200, 50, 50)
AUTOMATIC_COLOR_TOP = (100, 255, 100)
AUTOMATIC_COLOR_BOTTOM = (50, 200, 50)
BUTTON_TEXT_COLOR = WHITE
BUTTON_BORDER_COLOR = (200, 200, 200)
SHADOW_COLOR = (50, 50, 50)
CLICK_EFFECT_COLOR_TOP = (0, 80, 150)
CLICK_EFFECT_COLOR_BOTTOM = (0, 50, 100)

# Input box properties
input_boxes_position = [(670, 70), (670, 120), (910, 70), (910, 120)]
ship_dim_button_pos = [(900, 420), (1025, 420), (1150, 420), (1275, 420)]  # lbh dim
ship_dim = [(780, 440), (880, 440), (980, 440), (1080, 440)]
input_box_width = 50 * 1.8
input_box_height = 40 * 1.1
input_boxes = ["", "", "", ""]
new_input_boxes = [False, False, False]  # Cargo / Passenger / Custom
horizontal_buttons = [False, False, False]  # Fuel / Speed / Comfort sub-priority
active_box = None
active_box2 = None
button_values = ["", "", "", ""]

# Geometry for the primary mode buttons (Cargo/Passenger/Custom) and the
# Fuel/Speed/Comfort sub-priority buttons. Shared by draw_new_input_boxes()
# and handle_mouse_click() so they always agree on hit areas.
_MODE_BTN_W, _MODE_BTN_H = 110, 54
_MODE_START_X, _MODE_START_Y = 833, 300
_SUB_BTN_H = 36
_SUB_Y = _MODE_START_Y + 70

# --- Port selector (Phase 2B) ---------------------------------------------
# Two arrow-selectors sitting above the Departure/Destination coordinate
# columns (input_boxes_position below). Cycling to a port auto-fills the
# matching lon/lat input boxes; cycling back to "Manual" (-1) leaves
# whatever is already typed there alone, so manual entry still works.
port_selection = [-1, -1]  # [departure_index, destination_index] into PORTS; -1 = Manual

_PORT_SEL_X = [670, 910]   # aligned with the Departure / Destination input-box columns
_PORT_SEL_Y = 25
_PORT_ARROW_W = 30
_PORT_ARROW_H = 34
_PORT_NAME_W = 220

# --- Historical snapshot date selector (Phase 2C) --------------------------
# "a" drives the single Calculate route (2C-1/2C-2); "a" + "b" together
# drive the "Compare Dates" overlay (2C-3). Sits in the gap between the
# mode/sub-priority buttons (ends ~y406) and the stats panel (starts y550).
date_selection = -1    # index into list_available_dates(); -1 = Default (trained PKL, no override)
date_b_selection = -1  # second date, only used by the Compare Dates button

_DATE_SEL_X = {"a": 670, "b": 970}
_DATE_SEL_Y_TITLE = 409
_DATE_SEL_Y = 425
_DATE_SEL_H = 30
_DATE_ARROW_W = 30
_DATE_NAME_W = 220
_DATE_DIFF_BTN_RECT = pygame.Rect(670, 465, 580, 34)

# --- Vessel profile selector (Phase 2D-2) ----------------------------------
# One arrow-selector that auto-fills the existing L/B/H/Eff ship-dimension
# boxes (draw_dim_boxes() below) from src/data/vessels.py. Placed to the
# right of those boxes/the date-selector panel, in open screen space, since
# that whole 670-1230 column is already packed with the coordinate inputs,
# mode buttons, and date selectors.
vessel_selection = -1  # index into VESSELS; -1 = Manual (boxes left as typed)

_VESSEL_SEL_X = 1250
_VESSEL_SEL_Y_TITLE = 405
_VESSEL_SEL_Y = 420
_VESSEL_ARROW_W = 30
_VESSEL_SEL_H = 34
_VESSEL_NAME_W = 220


# Function to draw gradient-filled rounded rectangles
def draw_gradient_button(screen, rect, color_top, color_bottom, border_radius=12):
    gradient_surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    for y in range(rect.height):
        blend_ratio = y / rect.height
        r = int(color_top[0] * (1 - blend_ratio) + color_bottom[0] * blend_ratio)
        g = int(color_top[1] * (1 - blend_ratio) + color_bottom[1] * blend_ratio)
        b = int(color_top[2] * (1 - blend_ratio) + color_bottom[2] * blend_ratio)
        pygame.draw.line(gradient_surface, (r, g, b), (0, y), (rect.width, y))
    pygame.draw.rect(screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=border_radius)
    screen.blit(gradient_surface, rect.topleft)


# Draw the input boxes with labels
def draw_input_boxes(screen):
    font = get_font(36)
    label_font = get_font(28)
    labels = ["Departure Lon:", "Departure Lat:", "Destination Lon:", "Destination Lat:"]

    for i, pos in enumerate(input_boxes_position):
        label_text = label_font.render(labels[i], True, LABEL_COLOR)
        screen.blit(label_text, (pos[0] - 7, pos[1]))  # Adjusted label position
        # Offset widened from 130 -> 150 so "Destination Lon:" fits without clipping.
        pygame.draw.rect(screen, INPUT_BOX_COLOR,
                          (pos[0] + 150, pos[1] - 10, input_box_width, input_box_height), 2)
        text = font.render(input_boxes[i], True, WHITE)
        screen.blit(text, (pos[0] + 155, pos[1] - 3))


def _port_label(index: int) -> str:
    return "Manual" if index == -1 else PORTS[index]["name"]


def draw_port_selectors(screen):
    """
    Draw the Departure/Destination port arrow-selectors. Only meaningful
    while the coordinate input boxes are visible, same as draw_input_boxes().
    """
    font = get_font(22, bold=True)
    label_font = get_font(16)
    titles = ["Departure Port", "Destination Port"]

    for col, x in enumerate(_PORT_SEL_X):
        title_text = label_font.render(titles[col], True, (180, 180, 180))
        screen.blit(title_text, (x, _PORT_SEL_Y - 16))

        left_rect = pygame.Rect(x, _PORT_SEL_Y, _PORT_ARROW_W, _PORT_ARROW_H)
        name_rect = pygame.Rect(x + _PORT_ARROW_W, _PORT_SEL_Y, _PORT_NAME_W, _PORT_ARROW_H)
        right_rect = pygame.Rect(x + _PORT_ARROW_W + _PORT_NAME_W, _PORT_SEL_Y,
                                  _PORT_ARROW_W, _PORT_ARROW_H)

        pygame.draw.rect(screen, (40, 60, 90), name_rect, border_radius=4)
        pygame.draw.rect(screen, BUTTON_BORDER_COLOR, name_rect, width=1, border_radius=4)
        for rect in (left_rect, right_rect):
            pygame.draw.rect(screen, (60, 90, 130), rect, border_radius=4)

        pygame.draw.polygon(screen, WHITE, [
            (left_rect.centerx + 5, left_rect.centery - 8),
            (left_rect.centerx + 5, left_rect.centery + 8),
            (left_rect.centerx - 6, left_rect.centery),
        ])
        pygame.draw.polygon(screen, WHITE, [
            (right_rect.centerx - 5, right_rect.centery - 8),
            (right_rect.centerx - 5, right_rect.centery + 8),
            (right_rect.centerx + 6, right_rect.centery),
        ])

        label = font.render(_port_label(port_selection[col]), True, WHITE)
        screen.blit(label, (name_rect.centerx - label.get_width() // 2,
                             name_rect.centery - label.get_height() // 2))


def _apply_port_selection(col: int):
    """Auto-fill the lon/lat input boxes for column 0 (departure) or 1 (destination)."""
    idx = port_selection[col]
    if idx == -1:
        return  # Manual — leave whatever is already typed there
    port = PORTS[idx]
    base = col * 2  # departure -> input_boxes[0:2], destination -> input_boxes[2:4]
    input_boxes[base] = str(port["lon"])
    input_boxes[base + 1] = str(port["lat"])


def handle_port_selector_click(event) -> bool:
    """
    Handle a MOUSEBUTTONDOWN on the port-selector arrows.
    Returns True if the click was consumed by an arrow.
    """
    for col, x in enumerate(_PORT_SEL_X):
        left_rect = pygame.Rect(x, _PORT_SEL_Y, _PORT_ARROW_W, _PORT_ARROW_H)
        right_rect = pygame.Rect(x + _PORT_ARROW_W + _PORT_NAME_W, _PORT_SEL_Y,
                                  _PORT_ARROW_W, _PORT_ARROW_H)

        if left_rect.collidepoint(event.pos):
            port_selection[col] = port_selection[col] - 1 if port_selection[col] > -1 else len(PORTS) - 1
            _apply_port_selection(col)
            return True
        if right_rect.collidepoint(event.pos):
            port_selection[col] = port_selection[col] + 1 if port_selection[col] < len(PORTS) - 1 else -1
            _apply_port_selection(col)
            return True
    return False


def _date_label(index: int) -> str:
    dates = list_available_dates()
    if index == -1 or index >= len(dates):
        return "Default (PKL)"
    return dates[index]


def draw_date_selectors(screen):
    """
    Draw the "Historical Date" selector (affects the single Calculate
    route — Phase 2C-1/2C-2), the "Compare With" selector, and the
    Compare Dates button that runs both through router.run_date_comparison()
    (Phase 2C-3). Always visible, independent of show_input_boxes — the
    date choice applies whether start/end came from the map or typed
    coordinates. Returns the Compare Dates button rect for click hit-testing.
    """
    font = get_font(18, bold=True)
    title_font = get_font(15)
    titles = {"a": "Historical Date (used by Calculate)", "b": "Compare With"}
    selections = {"a": date_selection, "b": date_b_selection}

    for key, x in _DATE_SEL_X.items():
        title_text = title_font.render(titles[key], True, (180, 180, 180))
        screen.blit(title_text, (x, _DATE_SEL_Y_TITLE))

        left_rect = pygame.Rect(x, _DATE_SEL_Y, _DATE_ARROW_W, _DATE_SEL_H)
        name_rect = pygame.Rect(x + _DATE_ARROW_W, _DATE_SEL_Y, _DATE_NAME_W, _DATE_SEL_H)
        right_rect = pygame.Rect(x + _DATE_ARROW_W + _DATE_NAME_W, _DATE_SEL_Y,
                                  _DATE_ARROW_W, _DATE_SEL_H)

        pygame.draw.rect(screen, (40, 60, 90), name_rect, border_radius=4)
        pygame.draw.rect(screen, BUTTON_BORDER_COLOR, name_rect, width=1, border_radius=4)
        for rect in (left_rect, right_rect):
            pygame.draw.rect(screen, (60, 90, 130), rect, border_radius=4)

        pygame.draw.polygon(screen, WHITE, [
            (left_rect.centerx + 4, left_rect.centery - 7),
            (left_rect.centerx + 4, left_rect.centery + 7),
            (left_rect.centerx - 5, left_rect.centery),
        ])
        pygame.draw.polygon(screen, WHITE, [
            (right_rect.centerx - 4, right_rect.centery - 7),
            (right_rect.centerx - 4, right_rect.centery + 7),
            (right_rect.centerx + 5, right_rect.centery),
        ])

        label = font.render(_date_label(selections[key]), True, WHITE)
        screen.blit(label, (name_rect.centerx - label.get_width() // 2,
                             name_rect.centery - label.get_height() // 2))

    draw_gradient_button(screen, _DATE_DIFF_BTN_RECT, (90, 70, 160), (60, 45, 120))
    diff_font = get_font(22)
    diff_text = diff_font.render("Compare Dates (A vs B)", True, BUTTON_TEXT_COLOR)
    screen.blit(diff_text, (_DATE_DIFF_BTN_RECT.centerx - diff_text.get_width() // 2,
                             _DATE_DIFF_BTN_RECT.centery - diff_text.get_height() // 2))
    return _DATE_DIFF_BTN_RECT


def handle_date_selector_click(event) -> bool:
    """
    Handle a MOUSEBUTTONDOWN on the date-selector arrows (not the Compare
    Dates button itself — main.py checks that one via the rect
    draw_date_selectors() returns, same convention as the other buttons).
    Returns True if the click was consumed by an arrow.
    """
    global date_selection, date_b_selection
    n = len(list_available_dates())

    for key, x in _DATE_SEL_X.items():
        left_rect = pygame.Rect(x, _DATE_SEL_Y, _DATE_ARROW_W, _DATE_SEL_H)
        right_rect = pygame.Rect(x + _DATE_ARROW_W + _DATE_NAME_W, _DATE_SEL_Y,
                                  _DATE_ARROW_W, _DATE_SEL_H)

        current = date_selection if key == "a" else date_b_selection
        if left_rect.collidepoint(event.pos):
            new_val = (current - 1) if current > -1 else (n - 1 if n else -1)
        elif right_rect.collidepoint(event.pos):
            new_val = (current + 1) if current < n - 1 else -1
        else:
            continue

        if key == "a":
            date_selection = new_val
        else:
            date_b_selection = new_val
        return True
    return False


def draw_dim_boxes(screen):
    font = get_font(36)
    label_font = get_font(28)
    labels = ["L:", "B:", "H:", "Eff:"]
    horizontal_spacing = 100  # Adjust the spacing between boxes
    start_x = 790  # Starting X position for the first box
    start_y_label = 420  # Y position for labels
    start_y_box = 440  # Y position for input boxes

    for i, label in enumerate(labels):
        # Calculate positions based on spacing
        label_x = start_x + i * horizontal_spacing
        box_x = label_x - 10
        box_y = start_y_box

        # Draw label
        label_text = label_font.render(label, True, LABEL_COLOR)
        screen.blit(label_text, (label_x, start_y_label))

        # Draw input box
        pygame.draw.rect(screen, INPUT_BOX_COLOR, (box_x, box_y, input_box_width, input_box_height), 4)

        # Draw text inside the input box
        text = font.render(button_values[i], True, WHITE)
        text_x = box_x + (input_box_width - text.get_width()) // 2
        text_y = box_y + (input_box_height - text.get_height()) // 2
        screen.blit(text, (text_x, text_y))


def _vessel_label(index: int) -> str:
    return "Manual" if index == -1 else VESSELS[index]["name"]


def draw_vessel_selector(screen):
    """
    Draw the "Vessel Profile" arrow-selector. Always visible, same as
    draw_dim_boxes() — not gated behind show_input_boxes.
    """
    font = get_font(20, bold=True)
    title_font = get_font(16)

    title_text = title_font.render("Vessel Profile", True, (180, 180, 180))
    screen.blit(title_text, (_VESSEL_SEL_X, _VESSEL_SEL_Y_TITLE))

    left_rect = pygame.Rect(_VESSEL_SEL_X, _VESSEL_SEL_Y, _VESSEL_ARROW_W, _VESSEL_SEL_H)
    name_rect = pygame.Rect(_VESSEL_SEL_X + _VESSEL_ARROW_W, _VESSEL_SEL_Y,
                             _VESSEL_NAME_W, _VESSEL_SEL_H)
    right_rect = pygame.Rect(_VESSEL_SEL_X + _VESSEL_ARROW_W + _VESSEL_NAME_W, _VESSEL_SEL_Y,
                              _VESSEL_ARROW_W, _VESSEL_SEL_H)

    pygame.draw.rect(screen, (40, 60, 90), name_rect, border_radius=4)
    pygame.draw.rect(screen, BUTTON_BORDER_COLOR, name_rect, width=1, border_radius=4)
    for rect in (left_rect, right_rect):
        pygame.draw.rect(screen, (60, 90, 130), rect, border_radius=4)

    pygame.draw.polygon(screen, WHITE, [
        (left_rect.centerx + 4, left_rect.centery - 7),
        (left_rect.centerx + 4, left_rect.centery + 7),
        (left_rect.centerx - 5, left_rect.centery),
    ])
    pygame.draw.polygon(screen, WHITE, [
        (right_rect.centerx - 4, right_rect.centery - 7),
        (right_rect.centerx - 4, right_rect.centery + 7),
        (right_rect.centerx + 5, right_rect.centery),
    ])

    label = font.render(_vessel_label(vessel_selection), True, WHITE)
    screen.blit(label, (name_rect.centerx - label.get_width() // 2,
                         name_rect.centery - label.get_height() // 2))


def _apply_vessel_selection():
    """
    Auto-fill the L/B/H/Eff boxes (button_values) from the selected
    vessel. "H" is filled with the vessel's draft — main.py already treats
    that box as a draft proxy (get_min_depth_for_vessel()), and the new
    hard-forbidden-cell filtering (router.get_neighbors(), Phase 2D-3)
    reads the same box via main.py's get_vessel_draft().
    """
    if vessel_selection == -1:
        return  # Manual — leave whatever is already typed there
    vessel = VESSELS[vessel_selection]
    button_values[0] = str(vessel["L"])
    button_values[1] = str(vessel["B"])
    button_values[2] = str(vessel["draft"])
    button_values[3] = str(vessel["eff"])


def handle_vessel_selector_click(event) -> bool:
    """
    Handle a MOUSEBUTTONDOWN on the vessel-selector arrows.
    Returns True if the click was consumed by an arrow.
    """
    global vessel_selection

    left_rect = pygame.Rect(_VESSEL_SEL_X, _VESSEL_SEL_Y, _VESSEL_ARROW_W, _VESSEL_SEL_H)
    right_rect = pygame.Rect(_VESSEL_SEL_X + _VESSEL_ARROW_W + _VESSEL_NAME_W, _VESSEL_SEL_Y,
                              _VESSEL_ARROW_W, _VESSEL_SEL_H)

    if left_rect.collidepoint(event.pos):
        vessel_selection = vessel_selection - 1 if vessel_selection > -1 else len(VESSELS) - 1
        _apply_vessel_selection()
        return True
    if right_rect.collidepoint(event.pos):
        vessel_selection = vessel_selection + 1 if vessel_selection < len(VESSELS) - 1 else -1
        _apply_vessel_selection()
        return True
    return False


def draw_new_input_boxes(screen):
    """
    Draw the three routing mode buttons (Cargo / Passenger / Custom)
    and the three sub-priority buttons (Fuel / Speed / Comfort).
    """
    font_label = get_font(22, bold=True)
    font_desc = get_font(18)
    font_sub = get_font(20, bold=True)

    # --- Primary mode buttons ---
    mode_labels = ["Cargo", "Passenger", "Custom"]
    mode_descs = ["Max load · fast", "Comfort · safety", "Set priorities"]
    mode_colors_on = [(50, 180, 80), (60, 140, 220), (200, 160, 40)]
    mode_colors_off = [(30, 80, 40), (30, 60, 110), (100, 75, 20)]

    for i in range(3):
        bx = _MODE_START_X + i * 130
        by = _MODE_START_Y
        color = mode_colors_on[i] if new_input_boxes[i] else mode_colors_off[i]
        box_rect = pygame.Rect(bx, by, _MODE_BTN_W, _MODE_BTN_H)

        pygame.draw.rect(screen, color, box_rect, border_radius=8)
        if new_input_boxes[i]:
            pygame.draw.rect(screen, (255, 255, 255), box_rect, 2, border_radius=8)

        lbl = font_label.render(mode_labels[i], True, (255, 255, 255))
        screen.blit(lbl, (box_rect.centerx - lbl.get_width() // 2, by + 8))
        desc = font_desc.render(mode_descs[i], True, (200, 200, 200))
        screen.blit(desc, (box_rect.centerx - desc.get_width() // 2, by + 30))

    # --- Sub-priority buttons (Fuel / Speed / Comfort) ---
    sub_labels = ["Fuel", "Speed", "Comfort"]
    sub_colors_on = [(220, 140, 30), (40, 160, 240), (220, 80, 180)]
    sub_colors_off = [(90, 55, 10), (15, 65, 100), (90, 30, 70)]

    for i in range(3):
        bx = _MODE_START_X + i * 130
        color = sub_colors_on[i] if horizontal_buttons[i] else sub_colors_off[i]
        box_rect = pygame.Rect(bx, _SUB_Y, _MODE_BTN_W, _SUB_BTN_H)

        pygame.draw.rect(screen, color, box_rect, border_radius=6)
        if horizontal_buttons[i]:
            pygame.draw.rect(screen, (255, 255, 255), box_rect, 2, border_radius=6)

        lbl = font_sub.render(sub_labels[i], True, (255, 255, 255))
        screen.blit(lbl, (box_rect.centerx - lbl.get_width() // 2, _SUB_Y + 8))

    # Label above sub-buttons
    note = get_font(19).render(
        "Sub-priority (active when Custom is selected):",
        True, (150, 150, 170))
    screen.blit(note, (_MODE_START_X, _SUB_Y - 18))


# Handle keyboard input for the active box
def handle_input(event):
    global active_box
    if active_box is not None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                input_boxes[active_box] = input_boxes[active_box][:-1]
            elif event.key == pygame.K_RETURN:
                pass
            else:
                input_boxes[active_box] += event.unicode


def handle_dir_input(event):
    global active_box2

    # Define the dimensions and positions of the input boxes
    input_box_positions = [
        (780, 440),  # Box 1 position
        (880, 440),  # Box 2 position
        (980, 440),  # Box 3 position
        (1080, 440)  # Box 4 position
    ]
    dim_box_width = 100  # Width of each input box
    dim_box_height = 40  # Height of each input box

    if event.type == pygame.MOUSEBUTTONDOWN:
        # Check if the mouse click is inside any input box
        mouse_x, mouse_y = event.pos
        for i, (box_x, box_y) in enumerate(input_box_positions):
            if box_x <= mouse_x <= box_x + dim_box_width and box_y <= mouse_y <= box_y + dim_box_height:
                active_box2 = i  # Set the active box to the clicked one
                break
        else:
            active_box2 = None  # Deselect if clicking outside any box

    # Process key inputs only if an input box is active
    if active_box2 is not None:
        if event.type == pygame.KEYDOWN:
            # Handle backspace key
            if event.key == pygame.K_BACKSPACE:
                if len(button_values[active_box2]) > 0:
                    button_values[active_box2] = button_values[active_box2][:-1]

            # Handle enter key (add logic for submission or focus change)
            elif event.key == pygame.K_RETURN:
                pass

            # Handle regular character input
            elif event.key != pygame.K_BACKSPACE:
                button_values[active_box2] += event.unicode


# Handle mouse click to select the active input box / mode button
def handle_mouse_click(event):
    global active_box, active_box2

    # Coordinate input boxes
    for i, pos in enumerate(input_boxes_position):
        if pygame.Rect(pos[0] + 150, pos[1] - 10,
                        input_box_width, input_box_height).collidepoint(event.pos):
            active_box = i
            break

    # Ship dimension boxes
    for i, pos in enumerate(ship_dim):
        if pygame.Rect(pos[0] + 130, pos[1] - 10,
                        input_box_width, input_box_height).collidepoint(event.pos):
            active_box2 = i
            break

    # Primary mode buttons (Cargo / Passenger / Custom)
    for i in range(3):
        bx = _MODE_START_X + i * 130
        if pygame.Rect(bx, _MODE_START_Y, _MODE_BTN_W, _MODE_BTN_H).collidepoint(event.pos):
            for j in range(len(new_input_boxes)):
                new_input_boxes[j] = False
            new_input_boxes[i] = True
            break

    # Sub-priority buttons (Fuel / Speed / Comfort)
    for i in range(3):
        bx = _MODE_START_X + i * 130
        if pygame.Rect(bx, _SUB_Y, _MODE_BTN_W, _SUB_BTN_H).collidepoint(event.pos):
            for j in range(len(horizontal_buttons)):
                horizontal_buttons[j] = False
            horizontal_buttons[i] = True
            break


# Draw "Click on Map" / "Type Coordinates" button
def draw_button(screen, show_input_boxes, is_clicked=False):
    button_rect = pygame.Rect(670, 200, 260, 60)

    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)

    if is_clicked:
        draw_gradient_button(screen, button_rect, CLICK_EFFECT_COLOR_TOP, CLICK_EFFECT_COLOR_BOTTOM)
    elif show_input_boxes:
        draw_gradient_button(screen, button_rect, AUTOMATIC_COLOR_TOP, AUTOMATIC_COLOR_BOTTOM)
    else:
        draw_gradient_button(screen, button_rect, MANUAL_COLOR_TOP, MANUAL_COLOR_BOTTOM)

    font = get_font(30)
    button_text = "Type Coordinates" if show_input_boxes else "Click on Map"
    button_text_rendered = font.render(button_text, True, BUTTON_TEXT_COLOR)
    screen.blit(button_text_rendered, (button_rect.centerx - button_text_rendered.get_width() // 2,
                                        button_rect.centery - button_text_rendered.get_height() // 2))
    return button_rect


# Draw "Start"/"Calculate" button with modern and on-click effects
def draw_start_button(screen, is_clicked=False):
    button_rect = pygame.Rect(950, 200, 220, 60)

    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)

    if is_clicked:
        draw_gradient_button(screen, button_rect, CLICK_EFFECT_COLOR_TOP, CLICK_EFFECT_COLOR_BOTTOM)
    else:
        draw_gradient_button(screen, button_rect, (0, 150, 255), (0, 100, 200))

    font = get_font(36)
    text = font.render("Calculate", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect


def draw_reset_button(screen):
    button_rect = pygame.Rect(670, 270, 260, 45)
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)
    draw_gradient_button(screen, button_rect, (180, 60, 60), (140, 30, 30))
    font = get_font(28)
    text = font.render("Reset Route", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect


def draw_compare_routes_button(screen, is_active=False):
    """
    Trigger a 3-way (speed/fuel/safe) route comparison — see
    router.run_multi_route(). Sits beside Reset Route, below Calculate.
    """
    button_rect = pygame.Rect(940, 270, 230, 45)
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)
    if is_active:
        draw_gradient_button(screen, button_rect, (190, 110, 230), (140, 60, 180))
    else:
        draw_gradient_button(screen, button_rect, (140, 60, 180), (100, 30, 140))
    font = get_font(24)
    text = font.render("Compare Routes", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect


def draw_pareto_button(screen, is_active=False):
    """
    Trigger a Pareto sweep (speed <-> fuel trade-off, Phase 3B) —
    see router.run_pareto_sweep(). Sits below the vessel selector, in the
    same open column (x=1250+) to the right of the already-packed
    670-1230 control area.
    """
    button_rect = pygame.Rect(1250, 470, 230, 40)
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)
    if is_active:
        draw_gradient_button(screen, button_rect, (230, 200, 60), (180, 150, 20))
    else:
        draw_gradient_button(screen, button_rect, (120, 100, 20), (90, 70, 10))
    font = get_font(22)
    text = font.render("Pareto Sweep", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect


def draw_benchmark_button(screen, is_active=False):
    """
    Trigger an algorithm benchmark (Dijkstra vs Greedy vs A*, Phase 3C) —
    see src/engine/benchmark.py. Sits directly below the Pareto Sweep
    button, same open column.
    """
    button_rect = pygame.Rect(1250, 515, 230, 40)
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)
    if is_active:
        draw_gradient_button(screen, button_rect, (120, 200, 160), (70, 150, 110))
    else:
        draw_gradient_button(screen, button_rect, (40, 100, 80), (20, 70, 55))
    font = get_font(22)
    text = font.render("Algorithm Benchmark", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect


def draw_fuel_estimation_button(screen):
    """Toggle the fuel-estimation detail overlay (see src/app/route_panel.py)."""
    button_rect = pygame.Rect(670, 378, 560, 40)
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 2, shadow_rect.y + 2)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=6)
    draw_gradient_button(screen, button_rect, (180, 100, 20), (130, 65, 10))
    font = get_font(26)
    text = font.render("Fuel Estimation", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect


# Placeholder for "Image Analysis" button (not implemented)
def draw_image_analysis_button(screen):
    pass


# Placeholder for "Retrain Model" button (not implemented)
def draw_retrain_model_button(screen):
    pass


def draw_path_coordinates_button(screen):
    """Export the current route to CSV and GPX (see src/engine/exporter.py)."""
    button_rect = pygame.Rect(670, 330, 560, 40)  # below the mode buttons
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 2, shadow_rect.y + 2)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=6)
    draw_gradient_button(screen, button_rect, (40, 120, 80), (20, 80, 50))
    font = get_font(26)
    text = font.render("Export Route  (CSV + GPX)", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                        button_rect.centery - text.get_height() // 2))
    return button_rect