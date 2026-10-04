"""
Event sandbox: a test board for checking by hand what each world event does.

    python3 event_sandbox.py

A 4-player game on a prepared board (every event's key countries are held
by someone) where events never come up by themselves: you pick them.
Everything else plays exactly like the real game, so you can play through
a round and watch the event resolve. After an event starts or ends, the
panel at the top lists everything it changed (also printed in the
terminal). Your own saves are never touched: the autosave and F5/F9
quicksave go to temporary files.

Keys (F1 shows them in the game too):
  F2          pick an event: start it now, or at the start of the next turn
  F3          end the current event now (runs its on_end)
  F4          end the current turn
  F7          list everything that changed since the event started
  F5 / F9     quicksave / quickload the sandbox
  Hovering over a country:
    O                  next owner (the players, then mouse)
    Shift + left/right click   +1 / -1 troop
    T / S / P          +1 tank / ship / plane (with Shift: -1)
    F                  fort level +1 (after 3 back to 0)
    A / D              airport / developed on or off
    N                  radioactive +3, as if the current player nuked it
  G           +10 of every resource for the current player
  C           +1 card for the current player
  B           current player bot on/off
  Esc         close the event list / help, otherwise fullscreen on/off
"""

from fonts import game_font
import os
import tempfile

import numpy as np
import pygame as pg

from board import get_countries
from engine import Engine
from events import EVENTS
from models import Kaertske, LANDMARKS, random_card_type
from save_load import save_game, load_game

AUTOSAVE = os.path.join(tempfile.gettempdir(), "oil_event_sandbox_autosave.json")
QUICKSAVE = os.path.join(tempfile.gettempdir(), "oil_event_sandbox_quicksave.json")

PLAYER_NAMES = ["Player 1", "Player 2", "Player 3", "Player 4"]

# country -> troops, per player (index into PLAYER_NAMES). Chosen so every
# event has something to act on: e.g. Player 1 holds Japan, Noord-Korea,
# Arabië and Nazi-Duitsland; Players 2 and 3 split Africa and the frozen
# north; Player 4 is down to one weak country (for eliminations).
BOARD = [
    {"Japan": 6, "Noord-Korea": 4, "China": 5, "Arabië": 3, "Nazi-Duitsland": 8, "India": 3,
     "Sri Lanka": 2},
    {"Belgisch Congo": 6, "Nigeria": 3, "Zuid-Afrika": 4, "Londen": 3, "Spanje": 3,
     "Los Angeles": 4, "Canada": 3, "Alaska": 2, "Maleisië": 2},
    {"Sahara": 5, "Somalië": 5, "Sovjet-Rusland": 6, "Brazilië": 4, "Peru": 3, "Outback": 4,
     "Mexico": 3},
    {"Mongolië": 1},
]
# country -> {attribute: value}
ASSETS = {
    "Japan": {"ships": 2, "tanks": 1},
    "Nazi-Duitsland": {"tanks": 2, "fort_lvl": 1},
    "China": {"fort_lvl": 2},
    "Londen": {"ships": 1, "planes": 1, "airport": True},
    "Belgisch Congo": {"tanks": 1},
    "Sovjet-Rusland": {"tanks": 1, "fort_lvl": 1},
}
START_RESOURCES = {"food": 60, "wood": 30, "steel": 30, "oil": 10, "nuclear": 5}

HELP = [
    "EVENT SANDBOX (F1: hide/show this)",
    "F2  pick an event (now / at next turn)",
    "F3  end the current event now",
    "F4  end the current turn",
    "F7  changes since the event started",
    "F5 / F9  quicksave / quickload",
    "Over a country:",
    "  O  next owner   Shift+click  +/-1 troop",
    "  T/S/P  +1 tank/ship/plane (Shift: -1)",
    "  F  fort +1   A  airport   D  developed",
    "  N  radioactive +3",
    "G  +10 resources   C  +1 card   B  bot on/off",
]


def setup_board(app):
    """Replace the random start with BOARD / ASSETS, on a full turn so the
    first turn isn't the no-recruiting opening turn."""
    app.countries = get_countries(app.default_player)
    for player, countries in zip(app.players, BOARD):
        for resource, amount in START_RESOURCES.items():
            setattr(player, resource, amount)
        for name, units in countries.items():
            country = app.countries[name]
            country.owner = player
            country.units = units
            if name in LANDMARKS:
                country.landmark_owner = player  # no forgotten-landmark penalty
    for name, values in ASSETS.items():
        for attr, value in values.items():
            setattr(app.countries[name], attr, value)
    app.turn = 0
    app.card_menu.player = app.players[0]
    manager = app.turn_manager
    manager.turn_num = manager.event_turn_index = len(app.players)


