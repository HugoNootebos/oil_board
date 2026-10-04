"""
Automated checks for the bots' decisions: sets up a small board, asks the bot
what it makes of it and reports PASS/FAIL per check -- the bot counterpart of
event_checks.py.

    python3 bot_checks.py [name filter]

Headless; your saves are never touched. Exit code 1 if anything failed.
Add a check here when adding a bot behaviour.
"""

import os
import sys
import tempfile
import traceback
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import bot  # noqa: E402
from board import get_connections, get_countries  # noqa: E402
from engine import Engine  # noqa: E402
from models import Player  # noqa: E402
from phases import TurnManager  # noqa: E402
from player_colors import COUNT_MODE_COLORS  # noqa: E402

SAVE = os.path.join(tempfile.gettempdir(), "oil_bot_checks.json")

app = Engine(mode="count", player_count=3, player_names=["A", "B", "C"])
app.save_path = SAVE

# Levels of the same bot with one behaviour switched off, to compare with.
bot.LEVELS["check_old_danger"] = dict(bot.LEVELS["hard"], exposure=0, retention=0)
bot.LEVELS["check_no_strike"] = dict(bot.LEVELS["hard"], strike=0, finish_max=0)

results = []  # (test, description, ok, detail)
_current_test = [""]


def check(description, ok, detail=""):
    results.append((_current_test[0], description, bool(ok), detail))


def reset(level="hard", **stock):
    """Fresh board (everything the mouse's), three players, player A (a bot of
    `level`) to move in the reinforcement phase with nothing to place."""
    app.countries = get_countries(app.default_player)
    app.connections = get_connections()
    app.players = [Player(name, color=COUNT_MODE_COLORS[i], food=1000, wood=0, steel=0, oil=0, nuclear=0)
                   for i, name in enumerate(("A", "B", "C"))]
    for key, value in stock.items():
        setattr(app.players[0], key, value)
    app.turn = 0
    app.card_menu.player = app.players[0]
    app.turn_manager = TurnManager(app)
    manager = app.turn_manager
    manager.turn_num = manager.event_turn_index = len(app.players)
    manager.bot.fast = True
    a = app.players[0]
    a.is_bot, a.bot_level, a.bot_personality = True, level, "balanced"
    a.start_ship = False
    a.attack, a.subattack = 0, 1
    manager.reinforcements = 0
    controller = bot.BotController(manager)
    controller.fast = True
    return controller, app.players


def own(player, name, units, **attrs):
    c = app.countries[name]
    c.owner = player
    c.units = units
    for key, value in attrs.items():
        setattr(c, key, value)
    return c


def links(kind):
    """{country: {neighbours over `kind` links}}"""
    result = {}
    for c in app.connections:
        a, b = tuple(c.connection)
        if c.kind == kind:
            result.setdefault(a, set()).add(b)
            result.setdefault(b, set()).add(a)
    return result


# --- the checks -----------------------------------------------------------------

def test_card_sets():
    cards = lambda *types: [SimpleNamespace(type=t) for t in types]
    check("three different cards are one set worth 10", bot.card_sets(cards(0, 1, 2)) == [10])
    check("three of a kind is worth 2m + 4", bot.card_sets(cards(1, 1, 1)) == [6])
    check("a Joker stands in for any card", bot.card_sets(cards(0, 1, 3)) == [10])
    check("two cards are no set", bot.card_sets(cards(0, 1)) == [])
    check("six different cards are two sets", bot.card_sets(cards(0, 1, 2, 0, 1, 2)) == [10, 10])


