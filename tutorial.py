"""
The tutorial (main menu > Tutorial): a real local game on a small fixed
board -- you in the south of Africa, two bots far away in New York and
Siberië -- with a panel that walks through the screen and the rules one
step at a time and plays the first turn along with the player.

A step either is a page to read (a Next button; the game takes no clicks
meanwhile) or waits for the player to do something on the board (it goes
on by itself once its `done` holds, or with Skip). What a step is about
is ringed on the screen (`Tutorial._shapes`). The phase buttons and End
turn are held back unless the step asks for them, so the turn can't run
ahead of the tutorial; a step whose goal has already been reached (the
player ran ahead anyway) is passed over.

World events are held back while the tutorial runs, and come on once it's
finished (or ended); the game then simply goes on. Its autosaves go to a
temporary file, so the player's own autosave stays as it was.

runner.play calls `handle_input` right after `Engine.io_handle` and `draw`
right before `Engine.present`.
"""

import math
import os
import tempfile

import pygame as pg

from board import get_countries
from fonts import game_font
from lang import t
from models import Kaertske, Position, WORLD_WIDTH
from phases import Phase, TurnManager, image_button_shape, PICTURE_BUTTON_SIZE

SAVE_PATH = os.path.join(tempfile.gettempdir(), "oil_tutorial.json")

# The board: the player's countries (troops), then each bot's start.
HOME = {"Zuid-Afrika": 6, "Belgisch Congo": 5}
BOT_STARTS = [("New York", 15), ("Siberië", 15)]
# Food, wood, steel, oil and nuclear in stock, and one card of each type
# (a set to trade).
STOCK = {"food": 60, "wood": 12, "steel": 22, "oil": 6, "nuclear": 0}
CARDS = (0, 1, 2)
# The view at the start: southern Africa right of the panel.
ZOOM = 2.0
OFFSET = (-280, -365)

PANEL_COLOR = (255, 248, 225)
MARK_COLOR = (255, 205, 0)
WIDTH = 268          # the panel (logical px)
PAD = 14
LEFT = (12, 96)      # its top-left: under the top-left buttons...
RIGHT = (676, 88)    # ...or, while the shop is open, in the shop's empty top right


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
    human, *bots = app.players
    for resource, amount in STOCK.items():
        setattr(human, resource, amount)
    human.cards = [Kaertske(kind, images=app.images) for kind in CARDS]
    for name, units in HOME.items():
        app.countries[name].owner = human
        app.countries[name].units = units
    for bot, (name, units) in zip(bots, BOT_STARTS):
        app.countries[name].owner = bot
        app.countries[name].units = units
        app.countries[name].airport = True  # as a normal start
    app.turn = 0
    app.card_menu.player = human
    # Past everyone's first turn (which gives nothing): income from the start.
    app.turn_manager.turn_num = len(app.players)
    app.save_path = SAVE_PATH
    app.settings["fast_bots"] = True
    app.view.zoom = ZOOM
    app.view.offset = Position(*OFFSET)


class Step:
    """One page of the tutorial: a title and a text (English source, through
    t(); "{}" in it are the country names `names`, translated). `done(tu)`:
    the step waits until it returns True (None: a page to read, with a Next
    button). `marks`: what's ringed on the screen, keys of Tutorial._shapes
    or country names, or a function of the Tutorial returning them.
    `phases`/`end_turn`: whether the phase buttons / End turn may be used."""

    def __init__(self, title, text, done=None, marks=(), names=(), phases=False, end_turn=False):
        self.title = title
        self.text = text
        self.done = done
        self.marks = marks
        self.names = names
        self.phases = phases
        self.end_turn = end_turn


def _card_marks(tu):
    menu = tu.app.card_menu
    if menu.trade_mode:
        return []
    return ["confirm"] if menu.show else ["cards"]


def _shop_marks(tu):
    player = tu.player
    if player.attack == 3 and player.subattack < 8:
        return [] if player.subattack == 4 else ["ship_card"]
    if player.attack == 3:
        return ["Zuid-Afrika"]
    return ["shop"]


def _dice_marks(tu):
    player = tu.player
    return ["dice", "confirm"] if player.attack == 1 and player.subattack == 2 else []


