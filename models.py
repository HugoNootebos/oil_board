import math
import zlib

import numpy as np
import pygame as pg
import sounds
from fonts import game_font
from pygame import gfxdraw
from matplotlib.path import Path
from player_colors import name_text_color, light_tint

# Countries whose conqueror has to drag a landmark onto them (from the
# settings menu) before ending their turn, and which sprite that is.
LANDMARKS = {"China": "pagoda", "Japan": "torii"}


def stable_hash(*names):
    """A hash that depends only on `names`: not on where the object sits in
    memory, nor on PYTHONHASHSEED. Sets of players, countries and
    connections iterate in hash order, and the bots break ties in that
    order, so with the default (address-based) hash the same game played
    twice came out differently."""
    return zlib.crc32("|".join(names).encode("utf-8"))


class Player:

    # Food never goes below 0: anything that would take it lower leaves it
    # at 0 (a shortfall at turn start is starvation, see ReinforcementPhase).
    @property
    def food(self):
        return self._food

    @food.setter
    def food(self, value):
        self._food = max(value, 0)

    def __init__(
            self,
            name,
            cards=None,
            food=45,
            wood=0,
            steel=0,
            nuclear=0,
            oil=0,
            color=None,
            troops=0,
            start_ship=True,
            is_bot=False,
    ):
        if cards is None:
            cards = list()
        self.name = name
        self.cards = cards
        self.food = food
        self.wood = wood
        self.steel = steel
        self.nuclear = nuclear
        self.oil = oil
        self.color = color
        self.troops = troops
        self.attack = 0
        self.subattack = 0
        # Their first ship bought in the shop is free (ShopPhase.ship_cost);
        # True until they've bought one.
        self.start_ship = start_ship
        # Movement phase (repositioning) is limited to one confirmed move
        # per turn; reset whenever the player re-enters that phase.
        self.repositioned_this_turn = False
        # Only one country may be developed per turn.
        self.developed_this_turn = False
        # Out of the game: no troops left on the board, never gets a turn.
        self.eliminated = False
        # Played by the computer (bot.py) instead of with the mouse.
        self.is_bot = is_bot
        # Its difficulty and style (bot.LEVELS / bot.PERSONALITIES).
        self.bot_level = "normal"
        self.bot_personality = "balanced"
        if self.color is None:
            self.color = 255 * np.random.rand(3)

    def __hash__(self):
        return stable_hash(self.name)


# Chance of each card type when one is drawn (the Joker, 3, is rare).
CARD_ODDS = (7 / 22, 7 / 22, 7 / 22, 1 / 22)


def random_card_type():
    """A card type (0-3) drawn with the odds in CARD_ODDS."""
    return int(np.random.choice(len(CARD_ODDS), p=CARD_ODDS))


