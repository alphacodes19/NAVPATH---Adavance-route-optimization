Download Roboto-Regular.ttf and Roboto-Bold.ttf from
https://fonts.google.com/specimen/Roboto and place them in this folder.

get_font() in src/app/ui_elements.py falls back to pygame's built-in
default font automatically if these files are absent, so the app runs
fine without them -- this just upgrades the look once you add them.