def snapshot(app):
    manager = app.turn_manager
    return {
        "countries": {
            name: {
                "owner": c.owner.name, "troops": c.units, "ships": c.ships, "tanks": c.tanks,
                "planes": c.planes, "fort": c.fort_lvl, "radioactive": c.radioactive,
                "airport": c.airport, "developed": c.developed,
            }
            for name, c in app.countries.items()
        },
        "players": {
            p.name: {
                "food": p.food, "wood": p.wood, "steel": p.steel, "oil": p.oil,
                "nuclear": p.nuclear, "cards": len(p.cards), "eliminated": p.eliminated,
            }
            for p in app.players
        },
        "routes": {tuple(sorted(c.connection)): c.kind for c in app.connections},
        "event cards waiting": manager.pending_event_cards,
    }


def _route_list(routes, limit=8):
    names = ["-".join(r) for r in sorted(routes)]
    return ", ".join(names[:limit]) + (" ... (+{})".format(len(names) - limit) if len(names) > limit else "")


def diff(before, after):
    """Human-readable list of what changed between two snapshots."""
    lines = []
    for section in ("players", "countries"):
        for name, old in before[section].items():
            new = after[section].get(name)
            if new is None:
                continue
            changes = ["{} {} -> {}".format(k, old[k], new[k]) for k in old if old[k] != new[k]]
            if changes:
                lines.append("{}: {}".format(name, ", ".join(changes)))
    old_routes, new_routes = before["routes"], after["routes"]
    added = set(new_routes) - set(old_routes)
    removed = set(old_routes) - set(new_routes)
    changed = {r for r in set(old_routes) & set(new_routes) if old_routes[r] != new_routes[r]}
    if added:
        lines.append("{} route(s) added: {}".format(len(added), _route_list(added)))
    if removed:
        lines.append("{} route(s) removed: {}".format(len(removed), _route_list(removed)))
    for route in sorted(changed):
        lines.append("route {}: {} -> {}".format("-".join(route), old_routes[route], new_routes[route]))
    if before["event cards waiting"] != after["event cards waiting"]:
        lines.append("event cards waiting: {} -> {}".format(
            before["event cards waiting"], after["event cards waiting"]))
    return lines or ["(nothing changed)"]


