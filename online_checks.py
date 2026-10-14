"""
Automated checks for online play (net.py, relay.py, online.py, viewer.py,
lobby.py, chat.py): the relay's routing, finding relays, the screen stream,
the lobby's seats, who may click in the game, the chat, each device's
country info panel, and a whole hosted game with a device joining it
through a real (local) relay. PASS/FAIL per check.

    python3 online_checks.py [name filter]

Headless; uses ports from 47900 up and the local network's beacons, and a
temporary folder for settings and saves (yours are never touched). Exit
code 1 if anything failed.
"""

import json
import os
import socket
import sys
import tempfile
import time
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["OIL_SAVES_DIR"] = tempfile.mkdtemp(prefix="oil_online_checks_")

import numpy as np  # noqa: E402
import pygame as pg  # noqa: E402

import chat  # noqa: E402
import controls  # noqa: E402
import lobby  # noqa: E402
import models  # noqa: E402
import net  # noqa: E402
import online  # noqa: E402
import relay  # noqa: E402
import sounds  # noqa: E402
import viewer  # noqa: E402
from engine import Engine  # noqa: E402
from models import Position  # noqa: E402

PORT0 = 47900

results = []  # (test, description, ok, detail)
_current_test = [""]


def check(description, ok, detail=""):
    results.append((_current_test[0], description, bool(ok), detail))


class Inbox:
    """A connection's messages, kept until a check looks for them."""

    def __init__(self, conn):
        self.conn = conn
        self.messages = []

    def wait(self, match, timeout=3.0):
        """The first message `match` accepts (a type name, or a function),
        taken out of the inbox; None if none came within `timeout`."""
        test = match if callable(match) else (lambda m: isinstance(m, dict) and m.get("type") == match)
        deadline = time.time() + timeout
        while True:
            self.messages += self.conn.poll()
            for k, message in enumerate(self.messages):
                if test(message):
                    return self.messages.pop(k)
            if time.time() > deadline:
                return None
            time.sleep(0.02)


# --- the relay ------------------------------------------------------------------

def test_relay():
    r = relay.start_embedded(first_port=PORT0)
    address = ("127.0.0.1", r.port)
    host = Inbox(net.connect(address))
    check("connecting says which relay it is", host.conn.relay == r.id and host.conn.kind == "lan")
    host.conn.send({"type": "open", "info": {"title": "Ann", "proto": net.PROTOCOL, "seats": 3, "taken": 1,
                                             "free": 2, "state": "lobby", "junk": "x" * 100}})
    opened = host.wait("opened")
    check("a host gets a room", opened is not None and opened.get("room"))

    a = Inbox(net.connect(address))
    a.conn.send({"type": "list"})
    rooms = a.wait("rooms")
    info = rooms["rooms"][0] if rooms and rooms["rooms"] else {}
    check("the list shows the room, unknown fields left out",
          info.get("room") == opened["room"] and info.get("title") == "Ann" and "junk" not in info, info)

    a.conn.send({"type": "join", "room": opened["room"]})
    joined = a.wait("joined")
    member = host.wait("member")
    check("joining gives a member number, and tells the host (with the device id)",
          joined and member and joined["member"] == member["member"] and member["device"] == net.device_id())
    number = joined["member"]

    a.conn.send({"type": "take", "seat": 1})
    got = host.wait("take")
    check("a member's message reaches the host, from it", got and got.get("from") == number and got.get("seat") == 1)
    host.conn.send({"type": "seats", "to": number, "x": 1})
    got = a.wait("seats")
    check("the host's message reaches that member, without 'to'", got == {"type": "seats", "x": 1}, got)
    host.conn.send_binary(b"picture", to=number)
    got = a.wait(lambda m: isinstance(m, bytes))
    check("binary from the host reaches the member", got == b"picture", got)
    a.conn.send_binary(b"back")
    got = host.wait(lambda m: isinstance(m, bytes))
    check("binary from a member reaches the host with its number in front",
          got == relay.MEMBER.pack(number) + b"back", got)

    b = Inbox(net.connect(address))
    b.conn.send({"type": "join", "room": opened["room"]})
    second = b.wait("joined")
    host.wait("member")
    host.conn.send({"type": "sound", "to": 0, "name": "click"})
    check("to 0 is to every member", a.wait("sound") is not None and b.wait("sound") is not None)

    host.conn.send({"type": "kick", "member": second["member"]})
    check("a kicked member is told", b.wait("kicked") is not None)
    left = host.wait("left")
    check("the host hears a kicked member left", left and left["member"] == second["member"])

    a.conn.send({"type": "leave"})
    left = host.wait("left")
    check("leaving tells the host", left and left["member"] == number)

    c = Inbox(net.connect(address))
    c.conn.send({"type": "join", "room": opened["room"]})
    c.wait("joined")
    host.wait("member")
    host.conn.close()
    check("when the host goes, its members hear the room closed", c.wait("closed") is not None)
    c.conn.send({"type": "list"})
    rooms = c.wait("rooms")
    check("and the room is off the list", rooms is not None and rooms["rooms"] == [], rooms)

    sock = socket.create_connection(address, timeout=3)
    sock.sendall(relay.pack_json({"type": "hello", "proto": relay.RELAY_PROTOCOL + 1, "device": "x"}))
    kind, payload = net._read_message(sock)
    sock.close()
    check("another relay protocol is refused", json.loads(payload.decode()).get("reason") == "version")
    try:
        net.connect(("127.0.0.1", 1), timeout=1)
        check("a wrong address raises ConnectError", False)
    except net.ConnectError:
        check("a wrong address raises ConnectError", True)
    for conn in (b.conn, c.conn, a.conn):
        conn.close()
    r.stop(0)


