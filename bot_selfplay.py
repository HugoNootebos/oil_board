"""
Bots playing whole games against each other, headless and as fast as
possible -- for testing and tuning bot.py.

    python3 bot_selfplay.py [games] [players]
        Every seat is the current bot. Prints each game's winner, number
        of turns and time taken. (players can be a list: 3,4,5,6.)

    python3 bot_selfplay.py [games] [players] --vs OTHER_BOT.py
        A/B test of the current bot.py (side A) against the bot in another
        file (side B), e.g. a copy of an older version (old_bot.py).
        --botA FILE puts a file on side A instead of bot.py.

    python3 bot_selfplay.py [games] [players] --tweakA attack_min_p=0.5
        A/B test of a tuning change: side A plays with the tweaked
        values (--tweakA and --tweakB can be repeated; --tweak is
        the same as --tweakA).

    python3 bot_selfplay.py [games] [players] --personality turtle
        A/B test of a personality: side A plays it, side B balanced.

Every bot plays the "hard" tunables (tweaked where --tweakA/--tweakB say
so) and is "balanced" unless --personality says otherwise. --jobs N plays
N games at once (one per CPU core); --maxturns N stops a game after N turns
(default 600; 24 turns is "6 rounds" at 4 players, a quick screen); --out
FILE is where the results go (one JSON line per game, so a crashed run
keeps what it had; default in the temp folder).

Games are reproducible: the same seed gives the same game, whichever
process or run it is played in. (The runner pins PYTHONHASHSEED to 0 for
that, and models.py hashes players, countries and connections by name.)
Autosaves and the mouse hover test are skipped, which makes a game faster.

In an A/B test the seats alternate between the sides, and every game is
played twice from the same start (seed) with the sides swapped, so both
get the same starting countries and turn order. When it is done it runs
bot_report.py on the results: side A's win rate, the placement score
(winner 1 ... first eliminated 0) and the "smarter" criterion -- what each
side steals by eliminating players (loot) against how often it gets
eliminated itself -- as differences per pair of games with 95% margins,
then the KPIs of the behaviours the bots are tuned for. `python3
bot_report.py FILE` redoes that for saved results.

Reading the numbers: 400 games only separate sides that differ by about 7
points of win rate, so a change is first judged by the KPI it is meant to
move (they are far more sensitive) and only confirmed by win rate. Even
two identical bots don't give a clean "no difference" when one has a
tiny tweak: a change that does nothing but alter the odd choice (try
--tweakA noise=0.02 --tweakB noise=0.02) already moves the placement a
bit, so compare against such a noise-matched control rather than against
zero.
"""

import os
import sys

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    # Sets of strings iterate in a different order in every process unless
    # the hash seed is fixed; worker processes inherit this.
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import argparse
import ast
import collections
import importlib.util
import json
import random
import signal
import subprocess
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402

import bot  # noqa: E402
import models  # noqa: E402
import phases  # noqa: E402
import save_load  # noqa: E402
from bot_kpi import Kpi  # noqa: E402
from engine import Engine  # noqa: E402
from models import CardMenu  # noqa: E402

MAX_TURNS = 600
# The "smarter" criterion: what a side steals by eliminating players (the
# loser's wood, steel, nuclear, oil -- and food under Einde van de
# mensheid -- plus their cards, a card counted as this many resources,
# roughly what it trades for), against how often it gets eliminated itself.
CARD_LOOT = 8
# The same with what the loot is worth to a bot: oil can't be spent on
# anything that matters (31% of the legacy loot is oil), a nuclear is
# worth a fifth of a nuke, a card is about 4 troops.
MARKET_LOOT = {"wood": 1, "steel": 1, "nuclear": 2, "oil": 0, "food": 0, "cards": 5}


