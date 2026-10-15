"""
The main menu's Update button: brings the installed app up to the latest
version of the game on GitHub (REPO, branch BRANCH).

Only active in the app (packaging/bootstrap.py sets OIL_DATA_DIR); run from
a copy of the game with `python3 runner.py` there is nothing to update.

The app keeps everything in the device's data folder (bootstrap.py):
    game/    these files, as of the version in game/.version
    libs/    the Python libraries of requirements.txt (until the first
             update that changes them, the ones inside the app are used)
    saves/   saves and settings: an update never touches them

An update is built next to the running game, in game.new/ (and libs.new/
when requirements.txt changed): the files that are the same as here are
copied, only the changed ones are downloaded (git's blob hash of each file
tells which). update.ready is written last; at its next start the app
swaps the new folders in before anything is opened (Windows can't rename
a folder while a file in it is open, such as the music playing), keeping
the old ones as game.old/libs.old. If that version then fails before the
main menu shows (mark_started), the app goes back to the old one.

Everything runs on a thread; the menu draws `state` every frame.
"""

import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request

REPO = "HugoNootebos/oil_board"
BRANCH = "Master"
API = "https://api.github.com/repos/" + REPO
RAW = "https://raw.githubusercontent.com/" + REPO

# Never taken from GitHub: the device's own saves, and files that are only
# there for developing the game.
SKIP_DIRS = {"saves", "__pycache__", ".git", ".github", ".backups", "bot_research", "build", "dist"}
SKIP_NAMES = {".DS_Store"}
# A version without these couldn't start or update itself any more.
NEEDED = ("runner.py", "updater.py")

VERSION_FILE = ".version"  # in game/: {"sha": ..., "title": ...}
READY_FILE = "update.ready"  # in the data folder: game.new (and libs.new) are complete
TRIAL_FILE = "update.trial"  # in the data folder: a new version hasn't reached the menu yet
LOG_FILE = "update.log"


def managed():
    """True when the app started the game (and it may update itself)."""
    return bool(os.environ.get("OIL_DATA_DIR"))


def _data_dir():
    return os.environ["OIL_DATA_DIR"]


def _game_dir():
    return os.environ.get("OIL_GAME_DIR") or os.path.dirname(os.path.abspath(__file__))


def installed():
    """{"sha", "title"} of the version that's running (both None if unknown)."""
    try:
        with open(os.path.join(_game_dir(), VERSION_FILE)) as f:
            version = json.load(f)
        return {"sha": version.get("sha"), "title": version.get("title")}
    except (OSError, ValueError, AttributeError):
        return {"sha": None, "title": None}


def mark_started():
    """The main menu is up: this version works, no going back to the old one."""
    if managed():
        try:
            os.remove(os.path.join(_data_dir(), TRIAL_FILE))
        except OSError:
            pass


def restart():
    """Start the app anew (which puts a downloaded update in place). The
    caller closes pygame first."""
    command = json.loads(os.environ["OIL_RESTART"])
    if os.name == "nt":
        # os.execv doesn't quote arguments on Windows (paths with spaces).
        # Not from the game's folder (runner.py's working directory): the
        # new app puts the update in place by renaming game/, and Windows
        # can't rename a folder that is a process's working directory.
        os.chdir(_data_dir())
        subprocess.Popen(command, cwd=_data_dir(), close_fds=True)
        os._exit(0)
    os.execv(command[0], command)


class UpdateState:
    """What the updater is doing, for the menu. status is one of:
    idle, checking, current (up to date), available, downloading,
    installing (libraries), ready (restart to use it), offline, failed,
    refused (the new version couldn't update itself)."""

    BUSY = ("checking", "downloading", "installing", "ready")

    def __init__(self):
        self.status = "idle"
        self.latest = None  # {"sha", "title"} on GitHub, once checked
        self.progress = 0.0  # of the download, 0..1
        self._thread = None

    @property
    def busy(self):
        return self.status in self.BUSY

    def start_check(self):
        """Look on GitHub whether there's a newer version (once per run)."""
        if managed() and self.status == "idle" and not self._running():
            self._start(self._check)

    def start_update(self):
        """The Update button: check, download, install; status "ready" when
        the app should restart."""
        if managed() and not self.busy and not self._running():
            self._start(self._update)

    def _running(self):
        return self._thread is not None and self._thread.is_alive()

    def _start(self, target):
        self._thread = threading.Thread(target=self._guarded, args=(target,), daemon=True)
        self._thread.start()

    def _guarded(self, target):
        try:
            target()
        except urllib.error.HTTPError as error:
            _log("GitHub answered {} {}".format(error.code, error.reason))
            self.status = "failed"
        except (urllib.error.URLError, socket.timeout) as error:
            _log("{}: {}".format(type(error).__name__, error))
            self.status = "offline"
        except Exception as error:  # never take the menu down with it
            _log("{}: {}".format(type(error).__name__, error))
            self.status = "failed"

    def _check(self):
        self.status = "checking"
        data = json.loads(_get(API + "/commits/" + BRANCH))
        message = data["commit"]["message"].strip()
        self.latest = {"sha": data["sha"], "title": message.splitlines()[0].strip() if message else data["sha"][:7]}
        self.status = "current" if self.latest["sha"] == installed()["sha"] else "available"

    def _update(self):
        self._check()
        if self.status == "current":
            return
        self.status = "downloading"
        self.progress = 0.0
        if _build_update(self.latest, self):
            self.status = "ready"
        elif self.status != "refused":
            self.status = "current"


