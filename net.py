"""
Online play's plumbing: connections to a relay, finding relays, and this
device's own id. Standard library only (no pygame).

How an online game works: the host's computer plays the game as always
(online.HostSession), and the devices that joined it show a picture of its
screen and send their mouse and controllers back (viewer.py). They don't
talk to each other directly but through a relay (relay.py), which every
one of them connects out to, so nobody but the relay's computer needs a
port open. There are two kinds of relay:

  - the main relay: relay.py on a computer at home, found at
    `server_address()` (packaging/relay/README.md). Games on it are
    visible to everyone online.
  - a LAN relay: a host that can't reach the main relay runs one inside its
    own game (relay.start_embedded); only its local network sees that game.

Every relay announces itself on its local network (a UDP broadcast, see
relay.py), and tells its id to whoever connects, so the same relay found
on this computer, on the local network and over the internet is used the
nearest way (`RoomBrowser`). That also keeps devices at home off the
internet address, which routers don't always loop back.

The messages between a host and its devices are online.py's and
viewer.py's; raise PROTOCOL whenever they change, so devices running
another version can see a game but not join it.
"""

import json
import os
import queue
import socket
import threading
import time
import uuid

from relay import (BEACON_EVERY, BEACON_PORT, BINARY, HEADER, JSON, MAX_MESSAGE, MEMBER, PORT,
                   RELAY_PROTOCOL, SILENT_LIMIT, pack, pack_json)

PROTOCOL = 3  # host <-> devices (online.py, viewer.py, chat.py); 2: the chat, 3: hover panels

# The main relay's address ("name:port"), once the home relay is set up
# (packaging/relay/README.md). OIL_SERVER or "online_server" in
# saves/settings.json override it.
DEFAULT_SERVER = "oilboard.duckdns.org:47800"

PING_EVERY = 10.0  # seconds; the relay drops a connection quiet for SILENT_LIMIT

# Ways to reach a relay, nearest first.
ROUTES = ("local", "lan", "online")


def parse_address(text, default_port=PORT):
    """"host:port" or "host" -> (host, port); None when it's no address."""
    host, sep, port = (text or "").strip().rpartition(":")
    if not sep:
        host, port = port, ""
    if not host or " " in host:
        return None
    try:
        port = int(port) if port else default_port
    except ValueError:
        return None
    return (host, port) if 0 < port < 65536 else None


def server_address():
    """The main relay's (host, port), or None when there's none set up."""
    import lang
    text = os.environ.get("OIL_SERVER") or lang.read_settings().get("online_server") or DEFAULT_SERVER
    return parse_address(text if isinstance(text, str) else "")


_device = None


def device_id():
    """This device's random id, kept in saves/settings.json: a device that
    drops out of a game and comes back gets its seats back by it."""
    global _device
    if _device is None:
        import lang
        value = lang.read_settings().get("device")
        if not isinstance(value, str) or not value:
            value = uuid.uuid4().hex
            lang.write_setting("device", value)
        _device = value
    return _device


# --- a connection ------------------------------------------------------------

class ConnectError(Exception):
    """Couldn't connect: str() is the reason ("unreachable", "version", ...)."""


def _read_message(sock):
    header = _recv_exactly(sock, HEADER.size)
    length, kind = HEADER.unpack(header)
    if length > MAX_MESSAGE:
        raise ValueError("message too long")
    return kind, _recv_exactly(sock, length)


