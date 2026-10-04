"""
Forked what-ifs: the cheapest way to tell whether a bot behaviour pays at the
moment it applies, much cheaper than comparing whole games.

    python3 bot_fork.py OUT.jsonl PLAYERS SEED0 GAMES [--stage 2:0,2] [--dice 2]
                        --arm off:endgame_alive=0,endgame_lead=1.1 --arm on:
    python3 bot_fork.py --report OUT.jsonl

A game is played from seed SEED0 with every seat the same bot (hard). When the
number of players alive first drops to a stage (--stage "ALIVE:i,j;ALIVE:i" --
the seat's i-th own turn in that stage; default "3:0;2:0,2"), the game is
forked at the start of that seat's reinforcement phase: for every arm and
every dice seed (--dice N of them) a child process continues the game from
exactly that board, with the same dice for all arms, and that one seat (the
focal seat) plays the arm's tunables (--arm NAME:KEY=VALUE,KEY=VALUE; an empty
list is the bot as it is). The children play to the end of the game (or
--maxturns) and write one JSON line each; the parent plays on and forks again.
The report compares the arms child by child (same board, same dice): rounds
until the game ends, how often the focal seat wins, and its stock at the end.

Because the arms only differ in what the focal seat decides from that moment
on, a behaviour that matters in a few turns (a strike, the endgame spend-down)
shows up with a few hundred forks, where a whole-game A/B needs thousands of
games. Games are reproducible, so results can be repeated exactly.
"""

import os
import sys

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")  # forking after pygame has started
    os.execv(sys.executable, [sys.executable] + sys.argv)
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

import argparse
import collections
import json
import math
import random
import signal
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402

import bot  # noqa: E402
import bot_selfplay as selfplay  # noqa: E402
import phases  # noqa: E402
from engine import Engine  # noqa: E402
from models import CardMenu  # noqa: E402

DEFAULT_STAGES = "3:0;2:0,2"


class Fork:
    """What the forking needs to know, in one place (module-level state)."""
    mode = "parent"          # "child" inside a forked child
    out = None
    players = 4
    stages = {}
    arms = []                # [(name, level name)]
    dice = (101, 102)
    maxturns = 400
    timeout = 300
    min_share = 0.0          # fork only a seat holding at least this share of all strength
    game_seed = 0
    forks = 0
    seen = set()
    stage_turns = {}
    seat = 0
    fork_turn = 0
    record = None
    count = {}
    app = None


def strength(app, player):
    return sum(3 + c.units for c in app.countries.values() if c.owner is player and c.units > 0)


def snapshot(app, seat):
    player = app.players[seat]
    total = sum(strength(app, q) for q in app.players if not q.eliminated) or 1
    owned = [c for c in app.countries.values() if c.owner is player and c.units > 0]
    return dict(countries=len(owned), troops=sum(c.units for c in owned), share=round(strength(app, player) / total, 4),
                wood=player.wood, steel=player.steel, oil=player.oil, nuclear=player.nuclear, food=player.food,
                cards=len(player.cards), tanks=sum(c.tanks for c in owned),
                alive=int(not player.eliminated and bool(owned)))


def install_counters():
    """Count what the focal seat buys and trades in a child."""
    def wrap(cls, name, key):
        original = getattr(cls, name)

        def wrapper(self, *args, **kwargs):
            if Fork.mode == "child" and Fork.app.turn == Fork.seat:
                Fork.count[key] = Fork.count.get(key, 0) + 1
            return original(self, *args, **kwargs)
        wrapper.__name__ = name
        setattr(cls, name, wrapper)
    wrap(phases.ShopPhase, "place_unit", "units bought")
    wrap(phases.ShopPhase, "place_fort", "forts")
    wrap(phases.ShopPhase, "drop_nuke", "nukes")
    wrap(CardMenu, "_execute_trade", "trades")


