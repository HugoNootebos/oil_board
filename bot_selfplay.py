"""
Bots playing whole games against each other, headless and as fast as
possible -- for testing and tuning bot.py.

    python3 bot_selfplay.py [games] [players]
        Every seat is the current bot. Prints each game's winner, number
        of turns and time taken.

    python3 bot_selfplay.py [games] [players] --vs OTHER_BOT.py
        A/B test of the current bot.py (side A) against the bot in another
        file (side B), e.g. an older version:
            git show <commit>:bot.py > /tmp/old_bot.py

    python3 bot_selfplay.py [games] [players] --levels hard,normal
        A/B test between two difficulty levels of the current bot.

    python3 bot_selfplay.py [games] [players] --levels hard,hard --tweak attack_min_p=0.5
        A/B test of a tuning change: side A plays its level with the
        tweaked values (--tweak can be repeated).

    python3 bot_selfplay.py [games] [players] --levels hard,hard --personality turtle
        A/B test of a personality: side A plays it, side B balanced.

A/B tests play "hard" against "hard" unless --levels says otherwise, and
every bot is "balanced" unless --personality says otherwise; --jobs N
plays N games at once (one per CPU core).

In an A/B test the seats alternate between the sides, and every game is
played twice from the same start (seed) with the sides swapped, so both
get the same starting countries and turn order. It prints side A's win
rate with a 95% margin, then the "smarter" criterion: what each side
steals by eliminating players (resources, plus CARD_LOOT a card) against
how often it's eliminated itself. Then per side: eliminations made and
their loot, troops lost to starvation, players that died on their own
turn (starved out) or were eliminated by a player, oil left unused, and
what they bought and traded for. --seed picks the first
seed, so a run can be repeated exactly.

Autosaves go to a temporary file, not saves/autosave.json.
"""

import argparse
import ast
import collections
import importlib.util
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402

import bot  # noqa: E402
import phases  # noqa: E402
from engine import Engine  # noqa: E402
from models import CardMenu  # noqa: E402

MAX_TURNS = 600
# The "smarter" criterion: what a side steals by eliminating players (the
# loser's wood, steel, nuclear, oil -- and food under Einde van de
# mensheid -- plus their cards, a card counted as this many resources,
# roughly what it trades for), against how often it gets eliminated itself.
CARD_LOOT = 8


class MixedBots:
    """Stands in for TurnManager.bot in an A/B game: every decision goes to
    the controller of the side the deciding player is on."""

    fast = True
    notice_ms = 0
    dice_ms = 0

    def __init__(self, manager, controllers):
        self.manager = manager
        self.controllers = controllers  # {player: controller}

    def update(self):
        engine = self.manager.engine
        self.controllers[engine.players[engine.turn]].update()

    def defence_tanks(self, country):
        controller = self.controllers[country.owner]
        if hasattr(controller, "defence_tanks"):
            return controller.defence_tanks(country)
        # An older bot.py: a module-level function.
        return sys.modules[type(controller).__module__].defence_tanks(self.manager.engine, country)

    def __getattr__(self, name):
        # Anything else asked of "the bot" (a decision for a player who may
        # not be the current one): the deciding player is the first
        # argument. An older bot without that decision gets today's.
        def call(player, *args, **kwargs):
            controller = self.controllers[player]
            if not hasattr(controller, name):
                controller = bot.BotController(self.manager)
            return getattr(controller, name)(player, *args, **kwargs)
        return call


