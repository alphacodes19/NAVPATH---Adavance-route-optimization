import pygame

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
new_input_boxes_position = [(900, 280), (1025, 280), (1150, 280)]  # New input boxes below buttons
horizontal_buttons_position = [(900, 350), (1025, 350), (1150, 350)]  # New horizontal buttons
ship_dim_button_pos = [(900,420),(1025,420),(1150,420),(1275,420)] #lbh dim
ship_dim = [(780, 440),(880, 440),(980, 440),(1080, 440)]
input_box_width = 50 * 1.8
input_box_height = 40 * 1.1
input_boxes = ["", "", "", ""]
new_input_boxes = [False, False, False]  # p and c buttons
horizontal_buttons = [False, False, False]  # Track state of horizontal buttons(speed,comfo,time)
active_box = None
active_box2 = None
button_values = ["", "", "", ""]


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
    font = pygame.font.Font(None, 36)
    label_font = pygame.font.Font(None, 28)
    labels = ["Departure X:", "Departure Y:", "Destination X:", "Destination Y:"]
    
    for i, pos in enumerate(input_boxes_position):
        label_text = label_font.render(labels[i], True, LABEL_COLOR)
        screen.blit(label_text, (pos[0] - 7, pos[1]))  # Adjusted label position
        pygame.draw.rect(screen, INPUT_BOX_COLOR, (pos[0] + 130, pos[1] - 10, input_box_width, input_box_height), 2)
        text = font.render(input_boxes[i], True, WHITE)
        screen.blit(text, (pos[0] + 135, pos[1] - 3))
        
def draw_dim_boxes(screen):
    font = pygame.font.Font(None, 36)
    label_font = pygame.font.Font(None, 28)
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


# Draw the new input boxes with labels
def draw_new_input_boxes(screen):
    label_font = pygame.font.Font(None, 28)
    new_labels = ["C", "P", "I"]
    horizontal_labels = ["Fuel", "Speed", "Comfort"]  # Labels for horizontal buttons
    
    # Custom colors for horizontal buttons
    horizontal_colors = [
        ((255, 165, 0), (255, 120, 0)),    # Brown gradient for Fuel
        ((0, 191, 255), (0, 150, 255)),   # Blue gradient for Speed
        ((255, 105, 180), (255, 20, 147))     # Purple gradient for Comfort
    ]
    
    # Draw C and P boxes (keeping original style)
    for i, pos in enumerate(new_input_boxes_position):
        color = GREEN if new_input_boxes[i] else RED
        box_rect = pygame.Rect(pos[0] - 67, pos[1] + 20, input_box_width - 5, input_box_height)
        pygame.draw.rect(screen, color, box_rect, border_radius=10)
        
        label_text = label_font.render(new_labels[i], True, WHITE)
        label_x = box_rect.centerx - label_text.get_width() // 2
        label_y = box_rect.centery - label_text.get_height() // 2
        screen.blit(label_text, (label_x, label_y))
    
    # Draw horizontal buttons with gradient and different shape
    for i, pos in enumerate(horizontal_buttons_position):
        # Determine button state color
        if horizontal_buttons[i]:
            color_top, color_bottom = horizontal_colors[i]
        else:
            # Desaturated version of the gradient when not active
            color_top = tuple(int(c * 0.5) for c in horizontal_colors[i][0])
            color_bottom = tuple(int(c * 0.5) for c in horizontal_colors[i][1])
        
        # Create a more interesting button shape (slightly skewed rectangle)
        box_rect = pygame.Rect(pos[0] - 67, pos[1] + 20, input_box_width - 5, input_box_height)
        
        # Create a surface for gradient
        gradient_surface = pygame.Surface(box_rect.size, pygame.SRCALPHA)
        for y in range(box_rect.height):
            blend_ratio = y / box_rect.height
            r = int(color_top[0] * (1 - blend_ratio) + color_bottom[0] * blend_ratio)
            g = int(color_top[1] * (1 - blend_ratio) + color_bottom[1] * blend_ratio)
            b = int(color_top[2] * (1 - blend_ratio) + color_bottom[2] * blend_ratio)
            pygame.draw.line(gradient_surface, (r, g, b), (0, y), (box_rect.width, y))
        
        # Draw skewed rectangle with rounded corners
        points = [
            (box_rect.left, box_rect.bottom),
            (box_rect.left + 10, box_rect.top),
            (box_rect.right - 10, box_rect.top),
            (box_rect.right, box_rect.bottom)
        ]
        
        # Create a surface to draw the polygon
        poly_surface = pygame.Surface(box_rect.size, pygame.SRCALPHA)
        pygame.draw.polygon(poly_surface, (0, 0, 0, 0), points)
        poly_surface.blit(gradient_surface, (0, 0))
        screen.blit(poly_surface, box_rect.topleft)
        
        # Add label
        label_text = label_font.render(horizontal_labels[i], True, WHITE)
        label_x = box_rect.centerx - label_text.get_width() // 2
        label_y = box_rect.centery - label_text.get_height() // 2
        screen.blit(label_text, (label_x, label_y))
        
        

        
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
    input_box_width = 100  # Width of each input box
    input_box_height = 40  # Height of each input box

    if event.type == pygame.MOUSEBUTTONDOWN:
        # Check if the mouse click is inside any input box
        mouse_x, mouse_y = event.pos
        for i, (box_x, box_y) in enumerate(input_box_positions):
            if box_x <= mouse_x <= box_x + input_box_width and box_y <= mouse_y <= box_y + input_box_height:
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
                # Add your logic here (e.g., submit or change focus)
                pass
            
            # Handle regular character input
            elif event.key != pygame.K_BACKSPACE:
                button_values[active_box2] += event.unicode



