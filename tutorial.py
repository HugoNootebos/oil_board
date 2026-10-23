"""
The tutorial (main menu > Tutorial): a scripted local game in nine parts.
The player (blue) starts with 12 troops in Venezuela; green holds Cuba and
New York, red Viking (with a fort) and Sovjet-Rusland. Over three turns the
panel walks the player through deploying, attacking and moving in, moving
troops, the natives, ships, rails, the train, eliminating green, planes and
tanks, a card trade, the airlift, nukes and a bridge, until red is out too
and the player has won.

A step either is a page to read (a Next button; the game takes no clicks
meanwhile) or waits for the player to do something on the board (it goes
on by itself once its `done` holds). What a step is about is ringed on the
screen (`Tutorial._shapes`). A step holds back the clicks that would leave
the script (`Step.hold`, e.g. a click on another country, or Confirm before
the right number of troops is set), and the phase buttons and End turn
unless it asks for them. So that the story always goes the same way, the
player's attacks always win (`_rig_dice`), and green and red are played by
the tutorial itself (`_npc_update` stands in for the bot's update).

World events are held back while the tutorial runs. End tutorial goes
back to the title screen. Its autosaves go to a temporary file, so the
player's own autosave stays as it was.

runner.play calls `handle_input` right after `Engine.io_handle` and `draw`
right before `Engine.present`.
"""

import math
import os
import random
import tempfile

import pygame as pg

import sounds
from board import get_countries
from fonts import game_font
from lang import t, Msg
from models import Kaertske, Position, WORLD_WIDTH
from phases import Phase, TurnManager, image_button_shape, PICTURE_BUTTON_SIZE

SAVE_PATH = os.path.join(tempfile.gettempdir(), "oil_tutorial.json")

BLUE, GREEN, RED = 0, 1, 2
VEN, MEX, BRA, PER = "Venezuela", "Mexico", "Brazilië", "Peru"
CUBA, NY, LON = "Cuba", "New York", "Londen"
VIK, SOV = "Viking", "Sovjet-Rusland"

# The board: each player's countries (troops), forts and airports.
START = {BLUE: {VEN: 12}, GREEN: {CUBA: 1, NY: 2}, RED: {VIK: 6, SOV: 1}}
FORTS = {VIK: 1}
AIRPORTS = (VEN,)
# Stocks. Green's is what the player loots from it (its wood: 10 once Cuba's
# harvest is in), and three cards of a set.
STOCKS = {
    BLUE: {"food": 45, "wood": 0, "steel": 0, "oil": 1, "nuclear": 0},
    GREEN: {"food": 45, "wood": 9, "steel": 40, "oil": 4, "nuclear": 0},
    RED: {"food": 45, "wood": 0, "steel": 0, "oil": 0, "nuclear": 0},
}
GREEN_CARDS = (0, 1, 2)
# What green and red do on their turns, one list per turn (_npc_turn).
NPC_MS = 900  # between their moves

# Where the view goes when a step starts (Step.focus): a map point and zoom,
# put at FOCUS_SPOT on screen (or at its own spot).
FOCUS_SPOT = (450, 400)
FOCUS = {
    "all": (240, 215, 1.3, (313, 380)),  # (left of the panel)
    "south": (150, 275, 2.3),
    "north": (215, 185, 1.9),
    "route": (185, 225, 1.6),
    "atlantic": (205, 215, 1.6, (313, 400)),  # (left of the panel)
    "europe": (300, 140, 2.0),
}

PANEL_COLOR = (255, 248, 225)
MARK_COLOR = (255, 205, 0)
WIDTH = 268          # the panel (logical px)
PAD = 14
GAP = 8              # between the panel and the country info panel (top right) it sits left of
SHOP_SPOT = (676, 88)  # while the shop is open: in the shop's empty top right


def new_game():
    """The tutorial's game: an Engine with the tutorial's board and its
    Tutorial (Engine.tutorial)."""
    from engine import Engine
    app = Engine(mode="count", player_count=3, player_names=[t("Player {}").format(1), "Bot 2", "Bot 3"],
                 player_bots=[False, True, True])
    _set_board(app)
    app.tutorial = Tutorial(app)
    return app


def _set_board(app):
    fresh = get_countries(app.default_player)
    for name, country in app.countries.items():
        country.owner = app.default_player
        country.units = fresh[name].units
        country.airport = fresh[name].airport
    for index, countries in START.items():
        player = app.players[index]
        for name, units in countries.items():
            app.countries[name].owner = player
            app.countries[name].units = units
        for resource, amount in STOCKS[index].items():
            setattr(player, resource, amount)
    for name, level in FORTS.items():
        app.countries[name].fort_lvl = level
    for name in AIRPORTS:
        app.countries[name].airport = True
    app.players[GREEN].cards = [Kaertske(kind, images=app.images) for kind in GREEN_CARDS]
    app.turn = BLUE
    app.card_menu.player = app.players[BLUE]
    # Past everyone's first turn (which gives nothing): income from the start.
    app.turn_manager.turn_num = len(app.players)
    app.save_path = SAVE_PATH
    app.settings["fast_bots"] = False  # (and kept off while it runs, see Tutorial.draw)


