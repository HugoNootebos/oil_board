"""
Automated checks for the world events: sets up a small scenario for each
event, runs it through the real game code (income, combat, conquest,
event hooks, save/load) and reports PASS/FAIL per check.

    python3 event_checks.py [name filter]

Headless; nothing is drawn and your saves are never touched (saves go to
a temporary file). Exit code 1 if anything failed. For looking at an
event by hand in the real game, use event_sandbox.py.
"""

import json
import os
import sys
import tempfile
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np  # noqa: E402

from board import CONTINENTS, get_connections, get_countries  # noqa: E402
from engine import Engine  # noqa: E402
import lang  # noqa: E402
from events import EVENTS  # noqa: E402
from models import Player  # noqa: E402
from phases import TurnManager  # noqa: E402
from player_colors import COUNT_MODE_COLORS  # noqa: E402
from save_load import save_game, load_game  # noqa: E402

SAVE = os.path.join(tempfile.gettempdir(), "oil_event_checks.json")
RESOURCES = ("wood", "steel", "oil", "nuclear")

app = Engine(mode="count", player_count=3, player_names=["A", "B", "C"])
app.save_path = SAVE
EVENT = {type(e).__name__: e for e in EVENTS}

results = []  # (test, description, ok, detail)
_current_test = [""]


def check(description, ok, detail=""):
    results.append((_current_test[0], description, bool(ok), detail))


# --- board helpers ---------------------------------------------------------

def reset():
    """Fresh board (everything mouse's), three fresh players, a fresh
    TurnManager, player A to move -- past the opening turns."""
    app.countries = get_countries(app.default_player)
    app.connections = get_connections()
    app.players = [Player(name, color=COUNT_MODE_COLORS[i], food=1000, wood=50, steel=50, oil=20, nuclear=10)
                   for i, name in enumerate(("A", "B", "C"))]
    app.turn = 0
    app.card_menu.player = app.players[0]
    app.turn_manager = TurnManager(app)
    manager = app.turn_manager
    manager.turn_num = manager.event_turn_index = len(app.players)
    manager.bot.fast = True
    app.io.left_pressed = 0
    return app.players


def m():
    return app.turn_manager


def country(name):
    return app.countries[name]


def own(player, name, units, **attrs):
    c = country(name)
    c.owner = player
    c.units = units
    for key, value in attrs.items():
        setattr(c, key, value)
    return c


def activate(event, current=0):
    """Start `event` on player `current`'s turn, as the scheduler does."""
    app.turn = current
    manager = m()
    manager.current_event = event
    manager.event_pending_players = {p for i, p in enumerate(app.players) if i != current}
    event.on_start(app)


def finish():
    manager = m()
    manager.current_event.on_end(app)
    manager.current_event = None


def resources(player):
    return {r: getattr(player, r) for r in RESOURCES + ("food",)}


def income(player):
    """Run `player`'s start of turn; returns what each resource changed by."""
    app.turn = app.players.index(player)
    player.attack, player.subattack = 0, 0
    before = resources(player)
    m().phases[0]._start_turn()
    return {r: getattr(player, r) - before[r] for r in before}


def fight(frm, to, attack, defence, land=True):
    """One round of combat from `frm` to `to` with fixed dice (through
    AttackPhase._apply_combat_results, so conquests run for real)."""
    phase = m().phases[1]
    app.turn = app.players.index(country(frm).owner)
    phase.reset()
    phase.attack_from, phase.defence_country = frm, to
    phase.attack_dice = np.array(attack, dtype=float)
    phase.defence_dice = np.array(defence, dtype=float)
    phase.selected_ships = phase.selected_tanks = phase.selected_planes = 0
    phase.active_tanks = phase.prepaid_planes = 0
    phase.attack_via_land = land
    m().defending_tanks[to] = 0
    phase._apply_combat_results()


def japan_routes():
    return [c for c in app.connections if "Japan" in c]


def neighbours(name, connections=None):
    return {n for c in (connections or app.connections) if name in c for n in c.connection if n != name}


def richest(names, resource=None):
    """The country among `names` producing the most (of `resource`)."""
    def total(n):
        c = country(n)
        return getattr(c, resource) if resource else sum(getattr(c, r) for r in RESOURCES + ("food",))
    return max(names, key=total)


def save_and_load():
    save_game(app, m(), SAVE)
    load_game(SAVE, app, m())
    return app.players


# --- one test per event ------------------------------------------------------

TESTS = []


def test(event_class):
    def register(fn):
        TESTS.append((event_class, fn))
        return fn
    return register


@test("JapanGoesCrazy")
def _(ev):
    a, b, c = reset()
    board_kinds = {frozenset(r.connection): r.kind for r in get_connections() if "Japan" in r}
    own(a, "Japan", 5)
    activate(ev)
    check("+5 troops on Japan", country("Japan").units == 10, country("Japan").units)
    check("every Japan route is land", all(r.kind == "land" for r in japan_routes()))
    check("Japan linked to every other country", neighbours("Japan") == set(app.countries) - {"Japan"},
          len(neighbours("Japan")))
    finish()
    kinds = {frozenset(r.connection): r.kind for r in japan_routes()}
    check("on_end: temporary routes removed", not any(getattr(r, "temporary", False) for r in app.connections))
    check("on_end: Japan's routes back as on the board", kinds == board_kinds)
    check("troops stay after the event", country("Japan").units == 10)

    a, b, c = reset()
    activate(ev)
    check("mouse's Japan: no troops yet", country("Japan").units == get_countries(app.default_player)["Japan"].units)
    own(b, "Japan", 3)
    check("taking Japan during the event triggers", ev.check_pending(app, a))
    check("... +5 for whoever took it", country("Japan").units == 8, country("Japan").units)
    check("... only once", not ev.check_pending(app, a) and country("Japan").units == 8)
    finish()


@test("NativesFightBack")
def _(ev):
    a, b, c = reset()
    a.is_bot = b.is_bot = True
    own(a, "China", 3)
    own(b, "Outback", 2)
    activate(ev)
    check("players' targets queued", list(ev.queue) == ["China", "Outback"], ev.queue)
    check("mouse's targets pending", set(ev.pending) == {"Sovjet-Rusland", "Peru", "Canada"}, ev.pending)
    a.attack, a.subattack = 1, 0
    check("mouse attack starts at a calm point", ev.check_pending(app, a) and a.attack == 6)
    for _ in range(500):
        m().phases[6].update()
        if a.attack != 6:
            break
    check("attacks finish, player back where they were", (a.attack, a.subattack) == (1, 0), (a.attack, a.subattack))
    check("queue worked through", not ev.queue, ev.queue)
    for name, owner, start in (("China", a, 3), ("Outback", b, 2)):
        c_ = country(name)
        held = c_.owner is owner and 1 <= c_.units <= start
        taken = c_.owner is app.default_player and 1 <= c_.units <= ev.TROOPS
        check("{} held or taken by the natives".format(name), held or taken, (c_.owner.name, c_.units))
    own(c, "Peru", 2)
    ev.check_pending(app, a)
    check("taking a pending target queues it", "Peru" in ev.queue and "Peru" not in ev.pending)
    finish()


