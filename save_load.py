"""
JSON save/load for the game.

The Engine itself (pygame surfaces, fonts, loaded sprite images, country
polygons...) isn't serializable, and doesn't need to be: board.py rebuilds
the map deterministically every time the game starts up. A save file only
needs to capture the *mutable* state layered on top of that fixed map --
who owns what, everyone's troops/assets/resources, whose turn it is, and
the handful of counters phases use to enforce their own rules (one
reposition per turn, one card per turn, etc).

Usage
-----
    from save_load import save_game, load_game

    save_game(engine, engine.turn_manager, "savegame.json")
    ...
    load_game("savegame.json", engine, engine.turn_manager)

`load_game` expects `engine` to already exist -- constructed the normal
way, so board.py has already built engine.countries / engine.connections
and engine.images is populated. It replaces engine.players outright and
overwrites every mutable field on the existing countries/connections in
place, rather than trying to reconstruct the whole Engine from scratch.

Scope note: a save only captures state at the *start of a phase*
(subattack always reloads as 0). Mid-action state that only makes sense
while it's actively being decided -- an attack's dice-in-progress, which
assets are queued in the asset-transport panel, a movement's partially
dragged troop split -- is not preserved; the safe/idle entry point of
whichever phase the player was in is used instead. In-progress rail
redistribution pools are likewise not preserved and are simply cleared.
"""

import json

import numpy as np

from models import Player, Kaertske

SAVE_VERSION = 1

# Sentinel used in place of a player name for countries/connections that
# belong to nobody (engine.default_player), since "the neutral player" has
# no stable, save-proof identity of its own to look up by name.
DEFAULT_PLAYER_KEY = "__default_player__"


class _NumpyEncoder(json.JSONEncoder):
    """A handful of fields (e.g. anything ever touched by a numpy random
    draw or array op) end up holding numpy scalar/array types rather than
    plain Python ones, which json.dump doesn't know how to serialize on
    its own. Converting them here means every field gets covered, not
    just the ones we remembered to cast by hand."""

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _color_to_list(color):
    """Plain, JSON-safe list of floats, whether `color` started out as a
    tuple, a list, or a numpy array (Player.color defaults to the latter
    when no explicit color is given)."""
    return [round(float(c), 2) for c in color]


def _player_to_dict(player):
    return {
        "name": player.name,
        "color": _color_to_list(player.color),
        "food": player.food,
        "wood": player.wood,
        "steel": player.steel,
        "nuclear": player.nuclear,
        "oil": player.oil,
        "troops": player.troops,
        "attack": player.attack,
        "start_ship": player.start_ship,
        "repositioned_this_turn": player.repositioned_this_turn,
        # Cards only need their type (0-3); Kaertske re-derives everything
        # else (name, sprite, layout position) from that plus engine.images.
        "cards": [card.type for card in player.cards],
    }


def _country_to_dict(country, default_player):
    return {
        "owner": DEFAULT_PLAYER_KEY if country.owner is default_player else country.owner.name,
        "food": country.food,
        "wood": country.wood,
        "steel": country.steel,
        "nuclear": country.nuclear,
        "oil": country.oil,
        "troops": country.troops,
        "units": country.units,
        "ships": country.ships,
        "planes": country.planes,
        "tanks": country.tanks,
        "fort_lvl": country.fort_lvl,
        "radioactive": country.radioactive,
        "developed": country.developed,
    }