class Step:
    """One page of the tutorial, in part `part` (1-9): a title and a text
    (English source, through t(); "{}" in it are the country names `names`,
    translated). `done(tu)`: the step waits until it returns True (None: a
    page to read, with a Next button). `marks`: what's ringed on the screen,
    keys of Tutorial._shapes or country names, or a function of the Tutorial
    returning them. `hold(tu, point)`: True for a click the step holds back
    (see _hold). `phases`/`end_turn`: whether the phase buttons / End turn
    may be used. `focus`: a FOCUS the view goes to as the step starts.
    `npc`: a page shown during that player's turn (GREEN or RED); its Next
    only comes once their moves are done, and their turn ends with it."""

    def __init__(self, part, title, text, done=None, marks=(), names=(), hold=None,
                 phases=False, end_turn=False, focus=None, npc=None):
        self.part = part
        self.title = title
        self.text = text
        self.done = done
        self.marks = marks
        self.names = names
        self.hold = hold
        self.phases = phases
        self.end_turn = end_turn
        self.focus = focus
        self.npc = npc


# --- what the steps look at ------------------------------------------------------------

def _units(name):
    return lambda tu: tu.app.countries[name].units


def _mine(tu, name):
    return tu.app.countries[name].owner is tu.player


def _deployed(tu):
    manager = tu.app.turn_manager
    player = tu.player
    return player.attack != 0 or (manager.turn_started and manager.all_reinforcements_deployed
                                  and manager.reinforcements <= 0 and player.subattack == 1)


def _picked(target):
    """The attack on `target` has been picked (or is already won)."""
    def done(tu):
        attack = tu.app.turn_manager.phases[1]
        return _mine(tu, target) or (tu.player.attack == 1 and tu.player.subattack >= 2
                                     and attack.defence_country == target)
    return done


def _won(target):
    """`target` is conquered (moving in may still be going on)."""
    return lambda tu: _mine(tu, target)


def _moved_in(target):
    """`target` is conquered and moving in has been confirmed."""
    return lambda tu: _mine(tu, target) and not (tu.player.attack == 1 and tu.player.subattack == 5)


def _phase(n):
    return lambda tu: tu.player.attack == n


def _rails(a, b):
    def done(tu):
        return any(set(c.connection) == {a, b} and c.rails for c in tu.app.connections) \
            and tu.player.attack != 3
    return done


def _bought(attr, name):
    return lambda tu: getattr(tu.app.countries[name], attr) > 0 and tu.player.attack != 3


def _moved_by(kind):
    """A rails ("rails") or airlift ("air") move was confirmed in this step."""
    return lambda tu: tu.moves[kind] > tu.start_moves[kind]


# --- what the steps hold back ------------------------------------------------------------

# (attack, subattack) of the screens whose green button settles where troops
# end up: moving in after a conquest, a move, a rail or air transfer.
SETTLING = {(1, 5), (2, 2), (1, 7), (2, 3)}


def _hold(only=None, confirm=None, reward=None):
    """A Step.hold: clicks on countries other than `only` (except while the
    dice are being looked at); the green button of a SETTLING screen while
    `confirm(tu)` is False; in the card trade, every reward but `reward`."""
    def hold(tu, point):
        app = tu.app
        player = tu.player
        if reward is not None and app.card_menu.trade_mode:
            from models import CardMenu
            return any(app.card_menu._option_rect(i).collidepoint(point)
                       for i, option in enumerate(CardMenu.TRADE_OPTIONS) if option[1] != reward)
        on_confirm = pg.Rect(*image_button_shape(Phase.CONFIRM_X, Phase.ROW_Y)[1:]).collidepoint(point)
        settling = (player.attack, player.subattack) in SETTLING
        if confirm is not None and on_confirm and settling and not confirm(tu):
            return True
        hover = app.io.hover_country
        resolving = player.attack == 1 and player.subattack in (3, 4, 9)
        return only is not None and hover is not None and hover not in only and not resolving
    return hold


# --- what the steps ring ------------------------------------------------------------------

def _attack_marks(source, target):
    def marks(tu):
        sub = tu.player.subattack if tu.player.attack == 1 else None
        if sub == 0 or (sub == 1 and tu.app.turn_manager.phases[1].attack_from != source):
            return [source]
        if sub == 1:
            return [target]
        if sub == 2:
            return ["dice", "confirm"]
        if sub == 5:
            return [source, target, "confirm"]
        return []
    return marks


def _move_marks(source, target):
    def marks(tu):
        sub = tu.player.subattack if tu.player.attack == 2 else None
        if sub == 0:
            return [source]
        if sub == 1:
            return [target]
        if sub == 2:
            return [source, target, "confirm"]
        return []
    return marks


def _shop_marks(card, *places):
    """The shop button, then the item's card, then where it goes."""
    def marks(tu):
        player = tu.player
        if player.attack == 3 and player.subattack < 8:
            return [card] if player.subattack == 0 else ["confirm_card"]
        if player.attack == 3:
            return list(places)
        return ["shop"]
    return marks


def _transfer_marks(origin, button, countries, tank=False):
    """Pick `origin`, its rails ("train") or airport ("plane_button")
    button, then the countries (and the tank in the selector)."""
    def marks(tu):
        player = tu.player
        if player.attack == 1 and player.subattack == 7:
            return list(countries) + (["troop_pool", "tank_pool"] if tank else []) + ["confirm"]
        if player.attack == 1 and player.subattack == 1:
            return [button]
        return [origin]
    return marks


def _card_marks(tu):
    menu = tu.app.card_menu
    if menu.trade_mode:
        return ["nuclear_option"]
    return ["confirm"] if menu.show else ["cards"]


