"""
The host's side of an online game (net.py has the whole picture, viewer.py
is the side of a device that joined): the lobby's seats, the devices that
joined and their pointers in the game, and what they get to see.

The host's computer plays the game exactly as a local game (runner.play);
a device that joined is just more pointers for it. Each device's mouse,
and each of its game controllers, is a RemotePointer that Controls and Io
take like a game controller (controls.Pad): it only clicks when its
player's decision is up (`remote_clickers`), and while it is, the host's
own mouse doesn't click (`mouse_allowed`).

Every device draws the map itself, from a copy of the game (viewer.py):
it pans and zooms it on its own, and its pointer points at the map
through its own view (RemotePointer.view, sent with its input). The host
sends it the game's state (`_sync_state`: save_load.game_data, then only
what changed, plus what's on screen: the countries highlighted, whose
decision it is...) and the action log (`_sync_log`), and the game's layer
(`OverlayStream`: everything the game draws over the map in the logical
960x640 -- the HUD, dice, popups, dialogs, the event card coming up --
as PNG pieces of what changed). What is each device's own it draws itself:
its chat (chat.py), the info panel of the country its pointer is over, the
action log (open or not), and its own menus (settings, the event card, a
look at the shop and its cards). Only the game's shop and cards on its
player's turn are the game's: the host draws them on the device's own
layer and sends that as a picture (`show_menus`). A device's pagoda/torii
dropped on its own map comes as landmark{name, on}.

Messages from the host to its devices (through the relay, "to" a member
or all): seats{state, title, seats}, start, state{full, set, countries},
log{lines, reset}, cursors{c}, sound{kind, name}, chat{lines, old},
menu{rect, png, dim} (no rect: none), end{reason}, and the game's layer
as BINARY (`OverlayStream.update_since`). From a device: take/release/
name{seat, text} (its seats), pads{bind}, ready (it shows the game now),
ack (a layer update arrived), mouse/pad (its input, with its view and
whether it has a menu of its own open), landmark{name, on}, chat{text}
(see chat.py).
"""

import base64
import io
import json
import math
import struct
import threading
import time

import numpy as np
import pygame as pg

import chat
import controls
import lang
import net
import relay
import save_load
import sounds
from lang import t
from models import Io, LANDMARKS, Position, View, WORLD_WIDTH

# Posted (by the network threads) to wake a game loop waiting for events.
NET_EVENT = pg.event.custom_type()

OVERLAY_SIZE = (controls.WIDTH, controls.HEIGHT)  # the game's layer, logical px
TILE = 80                  # px: the layer is compared and sent in tiles this size
CAPTURE_MS = 50            # at most 20 captures a second
MAX_RECTS = 12             # more changed pieces than this go as their bounding box
MAX_IN_FLIGHT = 2          # updates on their way to a device before it has to say it got them
CURSOR_MS = 33             # cursors at most 30 times a second
HOVER_MS = 80              # a device's own layer (the game's shop/cards) at most 12 times a second
STATE_MS = 50              # the game's state at most 20 times a second
LOG_LINES = 100            # the action log a device gets on coming in
MAX_PADS = 8               # game controllers per device
NAME_MAX = 20

MIDDLE = "middle"  # a mouse's middle button
BUTTONS = {controls.A, controls.B, MIDDLE}

KINDS = ("open", "host", "bot")  # what the host can make a seat in a new game


def wake():
    """Wake a game loop waiting in pg.event.wait() (from a network thread)."""
    try:
        pg.event.post(pg.event.Event(NET_EVENT))
    except pg.error:
        pass  # no window (anymore)


def clean_name(text):
    return "".join(ch for ch in str(text) if ch.isprintable())[:NAME_MAX]


def _button(value):
    return isinstance(value, (int, str)) and not isinstance(value, bool) and value in BUTTONS


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def map_spot(view, x, y):
    """The map point under (x, y) (logical px) in `view`, as [x, y]."""
    return [round((x - 0.5 * view.WIDTH) / view.zoom - view.offset.x, 1),
            round((y - 0.5 * view.HEIGHT) / view.zoom - view.offset.y, 1)]


def cursor_spot(entry, view, overlay):
    """Where a cursor of the list `HostSession._cursor_list` makes
    ([x, y, ..., map x, map y]) is drawn on a screen with `view`: over the
    map, at the same map point (each device has its own view of it); over
    the game's layer (`overlay`: a popup, the HUD...), at the same place on
    the screen."""
    x, y, mx, my = entry[0], entry[1], entry[8], entry[9]
    inside = 0 <= x < overlay.get_width() and 0 <= y < overlay.get_height()
    if mx is None or my is None or (inside and overlay.get_at((int(x), int(y)))[3]):
        return x, y
    period = WORLD_WIDTH * view.zoom
    sx = (mx + view.offset.x) * view.zoom
    sx = (sx + 0.5 * period) % period - 0.5 * period  # the copy of the world nearest the middle
    return sx + 0.5 * view.WIDTH, (my + view.offset.y) * view.zoom + 0.5 * view.HEIGHT