@test("DevelopmentAid")
def _(ev):
    a, b, c = reset()
    europe = richest(CONTINENTS["Europe"])
    own(a, europe, 2)
    own(b, "Belgisch Congo", 6)
    own(c, "Nigeria", 3)
    activate(ev)
    before_b = resources(b)
    gained = income(a)
    expected = {r: getattr(country(europe), r) for r in RESOURCES + ("food",)}
    check("{}'s income goes to most troops in Africa".format(europe),
          all(getattr(b, r) - before_b[r] == expected[r] for r in expected),
          {r: getattr(b, r) - before_b[r] for r in expected})
    check("owner gets none of it", all(gained[r] == 0 for r in RESOURCES), gained)
    own(c, "Nigeria", 6)  # tie in Africa: nobody leads
    before_b = resources(b)
    gained = income(a)
    check("tie in Africa: owner keeps it", all(gained[r] == expected[r] for r in RESOURCES)
          and resources(b) == before_b, gained)
    finish()


@test("EmperorsHonor")
def _(ev):
    a, b, c = reset()
    targets = neighbours("Japan")
    fortified = sorted(targets)[0]
    own(b, fortified, 3, fort_lvl=2, tanks=1)
    own(a, "Sahara", 10)
    own(a, "Madagaskar", 10)
    own(b, "Londen", 10)
    own(c, "Canada", 5)
    for name in ("Nigeria", "Zuid-Afrika"):
        own(c, name, 1)  # one round takes them
    country("Spanje").units = 1  # the mouse's
    activate(ev)
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    fight("Madagaskar", "Zuid-Afrika", [6, 6, 6], [1])
    fight("Londen", "Spanje", [6, 6, 6], [1])
    check("only conquests from other players are counted (not the mouse's)",
          ev.conquest_counts == {"A": 2}, ev.conquest_counts)
    check("leaderboard in the event panel", ev.panel_lines(app)[1:] == ["A: 2", "B: 0", "C: 0"],
          ev.panel_lines(app))
    finish()
    check("most conquests claims every country around Japan",
          all(country(n).owner is a and country(n).units == 1 for n in targets))
    check("claimed countries lose fort and tanks", country(fortified).fort_lvl == 0 and country(fortified).tanks == 0)

    a, b, c = reset()
    own(a, "Sahara", 10)
    own(b, "Londen", 10)
    own(c, "Canada", 5)
    own(c, "Nigeria", 1)
    own(c, "Spanje", 1)
    activate(ev)
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    fight("Londen", "Spanje", [6, 6, 6], [1])
    finish()
    check("tie: nothing happens", all(country(n).owner is app.default_player for n in targets))

    a, b, c = reset()
    own(a, "Sahara", 10)
    country("Nigeria").units = 1  # the mouse's
    activate(ev)
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    finish()
    check("only mouse countries conquered: nothing happens",
          all(country(n).owner is app.default_player for n in targets))

    a, b, c = reset()
    own(a, "Sahara", 10)
    own(c, "Canada", 5)
    own(c, "Nigeria", 1)
    activate(ev)
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    a, b, c = save_and_load()
    finish()
    check("save/load mid-event keeps the conquest tally",
          all(country(n).owner is a for n in targets),
          "after loading, the countries around Japan went to {}".format(
              country(sorted(targets)[0]).owner.name
              if country(sorted(targets)[0]).owner in app.players + [app.default_player]
              else "a player object that no longer exists"))


@test("WrongButton")
def _(ev):
    a, b, c = reset()
    own(a, "Noord-Korea", 4)
    own(b, "Kazachstan", 7)
    a.attack, a.subattack = 1, 0
    activate(ev)
    check("human owner is sent to the pick screen", a.attack == 5 and m().phases[5].chooser is a)
    m().phases[5].pick(country("Kazachstan"))
    check("nuke halves the troops", country("Kazachstan").units == 3, country("Kazachstan").units)
    check("... radioactive 3, bombed by the chooser",
          country("Kazachstan").radioactive == 3 and country("Kazachstan").bombed_by is a)
    check("player back where they were", (a.attack, a.subattack) == (1, 0))
    check("only once", not ev.check_pending(app, a))
    finish()

    a, b, c = reset()
    a.is_bot = True
    own(a, "Noord-Korea", 4)
    own(b, "Kazachstan", 7)
    own(c, "India", 3)
    activate(ev)
    check("bot owner nukes the biggest enemy army in Asia", country("Kazachstan").units == 3 and a.attack == 0)
    finish()

    a, b, c = reset()
    activate(ev)
    check("mouse's Noord-Korea: nothing yet", a.attack == 0 and not ev.triggered)
    own(b, "Noord-Korea", 2)
    a.attack, a.subattack = 1, 0
    check("taking it during the event triggers", ev.check_pending(app, a) and a.attack == 5)
    check("... and the new owner picks", m().phases[5].chooser is b)
    m().phases[5].pick(country("India"))
    check("... strike credited to them", country("India").bombed_by is b)
    finish()


def bonus_test(ev, home, other):
    a, b, c = reset()
    own(a, home, 10)
    own(a, other, 10)
    own(b, "Peru", 10)
    activate(ev)
    fight(home, "Peru", [3], [3])
    check("from {}: +1 turns a tie into a win".format(home),
          country("Peru").units == 9 and country(home).units == 10)
    fight(other, "Peru", [3], [3])
    check("from elsewhere: no bonus", country(other).units == 9)
    finish()
    fight(home, "Peru", [3], [3])
    check("after the event: no bonus", country(home).units == 9)


@test("JapaneseAggression")
def _(ev):
    bonus_test(ev, "Japan", "India")


@test("NaziExpansion")
def _(ev):
    bonus_test(ev, "Nazi-Duitsland", "Londen")