class Stats:
    """Tallies per side, gathered by wrapping a few game methods (so only
    one per process)."""

    def __init__(self):
        self.side_of = {}  # player -> "A" / "B"
        self.count = collections.defaultdict(collections.Counter)
        self._install()

    def add(self, player, key, amount=1):
        side = self.side_of.get(player)
        if side is not None:
            self.count[side][key] += amount

    def _install(self):
        stats = self

        def wrap(cls, name, before=None, after=None):
            original = getattr(cls, name)

            def wrapper(self, *args, **kwargs):
                state = before(self, *args, **kwargs) if before else None
                result = original(self, *args, **kwargs)
                if after:
                    after(self, result, state, *args, **kwargs)
                return result
            setattr(cls, name, wrapper)

        def current(phase):
            engine = phase.engine
            return engine.players[engine.turn]

        def started(phase, result, state):
            if phase.player.subattack == 3:
                stats.add(phase.player, "troops starved", phase.starved)
        wrap(phases.ReinforcementPhase, "_start_turn", after=started)

        def eliminated(manager, player):
            victor = manager.elimination_loot.get(player, (None, []))[0]
            if victor is not None:
                stats.add(player, "eliminated by a player")
            elif player is current(manager.phases[0]):
                stats.add(player, "died on own turn")
            else:
                stats.add(player, "died otherwise")
        wrap(phases.TurnManager, "_eliminate", before=eliminated)

        def took_last(phase, result, state, player, country):
            loser, before = state
            entry = phase.manager.elimination_loot.get(loser)
            if entry is None or entry is before:
                return  # not their last country
            victor, loot = entry
            stats.add(victor, "eliminations made")
            for amount, what in loot:
                stats.add(victor, "loot: " + what, amount)
                stats.add(victor, "loot score", amount * (CARD_LOOT if what == "cards" else 1))
        wrap(phases.Phase, "take_last_country",
             before=lambda phase, player, country: (country.owner, phase.manager.elimination_loot.get(country.owner)),
             after=took_last)

        def turn_end(manager):
            player = current(manager.phases[0])
            if player.attack == 2:
                stats.add(player, "turns")
                stats.add(player, "oil at turn end", player.oil)
                stats.add(player, "food at turn end", player.food)
                stats.add(player, "troops at turn end", sum(
                    c.units for c in manager.engine.countries.values() if c.owner is player))
        wrap(phases.TurnManager, "end_phase", before=turn_end)

        def bought(what):
            return lambda phase, *args, **kwargs: stats.add(current(phase), "bought " + what)
        wrap(phases.ShopPhase, "drop_nuke", before=bought("nuke"))
        wrap(phases.ShopPhase, "place_unit",
             before=lambda phase, attr, *a: stats.add(current(phase), "bought " + attr))
        wrap(phases.ShopPhase, "place_fort",
             after=lambda phase, ok, state, *a: ok and stats.add(current(phase), "bought forts"))
        for method, what in (("build_rails", "rails"), ("build_bridge", "bridges")):
            if hasattr(phases.ShopPhase, method):
                wrap(phases.ShopPhase, method,
                     after=lambda phase, ok, state, *a, what=what: ok and stats.add(current(phase), "bought " + what))
        wrap(phases.MovementPhase, "develop", before=bought("developments"))

        def traded(menu, reward, amount):
            stats.add(menu.player, "cards traded for " + reward)
        wrap(CardMenu, "_execute_trade", before=traded)