class Seat:
    """One player of an online game. kind: "host" (plays on the host's
    computer), "bot", "remote" (a device that joined: `member`) or "open"
    (nobody yet, or their device dropped out: the host's mouse plays it
    then). `kinds`: what the host may make it (a saved game's humans stay
    human, its bots bots). `device` is the id of the device that last had
    it: coming back, it gets it again."""

    def __init__(self, name="", color=(235, 235, 235), kind="open", fixed=False, kinds=KINDS):
        self.name = name
        self.color = tuple(int(c) for c in color)
        self.kind = kind
        self.fixed = fixed  # the name can't change (a saved game, De 3 Neven, a game that started)
        self.kinds = kinds
        self.member = None
        self.device = None

    def to_json(self):
        return {"name": self.name, "color": list(self.color), "kind": self.kind,
                "member": self.member, "fixed": self.fixed}


class RemotePointer:
    """A joined device's mouse (number "m") or one of its game controllers
    (its number), as the host's game sees it: like a controls.Pad, so
    Controls and Io take it as one more pointer, pointing at the map
    through its device's `view` (which pans and zooms on the device). Its
    input arrives between frames (`feed`) and is handed out a frame at a
    time (`next_frame`): a second click of the same button within one frame
    waits for the next."""

    pan = (0.0, 0.0)  # (the device pans and zooms its own map)
    zoom_steps = ()

    def __init__(self, member, number="m", view=None):
        self.member = member
        self.number = number
        self.view = view
        self.x, self.y = controls.WIDTH * 0.5, controls.HEIGHT * 0.5
        self.held = set()
        self.taps = []
        self.last_active = -1
        self._presses = []

    @property
    def pos(self):
        return int(self.x), int(self.y)

    @property
    def pressed(self):
        A, B = controls.A, controls.B
        return (A in self.held or A in self.taps, MIDDLE in self.held, B in self.held or B in self.taps)

    @property
    def fresh(self):
        return (controls.A in self.taps, False, controls.B in self.taps)

    def tapped(self, button):
        return button in self.taps

    def feed(self, message, now):
        try:
            x = min(max(float(message.get("x", self.x)), 0.0), controls.WIDTH - 1.0)
            y = min(max(float(message.get("y", self.y)), 0.0), controls.HEIGHT - 1.0)
        except (TypeError, ValueError):
            return
        if (x, y) != (self.x, self.y):
            self.x, self.y = x, y
            self.last_active = now
        held, down = message.get("held"), message.get("down")
        self.held = {b for b in held if _button(b)} if isinstance(held, list) else set()
        presses = [b for b in down if _button(b)][:8] if isinstance(down, list) else []
        if presses:
            self._presses += presses
            self.last_active = now

    def next_frame(self):
        taps, later = [], []
        for button in self._presses:
            # Pressed again right after (two clicks arriving together): Io has
            # to see it up for a frame in between, or it's no new click.
            (later if button in taps or button in self.taps else taps).append(button)
        self.taps, self._presses = taps, later


class OverlayStream:
    """The game's layer (Engine.ui: what the game draws over the map, in
    the logical 960x640, see the module docstring) as the joined devices
    get it: captured at most every CAPTURE_MS, compared tile by tile with
    the capture before, and sent as PNG pieces (see-through where the map
    shows) of whatever changed since the capture a device already has
    (`update_since`). A slow device so gets fewer, bigger updates rather
    than falling ever further behind."""

    def __init__(self, size=OVERLAY_SIZE, tile=TILE):
        self.size = size
        self.tile = tile
        self.cols, self.rows = size[0] // tile, size[1] // tile
        self.seq = 0  # the current capture's number
        self.frame = None
        self.pending = False  # a capture was skipped (too soon after the last): one is still owed
        self._pixels = None
        self._changed_at = np.zeros((self.rows, self.cols), dtype=np.int64)  # capture a tile last changed in
        self._captured_at = None
        self._updates = {}  # base capture -> update to the current one

    def capture(self, surface, now=None):
        """Take the layer `surface` (OVERLAY_SIZE, with alpha). Returns True
        when it changed."""
        now = pg.time.get_ticks() if now is None else now
        if self._captured_at is not None and 0 <= now - self._captured_at < CAPTURE_MS:
            self.pending = True
            return False
        self._captured_at = now
        self.pending = False
        if surface.get_size() != self.size:
            surface = pg.transform.smoothscale(surface, self.size)
        pixels = np.frombuffer(pg.image.tobytes(surface, "RGBA"), dtype=np.uint8).reshape(
            self.size[1], self.size[0], 4)
        if self._pixels is None:
            changed = np.ones((self.rows, self.cols), dtype=bool)
        else:
            differs = (pixels != self._pixels).any(axis=2)
            changed = differs.reshape(self.rows, self.tile, self.cols, self.tile).any(axis=(1, 3))
        if not changed.any():
            return False
        self.seq += 1
        self._changed_at[changed] = self.seq
        self.frame, self._pixels = surface.copy(), pixels
        self._updates = {}
        return True

    def update_since(self, base):
        """The bytes that bring a device that has capture `base` to the
        current one (base -1: nothing yet, the whole layer); None when it
        already has it."""
        if self.frame is None or base >= self.seq:
            return None
        update = self._updates.get(base)
        if update is None:
            rects = self._rects(self._changed_at > base) if base >= 0 else \
                [(0, 0, self.size[0], self.size[1])]
            pieces, header = [], []
            for x, y, w, h in rects:
                buffer = io.BytesIO()
                pg.image.save(self.frame.subsurface((x, y, w, h)), buffer, "update.png")
                pieces.append(buffer.getvalue())
                header.append([x, y, w, h, len(pieces[-1])])
            head = json.dumps({"seq": self.seq, "size": list(self.size), "rects": header}).encode("utf-8")
            update = self._updates[base] = struct.pack(">I", len(head)) + head + b"".join(pieces)
        return update

    def _rects(self, mask):
        """The tiles in `mask` as a few rectangles (px): each row's runs of
        tiles, a run merged with the same run in the row above."""
        rects = []
        open_runs = {}  # (first column, end column) -> [first row, rows]
        for r in range(self.rows):
            runs = set()
            c = 0
            while c < self.cols:
                if mask[r, c]:
                    start = c
                    while c < self.cols and mask[r, c]:
                        c += 1
                    runs.add((start, c))
                c += 1
            for run in list(open_runs):
                if run not in runs:
                    rects.append((run,) + tuple(open_runs.pop(run)))
            for run in runs:
                if run in open_runs:
                    open_runs[run][1] += 1
                else:
                    open_runs[run] = [r, 1]
        rects += [(run, r0, n) for run, (r0, n) in open_runs.items()]
        if len(rects) > MAX_RECTS:
            rows, cols = np.nonzero(mask)
            rects = [((cols.min(), cols.max() + 1), rows.min(), rows.max() + 1 - rows.min())]
        tile = self.tile
        return [(int(c0) * tile, int(r0) * tile, (int(c1) - int(c0)) * tile, int(n) * tile)
                for (c0, c1), r0, n in rects]


