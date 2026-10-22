"""
Automated checks for online play (net.py, relay.py, online.py, viewer.py,
lobby.py, chat.py): the relay's routing, finding relays, the stream of the
game's layer, the lobby's seats, who may click in the game, the game's
state on a device's own copy of the game (its own view, cursors), the
chat, each device's country info panel and own menus, and a whole hosted
game with a device joining it through a real (local) relay. PASS/FAIL per
check.

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

import pygame as pg  # noqa: E402

import chat  # noqa: E402
import controls  # noqa: E402
import lang  # noqa: E402
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


# --- the stream of the game's layer ---------------------------------------------------

def _layer():
    """A game's layer: see-through, with a HUD panel and a half-dark dim."""
    layer = pg.Surface(online.OVERLAY_SIZE, pg.SRCALPHA)
    pg.draw.rect(layer, (200, 200, 200, 255), (810, 256, 150, 384))
    pg.draw.rect(layer, (0, 0, 0, 140), (0, 0, 300, 200))
    pg.draw.circle(layer, (250, 225, 130, 255), (480, 320), 50)
    return layer


def _same(a, b):
    """Whether two layers are the same, pixel for pixel, alpha and all."""
    return pg.image.tobytes(a, "RGBA") == pg.image.tobytes(b, "RGBA")


def _area(update):
    (length,) = __import__("struct").unpack_from(">I", update)
    head = json.loads(update[4:4 + length].decode())
    return sum(w * h for _, _, w, h, _ in head["rects"]), len(head["rects"])