def load_bot_module(path):
    spec = importlib.util.spec_from_file_location("other_bot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def play_game(player_count, seed, sides=None, levels=None, other=None, stats=None, personality=None):
    """One headless game. `sides` gives each seat's side ("A"/"B"), or None
    when every seat is the current bot. Side B plays `other`'s bot (a
    module) if given; `levels` ({side: level}) sets each side's level.
    `personality` is side A's (everyone else is balanced). Returns
    (winning side or name, number of turns)."""
    np.random.seed(seed)
    random.seed(seed)
    names = ["Bot {}".format(i + 1) for i in range(player_count)]
    if sides:
        names = ["{} {}".format(side, i + 1) for i, side in enumerate(sides)]
    app = Engine(mode="count", player_count=player_count, player_names=names,
                 player_bots=[True] * player_count)
    app.save_path = os.path.join(tempfile.gettempdir(), "oil_bot_selfplay.json")
    manager = app.turn_manager
    manager.bot.fast = True
    if sides:
        for player, side in zip(app.players, sides):
            player.bot_personality = personality if personality and side == "A" else bot.DEFAULT_PERSONALITY
            if levels:
                player.bot_level = levels[side]
            if stats is not None:
                stats.side_of[player] = side
        if other is not None:
            controllers = {}
            for player, side in zip(app.players, sides):
                module = other if side == "B" else bot
                controller = module.BotController(manager)
                controller.fast = True
                controllers[player] = controller
            manager.bot = MixedBots(manager, controllers)
    while not manager.game_over and manager.turn_num < MAX_TURNS:
        app.io_handle()
        app.update_turn()
    alive = [p for p in app.players if not p.eliminated]
    winner = alive[0] if manager.game_over and alive else None
    if winner is None:
        return None, manager.turn_num
    return (sides[app.players.index(winner)] if sides else winner.name), manager.turn_num


# One A/B game per call, possibly in a worker process (--jobs): each
# process loads the other bot and installs the stats hooks once.
_worker = {}


def _init_worker(tweaked, other_path, personality):
    if tweaked:
        bot.LEVELS["tweaked"] = tweaked
    _worker["other"] = load_bot_module(other_path) if other_path else None
    _worker["stats"] = Stats()
    _worker["personality"] = personality


def _ab_game(job):
    i, players, seed, levels = job
    # Pairs of games from the same seed, sides swapped.
    sides = ["A" if (seat % 2 == 0) == (i % 2 == 0) else "B" for seat in range(players)]
    stats = _worker["stats"]
    stats.side_of.clear()
    stats.count.clear()
    winner, turns = play_game(players, seed + i // 2, sides, levels, _worker["other"], stats,
                              _worker["personality"])
    return winner, turns, {side: dict(counter) for side, counter in stats.count.items()}


def ab_test(games, players, seed, levels, tweaked=None, other_path=None, jobs=1, personality=None):
    wins = collections.Counter()
    totals = collections.defaultdict(collections.Counter)
    turns = []
    # Per game, side A minus side B: loot score, and times eliminated.
    loot_gap, elim_gap = [], []
    eliminated_keys = ("eliminated by a player", "died on own turn", "died otherwise")
    start = time.time()
    job_list = [(i, players, seed, levels) for i in range(games)]
    if jobs > 1:
        import multiprocessing
        pool = multiprocessing.Pool(jobs, initializer=_init_worker, initargs=(tweaked, other_path, personality))
        results = pool.imap_unordered(_ab_game, job_list)
    else:
        _init_worker(tweaked, other_path, personality)
        pool = None
        results = map(_ab_game, job_list)
    for done, (winner, n, counts) in enumerate(results, 1):
        wins[winner] += 1
        turns.append(n)
        for side, counter in counts.items():
            totals[side].update(counter)
        side_a, side_b = counts.get("A", {}), counts.get("B", {})
        loot_gap.append(side_a.get("loot score", 0) - side_b.get("loot score", 0))
        elim_gap.append(sum(side_a.get(k, 0) - side_b.get(k, 0) for k in eliminated_keys))
        decided = wins["A"] + wins["B"]
        if done % 10 == 0 or done == games:
            rate = wins["A"] / decided if decided else 0
            print("{:4d} games: A {:3d}  B {:3d}  draws {:2d}  A win rate {:.1%}  ({:.0f} s)".format(
                done, wins["A"], wins["B"], wins[None], rate, time.time() - start), flush=True)
    if pool is not None:
        # Every result is in: stop the workers rather than wait for them to
        # wind down (a worker can hang on exit).
        pool.terminate()
        pool.join()
    decided = wins["A"] + wins["B"]
    rate = wins["A"] / decided if decided else 0
    margin = 1.96 * (rate * (1 - rate) / decided) ** 0.5 if decided else 0
    print()
    print("A win rate {:.1%} +- {:.1%} over {} decided games; median game {} turns".format(
        rate, margin, decided, sorted(turns)[len(turns) // 2]))

    def per_game(side, *keys):
        return sum(totals[side][k] for k in keys) / games

    def gap(values):
        """Mean of A-minus-B per game, with a 95% margin."""
        mean = sum(values) / len(values)
        spread = (sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)) ** 0.5
        return "{:+.2f} +- {:.2f}".format(mean, 1.96 * spread / len(values) ** 0.5)
    print("Loot stolen by eliminating players, per game (resources + {} a card): A {:.1f}, B {:.1f} "
          "(A-B {})".format(CARD_LOOT, per_game("A", "loot score"), per_game("B", "loot score"), gap(loot_gap)))
    print("Eliminated, per game: A {:.2f}, B {:.2f} (A-B {})".format(
        per_game("A", *eliminated_keys), per_game("B", *eliminated_keys), gap(elim_gap)))
    print()
    keys = sorted(set(totals["A"]) | set(totals["B"]))
    per_turn = ("oil at turn end", "food at turn end", "troops at turn end")
    print("{:28s} {:>10s} {:>10s}".format("per game (per turn for *)", "A", "B"))
    for key in keys:
        if key == "turns":
            continue
        row = []
        for side in "AB":
            value = totals[side][key]
            if key in per_turn:
                row.append(value / max(totals[side]["turns"], 1))
            else:
                row.append(value / games)
        label = key + (" *" if key in per_turn else "")
        print("{:28s} {:10.2f} {:10.2f}".format(label, *row))


def main():
    parser = argparse.ArgumentParser(description="Headless bot-vs-bot games.")
    parser.add_argument("games", nargs="?", type=int, default=1)
    parser.add_argument("players", nargs="?", type=int, default=4)
    parser.add_argument("--vs", metavar="BOT_FILE", help="A/B test against the bot in this file")
    parser.add_argument("--levels", metavar="A,B", help="A/B test between two levels of the current bot")
    parser.add_argument("--tweak", metavar="KEY=VALUE", action="append", default=[],
                        help="change one of side A's tunables")
    parser.add_argument("--personality", choices=sorted(bot.PERSONALITIES),
                        help="side A's personality (everyone else is balanced)")
    parser.add_argument("--seed", type=int, default=1, help="seed of the first game")
    parser.add_argument("--jobs", type=int, default=1, help="games played at once (one per CPU core)")
    args = parser.parse_args()

    if args.vs or args.levels or args.tweak or args.personality:
        a, b = (args.levels or "hard,hard").split(",")
        levels = {"A": a.strip(), "B": b.strip()}
        tweaked = None
        if args.tweak:
            tweaked = dict(bot.LEVELS[levels["A"]])
            for item in args.tweak:
                key, value = item.split("=")
                if key not in tweaked:
                    parser.error("unknown tunable: " + key)
                tweaked[key] = type(tweaked[key])(ast.literal_eval(value))
            levels["A"] = "tweaked"
        ab_test(args.games, args.players, args.seed, levels, tweaked, args.vs, args.jobs, args.personality)
        return

    for i in range(args.games):
        start = time.time()
        winner, turns = play_game(args.players, args.seed + i)
        print("game {}: {} after {} turns ({:.1f} s)".format(
            i + 1, winner or "no winner", turns, time.time() - start))


if __name__ == "__main__":
    main()
