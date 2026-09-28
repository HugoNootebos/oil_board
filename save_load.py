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

    save_game(engine, engine.turn_manager, slot_path(0), name="My game")
    ...
    load_game(slot_path(0), engine, engine.turn_manager)

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
import os

import numpy as np

from models import Player, Kaertske, Connection

SAVE_VERSION = 1

# Save files: one autosave (written at the start of every turn) plus four
# manual slots the player names themselves via Settings > Save As.
SAVE_DIR = "saves"
AUTOSAVE_PATH = os.path.join(SAVE_DIR, "autosave.json")
SAVE_SLOT_COUNT = 4
LEGACY_SAVE_PATH = "savegame.json"  # the single save file used before slots


def slot_path(index):
    """Path of manual save slot `index` (0-based)."""
    return os.path.join(SAVE_DIR, "slot{}.json".format(index + 1))


def migrate_legacy_save():
    """An old single savegame.json becomes the autosave, so switching to
    save slots doesn't lose it."""
    if os.path.isfile(LEGACY_SAVE_PATH) and not os.path.isfile(AUTOSAVE_PATH):
        os.makedirs(SAVE_DIR, exist_ok=True)
        os.replace(LEGACY_SAVE_PATH, AUTOSAVE_PATH)


def read_save_name(path):
    """The name a save was given, or None if there's no (readable) save
    at `path`. Saves from before names existed are just "Saved game"."""
    try:
        with open(path) as f:
            return json.load(f).get("save_name") or "Saved game"
    except (OSError, ValueError):
        return None

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
        "boat_to_deploy": player.start_ship,
        "repositioned_this_turn": player.repositioned_this_turn,
        "developed_this_turn": player.developed_this_turn,
        "eliminated": player.eliminated,
        "is_bot": player.is_bot,
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
        "airport": country.airport,
        "dormant_owner": None if country.dormant_owner is None else country.dormant_owner.name,
        "bombed_by": None if country.bombed_by is None else country.bombed_by.name,
        "landmark_owner": None if country.landmark_owner is None else country.landmark_owner.name,
        "voc_weakened": country.voc_weakened,
    }


def save_game(engine, manager, path=AUTOSAVE_PATH, event_schedule_pending=False, name=None):
    """Write the current game state to `path` as JSON, under `name` (what
    the load screen shows; the autosave is simply "Autosave").

    event_schedule_pending marks a save taken as a turn starts, before
    TurnManager._update_event_schedule has run for it (the autosave):
    loading it runs that step, so the turn's event is drawn then."""
    data = {
        "version": SAVE_VERSION,
        "save_name": name or "Autosave",
        "default_game": engine.default_game,
        "settings": dict(engine.settings),
        "turn": {
            "current_player_index": engine.turn,
            "turn_num": manager.turn_num,
        },
        "manager": {
            "reinforcements": manager.reinforcements,
            "all_reinforcements_deployed": manager.all_reinforcements_deployed,
            "attacked": list(manager.attacked),
            "defending_tanks": dict(manager.defending_tanks),
            "landmarks_punished": sorted(manager.landmarks_punished),
            "conquered_enemy_this_turn": manager.conquered_enemy_this_turn,
            "pending_event_cards": manager.pending_event_cards,
            "initial_units": dict(manager.initial_units),
            "saved_attack": manager.saved_attack,
            "saved_subattack": manager.saved_subattack,
            # World events, saved by name (events and players alike) so
            # they survive round-trips even if EVENTS has changed since
            # the save was written (see load).
            "event_turn_index": manager.event_turn_index,
            "event_bag": [e.name for e in manager.event_bag],
            "event_history": [e.name for e in manager.event_history],
            "current_event": manager.current_event.name if manager.current_event else None,
            "event_state": manager.current_event.save_state(engine) if manager.current_event else {},
            "event_pending_players": [p.name for p in manager.event_pending_players],
            "reveal_pool": [p.name for p in manager.reveal_pool],
            "awaiting_gap": manager.awaiting_gap,
            "event_schedule_pending": event_schedule_pending,
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
                "temporary": getattr(c, "temporary", False),
            }
            for c in engine.connections
        ],
    }
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, cls=_NumpyEncoder)


# Old country name -> current one, for saves made before a rename.
RENAMED_COUNTRIES = {"Californië": "Los Angeles"}