class ForkBot(bot.BotController):
    """The bot, forking the game at the moment a stage asks for it."""

    def _reinforce(self):
        player, manager = self.player, self.manager
        if Fork.mode == "parent" and player.subattack in (1, 2):
            tick = (manager.turn_num, player.name)
            if tick not in Fork.seen:
                Fork.seen.add(tick)
                alive = sum(1 for p in self.engine.players if not p.eliminated)
                seat = self.engine.turn
                if alive in Fork.stages and alive < Fork.players:
                    index = Fork.stage_turns.get((alive, seat), 0)
                    Fork.stage_turns[(alive, seat)] = index + 1
                    if index in Fork.stages[alive] and snapshot(self.engine, seat)["share"] >= Fork.min_share \
                            and self._fork(alive, index):
                        return  # in a child: the arm's level is set, the next frame plays it
        super()._reinforce()

    def _fork(self, alive, index):
        engine, manager = self.engine, self.manager
        seat = engine.turn
        before = snapshot(engine, seat)
        sys.stdout.flush()
        Fork.forks += 1
        fork_id = Fork.forks
        for dice in Fork.dice:
            for name, level in Fork.arms:
                pid = os.fork()
                if pid:
                    os.waitpid(pid, 0)
                    continue
                try:
                    signal.signal(signal.SIGALRM, lambda *args: _give_up(fork_id, dice, name))
                    signal.alarm(Fork.timeout)
                    Fork.mode, Fork.seat, Fork.fork_turn, Fork.count = "child", seat, manager.turn_num, {}
                    Fork.record = dict(seed=Fork.game_seed, fork=fork_id, dice=dice, arm=name, alive0=alive, index=index,
                                       seat=seat, players=Fork.players, turn0=manager.turn_num, before=before)
                    np.random.seed(dice)
                    random.seed(dice)
                    engine.players[seat].bot_level = level
                    self._cache = {}
                    return True
                except BaseException:
                    import traceback
                    with open(Fork.out + ".err", "a") as f:
                        f.write(traceback.format_exc() + "\n")
                    os._exit(1)
        return False


def _give_up(fork_id, dice, name):
    with open(Fork.out, "a") as f:
        f.write(json.dumps(dict(seed=Fork.game_seed, fork=fork_id, dice=dice, arm=name, timeout=1)) + "\n")
    os._exit(2)


