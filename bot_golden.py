"""
Golden traces: proof that a change to bot.py (or the game) that should not
change how the bots play really doesn't.

    python3 bot_golden.py                  compare with golden_traces.json
    python3 bot_golden.py --update         (re)write golden_traces.json
    python3 bot_golden.py --bot old_bot.py --update
                                           take the traces from another bot file
    python3 bot_golden.py --tweak strike=0 --tweak chain_weight=0
                                           compare with a tunable switched off

It plays 12 whole games (3, 4, 5 and 6 players, 3 seeds each; hard, balanced,
every seat the same bot) and boils every game down to an md5 of the board and
every player's stock at the end of each turn. Games are reproducible (see
bot_selfplay.py), so the traces are too: if one differs, the bot (or the
rules) played differently, from the first turn that did not match.

The usual use: golden_traces.json holds the traces of old_bot.py, the bot as
it was before the retraining. A new tunable that is switched off (0, the
old behaviour) must reproduce them exactly; a speed-up of bot.py must too.
A change that is meant to change play will of course differ -- then compare
bots with bot_selfplay.py instead.
"""

import os
import sys

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import argparse
import hashlib
import json
import multiprocessing

import numpy as np

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import bot  # noqa: E402
import bot_selfplay as selfplay  # noqa: E402
import phases  # noqa: E402

GOLDEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_traces.json")
GAMES = [(players, seed) for players in (3, 4, 5, 6) for seed in (1, 2, 3)]
LEVEL = "hard"

_worker = {}
_trace = []


def _plain(row):
    """numpy scalars as Python ones: numpy 2 writes np.int64(5) where numpy 1
    wrote 5, which would change every md5 without any play changing."""
    return tuple(value.item() if isinstance(value, np.generic) else value for value in row)


def _record(manager):
    engine = manager.engine
    _trace.append((
        manager.turn_num, engine.turn,
        tuple(_plain((p.name, p.food, p.wood, p.steel, p.oil, p.nuclear, len(p.cards), p.eliminated))
              for p in engine.players),
        tuple(_plain((name, c.owner.name, c.units, c.ships, c.tanks, c.planes, c.fort_lvl, c.developed, c.radioactive))
              for name, c in engine.countries.items()),
    ))


def _init(bot_file, tweaks):
    selfplay.patch_headless()
    module = selfplay.load_bot_module(bot_file) if bot_file else bot
    level = LEVEL
    if tweaks:
        selfplay._tweaked(module, LEVEL, tweaks, "golden")
        level = "golden"
    _worker.update(module=module, level=level)
    original = phases.TurnManager.end_phase

    def end_phase(self):
        _record(self)
        return original(self)
    phases.TurnManager.end_phase = end_phase


def _play(job):
    players, seed = job
    del _trace[:]
    sides = ["A"] * players
    result = selfplay.play_game(players, seed, sides, {"A": _worker["level"]}, {"A": _worker["module"]})
    digest = hashlib.md5(repr(_trace).encode()).hexdigest()
    return "{}p-seed{}".format(players, seed), dict(md5=digest, turns=result["turns"], winner=result["winner"],
                                                  records=len(_trace))


def main():
    parser = argparse.ArgumentParser(description="Compare bot play with the golden traces.")
    parser.add_argument("--bot", metavar="FILE", help="a bot file to play instead of bot.py")
    parser.add_argument("--tweak", metavar="KEY=VALUE", action="append", default=[],
                        help="change a tunable of the hard level (repeatable)")
    parser.add_argument("--update", action="store_true", help="write the traces instead of comparing")
    parser.add_argument("--golden", default=GOLDEN_FILE, help="the file with the golden traces")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    with multiprocessing.Pool(args.jobs, initializer=_init, initargs=(args.bot, args.tweak)) as pool:
        traces = dict(pool.map(_play, GAMES))
    if args.update:
        with open(args.golden, "w") as f:
            json.dump(dict(source=args.bot or "bot.py", tweaks=args.tweak, traces=traces), f, indent=1, sort_keys=True)
        print("wrote {} traces to {}".format(len(traces), args.golden))
        return
    with open(args.golden) as f:
        golden = json.load(f)
    differing = [key for key in sorted(golden["traces"]) if traces.get(key, {}).get("md5") != golden["traces"][key]["md5"]]
    for key in sorted(golden["traces"]):
        mark = "DIFFERS" if key in differing else "same   "
        now, then = traces[key], golden["traces"][key]
        print("{}  {:12s} now: {} turns, winner {}   golden: {} turns, winner {}".format(
            mark, key, now["turns"], now["winner"], then["turns"], then["winner"]))
    print("\n{} of {} games identical to the golden traces ({}).".format(
        len(golden["traces"]) - len(differing), len(golden["traces"]), golden["source"]))
    sys.exit(1 if differing else 0)


if __name__ == "__main__":
    main()