class Sandbox:

    def __init__(self, app):
        self.app = app
        self.manager = app.turn_manager
        self.font = game_font(15)
        self.title_font = game_font(20, bold=True)
        self.help_open = True
        self.picker_open = False
        self.at_turn_start = False  # picker timing
        self.queued = None          # event to start as the next turn begins
        self.start_snapshot = None  # board as it was just before the event started
        self.report_title = "No event yet: press F2"
        self.report = []
        # Events only come when picked (see _schedule).
        self.manager._update_event_schedule = self._schedule

    @property
    def player(self):
        return self.app.players[self.app.turn]

    # --- events ------------------------------------------------------------

    def _schedule(self):
        """Replaces TurnManager._update_event_schedule: an event still lasts
        one full round (every player one turn), but none is ever drawn at
        random -- only the one queued from the event list."""
        manager = self.manager
        current = self.player
        if manager.current_event is not None and not manager.event_pending_players:
            self.end_event("its round is over")
        if manager.current_event is not None:
            manager.event_pending_players.discard(current)
            manager.event_pending_players -= {p for p in manager.event_pending_players if manager._is_out(p)}
            return
        if self.queued is not None:
            event, self.queued = self.queued, None
            self.start_event(event)

    def start_event(self, event):
        """Start `event` right now, the way TurnManager does: the current
        player's turn counts as the first of its round."""
        manager, app = self.manager, self.app
        if manager.current_event is not None:
            self.end_event("replaced by {}".format(event.name))
        before = snapshot(app)
        alive = {p for p in app.players if not manager._is_out(p)}
        manager.current_event = event
        manager.event_pending_players = alive - {self.player}
        manager.event_history.append(event)
        manager.event_notice = event
        event.on_start(app)
        self.start_snapshot = before
        self.show_report("{} started (on_start)".format(event.name), diff(before, snapshot(app)))

    def end_event(self, why):
        manager, app = self.manager, self.app
        event = manager.current_event
        if event is None:
            return
        player = self.player
        # Don't leave the player stuck on a pick / mouse attack of an event
        # that's no longer there.
        if player.attack == 5:
            player.attack, player.subattack = manager.phases[5].return_to
            manager.phases[5].predicate = None
        elif player.attack == 6:
            player.attack, player.subattack = getattr(event, "return_to", (1, 0))
        before = snapshot(app)
        event.on_end(app)
        manager.current_event = None
        manager.event_pending_players = set()
        self.start_snapshot = None
        self.show_report("{} ended, {} (on_end)".format(event.name, why), diff(before, snapshot(app)))

    def end_turn(self):
        manager, app = self.manager, self.app
        player = self.player
        app.card_menu.show = False
        if player.attack == 3:
            manager.close_shop()
        player.attack, player.subattack = 2, 0
        manager.phases[1].reset()
        manager.phases[2].reset()
        manager.end_phase()  # 2 -> 0: cards, next player, event schedule

    def show_report(self, title, lines):
        self.report_title = title
        self.report = lines
        print("\n== {} ==".format(title))
        for line in lines:
            print("  " + line)

    # --- input -----------------------------------------------------------------

    def _picker_layout(self):
        """(panel rect, [(rect, timing)], [(rect, event)]) in UI coordinates."""
        panel = pg.Rect(110, 30, 740, 580)
        timing = [
            (pg.Rect(panel.x + 20, panel.y + 45, 340, 32), False),
            (pg.Rect(panel.x + 380, panel.y + 45, 340, 32), True),
        ]
        rows = (len(EVENTS) + 1) // 2
        buttons = []
        for i, event in enumerate(EVENTS):
            col, row = divmod(i, rows)
            buttons.append((pg.Rect(panel.x + 20 + col * 360, panel.y + 95 + row * 39, 340, 34), event))
        return panel, timing, buttons

    def handle(self, events):
        """Keys and clicks for the sandbox, before the game sees them.
        Clicks the sandbox uses are consumed."""
        app, io = self.app, self.app.io
        if app.typing_save_name:
            return
        for event in events:
            if event.type == pg.KEYDOWN:
                self._key(event.key, event.mod)
        if self.picker_open:
            if io.left_pressed:
                self._picker_click((io.mouse_position.x, io.mouse_position.y))
            io.left_pressed = 0
            io.right_clicked = 0
            return
        hover = io.hover_country
        if hover is not None and pg.key.get_mods() & pg.KMOD_SHIFT and (io.left_pressed or io.right_clicked):
            country = app.countries[hover]
            country.units = max(country.units + (1 if io.left_pressed else -1), 0)
            io.left_pressed = 0
            io.right_clicked = 0

    def _picker_click(self, pos):
        panel, timing, buttons = self._picker_layout()
        if not panel.collidepoint(pos):
            self.picker_open = False
            return
        for rect, at_turn_start in timing:
            if rect.collidepoint(pos):
                self.at_turn_start = at_turn_start
                return
        for rect, event in buttons:
            if rect.collidepoint(pos):
                self.picker_open = False
                self.pick(event)
                return

    def pick(self, event):
        """What clicking `event` in the list does, with the current timing."""
        if self.at_turn_start:
            self.end_event("making way for {}".format(event.name))
            self.queued = event
            self.end_turn()
        else:
            self.start_event(event)

    def _key(self, key, mod):
        app, manager = self.app, self.manager
        shift = bool(mod & pg.KMOD_SHIFT)
        if key == pg.K_ESCAPE:
            if self.picker_open or self.help_open:
                self.picker_open = self.help_open = False
            else:
                app.toggle_fullscreen()
        elif key == pg.K_F1:
            self.help_open = not self.help_open
        elif key == pg.K_F2:
            self.picker_open = not self.picker_open
        elif key == pg.K_F3:
            if manager.current_event is not None:
                self.end_event("ended by hand")
        elif key == pg.K_F4:
            self.end_turn()
        elif key == pg.K_F7:
            if manager.current_event is not None and self.start_snapshot is not None:
                self.show_report("Changes since {} started".format(manager.current_event.name),
                                 diff(self.start_snapshot, snapshot(app)))
        elif key == pg.K_F5:
            save_game(app, manager, QUICKSAVE, name="Event sandbox")
            self.show_report("Quicksaved", [QUICKSAVE])
        elif key == pg.K_F9:
            if os.path.isfile(QUICKSAVE):
                load_game(QUICKSAVE, app, manager)
                self.start_snapshot = snapshot(app) if manager.current_event is not None else None
                self.show_report("Quickloaded (the turn restarts at its phase's first step)", [])
        elif key == pg.K_g:
            for resource in START_RESOURCES:
                setattr(self.player, resource, getattr(self.player, resource) + 10)
        elif key == pg.K_c:
            self.player.cards.append(Kaertske(random_card_type(), images=app.images))
            app.card_menu.organize_cards()
        elif key == pg.K_b:
            self.player.is_bot = not self.player.is_bot
        else:
            self._country_key(key, shift)

    def _country_key(self, key, shift):
        app = self.app
        name = app.io.hover_country
        if name is None:
            return
        country = app.countries[name]
        step = -1 if shift else 1
        if key == pg.K_o:
            owners = [p for p in app.players if not p.eliminated] + [app.default_player]
            index = owners.index(country.owner) if country.owner in owners else -1
            country.owner = owners[(index + 1) % len(owners)]
            country.units = max(country.units, 1)
            if name in LANDMARKS:
                is_player = country.owner is not app.default_player
                country.landmark_owner = country.owner if is_player else None
        elif key in (pg.K_t, pg.K_s, pg.K_p):
            attr = {pg.K_t: "tanks", pg.K_s: "ships", pg.K_p: "planes"}[key]
            setattr(country, attr, max(getattr(country, attr) + step, 0))
            if attr == "planes" and country.planes > 0:
                country.airport = True
        elif key == pg.K_f:
            country.fort_lvl = (country.fort_lvl + 1) % 4
        elif key == pg.K_a:
            country.airport = not country.airport
        elif key == pg.K_d:
            country.developed = not country.developed
        elif key == pg.K_n:
            country.radioactive += 3
            country.bombed_by = self.player

    # --- drawing -------------------------------------------------------------

    def _text(self, text, x, y, font=None, color=(0, 0, 0)):
        self.app.view.screen.blit((font or self.font).render(text, True, color), (x, y))

    def _wrapped(self, text, width):
        return self.manager._wrap_text(text, self.font, width) or [""]

    def _status_lines(self):
        manager, app = self.manager, self.app
        event = manager.current_event
        lines = []
        if event is None:
            lines.append("No event active")
        else:
            waiting = ", ".join(sorted(p.name for p in manager.event_pending_players)) or "nobody (ends after this turn)"
            lines.append("EVENT: {}  --  still to play: {}".format(event.name, waiting))
            state = event.save_state(app)
            if state:
                lines.append("event state: " + ", ".join("{}={}".format(k, v) for k, v in state.items()))
            cost = event.discount_shop_cost(app, {"wood": 15})
            if cost != {"wood": 15}:
                lines.append("shop: a ship costs {} wood instead of 15".format(cost["wood"]))
            hover = app.io.hover_country
            if hover is not None:
                lines.append(self._hover_effects(event, app.countries[hover]))
        if self.queued is not None:
            lines.append("queued for the next turn: {}".format(self.queued.name))
        if manager.pending_event_cards:
            lines.append("event cards waiting for {}: {}".format(self.player.name, manager.pending_event_cards))
        return lines

    def _hover_effects(self, event, country):
        app = self.app
        bits = []
        bonus = event.attack_bonus(app, country)
        if bonus:
            bits.append("attacking from here: {:+d} on every die".format(bonus))
        if country.owner is not app.default_player:
            penalty = event.dice_penalty(app, country.owner)
            if penalty:
                bits.append("{}'s dice -{}".format(country.owner.name, penalty))
        if not event.can_attack_from(app, country):
            bits.append("can't attack from here")
        if not event.can_attack_target(app, country):
            bits.append("can't be attacked")
        if event.free_claim_allowed(app, country):
            bits.append("can be claimed for free")
        return "{}: {}".format(country.name, "; ".join(bits) if bits else "no combat effect from the event")

    def _dice_on_screen(self):
        """Whether an attack's dice (drawn top centre) are showing."""
        player = self.player
        return (player.attack == 1 and player.subattack in (2, 3, 4, 6, 8)) or player.attack == 6

    def draw(self):
        screen = self.app.view.screen
        dice = self._dice_on_screen()
        if dice:
            # Right of the dice and their bonus badges, above the tank
            # panels: just the event status, the report waits.
            # (and below the owner panel of a hovered country, top right).
            x, y, width, max_lines = 560, 80, 245, 7
        else:
            # Right of the help box, left of the hovered country's owner
            # panel (which starts about 150px left of the country panel).
            x, y, width, max_lines = 305, 4, 330, None
        lines = []
        for line in self._status_lines():
            lines.extend(self._wrapped(line, width - 16))
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines - 1] + ["..."]
        # While a message box is up, keep the panel short so it doesn't cover it.
        if not dice and not self.manager.dialog_active and not self.picker_open:
            lines.append("")
            lines.extend(self._wrapped(self.report_title, width - 16))
            report = []
            for line in self.report:
                report.extend(self._wrapped("- " + line, width - 16))
            if len(report) > 14:
                report = report[:13] + ["... {} more lines in the terminal".format(len(report) - 13)]
            lines.extend(report)
        height = 8 + 17 * len(lines)
        pg.draw.rect(screen, (255, 250, 225, 235), pg.Rect(x, y, width, height))
        pg.draw.rect(screen, (0, 0, 0), pg.Rect(x, y, width, height), 2)
        for i, line in enumerate(lines):
            bold = i == 0 or line == self.report_title
            self._text(line, x + 8, y + 4 + 17 * i, color=(120, 0, 0) if bold else (0, 0, 0))

        if self.help_open and not self.picker_open and not dice:
            hx, hy, hw = 10, 150, 285
            hh = 10 + 18 * len(HELP)
            pg.draw.rect(screen, (230, 240, 255, 235), pg.Rect(hx, hy, hw, hh))
            pg.draw.rect(screen, (0, 0, 0), pg.Rect(hx, hy, hw, hh), 2)
            for i, line in enumerate(HELP):
                self._text(line, hx + 8, hy + 5 + 18 * i)

        if self.picker_open:
            self._draw_picker()

    def _draw_picker(self):
        screen = self.app.view.screen
        mouse = (self.app.io.mouse_position.x, self.app.io.mouse_position.y)
        panel, timing, buttons = self._picker_layout()
        pg.draw.rect(screen, (250, 225, 130), panel)
        pg.draw.rect(screen, (0, 0, 0), panel, 3)
        self._text("Pick an event (F2 / Esc / click outside to close)", panel.x + 20, panel.y + 12, self.title_font)
        labels = {False: "Start now (mid-turn)", True: "Start at the next turn (as in the game)"}
        for rect, at_turn_start in timing:
            selected = self.at_turn_start == at_turn_start
            pg.draw.rect(screen, (150, 245, 150) if selected else (235, 235, 235), rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 3 if selected else 1)
            self._text(labels[at_turn_start], rect.x + 10, rect.y + 7)
        current = self.manager.current_event
        for rect, event in buttons:
            fill = (255, 255, 255) if rect.collidepoint(mouse) else (240, 240, 240)
            if event is current:
                fill = (190, 220, 255)
            pg.draw.rect(screen, fill, rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 1)
            self._text(event.name, rect.x + 10, rect.y + 8)


def frame(app, sandbox, events=()):
    """One frame of the sandbox: input, then the game, then the overlay."""
    app.handle_events(events)
    app.io_handle()
    sandbox.handle(events)
    app.draw_world()
    app.draw_gui()
    app.update_turn()
    app.control_card_menu()
    sandbox.draw()
    app.present()


def main():
    app = Engine(mode="count", player_count=len(PLAYER_NAMES), player_names=PLAYER_NAMES)
    app.save_path = AUTOSAVE
    app.toggle_fullscreen()  # start in a window
    setup_board(app)
    sandbox = Sandbox(app)
    print(__doc__)
    clock = pg.time.Clock()
    while True:
        events = pg.event.get()
        zoom = 1.0
        for event in events:
            if event.type == pg.QUIT:
                return
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 5:
                zoom /= 1.1
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 4:
                zoom *= 1.1
        if zoom != 1.0:
            app.view.zoom_at(app.io.mouse_position, zoom)
        frame(app, sandbox, events)
        if app.pending_quit:
            return
        pg.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()
    pg.quit()
