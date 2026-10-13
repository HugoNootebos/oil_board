"""
The relay for OIL's online play (net.py has the whole picture): it keeps
the list of open games and passes messages between each game's host and
the devices that joined it, without looking inside them. Everyone
connects out to the relay, so only the relay's computer needs a port open.

    python3 relay.py [--port 47800]

runs the main relay, on a computer at home (packaging/relay/README.md:
port forwarding, starting at login). A host that can't reach it runs one
itself for its local network (start_embedded). Standard library only and
self-contained, so any Python 3.7+ runs it from wherever it's copied to.

A message is a 4-byte length, a 1-byte kind (JSON or BINARY) and the
payload; JSON messages are objects with a "type". After `hello` a
connection is a host (`open`: it gets a room) or a member of one (`join`):

    from anyone   hello{proto, device} -> welcome{relay, kind} | refused{reason}
                  list -> rooms{rooms}         ping -> pong
    from a host   open{info} -> opened{room}   info{info} (the listing)
                  kick{member}                 anything with "to": that member (0: all)
                  BINARY: 4-byte member (0: all) + data, passed on as data
    from members  join{room, ...} -> joined{room, member, info} (the host
                  gets member{member, device}),  leave (the host gets left{member})
                  anything else goes to the host with "from": member;
                  BINARY goes to the host with the 4-byte member in front
    to members    closed (the host went away), kicked

Raise RELAY_PROTOCOL whenever these change (and update the home relay).
"""

import argparse
import asyncio
import json
import socket
import struct
import threading
import time
import uuid

RELAY_PROTOCOL = 1
PORT = 47800          # TCP: the relay
BEACON_PORT = 47801   # UDP: relays announce themselves on their local network
BEACON_EVERY = 2.0    # seconds
MAX_MESSAGE = 8 * 1024 * 1024
SILENT_LIMIT = 45.0   # a connection quiet for longer (clients ping every 10 s) is dropped
HELLO_TIMEOUT = 10.0
MAX_ROOMS = 100
MAX_MEMBERS = 16
MAX_BACKLOG = 16 * 1024 * 1024  # bytes waiting for one slow device before it's dropped

JSON, BINARY = 1, 2
HEADER = struct.Struct(">IB")
MEMBER = struct.Struct(">I")


def pack(kind, payload):
    return HEADER.pack(len(payload), kind) + payload


def pack_json(message):
    return pack(JSON, json.dumps(message, separators=(",", ":")).encode("utf-8"))


# What a room shows in the list of games, and of what type.
ROOM_FIELDS = {"title": str, "proto": int, "seats": int, "taken": int, "free": int, "state": str}


def _clean_info(info):
    if not isinstance(info, dict):
        return {}
    clean = {}
    for key, kind in ROOM_FIELDS.items():
        value = info.get(key)
        if isinstance(value, kind) and not isinstance(value, bool):
            clean[key] = value[:40] if kind is str else value
    return clean


def _log(*parts):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *parts, flush=True)


class _Client:

    def __init__(self, writer):
        self.writer = writer
        self.device = ""
        self.room = None
        self.member = None  # 0 for the room's host, else its member number

    def send(self, data):
        if self.writer.is_closing():
            return
        transport = self.writer.transport
        if transport.get_write_buffer_size() > MAX_BACKLOG:
            transport.abort()  # can't keep up: better gone than ever further behind
            return
        self.writer.write(data)


class _Room:

    def __init__(self, room_id, host, info):
        self.id = room_id
        self.host = host
        self.info = info
        self.members = {}  # member number -> _Client