@test("StormAtSea")
def _(ev):
    a, b, c = reset()
    np.random.seed(1)
    rate = np.mean([ev.sea_attack_check(app) for _ in range(6000)])
    check("pirates strike about 1 in 3 times", 0.30 < rate < 0.37, round(rate, 3))
    own(a, "Japan", 10, ships=1)
    own(b, "Kazachstan", 5)
    activate(ev)
    ev.sea_attack_check = lambda engine: True
    try:
        phase = m().phases[1]
        for land in (False, True):
            phase.reset()
            phase.attack_from, phase.defence_country = "Japan", "Kazachstan"
            phase.attack_dice = phase._default_attack_dice(10)
            phase.defence_dice = np.zeros(2)
            phase.attack_via_land = land
            phase.selected_ships = 1
            phase.active_tanks = phase.selected_planes = phase.prepaid_planes = 0
            phase.roll_attack()
            if not land:
                check("sea attack: the 3 committed troops are lost", country("Japan").units == 7,
                      country("Japan").units)
                check("and the ship carrying them: the battle is over",
                      country("Japan").ships == 0 and phase.selected_ships == 0 and a.subattack == 0
                      and phase.attack_from is None, (country("Japan").ships, a.subattack))
                country("Japan").ships = 1
            else:
                check("land attack: never hit", country("Japan").units == 7 and a.subattack == 3)

        # Only the troops on selected dice: the one left behind stays home.
        own(a, "Japan", 3, ships=1)
        phase.reset()
        phase.attack_from, phase.defence_country = "Japan", "Kazachstan"
        phase.attack_dice = phase._default_attack_dice(3)
        phase.defence_dice = np.zeros(2)
        phase.attack_via_land = False
        phase.selected_ships, phase.selected_tanks, phase.selected_planes = 1, 0, 0
        phase.roll_attack()
        check("pirates take the 2 on selected dice, not the 1 left behind",
              country("Japan").units == 1 and country("Japan").owner is a, country("Japan").units)

        # Everything brought along sinks with them; what stayed home is kept.
        own(a, "Japan", 10, ships=2, tanks=3, planes=1)
        a.oil = 5
        phase.reset()
        phase.attack_from, phase.defence_country = "Japan", "Kazachstan"
        phase.attack_dice = phase._default_attack_dice(10)
        phase.defence_dice = np.zeros(2)
        phase.attack_via_land = False
        phase.selected_ships, phase.selected_tanks, phase.selected_planes = 1, 2, 0
        phase.active_tanks = 2
        phase.roll_attack()
        japan = country("Japan")
        check("the ship and the tanks on it are lost, the rest stays",
              (japan.units, japan.ships, japan.tanks, japan.planes) == (7, 1, 1, 1) and a.oil == 5,
              (japan.units, japan.ships, japan.tanks, japan.planes, a.oil))
        check("the notice says the convoy went down", m().notices[-1] == lang.t(
            "{} units and everything they brought along have been lost to pirates").format(3), m().notices[-1])
        m().notices.clear()

        # Flying across: 2 dice selected, the plane and a tank go down too.
        own(a, "Japan", 10, ships=0, tanks=2, planes=2)
        phase.reset()
        phase.attack_from, phase.defence_country = "Japan", "Kazachstan"
        phase.attack_dice = np.array([0.0, 0.0, 1.0])
        phase.defence_dice = np.zeros(2)
        phase.attack_via_land = False
        phase.selected_ships, phase.selected_tanks, phase.selected_planes = 0, 1, 1
        phase.active_tanks = 1
        phase.roll_attack()
        check("by plane: 2 troops (2 dice), the plane and the tank are lost",
              (japan.units, japan.tanks, japan.planes) == (8, 1, 1),
              (japan.units, japan.tanks, japan.planes))
        m().notices.clear()

        # In a real game everyone sees the wheel spin first (subattack 9).
        m().bot.fast = False
        for lost in (True, False):
            ev.sea_attack_check = lambda engine, lost=lost: lost
            own(a, "Japan", 10, ships=1)
            a.attack = 1
            phase.reset()
            phase.attack_from, phase.defence_country = "Japan", "Kazachstan"
            phase.attack_dice = phase._default_attack_dice(10)
            phase.defence_dice = np.zeros(2)
            phase.attack_via_land = False
            phase.selected_ships, phase.selected_tanks, phase.selected_planes = 1, 0, 0
            phase.roll_attack()
            wheel = phase.wheel
            check("wheel spins before anything happens ({})".format("pirates" if lost else "safe"),
                  a.subattack == 9 and wheel is not None and wheel.lost is lost and wheel.slices == 3
                  and country("Japan").units == 10)
            check("shop and cards blocked while it spins", m().attack_in_progress() and m().animating())
            phase.update()
            check("still spinning a moment later", a.subattack == 9 and not wheel.landed())
            # Where it stops: under the pointer at the top, in the pirate's
            # slice (0) exactly when the army is lost.
            under = (-wheel.final) % 360
            check("it lands on the pirate only when lost", (under < wheel.width) is lost, round(under, 1))
            wheel.start -= wheel.spin_ms + wheel.hold_ms + 1
            phase.update()
            if lost:
                check("after the wheel: the army and its ship are lost at sea",
                      country("Japan").units == 7 and country("Japan").ships == 0 and a.subattack == 0
                      and phase.wheel is None)
            else:
                check("after the wheel: on to the dice", country("Japan").units == 10 and a.subattack == 3
                      and country("Japan").ships == 1 and phase.wheel is None and not m().animating())
    finally:
        del ev.sea_attack_check
        m().bot.fast = True
    finish()


@test("ChildSoldiers")
def _(ev):
    a, b, c = reset()
    own(a, "Sahara", 10)
    own(a, "Somalië", 10)
    own(a, "Spanje", 10)
    own(b, "Nigeria", 1)
    own(b, "Londen", 1)
    own(c, "Peru", 3)
    activate(ev)
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    check("African country from a player: +1 card", m().pending_event_cards == 1)
    fight("Somalië", "Belgisch Congo", [6, 6, 6], [1, 1])
    fight("Somalië", "Belgisch Congo", [6, 6, 6], [1, 1])
    check("African country from mouse: nothing", country("Belgisch Congo").owner is a and m().pending_event_cards == 1)
    fight("Spanje", "Londen", [6, 6, 6], [1])
    check("non-African country: nothing", m().pending_event_cards == 1)
    cards = len(a.cards)
    a.attack, a.subattack = 2, 0
    m().end_phase()
    check("cards handed out at the end of the turn (1 conquest + 1 event)", len(a.cards) == cards + 2,
          len(a.cards) - cards)
    finish()


@test("Slavery")
def _(ev):
    a, b, c = reset()
    own(b, "Nigeria", 3)
    own(c, "Sahara", 5)
    start = {n: country(n).units for n in CONTINENTS["Africa"]}
    activate(ev)
    check("+1 on players' African countries", country("Nigeria").units == 4 and country("Sahara").units == 6)
    check("mouse's African countries unchanged",
          all(country(n).units == start[n] for n in CONTINENTS["Africa"] if n not in ("Nigeria", "Sahara")))
    own(a, "Madagaskar", 2)
    check("taken during the event: +1", ev.check_pending(app, a) and country("Madagaskar").units == 3)
    check("... only once", not ev.check_pending(app, a) and country("Madagaskar").units == 3)
    finish()


@test("EndOfHumanity")
def _(ev):
    a, b, c = reset()
    own(a, "Sahara", 10)
    own(b, "Nigeria", 1)
    a.food, b.food = 100, 40
    activate(ev)
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    check("eliminator gets the loser's food", a.food == 140 and b.food == 0, (a.food, b.food))
    m()._check_eliminations()
    check("loser eliminated", b.eliminated)
    finish()

    a, b, c = reset()
    own(a, "Sahara", 10)
    own(b, "Nigeria", 1)
    a.food, b.food = 100, 40
    fight("Sahara", "Nigeria", [6, 6, 6], [1])
    check("without the event: no food taken", a.food == 100)


