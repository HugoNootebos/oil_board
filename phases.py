"""
Turn-phase state machine, rewritten from the procedural running.py loop.

Each game phase (reinforcement, attack, movement, shop) is a
`Phase` subclass with an `update()` method that is called once per frame. A
`TurnManager` owns all phases, shared per-turn state, and the small amount of
global logic (end-turn buttons, the "too many cards" warning, opening/closing
the shop from anywhere).

Country/connection lookups use country *names* (dict keys), matching
board.py / models.py, instead of the list indices running.py used.
"""

import pygame as pg
from fonts import game_font
from lang import t, Msg, Join
import sounds
import numpy as np

from models import Position, Dice, Kaertske, LANDMARKS, random_card_type
from board import CONTINENTS
from events import EVENTS

# Kaertskes awarded at the start of a turn for holding a whole continent.
CONTINENT_CARD_BONUS = {"Asia": 2, "Europe": 1, "Africa": 1, "North America": 1}


def income_multiplier(engine, country, player):
    """How many times over `country` yields its (non-troop) resources at
    the start of `player`'s turn: developed countries double, except the
    first income after developing, which is nothing unless someone else
    took the country meanwhile or the player holds its whole continent."""
    mult = 2 if country.developed else 1
    if country.dormant_owner is not None:
        holds_continent = all(
            engine.countries[n].owner == player
            for members in CONTINENTS.values() if country.name in members
            for n in members
        )
        if country.dormant_owner is player and not holds_continent:
            mult = 0
    return mult


_ASSET_ICONS = {}
_IMAGE_BUTTONS = {}

# Confirm / cancel buttons are images/<name>_button.png, drawn at their own
# size (pixel art, 4 px a pixel; scaled nearest-neighbour if that changes).
IMAGE_BUTTON_W, IMAGE_BUTTON_H = 128, 68
# develop_button.png, train_button.png and plane_button.png are 60x41
# pixel art (at 1, 4 and 4 px a pixel): drawn at 2.
PICTURE_BUTTON_SIZE = (120, 82)