class Kaertske:
    """A card in a player's hand. The card menu shows just the sprite on
    its panel with a soft white glow behind it; a card that isn't selected
    for trading is drawn in grey."""

    GLOW_MARGIN = 15
    _glows = {}
    _greys = {}

    def __init__(self, type, images, width=110, height=150):
        self.name_mapping = {
            0: 'Menneke',
            1: 'Paerd',
            2: 'Vliegtuig',
            3: 'Joker',
        }
        self.sprite_mapping = {
            0: images['spr_card0'],
            1: images['spr_card1'],
            2: images['spr_card2'],
            3: images.get('spr_joker', images['spr_nuke'])
        }
        self.name = self.name_mapping[type]
        self.type = type
        self.use = False
        self.width = width
        self.height = height
        self.pos = Position(0, 0)

    def rect(self):
        return pg.Rect(self.pos.x, self.pos.y, self.width, self.height)

    @classmethod
    def _glow(cls, w, h):
        """White radial glow, opaque-ish in the middle, fading to nothing
        at the edge of a w x h box."""
        if (w, h) not in cls._glows:
            surf = pg.Surface((w, h), pg.SRCALPHA)
            surf.fill((255, 255, 255, 0))
            x = (np.arange(w) - (w - 1) / 2) / (w / 2)
            y = (np.arange(h) - (h - 1) / 2) / (h / 2)
            d = np.sqrt(x[:, None] ** 2 + y[None, :] ** 2)
            alpha = pg.surfarray.pixels_alpha(surf)
            alpha[...] = (np.clip(1 - d, 0, 1) ** 1.5 * 230).astype(np.uint8)
            del alpha  # unlocks the surface
            cls._glows[(w, h)] = surf
        return cls._glows[(w, h)]

    @classmethod
    def _grey(cls, image):
        """Mid-grey copy of a sprite (keeps its alpha).
        (Not pg.transform.grayscale: in pygame-ce 2.5 it garbles alpha.)"""
        if image not in cls._greys:
            grey = image.copy()
            rgb = pg.surfarray.pixels3d(grey)
            rgb[...] = (rgb @ np.array([0.299, 0.587, 0.114]) * 0.45 + 110).astype(np.uint8)[..., None]
            del rgb
            cls._greys[image] = grey
        return cls._greys[image]

    def draw(self, view):
        rect = self.rect()
        m = self.GLOW_MARGIN
        view.screen.blit(self._glow(rect.w + 2 * m, rect.h + 2 * m), (rect.x - m, rect.y - m))
        image = self.sprite_mapping[self.type].image
        if not self.use:
            image = self._grey(image)
        sw, sh = image.get_size()
        view.screen.blit(image, (rect.x + (rect.w - sw) // 2, rect.y + (rect.h - sh) // 2))


class Country:

    def __init__(
            self,
            name,
            polygon,
            owner,
            food=0,
            wood=0,
            steel=0,
            nuclear=0,
            oil=0,
            troops=0,
            units=2,
            ships=0,
            planes=0,
            tanks=0,
            fort_lvl=0,
            radioactive=0,
            developed=False,
            dormant_owner=None,
            bombed_by=None,
            airport=False,
            landmark_owner=None,
            shade=0,
    ):
        self.raw_polygon = polygon
        # Transform python tuples to Position object:
        self.polygon = [
            [
                Position(point[0], point[1]) for point in pol
            ] for pol in polygon
        ]
        # Pass other variables to object
        self.name = name
        self.food = food
        self.wood = wood
        self.steel = steel
        self.nuclear = nuclear
        self.oil = oil
        self.owner = owner
        self.troops = troops
        self.units = units
        self.ships = ships
        self.planes = planes
        self.tanks = tanks
        self.fort_lvl = fort_lvl
        self.radioactive = radioactive
        self.developed = developed
        # Set to the player who developed this country until its first
        # income phase afterwards, which is skipped (see ReinforcementPhase).
        self.dormant_owner = dormant_owner
        # Who dropped the nuke here, if radioactive: their turn start is
        # what ticks the radioactivity down (see ReinforcementPhase).
        self.bombed_by = bombed_by
        self.airport = airport
        # China's pagoda / Japan's torii (see phases.LANDMARKS): the player
        # who placed it, shown only while they still own the country.
        self.landmark_owner = landmark_owner
        # Mouse country that "maak van de VOC een deel 2" took a troop
        # from; it gets it back when the event ends.
        self.voc_weakened = False
        self.shade = shade

        center = np.average(np.array([np.average(p, axis=0) for p in polygon]), axis=0)
        if name in ["Sri Lanka", "Japan", "Cuba", "Pearl Harbor"]:
            center += np.array([0, 20])
        if name == "IJsland":
            center += np.array([-10, 10])
        if name == "Canada":
            center += np.array([-30, 30])
        self.mass_center = Position(int(center[0]), int(center[1]))

    def set_outline(self, raw_polygon):
        """Replace the drawn outline (finer coastlines) while keeping the
        original polygon for the mass center; hit-testing accepts both."""
        self.polygon = [[Position(p[0], p[1]) for p in pol] for pol in raw_polygon]
        self.hit_polygon = list(self.raw_polygon) + [list(pol) for pol in raw_polygon]

    def scale_shape(self, factor):
        """Enlarge (or shrink) the country's outlines -- drawn and
        hit-testing alike -- by `factor` about the centre of its drawn
        land area. The troop circle (mass_center) and so every connection
        line stay where they are."""
        area = cx = cy = 0.0
        for ring in self.polygon:
            for a, b in zip(ring, ring[1:] + ring[:1]):
                cross = a.x * b.y - b.x * a.y
                area += cross
                cx += (a.x + b.x) * cross
                cy += (a.y + b.y) * cross
        if area == 0:
            return
        cx, cy = cx / (3 * area), cy / (3 * area)

        def scaled(p):
            return (cx + (p[0] - cx) * factor, cy + (p[1] - cy) * factor)

        self.raw_polygon = [[scaled(p) for p in ring] for ring in self.raw_polygon]
        self.hit_polygon = [[scaled(p) for p in ring] for ring in getattr(self, "hit_polygon", self.raw_polygon)]
        self.polygon = [[Position(*scaled((p.x, p.y))) for p in ring] for ring in self.polygon]

    def translate(self, dx, dy):
        """Move the whole country -- outlines, hit-testing and troop
        circle (so its connection lines follow) -- by (dx, dy)."""
        def moved(ring):
            return [(p[0] + dx, p[1] + dy) for p in ring]

        self.raw_polygon = [moved(ring) for ring in self.raw_polygon]
        self.hit_polygon = [moved(ring) for ring in getattr(self, "hit_polygon", self.raw_polygon)]
        self.polygon = [[Position(p.x + dx, p.y + dy) for p in ring] for ring in self.polygon]
        self.mass_center = Position(int(round(self.mass_center.x + dx)), int(round(self.mass_center.y + dy)))

    def set_drawn_outline(self, rings):
        """Replace only the drawn outline (e.g. smoothed, see
        outline_smoothing); hit-testing is left as it is."""
        self.polygon = [[Position(p[0], p[1]) for p in ring] for ring in rings]

    def __hash__(self):
        return stable_hash(self.name)

    def point_in_country(self, point):
        polygons = getattr(self, "hit_polygon", self.raw_polygon)
        # Building a matplotlib Path per polygon on every hover test cost
        # about a third of a headless game; they only change when the
        # polygons are replaced (scale/translate/set_outline), which makes
        # a new list.
        cached = getattr(self, "_hit_paths", None)
        if cached is None or cached[0] is not polygons:
            cached = self._hit_paths = (polygons, [Path(pol) for pol in polygons])
        for path in cached[1]:
            if path.contains_point((point.x, point.y)):
                return True
        return False

    def draw(
            self,
            view,
            shading_factor=50,
            border_width=2,
            border_color=(0, 0, 0),
            draw_border=True,
    ):
        """Fill (and radioactive band), plus the border unless draw_border
        is False -- the map draws borders separately (draw_border below)
        so it can blend them all in at once."""
        color = tuple(int(c) for c in np.clip(self.owner.color + self.shade * shading_factor * np.array([1, 1, 1]), 0, 255))
        width = max(1, int(round(border_width * view.draw_scale)))
        for pol in self.polygon:
            points = [point.to_px(view) for point in pol]
            pg.draw.polygon(view.map_surface, color, points)
            if self.developed:
                self._draw_developed_band(view, points)
            if draw_border:
                pg.draw.polygon(view.map_surface, border_color, points, width)
            if self.radioactive > 0:
                self._draw_hazard_band(view, points, border_color, width, outline=draw_border)

    def draw_border(self, view, border_color, border_width=2):
        width = max(1, int(round(border_width * view.draw_scale)))
        for pol in self.polygon:
            pg.draw.polygon(view.map_surface, border_color, [point.to_px(view) for point in pol], width)

    HAZARD_BAND = 7     # logical px, along the inside of the border
    HAZARD_STRIPE = 9   # logical px between stripes
    # Developed countries: a sun-yellow band along the inside of the border.
    # The grey border covers the first 1px of it, so 2px shows.
    DEVELOPED_COLOR = (255, 200, 40)
    DEVELOPED_BAND = 3  # logical px
    # Still being developed (dormant_owner set, before its first income):
    # the band is dotted instead, one dot every DEVELOPING_DOT_STEP.
    DEVELOPING_DOT_STEP = 7  # logical px

    @staticmethod
    def _band_alpha(points, band):
        """(alpha surface, x0, y0) for the strip inside the polygon
        `points` within `band` px of its edge, or None if it's too small.
        Built with plain alpha blends (no Mask.to_surface, which came out
        as a solid box on some display surface formats)."""
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0 + 2, max(ys) - y0 + 2
        if w < 4 or h < 4:
            return None
        local = [(x - x0, y - y0) for x, y in points]
        band_alpha = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.polygon(band_alpha, (255, 255, 255, 255), local)
        edge = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.polygon(edge, (255, 255, 255, 255), local, band * 2)
        band_alpha.blit(edge, (0, 0), special_flags=pg.BLEND_RGBA_MIN)
        return band_alpha, x0, y0

    @staticmethod
    def _blit_band(view, layer, x0, y0):
        view.map_surface.blit(layer, (x0, y0))
        # Blitting a translucent surface onto a display-format surface also
        # blends its alpha channel, leaving transparent (alpha 0) pixels
        # that show up as a solid box on screen -- put full opacity back.
        view.map_surface.fill((0, 0, 0, 255), pg.Rect((x0, y0), layer.get_size()), special_flags=pg.BLEND_RGBA_MAX)

    def _draw_developed_band(self, view, points):
        band = max(2, int(round(self.DEVELOPED_BAND * view.draw_scale)))
        found = self._band_alpha(points, band)
        if found is None:
            return
        band_alpha, x0, y0 = found
        layer = pg.Surface(band_alpha.get_size(), pg.SRCALPHA)
        layer.fill(self.DEVELOPED_COLOR + (255,))
        if self.dormant_owner is not None:
            dots = pg.Surface(band_alpha.get_size(), pg.SRCALPHA)
            step = max(4.0, self.DEVELOPING_DOT_STEP * view.draw_scale)
            local = [(x - x0, y - y0) for x, y in points]
            carry = 0.0  # distance along the outline to the next dot
            for (ax, ay), (bx, by) in zip(local, local[1:] + local[:1]):
                length = math.hypot(bx - ax, by - ay)
                d = carry
                while d < length:
                    t = d / length
                    pg.draw.circle(dots, (255, 255, 255, 255),
                                   (round(ax + (bx - ax) * t), round(ay + (by - ay) * t)), band)
                    d += step
                carry = d - length
            band_alpha.blit(dots, (0, 0), special_flags=pg.BLEND_RGBA_MIN)
        layer.blit(band_alpha, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self._blit_band(view, layer, x0, y0)

    def _draw_hazard_band(self, view, points, border_color, border_width, outline=True):
        """Yellow/black warning stripes along the inside of the border."""
        s = view.draw_scale
        band = max(2, int(round(self.HAZARD_BAND * s)))
        period = max(4, int(round(self.HAZARD_STRIPE * s)))
        found = self._band_alpha(points, band)
        if found is None:
            return
        band_alpha, x0, y0 = found
        w, h = band_alpha.get_size()
        stripes = pg.Surface((w, h), pg.SRCALPHA)
        stripes.fill((25, 25, 25, 255))
        k = -h
        while k < w + h:
            pg.draw.polygon(stripes, (250, 210, 0, 255),
                            [(k, 0), (k + period // 2, 0), (k + period // 2 + h, h), (k + h, h)])
            k += period
        stripes.blit(band_alpha, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self._blit_band(view, stripes, x0, y0)
        # Redraw the outline over the band so the edge stays crisp.
        if outline:
            pg.draw.polygon(view.map_surface, border_color, points, border_width)

    # Troop marker: a circle (a square for countries with an airport) filled
    # with a light tint of the owner's colour, white edge, black number.
    # White lines across it show assets: ship "/", tank "-", plane "\" (as
    # (dx, dy) directions; screen y points down). A fort puts a white badge
    # behind it with 2 / 4 / 8 battlements for level 1 / 2 / 3.
    MARKER_TINT = 0.5
    ASSET_LINES = (("ships", (1, -1)), ("tanks", (1, 0)), ("planes", (1, 1)))
    BADGE_FILL, BADGE_EDGE = (255, 255, 255), (120, 120, 120)
    BADGE_BATTLEMENTS = {1: 2, 2: 4, 3: 8}

    def draw_troops(
            self,
            font,
            view,
            show_ships_planes=True,
            show_tanks=True,
            circle_radius=14,
            outline_width=2,
    ):
        s = view.draw_scale
        x, y = self.mass_center.to_px(view)
        surface = view.map_surface
        radius = int(round(circle_radius * s))
        border = max(1, int(round(outline_width * s)))
        fill = light_tint(tuple(int(c) for c in self.owner.color), self.MARKER_TINT)
        shown = {"ships": show_ships_planes, "planes": show_ships_planes, "tanks": show_tanks}
        lines = [d for attr, d in self.ASSET_LINES if shown[attr] and getattr(self, attr) > 0]
        line_w = max(1, int(round(1.4 * s)))
        white = (255, 255, 255)

        if self.airport:
            # Slightly smaller than the circle so it looks about the same size.
            half = int(round(radius * 0.88))
            if self.fort_lvl:
                self._draw_fort_badge(surface, x, y, half, s, square=True)
            rect = pg.Rect(x - half, y - half, 2 * half + 1, 2 * half + 1)
            pg.draw.rect(surface, white, rect)
            inner = rect.inflate(-2 * border, -2 * border)
            pg.draw.rect(surface, fill, inner)
            reach = inner.w / 2  # to the edge (corners for the diagonals)
            for dx, dy in lines:
                pg.draw.line(surface, white, (x - dx * reach, y - dy * reach), (x + dx * reach, y + dy * reach), line_w)
        else:
            if self.fort_lvl:
                self._draw_fort_badge(surface, x, y, radius, s, square=False)
            gfxdraw.filled_circle(surface, x, y, radius, white)
            gfxdraw.aacircle(surface, x, y, radius, white)
            inner = radius - border
            gfxdraw.filled_circle(surface, x, y, inner, fill)
            gfxdraw.aacircle(surface, x, y, inner, fill)
            for dx, dy in lines:
                reach = inner / math.hypot(dx, dy)  # to the edge of the circle
                pg.draw.line(surface, white, (x - dx * reach, y - dy * reach), (x + dx * reach, y + dy * reach), line_w)

        text = font.render(str(self.units), True, (0, 0, 0))
        surface.blit(text, (x - text.get_width() // 2, y - text.get_height() // 2))

    def _draw_fort_badge(self, surface, x, y, half, s, square):
        """White badge behind the troop marker (half-size `half`): a thin
        wall around it with battlements along the top, a rounded bottom
        under a circle and a square one under an airport's square."""
        R = half + 2.0 * s                 # badge half-width (wall 2 px)
        n = self.BADGE_BATTLEMENTS[self.fort_lvl]
        mw = min(4.5 * s, 2 * R / (2 * n - 1))  # narrower when many; gaps >= width
        mh = int(round(3.5 * s))
        top = int(round(y - R))
        # Whole-pixel battlements mirrored around the centre line, so both
        # sides match exactly: offsets for the left half, then flipped.
        Ri = int(round(R))
        hw = max(1, int(round(mw / 2)))    # half-width; each is 2 * hw + 1 wide
        left = [int(round(-Ri + hw + i * (2 * Ri - 2 * hw) / (n - 1))) for i in range(n // 2)]
        offsets = left + [-d for d in reversed(left)]
        for pad, color in ((max(1, round(s)), self.BADGE_EDGE), (0, self.BADGE_FILL)):
            rr = int(round(R + pad))
            if square:
                pg.draw.rect(surface, color, pg.Rect(x - rr, top - pad, 2 * rr + 1, 2 * (y - top + pad) + 1))
            else:
                gfxdraw.filled_circle(surface, x, y, rr, color)   # rounded bottom
                gfxdraw.aacircle(surface, x, y, rr, color)
                pg.draw.rect(surface, color, pg.Rect(x - rr, top - pad, 2 * rr + 1, y - top + pad + 1))
            for d in offsets:
                pg.draw.rect(surface, color, pg.Rect(x + d - hw - pad, top - mh - pad, 2 * (hw + pad) + 1, mh + pad + 1))

    def draw_assets(self, view, img_ship, img_tank, img_plane, show_military=True):
        x, y = self.mass_center.to_px(view)
        # One icon per asset type no matter how many units of it there are
        # (2, 3, 4 ships all look the same as 1 ship) -- each entry below
        # is only drawn once, gated on presence rather than count. Neither
        # the fort nor radioactivity gets a map icon -- both only show in
        # the country info panel.
        if not show_military:
            return
        assets = [
            (self.ships > 0, img_ship),
            (self.tanks > 0, img_tank),
            (self.planes > 0, img_plane),
        ]
        present = [img for is_present, img in assets if is_present]
        y += int(30 * view.draw_scale)  # comfortably below the troop count circle, not obscuring it
        spacing = 25 * view.draw_scale
        start_x = -spacing * (len(present) - 1) / 2
        for i, img in enumerate(present):
            img.draw(view.map_surface, Position(int(x + start_x + i * spacing), y))


class Connection:

    def __init__(self, connection, kind, rails=False):
        self.connection = connection
        self.kind = kind
        # Whether rails have been built along this connection. Kept separate
        # from `kind` (which stays "land"/"sea") so existing attack/movement
        # logic that checks `kind` keeps working once rails go in.
        self.rails = rails

    def __contains__(self, other):
        return other in self.connection

    def __hash__(self):
        # engine.connections is a set: its iteration order must not depend
        # on memory addresses (see stable_hash). Equality stays identity.
        return stable_hash(*sorted(self.connection))

    # Routes drawn as a smooth curve through waypoints (map coordinates)
    # instead of a straight line, keyed by the pair of countries: the
    # country the path starts from, then the points in order. Only the
    # drawing changes -- the connection itself is the same.
    WAYPOINTS = {
        # Spanje -> Nigeria hugs the west African coast, like the VOC
        # ships' route around Africa.
        frozenset({"Spanje", "Nigeria"}): ("Spanje", [
            (252, 214), (246, 236), (236, 260), (230, 282), (229, 302), (235, 318), (252, 327),
        ]),
    }

    def _path(self, countries, view):
        """Pixel points of this route, if it has waypoints (else None)."""
        entry = self.WAYPOINTS.get(frozenset(self.connection))
        if entry is None:
            return None
        start, waypoints = entry
        end = next(name for name in self.connection if name != start)
        control = [countries[start].mass_center] + [Position(x, y) for x, y in waypoints] + \
                  [countries[end].mass_center]
        control = [p.to_px(view) for p in control]
        # Catmull-Rom spline through the control points, for a smooth curve.
        padded = [control[0]] + control + [control[-1]]
        path = []
        for i in range(1, len(padded) - 2):
            p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
            for step in range(8):
                t = step / 8
                path.append(tuple(
                    0.5 * (2 * p1[k] + (p2[k] - p0[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t * t
                           + (3 * p1[k] - p0[k] - 3 * p2[k] + p3[k]) * t ** 3)
                    for k in range(2)))
        path.append(control[-1])
        return path

    def draw(
            self,
            countries,
            connection_colors,
            view,
            outline_color=(0, 0, 0),
            line_width=5,
            outline_width=2,
    ):
        points = [countries[name].mass_center.to_px(view) for name in self.connection]
        if {"Alaska", "Siberië"}.issubset(self.connection) or {"Japan", "Pearl Harbor"}.issubset(self.connection):
            logical = [countries[name].mass_center.transform_coordinates(view) for name in self.connection]
            swap = logical[0].x < logical[0].y

            def edge(flag):
                return int(view.WIDTH * flag * view.draw_scale + view.draw_ox)

            points = [points[0], (edge(not swap), points[0][1]), points[1], (edge(swap), points[1][1])]
        # A connection with rails built on it is drawn grey regardless of
        # whether it's a land or sea link.
        line_color = connection_colors["rails"] if self.rails else connection_colors[self.kind]
        # Each piece is a polyline: the plain straight line, the two halves
        # of a route wrapping around the map edge, or a waypoint curve.
        path = self._path(countries, view)
        pieces = [path] if path is not None else [list(pair) for pair in zip(points[0::2], points[1::2])]
        if self.kind == "sea" and not self.rails:
            # Sea routes: evenly spaced dots, no outline.
            for piece in pieces:
                self._draw_dots(view, line_color, piece, line_width)
            return
        outer = max(1, int(round(line_width * view.draw_scale)))
        inner = max(1, int(round((line_width - outline_width) * view.draw_scale)))
        for piece in pieces:
            pg.draw.lines(view.map_surface, outline_color, False, piece, outer)
            pg.draw.lines(view.map_surface, line_color, False, piece, inner)

    # Sea routes: evenly spaced dots, DOT_STEP logical px apart.
    DOT_STEP = 7

    @classmethod
    def _draw_dots(cls, view, color, piece, line_width):
        """Dots along the polyline `piece`, spaced evenly across its bends."""
        s = view.draw_scale
        step = cls.DOT_STEP * s
        radius = max(1, int(round(line_width * s * 0.4)))
        t = 0.0  # distance along the current segment of the next dot
        for (x1, y1), (x2, y2) in zip(piece, piece[1:]):
            length = math.hypot(x2 - x1, y2 - y1)
            if length == 0:
                continue
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            while t <= length:
                cx, cy = int(round(x1 + ux * t)), int(round(y1 + uy * t))
                gfxdraw.filled_circle(view.map_surface, cx, cy, radius, color)
                gfxdraw.aacircle(view.map_surface, cx, cy, radius, color)
                t += step
            t -= length


class Position:

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Position(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Position(self.x - other.x, self.y - other.y)

    def __str__(self):
        return "({}, {})".format(self.x, self.y)

    def transform_coordinates(self, view):
        return Position(
            int((self.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH),
            int((self.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT),
        )

    def to_px(self, view):
        """Pixel position on view.map_surface (float-accurate, unlike
        transform_coordinates, which is the truncated logical version)."""
        x = (self.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH
        y = (self.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT
        return int(round(x * view.draw_scale + view.draw_ox)), int(round(y * view.draw_scale + view.draw_oy))

    def screen_to_coordinates(self, view):
        return Position(
            int((self.x - 0.5 * view.WIDTH) / view.zoom - view.offset.x),
            int((self.y - 0.5 * view.HEIGHT) / view.zoom - view.offset.y),
        )

    def to_tuple(self):
        return self.x, self.y


class Image:

    def __init__(self, name, scale=None):
        self.image = pg.image.load("./images/{}.png".format(name)).convert_alpha()
        if scale is not None:
            self.image = pg.transform.smoothscale(self.image, scale)
        self.name = name

    def draw(self, screen, pos):
        screen.blit(self.image, (pos.x, pos.y))


class Dice:

    def __init__(self, color, used=0, eyes=0):
        self.color = color
        self.used = used
        self.eyes = eyes

    def draw(
            self,
            screen,
            pos,
            border_width=6,
            dot_radius=6,
            size=70,
    ):
        # A white die (light grey when deselected, `used`) with a thick border and eyes in the owning player's
        # colour. `eyes` of 0 draws a blank (not yet rolled) die.
        color = tuple(int(c) for c in np.clip(self.color, 0, 255))
        square = pg.Rect(pos.x - 0.5 * size, pos.y - 0.5 * size, size, size)
        face = (160, 160, 160) if self.used else (255, 255, 255)
        pg.draw.rect(screen, face, square, border_radius=10)
        pg.draw.rect(screen, color, square, border_width, border_radius=10)
        d = 17
        if self.eyes in {1, 3, 5}:
            pg.draw.circle(screen, color, (pos.x, pos.y), dot_radius)
        if self.eyes in {2, 3, 4, 5, 6}:
            pg.draw.circle(screen, color, (pos.x - d, pos.y + d), dot_radius)
            pg.draw.circle(screen, color, (pos.x + d, pos.y - d), dot_radius)
        if self.eyes in {4, 5, 6}:
            pg.draw.circle(screen, color, (pos.x + d, pos.y + d), dot_radius)
            pg.draw.circle(screen, color, (pos.x - d, pos.y - d), dot_radius)
        if self.eyes == 6:
            pg.draw.circle(screen, color, (pos.x + d, pos.y), dot_radius)
            pg.draw.circle(screen, color, (pos.x - d, pos.y), dot_radius)


class Io:

    # Matches Country.draw_troops' default circle_radius (logical px).
    TROOP_CIRCLE_RADIUS = 14

    def __init__(self):
        self.mouse_state = [0, 0, 0]
        self.previous_mouse_state = [0, 0, 0]
        self.left_pressed = 0
        # A right-button press and release without dragging (the right
        # button also pans the map); True on the frame it's released.
        self.right_clicked = False
        self._right_down_at = None
        self.mouse_position = Position(0, 0)
        self.transformed_mouse_position = Position(0, 0)
        self.previous_mouse_position = Position(0, 0)
        self.previous_transformed_mouse_position = Position(0, 0)
        self.hover_country = None
        # Buttons register where they are each frame (`button`); next frame
        # the topmost one under the mouse owns the click, so whatever is
        # behind it (the map, another button) doesn't get it too.
        self.buttons = []
        self.top_button = None

    @staticmethod
    def _contains(shape, p):
        if shape[0] == "c":
            _, cx, cy, r = shape
            return (p.x - cx) ** 2 + (p.y - cy) ** 2 <= r ** 2
        _, x, y, w, h = shape
        return x <= p.x <= x + w and y <= p.y <= y + h

    def button(self, shape):
        """Register a button ("r", x, y, w, h) or ("c", cx, cy, r) drawn
        this frame; True when it's clicked and no button registered after
        it last frame (i.e. drawn on top) is under the mouse."""
        self.buttons.append(shape)
        if not (self.left_pressed and self._contains(shape, self.mouse_position)):
            return False
        return self.top_button is None or self.top_button == shape

    def update(self, view, countries):
        self.previous_mouse_state = self.mouse_state
        self.mouse_state = pg.mouse.get_pressed()
        self.left_pressed = not self.previous_mouse_state[0] and self.mouse_state[0]
        self.previous_mouse_position = self.mouse_position
        current_pos = pg.mouse.get_pos()
        # Window pixels -> the logical 960x640 UI coordinates.
        self.mouse_position = Position(
            int((current_pos[0] - view.ox) / view.scale),
            int((current_pos[1] - view.oy) / view.scale),
        )
        self.transformed_mouse_position = self.mouse_position.screen_to_coordinates(view)
        self.right_clicked = False
        if self.mouse_state[2] and not self.previous_mouse_state[2]:
            self._right_down_at = self.mouse_position
        elif not self.mouse_state[2] and self.previous_mouse_state[2] and self._right_down_at is not None:
            start = self._right_down_at
            self.right_clicked = (self.mouse_position.x - start.x) ** 2 + (self.mouse_position.y - start.y) ** 2 <= 4 ** 2
            self._right_down_at = None
        self.previous_transformed_mouse_position = self.previous_mouse_position.screen_to_coordinates(view)
        # Update hover_country. A country's troop circle counts as part of
        # it (it can overhang the border, e.g. on small countries); when
        # several circles are under the mouse, the nearest centre wins.
        self.hover_country = None
        best = None
        for country in countries:
            cx = (country.mass_center.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH
            cy = (country.mass_center.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT
            dx, dy = self.mouse_position.x - cx, self.mouse_position.y - cy
            d2 = dx ** 2 + dy ** 2
            r = self.TROOP_CIRCLE_RADIUS
            # Airports draw a square (see Country.draw_troops) instead.
            inside = max(abs(dx), abs(dy)) <= r * 0.88 if country.airport else d2 <= r ** 2
            if inside and (best is None or d2 < best):
                best = d2
                self.hover_country = country.name
        if self.hover_country is None:
            for country in countries:
                if country.point_in_country(self.transformed_mouse_position):
                    self.hover_country = country.name
        last, self.buttons = self.buttons, []
        self.top_button = next((b for b in reversed(last) if self._contains(b, self.mouse_position)), None)
        if self.top_button is not None:
            self.hover_country = None  # the map behind a button is out of reach

    def drag_map(self, offset):
        # Either the middle or right mouse button drags (pans) the map
        # sideways -- right-click is the more commonly expected one, and
        # is otherwise unused anywhere in the game.
        if self.mouse_state[1] or self.mouse_state[2]:
            return offset + self.transformed_mouse_position - self.previous_transformed_mouse_position
        return offset


class View:

    MIN_ZOOM = 0.3
    MAX_ZOOM = 6.0

    def __init__(self, screen, zoom, offset, WIDTH, HEIGHT):
        self.screen = screen
        self.zoom = zoom
        self.offset = offset
        self.WIDTH = WIDTH
        self.HEIGHT = HEIGHT
        # The game UI is drawn on `screen` at a fixed logical WIDTH x HEIGHT
        # and scaled up. The map is drawn straight onto `map_surface` in
        # real pixels: `scale`/`ox`/`oy` place the logical area inside the
        # window, and draw_* are what Position.to_px currently uses.
        self.window = None
        self.map_surface = None
        self.scale = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.draw_scale = 1.0
        self.draw_ox = 0.0
        self.draw_oy = 0.0

    def zoom_at(self, screen_pos, factor):
        """Multiply zoom by `factor`, adjusting offset so the world point
        currently under `screen_pos` stays under the cursor, instead of
        the map appearing to slide off toward a screen corner as it's
        zoomed (the naive "just change self.zoom" approach)."""
        world_before = screen_pos.screen_to_coordinates(self)
        self.zoom = min(max(self.zoom * factor, self.MIN_ZOOM), self.MAX_ZOOM)
        self.offset = Position(
            (screen_pos.x - 0.5 * self.WIDTH) / self.zoom - world_before.x,
            (screen_pos.y - 0.5 * self.HEIGHT) / self.zoom - world_before.y,
        )


class Button:

    def __init__(self, pos, width, height, color, outline_color=(0, 0, 0), outline_width=2, image=None):
        self.pos = pos
        self.width = width
        self.height = height
        self.color = color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.image = image

    def draw(self, view, io):
        mouse_in_button = (self.pos.x < io.mouse_position.x < self.pos.x + self.width and
                           self.pos.y < io.mouse_position.y < self.pos.y + self.height)
        io.button(self._shape())
        w = 3 * mouse_in_button
        shade = 40 * (mouse_in_button and io.mouse_state[0])
        pg.draw.rect(
            view.screen,
            [max(col - shade, 0) for col in self.color],
            pg.Rect(self.pos.x - w, self.pos.y - w, self.width + 2 * w, self.height + 2 * w)),
        pg.draw.rect(
            view.screen,
            self.outline_color,
            pg.Rect(self.pos.x - w, self.pos.y - w, self.width + 2 * w, self.height + 2 * w),
            self.outline_width
        )
        if self.image is not None:
            iw, ih = self.image.image.get_size()
            self.image.draw(
                view.screen,
                Position(self.pos.x + (self.width - iw) // 2, self.pos.y + (self.height - ih) // 2),
            )

    def _shape(self):
        return ("r", self.pos.x, self.pos.y, self.width, self.height)

    def release_button(self, function_to_execute, io):
        shape = self._shape()
        if io.left_pressed and io._contains(shape, io.mouse_position) and io.top_button in (None, shape):
            function_to_execute()


class Gui:

    def __init__(
            self,
            io,
            gray1=(200, 200, 200),
            gray2=(150, 150, 150),
            width=150,
            height=384,
            outline_color=(0, 0, 0),
    ):
        self.gray1 = gray1
        self.gray2 = gray2
        self.width = width
        self.height = height
        self.outline_color = outline_color
        self.io = io

    def draw_overlay(self, view):
        # Only the player panel is always there; the country info panel
        # draws its own background, sized to its contents.
        pg.draw.rect(
            view.screen,
            self.gray1,
            pg.Rect(view.WIDTH - self.width, view.HEIGHT - self.height, self.width, view.HEIGHT),
        )

    # Owner mini-stats under the country info: icon + amount, 3 per row.
    OWNER_CELLS = [("spr_food", "food"), ("spr_wood", "wood"), ("spr_steel", "steel"),
                   ("spr_oil", "oil"), ("spr_nuclear", "nuclear"), ("spr_troops", "helmets"),
                   ("spr_cards", "cards")]

    def draw_country_stats(self, view, country, font, images, owner_stats=None):
        """`owner_stats` = (player, {food, wood, steel, oil, nuclear,
        helmets, cards}, mini_images): draws a compact summary of the country's
        owner under the country info."""
        # A developed country yields double, so its resources show doubled
        # (troops don't double) -- but not while it's still under
        # construction (dormant_owner set until its first income).
        mult = 2 if country.developed and country.dormant_owner is None else 1
        image_list = [images["spr_food"]] * (country.food * mult) + \
                     [images["spr_wood"]] * (country.wood * mult) + \
                     [images["spr_steel"]] * (country.steel * mult) + \
                     [images["spr_oil"]] * (country.oil * mult) + \
                     [images["spr_nuclear"]] * (country.nuclear * mult) + \
                     [images["spr_troops"]] * country.troops
        # Airport/developed flags (developing.png while the idle first-income
        # turn hasn't passed yet) and the fort level share one row of icons.
        status_items = []
        if country.airport:
            status_items.append((images["spr_airport"], None))
        if country.developed:
            developed_icon = images["spr_developing"] if country.dormant_owner is not None else images["spr_developed"]
            status_items.append((developed_icon, None))
        if country.fort_lvl:
            status_items.append((images["spr_fort"], "L{}".format(country.fort_lvl)))
        if country.landmark_owner is not None and country.landmark_owner is country.owner:
            status_items.append((images["spr_{}".format(LANDMARKS[country.name])], None))
        status_h = 30 if status_items else 0

        # Military assets stationed here: ships/tanks/planes packed into a
        # compact icon+count grid (like the owner mini-stats below), with
        # radioactivity as its own line since it needs a bit more text.
        asset_cells = []
        if country.ships:
            asset_cells.append((images["spr_ship"], "x{}".format(country.ships)))
        if country.tanks:
            asset_cells.append((images["spr_tank"], "x{}".format(country.tanks)))
        if country.planes:
            asset_cells.append((images["spr_plane"], "x{}".format(country.planes)))
        assets_grid_h = 26 * -(-len(asset_cells) // 3) if asset_cells else 0  # ceil div, 3 per row
        radioactive_h = 22 if country.radioactive else 0

        # Normal: 40px sprites, 3 per row, up to 3 rows. More than that
        # (developed China, Outback...) -> smaller sprites, 5 per row.
        compact = len(image_list) > 9
        per_row, cell = (5, 28) if compact else (3, 46)
        y_status = 30 + -(-len(image_list) // per_row) * cell
        y_assets = y_status + status_h
        base_h = y_assets + assets_grid_h + radioactive_h + 6
        panel_h = base_h
        if owner_stats:
            panel_h = max(panel_h, self.OWNER_MIN_H)  # room for the owner box beside it

        x0 = view.WIDTH - self.width
        pg.draw.rect(view.screen, self.gray1, pg.Rect(x0, 0, self.width, panel_h))

        # Another player's country: their colour makes a band over the top
        # of both this panel and the owner box beside it, with the names in it.
        name_color = self.outline_color
        if owner_stats:
            owner = owner_stats[0]
            name_color = name_text_color(owner.color)
            if not hasattr(self, "small_font"):
                self.small_font = game_font(15)
            self._draw_owner_box(view, owner_stats, x0, font)
        elif country.owner is not None:
            # The active player's own country, or the neutral mouse's: the
            # owner's colour makes the name band over this panel alone.
            name_color = name_text_color(country.owner.color)
            pg.draw.rect(view.screen, country.owner.color, pg.Rect(x0, 0, self.width, self.OWNER_BAND_H))
        banded = country.owner is not None

        name = font.render(country.name, True, name_color)
        avail = self.width - 16
        if name.get_width() > avail:
            # Long names (e.g. Papoea Nieuw Guinea) get a smaller font.
            if not hasattr(self, "small_font"):
                self.small_font = game_font(15)
            name = self.small_font.render(country.name, True, name_color)
        view.screen.blit(name, (x0 + (self.width - name.get_width()) // 2,
                                (self.OWNER_BAND_H - name.get_height()) // 2 if banded else 2))
        for index, image in enumerate(image_list):
            px, py = x0 + 8 + (index % per_row) * cell, 30 + (index // per_row) * cell
            if not compact:
                image.draw(view.screen, Position(px, py))
                continue
            iw, ih = image.image.get_size()
            small = (max(1, round(iw * 26 / max(iw, ih))), max(1, round(ih * 26 / max(iw, ih))))
            cache = self.__dict__.setdefault("_small_sprites", {})
            if (id(image), small) not in cache:
                cache[(id(image), small)] = pg.transform.smoothscale(image.image, small)
            sprite = cache[(id(image), small)]
            view.screen.blit(sprite, (px + (26 - small[0]) // 2, py + (26 - small[1]) // 2))
        if (status_items or asset_cells or country.radioactive) and not hasattr(self, "small_font"):
            self.small_font = game_font(15)
        sx = x0 + 8
        for icon, text in status_items:
            iw, ih = icon.image.get_size()
            icon.draw(view.screen, Position(sx, y_status + 2 + (24 - ih) // 2))
            sx += iw + 4
            if text is not None:
                label = self.small_font.render(text, True, self.outline_color)
                view.screen.blit(label, (sx, y_status + 2 + (24 - label.get_height()) // 2))
                sx += label.get_width() + 8

        for i, (icon, text) in enumerate(asset_cells):
            cx = x0 + 6 + (i % 3) * 48
            cy = y_assets + (i // 3) * 26
            iw, ih = icon.image.get_size()
            icon.draw(view.screen, Position(cx + (20 - iw) // 2, cy + (20 - ih) // 2))
            view.screen.blit(self.small_font.render(text, True, self.outline_color), (cx + 22, cy + 2))
        if country.radioactive:
            ry = y_assets + assets_grid_h
            icon = images["spr_nuke"]
            iw, ih = icon.image.get_size()
            icon.draw(view.screen, Position(x0 + 8 + (20 - iw) // 2, ry + (22 - ih) // 2))
            turns = "turn" if country.radioactive == 1 else "turns"
            text = "{} {} left".format(country.radioactive, turns)
            view.screen.blit(self.small_font.render(text, True, self.outline_color), (x0 + 34, ry + 3))

        # Dark outline round the panel below the band. With the owner box
        # beside it, the left side runs on from the box's right line as one
        # line down to the bottom of this panel.
        top = self.OWNER_BAND_H if banded else 0
        left = x0 - 2 if owner_stats else x0
        rects = [pg.Rect(view.WIDTH - 2, top, 2, panel_h - top), pg.Rect(left, panel_h - 2, view.WIDTH - left, 2),
                 pg.Rect(left, top, 2, panel_h - top)]
        for rect in rects:
            pg.draw.rect(view.screen, self.OWNER_LINE_COLOR, rect)

    OWNER_BAND_H = 26
    OWNER_MIN_H = 82  # owner box height: that of a country panel with 3 resources
    OWNER_LINE_COLOR = (90, 90, 90)
    # Order of the owner's stats: 4 columns over 2 rows, cards centred
    # between the rows in the last column.
    OWNER_ORDER = ["food", "wood", "steel", "cards", "nuclear", "helmets", "oil"]

    def _draw_owner_box(self, view, owner_stats, country_x0, font):
        """The owner's stats in a compact box flush left of the country panel,
        always OWNER_MIN_H high whatever the country panel's height."""
        h = self.OWNER_MIN_H
        owner, amounts, mini = owner_stats
        sprites = dict((key, mini[sprite]) for sprite, key in self.OWNER_CELLS)
        col_w = 20 + 2 + self.small_font.size("88")[0] + 4
        band = self.OWNER_BAND_H
        row_h = 26
        w = 3 * col_w + 4 + 20 + 3 + self.small_font.size(str(amounts["cards"]))[0] + 5
        # Stat rows centred between the band and the outline at the bottom.
        top = band + (h - 2 - band - (row_h + 20)) // 2
        x0 = country_x0 - w
        pg.draw.rect(view.screen, self.gray1, pg.Rect(x0, 0, w, h))
        # The band runs on over the country panel to the screen edge.
        pg.draw.rect(view.screen, owner.color, pg.Rect(x0, 0, w + self.width, band))
        label = font.render(owner.name, True, name_text_color(owner.color))
        view.screen.blit(label, (x0 + (w - label.get_width()) // 2, (band - label.get_height()) // 2))
        for i, key in enumerate(self.OWNER_ORDER):
            cx = x0 + 4 + (i % 4) * col_w
            cy = top + (i // 4) * row_h
            if key == "cards":
                cy = top + row_h // 2
            image = sprites[key]
            iw, ih = image.image.get_size()
            image.draw(view.screen, Position(cx + (20 - iw) // 2, cy + (20 - ih) // 2))
            view.screen.blit(self.small_font.render(str(amounts[key]), True, self.outline_color), (cx + 22, cy + 2))
        # Dark outline round the box, below the band.
        for rect in (pg.Rect(x0, band, 2, h - band), pg.Rect(x0 + w - 2, band, 2, h - band),
                     pg.Rect(x0, h - 2, w, 2)):
            pg.draw.rect(view.screen, self.OWNER_LINE_COLOR, rect)

    def draw_player_outline(self, view):
        """Dark outline all round the player panel (name band included),
        drawn after the phase box so nothing covers it."""
        x0, y0 = view.WIDTH - self.width, view.HEIGHT - self.height
        h = view.HEIGHT - y0
        for rect in (pg.Rect(x0, y0, self.width, 2), pg.Rect(x0, view.HEIGHT - 2, self.width, 2),
                     pg.Rect(x0, y0, 2, h), pg.Rect(view.WIDTH - 2, y0, 2, h)):
            pg.draw.rect(view.screen, self.OWNER_LINE_COLOR, rect)

    # Player panel layout (all in logical UI pixels): a name header, then
    # one row per resource, with enough clearance below the last row that
    # it doesn't crowd the phase-selector buttons anchored to the bottom.
    PLAYER_HEADER_H = 24
    PLAYER_ROWS_TOP_PAD = 6
    PLAYER_ROW_H = 42
    PLAYER_TEXT_X = 24         # left of the amount column (sprites sit at 8)
    PLAYER_AMOUNT_CX = 79      # centre line of the amounts

    def draw_player_stats(self, view, player, font, images, production=None):
        if not hasattr(self, "small_font"):
            self.small_font = game_font(15)
        x0 = view.WIDTH - self.width
        y0 = view.HEIGHT - self.height

        header_rect = pg.Rect(x0, y0, self.width, self.PLAYER_HEADER_H)
        pg.draw.rect(view.screen, player.color, header_rect)
        if not hasattr(self, "bold_font"):
            self.bold_font = game_font(20, bold=True)
        label = player.name + (" (bot)" if player.is_bot else "")
        name = self.bold_font.render(label, True, name_text_color(player.color))
        view.screen.blit(name, (x0 + (self.width - name.get_width()) // 2, header_rect.centery - name.get_height() // 2))

        resource_stats = [
            (images["spr_food"], player.food, 0),
            (images["spr_wood"], player.wood, 1),
            (images["spr_steel"], player.steel, 2),
            (images["spr_oil"], player.oil, 3),
            (images["spr_nuclear"], player.nuclear, 4),
            # Helmets: what the player's countries hold right now (live),
            # not the figure frozen at the start of the turn.
            (images["spr_troops"], production["helmets"] if production else player.troops, 5),
        ]
        resource_names = ["food", "wood", "steel", "oil", "nuclear", "troops"]
        rows_top = y0 + self.PLAYER_HEADER_H + self.PLAYER_ROWS_TOP_PAD
        for image, amount, index in resource_stats:
            pos = Position(x0 + self.PLAYER_TEXT_X, rows_top + index * self.PLAYER_ROW_H)
            iw, ih = image.image.get_size()
            image.draw(view.screen, pos + Position((40 - iw) // 2 - self.PLAYER_TEXT_X + 8, (40 - ih) // 2))
            text = font.render("{}".format(amount), True, self.outline_color)
            text_pos = pos + Position(0, (40 - text.get_height()) // 2)
            # Amounts are centred on one line so 1- and 2-digit ones line up.
            view.screen.blit(text, (x0 + self.PLAYER_AMOUNT_CX - text.get_width() // 2, text_pos.y))
            if production is not None:
                if index < 5:
                    gain = production[resource_names[index]]
                else:  # helmets: the reinforcements they bring each turn
                    gain = production["helmets"] // 3 + 3
                color = (0, 120, 0) if gain > 0 else (170, 0, 0) if gain < 0 else self.outline_color
                bracket = self.small_font.render("({:+d})".format(gain), True, color)
                view.screen.blit(bracket, (x0 + self.width - 10 - bracket.get_width(), pos.y + 13))

    phase_button_radius = 21
    PHASE_BOX_H = 100

    def phase_button_center(self, view, index):
        """Center of the index-th phase button (reinforce/attack/move)."""
        return (view.WIDTH - self.width + 8 + self.phase_button_radius + 4 + 45 * index,
                view.HEIGHT - self.PHASE_BOX_H + 30)

    def phase_button_hit(self, view, index, pos):
        cx, cy = self.phase_button_center(view, index)
        return (pos.x - cx) ** 2 + (pos.y - cy) ** 2 <= self.phase_button_radius ** 2

    def end_turn_rect(self, view):
        return pg.Rect(view.WIDTH - self.width + 12, view.HEIGHT - self.PHASE_BOX_H + 62,
                       self.width - 24, 30)

    def end_turn_hit(self, view, pos):
        return self.end_turn_rect(view).collidepoint(pos.x, pos.y)

    def draw_attack_phase(
            self,
            view,
            player,
            images=None,
            outline_color=(0, 0, 0),
            colors=[(224, 224, 0), (255, 80, 79), (255, 165, 0)],
            icon_keys=("spr_recruit_phase", "spr_attack_phase", "spr_move_phase"),
            outline_width=2,
            end_turn_enabled=True,
    ):
        """The phase box under the player panel: the three phase buttons
        and an End turn button."""
        if not hasattr(self, "_phase_dim_overlay"):
            # A translucent dark circle dropped over a phase button dims
            # its fill and icon together, without touching the (shared)
            # icon images themselves.
            d = self.phase_button_radius * 2
            overlay = pg.Surface((d, d), pg.SRCALPHA)
            pg.draw.circle(overlay, (15, 15, 15, 150), (self.phase_button_radius, self.phase_button_radius), self.phase_button_radius)
            self._phase_dim_overlay = overlay

        x0 = view.WIDTH - self.width
        y0 = view.HEIGHT - self.PHASE_BOX_H
        pg.draw.line(view.screen, outline_color, (x0, y0), (view.WIDTH, y0), 2)

        for index, color in enumerate(colors):
            center = self.phase_button_center(view, index)
            hovered = self.phase_button_hit(view, index, self.io.mouse_position)
            self.io.button(("c", center[0], center[1], self.phase_button_radius))
            current = player.attack == index
            shade = 40 * (hovered and self.io.mouse_state[0])
            pg.draw.circle(view.screen, [max(col - shade, 0) for col in color], center, self.phase_button_radius)
            if images is not None:
                icon = images[icon_keys[index]]
                iw, ih = icon.image.get_size()
                icon.draw(view.screen, Position(center[0] - iw // 2, center[1] - ih // 2))
            if not current:
                # Dim whichever phases aren't the active one, so it's
                # obvious at a glance which phase you're in.
                view.screen.blit(
                    self._phase_dim_overlay,
                    (center[0] - self.phase_button_radius, center[1] - self.phase_button_radius),
                )
            pg.draw.circle(
                view.screen,
                outline_color,
                center,
                self.phase_button_radius,
                (outline_width if current else 1) + 2 * hovered,
            )

        rect = self.end_turn_rect(view)
        hovered = end_turn_enabled and self.end_turn_hit(view, self.io.mouse_position)
        self.io.button(("r", rect.x, rect.y, rect.w, rect.h))
        if not end_turn_enabled and self.io.left_pressed and self.end_turn_hit(view, self.io.mouse_position):
            sounds.play("error")
        shade = 40 * (hovered and self.io.mouse_state[0])
        base = (245, 150, 150) if end_turn_enabled else (190, 170, 170)
        pg.draw.rect(view.screen, [max(c - shade, 0) for c in base], rect, border_radius=6)
        pg.draw.rect(view.screen, outline_color, rect, 2 + hovered, border_radius=6)
        if not hasattr(self, "bold_font"):
            self.bold_font = game_font(20, bold=True)
        label = self.bold_font.render("End turn", True, outline_color if end_turn_enabled else (110, 110, 110))
        view.screen.blit(label, (rect.centerx - label.get_width() // 2, rect.centery - label.get_height() // 2))


class Shop:
    def __init__(self):
        print('shop')


class CardMenu:

    PANEL_COLOR = (195, 235, 190)  # same as the cards button

    # (label, reward attribute, multiplier of the trade's base value)
    TRADE_OPTIONS = [
        ("spr_troops", "helmets", 1),
        ("spr_food", "food", 2.5),
        ("spr_wood", "wood", 3),
        ("spr_steel", "steel", 2),
        ("spr_oil", "oil", 2),
        ("spr_nuclear", "nuclear", 1),
    ]

    def __init__(self, view, player):
        self.player = player
        self.view = view
        self.show = False
        self._last_hovered = None
        self.engine = None  # set by Engine; needed for sprites and the turn manager
        self.trade_mode = False
        self.trade_cards = []
        self.trade_base = 0
        self.organize_cards()
        self.use_cards_automatic()

    def organize_cards(self):
        cards = self.player.cards
        if cards:
            # Wide gaps while they fit; overlap (like a hand) once there are
            # too many to lay out side by side.
            spacing = min(cards[0].width + 20, (self.view.WIDTH - 300 - cards[0].width) / max(len(cards) - 1, 1))
            total = spacing * (len(cards) - 1) + cards[0].width
        for index, card in enumerate(cards):
            card.pos = Position(
                x=self.view.WIDTH * 0.5 - total * 0.5 + spacing * index,
                y=self.view.HEIGHT * 0.5 - card.height * 0.5,
            )
            card.use = False

    def card_at(self, pos):
        """Topmost card under (x, y): the last one drawn."""
        for card in reversed(self.player.cards):
            if card.rect().collidepoint(pos):
                return card
        return None

    def sync_forced(self, forced):
        """While the player holds too many cards the menu is forced open:
        lay out the hand whenever it changes (cards just arrived) and
        preselect a set the first time it opens."""
        count = len(self.player.cards)
        if forced:
            if not self.show or count != getattr(self, "_forced_count", None):
                self.show = True
                self.organize_cards()
                self.use_cards_automatic()
            self._forced_count = count
        else:
            self._forced_count = None
        self.forced = forced

    def selected_trade_value(self):
        """Base value of the currently selected cards, or None if they
        aren't exactly three cards forming a valid set (three of a kind,
        or one of each; jokers stand in for anything)."""
        use_cards = [card for card in self.player.cards if card.use]
        if len(use_cards) != 3:
            return None
        possible_equal_sets, possible_different_set = self.check_set(use_cards)
        if possible_different_set:
            return 10
        if possible_equal_sets:
            return max(possible_equal_sets) * 2 + 4
        return None

    def _trade_button_rect(self):
        """The green Confirm button, where the phases put theirs."""
        from phases import Phase, image_button_shape
        _, x, y, w, h = image_button_shape(Phase.CONFIRM_X, Phase.ROW_Y)
        return pg.Rect(x, y, w, h)

    def _option_rect(self, index):
        return pg.Rect(self.view.WIDTH * 0.5 - 110, 60 + index * 58, 220, 50)

    def _back_rect(self):
        return pg.Rect(self.view.WIDTH * 0.5 - 60, 60 + 6 * 58 + 6, 120, 40)

    def _panel_rect(self):
        cards = self.player.cards
        if not cards:
            return pg.Rect(0, 0, 0, 0)
        left = min(card.pos.x for card in cards)
        right = max(card.pos.x + card.width for card in cards)
        return pg.Rect(left - 30, cards[0].pos.y - 40, right - left + 60, cards[0].height + 80)

    def _on_card_button(self, pos):
        # The cards button toggles the menu itself; don't close it twice.
        if self.engine is None:
            return False
        b = self.engine._card_button()
        return pg.Rect(b.pos.x, b.pos.y, b.width, b.height).collidepoint(pos)

    def can_trade_now(self):
        return self.engine is not None and self.engine.turn_manager.can_trade()

    def handle_input(self, io):
        """Runs before the phases each frame; a click it uses is consumed
        so it can't also hit whatever is under the menu on the map."""
        pos = (io.mouse_position.x, io.mouse_position.y)
        if self.trade_mode:
            if io.left_pressed:
                for index, (_, reward, mult) in enumerate(self.TRADE_OPTIONS):
                    if self._option_rect(index).collidepoint(pos):
                        self._execute_trade(reward, int(round(self.trade_base * mult)))
                        break
                else:
                    if self._back_rect().collidepoint(pos):
                        self.trade_mode = False
            io.left_pressed = 0
            return
        if not self.show:
            return
        if io.left_pressed:
            card = self.card_at(pos)
            if card is not None:
                card.use = not card.use
                io.left_pressed = 0
                return
            if not getattr(self, "forced", False) and not self._panel_rect().collidepoint(pos) \
                    and not self._trade_button_rect().collidepoint(pos) \
                    and not self._on_card_button(pos):
                self.show = False  # click outside the panel closes it
                io.left_pressed = 0
                return
        value = self.selected_trade_value()
        if value is not None and io.left_pressed and self._trade_button_rect().collidepoint(pos):
            io.left_pressed = 0
            if self.can_trade_now():
                self.trade_mode = True
                self.trade_base = value
                self.trade_cards = [card for card in self.player.cards if card.use]
            else:
                sounds.play("error")

    def _execute_trade(self, reward, amount):
        player = self.player
        for card in self.trade_cards:
            player.cards.remove(card)
        self.engine.log_action(player, " traded {} cards ({}) for {} {}".format(
            len(self.trade_cards), ", ".join(card.name for card in self.trade_cards),
            amount, "troops" if reward == "helmets" else reward))
        if reward == "helmets":
            self.engine.turn_manager.gain_troops(amount)
        else:
            setattr(player, reward, getattr(player, reward) + amount)
        self.trade_mode = False
        self.trade_cards = []
        self.show = False
        self.organize_cards()

    def draw(self, io, font):
        screen = self.view.screen
        if self.trade_mode:
            pg.draw.rect(screen, (235, 235, 245), pg.Rect(self.view.WIDTH * 0.5 - 130, 20, 260, 6 * 58 + 82))
            pg.draw.rect(screen, (0, 0, 0), pg.Rect(self.view.WIDTH * 0.5 - 130, 20, 260, 6 * 58 + 82), 3)
            screen.blit(font.render("Trade cards for:", True, (0, 0, 0)), (self.view.WIDTH * 0.5 - 60, 30))
            images = self.engine.hud_images
            mouse = (io.mouse_position.x, io.mouse_position.y)
            for index, (sprite, _, mult) in enumerate(self.TRADE_OPTIONS):
                rect = self._option_rect(index)
                hovered = rect.collidepoint(mouse)
                pg.draw.rect(screen, (190, 230, 190) if hovered else (215, 215, 215), rect)
                pg.draw.rect(screen, (0, 0, 0), rect, 3 if hovered else 2)
                image = images[sprite]
                iw, ih = image.image.get_size()
                image.draw(screen, Position(rect.x + 12 + (40 - iw) // 2, rect.y + 5 + (40 - ih) // 2))
                amount = int(round(self.trade_base * mult))
                screen.blit(font.render("X {}".format(amount), True, (0, 0, 0)), (rect.x + 75, rect.y + 13))
            back = self._back_rect()
            pg.draw.rect(screen, (245, 150, 150), back)
            pg.draw.rect(screen, (0, 0, 0), back, 2)
            screen.blit(font.render("Back", True, (0, 0, 0)), (back.x + 38, back.y + 9))
            return
        if not self.show:
            return
        if self.player.cards:
            # Panel in the cards button's colour behind the hand.
            panel = self._panel_rect()
            pg.draw.rect(screen, self.PANEL_COLOR, panel, border_radius=12)
            pg.draw.rect(screen, (0, 0, 0), panel, 3, border_radius=12)
        if getattr(self, "forced", False) and self.player.cards:
            warning = game_font(26).render(
                "WARNING you currently hold too many cards", True, (255, 255, 255))
            box = pg.Rect(0, 0, warning.get_width() + 30, warning.get_height() + 14)
            box.center = (int(self.view.WIDTH * 0.5), int(self.player.cards[0].pos.y) - 45)
            pg.draw.rect(screen, (190, 0, 0), box)
            pg.draw.rect(screen, (0, 0, 0), box, 3)
            screen.blit(warning, (box.x + 15, box.y + 7))
        # Whole hand face up; the hovered card is drawn last, on top.
        hovered = self.card_at((io.mouse_position.x, io.mouse_position.y))
        if hovered is not self._last_hovered and hovered is not None and hovered.type == 1:
            sounds.play("horse")  # only the horse card ('Paerd', card1)
        self._last_hovered = hovered
        for card in self.player.cards:
            if card is not hovered:
                card.draw(self.view)
        if hovered is not None:
            hovered.draw(self.view)
        if self.selected_trade_value() is not None:
            # The click itself is handled (and consumed) in handle_input.
            from phases import Phase, draw_confirm_button
            allowed = self.can_trade_now()
            draw_confirm_button(self.engine, Phase.CONFIRM_X, Phase.ROW_Y, allowed)
            if not allowed:
                self.engine.turn_manager.phases[0].blit_hint(
                    "Cards can only be traded in the recruitment phase")

    def use_cards_automatic(self):
        possible_equal_sets, possible_different_set = self.check_set(self.player.cards)
        if possible_different_set:
            for i in range(3):
                found_i = False
                for card in self.player.cards:
                    if card.type == i:
                        found_i = True
                        card.use = True
                        break
                if not found_i:
                    for card in self.player.cards:
                        if card.type == 3 and not card.use:
                            card.use = True
                            break
        else:
            if len(possible_equal_sets) > 0:
                for i in range(3):
                    found = False
                    for card in self.player.cards:
                        if card.type == max(possible_equal_sets) and not card.use:
                            found = True
                            card.use = True
                            break
                    if not found:
                        for card in self.player.cards:
                            if card.type == 3 and not card.use:
                                card.use = True
                                break

    @staticmethod
    def check_set(cardlist):
        possible_equal_sets = [i for i in range(3) if sum([k.type in {i, 3} for k in cardlist]) >= 3]
        possible_different_set = len(set([k.type for k in cardlist if k.type != 3])) + len(
            [k.type for k in cardlist if k.type == 3]) >= 3
        return possible_equal_sets, possible_different_set


class Reinforcement:

    def cards(self):


        def update_use_automatic(card_list):
            possible_equal_sets, possible_different_set = check_set(card_list)


    def reinforce(self):
        self.check_warning()
        self.feed_troops()
        self.add_resources()
        self.deploy_troops()

    def add_troops(self):
        pass

    def feed_troops(self):
        pass