@test("VOCPart2")
def _(ev):
    a, b, c = reset()
    own(a, "Sahara", 5)
    own(a, "Nigeria", 3)
    start = {n: c_.units for n, c_ in app.countries.items() if c_.owner is app.default_player}
    activate(ev)
    check("every mouse country 1 troop less",
          all(country(n).units == max(u - 1, 0) for n, u in start.items()))
    empty = sorted(n for n in start if country(n).units == 0)
    check("some mouse countries emptied (claimable)", bool(empty), len(empty))
    target = empty[0]
    check("empty mouse country can be claimed", ev.free_claim_allowed(app, country(target)))
    phase = m().phases[1]
    phase.reset()
    a.attack, a.subattack = 1, 1
    phase.attack_from = "Sahara"
    phase._start_attack(target, True)
    check("claimed without a fight", country(target).owner is a and a.subattack == 5)
    m().phases[0].abandon(country("Nigeria"))
    initial = app.initial_country_units["Nigeria"]
    check("abandoned during the event: also 1 less", country("Nigeria").units == max(initial - 1, 0))
    finish()
    check("on_end: mouse countries back to strength",
          all(country(n).units == u for n, u in start.items() if country(n).owner is app.default_player))
    check("on_end: abandoned one back too", country("Nigeria").units == initial)
    check("on_end: claimed country untouched", country(target).owner is a)


@test("VOCPart2")
def _(ev):
    a, b, c = reset()
    own(a, "India", 3)
    own(a, "Kazachstan", 2)
    activate(ev)
    phase = m().phases[2]
    phase.reset()
    a.attack, a.subattack = 2, 2
    phase.origin_country, phase.target_country = "India", "Kazachstan"
    phase.initial_origin, phase.initial_target = 3, 2
    phase.initial_origin_ships = phase.initial_target_ships = 0
    phase.initial_origin_tanks = phase.initial_target_tanks = 0
    phase.initial_origin_planes = phase.initial_target_planes = 0
    phase.oil_spent_on_planes = 0
    country("India").units, country("Kazachstan").units = 0, 5
    m().end_phase()
    check("unfinished move undone when ending the turn", country("India").units == 3 and country("India").owner is a
          and country("Kazachstan").units == 2,
          (country("India").units, country("India").owner.name, country("Kazachstan").units))
    country("India").units = 0
    a.attack, a.subattack = 1, 0
    m().end_phase()
    check("0-troop country goes to mouse", country("India").owner is app.default_player)
    finish()


@test("NuclearWinter")
def _(ev):
    a, b, c = reset()
    name = richest([n for n, c_ in app.countries.items() if c_.food > 0])
    own(a, name, 2)
    activate(ev)
    gained = income(a)
    check("no food produced (troops still eat)", gained["food"] == -2, gained)
    check("other resources still arrive", all(gained[r] == getattr(country(name), r) for r in RESOURCES), gained)
    finish()


@test("PutinsWar")
def _(ev):
    a, b, c = reset()
    oil = richest([n for n, c_ in app.countries.items() if c_.oil > 0 and n not in ev.COUNTRIES], "oil")
    food = richest([n for n, c_ in app.countries.items()
                    if c_.food > 0 and n not in ev.COUNTRIES and n != oil], "food")
    own(a, "Spanje", 2)
    own(a, oil, 2)
    own(b, food, 2)
    activate(ev)
    gained = income(a)
    check("owner of an EU country: no food (troops still eat), no oil",
          gained["food"] == -4 and gained["oil"] == 0, gained)
    check("... other resources still arrive",
          gained["wood"] == country("Spanje").wood + country(oil).wood, gained)
    gained = income(b)
    check("no EU country: income as usual", gained["food"] > 0, gained)
    finish()


@test("ChildLabor")
def _(ev):
    a, b, c = reset()
    own(a, "India", 3)
    own(a, "Sri Lanka", 2)
    own(b, "Maleisië", 2)
    steel = (a.steel, b.steel, c.steel)
    activate(ev)
    check("+5 steel per country held", (a.steel - steel[0], b.steel - steel[1]) == (10, 5))
    own(c, "Nederlands-Indië", 2)
    check("taken during the event: +5", ev.check_pending(app, a) and c.steel - steel[2] == 5)
    check("... only once", not ev.check_pending(app, a) and c.steel - steel[2] == 5)
    finish()


@test("Ebola")
def _(ev):
    a, b, c = reset()
    own(b, "Belgisch Congo", 6, tanks=2)
    own(c, "Nigeria", 3)
    activate(ev)
    bc = country("Belgisch Congo")
    check("most troops in Africa goes to mouse", bc.owner is app.default_player and bc.tanks == 0)
    check("... with its starting garrison", bc.units == app.initial_country_units["Belgisch Congo"])
    check("the other stays", country("Nigeria").owner is c)
    line = "".join(str(part) for part, _ in app.action_log[-2])
    expected = b.name + lang.t(" lost {} troops in {} due to ebola").format(6, lang.t("Belgisch Congo"))
    check("logged as the owner's loss", line == expected, line)
    finish()

    a, b, c = reset()
    own(b, "Belgisch Congo", 4)
    own(c, "Nigeria", 4)
    activate(ev)
    check("tie between players: nothing yet", country("Belgisch Congo").owner is b and country("Nigeria").owner is c)
    country("Nigeria").units = 5
    check("tie broken during the event: strikes then", ev.check_pending(app, a)
          and country("Nigeria").owner is app.default_player and country("Belgisch Congo").owner is b)
    finish()

    a, b, c = reset()
    own(a, "Sahara", 2)
    own(b, "Belgisch Congo", 4)
    own(b, "Nigeria", 4)
    activate(ev)
    check("tie within one player: not on someone else's turn", not ev.check_pending(app, a))
    app.turn = 1
    b.attack, b.subattack = 0, 0
    m().phases[0]._start_turn()
    check("... they pick at their turn start", b.attack == 5)
    m().phases[5].pick(country("Nigeria"))
    check("... the picked one goes to mouse", country("Nigeria").owner is app.default_player
          and country("Belgisch Congo").owner is b)
    finish()


@test("HarshWinter")
def _(ev):
    a, b, c = reset()
    own(a, "Alaska", 5)
    own(a, "New York", 5)
    own(b, "Canada", 3)
    activate(ev)
    phase = m().phases[1]

    def try_attack(frm, to):
        phase.reset()
        a.attack, a.subattack = 1, 1
        phase.attack_from = frm
        phase._start_attack(to, True)
        return a.subattack == 2

    check("can't attack from a frozen country", not try_attack("Alaska", "Mexico"))
    check("can't attack a frozen country", not try_attack("New York", "Canada"))
    check("others can fight", try_attack("New York", "Mexico"))
    finish()
    check("after the event: allowed again", try_attack("Alaska", "Canada"))


