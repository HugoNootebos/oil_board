"""
The host's side of an online game (net.py has the whole picture, viewer.py
is the side of a device that joined): the lobby's seats, the devices that
joined and their pointers in the game, and the picture of the screen they
get to see.

The host's computer plays the game exactly as a local game (runner.play);
a device that joined is just more pointers for it. Each device's mouse,
and each of its game controllers, is a RemotePointer that Controls and Io
take like a game controller (controls.Pad): it only clicks when its
player's decision is up (`remote_clickers`), and while it is, the host's
own mouse doesn't click (`mouse_allowed`). What the devices see is the
host's screen (`FrameStream`), with everyone's cursor drawn on top by each
device itself, and they hear the host's sounds (sounds.listener). What is
each device's own is left out of that picture and drawn by the device: its
chat (chat.py) and the info panel of the country its pointer is over
(`show_hovers`: the host makes it, the device shows it).

Messages from the host to its devices (through the relay, "to" a member
or all): seats{state, title, seats}, start, cursors{c}, sound{kind, name},
chat{lines, old}, hover{rect, png} (no rect: none), end{reason}, and the
screen as BINARY
(`FrameStream.update_since`). From a device: take/release/name{seat, text}
(its seats), pads{bind}, ready (it shows the game now), ack (an update
arrived), mouse/pad (its input), chat{text} (see chat.py).
"""

import base64
import io
import json
import struct
import threading
import time

import numpy as np
import pygame as pg

import chat
import controls
import net
import relay
import sounds
from lang import t

# Posted (by the network threads) to wake a game loop waiting for events.
NET_EVENT = pg.event.custom_type()

STREAM_SIZE = (1200, 800)  # the picture devices get, the game's 960x640 area scaled
TILE = 80                  # px: the picture is compared and sent in tiles this size
CAPTURE_MS = 50            # at most 20 pictures a second
MAX_RECTS = 12             # more changed pieces than this go as their bounding box
BLUR_SHARE = 0.4           # a change bigger than this share of the picture (the map moving) goes at half size
HALF_MS = 100              # and at most 10 times a second
MAX_IN_FLIGHT = 2          # updates on their way to a device before it has to say it got them
CURSOR_MS = 33             # cursors at most 30 times a second
HOVER_MS = 80              # a device's country info panel at most 12 times a second
MAX_PADS = 8               # game controllers per device
NAME_MAX = 20

