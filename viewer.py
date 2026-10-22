"""
A joined device's side of an online game (online.py is the host's). The
game is played on the host's computer only; this device keeps a copy of
it to draw (`Viewer.game`, an Engine that never plays: the host's state
is put onto it as it comes in, save_load.apply_data) and sends its mouse
and game controllers back, which click on the host when one of its players
decides (online.HostSession.remote_clickers).

What it draws itself, from that copy: the map, which it pans and zooms on
its own (its view goes along with its input, so its clicks hit what it
sees), the info panel of the country under its pointer, the action log
(open or not, scrolled or not), the HUD buttons, and its own menus: the
settings (what its map shows is its own; the rest is the host's), the
event card, a look at the shop and at the cards of its player whose turn
comes soonest, and the Controllers panel, which pairs this device's
controllers with this device's players (nobody else sees it; the host
hears which controller is whose: pads{bind}). Its pagoda/torii is dragged
onto its own map and placed by the host (landmark{name, on}). Over its map
it lays the game's layer as the
host draws it (online.OverlayStream: the HUD, dice, popups, dialogs, the
event card coming up), and on its player's turn the game's shop and cards
(drawn by the host for this device alone). The chat (chat.py) is its own;
the cursors are everyone's, at the same map point (online.cursor_spot).
It shows the game in the host's language, and hears the host's sounds.

Esc (or a controller's Back button) opens a small menu of this device's
own: back to the game, fullscreen or windowed, leave the game.
"""

import base64
import binascii
import copy
import io

import pygame as pg

import chat
import controls
import lang
import online
import save_load
import sounds
from engine import Engine, open_window
from events import EVENTS
from fonts import game_font
from lang import t
from menu import _draw_button

WIDTH, HEIGHT = controls.WIDTH, controls.HEIGHT
MOTION_MS = 16    # input sent at most this often while only the pointer moves
HINT_MS = 6000    # how long "Esc: menu" shows at the start
SETTLE_FRAMES = 5  # frames drawn after anything happened (the smooth map comes a frame later)
IDLE_MS = 250     # nothing happening: look again this often
BACK = pg.CONTROLLER_BUTTON_BACK
MOUSE_BUTTONS = {1: controls.A, 2: online.MIDDLE, 3: controls.B}
SENT_BUTTONS = {controls.A, controls.B}  # a controller's buttons the host gets

# Why a game ended for this device, as the host or relay said it.
ENDINGS = {
    "ended": "The host ended the game",
    "closed": "The host closed the game",
    "gone": "The host has left the game",
    "kicked": "You were removed from the game",
    "lost": "The connection to the game was lost",
}