@test("Pilgrimage")
def _(ev):
    a, b, c = reset()
    own(a, "Arabië", 3)
    own(a, "Kazachstan", 5)
    own(a, "Japan", 4)
    activate(ev)
    check("all troops to Arabië, +5", country("Arabië").units == 17, country("Arabië").units)
    check("other countries left to mouse",
          country("Kazachstan").owner is app.default_player and country("Japan").owner is app.default_player)
    finish()

    a, b, c = reset()
    activate(ev)
    own(b, "Arabië", 2)
    own(b, "India", 4)
    check("taken during the event: happens then", ev.check_pending(app, a) and country("Arabië").units == 11)
    check("... only once", not ev.check_pending(app, a))
    finish()


@test("Looting")
def _(ev):
    reset()
    shop = m().phases[3]
    activate(ev)
    check("half price, rounded up", shop._cost({"wood": 15}) == {"wood": 8}
          and shop._cost({"nuclear": 5}) == {"nuclear": 3}
          and shop._cost({"wood": 2, "steel": 1}) == {"wood": 1, "steel": 1})
    finish()
    check("after the event: full price", shop._cost({"wood": 15}) == {"wood": 15})


@test("ClimateHoax")
def _(ev):
    a, b, c = reset()
    own(a, "India", 3)
    own(b, "Peru", 2)
    activate(ev)
    a.attack, a.subattack = 0, 0
    m().phases[0]._start_turn()
    check("turn start: pick a country for the plane", a.attack == 5)
    m().phases[5].pick(country("India"))
    check("free plane + airport", country("India").planes == 1 and country("India").airport)
    check("back to the turn start", (a.attack, a.subattack) == (0, 0))
    m().phases[0]._start_turn()
    check("turn goes on, no second plane", a.attack == 0 and a.subattack in (1, 3) and country("India").planes == 1)
    app.turn = 1
    b.attack, b.subattack = 0, 0
    m().phases[0]._start_turn()
    check("next player gets theirs too", b.attack == 5)
    finish()


@test("TrumpWall")
def _(ev):
    reset()
    board_pairs = {frozenset(r.connection) for r in get_connections()}
    for pair in ev.PAIRS:
        check("route {} exists on the map".format(" - ".join(sorted(pair))), frozenset(pair) in board_pairs)
    activate(ev)
    now = {frozenset(r.connection) for r in app.connections}
    check("no route between the VS and Mexico", not any(frozenset(p) in now for p in ev.PAIRS))
    check("VS countries not linked to Mexico",
          not (neighbours("Mexico") & {"Los Angeles", "Redneck", "New York", "Pearl Harbor"}),
          sorted(neighbours("Mexico")))
    finish()
    check("on_end: routes back", {frozenset(r.connection) for r in app.connections} == board_pairs)


@test("GoodEconomy")
def _(ev):
    a, b, c = reset()
    oily = richest(list(app.countries), "oil")
    dry = next(n for n, c_ in app.countries.items() if c_.oil == 0 and n != oily)
    own(a, oily, 2)
    own(b, dry, 2)
    activate(ev)
    check("oil country: +1 oil", income(a)["oil"] == country(oily).oil + 1)
    check("no oil: nothing extra", income(b)["oil"] == 0)
    finish()


@test("Covid")
def _(ev):
    a, b, c = reset()
    own(a, "Brazilië", 3)
    own(b, "Peru", 3)
    activate(ev)
    income(a)
    check("holding Brazilië: no reinforcements", m().reinforcements == 0, m().reinforcements)
    income(b)
    expected = country("Peru").troops // 3 + 3
    check("others: normal reinforcements", m().reinforcements == expected, (m().reinforcements, expected))
    finish()


@test("Drugs")
def _(ev):
    a, b, c = reset()
    own(a, "Mexico", 10)
    own(b, "Peru", 10)
    own(b, "Argentinië", 10)
    activate(ev)
    fight("Mexico", "Peru", [4], [3])
    check("attacker holding a drug country: -1 (4 vs 3 lost)", country("Mexico").units == 9)
    fight("Peru", "Mexico", [3], [3])
    check("defender holding one: -1 (3 vs 3 won)", country("Mexico").units == 8)
    fight("Argentinië", "Brazilië", [4], [4])
    check("mouse never gets the penalty", country("Argentinië").units == 9)
    check("dice_penalty for mouse is 0", ev.dice_penalty(app, app.default_player) == 0)
    finish()


@test("GasInRoubles")
def _(ev):
    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Sovjet-Rusland", 5)
    own(c, "Canada", 5)
    a.attack, a.subattack = 1, 0
    activate(ev)
    check("owner gets 5 oil", b.oil == 25, b.oil)
    check("the others' oil goes into the pool", a.oil == 0 and c.oil == 0 and ev.pool == 40, (a.oil, c.oil, ev.pool))
    check("a notice says so", len(m().notices) == 1)
    m().notices.clear()
    check("human owner is sent to the share screen", a.attack == 7 and m().acting_player() is b)
    phase = m().phases[7]
    phase.update()
    check("share screen draws, nothing shared yet", phase.shares == {a: 0, c: 0} and a.attack == 7, phase.shares)
    check("shop and cards blocked meanwhile", m().attack_in_progress())
    io = app.io
    io.mouse_position.x, io.mouse_position.y = phase.CONFIRM_X, phase.ROW_Y
    io.left_pressed, io.top_button = 1, None
    phase.update()
    io.left_pressed = 0
    check("the eye hides the panel", phase.hidden and a.attack == 7 and phase.shares == {a: 0, c: 0})
    io.left_pressed = 1
    phase.update()
    io.left_pressed = 0
    check("and shows it again", not phase.hidden and a.attack == 7)
    a, b, c = save_and_load()
    check("save/load mid-share keeps the pool and chooser", ev.pool == 40 and ev.chooser is b and a.attack == 7)
    phase.update()
    phase.shares = {a: 10, c: 25}
    phase.update()
    check("Confirm only once the pool is empty", a.attack == 7 and a.oil == 0)
    phase.shares = {a: 10, c: 30}
    phase._finish(ev, dict(phase.shares))
    check("oil handed out as chosen", a.oil == 10 and c.oil == 30 and b.oil == 25, (a.oil, b.oil, c.oil))
    check("player back where they were", (a.attack, a.subattack) == (1, 0))
    check("only once", not ev.check_pending(app, a))
    finish()

    a, b, c = reset()
    a.is_bot = True
    own(a, "Sovjet-Rusland", 5)
    own(b, "Londen", 30)
    own(c, "Canada", 2)
    activate(ev)
    check("bot owner shares at once, all to the weakest", a.oil == 25 and b.oil == 0 and c.oil == 40
          and a.attack == 0 and ev.pool == 0, (a.oil, b.oil, c.oil))
    finish()

    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Canada", 5)
    activate(ev)
    check("mouse's Sovjet-Rusland: nothing yet", a.oil == 20 and not ev.triggered)
    own(c, "Sovjet-Rusland", 2)
    a.attack, a.subattack = 1, 0
    check("taking it during the event triggers", ev.check_pending(app, a) and a.attack == 7 and ev.chooser is c)
    finish()
    check("never shared out: evenly at the end", a.oil == 20 and b.oil == 20 and c.oil == 25,
          (a.oil, b.oil, c.oil))

    a, b, c = reset()
    own(a, "Sovjet-Rusland", 5)
    own(b, "Londen", 5)
    own(c, "Canada", 5)
    b.oil = c.oil = 0
    activate(ev)
    check("nobody else has oil: only the 5, no share screen", a.oil == 25 and a.attack == 0)
    finish()