def test_stream():
    layer = _layer()
    stream = online.OverlayStream()
    check("the first capture is a change", stream.capture(layer, now=1000) and stream.seq == 1)
    device = pg.Surface(online.OVERLAY_SIZE, pg.SRCALPHA)
    device.fill((9, 9, 9, 9))
    update = stream.update_since(-1)
    check("a device's first update is the whole layer",
          _area(update)[0] == online.OVERLAY_SIZE[0] * online.OVERLAY_SIZE[1])
    check("it says its capture number", online.apply_update(device, update) == 1)
    check("the device's layer is the host's exactly, see-through where the map shows",
          _same(device, stream.frame) and device.get_at((600, 100))[3] == 0 and device.get_at((100, 100))[3] == 140)
    check("the same update is made once and shared", stream.update_since(-1) is update)
    check("mostly see-through, it's small", len(update) < 40000, len(update))

    pg.draw.rect(layer, (255, 0, 0, 255), (100, 100, 20, 20))
    check("too soon after the last capture: owed", not stream.capture(layer, now=1020) and stream.pending)
    check("then taken", stream.capture(layer, now=1060) and stream.seq == 2 and not stream.pending)
    area, rects = _area(stream.update_since(1))
    check("a small change sends only its tiles", area <= 4 * online.TILE ** 2 and rects <= 2, (area, rects))
    check("nothing new: nothing sent", stream.update_since(2) is None)
    check("an unchanged layer is no new capture", not stream.capture(layer, now=1200) and stream.seq == 2)

    layer.fill((0, 0, 0, 0), (440, 280, 80, 80))  # (something closed: see-through again)
    pg.draw.rect(layer, (0, 255, 0, 255), (800, 500, 30, 30))
    stream.capture(layer, now=1300)
    area_last, _ = _area(stream.update_since(2))
    area_both, rects_both = _area(stream.update_since(1))
    check("a device behind gets everything since its capture in one update",
          area_both > area_last and rects_both >= 2, (area_both, area_last))
    online.apply_update(device, stream.update_since(1))
    check("and then has the host's layer (what went see-through too)", _same(device, stream.frame))

    for x in range(0, 960, 128):
        for y in range(0, 640, 128):
            pg.draw.rect(layer, (x % 255, y % 255, 90, 255), (x, y, 10, 10))
    stream.capture(layer, now=1400)
    check("many scattered pieces go as one box", _area(stream.update_since(stream.seq - 1))[1] == 1)
    try:
        online.apply_update(device, b"\x00\x00\x00\x05junk!")
        check("garbage is no update", False)
    except ValueError:
        check("garbage is no update", True)


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
    s._input(s.members[1], {"type": "mouse", "x": 50, "y": 50, "held": [], "down": [], "menu": True})
    _frame(app)
    check("while their device has a menu of its own open, its clicks are that menu's, not the game's",
          mouse not in pads.clickers and not pads.mouse_ok)
    s._input(s.members[1], {"type": "mouse", "x": 50, "y": 50, "held": [], "down": [], "menu": False})
    _frame(app)
    check("and then the game gets their clicks again", mouse in pads.clickers)
    mouse.feed({"x": 50, "y": 50, "held": [controls.A], "down": [controls.A]}, pg.time.get_ticks())
    _frame(app)
    check("their click on the settings button opens nothing here (their settings are their own)",
          not app.settings_open and not s.devices[0].look)
    mouse.next_frame()
    mouse.feed({"x": 5, "y": 630, "held": [], "down": [controls.A]}, pg.time.get_ticks())
    mouse.next_frame()
    check("a click and release within one frame still clicks", mouse.pressed[0] and mouse.fresh[0])
    mouse.next_frame()
    mouse.feed({"x": 5, "y": 630, "held": [], "down": [controls.A, controls.A]}, pg.time.get_ticks())
    taps = []
    for _ in range(3):
        mouse.next_frame()
        taps.append(mouse.tapped(controls.A))
    check("two clicks arriving together are two clicks (a frame up in between)", taps == [True, False, True], taps)
    s._input(s.members[1], {"type": "mouse", "x": 5, "y": 630, "view": [2.5, -100, -50.5]})
    check("its device's view comes with its input (it points at the map through it)",
          mouse.view.zoom == 2.5 and (mouse.view.offset.x, mouse.view.offset.y) == (-100, -50.5))
    s._input(s.members[1], {"type": "mouse", "x": 5, "y": 630, "view": [99, "x", None]})
    check("(a broken one is left out)", mouse.view.zoom == 2.5)
    s._input(s.members[1], {"type": "mouse", "x": 5, "y": 630, "view": [99, 0, 0]})
    check("(a zoom past the limits is kept within them)", mouse.view.zoom == models.View.MAX_ZOOM)

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
        # The country under a top-left button or the chat button: a click
        # there is the button's, not the country's.
        for spot_x, spot_y in [(b.pos.x + 30, b.pos.y + 30) for b in (
                app._settings_button(), app._shop_button(), app._card_button(), app._event_button())] \
                + [chat.BUTTON.center]:
            mc = app.countries[name].mass_center
            view.offset = Position((spot_x - 0.5 * view.WIDTH) / view.zoom - mc.x,
                                   (spot_y - 0.5 * view.HEIGHT) / view.zoom - mc.y)
            mouse.view = view
            x, y = spot_x, spot_y
            pg.mouse.get_pos = lambda: (x * view.scale + view.ox, y * view.scale + view.oy)
            _frame(app)
            check("a click on the button at {} says nothing (host, device)".format((spot_x, spot_y)),
                  click(host=True) == [] and (_frame(app) or click(device=True) == []))
            _frame(app)
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
    streamed = tuple(s.stream.frame.get_at(spot))
    check("but it's not in the game's layer the devices get (they have their own)",
          streamed[:3] != chat.COLOR, streamed)

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
    s.chat.handle(_event(pg.MOUSEBUTTONDOWN, button=1, pos=button), to_logical)
    outside = _window_pos(view, 600, 400)
    real_pos, real_pressed = pg.mouse.get_pos, pg.mouse.get_pressed
    try:
        pg.mouse.get_pos = lambda: outside
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, False)
        app.io_handle()
        took = s.chat.handle(_event(pg.MOUSEBUTTONDOWN, button=1, pos=outside), to_logical)
        pg.mouse.get_pressed = lambda num_buttons=3: (True, False, False)
        app.io_handle()
        check("a click anywhere outside the chat closes it, and the game doesn't get that click",
              took and not s.chat.open and not app.io.left_pressed)
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, False)
        s.chat.handle(_event(pg.MOUSEBUTTONUP, button=1, pos=outside), to_logical)
        app.io_handle()
        app.io_handle()
        pg.mouse.get_pressed = lambda num_buttons=3: (True, False, False)
        app.io_handle()
        check("(the next click is the game's again)", not s.chat.taken and app.io.left_pressed)
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, False)
        app.io_handle()
    finally:
        pg.mouse.get_pos, pg.mouse.get_pressed = real_pos, real_pressed
    check("closed, a click outside it is the game's",
          not s.chat.handle(_event(pg.MOUSEBUTTONDOWN, button=1, pos=outside), to_logical))
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
    far = (round(v.area.x + 700 * v.scale), round(v.area.y + 500 * v.scale))
    v._events([_event(pg.MOUSEBUTTONDOWN, button=3, pos=far)])
    check("a click outside its chat closes it, and isn't sent to the host",
          not v.chat.open and v._down == [] and v._swallowed == {controls.B})
    v._events([_event(pg.MOUSEBUTTONUP, button=3, pos=far)])
    v._events([_event(pg.MOUSEBUTTONDOWN, button=1, pos=at)])
    v._events([_event(pg.MOUSEBUTTONUP, button=1, pos=at)])
    v._events([_key(pg.K_ESCAPE)])
    check("Esc closes its chat first, then opens its menu", not v.chat.open and not v.menu_open)
    v._events([_key(pg.K_ESCAPE)])
    check("(its menu)", v.menu_open)
    v.menu_open = False
    v._events([_event(pg.MOUSEBUTTONDOWN, button=1, pos=(at[0] + 400, at[1] + 200))])
    check("a click elsewhere is the host's", v._down == [controls.A])
    v._draw((500, 300))


