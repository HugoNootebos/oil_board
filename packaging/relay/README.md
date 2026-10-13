# The OIL relay on a computer at home

Online games go through a small relay program (`relay.py`, see `net.py` for how it all fits together).
All the players' copies of the game connect *out* to it, so only the relay's computer needs a port
open to the internet. Online games can be played whenever that computer is on and the relay is running.
When nobody can reach it, a host's game still works on its own local network.

## 1. Install the relay (once)

On the home computer (a Mac), in this game folder:

```bash
sh packaging/relay/install.sh
```

It copies `relay.py` to `~/Library/Application Support/OIL-relay` and starts it now and at every login.
It keeps running, and keeps the Mac from going to sleep on its own while it does. Its log is in
`~/Library/Logs/oil-relay.log`. Run it again after `relay.py` changes. `sh packaging/relay/install.sh --remove`
takes it out again.

The first time, macOS may ask whether Python may accept incoming connections: click **Allow**. If you
missed it: System Settings › Network › Firewall › Options, add `python3` and set it to allow.

The relay only uses the standard library: any Python 3.7 or newer works, no `pip install` needed.

**Energy:** the relay keeps the Mac awake while it's on, but a laptop with its lid closed still sleeps.
Leave the lid open or use a desktop.

## 2. Open the port on the router (once)

In the router's settings (usually at http://192.168.1.1 or http://192.168.2.254, with the password on its
sticker):

1. **A fixed address for the computer:** give it a fixed local address. The setting is often called
   *DHCP reservation*, *static lease* or *fixed IP*.
2. **Port forwarding:** forward **TCP port 47800** to that address. The setting is often called
   *port forwarding*, *virtual server* or *NAT*.

**Check first** whether your provider gives you a real public address. Compare the WAN/internet address
on the router's status page with what https://whatismyip.com shows:

- **The same:** port forwarding works.
- **Different**, often starting with `100.64.` to `100.127.`: the provider uses carrier-grade NAT, and
  port forwarding can't work. Ask the provider for a public IPv4 address (often free), or run the relay
  on a cheap rented server instead.

## 3. A fixed name for the home address (once)

The home's public address changes now and then, so the game connects to a name that keeps following it.

1. Go to https://www.duckdns.org, sign in, and create a subdomain, e.g. `oilboard` (that gives
   `oilboard.duckdns.org`). Copy the token shown there.
2. On the relay's computer, run:

   ```bash
   sh packaging/relay/install.sh oilboard YOUR-TOKEN
   ```

   This also keeps the name pointing at the home address, every 5 minutes.

Many routers can do this themselves instead (a *DDNS* setting). Use that if you prefer.

## 4. Tell the game where the relay is (once)

In `net.py`, set the name and port:

```python
DEFAULT_SERVER = "oilboard.duckdns.org:47800"
```

Then commit and push: every player gets it with the Update button. Until then, one device can try a
relay by putting `"online_server": "oilboard.duckdns.org:47800"` in its `saves/settings.json` (in the app:
`~/Library/Application Support/OIL/saves/settings.json`), or by starting the game with
`OIL_SERVER=oilboard.duckdns.org:47800`.

## Checking it works

- **On the relay's computer:** `tail ~/Library/Logs/oil-relay.log` should show
  `OIL relay ... listening on port 47800`, and a line for every game opened and joined.
- **From outside:** use a laptop on a phone's hotspot (not the home Wi-Fi). Online Game › Join should
  say nothing about the server being unreachable, and show the games hosted at home as **Online**.
- **Inside the home:** devices find the relay through the local network, even when the router can't
  reach its own public address from inside.

## Updating the relay

The relay passes messages along without looking inside them, so game updates don't need a new relay.
Only when `RELAY_PROTOCOL` in `relay.py` changes do you need to update it on the home computer: pull
the new version and run `install.sh` again. Until then, the game says it can't reach the online server
and only shows local-network games.
