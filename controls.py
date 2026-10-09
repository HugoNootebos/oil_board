"""
Game controllers (Xbox, PlayStation, Switch Pro, ...): every player can
use their own, each with its own cursor on screen. A controller drives its
cursor like a mouse:

    left stick   move the cursor        A      left click
    right stick  pan the map            B      right click
    LB / RB      zoom out / in          Start  settings menu

In the game only the acting player's controller clicks
(TurnManager.acting_player: whoever's turn it is, a human defender picking
tanks or dice, an event's chooser); the others can still move their
cursor around, drawn faded. On a bot's turn every paired controller may
click (the bot's phase takes no clicks, so that's the settings and event
buttons, the map's hover panels, panning and zooming). The real mouse
keeps working for everyone. In the start menus every controller clicks.

Controllers are paired with players by name: on the player-names screen
(menu.py) or in the game's Controllers panel (Engine._draw_pairing).
Pairings aren't saved: SDL numbers the controllers anew every session.

Cursors live in the logical 960x640 UI space, the same in the menus (drawn
on their canvas) as in the game (Engine.present scales them).
"""

import itertools

import pygame as pg

from fonts import game_font

try:
    from pygame._sdl2 import controller as sdl_controller
except ImportError:  # a pygame without SDL2's game controller support
    sdl_controller = None

WIDTH, HEIGHT = 960, 640
DEADZONE = 0.2  # of a stick's full tilt
CURSOR_SPEED = 700  # logical px per second at full tilt
PAN_SPEED = 650  # logical px per second at full tilt
MAX_DT = 50  # ms: a longer gap (the game loop idling) doesn't make a cursor jump
UNPAIRED_COLOR = (235, 235, 235)
FADED_ALPHA = 110

A = pg.CONTROLLER_BUTTON_A
B = pg.CONTROLLER_BUTTON_B
START = pg.CONTROLLER_BUTTON_START
ZOOM_BUTTONS = {pg.CONTROLLER_BUTTON_LEFTSHOULDER: -1, pg.CONTROLLER_BUTTON_RIGHTSHOULDER: 1}

# The arrow cursor in logical px, tip at (0, 0).
CURSOR_SIZE = 1.25
ARROW = [(x * CURSOR_SIZE, y * CURSOR_SIZE)
         for x, y in [(0, 0), (0, 20), (5, 15.5), (8.5, 23.5), (12, 22), (8.5, 14.5), (14.5, 14.5)]]


def _stick(x, y):
    """Raw stick axes -> (dx, dy) of length 0..1: nothing inside the
    deadzone, then quadratic, so a small tilt gives fine control."""
    x, y = x / 32767.0, y / 32767.0
    length = (x * x + y * y) ** 0.5
    if length < DEADZONE:
        return 0.0, 0.0
    strength = min(1.0, (length - DEADZONE) / (1 - DEADZONE)) ** 2
    return x / length * strength, y / length * strength


class Pad:
    """One connected controller and its cursor."""

    def __init__(self, controller, instance_id, number):
        self.controller = controller
        self.instance_id = instance_id
        self.number = number  # 1, 2, ...: how the pairing buttons call it
        # Start apart, so the cursors don't hide each other.
        self.x = WIDTH * 0.5 + 30 * (number - 1)
        self.y = HEIGHT * 0.5 + 20 * (number - 1)
        self.held = set()
        self.taps = []  # buttons pressed since the last frame
        self.pan = (0.0, 0.0)  # logical px the right stick pans this frame
        self.moving = False  # a stick is tilted
        self.last_active = -1  # ticks it was last used
        self.led = None

    @property
    def pos(self):
        return int(self.x), int(self.y)

    @property
    def pressed(self):
        """Like pg.mouse.get_pressed(): (A, -, B). A tap shorter than a
        frame still counts as held for the frame it came in."""
        return (A in self.held or A in self.taps, False, B in self.held or B in self.taps)

    @property
    def fresh(self):
        """Which of `pressed` were pressed this frame."""
        return (A in self.taps, False, B in self.taps)

    def tapped(self, button):
        return button in self.taps

    @property
    def zoom_steps(self):
        """+1 per zoom-in (RB) press this frame, -1 per zoom-out (LB)."""
        return [ZOOM_BUTTONS[b] for b in self.taps if b in ZOOM_BUTTONS]

    def axis(self, axis):
        try:
            return self.controller.get_axis(axis)
        except pg.error:
            return 0

    def set_led(self, color):
        """Light the controller (where it has a light) in `color`."""
        if color == self.led:
            return
        self.led = color
        try:
            self.controller.set_led(color)
        except (pg.error, AttributeError):
            pass


