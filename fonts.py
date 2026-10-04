"""The game's font: Inter (fonts/Inter-*.ttf, SIL Open Font License)."""
import os

import pygame as pg

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Inter is wider and taller than the Times New Roman the layouts were made
# for, so sizes are scaled down to keep text in its boxes.
SIZE_SCALE = 0.82


def game_font(size, bold=False):
    """A pygame Font in Inter at (roughly) the size the old Times New Roman
    text had; falls back to a system font if the files are missing."""
    path = os.path.join(_DIR, "Inter-Bold.ttf" if bold else "Inter-Regular.ttf")
    if os.path.exists(path):
        return pg.font.Font(path, max(6, round(size * SIZE_SCALE)))
    return pg.font.SysFont("Times New Roman", size, bold=bold)