# --- finding relays ------------------------------------------------------------

def _lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("10.255.255.255", 1))  # picks a route, sends nothing
        ip = sock.getsockname()[0]
        sock.close()
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def test_discovery():
    check("addresses are parsed", net.parse_address("example.org:1234") == ("example.org", 1234)
          and net.parse_address("10.0.0.2") == ("10.0.0.2", relay.PORT)
          and net.parse_address("x:y") is None and net.parse_address("") is None)
    r = relay.start_embedded(first_port=PORT0 + 10)
    browser = net.RoomBrowser()
    deadline = time.time() + 6
    while time.time() < deadline and not any(f.conn.relay == r.id and f.route == "local" for f in browser.found()):
        time.sleep(0.1)  # (its broadcast may come in first, from this computer's network address)
    found = [f for f in browser.found() if f.conn.relay == r.id]
    check("a relay on this computer is found by its beacon", len(found) == 1 and found[0].route == "local",
          [(f.route, f.address) for f in found])
    ip = _lan_ip()
    if ip is not None:
        browser.add_address((ip, r.port))
        time.sleep(2.5)
        found = [f for f in browser.found() if f.conn.relay == r.id]
        check("the same relay at another address is kept once, the nearest way",
              len(found) == 1 and found[0].route == "local", [(f.route, f.address) for f in found])
    browser.close()

    main = relay.start_embedded(first_port=PORT0 + 20, kind="main")
    conn = net.find_main_relay()
    check("a host finds a main relay", conn is not None and conn.kind == "main")
    if conn is not None:
        conn.close()
    r.stop(0)
    main.stop(0)


# --- the screen stream ------------------------------------------------------------

def _scene(surface, shift=0):
    surface.fill((0, 150, 235))
    for i in range(12):
        pg.draw.polygon(surface, (40 + i * 15, 155, 60), [(i * 80 + shift, 80), (i * 80 + 120, 300), (i * 80 + 30, 600)])
    pg.draw.rect(surface, (250, 225, 130), (300, 200, 360, 200))


def _error(a, b):
    pa = np.frombuffer(pg.image.tobytes(a, "RGB"), np.uint8).astype(int)
    pb = np.frombuffer(pg.image.tobytes(b, "RGB"), np.uint8).astype(int)
    return float(np.abs(pa - pb).mean())


def _area(update):
    (length,) = __import__("struct").unpack_from(">I", update)
    head = json.loads(update[4:4 + length].decode())
    return sum(w * h for _, _, w, h, _ in head["rects"]), len(head["rects"])


def test_stream():
    window = pg.Surface((960, 640))
    _scene(window)
    stream = online.FrameStream()
    check("the first capture is a change", stream.capture(window, now=1000) and stream.seq == 1)
    device = pg.Surface(online.STREAM_SIZE)
    update, half = stream.update_since(-1)
    check("a device's first update is the whole picture, sharp",
          _area(update)[0] == online.STREAM_SIZE[0] * online.STREAM_SIZE[1] and not half)
    check("it says its frame number", online.apply_update(device, update) == 1)
    error = _error(device, stream.frame)
    check("the device's picture is the host's (JPEG close)", error < 3, error)
    check("the same update is made once and shared", stream.update_since(-1)[0] is update)

    pg.draw.rect(window, (255, 0, 0), (100, 100, 20, 20))
    check("too soon after the last capture: owed", not stream.capture(window, now=1020) and stream.pending)
    check("then taken", stream.capture(window, now=1060) and stream.seq == 2 and not stream.pending)
    area, rects = _area(stream.update_since(1)[0])
    check("a small change sends only its tiles", area <= 4 * online.TILE ** 2 and rects <= 2, (area, rects))
    check("nothing new: nothing sent", stream.update_since(2) == (None, False))
    check("an unchanged picture is no new frame", not stream.capture(window, now=1200) and stream.seq == 2)

    pg.draw.rect(window, (0, 255, 0), (800, 500, 30, 30))
    stream.capture(window, now=1300)
    area_last, _ = _area(stream.update_since(2)[0])
    area_both, rects_both = _area(stream.update_since(1)[0])
    check("a device behind gets everything since its frame in one update",
          area_both > area_last and rects_both >= 2, (area_both, area_last))
    online.apply_update(device, stream.update_since(1)[0])
    check("and then has the host's picture", _error(device, stream.frame) < 3)

    for x in range(0, 960, 128):
        for y in range(0, 640, 128):
            pg.draw.rect(window, (x % 255, y % 255, 90), (x, y, 10, 10))
    stream.capture(window, now=1400)
    check("many scattered pieces go as one box", _area(stream.update_since(stream.seq - 1)[0])[1] == 1)

    _scene(window, shift=37)  # the map moved: nearly everything changed
    stream.capture(window, now=1500)
    update, half = stream.update_since(stream.seq - 1)
    online.apply_update(device, update)
    check("a big change (the map moving) goes at half size", half and len(update) < 60000, len(update))
    error = _error(device, stream.frame)
    check("which the device shows, a bit soft", 1 < error < 12, error)
    update, half = stream.update_since(-1)
    online.apply_update(device, update)
    check("and sharp again from frame -1", not half and _error(device, stream.frame) < 3)
    try:
        online.apply_update(device, b"\x00\x00\x00\x05junk!")
        check("garbage is no update", False)
    except ValueError:
        check("garbage is no update", True)

    big = pg.Surface((1600, 1000))
    _scene(big)
    other = online.FrameStream()
    other.capture(big, rect=(10, 20, 1500, 1000), now=0)
    check("any size of window is scaled to the stream's",
          other.frame.get_size() == online.STREAM_SIZE)