def test_exposure_sees_chains():
    # B's stack, then a mouse country, then A's country: nothing of B's touches A's
    # country, but B can take the mouse country on the way and strike from there.
    land = links("land")
    path = None
    for x in sorted(land):
        for m in sorted(land[x]):
            for z in sorted(land[m]):
                if z != x and z not in land[x]:
                    path = (x, m, z)
                    break
            if path:
                break
        if path:
            break
    x, m, z = path
    for level, expect_exposed in (("hard", True), ("check_old_danger", False)):
        ctl, (a, b, c) = reset(level)
        own(b, x, 15)
        own(a, z, 2)
        own(c, "Argentinië" if "Argentinië" not in path else "Peru", 5)
        danger = ctl._danger(app.countries[z])
        check("{}: country {} behind the mouse's {} from B's stack in {} ({:.2f})".format(
            "exposure sees a chain" if expect_exposed else "the old model does not", z, m, x, danger),
            (danger > 0.05) == expect_exposed)


def test_exposure_not_moved_yet():
    ctl, (a, b, c) = reset()
    manager = app.turn_manager
    manager.turn_num = 0  # the very first round: B and C have not moved
    check("a player that has not moved yet is recognised", ctl._not_moved_yet(b) and not ctl._not_moved_yet(a))
    manager.turn_num = 3
    check("after the first round everyone has moved", not ctl._not_moved_yet(b))


def test_water_protection():
    # an island with an enemy stack across the water: protected while the enemy can
    # neither cross nor buy a crossing, exposed once it can buy a ship
    sea, land = links("sea"), links("land")
    island = next(n for n in sorted(sea) if n not in land and len(sea[n]) >= 2)
    shore = sorted(sea[island])[0]
    ctl, (a, b, c) = reset()
    b.start_ship = False
    own(a, island, 1)
    own(b, shore, 15)
    own(c, "Argentinië" if shore != "Argentinië" else "Peru", 3)
    protected = ctl._danger(app.countries[island])
    b.wood = 20
    ctl._cache = {}
    exposed = ctl._danger(app.countries[island])
    check("{} across the water from a 15-stack with no crossing to be had: {:.3f}".format(island, protected),
          protected < 0.02)
    check("... once the enemy can buy a ship: {:.3f}".format(exposed), exposed > protected + 0.05)


def test_retention():
    # a country that will be lost straight away is worth less than one that stays
    land = links("land")
    sea = links("sea")
    island = next(n for n in sorted(sea) if n not in land and len(sea[n]) >= 2)
    mainland = next(n for n in sorted(land) if len(land[n]) >= 3 and n not in sea)
    values = {}
    for level in ("hard", "check_old_danger"):
        ctl, (a, b, c) = reset(level)
        own(b, mainland, 2)
        for neighbour in sorted(land[mainland]):
            own(c, neighbour, 12)
        own(b, island, 2)
        own(a, "Argentinië" if "Argentinië" not in land[mainland] else "Peru", 5)
        values[level] = (ctl._target_value(app.countries[mainland]), ctl._target_value(app.countries[island]))
    gap_new = values["hard"][1] - values["hard"][0]
    gap_old = values["check_old_danger"][1] - values["check_old_danger"][0]
    check("retention values the unreachable {} over the ringed-in {} more than the old model "
          "(gap {:.1f} vs {:.1f})".format(island, mainland, gap_new, gap_old), gap_new > gap_old + 0.5)


def _strike_board(level="hard", nuclear=5, victim_units=10):
    """A holds a stack of 7 next to B's last country (10 troops: too hard to take
    as it is), the third player sits elsewhere."""
    ctl, (a, b, c) = reset(level, nuclear=nuclear)
    land = links("land")
    x = next(n for n in sorted(land) if len(land[n]) >= 2)
    y = sorted(land[x])[0]
    own(a, x, 7)
    own(b, y, victim_units)
    far = "Argentinië" if "Argentinië" not in (x, y) and "Argentinië" not in land[x] else "Gold Coast"
    own(c, far, 5)
    return ctl, (a, b, c), x, y


def test_strike_nuke():
    ctl, (a, b, c), x, y = _strike_board(nuclear=5)
    check("without a nuke the 10-troop last country is not worth a hunt", b not in ctl._hunt())
    plan = ctl._strike_plan()
    check("the strike plan uses the nuke on the victim's last country",
          plan is not None and plan[1]["nukes"] == [y], str(plan and plan[1]["nukes"]))
    steps = 0
    while ctl._strike_step() and steps < 10:
        steps += 1
    check("the nuke was fired: {} halves to 5 and A's nuclear is spent".format(y),
          app.countries[y].units == 5 and a.nuclear == 0, "units {} nuclear {}".format(app.countries[y].units, a.nuclear))
    ctl._cache = {}
    check("... and the hunt now goes for B", b in ctl._hunt())


