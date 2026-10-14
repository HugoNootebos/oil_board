"""
A joined device's side of an online game (online.py is the host's): the
host's screen as it comes in, everyone's cursor on top of it, the host's
sounds, and this device's mouse and game controllers sent back. The game
itself runs on the host's computer only; this device's pointers click
there when one of its players decides (online.HostSession.remote_clickers).

Esc (or a controller's Back button) opens a small menu of this device's
own: back to the game, fullscreen or windowed, leave the game. The chat
(chat.py) is this device's own too: drawn over the host's picture, its
clicks and keys stay here; only a message sent goes to the host.
"""

import pygame as pg

import chat
import controls
import online
import sounds
from engine import open_window
from fonts import game_font
from lang import t
from menu import _draw_button

WIDTH, HEIGHT = controls.WIDTH, controls.HEIGHT
MOTION_MS = 16    # mouse moves sent at most this often
HINT_MS = 6000    # how long "Esc: menu" shows at the start
BACK = pg.CONTROLLER_BUTTON_BACK
MOUSE_BUTTONS = {1: controls.A, 2: online.MIDDLE, 3: controls.B}

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
        self.frame = pg.Surface(online.STREAM_SIZE)
        self.frame.fill((30, 30, 40))
        self.seq = 0
        self.scaled = None
        self.cursors = []
        self.pads = controls.get()
        self.menu_open = False
        self.hint_until = pg.time.get_ticks() + HINT_MS
        self.font = game_font(26)
        self.hint_font = game_font(18)
        self._down, self._wheel = [], 0
        self._mouse_sent, self._mouse_sent_at = None, 0
        self._pads_sent = {}
        self._bind_sent = None
        self._drawn = None
        self._swallowed = set()  # mouse buttons pressed on the chat: not sent as held
        self.chat = chat.Chat(lambda text: self.conn.send({"type": "chat", "text": text}), me)
        self._layout()

    def _layout(self):
        """The game's 960x640 area in the window: as big as fits, centred."""
        sw, sh = self.window.get_size()
        self.scale = min(sw / WIDTH, sh / HEIGHT)
        w, h = round(WIDTH * self.scale), round(HEIGHT * self.scale)
        self.area = pg.Rect((sw - w) // 2, (sh - h) // 2, w, h)
        self.scaled = None
        self._drawn = None

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
        while True:
            events = pg.event.get()
            if any(event.type == pg.QUIT for event in events):
                self._leave()
                pg.quit()
                raise SystemExit
            clicks = self._events(events)
            self.pads.handle_events(events)
            if any(pad.tapped(BACK) for pad in self.pads.pads):
                self.menu_open = not self.menu_open
            mouse = self._logical(pg.mouse.get_pos())
            if self.menu_open:
                clicks += [pad.pos for pad in self.pads.pads if pad.tapped(controls.A)]
                if self._menu(mouse, clicks) == "leave":
                    self._leave()
                    return None
                self._down, self._wheel = [], 0
            else:
                self._send_input(mouse)
            ending = self._receive()
            if ending is not None:
                return t(ENDINGS[ending])
            self._draw(mouse)
            clock.tick(60)

    def _events(self, events):
        """This frame's mouse and keys: the chat's go to the chat, Esc
        toggles the menu, the rest is for the host. Returns the left clicks
        (logical), for the menu."""
        clicks = []
        for event in events:
            if not self.menu_open and self.chat.handle(event, self._logical):
                if event.type == pg.MOUSEBUTTONDOWN and event.button in MOUSE_BUTTONS:
                    self._swallowed.add(MOUSE_BUTTONS[event.button])
                continue
            if event.type == pg.MOUSEBUTTONUP and event.button in MOUSE_BUTTONS:
                self._swallowed.discard(MOUSE_BUTTONS[event.button])
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

    # --- the network -------------------------------------------------------

    def _send_input(self, mouse):
        conn = self.conn
        now = pg.time.get_ticks()
        held = [b for b, on in zip((controls.A, online.MIDDLE, controls.B), pg.mouse.get_pressed())
                if on and b not in self._swallowed]  # (a press on the chat isn't the host's)
        state = (mouse, held)
        if self._down or self._wheel or (state != self._mouse_sent and (
                self._mouse_sent is None or held != self._mouse_sent[1] or now - self._mouse_sent_at >= MOTION_MS)):
            conn.send({"type": "mouse", "x": mouse[0], "y": mouse[1], "held": held,
                       "down": self._down, "wheel": self._wheel})
            self._mouse_sent, self._mouse_sent_at = state, now
            self._down, self._wheel = [], 0
        numbers = set()
        for pad in self.pads.pads:
            numbers.add(pad.number)
            state = (pad.pos, sorted(pad.held))
            down = [b for b in pad.taps if b != BACK]
            if down or pad.pan != (0.0, 0.0) or state != self._pads_sent.get(pad.number):
                conn.send({"type": "pad", "n": pad.number, "x": pad.x, "y": pad.y, "held": sorted(pad.held),
                           "down": down, "pan": list(pad.pan)})
                self._pads_sent[pad.number] = state
        for number in [n for n in self._pads_sent if n not in numbers]:
            conn.send({"type": "pad", "n": number, "gone": True})  # unplugged
            del self._pads_sent[number]
        bind = {str(pad.number): self.pads.bindings[pad.instance_id]
                for pad in self.pads.pads if pad.instance_id in self.pads.bindings}
        if bind != self._bind_sent:
            conn.send({"type": "pads", "bind": bind})
            self._bind_sent = bind

    def _receive(self):
        """Take in what came from the host: the picture, cursors, sounds.
        Returns a key of ENDINGS when the game is over for this device."""
        for message in self.conn.poll():
            if isinstance(message, bytes):
                try:
                    self.seq = online.apply_update(self.frame, message)
                except ValueError:
                    continue
                self.scaled = None
                self.conn.send({"type": "ack", "seq": self.seq})
                continue
            kind = message.get("type")
            if kind == "cursors" and isinstance(message.get("c"), list):
                self.cursors = [c for c in message["c"] if _valid_cursor(c)]
            elif kind == "sound":
                name = str(message.get("name", ""))
                if message.get("kind") == "country":
                    sounds.play_country(name)
                elif name.replace("_", "").isalnum():
                    sounds.play(name)
            elif kind == "chat":
                self.chat.add(message.get("lines"), old=bool(message.get("old")))
            elif kind == "seats" and isinstance(message.get("seats"), list):
                self.seats = message["seats"]
            elif kind == "end":
                return "closed" if message.get("reason") == "closed" else "ended"
            elif kind == "closed":
                return "gone"
            elif kind == "kicked":
                return "kicked"
        return "lost" if self.conn.closed else None

    def _leave(self):
        self.conn.send({"type": "leave"})
        self.conn.close()

    # --- drawing -----------------------------------------------------------

    def _draw(self, mouse):
        hint = pg.time.get_ticks() < self.hint_until
        pads = [(pad.number, pad.pos) for pad in self.pads.pads]
        key = (self.seq, self.window.get_size(), str(self.cursors), pads, self.menu_open,
               mouse if self.menu_open else None, hint, self.chat.key(mouse))
        if key == self._drawn:
            return  # nothing new to show
        self._drawn = key
        window, area, scale = self.window, self.area, self.scale
        if self.scaled is None:
            self.scaled = pg.transform.smoothscale(self.frame, area.size)
        window.fill((0, 0, 0))
        window.blit(self.scaled, area.topleft)
        self.chat.draw(window, scale, area.topleft, mouse)
        own = {}  # this device's controllers: how the host says they look
        for x, y, r, g, b, faded, member, number in self.cursors:
            if member == self.me:
                own[number] = ((r, g, b), faded)
                continue  # its mouse is the system's cursor, its controllers drawn below
            self._cursor((r, g, b), faded, x, y)
        for pad in self.pads.pads:
            color, faded = own.get(pad.number, (controls.UNPAIRED_COLOR, False))
            self._cursor(color, faded, pad.x, pad.y)
        if self.menu_open or hint:
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


def _valid_cursor(entry):
    return (isinstance(entry, list) and len(entry) == 8
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in entry[:5])
            and all(0 <= int(v) <= 255 for v in entry[2:5])
            and isinstance(entry[6], int) and isinstance(entry[7], (int, str)))


def run(conn, me, seats):
    """Play a joined online game on this device (see Viewer.run)."""
    return Viewer(conn, me, seats).run()