state = UpdateState()


def _build_update(latest, update):
    """Builds game.new (and libs.new) for `latest` and marks them ready.
    Returns False when nothing needs replacing (then only .version is
    brought up to date) or the version is refused."""
    data, game = _data_dir(), _game_dir()
    ready = os.path.join(data, READY_FILE)
    if os.path.exists(ready):
        os.remove(ready)
    sha = latest["sha"]
    tree = json.loads(_get(API + "/git/trees/" + sha + "?recursive=1"))
    if tree.get("truncated"):
        raise RuntimeError("file list too long")
    files = {item["path"]: (item["sha"], item.get("size", 0)) for item in tree["tree"]
             if item["type"] == "blob" and item.get("mode") in ("100644", "100755") and _wanted(item["path"])}
    if not all(name in files for name in NEEDED):
        _log("{} lacks {}: not installed".format(sha, ", ".join(n for n in NEEDED if n not in files)))
        update.status = "refused"
        return False

    changed = [path for path, (blob, _) in files.items()
               if not os.path.isfile(os.path.join(game, path)) or _blob_sha(os.path.join(game, path)) != blob]
    removed = [path for path in _local_files(game) if path not in files]
    new_requirements = _requirements_changed(files, changed, sha)
    version = {"sha": sha, "title": latest["title"]}
    if not changed and not removed and new_requirements is None:
        _write_json(os.path.join(game, VERSION_FILE), version)
        return False

    new = os.path.join(data, "game.new")
    shutil.rmtree(new, ignore_errors=True)
    for path in files:
        if path not in changed:
            _copy(os.path.join(game, path), os.path.join(new, path))
    total = sum(files[path][1] for path in changed) or 1
    done = 0
    for path in changed:
        target = os.path.join(new, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            for chunk in _stream(RAW + "/" + sha + "/" + urllib.request.quote(path)):
                f.write(chunk)
                done += len(chunk)
                update.progress = min(1.0, done / total)
        if _blob_sha(target) != files[path][0]:
            raise RuntimeError("{} arrived damaged".format(path))
    _write_json(os.path.join(new, VERSION_FILE), version)

    libs = new_requirements is not None
    if libs:
        update.status = "installing"
        _install_libraries(os.path.join(new, "requirements.txt"), os.path.join(data, "libs.new"))
    _write_json(ready, {"sha": sha, "libs": libs})
    _log("ready: {} ({} files downloaded, {} removed{})".format(
        latest["title"], len(changed), len(removed), ", new libraries" if libs else ""))
    return True


def _requirements_changed(files, changed, sha):
    """The new requirements.txt's text if it differs from what the
    libraries in use were installed from, else None."""
    if "requirements.txt" not in files:
        return None
    if "requirements.txt" in changed:
        new = _get(RAW + "/" + sha + "/requirements.txt").decode("utf-8")
    else:
        new = _read(os.path.join(_game_dir(), "requirements.txt"))
    # The libraries were installed from a copy of requirements.txt kept
    # with them; without one (no OIL_LIBS_DIR: the libraries this Python
    # has) they're taken to match the game's own file.
    libs = os.environ.get("OIL_LIBS_DIR")
    current = _read(os.path.join(libs, "requirements.txt")) if libs else None
    if current is None:
        current = _read(os.path.join(_game_dir(), "requirements.txt"))
    return None if _lines(new) == _lines(current) else new


def _install_libraries(requirements, target):
    """pip-installs `requirements` into `target` with the app's own Python,
    keeping a copy of the file there (see _requirements_changed)."""
    shutil.rmtree(target, ignore_errors=True)
    python, flags = sys.executable, 0
    if os.name == "nt":
        # pythonw has no console; python.exe without a window gives pip one to write to.
        console = os.path.join(os.path.dirname(python), "python.exe")
        python = console if os.path.isfile(console) else python
        flags = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        [python, "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
         "--only-binary=:all:", "--target", target, "-r", requirements],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags, timeout=1800)
    if result.returncode != 0:
        _log(result.stdout.decode("utf-8", "replace")[-4000:])
        raise RuntimeError("pip failed")
    shutil.copy2(requirements, os.path.join(target, "requirements.txt"))


def _wanted(path):
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts) or path.startswith("/"):
        return False
    return parts[0] not in SKIP_DIRS and parts[-1] not in SKIP_NAMES and "__pycache__" not in parts


def _local_files(game):
    """The game's files as repo paths (a/b.py), without the skipped ones."""
    for root, dirs, names in os.walk(game):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            path = os.path.relpath(os.path.join(root, name), game).replace(os.sep, "/")
            if path != VERSION_FILE and _wanted(path):
                yield path


def _blob_sha(path):
    """The hash git gives the file's contents (as in GitHub's file list)."""
    digest = hashlib.sha1(b"blob %d\0" % os.path.getsize(path))
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ssl_context():
    # python.org's Python on macOS has no certificates of its own.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url):
    request = urllib.request.Request(url, headers={"User-Agent": "OIL-updater",
                                                   "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=30, context=_ssl_context())


def _get(url):
    with _open(url) as response:
        return response.read()


def _stream(url):
    with _open(url) as response:
        for chunk in iter(lambda: response.read(1 << 16), b""):
            yield chunk


def _copy(source, target):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source, target)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip() and not line.strip().startswith("#")]


def _write_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(value, f)
    os.replace(temporary, path)


def _log(line):
    try:
        with open(os.path.join(_data_dir(), LOG_FILE), "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except (OSError, KeyError):
        pass