# --- the lobby's seats -----------------------------------------------------------

def _session(seats):
    session = online.HostSession(seats, connect=False)
    session.status = "online"
    return session


def test_seats():
    seats = lobby._new_seats(4)
    check("a new game: the first seat here, the rest open", [s.kind for s in seats] == ["host", "open", "open", "open"])
    s = _session(seats)
    check("open seats keep it from starting", s.start_problem() == online.t("Every seat needs a player"))
    s.cycle_kind(1)
    s.cycle_kind(2)
    s.cycle_kind(2)
    check("the host cycles open -> here -> bot", [x.kind for x in seats[:3]] == ["host", "host", "bot"])
    check("names left empty become Player N / Bot N",
          s.seat_name(1) == online.t("Player {}").format(2) and s.seat_name(2) == "Bot 3")
    s.cycle_kind(1)
    s.cycle_kind(1)
    check("... -> open", seats[1].kind == "open")

    s._member_joined({"member": 1, "device": "dev-a"})
    s._member_joined({"member": 2, "device": "dev-b"})
    one, two = s.members[1], s.members[2]
    check("a device takes an open seat", s._seat_request(one, "take", {"seat": 1}) and seats[1].kind == "remote"
          and seats[1].member == 1 and seats[1].device == "dev-a")
    check("not one that's taken", not s._seat_request(two, "take", {"seat": 1}) and seats[1].member == 1)
    check("not a bot's", not s._seat_request(two, "take", {"seat": 2}))
    check("nor one that doesn't exist", not s._seat_request(two, "take", {"seat": 9}))
    s._seat_request(one, "name", {"seat": 1, "text": "Bea\x00\n" + "x" * 40})
    check("it names its seat: printable, at most 20", seats[1].name == ("Bea" + "x" * 17), seats[1].name)
    check("nobody else may", not s._seat_request(two, "name", {"seat": 1, "text": "Hack"}))
    s.set_name(0, "Ann")
    s._seat_request(two, "take", {"seat": 3})
    s._seat_request(two, "name", {"seat": 3, "text": "ann "})
    check("the same name twice keeps it from starting",
          s.start_problem() == online.t("Two players have the same name"))
    s._seat_request(two, "name", {"seat": 3, "text": "Cas"})
    check("and then it can start", s.start_problem() is None, s.start_problem())
    info = s.room_info()
    check("the listing: the host's name, all taken", info["title"] == "Ann" and info["free"] == 0 and info["taken"] == 4)
    s._seat_request(two, "release", {"seat": 3})
    check("a released seat is open again, its name gone", seats[3].kind == "open" and seats[3].name == ""
          and seats[3].device is None)

    s._member_left(1)
    check("a device that drops out leaves its seat open (and remembered)",
          seats[1].kind == "open" and seats[1].member is None and seats[1].device == "dev-a")
    s._member_joined({"member": 3, "device": "dev-a"})
    check("coming back, it gets it again", seats[1].kind == "remote" and seats[1].member == 3)
    s.cycle_kind(1)
    check("the host can take a joined device's seat off it", seats[1].kind == "open" and seats[1].member is None)

    path = os.path.join(os.environ["OIL_SAVES_DIR"], "online_seats.json")
    with open(path, "w") as f:
        json.dump({"players": [{"name": "Hugo", "color": [60, 110, 230], "is_bot": False},
                               {"name": "Bot 2", "color": [40, 160, 70], "is_bot": True},
                               {"name": "Tètè", "color": [210, 40, 40], "is_bot": False}]}, f)
    saved = lobby._saved_seats(path)
    check("a saved game: its names, its bots, its first human here",
          [(x.name, x.kind, x.fixed) for x in saved] == [("Hugo", "host", True), ("Bot 2", "bot", True),
                                                         ("Tètè", "open", True)])
    s = _session(saved)
    s.cycle_kind(1)
    s.cycle_kind(2)
    s.set_name(0, "Other")
    check("its bots stay bots, its humans human, its names fixed",
          [x.kind for x in saved] == ["host", "bot", "host"] and saved[0].name == "Hugo")
    neven = lobby._new_seats("default")
    check("De 3 Neven: their names, fixed", [x.name for x in neven] == ["Hugo", "Joeri", "Tètè"]
          and all(x.fixed for x in neven))


# --- who may click ------------------------------------------------------------------

def _frame(app):
    """One frame of runner.play, without the window."""
    if app.online is not None:
        app.online.update()
    app.io_handle()
    app.draw_world()
    app.draw_gui()
    app.update_turn()
    app.control_card_menu()
    app.present()
    if app.online is not None:
        app.online.pump()


def _game(names=("A", "B", "C")):
    app = Engine(mode="count", player_count=len(names), player_names=list(names))
    app.controls = controls.get()
    return app


