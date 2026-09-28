"""Fixed player colors for a plain N-player game (as opposed to "de Neven",
which picks its own three from Player's default random palette).

Shared by menu.py (to tint each name box while it's being typed into) and
engine.py (to actually assign the colors to the players), so the preview a
player sees while entering their name always matches what they get in-game.
"""

COUNT_MODE_COLORS = [
    (60, 110, 230),   # blue
    (40, 160, 70),    # green
    (210, 40, 40),    # red
    (230, 200, 40),   # yellow -- see YELLOW below
    (150, 60, 200),   # purple
    (230, 140, 40),   # orange
]


def light_tint(color, amount=0.65):
    """`color` blended `amount` of the way toward white -- a pale shade
    that still reads as that color, with dark text staying legible on it."""
    return tuple(int(c + (255 - c) * amount) for c in color)


YELLOW = (230, 200, 40)


def name_text_color(color):
    """Text color for a player's name drawn on a block of their own color:
    black on the yellow player (white is unreadable there), white otherwise."""
    return (0, 0, 0) if tuple(int(c) for c in color) == YELLOW else (255, 255, 255)