# --- a device's own copy of the game, linked to a host in this process ---------------

class Wire:
    """The relay between a host session (its `conn`) and the devices, in
    this process: what the host sends goes to the devices it's for."""

    def __init__(self):
        self.closed = False
        self.wake = None
        self.inboxes = {}   # member -> messages for it
        self.incoming = []  # from the devices, for the host
        self.sent = []      # everything the host sent: (to, message)

    def send(self, message):
        message = dict(message)
        to = message.pop("to", 0)
        self.sent.append((to, message))
        for member, inbox in self.inboxes.items():
            if to in (0, member):
                inbox.append(message)

    def send_binary(self, data, to=0):
        self.sent.append((to, data))
        for member, inbox in self.inboxes.items():
            if to in (0, member):
                inbox.append(data)

    def poll(self):
        incoming, self.incoming = self.incoming, []
        return incoming

    def close(self):
        self.closed = True


class DeviceConn:
    """A device's end of a Wire."""

    def __init__(self, wire, member):
        self.wire, self.member = wire, member
        self.sent = []
        self.closed = False
        self.wake = None
        wire.inboxes[member] = []

    def send(self, message):
        self.sent.append(message)
        self.wire.incoming.append(dict(message, **{"from": self.member}))

    def poll(self):
        incoming, self.wire.inboxes[self.member] = self.wire.inboxes[self.member], []
        return incoming

    def close(self):
        self.closed = True


def _linked(turn=1, watcher=False):
    """A host's game (A here, B and C on device 1; device 2 only watches)
    and device 1's viewer (its copy of the game made from what came in)."""
    app = _game()
    app.turn = turn
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    wire = s.conn = Wire()
    numbers = (1, 2) if watcher else (1,)
    for number in numbers:
        s._member_joined({"member": number, "device": "dev{}".format(number)})
    for i in (1, 2):
        s._seat_request(s.members[1], "take", {"seat": i})
    s.start_game(app)
    v = viewer.Viewer(DeviceConn(wire, 1), 1, [seat.to_json() for seat in seats])
    others = [DeviceConn(wire, number) for number in numbers[1:]]
    # (The device's copy opens a window: the host draws off screen.)
    app.view.window = pg.Surface(app.view.window.get_size())
    for number in numbers:
        wire.incoming.append({"type": "ready", "from": number})
    for _ in range(3):
        _both(app, v)
    return app, s, v, wire, others


_device_mouse = [((0, 0), (False, False, False))]  # the device's mouse (window px, buttons), see _Mouse


def _both(app, v, events=()):
    """A frame on the host, then one on the device (nothing held back by
    the host's timing). One process, one pg.mouse: the host's mouse is out
    of the window, the device's where _Mouse put it."""
    s = app.online
    s._state_at, s._cursors_at, s.stream._captured_at = -10 ** 9, -10 ** 9, None
    for device in s.devices.values():
        device.sent_at = -10 ** 9
    saved = pg.mouse.get_pos, pg.mouse.get_pressed, pg.mouse.get_focused
    try:
        pg.mouse.get_pos, pg.mouse.get_focused = (lambda: (0, 0)), (lambda: False)
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, False)
        _frame(app)
        at, held = _device_mouse[0]
        pg.mouse.get_pos, pg.mouse.get_pressed = (lambda: at), (lambda num_buttons=3: held)
        v.frames_left = max(v.frames_left, 1)
        return v.frame(list(events))
    finally:
        pg.mouse.get_pos, pg.mouse.get_pressed, pg.mouse.get_focused = saved


def _device_pos(v, x, y):
    """Logical (x, y) in the device's window."""
    return round(v.area.x + x * v.scale), round(v.area.y + y * v.scale)


class _Mouse:
    """The device's mouse at a logical point (in its window) for the frames
    in it (_both), its left button held or not (or `held`: all three)."""

    def __init__(self, v, x, y, held=False):
        self.state = (_device_pos(v, x, y), held if isinstance(held, tuple) else (held, False, False))

    def __enter__(self):
        self.saved, _device_mouse[0] = _device_mouse[0], self.state

    def __exit__(self, *exc):
        _device_mouse[0] = self.saved