def apply_update(surface, data):
    """Put an update (OverlayStream.update_since) onto `surface` (with
    alpha, the stream's size): its pieces replace what was there. Returns
    its capture number; ValueError if it's no update."""
    try:
        (length,) = struct.unpack_from(">I", data)
        head = json.loads(data[4:4 + length].decode("utf-8"))
        position = 4 + length
        bounds = surface.get_rect()
        for x, y, w, h, size in head["rects"]:
            image = pg.image.load(io.BytesIO(data[position:position + size]), "update.png")
            position += size
            rect = pg.Rect(x, y, w, h)
            if bounds.contains(rect) and image.get_size() == (w, h):
                surface.fill((0, 0, 0, 0), rect)
                surface.blit(image, rect, special_flags=pg.BLEND_RGBA_MAX)  # (a copy, alpha and all)
        return int(head["seq"])
    except (struct.error, ValueError, KeyError, TypeError, pg.error) as error:
        raise ValueError("not an update") from error


class Member:
    """A device that joined the host's game (its relay member number)."""

    def __init__(self, number, device):
        self.id = number
        self.device = device
        # How it shows the map (its pointers point at the map through it).
        self.view = View(None, View.START_ZOOM, Position(*View.START_OFFSET), controls.WIDTH, controls.HEIGHT)
        self.pointers = {"m": RemotePointer(number, "m", self.view)}
        self.pad_names = {}    # its controllers: number -> player name
        self.viewing = False   # in the game (it said "ready"), not in the lobby
        self.menu_open = False  # it has a menu of its own open (its clicks are that menu's)
        self.base = -1         # the layer capture it has (or will have, once what's on its way arrives)
        self.in_flight = 0
        self.has_state = False  # it has the game's state (then it gets what changes)
        self.log_sent = False
        self.log_last = None   # the last action-log line it has


class Device:
    """A device's own menus in the game (Engine.own_menus): this computer's
    (id 0, run by the host) or a joined device's (its member number; run by
    the device itself, viewer.py, which uses `look` and `cards`). On the
    host its pointer reads clicks for them (`io`), they're drawn on its
    `layer`, and a joined device's layer is where the game's shop and cards
    are drawn on its player's turn (Engine.private_layer)."""

    def __init__(self, number):
        self.id = number
        self.io = Io()
        self.layer = None
        self.drawn = False     # its layer has been used this frame
        self.dim = False       # a joined device's menu wants its picture dimmed
        self.look = None       # "shop" / "cards": a look at them (not the game's own)
        self.cards = None      # the models.CardMenu its cards look shows
        self.fields = {"settings_open": False, "event_info_open": False, "dragging_landmark": None,
                       "save_as_open": False, "save_as_slot": None, "save_as_name": "", "save_as_names": []}
        self.start_seen = False
        self.sent = None       # the menu picture it has
        self.sent_at = -HOVER_MS


