import math

import numpy as np
import pygame as pg
from pygame import gfxdraw
from matplotlib.path import Path
from player_colors import name_text_color, light_tint

# Countries whose conqueror has to drag a landmark onto them (from the
# settings menu) before ending their turn, and which sprite that is.
LANDMARKS = {"China": "pagoda", "Japan": "torii"}


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
        # The one free boat per game, still to be put on one of their
        # countries with the boat button in the recruitment phase.
        self.start_ship = start_ship
        # Movement phase (repositioning) is limited to one confirmed move
        # per turn; reset whenever the player re-enters that phase.
        self.repositioned_this_turn = False
        # Only one country may be developed per turn.
        self.developed_this_turn = False
        # Out of the game: no troops left on the board, never gets a turn.
        self.eliminated = False
        # Played by the computer (bot.py) instead of with the mouse, at a
        # difficulty level and with a personality (see bot.LEVELS and
        # bot.PERSONALITIES).
        self.is_bot = is_bot
        self.bot_level = "normal"
        self.bot_personality = "balanced"
        if self.color is None:
            self.color = 255 * np.random.rand(3)


class Kaertske:

    def __init__(
            self,
            type,
            images,
            width=110,
            height=150,
            color=(64, 224, 208),
            outline_color=(0, 0, 0),
            outline_width=2
    ):
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
        self.back_logo = images.get('spr_cards')
        self.back_color = (70, 80, 160)
        self.name = self.name_mapping[type]
        self.type = type
        self.use = False
        self.width = width
        self.height = height
        self.color = color
        self.outline_color = outline_color
        self.use_height = 20
        self.pos = Position(0, 0)
        self.outline_width = outline_width

    def rect(self):
        return pg.Rect(self.pos.x, self.pos.y - self.use_height * self.use, self.width, self.height)

    def draw(self, view, faceup=True):
        """Front: the sprite centred on the card. Back: a plain colour with
        the cards-menu logo in the middle."""
        rect = self.rect()
        pg.draw.rect(view.screen, self.color if faceup else self.back_color, rect)
        if faceup:
            sprite = self.sprite_mapping[self.type]
            sw, sh = sprite.image.get_size()
            sprite.draw(view.screen, Position(rect.x + (rect.w - sw) // 2, rect.y + (rect.h - sh) // 2))
        elif self.back_logo is not None:
            lw, lh = self.back_logo.image.get_size()
            self.back_logo.draw(view.screen, Position(rect.x + (rect.w - lw) // 2, rect.y + (rect.h - lh) // 2))
        pg.draw.rect(view.screen, self.outline_color, rect, self.outline_width)

    def update_use_manual(self, io):
        h = self.use_height * self.use
        if (
                self.pos.x < io.mouse_position.x < self.pos.x + self.width and
                self.pos.y - h < io.mouse_position.y < self.pos.y - h + self.height and
                io.left_pressed
        ):
            self.use = not self.use
            return True
        return False


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

    def point_in_country(self, point):
        for pol in getattr(self, "hit_polygon", self.raw_polygon):
            if Path(pol).contains_point((point.x, point.y)):
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

    def _draw_hazard_band(self, view, points, border_color, border_width, outline=True):
        """Yellow/black warning stripes along the inside of the border."""
        s = view.draw_scale
        band = max(2, int(round(self.HAZARD_BAND * s)))
        period = max(4, int(round(self.HAZARD_STRIPE * s)))
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0 + 2, max(ys) - y0 + 2
        if w < 4 or h < 4:
            return
        local = [(x - x0, y - y0) for x, y in points]
        # Band alpha = inside of the polygon AND within `band` px of its edge,
        # built with plain alpha blends (no Mask.to_surface, which came out
        # as a solid box on some display surface formats).
        band_alpha = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.polygon(band_alpha, (255, 255, 255, 255), local)
        edge = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.polygon(edge, (255, 255, 255, 255), local, band * 2)
        band_alpha.blit(edge, (0, 0), special_flags=pg.BLEND_RGBA_MIN)
        stripes = pg.Surface((w, h), pg.SRCALPHA)
        stripes.fill((25, 25, 25, 255))
        k = -h
        while k < w + h:
            pg.draw.polygon(stripes, (250, 210, 0, 255),
                            [(k, 0), (k + period // 2, 0), (k + period // 2 + h, h), (k + h, h)])
            k += period
        stripes.blit(band_alpha, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        view.map_surface.blit(stripes, (x0, y0))
        # Blitting a translucent surface onto a display-format surface also
        # blends its alpha channel, leaving transparent (alpha 0) pixels
        # that show up as a solid box on screen -- put full opacity back.
        view.map_surface.fill((0, 0, 0, 255), pg.Rect(x0, y0, w, h), special_flags=pg.BLEND_RGBA_MAX)
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
        # A white die with a thick border and eyes in the owning player's
        # colour. `eyes` of 0 draws a blank (not yet rolled) die.
        color = tuple(int(c) for c in np.clip(self.color, 0, 255))
        square = pg.Rect(pos.x - 0.5 * size, pos.y - 0.5 * size, size, size)
        pg.draw.rect(screen, (255, 255, 255), square, border_radius=10)
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

    def release_button(self, function_to_execute, io):
        mouse_in_button = (self.pos.x < io.mouse_position.x < self.pos.x + self.width and
                           self.pos.y < io.mouse_position.y < self.pos.y + self.height)
        if mouse_in_button and io.left_pressed:
            function_to_execute()


class Gui:

    def __init__(
            self,
            io,
            gray1=(200, 200, 200),
            gray2=(150, 150, 150),
            width=150,
            height=340,
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
            self.gray2,
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
        owner_rows = -(-len(self.OWNER_CELLS) // 3)  # ceil div, 3 per row
        panel_h = base_h + (20 + owner_rows * 28 + 6 if owner_stats else 0)

        x0 = view.WIDTH - self.width
        pg.draw.rect(view.screen, self.gray1, pg.Rect(x0, 0, self.width, panel_h))
        pg.draw.line(view.screen, self.outline_color, (x0, panel_h), (view.WIDTH, panel_h), 2)

        name = font.render(country.name, True, self.outline_color)
        avail = self.width - 16
        if name.get_width() > avail:
            # Long names (e.g. Papoea Nieuw Guinea) get a smaller font.
            if not hasattr(self, "small_font"):
                self.small_font = pg.font.SysFont("Times New Roman", 15)
            name = self.small_font.render(country.name, True, self.outline_color)
        view.screen.blit(name, (x0 + 8, 2))
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
            self.small_font = pg.font.SysFont("Times New Roman", 15)
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

        if owner_stats:
            owner, amounts, mini = owner_stats
            if not hasattr(self, "small_font"):
                self.small_font = pg.font.SysFont("Times New Roman", 15)
            pg.draw.line(view.screen, self.outline_color, (x0, base_h - 3), (view.WIDTH, base_h - 3), 1)
            pg.draw.rect(view.screen, owner.color, pg.Rect(x0, base_h, self.width, 20))
            view.screen.blit(self.small_font.render(owner.name, True, name_text_color(owner.color)), (x0 + 8, base_h + 1))
            for i, (sprite, key) in enumerate(self.OWNER_CELLS):
                cx = x0 + 6 + (i % 3) * 48
                cy = base_h + 24 + (i // 3) * 28
                image = mini[sprite]
                iw, ih = image.image.get_size()
                image.draw(view.screen, Position(cx + (20 - iw) // 2, cy + (20 - ih) // 2))
                view.screen.blit(self.small_font.render(str(amounts[key]), True, self.outline_color), (cx + 22, cy + 2))

    # Player panel layout (all in logical UI pixels): a name header, then
    # one row per resource, with enough clearance below the last row that
    # it doesn't crowd the phase-selector buttons anchored to the bottom.
    PLAYER_HEADER_H = 24
    PLAYER_ROWS_TOP_PAD = 6
    PLAYER_ROW_H = 42

    def draw_player_stats(self, view, player, font, images, production=None):
        if not hasattr(self, "small_font"):
            self.small_font = pg.font.SysFont("Times New Roman", 15)
        x0 = view.WIDTH - self.width
        y0 = view.HEIGHT - self.height

        header_rect = pg.Rect(x0, y0, self.width, self.PLAYER_HEADER_H)
        pg.draw.rect(view.screen, player.color, header_rect)
        if not hasattr(self, "bold_font"):
            self.bold_font = pg.font.SysFont("Times New Roman", 20, bold=True)
        label = player.name + (" (bot)" if player.is_bot else "")
        name = self.bold_font.render(label, True, name_text_color(player.color))
        view.screen.blit(name, (x0 + 10, header_rect.centery - name.get_height() // 2))

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
            pos = Position(x0 + 8, rows_top + index * self.PLAYER_ROW_H)
            iw, ih = image.image.get_size()
            image.draw(view.screen, pos + Position((40 - iw) // 2, (40 - ih) // 2))
            text = font.render("{}".format(amount), True, self.outline_color)
            text_pos = pos + Position(48, (40 - text.get_height()) // 2)
            view.screen.blit(text, text_pos.to_tuple())
            if production is not None and index < 5:  # no bracket for troops
                gain = production[resource_names[index]]
                color = (0, 120, 0) if gain > 0 else (170, 0, 0) if gain < 0 else self.outline_color
                bracket = self.small_font.render("({:+d})".format(gain), True, color)
                view.screen.blit(bracket, (text_pos.x + text.get_width() + 6, pos.y + 13))

    phase_button_radius = 21

    def phase_button_center(self, view, index):
        """Center of the index-th phase button (reinforce/attack/move)."""
        return view.WIDTH - self.width + 5 + self.phase_button_radius + 48 * index, view.HEIGHT - 26

    def phase_button_hit(self, view, index, pos):
        cx, cy = self.phase_button_center(view, index)
        return (pos.x - cx) ** 2 + (pos.y - cy) ** 2 <= self.phase_button_radius ** 2

    def draw_attack_phase(
            self,
            view,
            player,
            images=None,
            outline_color=(0, 0, 0),
            colors=[(224, 224, 0), (255, 80, 79), (255, 165, 0)],
            icon_keys=("spr_recruit_phase", "spr_attack_phase", "spr_move_phase"),
            outline_width=2,
    ):
        if not hasattr(self, "_phase_dim_overlay"):
            # A translucent dark circle dropped over a phase button dims
            # its fill and icon together, without touching the (shared)
            # icon images themselves.
            d = self.phase_button_radius * 2
            overlay = pg.Surface((d, d), pg.SRCALPHA)
            pg.draw.circle(overlay, (15, 15, 15, 150), (self.phase_button_radius, self.phase_button_radius), self.phase_button_radius)
            self._phase_dim_overlay = overlay

        for index, color in enumerate(colors):
            center = self.phase_button_center(view, index)
            hovered = self.phase_button_hit(view, index, self.io.mouse_position)
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


class Shop:
    def __init__(self):
        print('shop')


class CardMenu:

    # (label, reward attribute, multiplier of the trade's base value)
    TRADE_OPTIONS = [
        ("spr_troops", "helmets", 1.5),
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
        return pg.Rect(self.view.WIDTH * 0.5 - 100, self.view.HEIGHT - 100, 200, 50)

    def _option_rect(self, index):
        return pg.Rect(self.view.WIDTH * 0.5 - 110, 60 + index * 58, 220, 50)

    def _back_rect(self):
        return pg.Rect(self.view.WIDTH * 0.5 - 60, 60 + 6 * 58 + 6, 120, 40)

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
        value = self.selected_trade_value()
        if value is not None and io.left_pressed and self._trade_button_rect().collidepoint(pos):
            io.left_pressed = 0
            if self.can_trade_now():
                self.trade_mode = True
                self.trade_base = value
                self.trade_cards = [card for card in self.player.cards if card.use]

    def _execute_trade(self, reward, amount):
        player = self.player
        for card in self.trade_cards:
            player.cards.remove(card)
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
        if getattr(self, "forced", False) and self.player.cards:
            warning = pg.font.SysFont("Times New Roman", 26).render(
                "WARNING you currently hold too many cards", True, (255, 255, 255))
            box = pg.Rect(0, 0, warning.get_width() + 30, warning.get_height() + 14)
            box.center = (int(self.view.WIDTH * 0.5), int(self.player.cards[0].pos.y) - 45)
            pg.draw.rect(screen, (190, 0, 0), box)
            pg.draw.rect(screen, (0, 0, 0), box, 3)
            screen.blit(warning, (box.x + 15, box.y + 7))
        # Hidden hand: backs only, until the mouse is over a card.
        hovered = self.card_at((io.mouse_position.x, io.mouse_position.y))
        for card in self.player.cards:
            if card is not hovered:
                card.draw(self.view, faceup=False)
        if hovered is not None:
            hovered.draw(self.view, faceup=True)
        if self.selected_trade_value() is not None:
            rect = self._trade_button_rect()
            allowed = self.can_trade_now()
            hovered = allowed and rect.collidepoint((io.mouse_position.x, io.mouse_position.y))
            pg.draw.rect(screen, ((255, 60, 60) if hovered else (255, 0, 0)) if allowed else (170, 170, 170), rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 2)
            screen.blit(font.render("TRADE", True, (0, 0, 0)), (rect.x + 70, rect.y + 12))
            if not allowed:
                screen.blit(font.render("Finish your current action first", True, (0, 0, 0)), (rect.x - 25, rect.y - 28))

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