def _device_click(app, v, x, y):
    """The device's mouse clicks at (x, y) (logical), the host's game taking
    whatever is sent."""
    at = _device_pos(v, x, y)
    with _Mouse(v, x, y):
        _both(app, v, [_event(pg.MOUSEMOTION, pos=at, rel=(1, 1), buttons=(0, 0, 0))])
    with _Mouse(v, x, y, held=True):
        _both(app, v, [_event(pg.MOUSEBUTTONDOWN, button=1, pos=at)])
        _both(app, v)
    with _Mouse(v, x, y):
        _both(app, v, [_event(pg.MOUSEBUTTONUP, button=1, pos=at)])
        _both(app, v)


def _spots(game, view, count, overlay=None):
    """`count` countries in view, each with a point (logical) that is on it
    (and not under the game's layer)."""
    found = []
    for country in game.countries.values():
        x = (country.mass_center.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH
        y = (country.mass_center.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT
        if not (250 < x < 650 and 150 < y < 450):
            continue
        if overlay is not None and overlay.get_at((int(x), int(y)))[3]:
            continue
        if game.io.country_at(view, game.countries.values(), Position(int(x), int(y)), []) == country.name:
            found.append((country.name, (int(x), int(y))))
    return found[:count]


def test_state():
    app, s, v, wire, _ = _linked()
    game = v.game
    check("the device makes its copy of the game from the host's state",
          game is not None and [p.name for p in game.players] == ["A", "B", "C"] and game.mirror is v)
    fulls = [to for to, m in wire.sent if isinstance(m, dict) and m.get("type") == "state" and m.get("full")]
    check("(all of it once, to that device)", fulls == [1], fulls)
    check("the same board: owners, troops, resources", all(
        game.countries[n].owner.name == c.owner.name and game.countries[n].units == c.units
        and game.countries[n].food == c.food for n, c in app.countries.items()))
    check("whose turn it is, the players' stock", game.turn == app.turn
          and [(p.food, p.wood, p.attack) for p in game.players] == [(p.food, p.wood, p.attack) for p in app.players])

    name = next(n for n, c in app.countries.items() if c.owner is app.default_player)
    del wire.sent[:]
    app.countries[name].owner, app.countries[name].units = app.players[2], 33
    _both(app, v)
    changes = [m for _, m in wire.sent if isinstance(m, dict) and m.get("type") == "state"]
    check("a change arrives", game.countries[name].owner is game.players[2] and game.countries[name].units == 33)
    check("only what changed is sent", len(changes) == 1 and list(changes[0]["countries"]) == [name]
          and not changes[0]["set"], changes)
    del wire.sent[:]
    _both(app, v)
    check("nothing changed: nothing sent", not [m for _, m in wire.sent if isinstance(m, dict)
                                                and m.get("type") == "state"])

    mine = next(n for n, c in app.countries.items() if c.owner is app.players[1])
    app.players[1].attack, app.players[1].subattack = 1, 1
    app.turn_manager.phases[1].attack_from = mine
    _both(app, v)
    _both(app, v)
    check("the countries the player picked are highlighted on the device too",
          game.countries[mine].shade == 1 and game.players[1].attack == 1 and game.players[1].subattack == 1)
    app.turn_manager.phases[1].attack_from = None
    app.players[1].attack, app.players[1].subattack = 0, 0
    _both(app, v)
    check("(and not once it's dropped)", game.countries[mine].shade == 0)

    app.log_action(app.players[1], lang.Msg("'s {} was destroyed in {}", "ship", name))
    _both(app, v)
    check("the action log comes along (to be translated on the device)",
          len(game.action_log) == len(app.action_log) and isinstance(game.action_log[-1][1][0], lang.Msg))
    del wire.sent[:]
    app.log_action("one more")
    _both(app, v)
    logs = [m for _, m in wire.sent if isinstance(m, dict) and m.get("type") == "log"]
    check("a new line goes on its own", len(logs) == 1 and len(logs[0]["lines"]) == 1 and not logs[0].get("reset")
          and str(game.action_log[-1][0][0]) == "one more")
    app.action_log = [[["a loaded game's", (255, 255, 255)]]]
    _both(app, v)
    check("a log that was replaced (a game loaded) is sent anew",
          [str(line[0][0]) for line in game.action_log] == ["a loaded game's"])

    saved = lang.language
    try:
        lang.language = "nl" if saved == "en" else "en"
        _both(app, v)
        check("the device shows the game in the host's language",
              v.state["online"]["lang"] == lang.language)
    finally:
        lang.language = saved

    view = game.view
    host_view = (app.view.zoom, app.view.offset.x, app.view.offset.y)
    view.zoom_at(Position(480, 320), 1.8)
    view.offset = view.offset + Position(60, -20)
    _both(app, v)
    _both(app, v)
    member = s.members[1]
    check("the device pans and zooms its own map; the host's stays", host_view ==
          (app.view.zoom, app.view.offset.x, app.view.offset.y) and abs(member.view.zoom - view.zoom) < 1e-3
          and abs(member.view.offset.x - view.offset.x) < 0.01)

    (target, at), = _spots(game, view, 1, v.overlay)
    host_there = app.io.country_at(app.view, app.countries.values(), Position(*at), [])
    with _Mouse(v, *at):
        _both(app, v, [_event(pg.MOUSEMOTION, pos=_device_pos(v, *at), rel=(1, 1), buttons=(0, 0, 0))])
        _both(app, v)
    check("its turn: the host's game points at what the device's pointer is over in its own view",
          app.io.source is member.pointers["m"] and app.io.hover_country == target and host_there != target,
          (app.io.hover_country, target, host_there))
    with _Mouse(v, at[0] + 40, at[1], held=(False, False, True)):
        _both(app, v, [_event(pg.MOUSEBUTTONDOWN, button=3, pos=_device_pos(v, at[0] + 40, at[1]))])
        _both(app, v)
    check("its right button held (dragging its own map) doesn't move the host's",
          host_view == (app.view.zoom, app.view.offset.x, app.view.offset.y))
    with _Mouse(v, at[0] + 40, at[1]):
        _both(app, v, [_event(pg.MOUSEBUTTONUP, button=3, pos=_device_pos(v, at[0] + 40, at[1]))])

    entry = [100, 200, 0, 0, 0, False, 0, "m"] + online.map_spot(app.view, 100, 200)
    x, y = online.cursor_spot(entry, view, pg.Surface((960, 640), pg.SRCALPHA))
    check("a cursor over the map is drawn at the same map point on every device",
          [round(c) for c in online.map_spot(view, x, y)] == [round(c) for c in entry[8:]], (x, y))
    cover = pg.Surface((960, 640), pg.SRCALPHA)
    cover.fill((0, 0, 0, 140), (50, 150, 100, 100))
    check("over the game's layer (a popup) at the same place on the screen",
          online.cursor_spot(entry, view, cover) == (100, 200))
    _both(app, v)
    check("the cursors come with their map point", v.cursors and all(len(c) == 10 for c in v.cursors), v.cursors)
    s.close()


def test_hover():
    app, s, v, wire, _ = _linked(turn=1)
    game = v.game
    game.view.zoom_at(Position(480, 320), 1.5)
    for _ in range(2):
        _both(app, v)
    (name, at), = _spots(game, game.view, 1, v.overlay)

    def hovered(x, y):
        with _Mouse(v, x, y):
            _both(app, v, [_event(pg.MOUSEMOTION, pos=_device_pos(v, x, y), rel=(1, 1), buttons=(0, 0, 0))])
            _both(app, v)
        return v._hovered()

    check("the device shows the panel of the country its own pointer is over, in its own view",
          hovered(*at) == name)
    image, rect = game.country_panel(name)
    corner = next((rect.x + x, rect.y + y) for y in range(2, rect.h - 2) for x in range(2, rect.w - 2)
                  if all(tuple(image.get_at((x + dx, y + dy)))[:3] == game.gui.gray1
                         for dx in range(-2, 3) for dy in range(-2, 3)))  # plain background
    on_screen = tuple(pg.display.get_surface().get_at(_device_pos(v, *corner)))[:3]
    check("drawn on its screen", max(abs(a - b) for a, b in zip(on_screen, game.gui.gray1)) < 12, on_screen)
    check("the host sends no panels (nor draws them in its layer)",
          not [m for _, m in wire.sent if isinstance(m, dict) and m.get("type") == "hover"]
          and s.stream.frame.get_at(corner)[3] == 0)
    check("not through the game's layer (the HUD)", hovered(900, 600) is None)
    check("not through the chat button (its own)", hovered(chat.BUTTON.centerx, chat.BUTTON.centery) is None)
    app.turn_manager.toggle_shop()
    check("not while its player's shop is open", hovered(*at) is None and v.private is not None)
    app.turn_manager.toggle_shop()
    check("(and again once it's closed)", hovered(*at) == name and v.private is None)
    s.close()

    app = _game()
    seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C")]
    s = _session(seats)
    s._member_joined({"member": 1, "device": "dev"})
    s.members[1].viewing = True
    s.start_game(app)
    app.turn = 0
    _frame(app)
    mine = next(name for name, _ in _spots(app, app.view, 20)
                if app.countries[name].owner in (app.default_player, app.players[app.turn]))
    at = next(point for name, point in _spots(app, app.view, 20) if name == mine)
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
                         for dx in range(-2, 3) for dy in range(-2, 3)))
    on_screen = tuple(pg.display.get_surface().get_at(_window_pos(view, *corner)))[:3]
    check("the host sees the panel of the country its own mouse is over",
          app.io.hover_country == mine and max(abs(a - b) for a, b in zip(on_screen, app.gui.gray1)) < 12, on_screen)
    check("but it's not in the game's layer (what the devices get)", s.stream.frame.get_at(corner)[3] == 0)
    s.close()


