from contextlib import contextmanager

import pygame as pg
import numpy as np
from board import get_connections, get_countries
from models import Position, Image, Player, Io, View, Gui, Shop, Button, CardMenu, LANDMARKS
from phases import TurnManager
from random import choice, sample
from player_colors import COUNT_MODE_COLORS
from save_load import AUTOSAVE_PATH, SAVE_SLOT_COUNT, slot_path, read_save_name, save_game

# Curated starting-country pools, keyed by player count: one is dealt to
# each player at random, regardless of whether the game is "de Neven" or a
# plain N-player game. A count with no pool here samples the whole map.
STARTING_COUNTRY_POOLS = {
    3: ["Sri Lanka", "Pearl Harbor", "Viking"],
    4: ["Zuid-Afrika", "Siberië", "New York", "Ottomaanse Rijk"],
    5: ["Noord-Korea", "Madagaskar", "Ottomaanse Rijk", "Pearl Harbor", "New York"],
    6: ["Gold Coast", "Arabië", "Venezuela", "Canada", "Nigeria", "Siberië"],
}


class Engine:

    def __init__(self, width=960, height=640, mode="prompt", player_count=None, player_names=None,
                 player_bots=None):
        # player_count/player_names are only used by mode="count" (a plain
        # N-player game, named on the screen after the new-game menu's
        # 3/4/5/6 buttons -- as opposed to mode="default", the named
        # "de Neven" trio). player_names falls back to generic names if not
        # given (e.g. called directly rather than through that screen).
        self.player_count = player_count
        self.player_names = player_names
        pg.init()
        pg.font.init()
        self.font = pg.font.SysFont('Times New Roman', 20)
        self.logical_size = (width, height)
        self.fullscreen = True
        window = self._set_display()
        # All UI code draws on this transparent surface at the logical
        # width x height; present() scales it over the map, which is drawn
        # directly in real screen pixels so it stays sharp.
        self.ui = pg.Surface((width, height), pg.SRCALPHA).convert_alpha()
        self.view = View(
            screen=self.ui,
            zoom=1.21,
            offset=Position(-401, -240),
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
            "spr_shop": Image("shop", scale=(52, 52)),
            "spr_cards": Image("cards", scale=(52, 52)),
            "spr_settings": Image("settings", scale=(52, 52)),
            "spr_event": Image("event", scale=(56, 56)),
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
        self.settings = {"assets": False, "sea": True, "land": True, "sea_route": True, "tank": True,
                         "landmarks": True, "fast_bots": False}
        self.pending_quit = False
        # Save As panel: open or not, which slot is being named (None while
        # still picking one), and the name typed so far.
        self.save_as_open = False
        self.save_as_slot = None
        self.save_as_name = ""
        # Where the autosave at the start of each turn goes.
        self.save_path = AUTOSAVE_PATH

        self.default_player = Player("mouse", color=(140, 140, 140))
        self.players = self.get_players(mode)
        # player_bots: which of the players (in order) the computer plays --
        # True, or the bot's difficulty level. Each bot gets a personality
        # at random.
        from bot import PERSONALITIES
        for player, is_bot in zip(self.players, player_bots or []):
            player.is_bot = bool(is_bot)
            if isinstance(is_bot, str):
                player.bot_level = is_bot
            if is_bot:
                player.bot_personality = choice(sorted(PERSONALITIES))
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
            # No boat here: each player deploys their one free boat
            # themselves during a recruitment phase (Player.start_ship).
            self.countries[country].airport = True

    # --- display / map rendering ----------------------------------------

    def _set_display(self):
        width, height = self.logical_size
        if self.fullscreen:
            return pg.display.set_mode((0, 0), pg.FULLSCREEN)
        desktop_w, desktop_h = pg.display.get_desktop_sizes()[0]
        factor = min(1.25, desktop_w * 0.9 / width, desktop_h * 0.85 / height)
        return pg.display.set_mode((int(width * factor), int(height * factor)))

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
        self.map_font = pg.font.SysFont('Times New Roman', max(8, int(20 * scale)))

        def sized(name, w, h):
            return Image(name, scale=(max(1, int(w * scale)), max(1, int(h * scale))))

        self.map_images = {
            "spr_ship": sized("ship", 30, 30),
            "spr_plane": sized("plane", 30, 30),
            "spr_tank": sized("tank", 30, 30),
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
            tuple((tuple(int(x) for x in c.owner.color), c.shade, c.radioactive > 0) for c in self.countries.values()),
            tuple((c.kind, c.rails) for c in self.connections),
            self.settings["sea"], self.settings["land"],
            self.settings["landmarks"], tuple(self._landmark_shown(name) for name in LANDMARKS),
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
    CONNECTION_OPACITY = 153  # 60%

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
        for country in self.countries.values():
            country.draw(view, border_color=self.colors["outlines"], draw_border=False)
        with self._blended(surface, self.BORDER_OPACITY):
            for country in self.countries.values():
                country.draw_border(view, self.BORDER_COLOR)
        with self._blended(surface, self.CONNECTION_OPACITY):
            for connection in self.connections:
                if not self.settings[connection.kind]:
                    continue
                connection.draw(self.countries, self.colors, view, outline_color=self.colors["outlines"])
        if self.settings["landmarks"]:
            self._draw_map_landmarks()
        surface.set_clip(None)
        if ss != 1:
            surface = pg.transform.smoothscale(surface, (sw, sh))
        return surface

    def draw_world(self, background_color=(200, 200, 255)):
        view = self.view
        self.ui.fill((0, 0, 0, 0))
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
        for country in self.countries.values():
            # The ship/plane and tank lines on the marker can each be
            # switched off in the settings menu.
            country.draw_troops(
                self.map_font, view,
                show_ships_planes=self.settings["sea_route"], show_tanks=self.settings["tank"],
            )
            country.draw_assets(
                view=view,
                img_ship=self.map_images["spr_ship"],
                img_plane=self.map_images["spr_plane"],
                img_tank=self.map_images["spr_tank"],
                show_military=self.settings["assets"],
            )
        view.window.set_clip(None)

    def present(self):
        """Scale the UI layer over the map (call right before flip)."""
        view = self.view
        width, height = self.logical_size
        size = (int(round(width * view.scale)), int(round(height * view.scale)))
        ui = self.ui if size == (width, height) else pg.transform.smoothscale(self.ui, size)
        view.window.blit(ui, (int(view.ox), int(view.oy)))

    def draw_gui(self):
        def handle_card_menu():
            if self.turn_manager.must_trade():
                return  # can't close the menu until enough cards are traded
            if not self.card_menu.show and self.turn_manager.attack_in_progress():
                return  # dice are cast: the attack has to finish first
            self.card_menu.player = self.players[self.turn]
            self.card_menu.trade_mode = False
            self.card_menu.show = not self.card_menu.show
            self.card_menu.organize_cards()
            self.card_menu.use_cards_automatic()

        self.gui.draw_overlay(self.view)
        if self.io.hover_country is not None:
            hovered = self.countries[self.io.hover_country]
            owner_stats = None
            owner = hovered.owner
            # What the owner holds, only when it's another real player.
            if owner is not self.default_player and owner is not self.players[self.turn]:
                amounts = {r: getattr(owner, r) for r in ("food", "wood", "steel", "oil", "nuclear")}
                amounts["helmets"] = self.production(owner)["helmets"]
                amounts["cards"] = len(owner.cards)
                owner_stats = (owner, amounts, self.mini_images)
            self.gui.draw_country_stats(
                view=self.view,
                country=hovered,
                font=self.font,
                images=self.hud_images,
                owner_stats=owner_stats,
            )
        player = self.players[self.turn]
        self.gui.draw_player_stats(self.view, player, self.font, self.hud_images, self.production(player))
        self.gui.draw_attack_phase(
            self.view, self.players[self.turn], images=self.hud_images, outline_color=self.colors["outlines"],
        )

        # Settings sits top-left on its own.
        settings_button = self._settings_button()
        settings_button.draw(self.view, self.io)
        if not self.turn_manager.dialog_active:
            # Gated on the dialog only (not modal_open), so this stays
            # clickable even while its own menu is what's blocking
            # everything else -- otherwise there'd be no way to close it.
            settings_button.release_button(self.toggle_settings, self.io)
        # On a bot's turn the shop and cards are the bot's business.
        blocked = self.modal_open or self.bot_turn

        # Shop and cards sit top-left too, to the right of settings.
        card_menu_button = self._card_button()
        card_menu_button.draw(self.view, self.io)
        if not blocked:
            card_menu_button.release_button(handle_card_menu, self.io)
        shop_menu_button = self._shop_button()
        shop_menu_button.draw(self.view, self.io)
        if not blocked:
            shop_menu_button.release_button(self.turn_manager.toggle_shop, self.io)

        if self.settings_open:
            self._draw_settings_menu()

    _top_button_x = 100  # shop, then cards to its right, both right of settings

    @property
    def bot_turn(self):
        """Whether the computer is playing the current turn."""
        return self.players[self.turn].is_bot

    @property
    def modal_open(self):
        """Whether some full-screen-ish overlay (an elimination/win dialog
        or the settings menu) should freeze everything else."""
        return self.turn_manager.dialog_active or self.settings_open

    def toggle_settings(self):
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
        return hovered and self.io.left_pressed

    def _draw_save_as(self, x, y, w, h, mouse):
        """Save As: pick one of the save slots, type a name for it, Save."""
        screen = self.view.screen
        screen.blit(self.font.render("Save As", True, (0, 0, 0)), (x + 15, y + 10))
        for i in range(SAVE_SLOT_COUNT):
            rect = pg.Rect(x + 20, y + 45 + i * 60, w - 40, 50)
            selected = self.save_as_slot == i
            pg.draw.rect(screen, (255, 255, 255) if selected else (235, 235, 235), rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 3 if selected else 2)
            screen.blit(self.font.render("Slot {}".format(i + 1), True, (90, 90, 90)), (rect.x + 8, rect.y + 3))
            if selected:
                text = self.font.render(self.save_as_name, True, (0, 0, 0))
                screen.blit(text, (rect.x + 8, rect.y + 25))
                if (pg.time.get_ticks() // 500) % 2 == 0:
                    cx = rect.x + 10 + text.get_width()
                    pg.draw.line(screen, (0, 0, 0), (cx, rect.y + 27), (cx, rect.bottom - 5), 2)
            else:
                name = self.save_as_names[i]
                text = self.font.render(name if name else "(empty)", True, (0, 0, 0) if name else (130, 130, 130))
                screen.blit(text, (rect.x + 8, rect.y + 25))
                if self.io.left_pressed and rect.collidepoint(mouse):
                    self.save_as_slot = i
                    self.save_as_name = (name or "")[:self.SAVE_NAME_MAX]

        hint_y = y + 45 + SAVE_SLOT_COUNT * 60
        if self.save_as_slot is None:
            hint = "Click a slot to save there"
        elif self.save_as_names[self.save_as_slot]:
            hint = "Type a name -- overwrites this slot"
        else:
            hint = "Type a name, then Save or Enter"
        screen.blit(self.font.render(hint, True, (0, 0, 0)), (x + 20, hint_y))

        save_rect = pg.Rect(x + 20, y + h - 110, w - 40, 40)
        if self._menu_button(save_rect, "Save", (150, 245, 150), mouse,
                             enabled=self.save_as_slot is not None and bool(self.save_as_name.strip())):
            self._commit_save_as()
        back_rect = pg.Rect(x + 20, y + h - 60, w - 40, 40)
        if self._menu_button(back_rect, "Back", (220, 220, 220), mouse):
            self._close_save_as()

    def _draw_settings_menu(self):
        view = self.view
        screen = view.screen
        io = self.io
        mouse = (io.mouse_position.x, io.mouse_position.y)

        if self.dragging_landmark is not None:
            self._drag_landmark()
            return

        dim = pg.Surface((view.WIDTH, view.HEIGHT), pg.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        screen.blit(dim, (0, 0))

        w, h = 340, 562
        x, y = view.WIDTH * 0.5 - w * 0.5, view.HEIGHT * 0.5 - h * 0.5
        pg.draw.rect(screen, self.SETTINGS_COLOR, pg.Rect(x, y, w, h))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, w, h), 3)

        if self.save_as_open:
            self._draw_save_as(x, y, w, h, mouse)
            return

        screen.blit(self.font.render("Settings", True, (0, 0, 0)), (x + 15, y + 10))

        quit_rect = pg.Rect(x + 20, y + 45, w - 40, 40)
        if self._menu_button(quit_rect, "Exit Game", (245, 150, 150), mouse):
            self.pending_quit = True

        save_as_rect = pg.Rect(x + 20, quit_rect.bottom + 10, w - 40, 40)
        if self._menu_button(save_as_rect, "Save As", (150, 200, 245), mouse):
            self.save_as_open = True
            self.save_as_slot = None
            self.save_as_names = [read_save_name(slot_path(i)) for i in range(SAVE_SLOT_COUNT)]

        toggles = [
            ("assets", "Show assets"), ("sea", "Show sea connections"), ("land", "Show land connections"),
            ("sea_route", "Ship / plane lines"), ("tank", "Tank lines"),
            ("landmarks", "Show torii/pagoda"), ("fast_bots", "Fast bots"),
        ]
        for i, (key, text) in enumerate(toggles):
            row_y = save_as_rect.bottom + 20 + i * 42
            box = pg.Rect(x + 20, row_y, 26, 26)
            pg.draw.rect(screen, (255, 255, 255), box)
            pg.draw.rect(screen, (0, 0, 0), box, 2)
            if self.settings[key]:
                pg.draw.line(screen, (0, 150, 0), (box.x + 4, box.y + 13), (box.x + 11, box.y + 21), 3)
                pg.draw.line(screen, (0, 150, 0), (box.x + 11, box.y + 21), (box.x + 22, box.y + 5), 3)
            screen.blit(self.font.render(text, True, (0, 0, 0)), (box.right + 10, box.y + 3))
            if io.left_pressed and box.collidepoint(mouse):
                self.settings[key] = not self.settings[key]

        # China's pagoda and Japan's torii: owed by whoever holds that
        # country without one, who drags it from here onto the map. Once
        # placed it's gone from here, until the country loses it again
        # (back to the mouse, or conquered by someone else).
        owed = self.turn_manager.landmarks_owed
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
        if not io.mouse_state[0]:
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

    def _settings_button(self):
        return Button(
            pos=Position(20, 20),
            width=60,
            height=60,
            color=self.SETTINGS_COLOR,
            outline_width=4 if self.settings_open else 2,
            image=self.hud_images['spr_settings'],
        )

    def _shop_button(self, outline_width=2):
        return Button(
            pos=Position(self._top_button_x, 20),
            width=60,
            height=60,
            color=(170, 230, 170),
            outline_width=outline_width,
            image=self.hud_images['spr_shop'],
        )

    def _card_button(self, outline_width=2):
        return Button(
            pos=Position(self._top_button_x + 80, 20),
            width=60,
            height=60,
            color=(100, 100, 255),
            outline_width=outline_width,
            image=self.hud_images['spr_cards'],
        )

    def production(self, player):
        """What `player`'s countries would yield right now: the resources
        as they'd arrive next income (food net of the troops to feed)."""
        from phases import income_multiplier
        totals = dict.fromkeys(("food", "wood", "steel", "oil", "nuclear", "troops", "helmets"), 0)
        units = 0
        for country in self.countries.values():
            if country.owner != player:
                continue
            units += country.units
            totals["helmets"] += country.troops
            if country.radioactive == 0:
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
        return totals

    def update_turn(self):
        if self.settings_open:
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
        if self.players[self.turn].attack == 3:
            # The shop's own browse panel is drawn over all three icons;
            # put them back in front so they all stay visible and clickable.
            self._settings_button().draw(self.view, self.io)
            self._shop_button(outline_width=4).draw(self.view, self.io)
            self._card_button().draw(self.view, self.io)

    def control_card_menu(self):
        if self.modal_open or self.bot_turn:
            self.card_menu.show = False
            self.card_menu.trade_mode = False
            return
        self.card_menu.draw(self.io, self.font)

    def io_handle(self):
        self.io.update(self.view, self.countries.values())
        self.view.offset = self.io.drag_map(self.view.offset)

    def get_players(self, mode="prompt"):
        if mode == "default":
            self.default_game = True
            return [
                Player("Hugo", color=(60, 110, 230)),
                Player("Joeri", color=(40, 160, 70)),
                Player("Tètè", color=(210, 40, 40)),
            ]
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
            return [
                Player("Hugo", color=(60, 110, 230)),
                Player("Joeri", color=(40, 160, 70)),
                Player("Tètè", color=(210, 40, 40)),
            ]
        else:
            self.default_game = False
            while True:
                try:
                    player_num = int(input("How many players? "))
                    break
                except ValueError:
                    pass
            return [Player(input("Player {}'s name? ".format(i + 1))) for i in range(player_num)]