def patch_headless():
    """What a game played without a window can do without: the mouse hover
    test (a third of the time) and the autosave after every turn."""
    models.Io.update = lambda self, view, countries: None
    save_load.save_game = lambda *args, **kwargs: None


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
                stats.add(victor, "loot market", amount * MARKET_LOOT.get(what, 0))
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
    # A name of its own per file, so two files (--botA and --vs) can be loaded.
    spec = importlib.util.spec_from_file_location("bot_file_" + os.path.splitext(os.path.basename(path))[0], path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def play_game(player_count, seed, sides=None, levels=None, modules=None, stats=None, kpi=None,
              personality=None, maxturns=MAX_TURNS, slim=False):
    """One headless game, the same every time for a seed. `sides` gives each
    seat's side ("A"/"B"), or None when every seat is the current bot;
    `levels` ({side: level}) and `modules` ({side: bot module}) say what
    each side plays; `personality` is side A's (everyone else is balanced).
    Returns a dict, the JSON line of an A/B run: winner (a side, or a seat's
    name without sides; None for no winner), turns, the Stats counts and,
    with a `kpi`, its counters, eliminations and (unless `slim`) per-turn
    series."""
    started, cpu = time.time(), time.process_time()
    np.random.seed(seed)
    random.seed(seed)
    names = ["Bot {}".format(i + 1) for i in range(player_count)]
    if sides:
        names = ["{} {}".format(side, i + 1) for i, side in enumerate(sides)]
    app = Engine(mode="count", player_count=player_count, player_names=names,
                 player_bots=[True] * player_count)
    app.save_path = os.path.join(tempfile.gettempdir(), "oil_bot_selfplay_{}.json".format(os.getpid()))
    manager = app.turn_manager
    manager.bot.fast = True
    if sides:
        for player, side in zip(app.players, sides):
            player.bot_personality = personality if personality and side == "A" else bot.DEFAULT_PERSONALITY
            if levels:
                player.bot_level = levels[side]
            if stats is not None:
                stats.side_of[player] = side
        if modules and any(module is not bot for module in modules.values()):
            controllers = {}
            for player, side in zip(app.players, sides):
                controller = modules[side].BotController(manager)
                controller.fast = True
                controllers[player] = controller
            manager.bot = MixedBots(manager, controllers)
    if kpi is not None:
        kpi.reset(app)
    while not manager.game_over and manager.turn_num < maxturns:
        app.io_handle()
        app.update_turn()
        if kpi is not None:
            kpi.tick()
    alive = [p for p in app.players if not p.eliminated]
    winner = alive[0] if manager.game_over and alive else None
    result = dict(seed=seed, players=player_count, sides=sides, turns=manager.turn_num,
                  winner=None if winner is None else (sides[app.players.index(winner)] if sides else winner.name),
                  wall=round(time.time() - started, 2), cpu=round(time.process_time() - cpu, 2),
                  personalities=[p.bot_personality for p in app.players],
                  levels=[p.bot_level for p in app.players])
    if stats is not None:
        result["count"] = {side: dict(counter) for side, counter in stats.count.items()}
    if kpi is not None:
        for player in app.players:
            if player.start_ship and not player.eliminated:
                kpi.add(player, "first_ship_never", 1)
        result.update(k={side: dict(counter) for side, counter in kpi.k.items()}, elims=kpi.elims)
        if not slim:
            result.update(series=kpi.series, end=[
                dict(p=i, alive=not p.eliminated, stock=[p.wood, p.steel, p.oil, p.nuclear, p.food, len(p.cards)],
                     start_ship=bool(p.start_ship),
                     n=sum(1 for c in app.countries.values() if c.owner is p),
                     troops=sum(c.units for c in app.countries.values() if c.owner is p))
                for i, p in enumerate(app.players)])
    return result


# One game per call, in a worker process when --jobs says so: each process
# loads the bot files, installs the stats hooks and patches the game once.
_worker = {}


def _tweaked(module, level, items, name):
    """Register a level of `module`: `level` with the KEY=VALUE overrides in `items`."""
    values = dict(module.LEVELS[level])
    for item in items:
        key, value = item.split("=")
        if key not in values:
            raise SystemExit("unknown tunable: " + key)
        values[key] = type(values[key])(ast.literal_eval(value))
    module.LEVELS[name] = values


def _init_worker(cfg):
    patch_headless()
    _worker["cfg"] = cfg
    if cfg["plain"]:
        return
    module_a = load_bot_module(cfg["botA"]) if cfg["botA"] else bot
    module_b = load_bot_module(cfg["vs"]) if cfg["vs"] else bot
    levels = list(cfg["levels"])
    if cfg["tweakA"]:
        _tweaked(module_a, levels[0], cfg["tweakA"], "tweakedA")
        levels[0] = "tweakedA"
    if cfg["tweakB"]:
        _tweaked(module_b, levels[1], cfg["tweakB"], "tweakedB")
        levels[1] = "tweakedB"
    _worker["levels"] = {"A": levels[0], "B": levels[1]}
    _worker["modules"] = {"A": module_a, "B": module_b}
    _worker["stats"] = Stats()
    _worker["kpi"] = None if cfg["no_kpi"] else Kpi(_worker["stats"])
    if cfg.get("refund"):
        install_refund(_worker["stats"], cfg["refund"])


def install_refund(stats, side):
    """A research oracle (--refund-assets A|B): `side` gets the price of every ship, tank,
    plane and fort destroyed on it back, in wood and steel -- what perfect care of assets
    could at most save, without changing how the bot plays."""
    import engine as engine_module
    original = engine_module.Engine.log_destroyed

    def refund(self, owner, country_name, ships=0, tanks=0, planes=0, fort=0):
        if owner is not None and stats.side_of.get(owner) == side:
            owner.wood += 15 * ships + sum(10 + 5 * k for k in range(fort))
            owner.steel += 20 * tanks + 10 * planes
        return original(self, owner, country_name, ships, tanks, planes, fort)
    engine_module.Engine.log_destroyed = refund


def _alarm(signum, frame):
    raise TimeoutError("game took too long (hung?)")


def _play(job):
    """Play game `i` of the run: the pair `i // 2` (seed, player count), with
    the sides on the seats swapped between the two games of a pair."""
    i, players, seed = job
    cfg = _worker["cfg"]
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(cfg["timeout"])
    try:
        if cfg["plain"]:
            result = play_game(players, seed, maxturns=cfg["maxturns"])
        else:
            sides = ["A" if (seat % 2 == 0) == (i % 2 == 0) else "B" for seat in range(players)]
            _worker["stats"].side_of.clear()
            _worker["stats"].count.clear()
            result = play_game(players, seed, sides, _worker["levels"], _worker["modules"], _worker["stats"],
                               _worker["kpi"], cfg["personality"], cfg["maxturns"], cfg["slim"])
        result["i"] = i
        return result
    except Exception as exc:  # a crashing game is data, not a reason to lose the run
        import traceback
        return dict(i=i, seed=seed, players=players, error=repr(exc), tb=traceback.format_exc()[-1500:])
    finally:
        signal.alarm(0)


def run(cfg, games, players, seed, jobs, out):
    """Play the games, write one JSON line each to `out`, print progress."""
    # In an A/B test pair p of games (the same seed, sides swapped) is
    # played at player count players[p % len(players)]; plain games each
    # get a seed of their own.
    step = 1 if cfg["plain"] else 2
    job_list = [(i, players[(i // step) % len(players)], seed + i // step) for i in range(games)]
    started = time.time()
    if jobs > 1:
        import multiprocessing
        pool = multiprocessing.Pool(jobs, initializer=_init_worker, initargs=(cfg,))
        results = pool.imap_unordered(_play, job_list)
    else:
        pool = None
        _init_worker(cfg)
        results = map(_play, job_list)
    with open(out, "a") as f:
        for done, result in enumerate(results, 1):
            f.write(json.dumps(result, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
            f.flush()
            if "error" in result:
                print("game {} (seed {}, {} players) crashed: {}".format(
                    result["i"], result["seed"], result["players"], result["error"]), flush=True)
            elif cfg["plain"]:
                print("game {}: {} after {} turns ({:.1f} s)".format(
                    done, result["winner"] or "no winner", result["turns"], result["wall"]), flush=True)
            elif done % 10 == 0 or done == games:
                print("{:4d}/{} games ({:.0f} s)".format(done, games, time.time() - started), flush=True)
    if pool is not None:
        # Every result is in: stop the workers rather than wait for them to
        # wind down (a worker can hang on exit).
        pool.terminate()
        pool.join()


def main():
    parser = argparse.ArgumentParser(description="Headless bot-vs-bot games.")
    parser.add_argument("games", nargs="?", type=int, default=1)
    parser.add_argument("players", nargs="?", default="4", help="player count, or a list such as 3,4,5,6")
    parser.add_argument("--vs", metavar="BOT_FILE", help="A/B test against the bot in this file (side B)")
    parser.add_argument("--botA", metavar="BOT_FILE", help="the bot in this file plays side A (default bot.py)")
    parser.add_argument("--tweak", "--tweakA", dest="tweakA", metavar="KEY=VALUE", action="append", default=[],
                        help="change one of side A's tunables (repeatable)")
    parser.add_argument("--tweakB", metavar="KEY=VALUE", action="append", default=[],
                        help="change one of side B's tunables (repeatable)")
    parser.add_argument("--personality", choices=sorted(bot.PERSONALITIES),
                        help="side A's personality (everyone else is balanced)")
    parser.add_argument("--seed", type=int, default=1, help="seed of the first game")
    parser.add_argument("--jobs", type=int, default=1, help="games played at once (one per CPU core)")
    parser.add_argument("--maxturns", type=int, default=MAX_TURNS, help="stop a game after this many turns")
    parser.add_argument("--timeout", type=int, default=900, help="seconds before a game counts as hung")
    parser.add_argument("--out", metavar="FILE", help="where the results go, one JSON line per game")
    parser.add_argument("--refund-assets", choices=["A", "B"], help="research oracle: this side gets the price of every asset it loses back")
    parser.add_argument("--no-kpi", action="store_true", help="skip the KPI counters (a little faster)")
    parser.add_argument("--slim", action="store_true", help="leave the per-turn series out of the results")
    args = parser.parse_args()

    players = [int(n) for n in args.players.split(",")]
    plain = not (args.vs or args.botA or args.tweakA or args.tweakB or args.personality or args.refund_assets)
    cfg = dict(plain=plain, botA=args.botA, vs=args.vs, levels=["hard", "hard"],
               tweakA=args.tweakA, tweakB=args.tweakB, personality=args.personality,
               maxturns=args.maxturns, timeout=args.timeout, no_kpi=args.no_kpi, slim=args.slim, refund=args.refund_assets)
    out = args.out or os.path.join(tempfile.gettempdir(), "oil_selfplay_{}.jsonl".format(int(time.time())))
    run(cfg, args.games, players, args.seed, args.jobs, out)
    if not plain:
        print("\nresults in {}\n".format(out), flush=True)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_report.py"), out])


if __name__ == "__main__":
    main()