# Handle mouse click to select the active input box
def handle_mouse_click(event):
    global active_box,active_box2
    for i, pos in enumerate(input_boxes_position):
        if pygame.Rect(pos[0] + 130, pos[1] - 10, input_box_width, input_box_height).collidepoint(event.pos):
            active_box = i
            break
    
    for i, pos in enumerate(ship_dim):
        if pygame.Rect(pos[0] + 130, pos[1] - 10, input_box_width, input_box_height).collidepoint(event.pos):
            active_box2 = i
            print(button_values)
            break    

    # Check for clicks on the C and P and I boxes
    for i, pos in enumerate(new_input_boxes_position):
        if pygame.Rect(pos[0] - 67, pos[1] + 20, input_box_width - 5, input_box_height).collidepoint(event.pos):
            for j in range(len(new_input_boxes)):
                new_input_boxes[j] = False
            new_input_boxes[i] = True
            break
    
    # Check for clicks on horizontal buttons
    for i, pos in enumerate(horizontal_buttons_position):
        if pygame.Rect(pos[0] - 67, pos[1] + 20, input_box_width - 5, input_box_height).collidepoint(event.pos):
            for j in range(len(horizontal_buttons)):
                horizontal_buttons[j] = False
            horizontal_buttons[i] = True
            break

# Draw "Manual" / "Automatic" button
def draw_button(screen, show_input_boxes, is_clicked=False):
    # Widened from 220 to 260px, and the font size dropped slightly (36->30)
    # to comfortably fit "Type Coordinates" / "Click on Map" — the old
    # "Manual"/"Automatic" labels were shorter and fit at the old size, but
    # these fuller, clearer labels need a bit more room.
    button_rect = pygame.Rect(670, 200, 260, 60)

    # Shadow effect
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)

    # Button appearance
    if is_clicked:
        draw_gradient_button(screen, button_rect, CLICK_EFFECT_COLOR_TOP, CLICK_EFFECT_COLOR_BOTTOM)
    elif show_input_boxes:
        draw_gradient_button(screen, button_rect, AUTOMATIC_COLOR_TOP, AUTOMATIC_COLOR_BOTTOM)
    else:
        draw_gradient_button(screen, button_rect, MANUAL_COLOR_TOP, MANUAL_COLOR_BOTTOM)

    font = pygame.font.Font(None, 30)
    # Renamed from "Manual"/"Automatic" — that labeling was backwards from
    # what either state actually does (the "Manual" label was shown while
    # input boxes were hidden, i.e. while you select points by clicking).
    button_text = "Type Coordinates" if show_input_boxes else "Click on Map"
    button_text_rendered = font.render(button_text, True, BUTTON_TEXT_COLOR)
    screen.blit(button_text_rendered, (button_rect.centerx - button_text_rendered.get_width() // 2,
                                       button_rect.centery - button_text_rendered.get_height() // 2))
    return button_rect

# Draw "Start" button with modern and on-click effects
def draw_start_button(screen, is_clicked=False):
    button_rect = pygame.Rect(950, 200, 220, 60)

    # Shadow effect
    shadow_rect = button_rect.copy()
    shadow_rect.topleft = (shadow_rect.x + 3, shadow_rect.y + 3)
    pygame.draw.rect(screen, SHADOW_COLOR, shadow_rect, border_radius=8)

    # Button appearance
    if is_clicked:
        draw_gradient_button(screen, button_rect, CLICK_EFFECT_COLOR_TOP, CLICK_EFFECT_COLOR_BOTTOM)
    else:
        draw_gradient_button(screen, button_rect, (0, 150, 255), (0, 100, 200))

    # Button text
    font = pygame.font.Font(None, 36)
    text = font.render("Calculate", True, BUTTON_TEXT_COLOR)
    screen.blit(text, (button_rect.centerx - text.get_width() // 2,
                       button_rect.centery - text.get_height() // 2))
    return button_rect

# Placeholder for "Fuel Estimation" button
def draw_fuel_estimation_button(screen):
    pass

# Placeholder for "Image Analysis" button
def draw_image_analysis_button(screen):
    pass

# Placeholder for "Retrain Model" button
def draw_retrain_model_button(screen):
    pass

# Placeholder for "Path Coordinates" button
def draw_path_coordinates_button(screen):
    pass