def _move_in_marks(tu):
    target = tu.app.turn_manager.phases[1].defence_country
    return [target, "confirm"] if target else ["confirm"]


def _move_marks(tu):
    sub = tu.player.subattack
    if sub == 0:
        return ["Zuid-Afrika"]
    if sub == 1:
        return ["Belgisch Congo"]
    return ["Belgisch Congo", "confirm"] if sub == 2 else []


def _deployed(tu):
    manager = tu.app.turn_manager
    player = tu.player
    return player.attack != 0 or (manager.turn_started and manager.all_reinforcements_deployed
                                  and manager.reinforcements <= 0 and player.subattack == 1)


def _ours(tu):
    return tu.app.turn == 0


STEPS = [
    Step("Welcome to OIL",
         "This tutorial plays your first turn with you, one step at a time. You are the blue player, "
         "in the south of Africa. Two bots play far away, in North America and Siberia.\n"
         "Click Next to begin.",
         marks=["own"]),
    Step("The map",
         "Every shape is a country, in the colour of its owner. Grey countries belong to nobody yet. "
         "The number on a country is its troops.\n"
         "Hold the right mouse button and drag to move the map; scroll to zoom in and out.",
         marks=["own"]),
    Step("Routes",
         "Countries are connected by routes: solid lines over land, dotted lines over sea. You can "
         "only attack and move along a route. To cross the sea you need a ship or a plane.",
         marks=["Belgisch Congo", "Somalië", "Nigeria", "Madagaskar"]),
    Step("Country info",
         "Point at a country, for example {}. The panel at the top right shows what it gives its "
         "owner every turn: food, wood, steel, oil, nuclear and helmets. It also shows an airport "
         "or fort, if it has one.",
         marks=lambda tu: ["Somalië"] + (["info_panel"] if tu.app.io.hover_country else []),
         names=["Somalië"]),
    Step("Your stock",
         "The panel at the bottom right shows your stock. The number in brackets next to it is what "
         "comes in at your next turn.\n"
         "At the start of every turn each troop eats 1 food (the red number); the green number is "
         "your harvest. Troops you can't feed starve.",
         marks=["player_panel"]),
    Step("New troops",
         "The helmets are the troop production of your countries. Every turn you get a third of "
         "your helmets plus 3 as new troops.",
         marks=["helmets"]),
    Step("The phases",
         "Every turn has three phases: deploying troops (yellow), attacking (red) and moving "
         "(orange). The bright button is the phase you're in. End turn ends your turn.",
         marks=["phases", "end_turn"]),
    Step("The buttons",
         "At the top left: the settings (save, exit, display), the shop, your cards and the world "
         "event. You'll use the shop and the cards in a moment.",
         marks=["settings", "shop", "cards", "event"]),
    Step("Cards",
         "You hold three cards. Three of a kind, or one of each, make a set, which you can trade "
         "for troops or resources, but only while deploying troops.\n"
         "Open your cards.",
         done=lambda tu: tu.app.card_menu.show or tu.app.card_menu.trade_mode or not tu.player.cards
         or tu.player.attack != 0,
         marks=["cards"]),
    Step("Trade a set",
         "Your three cards are already selected. Click the green button to trade them, then pick a "
         "reward. One of each is worth 10 troops (or 25 food, 30 wood, 20 steel, 20 oil or 10 "
         "nuclear).",
         done=lambda tu: not tu.player.cards or tu.player.attack != 0,
         marks=_card_marks),
    Step("Getting cards",
         "You get a card at the end of every turn in which you conquered a country of another "
         "player, and cards for holding a whole continent. Holding more than 4 cards forces you "
         "to trade."),
    Step("Deploy your troops",
         "The number on the soldier at the left is how many new troops you can place. Left-click "
         "one of your countries to put a troop there, right-click to take it back.\n"
         "Put them in {}: you'll attack from there.",
         done=_deployed, marks=["soldier", "Belgisch Congo"], names=["Belgisch Congo"]),
    Step("The shop",
         "With wood, steel and nuclear you buy things in the shop: bridges and rails, nukes, and "
         "(only while deploying) ships, planes, tanks and forts. Ships and planes take troops across "
         "the sea, a tank adds 1 to your highest attack die, a fort adds to every defence die.",
         marks=["shop"]),
    Step("Buy a ship",
         "Your first ship is free. Open the shop, click the ship, click the green button and then "
         "click {} to put the ship there.",
         done=lambda tu: (tu.player.attack != 3 and tu.assets() != tu.start_assets)
         or tu.player.attack in (1, 2),
         marks=_shop_marks, names=["Zuid-Afrika"]),
    Step("On to the attack",
         "Click the red button to go to the attack phase.",
         done=lambda tu: tu.player.attack in (1, 2) or not _ours(tu),
         marks=["attack_phase"], phases=True),
    Step("Pick a target",
         "Click {} to attack from it, then {} to attack it.",
         done=lambda tu: tu.player.attack != 1 or tu.player.subattack >= 2,
         marks=["Belgisch Congo", "Somalië"], names=["Belgisch Congo", "Somalië"]),
    Step("Rolling the dice",
         "You roll a die for every attacking troop, at most 3 (one troop stays home). The defender "
         "rolls up to 2. The highest dice are compared in pairs: the higher die wins, a tie goes to "
         "the defender, and the loser of each pair loses a troop.\n"
         "Click a die to leave it out, then click the green button to roll.",
         done=lambda tu: tu.rolls > tu.start_rolls or tu.player.attack != 1,
         marks=_dice_marks),
    Step("Conquer it",
         "After a roll, click anywhere to count the losses. Keep rolling until {} has no troops "
         "left: then it's yours. A fort adds to every defence die, an active tank adds 1 to your "
         "highest die.\n"
         "Careful: if you roll 1 or 2 dice and lose them all, the ships, tanks and planes you "
         "brought along are destroyed.",
         done=lambda tu: tu.owned() > len(HOME) or tu.player.attack != 1,
         marks=_dice_marks, names=["Somalië"]),
    Step("Move in",
         "Your troops move into the conquered country, all but one. Click the country you "
         "attacked from to keep one more there, or the new country to send one more in. Then click "
         "the green button.",
         done=lambda tu: not (tu.player.attack == 1 and tu.player.subattack == 5),
         marks=_move_in_marks),
    Step("Conquests",
         "A conquered country gives you its production from your next turn on. You can attack as "
         "often as you like in this phase, as long as you have troops to spare."),
    Step("On to moving",
         "Click the orange button to go to the move phase.",
         done=lambda tu: tu.player.attack == 2 or not _ours(tu),
         marks=["move_phase"], phases=True),
    Step("Move troops",
         "Once per turn you can move troops between two of your countries that are connected "
         "through your own countries. Click {}, then {}. Click a country to move a troop into it, "
         "then click the green button.",
         done=lambda tu: tu.player.repositioned_this_turn or tu.player.attack != 2,
         marks=_move_marks, names=["Zuid-Afrika", "Belgisch Congo"]),
    Step("Developing",
         "In this phase you can also develop one country per turn (the button at the bottom left). "
         "You pay what the country produces once; it then gives nothing at your next turn, and "
         "double from then on (right away if you hold its whole continent).",
         marks=lambda tu: ["develop"] if tu.player.attack == 2 else []),
    Step("End your turn",
         "Click End turn. The bots then play their turns.",
         done=lambda tu: not _ours(tu),
         marks=["end_turn"], end_turn=True),
    Step("The others play",
         "The bots are playing now. Everything that happens appears at the bottom left: click that "
         "box to read the whole log.",
         done=lambda tu: _ours(tu) and tu.app.turn_manager.turn_started,
         marks=["log"]),
    Step("Your turn again",
         "Your troops have eaten and your countries delivered their production: see your stock at "
         "the bottom right. The soldier shows your new troops.",
         marks=["player_panel", "soldier"]),
    Step("World events",
         "Every few turns a world event is drawn: a card that changes the rules for a full round, "
         "such as income, attacks or prices. The event button shows the active one and when the "
         "next one comes. In this tutorial they were held back.",
         marks=["event"]),
    Step("More to discover",
         "Rails let your troops travel far through your own countries. A bridge turns a sea route "
         "into a land route. Planes cross the sea for 1 oil, and give their country an airport. A "
         "nuke halves the troops of a country next to yours, which then produces nothing for 3 "
         "turns."),
    Step("Winning",
         "Take a player's last country and they're out: you get their wood, steel, oil, nuclear "
         "and cards. The last player left wins the game."),
    Step("That's it!",
         "You know the basics. Play on against the two bots in this game; world events are on from "
         "now. You can leave through the settings (top left): Exit Game."),
]