STEPS = [
    # 1 -----------------------------------------------------------------------------------
    Step(1, "Welcome to OIL",
         "You are the blue player and you are competing against red and green. The grey countries "
         "belong to the natives. You win by eliminating both other players.",
         marks=[VEN, CUBA, NY, VIK, SOV], focus="all"),
    Step(1, "Your stock",
         "The panel on the left shows your stock: food, wood, steel, oil, uranium and troop "
         "production. The number in brackets is what comes in at your next turn. Every troop eats "
         "1 food at the start of your turn.",
         marks=["player_panel"], focus="south"),
    Step(1, "Place your troops",
         "Every turn brings new troops: 3 this time (the soldier at the bottom left). Left-click {} "
         "three times to place them.",
         names=[VEN], done=_deployed, hold=_hold(only=[VEN]), marks=["soldier", VEN]),
    Step(1, "On to the attack",
         "Click the red button to go to the attack phase.",
         done=lambda tu: tu.player.attack >= 1, hold=_hold(only=[]), marks=["attack_phase"], phases=True),

    # 2 -----------------------------------------------------------------------------------
    Step(2, "Attack Mexico",
         "Click {} to attack from it, then {} to attack it.",
         names=[VEN, MEX], done=_picked(MEX), hold=_hold(only=[VEN, MEX]), marks=_attack_marks(VEN, MEX)),
    Step(2, "Roll the dice",
         "You roll a die for every attacking troop, at most 3 (one stays home); the defender rolls "
         "up to 2. The highest dice are compared in pairs: the higher one wins, a tie goes to the "
         "defender, and each loser loses a troop.\n"
         "Click the green button to roll, then click anywhere to see the result.",
         done=_won(MEX), hold=_hold(only=[VEN, MEX]), marks=_attack_marks(VEN, MEX)),
    Step(2, "Move in 3 troops",
         "{} is yours. Now you get to choose how many troops to move in. Click on {} or {} until "
         "only 3 troops move into {}, then click the green button to confirm.",
         names=[MEX, VEN, MEX, MEX], done=_moved_in(MEX),
         hold=_hold(only=[VEN, MEX], confirm=lambda tu: _units(MEX)(tu) == 3), marks=_attack_marks(VEN, MEX)),
    Step(2, "Attack Brazil",
         "Attack {} from {} the same way: click {}, then {}, roll, and click to see the result.",
         names=[BRA, VEN, VEN, BRA], done=_won(BRA), hold=_hold(only=[VEN, BRA]),
         marks=_attack_marks(VEN, BRA)),
    Step(2, "Everyone in",
         "This time move all your troops into {}, leaving {} empty: click {} until {} has none "
         "left. Then click the green button.",
         names=[BRA, VEN, BRA, VEN], done=_moved_in(BRA),
         hold=_hold(only=[VEN, BRA], confirm=lambda tu: _units(VEN)(tu) == 0), marks=_attack_marks(VEN, BRA)),
    Step(2, "The natives",
         "Nobody holds {} now, so the natives took it back. Most native countries go back to 2 "
         "troops; a few are different, you'll find out about those later.",
         names=[VEN], marks=[VEN]),
    Step(2, "Attack Peru",
         "Now attack {} from {}: click {}, then {}, roll, and click to see the result.",
         names=[PER, BRA, BRA, PER], done=_won(PER), hold=_hold(only=[BRA, PER]),
         marks=_attack_marks(BRA, PER)),
    Step(2, "Move in 5 troops",
         "Move 5 troops into {}: click {} or {} until {} has 5, then click the green button.",
         names=[PER, BRA, PER, PER], done=_moved_in(PER),
         hold=_hold(only=[BRA, PER], confirm=lambda tu: _units(PER)(tu) == 5), marks=_attack_marks(BRA, PER)),
    Step(2, "On to moving",
         "Click the orange button to go to the move phase.",
         done=_phase(2), hold=_hold(only=[]), marks=["move_phase"], phases=True),

    # 3 -----------------------------------------------------------------------------------
    Step(3, "Move 2 troops",
         "Once per turn you can move troops between two of your countries. Click {}, then {}, "
         "then click {} twice to move 2 troops there, and click the green button.",
         names=[PER, BRA, BRA], done=lambda tu: tu.player.repositioned_this_turn,
         hold=_hold(only=[PER, BRA], confirm=lambda tu: _units(PER)(tu) == 3), marks=_move_marks(PER, BRA)),
    Step(3, "Cut off",
         "{} and {} are both yours, but you can't move troops between them: moves only go through "
         "your own countries, and the way runs through {}, which the natives hold now.",
         names=[PER, MEX, VEN], marks=[PER, MEX, VEN]),
    Step(3, "End your turn",
         "Click End turn. Then the others play.",
         done=lambda tu: tu.app.turn != BLUE, hold=_hold(only=[]), marks=["end_turn"], end_turn=True),

    # 4 -----------------------------------------------------------------------------------
    Step(4, "Green's turn",
         "Green places 3 troops and a ship in {}, crosses the sea to attack {} and moves in, "
         "leaving 1 troop in {}.",
         names=[NY, LON, NY], npc=GREEN, marks=[NY, LON], focus="north"),
    Step(4, "Red's turn",
         "Red adds 3 troops to {} and ends its turn.",
         names=[VIK], npc=RED, marks=[VIK], focus="europe"),

    # 5 -----------------------------------------------------------------------------------
    Step(5, "Over the sea",
         "The dotted blue lines are sea routes. You can't cross them without something to carry "
         "your troops over the water: a ship, or a plane.",
         marks=[MEX, CUBA], focus="south"),
    Step(5, "Buy a ship",
         "Your first ship each game is free. Open the shop, click the ship, click the green button and then "
         "click {} to put it there.",
         names=[MEX], done=_bought("ships", MEX), hold=_hold(only=[MEX]), marks=_shop_marks("ship_card", MEX)),
    Step(5, "Place your troops",
         "Put your 3 new troops in {} too.",
         names=[MEX], done=_deployed, hold=_hold(only=[MEX]), marks=["soldier", MEX]),
    Step(5, "On to the attack",
         "Click the red button to go to the attack phase.",
         done=lambda tu: tu.player.attack >= 1, hold=_hold(only=[]), marks=["attack_phase"], phases=True),

    # 6 -----------------------------------------------------------------------------------
    Step(6, "A chance",
         "Green is spread thin: 1 troop in {}, 1 in {} and 4 in {}. If you bring your troops "
         "together, you can eliminate green this turn.",
         names=[CUBA, NY, LON], marks=[CUBA, NY, LON], focus="route"),
    Step(6, "Retake Venezuela",
         "First attack {} from {}. When it's yours, move in all your troops but one.",
         names=[VEN, BRA], done=_moved_in(VEN),
         hold=_hold(only=[BRA, VEN], confirm=lambda tu: _units(BRA)(tu) == 1), marks=_attack_marks(BRA, VEN)),
    Step(6, "Rails",
         "Rails let your troops ride from country to country in one go. Open the shop, pick the "
         "rails (2 wood, 1 steel), click the green button, then click {} and {}.",
         names=[PER, VEN], done=_rails(PER, VEN), hold=_hold(only=[PER, VEN]),
         marks=_shop_marks("rails_card", PER, VEN)),
    Step(6, "More rails",
         "Now lay rails from {} to {} the same way.",
         names=[VEN, MEX], done=_rails(VEN, MEX), hold=_hold(only=[VEN, MEX]),
         marks=_shop_marks("rails_card", VEN, MEX)),
    Step(6, "Take the train",
         "Click {}, then the train button at the bottom left (1 oil). Right-click {} and {} to take "
         "their troops out, leaving 1 in each, and left-click {} to put them all there. Then click "
         "the green button.",
         names=[MEX, VEN, PER, MEX], done=_moved_by("rails"),
         hold=_hold(only=[MEX, VEN, PER], confirm=lambda tu: _units(VEN)(tu) == 1 and _units(PER)(tu) == 1),
         marks=_transfer_marks(MEX, "train", [VEN, PER, MEX])),
    Step(6, "Across to Cuba",
         "Attack {} from {}: your ship carries the troops across. When it's yours, move every troop "
         "in and leave {} empty: keeping all your troops together gives the best chance to "
         "eliminate green this turn.",
         names=[CUBA, MEX, MEX], done=_moved_in(CUBA),
         hold=_hold(only=[MEX, CUBA], confirm=lambda tu: _units(MEX)(tu) == 0), marks=_attack_marks(MEX, CUBA)),
    Step(6, "On to New York",
         "Attack {} from {}, and again move everyone in, leaving {} empty.",
         names=[NY, CUBA, CUBA], done=_moved_in(NY),
         hold=_hold(only=[CUBA, NY], confirm=lambda tu: _units(CUBA)(tu) == 0), marks=_attack_marks(CUBA, NY)),
    Step(6, "Take London",
         "Attack {}, green's last country, from {}. Roll until it's yours, then click the green "
         "button to move in.",
         names=[LON, NY], done=_moved_in(LON),
         hold=_hold(only=[NY, LON], confirm=lambda tu: _units(NY)(tu) >= 1), marks=_attack_marks(NY, LON)),
    Step(6, "Green is out",
         "Taking a player's last country eliminates them, and you get their cards, wood, steel, oil "
         "and uranium, but not their food: 3 cards, 40 steel, 4 oil and 10 wood.",
         marks=["player_panel"]),
    Step(6, "On to moving",
         "Click the orange button to go to the move phase.",
         done=_phase(2), hold=_hold(only=[]), marks=["move_phase"], phases=True),
    Step(6, "Sail back",
         "Move your ship and troops back to {}: click {}, then {}, and click {} until {} has 1 "
         "left. Then pick the ship at the top, click {} once and click the green button.",
         names=[NY, LON, NY, NY, LON, NY], done=lambda tu: tu.player.repositioned_this_turn,
         hold=_hold(only=[LON, NY], confirm=lambda tu: _units(LON)(tu) == 1 and tu.app.countries[NY].ships > 0),
         marks=_move_marks(LON, NY), focus="north"),
    Step(6, "End your turn",
         "Click End turn.",
         done=lambda tu: tu.app.turn != BLUE, hold=_hold(only=[]), marks=["end_turn"], end_turn=True),

    # 7 -----------------------------------------------------------------------------------
    Step(7, "Red's turn",
         "Red adds 3 more troops to {}: 12 now, behind its fort.",
         names=[VIK], npc=RED, marks=[VIK], focus="europe"),

    # 8 -----------------------------------------------------------------------------------
    Step(8, "Place your troops",
         "Put your 3 new troops in {}.",
         names=[LON], done=_deployed, hold=_hold(only=[LON]), marks=["soldier", LON], focus="atlantic"),
    Step(8, "Buy a plane",
         "A plane carries troops across the sea, for 1 oil per attack, and makes its country an "
         "airport. Buy one (10 steel) and put it in {}.",
         names=[LON], done=_bought("planes", LON), hold=_hold(only=[LON]), marks=_shop_marks("plane_card", LON)),
    Step(8, "Buy a tank",
         "A tank adds 1 to your highest die when you attack, for 1 oil per attack. Buy one (20 "
         "steel) and put it in {}.",
         names=[VEN], done=_bought("tanks", VEN), hold=_hold(only=[VEN]), marks=_shop_marks("tank_card", VEN)),
    Step(8, "Trade cards",
         "Conquering a country of another player earns you a card at the end of your turn: with "
         "green's 3 cards you now hold 4. Three different cards make a set worth 10. Open your "
         "cards (the set is selected), click the green button and take 10 uranium: you'll need it "
         "later.",
         done=lambda tu: tu.player.nuclear >= 10 and not tu.app.card_menu.trade_mode,
         hold=_hold(reward="nuclear"), marks=_card_marks),
    Step(8, "On to the attack",
         "Click the red button to go to the attack phase.",
         done=lambda tu: tu.player.attack >= 1, hold=_hold(only=[]), marks=["attack_phase"], phases=True),

    # 9 -----------------------------------------------------------------------------------
    Step(9, "The fort",
         "{} has a fort: it adds 1 to every die red defends with, and 12 troops stand behind it. "
         "That will be a hard fight.",
         names=[VIK], marks=[VIK], focus="atlantic"),
    Step(9, "Rails to Brazil",
         "Lay rails between {} and {} too: open the shop, pick the rails, click the green button, "
         "then click {} and {}.",
         names=[BRA, VEN, BRA, VEN], done=_rails(BRA, VEN), hold=_hold(only=[BRA, VEN]),
         marks=_shop_marks("rails_card", BRA, VEN)),
    Step(9, "Gather by rail",
         "First bring your troops in South America together: click {}, then the train button, "
         "right-click {} and {} to remove troops there and left-click {} to place them down. Then "
         "click the green button.",
         names=[VEN, PER, BRA, VEN], done=_moved_by("rails"),
         hold=_hold(only=[VEN, PER, BRA], confirm=lambda tu: _units(PER)(tu) == 0 and _units(BRA)(tu) == 0),
         marks=_transfer_marks(VEN, "train", [PER, BRA, VEN])),
    Step(9, "Fly to London",
         "Airports do the same thing as rails by connecting all of your airport countries together. "
         "As long as you have at least one airplane at one of your airports and 1 oil to pay for the "
         "flight, you can reposition troops and tanks between your airports as you like. Click on "
         "the plane button that appears when you have either {} or {} selected. Right-click to "
         "remove troops from {} until it is empty, then select the tank icon at the top and "
         "right-click {} again to remove the tank as well. Left-click on {} to place the tank and "
         "troops.",
         names=[VEN, LON, VEN, VEN, LON], done=_moved_by("air"),
         hold=_hold(only=[VEN, LON], confirm=lambda tu: _units(VEN)(tu) == 0
                    and tu.app.countries[VEN].tanks == 0),
         marks=_transfer_marks(VEN, "plane_button", [VEN, LON], tank=True)),
    Step(9, "Nuke Viking",
         "A nuke kills half the troops of a country adjacent to yours. Buy one in the shop (5 nuclear) "
         "and click {}. Then do it once more.",
         names=[VIK], done=lambda tu: tu.app.countries[VIK].radioactive >= 6 and tu.player.attack != 3,
         hold=_hold(only=[VIK]), marks=_shop_marks("nuke_card", VIK), focus="europe"),
    Step(9, "Fallout",
         "Two nukes brought {} from 12 troops down to 3. And while it's radioactive (3 turns per "
         "nuke) it produces nothing.",
         names=[VIK], marks=[VIK]),
    Step(9, "Attack Viking",
         "Attack {} from {}: the plane carries your troops across (1 oil) and the tank adds 1 to "
         "your highest die (1 oil). Roll until it's yours, then move all your troops in.",
         names=[VIK, LON], done=_moved_in(VIK),
         hold=_hold(only=[LON, VIK], confirm=lambda tu: _units(LON)(tu) == 0), marks=_attack_marks(LON, VIK)),
    Step(9, "Out of oil",
         "Red's last country, {}, lies across the sea, and your oil is gone: the plane can't take "
         "your troops over.",
         names=[SOV], marks=[SOV, "oil"]),
    Step(9, "Build a bridge",
         "A bridge turns a sea route into a land route. Buy one (10 wood), then click {} and then {}.",
         names=[VIK, SOV], done=lambda tu: any(set(c.connection) == {VIK, SOV} and c.kind == "land"
                                               for c in tu.app.connections) and tu.player.attack != 3,
         hold=_hold(only=[VIK, SOV]), marks=_shop_marks("bridge_card", VIK, SOV)),
    Step(9, "Bring or leave",
         "Before you roll, the button at the top with a ship, a plane and a tank lets you choose "
         "which of them come along into the fight. What you bring moves into the country you "
         "conquer, but it's destroyed if you roll 1 or 2 dice and lose them all. Without oil your "
         "tank adds nothing to your dice, so you could leave it at home.",
         marks=[VIK]),
    Step(9, "Eliminate red",
         "Attack {} from {} by crossing your bridge, and win the game!",
         names=[SOV, VIK], done=lambda tu: tu.app.turn_manager.game_over,
         hold=_hold(only=[VIK, SOV]), marks=_attack_marks(VIK, SOV)),
]
PARTS = 9