@test("GreenlandNotForSale")
def _(ev):
    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Groenland", 6, tanks=1, fort_lvl=1, planes=1)
    own(b, "Canada", 5)
    own(c, "Mexico", 5)
    a.attack, a.subattack = 1, 0
    activate(ev)
    check("auction screen, the current player bids first",
          a.attack == 8 and ev.bidder(app) is a and m().acting_player() is a)
    check("the owner doesn't bid", ev.bidders == ["A", "C"], ev.bidders)
    phase = m().phases[8]
    phase.update()
    phase.amount = 7
    check("shop and cards blocked meanwhile", m().attack_in_progress())
    ev.bid(app, a, 7)
    check("next bidder's turn, from 0", ev.bidder(app) is c and m().acting_player() is c)
    phase.update()
    check("... their bid starts at 0", phase.amount == 0)
    a, b, c = save_and_load()
    check("save/load mid-auction keeps the bids", ev.bids == {"A": 7} and ev.bidder(app) is c and a.attack == 8)
    ev.bid(app, c, 5)
    phase.update()
    g = country("Groenland")
    check("highest bidder gets it with everything on it",
          g.owner is a and g.units == 6 and g.tanks == 1 and g.fort_lvl == 1 and g.planes == 1)
    check("... and pays the previous owner", a.oil == 13 and b.oil == 27 and c.oil == 20, (a.oil, b.oil, c.oil))
    check("player back where they were", (a.attack, a.subattack) == (1, 0))
    check("bids shown afterwards", any("7" in n[1] and "5" in n[1] for n in m().notices), m().notices)
    finish()

    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Groenland", 6)
    own(c, "Mexico", 5)
    activate(ev)
    ev.bid(app, a, 5)
    ev.bid(app, c, 5)
    check("tie for the highest bid: nothing happens",
          country("Groenland").owner is b and a.oil == c.oil == 20 and b.oil == 20)
    finish()

    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Canada", 5)
    own(c, "Mexico", 5)
    b.oil = 0
    activate(ev)
    check("mouse's Groenland: everyone bids", ev.bidders == ["A", "B", "C"], ev.bidders)
    ev.bid(app, a, 3)
    check("no oil: bids 0 without a screen", ev.bids == {"A": 3, "B": 0} and ev.bidder(app) is c, dict(ev.bids))
    ev.bid(app, c, 20)
    check("bought from the mouse: the oil is gone", country("Groenland").owner is c and c.oil == 0 and a.oil == 20)
    finish()

    a, b, c = reset()
    a.is_bot = c.is_bot = True
    own(a, "Londen", 5)
    own(b, "Groenland", 6, tanks=2)
    own(b, "Canada", 5)
    own(c, "Mexico", 5)
    c.oil = 10
    activate(ev)
    check("bots bid at once, no screen", a.attack == 0 and not ev.bidders and country("Groenland").owner is not b
          and a.oil + c.oil < 30, (a.oil, c.oil, country("Groenland").owner.name))
    finish()

    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Groenland", 6)
    own(c, "Mexico", 5)
    c.oil = 0
    activate(ev)
    ev.bid(app, a, 4)
    check("buying someone's last country eliminates them, with their loot",
          country("Groenland").owner is a and b in m().elimination_loot and a.oil == 20 - 4 + 24, a.oil)
    finish()


@test("IsraelVictim")
def _(ev):
    from models import Position
    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Ottomaanse Rijk", 5)
    own(c, "Mexico", 5)
    a.attack, a.subattack = 1, 0
    activate(ev)
    m().notices.clear()
    check("human owner gets the turn-order screen", a.attack == 9 and m().acting_player() is b)
    phase = m().phases[9]
    io = app.io
    phase.update()
    check("starts from the current order", phase.order == [a, b, c], [p.name for p in phase.order])
    # Drag A (row 1) to the bottom.
    phase.dragging, phase.grab_dy = 0, 0
    io.mouse_state, io.mouse_position = (1, 0, 0), Position(400, 10000)
    phase.update()
    check("dragging moves the row", phase.order == [b, c, a] and phase.dragging == 2,
          [p.name for p in phase.order])
    io.mouse_state = (0, 0, 0)
    phase.update()
    check("letting go drops it", phase.dragging is None and phase.order == [b, c, a])
    check("shop and cards blocked meanwhile", m().attack_in_progress())
    phase._finish(ev, [p.name for p in phase.order])
    check("new turn order kept", app.players == [b, c, a], [p.name for p in app.players])
    check("current player keeps the turn", app.players[app.turn] is a and (a.attack, a.subattack) == (1, 0))
    check("... then it goes on in the new order", app.players[(app.turn + 1) % 3] is b)
    a, b, c = save_and_load()
    check("save/load keeps the order", [p.name for p in app.players] == ["B", "C", "A"]
          and app.players[app.turn].name == "A")
    check("only once", not ev.check_pending(app, a))
    finish()

    a, b, c = reset()
    a.is_bot = True
    own(a, "Ottomaanse Rijk", 5)
    own(b, "Londen", 30)
    own(c, "Mexico", 2)
    app.turn = 1
    activate(ev, current=1)
    check("bot owner sets it at once: itself, then weakest first",
          app.players == [a, c, b] and app.players[app.turn] is b and b.attack == 0,
          [p.name for p in app.players])
    finish()

    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Canada", 5)
    activate(ev)
    check("mouse's Ottomaanse Rijk: nothing yet", a.attack == 0 and not ev.triggered)
    own(c, "Ottomaanse Rijk", 2)
    a.attack, a.subattack = 1, 0
    check("taking it during the event: the new owner sets the order",
          ev.check_pending(app, a) and a.attack == 9 and ev.chooser is c)
    country("Canada").owner = app.default_player  # B is out
    check("the screen lists only players still in", ev.in_play(app) == [a, c])
    ev.reorder(app, ["C", "A"])
    check("players out of the game go last", app.players == [c, a, b],
          [p.name for p in app.players])
    finish()