def test_clicks():
    app = _game()
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    s._member_joined({"member": 1, "device": "dev"})
    for i in (1, 2):
        s._seat_request(s.members[1], "take", {"seat": i})
    s.members[1].viewing = True
    s.start_game(app)
    pads = app.controls
    mouse = s.members[1].pointers["m"]

    app.turn = 0
    _frame(app)
    check("the host's player decides: the host's mouse clicks, the device doesn't",
          pads.mouse_ok and mouse not in pads.clickers and app.io.source is None)

    app.turn = 1
    _frame(app)
    check("a joined player decides: their device clicks, the host's mouse doesn't",
          not pads.mouse_ok and mouse in pads.clickers and app.io.source is mouse)
    def own():
        return s.devices[1].fields
    mouse.feed({"x": 50, "y": 50, "held": [controls.A], "down": [controls.A]}, pg.time.get_ticks())
    _frame(app)
    check("their click on settings opens their own settings, not the host's",
          own()["settings_open"] and not app.settings_open)
    _frame(app)
    check("while it's open their clicks are its, not the game's", mouse not in pads.clickers)
    for x, y in ((300, 165), (600, 165), (220, 227)):  # Exit Game, Save As, the first toggle
        mouse.feed({"x": x, "y": y, "held": [], "down": []}, pg.time.get_ticks())
        _frame(app)
        mouse.feed({"x": x, "y": y, "held": [controls.A], "down": [controls.A]}, pg.time.get_ticks())
        _frame(app)
        mouse.feed({"x": x, "y": y, "held": [], "down": []}, pg.time.get_ticks())
        _frame(app)
    check("a joined device can't exit, save or change the settings",
          not app.pending_quit and not own()["save_as_open"] and not app.settings["assets"] and own()["settings_open"])
    mouse.feed({"x": 5, "y": 630, "held": [], "down": [controls.A]}, pg.time.get_ticks())
    _frame(app)
    check("a click and release within one frame still clicks (closing the menu)", not own()["settings_open"])
    _frame(app)
    mouse.feed({"x": 50, "y": 50, "held": [], "down": [controls.A, controls.A]}, pg.time.get_ticks())
    _frame(app)
    opened = own()["settings_open"]
    _frame(app)
    _frame(app)
    check("two clicks arriving together are two clicks (opened, then closed)", opened and not own()["settings_open"])
    _frame(app)
    check("and then the game gets their clicks again", mouse in pads.clickers)

    app.turn = 2
    _frame(app)
    check("one device plays for each of its players", mouse in pads.clickers and not pads.mouse_ok)

    s._input(s.members[1], {"type": "pad", "n": 4, "x": 100, "y": 100, "held": []})
    s._pads(s.members[1], {"4": "C"})
    pad = s.members[1].pointers[4]
    app.turn = 1
    _frame(app)
    check("a device's controller clicks only for its own player (not B)", pad not in pads.clickers)
    app.turn = 2
    _frame(app)
    check("(but for C)", pad in pads.clickers)

    app.players[1].is_bot = True
    app.turn = 1
    _frame(app)
    check("a bot's turn: everyone's pointers may click", pads.mouse_ok and mouse in pads.clickers)
    app.players[1].is_bot = False

    s._member_left(1)
    app.turn = 1
    _frame(app)
    check("a device that dropped out: the host's mouse plays its players", pads.mouse_ok and not pads.clickers
          and app.io.source is None and s.pointers() == [])

    for player in app.players[1:]:
        player.eliminated = True
    app.turn_manager._draw_dialog = lambda *args, **kwargs: True
    app.turn_manager._show_dialogs()
    check("online, Quit after the game is won goes back to the host's menu (not closing it)", app.pending_quit)
    s.close()
    check("closing ends the session", app.online is None and sounds.listener is None)