MIDDLE = "middle"  # a mouse's middle button (pans the map, like the right one)
BUTTONS = {controls.A, controls.B, controls.START, MIDDLE} | set(controls.ZOOM_BUTTONS)

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
    Controls and Io take it as one more pointer. Its input arrives between
    frames (`feed`) and is handed out a frame at a time (`next_frame`): a
    second click of the same button within one frame waits for the next."""

    def __init__(self, member, number="m"):
        self.member = member
        self.number = number
        self.x, self.y = controls.WIDTH * 0.5, controls.HEIGHT * 0.5
        self.held = set()
        self.taps = []
        self.zoom = []
        self.pan = (0.0, 0.0)
        self.last_active = -1
        self._presses = []
        self._wheel = 0
        self._pan = [0.0, 0.0]

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

    @property
    def zoom_steps(self):
        return list(self.zoom) + [controls.ZOOM_BUTTONS[b] for b in self.taps if b in controls.ZOOM_BUTTONS]

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
        wheel = message.get("wheel", 0)
        if isinstance(wheel, int) and not isinstance(wheel, bool) and wheel:
            self._wheel = min(max(self._wheel + wheel, -20), 20)
            self.last_active = now
        pan = message.get("pan")
        if isinstance(pan, list) and len(pan) == 2 and all(isinstance(v, (int, float)) for v in pan):
            self._pan = [min(max(self._pan[i] + pan[i], -2000.0), 2000.0) for i in range(2)]
            if any(pan):
                self.last_active = now

    def next_frame(self):
        taps, later = [], []
        for button in self._presses:
            # Pressed again right after (two clicks arriving together): Io has
            # to see it up for a frame in between, or it's no new click.
            (later if button in taps or button in self.taps else taps).append(button)
        self.taps, self._presses = taps, later
        self.zoom = [1 if self._wheel > 0 else -1] * abs(self._wheel)
        self._wheel = 0
        self.pan = tuple(self._pan)
        self._pan = [0.0, 0.0]


class FrameStream:
    """The host's screen as the joined devices get it: captured at most every
    CAPTURE_MS, compared tile by tile with the capture before, and sent as
    JPEG pieces of whatever changed since the frame a device already has
    (`update_since`). A slow device so gets fewer, bigger updates rather
    than falling ever further behind. While the map pans or zooms (nearly
    everything changes) the picture goes at half size, a quarter of the
    bytes; once it stands still the device gets it sharp again
    (HostSession.pump)."""

    def __init__(self, size=STREAM_SIZE, tile=TILE):
        self.size = size
        self.tile = tile
        self.cols, self.rows = size[0] // tile, size[1] // tile
        self.seq = 0  # the current frame's number
        self.frame = None
        self.pending = False  # a capture was skipped (too soon after the last): one is still owed
        self._pixels = None
        self._changed_at = np.zeros((self.rows, self.cols), dtype=np.int64)  # frame a tile last changed in
        self._captured_at = None
        self._updates = {}  # base frame -> update to the current frame

    def capture(self, surface, rect=None, now=None):
        """Take the picture of `rect` (the game's area) of `surface`.
        Returns True when it changed."""
        now = pg.time.get_ticks() if now is None else now
        if self._captured_at is not None and 0 <= now - self._captured_at < CAPTURE_MS:
            self.pending = True
            return False
        self._captured_at = now
        self.pending = False
        rect = surface.get_rect() if rect is None else pg.Rect(rect).clip(surface.get_rect())
        if rect.w < 1 or rect.h < 1:
            return False
        part = surface.subsurface(rect)
        frame = part.copy() if rect.size == self.size else pg.transform.smoothscale(part, self.size)
        pixels = np.frombuffer(pg.image.tobytes(frame, "RGB"), dtype=np.uint8).reshape(self.size[1], self.size[0], 3)
        if self._pixels is None:
            changed = np.ones((self.rows, self.cols), dtype=bool)
        else:
            differs = (pixels != self._pixels).any(axis=2)
            changed = differs.reshape(self.rows, self.tile, self.cols, self.tile).any(axis=(1, 3))
        if not changed.any():
            return False
        self.seq += 1
        self._changed_at[changed] = self.seq
        self.frame, self._pixels = frame, pixels
        self._updates = {}
        return True

    def update_since(self, base):
        """(bytes, half) that bring a device that has frame `base` to the
        current one; (None, False) when it already has it. base -1 (nothing
        yet, or sharp again) is the whole picture, sharp; a change of more
        than BLUR_SHARE of it goes as the whole picture at half size (half)."""
        if self.frame is None or base >= self.seq:
            return None, False
        update = self._updates.get(base)
        if update is None:
            rects = self._rects(self._changed_at > base)
            width, height = self.size
            half = base >= 0 and sum(w * h for _, _, w, h in rects) > BLUR_SHARE * width * height
            if half:
                rects = [(0, 0, width, height)]
            pieces, header = [], []
            for x, y, w, h in rects:
                piece = self.frame.subsurface((x, y, w, h))
                if half:
                    piece = pg.transform.smoothscale(piece, (w // 2, h // 2))
                buffer = io.BytesIO()
                pg.image.save(piece, buffer, "update.jpg")
                pieces.append(buffer.getvalue())
                header.append([x, y, w, h, len(pieces[-1])])
            head = json.dumps({"seq": self.seq, "size": list(self.size), "rects": header,
                               "half": half}).encode("utf-8")
            update = self._updates[base] = (struct.pack(">I", len(head)) + head + b"".join(pieces), half)
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
    """Paint an update (FrameStream.update_since) onto `surface`, the
    stream's size. Returns its frame number; ValueError if it's no update."""
    try:
        (length,) = struct.unpack_from(">I", data)
        head = json.loads(data[4:4 + length].decode("utf-8"))
        position = 4 + length
        bounds = surface.get_rect()
        half = bool(head.get("half"))
        for x, y, w, h, size in head["rects"]:
            image = pg.image.load(io.BytesIO(data[position:position + size]), "update.jpg")
            position += size
            if half and image.get_size() == (w // 2, h // 2):
                image = pg.transform.smoothscale(image, (w, h))
            if bounds.contains(pg.Rect(x, y, w, h)) and image.get_size() == (w, h):
                surface.blit(image, (x, y))
        return int(head["seq"])
    except (struct.error, ValueError, KeyError, TypeError, pg.error) as error:
        raise ValueError("not an update") from error


class Member:
    """A device that joined the host's game (its relay member number)."""

    def __init__(self, number, device):
        self.id = number
        self.device = device
        self.pointers = {"m": RemotePointer(number, "m")}
        self.pad_names = {}    # its controllers: number -> player name
        self.viewing = False   # in the game (it said "ready"), not in the lobby
        self.base = -1         # the frame it has (or will have, once what's on its way arrives)
        self.in_flight = 0
        self.blurred = False   # it got a half-size picture: it gets it sharp once things stand still
        self.sent_at = -HALF_MS
        self.hover = None      # the country info panel it has (show_hovers)
        self.hover_at = -HOVER_MS


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
        self.stream = FrameStream()
        self._relay = None
        self._closing = False
        self._cursors = None
        self._cursors_at = 0
        self._cursor_due = False
        self._picture_due = False
        self._hover_due = False
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
                    member.hover = None
                    self._cursors = None  # it needs them all
                    if self.chat.lines:
                        self._send({"type": "chat", "lines": self.chat.lines, "old": True}, to=member.id)
                elif kind == "pads":
                    self._pads(member, message.get("bind"))
                elif kind == "chat":
                    if member.viewing:
                        self.say(message.get("text", ""), member)
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
        for seat in self.seats:
            if device and seat.kind == "open" and seat.device == device:
                seat.kind, seat.member = "remote", number  # back after dropping out
        return True

    def _member_left(self, number):
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
                pointer = member.pointers[number] = RemotePointer(member.id, number)
        pointer.feed(message, pg.time.get_ticks())
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

    @property
    def viewers(self):
        return any(member.viewing for member in self.members.values())

    @property
    def busy(self):
        """Something still has to go out: keep drawing frames."""
        return self.stream.pending or self._cursor_due or self._picture_due or self._hover_due

    def capture(self, window, rect):
        """Engine.present: the game's area of the window, before any cursor."""
        if self.state == "game" and self.viewers:
            self.stream.capture(window, rect)
        else:
            self.stream.pending = False

    def pump(self):
        """Send the devices what's new: the picture (each at its own pace)
        and the cursors. Call after every frame."""
        conn = self.conn
        if conn is None or conn.closed or self.state != "game":
            return
        now = pg.time.get_ticks()
        self._picture_due = False
        for member in self.members.values():
            if not member.viewing or member.in_flight >= MAX_IN_FLIGHT:
                continue
            update, half = self.stream.update_since(member.base)
            if half and now - member.sent_at < HALF_MS:
                self._picture_due = True  # moving: the next picture a little later
                continue
            if half:
                member.blurred = True
            elif member.blurred and not self.stream.pending:
                update, _ = self.stream.update_since(-1)  # standing still: all of it sharp again
                member.blurred = False
            if update is not None:
                conn.send_binary(update, to=member.id)
                member.base = self.stream.seq
                member.in_flight += 1
                member.sent_at = now
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
        controller's number], in the game's 960x640."""
        app, pads, view = self.app, self.app.controls, self.app.view
        entries = []
        x, y = pg.mouse.get_pos()
        x, y = round((x - view.ox) / view.scale), round((y - view.oy) / view.scale)
        if pg.mouse.get_focused() and 0 <= x < controls.WIDTH and 0 <= y < controls.HEIGHT:
            names = [seat.name for seat in self.seats if seat.kind == "host"]
            color, faded = self._look(names, pads is None or pads.mouse_ok)
            entries.append([x, y] + list(color) + [faded, 0, "m"])
        if pads is not None:
            for pad, (color, faded) in app._pad_looks().items():
                entries.append([round(pad.x), round(pad.y)] + [int(c) for c in color] + [bool(faded), 0, pad.number])
        clickers = pads.clickers if pads is not None else []
        for pointer in self.pointers():
            color, faded = self._look(self.names_of(pointer), pointer in clickers)
            entries.append([round(pointer.x), round(pointer.y)] + list(color) + [faded, pointer.member, pointer.number])
        return entries

    def draw_cursors(self, surface, scale, offset):
        """The devices' cursors on the host's own screen (Engine.present)."""
        clickers = self.app.controls.clickers if self.app.controls is not None else []
        for pointer in self.pointers():
            color, faded = self._look(self.names_of(pointer), pointer in clickers)
            sprite, margin = controls.cursor_sprite(color, faded, scale)
            surface.blit(sprite, (round(offset[0] + pointer.x * scale) - margin,
                                  round(offset[1] + pointer.y * scale) - margin))

    def _sound(self, kind, name):
        """sounds.listener: the devices hear what the host hears."""
        if self.viewers:
            self._send({"type": "sound", "kind": kind, "name": name})

    # --- in the game: each device's country info panel ----------------------------------

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

    def _pointers_of(self, member):
        """A joined device's pointers that it has used, as `_pointers_here`."""
        names = self._names(member.id)
        own = set(member.pad_names.values()) & set(names)
        entries = []
        for pointer in member.pointers.values():
            if pointer.last_active < 0:
                continue
            if pointer.number == "m":
                stands_for = [name for name in names if name not in own] or names
            else:
                stands_for = self.names_of(pointer)
            entries.append(((pointer.x, pointer.y), stands_for, pointer.last_active))
        return entries

    def _hovered(self, entries, chat_here=None):
        """The country a device's info panel shows: of its pointers over a
        country, the one whose player decides soonest; between equals the
        one used last."""
        best = None
        for position, names, used in entries:
            name = self.app.device_country_at(position, chat_here)
            if name is not None:
                key = (self._turn_rank(names), -used)
                if best is None or key < best[0]:
                    best = (key, name)
        return best[1] if best is not None else None

    def show_hovers(self, window, scale, offset):
        """Every device's country info panel, for the country its own pointer
        is over (Engine.present, after the picture for the devices is
        taken): drawn here for this computer, sent as a picture to each
        device that joined (when it changes, at most every HOVER_MS)."""
        if self.state != "game":
            return
        panels = {}

        def panel(name):
            if name not in panels:
                image, rect = self.app.country_panel(name)
                panels[name] = [image, rect, (name, tuple(rect), hash(pg.image.tobytes(image, "RGBA"))), None]
            return panels[name]

        name = self._hovered(self._pointers_here(), self.chat)
        if name is not None:
            image, rect = panel(name)[:2]
            size = (max(1, round(rect.w * scale)), max(1, round(rect.h * scale)))
            window.blit(image if scale == 1 else pg.transform.smoothscale(image, size),
                        (round(offset[0] + rect.x * scale), round(offset[1] + rect.y * scale)))
        now = pg.time.get_ticks()
        self._hover_due = False
        for member in self.members.values():
            if not member.viewing:
                continue
            name = self._hovered(self._pointers_of(member))
            shown = panel(name) if name is not None else None
            key = shown[2] if shown is not None else None
            if key == member.hover:
                continue
            if 0 <= now - member.hover_at < HOVER_MS:
                self._hover_due = True  # (busy: a frame more to send it)
                continue
            message = {"type": "hover"}
            if shown is not None:
                if shown[3] is None:
                    data = io.BytesIO()
                    pg.image.save(shown[0], data, "panel.png")
                    shown[3] = base64.b64encode(data.getvalue()).decode("ascii")
                message.update(rect=list(shown[1]), png=shown[3])
            self._send(message, to=member.id)
            member.hover, member.hover_at = key, now

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
        picture for the devices is taken, so it's the host's alone)."""
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
