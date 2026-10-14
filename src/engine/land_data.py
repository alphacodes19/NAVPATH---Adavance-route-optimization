"""Canonical land-cell mask shared by the UI and routing engine.

The mask is derived from the same map and transparent foreground overlay used
by the application, but it is built with OpenCV/NumPy so engine modules never
need to import pygame.
"""

from __future__ import annotations

import cv2
import numpy as np

from src import config

MAP_WIDTH = 550
MAP_HEIGHT = 600
CELL_SIZE = 4


def _load_land_cells() -> set[tuple[int, int]]:
    """Build the land mask by compositing the foreground over the base map.

    The application displays both images at 550x600 pixels and samples the
    centre pixel of every 4x4 grid cell. INTER_NEAREST mirrors the unfiltered
    scaling used by pygame.transform.scale.
    """
    background = cv2.imread(config.INDIA_MAP_IMG, cv2.IMREAD_COLOR)
    if background is None:
        raise FileNotFoundError(
            f"Could not load base map image: {config.INDIA_MAP_IMG}"
        )

    foreground = cv2.imread(config.INDIA_FOREGROUND_IMG, cv2.IMREAD_UNCHANGED)
    if foreground is None:
        raise FileNotFoundError(
            f"Could not load land-overlay image: {config.INDIA_FOREGROUND_IMG}"
        )

    size = (MAP_WIDTH, MAP_HEIGHT)
    background = cv2.resize(background, size, interpolation=cv2.INTER_NEAREST)
    foreground = cv2.resize(foreground, size, interpolation=cv2.INTER_NEAREST)

    if foreground.ndim == 3 and foreground.shape[2] == 4:
        # OpenCV loads BGRA. Black detection is channel-order independent.
        alpha = foreground[:, :, 3:4].astype(np.uint16)
        foreground_rgb = foreground[:, :, :3].astype(np.uint16)
        background_rgb = background.astype(np.uint16)
        composite = (
            foreground_rgb * alpha + background_rgb * (255 - alpha)
        ) // 255
        composite = composite.astype(np.uint8)
    elif foreground.ndim == 3 and foreground.shape[2] == 3:
        composite = foreground
    else:
        raise ValueError(
            "Land-overlay image must have 3 colour channels or 3 colour "
            f"channels plus alpha; received shape {foreground.shape}."
        )

    # Pixel centre of each grid cell, consistent with main.py's former mask.
    sample = composite[CELL_SIZE // 2::CELL_SIZE, CELL_SIZE // 2::CELL_SIZE]
    black_mask = np.all(sample == 0, axis=2)
    ys, xs = np.nonzero(black_mask)
    return {(int(x), int(y)) for y, x in zip(ys, xs)}


# Immutable canonical set: callers can share it without accidentally mutating
# the land mask used by every route calculation.
LAND_CELLS = frozenset(_load_land_cells())
