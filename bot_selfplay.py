"""
Bots playing whole games against each other, headless and as fast as
possible -- for testing and tuning bot.py.

    python3 bot_selfplay.py [games] [players]

Prints each game's winner, number of turns and time taken. Autosaves go
to a temporary file, not saves/autosave.json.
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from engine import Engine  # noqa: E402

MAX_TURNS = 600


def play_game(player_count):
    app = Engine(mode="count", player_count=player_count,
                 player_names=["Bot {}".format(i + 1) for i in range(player_count)],
                 player_bots=[True] * player_count)
    app.save_path = os.path.join(tempfile.gettempdir(), "oil_bot_selfplay.json")
    manager = app.turn_manager
    manager.bot.fast = True
    while not manager.game_over and manager.turn_num < MAX_TURNS:
        app.io_handle()
        app.update_turn()
    alive = [p for p in app.players if not p.eliminated]
    return (alive[0].name if manager.game_over and alive else None), manager.turn_num


def main():
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    players = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    for i in range(games):
        start = time.time()
        winner, turns = play_game(players)
        print("game {}: {} after {} turns ({:.1f} s)".format(
            i + 1, winner or "no winner", turns, time.time() - start))


if __name__ == "__main__":
    main()
