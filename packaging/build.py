"""
Builds the OIL app: the Python that comes with it (python-build-standalone,
pinned below), the libraries of requirements.txt, packaging/bootstrap.py and
a copy of the game for its very first start (after that the Update button
keeps the game up to date, see updater.py).

    python3 packaging/build.py mac-arm64 mac-x86_64   # on a Mac: dist/OIL-mac-*.zip
    python  packaging/build.py windows                # on Windows: build/windows/OIL,
                                                      # then oil_installer.iss -> dist/OIL-Setup.exe

The GitHub workflow (.github/workflows/build-app.yml) runs both and puts the
results in a GitHub Release. Only needed again to change the Python itself
or bootstrap.py: everything else reaches players through Update.

The game copy is this folder as it is (without saves/ and the other
SKIP folders); its game/.version is the git commit when the folder is a
clean git checkout, else unknown, so the first Update brings it in line
with GitHub.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "packaging")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")

PYTHON = "3.12"
RUNTIME_RELEASE = "20260924"
RUNTIME_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/{release}/"
               "cpython-3.12.14%2B{release}-{triple}-install_only_stripped.tar.gz")
TARGETS = {
    "mac-arm64": {
        "triple": "aarch64-apple-darwin",
        "sha256": "c2edb321cd32ec2b170df208db0446dccc4398db602ca27cf2079098fb1f7d9d",
        "platform": "macosx_11_0_arm64", "macos": "11.0", "zip": "OIL-mac-arm64.zip",
    },
    "mac-x86_64": {
        "triple": "x86_64-apple-darwin",
        "sha256": "7ea9761b9069c10b9a20531d568645849d604c59e9c7f11f6659f1e1790c968e",
        "platform": "macosx_10_13_x86_64", "macos": "10.13", "zip": "OIL-mac-intel.zip",
    },
    "windows": {
        "triple": "x86_64-pc-windows-msvc",
        "sha256": "c5bf8edfe858c1df9891be498b5bbc8761d383df5b9790658b088fea4870433a",
        "platform": "win_amd64",
    },
}

# Left out of the game copy (as updater.SKIP_DIRS), and out of the Python.
GAME_SKIP = ("saves", "__pycache__", ".git", ".github", ".backups", "bot_research", "build", "dist",
             ".DS_Store")
STDLIB_SKIP = ("test", "tests", "idlelib", "tkinter", "turtledemo", "__pycache__", "_tkinter*",
               "lib2to3", "ensurepip")


def run(*command, **kwargs):
    print("+", " ".join(command))
    return subprocess.run(command, check=True, **kwargs)


def runtime(name):
    """The python-build-standalone runtime of a target, unpacked (cached in build/)."""
    target = TARGETS[name]
    archive = os.path.join(BUILD, "cache", "{}-{}.tar.gz".format(target["triple"], RUNTIME_RELEASE))
    if not os.path.isfile(archive):
        os.makedirs(os.path.dirname(archive), exist_ok=True)
        url = RUNTIME_URL.format(release=RUNTIME_RELEASE, triple=target["triple"])
        print("downloading", url)
        with urllib.request.urlopen(url, context=_ssl()) as response, open(archive + ".part", "wb") as f:
            shutil.copyfileobj(response, f)
        os.replace(archive + ".part", archive)
    with open(archive, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != target["sha256"]:
            os.remove(archive)
            raise SystemExit("checksum mismatch: " + archive)
    unpacked = os.path.join(BUILD, "cache", target["triple"])
    if not os.path.isdir(unpacked):
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked + ".part")
        os.replace(unpacked + ".part", unpacked)
    return os.path.join(unpacked, "python")


def install_libraries(name, libs):
    """requirements.txt for the target's platform, into `libs`, with a copy
    of the file (updater.py compares it with an update's)."""
    target = TARGETS[name]
    shutil.rmtree(libs, ignore_errors=True)
    run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
        "--only-binary=:all:", "--platform", target["platform"], "--python-version", PYTHON,
        "--implementation", "cp", "--target", libs, "-r", os.path.join(ROOT, "requirements.txt"))
    shutil.rmtree(os.path.join(libs, "bin"), ignore_errors=True)
    shutil.copy2(os.path.join(ROOT, "requirements.txt"), os.path.join(libs, "requirements.txt"))


def copy_game(game):
    shutil.rmtree(game, ignore_errors=True)
    shutil.copytree(ROOT, game, ignore=shutil.ignore_patterns(*GAME_SKIP))
    with open(os.path.join(game, ".version"), "w") as f:
        json.dump(version(), f)


def version():
    """{"sha", "title"} of this folder: the git commit if nothing differs from it."""
    def git(*args):
        return subprocess.run(("git",) + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              check=True).stdout.decode().strip()
    try:
        sha, title = git("rev-parse", "HEAD"), git("log", "-1", "--format=%s")
        changed = git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        return {"sha": None, "title": None}
    if changed:  # not exactly that commit: the first Update brings it in line
        return {"sha": None, "title": title + " (local)"}
    return {"sha": sha, "title": title}