class HostSession:
    """A hosted online game: from the lobby (lobby.py's host screen) to its
    end. Opening the room happens in the background: `status` goes from
    "connecting" to "online" (the main relay: everyone can see it), "lan"
    (a relay of its own: only the local network can) or "failed"."""

    def __init__(self, seats, connect=True):
        self.seats = seats
        self.state = "lobby"  # "game" once started, "closed" when over
        self.status = "connecting"
        self.conn = None
        self.members = {}  # relay member number -> Member
        self.app = None
        self.stream = OverlayStream()
        self._relay = None
        self._closing = False
        self._cursors = None
        self._cursors_at = 0
        self._cursor_due = False
        self._menu_due = False
        self._game_state = None  # what the devices that have it were sent last
        self._state_at = -STATE_MS
        self._state_due = False
        self.devices = {0: Device(0)}  # their own layers, by device (0: this computer)
        self.chat = chat.Chat(self.say)  # this computer's chat (the host's messages go out from `say`)
        if connect:  # (online_checks.py tries a session without a network)
            threading.Thread(target=self._open, name="oil-host", daemon=True).start()

    # --- opening the room ------------------------------------------------

    def _open(self):
        conn = net.find_main_relay(stop=lambda: self._closing)
        if conn is None and not self._closing:
            try:
                self._relay = relay.start_embedded()
                conn = net.connect(("127.0.0.1", self._relay.port))
            except (OSError, net.ConnectError):
                conn = None
        if conn is not None and not self._closing:
            conn.send({"type": "open", "info": self.room_info()})
            deadline = time.time() + 5
            while time.time() < deadline and not conn.closed and not self._closing:
                if any(isinstance(m, dict) and m.get("type") == "opened" for m in conn.poll()):
                    conn.wake = wake
                    self.conn = conn
                    self.status = "online" if conn.kind == "main" else "lan"
                    if self._closing:
                        self.close("closed")
                    return
                time.sleep(0.05)
        if conn is not None:
            conn.close()
        if self._relay is not None:
            self._relay.stop(0)
            self._relay = None
        if not self._closing:
            self.status = "failed"

    def room_info(self):
        """The game as the list of games shows it."""
        hosts = [self.seat_name(i) for i, seat in enumerate(self.seats) if seat.kind == "host"]
        free = sum(seat.kind == "open" for seat in self.seats)
        return {"title": (hosts[0] if hosts else self.seat_name(0))[:40], "proto": net.PROTOCOL,
                "seats": len(self.seats), "taken": len(self.seats) - free, "free": free, "state": self.state}

    # --- the lobby ------------------------------------------------------------

    def seat_name(self, i):
        """Seat i's name, or the name it gets when none was typed (as on the
        player-names screen)."""
        seat = self.seats[i]
        if seat.name.strip():
            return seat.name.strip()
        return "Bot {}".format(i + 1) if seat.kind == "bot" else t("Player {}").format(i + 1)

    def cycle_kind(self, i):
        """The host clicks a seat's kind: the next of its kinds; a joined
        device's seat is taken off it."""
        seat = self.seats[i]
        if seat.kind == "remote":
            seat.kind, seat.member, seat.device = "open", None, None
        elif seat.kind in seat.kinds and len(seat.kinds) > 1:
            seat.kind = seat.kinds[(seat.kinds.index(seat.kind) + 1) % len(seat.kinds)]
        else:
            return
        self._changed()

    def set_name(self, i, text):
        seat = self.seats[i]
        if not seat.fixed and seat.kind in ("host", "bot"):
            seat.name = clean_name(text)
            self._changed()

    def start_problem(self):
        """Why the game can't start yet (to show), or None."""
        if self.status not in ("online", "lan"):
            return t("Waiting for the connection")
        if any(seat.kind == "open" for seat in self.seats):
            return t("Every seat needs a player")
        names = [self.seat_name(i).casefold() for i in range(len(self.seats))]
        if len(set(names)) < len(names):
            return t("Two players have the same name")
        return None

    def start_game(self, app):
        """The game (`app`, made from the seats) starts: from now on its
        players are the seats, by name."""
        self.app = app
        self.state = "game"
        app.online = self
        for seat, player in zip(self.seats, app.players):
            seat.name = player.name
            seat.fixed = True
        sounds.listener = self._sound
        self._changed()  # the final names first: devices pair their controllers by them
        self._send({"type": "start"})

    def _changed(self):
        """Tell the relay's list and the devices how the seats are now."""
        if self.conn is None:
            return
        self.conn.send({"type": "info", "info": self.room_info()})
        seats = [dict(seat.to_json(), shown=self.seat_name(i)) for i, seat in enumerate(self.seats)]
        self._send({"type": "seats", "state": self.state, "title": self.room_info()["title"], "seats": seats})

    def _send(self, message, to=0):
        if self.conn is not None:
            self.conn.send(dict(message, to=to))

    # --- what comes in ------------------------------------------------------

    def update(self):
        """Take in what came from the relay; call every frame (lobby and
        game). True when a device's input came in."""
        conn = self.conn
        got_input = changed = False
        for message in conn.poll() if conn is not None else []:
            if not isinstance(message, dict):
                continue
            kind = message.get("type")
            if kind == "member":
                changed = self._member_joined(message) or changed
            elif kind == "left":
                changed = self._member_left(message.get("member")) or changed
            else:
                member = self.members.get(message.get("from"))
                if member is None:
                    continue
                if kind in ("mouse", "pad"):
                    got_input = self._input(member, message) or got_input
                elif kind == "ack":
                    member.in_flight = max(0, member.in_flight - 1)
                elif kind == "ready":
                    member.viewing, member.base, member.in_flight = True, -1, 0
                    member.has_state, member.log_sent, member.log_last = False, False, None
                    if member.id in self.devices:
                        self.devices[member.id].sent = None
                    self._cursors = None  # it needs them all
                    if self.chat.lines:
                        self._send({"type": "chat", "lines": self.chat.lines, "old": True}, to=member.id)
                elif kind == "pads":
                    self._pads(member, message.get("bind"))
                elif kind == "chat":
                    if member.viewing:
                        self.say(message.get("text", ""), member)
                elif kind == "landmark":
                    got_input = self._landmark(member, message) or got_input
                else:
                    changed = self._seat_request(member, kind, message) or changed
        if changed:
            self._changed()
        if conn is not None and conn.closed and self.state != "closed":
            self._lost()
        for pointer in self.pointers():
            pointer.next_frame()
        return got_input

    def _member_joined(self, message):
        number = message.get("member")
        if not isinstance(number, int):
            return False
        device = str(message.get("device", ""))
        self.members[number] = Member(number, device)
        self.devices[number] = Device(number)
        for seat in self.seats:
            if device and seat.kind == "open" and seat.device == device:
                seat.kind, seat.member = "remote", number  # back after dropping out
        return True

    def _member_left(self, number):
        self.devices.pop(number, None)
        if self.members.pop(number, None) is None:
            return False
        for seat in self.seats:
            if seat.member == number:
                seat.kind, seat.member = "open", None  # `device` stays, for coming back
        return True

    def _seat_request(self, member, kind, message):
        i = message.get("seat")
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(self.seats):
            return False
        seat = self.seats[i]
        if kind == "take" and seat.kind == "open":
            seat.kind, seat.member, seat.device = "remote", member.id, member.device
            if not seat.fixed:
                seat.name = ""
            return True
        if seat.member != member.id:
            return False
        if kind == "release":
            seat.kind, seat.member, seat.device = "open", None, None
            if not seat.fixed:
                seat.name = ""
            return True
        if kind == "name" and not seat.fixed:
            seat.name = clean_name(message.get("text", ""))
            return True
        return False

    def _pads(self, member, bind):
        names = self._names(member.id)
        member.pad_names = {}
        if isinstance(bind, dict):
            for number, name in bind.items():
                try:
                    number = int(number)
                except ValueError:
                    continue
                if name in names:
                    member.pad_names[number] = name

    def _input(self, member, message):
        view = message.get("view")
        if isinstance(view, list) and len(view) == 3 and all(_number(v) for v in view):
            member.view.zoom = min(max(float(view[0]), View.MIN_ZOOM), View.MAX_ZOOM)
            member.view.offset = Position(*(min(max(float(v), -1e5), 1e5) for v in view[1:]))
        if isinstance(message.get("menu"), bool):
            member.menu_open = message["menu"]
        if message["type"] == "mouse":
            pointer = member.pointers["m"]
        else:
            number = message.get("n")
            if not isinstance(number, int) or isinstance(number, bool):
                return False
            if message.get("gone"):
                return member.pointers.pop(number, None) is not None
            pointer = member.pointers.get(number)
            if pointer is None:
                if len(member.pointers) > MAX_PADS:
                    return False
                pointer = member.pointers[number] = RemotePointer(member.id, number, member.view)
        pointer.feed(message, pg.time.get_ticks())
        return True

    def _landmark(self, member, message):
        """A device's player dropped the pagoda/torii `name` on the country
        `on` of its own map (Engine._drag_landmark there): as when it's
        dropped here."""
        app = self.app
        name, on = message.get("name"), message.get("on")
        if self.state != "game" or app is None or not isinstance(name, str) or not isinstance(on, str):
            return False
        manager = app.turn_manager
        if self.current_device() != member.id or manager.dialog_active or name not in manager.landmarks_owed:
            return False
        if on == name:
            manager.place_landmark(name)
        elif on in LANDMARKS:
            manager.misplace_landmark(name, on)
        else:
            return False
        return True

    def _lost(self):
        """The connection to the relay broke: the game goes on here alone."""
        app, playing = self.app, self.state == "game"
        self.close("ended")
        self.status = "failed"
        if playing and app is not None:
            app.turn_manager.notices.append([
                t("The online connection was lost"),
                t("The game goes on here. To play on together, host it again: Online Game, Host, Continue")])

    # --- in the game: who clicks ----------------------------------------------

    def pointers(self):
        """The pointers of the devices that are in the game."""
        return [p for m in self.members.values() if m.viewing for p in m.pointers.values()]

    def _seat_of(self, name):
        return next((seat for seat in self.seats if seat.name == name), None)

    def _names(self, member_id):
        return [seat.name for seat in self.seats if seat.member == member_id]

    def names_of(self, pointer):
        """The players `pointer` stands for: all of its device's for its
        mouse; for a controller the one it's paired with (or the device's
        only player)."""
        names = self._names(pointer.member)
        if pointer.number == "m":
            return names
        member = self.members.get(pointer.member)
        name = member.pad_names.get(pointer.number) if member is not None else None
        if name in names:
            return [name]
        return names if len(names) == 1 else []

    def is_remote(self, pointer):
        return isinstance(pointer, RemotePointer)

    def local_players(self, players):
        """The players on the host's computer itself."""
        kinds = {seat.name: seat.kind for seat in self.seats}
        return [p for p in players if kinds.get(p.name, "host") in ("host", "bot")]

    def mouse_allowed(self, acting):
        """Whether the host's own mouse may click: not while it's the
        decision of a player on a joined device that's still there."""
        if acting.is_bot or getattr(self.app.turn_manager, "game_over", False):
            return True
        seat = self._seat_of(acting.name)
        return seat is None or seat.kind != "remote" or seat.member not in self.members

    def remote_clickers(self, acting):
        """The remote pointers that may click now (see controls.Controls.frame):
        those of `acting`'s device that stand for them; on a bot's turn
        everyone's (as every paired controller)."""
        if acting.is_bot:
            return [p for p in self.pointers() if self.names_of(p)]
        return [p for p in self.pointers() if acting.name in self.names_of(p)]

    # --- in the game: what goes out --------------------------------------------

    def _viewing(self):
        return [member for member in self.members.values() if member.viewing]

    @property
    def viewers(self):
        return any(member.viewing for member in self.members.values())

    @property
    def busy(self):
        """Something still has to go out: keep drawing frames."""
        return self.stream.pending or self._cursor_due or self._state_due or self._menu_due

    def capture(self, layer):
        """Engine.present: the game's layer (Engine.ui, before what's this
        computer's own is drawn on it)."""
        if self.state == "game" and self.viewers:
            self.stream.capture(layer)
        else:
            self.stream.pending = False

    def pump(self):
        """Send the devices what's new: the game's state and log, its layer
        (each at its own pace) and the cursors. Call after every frame."""
        conn = self.conn
        if conn is None or conn.closed or self.state != "game":
            return
        now = pg.time.get_ticks()
        self._sync_state(now)
        self._sync_log()
        for member in self._viewing():
            if member.in_flight >= MAX_IN_FLIGHT:
                continue
            update = self.stream.update_since(member.base)
            if update is not None:
                conn.send_binary(update, to=member.id)
                member.base = self.stream.seq
                member.in_flight += 1
        self._cursor_due = False
        if not self.viewers:
            return
        cursors = self._cursor_list()
        if cursors != self._cursors:
            if now - self._cursors_at < CURSOR_MS:
                self._cursor_due = True
            else:
                self._send({"type": "cursors", "c": cursors})
                self._cursors, self._cursors_at = cursors, now

    def game_state(self):
        """What a device needs to draw the game itself: the game's state as a
        save has it (save_load.game_data, without the log and the host's
        display settings), plus what's on screen ("online"): the steps of
        the players' phases, the countries highlighted, whose decision it
        is, whether a dialog is up, the pagoda/torii still to be placed and
        the host's language. Plain JSON."""
        app = self.app
        manager = app.turn_manager
        data = save_load.game_data(app, manager, log=False)
        data.pop("settings", None)
        data["online"] = {
            "subattack": [player.subattack for player in app.players],
            "shade": {name: country.shade for name, country in app.countries.items() if country.shade},
            "acting": manager.acting_player().name,
            "dialog": bool(manager.dialog_active),
            "owed": sorted(manager.landmarks_owed),
            "lang": lang.language,
            "fast_bots": bool(app.settings.get("fast_bots")),
        }
        return json.loads(json.dumps(data, cls=save_load._NumpyEncoder))

    def _sync_state(self, now):
        """Every device in the game gets the game's state: all of it when it
        comes in, then (at most every STATE_MS) what changed: the parts of
        it that did, of the countries only those that changed."""
        members = self._viewing()
        if not members:
            self._state_due = False
            return
        if 0 <= now - self._state_at < STATE_MS:
            self._state_due = True
            return
        self._state_at, self._state_due = now, False
        state, old = self.game_state(), self._game_state
        if old is not None and state != old:
            changed = {key: value for key, value in state.items() if key != "countries" and old.get(key) != value}
            countries = {name: country for name, country in state["countries"].items()
                         if old["countries"].get(name) != country}
            for member in members:
                if member.has_state:
                    self._send({"type": "state", "set": changed, "countries": countries}, to=member.id)
        self._game_state = state
        for member in members:
            if not member.has_state:
                self._send({"type": "state", "full": True, "set": state}, to=member.id)
                member.has_state = True

    def _sync_log(self):
        """Every device in the game gets the action log: its last LOG_LINES
        lines when it comes in (or when the log was replaced: a game
        loaded), then the lines added."""
        recent = self.app.action_log[-LOG_LINES:]
        newest = recent[-1] if recent else None
        for member in self._viewing():
            if member.log_sent and newest is member.log_last:
                continue
            start = None
            if member.log_sent and member.log_last is not None:
                start = next((i + 1 for i in range(len(recent) - 1, -1, -1) if recent[i] is member.log_last), None)
            if start is None:
                message = {"type": "log", "reset": True, "lines": [save_load.log_line(line) for line in recent]}
            else:
                message = {"type": "log", "lines": [save_load.log_line(line) for line in recent[start:]]}
            self._send(json.loads(json.dumps(message, cls=save_load._NumpyEncoder)), to=member.id)
            member.log_sent, member.log_last = True, newest

    def _look(self, names, clicker):
        """(colour, faded) of a cursor standing for the players `names`: the
        colour of the one whose decision it is, else of the first; faded
        while it can't click."""
        app = self.app
        acting = app.turn_manager.acting_player()
        name = acting.name if acting.name in names else (names[0] if names else None)
        player = next((p for p in app.players if p.name == name), None)
        color = tuple(int(c) for c in player.color) if player is not None else controls.UNPAIRED_COLOR
        return color, not clicker

    def _cursor_list(self):
        """Every cursor: [x, y, r, g, b, faded, member (0: the host), "m" or a
        controller's number, map x, map y]: where it is in the game's
        960x640 and the map point it's over in its own device's view (see
        cursor_spot)."""
        app, pads, view = self.app, self.app.controls, self.app.view
        entries = []
        x, y = pg.mouse.get_pos()
        x, y = round((x - view.ox) / view.scale), round((y - view.oy) / view.scale)
        if pg.mouse.get_focused() and 0 <= x < controls.WIDTH and 0 <= y < controls.HEIGHT:
            names = [seat.name for seat in self.seats if seat.kind == "host"]
            color, faded = self._look(names, pads is None or pads.mouse_ok)
            entries.append([x, y] + list(color) + [faded, 0, "m"] + map_spot(view, x, y))
        if pads is not None:
            for pad, (color, faded) in app._pad_looks().items():
                x, y = round(pad.x), round(pad.y)
                entries.append([x, y] + [int(c) for c in color] + [bool(faded), 0, pad.number] + map_spot(view, x, y))
        clickers = pads.clickers if pads is not None else []
        for pointer in self.pointers():
            color, faded = self._look(self.names_of(pointer), pointer in clickers)
            x, y = round(pointer.x), round(pointer.y)
            entries.append([x, y] + list(color) + [faded, pointer.member, pointer.number]
                           + map_spot(pointer.view, x, y))
        return entries

    def draw_cursors(self, surface, scale, offset):
        """The devices' cursors on the host's own screen (Engine.present)."""
        clickers = self.app.controls.clickers if self.app.controls is not None else []
        for pointer in self.pointers():
            color, faded = self._look(self.names_of(pointer), pointer in clickers)
            sprite, margin = controls.cursor_sprite(color, faded, scale)
            entry = [pointer.x, pointer.y, 0, 0, 0, faded, 0, 0] + map_spot(pointer.view, pointer.x, pointer.y)
            x, y = cursor_spot(entry, self.app.view, self.app.ui)
            surface.blit(sprite, (round(offset[0] + x * scale) - margin, round(offset[1] + y * scale) - margin))

    def _sound(self, kind, name):
        """sounds.listener: the devices hear what the host hears."""
        if self.viewers:
            self._send({"type": "sound", "kind": kind, "name": name})

    # --- in the game: this computer's country info panel ----------------------------------

    def _turn_rank(self, names):
        """How soon the players `names` decide: the one deciding now first,
        then by turns to go; no player at all last."""
        app = self.app
        acting = app.turn_manager.acting_player()
        count = len(app.players)
        ranks = [0 if player is acting else 1 + (i - app.turn) % count
                 for i, player in enumerate(app.players)
                 if player.name in names and not getattr(player, "eliminated", False)]
        return min(ranks, default=count + 1)

    def _pointers_here(self):
        """This computer's pointers that are in use: (position, the players it
        stands for, when last used). A controller stands for its player, the
        mouse for this computer's players without one of their own."""
        app, pads = self.app, self.app.controls
        here = [seat.name for seat in self.seats if seat.kind == "host"]
        entries, own = [], set()
        for pad in pads.pads if pads is not None else []:
            player = pads.player_of(pad, app.players)
            names = [player.name] if player is not None and player.name in here else []
            own.update(names)
            if pad.last_active >= 0:
                entries.append(((pad.x, pad.y), names, pad.last_active))
        if pg.mouse.get_focused():
            x, y = pg.mouse.get_pos()
            view = app.view
            entries.append((((x - view.ox) / view.scale, (y - view.oy) / view.scale),
                            [name for name in here if name not in own] or here,
                            pads.mouse_active if pads is not None else 0))
        return entries

    def _hovered(self, number, entries, chat_here=None):
        """The country device `number`'s info panel shows: of its pointers
        over a country, the one whose player decides soonest; between equals
        the one used last. None while it has a menu of its own open, or the
        game's shop (its player's turn)."""
        shopper = self.app.players[self.app.turn]
        if self.own_menu_open(number) or (
                shopper.attack == 3 and shopper.subattack < 8 and self.current_device() == number):
            return None
        best = None
        for position, names, used in entries:
            name = self.app.device_country_at(position, chat_here)
            if name is not None:
                key = (self._turn_rank(names), -used)
                if best is None or key < best[0]:
                    best = (key, name)
        return best[1] if best is not None else None

    def show_hovers(self, window, scale, offset):
        """This computer's country info panel, for the country its own
        pointer is over (Engine.present, after the game's layer is taken
        for the devices, which draw their own)."""
        if self.state != "game":
            return
        name = self._hovered(0, self._pointers_here(), self.chat)
        if name is None:
            return
        image, rect = self.app.country_panel(name)
        size = (max(1, round(rect.w * scale)), max(1, round(rect.h * scale)))
        window.blit(image if scale == 1 else pg.transform.smoothscale(image, size),
                    (round(offset[0] + rect.x * scale), round(offset[1] + rect.y * scale)))

    # --- in the game: each device's own menus (Engine.own_menus) --------------------------

    def device_of(self, name):
        """The device the player called `name` plays on: a joined one's
        number, else 0 (this computer: its own players, and those of a device
        that dropped out)."""
        seat = self._seat_of(name)
        if seat is not None and seat.kind == "remote" and seat.member in self.members:
            return seat.member
        return 0

    def current_device(self):
        """The device of the player whose turn it is; None on a bot's turn."""
        player = self.app.players[self.app.turn]
        return None if player.is_bot else self.device_of(player.name)

    def device_of_pointer(self, pointer):
        """A pointer's device: a joined one's, 0 for this computer's mouse
        (None) or controllers, None for nobody's (the parked pointer)."""
        if isinstance(pointer, RemotePointer):
            return pointer.member
        return 0 if pointer is None or isinstance(pointer, controls.Pad) else None

    def soonest_player(self, number):
        """Of the (human) players on device `number`, the one whose turn
        comes soonest; None for a device that only watches."""
        players = [p for p in self.app.players if not p.is_bot and self.device_of(p.name) == number
                   and not getattr(p, "eliminated", False)]
        return min(players, key=lambda p: self._turn_rank([p.name]), default=None)

    def own_menu_open(self, number):
        """Whether device `number` has a menu of its own open (a joined
        device says so with its input)."""
        if number != 0:
            member = self.members.get(number)
            return member is not None and member.menu_open
        device = self.devices[0]
        return device.look is not None or self.app.settings_open or self.app.event_info_open or self.app.pairing_open

    def menu_blocks(self, pointer):
        """Whether `pointer`'s device has a menu of its own open: then its
        clicks are that menu's, not the game's (controls.Controls.frame)."""
        number = self.device_of_pointer(pointer)
        return number is not None and self.own_menu_open(number)

    def device_pointer(self, device):
        """The pointer this computer's own menus follow: the one it used
        last (None: its mouse)."""
        pads = self.app.controls
        if pads is None:
            return None
        used = [pad for pad in pads.pads if pad.last_active >= 0]
        latest = max(used, key=lambda pad: pad.last_active, default=None)
        return latest if latest is not None and latest.last_active > pads.mouse_active else None

    def started_settings(self, device):
        """Whether one of this computer's controllers pressed Start (its settings)."""
        pads = self.app.controls.pads if self.app.controls is not None else []
        return any(pad.tapped(controls.START) for pad in pads)

    def new_frame(self):
        """Every device's layer starts empty (Engine.draw_world)."""
        for device in self.devices.values():
            device.drawn = device.dim = False

    def layer(self, device):
        """The device's own layer (960x640), emptied when first used in a frame."""
        if device.layer is None:
            device.layer = pg.Surface((controls.WIDTH, controls.HEIGHT), pg.SRCALPHA)
        if not device.drawn:
            device.layer.fill((0, 0, 0, 0))
            device.drawn = True
        return device.layer

    def show_menus(self, window, scale, offset):
        """Every device's own layer: this computer's menus (Engine.own_menus)
        drawn here; on a joined device's player's turn the game's shop and
        cards, sent to it as a picture when it changes (at most every
        HOVER_MS)."""
        if self.state != "game":
            return
        now = pg.time.get_ticks()
        self._menu_due = False
        for device in self.devices.values():
            rect = device.layer.get_bounding_rect() if device.drawn else None
            image = device.layer.subsurface(rect) if rect else None
            if device.id == 0:
                if image is not None:
                    size = (max(1, round(rect.w * scale)), max(1, round(rect.h * scale)))
                    window.blit(image if scale == 1 else pg.transform.smoothscale(image, size),
                                (round(offset[0] + rect.x * scale), round(offset[1] + rect.y * scale)))
                continue
            member = self.members.get(device.id)
            if member is None or not member.viewing:
                continue
            key = (tuple(rect), device.dim, hash(pg.image.tobytes(image, "RGBA"))) if image is not None else \
                (None, device.dim)
            if key == device.sent:
                continue
            if 0 <= now - device.sent_at < HOVER_MS:
                self._menu_due = True
                continue
            message = {"type": "menu", "dim": device.dim}
            if image is not None:
                data = io.BytesIO()
                pg.image.save(image, data, "menu.png")
                message.update(rect=list(rect), png=base64.b64encode(data.getvalue()).decode("ascii"))
            self._send(message, to=device.id)
            device.sent, device.sent_at = key, now

    # --- in the game: the chat (chat.py) ---------------------------------------------

    def say(self, text, member=None):
        """A chat message typed here (`member` None) or on a joined device:
        stamped with who said it (their players' names, the colour of the
        first) and sent to every device in the game."""
        text = chat.clean_text(text)
        if not text or self.state != "game":
            return
        if member is None:
            number, names = 0, [seat.name for seat in self.seats if seat.kind == "host"]
        else:
            number, names = member.id, self._names(member.id)
        player = next((p for p in self.app.players if names and p.name == names[0]), None)
        color = player.color if player is not None else chat.NO_COLOR
        line = [number, " & ".join(names)[:chat.NAME_MAX], [int(c) for c in color], text]
        self.chat.add([line])
        for other in self.members.values():
            if other.viewing:
                self._send({"type": "chat", "lines": [line]}, to=other.id)

    def draw_chat(self, window, scale, offset):
        """This computer's chat, over the game (Engine.present: after the
        game's layer for the devices is taken, so it's the host's alone)."""
        if self.state != "game":
            return
        mouse = None
        if pg.mouse.get_focused():
            x, y = pg.mouse.get_pos()
            mouse = ((x - offset[0]) / scale, (y - offset[1]) / scale)
        self.chat.draw(window, scale, offset, mouse)

    # --- the end ------------------------------------------------------------------

    def close(self, reason="ended"):
        """End it: the devices are told (`reason`: "ended", or "closed" for a
        lobby given up) and the connection closes."""
        self._closing = True
        self.state = "closed"
        if sounds.listener == self._sound:
            sounds.listener = None
        if self.conn is not None and not self.conn.closed:
            self._send({"type": "end", "reason": reason})
            self.conn.close()
        if self._relay is not None:
            self._relay.stop()
            self._relay = None
        if self.app is not None and getattr(self.app, "online", None) is self:
            self.app.online = None
