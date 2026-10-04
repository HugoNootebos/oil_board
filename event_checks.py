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
            else:
                check("land attack: never hit", country("Japan").units == 7 and a.subattack == 3)
    finally:
        del ev.sea_attack_check
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