def test_menus():
    app, s, v, wire, (eyes,) = _linked(turn=0, watcher=True)
    game, member = v.game, s.members[1]

    def pressed_on_host():
        return [m for m in v.conn.sent if m.get("type") in ("mouse", "pad") and m.get("down")]

    shop = game._shop_button()
    shop_at = (shop.pos.x + 30, shop.pos.y + 30)
    del v.conn.sent[:]
    _device_click(app, v, *shop_at)
    check("anyone may open the shop: someone else's turn, a look of their own",
          v.device.look == "shop" and app.players[0].attack != 3)
    check("its click isn't sent to the host, which hears the device has a menu open",
          not pressed_on_host() and member.menu_open and member.pointers["m"] not in app.controls.clickers)
    _device_click(app, v, 225, 150)  # the bridge
    check("everything in it is out of reach", app.players[1].subattack == 0 and game.players[1].subattack == 0
          and v.device.look == "shop")
    _device_click(app, v, 5, 630)
    check("a click outside closes it", v.device.look is None and not member.menu_open and not pressed_on_host())

    cards_at = (game._card_button().pos.x + 30, 50)
    _device_click(app, v, *cards_at)
    check("cards: nothing to show when their player has none", v.device.look is None)
    app.players[1].cards = [models.Kaertske(t, images=app.images) for t in (0, 1, 2)]
    app.players[2].cards = [models.Kaertske(0, images=app.images)]
    _both(app, v)
    _device_click(app, v, *cards_at)
    check("cards: those of their player whose turn comes soonest (B, then C)",
          v.device.look == "cards" and v.device.cards.player is game.players[1]
          and [c.type for c in game.players[1].cards] == [0, 1, 2])
    check("only to look at: nothing picked for a trade", not any(card.use for card in app.players[1].cards))
    _device_click(app, v, 5, 630)

    app.turn = 1
    _both(app, v)
    del v.conn.sent[:]
    _device_click(app, v, *cards_at)
    check("on B's turn their cards button is the game's own (with trading), clicked on the host",
          v.device.look is None and pressed_on_host() and app.card_menu.show
          and app.card_menu.player is app.players[1])
    check("drawn on their screen only (sent to that device)", v.private is not None
          and app.ui.get_at((480, 330))[3] == 0 and not [m for to, m in wire.sent if isinstance(m, dict)
                                                       and m.get("type") == "menu" and m.get("png") and to != 1])
    _device_click(app, v, 5, 630)
    app.card_menu.show = False
    app.turn = 0
    _both(app, v)

    event_at = (game._event_button().pos.x + 30, 50)
    _device_click(app, v, *event_at)
    check("the event card: on its own screen", game.event_info_open and not app.event_info_open)
    _device_click(app, v, 400, 400)
    check("a click closes it", not game.event_info_open)

    settings_at = (game._settings_button().pos.x + 30, 50)
    _device_click(app, v, *settings_at)
    check("its settings: its own", game.settings_open and not app.settings_open and member.menu_open)
    for x, y in ((300, 215), (600, 215)):  # Exit Game, Save As
        _device_click(app, v, x, y)
    check("a joined device can't exit or save", not app.pending_quit and not game.pending_quit
          and not game.save_as_open and game.settings_open)
    _device_click(app, v, 220, 277)  # the first toggle: show continents
    check("what its map shows is its own to set", game.settings["continents"] and not app.settings["continents"])
    _device_click(app, v, 5, 630)
    check("(closed)", not game.settings_open)

    app.turn = 1
    for name in ("Japan", "China"):
        app.countries[name].owner = app.players[1]
        app.countries[name].landmark_owner = None
    _both(app, v)
    check("the pagoda and torii its player has to place are known on the device", v.owed == {"Japan", "China"})
    v.place_landmark("Japan", "Japan")
    _both(app, v)
    check("dropped on its own map: placed by the host", app.countries["Japan"].landmark_owner is app.players[1])
    eyes.send({"type": "landmark", "name": "China", "on": "China"})
    _both(app, v)
    check("not by a device whose turn it isn't", app.countries["China"].landmark_owner is None)
    v.place_landmark("China", "Japan")
    _both(app, v)
    check("on the wrong one: its own country is punished (as on the host)", "China" in app.turn_manager.landmarks_punished)
    del app.turn_manager.notices[:]  # (what was punished, and why)

    app.turn = 0
    app.turn_manager.toggle_shop()
    _frame(app)
    host_layer = s.devices[0].layer
    check("the host's turn: its shop is the game's, on its screen alone",
          app.players[0].attack == 3 and s.devices[0].drawn
          and tuple(host_layer.get_at((400, 588)))[:3] == app.SHOP_COLOR and app.ui.get_at((400, 588))[3] == 0)
    _device_click(app, v, *shop_at)
    check("meanwhile others look at theirs", v.device.look == "shop" and app.players[0].attack == 3)
    _device_click(app, v, 5, 630)
    app.turn_manager.toggle_shop()
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
    check("a device takes in the game's shop/cards (none, or a broken one: none)", v.private is None and v.dim)
    v._draw((500, 300))