class Viewer:

    def __init__(self, conn, me, seats):
        self.conn = conn
        self.me = me        # this device's member number at the relay
        self.seats = seats  # the host's last word on them (online.Seat.to_json)
        self.fullscreen = True
        self.window = open_window((WIDTH, HEIGHT), self.fullscreen)
        self.game = None    # the copy of the host's game this device draws (once its state came)
        self.state = None   # the host's game state (online.HostSession.game_state)
        self.log = []       # the action log (the copy's, once there is one)
        # The copy's own events (an event keeps its state on itself).
        self.events = {event.name: copy.deepcopy(event) for event in EVENTS}
        self.overlay = pg.Surface((WIDTH, HEIGHT), pg.SRCALPHA)  # the game's layer, as the host draws it
        self.seq = 0
        self.private = None  # (image, logical rect): the game's shop/cards on this device's player's turn
        self.dim = False     # and whether that dims what's under it
        self.cursors = []
        self.pads = controls.get()
        self.device = online.Device(me)  # its own menus' state (look, cards)
        self.menu_open = False
        self.hint_until = pg.time.get_ticks() + HINT_MS
        self.font = game_font(26)
        self.hint_font = game_font(18)
        self._language = lang.language
        self._down, self._wheel = [], 0
        self._sent_down = []
        self._mouse_sent, self._mouse_sent_at = None, 0
        self._pads_sent = {}
        self._pad_down = {}
        self._pad_swallowed = {}  # a controller's buttons pressed for this device's own: not sent while held
        self._bind_sent = None
        self._swallowed = set()  # mouse buttons pressed on the chat or for this device's own: not sent as held
        self._scaled = {}        # cached scaled layers: name -> (key, surface)
        self._messages = 0       # messages taken in this frame
        self.frames_left = SETTLE_FRAMES
        self.chat = chat.Chat(lambda text: self.conn.send({"type": "chat", "text": text}), me)
        self._layout()

    def _layout(self):
        """The game's 960x640 area in the window: as big as fits, centred."""
        if self.game is not None:
            self.game._layout()
            view = self.game.view
            self.window, self.scale = view.window, view.scale
            self.area = pg.Rect(int(view.ox), int(view.oy), round(WIDTH * view.scale), round(HEIGHT * view.scale))
        else:
            sw, sh = self.window.get_size()
            self.scale = min(sw / WIDTH, sh / HEIGHT)
            w, h = round(WIDTH * self.scale), round(HEIGHT * self.scale)
            self.area = pg.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        self._scaled = {}

    def _logical(self, pos):
        x = (pos[0] - self.area.x) / self.scale
        y = (pos[1] - self.area.y) / self.scale
        return int(min(max(x, 0), WIDTH - 1)), int(min(max(y, 0), HEIGHT - 1))

    def run(self):
        """Until the game ends for this device: returns why (text to show),
        or None when it left by itself. Closing the window quits."""
        self.conn.wake = online.wake
        self.conn.send({"type": "ready"})
        self.pads._show_cursor(True)
        sounds.start_background()
        clock = pg.time.Clock()
        try:
            while True:
                if self.frames_left == 0:
                    event = pg.event.wait(IDLE_MS)  # (a message from the host wakes it: online.wake)
                    events = ([event] if event.type != pg.NOEVENT else []) + pg.event.get()
                else:
                    events = pg.event.get()
                if any(event.type == pg.QUIT for event in events):
                    self._leave()
                    pg.quit()
                    raise SystemExit
                ending = self.frame(events)
                if ending == "leave":
                    self._leave()
                    return None
                if ending is not None:
                    return t(ENDINGS[ending])
                clock.tick(60)
        finally:
            lang.language = self._language  # (the host's, while in its game)

    def frame(self, events):
        """One frame: this device's input, what came from the host, the
        screen. Returns "leave" when Leave game was clicked, a key of ENDINGS
        when the game is over for this device, else None."""
        clicks = self._events(events)
        self.pads.handle_events(events)
        if any(pad.tapped(BACK) for pad in self.pads.pads):
            self.menu_open = not self.menu_open
        self._messages = 0
        ending = self._receive()
        if ending is not None:
            return ending
        if events or self._messages or self.pads.busy:
            self.frames_left = SETTLE_FRAMES
        if pg.time.get_ticks() < self.hint_until:
            self.frames_left = max(self.frames_left, 1)
        mouse = self._logical(pg.mouse.get_pos())
        drawing = self.frames_left > 0  # (every input is an event: it's always drawn)
        if self.menu_open:
            clicks += [pad.pos for pad in self.pads.pads if pad.tapped(controls.A)]
            if self._menu(mouse, clicks) == "leave":
                return "leave"
            self._down, self._wheel = [], 0
        elif self.game is not None and drawing:
            self._input(mouse)
        if drawing:
            self.frames_left -= 1
            self._draw(mouse)
        if not self.menu_open and self.game is not None:
            self._send_input(mouse)
        return None

    def _events(self, events):
        """This frame's mouse and keys: the chat's go to the chat, Esc
        toggles the menu, the rest is the game's. Returns the left clicks
        (logical), for the menu."""
        clicks = []
        for event in events:
            if not self.menu_open and self.chat.handle(event, self._logical):
                if event.type == pg.MOUSEBUTTONDOWN and event.button in MOUSE_BUTTONS:
                    self._swallowed.add(MOUSE_BUTTONS[event.button])
                continue
            if event.type == pg.MOUSEBUTTONUP and event.button in MOUSE_BUTTONS:
                self._swallowed.discard(MOUSE_BUTTONS[event.button])
            if self.game is not None and self.game.typing_save_name:
                continue  # (a joined device can't save; just in case)
            if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
                self.menu_open = not self.menu_open
            elif event.type == pg.MOUSEBUTTONDOWN:
                if event.button == 1:
                    clicks.append(self._logical(event.pos))
                if event.button in MOUSE_BUTTONS:
                    self._down.append(MOUSE_BUTTONS[event.button])
                elif event.button in (4, 5):
                    self._wheel += 1 if event.button == 4 else -1
            elif event.type in (pg.VIDEORESIZE, pg.WINDOWSIZECHANGED):
                self._layout()
        return clicks

    # --- standing in for the online session (Engine.mirror) ----------------------

    def _online(self, key, default=None):
        """What the host says is on screen (HostSession.game_state's "online")."""
        return ((self.state or {}).get("online") or {}).get(key, default)

    @property
    def dialog(self):
        """Whether a dialog is up on the host (it takes every click)."""
        return bool(self._online("dialog", False))

    @property
    def owed(self):
        """The pagoda/torii the current player still has to place."""
        owed = self._online("owed", [])
        return set(owed) if isinstance(owed, list) else set()

    def _device_of(self, name):
        """The device the player called `name` plays on (as HostSession.device_of)."""
        seat = next((s for s in self.seats if isinstance(s, dict) and s.get("name") == name), None)
        return seat.get("member") if seat is not None and seat.get("kind") == "remote" else 0

    def current_device(self):
        """The device of the player whose turn it is; None on a bot's turn."""
        player = self.game.players[self.game.turn]
        return None if player.is_bot else self._device_of(player.name)

    def soonest_player(self, number):
        """Of the (human) players on device `number`, the one whose turn
        comes soonest (the one deciding now first); None for none."""
        game, acting = self.game, self._online("acting")
        count = len(game.players)
        ranked = [(0 if player.name == acting else 1 + (i - game.turn) % count, i)
                  for i, player in enumerate(game.players)
                  if not player.is_bot and not player.eliminated and self._device_of(player.name) == number]
        return game.players[min(ranked)[1]] if ranked else None

    def local_players(self, players):
        """This device's players (its Controllers panel pairs them)."""
        return [player for player in players if self._device_of(player.name) == self.me]

    def place_landmark(self, name, on):
        """This device's player dropped the pagoda/torii `name` on `on`."""
        self.conn.send({"type": "landmark", "name": name, "on": on})

    # --- the network -------------------------------------------------------

    def _receive(self):
        """Take in what came from the host: the game's state, its log and
        layer, cursors, sounds. Returns a key of ENDINGS when the game is
        over for this device."""
        for message in self.conn.poll():
            self._messages += 1
            if isinstance(message, bytes):
                try:
                    self.seq = online.apply_update(self.overlay, message)
                except ValueError:
                    continue
                self._scaled.pop("overlay", None)
                self.conn.send({"type": "ack", "seq": self.seq})
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("type")
            if kind == "state":
                self._take_state(message)
            elif kind == "log":
                self._take_log(message)
            elif kind == "cursors" and isinstance(message.get("c"), list):
                self.cursors = [c for c in message["c"] if _valid_cursor(c)]
            elif kind == "sound":
                name = str(message.get("name", ""))
                if message.get("kind") == "country":
                    sounds.play_country(name)
                elif name.replace("_", "").isalnum():
                    sounds.play(name)
            elif kind == "chat":
                self.chat.add(message.get("lines"), old=bool(message.get("old")))
            elif kind == "menu":
                self.private, self.dim = _overlay(message), bool(message.get("dim"))
                self._scaled.pop("private", None)
            elif kind == "seats" and isinstance(message.get("seats"), list):
                self.seats = message["seats"]
            elif kind == "end":
                return "closed" if message.get("reason") == "closed" else "ended"
            elif kind == "closed":
                return "gone"
            elif kind == "kicked":
                return "kicked"
        return "lost" if self.conn.closed else None

    def _take_state(self, message):
        """The host's game state: all of it, or what changed since."""
        data, countries = message.get("set"), message.get("countries")
        if not isinstance(data, dict):
            return
        if message.get("full"):
            state = dict(data)
        elif self.state is None:
            return  # (the whole of it is on its way)
        else:
            state = dict(self.state, **data)
            state["countries"] = dict(state["countries"], **(countries if isinstance(countries, dict) else {}))
        try:
            self._apply(state)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            return  # not a state this version can draw
        self.state = state

    def _apply(self, state):
        """Put the host's state onto this device's copy of the game (made on
        the first)."""
        if self.game is None:
            names = [str(player["name"]) for player in state["players"]]
            game = Engine(mode="count", player_count=len(names), player_names=names, fullscreen=self.fullscreen)
            game.mirror = self
            game.controls = self.pads  # (its Controllers panel pairs them)
            game.action_log = self.log
            self.game = game
            self._layout()
            new = True
        else:
            new = False
        game = self.game
        save_load.apply_data(state, game, game.turn_manager, events=self.events, mirror=True)
        extra = state.get("online") or {}
        for player, step in zip(game.players, extra.get("subattack", [])):
            player.subattack = step
        shade = extra.get("shade") or {}
        for name, country in game.countries.items():
            country.shade = shade.get(name, 0)
        if extra.get("lang") in lang.LANGUAGES:
            lang.language = extra["lang"]
        game.settings["fast_bots"] = bool(extra.get("fast_bots"))
        if new and self.pads.needs_pairing(game.local_players()):
            game.open_pairing()  # who has which controller? (as on the host)

    def _take_log(self, message):
        """Action-log lines from the host: the last ones (reset), or new ones."""
        lines = message.get("lines")
        if not isinstance(lines, list):
            return
        try:
            lines = [save_load.read_log_line(line) for line in lines]
        except (TypeError, ValueError, KeyError, IndexError, AttributeError):
            return
        if message.get("reset"):
            self.log[:] = lines
            if self.game is not None:
                self.game.action_scroll = 0
            return
        self.log.extend(lines)
        del self.log[:-Engine.ACTION_LOG_MAX]
        game = self.game
        if game is not None and game.action_log_open and game.action_scroll:
            # Reading further back: keep the same lines in view.
            game.action_scroll = min(game.action_scroll + len(lines), game._action_scroll_max())

    def _send_input(self, mouse):
        """This device's mouse and controllers, for the host: where they
        are, the buttons held and pressed (not those for this device's own:
        its menus, its HUD buttons, its log), its view and whether it has a
        menu of its own open."""
        conn, view = self.conn, self.game.view
        now = pg.time.get_ticks()
        shown = [round(view.zoom, 4), round(view.offset.x, 2), round(view.offset.y, 2)]
        own = self._own_open()
        held = [b for b, on in zip((controls.A, online.MIDDLE, controls.B), pg.mouse.get_pressed())
                if on and b not in self._swallowed]
        state = (mouse, held, shown, own)
        sent = self._mouse_sent
        if self._sent_down or (state != sent and (
                sent is None or held != sent[1] or own != sent[3] or now - self._mouse_sent_at >= MOTION_MS)):
            conn.send({"type": "mouse", "x": mouse[0], "y": mouse[1], "held": held, "down": self._sent_down,
                       "view": shown, "menu": own})
            self._mouse_sent, self._mouse_sent_at = state, now
        self._sent_down = []
        numbers = set()
        for pad in self.pads.pads:
            numbers.add(pad.number)
            swallowed = self._pad_swallowed.get(pad.number, set())
            pad_held = sorted(b for b in pad.held if b in SENT_BUTTONS and b not in swallowed)
            down = self._pad_down.pop(pad.number, [])
            state = (pad.pos, pad_held, shown, own)
            if down or state != self._pads_sent.get(pad.number):
                conn.send({"type": "pad", "n": pad.number, "x": pad.x, "y": pad.y, "held": pad_held,
                           "down": down, "view": shown, "menu": own})
                self._pads_sent[pad.number] = state
        for number in [n for n in self._pads_sent if n not in numbers]:
            conn.send({"type": "pad", "n": number, "gone": True})  # unplugged
            del self._pads_sent[number]
        bind = {str(pad.number): self.pads.bindings[pad.instance_id]
                for pad in self.pads.pads if pad.instance_id in self.pads.bindings}
        if bind != self._bind_sent:
            conn.send({"type": "pads", "bind": bind})
            self._bind_sent = bind

    def _leave(self):
        self.conn.send({"type": "leave"})
        self.conn.close()

    # --- this device's own: input --------------------------------------------

    def _own_open(self):
        """Whether one of this device's own menus is open."""
        game = self.game
        return game is not None and (game.settings_open or game.event_info_open or game.pairing_open
                                     or self.device.look is not None)

    def _turn_order_hidden(self):
        """The turn order is left out under a menu of this device's own and
        while the game's shop (its player's) is on its screen."""
        return self._own_open() or self._my_shop()

    def _my_shop(self):
        """The game's shop is open on this device (its player's turn)."""
        player = self.game.players[self.game.turn]
        return player.attack == 3 and player.subattack < 8 and self.current_device() == self.me

    def _local_at(self, position):
        """Whether a click at `position` (logical) is for this device's own
        (its menus, its HUD buttons, its action log), not for the game."""
        game = self.game
        if game.dialog_up:
            return False  # (the host's dialog takes every click)
        if self._own_open():
            return True
        box = game._action_box_rect()
        if box is not None and box.collidepoint(position):
            return True
        if not (self._turn_order_hidden() or game._turn_order_hidden()) and                 game._turn_order_rect().collidepoint(position):
            return True
        kind = game.own_button_at(position)
        if kind in ("settings", "event"):
            return True
        return kind in ("shop", "cards") and self.current_device() != self.me  # (a look; on its turn the game's)

    def _input(self, mouse):
        """This device's pointer on its own copy of the game: which clicks
        are its own (`_local_at`, kept from the host), and its panning and
        zooming."""
        game, pads = self.game, self.pads
        view, io = game.view, game.io
        source = pads._latest(pads.pads)  # (None: the mouse)
        io.buttons += self.chat.shapes()  # the map under the chat is out of reach
        io.update(view, game.countries.values(), source, pads.fresh(source))
        if source is None and self._swallowed:
            io.left_pressed, io.right_clicked = 0, False  # (pressed on the chat)
        own = self._own_open()
        mine = game.local_players()
        if not own and not game.dialog_up and pads.needs_pairing(mine) and any(
                pad.tapped(controls.A) and pads.player_of(pad, mine) is None for pad in pads.pads):
            game.open_pairing()  # a controller nobody has yet wants in (that press is the panel's)
            own = True
        for button in self._down:
            if own or (button == controls.A and self._local_at(mouse)):
                self._swallowed.add(button)
            else:
                self._sent_down.append(button)
        self._down = []
        for pad in pads.pads:
            swallowed = self._pad_swallowed.setdefault(pad.number, set())
            swallowed &= pad.held
            for button in pad.taps:
                if button not in SENT_BUTTONS:
                    continue  # Start, Back, LB/RB: this device's own
                if own or (button == controls.A and self._local_at(pad.pos)):
                    swallowed.add(button)
                else:
                    self._pad_down.setdefault(pad.number, []).append(button)
        # Panning and zooming are this device's own: everyone's here, or only
        # the deciding player's when several players share it.
        scroll_mouse, scroll_pads = pads.scrollers(mine, self._online("acting"))
        game.zoom_view([1 if self._wheel > 0 else -1] * abs(self._wheel) if scroll_mouse else [], scroll_pads)
        self._wheel = 0
        game.pan_view(scroll_mouse, scroll_pads)

    def _hovered(self):
        """The country whose info panel this device shows: the one under its
        pointer, unless something is over the map there (the game's layer,
        the game's shop) or one of its own menus is open."""
        io = self.game.io
        name = io.hover_country
        if name is None or self._own_open() or self._my_shop():
            return None
        x, y = io.mouse_position.x, io.mouse_position.y
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT) or self.overlay.get_at((x, y))[3]:
            return None
        if self.private is not None:
            image, rect = self.private
            if rect.collidepoint(x, y) and image.get_at((x - rect.x, y - rect.y))[3]:
                return None
        return name

    # --- drawing -----------------------------------------------------------

    def _draw(self, mouse):
        window, area = self.window, self.area
        if self.game is None:
            window.fill((30, 30, 40))
            text = self.font.render(t("Waiting for the game..."), True, (255, 255, 255))
            window.blit(text, text.get_rect(center=area.center))
        else:
            self._draw_game()
        self.chat.draw(window, self.scale, area.topleft, mouse)
        own = {}  # this device's controllers: how the host says they look
        view = self.game.view if self.game is not None else None
        for entry in self.cursors:
            x, y, r, g, b, faded, member, number = entry[:8]
            if member == self.me:
                own[number] = ((r, g, b), faded)
                continue  # its mouse is the system's cursor, its controllers drawn below
            if view is not None:
                x, y = online.cursor_spot(entry, view, self.overlay)
            self._cursor((r, g, b), faded, x, y)
        for pad in self.pads.pads:
            color, faded = own.get(pad.number, (controls.UNPAIRED_COLOR, False))
            self._cursor(color, faded, pad.x, pad.y)
        if self.menu_open or pg.time.get_ticks() < self.hint_until:
            canvas = pg.Surface((WIDTH, HEIGHT), pg.SRCALPHA)
            if self.menu_open:
                self._draw_menu(canvas, mouse)
            else:
                text = self.hint_font.render(t("Esc: menu (leave the game, fullscreen)"), True, (255, 255, 255))
                box = text.get_rect(midbottom=(WIDTH // 2, HEIGHT - 12)).inflate(16, 8)
                pg.draw.rect(canvas, (0, 0, 0, 170), box, border_radius=6)
                canvas.blit(text, text.get_rect(center=box.center))
            window.blit(pg.transform.smoothscale(canvas, area.size), area.topleft)
        pg.display.flip()

    def _draw_game(self):
        """The map from this device's copy of the game, the game's layer over
        it, then what's this device's own."""
        game, area = self.game, self.area
        game.draw_world()
        window = game.view.window
        window.blit(self._scale("overlay", self.overlay, pg.Rect((0, 0), (WIDTH, HEIGHT))), area.topleft)
        if self.private is not None or self.dim:
            if self.dim:
                dim = pg.Surface(area.size, pg.SRCALPHA)
                dim.fill((0, 0, 0, 140))
                window.blit(dim, area.topleft)
            if self.private is not None:
                image, rect = self.private
                window.blit(self._scale("private", image, rect),
                            (area.x + round(rect.x * self.scale), area.y + round(rect.y * self.scale)))
        # On the copy's own layer (game.ui, emptied by draw_world).
        menu_was_open = self.menu_open
        if menu_was_open:
            game.io.left_pressed, game.io.right_clicked = 0, False  # (the clicks are the Esc menu's)
        game._handle_action_box()
        game._handle_turn_order(self._turn_order_hidden())
        if not game.dialog_up:
            game._hud_buttons(shop_open=self._my_shop() or self.device.look == "shop")
        name = self._hovered() if not menu_was_open else None
        if name is not None:
            game._draw_country_info(name)
        game._draw_turn_order(self._turn_order_hidden())
        game._draw_action_box()
        start = not menu_was_open and any(pad.tapped(controls.START) for pad in self.pads.pads)
        game._own_menu(self.device, start)
        window.blit(pg.transform.smoothscale(game.ui, area.size), area.topleft)

    def _scale(self, name, image, rect):
        """`image` (in logical `rect`) scaled to the window, kept until it changes."""
        size = (max(1, round(rect.w * self.scale)), max(1, round(rect.h * self.scale)))
        key, scaled = self._scaled.get(name, (None, None))
        if key != (id(image), size):
            scaled = pg.transform.smoothscale(image, size)
            self._scaled[name] = ((id(image), size), scaled)
        return scaled

    def _cursor(self, color, faded, x, y):
        sprite, margin = controls.cursor_sprite(color, faded, self.scale)
        self.window.blit(sprite, (round(self.area.x + x * self.scale) - margin,
                                  round(self.area.y + y * self.scale) - margin))

    def _menu_rects(self):
        w, h = 340, 64
        x = WIDTH // 2 - w // 2
        return [pg.Rect(x, 210 + i * (h + 18), w, h) for i in range(3)]

    def _menu_labels(self):
        return [t("Back to game"), t("Windowed") if self.fullscreen else t("Fullscreen"), t("Leave game")]

    def _menu(self, mouse, clicks):
        """This device's own menu: returns "leave" when Leave game is clicked."""
        back, screen_mode, leave = self._menu_rects()
        for click in clicks:
            if back.collidepoint(click):
                sounds.play("click")
                self.menu_open = False
            elif screen_mode.collidepoint(click):
                sounds.play("click")
                self.fullscreen = not self.fullscreen
                if self.game is not None:
                    self.game.toggle_fullscreen()
                else:
                    self.window = open_window((WIDTH, HEIGHT), self.fullscreen)
                self._layout()
            elif leave.collidepoint(click):
                sounds.play("click")
                return "leave"
        return None

    def _draw_menu(self, canvas, mouse):
        canvas.fill((0, 0, 0, 150))
        rects = self._menu_rects()
        panel = rects[0].union(rects[-1]).inflate(60, 110).move(0, -20)
        pg.draw.rect(canvas, (255, 240, 170), panel)
        pg.draw.rect(canvas, (0, 0, 0), panel, 3)
        title = self.font.render(t("Online Game"), True, (0, 0, 0))
        canvas.blit(title, (panel.centerx - title.get_width() // 2, panel.y + 14))
        colors = [(150, 245, 150), (150, 200, 245), (240, 100, 100)]
        for rect, label, color in zip(rects, self._menu_labels(), colors):
            _draw_button(canvas, self.font, rect, label, color, hovered=rect.collidepoint(mouse))


def _overlay(message):
    """(image, logical rect) of a menu message from the host; None for
    none, or anything broken or out of place."""
    rect, data = message.get("rect"), message.get("png")
    if not (isinstance(rect, list) and len(rect) == 4 and isinstance(data, str)
            and all(isinstance(v, int) and not isinstance(v, bool) for v in rect)):
        return None
    rect = pg.Rect(rect)
    try:
        image = pg.image.load(io.BytesIO(base64.b64decode(data)), "overlay.png")
    except (ValueError, binascii.Error, pg.error):
        return None
    if image.get_size() != rect.size or not pg.Rect(0, 0, WIDTH, HEIGHT).contains(rect):
        return None
    return image, rect


def _valid_cursor(entry):
    return (isinstance(entry, list) and len(entry) == 10
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in entry[:5])
            and all(0 <= int(v) <= 255 for v in entry[2:5])
            and isinstance(entry[6], int) and isinstance(entry[7], (int, str))
            and all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for v in entry[8:]))


def run(conn, me, seats):
    """Play a joined online game on this device (see Viewer.run)."""
    return Viewer(conn, me, seats).run()