def _recv_exactly(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def connect(address, timeout=5.0):
    """A Connection to the relay at (host, port), after saying hello.
    Raises ConnectError."""
    try:
        sock = socket.create_connection(address, timeout=timeout)
    except (OSError, ValueError):
        raise ConnectError("unreachable")
    try:
        sock.sendall(pack_json({"type": "hello", "proto": RELAY_PROTOCOL, "device": device_id()}))
        kind, payload = _read_message(sock)
        welcome = json.loads(payload.decode("utf-8")) if kind == JSON else {}
    except (OSError, ValueError):
        sock.close()
        raise ConnectError("unreachable")
    if not isinstance(welcome, dict) or welcome.get("type") != "welcome":
        sock.close()
        raise ConnectError(welcome.get("reason", "unreachable") if isinstance(welcome, dict) else "unreachable")
    sock.settimeout(None)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    return Connection(sock, welcome, address)


class Connection:
    """A connection to a relay. Messages go out and come in on threads of
    their own, so the game never waits for the network: `send`/
    `send_binary` queue, `poll()` returns what came in since (dicts for
    JSON, bytes for BINARY). `wake`, when set, is called (from the network
    thread) when something comes in while nobody polled yet -- the game uses
    it to wake its loop. `closed` once it's over."""

    def __init__(self, sock, welcome, address):
        self.sock = sock
        self.address = address
        self.relay = welcome.get("relay")  # the relay's id
        self.kind = welcome.get("kind")    # "main" or "lan"
        self.wake = None
        self.closed = False
        self._inbox = queue.Queue()
        self._outbox = queue.Queue()
        self._woken = False
        self._heard = time.time()
        threading.Thread(target=self._read, name="oil-net-in", daemon=True).start()
        threading.Thread(target=self._write, name="oil-net-out", daemon=True).start()

    def send(self, message):
        if not self.closed:
            self._outbox.put(pack_json(message))

    def send_binary(self, data, to=None):
        """`data` to the relay; from a host, `to` is the member it's for."""
        if not self.closed:
            self._outbox.put(pack(BINARY, (MEMBER.pack(to) if to is not None else b"") + data))

    def poll(self):
        self._woken = False
        messages = []
        while True:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                return messages

    def close(self):
        """Close after sending what's still queued."""
        if not self.closed:
            self._outbox.put(None)
            self.closed = True

    def _read(self):
        try:
            while True:
                kind, payload = _read_message(self.sock)
                self._heard = time.time()
                if kind == JSON:
                    message = json.loads(payload.decode("utf-8"))
                    if not isinstance(message, dict) or message.get("type") == "pong":
                        continue
                    self._inbox.put(message)
                else:
                    self._inbox.put(payload)
                if self.wake is not None and not self._woken:
                    self._woken = True
                    self.wake()
        except (OSError, ValueError):
            pass
        self.closed = True
        self._outbox.put(None)
        if self.wake is not None:
            self.wake()

    def _write(self):
        try:
            while True:
                try:
                    data = self._outbox.get(timeout=PING_EVERY)
                except queue.Empty:
                    if time.time() - self._heard > SILENT_LIMIT:
                        break  # the relay is gone without saying so
                    data = pack_json({"type": "ping"})
                if data is None:
                    break
                self.sock.sendall(data)
        except OSError:
            pass
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


# --- finding relays --------------------------------------------------------------

class _Beacons:
    """Listens, in the background, for the relays announcing themselves on
    the local network (relay.Relay._beacons)."""

    def __init__(self):
        self._seen = {}  # relay id -> ((ip, port), kind, time)
        self._lock = threading.Lock()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # more games on one computer
            sock.bind(("", BEACON_PORT))
        except OSError:
            sock.close()
            return  # nothing heard: this computer and typed-in addresses still work
        threading.Thread(target=self._listen, args=(sock,), name="oil-beacons", daemon=True).start()

    def _listen(self, sock):
        while True:
            try:
                data, (ip, _) = sock.recvfrom(2048)
                beacon = json.loads(data.decode("utf-8"))
                if not isinstance(beacon, dict) or beacon.get("oil") != RELAY_PROTOCOL:
                    continue
                port = int(beacon["port"])
                relay_id = str(beacon["relay"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            with self._lock:
                self._seen[relay_id] = ((ip, port), beacon.get("kind"), time.time())

    def recent(self):
        """[((ip, port), kind)] of the relays heard from lately."""
        now = time.time()
        with self._lock:
            return [(address, kind) for address, kind, seen in self._seen.values()
                    if now - seen < 3 * BEACON_EVERY]


_beacons = None


def beacons():
    global _beacons
    if _beacons is None:
        _beacons = _Beacons()
    return _beacons


class Found:
    """A relay a RoomBrowser is connected to."""

    def __init__(self, conn, route):
        self.conn = conn
        self.route = route
        self.kind = conn.kind  # "main" or "lan"
        self.address = conn.address
        self.rooms = []


class RoomBrowser:
    """Keeps, in the background, a connection to every relay it can find --
    on this computer, on the local network (beacons), the main relay
    (server_address), and any typed-in address -- and the games open on
    them (`rooms()`). The same relay found more than once (its id) is kept
    by the nearest route (ROUTES)."""

    REFRESH = 1.5  # seconds between asking each relay for its games
    RETRY = 8.0    # seconds before trying an address again that didn't answer

    def __init__(self):
        self._lock = threading.Lock()
        self._found = {}       # relay id -> Found
        self._tried = {}       # address -> time it was last tried
        self._trying = set()   # addresses being tried now
        self._extra = []       # typed-in addresses
        self.server = server_address()
        self.server_state = "none" if self.server is None else "trying"  # "ok", "unreachable"
        self._stop = False
        beacons()
        self._started = time.time()
        threading.Thread(target=self._run, name="oil-browser", daemon=True).start()

    def add_address(self, address):
        with self._lock:
            if address not in self._extra:
                self._extra.append(address)
            self._tried.pop(address, None)

    def rooms(self):
        """[(Found, room info)] of every relay found."""
        with self._lock:
            return [(found, room) for found in self._found.values() for room in found.rooms]

    def found(self):
        with self._lock:
            return list(self._found.values())

    def settled(self):
        """Whether everything there is to try has been tried once (beacons
        take a moment to be heard)."""
        with self._lock:
            pending = bool(self._trying) or any(a not in self._tried for a, _ in self._candidates())
        return not pending and time.time() - self._started > 1.2 * BEACON_EVERY

    def take(self, found):
        """Hand `found`'s connection over (the browser forgets it)."""
        with self._lock:
            self._found.pop(found.conn.relay, None)
        return found.conn

    def close(self):
        self._stop = True
        with self._lock:
            for found in self._found.values():
                found.conn.close()
            self._found = {}

    def _candidates(self):
        candidates = [(("127.0.0.1", PORT), "local")]
        for address, _ in beacons().recent():
            candidates.append((address, "local" if address[0].startswith("127.") else "lan"))
        if self.server is not None:
            candidates.append((self.server, "online"))
        candidates += [(address, "lan") for address in self._extra]
        return candidates

    def _run(self):
        while not self._stop:
            now = time.time()
            with self._lock:
                connected = {found.address for found in self._found.values()}
                for address, route in self._candidates():
                    if address in connected or address in self._trying \
                            or now - self._tried.get(address, -self.RETRY) < self.RETRY:
                        continue
                    self._trying.add(address)
                    threading.Thread(target=self._try, args=(address, route), daemon=True).start()
                found = list(self._found.values())
            for item in found:
                for message in item.conn.poll():
                    if isinstance(message, dict) and message.get("type") == "rooms" \
                            and isinstance(message.get("rooms"), list):
                        item.rooms = [room for room in message["rooms"] if isinstance(room, dict)]
                if item.conn.closed:
                    with self._lock:
                        if self._found.get(item.conn.relay) is item:
                            del self._found[item.conn.relay]
                else:
                    item.conn.send({"type": "list"})
            time.sleep(self.REFRESH)

    def _try(self, address, route):
        try:
            conn = connect(address, timeout=8.0 if route == "online" else 3.0)
        except ConnectError:
            conn = None
        with self._lock:
            self._trying.discard(address)
            self._tried[address] = time.time()
            if route == "online" and address == self.server:
                self.server_state = "ok" if conn is not None else "unreachable"
            if conn is None:
                return
            if self._stop:
                conn.close()
                return
            existing = self._found.get(conn.relay)
            if existing is not None and ROUTES.index(existing.route) <= ROUTES.index(route):
                conn.close()  # already connected to it, and at least as near
                return
            if existing is not None:
                existing.conn.close()
            self._found[conn.relay] = Found(conn, route)
        conn.send({"type": "list"})


def find_main_relay(stop=lambda: False):
    """For a host: a Connection to the main relay by its nearest route, or
    None when it can't be reached (or `stop()` says to give up)."""
    browser = RoomBrowser()
    try:
        while not stop():
            mains = [f for f in browser.found() if f.kind == "main"]
            if mains and (browser.settled() or min(ROUTES.index(f.route) for f in mains) == 0):
                best = min(mains, key=lambda f: ROUTES.index(f.route))
                return browser.take(best)
            if browser.settled():
                return None
            time.sleep(0.1)
        return None
    finally:
        browser.close()
