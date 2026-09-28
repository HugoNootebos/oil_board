"""Where on the map a country's pagoda/torii sprite goes: the spot inside
the country with the most free land around it -- away from its coast and
borders, its troop circle (and the asset icons under it) and the
connection lines drawn through it. Worked out once, in map coordinates,
since none of those ever move.
"""

import numpy as np
from matplotlib.path import Path

# Obstacle sizes in map units, from their on-screen size at the default
# zoom (the circle, icons and lines keep a fixed screen size).
DEFAULT_ZOOM = 1.21
CIRCLE_RADIUS = 16 / DEFAULT_ZOOM            # troop circle + a little margin
LINE_HALF_WIDTH = 4 / DEFAULT_ZOOM           # connection line (5px) + margin
ASSET_BOX = (-40 / DEFAULT_ZOOM, 25 / DEFAULT_ZOOM,   # x0, y0, x1, y1 around the
             60 / DEFAULT_ZOOM, 62 / DEFAULT_ZOOM)    # centre (see draw_assets)
GRID_STEP = 0.5
MAX_HALF_SIZE = 12.0   # biggest sprite: 24 map units across
MIN_HALF_SIZE = 4.0
# Below this much room on land (a thin island chain like Japan) the sprite
# may overhang the coast instead, at this half size.
MIN_LAND_HALF_SIZE = 7.0
OVERHANG_HALF_SIZE = 9.0


def _segment_distances(px, py, a, b):
    """Distance from every point (px, py) to the segment a-b."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return np.hypot(px - ax, py - ay)
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / length2, 0, 1)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _connection_segments(country, countries, connections):
    """The connection lines as drawn through `country`, as map segments.
    The two links that wrap around the map edge are drawn as horizontal
    lines to the edge instead (see Connection.draw)."""
    center = (country.mass_center.x, country.mass_center.y)
    segments = []
    for connection in connections:
        if country.name not in connection:
            continue
        other = next(n for n in connection.connection if n != country.name)
        other_center = (countries[other].mass_center.x, countries[other].mass_center.y)
        wraps = {"Alaska", "Siberië"}.issubset(connection.connection) or \
            {"Japan", "Pearl Harbor"}.issubset(connection.connection)
        if wraps:
            # The eastern one runs off the right edge, the western one the left.
            far_x = center[0] + (2000 if center[0] > other_center[0] else -2000)
            segments.append((center, (far_x, center[1])))
        else:
            segments.append((center, other_center))
    return segments


def find_spot(country, countries, connections):
    """(x, y, half_size) in map units: centre and half the width of the
    biggest square sprite that fits in open land in `country`."""
    rings = [[(p.x, p.y) for p in ring] for ring in country.polygon]
    xs = np.concatenate([[p[0] for p in ring] for ring in rings])
    ys = np.concatenate([[p[1] for p in ring] for ring in rings])
    gx, gy = np.meshgrid(np.arange(xs.min(), xs.max(), GRID_STEP), np.arange(ys.min(), ys.max(), GRID_STEP))
    px, py = gx.ravel(), gy.ravel()

    inside = np.zeros(px.shape, dtype=bool)
    for ring in rings:
        inside |= Path(ring).contains_points(np.column_stack([px, py]))
    px, py = px[inside], py[inside]
    if len(px) == 0:
        return country.mass_center.x, country.mass_center.y, MIN_HALF_SIZE

    # Room around each point: the nearest of every obstacle. The own
    # outline (coast and borders) is kept apart, see the overhang below.
    coast = np.full(px.shape, np.inf)
    for ring in rings:
        for a, b in zip(ring, ring[1:] + ring[:1]):
            coast = np.minimum(coast, _segment_distances(px, py, a, b))
    room = np.full(px.shape, np.inf)
    cx, cy = country.mass_center.x, country.mass_center.y
    room = np.minimum(room, np.hypot(px - cx, py - cy) - CIRCLE_RADIUS)
    x0, y0, x1, y1 = ASSET_BOX
    box_dx = np.maximum(np.maximum(cx + x0 - px, px - (cx + x1)), 0)
    box_dy = np.maximum(np.maximum(cy + y0 - py, py - (cy + y1)), 0)
    room = np.minimum(room, np.hypot(box_dx, box_dy))
    for a, b in _connection_segments(country, countries, connections):
        room = np.minimum(room, _segment_distances(px, py, a, b) - LINE_HALF_WIDTH)

    on_land = np.minimum(room, coast)
    best = int(np.argmax(on_land))
    # A square's corners reach further than its sides: keep them in too.
    half = on_land[best] / 1.2
    if half >= MIN_LAND_HALF_SIZE:
        return float(px[best]), float(py[best]), float(min(half, MAX_HALF_SIZE))

    # Too thin to fit on land: centred on land but allowed over the sea --
    # still clear of the circle, lines and every other country -- on the
    # widest bit of land among the spots with enough room.
    lo_x, hi_x = xs.min() - 30, xs.max() + 30
    lo_y, hi_y = ys.min() - 30, ys.max() + 30
    for other in countries.values():
        if other is country:
            continue
        for ring in other.polygon:
            pts = [(p.x, p.y) for p in ring]
            if not any(lo_x <= x <= hi_x and lo_y <= y <= hi_y for x, y in pts):
                continue
            for a, b in zip(pts, pts[1:] + pts[:1]):
                room = np.minimum(room, _segment_distances(px, py, a, b))
    fits = np.minimum(room / 1.2, OVERHANG_HALF_SIZE)
    best = int(np.argmax(fits * 1000 + coast))
    return float(px[best]), float(py[best]), float(max(fits[best], MIN_HALF_SIZE))