def build_mac(name):
    target = TARGETS[name]
    python = runtime(name)
    out = os.path.join(BUILD, name)
    app = os.path.join(out, "OIL.app")
    shutil.rmtree(out, ignore_errors=True)
    contents = os.path.join(app, "Contents")
    macos, resources = os.path.join(contents, "MacOS"), os.path.join(contents, "Resources")
    os.makedirs(macos)
    os.makedirs(resources)

    # The Python: its program next to the launcher in MacOS/ (so macOS sees
    # OIL, not Python, in the Dock and menu bar), its library in lib/ (where
    # Python looks for it, next to the folder it runs from).
    shutil.copy2(os.path.join(python, "bin", "python" + PYTHON), os.path.join(macos, "python3"))
    shutil.copytree(os.path.join(python, "lib", "python" + PYTHON),
                    os.path.join(contents, "lib", "python" + PYTHON),
                    ignore=shutil.ignore_patterns(*STDLIB_SKIP))
    launcher = os.path.join(macos, "OIL")
    with open(launcher, "w") as f:
        f.write(MAC_LAUNCHER)
    os.chmod(launcher, 0o755)
    with open(os.path.join(contents, "Info.plist"), "w") as f:
        f.write(INFO_PLIST.format(macos=target["macos"]))

    shutil.copy2(os.path.join(HERE, "bootstrap.py"), resources)
    install_libraries(name, os.path.join(resources, "libs"))
    copy_game(os.path.join(resources, "game"))
    make_icns(os.path.join(resources, "OIL.icns"))

    smoke_test(os.path.join(macos, "python3"), resources)
    run("codesign", "--force", "--deep", "--sign", "-", app)
    os.makedirs(DIST, exist_ok=True)
    archive = os.path.join(DIST, target["zip"])
    if os.path.exists(archive):
        os.remove(archive)
    run("ditto", "-c", "-k", "--keepParent", app, archive)
    print("built", archive)


def build_windows(name="windows"):
    python = runtime(name)
    out = os.path.join(BUILD, name, "OIL")
    shutil.rmtree(os.path.dirname(out), ignore_errors=True)
    shutil.copytree(python, os.path.join(out, "python"),
                    ignore=shutil.ignore_patterns("tcl", "include", *STDLIB_SKIP))
    shutil.copy2(os.path.join(HERE, "bootstrap.py"), out)
    install_libraries(name, os.path.join(out, "libs"))
    copy_game(os.path.join(out, "game"))
    from PIL import Image  # pip install pillow
    Image.open(os.path.join(HERE, "icon.png")).save(
        os.path.join(out, "OIL.ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    smoke_test(os.path.join(out, "python", "python.exe"), out)
    print("built", out, "- now: iscc packaging\\oil_installer.iss")


def smoke_test(python, resources):
    """The app's Python finds the libraries the game needs (when this
    machine can run it). -B: nothing may be written into the app."""
    try:
        subprocess.run([python, "-I", "-B", "-c", "pass"], check=True)
    except (OSError, subprocess.CalledProcessError):
        print("(can't run this Python here: not tested)")
        return
    run(python, "-I", "-B", "-c",
        "import sys; sys.path[:0] = [{!r}, {!r}]; import pygame, numpy, matplotlib.path, certifi, "
        "ssl, json, urllib.request; print('libraries OK')".format(
            os.path.join(resources, "game"), os.path.join(resources, "libs")))


def make_icns(path):
    iconset = os.path.join(BUILD, "OIL.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    source = os.path.join(HERE, "icon.png")
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = "icon_{0}x{0}{1}.png".format(size, "@2x" if scale == 2 else "")
            run("sips", "-z", str(size * scale), str(size * scale), source, "--out", os.path.join(iconset, name),
                stdout=subprocess.DEVNULL)
    run("iconutil", "-c", "icns", iconset, "-o", path)


def _ssl():
    try:
        import certifi
        import ssl
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


MAC_LAUNCHER = """#!/bin/sh
# Starts OIL with the Python inside the app; packaging/bootstrap.py does the rest.
# Compiled Python goes to the user's caches, so nothing in the app changes.
here="$(cd "$(dirname "$0")" && pwd)"
export OIL_LAUNCHER="$here/OIL"
exec "$here/python3" -I -X pycache_prefix="$HOME/Library/Caches/OIL" "$here/../Resources/bootstrap.py"
"""

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>OIL</string>
    <key>CFBundleDisplayName</key><string>OIL</string>
    <key>CFBundleIdentifier</key><string>com.hugonootebos.oil</string>
    <key>CFBundleExecutable</key><string>OIL</string>
    <key>CFBundleIconFile</key><string>OIL</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>{macos}</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.strategy-games</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSBluetoothAlwaysUsageDescription</key><string>OIL uses Bluetooth for game controllers.</string>
</dict>
</plist>
"""


if __name__ == "__main__":
    names = sys.argv[1:] or ["mac-arm64"]
    for name in names:
        if name not in TARGETS:
            raise SystemExit("unknown target {} (one of {})".format(name, ", ".join(TARGETS)))
        build_windows(name) if name == "windows" else build_mac(name)