class Controls:

    def __init__(self):
        self.pads = []
        self.bindings = {}  # instance_id -> player name
        # Players whose controller was unplugged: the next one plugged in is
        # theirs, when that leaves no doubt (only one of them).
        self.waiting = []
        self.mouse_active = 0  # ticks the mouse was last moved or clicked
        self.mouse_fresh = (False, False, False)  # its buttons pressed this frame
        # The controllers that may click this frame, in the game (`frame`).
        self.clickers = []
        self._ticks = None
        self._cursor_visible = True
        self._sprites = {}
        if sdl_controller is not None:
            sdl_controller.init()
            for index in range(sdl_controller.get_count()):  # those already plugged in
                self._add(index)

    # --- connecting and pairing -------------------------------------------

    def _add(self, device_index):
        if sdl_controller is None or not sdl_controller.is_controller(device_index):
            return
        try:
            controller = sdl_controller.Controller(device_index)
            instance_id = controller.as_joystick().get_instance_id()
        except pg.error:
            return
        if self.pad(instance_id) is not None:
            return  # SDL also announces the ones already open at the start
        used = {pad.number for pad in self.pads}
        pad = Pad(controller, instance_id, next(n for n in itertools.count(1) if n not in used))
        self.pads.append(pad)
        if len(self.waiting) == 1:
            self.bind(pad, self.waiting[0])

    def _remove(self, instance_id):
        pad = self.pad(instance_id)
        if pad is None:
            return
        self.pads.remove(pad)
        name = self.bindings.pop(instance_id, None)
        if name is not None:
            self.waiting.append(name)

    def pad(self, instance_id):
        return next((pad for pad in self.pads if pad.instance_id == instance_id), None)

    def pad_of(self, name):
        """The controller paired with the player called `name`, if any."""
        return next((pad for pad in self.pads if self.bindings.get(pad.instance_id) == name), None)

    def player_of(self, pad, players):
        """The (human) player among `players` that `pad` is paired with."""
        name = self.bindings.get(pad.instance_id)
        return next((p for p in players if p.name == name and not p.is_bot), None)

    def bind(self, pad, name):
        """Pair `pad` with the player called `name` (None: unpair it). A
        player has one controller at most."""
        if name is not None:
            for other in self.pads:
                if self.bindings.get(other.instance_id) == name:
                    del self.bindings[other.instance_id]
            self.bindings[pad.instance_id] = name
            if name in self.waiting:
                self.waiting.remove(name)
        else:
            self.bindings.pop(pad.instance_id, None)

    def pair_all(self, pairs):
        """Start over with these (pad, name) pairs (a new game's)."""
        self.bindings = {}
        self.waiting = []
        for pad, name in pairs:
            if pad in self.pads:
                self.bind(pad, name)

    def needs_pairing(self, players):
        """A controller nobody has, and a human player without one."""
        humans = [p for p in players if not p.is_bot]
        return (any(self.player_of(pad, humans) is None for pad in self.pads)
                and any(self.pad_of(p.name) is None for p in humans))

    # --- input --------------------------------------------------------------

    @property
    def busy(self):
        """A stick is tilted: keep drawing frames, events or not."""
        return any(pad.moving for pad in self.pads)

    def handle_events(self, events):
        """Read this frame's events (call once a frame, before the input is
        used) and move the cursors."""
        now = pg.time.get_ticks()
        for pad in self.pads:
            pad.taps = []
        mouse_fresh = [False, False, False]
        for event in events:
            if event.type == pg.CONTROLLERDEVICEADDED:
                self._add(event.device_index)
            elif event.type == pg.CONTROLLERDEVICEREMOVED:
                self._remove(event.instance_id)
            elif event.type in (pg.CONTROLLERBUTTONDOWN, pg.CONTROLLERBUTTONUP):
                pad = self.pad(event.instance_id)
                if pad is None:
                    continue
                if event.type == pg.CONTROLLERBUTTONDOWN:
                    pad.held.add(event.button)
                    pad.taps.append(event.button)
                    pad.last_active = now
                else:
                    pad.held.discard(event.button)
            elif event.type == pg.MOUSEMOTION:
                if event.rel != (0, 0):  # not one made by hiding/showing the cursor
                    self.mouse_active = now
            elif event.type == pg.MOUSEWHEEL:
                self.mouse_active = now
            elif event.type == pg.MOUSEBUTTONDOWN:
                self.mouse_active = now
                if 1 <= event.button <= 3:
                    mouse_fresh[event.button - 1] = True
        self.mouse_fresh = tuple(mouse_fresh)

        dt = 0 if self._ticks is None else min(MAX_DT, max(0, now - self._ticks)) / 1000.0
        self._ticks = now
        for pad in self.pads:
            dx, dy = _stick(pad.axis(pg.CONTROLLER_AXIS_LEFTX), pad.axis(pg.CONTROLLER_AXIS_LEFTY))
            px, py = _stick(pad.axis(pg.CONTROLLER_AXIS_RIGHTX), pad.axis(pg.CONTROLLER_AXIS_RIGHTY))
            pad.moving = bool(dx or dy or px or py)
            if pad.moving:
                pad.last_active = now
            pad.x = min(max(pad.x + dx * CURSOR_SPEED * dt, 0), WIDTH - 1)
            pad.y = min(max(pad.y + dy * CURSOR_SPEED * dt, 0), HEIGHT - 1)
            pad.pan = (px * PAN_SPEED * dt, py * PAN_SPEED * dt)

    def frame(self, engine):
        """In the game: decide which controllers may click this frame (see
        the module docstring) and return the pointer Io follows -- the one
        of them used last, or None (the mouse) when the mouse was used more
        recently."""
        if engine.pairing_open:
            self.clickers = list(self.pads)
        else:
            acting = engine.turn_manager.acting_player()
            if acting.is_bot:
                self.clickers = [pad for pad in self.pads if self.player_of(pad, engine.players)]
            else:
                self.clickers = [pad for pad in self.pads
                                 if self.bindings.get(pad.instance_id) == acting.name]
        source = self._latest(self.clickers)
        self._show_cursor(source is None)
        return source

    def fresh(self, source):
        """Buttons of `source` (a Pad, or None for the mouse) pressed this frame."""
        return source.fresh if source is not None else self.mouse_fresh

    def _latest(self, pads):
        latest = max(pads, key=lambda pad: pad.last_active, default=None)
        if latest is None or latest.last_active <= self.mouse_active:
            return None
        return latest

    def menu_input(self, events, scale):
        """For the start menus (drawn at 960x640, shown `scale` times that):
        reads the events, returns (hover position, clicks). Every
        controller clicks there; a click is (position, pad), pad None for
        the mouse."""
        self.handle_events(events)
        clicks = [((round(e.pos[0] / scale), round(e.pos[1] / scale)), None)
                  for e in events if e.type == pg.MOUSEBUTTONDOWN and e.button == 1]
        clicks += [(pad.pos, pad) for pad in self.pads if pad.tapped(A)]
        latest = self._latest(self.pads)
        self._show_cursor(latest is None)
        if latest is not None:
            return latest.pos, clicks
        x, y = pg.mouse.get_pos()
        return (round(x / scale), round(y / scale)), clicks

    def _show_cursor(self, visible):
        """The system's mouse cursor is hidden while a controller was used last."""
        if visible != self._cursor_visible:
            self._cursor_visible = visible
            pg.mouse.set_visible(visible)

    # --- drawing ------------------------------------------------------------

    def draw(self, surface, scale=1.0, offset=(0, 0), looks=None):
        """Every controller's cursor on `surface`, at its logical position
        times `scale` plus `offset`. looks: pad -> (color, faded); white
        and numbered when it's not given (an unpaired controller)."""
        for pad in self.pads:
            color, faded = (looks or {}).get(pad, (UNPAIRED_COLOR, False))
            number = pad.number if color == UNPAIRED_COLOR else None
            sprite, margin = self._sprite(color, faded, scale, number)
            surface.blit(sprite, (round(offset[0] + pad.x * scale) - margin,
                                  round(offset[1] + pad.y * scale) - margin))

    def _sprite(self, color, faded, scale, number):
        key = (tuple(color), faded, round(scale, 3), number)
        if key not in self._sprites:
            margin = max(2, round(2 * scale))
            points = [(margin + x * scale, margin + y * scale) for x, y in ARROW]
            w, h = int(16 * CURSOR_SIZE * scale) + 2 * margin, int(25 * CURSOR_SIZE * scale) + 2 * margin
            label = None
            if number is not None:
                label = game_font(max(8, int(14 * scale)), bold=True).render(str(number), True, (0, 0, 0))
                w += label.get_width() + margin
            sprite = pg.Surface((w, h), pg.SRCALPHA)
            pg.draw.polygon(sprite, color, points)
            pg.draw.polygon(sprite, (0, 0, 0), points, max(1, round(1.5 * scale)))
            if label is not None:
                lx, ly = int(16 * CURSOR_SIZE * scale) + margin, int(13 * CURSOR_SIZE * scale)
                pg.draw.rect(sprite, color, (lx - 2, ly - 1, label.get_width() + 4, label.get_height() + 2))
                pg.draw.rect(sprite, (0, 0, 0), (lx - 2, ly - 1, label.get_width() + 4, label.get_height() + 2), 1)
                sprite.blit(label, (lx, ly))
            if faded:
                sprite.set_alpha(FADED_ALPHA)
            self._sprites[key] = (sprite, margin)
        return self._sprites[key]


_controls = None


def get():
    """The one Controls (made on first use; pygame must be initialised)."""
    global _controls
    if _controls is None:
        _controls = Controls()
    return _controls