@test("EvilSpirits")
def _(ev):
    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Maleisië", 3, developed=True, dormant_owner=b)
    b.food = 15
    a.attack, a.subattack = 1, 0
    activate(ev)
    g = country("Maleisië")
    check("developed: the owner is asked (also outside their turn)",
          a.attack == 10 and m().acting_player() is b and b.food == 15)
    check("shop and cards blocked meanwhile", m().attack_in_progress())
    m().phases[10].update()
    check("the question screen draws, nothing decided yet", a.attack == 10 and g.developed)
    a, b, c = save_and_load()
    check("save/load keeps the question", ev.chooser is b and a.attack == 10)
    ev.choose(app, b, True)
    a.attack, a.subattack = ev.return_to
    g = country("Maleisië")
    check("yes: pays 10 food, stays developed", b.food == 5 and g.developed, b.food)
    check("... with a notice", len(m().notices) == 1)
    check("only once", not ev.check_pending(app, a) and b.food == 5)
    finish()

    a, b, c = reset()
    own(b, "Maleisië", 3, developed=True, dormant_owner=b)
    activate(ev)
    ev.choose(app, b, False)
    g = country("Maleisië")
    check("no: development undone, food kept", not g.developed and g.dormant_owner is None and b.food == 1000)
    finish()

    a, b, c = reset()
    own(b, "Maleisië", 3, developed=True)
    b.food = 9
    activate(ev)
    g = country("Maleisië")
    check("not enough food: no question, development undone",
          a.attack == 0 and not g.developed and b.food == 9)
    finish()

    a, b, c = reset()
    b.is_bot = True
    own(b, "Maleisië", 3, developed=True)
    activate(ev)
    check("bot owner decides at once", a.attack == 0 and ev.triggered and ev.chooser is None
          and (b.food == 990) == country("Maleisië").developed)
    finish()

    a, b, c = reset()
    own(a, "Maleisië", 3)
    activate(ev)
    check("not developed: nothing yet", a.attack == 0 and not ev.triggered)
    country("Maleisië").developed = True
    a.attack, a.subattack = 1, 0
    check("developed during the event: asked then", ev.check_pending(app, a) and a.attack == 10)
    finish()

    a, b, c = reset()
    country("Maleisië").developed = True  # the mouse's
    activate(ev)
    check("the mouse's: nothing until a player holds it", not ev.triggered)
    own(c, "Maleisië", 2)
    check("... then they're asked", ev.check_pending(app, a) and ev.chooser is c)
    finish()

@test("Inflation")
def _(ev):
    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Belarus", 5)
    own(b, "Canada", 5)
    own(c, "Mexico", 5)
    own(c, "Sovjet-Rusland", 5)
    activate(ev)
    shop = m().phases[3]
    price = {"wood": 15, "steel": 1}
    app.turn = 0
    check("a Western country: double", shop._cost(price) == {"wood": 30, "steel": 2}, shop._cost(price))
    app.turn = 1
    check("Belarus: half (rounded up), also with a Western country",
          shop._cost(price) == {"wood": 8, "steel": 1}, shop._cost(price))
    app.turn = 2
    check("Mexico and Sovjet-Rusland aren't Western: as usual", shop._cost(price) == price, shop._cost(price))
    check("Western countries", set(ev.WESTERN) == {
        "Alaska", "New York", "Los Angeles", "Canada", "Groenland", "Pearl Harbor", "Redneck",
        "IJsland", "Viking", "Nazi-Duitsland", "Romeinse Rijk", "Spanje", "Londen"})
    finish()
    app.turn = 0
    check("after the event: as usual", shop._cost(price) == price)


@test("Immigration")
def _(ev):
    a, b, c = reset()
    own(a, "Londen", 5)
    own(b, "Spanje", 2)
    activate(ev)
    londen, ijsland = country("Londen"), country("IJsland")
    check("Western Europe +3 troops each, also the mouse's",
          londen.units == 8 and londen.immigrants == 3 and ijsland.immigrants == 3
          and country("Belarus").immigrants == 0 and country("Sovjet-Rusland").immigrants == 0)
    finish()
    check("they stay after the event", londen.immigrants == 3)

    phase = m().phases[1]
    app.turn = 0
    a.attack, a.subattack = 1, 1
    phase.attack_from = "Londen"
    target = sorted(neighbours("Londen") - set(ev.COUNTRIES))[0] if neighbours("Londen") - set(ev.COUNTRIES) \
        else sorted(neighbours("Londen"))[0]
    phase._start_attack(target, phase.connected("Londen", target, "land"))
    check("attack dice: only the 5 others (3), all thrown", list(phase.attack_dice) == [0, 0, 0],
          list(phase.attack_dice))
    londen.units = 4
    phase._start_attack(target, phase.connected("Londen", target, "land"))
    check("1 besides the immigrants: it may throw", list(phase.attack_dice) == [0], list(phase.attack_dice))
    londen.units = 3
    phase.defence_country, phase.attack_dice = None, []
    phase._start_attack(target, True)
    check("only immigrants: no attack", phase.defence_country is None)

    own(a, "Londen", 8)
    londen.immigrants = 3
    country("Spanje").units = 2
    fight("Spanje", "Londen", [6, 6, 6], [1, 1])
    check("defending: they fight, and die last", londen.units == 6 and londen.immigrants == 3)
    fight("Spanje", "Londen", [6, 6, 6], [1, 1])
    fight("Spanje", "Londen", [6, 6, 6], [1, 1])
    check("... down to 2: 2 immigrants left", londen.units == 2 and londen.immigrants == 2,
          (londen.units, londen.immigrants))

    a, b, c = reset()
    own(a, "Londen", 6)
    londen = country("Londen")
    londen.immigrants = 3
    victim = sorted(n for n in neighbours("Londen") if phase.connected("Londen", n, "land")) \
        or sorted(neighbours("Londen"))
    victim = victim[0]
    country(victim).units = 1
    fight("Londen", victim, [6, 6, 6], [1], land=phase.connected("Londen", victim, "land"))
    check("conquest: everything but the immigrants moves in",
          country(victim).owner is a and country(victim).units == 3 and londen.units == 3
          and londen.immigrants == 3, (country(victim).units, londen.units))
    check("... and the move-in can't take them", londen.units - londen.immigrants == 0)
    phase.reset()

    a, b, c = reset()
    own(a, "Londen", 5)
    own(a, "Spanje", 1)
    londen = country("Londen")
    londen.immigrants = 3
    move = m().phases[2]
    move.move_resource, move.troops_require_sea, move.ships_via_sea = "units", False, False
    for _ in range(5):
        move._shift_resource(londen, country("Spanje"), towards_origin=False)
    check("moving: the immigrants stay", londen.units == 3 and country("Spanje").units == 3,
          (londen.units, country("Spanje").units))
    country("Spanje").units, country("Spanje").immigrants = 3, 2
    for _ in range(5):
        move._shift_resource(londen, country("Spanje"), towards_origin=True)
    check("... also the target's own", country("Spanje").units == 2 and londen.units == 4)
    a, b, c = save_and_load()
    check("save/load keeps them", country("Londen").immigrants == 3 and country("Spanje").immigrants == 2)

    bot = m().bot
    londen = country("Londen")
    with bot._what_if((londen, "units", 0)):
        inside = londen.immigrants
    check("the bot's what-ifs put them back", inside == 0 and londen.immigrants == 3 and londen.units == 4)
    check("bot sees only the others as free", londen.free == 1 and londen.keep == 3)

    # Starvation: immigrants only go once no other troop is left.
    a, b, c = reset()
    own(a, "Londen", 5)
    own(a, "Spanje", 1)
    londen, spanje = country("Londen"), country("Spanje")
    londen.immigrants = 3
    app.turn = 0
    rp = m().phases[0]
    rp.starved = 4
    rp.starve_pool = -4
    rp.starve_initial = {n: x.units for n, x in app.countries.items()}
    rp.starve_immigrants = {n: x.immigrants for n, x in app.countries.items()}
    a.attack, a.subattack = 0, 4
    io = app.io

    def click(name, right=True):
        io.hover_country, io.right_clicked, io.left_pressed = name, right, 0 if right else 1
        rp._starvation_pool()
        io.right_clicked, io.left_pressed = False, 0

    for _ in range(3):
        click("Londen")
    check("starving: not the immigrants while others are left", londen.units == 3 and londen.immigrants == 3
          and rp.starve_pool == -2, (londen.units, rp.starve_pool))
    click("Spanje")
    click("Londen")
    check("... only immigrants left: then they starve", londen.units == 2 and londen.immigrants == 2
          and spanje.units == 0 and rp.starve_pool == 0)
    click("Londen", right=False)
    check("put back: the immigrant comes back", londen.units == 3 and londen.immigrants == 3)
    click("Spanje", right=False)
    check("a regular troop put back instead", spanje.units == 1 and rp.starve_pool == -2)
    click("Londen")
    check("... then the immigrants are safe again", londen.units == 3 and rp.starve_pool == -2)

    a, b, c = reset()
    a.is_bot = True
    own(a, "Londen", 5)
    own(a, "Spanje", 2)
    country("Londen").immigrants = 4
    app.turn = 0
    m().phases[0].starved = 3
    m().bot._starve()
    check("bot starves the other troops, not the immigrants",
          country("Londen").units == 4 and country("Londen").immigrants == 4
          and country("Spanje").owner is app.default_player, (country("Londen").units, country("Spanje").owner.name))
    m().phases[0].starved = 1
    m().bot._starve()
    check("... only immigrants left: then one of them", country("Londen").units == 3
          and country("Londen").immigrants == 3)

    a, b, c = reset()
    own(a, "Arabië", 2)
    own(a, "Londen", 5)
    own(a, "Spanje", 4)
    country("Londen").immigrants = 3
    EVENT["Pilgrimage"]._apply(app)
    check("bedevaart: the immigrants stay home",
          country("Londen").owner is a and country("Londen").units == 3 and country("Arabië").units == 2 + 2 + 4 + 5
          and country("Spanje").owner is app.default_player, country("Arabië").units)