def test_strike_nothing_to_convert():
    ctl, (a, b, c), x, y = _strike_board(nuclear=0)
    check("with nothing to convert there is no strike", ctl._strike_plan() is None)
    ctl, (a, b, c), x, y = _strike_board(level="check_no_strike", nuclear=5)
    steps = 0
    while ctl._strike_step() and steps < 10:
        steps += 1
    check("with the strike tunables at 0 nothing is fired", app.countries[y].units == 10 and a.nuclear == 5)


def test_finisher():
    ctl, (a, b, c), x, y = _strike_board(nuclear=10, victim_units=3)
    check("a sure elimination: 3 troops take 2 nukes and A holds 2", ctl._finish_step())
    check("... the first nuke halves the garrison", app.countries[y].units == 1)
    check("... the second one wipes B out", ctl._finish_step() and app.countries[y].owner is app.default_player
          and not any(cc.owner is b for cc in app.countries.values()))
    import numpy as np
    ctl, (a, b, c), x, y = _strike_board(nuclear=10, victim_units=3)
    app.countries[y].units = np.int64(3)  # troop counts that came out of dice are numpy ints
    check("it copes with numpy troop counts", ctl._finish_step())
    ctl, (a, b, c), x, y = _strike_board(nuclear=5, victim_units=3)
    check("one nuke short of a sure elimination: it waits", not ctl._finish_step() and app.countries[y].units == 3)
    ctl, (a, b, c), x, y = _strike_board(level="check_no_strike", nuclear=10, victim_units=3)
    check("finish_max 0 switches it off", not ctl._finish_step())


def test_loot_constants():
    ctl, (a, b, c), x, y = _strike_board(nuclear=0)
    b.wood = 4
    base_prize = ctl._prize(b)
    bot.LEVELS["check_rival"] = dict(bot.LEVELS["hard"], rival_value=12.0, loot_card=5.0)
    ctl2, (a2, b2, c2), x2, y2 = _strike_board(level="check_rival", nuclear=0)
    b2.wood = 4
    check("rival_value adds to the prize ({:.1f} -> {:.1f})".format(base_prize, ctl2._prize(b2)),
          abs(ctl2._prize(b2) - base_prize - 6.0) < 1e-9)


def test_endgame():
    land = links("land")
    x, y, z = [n for n in sorted(land) if len(land[n]) >= 2][:3]
    hard = bot.LEVELS["hard"]
    ctl, (a, b, c) = reset()
    own(a, x, 10)
    own(b, y, 6)
    own(c, z, 6)
    check("three players, the leader at 42% of the strength: no endgame yet", not ctl._endgame()
          and ctl.params["price_factor"] == hard["price_factor"])
    c.eliminated = True
    own(c, z, 6)
    app.countries[z].owner = app.default_player
    ctl._cache = {}  # the board changed under the bot
    check("two players left, A in the lead: the endgame", ctl._endgame())
    check("... the shop's price factor goes to {} and weak sets are traded".format(hard["price_factor"] * hard["endgame_price"]),
          ctl.params["price_factor"] == hard["price_factor"] * hard["endgame_price"] and not ctl.params["hold_weak_sets"])
    app.turn = 1  # B (the trailer, also a hard bot) decides
    b.bot_level = "hard"
    ctl._cache = {}
    check("... but not for the trailer", not ctl._endgame() and ctl.params["price_factor"] == hard["price_factor"])
    app.turn = 0
    ctl._cache = {}
    own(a, x, 60)
    c.eliminated = False
    app.countries[z].owner = c
    check("three players, A holding 70%+ of the strength: the endgame", ctl._endgame())
    bot.LEVELS["check_no_endgame"] = dict(hard, endgame_alive=0, endgame_lead=1.1)
    ctl2, (a2, b2, c2) = reset("check_no_endgame")
    own(a2, x, 60)
    own(b2, y, 2)
    check("with the endgame tunables off nothing changes", not ctl2._endgame())