class _FakeController:
    """A game controller standing still (for controls.Pad)."""

    def get_axis(self, axis):
        return 0

    def set_led(self, color):
        pass


def test_pairing():
    pads = controls.get()
    pad = controls.Pad(_FakeController(), 4242, 7)
    saved = list(pads.pads), dict(pads.bindings)
    pads.pads.append(pad)  # (one process: the host and the device share it)
    try:
        app, s, v, wire, _ = _linked(turn=1)
        game, member = v.game, s.members[1]
        check("a device with a controller nobody has opens its own Controllers panel as the game starts",
              game.pairing_open and not app.pairing_open and member.menu_open)
        check("it's for this device's players", [p.name for p in game.local_players()] == ["B", "C"])
        check("nobody else sees it (it's not in the game's layer)", s.stream.frame.get_at((480, 300))[3] == 0)
        game._pairing_since = -10 ** 6
        pad.x, pad.y = 480, 288  # on B's row
        _both(app, v, [_event(pg.CONTROLLERBUTTONDOWN, instance_id=4242, button=controls.A)])
        _both(app, v, [_event(pg.CONTROLLERBUTTONUP, instance_id=4242, button=controls.A)])
        check("its controller pressing A on a row is that player's, and the host hears it",
              pads.bindings.get(4242) == "B" and member.pad_names == {7: "B"}, (pads.bindings, member.pad_names))
        _device_click(app, v, 480, 418)  # Done
        check("Done closes it, and the device's clicks are the game's again",
              not game.pairing_open and not member.menu_open and member.pointers["m"] in app.controls.clickers)

        _device_click(app, v, game._settings_button().pos.x + 30, 50)
        _device_click(app, v, 605, 326)  # Controllers, in its settings
        check("a joined device opens it from its own settings", game.pairing_open and not game.settings_open
              and not app.pairing_open)
        _device_click(app, v, 480, 418)

        app.open_pairing()
        _both(app, v)
        check("the host's panel is its own: on its screen alone, for its own players, the game goes on",
              app.pairing_open and s.devices[0].drawn and app.ui.get_at((480, 300))[3] == 0
              and not app.modal_open and [p.name for p in app.local_players()] == ["A"]
              and member.pointers["m"] in app.controls.clickers)
        app.pairing_open = False
        s.close()

        app = _game()
        app.open_pairing()
        _frame(app)
        check("a local game: the panel stops the game, as it did", app.modal_open and pad in app.controls.clickers)
    finally:
        pads.pads[:], pads.bindings = saved