def image_button_shape(cx, cy, size=(IMAGE_BUTTON_W, IMAGE_BUTTON_H)):
    """Hit area ("r", x, y, w, h) of an image button centred on (cx, cy)."""
    w, h = size
    return ("r", int(cx) - w // 2, int(cy) - h // 2, w, h)


def draw_image_button(engine, cx, cy, name, enabled=True, size=(IMAGE_BUTTON_W, IMAGE_BUTTON_H)):
    """Rectangular button images/<name>_button.png, `size` big and centred
    on (cx, cy) in logical UI coordinates. Returns True when it was
    clicked; a disabled one is drawn washed-out grey and never reports a
    click."""
    if (name, size) not in _IMAGE_BUTTONS:
        image = pg.transform.scale(
            pg.image.load("./images/{}_button.png".format(name)).convert_alpha(), size)
        hover = image.copy()
        hover.fill((25, 25, 25), special_flags=pg.BLEND_RGB_ADD)
        # Grey, halfway to (170, 170, 170).
        # (Not pg.transform.grayscale: in pygame-ce 2.5 it garbles alpha.)
        disabled = image.copy()
        rgb = pg.surfarray.pixels3d(disabled)
        rgb[...] = (rgb @ np.array([0.299, 0.587, 0.114]) * 0.5 + 85).astype(np.uint8)[..., None]
        del rgb  # unlocks the surface
        _IMAGE_BUTTONS[(name, size)] = image, hover, disabled
    image, hover, disabled = _IMAGE_BUTTONS[(name, size)]
    shape = image_button_shape(cx, cy, size)
    if not enabled:
        image = disabled
    elif engine.io._contains(shape, engine.io.mouse_position):
        image = hover
    engine.view.screen.blit(image, shape[1:3])
    clicked = engine.io.button(shape)
    if clicked and not enabled:
        sounds.play("error")
    return bool(enabled and clicked)


def draw_confirm_button(engine, cx, cy, enabled=True):
    """Green confirm button (confirm_button.png)."""
    return draw_image_button(engine, cx, cy, "confirm", enabled)


def draw_cancel_button(engine, cx, cy):
    """Red cancel button (cancel_button.png)."""
    return draw_image_button(engine, cx, cy, "cancel")


class IconNotice(str):
    """A notice text that also names a sprite (images/<icon>.png) for its pop-up."""

    def __new__(cls, text, icon):
        obj = super().__new__(cls, text)
        obj.icon = icon
        return obj


class Phase:
    """Base class for a single turn-phase (a value of player.attack)."""

    # Whether the rail screen may start attacks on unclaimed countries.
    rail_attack = False

    def _rail_attack_targets(self, origin):
        return set()

    def _air_attack_targets(self):
        return set()

    def __init__(self, manager):
        self.manager = manager

    @property
    def engine(self):
        return self.manager.engine

    @property
    def player(self):
        return self.engine.players[self.engine.turn]

    @property
    def io(self):
        return self.engine.io

    @property
    def view(self):
        return self.engine.view

    # --- small drawing/input helpers -------------------------------------

    def mouse_in(self, x0, y0, x1, y1):
        p = self.io.mouse_position
        return x0 <= p.x <= x1 and y0 <= p.y <= y1

    def clicked(self, x0, y0, x1, y1):
        return self.io.button(("r", x0, y0, x1 - x0, y1 - y0))

    def clicked_if(self, x0, y0, x1, y1, allowed):
        """A click on a button that only works when `allowed`; a click on it
        when it doesn't gives the error sound instead."""
        if not self.clicked(x0, y0, x1, y1):
            return False
        if not allowed:
            sounds.play("error")
        return bool(allowed)

    # Attack dice: thrown ones in the middle of the screen (attacker's row,
    # defender's row below it), the dice to pick from further down.
    THROWN_ATTACK_Y = 245
    THROWN_DEFENCE_Y = 325
    PICK_DICE_Y = 450
    PICK_TEXT_Y = 415

    def dice_x(self, index, count):
        """Left edge of die `index` in a centred row of `count` 70px dice."""
        return int(self.view.WIDTH * 0.5 - 40 * (count - 1) - 35 + 80 * index)

    def thrown_columns(self):
        """Number of columns for the thrown dice: attack die i is compared to
        defence die i, so both rows use the same columns."""
        attack = sum(1 for d in self.attack_dice if d > 0)
        defence = sum(1 for d in self.defence_dice if d > 0)
        return max(attack, defence, 1)

    def draw_rect(self, color, x, y, w, h, width=0):
        import pygame as pg
        pg.draw.rect(self.view.screen, color, pg.Rect(x, y, w, h), width)

    def draw_circle(self, color, cx, cy, radius, width=0):
        import pygame as pg
        pg.draw.circle(self.view.screen, color, (int(cx), int(cy)), radius, width)

    def in_circle(self, cx, cy, radius):
        p = self.io.mouse_position
        return (p.x - cx) ** 2 + (p.y - cy) ** 2 <= radius ** 2

    def clicked_circle(self, cx, cy, radius):
        return self.io.button(("c", cx, cy, radius))

    def confirm_button(self, cx, cy, enabled=True):
        """Green confirm button; True when clicked. See draw_confirm_button."""
        return draw_confirm_button(self.engine, cx, cy, enabled)

    def cancel_button(self, cx, cy):
        """Red cancel button; True when clicked."""
        return draw_cancel_button(self.engine, cx, cy)

    # Pop-ups closed by a click anywhere (the attack's asset panel, the
    # defender's tanks): light blue, with a hint along the bottom. They
    # ignore clicks for POPUP_GRACE_MS after opening, so a double click on
    # what opened them (the attacker's roll, for the defender's tanks)
    # can't close them unseen.
    POPUP_COLOR = (160, 200, 240)
    POPUP_HINT_COLOR = (40, 60, 110)
    POPUP_GRACE_MS = 500
    popup_opened_at = 0
    _popup_hint_font = None

    def open_popup(self, subattack):
        """Go to `subattack`, whose screen is a click-anywhere pop-up."""
        self.player.subattack = subattack
        self.popup_opened_at = pg.time.get_ticks()

    def click_anywhere_popup(self, x, y, w, h):
        """Draw a click-anywhere pop-up's box (its own buttons go on top,
        drawn after this). True when it's clicked anywhere but on a button
        -- its own or the HUD's -- once it's been open POPUP_GRACE_MS."""
        self.draw_rect(self.POPUP_COLOR, x, y, w, h)
        self.draw_rect((0, 0, 0), x, y, w, h, 3)
        if Phase._popup_hint_font is None:
            Phase._popup_hint_font = game_font(15)
        hint = self._popup_hint_font.render(t("Click anywhere to continue"), True, self.POPUP_HINT_COLOR)
        self.view.screen.blit(hint, hint.get_rect(midbottom=(int(x + w * 0.5), int(y + h - 12))))
        # The box counts as a button under its own ones, so a click on it
        # can't reach the map behind (e.g. reselect the attacker).
        on_box = self.io.button(("r", x, y, w, h))
        return (bool(self.io.left_pressed) and (on_box or self.io.top_button is None)
                and pg.time.get_ticks() - self.popup_opened_at >= self.POPUP_GRACE_MS)

    # Confirm / cancel sit just left of the player panel (150 wide), cancel
    # on the right, their bottoms 8 px above the bottom of the screen. The
    # develop / rails / airport buttons go in a column at the left edge
    # (_left_button_pos).
    BUTTON_GAP = 8
    BUTTON_BOTTOM = 640 - 8
    ROW_Y = BUTTON_BOTTOM - IMAGE_BUTTON_H // 2
    CANCEL_X = 960 - 150 - BUTTON_GAP - IMAGE_BUTTON_W // 2
    CONFIRM_X = CANCEL_X - IMAGE_BUTTON_W - BUTTON_GAP

    ASSETS_BUTTON_SIZE = 56

    def assets_button(self, x, y):
        """Square button with a ship, plane and tank on it, top-left at
        (x, y); True when clicked."""
        import pygame as pg
        size = self.ASSETS_BUTTON_SIZE
        sprite = 24
        if "ship" not in _ASSET_ICONS:
            for name in ("ship", "plane", "tank"):
                _ASSET_ICONS[name] = pg.transform.smoothscale(
                    pg.image.load("./images/{}.png".format(name)).convert_alpha(), (sprite, sprite))
        self.draw_rect((180, 180, 255), x, y, size, size)
        self.draw_rect((0, 0, 0), x, y, size, size, 2)
        screen = self.view.screen
        screen.blit(_ASSET_ICONS["ship"], (x + 3, y + 4))
        screen.blit(_ASSET_ICONS["plane"], (x + size - sprite - 3, y + 4))
        screen.blit(_ASSET_ICONS["tank"], (x + (size - sprite) // 2, y + size - sprite - 4))
        return self.clicked(x, y, x + size, y + size)

    def blit_text(self, text, x, y, color=(0, 0, 0)):
        self.view.screen.blit(self.engine.font.render(text, True, color), (x, y))

    HINT_COLOR = (245, 130, 130)

    def _draw_reinforcements(self, count):
        """Troops left to deploy: the troop-card soldier with a signed
        number over it, just left of the player panel (10 px further than
        the cancel button) and level with its helmet row."""
        import pygame as pg
        view = self.view
        gui = self.engine.gui
        height = 48
        if "reinforcements" not in _ASSET_ICONS:
            sprite = pg.image.load("./images/card0.png").convert_alpha()
            _ASSET_ICONS["reinforcements"] = pg.transform.smoothscale(
                sprite, (round(sprite.get_width() * height / sprite.get_height()), height))
        sprite = _ASSET_ICONS["reinforcements"]
        right = view.WIDTH - gui.width - self.BUTTON_GAP - 10
        cx = right - sprite.get_width() // 2
        cy = gui.player_row_center_y(view, gui.HELMET_ROW)
        view.screen.blit(sprite, (right - sprite.get_width(), cy - height // 2))
        label = ("+" if count >= 0 else "-") + str(abs(count))
        text = self.engine.font.render(label, True, (0, 0, 0))
        outline = self.engine.font.render(label, True, (255, 255, 255))
        x, y = cx - text.get_width() // 2, cy - text.get_height() // 2
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    view.screen.blit(outline, (x + dx, y + dy))
        view.screen.blit(text, (x, y))

    def blit_hint(self, text):
        """A warning/hint line: black text on a light red box flush with the
        top of the action log box (bottom-left); several stack upward."""
        engine = self.engine
        rect = engine._action_box_rect()
        top = rect.y if rect else self.view.HEIGHT - engine.ACTION_BOX_H
        surf = engine.font.render(text, True, (0, 0, 0))
        box = pg.Rect(0, 0, surf.get_width() + 20, surf.get_height() + 8)
        box.bottomleft = (0, top - engine.hint_rows * box.h)
        engine.hint_rows += 1
        bg = pg.Surface(box.size, pg.SRCALPHA)
        bg.fill(self.HINT_COLOR + (204,))  # same 80% as the action log box
        self.view.screen.blit(bg, box.topleft)
        self.view.screen.blit(surf, (box.x + 10, box.y + 4))

    def connected(self, a, b, kind=None):
        for c in self.engine.connections:
            if a in c and b in c and (kind is None or c.kind == kind):
                return True
        return False

    def take_last_country(self, player, country):
        """`player` has just taken `country` from its owner (by conquest or
        by nuking it empty). If it was the owner's last country, they're
        eliminated by `player`: all their wood/steel/nuclear/oil and cards
        go to `player`, and it counts as conquering an enemy this turn."""
        engine = self.engine
        loser = country.owner
        if loser is engine.default_player or loser is player:
            return
        if any(c.owner is loser and c is not country for c in engine.countries.values()):
            return
        self.manager.conquered_enemy_this_turn = True
        resources = ("wood", "steel", "nuclear", "oil", "food")
        before = {r: getattr(player, r) for r in resources}
        cards_before = len(player.cards)
        player.wood += loser.wood
        player.steel += loser.steel
        player.nuclear += loser.nuclear
        player.oil += loser.oil
        player.cards += loser.cards
        loser.wood = loser.steel = loser.nuclear = loser.oil = 0
        loser.cards = []
        if self.manager.current_event is not None:
            self.manager.current_event.on_player_eliminated(engine, player, loser)
        # Remembered for the "has been eliminated" notice, shown once
        # _check_eliminations notices they're gone.
        gained = [(getattr(player, r) - before[r], r) for r in resources]
        gained.append((len(player.cards) - cards_before, "cards"))
        self.manager.elimination_loot[loser] = (player, [(n, r) for n, r in gained if n > 0])

    def abandon(self, country):
        """Hand a country over to the neutral default_player. Nobody is
        left to crew/maintain any ships, tanks, planes, forts or nukes
        sitting there, so they're destroyed along with the ownership
        change, and its garrison resets to whatever board.py originally
        put there (some countries start at 1, not the usual 2)."""
        self.engine.log_wiped(country)
        country.owner = self.engine.default_player
        country.units = self.engine.initial_country_units.get(country.name, 2)
        event = self.manager.current_event
        if event is not None:
            country.units = event.abandoned_units(self.engine, country, country.units)
        country.ships = 0
        country.tanks = 0
        country.planes = 0
        country.fort_lvl = 0
        country.landmark_owner = None
        # Radioactivity (and who dropped it) survives abandonment -- it's
        # a property of the ground itself, not of who happens to hold it.

    # --- rail network redistribution ---------------------------------
    # Shared by any phase with a notion of a currently-selected origin
    # country (AttackPhase.attack_from, MovementPhase.origin_country):
    # a circular button pops up to spend 1 oil and freely redistribute
    # troops and tanks among every one of the player's countries reachable
    # purely by hopping along built rails (or, by air, among all their
    # airports).

    def _init_rail_state(self):
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_initial_tanks = {}
        self.rail_initial_planes = {}
        self.rail_pool = 0
        self.rail_tank_pool = 0
        self.rail_plane_pool = 0
        # Which of "units"/"tanks"/"planes" (by air only) clicks on the
        # redistribute screen move.
        self.rail_resource = "units"
        self._rail_return_subattack = 0
        self._rail_mode_subattack = None  # subclasses set this
        # "rails" or "air": which network the redistribute screen is
        # currently working on.
        self._redistribute_kind = "rails"
        # Last country a pool troop was dropped into on the rail screen.
        self.rail_last_added = None
        # True on the frame the redistribute screen was entered, so the
        # click that opened it can't also press a button drawn under it.
        self._rail_just_entered = False

    def _compute_rail_network(self, origin, player):
        """Countries owned by `player` reachable from `origin` by hopping
        only along rail connections. Travel may pass freely through
        default_player (unclaimed) territory, but is blocked as soon as it
        would have to cross a country owned by another player."""
        visited = self._rail_reachable(origin, player)
        return {name for name in visited if self.engine.countries[name].owner == player}

    def _rail_reachable(self, origin, player):
        """Every country (own or unclaimed) the rails lead to from origin."""
        engine = self.engine
        visited = {origin}
        frontier = {origin}
        while frontier:
            next_frontier = set()
            for name in frontier:
                for c in engine.connections:
                    if not getattr(c, "rails", False) or name not in c:
                        continue
                    for other in c.connection:
                        if other == name or other in visited:
                            continue
                        owner = engine.countries[other].owner
                        if owner == player or owner == engine.default_player:
                            visited.add(other)
                            next_frontier.add(other)
            frontier = next_frontier
        return visited

    def _draw_oil_cost_above(self, cx, cy, cost, half_h=IMAGE_BUTTON_H // 2):
        """"-N <oil>" label (half-size oil sprite) centred over the button
        at (cx, cy), `half_h` half its height (a confirm button's by
        default); nothing when cost is 0."""
        if cost <= 0:
            return
        if "oil_small" not in _ASSET_ICONS:
            image = self.engine.hud_images["spr_oil"].image
            w, h = image.get_size()
            _ASSET_ICONS["oil_small"] = pg.transform.smoothscale(image, (w // 2, h // 2))
        oil = _ASSET_ICONS["oil_small"]
        font = self.engine.font
        text = "-{}".format(cost)
        text_w, text_h = font.size(text)
        row_h = max(text_h, oil.get_height())
        x = cx - (text_w + 3 + oil.get_width()) // 2
        top = cy - half_h - 4 - row_h
        screen = self.view.screen
        screen.blit(font.render(text, True, (0, 0, 0)), (x, top + (row_h - text_h) // 2))
        screen.blit(oil, (x + text_w + 3, top + (row_h - oil.get_height()) // 2))

    def _redistribute_button(self, slot, icon_name, enabled=True):
        """Button images/<icon_name>_button.png in the left column, rails
        (slot 0) above develop's spot, airport (1) above that, with its
        "-1 [oil]" cost to its right. Returns True when clicked."""
        cx, cy = self._left_button_pos(1 + slot)
        self._draw_oil_cost_beside(cx + PICTURE_BUTTON_SIZE[0] // 2 + self.BUTTON_GAP, cy, 1)
        return draw_image_button(self.engine, cx, cy, icon_name, enabled, PICTURE_BUTTON_SIZE)

    def _left_button_pos(self, row):
        """Centre of a picture button in the left column: row 0 (develop)
        at the bottom, room for one hint box (blit_hint) left between it
        and the action log box; row 1 (rails) above it, row 2 (airport)
        above that."""
        engine = self.engine
        w, h = PICTURE_BUTTON_SIZE
        hint_h = engine.font.get_height() + 8
        bottom = self.view.HEIGHT - engine.ACTION_BOX_H - hint_h - self.BUTTON_GAP
        return self.BUTTON_GAP + w // 2, bottom - h // 2 - row * (h + self.BUTTON_GAP)

    def _draw_oil_cost_beside(self, x, cy, cost):
        """"-N <oil>" label (half-size oil sprite) from x, centred on cy."""
        if "oil_small" not in _ASSET_ICONS:
            image = self.engine.hud_images["spr_oil"].image
            iw, ih = image.get_size()
            _ASSET_ICONS["oil_small"] = pg.transform.smoothscale(image, (iw // 2, ih // 2))
        oil = _ASSET_ICONS["oil_small"]
        text = self.engine.font.render("-{}".format(cost), True, (0, 0, 0))
        screen = self.view.screen
        screen.blit(text, (x, cy - text.get_height() // 2))
        screen.blit(oil, (x + text.get_width() + 3, cy - oil.get_height() // 2))

    def _draw_rails_button(self, origin, allowed_subs):
        player = self.player
        if origin is None or player.subattack not in allowed_subs:
            return
        network = self._compute_rail_network(origin, player)
        if len(network) <= 1 and not (self.rail_attack and self._rail_attack_targets(origin)):
            return

        if self._redistribute_button(0, "train", player.oil >= 1):
            self._enter_redistribute(network, "rails")

    def _enter_redistribute(self, network, kind):
        """Pay the 1 oil and open the redistribute screen for `network`
        (a set of the player's country names), by "rails" or "air"."""
        engine = self.engine
        player = self.player
        player.oil -= 1
        self.rail_network = sorted(network)
        self.rail_initial_units = {name: engine.countries[name].units for name in self.rail_network}
        self.rail_initial_tanks = {name: engine.countries[name].tanks for name in self.rail_network}
        self.rail_initial_planes = {name: engine.countries[name].planes for name in self.rail_network}
        self.rail_pool = 0
        self.rail_tank_pool = 0
        self.rail_plane_pool = 0
        self.rail_resource = "units"
        self.rail_last_added = None
        self._redistribute_kind = kind
        self._rail_return_subattack = player.subattack
        self._rail_just_entered = True
        player.subattack = self._rail_mode_subattack

    def _draw_airport_button(self, origin, allowed_subs):
        """Like the rails button, but links every airport the player owns.
        Needs the origin to be one of them, a plane at some airport and
        at least 1 oil; troops and tanks then move freely between all
        airports."""
        player = self.player
        engine = self.engine
        if origin is None or player.subattack not in allowed_subs:
            return
        if not engine.countries[origin].airport or engine.countries[origin].owner != player:
            return
        network = {n for n, c in engine.countries.items() if c.owner == player and c.airport}
        if player.oil < 1 or not any(engine.countries[n].planes > 0 for n in network):
            return
        if len(network) <= 1 and not (self.rail_attack and self._air_attack_targets()):
            return

        if self._redistribute_button(1, "plane"):
            self._enter_redistribute(network, "air")

    def _redistribute_rails(self):
        engine = self.engine
        player = self.player
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT

        by_air = self._redistribute_kind == "air"
        # Resource selector, as on the movement screen (troops and tanks;
        # boats can't go by rail or air, and planes only move between
        # airports): each pool's sprite with its count, click one to pick it.
        pools = [("units", "spr_troops", self.rail_pool), ("tanks", "spr_tank", self.rail_tank_pool)]
        if by_air:
            pools.append(("planes", "spr_plane", self.rail_plane_pool))
        picked = self._resource_selector(pools, self.rail_resource)
        if picked is not None:
            self.rail_resource = picked
        pool_attr = {"units": "rail_pool", "tanks": "rail_tank_pool", "planes": "rail_plane_pool"}[self.rail_resource]

        # As when deploying troops: left-click a country to put one there
        # from the pool, right-click to take one out into the pool.
        hover = self.io.hover_country
        if hover in self.rail_network and (self.io.left_pressed or self.io.right_clicked):
            country = engine.countries[hover]
            key = self.rail_resource
            pool = getattr(self, pool_attr)
            if self.io.left_pressed and pool > 0:
                setattr(country, key, getattr(country, key) + 1)
                setattr(self, pool_attr, pool - 1)
                self.rail_last_added = hover
            elif self.io.right_clicked:
                if getattr(country, key) > 0:
                    setattr(country, key, getattr(country, key) - 1)
                    setattr(self, pool_attr, pool + 1)
                else:
                    sounds.play("error")  # nothing of that kind to take out
        elif hover is not None and self.io.right_clicked:
            sounds.play("error")  # not on the network

        if any(engine.countries[n].units == 0 and (engine.countries[n].tanks > 0 or engine.countries[n].planes > 0)
               for n in self.rail_network):
            self.blit_hint(t("Tanks and planes in an emptied country are lost on Confirm"))

        done_active = self.rail_pool == 0 and self.rail_tank_pool == 0 and self.rail_plane_pool == 0
        confirm_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y, done_active)
        cancel_clicked = self.cancel_button(self.CANCEL_X, self.ROW_Y) and not self._rail_just_entered
        self._rail_just_entered = False
        if cancel_clicked:
            self._cancel_redistribute()
        elif confirm_clicked:
            self._finish_redistribute()
        else:
            self._rail_extra(done_active)

    SELECT_GLOW = (255, 220, 60)
    _selector_icons = {}

    def _selector_icon(self, sprite):
        """Sprite for the resource selector (cached): troops as the
        troop-card soldier, 56 px tall; the rest 44 px square."""
        if sprite not in self._selector_icons:
            if sprite == "spr_troops":
                surf = self.engine.images["spr_card0"].image
                size = (round(surf.get_width() * 56 / surf.get_height()), 56)
            else:
                surf = self.engine.images[sprite].image
                size = (44, 44)
            self._selector_icons[sprite] = pg.transform.smoothscale(surf, size)
        return self._selector_icons[sprite]

    _glow = None

    def _selector_glow(self):
        """Soft yellow disc that marks the selected resource (cached)."""
        if Phase._glow is None:
            radius = 42
            surf = pg.Surface((radius * 2, radius * 2), pg.SRCALPHA)
            for r in range(radius, 0, -1):
                alpha = int(255 * min(1, 1.6 * (1 - r / radius)) ** 0.9)
                pg.draw.circle(surf, self.SELECT_GLOW + (alpha,), (radius, radius), r)
            Phase._glow = surf
        return Phase._glow

    SELECTOR_STEP = 67  # between sprite centres

    def _resource_selector(self, items, selected, y=22, disabled=()):
        """Row of resource sprites centred at the top: a glow behind the
        selected one, a click picks one (returned, else None). Items are
        (key, sprite, count); a count is drawn on the sprite (dimmed while
        0) unless it is None. Keys in `disabled` are dimmed and only give
        the error sound when clicked. The default `y` centres the row on
        the HUD buttons (cards button: top 20, 60 high)."""
        screen = self.view.screen
        font = pg.font.Font(None, 30)
        step = self.SELECTOR_STEP
        left = (self.view.WIDTH - ((len(items) - 1) * step + 80)) // 2
        picked = None
        for i, (key, sprite, count) in enumerate(items):
            cx, cy = left + i * step + 40, y + 28
            if key == selected:
                glow = self._selector_glow()
                screen.blit(glow, (cx - glow.get_width() // 2, cy - glow.get_height() // 2))
            icon = self._selector_icon(sprite)
            if count == 0 or key in disabled:
                icon = icon.copy()
                icon.fill((255, 255, 255, 110), special_flags=pg.BLEND_RGBA_MULT)
            screen.blit(icon, (cx - icon.get_width() // 2, cy - icon.get_height() // 2))
            if count is not None:
                text = font.render(str(count), True, (255, 255, 255))
                outline = font.render(str(count), True, (0, 0, 0))
                tx, ty = cx - text.get_width() // 2, cy - text.get_height() // 2
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        screen.blit(outline, (tx + dx, ty + dy))
                screen.blit(text, (tx, ty))
            if self.clicked(cx - step // 2, y, cx + step // 2, y + 56):
                if key in disabled:
                    sounds.play("error")
                else:
                    picked = key
        return picked

    def _cancel_redistribute(self):
        """Undo every change made on the redistribute screen: troops go back
        to where they were, and the 1 oil the button cost is refunded."""
        for name, units in self.rail_initial_units.items():
            self.engine.countries[name].units = units
        for name, tanks in self.rail_initial_tanks.items():
            self.engine.countries[name].tanks = tanks
        for name, planes in self.rail_initial_planes.items():
            self.engine.countries[name].planes = planes
        self.player.oil += 1
        self.rail_pool = 0
        self.rail_tank_pool = 0
        self.rail_plane_pool = 0
        self.rail_last_added = None
        self.player.subattack = self._rail_return_subattack
        self.rail_network = []
        self.rail_initial_units = {}

    def _finish_redistribute(self):
        countries = self.engine.countries
        changes = []
        for label, initial, attr in (("troops", self.rail_initial_units, "units"),
                                     ("tanks", self.rail_initial_tanks, "tanks"),
                                     ("planes", self.rail_initial_planes, "planes")):
            for name in self.rail_network:
                diff = getattr(countries[name], attr) - initial.get(name, 0)
                if diff:
                    changes.append(Msg("{}{} {}{}", "+" if diff > 0 else "-", abs(diff),
                                       "" if attr == "units" else label + " ", name))
        self.engine.log_action(self.player, Msg(
            " moved {}: {}", "by air" if self._redistribute_kind == "air" else "along rails",
            Join(changes) if changes else "nothing changed"))
        for name in self.rail_network:
            country = self.engine.countries[name]
            if country.units == 0:
                self.abandon(country)
        self.player.subattack = self._rail_return_subattack
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_initial_tanks = {}
        self.rail_initial_planes = {}

    def _rail_extra(self, done_active):
        """Hook for phase-specific extras on the rail redistribute screen."""

    def update(self):
        raise NotImplementedError


class ReinforcementPhase(Phase):
    """player.attack == 0"""

    # Troops still to starve this turn (the popup's count; 0 once chosen).
    starved = 0
    _hint_font = None  # the starvation popup's "click anywhere" line

    def _start_turn(self):
        engine = self.engine
        player = self.player
        manager = self.manager

        if manager.current_event is not None:
            manager.current_event.on_turn_start(engine, player)
            if player.attack != 0:
                return False  # diverted into a forced action (e.g. Verkeerde knop)

        manager.initial_units = {name: c.units for name, c in engine.countries.items()}
        # Every player's very first turn is a special reinforcement phase:
        # no troops to deploy, no army to feed yet and no income from their
        # countries (see TurnManager.update).
        first_round = manager.turn_num < len(engine.players)
        units = sum(c.units for c in engine.countries.values() if c.owner == player)

        # Troops are fed from the food already in stock. Whoever it can't
        # feed starves; a player without starvation gets this turn's
        # production right away, one with starvation only once they've
        # chosen who dies (see finish_starvation) -- countries left empty
        # by that produce nothing.
        food_cost = 0 if first_round else units
        starved = max(food_cost - player.food, 0)
        if starved == 0:
            self._produce(first_round)
            player.food -= food_cost
        else:
            player.food = 0
            manager.reinforcements = 0
        manager.turn_started = True
        self.starved = starved

        if units == 0:
            manager.next_turn()
            return False

        if starved == 0:
            self._continent_cards()  # with starvation: after the survivors are chosen

        manager.all_reinforcements_deployed = False
        manager.attacked = []
        manager.defending_tanks = {}
        manager.tank_fees = {}
        manager.conquered_enemy_this_turn = False
        # Starvation: popup (sub 3), then the player picks who dies (sub 4).
        player.subattack = 3 if starved > 0 else 1
        return True

    def _continent_cards(self):
        """Cards for every continent the player holds completely."""
        engine = self.engine
        player = self.player
        for continent, bonus in CONTINENT_CARD_BONUS.items():
            if all(engine.countries[n].owner == player for n in CONTINENTS[continent]):
                for _ in range(bonus):
                    player.cards.append(Kaertske(random_card_type(), images=engine.images))
                self.manager.notices.append(t(
                    "You received {} card for having {}" if bonus == 1 else "You received {} cards for having {}"
                ).format(bonus, t(continent)))

    def _produce(self, first_round=False):
        """The turn's income from the player's countries, their troops (and
        so the reinforcements) and the radioactivity ticking down."""
        engine = self.engine
        player = self.player
        manager = self.manager
        player.troops = 0
        for country in engine.countries.values():
            if country.owner == player:
                # A radioactive country produces nothing while it heals --
                # not even troops (helmets) towards the reinforcements.
                if country.radioactive == 0:
                    player.troops += country.troops
                if country.radioactive == 0 and not first_round:
                    mult = income_multiplier(engine, country, player)
                    if country.dormant_owner is player and mult > 0:
                        # Developed last turn and they still hold it and its
                        # whole continent: no waiting for the first income.
                        continent = next(name for name, members in CONTINENTS.items() if country.name in members)
                        manager.notices.append(t("Because you control {}, {} was developed instantly!").format(
                            t(continent), t(country.name)))
                    country.dormant_owner = None
                    amounts = {
                        "food": country.food * mult,
                        "wood": country.wood * mult,
                        "steel": country.steel * mult,
                        "oil": country.oil * mult,
                        "nuclear": country.nuclear * mult,
                    }
                    target = player
                    if manager.current_event is not None:
                        target, amounts = manager.current_event.modify_income(engine, country, player, amounts)
                    target.food += amounts["food"]
                    target.wood += amounts["wood"]
                    target.steel += amounts["steel"]
                    target.oil += amounts["oil"]
                    target.nuclear += amounts["nuclear"]

        # Radioactivity ticks down on the bomber's turn, not the country's
        # owner's -- a nuked country the owner still holds only heals once
        # whoever dropped the bomb takes another turn. If the bomber is
        # unknown (an old save, or the bomber has since been eliminated),
        # fall back to ticking it down on the current owner's turn instead.
        for country in engine.countries.values():
            if country.radioactive == 0:
                continue
            bomber = country.bombed_by
            if bomber is player or (bomber is None and country.owner is player):
                country.radioactive -= 1
                if country.radioactive == 0:
                    country.bombed_by = None

        manager.reinforcements = int((player.troops - player.troops % 3) / 3 + 3)
        if first_round:
            manager.reinforcements = 0
        elif manager.current_event is not None:
            manager.reinforcements = manager.current_event.reinforcement_override(engine, player, manager.reinforcements)

    def finish_starvation(self):
        """The starved troops have been chosen (also called by bots): the
        countries emptied by that are given up and only then does the
        turn's production come in, from what's left."""
        engine = self.engine
        player = self.player
        for country in engine.countries.values():
            if country.owner == player and country.units == 0:
                self.abandon(country)
        engine.log_action(player, Msg(" lost {} troops to starvation", self.starved))
        self.starved = 0
        self._produce()
        self._continent_cards()
        self.manager.initial_units = {n: c.units for n, c in engine.countries.items()}
        player.subattack = 1

    def _starvation_popup(self):
        """The starving bowl, how many troops starved, and a click anywhere
        (but on a HUD button) moves on to picking who dies."""
        import pygame as pg
        view = self.view
        screen = view.screen
        w, h = 400, 240
        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        cx = int(view.WIDTH * 0.5)
        self.draw_rect((230, 170, 170), x, y, w, h)
        self.draw_rect((0, 0, 0), x, y, w, h, 3)
        if "starving" not in _ASSET_ICONS:
            # Pixel art: scaled 2x without smoothing.
            _ASSET_ICONS["starving"] = pg.transform.scale(
                pg.image.load("./images/starving.png").convert_alpha(), (112, 112))
        icon = _ASSET_ICONS["starving"]
        screen.blit(icon, icon.get_rect(midtop=(cx, int(y + 22))))
        text = self.engine.font.render(t("{} troops starved to death").format(self.starved), True, (0, 0, 0))
        screen.blit(text, text.get_rect(midtop=(cx, int(y + 160))))
        if ReinforcementPhase._hint_font is None:
            ReinforcementPhase._hint_font = game_font(15)
        hint = self._hint_font.render(t("Click anywhere to continue"), True, (110, 70, 70))
        screen.blit(hint, hint.get_rect(midbottom=(cx, int(y + h - 18))))
        if self.io.left_pressed and self.io.top_button is None:
            self.starve_pool = -self.starved
            self.starve_initial = {n: c.units for n, c in self.engine.countries.items()}
            self.player.subattack = 4

    def _starvation_pool(self):
        """Remove troops from owned countries until the pool (starting at
        -starved) reaches 0. Emptied countries stay owned until Confirm."""
        engine = self.engine
        player = self.player
        HEIGHT = self.view.HEIGHT

        # The pool as the deploy screen's soldier ("-N", by the helmet row).
        self._draw_reinforcements(self.starve_pool)
        active = self.starve_pool == 0
        confirm_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y, active)

        # Same buttons as deploying: right-click one of your countries to
        # remove a troop, left-click to put one back.
        if confirm_clicked:
            self.finish_starvation()
        elif self.io.hover_country is not None:
            name = self.io.hover_country
            country = engine.countries[name]
            if country.owner != player:
                if self.io.right_clicked:
                    sounds.play("error")
                return
            if self.io.right_clicked:
                if self.starve_pool < 0 and country.units > 0:
                    country.units -= 1
                    self.starve_pool += 1
                else:
                    sounds.play("error")  # nobody left to remove, or enough already gone
            elif self.io.left_pressed and country.units < self.starve_initial[name]:
                country.units += 1
                self.starve_pool -= 1

    def update(self):
        player = self.player
        engine = self.engine
        manager = self.manager
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT

        if player.subattack == 0:
            if manager.turn_started:
                # Back at sub 0 of a turn that has already started (a save
                # taken mid-phase, an event pick resumed from one): the
                # army was fed and the income and reinforcements given --
                # on to the starvation popup or deploying, not again.
                player.subattack = 3 if self.starved > 0 else 1
            elif not self._start_turn():
                return

        if player.subattack == 3:
            self._starvation_popup()
            return
        if player.subattack == 4:
            self._starvation_pool()
            return

        if manager.pending_troops:
            manager.reinforcements += manager.pending_troops
            manager.pending_troops = 0
            manager.all_reinforcements_deployed = False

        self._draw_reinforcements(manager.reinforcements)

        # Left-click one of your countries to place a troop there,
        # right-click to take back one placed this turn. (subattack 2 was
        # the old separate "remove" mode; treated the same for old saves.)
        hover = self.io.hover_country
        if player.subattack in (1, 2):
            player.subattack = 1
            if manager.reinforcements <= 0:
                manager.all_reinforcements_deployed = True
            if hover is not None and engine.countries[hover].owner == player:
                country = engine.countries[hover]
                if self.io.left_pressed and not manager.all_reinforcements_deployed:
                    country.units += 1
                    manager.reinforcements -= 1
                elif self.io.right_clicked:
                    if country.units > manager.initial_units.get(hover, 0):
                        country.units -= 1
                        manager.reinforcements += 1
                        manager.all_reinforcements_deployed = False
                    else:
                        sounds.play("error")  # nothing placed this turn to take back
            elif hover is not None and self.io.right_clicked:
                sounds.play("error")  # not their country


class AttackPhase(Phase):
    """player.attack == 1"""

    def __init__(self, manager):
        super().__init__(manager)
        self.attack_from = None
        self.defence_country = None
        self.attack_dice = None
        self.defence_dice = None
        self.timer = 0
        self.conquest_units = 0
        self.selected_ships = 0
        self.attack_via_land = False
        self.selected_tanks = 0
        self.active_tanks = 0
        self.selected_planes = 0
        # Planes whose fuel was already paid for by the airport button.
        self.prepaid_planes = 0
        self.plane_fee_paid = False
        # Active tanks of this attack whose oil is already paid (see
        # _paid_tanks): remembered per tank army in manager.tank_fees.
        self.tank_fee_paid = 0
        # Tanks the defender is picking to use (subattack 8).
        self.defence_tank_choice = 0
        # True from a free claim (an emptied "maak van de VOC een deel 2"
        # country) until its move-in is confirmed: the move-in screen
        # then has an Assets button, and the asset panel works on the
        # already-claimed country instead of an attack to come.
        self.free_claim = False
        self._init_rail_state()
        self._rail_mode_subattack = 7

    def reset(self):
        """Clear anything that would otherwise linger visually (mainly the
        shading _highlight_selection applies) from whoever last used this
        phase -- AttackPhase is a single shared instance across every
        player's turn, not one per player."""
        self.attack_from = None
        self.defence_country = None
        self.attack_dice = None
        self.defence_dice = None
        self.free_claim = False
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_initial_tanks = {}
        self.rail_initial_planes = {}
        self.rail_pool = 0
        self.rail_tank_pool = 0
        self.rail_plane_pool = 0

    def update(self):
        player = self.player
        self._highlight_selection()
        subs = (1,) if self.free_claim else (1, 6)
        self._draw_rails_button(self.attack_from, subs)
        self._draw_airport_button(self.attack_from, subs)
        sub = player.subattack
        self._draw_cancel_attack()
        sub = player.subattack
        if sub in (0, 1):
            self._select_target()
        elif sub == 6:
            self._select_asset_transport()
        elif sub == 2:
            self._choose_dice_count()
        elif sub == 3:
            self._roll_dice()
        elif sub == 4:
            self._resolve_combat()
        elif sub == 5:
            self._post_conquest()
        elif sub == 7:
            self._redistribute_rails()
        elif sub == 8:
            self._select_defence_tanks()

    def _draw_cancel_attack(self):
        """Cancel button: same as clicking the attacking country again
        (back to picking an attacker). Only before dice are cast."""
        player = self.player
        if self.attack_from is None or self.free_claim or player.subattack not in (1, 2, 6):
            return
        if self.cancel_button(self.CANCEL_X, self.ROW_Y):
            player.subattack = 0
            self.attack_from = None
            self.defence_country = None

    def _highlight_selection(self):
        engine = self.engine
        if self.player.subattack == 7:
            for name in self.rail_network:
                engine.countries[name].shade = 1
            return
        if self.attack_from is not None:
            engine.countries[self.attack_from].shade = 1
        if self.defence_country is not None:
            engine.countries[self.defence_country].shade = 1

    def _try_reselect(self):
        """While attacker/defender are chosen but dice haven't been cast yet,
        clicking the defending country again backs up to re-picking a target;
        clicking the attacking country again backs up to re-picking the
        attacker entirely."""
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return False
        if hover == self.attack_from:
            self.player.subattack = 0
            self.attack_from = None
            self.defence_country = None
            return True
        if self.defence_country is not None and hover == self.defence_country:
            self.player.subattack = 1
            self.defence_country = None
            return True
        return False

    def _select_target(self):
        engine = self.engine
        player = self.player
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if player.subattack == 0:
            if engine.countries[hover].owner == player:
                event = self.manager.current_event
                if event is not None and not event.can_attack_from(engine, engine.countries[hover]):
                    return  # frozen out of attacking this round
                player.subattack = 1
                self.attack_from = hover
        else:
            if hover == self.attack_from:
                player.subattack = 0
                self.attack_from = None
                return
            if engine.countries[hover].owner == player:
                self.attack_from = hover
                return
            from_c = engine.countries[self.attack_from]
            is_land_route = self.connected(self.attack_from, hover, "land")
            can_attack = is_land_route or (
                self.connected(self.attack_from, hover, "sea") and (
                    from_c.ships > 0 or (from_c.planes > 0 and player.oil >= 1)
                )
            )
            if can_attack:
                self._start_attack(hover, is_land_route)

    rail_attack = True

    def _rail_attack_targets(self, origin):
        """Unclaimed countries the rails lead to from origin."""
        engine = self.engine
        reachable = self._rail_reachable(origin, self.player)
        return {n for n in reachable if engine.countries[n].owner == engine.default_player}

    def _rail_extra(self, done_active):
        """Attack phase only: from the rail screen an attack may be started
        against any unclaimed country the rail network leads to."""
        engine = self.engine
        by_air = self._redistribute_kind == "air"
        if by_air:
            targets = self._air_attack_targets()
        else:
            targets = self._rail_attack_targets(self.attack_from)
        for name in targets:
            engine.countries[name].shade = -1
        hover = self.io.hover_country
        if hover not in targets or not done_active:
            return
        # The attack launches from wherever the last pool troop landed, or
        # from the country selected when the rails/airport button was hit.
        launch = self.rail_last_added if self.rail_last_added is not None else self.attack_from
        if by_air and engine.countries[launch].planes == 0:
            self.blit_hint(t("Air attack needs a plane in the launch airport"))
            return
        if self.io.left_pressed:
            self.attack_from = launch
            self._finish_redistribute()
            if engine.countries[self.attack_from].owner != self.player:
                self.attack_from = None
                self.player.subattack = 0
                return
            self._start_attack(hover, not by_air, via_air=by_air)

    def _air_attack_targets(self):
        """Airports nobody owns: reachable by plane from any airport."""
        engine = self.engine
        return {n for n, c in engine.countries.items() if c.airport and c.owner == engine.default_player}

    def _start_attack(self, hover, is_land_route, via_air=False):
        self.plane_fee_paid = False  # planes pay oil again on every new attack
        engine = self.engine
        player = self.player
        manager = self.manager
        self.tank_fee_paid = self._paid_tanks(self.attack_from, hover)
        from_c = engine.countries[self.attack_from]
        target = engine.countries[hover]
        event = manager.current_event

        # An active event may forbid this attack entirely (e.g. "strenge
        # winter" freezing certain countries out of attacking or being
        # attacked) -- checked here too since every attack path (the map,
        # rails, the airport) funnels through this method, same as the
        # free-claim check right below.
        if event is not None and not (event.can_attack_from(engine, from_c) and event.can_attack_target(engine, target)):
            return  # forbidden -- nothing happens, same as any other invalid target

        # An active event may let some targets (e.g. an emptied-out
        # "maak van de VOC een deel 2" country) be claimed outright,
        # skipping combat entirely -- checked here since every attack
        # path (the map, rails, the airport) funnels through this method.
        # The claim goes straight to the move-in screen: at least 1 troop
        # moves in (and, as after any conquest, at least 1 stays behind).
        # Tanks and (over sea) ships come along by default; planes cost
        # oil, so only one comes along when it's the sole way across. The
        # Assets button there reopens the asset panel to change this.
        if event is not None and from_c.units > 1 and event.free_claim_allowed(engine, target):
            self.free_claim = True
            self.defence_country = hover
            self.prepaid_planes = 1 if via_air else 0
            self.attack_via_land = is_land_route
            self.selected_ships = 0 if (is_land_route or via_air) else from_c.ships
            self.selected_tanks = from_c.tanks
            self.active_tanks = 0
            needs_plane = not is_land_route and self.selected_ships == 0
            self.selected_planes = min(from_c.planes, 1, player.oil + self.prepaid_planes) if needs_plane else 0
            self.conquest_units = 1
            target.units = 0
            self._conquer(target, from_c)
            player.subattack = 5
            return

        self.free_claim = False
        self.prepaid_planes = 1 if via_air else 0
        self.defence_country = hover
        self.attack_dice = self._default_attack_dice(from_c.units)
        self.defence_dice = np.zeros(min(engine.countries[hover].units, 2))
        # Default to bringing everything available; the player can
        # open the asset panel from the dice screen to dial it down.
        # A boat can never cross a land connection: attacking a
        # land-adjacent country automatically leaves the boats
        # behind, and the player can't bring any along afterwards
        # either (see the locked ships row in the asset panel).
        self.attack_via_land = is_land_route
        self.selected_ships = 0 if (is_land_route or via_air) else from_c.ships
        self.selected_tanks = from_c.tanks
        # Active tanks default to matching the tanks brought along,
        # capped by what oil can actually afford; tanks get first
        # claim on the oil budget, planes get whatever's left.
        self.active_tanks = min(self.selected_tanks, player.oil + self.tank_fee_paid)
        self.selected_planes = min(from_c.planes, max(player.oil - self._tank_oil() + self.prepaid_planes, 0))
        player.subattack = 2

    def _has_attack_assets(self):
        """Does the attacking army have any ships, tanks or planes? (After a
        free claim some may already sit in the claimed country.)"""
        countries = self.engine.countries
        held = [countries[self.attack_from]]
        if self.free_claim:
            held.append(countries[self.defence_country])
        return any(c.ships or c.tanks or c.planes for c in held)

    def _free_claim_assets(self, bring):
        """Free claim only: the claimed country already holds the assets
        brought along. bring=False sends them all back to attack_from (so
        the asset panel can pick afresh), bring=True moves the selected
        ones over again."""
        from_c = self.engine.countries[self.attack_from]
        target = self.engine.countries[self.defence_country]
        for key in ("ships", "tanks", "planes"):
            total = getattr(from_c, key) + getattr(target, key)
            moved = getattr(self, "selected_" + key) if bring else 0
            setattr(target, key, moved)
            setattr(from_c, key, total - moved)

    def _select_asset_transport(self):
        if not self.free_claim and self._try_reselect():
            return
        engine = self.engine
        player = self.player
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        from_c = engine.countries[self.attack_from]

        panel_x, panel_y, panel_w, panel_h = WIDTH * 0.5 - 220, HEIGHT * 0.5 - 160, 440, 320
        done = self.click_anywhere_popup(panel_x, panel_y, panel_w, panel_h)
        # Oil it will cost: centred above the "click anywhere" hint.
        cost_x, cost_y = panel_x + panel_w * 0.5, panel_y + 264
        self.blit_text(t("Bring along from {}:").format(t(self.attack_from)), panel_x + 20, panel_y + 10)

        rows = [
            ("selected_ships", from_c.ships, engine.images["spr_ship"]),
            ("selected_planes", from_c.planes, engine.images["spr_plane"]),
            ("selected_tanks", from_c.tanks, engine.images["spr_tank"]),
        ]
        for i, (attr, available, sprite) in enumerate(rows):
            row_y = panel_y + 50 + i * 52
            sprite.draw(view.screen, Position(panel_x + 20, row_y))
            selected = getattr(self, attr)
            label = "{} / {}".format(selected, available)
            if attr == "selected_ships" and self.attack_via_land:
                label += t(" (no boats over land)")
            self.blit_text(label, panel_x + 70, row_y + 8)

            minus_x = panel_x + 340
            self.draw_rect((200, 100, 100), minus_x, row_y, 30, 30)
            self.draw_rect((0, 0, 0), minus_x, row_y, 30, 30, 2)
            self.blit_text("-", minus_x + 11, row_y + 4)
            if self.clicked_if(minus_x, row_y, minus_x + 30, row_y + 30, selected > 0):
                setattr(self, attr, selected - 1)
                if attr == "selected_tanks":
                    # Decreasing tanks mirrors the decrease onto active
                    # tanks (and can never leave more active than brought).
                    self.active_tanks = min(max(self.active_tanks - 1, 0), self.selected_tanks)

            plus_x = panel_x + 385
            self.draw_rect((100, 200, 100), plus_x, row_y, 30, 30)
            self.draw_rect((0, 0, 0), plus_x, row_y, 30, 30, 2)
            self.blit_text("+", plus_x + 9, row_y + 4)
            # Planes cost 1 oil each, drawn from the same pool active tanks
            # (below) already reserve, so cap how many can be selected by
            # what's left.
            room_left = available
            if attr == "selected_planes":
                room_left = min(available, max(player.oil - self._tank_oil() + self.prepaid_planes, 0))
            elif attr == "selected_ships" and self.attack_via_land:
                # A boat can't cross a land connection, so no ships can be
                # brought along on a land attack -- locked at 0.
                room_left = 0
            if self.clicked_if(plus_x, row_y, plus_x + 30, row_y + 30, selected < room_left):
                setattr(self, attr, selected + 1)

        # A sea attack physically requires a ship or a fuelled plane to
        # cross the water. If the player deselects the last of both, the
        # attack can no longer happen at all -- bail all the way back out
        # to picking a fresh attack_from rather than leaving them stuck on
        # an impossible asset panel.
        no_escort = self.prepaid_planes == 0 and not self.attack_via_land and \
            self.selected_ships == 0 and self.selected_planes == 0
        if self.free_claim:
            # Already claimed: can't back out, so just block continuing
            # until something is carrying the troops across again.
            if no_escort:
                self.blit_text(t("Needs a ship or plane to cross the sea"), panel_x + 20, panel_y + 50 + len(rows) * 52 + 8)
            self._draw_oil_cost(cost_x, cost_y, max(self.selected_planes - self.prepaid_planes, 0))
            if done and no_escort:
                sounds.play("error")
            elif done:
                self._free_claim_assets(True)
                player.subattack = 5
            return
        if not self.attack_via_land and self.selected_ships == 0 and self.selected_planes == 0:
            self.attack_from = None
            self.defence_country = None
            self.attack_via_land = False
            player.subattack = 0
            return

        # Active tanks: an opt-in subset of the tanks brought along. Each
        # active tank costs 1 oil (shared with planes) and adds +1 to the
        # highest attack die every round of this combat, until the attack
        # ends or the territory is conquered. Tanks already paid for
        # against this target (tank_fee_paid) cost nothing again.
        active_row_y = panel_y + 50 + len(rows) * 52
        engine.images["spr_tank"].draw(view.screen, Position(panel_x + 20, active_row_y))
        self.blit_text(
            t("Active: {} / {}").format(self.active_tanks, self.selected_tanks),
            panel_x + 70, active_row_y + 8,
        )

        active_minus_x = panel_x + 340
        self.draw_rect((200, 100, 100), active_minus_x, active_row_y, 30, 30)
        self.draw_rect((0, 0, 0), active_minus_x, active_row_y, 30, 30, 2)
        self.blit_text("-", active_minus_x + 11, active_row_y + 4)
        if self.clicked_if(active_minus_x, active_row_y, active_minus_x + 30, active_row_y + 30, self.active_tanks > 0):
            self.active_tanks -= 1

        active_plus_x = panel_x + 385
        self.draw_rect((100, 200, 100), active_plus_x, active_row_y, 30, 30)
        self.draw_rect((0, 0, 0), active_plus_x, active_row_y, 30, 30, 2)
        self.blit_text("+", active_plus_x + 9, active_row_y + 4)
        plane_cost = max(self.selected_planes - self.prepaid_planes, 0)
        active_room_left = min(self.selected_tanks, max(player.oil - plane_cost, 0) + self.tank_fee_paid)
        if self.clicked_if(active_plus_x, active_row_y, active_plus_x + 30, active_row_y + 30,
                           self.active_tanks < active_room_left):
            self.active_tanks += 1

        # Reconcile the two oil-consuming selections regardless of which
        # one just moved, so neither can drift over the available budget.
        plane_cost = max(self.selected_planes - self.prepaid_planes, 0)
        self.active_tanks = min(self.active_tanks, self.selected_tanks,
                                max(player.oil - plane_cost, 0) + self.tank_fee_paid)
        self.selected_planes = min(
            self.selected_planes, max(player.oil - self._tank_oil() + self.prepaid_planes, 0))

        # Oil this attack will use (charged on the first roll against a
        # country, see _apply_combat_results): active tanks + unpaid planes.
        self._draw_oil_cost(cost_x, cost_y, self._attack_oil_cost())
        if done:
            player.subattack = 2

    def _attack_oil_cost(self):
        """Oil the next roll uses (see _apply_combat_results): unpaid
        planes (once per attack) + active tanks not yet paid for."""
        planes = 0 if self.plane_fee_paid else max(self.selected_planes - self.prepaid_planes, 0)
        return self._tank_oil() + planes

    def _tank_oil(self):
        """Oil the active tanks still need: those beyond tank_fee_paid."""
        return max(self.active_tanks - self.tank_fee_paid, 0)

    def _paid_tanks(self, from_name, target_name):
        """Tanks of the army in `from_name` already paid for against
        `target_name` this turn. An army's payment holds until it rolls
        against another country (so cancelling and re-picking the same
        target keeps it); capped by the tanks still there."""
        fee = self.manager.tank_fees.get(from_name)
        if from_name is None or fee is None or fee[0] != target_name:
            return 0
        return min(fee[1], self.engine.countries[from_name].tanks)

    def _draw_oil_cost(self, cx, cy, cost):
        """"-N <oil>" label centred on (cx, cy) (in a pop-up, above its
        "click anywhere" hint); nothing when cost is 0."""
        if cost <= 0:
            return
        text = "-{}".format(cost)
        oil = self.engine.hud_images["spr_oil"]
        text_w = self.engine.font.size(text)[0]
        x = cx - (text_w + 4 + oil.image.get_width()) * 0.5
        self.blit_text(text, x, cy - 10)
        oil.draw(self.view.screen, Position(x + text_w + 4, cy - 20))

    def _defending_tanks(self):
        """Tanks the defender committed to this attack (0 if none yet)."""
        return self.manager.defending_tanks.get(self.defence_country, 0)

    def _needs_defence_tank_choice(self):
        """The defender gets to pick tanks once per attacked country per
        turn -- if they're a real player with tanks there and oil to run them."""
        engine = self.engine
        defence = engine.countries[self.defence_country]
        return (self.defence_country not in self.manager.defending_tanks
                and defence.owner is not engine.default_player
                and defence.tanks > 0 and defence.owner.oil > 0)

    def _select_defence_tanks(self):
        """The attacker has pressed roll: before their dice are thrown, the
        defender picks how many of their tanks there to use. Each costs 1
        oil (paid now) and adds +1 to the highest defence die every round
        of this attack, mirroring the attacker's active tanks."""
        engine = self.engine
        view = self.view
        defence = engine.countries[self.defence_country]
        owner = defence.owner
        most = min(defence.tanks, owner.oil)
        self.defence_tank_choice = min(self.defence_tank_choice, most)

        panel_w, panel_h = 440, 180
        panel_x, panel_y = view.WIDTH * 0.5 - panel_w * 0.5, view.HEIGHT * 0.5 - panel_h * 0.5
        done = self.click_anywhere_popup(panel_x, panel_y, panel_w, panel_h)
        self.blit_text(t("{}: defend {} with tanks").format(owner.name, t(self.defence_country)),
                       panel_x + 20, panel_y + 10)

        row_y = panel_y + 50
        engine.images["spr_tank"].draw(view.screen, Position(panel_x + 20, row_y))
        self.blit_text("{} / {}".format(self.defence_tank_choice, defence.tanks), panel_x + 70, row_y + 8)

        minus_x = panel_x + 340
        self.draw_rect((200, 100, 100), minus_x, row_y, 30, 30)
        self.draw_rect((0, 0, 0), minus_x, row_y, 30, 30, 2)
        self.blit_text("-", minus_x + 11, row_y + 4)
        if self.clicked_if(minus_x, row_y, minus_x + 30, row_y + 30, self.defence_tank_choice > 0):
            self.defence_tank_choice -= 1

        plus_x = panel_x + 385
        self.draw_rect((100, 200, 100), plus_x, row_y, 30, 30)
        self.draw_rect((0, 0, 0), plus_x, row_y, 30, 30, 2)
        self.blit_text("+", plus_x + 9, row_y + 4)
        if self.clicked_if(plus_x, row_y, plus_x + 30, row_y + 30, self.defence_tank_choice < most):
            self.defence_tank_choice += 1

        self._draw_oil_cost(panel_x + panel_w * 0.5, panel_y + 118, self.defence_tank_choice)
        if done:
            owner.oil -= self.defence_tank_choice
            self.manager.defending_tanks[self.defence_country] = self.defence_tank_choice
            self._cast_attack_dice()

    @staticmethod
    def _default_attack_dice(units):
        """One die per troop, up to 3, all selected (0) except that one
        troop is left behind in the attacking country by default: with 3 or
        fewer troops, the last die starts deselected (1). The player can
        still toggle it back on in dice selection."""
        dice = np.zeros(min(units, 3))
        if 1 < units <= 3:
            dice[-1] = 1
        return dice

    def _choose_dice_count(self):
        if self._try_reselect():
            return
        # NOTE: ported as-is from running.py, including the (fairly obscure)
        # original behaviour: an empty dice array short-circuits back to 0.
        if np.all(self.attack_dice):
            self.player.subattack = 0
            return
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        roll_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y)
        self._draw_oil_cost_above(self.CONFIRM_X, self.ROW_Y, self._attack_oil_cost())

        if self._has_attack_assets() and self.assets_button(WIDTH - 350, 12):
            self.open_popup(6)
            return

        for i in range(len(self.attack_dice)):
            y = self.PICK_DICE_Y + 40 * self.attack_dice[i]
            x = self.dice_x(i, len(self.attack_dice))
            Dice(self.player.color, used=bool(self.attack_dice[i])).draw(view.screen, Position(x + 35, y + 35))
            if self.clicked(x, y, x + 70, y + 70):
                self.attack_dice[i] = not self.attack_dice[i]
        if roll_clicked:
            self.roll_attack()

    def roll_attack(self):
        """The attacker presses roll (also called by bots)."""
        engine = self.engine
        manager = self.manager
        if not self.attack_via_land and manager.current_event is not None and \
                manager.current_event.sea_attack_check(engine):
            # Pirates: the whole force committed to this roll is lost
            # before any dice are even thrown.
            killed = len(self.attack_dice)
            attack_from = engine.countries[self.attack_from]
            attack_from.units -= killed
            manager.notices.append(t("{} units have been killed by pirates").format(killed))
            engine.log_action(self.player, Msg("'s attack lost {} units to pirates", killed))
            if attack_from.units <= 0:
                self.abandon(attack_from)
                self.player.subattack = 0
                self.attack_from = None
                self.defence_country = None
            else:
                defence = engine.countries[self.defence_country]
                self.attack_dice = self._default_attack_dice(attack_from.units)
                self.defence_dice = np.zeros(min(defence.units, 2))
                self.player.subattack = 2
            return
        if self._needs_defence_tank_choice():
            defence = engine.countries[self.defence_country]
            if getattr(defence.owner, "is_bot", False):
                # A bot defender decides on the spot (see bot.py).
                choice = manager.bot.defence_tanks(defence)
                defence.owner.oil -= choice
                manager.defending_tanks[self.defence_country] = choice
                self._cast_attack_dice()
                return
            # Default to every tank their oil can run, like the
            # attacker's active tanks.
            self.defence_tank_choice = min(defence.tanks, defence.owner.oil)
            self.open_popup(8)
            return
        self._cast_attack_dice()

    def _cast_attack_dice(self):
        for i in range(len(self.attack_dice)):
            self.attack_dice[i] = (not self.attack_dice[i]) * np.random.randint(1, 7)
        self.player.subattack = 3

    def _roll_dice(self):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        roll_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y)
        # The attacker's roll, with its tank/event bonus, stays visible
        # while the defender decides how many dice to throw.
        self._draw_attack_dice()
        defence = engine.countries[self.defence_country]
        # With only one die there is nothing to choose, so it rolls straight away.
        # Bots always defend with every die they have.
        auto_roll = defence.owner == engine.default_player or len(self.defence_dice) == 1 \
            or getattr(defence.owner, "is_bot", False)
        for i in range(len(self.defence_dice)):
            y = self.PICK_DICE_Y + 40 * self.defence_dice[i]
            x = self.dice_x(i, len(self.defence_dice))
            Dice(defence.owner.color, used=bool(self.defence_dice[i])).draw(view.screen, Position(x + 35, y + 35))
            if not auto_roll and self.clicked(x, y, x + 70, y + 70):
                self.defence_dice[i] = not self.defence_dice[i]
        defender_cast = roll_clicked and sum(
            not d for d in self.defence_dice
        ) != 0
        if roll_clicked and not auto_roll and not defender_cast:
            sounds.play("error")  # every die left out
        if auto_roll or defender_cast:
            for i in range(len(self.defence_dice)):
                self.defence_dice[i] = (not self.defence_dice[i]) * np.random.randint(1, 7)
            self.player.subattack = 4
            self.timer = 0

    def _draw_attack_dice(self):
        """The attacker's cast dice, highest to lowest. Active tanks boost
        the highest die (on top of any flat event bonus, which applies to
        every die, and an event dice penalty, which also applies to every
        die) -- shown as a badge on each die it changes."""
        view = self.view
        engine = self.engine
        event_bonus = 0
        attacker_penalty = 0
        if self.manager.current_event is not None:
            event = self.manager.current_event
            event_bonus = event.attack_bonus(engine, engine.countries[self.attack_from])
            attacker_penalty = event.dice_penalty(engine, self.player)
        attack = sorted((int(d) for d in self.attack_dice if d > 0), reverse=True)
        for i, value in enumerate(attack):
            x = self.dice_x(i, self.thrown_columns())
            y = self.THROWN_ATTACK_Y
            Dice(self.player.color, eyes=value).draw(view.screen, Position(x + 35, y + 35))
            badge = event_bonus + (self.active_tanks if i == 0 else 0) - attacker_penalty
            if badge != 0:
                self._bonus_badge(x, y, badge)

    def _resolve_combat(self):
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        engine = self.engine
        fort = engine.countries[self.defence_country].fort_lvl
        defender_penalty = 0
        if self.manager.current_event is not None:
            defender_penalty = self.manager.current_event.dice_penalty(
                engine, engine.countries[self.defence_country].owner)
        # Dice are shown highest to lowest; the fort boosts every defence
        # die (alongside any event dice penalty on the defender), and the
        # defender's tanks boost the highest one.
        self._draw_attack_dice()
        defence = sorted((int(d) for d in self.defence_dice if d > 0), reverse=True)
        for i, value in enumerate(defence):
            x = self.dice_x(i, self.thrown_columns())
            y = self.THROWN_DEFENCE_Y
            Dice(engine.countries[self.defence_country].owner.color, eyes=value).draw(view.screen, Position(x + 35, y + 35))
            badge = fort - defender_penalty + (self._defending_tanks() if i == 0 else 0)
            if badge != 0:
                self._bonus_badge(x, y, badge)
        if self.io.left_pressed:
            self.timer = 150
        if self.timer != 150:
            return
        self._apply_combat_results()
        self.timer = 0

    def _bonus_badge(self, x, y, amount):
        """Small signed tag ("+N" or "-N") on the bottom-right corner of a
        70x70 die at (x, y)."""
        self.draw_rect((235, 235, 245), x + 34, y + 56, 38, 22)
        self.draw_rect((0, 0, 0), x + 34, y + 56, 38, 22, 2)
        self.blit_text("{:+d}".format(amount), x + 42, y + 58)

    def _apply_combat_results(self):
        engine = self.engine
        player = self.player
        manager = self.manager
        attack_from = engine.countries[self.attack_from]
        defence = engine.countries[self.defence_country]

        D = np.sort(self.defence_dice[self.defence_dice > 0]) + defence.fort_lvl
        A = np.sort(self.attack_dice[self.attack_dice > 0])
        if manager.current_event is not None:
            event = manager.current_event
            A = A + event.attack_bonus(engine, attack_from) - event.dice_penalty(engine, player)
            D = D - event.dice_penalty(engine, defence.owner)
        if len(A) > 0:
            A[-1] += self.active_tanks
        if len(D) > 0:
            D[-1] += self._defending_tanks()
        player.oil -= self._attack_oil_cost()
        self.plane_fee_paid = True
        # The army's tank payment now covers this target (and is gone for
        # any other target it had before).
        self.tank_fee_paid = max(self.tank_fee_paid, self.active_tanks)
        manager.tank_fees[self.attack_from] = (self.defence_country, self.tank_fee_paid)
        manager.attacked.append(self.defence_country)

        n = min(len(D), len(A))
        attack_loss = [A[-1 - i] <= D[-1 - i] for i in range(n)]
        attack_from.units -= sum(attack_loss)
        defence.units -= sum(not a for a in attack_loss)
        defender = defence.owner
        self._log_battle(player, defender, defence, sum(attack_loss),
                         sum(not a for a in attack_loss), conquered=defence.units <= 0)
        # A failed landing over sea: rolling 1 die and losing it, or 2 dice
        # and losing both, sinks every asset brought along on the attack.
        if not self.attack_via_land and len(A) in (1, 2) and n == len(A) and all(attack_loss):
            ships, tanks, planes = self.selected_ships, self.selected_tanks, self.selected_planes
            if ships or tanks or planes:
                attack_from.ships = max(attack_from.ships - ships, 0)
                attack_from.tanks = max(attack_from.tanks - tanks, 0)
                attack_from.planes = max(attack_from.planes - planes, 0)
                self.selected_ships = self.selected_tanks = self.selected_planes = 0
                self.active_tanks = 0
                engine.log_destroyed(player, defence.name, ships, tanks, planes)

        if defence.units <= 0:
            self.conquest_units = len(A)
            total_units = defence.units + attack_from.units
            self._conquer(defence, attack_from, log=False)
            if total_units == self.conquest_units:
                # Every troop left in attack_from rolled, and they all have
                # to move in -- nothing to choose, so skip the confirmation.
                self._finish_conquest(attack_from)
            else:
                player.subattack = 5
        elif attack_from.units <= 0:
            if defence.owner is engine.default_player:
                sounds.play("mouse")
            # Attacker's stack is spent; nothing left to roll with, so back
            # out to re-picking an attacker instead of showing an empty
            # dice screen. With nobody left there to hold it, the country
            # they attacked from goes neutral, same as any other country
            # emptied out to 0.
            self.abandon(attack_from)
            player.subattack = 0
            self.attack_from = None
            self.defence_country = None
        else:
            # Defender survived and the attacker still has troops: stay on
            # the dice-select screen for another round against the same
            # target, re-sized to the troops that remain after this roll.
            self.attack_dice = self._default_attack_dice(attack_from.units)
            self.defence_dice = np.zeros(min(defence.units, 2))
            player.subattack = 2

    def _log_battle(self, player, defender, country, lost, killed, conquered):
        """One log line per attack on a country: successive rounds against
        the same target add up in the same (still last) line."""
        engine = self.engine
        battle = getattr(self, "_battle", None)
        if battle and battle["player"] is player and battle["country"] == country.name \
                and engine.action_log and engine.action_log[-1] is battle["entry"]:
            battle["lost"] += lost
            battle["killed"] += killed
            entry = battle["entry"]
        else:
            entry = None
            battle = self._battle = {"player": player, "country": country.name,
                                     "lost": lost, "killed": killed, "entry": None}
        lost, killed = battle["lost"], battle["killed"]
        counts = Msg("{} lost, {} defeated", lost, killed)
        if conquered:
            parts = [player, Msg(" took {} from ", country.name), defender, Msg(": {}", counts)]
        else:
            parts = [player, Msg(" attacked "), defender, Msg(" in {}: {}", country.name, counts)]
        if entry is None:
            engine.log_action(*parts)
            battle["entry"] = engine.action_log[-1]
        else:
            engine.log_action(*parts)
            new = engine.action_log.pop()
            del engine.action_log[-1]      # drop the old line, keep the updated one
            engine.action_log.append(new)
            battle["entry"] = new
        if conquered:
            self._battle = None

    def _conquer(self, defence, attack_from, log=True):
        engine = self.engine
        player = self.player
        manager = self.manager
        previous_owner = defence.owner

        if defence.owner != engine.default_player:
            manager.conquered_enemy_this_turn = True
        if log:
            engine.log_action(player, Msg(" took {} from ", defence.name), previous_owner)

        # Conquest wipes out whatever the previous owner had stationed here
        # -- ships, tanks, planes, and (already handled below) the fort --
        # then whatever the attacker brought along replaces it. This has
        # to be unconditional: previously, bringing along zero of every
        # asset type left the defender's own assets untouched instead of
        # destroyed.
        engine.log_wiped(defence)
        defence.ships = self.selected_ships
        defence.planes = self.selected_planes
        defence.tanks = self.selected_tanks
        attack_from.ships -= self.selected_ships
        attack_from.planes -= self.selected_planes
        attack_from.tanks -= self.selected_tanks

        self.take_last_country(player, defence)

        defence.fort_lvl = 0
        defence.owner = player
        manager.landmark_conquered(defence)
        total_units = defence.units + attack_from.units
        # Default to moving as many troops as possible into the newly
        # conquered country, leaving just 1 behind to hold attack_from.
        # The post-conquest menu still lets the player fine-tune this,
        # so this is only the starting point.
        defence.units = max(total_units - 1, self.conquest_units)
        attack_from.units = total_units - defence.units

        if manager.current_event is not None:
            manager.current_event.on_conquest(engine, player, defence, previous_owner)

    def _post_conquest(self):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        attack_from = engine.countries[self.attack_from]
        defence = engine.countries[self.defence_country]

        confirm_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y)

        if self.free_claim:
            self._draw_oil_cost_above(self.CONFIRM_X, self.ROW_Y, max(self.selected_planes - self.prepaid_planes, 0))
            # Same Assets button as on the dice screen.
            if self._has_attack_assets() and self.assets_button(WIDTH - 350, 12):
                self._free_claim_assets(False)
                self.open_popup(6)
                return

        # Left-click a country to shift one troop into it, right-click to
        # shift one back out; either wraps around at the ends.
        hover = self.io.hover_country
        step = 0
        if hover is not None and (self.io.left_pressed or self.io.right_clicked):
            if hover == self.defence_country:
                step = 1
            elif hover == self.attack_from:
                step = -1
            if not self.io.left_pressed:
                step = -step
        if step:
            total_units = defence.units + attack_from.units
            moved = defence.units + step
            if moved > total_units:
                moved = self.conquest_units
            elif moved < self.conquest_units:
                moved = total_units
            defence.units = moved
            attack_from.units = total_units - moved

        if confirm_clicked:
            self._finish_conquest(attack_from)

    def _finish_conquest(self, attack_from):
        if self.free_claim:
            # Planes brought along on a free claim are paid for now (in a
            # normal attack that happens on the first roll).
            self.player.oil -= max(self.selected_planes - self.prepaid_planes, 0)
            self.free_claim = False
        self.player.subattack = 0
        if attack_from.units == 0:
            self.abandon(attack_from)
        self.attack_from = None
        self.defence_country = None


class MovementPhase(Phase):
    """player.attack == 2"""

    def __init__(self, manager):
        super().__init__(manager)
        self.origin_country = None
        self.finished_list = set()
        self.target_country = None
        self.develop_target = None
        self.initial_origin = 0
        self.initial_target = 0
        # Which resource the origin/target click-to-shift applies to.
        self.move_resource = "units"
        self.initial_origin_ships = 0
        self.initial_target_ships = 0
        self.initial_origin_tanks = 0
        self.initial_target_tanks = 0
        self.initial_origin_planes = 0
        self.initial_target_planes = 0
        # Whether the origin and target are connected by an unbroken chain
        # of sea connections through the player's own territory -- boats
        # can't be moved between them otherwise.
        self.ships_via_sea = False
        # Whether NO all-land route exists between origin and target, so
        # troops need an escorting ship or (fuelled) plane to make the
        # crossing at all.
        self.troops_require_sea = False
        # Net oil spent moving planes this session, refunded on Cancel.
        self.oil_spent_on_planes = 0
        self._init_rail_state()
        self._rail_mode_subattack = 3

    def reset(self):
        """Clear anything that would otherwise linger visually (mainly the
        shading _highlight_selection applies) from whoever last used this
        phase -- MovementPhase is a single shared instance across every
        player's turn, not one per player."""
        self.origin_country = None
        self.target_country = None
        self.develop_target = None
        self.finished_list = set()
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_initial_tanks = {}
        self.rail_initial_planes = {}
        self.rail_pool = 0
        self.rail_tank_pool = 0
        self.rail_plane_pool = 0

    def update(self):
        player = self.player
        self._highlight_selection()
        self._draw_rails_button(self.origin_country, (1, 2))
        self._draw_airport_button(self.origin_country, (1, 2))
        sub = player.subattack
        if sub in (0, 4) and self._develop_ui():
            return
        if sub == 4:
            self._select_develop_target()
        elif sub == 0:
            self._select_origin()
        elif sub == 1:
            self._select_target()
        elif sub == 2:
            self._adjust_units()
        elif sub == 3:
            self._redistribute_rails()

    DEVELOP_RESOURCES = ("food", "wood", "steel", "oil", "nuclear")

    def _develop_ui(self):
        """Draws the Develop toggle (bottom of the left column; while picking
        a country the Cancel button also toggles it off) and, once an
        affordable country is picked, the Confirm button. Returns True if a
        button consumed this frame's click."""
        engine = self.engine
        player = self.player
        HEIGHT, WIDTH = self.view.HEIGHT, self.view.WIDTH
        active = player.subattack == 4

        dx, dy = self._left_button_pos(0)
        if player.developed_this_turn:
            # Greyed out; a click on it only gives the error sound.
            draw_image_button(self.engine, dx, dy, "develop", enabled=False, size=PICTURE_BUTTON_SIZE)
            return self.io.button(image_button_shape(dx, dy, PICTURE_BUTTON_SIZE))

        # Greyed out (error sound on a click) when none of the player's
        # undeveloped countries has anything to develop. While picking a
        # country it toggles back off, as does the cancel button.
        developable = active or any(
            c.owner == player and not c.developed and any(self.develop_cost(c).values())
            for c in engine.countries.values())
        toggled = draw_image_button(self.engine, dx, dy, "develop", enabled=developable, size=PICTURE_BUTTON_SIZE)
        if active:
            toggled = self.cancel_button(self.CANCEL_X, self.ROW_Y) or toggled
        if toggled:
            self.develop_target = None
            player.subattack = 0 if active else 4
            return True

        if not active or self.develop_target is None:
            return False

        country = engine.countries[self.develop_target]
        cost = {r: getattr(country, r) for r in self.DEVELOP_RESOURCES}
        affordable = sum(cost.values()) > 0 and all(getattr(player, r) >= n for r, n in cost.items())
        # Cost row centred over the Confirm button: "-x [icon] -y [icon]".
        font = self.engine.font
        items = [("-{}".format(n), self.engine.mini_images["spr_" + r]) for r, n in cost.items() if n]
        widths = [font.size(text)[0] + 2 + icon.image.get_size()[0] for text, icon in items]
        cost_x = self.CONFIRM_X - (sum(widths) + 10 * max(len(items) - 1, 0)) // 2
        row_y = self.ROW_Y - IMAGE_BUTTON_H // 2 - 4 - 20
        for (text, icon), w in zip(items, widths):
            surf = font.render(text, True, (0, 0, 0))
            self.view.screen.blit(surf, (cost_x, row_y + 10 - surf.get_height() // 2))
            iw, ih = icon.image.get_size()
            icon.draw(self.view.screen, Position(cost_x + w - iw, row_y + (20 - ih) // 2))
            cost_x += w + 10
        if self.confirm_button(self.CONFIRM_X, self.ROW_Y, enabled=affordable):
            self.develop(country)
            self.develop_target = None
            player.subattack = 0
            return True
        return False

    def develop_cost(self, country):
        return {r: getattr(country, r) for r in self.DEVELOP_RESOURCES}

    def develop(self, country):
        """Pay for and develop `country` (affordability already checked)."""
        player = self.player
        for r, n in self.develop_cost(country).items():
            setattr(player, r, getattr(player, r) - n)
        country.developed = True
        country.dormant_owner = player
        player.developed_this_turn = True
        self.engine.log_action(player, Msg(" started developing {}", country.name))

    def _select_develop_target(self):
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        country = self.engine.countries[hover]
        if country.owner == self.player and not country.developed:
            if not any(self.develop_cost(country).values()):
                sounds.play("error")  # nothing to develop there
                return
            self.develop_target = None if hover == self.develop_target else hover

    def _highlight_selection(self):
        engine = self.engine
        if self.develop_target is not None and self.player.subattack == 4:
            engine.countries[self.develop_target].shade = 1
            return
        if self.player.subattack == 3:
            for name in self.rail_network:
                engine.countries[name].shade = 1
            return
        if self.origin_country is not None:
            engine.countries[self.origin_country].shade = 1
        if self.target_country is not None:
            engine.countries[self.target_country].shade = 1

    def _select_origin(self):
        engine = self.engine
        player = self.player
        if player.repositioned_this_turn:
            self.blit_hint(t("Already repositioned this turn"))
            if self.io.left_pressed and self.io.hover_country is not None:
                sounds.play("error")
            return
        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None and engine.countries[hover].owner == player:
            self.origin_country = hover
            self._flood_fill()
            player.subattack = 1

    def _flood_fill(self):
        """Every country the player owns reachable from origin_country by
        hopping through any connection (land or sea), as long as each
        intermediate country along the way is also theirs."""
        engine = self.engine
        player = self.player
        finished = {self.origin_country}
        while True:
            size_before = len(finished)
            neighbours = set()
            for name in finished:
                for c in engine.connections:
                    if name in c:
                        neighbours.update(c.connection)
            finished |= {n for n in neighbours if engine.countries[n].owner == player}
            if len(finished) == size_before:
                break
        self.finished_list = finished

    def _sea_flood_fill(self, origin):
        """Like _flood_fill, but only hopping along sea connections --
        used to check whether ships can legally be moved to a target,
        since a boat can never travel a land connection."""
        engine = self.engine
        player = self.player
        finished = {origin}
        while True:
            size_before = len(finished)
            neighbours = set()
            for name in finished:
                for c in engine.connections:
                    if c.kind == "sea" and name in c:
                        neighbours.update(c.connection)
            finished |= {n for n in neighbours if engine.countries[n].owner == player}
            if len(finished) == size_before:
                break
        return finished

    def _land_flood_fill(self, origin):
        """Like _flood_fill, but only hopping along land connections --
        used to check whether troops can march the whole way unassisted.
        If a target isn't in here, at least one leg of every route to it
        crosses open sea, so troops need an escorting ship or plane."""
        engine = self.engine
        player = self.player
        finished = {origin}
        while True:
            size_before = len(finished)
            neighbours = set()
            for name in finished:
                for c in engine.connections:
                    if c.kind == "land" and name in c:
                        neighbours.update(c.connection)
            finished |= {n for n in neighbours if engine.countries[n].owner == player}
            if len(finished) == size_before:
                break
        return finished

    def _has_sea_escort(self, target):
        """Whether a ship or plane has actually been brought along (moved
        into target during this session) to escort troops across water."""
        return target.ships > self.initial_target_ships or target.planes > self.initial_target_planes

    def _ships_unmanned(self, target):
        """Ships moved this session without at least one troop going the
        same way: a ship can't sail without someone aboard."""
        ships_moved = target.ships - self.initial_target_ships
        troops_moved = target.units - self.initial_target
        return (ships_moved > 0 and troops_moved < 1) or (ships_moved < 0 and troops_moved > -1)

    def _select_target(self):
        engine = self.engine
        player = self.player
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.origin_country:
            self.origin_country = None
            player.subattack = 0
        elif hover in self.finished_list:
            origin = engine.countries[self.origin_country]
            target = engine.countries[hover]
            self.target_country = hover
            self.initial_origin = origin.units
            self.initial_target = target.units
            self.initial_origin_ships = origin.ships
            self.initial_target_ships = target.ships
            self.initial_origin_tanks = origin.tanks
            self.initial_target_tanks = target.tanks
            self.initial_origin_planes = origin.planes
            self.initial_target_planes = target.planes
            self.ships_via_sea = hover in self._sea_flood_fill(self.origin_country)
            self.troops_require_sea = hover not in self._land_flood_fill(self.origin_country)
            self.oil_spent_on_planes = 0
            self.move_resource = "units"
            self._auto_escort(origin, target)
            player.subattack = 2

    def _auto_escort(self, origin, target):
        """Troops can't cross open sea alone: send one boat along if the
        sea route allows it, otherwise one plane (1 oil), so the player
        lands straight in the adjust screen instead of being stuck."""
        if not self.troops_require_sea:
            return
        if self.ships_via_sea and origin.ships > 0:
            origin.ships -= 1
            target.ships += 1
            if origin.units > 1:
                # A ship needs at least one troop aboard (see
                # _ships_unmanned); send one along if that doesn't empty
                # the origin.
                origin.units -= 1
                target.units += 1
        elif origin.planes > 0 and self.player.oil >= 1:
            origin.planes -= 1
            target.planes += 1
            self.player.oil -= 1
            self.oil_spent_on_planes += 1

    def _shift_resource(self, origin, target, towards_origin):
        """Move 1 unit of self.move_resource between origin and target."""
        key = self.move_resource

        if key == "ships" and not self.ships_via_sea:
            return  # locked: no unbroken sea route between these two

        if key == "units":
            if self.troops_require_sea and not self._has_sea_escort(target):
                return  # troops can't cross open sea without an escort
            # Same bounded increment/decrement AttackPhase._post_conquest
            # uses while deciding how many troops move into a freshly
            # conquered country: 0 (or the full total) is a deliberate
            # endpoint you land on and stay at, not a value you flicker
            # through via modulo wraparound. This is what makes moving out
            # the very last troop a clean, intentional choice rather than
            # something that could accidentally cycle past 0.
            total_units = origin.units + target.units
            if towards_origin:
                if target.units - 1 < 0 or origin.units + 1 > total_units:
                    target.units = 0
                    origin.units = total_units
                else:
                    target.units -= 1
                    origin.units += 1
            else:
                if origin.units - 1 < 0 or target.units + 1 > total_units:
                    origin.units = 0
                    target.units = total_units
                else:
                    origin.units -= 1
                    target.units += 1
            return

        origin_val = getattr(origin, key)
        target_val = getattr(target, key)
        total = origin_val + target_val + 1
        if towards_origin:
            new_origin = (origin_val + 1) % total
            new_target = (target_val - 1) % total
        else:
            new_origin = (origin_val - 1) % total
            new_target = (target_val + 1) % total

        if key == "planes":
            # Every plane relocated (in either direction, relative to
            # where it started this session) costs 1 oil; moving one back
            # toward its starting country refunds the oil already spent
            # on it. Block the move outright if it would take oil below 0.
            old_delta = abs(target_val - self.initial_target_planes)
            new_delta = abs(new_target - self.initial_target_planes)
            cost_change = new_delta - old_delta
            if cost_change > 0 and self.player.oil < cost_change:
                return
            self.player.oil -= cost_change
            self.oil_spent_on_planes += cost_change

        setattr(origin, key, new_origin)
        setattr(target, key, new_target)

    def _log_move(self, origin, target):
        """"moved: -1 India, +1 Belarus" (assets named: "+1 ships Belarus"),
        the country troops left first."""
        changes = {origin.name: [], target.name: []}
        for key, word in (("units", ""), ("ships", "ships "), ("tanks", "tanks "), ("planes", "planes ")):
            n = getattr(origin, key) - getattr(self, "initial_origin" + ("" if key == "units" else "_" + key))
            if n:
                changes[origin.name].append(Msg("{:+d} {}{}", n, word, origin.name))
                changes[target.name].append(Msg("{:+d} {}{}", -n, word, target.name))
        if changes[origin.name]:
            source, dest = (target, origin) if origin.units > self.initial_origin else (origin, target)
            self.engine.log_action(self.player, Msg(" moved: {}", Join(changes[source.name] + changes[dest.name])))

    def _cancel_adjustment(self, origin, target):
        origin.units, target.units = self.initial_origin, self.initial_target
        origin.ships, target.ships = self.initial_origin_ships, self.initial_target_ships
        origin.tanks, target.tanks = self.initial_origin_tanks, self.initial_target_tanks
        origin.planes, target.planes = self.initial_origin_planes, self.initial_target_planes
        self.player.oil += self.oil_spent_on_planes
        self.oil_spent_on_planes = 0
        # Back to picking an origin: neither country stays highlighted.
        self.origin_country = None
        self.target_country = None
        self.finished_list = set()
        self.player.subattack = 0

    def _adjust_units(self):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        origin = engine.countries[self.origin_country]
        target = engine.countries[self.target_country]

        # Resource selector: which of troops/ships/tanks/planes does
        # clicking origin/target currently move?
        resources = [
            ("units", "spr_troops", None),
            ("ships", "spr_ship", None),
            ("tanks", "spr_tank", None),
            ("planes", "spr_plane", None),
        ]
        # Ships/tanks/planes that neither country has are greyed out.
        absent = {key for key in ("ships", "tanks", "planes")
                  if getattr(origin, key) + getattr(target, key) == 0}
        if self.move_resource in absent:
            self.move_resource = "units"
        picked = self._resource_selector(resources, self.move_resource, disabled=absent)
        if picked is not None:
            self.move_resource = picked

        if self.move_resource == "ships" and not self.ships_via_sea:
            self.blit_hint(t("No unbroken sea route -- ships can't move here"))
        elif self.move_resource == "units" and self.troops_require_sea and not self._has_sea_escort(target):
            self.blit_hint(t("No land route -- bring a ship or plane to escort troops"))
        elif self.move_resource == "planes":
            self.blit_hint(t("Planes cost 1 oil each to relocate"))

        if origin.units == 0 or target.units == 0:
            self.blit_hint(t("Emptied country will be abandoned on Confirm"))

        # Troops that crossed open sea need a boat or plane along for the
        # ride; without one the move can't be confirmed.
        blocked = (
            self.troops_require_sea
            and origin.units != self.initial_origin
            and not self._has_sea_escort(target)
        )
        if blocked and self.move_resource != "units":
            self.blit_hint(t("Troops need a ship or plane to cross the sea"))
        elif self._ships_unmanned(target):
            blocked = True
            self.blit_hint(t("A ship needs at least one troop moving with it"))

        confirm_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y, not blocked)
        # Planes moved cost 1 oil each (already taken, refunded on Cancel).
        self._draw_oil_cost_above(self.CONFIRM_X, self.ROW_Y, self.oil_spent_on_planes)
        cancel_clicked = self.cancel_button(self.CANCEL_X, self.ROW_Y)

        hover = self.io.hover_country
        if self.io.left_pressed and hover == self.origin_country:
            self._shift_resource(origin, target, towards_origin=True)
        elif self.io.left_pressed and hover == self.target_country:
            self._shift_resource(origin, target, towards_origin=False)
        elif cancel_clicked:
            self._cancel_adjustment(origin, target)
            return
        elif confirm_clicked:
            # Only now -- on explicit confirmation -- does an emptied
            # country actually flip over to the neutral default_player.
            # Dragging a country's troops down to 0 mid-adjustment (or
            # cycling past 0 via the wraparound) no longer abandons it on
            # the spot.
            if origin.units == 0:
                self.abandon(origin)
            elif target.units == 0:
                self.abandon(target)
            self._log_move(origin, target)
            # Only one confirmed reposition is allowed per turn.
            self.player.repositioned_this_turn = True
            self.origin_country = None
            self.target_country = None
            self.finished_list = set()
            self.player.subattack = 0


class ShopPhase(Phase):
    """player.attack == 3 -- building infrastructure and units."""

    def __init__(self, manager):
        super().__init__(manager)
        self.build_origin = None

    def _cost(self, base):
        """`base` ({resource: amount}) adjusted for an active event that
        changes shop prices (e.g. "plunderingen"), for both display and
        the actual charge -- both always go through this so they can
        never drift apart."""
        event = self.manager.current_event
        return dict(event.discount_shop_cost(self.engine, base)) if event is not None else dict(base)

    def update(self):
        player = self.player
        if player.subattack < 8:
            if self._draw_menu():
                return
        self._handle_placement()
        if player.subattack > 8:
            self._draw_cancel()

    def _draw_menu(self):
        """Returns True if the shop was closed this frame."""
        player = self.player
        engine = self.engine
        view = self.view
        bg = engine.colors["card_background"]
        sel = engine.colors["card_selected"]
        selected_at_start = player.subattack

        fx, fy = self._frame_origin()
        self.draw_rect(engine.SHOP_COLOR, fx, fy, self.FRAME_W, self.FRAME_H)
        self.draw_rect((0, 0, 0), fx, fy, self.FRAME_W, self.FRAME_H, 3)
        if self._clicked_outside_frame():
            self.manager.close_shop()
            return True

        # Infrastructure: bridge / rails / nuke
        shop = engine.shop_images
        cost_icons = engine.hud_images
        bridge_cost = self._cost({"wood": 10})
        rails_cost = self._cost({"wood": 2, "steel": 1})
        nuke_cost = self._cost({"nuclear": 5})
        infra = [
            (1, fx + 30, "spr_bridge", [("spr_wood", "X {}".format(bridge_cost["wood"]))]),
            (2, fx + 180, "spr_rails",
             [("spr_wood", "X {}".format(rails_cost["wood"])), ("spr_steel", "X {}".format(rails_cost["steel"]))]),
            (3, fx + 330, "spr_nuke", [("spr_nuclear", "X {}".format(nuke_cost["nuclear"]))]),
        ]
        affordability = {
            1: player.wood >= bridge_cost["wood"],
            2: player.wood >= rails_cost["wood"] and player.steel >= rails_cost["steel"],
            3: player.nuclear >= nuke_cost["nuclear"],
        }
        card_x, card_y = self._selected_card_center()
        on_confirm = 0 < player.subattack < 8 and self.mouse_in(
            card_x - IMAGE_BUTTON_W // 2, card_y - IMAGE_BUTTON_H // 2,
            card_x + IMAGE_BUTTON_W // 2, card_y + IMAGE_BUTTON_H // 2)
        for sub, x, sprite, costs in infra:
            if affordability[sub] and self.clicked(x, fy + 30, x + 130, fy + 265) and not on_confirm:
                player.subattack = 0 if player.subattack == sub else sub
            elif not affordability[sub] and self.clicked(x, fy + 30, x + 130, fy + 265) and not on_confirm:
                sounds.play("error")
            self._draw_shop_card(
                x, fy + 30, sel if player.subattack == sub else bg, shop[sprite], costs,
                affordable=affordability[sub],
            )

        # Units: only buildable when the shop was opened from the
        # reinforcement phase (mirrors running.py's `attack in (0, 4)` guard,
        # simplified since the legacy attack==4 card phase no longer exists).
        units_allowed = self.manager.saved_attack == 0
        ship_cost = self.ship_cost()
        plane_cost = self._cost({"steel": 10})
        tank_cost = self._cost({"steel": 20})
        # The fort card shows all three level-up prices; affordability
        # (like the actual build) assumes buying the cheapest, level 1.
        fort_tiers = [self._cost({"wood": 10 + 5 * lvl})["wood"] for lvl in range(3)]
        units = [
            (4, fx + 30, "spr_ship", player.wood >= ship_cost["wood"], [("spr_wood", "X {}".format(ship_cost["wood"]) if ship_cost["wood"] else t("Free"))]),
            (5, fx + 180, "spr_plane", player.steel >= plane_cost["steel"], [("spr_steel", "X {}".format(plane_cost["steel"]))]),
            (6, fx + 330, "spr_tank", player.steel >= tank_cost["steel"], [("spr_steel", "X {}".format(tank_cost["steel"]))]),
            (7, fx + 480, "spr_fort", player.wood >= fort_tiers[0], [("spr_wood", "/".join(str(tier) for tier in fort_tiers))]),
        ]
        for sub, x, sprite, affordable, costs in units:
            if units_allowed and affordable and self.clicked(x, fy + 295, x + 130, fy + 530) \
                    and not on_confirm:
                player.subattack = 0 if player.subattack == sub else sub
            elif not (units_allowed and affordable) and self.clicked(x, fy + 295, x + 130, fy + 530) \
                    and not on_confirm:
                sounds.play("error")
            self._draw_shop_card(
                x, fy + 295, sel if player.subattack == sub else bg, shop[sprite], costs,
                affordable=affordable, blocked=not units_allowed,
            )

        if 0 < player.subattack < 8:
            # A click that just selected this item (so the button only appeared
            # this frame, right under the cursor) must not also buy it.
            if self.confirm_button(*self._selected_card_center()) \
                    and player.subattack == selected_at_start:
                player.subattack += 8
        return False

    FRAME_W, FRAME_H = 640, 560

    def _frame_origin(self):
        """Top-left of the shop frame, centred on the screen."""
        return (self.view.WIDTH - self.FRAME_W) // 2, (self.view.HEIGHT - self.FRAME_H) // 2

    def _clicked_outside_frame(self):
        """A click anywhere outside the frame closes the shop -- except on
        the settings / shop / cards icons, which handle their own clicks
        (the shop icon already toggles it closed)."""
        if not self.io.left_pressed:
            return False
        fx, fy = self._frame_origin()
        if self.mouse_in(fx, fy, fx + self.FRAME_W, fy + self.FRAME_H):
            return False
        engine = self.engine
        for button in (engine._settings_button(), engine._shop_button(), engine._card_button()):
            if self.mouse_in(button.pos.x, button.pos.y, button.pos.x + button.width, button.pos.y + button.height):
                return False
        return True

    def _selected_card_center(self):
        """Centre of the currently selected shop card."""
        sub = self.player.subattack
        fx, fy = self._frame_origin()
        if sub <= 3:
            return fx + 30 + 150 * (sub - 1) + 65, fy + 30 + 117
        return fx + 30 + 150 * (sub - 4) + 65, fy + 295 + 117

    def _draw_shop_card(self, x, y, color, sprite, costs, affordable=True, blocked=False):
        """One 130x235 shop card: the item sprite centred in the upper
        part, its cost (icon + amount) rows stacked at the bottom. An
        unaffordable item (the fort card checks the price of the next
        level, lvl 1, since that's what a click there would buy) gets a
        50% grey overlay so it reads as unavailable; a `blocked` one (not
        buyable in this phase) a 50% red one. Overlays sit on top of the
        sprite and costs."""
        self.draw_rect(color, x, y, 130, 235)
        iw, ih = sprite.image.get_size()
        sprite.draw(self.view.screen, Position(x + (130 - iw) // 2, y + 12 + (128 - ih) // 2))
        icons = self.engine.hud_images
        row_h = 42
        top = y + 235 - 10 - row_h * len(costs)
        for i, (icon_name, text) in enumerate(costs):
            icon = icons[icon_name]
            text_w = self.engine.font.size(text)[0]
            iw2, ih2 = icon.image.get_size()
            start = x + (130 - (40 + 8 + text_w)) // 2
            row_y = top + i * row_h
            icon.draw(self.view.screen, Position(start + (40 - iw2) // 2, row_y + (40 - ih2) // 2))
            self.blit_text(text, start + 48, row_y + 10)
        tint = (215, 30, 30) if blocked else (70, 70, 70) if not affordable else None
        if tint:
            import pygame as pg
            overlay = pg.Surface((130, 235), pg.SRCALPHA)
            overlay.fill(tint + (128,))
            self.view.screen.blit(overlay, (x, y))
        self.draw_rect((0, 0, 0), x, y, 130, 235, 3)

    def _draw_cancel(self):
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        if self.cancel_button(self.CANCEL_X, self.ROW_Y):
            self.manager.close_shop()

    def _handle_placement(self):
        sub = self.player.subattack
        if sub == 9:
            self._pick_origin(16)
        elif sub == 16:
            self._build_link(back=9)
        elif sub == 10:
            self._pick_origin(17)
        elif sub == 17:
            self._build_rails(back=10)
        elif sub == 11:
            self._build_nuke()
        elif sub == 12:
            self._build_unit("ships", self.ship_cost())
        elif sub == 13:
            self._build_unit("planes", self._cost({"steel": 10}))
        elif sub == 14:
            self._build_unit("tanks", self._cost({"steel": 20}))
        elif sub == 15:
            self._build_fort()

    def _pick_origin(self, next_sub):
        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None and self.engine.countries[hover].owner == self.player:
            self.build_origin = hover
            self.player.subattack = next_sub

    def _build_link(self, back):
        if self.build_origin is not None:
            self.engine.countries[self.build_origin].shade = 1
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.build_origin:
            self.build_origin = None
            self.player.subattack = back
            return
        if self.build_bridge(self.build_origin, hover):
            self.manager.close_shop()

    def build_bridge(self, a, b):
        """Turn the sea route between `a` (the player's) and `b` into a land
        route and pay for it; True if there was one."""
        cost = self._cost({"wood": 10})
        if self.engine.countries[a].owner != self.player or self.player.wood < cost["wood"]:
            return False
        for c in self.engine.connections:
            if {a, b} == set(c.connection) and c.kind == "sea":
                c.kind = "land"
                self.player.wood -= cost["wood"]
                self.engine.log_action(self.player, Msg(" built a bridge from {} to {}", a, b))
                return True
        return False

    def _build_rails(self, back):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT

        if self.build_origin is not None:
            engine.countries[self.build_origin].shade = 1

        # Cancel while picking the second country: back out to re-picking
        # an origin without spending anything. Nothing has been charged
        # yet at this point (wood/steel are only deducted once a valid
        # pair is confirmed below), so cancelling here already amounts to
        # a full refund -- the player simply never pays.
        if self.cancel_button(self.CANCEL_X, self.ROW_Y):
            self.build_origin = None
            self.player.subattack = back
            return

        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.build_origin:
            self.build_origin = None
            self.player.subattack = back
            return
        if self.build_rails(self.build_origin, hover):
            self.manager.close_shop()

    def build_rails(self, a, b):
        """Lay rails on the land route between the player's countries `a`
        and `b` and pay for them; True if they were laid."""
        countries = self.engine.countries
        cost = self._cost({"wood": 2, "steel": 1})
        if countries[a].owner != self.player or countries[b].owner != self.player \
                or self.player.wood < cost["wood"] or self.player.steel < cost["steel"]:
            return False
        for c in self.engine.connections:
            if {a, b} == set(c.connection) and c.kind == "land":
                if c.rails:
                    return False  # already has rails: nothing to buy
                c.rails = True  # draws grey (Connection.draw) and enables rail redistribution
                self.player.wood -= cost["wood"]
                self.player.steel -= cost["steel"]
                self.engine.log_action(self.player, Msg(" built rails from {} to {}", a, b))
                return True
        return False

    def _nuke_targets(self):
        """Every country not the player's own that's adjacent (land or sea)
        to at least one country they own -- a missile doesn't need a boat
        or plane, so any of their own countries can launch it."""
        engine = self.engine
        player = self.player
        owned = [name for name, c in engine.countries.items() if c.owner == player]
        return {
            name for name, c in engine.countries.items()
            if c.owner != player and any(self.connected(origin, name) for origin in owned)
        }

    def _build_nuke(self):
        engine = self.engine
        targets = self._nuke_targets()
        for name in targets:
            engine.countries[name].shade = 1

        hover = self.io.hover_country
        if not (self.io.left_pressed and hover in targets):
            return
        self.drop_nuke(hover)
        self.manager.close_shop()

    def drop_nuke(self, name):
        """Nuke the country `name` (one of _nuke_targets) and pay for it."""
        target = self.engine.countries[name]
        sounds.play("abomb")
        target.radioactive += 3
        target.bombed_by = self.player
        destroyed = target.units - target.units // 2
        target.units = target.units // 2  # rounded down
        self.engine.log_action(self.player, Msg(" nuked {}: {} casualty" if destroyed == 1
                                                else " nuked {}: {} casualties", name, destroyed))
        if target.units == 0:
            # Nobody survives to hold it: a player's country is abandoned
            # on the spot (same as emptying it while redistributing), an
            # unclaimed one is simply repopulated. If it was a player's
            # last country, that counts as eliminating them, just as if
            # it had been conquered.
            self.take_last_country(self.player, target)
            self.abandon(target)
        self.player.nuclear -= self._cost({"nuclear": 5})["nuclear"]

    def _build_unit(self, attr, cost):
        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None and self.engine.countries[hover].owner == self.player:
            self.place_unit(attr, cost, hover)
            self.manager.close_shop()

    def ship_cost(self):
        """A player's first ship is free (Player.start_ship)."""
        return {"wood": 0} if self.player.start_ship else self._cost({"wood": 15})

    def place_unit(self, attr, cost, name):
        """Put a bought ship/plane/tank (`attr`) on the player's country `name`."""
        country = self.engine.countries[name]
        if attr == "ships":
            self.player.start_ship = False
        setattr(country, attr, getattr(country, attr) + 1)
        if attr == "planes":
            country.airport = True
        for resource, amount in cost.items():
            setattr(self.player, resource, getattr(self.player, resource) - amount)
        self.engine.log_action(self.player, Msg(
            {"ships": " placed a ship in {}", "planes": " placed a plane in {}", "tanks": " placed a tank in {}"}[attr],
            name))

    def fort_cost(self, country):
        return self._cost({"wood": 10 + 5 * country.fort_lvl})["wood"]

    def _build_fort(self):
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if self.place_fort(hover):
            self.manager.close_shop()

    def place_fort(self, name):
        """Raise the fort on `name` one level if allowed; True if it was."""
        country = self.engine.countries[name]
        cost = self.fort_cost(country)
        if country.owner == self.player and country.fort_lvl <= 2 and self.player.wood >= cost:
            self.player.wood -= cost
            country.fort_lvl += 1
            self.engine.log_action(self.player, Msg(" built a fort in {}", name))
            return True
        return False


class RecruitPhase(Phase):
    """player.attack == 4 -- temporary recruitment after trading cards for
    troops outside the reinforcement phase: place them on any of the
    player's territories the way reinforcements are deployed (left-click
    add, right-click take back), then Confirm returns to where they came
    from."""

    def __init__(self, manager):
        super().__init__(manager)
        self.pool = 0
        self.initial_units = {}

    def start(self, troops):
        self.pool = troops
        self.initial_units = {name: c.units for name, c in self.engine.countries.items()}

    def update(self):
        engine = self.engine
        player = self.player

        self._draw_reinforcements(self.pool)
        confirm_clicked = self.confirm_button(self.CONFIRM_X, self.ROW_Y, self.pool == 0)
        if confirm_clicked:
            self.manager.end_trade_recruit()
            return

        hover = self.io.hover_country
        if hover is None or engine.countries[hover].owner != player:
            if hover is not None and self.io.right_clicked:
                sounds.play("error")  # not their country
            return
        country = engine.countries[hover]
        if self.io.left_pressed and self.pool > 0:
            country.units += 1
            self.pool -= 1
        elif self.io.right_clicked:
            if country.units > self.initial_units.get(hover, 0):
                country.units -= 1
                self.pool += 1
            else:
                sounds.play("error")  # nothing placed here to take back


class EventTargetPhase(Phase):
    """player.attack == 5 -- a world event forcing this player to pick a
    country matching some predicate (e.g. WrongButton, in events.py, needs
    an Asia target), then runs a callback on it. Generic so any future
    event needing a forced pick can reuse it rather than adding its own
    phase; returns to whichever (attack, subattack) the player was
    diverted from once a valid country is clicked -- there's no way to
    cancel out of it, since the whole point is that it's forced."""

    def __init__(self, manager):
        super().__init__(manager)
        self.predicate = None
        self.on_pick = None
        self.prompt = ""
        self.return_to = (0, 0)
        # Who makes the pick (and is passed to on_pick): the current
        # player unless an event says otherwise -- e.g. WrongButton's
        # Noord-Korea owner, possibly during someone else's turn.
        self.chooser = None

    def start(self, predicate, on_pick, prompt, return_to, chooser=None):
        self.predicate = predicate
        self.on_pick = on_pick
        self.prompt = prompt
        self.return_to = return_to
        self.chooser = chooser

    def update(self):
        engine = self.engine
        player = self.player
        if self.predicate is None:
            # This phase's own state isn't saved (same scope as every
            # other mid-action state -- see save_load.py), so resuming a
            # save taken mid-selection would otherwise find it empty and
            # crash. Bail to a safe default instead.
            player.attack, player.subattack = 0, 0
            return
        self.blit_hint(t(self.prompt))

        valid = [c for c in engine.countries.values() if self.predicate(c)]
        for country in valid:
            country.shade = 1

        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        country = engine.countries[hover]
        if not self.predicate(country):
            return
        self.pick(country)

    def pick(self, country):
        """`country` (matching the predicate) is chosen: back to where the
        player came from, then run the event's callback on it."""
        player = self.player
        chooser = self.chooser or player
        on_pick, return_to = self.on_pick, self.return_to
        self.predicate = self.on_pick = self.chooser = None
        player.attack, player.subattack = return_to
        on_pick(self.engine, chooser, country)


class MouseAttackPhase(Phase):
    """player.attack == 6 -- an event has mouse attack countries the way a
    player would (NativesFightBack): one country at a time, `TROOPS`
    attackers each, the dice shown round by round. Mouse always throws
    as many dice as it can; the defender picks their tanks and how many
    dice to throw, as in any attack (a bot defender decides by itself).
    Works through the active event's `queue`, then goes back to its
    `return_to`. Everything it needs is in the event (saved), so a save
    loaded mid-attack just starts the current country's fight over."""

    def __init__(self, manager):
        super().__init__(manager)
        self.target = None
        self.troops = 0
        self.tanks = 0
        self.tank_choice = 0
        self.attack_dice = []
        self.defence_dice = np.zeros(0)
        self.rolled_at = 0

    def update(self):
        event = self.manager.current_event
        player = self.player
        if event is None or not getattr(event, "queue", None):
            self.target = None
            player.attack, player.subattack = getattr(event, "return_to", (1, 0))
            return
        if player.subattack == 0 or self.target != event.queue[0]:
            self._begin(event)
            return
        country = self.engine.countries[self.target]
        self.blit_hint(t("{}: mouse attacks {} of {} -- {} troops left").format(
            t(event.name), t(self.target), country.owner.name, self.troops))
        country.shade = 1
        if player.subattack == 1:
            self._choose_tanks(country)
        elif player.subattack == 3:
            self._defender_dice(country)
        elif player.subattack == 4:
            self._resolve(event, country)

    def _begin(self, event):
        engine = self.engine
        country = engine.countries[event.queue[0]]
        owner = country.owner
        if owner is engine.default_player:
            event.queue.pop(0)  # nothing (left) to attack there
            return
        self.target = country.name
        self.troops = event.TROOPS
        self.native_losses = self.owner_losses = 0
        sounds.play("mouse")
        self.tanks = 0
        if country.tanks > 0 and owner.oil > 0:
            if owner.is_bot:
                self.tanks = self.manager.bot.defence_tanks(country)
                owner.oil -= self.tanks
            else:
                # Default to every tank their oil can run.
                self.tank_choice = min(country.tanks, owner.oil)
                self.open_popup(1)
                return
        self._roll()

    def _choose_tanks(self, country):
        """Same panel as a defender gets against a player's attack."""
        engine, view = self.engine, self.view
        owner = country.owner
        most = min(country.tanks, owner.oil)
        panel_w, panel_h = 440, 180
        panel_x, panel_y = view.WIDTH * 0.5 - panel_w * 0.5, view.HEIGHT * 0.5 - panel_h * 0.5
        done = self.click_anywhere_popup(panel_x, panel_y, panel_w, panel_h)
        self.blit_text(t("{}: defend {} with tanks").format(owner.name, t(country.name)), panel_x + 20, panel_y + 10)
        row_y = panel_y + 50
        engine.images["spr_tank"].draw(view.screen, Position(panel_x + 20, row_y))
        self.blit_text("{} / {}".format(self.tank_choice, country.tanks), panel_x + 70, row_y + 8)
        minus_x, plus_x = panel_x + 340, panel_x + 385
        self.draw_rect((200, 100, 100), minus_x, row_y, 30, 30)
        self.draw_rect((0, 0, 0), minus_x, row_y, 30, 30, 2)
        self.blit_text("-", minus_x + 11, row_y + 4)
        if self.clicked_if(minus_x, row_y, minus_x + 30, row_y + 30, self.tank_choice > 0):
            self.tank_choice -= 1
        self.draw_rect((100, 200, 100), plus_x, row_y, 30, 30)
        self.draw_rect((0, 0, 0), plus_x, row_y, 30, 30, 2)
        self.blit_text("+", plus_x + 9, row_y + 4)
        if self.clicked_if(plus_x, row_y, plus_x + 30, row_y + 30, self.tank_choice < most):
            self.tank_choice += 1
        self.manager.phases[1]._draw_oil_cost(panel_x + panel_w * 0.5, panel_y + 118, self.tank_choice)
        if done:
            owner.oil -= self.tank_choice
            self.tanks = self.tank_choice
            self._roll()

    def _roll(self):
        """Mouse throws (always as many dice as it can); the defender's
        dice are then theirs to pick."""
        country = self.engine.countries[self.target]
        self.attack_dice = sorted(np.random.randint(1, 7, size=min(self.troops, 3)), reverse=True)
        self.defence_dice = np.zeros(min(country.units, 2))
        self.player.subattack = 3

    def _draw_mouse_dice(self):
        mouse = self.engine.default_player
        for i, value in enumerate(self.attack_dice):
            x = self.dice_x(i, self.thrown_columns())
            Dice(mouse.color, eyes=int(value)).draw(self.view.screen, Position(x + 35, self.THROWN_ATTACK_Y + 35))

    def _defender_dice(self, country):
        """As in AttackPhase._roll_dice: the defender clicks dice to leave
        out and throws; one die, or a bot, throws straight away."""
        view = self.view
        self._draw_mouse_dice()
        owner = country.owner
        auto_roll = owner.is_bot or len(self.defence_dice) == 1
        roll_clicked = not auto_roll and self.confirm_button(self.CONFIRM_X, self.ROW_Y)
        if not auto_roll:
            self.blit_hint(t("{}: click dice to leave out, then roll").format(owner.name))
        for i in range(len(self.defence_dice)):
            y = self.PICK_DICE_Y + 40 * self.defence_dice[i]
            x = self.dice_x(i, len(self.defence_dice))
            Dice(owner.color, used=bool(self.defence_dice[i])).draw(view.screen, Position(x + 35, y + 35))
            if not auto_roll and self.clicked(x, y, x + 70, y + 70):
                self.defence_dice[i] = not self.defence_dice[i]
        if roll_clicked and not auto_roll and sum(not d for d in self.defence_dice) == 0:
            sounds.play("error")  # every die left out
        if auto_roll or (roll_clicked and sum(not d for d in self.defence_dice) != 0):
            for i in range(len(self.defence_dice)):
                self.defence_dice[i] = (not self.defence_dice[i]) * np.random.randint(1, 7)
            self.player.subattack = 4
            import pygame as pg
            self.rolled_at = pg.time.get_ticks()

    def _resolve(self, event, country):
        """Both rolls on screen (fort on every defence die, tanks on the
        highest); a click -- or, for a bot defender, a short pause --
        applies them."""
        import pygame as pg
        from bot import DICE_MS
        view = self.view
        self._draw_mouse_dice()
        defence = sorted((int(d) for d in self.defence_dice if d > 0), reverse=True)
        for i, value in enumerate(defence):
            x = self.dice_x(i, self.thrown_columns())
            y = self.THROWN_DEFENCE_Y
            Dice(country.owner.color, eyes=value).draw(view.screen, Position(x + 35, y + 35))
            badge = country.fort_lvl + (self.tanks if i == 0 else 0)
            if badge != 0:
                self.manager.phases[1]._bonus_badge(x, y, badge)
        wait = 0 if self.manager.bot.fast else DICE_MS
        if not self.io.left_pressed and not (country.owner.is_bot and pg.time.get_ticks() - self.rolled_at >= wait):
            return

        A = np.array(sorted(self.attack_dice))
        D = np.sort(np.array(defence)) + country.fort_lvl
        if len(D) > 0:
            D[-1] += self.tanks
        n = min(len(A), len(D))
        attack_loss = [A[-1 - i] <= D[-1 - i] for i in range(n)]
        self.troops -= sum(attack_loss)
        country.units -= sum(not lost for lost in attack_loss)
        self.native_losses = getattr(self, "native_losses", 0) + sum(attack_loss)
        self.owner_losses = getattr(self, "owner_losses", 0) + sum(not lost for lost in attack_loss)

        owner = country.owner
        if country.units <= 0:
            # Taken the same way a conquest wipes out what was there.
            counts = Msg(": {} lost, {} defeated", self.native_losses, self.owner_losses)
            self.engine.log_action(Msg("The natives took {} from ", country.name), owner, counts)
            self.engine.log_wiped(country)
            country.owner = self.engine.default_player
            country.units = self.troops
            country.ships = country.tanks = country.planes = country.fort_lvl = 0
            country.landmark_owner = None
            self.manager.notices.append([event.name, t("The natives took {} from {}{}").format(
                t(country.name), owner.name, counts)])
        elif self.troops <= 0:
            counts = Msg(": {} lost, {} destroyed", self.owner_losses, self.native_losses)
            self.manager.notices.append([event.name, t("{} defended {} from the natives{}").format(
                owner.name, t(country.name), counts)])
            self.engine.log_action(owner, Msg(" defended {} from the natives{}", country.name, counts))
        else:
            self._roll()
            return
        event.queue.pop(0)
        self.target = None
        self.player.subattack = 0


class TurnManager:
    """Owns all Phase instances and the small amount of cross-phase state."""

    def __init__(self, engine):
        self.engine = engine
        self.reinforcements = 0
        self.all_reinforcements_deployed = True
        self.attacked = []
        # Per attacking country: (target, active tanks paid for) -- an
        # army's tanks pay oil once per target until it rolls elsewhere.
        self.tank_fees = {}
        # Tanks each defending country committed against this turn's
        # attacks (already paid for in oil) -- reset along with attacked.
        self.defending_tanks = {}
        # China/Japan already punished this turn for a missing/misplaced
        # pagoda/torii (see landmarks_owed).
        self.landmarks_punished = set()
        # Whether the player has conquered at least one non-neutral
        # (i.e. another player's) territory so far this turn -- checked
        # when the turn actually ends to award a card.
        self.conquered_enemy_this_turn = False
        self.turn_num = 0
        # The current player's turn start (feeding, income, reinforcements)
        # has been worked out: coming back to the reinforcement phase's
        # sub 0 must not run it again (see ReinforcementPhase.update).
        self.turn_started = False
        self.initial_units = {}
        self.saved_attack = 0
        self.saved_subattack = 0
        # Pop-up messages waiting for an OK click (e.g. eliminations).
        self.notices = []
        self._sounded_notice = None
        self._dialog_icons = {}
        # Eliminated player -> (victor, [(amount, resource), ...]) of what
        # the victor looted, for the elimination notice.
        self.elimination_loot = {}
        # A newly-revealed world event, shown as its own richer overlay
        # (sprite + name + description) rather than a plain notice.
        self.event_notice = None
        self.game_over = False
        self.phases = {
            0: ReinforcementPhase(self),
            1: AttackPhase(self),
            2: MovementPhase(self),
            3: ShopPhase(self),
            4: RecruitPhase(self),
            5: EventTargetPhase(self),
            6: MouseAttackPhase(self),
        }
        self.recruit_return = (0, 0)
        self.pending_troops = 0
        from bot import BotController
        self.bot = BotController(self)
        # When the dialog currently up was first shown (see _show_dialogs).
        self._dialog_shown_at = None

        # World events -- see _update_event_schedule for the timing rule.
        # event_turn_index only gates the opening grace period (everyone's
        # first turn); every duration after that is tracked against actual
        # Player objects, so eliminations shrink a round in progress and
        # who gets to "reveal" the next event rotates correctly even as
        # the player count changes.
        self.event_turn_index = 0
        self.current_event = None
        self.event_pending_players = set()  # still need a turn under current_event
        self.reveal_pool = set()            # alive players who haven't revealed one this pass
        self.awaiting_gap = False           # the one event-free turn right after one ends
        self.event_bag = []       # shuffled events not yet drawn this pass
        self.event_history = []   # events drawn so far, in draw order
        # Cards an event has queued for the current player, given out at
        # the end of their turn alongside the regular conquest card (e.g.
        # ChildSoldiers) -- generic so any event can add to it.
        self.pending_event_cards = 0

    def _reset_shop_selection(self):
        """Forget any picked item / origin country and clear their highlight."""
        shop = self.phases[3]
        shop.build_origin = None
        for country in self.engine.countries.values():
            country.shade = 0

    def acting_player(self):
        """The player whose decision the game waits for: whoever's turn it
        is, except a human defender picking tanks or dice (also against an
        event's mouse attack) and an event's chooser. Their game controller
        is the one that clicks (controls.py)."""
        engine = self.engine
        player = engine.players[engine.turn]
        if self.dialog_active:
            return player
        if player.attack == 1 and player.subattack in (3, 8):
            # As BotController._human_defending.
            attack = self.phases[1]
            if attack.defence_country is not None:
                owner = engine.countries[attack.defence_country].owner
                if owner is not engine.default_player and not owner.is_bot \
                        and (player.subattack == 8 or len(attack.defence_dice) > 1):
                    return owner
        if player.attack == 5 and self.phases[5].chooser is not None:
            return self.phases[5].chooser
        if player.attack == 6 and player.subattack in (1, 3):
            target = self.phases[6].target
            if target is not None and engine.countries[target].owner is not engine.default_player:
                return engine.countries[target].owner
        return player

    def attack_in_progress(self):
        """Dice have been cast for an attack (rolled, being resolved, or
        choosing how many troops move in): it has to be finished before the
        shop, the card menu or the move phase can be opened."""
        player = self.engine.players[self.engine.turn]
        if player.attack == 1 and player.subattack == 6 and self.phases[1].free_claim:
            return True  # asset panel of a free claim: already conquered
        if player.attack == 6:
            return True  # an event's mouse attack (MouseAttackPhase)
        return player.attack == 1 and player.subattack in (3, 4, 5, 8)

    def open_shop(self):
        player = self.engine.players[self.engine.turn]
        if player.attack == 1 and player.subattack in (2, 6):
            # Opened from dice selection (or its asset panel), before any
            # die is cast: the attack is called off and both countries are
            # deselected, so closing the shop returns to picking an attacker.
            self.phases[1].reset()
            player.subattack = 0
        if player.attack != 3:
            self.saved_attack = player.attack
            self.saved_subattack = player.subattack
            player.attack = 3
        # Always open with nothing selected.
        player.subattack = 0
        self._reset_shop_selection()

    MAX_CARDS = 4

    def must_trade(self, player=None):
        """A player holding more than 4 cards is locked into the card menu
        until they've traded down to 4 or fewer. When the cards come from
        eliminating someone, that waits until the player has confirmed how
        many troops move in (bots trade straight away, as they always have)."""
        player = player or self.engine.players[self.engine.turn]
        if player.eliminated or len(player.cards) <= self.MAX_CARDS:
            return False
        return player.is_bot or not self.moving_in(player)

    def moving_in(self, player):
        """`player` is choosing how many troops move into a country just
        conquered or claimed (or is in a free claim's asset panel, opened
        from that screen)."""
        if player.attack != 1:
            return False
        return player.subattack == 5 or (player.subattack == 6 and self.phases[1].free_claim)

    def can_trade(self):
        """Cards can only be traded while deploying troops in the
        reinforcement phase -- unless the player holds too many cards,
        which forces a trade at any point."""
        player = self.engine.players[self.engine.turn]
        if self.must_trade(player):
            return True
        return player.attack == 0 and player.subattack in (1, 2)

    def gain_troops(self, amount):
        """Troops from a card trade: into the reinforcement pool if the
        player is recruiting, otherwise via a temporary recruit phase."""
        player = self.engine.players[self.engine.turn]
        if player.attack == 4:
            self.phases[4].pool += amount  # already placing traded troops
            return
        if player.attack == 0:
            if player.subattack in (1, 2):
                self.reinforcements += amount
                self.all_reinforcements_deployed = False
            else:
                # Before the turn's income is worked out (or during the
                # starvation screens): held back until deployment starts.
                self.pending_troops += amount
            return
        self.recruit_return = (player.attack, player.subattack)
        player.attack = 4
        player.subattack = 0
        self.phases[4].start(amount)

    def end_trade_recruit(self):
        player = self.engine.players[self.engine.turn]
        player.attack, player.subattack = self.recruit_return

    def toggle_shop(self):
        """The shop icon opens the shop, and closes it again."""
        attack = self.engine.players[self.engine.turn].attack
        if attack == 3:
            self.close_shop()
        elif attack != 4 and not self.must_trade() and not self.attack_in_progress():
            # not while placing traded troops, or mid-attack once dice are cast
            self.open_shop()
        else:
            sounds.play("error")

    def close_shop(self):
        player = self.engine.players[self.engine.turn]
        player.attack = self.saved_attack
        player.subattack = self.saved_subattack
        self._reset_shop_selection()

    def landmark_conquered(self, country):
        """The current player just took `country`: if it's China or Japan,
        any old pagoda/torii there is gone -- they owe a new one."""
        if country.name in LANDMARKS:
            country.landmark_owner = None

    @property
    def landmarks_owed(self):
        """China/Japan the current player holds without their pagoda/torii
        -- to be dragged on from the settings menu before the turn ends --
        except any already punished this turn."""
        engine = self.engine
        player = engine.players[engine.turn]
        return {
            name for name in LANDMARKS
            if engine.countries[name].owner is player
            and engine.countries[name].landmark_owner is not player
            and name not in self.landmarks_punished
        }

    def place_landmark(self, name):
        """Settings-menu drop of the pagoda/torii onto its own country `name`."""
        self.engine.countries[name].landmark_owner = self.engine.players[self.engine.turn]
        sounds.play(LANDMARKS[name])

    def misplace_landmark(self, name, dropped_on):
        """The pagoda/torii that belongs on `name` was dropped on the other
        landmark country `dropped_on` instead: `name` gets the forgot-it
        punishment on the spot."""
        item = LANDMARKS[name]
        self._punish_landmark(name, t("the {} belongs on {}, not {}").format(t(item), t(name), t(dropped_on)),
                              "misplaced")

    def _punish_landmark(self, name, reason, verb="forgot"):
        """All troops but 1 removed from `name` -- or, with just 1 there,
        the mouse takes it over. At most once per country per turn."""
        engine = self.engine
        player = engine.players[engine.turn]
        country = engine.countries[name]
        self.landmarks_punished.add(name)
        if country.units <= 1:
            engine.log_action(player, Msg(
                " forgot the {}: {} was taken over by the mouse" if verb == "forgot"
                else " misplaced the {}: {} was taken over by the mouse", LANDMARKS[name], name))
            self.phases[0].abandon(country)
            self.notices.append(IconNotice(t("{}, {}, {} was taken over by the mouse").format(
                player.name, reason, t(name)), LANDMARKS[name]))
        else:
            removed = country.units - 1
            country.units = 1
            self.notices.append(IconNotice(t("{}, {}, {} {} removed from {}").format(
                player.name, reason, removed, t("troop was" if removed == 1 else "troops were"), t(name)),
                LANDMARKS[name]))
            engine.log_action(player, Msg(
                " forgot the {}: lost {} {} in {}" if verb == "forgot" else " misplaced the {}: lost {} {} in {}",
                LANDMARKS[name], removed, "troop" if removed == 1 else "troops", name))

    def _apply_landmark_penalties(self):
        """The turn is being passed: every China/Japan the player still
        holds without its pagoda/torii is punished."""
        for name in sorted(self.landmarks_owed):
            self._punish_landmark(name, t("you forgot the {}").format(t(LANDMARKS[name])))

    def next_turn(self):
        players = self.engine.players
        self.landmarks_punished = set()
        self.turn_started = False
        for _ in range(len(players)):
            self.engine.turn = (self.engine.turn + 1) % len(players)
            self.turn_num += 1
            if not self._is_out(players[self.engine.turn]):
                break
        # Exactly one advance per real turn transition, unlike turn_num
        # above (which also ticks for eliminated players skipped over) --
        # events are scheduled against actual turns played.
        self.event_turn_index += 1
        # Autosave as the new turn starts, before its event is drawn (the
        # save is flagged so loading it runs the schedule step below).
        # The bag is shuffled first, so reloading draws the same event.
        from save_load import save_game
        self._refill_event_bag()
        save_game(self.engine, self, self.engine.save_path, event_schedule_pending=True)
        self._update_event_schedule()

    def _is_out(self, player):
        """Eliminated, or about to be: no troops left anywhere on the board.
        (The eliminated flag itself is only set by _check_eliminations on
        the next frame, which can be too late when a turn is just changing
        hands -- e.g. the previous event's on_end wiping someone out.)"""
        return player.eliminated or not any(
            c.owner is player and c.units > 0 for c in self.engine.countries.values())

    def _draw_next_event(self):
        """Pick (and record in event_history) the next event to reveal,
        refilling and reshuffling the bag from EVENTS when it runs out.
        Avoids drawing the same event twice back-to-back across a
        reshuffle."""
        self._refill_event_bag()
        event = self.event_bag.pop()
        self.event_history.append(event)
        return event

    def _refill_event_bag(self):
        """Reshuffle a fresh bag from EVENTS if the current one is empty."""
        if not self.event_bag and EVENTS:
            # Leave out anything already drawn in the current pass, so each
            # event occurs once before any repeats -- even if the bag was
            # lost (e.g. loading an older save that didn't store it).
            drawn_this_pass = len(self.event_history) % len(EVENTS)
            already_drawn = self.event_history[-drawn_this_pass:] if drawn_this_pass else []
            self.event_bag = [e for e in EVENTS if e not in already_drawn]
            np.random.shuffle(self.event_bag)
            if len(self.event_bag) > 1 and self.event_history and self.event_bag[-1] is self.event_history[-1]:
                self.event_bag[0], self.event_bag[-1] = self.event_bag[-1], self.event_bag[0]

    def _update_event_schedule(self):
        """Called once per real turn transition, with the new turn already
        current. The rules:
          - Every player's first turn passes with no event.
          - An event then stays active for one full round -- every
            currently alive player gets exactly one turn under it, even
            if some are eliminated (or newly eliminated) partway through,
            so the round shrinks with the population instead of a fixed
            length.
          - Exactly one player's turn passes with no event.
          - The next event is revealed on the turn after that, but only
            once every currently alive player has had a turn revealing
            one in the current pass -- so it's a different player each
            time until the pass is complete, then it starts over.
        """
        engine = self.engine
        current_player = engine.players[engine.turn]

        # Did the round finish on the PREVIOUS turn (the last pending
        # player took theirs)? End it now, before deciding whether the
        # event applies to the player whose turn is only just starting --
        # otherwise the round's last player would never actually get a
        # turn "under" it, since it'd already look ended by the time
        # anything checks current_event during their turn.
        if self.current_event is not None and not self.event_pending_players:
            self.current_event.on_end(engine)
            self.current_event = None
            self.awaiting_gap = True

        if self.current_event is not None:
            # This turn counts as this player's turn under the event.
            self.event_pending_players.discard(current_player)
            self.event_pending_players -= {p for p in self.event_pending_players if self._is_out(p)}
            return

        if not EVENTS or self.event_turn_index < len(engine.players):
            return  # no events defined yet, or still in the opening grace period

        if self.awaiting_gap:
            self.awaiting_gap = False
            return  # the mandatory event-free turn right after one ends

        # Whoever hasn't revealed one yet this pass over the currently
        # alive players; refill once everyone alive has had a turn.
        alive = {p for p in engine.players if not self._is_out(p)}
        if current_player not in alive:
            return  # wiped out as their turn began: never the one to reveal
        self.reveal_pool &= alive
        if not self.reveal_pool:
            self.reveal_pool = set(alive)
        if current_player not in self.reveal_pool:
            return  # someone else's turn to reveal one; try again next turn

        event = self._draw_next_event()
        self.current_event = event
        self.reveal_pool.discard(current_player)
        self.event_pending_players = alive - {current_player}
        self.event_notice = event
        event.on_start(engine)
        engine.log_action(Msg("Event: {}", event.name))

    def turns_until_next_event(self):
        """(turns, player): how many turn changes from now until the next
        event card is drawn, and whose turn that'll be -- by playing
        _update_event_schedule forward without side effects, assuming
        nobody is eliminated in the meantime. None if there are no events."""
        engine = self.engine
        players = engine.players
        alive = {p for p in players if not self._is_out(p)}
        if not EVENTS or not alive:
            return None
        active = self.current_event is not None
        pending = set(self.event_pending_players) & alive
        awaiting_gap = self.awaiting_gap
        pool = set(self.reveal_pool)
        index = self.event_turn_index
        turn = engine.turn
        # Each player gets a turn at most every len(players) steps, and a
        # full event cycle is at most two rounds plus a pass of reveals.
        for step in range(1, 4 * len(players) * (len(players) + 2)):
            for _ in range(len(players)):
                turn = (turn + 1) % len(players)
                if players[turn] in alive:
                    break
            player = players[turn]
            index += 1
            if active and not pending:
                active = False
                awaiting_gap = True
            if active:
                pending.discard(player)
                continue
            if index < len(players):
                continue
            if awaiting_gap:
                awaiting_gap = False
                continue
            pool &= alive
            if not pool:
                pool = set(alive)
            if player in pool:
                return step, player
        return None

    # (attack, subattack) states where the current player's troops sit in a
    # temporary pool rather than on the board (rail/air redistribution and
    # starvation), so an empty board there doesn't mean they're dead.
    POOL_STATES = {(0, 4), (1, 7), (2, 3)}

    def _check_eliminations(self):
        engine = self.engine
        current = engine.players[engine.turn]
        attack, sub = current.attack, current.subattack
        if attack == 3:
            attack, sub = self.saved_attack, self.saved_subattack
        # A defender whose last troops just died still owns the country
        # until _conquer runs; don't eliminate them before that.
        defence = self.phases[1].defence_country
        pending = engine.countries[defence].owner if defence is not None and current.attack == 1 else None

        for player in engine.players:
            if player.eliminated or player is pending:
                continue
            if player is current and (attack, sub) in self.POOL_STATES:
                continue
            if any(c.owner is player and c.units > 0 for c in engine.countries.values()):
                continue
            self._eliminate(player)

    def _check_event_pending(self, player):
        """Give the active event its chance (Event.check_pending) to apply
        an effect that couldn't happen when it started, at a calm point of
        the turn: deploying, or picking in the attack/move phase -- never
        mid-combat, mid-adjustment or in the shop."""
        event = self.current_event
        if event is None or self.must_trade(player):
            return
        attack, sub = player.attack, player.subattack
        if not ((attack == 0 and sub in (1, 2)) or (attack in (1, 2) and sub in (0, 1))):
            return
        before = {n: c.units for n, c in self.engine.countries.items()}
        if not event.check_pending(self.engine, player):
            return
        if attack == 0:
            # Troops the event added or moved aren't this turn's
            # reinforcements: right-click may not take them back.
            for n, c in self.engine.countries.items():
                self.initial_units[n] = max(self.initial_units.get(n, 0) + c.units - before[n], 0)
        else:
            # Whatever was selected may have changed hands: pick afresh.
            self.phases[attack].reset()
            if player.attack == attack:
                player.subattack = 0

    def _draw_dialog(self, lines, button, big=False, icon=None):
        """Centered modal box. Returns True if its button was clicked; with
        button "OK" there is no button: a click anywhere dismisses it. `icon`
        is an image name (images/) shown above the text."""
        import pygame as pg
        view = self.engine.view
        io = self.engine.io
        screen = view.screen
        if big:
            dim = pg.Surface((view.WIDTH, view.HEIGHT), pg.SRCALPHA)
            dim.fill((0, 0, 0, 170))
            screen.blit(dim, (0, 0))
        w, min_h = (520, 260) if big else (420, 210)
        text_w = w - 40
        font = game_font(34 if big else 20)
        # Each line is wrapped to the box width; its wrapped pieces sit
        # close together, separate lines 50px apart as before.
        offsets, pieces = [], []
        offset = 0
        for i, line in enumerate(lines):
            if i:
                offset += 50
            # t(): an event's name heading its notice is translated only here.
            for j, piece in enumerate(self._wrap_text(t(line), font, text_w) or [""]):
                if j:
                    offset += font.get_height() + 4
                offsets.append(offset)
                pieces.append(piece)
        click_anywhere = button == "OK"
        icon_h = 84 if icon else 0  # 72px sprite + gap
        if click_anywhere:
            hint_font = game_font(14)
            h = 40 + icon_h + offset + font.get_height() + 22 + hint_font.get_height() + 20
        else:
            h = max(min_h, offset + 170)  # clear of the 44px-radius button
        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        pg.draw.rect(screen, (250, 225, 130), pg.Rect(x, y, w, h))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, w, h), 3)
        for piece, offset in zip(pieces, offsets):
            img = font.render(piece, True, (0, 0, 0))
            if img.get_width() > text_w:  # a single word too long to wrap
                img = pg.transform.smoothscale(
                    img, (text_w, max(1, int(img.get_height() * text_w / img.get_width()))))
            screen.blit(img, (view.WIDTH * 0.5 - img.get_width() * 0.5, y + 40 + icon_h + offset))
        if click_anywhere:
            if icon:
                sprite = self._dialog_icons.get(icon)
                if sprite is None:
                    sprite = self._dialog_icons[icon] = pg.transform.smoothscale(
                        pg.image.load("./images/{}.png".format(icon)).convert_alpha(), (72, 72))
                screen.blit(sprite, (view.WIDTH * 0.5 - 36, y + 20))
            hint = hint_font.render(t("click anywhere to continue"), True, (90, 50, 50))
            screen.blit(hint, (view.WIDTH * 0.5 - hint.get_width() * 0.5, y + h - 20 - hint.get_height()))
            return bool(io.left_pressed)
        bx, by, bw, bh = view.WIDTH * 0.5 - 60, y + h - 60, 120, 40
        pg.draw.rect(screen, (150, 245, 150), pg.Rect(bx, by, bw, bh))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(bx, by, bw, bh), 2)
        img = self.engine.font.render(t(button), True, (0, 0, 0))
        screen.blit(img, (bx + bw * 0.5 - img.get_width() * 0.5, by + 10))
        m = io.mouse_position
        return io.button(("r", bx, by, bw, bh))

    @property
    def dialog_active(self):
        """Whether an elimination message, a new-event overlay, or the win
        screen is up."""
        players = self.engine.players
        alive = sum(not p.eliminated for p in players)
        return self.event_notice is not None or bool(self.notices) or (alive <= 1 and len(players) > 1)

    @staticmethod
    def _wrap_text(text, font, max_width):
        """`text` split into lines, each rendering to at most max_width."""
        lines = []
        current = ""
        for word in text.split():
            trial = "{} {}".format(current, word).strip()
            if current and font.size(trial)[0] > max_width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    def _draw_event_dialog(self, event):
        """Sprite + name + description overlay for a newly-revealed world
        event. Returns True when it's clicked (anywhere)."""
        import pygame as pg
        view = self.engine.view
        io = self.engine.io
        screen = view.screen

        dim = pg.Surface((view.WIDTH, view.HEIGHT), pg.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        screen.blit(dim, (0, 0))

        name_font = game_font(28, bold=True)
        desc_font = game_font(19)
        w = 520
        text_w = w - 80
        lines = self._wrap_text(t(event.description), desc_font, text_w)

        icon = self.engine.hud_images["spr_event"]
        iw, ih = icon.image.get_size()
        name_h = name_font.get_height()
        line_h = desc_font.get_height() + 4
        hint_font = game_font(14)
        top_pad, gap1, gap2, pre_hint_pad, bottom_pad = 24, 16, 16, 22, 20
        h = (top_pad + ih + gap1 + name_h + gap2 + line_h * len(lines) + pre_hint_pad
             + hint_font.get_height() + bottom_pad)

        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        pg.draw.rect(screen, (250, 225, 130), pg.Rect(x, y, w, h))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, w, h), 3)

        cy = y + top_pad
        icon.draw(screen, Position(int(x + w * 0.5 - iw * 0.5), int(cy)))
        cy += ih + gap1

        name_surf = name_font.render(t(event.name), True, (0, 0, 0))
        screen.blit(name_surf, (x + w * 0.5 - name_surf.get_width() * 0.5, cy))
        cy += name_h + gap2

        for line in lines:
            line_surf = desc_font.render(line, True, (0, 0, 0))
            screen.blit(line_surf, (x + w * 0.5 - line_surf.get_width() * 0.5, cy))
            cy += line_h

        # Same hint as the other click-anywhere messages (_draw_dialog).
        hint = hint_font.render(t("click anywhere to continue"), True, (90, 50, 50))
        screen.blit(hint, (x + w * 0.5 - hint.get_width() * 0.5, y + h - bottom_pad - hint.get_height()))
        return bool(io.left_pressed)

    def _bot_dismisses(self, dialog):
        """On a bot's turn nobody may be there to click OK: a message
        closes by itself after a while (the bot's notice delay)."""
        if not self.engine.players[self.engine.turn].is_bot:
            self._dialog_shown_at = None
            return False
        import pygame as pg
        now = pg.time.get_ticks()
        if self._dialog_shown_at is None or self._dialog_shown_at[0] is not dialog:
            self._dialog_shown_at = (dialog, now)
        return now - self._dialog_shown_at[1] >= self.bot.notice_ms

    def _show_dialogs(self):
        """Blocks the game while a message or the win screen is showing.
        Returns True if one was drawn this frame."""
        import pygame as pg
        if self.event_notice is not None:
            if self._draw_event_dialog(self.event_notice) or self._bot_dismisses(self.event_notice):
                self.event_notice = None
            return True
        if self.notices:
            notice = self.notices[0]
            if notice is not self._sounded_notice:
                self._sounded_notice = notice
                if getattr(notice, "icon", None) in ("pagoda", "torii"):
                    sounds.play(notice.icon)
            if self._draw_dialog([notice] if isinstance(notice, str) else notice, "OK",
                                 icon=getattr(notice, "icon", None)) \
                    or self._bot_dismisses(notice):
                self.notices.pop(0)
            return True
        alive = [p for p in self.engine.players if not p.eliminated]
        if len(alive) <= 1 and len(self.engine.players) > 1:
            self.game_over = True
            lines = [t("{} wins!").format(alive[0].name)] if alive else [t("Nobody survived")]
            if self._draw_dialog(lines, "Quit", big=True):
                pg.event.post(pg.event.Event(pg.QUIT))
            return True
        return False

    def _eliminate(self, player):
        engine = self.engine
        players = engine.players
        player.eliminated = True
        engine.log_action(player, Msg(" has been eliminated"))
        lines = [t("{} has been eliminated").format(player.name)]
        victor, loot = self.elimination_loot.pop(player, (None, []))
        if victor is not None:
            if loot:
                lines.append(t("{} gained:").format(victor.name))
                lines.append(", ".join("{} {}".format(n, t(r)) for n, r in loot))
            else:
                lines.append(t("{} gained nothing").format(victor.name))
        self.notices.append(lines)

        # Nobody left to have dropped their bombs; hand each countdown to
        # whoever is next in turn order (skipping anyone else already out).
        successor = None
        for offset in range(1, len(players)):
            candidate = players[(players.index(player) + offset) % len(players)]
            if not candidate.eliminated:
                successor = candidate
                break
        for country in engine.countries.values():
            if country.bombed_by is player:
                country.bombed_by = successor
            if country.owner is player:
                self.phases[0].abandon(country)
        if player is engine.players[engine.turn]:
            # Their turn ends on the spot.
            player.attack = 0
            player.subattack = 0
            engine.card_menu.show = False
            self.attacked = []
            self.defending_tanks = {}
            self.tank_fees = {}
            self.conquered_enemy_this_turn = False
            self.phases[1].reset()
            self.phases[2].reset()
            self.next_turn()

    def can_end_turn(self):
        """The End turn button works once every troop is placed, and not
        in the shop or while an attack is in progress."""
        player = self.engine.players[self.engine.turn]
        return self.all_reinforcements_deployed and player.attack < 3 and not self.attack_in_progress()

    def _handle_end_turn_button(self):
        engine = self.engine
        player = engine.players[engine.turn]
        view = engine.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        if engine.io.left_pressed:
            # A click on a phase button that can't be used right now.
            usable = player.attack < 3 and not self.attack_in_progress() and self.all_reinforcements_deployed
            for i in range(3):
                if engine.gui.phase_button_hit(view, i, engine.io.mouse_position) and \
                        not (usable and i == player.attack + 1):
                    sounds.play("error")
        if player.attack >= 3:  # shop / traded-troop placement
            return
        if self.attack_in_progress():
            return  # dice are cast: the attack has to finish first
        # The phase buttons only step forward to attack/move; the turn
        # itself ends only with the End turn button.
        index = player.attack + 1
        if index <= 2 and self.all_reinforcements_deployed and engine.io.left_pressed and \
                engine.gui.phase_button_hit(view, index, engine.io.mouse_position):
            self.end_phase()
        if self.can_end_turn() and engine.io.left_pressed and \
                engine.gui.end_turn_hit(view, engine.io.mouse_position):
            # End turn: run through whatever phases are left.
            turn = engine.turn
            while engine.turn == turn and player.attack < 3 and not self.attack_in_progress():
                self.end_phase()
                if player.attack == 0:
                    break

    def _cancel_unfinished_move(self, player):
        """Leaving a phase while a move/rail screen is still open (only
        Confirm abandons an emptied country) undoes that move, so no
        country is left owned with 0 troops. Any that remain are given up."""
        phase = self.phases.get(player.attack)
        if player.attack == 2 and player.subattack == 2:
            phase._cancel_adjustment(self.engine.countries[phase.origin_country],
                                     self.engine.countries[phase.target_country])
        elif (player.attack, player.subattack) in ((1, 7), (2, 3)):
            phase._cancel_redistribute()
        # Any country left at 0 troops always goes to the mouse.
        for country in self.engine.countries.values():
            if country.owner is not self.engine.default_player and country.units <= 0:
                self.phases[0].abandon(country)

    def end_phase(self):
        """On to the next phase: reinforce -> attack -> move -> next turn
        (the phase buttons; bots call it directly)."""
        engine = self.engine
        player = engine.players[engine.turn]
        self._cancel_unfinished_move(player)
        player.attack = (player.attack + 1) % 3
        player.subattack = 0
        if player.attack == 1:
            self.phases[1].reset()
        if player.attack == 2:
            player.repositioned_this_turn = False
            player.developed_this_turn = False
            self.phases[2].reset()
        if player.attack == 0:
            if self.conquered_enemy_this_turn:
                player.cards.append(Kaertske(random_card_type(), images=engine.images))
            self.conquered_enemy_this_turn = False
            for _ in range(self.pending_event_cards):
                player.cards.append(Kaertske(random_card_type(), images=engine.images))
            self.pending_event_cards = 0
            self._apply_landmark_penalties()
            self.next_turn()

    def update(self):
        engine = self.engine
        self._check_eliminations()
        if self._show_dialogs():
            return
        player = engine.players[engine.turn]

        # Clear any highlighting a phase set last frame (e.g. attack/defence
        # selection) so it doesn't linger once no longer relevant.
        for country in engine.countries.values():
            country.shade = 0

        self._check_event_pending(player)

        # Too many cards: the card menu is forced open and nothing else in
        # the game responds until they've traded down to 4 or fewer.
        if player.is_bot:
            self.bot.update()
            return

        if self.must_trade(player):
            engine.card_menu.show = True
            return

        phase = self.phases.get(player.attack)
        if phase is not None:
            phase.update()

        self._handle_end_turn_button()
