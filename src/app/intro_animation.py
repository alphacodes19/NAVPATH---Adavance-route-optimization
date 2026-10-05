import pygame
import cv2
import time

def play_intro_animation(screen, intro_video_path, screen_width, screen_height):
    """
    Plays an intro animation video (MP4 file) before the main application starts.

    Args:
        screen (pygame.Surface): The Pygame display surface.
        intro_video_path (str): Path to the video file.
        screen_width (int): Width of the display.
        screen_height (int): Height of the display.
    """
    try:
        # Initialize Pygame
        pygame.init()

        # Open the video file using OpenCV
        cap = cv2.VideoCapture(intro_video_path)

        if not cap.isOpened():
            print("Error: Couldn't open video file.")
            return

        # Set up the frame rate (fps)
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Initialize time for accurate frame delay
        clock = pygame.time.Clock()

        while cap.isOpened():
            ret, frame = cap.read()

            if not ret:
                break  # End of video

            # Flip the frame horizontally to create the mirror effect (lateral inversion)
            frame = cv2.flip(frame, 1)  # 1 for horizontal flip

            # Apply 270-degree rotation (counter-clockwise)
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)  # Rotate the frame by 270 degrees

            # Convert frame from BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Convert frame to Pygame surface
            frame_surface = pygame.surfarray.make_surface(frame_rgb)

            # Resize the frame to fit the screen with higher quality resizing
            frame_surface = pygame.transform.smoothscale(frame_surface, (screen_width, screen_height))

            # Display the frame on the screen
            screen.blit(frame_surface, (0, 0))
            pygame.display.update()

            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    cap.release()
                    pygame.quit()
                    return

            # Delay to match video fps using Pygame clock for better accuracy
            clock.tick(100)

        # Release the video capture object after playing the video
        cap.release()

    except Exception as e:
        print(f"Error playing intro animation: {e}")
        time.sleep(5)  # Replace video with a 5-second delay if error occurs