class Relay:

    def __init__(self, kind="main"):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind  # "main" (relay.py on its own) or "lan" (inside a host's game)
        self.port = None
        self.rooms = {}
        self._next_member = 1
        self._clients = set()
        self._server = None
        self._beacon = None
        self._loop = None
        self.quiet = kind != "main"  # only the main relay logs

    async def serve(self, port):
        self._server = await asyncio.start_server(self._handle, None, port)
        self.port = port
        self._beacon = asyncio.ensure_future(self._beacons())

    # --- connections ----------------------------------------------------

    async def _handle(self, reader, writer):
        client = _Client(writer)
        self._clients.add(client)
        try:
            kind, payload = await asyncio.wait_for(_read(reader), HELLO_TIMEOUT)
            hello = json.loads(payload.decode("utf-8")) if kind == JSON else None
            if not isinstance(hello, dict) or hello.get("type") != "hello":
                return
            if hello.get("proto") != RELAY_PROTOCOL:
                client.send(pack_json({"type": "refused", "reason": "version"}))
                await writer.drain()
                return
            client.device = str(hello.get("device", ""))[:64]
            client.send(pack_json({"type": "welcome", "relay": self.id, "kind": self.kind,
                                   "proto": RELAY_PROTOCOL}))
            while True:
                kind, payload = await asyncio.wait_for(_read(reader), SILENT_LIMIT)
                try:
                    if kind == JSON:
                        message = json.loads(payload.decode("utf-8"))
                        if isinstance(message, dict):
                            self._on_json(client, message)
                    elif kind == BINARY:
                        self._on_binary(client, payload)
                except (TypeError, AttributeError, KeyError, ValueError):
                    pass  # a malformed message: ignored
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            self._clients.discard(client)
            self._drop(client)
            writer.close()

    def _on_json(self, client, message):
        kind = message.get("type")
        room = client.room
        if kind == "ping":
            client.send(pack_json({"type": "pong"}))
        elif kind == "list":
            client.send(pack_json({"type": "rooms", "rooms": [dict(r.info, room=r.id) for r in self.rooms.values()]}))
        elif kind == "open" and room is None:
            if len(self.rooms) >= MAX_ROOMS:
                client.send(pack_json({"type": "refused", "reason": "full"}))
                return
            room = _Room(uuid.uuid4().hex[:8], client, _clean_info(message.get("info")))
            self.rooms[room.id] = room
            client.room, client.member = room, 0
            client.send(pack_json({"type": "opened", "room": room.id}))
            self._say("opened", room.id, room.info.get("title", ""))
        elif kind == "info" and room is not None and client.member == 0:
            room.info = _clean_info(message.get("info"))
        elif kind == "join" and room is None:
            room = self.rooms.get(message.get("room"))
            if room is None or len(room.members) >= MAX_MEMBERS:
                client.send(pack_json({"type": "refused", "reason": "gone" if room is None else "full"}))
                return
            number = self._next_member
            self._next_member += 1
            room.members[number] = client
            client.room, client.member = room, number
            client.send(pack_json({"type": "joined", "room": room.id, "member": number, "info": room.info}))
            room.host.send(pack_json({"type": "member", "member": number, "device": client.device}))
            self._say("joined", room.id, number)
        elif room is None:
            return
        elif client.member == 0:
            if kind == "kick":
                member = room.members.get(message.get("member"))
                if member is not None:
                    member.send(pack_json({"type": "kicked"}))
                    self._leave(member)
                return
            to = message.pop("to", 0)
            data = pack_json(message)
            for member in (room.members.values() if to == 0 else [room.members.get(to)]):
                if member is not None:
                    member.send(data)
        elif kind == "leave":
            self._leave(client)
        else:
            message["from"] = client.member
            room.host.send(pack_json(message))

    def _on_binary(self, client, payload):
        room = client.room
        if room is None:
            return
        if client.member == 0:
            if len(payload) < MEMBER.size:
                return
            (to,) = MEMBER.unpack_from(payload)
            data = pack(BINARY, payload[MEMBER.size:])
            for member in (list(room.members.values()) if to == 0 else [room.members.get(to)]):
                if member is not None:
                    member.send(data)
        else:
            room.host.send(pack(BINARY, MEMBER.pack(client.member) + payload))

    def _leave(self, client):
        """A member leaves its room (the host is told)."""
        room = client.room
        if room is None or not client.member:
            return
        room.members.pop(client.member, None)
        room.host.send(pack_json({"type": "left", "member": client.member}))
        self._say("left", room.id, client.member)
        client.room, client.member = None, None

    def _drop(self, client):
        """A connection is gone: its room closes if it was the host."""
        room = client.room
        if room is None:
            return
        if client.member == 0:
            self.rooms.pop(room.id, None)
            for member in room.members.values():
                member.send(pack_json({"type": "closed"}))
                member.room, member.member = None, None
            self._say("closed", room.id)
        else:
            self._leave(client)

    def _say(self, *parts):
        if not self.quiet:
            _log(*parts)

    # --- telling the local network ----------------------------------------

    async def _beacons(self):
        """Every BEACON_EVERY seconds: "an OIL relay is here" to the local
        network (and to this computer itself, where broadcasts may not
        come back)."""
        payload = json.dumps({"oil": RELAY_PROTOCOL, "relay": self.id, "kind": self.kind,
                              "port": self.port}).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setblocking(False)
            while True:
                for target in ("255.255.255.255", "127.0.0.1"):
                    try:
                        sock.sendto(payload, (target, BEACON_PORT))
                    except OSError:
                        pass  # no network right now: try again next time
                await asyncio.sleep(BEACON_EVERY)
        finally:
            sock.close()

    # --- running inside the game --------------------------------------------

    def stop(self, delay=1.0):
        """Stop a relay started by start_embedded, after `delay` seconds (so
        a last message, e.g. "the game has ended", still gets through)."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.call_later, delay, self._shutdown)

    def _shutdown(self):
        if self._beacon is not None:
            self._beacon.cancel()
        if self._server is not None:
            self._server.close()
        for client in list(self._clients):
            client.writer.transport.abort()
        self._loop.call_later(0.1, self._loop.stop)


async def _read(reader):
    length, kind = HEADER.unpack(await reader.readexactly(HEADER.size))
    if length > MAX_MESSAGE:
        raise ValueError("message too long")
    return kind, await reader.readexactly(length)


def start_embedded(first_port=PORT, tries=10, kind="lan"):
    """A LAN relay on a thread of its own, for a host that can't reach the
    main relay: on the first free port from `first_port`. Returns the
    Relay (its `port`; `stop()` when done). Raises OSError when no port is
    free. (online_checks.py also starts a "main" one this way.)"""
    relay = Relay(kind=kind)
    started = threading.Event()

    def run():
        loop = asyncio.new_event_loop()
        relay._loop = loop
        asyncio.set_event_loop(loop)

        async def start():
            for port in range(first_port, first_port + tries):
                try:
                    await relay.serve(port)
                    return
                except OSError:
                    continue

        try:
            loop.run_until_complete(start())
        finally:
            started.set()
        if relay.port is not None:
            loop.run_forever()
        loop.close()

    threading.Thread(target=run, name="oil-relay", daemon=True).start()
    started.wait(5)
    if relay.port is None:
        raise OSError("no free port for a relay")
    return relay


def main():
    parser = argparse.ArgumentParser(description="The relay OIL's online games go through.")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    relay = Relay(kind="main")

    async def run():
        relay._loop = asyncio.get_running_loop()
        await relay.serve(args.port)
        _log("OIL relay {} listening on port {}".format(relay.id, args.port))
        while True:
            await asyncio.sleep(3600)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