class Tutorial:
    """The tutorial's panel and steps over the tutorial's game (`app`)."""

    def __init__(self, app):
        self.app = app
        self.player = app.players[0]
        self.steps = STEPS
        self.index = 0
        self.active = True
        self.rolls = 0              # the player's attack rolls (see _count_rolls)
        self.start_rolls = 0        # ...when the step started
        self.start_assets = None    # assets() when the step started
        self._panel = None          # the panel's rect, as last drawn
        self._buttons = {}          # its buttons: name -> rect
        self.title_font = game_font(24, bold=True)
        self.font = game_font(18)
        self.small_font = game_font(16)
        # No world events during the tutorial (finish puts them back).
        app.turn_manager._update_event_schedule = lambda: None
        self._count_rolls()
        self._enter()

    def _count_rolls(self):
        attack = self.app.turn_manager.phases[1]
        roll = attack.roll_attack

        def counted():
            if self.app.players[self.app.turn] is self.player:
                self.rolls += 1
            return roll()

        attack.roll_attack = counted

    # --- the game as the steps see it -----------------------------------------------

    def owned(self):
        return sum(1 for c in self.app.countries.values() if c.owner is self.player)

    def assets(self):
        """What a purchase changes: the player's ships/tanks/planes/forts and
        the wood, steel and nuclear they pay with."""
        player = self.player
        mine = [c for c in self.app.countries.values() if c.owner is player]
        return (tuple(sum(getattr(c, key) for c in mine) for key in ("ships", "tanks", "planes", "fort_lvl"))
                + (player.wood, player.steel, player.nuclear))

    @property
    def step(self):
        return self.steps[self.index] if self.active else None

    def _enter(self):
        self.start_rolls = self.rolls
        self.start_assets = self.assets()

    def _next(self):
        self.index += 1
        if self.index >= len(self.steps):
            self.finish()
        else:
            self._enter()

    def finish(self):
        """The tutorial is over (or ended early): the panel goes and world
        events come on; the game goes on."""
        self.active = False
        self.app.turn_manager.__dict__.pop("_update_event_schedule", None)

    # --- input ---------------------------------------------------------------------------

    def handle_input(self):
        """Runs right after Engine.io_handle: the panel's own clicks, and the
        clicks the current step holds back from the game."""
        step = self.step
        if step is None:
            return
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
        if self.app.turn_manager.dialog_active:
            return  # a dialog's click is always the game's
        if step.done is None:
            io.left_pressed = 0  # a page to read: the game waits
            io.right_clicked = False
            return
        gui, view = self.app.gui, self.app.view
        held = (not step.phases and any(gui.phase_button_hit(view, i, pos) for i in range(3))) \
            or (not step.end_turn and gui.end_turn_hit(view, pos))
        if held:
            io.left_pressed = 0

    def _press(self, name):
        if name == "end":
            self.finish()
        elif name == "next":
            self._next()

    # --- drawing -------------------------------------------------------------------------

    def draw(self):
        """Runs right before Engine.present: moves on when the step is done,
        then rings what it's about and draws the panel."""
        if not self.active:
            return
        while self.active and self.step.done is not None and self.step.done(self):
            self._next()
        if not self.active:
            return
        step = self.step
        marks = step.marks(self) if callable(step.marks) else step.marks
        if not self.app.turn_manager.dialog_active:
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

    def _shapes(self, key):
        """What `key` rings: ("r", rect) or ("c", center, radius), in the
        logical 960x640."""
        app = self.app
        view, gui = app.view, app.gui
        if key == "own":
            return [s for name, c in app.countries.items() if c.owner is self.player
                    for s in self._shapes(name)]
        if key in app.countries:
            return [("c", self._marker(app.countries[key]), 16)]
        buttons = {"settings": app._settings_button, "shop": app._shop_button,
                   "cards": app._card_button, "event": app._event_button}
        if key in buttons:
            button = buttons[key]()
            return [("r", pg.Rect(button.pos.x, button.pos.y, button.width, button.height))]
        x0 = view.WIDTH - gui.width
        if key == "player_panel":
            return [("r", pg.Rect(x0, view.HEIGHT - gui.height, gui.width, gui.height - gui.PHASE_BOX_H))]
        if key == "helmets":
            cy = gui.player_row_center_y(view, gui.HELMET_ROW)
            return [("r", pg.Rect(x0 + 2, cy - 21, gui.width - 4, 42))]
        if key == "info_panel":
            return [("r", pg.Rect(x0, 0, gui.width, 170))]
        if key in ("phases", "attack_phase", "move_phase"):
            r = gui.phase_button_radius
            if key != "phases":
                return [("c", gui.phase_button_center(view, 1 if key == "attack_phase" else 2), r)]
            (x1, y), (x2, _) = gui.phase_button_center(view, 0), gui.phase_button_center(view, 2)
            return [("r", pg.Rect(x1 - r, y - r, x2 - x1 + 2 * r, 2 * r))]
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
        if key == "develop":
            cx, cy = app.turn_manager.phases[2]._left_button_pos(0)
            w, h = PICTURE_BUTTON_SIZE
            return [("r", pg.Rect(cx - w // 2, cy - h // 2, w, h))]
        if key == "log":
            rect = app._action_box_rect()
            return [("r", rect)] if rect is not None else []
        if key == "ship_card":
            # ShopPhase._draw_menu's ship card (first of the units row).
            shop = app.turn_manager.phases[3]
            fx, fy = shop._frame_origin()
            return [("r", pg.Rect(fx + 30, fy + 295, 130, 235))]
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
        player = self.player
        shop_open = app.players[app.turn] is player and player.attack == 3 and player.subattack < 8
        x, y = RIGHT if shop_open else LEFT
        inner = WIDTH - 2 * PAD

        title = TurnManager._wrap_text(t(step.title), self.title_font, inner - 50)
        text = t(step.text).format(*(t(name) for name in step.names))
        paragraphs = [TurnManager._wrap_text(part, self.font, inner) for part in text.split("\n")]
        line_h = self.font.get_height() + 2
        title_h = len(title) * (self.title_font.get_height() + 2)
        body_h = sum(len(lines) * line_h for lines in paragraphs) + 8 * (len(paragraphs) - 1)
        button_h = 34
        height = PAD + title_h + 10 + body_h + 16 + button_h + PAD
        panel = pg.Rect(x, y, WIDTH, height)
        self._panel = panel

        pg.draw.rect(screen, PANEL_COLOR, panel, border_radius=8)
        pg.draw.rect(screen, (0, 0, 0), panel, 3, border_radius=8)
        count = self.small_font.render("{} / {}".format(self.index + 1, len(self.steps)), True, (120, 110, 90))
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

        # Next (a page to read), Skip (a step on the board), Play on (the
        # last one); and End tutorial for the rest.
        last = self.index == len(self.steps) - 1
        label = t("Play on") if last else t("Next") if step.done is None else t("Skip")
        color = (150, 245, 150) if step.done is None else (215, 215, 215)
        next_w = max(96, self.font.size(label)[0] + 24)
        next_rect = pg.Rect(panel.right - PAD - next_w, panel.bottom - PAD - button_h, next_w, button_h)
        end_rect = None
        if not last:
            end_label = t("End tutorial")
            end_rect = pg.Rect(x + PAD, next_rect.y, self.small_font.size(end_label)[0] + 20, button_h)
        self._buttons = {"next": next_rect}
        mouse = app.io.mouse_position
        self._button(next_rect, label, color, self.font, mouse)
        if end_rect is not None:
            self._buttons["end"] = end_rect
            self._button(end_rect, end_label, (235, 225, 200), self.small_font, mouse)
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
