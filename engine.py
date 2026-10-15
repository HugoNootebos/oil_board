from contextlib import contextmanager

import pygame as pg
import sounds
import controls
import chat as online_chat
from fonts import game_font
from lang import t, Msg, Join
import numpy as np
from board import CONTINENTS, get_connections, get_countries
from models import Position, Image, Player, Io, View, Gui, Shop, Button, CardMenu, LANDMARKS, WORLD_WIDTH, WRAP_ROUTES
from phases import TurnManager
import random
from random import sample
from player_colors import COUNT_MODE_COLORS, light_tint
from save_load import AUTOSAVE_PATH, SAVE_SLOT_COUNT, slot_path, read_save_name, save_game

# Curated starting-country pools, keyed by player count: one is dealt to
# each player at random, regardless of whether the game is "de Neven" or a
# plain N-player game. A count with no pool here samples the whole map.
# "De 3 Neven": the named default game's players (mode="default").
DEFAULT_PLAYERS = [("Hugo", (60, 110, 230)), ("Joeri", (40, 160, 70)), ("Tètè", (210, 40, 40))]

STARTING_COUNTRY_POOLS = {
    3: ["Sri Lanka", "Pearl Harbor", "Viking"],
    4: ["Zuid-Afrika", "Siberië", "New York", "Ottomaanse Rijk"],
    5: ["Noord-Korea", "Madagaskar", "Ottomaanse Rijk", "Pearl Harbor", "New York"],
    6: ["Gold Coast", "Arabië", "Venezuela", "Canada", "Nigeria", "Siberië"],
}


def open_window(logical_size, fullscreen):
    """The game's window: fullscreen, or as big as fits the screen (at most
    1.25x the logical size). Also a joined online game's (viewer.py)."""
    width, height = logical_size
    if fullscreen:
        return pg.display.set_mode((0, 0), pg.FULLSCREEN)
    desktop_w, desktop_h = pg.display.get_desktop_sizes()[0]
    factor = min(1.25, desktop_w * 0.9 / width, desktop_h * 0.85 / height)
    return pg.display.set_mode((int(width * factor), int(height * factor)))