def load_game(path, engine, manager):
    """Read `path` and apply it onto an already-constructed `engine` and
    its `manager` (TurnManager), in place."""
    with open(path) as f:
        text = f.read()
    # Countries renamed since the save was made keep their state.
    for old_name, new_name in RENAMED_COUNTRIES.items():
        text = text.replace(json.dumps(old_name)[1:-1], json.dumps(new_name)[1:-1])
        text = text.replace(old_name, new_name)
    data = json.loads(text)

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
            # Saves from before the boat button got their boat at the start.
            start_ship=pdata.get("boat_to_deploy", False),
        )
        player.attack = pdata["attack"]
        # Always resume at the safe/idle entry point of whichever phase
        # the player was in -- see the scope note at the top of this file.
        player.subattack = 0
        player.repositioned_this_turn = pdata["repositioned_this_turn"]
        player.developed_this_turn = pdata.get("developed_this_turn", False)
        player.eliminated = pdata.get("eliminated", False)
        player.is_bot = pdata.get("is_bot", False)
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
        country.airport = cdata.get("airport", False)
        dormant = cdata.get("dormant_owner")
        country.dormant_owner = players_by_name.get(dormant) if dormant else None
        bomber = cdata.get("bombed_by")
        country.bombed_by = players_by_name.get(bomber) if bomber else None
        placer = cdata.get("landmark_owner")
        country.landmark_owner = players_by_name.get(placer) if placer else None
        country.voc_weakened = cdata.get("voc_weakened", False)

    # --- connections ------------------------------------------------------
    for cdata in data["connections"]:
        wanted = set(cdata["between"])
        for c in engine.connections:
            if set(c.connection) == wanted:
                c.kind = cdata["kind"]
                c.rails = cdata["rails"]
                break
        else:
            if cdata.get("temporary"):
                # A route an active event added (see JapanGoesCrazy); the
                # event's on_end removes it again by this flag.
                route = Connection(wanted, cdata["kind"], rails=cdata["rails"])
                route.temporary = True
                engine.connections.add(route)

    # --- turn / manager state ------------------------------------------
    engine.turn = data["turn"]["current_player_index"]
    engine.default_game = data.get("default_game", engine.default_game)
    # Settings toggles; keys missing from older saves keep their defaults.
    for key, value in data.get("settings", {}).items():
        if key in engine.settings:
            engine.settings[key] = bool(value)
    manager.turn_num = data["turn"]["turn_num"]
    mdata = data["manager"]
    manager.reinforcements = mdata["reinforcements"]
    manager.all_reinforcements_deployed = mdata["all_reinforcements_deployed"]
    manager.attacked = list(mdata["attacked"])
    manager.defending_tanks = dict(mdata.get("defending_tanks", {}))
    manager.landmarks_punished = set(mdata.get("landmarks_punished", []))
    manager.conquered_enemy_this_turn = mdata["conquered_enemy_this_turn"]
    manager.pending_event_cards = mdata.get("pending_event_cards", 0)
    manager.initial_units = dict(mdata["initial_units"])
    manager.saved_attack = mdata["saved_attack"]
    manager.saved_subattack = mdata["saved_subattack"]

    # World events: resolve saved names back to Event objects. If any name
    # isn't found (EVENTS changed since the save was written), the whole
    # drawn-so-far history is discarded rather than partially kept, since
    # dropping just the unknown entries would desync it from
    # event_turn_index; it's simply redrawn fresh from here on, same as a
    # freshly-started game reaching that point.
    from events import EVENTS
    by_name = {e.name: e for e in EVENTS}
    manager.event_turn_index = mdata.get("event_turn_index", 0)
    try:
        manager.event_bag = [by_name[n] for n in mdata.get("event_bag", [])]
        manager.event_history = [by_name[n] for n in mdata.get("event_history", [])]
        current_name = mdata.get("current_event")
        manager.current_event = by_name[current_name] if current_name else None
        if manager.current_event is not None:
            manager.current_event.load_state(engine, mdata.get("event_state", {}))
    except KeyError:
        manager.event_bag = []
        manager.event_history = []
        manager.current_event = None
    # Players referenced by the event schedule, resolved the same way --
    # a name no longer in the roster (shouldn't normally happen) is just
    # dropped rather than failing the whole load.
    manager.event_pending_players = {
        players_by_name[n] for n in mdata.get("event_pending_players", []) if n in players_by_name
    }
    manager.reveal_pool = {
        players_by_name[n] for n in mdata.get("reveal_pool", []) if n in players_by_name
    }
    manager.awaiting_gap = mdata.get("awaiting_gap", False)

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

    # An autosave was taken before this turn's event step ran; run it now.
    manager.event_notice = None
    if mdata.get("event_schedule_pending", False):
        manager._update_event_schedule()
