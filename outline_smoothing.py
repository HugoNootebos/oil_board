"""Rounded country outlines for drawing.

Every outline is replaced by a curve through its original points (a cubic
Hermite / Catmull-Rom spline), with extra points interpolated along each
edge so long straight hand-drawn edges bend smoothly into their
neighbours.

Neighbouring countries share their border points, and both have to bend
that border the same way or thin gaps/overlaps would appear between them.
The curve of one edge only depends on its two end points and the tangent
at each: at an ordinary point the tangent comes from its two neighbours
along the outline, which are the same for every country containing the
point (just walked in the opposite direction, which gives the identical
curve). A point where that isn't true -- where three countries meet, or a
border meets the coast -- is a junction: it's kept as a sharp corner, with
each edge leaving it pointing straight at its other end.

Used for drawing only: hit-testing and country centres still come from the
original outlines (see Country.set_outline).
"""

import math
from collections import defaultdict

# Logical px of edge per interpolated point, and the most points added to
# a single edge (coastlines are already fine-grained and barely change).
STEP = 3.0
MAX_POINTS_PER_EDGE = 12


def _key(p):
    return (round(p[0], 3), round(p[1], 3))


def _junctions(rings):
    """Points whose neighbours along the outline differ between the rings
    containing them, or that a ring passes through more than once."""
    neighbours = {}
    junctions = set()
    for ring in rings:
        n = len(ring)
        seen = set()
        for i, p in enumerate(ring):
            k = _key(p)
            pair = frozenset((_key(ring[i - 1]), _key(ring[(i + 1) % n])))
            if k in seen or len(pair) < 2:
                junctions.add(k)
            seen.add(k)
            if k in neighbours and neighbours[k] != pair:
                junctions.add(k)
            neighbours.setdefault(k, pair)
    return junctions


def _dedupe(ring):
    """Drop consecutive repeated points (and a closing repeat)."""
    out = []
    for p in ring:
        if not out or _key(p) != _key(out[-1]):
            out.append(p)
    if len(out) > 1 and _key(out[0]) == _key(out[-1]):
        out.pop()
    return out


def _smooth_ring(ring, junctions):
    n = len(ring)
    if n < 3:
        return list(ring)

    def tangent(i, towards):
        """Tangent at ring[i] for the edge heading to ring[towards]."""
        p = ring[i]
        if _key(p) in junctions:
            q = ring[towards]
            return (q[0] - p[0], q[1] - p[1]) if towards == (i + 1) % n else (p[0] - q[0], p[1] - q[1])
        a, b = ring[i - 1], ring[(i + 1) % n]
        return ((b[0] - a[0]) * 0.5, (b[1] - a[1]) * 0.5)

    out = []
    for i in range(n):
        j = (i + 1) % n
        p0, p1 = ring[i], ring[j]
        m0 = tangent(i, j)
        m1 = tangent(j, i)
        out.append(p0)
        steps = min(MAX_POINTS_PER_EDGE, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / STEP))
        for s in range(1, steps + 1):
            t = s / (steps + 1)
            t2, t3 = t * t, t * t * t
            h00 = 2 * t3 - 3 * t2 + 1
            h10 = t3 - 2 * t2 + t
            h01 = -2 * t3 + 3 * t2
            h11 = t3 - t2
            out.append((
                h00 * p0[0] + h10 * m0[0] + h01 * p1[0] + h11 * m1[0],
                h00 * p0[1] + h10 * m0[1] + h01 * p1[1] + h11 * m1[1],
            ))
    return out


def smooth_outlines(outlines):
    """{country name: [ring, ...]} (rings of (x, y)) -> the same with every
    ring smoothed. Must be given every country at once, so shared borders
    are recognised."""
    cleaned = {name: [_dedupe(ring) for ring in rings] for name, rings in outlines.items()}
    junctions = _junctions([ring for rings in cleaned.values() for ring in rings])
    return {name: [_smooth_ring(ring, junctions) for ring in rings] for name, rings in cleaned.items()}
