"""
The OIL relay on a Windows computer at home: install.ps1 copies this next
to relay.py and starts it at every login (the Windows counterpart of
nl.oil.relay.plist). It runs the relay without a window, logs to
oil-relay.log next to it, keeps the computer from going to sleep on its
own while it runs (as caffeinate -i does on the Mac), starts the relay
again when it stops, and keeps NAME.duckdns.org pointing at this home's
address when duckdns.json ({"name": ..., "token": ...}) is there.

    pythonw oil_relay.pyw [--port 47800]
"""

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback

import relay  # the copy next to this file

CURL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "oil-relay.log")
MAX_LOG = 1024 * 1024  # bytes: a longer log becomes oil-relay.old.log at the start
DUCKDNS_EVERY = 300    # seconds
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def _duckdns(name, token):
    """Every DUCKDNS_EVERY seconds: tell DuckDNS this home's address (it
    takes the one the request comes from), with Windows' own curl: Python's
    ssl only trusts the root certificates Windows happens to have fetched
    already, which needn't include DuckDNS's. Logs only what changes."""
    url = "https://www.duckdns.org/update?domains={}&token={}&ip=".format(name, token)
    last = None
    while True:
        try:
            done = subprocess.run([CURL, "-s", "-m", "30", url], stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            answer = done.stdout.decode("ascii", "replace").strip()  # OK, or KO: wrong name/token
            if done.returncode or not answer:
                answer = "unreachable (curl error {})".format(done.returncode)
        except (OSError, subprocess.SubprocessError) as error:
            answer = "unreachable ({})".format(error)
        if answer != last:
            relay._log("DuckDNS {}.duckdns.org: {}".format(name, answer))
            last = answer
        time.sleep(DUCKDNS_EVERY)


def main():
    if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_LOG:
        os.replace(LOG, os.path.join(HERE, "oil-relay.old.log"))
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)  # pythonw has none
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        with open(os.path.join(HERE, "duckdns.json"), encoding="utf-8-sig") as file:
            duck = json.load(file)
    except (OSError, ValueError):
        duck = {}
    if isinstance(duck, dict) and duck.get("name") and duck.get("token"):
        threading.Thread(target=_duckdns, args=(duck["name"], duck["token"]), daemon=True).start()
    wait = 10
    while True:
        started = time.time()
        try:
            relay.main()  # takes --port from sys.argv
        except OSError as error:
            relay._log("The relay can't start:", error)  # e.g. its port is taken (a game's own LAN relay)
        except Exception:
            traceback.print_exc()
        if time.time() - started > 600:
            wait = 10
        relay._log("The relay stopped; starting it again in {} s".format(wait))
        time.sleep(wait)
        wait = min(2 * wait, 300)


if __name__ == "__main__":
    main()