class Engine:

    def __init__(self, width=960, height=640, mode="prompt", player_count=None, player_names=None,
                 player_bots=None, fullscreen=True):
        # player_count/player_names are only used by mode="count" (a plain
        # N-player game, named on the screen after the new-game menu's
        # 3/4/5/6 buttons -- as opposed to mode="default", the named
        # "de Neven" trio). player_names falls back to generic names if not
        # given (e.g. called directly rather than through that screen).
        self.player_count = player_count
        self.player_names = player_names
        sounds.init_pygame()
        self.font = game_font(20)
        self.logical_size = (width, height)
        self.fullscreen = fullscreen
        window = self._set_display()
        # All UI code draws on this transparent surface at the logical
        # width x height; present() scales it over the map, which is drawn
        # directly in real screen pixels so it stays sharp.
        self.ui = pg.Surface((width, height), pg.SRCALPHA).convert_alpha()
        self.view = View(
            screen=self.ui,
            zoom=View.START_ZOOM,
            offset=Position(*View.START_OFFSET),
            WIDTH=width,
            HEIGHT=height,
        )
        self.view.window = window
        self._layer = None
        self._layer_key = None
        self._layer_ss = 1

        self.io = Io()

        self.colors = {
            "card_background": (240, 240, 240),
            "card_selected": (200, 200, 200),
            "red_button": (245, 150, 150),
            "green_button": (150, 245, 150),
            "outlines": (0, 0, 0),
            "land": (0, 155, 0),
            "sea": (0, 150, 235),
            "rails": (100, 100, 100),
        }

        self.images = {
            "nuclear": Image("nuclear"),
            "spr_food": Image("food"),
            "spr_troops": Image("troops"),
            "spr_wood": Image("wood"),
            "spr_oil": Image("oil"),
            "spr_steel": Image("steel"),
            "spr_nuclear": Image("nuclear"),
            "spr_shop": Image("shop"),
            "spr_cards": Image("cards"),
            "spr_card0": Image("card0"),
            "spr_card1": Image("card1"),
            "spr_card2": Image("card2"),
            "spr_bridge": Image("bridge"),
            "spr_ship": Image("ship", scale=(30,30)),
            "spr_plane": Image("plane", scale=(30,30)),
            "spr_tank": Image("tank", scale=(30,30)),
            "spr_rails": Image("rails"),
            "spr_fort": Image("fort"),
            "spr_nuke": Image("nuke", scale=(30,30)),
            "spr_joker": Image("nuke"),  # full size, for the joker card
        }

        # Smaller versions for HUD use (side panel, buttons, map assets);
        # the shop keeps drawing the full-size sprites from self.images.
        icon = (40, 40)
        mini = (20, 20)
        self.mini_images = {
            "spr_food": Image("food", scale=(13, 20)),
            "spr_wood": Image("wood", scale=mini),
            "spr_steel": Image("steel", scale=mini),
            "spr_oil": Image("oil", scale=mini),
            "spr_nuclear": Image("nuclear", scale=mini),
            "spr_troops": Image("troops", scale=mini),
            "spr_cards": Image("cards", scale=mini),
        }
        self.hud_images = {
            "spr_food": Image("food", scale=(27, 40)),
            "spr_wood": Image("wood", scale=icon),
            "spr_steel": Image("steel", scale=icon),
            "spr_oil": Image("oil", scale=icon),
            "spr_nuclear": Image("nuclear", scale=icon),
            "spr_troops": Image("troops", scale=icon),
            "spr_fort": Image("fort", scale=mini),
            "spr_ship": Image("ship", scale=mini),
            "spr_tank": Image("tank", scale=mini),
            "spr_plane": Image("plane", scale=mini),
            "spr_nuke": Image("nuke", scale=(8, 22)),
            "spr_airport": Image("airport", scale=(24, 24)),
            "spr_developed": Image("developed", scale=(24, 24)),
            "spr_developing": Image("developing", scale=(24, 24)),
            "spr_pagoda": Image("pagoda", scale=(24, 24)),
            "spr_torii": Image("torii", scale=(24, 24)),
            "spr_rails": Image("rails", scale=(30, 30)),
            # The top-left buttons' sprites (BUTTON_SIZE).
            "spr_shop": Image("shop", scale=(38, 38)),
            "spr_cards": Image("cards", scale=(38, 38)),
            "spr_settings": Image("settings", scale=(38, 38)),
            "btn_event": Image("event", scale=(40, 40)),
            "spr_event": Image("event", scale=(56, 56)),  # (the event card dialogs)
            "spr_recruit_phase": Image("recruit_phase", scale=(26, 26)),
            "spr_attack_phase": Image("attack_phase", scale=(26, 26)),
            "spr_move_phase": Image("move_phase", scale=(26, 26)),
        }

        # Full-size art for the shop cards (the shared versions in
        # self.images are shrunk for the map and are too small there).
        self.shop_images = {
            "spr_bridge": Image("bridge"),
            "spr_rails": Image("rails"),
            "spr_nuke": Image("nuke", scale=(45, 120)),
            "spr_ship": Image("ship"),
            "spr_plane": Image("plane"),
            "spr_tank": Image("tank"),
            "spr_fort": Image("fort"),
        }

        # Big versions for the settings menu, where they're dragged from.
        self.landmark_images = {item: Image(item, scale=(90, 90)) for item in LANDMARKS.values()}
        # Full-size originals, scaled to the map zoom as needed (cached).
        self.landmark_full = {item: Image(item) for item in LANDMARKS.values()}
        self._landmark_scaled = {}
        # Country name whose landmark is being dragged out of the settings menu.
        self.dragging_landmark = None

        self._layout()

        self.gui = Gui(self.io, outline_color=self.colors["outlines"])

        # Settings menu: display toggles, "Save As" into one of the named
        # save slots, and the exit request the main loop (runner.py) polls
        # for, since only it can cleanly exit.
        self.settings_open = False
        self.settings = {"continents": False, "fast_bots": False}
        self.pending_quit = False
        # Game controllers (controls.Controls, set by runner.py; None in the
        # headless tools) and the Controllers panel that pairs them with
        # players (_draw_pairing).
        self.controls = None
        self.pairing_open = False
        # An online game's host side (online.HostSession, set when the game
        # starts from the online lobby; None in a local game): the devices
        # that joined, their pointers, and the game's state and layer they get.
        self.online = None
        # A joined online device's copy of the host's game (viewer.Viewer,
        # which draws it but doesn't play it); None otherwise.
        self.mirror = None
        self._pairing_since = 0
        # The event info menu (event button, top right): the active event
        # and how long until the next one is drawn.
        self.event_info_open = False
        # Save As panel: open or not, which slot is being named (None while
        # still picking one), and the name typed so far.
        self.save_as_open = False
        self.save_as_slot = None
        self.save_as_name = ""
        self.save_as_names = []
        # Online, while a device's own menus run (device_context): that
        # device (online.Device); None otherwise.
        self._device = None
        # Where the autosave at the start of each turn goes.
        self.save_path = AUTOSAVE_PATH
        # The tutorial's guide over this game (tutorial.Tutorial, set by
        # tutorial.new_game); None in any other game.
        self.tutorial = None

        self.default_player = Player("mouse", color=(140, 140, 140))
        # What the box at the bottom left says: one line per thing that
        # happened, each a list of [text, (r, g, b)] pieces (see log_action).
        self.action_log = []
        self.hint_rows = 0
        self.action_log_open = False
        self.action_scroll = 0  # lines back from the newest, while open
        # The turn order (bottom right): a square of colour bands, or opened
        # into a box per player. Each device's own, like the action log.
        self.turn_order_open = False
        self.players = self.get_players(mode)
        # player_bots: which of the players (in order) the computer plays
        # (True) and which are human (False). Each bot gets a random
        # personality (see bot.PERSONALITIES).
        import bot
        for player, is_bot in zip(self.players, player_bots or []):
            player.is_bot = bool(is_bot)
            if is_bot:
                player.bot_personality = random.choice(list(bot.PERSONALITIES))
        self.countries = get_countries(self.default_player)
        self.connections = get_connections()

        # Snapshot of each country's troop count as set up on the board,
        # before starting-country bonuses are applied below. Used to
        # restock a country back to its game-start garrison whenever it
        # ends up abandoned (e.g. emptied out via rail redistribution).
        self.initial_country_units = {name: country.units for name, country in self.countries.items()}
        # Where each placed pagoda/torii is drawn on the map: (x, y, half
        # size) in map units, in open land away from circles and lines.
        from landmark_placement import find_spot
        self.landmark_spots = {
            name: find_spot(self.countries[name], self.countries, self.connections) for name in LANDMARKS
        }
        # The map wraps around east-west and is drawn once per copy of the
        # world on screen: (min x, max x) of what one copy draws, its
        # Pacific routes (into the next copy) and troop circles included.
        xs = [p.x for country in self.countries.values() for ring in country.polygon for p in ring]
        for route in WRAP_ROUTES:
            xs.append(min(self.countries[name].mass_center.x for name in route) + WORLD_WIDTH)
        margin = 2 * Io.TROOP_CIRCLE_RADIUS / View.MIN_ZOOM
        self._world_extent = (min(xs) - margin, max(xs) + margin)

        self.reinforcements = 0
        self.all_reinforcements_deployed = True
        self.checked = False
        self.attacked = []
        self.turn_num = 0
        self.card_limit = 0
        self.turn = np.random.randint(len(self.players))

        self.card_menu = CardMenu(self.view, self.players[self.turn])
        self.card_menu.engine = self
        self.turn_manager = TurnManager(self)

        # Fixed, curated starting-country pools by player count (used for
        # both "de Neven" and a plain N-player game); anything else falls
        # back to sampling from the whole map.
        pool = STARTING_COUNTRY_POOLS.get(len(self.players))
        if pool is not None:
            starting_countries = sample(pool, len(self.players))
        else:
            starting_countries = sample(list(self.countries.keys()), len(self.players))

        for index, country in enumerate(starting_countries):
            self.countries[country].owner = self.players[index]
            self.countries[country].units = 15
            # No boat here: each player's first ship from the shop is free
            # (Player.start_ship).
            self.countries[country].airport = True

    # --- display / map rendering ----------------------------------------

    def _set_display(self):
        return open_window(self.logical_size, self.fullscreen)

    def _layout(self):
        """Fit the logical area into the window (letterboxed, aspect kept)
        and rebuild everything sized in real pixels."""
        view = self.view
        width, height = self.logical_size
        sw, sh = view.window.get_size()
        scale = min(sw / width, sh / height)
        view.scale = scale
        view.ox = (sw - width * scale) / 2
        view.oy = (sh - height * scale) / 2
        self._layer_key = None
        self.map_font = game_font(max(8, int(20 * scale)))

        def sized(name, w, h):
            return Image(name, scale=(max(1, int(w * scale)), max(1, int(h * scale))))

        self.map_images = {
            "spr_fort": sized("fort", 30, 30),
            "spr_nuke": sized("nuke", 12, 32),
        }

    def _landmark_shown(self, name):
        """Whether country `name`'s pagoda/torii has been placed by its owner."""
        country = self.countries[name]
        return country.landmark_owner is not None and country.landmark_owner is country.owner

    def _draw_map_landmarks(self):
        """Placed pagodas/torii on the map at their open-land spot, scaled
        with the map (part of the cached map layer)."""
        view = self.view
        for name, item in LANDMARKS.items():
            if not self._landmark_shown(name):
                continue
            x, y, half = self.landmark_spots[name]
            size = max(1, int(round(2 * half * view.zoom * view.draw_scale)))
            key = (item, size)
            if key not in self._landmark_scaled:
                if len(self._landmark_scaled) > 16:
                    self._landmark_scaled.clear()  # sizes from old zoom levels
                self._landmark_scaled[key] = pg.transform.smoothscale(self.landmark_full[item].image, (size, size))
            cx, cy = Position(x, y).to_px(view)
            rect = view.map_surface.blit(self._landmark_scaled[key], (cx - size // 2, cy - size // 2))
            # Same as the radioactive hazard band (Country._draw_hazard_band):
            # blitting a translucent sprite onto the display-format map layer
            # also blends its alpha channel, leaving transparent pixels that
            # show up as a solid box on screen -- put full opacity back.
            view.map_surface.fill((0, 0, 0, 255), rect, special_flags=pg.BLEND_RGBA_MAX)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.view.window = self._set_display()
        self._layout()

    def _map_keys(self):
        """(view key, state key): the first changes while panning/zooming,
        the second when the board itself changes (colours, highlights,
        rails...)."""
        view = self.view
        view_key = (view.scale, view.ox, view.oy, view.window.get_size(), view.zoom, view.offset.x, view.offset.y)
        state_key = (
            tuple((tuple(int(x) for x in c.owner.color), c.shade, c.radioactive > 0, c.developed,
                   c.dormant_owner is not None)
                  for c in self.countries.values()),
            tuple((c.kind, c.rails) for c in self.connections),
            tuple(self._landmark_shown(name) for name in LANDMARKS),
            self.settings["continents"],
        )
        return view_key, state_key

    def _logical_clip(self, factor=1):
        view = self.view
        width, height = self.logical_size
        return pg.Rect(
            int(view.ox * factor), int(view.oy * factor),
            int(round(width * view.scale * factor)), int(round(height * view.scale * factor)),
        )

    # Country borders and connections are drawn partly see-through.
    BORDER_COLOR = (120, 120, 120)
    BORDER_OPACITY = 204      # 80%
    CONNECTION_OPACITY = 178  # 70%
    # "Show continents" (settings menu): countries filled in their
    # continent's colour instead of their owner's (the troop circles keep
    # the owner's).
    CONTINENT_COLORS = {
        "North America": (240, 210, 40),   # yellow
        "South America": (220, 60, 50),    # red
        "Europe": (60, 110, 220),          # blue
        "Africa": (150, 100, 55),          # brown
        "Asia": (60, 170, 70),             # green
        "Oceania": (150, 80, 190),         # purple
    }
    CONTINENT_FILL = {name: color for continent, color in CONTINENT_COLORS.items()
                      for name in CONTINENTS[continent]}

    @staticmethod
    @contextmanager
    def _blended(surface, opacity):
        """Whatever is drawn onto `surface` inside the block ends up at
        `opacity` (0-255): it's drawn normally, then a snapshot from before
        is laid back over it at the remaining opacity. (Drawing onto a
        transparent layer instead leaves artifacts on antialiased edges.)"""
        before = surface.copy()
        yield
        before.set_alpha(255 - opacity)
        clip = surface.get_clip()
        surface.set_clip(None)
        surface.blit(before, (0, 0))
        surface.set_clip(clip)

    def _render_layer(self, ss, background_color):
        """Countries + connections in real pixels. ss=2 draws at double
        size and shrinks it back, which antialiases every edge."""
        view = self.view
        sw, sh = view.window.get_size()
        surface = pg.Surface((sw * ss, sh * ss))
        # Fully opaque, alpha channel included: on a display format that has
        # one, alpha-blended sprites (e.g. the radioactive hazard band) would
        # otherwise blend against alpha 0 and come out as a solid box.
        surface.fill((0, 0, 0, 255))
        view.map_surface = surface
        view.draw_scale = view.scale * ss
        view.draw_ox = view.ox * ss
        view.draw_oy = view.oy * ss
        clip = self._logical_clip(ss)
        surface.set_clip(clip)
        surface.fill(tuple(background_color) + (255,), clip)
        copies = view.copies(self._world_extent)
        by_continent = self.settings["continents"]
        for dx in copies:
            with view.shifted(dx):
                for country in self.countries.values():
                    fill = self.CONTINENT_FILL.get(country.name) if by_continent else None
                    country.draw(view, border_color=self.colors["outlines"], draw_border=False, fill=fill)
        with self._blended(surface, self.BORDER_OPACITY):
            for dx in copies:
                with view.shifted(dx):
                    for country in self.countries.values():
                        country.draw_border(view, self.BORDER_COLOR)
        with self._blended(surface, self.CONNECTION_OPACITY):
            for dx in copies:
                with view.shifted(dx):
                    for connection in self.connections:
                        connection.draw(self.countries, self.colors, view, outline_color=self.colors["outlines"])
        for dx in copies:
            with view.shifted(dx):
                self._draw_map_landmarks()
        surface.set_clip(None)
        if ss != 1:
            surface = pg.transform.smoothscale(surface, (sw, sh))
        return surface

    def draw_world(self, background_color=(200, 200, 255)):
        view = self.view
        self.ui.fill((0, 0, 0, 0))
        if self.online is not None:
            self.online.new_frame()
        # The (expensive) antialiased map is cached. While the view is
        # panning/zooming a fast unsmoothed version is shown, and the smooth
        # one replaces it as soon as it settles. A change to the board
        # alone (a click highlighting or conquering a country) goes straight
        # to the smooth version so nothing visibly flips between the two.
        view_key, state_key = self._map_keys()
        if self._layer_key is None or view_key != self._layer_key[0]:
            self._layer = self._render_layer(1, background_color)
            self._layer_ss = 1
        elif state_key != self._layer_key[1] or self._layer_ss == 1:
            self._layer = self._render_layer(2, background_color)
            self._layer_ss = 2
        self._layer_key = (view_key, state_key)
        view.window.blit(self._layer, (0, 0))

        view.map_surface = view.window
        view.draw_scale = view.scale
        view.draw_ox = view.ox
        view.draw_oy = view.oy
        view.window.set_clip(self._logical_clip())
        for dx in view.copies(self._world_extent):
            with view.shifted(dx):
                for country in self.countries.values():
                    country.draw_troops(self.map_font, view)
        view.window.set_clip(None)

    def present(self):
        """Scale the UI layer over the map (call right before flip)."""
        view = self.view
        if self.online is not None:
            # The game's layer, which every device that joined shows over its
            # own map: before what's this computer's own (the action log, the
            # country info panel, its menus, its chat, the cursors).
            self.online.capture(self.ui)
        self._draw_turn_order()
        self._draw_action_box()  # (an opened log goes over the turn order too)
        width, height = self.logical_size
        size = (int(round(width * view.scale)), int(round(height * view.scale)))
        ui = self.ui if size == (width, height) else pg.transform.smoothscale(self.ui, size)
        view.window.blit(ui, (int(view.ox), int(view.oy)))
        if self.online is not None:
            # What's this computer's own: the info panel of the country its
            # pointer is over, its menus and its chat.
            self.online.show_hovers(view.window, view.scale, (view.ox, view.oy))
            self.online.show_menus(view.window, view.scale, (view.ox, view.oy))
            self.online.draw_chat(view.window, view.scale, (view.ox, view.oy))
        if self.controls is not None and self.controls.pads:
            self.controls.draw(view.window, view.scale, (view.ox, view.oy), self._pad_looks())
        if self.online is not None:
            self.online.draw_cursors(view.window, view.scale, (view.ox, view.oy))

    def _pad_looks(self):
        """Each game controller's cursor: its player's colour (white while
        unpaired) and faded when it can't click right now. The controller
        lights up in that colour too, where it has a light."""
        looks = {}
        for pad in self.controls.pads:
            player = self.controls.player_of(pad, self.players)
            color = player.color if player is not None else controls.UNPAIRED_COLOR
            looks[pad] = (color, pad not in self.controls.clickers)
            pad.set_led(color)
        return looks

    def log_action(self, *parts):
        """Add a line to the bottom-left box's history: strings are drawn
        white, a Player as their name in (a light shade of) their colour.
        A lang.Msg is kept as it is, so it's translated whenever it's drawn
        (also after a save is loaded in the other language)."""
        self.action_log.append([
            [part.name, light_tint(part.color, self.NAME_TINT)] if isinstance(part, Player)
            else [part if isinstance(part, Msg) else str(part), (255, 255, 255)]
            for part in parts
        ])
        del self.action_log[:-self.ACTION_LOG_MAX]
        if self.action_log_open and self.action_scroll:
            # Reading further back: keep the same lines in view.
            self.action_scroll = min(self.action_scroll + 1, self._action_scroll_max())

    def log_destroyed(self, owner, country_name, ships=0, tanks=0, planes=0, fort=0):
        """Log the loss of `owner`'s assets in a country, e.g. "Player 2's
        ship was destroyed in Japan". Nothing is logged when nothing was
        lost."""
        items = [Msg(plural, k) if k > 1 else word
                 for k, word, plural in ((ships, "ship", "{} ships"), (tanks, "tank", "{} tanks"),
                                         (planes, "plane", "{} planes"))
                 if k > 0]
        if fort > 0:
            items.append("fort")
        if not items or owner is None:
            return
        single = len(items) == 1 and max(ships, tanks, planes, 1) == 1
        self.log_action(owner, Msg("'s {} was destroyed in {}" if single else "'s {} were destroyed in {}",
                                   Join(items, ", ", " and "), country_name))

    def log_wiped(self, country):
        """Log every asset (ships, tanks, planes, fort) in `country` that's
        about to be wiped out, as its current owner's loss."""
        self.log_destroyed(country.owner, country.name, country.ships, country.tanks,
                           country.planes, country.fort_lvl)

    NAME_TINT = 0.35
    ACTION_BOX_H = 30          # collapsed: one line
    ACTION_BOX_MAX_W = 620
    ACTION_LOG_MAX = 500       # lines of history kept
    ACTION_LOG_ROWS = 10       # lines shown when expanded
    ACTION_ROW_H = 24
    ACTION_OPEN_W = 520

    def _action_box_rect(self):
        """The bottom-left box's rect in logical UI coordinates, or None
        while there's nothing to show."""
        if not self.action_log:
            return None
        view = self.view
        if self.action_log_open:
            width = min(max(self.ACTION_OPEN_W, self._action_log_width() + 26), view.WIDTH)
            height = self.ACTION_LOG_ROWS * self.ACTION_ROW_H + 12
        else:
            pieces = [self.font.size(str(text))[0] for text, _ in self.action_log[-1]]
            width = min(sum(pieces) + 22, self.ACTION_BOX_MAX_W)
            height = self.ACTION_BOX_H
        return pg.Rect(0, view.HEIGHT - height, width, height)

    def _action_log_width(self):
        """Width of the longest line in the whole history (so the open box
        doesn't change size while scrolling); cached until a line is added."""
        key = (len(self.action_log), id(self.action_log[-1]))
        if getattr(self, "_action_width_key", None) != key:
            self._action_width_key = key
            self._action_width = max(sum(self.font.size(str(text))[0] for text, _ in line)
                                     for line in self.action_log)
        return self._action_width

    def _remote_pointer(self):
        """Online, whether Io follows a joined device's pointer (which has its
        own action log, view and menus)."""
        return self.online is not None and self.online.is_remote(self.io.source)

    def _action_scroll_max(self):
        return max(len(self.action_log) - self.ACTION_LOG_ROWS, 0)

    def _handle_action_box(self):
        """A click on the box opens/closes the history. Runs before the
        phases each frame so the click doesn't also hit what's under it."""
        rect = self._action_box_rect()
        if rect is None or self.modal_open or self._remote_pointer():
            return
        io = self.io
        if rect.collidepoint(io.mouse_position.x, io.mouse_position.y):
            if io.left_pressed:
                self.action_log_open = not self.action_log_open
                self.action_scroll = 0
            if io.left_pressed or io.right_clicked:
                io.left_pressed = 0
                io.right_clicked = False

    def scroll_action_log(self, direction):
        """Mouse wheel over the open history: direction +1 scrolls back into
        the past, -1 forward. True when the wheel was used up by it."""
        rect = self._action_box_rect()
        if rect is None or not self.action_log_open or self.modal_open or self._remote_pointer():
            return False
        if not rect.collidepoint(self.io.mouse_position.x, self.io.mouse_position.y):
            return False
        self.action_scroll = max(0, min(self.action_scroll + direction, self._action_scroll_max()))
        return True

    def _draw_action_box(self):
        """Black 80% box flush with the bottom-left corner of the screen:
        the last line, or (opened) the last 10 with the older ones a
        scroll away. Drawn last, over everything else."""
        rect = self._action_box_rect()
        if rect is None:
            return
        box = pg.Surface(rect.size, pg.SRCALPHA)
        pg.draw.rect(box, (0, 0, 0, 204), box.get_rect(), border_top_right_radius=6)
        if self.action_log_open:
            self.action_scroll = min(self.action_scroll, self._action_scroll_max())
            end = len(self.action_log) - self.action_scroll
            lines = self.action_log[max(end - self.ACTION_LOG_ROWS, 0):end]
            # Newest at the bottom, like the collapsed line it grew from.
            top = rect.h - 6 - len(lines) * self.ACTION_ROW_H
            for n, line in enumerate(lines):
                self._blit_action_line(box, line, 10, top + n * self.ACTION_ROW_H, self.ACTION_ROW_H, rect.w - 26)
            if self._action_scroll_max():
                track = pg.Rect(rect.w - 10, 8, 4, rect.h - 16)
                pg.draw.rect(box, (255, 255, 255, 50), track, border_radius=2)
                total = len(self.action_log)
                thumb_h = max(18, track.h * self.ACTION_LOG_ROWS // total)
                room = track.h - thumb_h
                thumb_y = track.y + room - room * self.action_scroll // self._action_scroll_max()
                pg.draw.rect(box, (255, 255, 255, 170), pg.Rect(track.x, thumb_y, 4, thumb_h), border_radius=2)
        else:
            self._blit_action_line(box, self.action_log[-1], 10, 0, rect.h, rect.w - 12)
        self.ui.blit(box, rect.topleft)

    # --- the turn order (bottom right, over the phase box) ------------------------------

    TURN_ORDER_GAP = 4
    TURN_ORDER_LIFT = 14  # the opened boxes end this far above the square's bottom

    def _turn_order_players(self):
        """The players still in the game in turn order, whose turn it is first."""
        n = len(self.players)
        current = self.players[self.turn]
        players = [self.players[(self.turn + k) % n] for k in range(n)]
        return [p for p in players if p is current or not self.turn_manager._is_out(p)]

    def _turn_order_opened(self):
        """The players in the opened turn order, or None while it's the
        square: the others only (the current player's stock is on the left)."""
        others = self._turn_order_players()[1:]
        return others if self.turn_order_open and others else None

    def _turn_order_rect(self):
        """Where the turn order is (logical): the square right above the
        phase box, or opened its boxes, flush with the right edge."""
        view, gui = self.view, self.gui
        size = self.BUTTON_SIZE
        bottom = view.HEIGHT - gui.PHASE_BOX_H - self.BUTTON_MARGIN
        others = self._turn_order_opened()
        if others is None:
            return pg.Rect(view.WIDTH - self.BUTTON_MARGIN - size, bottom - size, size, size)
        height = len(others) * (gui.TURN_BOX_H + self.TURN_ORDER_GAP) - self.TURN_ORDER_GAP
        bottom -= self.TURN_ORDER_LIFT
        return pg.Rect(view.WIDTH - gui.TURN_BOX_W, bottom - height, gui.TURN_BOX_W, height)

    def _turn_order_hidden(self):
        """Whether the turn order is left out: under a dialog or a menu of
        this device's own, or while the game's shop or cards are open on this
        screen (a joined device works that out itself: viewer.py)."""
        if self.modal_open:
            return True
        if self.mirror is not None:
            return False
        player = self.players[self.turn]
        here = self.online is None or self.online.current_device() == 0
        return here and ((player.attack == 3 and player.subattack < 8) or self.card_menu.show)

    def _handle_turn_order(self, hidden=False):
        """A click on the turn order opens or closes it and goes no further;
        the map under it is out of reach. Runs before the phases each frame,
        like _handle_action_box."""
        if hidden or self._turn_order_hidden() or self._remote_pointer():
            return
        rect = self._turn_order_rect()
        io = self.io
        io.button(("r", rect.x, rect.y, rect.w, rect.h))
        if rect.collidepoint(io.mouse_position.x, io.mouse_position.y):
            if io.left_pressed:
                self.turn_order_open = not self.turn_order_open
            if io.left_pressed or io.right_clicked:
                io.left_pressed = 0
                io.right_clicked = False

    def _draw_turn_order(self, hidden=False):
        """The turn order: closed, a square with a band in each player's
        colour, whose turn it is on top; opened, a box per other player with
        their stock (Gui.draw_turn_box), the next player on top and the event
        tag on whoever draws the next event card. Each device's own (drawn
        after the game's layer is taken), under the action log."""
        if hidden or self._turn_order_hidden():
            return
        view, gui, manager = self.view, self.gui, self.turn_manager
        rect = self._turn_order_rect()
        others = self._turn_order_opened()
        if others is None:
            players = self._turn_order_players()
            inner = rect.inflate(-4, -4)
            top = inner.y
            for i, player in enumerate(players):
                bottom = inner.y + inner.h * (i + 1) // len(players)
                color = gui._faded(player.color) if player.name in manager.skip_turns else player.color
                pg.draw.rect(view.screen, color, pg.Rect(inner.x, top, inner.w, bottom - top))
                top = bottom
            pg.draw.rect(view.screen, (0, 0, 0), rect, 2)
            return
        upcoming = manager.turns_until_next_event()
        if self.tutorial is not None and self.tutorial.active:
            upcoming = None  # (the tutorial holds the events back)
        y = rect.y
        for player in others:
            amounts = {r: getattr(player, r) for r in ("food", "wood", "steel", "oil", "nuclear")}
            amounts["helmets"] = self.production(player)["helmets"]
            amounts["cards"] = len(player.cards)
            gui.draw_turn_box(view, player, amounts, pg.Rect(rect.x, y, rect.w, gui.TURN_BOX_H),
                              event=upcoming is not None and upcoming[1] is player,
                              skips=player.name in manager.skip_turns)
            y += gui.TURN_BOX_H + self.TURN_ORDER_GAP

    def _blit_action_line(self, surface, line, x, y, height, max_x):
        for text, color in line:
            piece = self.font.render(str(text), True, tuple(color))
            surface.blit(piece, (x, y + (height - piece.get_height()) // 2))
            x += piece.get_width()
            if x > max_x:
                break

    def draw_gui(self):
        def handle_card_menu():
            if self.turn_manager.must_trade():
                sounds.play("error")
                return  # can't close the menu until enough cards are traded
            if not self.card_menu.show and self.turn_manager.attack_in_progress():
                sounds.play("error")
                return  # dice are cast: the attack has to finish first
            if not self.card_menu.show and not self.players[self.turn].cards:
                sounds.play("error")
                return  # nothing to show
            self.card_menu.player = self.players[self.turn]
            self.card_menu.trade_mode = False
            self.card_menu.show = not self.card_menu.show
            self.card_menu.organize_cards()
            self.card_menu.use_cards_automatic()

        self._handle_action_box()
        self._handle_turn_order()
        if self.io.hover_country is not None and self.online is None:
            # (Online every device shows the country its own pointer is
            # over: online.HostSession.show_hovers.)
            self._draw_country_info(self.io.hover_country)
        player = self.players[self.turn]
        self.gui.draw_player_stats(self.view, player, self.font, self.STATS_POS, self.production(player))
        self.gui.draw_attack_phase(
            self.view, self.players[self.turn], images=self.hud_images, outline_color=self.colors["outlines"],
            end_turn_enabled=self.turn_manager.can_end_turn(),
        )

        # Online every device opens these menus for itself (own_menus);
        # only the shop and cards of the player whose turn it is are the
        # game's, and those only for their own device.
        local = self.online is None
        # Settings sits top-left on its own.
        settings_button = self._settings_button()
        settings_button.draw(self.view, self.io)
        if not self.turn_manager.dialog_active and local:
            # Gated on the dialog only (not modal_open), so this stays
            # clickable even while its own menu is what's blocking
            # everything else -- otherwise there'd be no way to close it.
            settings_button.release_button(self.toggle_settings, self.io)
        # On a bot's turn the shop and cards are the bot's business.
        blocked = self.modal_open or self.bot_turn or not (
            local or self.online.device_of_pointer(self.io.source) == self.online.current_device())

        # Shop and cards sit top-left too, to the right of settings.
        card_menu_button = self._card_button()
        card_menu_button.draw(self.view, self.io)
        if not blocked:
            card_menu_button.release_button(handle_card_menu, self.io)
        shop_menu_button = self._shop_button()
        shop_menu_button.draw(self.view, self.io)
        if not blocked:
            shop_menu_button.release_button(self.turn_manager.toggle_shop, self.io)

        # Event info sits top-left too, after the cards button.
        event_button = self._event_button()
        event_button.draw(self.view, self.io)
        if not self.turn_manager.dialog_active and not self.settings_open and not self.pairing_open and local:
            event_button.release_button(self.toggle_event_info, self.io)

        if self.settings_open and local:
            self._draw_settings_menu()
        elif self.event_info_open and local:
            self._draw_event_info()
        elif self.pairing_open and local:
            self._draw_pairing()

    def _draw_country_info(self, name):
        """The info panel (top right) of the country called `name`, on view.screen."""
        self.gui.draw_country_stats(view=self.view, country=self.countries[name], font=self.font,
                                    images=self.hud_images)

    def country_panel(self, name):
        """The info panel of the country called `name` on its own (online,
        for a device's pointer): (image, its rect in the logical 960x640)."""
        view = self.view
        layer = getattr(self, "_panel_layer", None)
        if layer is None or layer.get_size() != (view.WIDTH, view.HEIGHT):
            layer = self._panel_layer = pg.Surface((view.WIDTH, view.HEIGHT), pg.SRCALPHA)
        layer.fill((0, 0, 0, 0))
        screen, view.screen = view.screen, layer
        try:
            self._draw_country_info(name)
        finally:
            view.screen = screen
        rect = layer.get_bounding_rect()
        return layer.subsurface(rect).copy(), rect

    def device_country_at(self, position, chat=None):
        """The country a device's pointer at `position` (logical) is over,
        for that device's info panel: None through the buttons on screen,
        the chat (its button is every device's; `chat` the host's own, panel
        and all, and the turn order: this computer's) or a dialog."""
        if self.modal_open:
            return None
        point = (int(position[0]), int(position[1]))
        if online_chat.BUTTON.collidepoint(point) or (chat is not None and chat.covers(point)):
            return None
        if chat is not None and not self._turn_order_hidden() and self._turn_order_rect().collidepoint(point):
            return None
        return self.io.country_at(self.view, self.countries.values(), Position(*point), self.io.buttons)

    # Top-left row: settings, shop, cards, event card; the chat button
    # (online) under settings (chat.BUTTON), the current player's stats
    # under that (also in a local game, where that place stays empty).
    BUTTON_MARGIN = 10
    BUTTON_SIZE = 44
    BUTTON_STEP = 50  # 44 wide + 6 gap
    STATS_POS = (0, BUTTON_MARGIN + 2 * BUTTON_STEP)  # (flush with the left edge)

    @property
    def bot_turn(self):
        """Whether the computer is playing the current turn."""
        return self.players[self.turn].is_bot

    @property
    def modal_open(self):
        """Whether some full-screen-ish overlay (an elimination/win dialog
        or the settings menu) should freeze everything else."""
        # (Online these are one device's own: the game goes on.)
        own = self.online is None and (self.settings_open or self.event_info_open or self.pairing_open)
        return self.dialog_up or own

    @property
    def dialog_up(self):
        """Whether a dialog (an elimination, a new event card, the win
        screen) is up; on a joined online device whether it is on the host."""
        return self.mirror.dialog if self.mirror is not None else self.turn_manager.dialog_active

    def local_players(self):
        """The players on this computer: all of them, except in an online
        game (those that joined from another device are left out; on a joined
        device its own)."""
        if self.mirror is not None:
            return self.mirror.local_players(self.players)
        return self.players if self.online is None else self.online.local_players(self.players)

    def toggle_event_info(self):
        self.event_info_open = not self.event_info_open
        self.io.left_pressed = 0  # the click shouldn't reach the map behind the button

    def open_pairing(self):
        self.settings_open = False
        self.event_info_open = False
        self.pairing_open = True
        self._pairing_since = pg.time.get_ticks()

    def toggle_settings(self):
        self.event_info_open = False
        self.pairing_open = False
        self.settings_open = not self.settings_open
        self.dragging_landmark = None
        self._close_save_as()

    SAVE_NAME_MAX = 24

    @property
    def typing_save_name(self):
        """Whether keystrokes are going into the Save As name box (so the
        main loop shouldn't treat e.g. Escape as its own shortcut)."""
        return self.settings_open and self.save_as_open and self.save_as_slot is not None

    def _close_save_as(self):
        self.save_as_open = False
        self.save_as_slot = None
        self.save_as_name = ""

    def _commit_save_as(self):
        name = self.save_as_name.strip()
        if not name:
            return
        save_game(self, self.turn_manager, slot_path(self.save_as_slot), name=name)
        self._close_save_as()

    def handle_events(self, events):
        """Keyboard input for the Save As name box, fed the raw pygame
        events by the main loop each frame."""
        if not self.typing_save_name:
            return
        for event in events:
            if event.type == pg.TEXTINPUT:
                self.save_as_name = (self.save_as_name + event.text)[:self.SAVE_NAME_MAX]
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_BACKSPACE:
                    self.save_as_name = self.save_as_name[:-1]
                elif event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                    self._commit_save_as()
                elif event.key == pg.K_ESCAPE:
                    self.save_as_slot = None  # back to picking a slot

    def _menu_button(self, rect, text, color, mouse, enabled=True):
        """A settings-menu button; returns True when clicked."""
        screen = self.view.screen
        hovered = enabled and rect.collidepoint(mouse)
        if not enabled:
            color = (170, 170, 170)
        elif hovered:
            color = tuple(min(255, c + 15) for c in color)
        pg.draw.rect(screen, color, rect)
        pg.draw.rect(screen, (0, 0, 0), rect, 2)
        label = self.font.render(text, True, (0, 0, 0))
        screen.blit(label, (rect.centerx - label.get_width() // 2, rect.centery - label.get_height() // 2))
        clicked = self.io.button(("r", rect.x, rect.y, rect.w, rect.h))
        if clicked and not enabled:
            sounds.play("error")
        return bool(enabled and clicked)

    def _draw_save_as(self, x, y, w, h, mouse):
        """Save As: pick one of the save slots, type a name for it, Save."""
        screen = self.view.screen
        screen.blit(self.font.render(t("Save As"), True, (0, 0, 0)), (x + 15, y + 10))
        for i in range(SAVE_SLOT_COUNT):
            rect = pg.Rect(x + 20, y + 45 + i * 60, w - 40, 50)
            selected = self.save_as_slot == i
            pg.draw.rect(screen, (255, 255, 255) if selected else (235, 235, 235), rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 3 if selected else 2)
            screen.blit(self.font.render(t("Slot {}").format(i + 1), True, (90, 90, 90)), (rect.x + 8, rect.y + 3))
            if selected:
                text = self.font.render(self.save_as_name, True, (0, 0, 0))
                screen.blit(text, (rect.x + 8, rect.y + 25))
                if (pg.time.get_ticks() // 500) % 2 == 0:
                    cx = rect.x + 10 + text.get_width()
                    pg.draw.line(screen, (0, 0, 0), (cx, rect.y + 27), (cx, rect.bottom - 5), 2)
            else:
                name = self.save_as_names[i]
                text = self.font.render(name if name else t("(empty)"), True, (0, 0, 0) if name else (130, 130, 130))
                screen.blit(text, (rect.x + 8, rect.y + 25))
                if self.io.left_pressed and rect.collidepoint(mouse):
                    self.save_as_slot = i
                    self.save_as_name = (name or "")[:self.SAVE_NAME_MAX]

        hint_y = y + 45 + SAVE_SLOT_COUNT * 60
        if self.save_as_slot is None:
            hint = t("Click a slot to save there")
        elif self.save_as_names[self.save_as_slot]:
            hint = t("Type a name -- overwrites this slot")
        else:
            hint = t("Type a name, then Save or Enter")
        screen.blit(self.font.render(hint, True, (0, 0, 0)), (x + 20, hint_y))

        save_rect = pg.Rect(x + 20, y + h - 110, w - 40, 40)
        if self._menu_button(save_rect, t("Save"), (150, 245, 150), mouse,
                             enabled=self.save_as_slot is not None and bool(self.save_as_name.strip())):
            self._commit_save_as()
        back_rect = pg.Rect(x + 20, y + h - 60, w - 40, 40)
        if self._menu_button(back_rect, t("Back"), (220, 220, 220), mouse):
            self._close_save_as()

    def _draw_settings_menu(self):
        view = self.view
        screen = view.screen
        io = self.io
        mouse = (io.mouse_position.x, io.mouse_position.y)

        if self.dragging_landmark is not None:
            self._drag_landmark()
            return

        self._dim()

        # Two columns; the Save As name picker keeps the narrow tall panel.
        if self.save_as_open:
            w, h = 340, 562
        else:
            w, h = 600, 340
        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        pg.draw.rect(screen, self.SETTINGS_COLOR, pg.Rect(x, y, w, h))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, w, h), 3)

        # A click outside the panel closes the menu (the settings button
        # itself toggles it, so leave that click to the button).
        btn = self._settings_button()
        on_button = pg.Rect(btn.pos.x, btn.pos.y, btn.width, btn.height).collidepoint(mouse)
        if io.left_pressed and not on_button and not pg.Rect(x, y, w, h).collidepoint(mouse):
            self.toggle_settings()
            io.left_pressed = 0
            return

        if self.save_as_open:
            self._draw_save_as(x, y, w, h, mouse)
            return

        screen.blit(self.font.render(t("Settings"), True, (0, 0, 0)), (x + 15, y + 10))

        col_w = (w - 60) // 2
        col_x = (x + 20, x + 40 + col_w)

        # Online a joined device's settings (viewer.py) are mostly to look
        # at: the game, its saves, the bots' speed and the controllers are
        # the host's. What its own map shows is its own.
        remote = self.mirror is not None

        quit_rect = pg.Rect(col_x[0], y + 45, col_w, 40)
        if self._menu_button(quit_rect, t("Exit Game"), (245, 150, 150), mouse, enabled=not remote):
            self.pending_quit = True

        save_as_rect = pg.Rect(col_x[1], y + 45, col_w, 40)
        if self._menu_button(save_as_rect, t("Save As"), (150, 200, 245), mouse, enabled=not remote):
            self.save_as_open = True
            self.save_as_slot = None
            self.save_as_names = [read_save_name(slot_path(i)) for i in range(SAVE_SLOT_COUNT)]

        # Left column: what the map shows; right column: bots.
        columns = [
            [("continents", "Show continents")],
            [("fast_bots", "Fast bots")],
        ]
        for c, toggles in enumerate(columns):
            for i, (key, text) in enumerate(toggles):
                row = pg.Rect(col_x[c], save_as_rect.bottom + 25 + i * 46, col_w, 34)
                if self._toggle_switch(row, text, self.settings[key], mouse,
                                       enabled=not (remote and key == "fast_bots")):
                    self.settings[key] = not self.settings[key]

        if self.controls is not None and self.controls.pads:
            # (Every device pairs its own controllers with its own players.)
            pads_rect = pg.Rect(col_x[1], save_as_rect.bottom + 25 + len(columns[1]) * 46, col_w, 40)
            if self._menu_button(pads_rect, t("Controllers"), (150, 200, 245), mouse):
                self.open_pairing()

        # China's pagoda and Japan's torii: owed by whoever holds that
        # country without one, who drags it from here onto the map. Once
        # placed it's gone from here, until the country loses it again
        # (back to the mouse, or conquered by someone else).
        # (Online only on the device of the player whose turn it is.)
        if self.mirror is not None:
            owed = self.mirror.owed if self.mirror.current_device() == self.mirror.me else set()
        else:
            mine = self.online is None or self.online.current_device() == 0
            owed = self.turn_manager.landmarks_owed if mine else {}
        size = 90
        gap = 30
        lx = x + w * 0.5 - size - gap * 0.5
        ly = y + h - size - 25
        for i, (name, item) in enumerate(LANDMARKS.items()):
            if self._landmark_shown(name):
                continue
            rect = pg.Rect(int(lx + i * (size + gap)), int(ly), size, size)
            screen.blit(self.landmark_images[item].image, rect)
            if name in owed and io.left_pressed and rect.collidepoint(mouse):
                self.dragging_landmark = name

        # Swallow every click while the menu is open, whether or not it hit
        # a control above -- nothing behind the dimmed overlay should react.
        if io.left_pressed:
            io.left_pressed = 0

    def _toggle_switch(self, row, text, on, mouse, enabled=True):
        """A labelled on/off switch filling `row`; returns True when clicked
        (never when not `enabled`: then the error sound)."""
        screen = self.view.screen
        track = pg.Rect(row.x, row.centery - 12, 46, 24)
        hovered = enabled and row.collidepoint(mouse)
        color = (60, 180, 80) if on else (170, 170, 170)
        if hovered:
            color = tuple(min(255, c + 20) for c in color)
        pg.draw.rect(screen, color, track, border_radius=12)
        pg.draw.rect(screen, (0, 0, 0), track, 2, border_radius=12)
        knob_x = track.right - 12 if on else track.x + 12
        pg.draw.circle(screen, (255, 255, 255), (knob_x, track.centery), 9)
        pg.draw.circle(screen, (0, 0, 0), (knob_x, track.centery), 9, 2)
        label = self.font.render(t(text), True, (0, 0, 0) if enabled else (110, 110, 110))
        screen.blit(label, (track.right + 12, row.centery - label.get_height() // 2))
        clicked = self.io.button(("r", row.x, row.y, row.w, row.h))
        if clicked and not enabled:
            sounds.play("error")
        return bool(enabled and clicked)

    def _drag_landmark(self):
        """A pagoda/torii follows the mouse over the (undimmed) map;
        letting go over its own country places it there and closes the
        menu, over the other landmark country punishes its own country
        (see TurnManager.misplace_landmark), anywhere else and it goes back
        into the menu."""
        io = self.io
        name = self.dragging_landmark
        sprite = self.landmark_images[LANDMARKS[name]].image
        mx, my = io.mouse_position.x, io.mouse_position.y
        self.view.screen.blit(sprite, (mx - sprite.get_width() // 2, my - sprite.get_height() // 2))
        if not io.mouse_state[0] and self.mirror is not None:
            # A joined device: dropped on its own map, placed by the host.
            self.dragging_landmark = None
            if io.hover_country == name or io.hover_country in LANDMARKS:
                self.mirror.place_landmark(name, io.hover_country)
                self.settings_open = False
        elif not io.mouse_state[0]:
            self.dragging_landmark = None
            if name in self.turn_manager.landmarks_owed:
                if io.hover_country == name:
                    self.turn_manager.place_landmark(name)
                    self.settings_open = False
                elif io.hover_country in LANDMARKS:
                    # The pagoda on Japan / torii on China: its own country
                    # is punished as if it had been forgotten.
                    self.turn_manager.misplace_landmark(name, io.hover_country)
                    self.settings_open = False
        if io.left_pressed:
            io.left_pressed = 0

    SETTINGS_COLOR = (255, 240, 170)  # light yellow, for the button and its menu

    def _dim(self):
        """Darken everything behind a menu. A joined device's own menu
        (device_context) leaves that to the device: it dims its picture."""
        if self._device is not None and self._device.id != 0:
            self._device.dim = True
            return
        dim = pg.Surface((self.view.WIDTH, self.view.HEIGHT), pg.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        self.view.screen.blit(dim, (0, 0))

    def _top_left_button(self, index, color, sprite, outline_width):
        return Button(
            pos=Position(self.BUTTON_MARGIN + index * self.BUTTON_STEP, self.BUTTON_MARGIN),
            width=self.BUTTON_SIZE,
            height=self.BUTTON_SIZE,
            color=color,
            outline_width=outline_width,
            image=self.hud_images[sprite],
        )

    def _settings_button(self):
        return self._top_left_button(0, self.SETTINGS_COLOR, "spr_settings", 4 if self.settings_open else 2)

    SHOP_COLOR = (165, 165, 255)  # same blue as the shop menu's background

    def _shop_button(self, outline_width=2):
        return self._top_left_button(1, self.SHOP_COLOR, "spr_shop", outline_width)

    def _card_button(self, outline_width=2):
        return self._top_left_button(2, CardMenu.PANEL_COLOR, "spr_cards", outline_width)

    EVENT_COLOR = (250, 225, 130)  # same yellow as the event card dialog

    def _event_button(self):
        return self._top_left_button(3, self.EVENT_COLOR, "btn_event", 4 if self.event_info_open else 2)

    def _draw_event_info(self):
        """The active event card (as shown when it was drawn), or "No
        active event card", plus how many turns until the next one."""
        view = self.view
        screen = view.screen
        manager = self.turn_manager
        event = manager.current_event

        self._dim()

        name_font = game_font(28, bold=True)
        desc_font = game_font(19)
        w = 520
        text_w = w - 80
        name = t(event.name) if event is not None else t("No active event card")
        lines = manager._wrap_text(t(event.description), desc_font, text_w) if event is not None else []
        extra = event.panel_lines(self) if event is not None else []  # e.g. a scoreboard

        upcoming = manager.turns_until_next_event()
        if upcoming is None:
            next_text = t("No more event cards")
        else:
            turns, player = upcoming
            if turns == 1:
                next_text = t("Next event card: next turn ({})").format(player.name)
            else:
                next_text = t("Next event card: in {} turns ({})").format(turns, player.name)

        icon = self.hud_images["spr_event"]
        iw, ih = icon.image.get_size()
        name_h = name_font.get_height()
        line_h = desc_font.get_height() + 4
        hint_font = game_font(14)
        top_pad, gap1, gap2, gap3, bottom_pad = 24, 16, 16, 18, 20
        h = (top_pad + ih + gap1 + name_h + gap2 + line_h * len(lines) + gap3 + line_h + gap3
             + 4 + hint_font.get_height() + bottom_pad + ((gap3 + line_h * len(extra)) if extra else 0))
        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        pg.draw.rect(screen, self.EVENT_COLOR, pg.Rect(x, y, w, h))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, w, h), 3)

        cy = y + top_pad
        icon.draw(screen, Position(int(x + w * 0.5 - iw * 0.5), int(cy)))
        cy += ih + gap1
        name_surf = name_font.render(name, True, (0, 0, 0))
        screen.blit(name_surf, (x + w * 0.5 - name_surf.get_width() * 0.5, cy))
        cy += name_h + gap2
        for line in lines:
            line_surf = desc_font.render(line, True, (0, 0, 0))
            screen.blit(line_surf, (x + w * 0.5 - line_surf.get_width() * 0.5, cy))
            cy += line_h
        if extra:
            cy += gap3
            for line in extra:
                line_surf = desc_font.render(line, True, (0, 0, 0))
                screen.blit(line_surf, (x + w * 0.5 - line_surf.get_width() * 0.5, cy))
                cy += line_h

        cy += gap3
        pg.draw.line(screen, (0, 0, 0), (x + 40, cy - gap3 * 0.5), (x + w - 40, cy - gap3 * 0.5), 1)
        next_surf = desc_font.render(next_text, True, (0, 0, 0))
        screen.blit(next_surf, (x + w * 0.5 - next_surf.get_width() * 0.5, cy))

        # A click anywhere closes it (the event button itself already had
        # its chance to, earlier in draw_gui), and goes no further.
        hint = hint_font.render(t("click anywhere to continue"), True, (90, 50, 50))
        screen.blit(hint, (x + w * 0.5 - hint.get_width() * 0.5, y + h - bottom_pad - hint.get_height()))
        if self.io.left_pressed:
            self.event_info_open = False
            self.io.left_pressed = 0

    def _draw_pairing(self):
        """The Controllers panel: a row per human player. A controller
        clicking (A) a row becomes that player's; the mouse clicking it
        takes the controller away again. Opens by itself when a game starts
        with a controller nobody has yet (runner.py), and from the settings
        menu. Online it's each device's own (own_menus; on a joined device
        viewer.py): its controllers, its players, on its screen alone."""
        view = self.view
        screen = view.screen
        io = self.io
        pads = self.controls
        mouse = (io.mouse_position.x, io.mouse_position.y)

        self._dim()

        humans = [p for p in self.local_players() if not p.is_bot]
        row_h, gap = 48, 10
        w, h = 480, 85 + len(humans) * (row_h + gap) + 70
        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        pg.draw.rect(screen, self.SETTINGS_COLOR, pg.Rect(x, y, w, h))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, w, h), 3)
        screen.blit(self.font.render(t("Controllers"), True, (0, 0, 0)), (x + 15, y + 10))
        screen.blit(self.font.render(t("Point at your name and press A"), True, (70, 70, 70)), (x + 15, y + 42))

        # Every controller clicks here, each for itself (not only the acting
        # player's); the mouse through Io, as everywhere.
        clicks = [(pad, pad.pos) for pad in pads.pads if pad.tapped(controls.A)]
        if io.left_pressed and io.source is None:
            clicks.append((None, mouse))
        settling = pg.time.get_ticks() - self._pairing_since < 300
        if settling:
            clicks = []  # the press that opened the panel doesn't pick a row too
        for i, player in enumerate(humans):
            rect = pg.Rect(x + 20, y + 80 + i * (row_h + gap), w - 40, row_h)
            for who, pos in clicks:
                if not rect.collidepoint(pos):
                    continue
                if who is not None:
                    pads.bind(who, player.name)
                elif pads.pad_of(player.name) is not None:
                    pads.bind(pads.pad_of(player.name), None)
            pad = pads.pad_of(player.name)
            fill = light_tint(player.color)
            if rect.collidepoint(mouse) or any(rect.collidepoint(p.pos) for p in pads.pads):
                fill = tuple(min(255, c + 20) for c in fill)
            pg.draw.rect(screen, fill, rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 2)
            name = self.font.render(player.name, True, (0, 0, 0))
            screen.blit(name, (rect.x + 12, rect.centery - name.get_height() // 2))
            label = t("Controller {}").format(pad.number) if pad is not None else t("No controller")
            text = self.font.render(label, True, (0, 0, 0) if pad is not None else (110, 110, 110))
            screen.blit(text, (rect.right - 12 - text.get_width(), rect.centery - text.get_height() // 2))

        done_rect = pg.Rect(int(x + w * 0.5 - 90), int(y + h - 58), 180, 42)
        done = self._menu_button(done_rect, t("Done"), (150, 245, 150), mouse)
        if (done and not settling) or any(who is not None and done_rect.collidepoint(pos) for who, pos in clicks):
            self.pairing_open = False
        if io.left_pressed:
            io.left_pressed = 0  # nothing behind the panel reacts

    def production(self, player):
        """What `player`'s countries would yield right now: the resources
        as they'd arrive next income (food net of the troops to feed), plus
        "units": the troops on the board that food has to feed."""
        from phases import income_multiplier
        totals = dict.fromkeys(("food", "wood", "steel", "oil", "nuclear", "troops", "helmets"), 0)
        units = 0
        for country in self.countries.values():
            if country.owner != player:
                continue
            units += country.units
            if country.radioactive == 0:
                # A radioactive country yields nothing while it heals, helmets
                # included (ReinforcementPhase._produce).
                totals["helmets"] += country.troops
                mult = income_multiplier(self, country, player)
                amounts = {r: getattr(country, r) * mult for r in ("food", "wood", "steel", "oil", "nuclear")}
                target = player
                current_event = self.turn_manager.current_event
                if current_event is not None:
                    target, amounts = current_event.modify_income(self, country, player, amounts)
                if target is player:
                    for resource, amount in amounts.items():
                        totals[resource] += amount
                totals["troops"] += country.troops
        totals["food"] -= units
        totals["units"] = units
        return totals

    def update_turn(self):
        self.hint_rows = 0  # stacked hint boxes drawn so far this frame
        if self.online is None and (self.settings_open or self.event_info_open or self.pairing_open):
            return  # frozen: drawing already happened in draw_gui
        if not self.turn_manager.dialog_active and not self.bot_turn:
            player = self.players[self.turn]
            if self.card_menu.player is not player:
                self.card_menu.player = player
                self.card_menu.trade_mode = False
                self.card_menu.organize_cards()
            self.card_menu.sync_forced(self.turn_manager.must_trade(player))
            self.card_menu.handle_input(self.io)
        self.turn_manager.update()
        shopper = self.players[self.turn]
        if shopper.attack == 3:
            # The shop's own browse panel is drawn over all three icons;
            # put them back in front so they all stay visible and clickable.
            with self.private_layer(shopper.subattack < 8):
                self._hud_buttons(shop_open=True)

    def _hud_buttons(self, shop_open=False):
        self._settings_button().draw(self.view, self.io)
        self._shop_button(outline_width=4 if shop_open else 2).draw(self.view, self.io)
        self._card_button().draw(self.view, self.io)
        self._event_button().draw(self.view, self.io)

    def control_card_menu(self):
        if self.modal_open or self.bot_turn:
            self.card_menu.show = False
            self.card_menu.trade_mode = False
        else:
            with self.private_layer():
                self.card_menu.draw(self.io, self.font)
        self.own_menus()

    # --- online: each device's own menus -------------------------------------------------

    @contextmanager
    def private_layer(self, active=True):
        """Online, what's drawn in here is the current player's alone (the
        game's shop and cards): it goes on their device's own layer."""
        session = self.online
        number = session.current_device() if active and session is not None and session.state == "game" else None
        if number is None or number not in session.devices:
            yield
            return
        screen, self.view.screen = self.view.screen, session.layer(session.devices[number])
        try:
            yield
        finally:
            self.view.screen = screen

    @contextmanager
    def device_context(self, device):
        """Run this computer's own menus (online): its pointer (device.io),
        its layer, and its sounds its own."""
        session, view = self.online, self.view
        old = self.io, view.screen, self._device
        self.io, view.screen, self._device = device.io, session.layer(device), device
        try:
            with sounds.private(None):
                yield
        finally:
            self.io, view.screen, self._device = old

    OWN_MENUS = ("settings", "shop", "cards", "event")

    def own_menus(self):
        """Online: every device opens the settings, the shop, the cards and
        the event card for itself, at any time, on its own screen only
        (drawn on its layer: online.HostSession.show_menus). The shop and
        cards of the player whose turn it is are the game's (draw_gui) and
        only theirs; anyone else gets a look (`device.look`): the shop all
        red, the cards of their player whose turn comes soonest. While a
        device has one open its pointers don't click in the game
        (controls.Controls.frame)."""
        session = self.online
        if session is None or session.state != "game":
            return
        # (A joined device runs its own: viewer.py.)
        device = session.devices[0]
        source = session.device_pointer(device)
        device.io.update(self.view, self.countries.values(), source,
                         source.fresh if source is not None else
                         (self.controls.mouse_fresh if self.controls is not None else None))
        with self.device_context(device):
            self._own_menu(device, session.started_settings(device))

    def _own_menu(self, device, start_pressed):
        """A device's own menus: this computer's, or on a joined device its
        own (viewer.py, with `mirror` standing in for the online session)."""
        io = self.io
        mouse = (io.mouse_position.x, io.mouse_position.y)
        session = self.online or self.mirror
        open_now = self._own_open(device)
        clicked = self.own_button_at(mouse) if io.left_pressed and not self.dialog_up else None
        if start_pressed and not self.dialog_up:
            clicked = "settings"
        if clicked is not None:
            game_own = clicked in ("shop", "cards") and session.current_device() == device.id
            if not game_own or open_now is not None:
                io.left_pressed = 0
                self._close_own(device)
                if clicked != open_now and not game_own:
                    self._open_own(device, clicked)
                    sounds.play("click")
        if self.settings_open:
            self._draw_settings_menu()
        elif self.pairing_open:
            self._draw_pairing()
        elif self.event_info_open:
            self._draw_event_info()
        elif device.look == "shop":
            if self.turn_manager.phases[3].draw_look():
                device.look = None
            else:
                self._hud_buttons(shop_open=True)
        elif device.look == "cards":
            self._draw_card_look(device)

    def own_button_at(self, position):
        """Which of the HUD buttons that open a device's own menus (settings,
        shop, cards, event card) is at `position` (logical), if any."""
        buttons = (self._settings_button(), self._shop_button(), self._card_button(), self._event_button())
        return next((kind for kind, b in zip(self.OWN_MENUS, buttons)
                     if pg.Rect(b.pos.x, b.pos.y, b.width, b.height).collidepoint(position)), None)

    def _own_open(self, device):
        """Which of its own menus a device has open (in its device_context)."""
        if self.settings_open:
            return "settings"
        if self.pairing_open:
            return "pairing"
        if self.event_info_open:
            return "event"
        return device.look

    def _close_own(self, device):
        if self.settings_open:
            self.toggle_settings()
        self.event_info_open = self.pairing_open = False
        device.look = None

    def _open_own(self, device, kind):
        if kind == "settings":
            self.toggle_settings()
        elif kind == "event":
            self.event_info_open = True
        elif kind == "shop":
            device.look = "shop"
        else:
            player = (self.online or self.mirror).soonest_player(device.id)
            if player is None or not player.cards:
                sounds.play("error")  # nothing to show
                return
            device.cards = CardMenu(self.view, player)
            device.cards.engine = self
            device.look = "cards"

    def _draw_card_look(self, device):
        """A look at the cards of a device's player whose turn comes soonest:
        only to see; a click outside them closes it."""
        menu = device.cards
        io = self.io
        if not menu.player.cards:
            device.look = None
            return
        menu.show, menu.trade_mode = True, False
        menu.organize_cards()  # (also takes the trade selection off: there's no trading here)
        pos = (io.mouse_position.x, io.mouse_position.y)
        if io.left_pressed and not menu._panel_rect().collidepoint(pos):
            device.look = None
            io.left_pressed = 0
            return
        menu.draw(io, self.font)
        io.button(("r",) + tuple(menu._panel_rect()))
        io.left_pressed = 0

    def io_handle(self):
        source = None if self.controls is None else self.controls.frame(self)
        chat = self.online.chat if self.online is not None and self.online.state == "game" else None
        if chat is not None and source is None:
            # This computer's chat lies over everything (it's drawn last, see
            # present): the buttons and map under it are out of the mouse's
            # reach. A joined device's pointer has a chat of its own.
            self.io.buttons += chat.shapes()
        if self.controls is None:
            self.io.update(self.view, self.countries.values())
        else:
            self.io.update(self.view, self.countries.values(), source, self.controls.fresh(source))
        if chat is not None and source is None and chat.covers((self.io.mouse_position.x, self.io.mouse_position.y)):
            # (runner.play gave the click to the chat already)
            self.io.left_pressed = 0
            self.io.right_clicked = False
        shopper = self.players[self.turn]
        if shopper.attack == 3 and shopper.subattack < 8:
            # Shop menu open: the map behind it is inert (no hover panels,
            # no country clicks); placing a bought item (subattack > 8)
            # still needs the map.
            self.io.hover_country = None
        if not self._remote_pointer():  # (a joined device pans and zooms its own map)
            self.view.offset = self.io.drag_map(self.view.offset)
        if self.controls is not None:
            # A controller's right stick moves the view the way it's tilted.
            for pad in self.controls.clickers:
                if pad.pan != (0.0, 0.0):
                    self.view.offset = self.view.offset + Position(-pad.pan[0] / self.view.zoom,
                                                                   -pad.pan[1] / self.view.zoom)
        self.view.wrap()

    def bystander_clicks(self):
        """A player whose turn it isn't, pressing A with their controller's
        cursor on a country, hears that country's name; online also with
        their mouse (a joined device's, or the host's while a joined
        device's player decides). Not for a click the game takes (a
        defender's dice, an event's pick: those controllers click, see
        controls.py), nor through the shop menu, the card menu, a dialog, the
        top-left buttons or (online) the chat."""
        pads = self.controls
        if pads is None or self.modal_open or self.card_menu.show:
            return
        current = self.players[self.turn]
        if current.attack == 3 and current.subattack < 8:
            return  # shop menu open

        def say(position, view=None, chat=None):
            point = (int(position[0]), int(position[1]))
            if self.own_button_at(point) or (self.online is not None and (
                    online_chat.BUTTON.collidepoint(point) or (chat is not None and chat.covers(point)))):
                return  # a click on the top-left buttons or the chat, not on the country under them
            name = self.io.country_at(view or self.view, self.countries.values(), Position(*point))
            if name is not None:
                sounds.play_country(name)

        bot_acting = self.turn_manager.acting_player().is_bot  # then every paired controller clicks
        for pad in pads.pads:
            if not pad.tapped(controls.A) or (pad in pads.clickers and not bot_acting)                     or (self.online is not None and self.online.own_menu_open(0)):
                continue
            player = pads.player_of(pad, self.players)
            if player is None or player is current:
                continue
            say(pad.pos)
        if self.online is None:
            return
        # Online: the pointers of the devices that joined, the same way.
        for pointer in self.online.pointers():
            if not pointer.tapped(controls.A) or (pointer in pads.clickers and not bot_acting)                     or self.online.menu_blocks(pointer):  # (a click in its own menu)
                continue
            names = self.online.names_of(pointer)
            if not names or current.name in names:
                continue
            say(pointer.pos, pointer.view)
        # And the host's own mouse, which doesn't click while a joined
        # device's player decides: for the players on this computer.
        if not pads.mouse_ok and pads.mouse_fresh[0] and not self.online.own_menu_open(0):
            names = [seat.name for seat in self.online.seats if seat.kind == "host"]
            if names and current.name not in names:
                x, y = pg.mouse.get_pos()
                say((int((x - self.view.ox) / self.view.scale), int((y - self.view.oy) / self.view.scale)),
                    chat=self.online.chat)

    def get_players(self, mode="prompt"):
        if mode == "default":
            self.default_game = True
            return [Player(name, color=color) for name, color in DEFAULT_PLAYERS]
        if mode == "count":
            self.default_game = False
            names = self.player_names
            if not names or len(names) != self.player_count:
                names = ["Player {}".format(i + 1) for i in range(self.player_count)]
            return [
                Player(name, color=COUNT_MODE_COLORS[i % len(COUNT_MODE_COLORS)])
                for i, name in enumerate(names)
            ]
        default = input("Play default? ")
        if default in {"yes", "y", "Y", "YES"}:
            self.default_game = True
            return [Player(name, color=color) for name, color in DEFAULT_PLAYERS]
        else:
            self.default_game = False
            while True:
                try:
                    player_num = int(input("How many players? "))
                    break
                except ValueError:
                    pass
            return [Player(input("Player {}'s name? ".format(i + 1))) for i in range(player_num)]