def child_done(app, manager, force=False):
    """In a child: write the record once the game is over (or cut off)."""
    if not (manager.game_over or force):
        return
    alive = [i for i, p in enumerate(app.players) if not p.eliminated]
    record = dict(Fork.record)
    record.update(winner=alive[0] if manager.game_over and len(alive) == 1 else None, end_turn=manager.turn_num,
                  rounds=round((manager.turn_num - Fork.fork_turn) / Fork.players, 2),
                  final=snapshot(app, Fork.seat), count=dict(Fork.count))
    with open(Fork.out, "a") as f:
        f.write(json.dumps(record, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
    os._exit(0)


def play(players, seed):
    """One game, all seats the bot at its level; children are forked on the way."""
    np.random.seed(seed)
    random.seed(seed)
    Fork.game_seed, Fork.mode, Fork.stage_turns, Fork.seen, Fork.forks = seed, "parent", {}, set(), 0
    app = Engine(mode="count", player_count=players, player_names=["Bot {}".format(i + 1) for i in range(players)],
                 player_bots=[True] * players)
    Fork.app = app
    app.save_path = os.path.join(selfplay.tempfile.gettempdir(), "oil_bot_fork_{}.json".format(os.getpid()))
    manager = app.turn_manager
    manager.bot.fast = True
    controllers = {}
    for player in app.players:
        player.bot_level, player.bot_personality = "hard", "balanced"
        controllers[player] = ForkBot(manager)
        controllers[player].fast = True
    manager.bot = selfplay.MixedBots(manager, controllers)
    while not manager.game_over and manager.turn_num < Fork.maxturns:
        app.io_handle()
        app.update_turn()
        if Fork.mode == "child":
            child_done(app, manager)
    if Fork.mode == "child":
        child_done(app, manager, force=True)
    return app, manager


def parse_stages(spec):
    stages = {}
    for part in spec.split(";"):
        alive, indices = part.split(":")
        stages[int(alive)] = {int(i) for i in indices.split(",")}
    return stages


def register_arm(spec):
    """"NAME:KEY=VALUE,KEY=VALUE" -> (name, level name); the level is hard with those tunables."""
    name, _, items = spec.partition(":")
    level = "fork_" + name
    selfplay._tweaked(bot, "hard", [item for item in items.split(",") if item], level)
    return name, level


def report(path):
    records = [json.loads(line) for line in open(path) if line.strip()]
    children = [r for r in records if "arm" in r and "rounds" in r]
    timeouts = [r for r in records if r.get("timeout")]
    arms = sorted({r["arm"] for r in children}, key=lambda a: [r["arm"] for r in children].index(a))
    print("{} children, {} timed out, arms: {}".format(len(children), len(timeouts), ", ".join(arms)))
    if not arms:
        return
    groups = collections.defaultdict(dict)
    for r in children:
        groups[(r["seed"], r["fork"], r["dice"])][r["arm"]] = r
    groups = {k: v for k, v in groups.items() if len(v) == len(arms)}
    print("{} forks with every arm; focal seat's share of strength at the fork: {:.2f}".format(
        len(groups), sum(v[arms[0]]["before"]["share"] for v in groups.values()) / max(len(groups), 1)))

    def mean_se(values):
        values = list(values)
        n = len(values)
        mean = sum(values) / n if n else float("nan")
        sd = (sum((x - mean) ** 2 for x in values) / (n - 1)) ** 0.5 if n > 1 else float("nan")
        return mean, sd / math.sqrt(n) if n > 1 else float("nan")

    print("\n{:10s} {:>14s} {:>14s} {:>14s} {:>12s}".format("arm", "rounds to end", "focal wins", "focal alive", "end share"))
    for arm in arms:
        rounds = [v[arm]["rounds"] for v in groups.values()]
        wins = [1.0 if v[arm]["winner"] == v[arm]["seat"] else 0.0 for v in groups.values()]
        alive = [v[arm]["final"]["alive"] for v in groups.values()]
        share = [v[arm]["final"]["share"] for v in groups.values()]
        print("{:10s} {:8.2f} +-{:4.2f} {:8.3f} +-{:4.3f} {:8.3f} +-{:4.3f} {:12.3f}".format(
            arm, *mean_se(rounds), *mean_se(wins), *mean_se(alive), mean_se(share)[0]))
    base = arms[0]
    for arm in arms[1:]:
        print("\n{} minus {} (paired, 95% margins):".format(arm, base))
        for label, get in (("rounds to end", lambda r: r["rounds"]),
                           ("focal wins", lambda r: 1.0 if r["winner"] == r["seat"] else 0.0),
                           ("focal alive", lambda r: r["final"]["alive"]),
                           ("end share", lambda r: r["final"]["share"])):
            mean, se = mean_se(get(v[arm]) - get(v[base]) for v in groups.values())
            print("  {:14s} {:+.3f} +- {:.3f}".format(label, mean, 1.96 * se))
        counts = collections.Counter()
        for v in groups.values():
            for key, n in v[arm]["count"].items():
                counts[key] += n
            for key, n in v[base]["count"].items():
                counts[key] -= n
        print("  per fork, what the focal seat did more: " + ", ".join(
            "{} {:+.2f}".format(key, n / max(len(groups), 1)) for key, n in sorted(counts.items())))


def main():
    parser = argparse.ArgumentParser(description="Forked what-ifs of bot behaviour.")
    parser.add_argument("out", nargs="?", help="where the results go (JSON lines)")
    parser.add_argument("players", nargs="?", type=int, default=4)
    parser.add_argument("seed", nargs="?", type=int, default=1, help="seed of the first game")
    parser.add_argument("games", nargs="?", type=int, default=1)
    parser.add_argument("--stage", default=DEFAULT_STAGES, help='where to fork: "ALIVE:i,j;ALIVE:i" (own turns in that stage)')
    parser.add_argument("--dice", type=int, default=2, help="dice seeds per fork")
    parser.add_argument("--arm", action="append", default=[], metavar="NAME:KEY=VALUE,...",
                        help="an arm (repeat; the first is the one the others are compared with)")
    parser.add_argument("--min-share", type=float, default=0.0, help="fork only a seat with at least this share of all strength")
    parser.add_argument("--maxturns", type=int, default=400)
    parser.add_argument("--timeout", type=int, default=300, help="seconds a child may take")
    parser.add_argument("--report", metavar="FILE", help="print the comparison of the arms in FILE and stop")
    args = parser.parse_args()
    if args.report:
        report(args.report)
        return
    if not args.out or len(args.arm) < 2:
        parser.error("OUT and at least two --arm are needed")
    selfplay.patch_headless()
    install_counters()
    Fork.out, Fork.players, Fork.stages = args.out, args.players, parse_stages(args.stage)
    Fork.arms = [register_arm(spec) for spec in args.arm]
    Fork.dice = tuple(range(101, 101 + args.dice))
    Fork.maxturns, Fork.timeout, Fork.min_share = args.maxturns, args.timeout, args.min_share
    for seed in range(args.seed, args.seed + args.games):
        started = time.time()
        app, manager = play(args.players, seed)
        print("game {} players seed {}: {} forks of {} children each, {} turns ({:.0f} s)".format(
            args.players, seed, Fork.forks, len(Fork.arms) * args.dice, manager.turn_num, time.time() - started), flush=True)


if __name__ == "__main__":
    main()