def test_names():
    app = _game()
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    s._member_joined({"member": 1, "device": "dev"})
    s._member_joined({"member": 2, "device": "dev2"})
    for member, seat in ((1, 1), (2, 2)):
        s._seat_request(s.members[member], "take", {"seat": seat})
        s.members[member].viewing = True
    s.start_game(app)
    pads, view = app.controls, app.view
    mouse = s.members[1].pointers["m"]
    said = []
    play_country, get_pos = sounds.play_country, pg.mouse.get_pos
    sounds.play_country = said.append
    app.turn = 0
    for _ in range(2):
        _frame(app)  # the buttons drawn, so country_at knows what covers the map

    def spot(country):
        x = (country.mass_center.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH
        y = (country.mass_center.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT
        return x, y

    name = next(n for n, c in app.countries.items() if 100 < spot(c)[0] < 860 and 100 < spot(c)[1] < 540
                and app.io.country_at(view, app.countries.values(), Position(*spot(c))) == n)
    x, y = spot(app.countries[name])
    pg.mouse.get_pos = lambda: (x * view.scale + view.ox, y * view.scale + view.oy)

    def click(device=False, host=False):
        """One frame with a click of the device's mouse and/or the host's
        (runner.play's order); what it said."""
        del said[:]
        mouse.feed({"x": x, "y": y, "held": [controls.A] if device else [], "down": [controls.A] if device else []},
                   pg.time.get_ticks())
        pads.handle_events([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(0, 0))] if host else [])
        s.update()
        app.io_handle()
        app.bystander_clicks()
        mouse.feed({"x": x, "y": y, "held": [], "down": []}, pg.time.get_ticks())
        pads.handle_events([])
        s.update()
        app.io_handle()
        return list(said)

    try:
        check("the host's player's turn: a joined player's mouse on a country says its name",
              click(device=True) == [name])
        check("(the host's own mouse doesn't: it plays)", click(host=True) == [])
        app.turn = 1
        _frame(app)
        check("a joined player's turn: the host's mouse on a country says its name",
              not pads.mouse_ok and click(host=True) == [name])
        check("(the joined player's own mouse doesn't: it plays)", click(device=True) == [])
        app.turn = 2
        _frame(app)
        check("another device's player's turn: both say it",
              click(device=True) == [name] and click(host=True) == [name])
        seats[0].kind = "open"  # nobody plays on the host's computer
        app.turn = 1
        _frame(app)
        check("no player on the host's computer: its mouse says nothing", click(host=True) == [])
    finally:
        sounds.play_country, pg.mouse.get_pos = play_country, get_pos
        s.close()


# --- a whole hosted game, through a local relay -----------------------------------

class FakeConn:
    """A viewer's connection without a network: what it sent, what comes in."""

    def __init__(self, incoming=()):
        self.sent = []
        self.incoming = list(incoming)
        self.closed = False
        self.wake = None

    def send(self, message):
        self.sent.append(message)

    def poll(self):
        incoming, self.incoming = self.incoming, []
        return incoming

    def close(self):
        self.closed = True


def _window_pos(view, x, y):
    """Logical (x, y) in the host's window."""
    return int(view.ox + x * view.scale), int(view.oy + y * view.scale)


def _event(kind, **attributes):
    return pg.event.Event(kind, **attributes)


def _key(key):
    return _event(pg.KEYDOWN, key=key, mod=0, unicode="")


def test_chat():
    spot = (chat.BUTTON.x + 4, chat.BUTTON.y + 4)  # on the button, beside the sprite
    app = _game()
    _frame(app)
    check("a local game has no chat button",
          tuple(pg.display.get_surface().get_at(_window_pos(app.view, *spot)))[:3] != chat.COLOR)

    app = _game()
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    s._member_joined({"member": 1, "device": "dev"})
    s._member_joined({"member": 2, "device": "watcher"})
    for i in (1, 2):
        s._seat_request(s.members[1], "take", {"seat": i})
    s.members[1].viewing = s.members[2].viewing = True
    s.start_game(app)
    app.turn = 0
    _frame(app)
    view = app.view
    check("online the host has the chat button (under the settings button)",
          tuple(pg.display.get_surface().get_at(_window_pos(view, *spot)))[:3] == chat.COLOR)
    scale = online.STREAM_SIZE[0] / controls.WIDTH
    streamed = tuple(s.stream.frame.get_at((int(spot[0] * scale), int(spot[1] * scale))))[:3]
    check("but the devices don't see it in the picture (they have their own)", streamed != chat.COLOR, streamed)

    def to_logical(pos):
        return (pos[0] - view.ox) / view.scale, (pos[1] - view.oy) / view.scale

    button = _window_pos(view, chat.BUTTON.centerx, chat.BUTTON.centery)
    real_pos, real_pressed, real_focused = pg.mouse.get_pos, pg.mouse.get_pressed, pg.mouse.get_focused
    try:
        pg.mouse.get_pos = lambda: button
        pg.mouse.get_focused = lambda: True
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, False)
        app.io_handle()
        pg.mouse.get_pressed = lambda num_buttons=3: (True, False, False)
        app.io_handle()
        check("the host's mouse pressing the chat button: the game doesn't get the click",
              not app.io.left_pressed and app.io.hover_country is None
              and app.io.top_button == chat.Chat(None).shapes()[0])
    finally:
        pg.mouse.get_pos, pg.mouse.get_pressed, pg.mouse.get_focused = real_pos, real_pressed, real_focused

    took = s.chat.handle(_event(pg.MOUSEBUTTONDOWN, button=1, pos=button), to_logical)
    check("a click on the button opens the chat", took and s.chat.open)
    took = [s.chat.handle(e, to_logical) for e in (_event(pg.TEXTINPUT, text="hello  world"),
                                                    _key(pg.K_F5), _key(pg.K_RETURN))]
    line = s.chat.lines[-1] if s.chat.lines else None
    check("while it's open every key is the chat's; Enter sends", all(took) and s.chat.draft == "")
    check("the host's message goes under its player's name and colour",
          line == [0, "A", list(app.players[0].color), "hello world"], line)
    check("Esc closes the chat", s.chat.handle(_key(pg.K_ESCAPE), to_logical) and not s.chat.open)
    check("closed, the keys are the game's again",
          not s.chat.handle(_key(pg.K_ESCAPE), to_logical)
          and not s.chat.handle(_event(pg.TEXTINPUT, text="x"), to_logical))
    s.say("hi", s.members[1])
    s.say("watching", s.members[2])
    check("a device's message: its players' names, the first one's colour",
          s.chat.lines[-2] == [1, "B & C", list(app.players[1].color), "hi"], s.chat.lines[-2])
    check("someone without a player is a spectator", s.chat.name(s.chat.lines[-1]) == online.t("Spectator"))
    check("messages that came in while it was closed are counted", s.chat.unread == 2)
    _frame(app)
    s.close()

    conn = FakeConn([{"type": "chat", "lines": [[0, "A", [60, 110, 230], "earlier"]], "old": True},
                     {"type": "chat", "lines": [[1, "B", [40, 160, 70], "mine"], "junk", [0, "A", [1, 2], "bad"]]},
                     {"type": "chat", "lines": [[0, "A", [60, 110, 230], "new"]]}])
    v = viewer.Viewer(conn, 1, [])
    v._receive()
    check("a device takes in the messages (the bad ones left out)",
          [line[3] for line in v.chat.lines] == ["earlier", "mine", "new"])
    check("only new ones from others count as unread (not the history, not its own)", v.chat.unread == 1)
    at = (round(v.area.x + chat.BUTTON.centerx * v.scale), round(v.area.y + chat.BUTTON.centery * v.scale))
    v._events([_event(pg.MOUSEBUTTONDOWN, button=1, pos=at)])
    check("a device's click on its chat button opens its chat, and isn't sent to the host",
          v.chat.open and v._down == [] and v._swallowed == {controls.A} and v.chat.unread == 0)
    v._events([_event(pg.MOUSEBUTTONUP, button=1, pos=at), _event(pg.TEXTINPUT, text="gg"), _key(pg.K_RETURN)])
    check("its message goes to the host", {"type": "chat", "text": "gg"} in conn.sent and not v._swallowed)
    v._events([_key(pg.K_ESCAPE)])
    check("Esc closes its chat first, then opens its menu", not v.chat.open and not v.menu_open)
    v._events([_key(pg.K_ESCAPE)])
    check("(its menu)", v.menu_open)
    v.menu_open = False
    v._events([_event(pg.MOUSEBUTTONDOWN, button=1, pos=(at[0] + 400, at[1] + 200))])
    check("a click elsewhere is the host's", v._down == [controls.A])
    v._draw((500, 300))