def test_scrolling():
    pads = controls.get()
    pad_a, pad_d = controls.Pad(_FakeController(), 5151, 8), controls.Pad(_FakeController(), 5252, 9)
    saved = list(pads.pads), dict(pads.bindings)
    pads.pads[:] = [pad_a, pad_d]  # (one process: the host and the device share it)
    saved_mouse = pg.mouse.get_pos, pg.mouse.get_pressed
    try:
        # The host's computer has A and D, the device B and C.
        app = _game(("A", "B", "C", "D"))
        seats = [online.Seat("A", kind="host"), online.Seat("B"), online.Seat("C"), online.Seat("D", kind="host")]
        s = _session(seats)
        s._member_joined({"member": 1, "device": "dev"})
        for i in (1, 2):
            s._seat_request(s.members[1], "take", {"seat": i})
        s.members[1].viewing = True
        s.start_game(app)
        pads.bind(pad_a, "A")
        pads.bind(pad_d, "D")
        app.pairing_open = False  # (opened by itself: controllers nobody had)
        theirs = s.members[1].view

        def pans(pad):
            before, kept = app.view.offset.x, (theirs.zoom, theirs.offset.x, theirs.offset.y)
            pad.pan = (40.0, 0.0)
            _frame(app)
            pad.pan = (0.0, 0.0)
            return app.view.offset.x != before and kept == (theirs.zoom, theirs.offset.x, theirs.offset.y)

        app.turn = 1
        _frame(app)
        mouse, moving = app.scrollers()
        check("a joined player decides: everyone here still pans and zooms this computer's map "
              "(its mouse too, which doesn't click)", not pads.mouse_ok and mouse and moving == [pad_a, pad_d])
        check("a controller's stick pans this computer's map, not the device's", pans(pad_d))
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, True)
        pg.mouse.get_pos = lambda: (300, 300)
        _frame(app)
        before = app.view.offset.x
        pg.mouse.get_pos = lambda: (340, 300)
        _frame(app)
        check("and the mouse drags it, while Io follows the device's pointer",
              app.view.offset.x > before and app.io.source is not None)
        pg.mouse.get_pressed = lambda num_buttons=3: (False, False, False)
        zoom = app.view.zoom
        app.zoom_view([1], [])
        check("and its wheel zooms it", app.view.zoom > zoom)

        app.turn = 0
        _frame(app)
        check("two players here, A decides: only A's controller pans and zooms (not the mouse, not D's)",
              app.scrollers() == (False, [pad_a]) and pans(pad_a) and not pans(pad_d))
        pads.bind(pad_a, None)
        check("A without a controller: the mouse does (it's A's)", app.scrollers() == (True, []))
        app.players[0].is_bot = True
        check("A a bot: everyone here does", app.scrollers() == (True, [pad_a, pad_d]))
        app.players[0].is_bot = False
        seats[3].kind = "bot"
        app.players[3].is_bot = True
        check("one player here: everyone here, always", app.scrollers() == (True, [pad_a, pad_d]))
        s.close()

        # The device's side: B and C on it, A on the host's computer.
        pg.mouse.get_pos, pg.mouse.get_pressed = saved_mouse
        pads.bindings = {}
        app, s, v, wire, _ = _linked(turn=0)
        game = v.game
        app.pairing_open = game.pairing_open = False
        mine = game.local_players()
        check("the device: another device's player decides, everyone here pans and zooms",
              pads.scrollers(mine, v._online("acting")) == (True, [pad_a, pad_d]))

        def drag():
            before, host = game.view.offset.x, (app.view.offset.x, app.view.zoom)
            with _Mouse(v, 300, 300, held=(False, True, False)):
                _both(app, v, [_event(pg.MOUSEMOTION, pos=_device_pos(v, 300, 300), rel=(1, 1), buttons=(0, 1, 0))])
            with _Mouse(v, 340, 300, held=(False, True, False)):
                _both(app, v, [_event(pg.MOUSEMOTION, pos=_device_pos(v, 340, 300), rel=(40, 0), buttons=(0, 1, 0))])
            with _Mouse(v, 340, 300):
                _both(app, v)
            return game.view.offset.x != before and (app.view.offset.x, app.view.zoom) == host

        check("its mouse drags its own map (the host's stays put)", drag())
        app.turn = 1
        for _ in range(2):
            _both(app, v)
        pads.bind(pad_d, "B")
        check("its B decides with a controller: only that one pans and zooms there",
              pads.scrollers(mine, v._online("acting")) == (False, [pad_d]) and not drag())
        pads.bind(pad_d, None)
        check("B without one: its mouse does", pads.scrollers(mine, v._online("acting")) == (True, []) and drag())
        s.close()
    finally:
        pads.pads[:], pads.bindings = saved
        pg.mouse.get_pos, pg.mouse.get_pressed = saved_mouse


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
    layer = pg.Surface(online.OVERLAY_SIZE, pg.SRCALPHA)
    got = state = None
    for _ in range(40):
        _frame(app)
        state = state or device.wait("state", timeout=0.05)
        update = device.wait(lambda m: isinstance(m, bytes), timeout=0.05)
        if update is not None:
            got = online.apply_update(layer, update)
            device.conn.send({"type": "ack", "seq": got})
        if got is not None and state is not None:
            break
    check("the device gets the game's state, all of it", state is not None and state.get("full")
          and [p["name"] for p in state["set"]["players"]] == ["Ann", "Bea", "Bot 3"]
          and len(state["set"]["countries"]) == len(app.countries))
    check("and the game's layer, exactly", got is not None and _same(layer, s.stream.frame))
    cursors = device.wait("cursors")
    check("and the cursors", cursors is not None and any(c[6] == me for c in cursors["c"]))

    device.conn.send({"type": "mouse", "x": 50, "y": 60, "held": [], "down": [], "view": [2.0, -300.0, -200.0],
                      "menu": True})
    member = s.members[me]
    check("the device's input comes in: where it points, its view, its own menu open", until(
        lambda: member.pointers["m"].pos == (50, 60) and member.view.zoom == 2.0 and member.menu_open))
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


TESTS = [test_relay, test_discovery, test_stream, test_seats, test_clicks, test_names, test_state, test_chat,
         test_hover, test_menus, test_pairing, test_scrolling, test_game]


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
