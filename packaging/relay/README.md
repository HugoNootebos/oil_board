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

### On a Windows computer instead

It needs Python 3.7 or newer from python.org (the game app's own Python isn't used).

1. **First** let the relay through Windows' firewall. Open PowerShell as administrator (right-click
   Start › *Windows PowerShell (Admin)*) and run this, with the path of your Python's `pythonw.exe`
   (step 2 prints the exact line when the rule is missing):

   ```powershell
   New-NetFirewallRule -DisplayName "OIL relay" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 47800 -Program "C:\...\Python312\pythonw.exe"
   ```

   Without it, Windows asks the first time the relay starts, and *Cancel* there, or allowing only
   private networks while Windows calls the home network public, blocks it for good.
2. In an ordinary PowerShell (not the administrator one: it refuses to run there), in this game folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\relay\install.ps1
   ```

   It copies `relay.py` and `oil_relay.pyw` to `%LOCALAPPDATA%\OIL-relay` and starts the relay now and
   at every login (a shortcut in the Startup folder; no window). It keeps running, starts again when it
   stops, and keeps the computer from going to sleep on its own while it does. Its log is
   `%LOCALAPPDATA%\OIL-relay\oil-relay.log`. Run it again after `relay.py` changes; `-Remove` takes it
   out again.

The relay runs while someone is signed in: locking the screen is fine, signing out stops it, and after
Windows restarts (for an update, say) someone has to sign in once.

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

**Two routers** (your own Wi-Fi router behind the provider's box: `tracert 1.1.1.1` on Windows,
`traceroute 1.1.1.1` on a Mac, shows two private addresses such as `192.168.x.x` before the public
ones): forward the port on both. On your own router, forward TCP 47800 to the computer. On the
provider's box, forward it to your own router's internet (WAN) address, which its status page shows.
Give the computer and your own router fixed addresses.

## 3. A fixed name for the home address (once)

The home's public address changes now and then, so the game connects to a name that keeps following it.

1. Go to https://www.duckdns.org, sign in, and create a subdomain, e.g. `oilboard` (that gives
   `oilboard.duckdns.org`). Copy the token shown there.
2. On the relay's computer, run:

   ```bash
   sh packaging/relay/install.sh oilboard YOUR-TOKEN
   ```

   This also keeps the name pointing at the home address, every 5 minutes. On Windows:

   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\relay\install.ps1 oilboard YOUR-TOKEN
   ```

   (the relay does it itself then; the token is kept in `%LOCALAPPDATA%\OIL-relay\duckdns.json`).

Many routers can do this themselves instead (a *DDNS* setting). Use that if you prefer.

## 4. Tell the game where the relay is (once)

In `net.py`, set the name and port:

```python
DEFAULT_SERVER = "oilboard.duckdns.org:47800"
```

Then commit and push: every player gets it with the Update button. Until then, one device can try a
relay by putting `"online_server": "oilboard.duckdns.org:47800"` in its `saves/settings.json` (in the app:
`~/Library/Application Support/OIL/saves/settings.json`, on Windows
`%LOCALAPPDATA%\OIL\saves\settings.json`), or by starting the game with
`OIL_SERVER=oilboard.duckdns.org:47800`.

## Checking it works

- **On the relay's computer:** `tail ~/Library/Logs/oil-relay.log` (Windows:
  `Get-Content $env:LOCALAPPDATA\OIL-relay\oil-relay.log -Tail 20`) should show
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
