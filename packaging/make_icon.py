"""
Draws the placeholder app icon: packaging/icon.png (1024x1024, the app's
icon; build_mac.sh and the Windows build turn it into .icns/.ico) and
images/icon.png (256x256, the window's icon, menu.ICON_IMAGE).

To use your own icon instead: put a 1024x1024 PNG at packaging/icon.png and
a 256x256 copy at images/icon.png, and don't run this.

    python3 packaging/make_icon.py
"""
import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame as pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCALE = 2  # drawn at twice the size, then scaled down: smooth edges


def draw(size=1024):
    pg.init()
    s = size * SCALE
    canvas = pg.Surface((s, s), pg.SRCALPHA)
    # A rounded square with a margin, like the other icons in the Dock.
    margin = s * 100 // 1024
    tile = pg.Rect(margin, margin, s - 2 * margin, s - 2 * margin)
    pg.draw.rect(canvas, (30, 30, 40), tile, border_radius=s * 185 // 1024)
    pg.draw.rect(canvas, (255, 200, 40), tile, width=s * 14 // 1024, border_radius=s * 185 // 1024)

    # The oil drop: point on top, round at the bottom.
    cx, top, bottom = s // 2, s * 190 // 1024, s * 625 // 1024
    half_height, half_width = (bottom - top) / 2, s * 175 / 1024
    middle = top + half_height
    points = []
    for i in range(240):
        a = 2 * math.pi * i / 240
        points.append((cx + half_width * math.sin(a) * math.sin(a / 2) ** 1.2,
                       middle - half_height * math.cos(a)))
    pg.draw.polygon(canvas, (10, 10, 12), points)
    pg.draw.polygon(canvas, (255, 200, 40), points, width=s * 12 // 1024)
    # A highlight on the drop.
    shine = pg.Rect(0, 0, s * 60 // 1024, s * 120 // 1024)
    shine.center = (cx - s * 75 // 1024, middle + s * 70 // 1024)
    pg.draw.ellipse(canvas, (90, 90, 100), shine)

    font = pg.font.Font(os.path.join(ROOT, "fonts", "Inter-Bold.ttf"), s * 210 // 1024)
    text = font.render("OIL", True, (255, 255, 255))
    canvas.blit(text, text.get_rect(center=(cx, s * 765 // 1024)))
    return pg.transform.smoothscale(canvas, (size, size))


if __name__ == "__main__":
    icon = draw()
    pg.image.save(icon, os.path.join(ROOT, "packaging", "icon.png"))
    pg.image.save(pg.transform.smoothscale(icon, (256, 256)), os.path.join(ROOT, "images", "icon.png"))
    print("packaging/icon.png, images/icon.png")