def save_game(engine, manager, path="savegame.json"):
    """Write the current game state to `path` as JSON."""
    data = {
        "version": SAVE_VERSION,
        "default_game": engine.default_game,
        "turn": {
            "current_player_index": engine.turn,
            "turn_num": manager.turn_num,
        },
        "manager": {
            "reinforcements": manager.reinforcements,
            "all_reinforcements_deployed": manager.all_reinforcements_deployed,
            "attacked": list(manager.attacked),
            "conquered_enemy_this_turn": manager.conquered_enemy_this_turn,
            "initial_units": dict(manager.initial_units),
            "saved_attack": manager.saved_attack,
            "saved_subattack": manager.saved_subattack,
        },
        "players": [_player_to_dict(p) for p in engine.players],
        "countries": {
            name: _country_to_dict(country, engine.default_player)
            for name, country in engine.countries.items()
        },
        "connections": [
            {
                "between": sorted(c.connection),
                "kind": c.kind,
                "rails": c.rails,
            }
            for c in engine.connections
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, cls=_NumpyEncoder)


def load_game(path, engine, manager):
    """Read `path` and apply it onto an already-constructed `engine` and
    its `manager` (TurnManager), in place."""
    with open(path) as f:
        data = json.load(f)

    # --- players ------------------------------------------------------
    new_players = []
    for pdata in data["players"]:
        player = Player(
            pdata["name"],
            food=pdata["food"],
            wood=pdata["wood"],
            steel=pdata["steel"],
            nuclear=pdata["nuclear"],
            oil=pdata["oil"],
            color=pdata["color"],
            troops=pdata["troops"],
            start_ship=pdata["start_ship"],
        )
        player.attack = pdata["attack"]
        # Always resume at the safe/idle entry point of whichever phase
        # the player was in -- see the scope note at the top of this file.
        player.subattack = 0
        player.repositioned_this_turn = pdata["repositioned_this_turn"]
        player.cards = [Kaertske(card_type, images=engine.images) for card_type in pdata["cards"]]
        new_players.append(player)
    engine.players = new_players
    players_by_name = {p.name: p for p in new_players}

    def resolve_owner(name):
        return engine.default_player if name == DEFAULT_PLAYER_KEY else players_by_name[name]

    # --- countries ------------------------------------------------------
    for name, cdata in data["countries"].items():
        country = engine.countries[name]
        country.owner = resolve_owner(cdata["owner"])
        country.food = cdata["food"]
        country.wood = cdata["wood"]
        country.steel = cdata["steel"]
        country.nuclear = cdata["nuclear"]
        country.oil = cdata["oil"]
        country.troops = cdata["troops"]
        country.units = cdata["units"]
        country.ships = cdata["ships"]
        country.planes = cdata["planes"]
        country.tanks = cdata["tanks"]
        country.fort_lvl = cdata["fort_lvl"]
        country.radioactive = cdata["radioactive"]
        country.developed = cdata["developed"]

    # --- connections ------------------------------------------------------
    for cdata in data["connections"]:
        wanted = set(cdata["between"])
        for c in engine.connections:
            if set(c.connection) == wanted:
                c.kind = cdata["kind"]
                c.rails = cdata["rails"]
                break

    # --- turn / manager state ------------------------------------------
    engine.turn = data["turn"]["current_player_index"]
    engine.default_game = data.get("default_game", engine.default_game)
    manager.turn_num = data["turn"]["turn_num"]
    mdata = data["manager"]
    manager.reinforcements = mdata["reinforcements"]
    manager.all_reinforcements_deployed = mdata["all_reinforcements_deployed"]
    manager.attacked = list(mdata["attacked"])
    manager.conquered_enemy_this_turn = mdata["conquered_enemy_this_turn"]
    manager.initial_units = dict(mdata["initial_units"])
    manager.saved_attack = mdata["saved_attack"]
    manager.saved_subattack = mdata["saved_subattack"]

    # Loading mid-selection could otherwise leave a phase highlighting (and
    # referencing) countries the now-active player never actually picked.
    manager.phases[1].reset()
    manager.phases[2].reset()

    # Re-point the card menu at whoever is now active and refresh its
    # layout/auto-use flags for their (freshly reconstructed) hand.
    active_player = engine.players[engine.turn]
    engine.card_menu.player = active_player
    engine.card_menu.organize_cards()
    engine.card_menu.use_cards_automatic()