def _spots(app, count):
    """`count` countries in view, each with a point (logical) that is on it."""
    view, found = app.view, []
    for country in app.countries.values():
        x = (country.mass_center.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH
        y = (country.mass_center.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT
        if 250 < x < 650 and 150 < y < 450 and app.device_country_at((x, y)) == country.name:
            found.append((country.name, (x, y)))
    return found[:count]


def test_hover():
    app = _game()
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    sent = []
    s._send = lambda message, to=0: sent.append((to, message))
    s._member_joined({"member": 1, "device": "dev"})
    s._member_joined({"member": 2, "device": "watcher"})
    for i in (1, 2):
        s._seat_request(s.members[1], "take", {"seat": i})
    s.members[1].viewing = s.members[2].viewing = True
    s.start_game(app)
    app.turn = 1
    _frame(app)
    (x_name, x_at), (y_name, y_at), (z_name, z_at) = _spots(app, 3)
    one, watcher = s.members[1], s.members[2]
    now = pg.time.get_ticks()
    one.pointers["m"].feed({"x": x_at[0], "y": x_at[1], "held": [], "down": []}, now)
    s._input(one, {"type": "pad", "n": 4, "x": y_at[0], "y": y_at[1], "held": []})
    s._pads(one, {"4": "C"})
    watcher.pointers["m"].feed({"x": z_at[0], "y": z_at[1], "held": [], "down": []}, now)

    def shown(member):
        time.sleep(online.HOVER_MS / 1000 + 0.02)  # (a device gets at most one every HOVER_MS)
        _frame(app)
        return member.hover[0] if member.hover is not None else None

    check("B's turn: the device shows what B's pointer (its mouse) is over", shown(one) == x_name)
    last = [message for to, message in sent if to == 1 and message["type"] == "hover"][-1]
    check("sent as a picture with its place", isinstance(last.get("png"), str) and len(last.get("rect", [])) == 4)
    app.turn = 2
    check("C's turn: what C's controller is over", shown(one) == y_name)
    app.turn = 0
    check("someone else's turn: the pointer of whoever of them is next (B)", shown(one) == x_name)
    check("a device watching sees what its own mouse is over", shown(watcher) == z_name)
    one.pointers["m"].feed({"x": chat.BUTTON.centerx, "y": chat.BUTTON.centery, "held": [], "down": []},
                           pg.time.get_ticks())
    check("not through the chat button (a device's own)", shown(one) == y_name)
    app.turn_manager.toggle_shop()
    check("not while the shop menu is open", shown(one) is None and shown(watcher) is None)
    app.turn_manager.toggle_shop()
    check("(and again once it's closed)", shown(watcher) == z_name)

    mine = next(name for name, _ in _spots(app, 20)
                if app.countries[name].owner in (app.default_player, app.players[app.turn]))
    at = next(point for name, point in _spots(app, 20) if name == mine)
    view = app.view
    real_pos, real_focused = pg.mouse.get_pos, pg.mouse.get_focused
    try:
        pg.mouse.get_pos = lambda: _window_pos(view, *at)
        pg.mouse.get_focused = lambda: True
        app.controls.mouse_active = pg.time.get_ticks()
        _frame(app)
        _frame(app)
    finally:
        pg.mouse.get_pos, pg.mouse.get_focused = real_pos, real_focused
    image, rect = app.country_panel(mine)
    corner = next((rect.x + x, rect.y + y) for y in range(2, rect.h - 2) for x in range(2, rect.w - 2)
                  if all(tuple(image.get_at((x + dx, y + dy)))[:3] == app.gui.gray1
                         for dx in range(-2, 3) for dy in range(-2, 3)))  # plain background
    on_screen = tuple(pg.display.get_surface().get_at(_window_pos(view, *corner)))[:3]
    check("the host sees the panel of the country its own mouse is over",
          app.io.hover_country == mine and max(abs(a - b) for a, b in zip(on_screen, app.gui.gray1)) < 12, on_screen)
    check("but it's not in the game's picture (what the devices get)", app.ui.get_at(corner)[3] == 0)
    s.close()

    conn = FakeConn([last])
    v = viewer.Viewer(conn, 1, [])
    v._receive()
    check("a device takes in its panel", v.hover is not None and list(v.hover[1]) == last["rect"])
    v._draw((500, 300))
    conn.incoming = [{"type": "hover"}]
    v._receive()
    check("and puts it away again", v.hover is None)
    conn.incoming = [{"type": "hover", "rect": [0, 0, 10, 10], "png": "not a picture"},
                     {"type": "hover", "rect": [900, 600, 200, 200], "png": last["png"]}]
    v._receive()
    check("a broken or misplaced panel isn't shown", v.hover is None)


def test_menus():
    app = _game()
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    sent = []
    s._send = lambda message, to=0: sent.append((to, message))
    s._member_joined({"member": 1, "device": "dev"})
    s._member_joined({"member": 2, "device": "watcher"})
    for i in (1, 2):
        s._seat_request(s.members[1], "take", {"seat": i})
    s.members[1].viewing = s.members[2].viewing = True
    s.start_game(app)
    app.turn = 0
    _frame(app)
    one, watcher = s.devices[1], s.devices[2]
    mouse, eyes = s.members[1].pointers["m"], s.members[2].pointers["m"]

    def click(pointer, x, y):
        pointer.feed({"x": x, "y": y, "held": [controls.A], "down": [controls.A]}, pg.time.get_ticks())
        _frame(app)
        pointer.feed({"x": x, "y": y, "held": [], "down": []}, pg.time.get_ticks())
        _frame(app)

    def menu_to(number):
        return [m for to, m in sent if to == number and m["type"] == "menu"]

    shop = app._shop_button()
    shop_at = (shop.pos.x + 30, shop.pos.y + 30)
    click(mouse, *shop_at)
    check("anyone may open the shop: someone else's turn, a look of their own",
          one.look == "shop" and app.players[0].attack != 3)
    check("it's drawn for them (sent as a picture)", menu_to(1) and menu_to(1)[-1].get("png"))
    check("and not in the game's picture", app.ui.get_at((400, 588))[3] == 0)
    del sent[:]
    time.sleep(online.HOVER_MS / 1000 + 0.02)
    click(mouse, 225, 150)  # the bridge
    errors = [(to, m) for to, m in sent if m["type"] == "sound" and m["name"] == "error"]
    check("everything in it is out of reach (the error sound, for that device alone)",
          errors and all(to == 1 for to, _ in errors) and app.players[1].subattack == 0, errors)
    click(mouse, 5, 630)
    check("a click outside closes it", one.look is None)
    time.sleep(online.HOVER_MS / 1000 + 0.02)
    _frame(app)
    check("(and the device is told)", menu_to(1)[-1].get("png") is None)

    click(mouse, app._card_button().pos.x + 30, 50)
    check("cards: nothing to show when their player has none", one.look is None)
    app.players[1].cards = [models.Kaertske(t, images=app.images) for t in (0, 1, 2)]
    app.players[2].cards = [models.Kaertske(0, images=app.images)]
    click(mouse, app._card_button().pos.x + 30, 50)
    check("cards: those of their player whose turn comes soonest (B, then C)",
          one.look == "cards" and one.cards.player is app.players[1])
    check("only to look at: nothing picked for a trade", not any(card.use for card in app.players[1].cards))
    click(mouse, 5, 630)
    app.turn = 1
    _frame(app)
    click(mouse, app._card_button().pos.x + 30, 50)
    check("on B's turn their cards button is the game's own (with trading)",
          one.look is None and app.card_menu.show and app.card_menu.player is app.players[1])
    check("drawn on their screen only", one.drawn and app.ui.get_at((480, 330))[3] == 0)
    click(mouse, 5, 630)
    app.turn = 0
    _frame(app)

    click(eyes, app._card_button().pos.x + 30, 50)
    check("someone watching has no cards to show", watcher.look is None)
    click(eyes, app._event_button().pos.x + 30, 50)
    check("the event card: on their screen", watcher.fields["event_info_open"] and not app.event_info_open)
    time.sleep(online.HOVER_MS / 1000 + 0.02)
    _frame(app)
    check("(dimming their picture)", menu_to(2)[-1].get("dim"))
    click(eyes, 400, 400)
    check("a click closes it", not watcher.fields["event_info_open"])

    app.turn_manager.toggle_shop()
    _frame(app)
    host_layer = s.devices[0].layer
    check("the host's turn: its shop is the game's, on its screen alone",
          app.players[0].attack == 3 and s.devices[0].drawn
          and tuple(host_layer.get_at((400, 588)))[:3] == app.SHOP_COLOR and app.ui.get_at((400, 588))[3] == 0)
    click(mouse, *shop_at)
    check("meanwhile others look at theirs", one.look == "shop" and app.players[0].attack == 3)
    click(mouse, 5, 630)
    app.turn_manager.toggle_shop()
    _frame(app)

    s._input(s.members[1], {"type": "pad", "n": 4, "x": 100, "y": 100, "held": [], "down": [controls.START]})
    _frame(app)
    check("a joined device's Start opens its own settings", one.fields["settings_open"] and not app.settings_open)
    s._input(s.members[1], {"type": "pad", "n": 4, "x": 100, "y": 100, "held": [], "down": [controls.START]})
    _frame(app)
    _frame(app)  # (the same button twice in a row: a frame apart)
    check("(and closes them)", not one.fields["settings_open"])
    app.toggle_settings()
    _frame(app)
    check("the host's own settings: on its screen, the game goes on",
          s.devices[0].drawn and app.ui.get_at((480, 320))[3] == 0 and not app.modal_open)
    app.toggle_settings()
    s.close()

    conn = FakeConn([{"type": "menu", "dim": True, "rect": [100, 100, 20, 20], "png": "x"},
                     {"type": "menu", "dim": True}])
    v = viewer.Viewer(conn, 1, [])
    v._receive()
    check("a device takes in its menu (none, or a broken one: none)", v.menu is None and v.dim)
    v._draw((500, 300))


def test_game():
    real = net.find_main_relay
    net.find_main_relay = lambda stop=None: None  # no main relay: the host starts its own
    try:
        _game_through_relay()
    finally:
        net.find_main_relay = real


def _game_through_relay():
    seats = lobby._new_seats(3)
    seats[0].name = "Ann"
    seats[2].kind = "bot"
    s = online.HostSession(seats)
    deadline = time.time() + 8
    while s.status == "connecting" and time.time() < deadline:
        time.sleep(0.05)
    check("without a main relay the host opens a game on its own (LAN) relay", s.status == "lan", s.status)
    if s.status != "lan":
        return
    device = Inbox(net.connect(("127.0.0.1", s._relay.port)))
    device.conn.send({"type": "list"})
    room = device.wait("rooms")["rooms"][0]
    check("the game is listed: the host's name, waiting, 1 free seat",
          room["title"] == "Ann" and room["state"] == "lobby" and room["free"] == 1, room)
    device.conn.send({"type": "join", "room": room["room"]})
    me = device.wait("joined")["member"]

    def until(condition, timeout=3.0):
        end = time.time() + timeout
        while not condition() and time.time() < end:
            s.update()
            time.sleep(0.02)
        return condition()

    check("the host sees the device", until(lambda: me in s.members))
    check("the device gets the seats", device.wait("seats") is not None)
    device.conn.send({"type": "take", "seat": 1})
    device.conn.send({"type": "name", "seat": 1, "text": "Bea"})
    check("it takes a seat and names it", until(lambda: seats[1].name == "Bea" and seats[1].member == me))
    check("so the game can start", s.start_problem() is None, s.start_problem())

    app = lobby._start(s, 3, {})
    app.controls = controls.get()
    check("the game's players are the seats", [p.name for p in app.players] == ["Ann", "Bea", "Bot 3"]
          and [p.is_bot for p in app.players] == [False, False, True])
    final = device.wait(lambda m: isinstance(m, dict) and m.get("type") == "seats" and m.get("state") == "game")
    check("the device hears the final seats, then start", final is not None and device.wait("start") is not None)

    app.turn = 1  # Bea's turn
    device.conn.send({"type": "ready"})
    screen = pg.Surface(online.STREAM_SIZE)
    got = None
    for _ in range(40):
        _frame(app)
        update = device.wait(lambda m: isinstance(m, bytes), timeout=0.05)
        if update is not None:
            got = online.apply_update(screen, update)
            device.conn.send({"type": "ack", "seq": got})
            break
    check("the device gets the host's screen", got is not None)
    if got is not None:
        error = _error(screen, s.stream.frame)
        check("and it is the host's screen (JPEG close)", error < 4, error)
    cursors = device.wait("cursors")
    check("and the cursors", cursors is not None and any(c[6] == me for c in cursors["c"]))

    device.conn.send({"type": "mouse", "x": 50, "y": 50, "held": [controls.A], "down": [controls.A]})
    device.conn.send({"type": "mouse", "x": 50, "y": 50, "held": [], "down": []})
    for _ in range(60):
        _frame(app)
        if s.devices[me].fields["settings_open"]:
            break
        time.sleep(0.02)
    check("the device's click works: its own settings open", s.devices[me].fields["settings_open"])
    sounds.play("click")
    sound = device.wait("sound")
    check("the device hears the host's sounds", sound is not None and sound["name"] == "click")
    device.conn.send({"type": "chat", "text": "good luck"})
    check("the device's chat message reaches the host",
          until(lambda: [line[3] for line in s.chat.lines] == ["good luck"]))
    said = device.wait("chat")
    check("and comes back to it under its player's name",
          said is not None and said["lines"] == [[me, "Bea", list(app.players[1].color), "good luck"]], said)
    s.say("thanks")
    said = device.wait("chat")
    check("the host's message reaches the device",
          said is not None and said["lines"][0][1:] == ["Ann", list(app.players[0].color), "thanks"], said)

    device.conn.send({"type": "leave"})
    check("a device leaving frees its seat, kept for it", until(lambda: seats[1].kind == "open")
          and seats[1].device == net.device_id())
    back = Inbox(net.connect(("127.0.0.1", s._relay.port)))
    back.conn.send({"type": "join", "room": room["room"]})
    back.wait("joined")
    check("coming back, the same device has it again", until(lambda: seats[1].kind == "remote"))
    back.conn.send({"type": "ready"})
    until(lambda: any(member.viewing for member in s.members.values()))
    history = back.wait("chat")
    check("and gets the chat so far (as read)", history is not None and history.get("old")
          and [line[3] for line in history["lines"]] == ["good luck", "thanks"], history)
    s.close("ended")
    end = back.wait("end")
    check("the host ending the game tells the devices", end is not None and end.get("reason") == "ended")
    for conn in (device.conn, back.conn):
        conn.close()


TESTS = [test_relay, test_discovery, test_stream, test_seats, test_clicks, test_names, test_chat, test_hover,
         test_menus, test_game]


def main():
    wanted = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    for test in TESTS:
        if wanted not in test.__name__:
            continue
        _current_test[0] = test.__name__[5:]
        try:
            test()
        except Exception:
            results.append((_current_test[0], "ran without errors", False, traceback.format_exc()))
    failed = 0
    for test, description, ok, detail in results:
        print("{}  {:10} {}".format("PASS" if ok else "FAIL", test, description))
        if not ok:
            failed += 1
            if detail != "":
                print("      ", detail)
    print("\n{} of {} checks passed".format(len(results) - failed, len(results)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
