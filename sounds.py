"""Sound effects and background music (mp3 files in sounds/).

Every call is safe when there is no audio device (headless runs): sounds
just don't play. The background music is kept very soft and is never
muted: effects play on top of it."""
import os
import pygame as pg

SOUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
BACKGROUND_FILE = "background.mp3"
BACKGROUND_VOLUME = 0.18

_sounds = {}
_ok = None
_last_mouse_ms = -10000
_click_pending = False  # a click this frame, sounded by frame_end unless it was invalid
_error_played = False
VOLUMES = {"click": 0.5, "abomb": 0.25, "conquer_country": 0.2}  # per-sound volume (default 1.0)


def _ready():
    global _ok
    if _ok is None:
        if os.environ.get("SDL_VIDEODRIVER") == "dummy":  # headless run: stay silent
            _ok = False
            return _ok
        try:
            if not pg.mixer.get_init():
                pg.mixer.init()
            _ok = True
        except pg.error:
            _ok = False
    return _ok


def start_background():
    """Loop the background music softly (no-op if it already plays)."""
    if not _ready():
        return
    try:
        if not pg.mixer.music.get_busy():
            pg.mixer.music.load(os.path.join(SOUND_DIR, BACKGROUND_FILE))
            pg.mixer.music.set_volume(BACKGROUND_VOLUME)
            pg.mixer.music.play(-1)
    except (pg.error, FileNotFoundError):
        pass


def play(name):
    """Play sounds/<name>.mp3 over the background music."""
    global _last_mouse_ms, _error_played
    if name == "error":
        _error_played = True
    if not _ready():
        return
    if name == "mouse":
        _last_mouse_ms = pg.time.get_ticks()
    try:
        sound = _sounds.get(name)
        if sound is None:
            sound = _sounds[name] = pg.mixer.Sound(os.path.join(SOUND_DIR, name + ".mp3"))
        sound.set_volume(VOLUMES.get(name, 1.0))
        sound.play()
    except (pg.error, FileNotFoundError):
        pass


def watch_owners(engine):
    """Once per frame: any country that changed hands (conquest, events,
    nukes, pagoda/torii penalties...) plays conquer_country. The first
    call after a game starts or loads (snapshot None) only records."""
    owners = {name: c.owner for name, c in engine.countries.items()}
    before = getattr(engine, "_owner_snapshot", None)
    engine._owner_snapshot = owners
    if before is None or before.keys() != owners.keys():
        return
    changed = [n for n in owners if before[n] is not owners[n]]
    if not changed:
        return
    if pg.time.get_ticks() - _last_mouse_ms <= 400:  # the mouse sound already covers it
        return
    mouse = engine.default_player
    if any(owners[n] is mouse for n in changed):
        # Taken by the mouse: mouse.mp3 -- except a pagoda/torii penalty,
        # which has its own sound with its pop-up.
        if not any(getattr(x, "icon", None) in ("pagoda", "torii")
                   for x in engine.turn_manager.notices):
            play("mouse")
    else:
        play("conquer_country")


# --- clicks that do nothing ------------------------------------------
# A click on a country that nobody consumed and that changed nothing in
# the game (no phase step, no units, no selection...) is an invalid click
# and plays error.mp3 -- once the button is released, so starting to
# drag/pan the map over a country stays silent.
_pending_error = None  # mouse position of the click, until released
DRAG_TOLERANCE = 6


def _simple(value):
    if isinstance(value, (int, float, str, bool, type(None))):
        return value
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(map(repr, value))) if isinstance(value, set) else tuple(_simple(v) for v in value)
    if isinstance(value, dict):
        return tuple((repr(k), _simple(v)) for k, v in value.items())
    return type(value).__name__


def _fingerprint(engine):
    manager = engine.turn_manager
    parts = [engine.turn, engine.settings_open, len(manager.notices)]
    for phase in manager.phases.values():
        parts.append(tuple((k, _simple(v)) for k, v in vars(phase).items()
                           if not any(t in k for t in ("timer", "_at", "_ms", "manager"))))
    for player in engine.players:
        parts.append((player.attack, player.subattack, player.food, player.wood, player.steel,
                      player.oil, player.nuclear, player.troops, len(player.cards)))
    for c in engine.countries.values():
        parts.append((id(c.owner), c.units, c.ships, c.tanks, c.planes, c.fort_lvl,
                      c.airport, c.radioactive, id(getattr(c, "dormant_owner", None))))
    return hash(repr(parts))


def frame_start(engine):
    """Call right after the input for this frame is read. Returns what
    `frame_end` needs, or None if this frame holds no click to judge."""
    io = engine.io
    if not io.left_pressed or io.hover_country is None:
        return None
    if engine.bot_turn or engine.modal_open or engine.card_menu.show \
            or engine.turn_manager.dialog_active or engine.event_info_open:
        return None
    return _fingerprint(engine)


def click_pressed():
    """A left click arrived this frame (in the game, not the menus)."""
    global _click_pending
    _click_pending = True


def frame_end(engine, before):
    """Sounds this frame's click: error.mp3 instead of the click if it was
    invalid (a disabled button already played it during the frame)."""
    global _pending_error, _click_pending, _error_played
    if before is not None and engine.io.left_pressed and _fingerprint(engine) == before:
        m = engine.io.mouse_position
        _pending_error = (m.x, m.y)
        _click_pending = False  # decided on release: error, or nothing if it becomes a drag
    if _click_pending and not _error_played:
        play("click")
    if _pending_error is not None:
        m = engine.io.mouse_position
        if abs(m.x - _pending_error[0]) + abs(m.y - _pending_error[1]) > DRAG_TOLERANCE:
            _pending_error = None
        elif not engine.io.mouse_state[0]:
            _pending_error = None
            play("error")
    _click_pending = _error_played = False
