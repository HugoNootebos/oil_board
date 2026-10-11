"""
Starts OIL as an app: the Mac app (OIL.app, build_mac.sh) and the Windows
shortcuts (oil_installer.iss) run this with the Python that comes with
the app. It's the one piece of the game that stays as it was built for as
long as the app is installed, so it only does what can't be done from the
game's own files: everything else, the updater too (updater.py), is in the
game and is updated with it.

Everything lives in the device's data folder (DATA_DIR):
    game/    the game's files, which the Update button replaces
    libs/    Python libraries an update installed (until then: the app's own)
    saves/   saves and settings.json, which no update touches
    crash.log, update.log

At every start:
  1. A start after an update that never reached the main menu (update.trial
     is still there) goes back to the previous version (game.old, libs.old).
  2. A downloaded update (update.ready) is put in place: game.new -> game,
     libs.new -> libs, the old ones kept as game.old and libs.old. Done here,
     before any game file is opened: Windows can't rename a folder while a
     file in it is open.
  3. The first start copies the game that came with the app into game/.
  4. game/runner.py runs, with the folders above in OIL_* variables.

Run from the game's folder (python3 packaging/bootstrap.py) it plays the
app with that folder as the game that came with it and this Python's own
libraries; OIL_DATA_DIR=<folder> keeps it out of the real data folder.
"""

import json
import os
import runpy
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
# Not copied from a game folder into the app's: the developer's own files.
SKIP = shutil.ignore_patterns("saves", "__pycache__", ".git", ".github", ".backups", "bot_research",
                              "build", "dist", ".DS_Store")


def data_dir():
    if os.environ.get("OIL_DATA_DIR"):
        return os.path.abspath(os.environ["OIL_DATA_DIR"])
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/OIL")
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "OIL")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "OIL")


def bundled():
    """(game, libs) that came with the app: next to this file. Run from a
    game folder (packaging/bootstrap.py), that folder and no libraries."""
    game = os.path.join(HERE, "game")
    if os.path.isfile(os.path.join(game, "runner.py")):
        libs = os.path.join(HERE, "libs")
        return game, (libs if os.path.isdir(libs) else None)
    return os.path.dirname(HERE), None


def log(data, name, text):
    try:
        with open(os.path.join(data, name), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
    except OSError:
        pass


def roll_back(data):
    """The last update never got as far as the main menu: back to before it."""
    trial = os.path.join(data, "update.trial")
    if not os.path.exists(trial):
        return
    try:
        with open(trial) as f:
            swapped = json.load(f).get("swapped", [])
    except (OSError, ValueError, AttributeError):
        swapped = []
    for name in swapped:
        current, old = os.path.join(data, name), os.path.join(data, name + ".old")
        if os.path.isdir(old):
            shutil.rmtree(current, ignore_errors=True)
            os.rename(old, current)
        elif name == "libs":
            shutil.rmtree(current, ignore_errors=True)  # back to the app's own libraries
    os.remove(trial)
    log(data, "update.log", "the update didn't start: back to the previous version")


def put_update_in_place(data):
    ready = os.path.join(data, "update.ready")
    if os.path.exists(ready):
        try:
            with open(ready) as f:
                libs = bool(json.load(f).get("libs"))
        except (OSError, ValueError, AttributeError):
            libs = False
        swapped = []
        for name in ("game", "libs") if libs else ("game",):
            new, current, old = (os.path.join(data, name + end) for end in (".new", "", ".old"))
            if not os.path.isdir(new):
                continue
            shutil.rmtree(old, ignore_errors=True)
            if os.path.isdir(current):
                os.rename(current, old)
            os.rename(new, current)
            swapped.append(name)
        with open(os.path.join(data, "update.trial"), "w") as f:
            json.dump({"swapped": swapped}, f)
        os.remove(ready)
    for leftover in ("game.new", "libs.new"):  # of an update that didn't finish
        shutil.rmtree(os.path.join(data, leftover), ignore_errors=True)


def prepare(data):
    """Steps 1-3 and the OIL_* variables; returns (game, libs) folders,
    libs None for this Python's own."""
    os.makedirs(data, exist_ok=True)
    roll_back(data)
    put_update_in_place(data)

    bundled_game, bundled_libs = bundled()
    game = os.path.join(data, "game")
    if not os.path.isfile(os.path.join(game, "runner.py")):
        shutil.rmtree(game, ignore_errors=True)
        shutil.copytree(bundled_game, game, ignore=SKIP)
    libs = os.path.join(data, "libs")
    if not os.path.isdir(libs):
        libs = bundled_libs
    saves = os.path.join(data, "saves")
    os.makedirs(saves, exist_ok=True)

    os.environ["OIL_DATA_DIR"] = data
    os.environ["OIL_GAME_DIR"] = game
    os.environ["OIL_SAVES_DIR"] = saves
    if libs:
        os.environ["OIL_LIBS_DIR"] = libs
    else:
        os.environ.pop("OIL_LIBS_DIR", None)
    # How to start again after an update: the Mac app's launcher script, or
    # this file with this Python as it was started.
    if os.environ.get("OIL_LAUNCHER"):
        restart = [os.environ["OIL_LAUNCHER"]]
    else:
        flags = ["-I"] if sys.flags.isolated else (["-s"] if sys.flags.no_user_site else [])
        restart = [sys.executable] + flags + [os.path.abspath(__file__)]
    os.environ["OIL_RESTART"] = json.dumps(restart)
    return game, libs


def main():
    data = data_dir()
    game, libs = prepare(data)
    if sys.path and os.path.abspath(sys.path[0] or ".") == HERE:
        sys.path.pop(0)  # this folder isn't the game's
    sys.path[:0] = [game] + ([libs] if libs else [])
    if sys.stdout is None or sys.stderr is None:  # pythonw on Windows
        sys.stdout = sys.stderr = open(os.path.join(data, "output.log"), "w", encoding="utf-8")
    if os.name == "nt":
        try:  # the taskbar shows OIL's icon rather than Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HugoNootebos.OIL")
        except Exception:
            pass

    try:
        runpy.run_path(os.path.join(game, "runner.py"), run_name="__main__")
    except SystemExit:
        raise
    except BaseException:
        log(data, "crash.log", traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