def test_buffer():
    land = links("land")
    x = next(n for n in sorted(land) if len(land[n]) >= 3)
    y, w = sorted(land[x])[:2]
    far = next(n for n in sorted(land) if n not in (x, y, w) and n not in land[x] and n not in land[y] and n not in land[w])
    bot.LEVELS["check_buffer"] = dict(bot.LEVELS["hard"], buffer=1, buffer_min_gain=-1e9, buffer_min_exposure=0.1)
    for level, expect in (("check_buffer", True), ("hard", False)):
        ctl, (a, b, c) = reset(level)
        own(a, x, 1)
        own(a, y, 5)
        own(a, far, 3)
        own(b, w, 15)
        own(c, "Argentinië" if "Argentinië" not in (x, y, w, far) else "Peru", 4)
        phase = app.turn_manager.phases[2]
        a.attack, a.subattack = 2, 0
        a.repositioned_this_turn = False
        moved = ctl._reposition(phase) if level == "hard" else ctl._buffer_run(phase)
        emptied = app.countries[x].owner is app.default_player
        if expect:
            check("buffer on: the exposed 1-troop {} is emptied into {} and goes to the mouse".format(x, y),
                  moved and emptied and app.countries[y].units == 6 and a.repositioned_this_turn)
            check("... with the mouse's native garrison ({}) on it".format(app.countries[x].units),
                  app.countries[x].units == app.initial_country_units.get(x, 2))
            ctl._cache = {}
            check("... and the bot leaves it alone while it is exposed", not ctl._retake_ok(app.countries[x]))
        else:
            check("buffer off (the default): nothing is emptied", not emptied)


def test_exposure_risk():
    land = links("land")
    path = None
    for x in sorted(land):
        for m in sorted(land[x]):
            for z in sorted(land[m]):
                if z != x and z not in land[x]:
                    path = (x, m, z)
                    break
            if path:
                break
        if path:
            break
    x, m, z = path
    bot.LEVELS["check_risk"] = dict(bot.LEVELS["hard"], risk_exposure=1)
    risks = {}
    for level in ("hard", "check_risk"):
        ctl, (a, b, c) = reset(level)
        own(a, z, 2)
        own(b, x, 15)
        own(c, "Argentinië" if "Argentinië" not in path else "Peru", 5)
        risks[level] = ctl._elimination_risk()
    check("a player's last country behind the mouse's {} from a 15-stack: the old model says safe ({:.2f})".format(m, risks["hard"]),
          risks["hard"] < 0.02)
    check("... the exposure model sees the chain ({:.2f})".format(risks["check_risk"]), risks["check_risk"] > 0.1)
    ctl, (a, b, c) = reset("check_risk")
    own(a, z, 2)
    own(b, x, 15)
    own(c, "Argentinië" if "Argentinië" not in path else "Peru", 5)
    wiped = ctl._elimination_risk(0, {b: 99})
    check("... and B wiped out is no threat any more ({:.2f})".format(wiped), wiped < risks["check_risk"] / 2)


# --- running them ------------------------------------------------------------------

def main():
    wanted = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    tests = [(name[5:], fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        if wanted and wanted not in name:
            continue
        _current_test[0] = name
        try:
            fn()
        except Exception:
            check("raised an exception", False, traceback.format_exc().strip().splitlines()[-1])
            traceback.print_exc()
    failed = 0
    current = None
    for name, description, ok, detail in results:
        if name != current:
            print("\n" + name)
            current = name
        failed += not ok
        print("  {}  {}{}".format("PASS" if ok else "FAIL", description, "" if ok or not detail else "  [" + detail + "]"))
    print("\n{} checks, {} failed".format(len(results), failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