class Tutorial:
    """The tutorial's panel and steps over the tutorial's game (`app`)."""

    def __init__(self, app):
        self.app = app
        self.player = app.players[BLUE]
        self.steps = STEPS
        self.index = 0
        self.active = True
        self.moves = {"rails": 0, "air": 0}   # confirmed rail and airlift moves (_count_moves)
        self.start_moves = dict(self.moves)   # ...when the step started
        self._panel = None          # the panel's rect, as last drawn
        self._buttons = {}          # its buttons: name -> rect
        self._npc_key = None        # whose turn the scripted moves are for
        self._npc_moves = []
        self._npc_at = 0
        self._npc_turns = {GREEN: 0, RED: 0}
        self.title_font = game_font(24, bold=True)
        self.font = game_font(18)
        self.small_font = game_font(16)
        manager = app.turn_manager
        # No world events during the tutorial; green and red play the
        # tutorial's script (finish puts both back).
        manager._update_event_schedule = lambda: None
        manager.bot.update = self._npc_update
        self._rig_dice()
        self._count_moves()
        self._enter()

    # --- the game, scripted ------------------------------------------------------------------

    def _rig_dice(self):
        """The player's attacks always win: their dice come up 5 or 6, the
        defender's low enough to lose every pair (fort and tanks included)."""
        attack = self.app.turn_manager.phases[1]
        cast, roll = attack._cast_attack_dice, attack._roll_dice

        def ours():
            return self.active and self.app.players[self.app.turn] is self.player

        def rigged_cast():
            cast()
            if ours():
                for i, die in enumerate(attack.attack_dice):
                    if die > 0:
                        attack.attack_dice[i] = random.choice((5, 6))

        def rigged_roll():
            roll()
            if ours() and self.player.subattack == 4:
                weakest = min(d for d in attack.attack_dice if d > 0)
                bonus = self.app.countries[attack.defence_country].fort_lvl + attack._defending_tanks()
                top = max(1, int(weakest) - 1 - bonus)
                for i, die in enumerate(attack.defence_dice):
                    if die > 0:
                        attack.defence_dice[i] = random.randint(1, top)

        attack._cast_attack_dice = rigged_cast
        attack._roll_dice = rigged_roll

    def _count_moves(self):
        """Count the player's confirmed rail and airlift moves (moves)."""
        attack = self.app.turn_manager.phases[1]
        finish = attack._finish_redistribute

        def counted():
            if self.app.players[self.app.turn] is self.player:
                self.moves[attack._redistribute_kind] += 1
            return finish()

        attack._finish_redistribute = counted

    def _npc_turn(self, index):
        """Green's and red's moves for their next turn: (function, args) in
        order; anything past the script just places its troops."""
        turn = self._npc_turns[index]
        self._npc_turns[index] += 1
        if index == GREEN and turn == 0:
            return [(self._deploy, NY, 3), (self._ship, NY), (self._take, NY, LON, 1)]
        if index == RED and turn in (0, 1):
            return [(self._deploy, VIK, 3)]
        biggest = max((c for c in self.app.countries.values() if c.owner is self.app.players[index]),
                      key=lambda c: c.units)
        return [(self._deploy, biggest.name, None)]

    def _npc_update(self):
        """Stands in for BotController.update on green's and red's turns: the
        phase draws itself (and starts the turn), then their scripted moves
        go one by one, NPC_MS apart, and the turn ends once the player has
        clicked Next on the page about it (npc_waiting)."""
        app = self.app
        manager = app.turn_manager
        player = app.players[app.turn]
        io = app.io
        clicks = io.left_pressed, io.right_clicked
        io.left_pressed, io.right_clicked = 0, False
        phase = manager.phases.get(player.attack)
        if phase is not None:
            phase.update()
        io.left_pressed, io.right_clicked = clicks
        if app.players[app.turn] is not player or not manager.turn_started:
            return
        now = pg.time.get_ticks()
        key = (manager.turn_num, app.turn)
        if key != self._npc_key:
            self._npc_key = key
            self._npc_moves = self._npc_turn(app.turn)
            self._npc_at = now + NPC_MS
        if now < self._npc_at:
            return
        self._npc_at = now + NPC_MS
        if self._npc_moves:
            move, *args = self._npc_moves.pop(0)
            move(player, *args)
            return
        if self.npc_waiting():
            return
        turn = app.turn
        while app.turn == turn and not manager.game_over:
            manager.end_phase()

    def npc_waiting(self):
        """Green's or red's moves are done and the page about their turn
        waits for the player's Next before the turn ends."""
        app = self.app
        step = self.step
        return (step is not None and step.npc == app.turn and not self._npc_moves
                and self._npc_key == (app.turn_manager.turn_num, app.turn))

    def _deploy(self, player, name, count):
        manager = self.app.turn_manager
        count = manager.reinforcements if count is None else count
        self.app.countries[name].units += count
        manager.reinforcements = 0
        manager.all_reinforcements_deployed = True
        self.app.log_action(player, Msg(" placed {} troops in {}", count, name))

    def _ship(self, player, name):
        self.app.turn_manager.phases[3].place_unit("ships", {"wood": 0}, name)

    def _take(self, player, source, target, keep):
        """`player` takes `target` from `source` (a sure win) and moves in
        all but `keep` troops, ships along."""
        countries = self.app.countries
        source, target = countries[source], countries[target]
        previous = target.owner
        self.app.log_wiped(target)
        target.owner = player
        target.units = source.units - keep
        target.ships, source.ships = source.ships, 0
        target.tanks = target.planes = target.fort_lvl = 0
        source.units = keep
        self.app.log_action(player, Msg(" took {} from ", target.name), previous)
        sounds.play("click")

    # --- the steps -----------------------------------------------------------------------------

    @property
    def step(self):
        return self.steps[self.index] if self.active else None

    def _enter(self):
        self.start_moves = dict(self.moves)
        if self.step.focus is not None:
            self._focus(*FOCUS[self.step.focus])

    def _focus(self, x, y, zoom, spot=FOCUS_SPOT):
        """Put map point (x, y) at `spot` on screen (by default the middle of
        the map between the player's stock and the side panels, below the
        panel), at `zoom`."""
        view = self.app.view
        sx, sy = spot
        view.zoom = zoom
        view.offset = Position((sx - 0.5 * view.WIDTH) / zoom - x, (sy - 0.5 * view.HEIGHT) / zoom - y)
        view.wrap()

    def _panel_spot(self):
        """The panel's (x, y, width): at the top, just left of the country
        info panel; while the shop is open, in the shop's empty top right;
        while the cards are open, wide and short above them (right of the
        top-left buttons), and right of the rewards once trading; on the dice
        screen below its Assets button."""
        app = self.app
        player = self.player
        right = app.view.WIDTH - app.gui.width - GAP
        if app.players[app.turn] is player and player.attack == 3 and player.subattack < 8:
            return SHOP_SPOT + (WIDTH,)
        if app.card_menu.trade_mode:
            return app.card_menu._option_rect(0).right + 2 * GAP, SHOP_SPOT[1], WIDTH
        if app.card_menu.show:
            buttons = app._event_button()
            left = buttons.pos.x + buttons.width + 2 * GAP
            return left, GAP, right - left
        if player.attack == 1 and player.subattack == 2 and app.players[app.turn] is player:
            # Below the dice screen's Assets button (AttackPhase._choose_dice_count).
            return right - WIDTH, 12 + Phase.ASSETS_BUTTON_SIZE + GAP, WIDTH
        return right - WIDTH, GAP, WIDTH

    def _next(self):
        self.index += 1
        if self.index >= len(self.steps):
            self.finish()
        else:
            self._enter()

    def finish(self):
        """The tutorial is over (the game won, or End tutorial, which then goes
        back to the title screen): the panel goes, and the held-back world
        events and green's and red's script are undone."""
        self.active = False
        manager = self.app.turn_manager
        manager.__dict__.pop("_update_event_schedule", None)
        manager.bot.__dict__.pop("update", None)

    # --- input ---------------------------------------------------------------------------

    def handle_input(self):
        """Runs right after Engine.io_handle: the panel's own clicks, and the
        clicks the current step holds back from the game."""
        step = self.step
        if step is None or self.app.turn_manager.dialog_active:
            return  # (a dialog's click is always the game's; the panel is hidden)
        io = self.app.io
        pos = io.mouse_position
        point = (pos.x, pos.y)
        if self._panel is not None and self._panel.collidepoint(point):
            if io.left_pressed:
                for name, rect in self._buttons.items():
                    if rect.collidepoint(point):
                        self._press(name)
            io.left_pressed = 0
            io.right_clicked = False
            io.hover_country = None
            return
        if step.done is None:
            io.left_pressed = 0  # a page to read: the game waits
            io.right_clicked = False
            return
        if not (io.left_pressed or io.right_clicked):
            return
        gui, view = self.app.gui, self.app.view
        held = (not step.phases and any(gui.phase_button_hit(view, i, pos) for i in range(3))) \
            or (not step.end_turn and gui.end_turn_hit(view, pos))
        if not held and step.hold is not None and self.app.players[self.app.turn] is self.player \
                and step.hold(self, point):
            held = True
            sounds.play("error")
        if held:
            io.left_pressed = 0
            io.right_clicked = False

    def _press(self, name):
        if name == "end":
            self.finish()
            self.app.pending_quit = True  # back to the title screen (runner.play)
        elif name == "next":
            self._next()

    # --- drawing -------------------------------------------------------------------------

    def draw(self):
        """Runs right before Engine.present: moves on when the step is done,
        then rings what it's about and draws the panel (not over a dialog)."""
        if not self.active:
            return
        self.app.settings["fast_bots"] = False  # the tutorial always plays at normal speed
        while self.active and self.step.done is not None and self.step.done(self):
            self._next()
        if not self.active or self.app.turn_manager.dialog_active:
            return
        step = self.step
        marks = step.marks(self) if callable(step.marks) else step.marks
        grow = 2 + 2 * math.sin(pg.time.get_ticks() / 160)
        for key in marks:
            for shape in self._shapes(key):
                self._ring(shape, grow)
        self._draw_panel(step)

    def _ring(self, shape, grow):
        screen = self.app.view.screen
        if shape[0] == "c":
            _, center, radius = shape
            radius = int(radius + 4 + grow)
            pg.draw.circle(screen, (0, 0, 0), center, radius + 2, 7)
            pg.draw.circle(screen, MARK_COLOR, center, radius + 1, 4)
            return
        rect = shape[1].inflate(2 * int(6 + grow), 2 * int(6 + grow))
        pg.draw.rect(screen, (0, 0, 0), rect, 6, border_radius=9)
        pg.draw.rect(screen, MARK_COLOR, rect.inflate(-2, -2), 4, border_radius=8)

    # The shop's cards: the infrastructure row, then the units row (ShopPhase._draw_menu).
    SHOP_CARDS = {"bridge_card": (0, 0), "rails_card": (0, 1), "nuke_card": (0, 2),
                  "ship_card": (1, 0), "plane_card": (1, 1), "tank_card": (1, 2)}

    def _shapes(self, key):
        """What `key` rings: ("r", rect) or ("c", center, radius), in the
        logical 960x640."""
        app = self.app
        view, gui = app.view, app.gui
        manager = app.turn_manager
        if key in app.countries:
            return [("c", self._marker(app.countries[key]), 16)]
        buttons = {"settings": app._settings_button, "shop": app._shop_button,
                   "cards": app._card_button, "event": app._event_button}
        if key in buttons:
            button = buttons[key]()
            return [("r", pg.Rect(button.pos.x, button.pos.y, button.width, button.height))]
        if key == "player_panel":
            return [("r", gui.player_rect)] if gui.player_rect is not None else []
        if key == "oil":
            return [("r", gui.player_rows[3])] if len(gui.player_rows) > 3 else []
        if key in ("attack_phase", "move_phase"):
            index = 1 if key == "attack_phase" else 2
            return [("c", gui.phase_button_center(view, index), gui.phase_button_radius)]
        if key == "end_turn":
            return [("r", gui.end_turn_rect(view))]
        if key == "confirm":
            return [("r", pg.Rect(*image_button_shape(Phase.CONFIRM_X, Phase.ROW_Y)[1:]))]
        if key == "soldier":
            # Phase._draw_reinforcements' card, at the left edge.
            bottom = view.HEIGHT - app.ACTION_BOX_H - (app.font.get_height() + 8) - 30
            return [("r", pg.Rect(Phase.BUTTON_GAP + 6, bottom - 100, 78, 104))]
        if key == "dice":
            return [("r", pg.Rect(Phase.DICE_CX - 125, Phase.PICK_DICE_Y - 5, 250, 120))]
        if key in ("train", "plane_button"):
            cx, cy = manager.phases[1]._left_button_pos(1 if key == "train" else 2)
            w, h = PICTURE_BUTTON_SIZE
            return [("r", pg.Rect(cx - w // 2, cy - h // 2, w, h))]
        if key in ("troop_pool", "tank_pool"):
            # The first (troops) or second (tanks) sprite of the redistribute
            # screen's selector (Phase._resource_selector).
            index = 0 if key == "troop_pool" else 1
            count = 3 if manager.phases[1]._redistribute_kind == "air" else 2
            step = Phase.SELECTOR_STEP
            left = (view.WIDTH - ((count - 1) * step + 80)) // 2
            return [("r", pg.Rect(left + index * step + 40 - 28, 22, 56, 56))]
        if key == "nuclear_option":
            from models import CardMenu
            index = [option[1] for option in CardMenu.TRADE_OPTIONS].index("nuclear")
            return [("r", app.card_menu._option_rect(index))]
        if key in self.SHOP_CARDS:
            row, column = self.SHOP_CARDS[key]
            fx, fy = manager.phases[3]._frame_origin()
            return [("r", pg.Rect(fx + 30 + 150 * column, fy + (30, 295)[row], 130, 235))]
        if key == "confirm_card":
            cx, cy = manager.phases[3]._selected_card_center()
            return [("r", pg.Rect(*image_button_shape(cx, cy)[1:]))]
        return []

    def _marker(self, country):
        """Centre of a country's troop marker on screen, the copy of the
        world nearest the middle (as Io.country_at)."""
        view = self.app.view
        cx = (country.mass_center.x + view.offset.x) * view.zoom
        cy = (country.mass_center.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT
        period = WORLD_WIDTH * view.zoom
        cx = (cx + 0.5 * period) % period - 0.5 * period + 0.5 * view.WIDTH
        return int(cx), int(cy)

    def _draw_panel(self, step):
        app = self.app
        screen = app.view.screen
        x, y, width = self._panel_spot()
        inner = width - 2 * PAD

        title = TurnManager._wrap_text(t(step.title), self.title_font, inner - 70)
        text = t(step.text).format(*(t(name) for name in step.names))
        paragraphs = [TurnManager._wrap_text(part, self.font, inner) for part in text.split("\n")]
        line_h = self.font.get_height() + 2
        title_h = len(title) * (self.title_font.get_height() + 2)
        body_h = sum(len(lines) * line_h for lines in paragraphs) + 8 * (len(paragraphs) - 1)
        button_h = 34
        height = PAD + title_h + 10 + body_h + 16 + button_h + PAD
        panel = pg.Rect(x, y, width, height)
        self._panel = panel

        pg.draw.rect(screen, PANEL_COLOR, panel, border_radius=8)
        pg.draw.rect(screen, (0, 0, 0), panel, 3, border_radius=8)
        count = self.small_font.render(t("Part {} of {}").format(step.part, PARTS), True, (120, 110, 90))
        screen.blit(count, (panel.right - PAD - count.get_width(), y + PAD + 2))
        top = y + PAD
        for line in title:
            screen.blit(self.title_font.render(line, True, (0, 0, 0)), (x + PAD, top))
            top += self.title_font.get_height() + 2
        top += 10
        for lines in paragraphs:
            for line in lines:
                screen.blit(self.font.render(line, True, (30, 30, 30)), (x + PAD, top))
                top += line_h
            top += 8

        # Next on a page to read (on green's or red's turn: once their moves
        # are done); End tutorial always.
        mouse = app.io.mouse_position
        self._buttons = {}
        end_label = t("End tutorial")
        end_rect = pg.Rect(x + PAD, panel.bottom - PAD - button_h, self.small_font.size(end_label)[0] + 20, button_h)
        self._buttons["end"] = end_rect
        self._button(end_rect, end_label, (235, 225, 200), self.small_font, mouse)
        if step.done is None and (step.npc is None or self.npc_waiting()):
            label = t("Next")
            next_w = max(96, self.font.size(label)[0] + 24)
            next_rect = pg.Rect(panel.right - PAD - next_w, end_rect.y, next_w, button_h)
            self._buttons["next"] = next_rect
            self._button(next_rect, label, (150, 245, 150), self.font, mouse)
        # The map and buttons under the panel are out of reach (Io.country_at).
        app.io.button(("r", panel.x, panel.y, panel.w, panel.h))

    def _button(self, rect, label, color, font, mouse):
        if rect.collidepoint(mouse.x, mouse.y):
            color = tuple(min(255, c + 25) for c in color)
        screen = self.app.view.screen
        pg.draw.rect(screen, color, rect, border_radius=6)
        pg.draw.rect(screen, (0, 0, 0), rect, 2, border_radius=6)
        text = font.render(label, True, (0, 0, 0))
        screen.blit(text, text.get_rect(center=rect.center))