@test("Woke")
def _(ev):
    a, b, c = reset()
    own(a, "Londen", 1)
    own(a, "Spanje", 5)
    own(b, "Canada", 5)
    own(b, "Mexico", 1)
    own(c, "Peru", 5)
    activate(ev)
    abandon = m().phases[0].abandon
    app.turn = 0
    abandon(country("Londen"))
    own(a, "Londen", 1)
    abandon(country("Londen"))
    check("a country given back scores once", ev.returned == {"A": ["Londen"]}, ev.returned)
    abandon(country("Mexico"))
    check("someone else's country emptied on A's turn (a nuke) doesn't count", "B" not in ev.returned)
    check("scoreboard in the event panel", ev.panel_lines(app)[1:] == ["A: 1", "B: 0", "C: 0"],
          ev.panel_lines(app))
    a, b, c = save_and_load()
    check("save/load keeps the score", ev.returned == {"A": ["Londen"]})
    m().notices.clear()
    finish()
    check("lowest score (a tie: all of them) is cancelled", m().skip_turns == {"B", "C"}, m().skip_turns)
    check("... with a notice", len(m().notices) == 1)
    a, b, c = save_and_load()
    check("save/load keeps who is cancelled", m().skip_turns == {"B", "C"})
    app.turn = 0
    m().next_turn()
    check("their turns are skipped: back to A", app.turn == 0 and not m().skip_turns,
          (app.players[app.turn].name, m().skip_turns))
    m().next_turn()
    check("... once", app.turn == 1)

    a, b, c = reset()
    a.is_bot = True
    own(a, "Londen", 1)
    own(a, "Spanje", 6)
    own(a, "Nazi-Duitsland", 6)
    own(b, "Canada", 5)
    own(c, "Peru", 5)
    activate(ev)
    app.turn = 0
    a.attack, a.subattack = 2, 0
    check("bot behind: gives a country back as its move", m().bot._give_back(m().phases[2])
          and len(ev.returned.get("A", [])) == 1 and a.repositioned_this_turn, ev.returned)
    check("... and stops once ahead", ev.bot_give_back(app, a) == 0)
    finish()
    check("then only the others are cancelled", m().skip_turns == {"B", "C"})


def generic(ev):
    """Every event: state survives JSON, save/load mid-event, on_end after it."""
    a, b, c = reset()
    for player, names in zip((a, b, c), (("Japan", "Noord-Korea", "Arabië", "India"),
                                         ("Belgisch Congo", "Nigeria", "Los Angeles", "Maleisië"),
                                         ("Sahara", "Brazilië", "Mexico", "Canada"))):
        for name in names:
            own(player, name, 4)
    activate(ev)
    json.dumps(ev.save_state(app))
    check("save_state is JSON", True)
    save_and_load()
    check("save/load keeps the event", m().current_event is ev)
    finish()
    check("on_end runs after a load", True)


def main():
    name_filter = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    tested = set()
    for class_name, fn in TESTS:
        ev = EVENT[class_name]
        tested.add(ev)
        for label, run in (("", fn), (" (save/load)", generic)):
            _current_test[0] = ev.name + label
            if name_filter not in _current_test[0].lower() and name_filter not in class_name.lower():
                continue
            try:
                run(ev)
            except Exception:
                check("ran without crashing", False, traceback.format_exc().strip().splitlines()[-1])
                traceback.print_exc()
    for ev in EVENTS:
        if ev not in tested:
            _current_test[0] = ev.name
            check("has a test in event_checks.py", False)

    failed = 0
    last = None
    for name, description, ok, detail in results:
        if name != last:
            print("\n" + name)
            last = name
        failed += not ok
        print("  {}  {}{}".format("PASS" if ok else "FAIL", description,
                                  "" if ok or detail == "" else "  [{}]".format(detail)))
    print("\n{} checks, {} failed".format(len(results), failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
