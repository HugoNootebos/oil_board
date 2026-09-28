"""
The computer player.

A player with `is_bot` set doesn't get mouse input: on their turn,
TurnManager.update hands control to BotController.update, which still lets
the current phase draw itself (with all clicks withheld) and then makes one
decision at a time, with a short pause in between so people can follow
along (and a status line saying what it's doing). It works through the same
phase methods the buttons use (AttackPhase.roll_attack, ShopPhase.place_unit,
TurnManager.end_phase, ...), so the rules stay in phases.py.

The one moment a bot's turn waits on someone else is a human defender
picking their tanks / defence dice; that phase screen then runs normally.
The other way round, a bot that's attacked picks its defending tanks in
defence_tanks() and always rolls every defence die, and an event's pick
for a bot during someone else's turn goes through pick_country().

Everything is valued in troops:
  - resources by need (_weights): food counts fully while the army is at
    what food can carry -- every troop beyond the food in stock starves at
    the turn start --, a stockpile of oil hardly at all;
  - a country by what it yields, its continent and cards, and a player it
    would finish off (_target_value, _hold_value);
  - an attack by its expected value, from exact odds of winning, survivors
    and kills, looking one conquest ahead (battle, _attack_ev);
  - a country's troops by what they can attack minus the chance a
    neighbour takes it before the bot's next turn (_danger,
    _position_value).

The strategy, per phase:
  - reinforce: trade a card set when it's worth it, for whatever helps
    most; place troops where they add the most, to an attack or a border;
    buy whatever is worth the most for its price (tanks, forts, ships,
    planes, bridges, rails, nukes);
  - attack: share out troops by rail or air if that pays, then keep making
    the attack worth the most, hunting down a player it can finish off,
    calling a fight off once it's no longer worth it, and splitting the
    troops after a conquest where they're worth the most;
  - move: develop a safe country if it pays, share out troops by rail or
    air, make the one move worth the most, and place any owed pagoda/torii.

How far it looks and how sure it plays depends on its level (LEVELS:
easy/normal/hard) and personality (PERSONALITIES).
"""

import itertools
import math
import random
from contextlib import contextmanager
from functools import lru_cache

import pygame as pg

from board import CONTINENTS
from models import CardMenu
from player_colors import light_tint
from phases import CONTINENT_CARD_BONUS

# Pauses (ms) so a bot's turn can be followed on screen.
STEP_MS = 400      # between actions
DICE_MS = 900      # how long a roll stays visible before it's resolved
NOTICE_MS = 2500   # a message on a bot's turn closes by itself after this
FAST_BOTS = 0.3    # all of these, with "Fast bots" on in the settings menu

# What a bot weighs its decisions with. Its difficulty level (a player's
# `bot_level`) picks one of LEVELS, and its personality (`bot_personality`)
# shifts a few of those values (see BotController.params). bot_selfplay.py
# can pit levels and tweaks against each other to tune these.
BASE = {
    "attack_min_p": 0.65,     # start an attack only with at least this chance
    "retreat_p": 0.25,        # call a running attack off below this chance
    # Troops that will starve at the next turn start anyway cost nothing
    # to lose: attacks made with them only need this chance.
    "free_attack_min_p": 0.4,
    "kill_value": 0.5,        # an enemy player's troop killed, in our troops
    "leader_bias": 8.0,       # extra value for hitting whoever leads, per share of the lead
    "enemy_aggression": 0.8,  # how likely a neighbour makes an attack that would work
    "next_turn_weight": 0.5,  # attacks a move sets up for next turn, vs this turn's
    "reposition_min_gain": 1.0,    # a move must be worth this much
    "redistribute_min_gain": 2.0,  # a rail/air redistribution too (it costs 1 oil)
    "asset_turns": 3,         # turns a tank, ship, plane or rails are counted for
    "fort_turns": 4,          # turns a fort or bridge is counted for
    "price_factor": 1.0,      # how dear the bot holds its resources when buying
    "follow_discount": 0.7,   # weight of what the survivors can take next
    "hunt_min_p": 0.3,        # go for an elimination this likely (cards and all)
    "horizon": 3,             # turns a conquered country's income is counted for
    "develop_horizon": 4,     # turns a development is expected to pay out
    "hold_weak_sets": True,   # keep a card set worth less than 10 unless it's needed
    "noise": 0.0,             # how much its choices are off, at random (0: never)
}
LEVELS = {
    "hard": dict(BASE),
    # Often picks a lesser option, hardly looks past the next conquest,
    # underestimates threats, never shuffles troops by rail or air and
    # holds on to its resources.
    "normal": dict(BASE, noise=0.4, follow_discount=0.3, enemy_aggression=0.6, hunt_min_p=0.5,
                   reposition_min_gain=2.0, redistribute_min_gain=99.0, price_factor=1.3),
    # Mostly picks at random among what looks good, only attacks sure
    # things, barely sees threats coming, never plans ahead, never hunts
    # anyone down and rarely buys anything.
    "easy": dict(BASE, noise=0.8, attack_min_p=0.75, free_attack_min_p=0.6, kill_value=0.2,
                 enemy_aggression=0.3, follow_discount=0.0, hunt_min_p=1.1, hold_weak_sets=False,
                 price_factor=2.0, reposition_min_gain=4.0, redistribute_min_gain=99.0),
}
DEFAULT_LEVEL = "normal"

# Shifts on top of the level, so bots of one level still play differently.
PERSONALITIES = {
    "balanced": {},
    "aggressive": {"attack_min_p": -0.1, "kill_value": 0.3, "enemy_aggression": -0.2, "follow_discount": 0.1},
    "builder": {"develop_horizon": 2, "horizon": 1, "price_factor": -0.2},
    "turtle": {"attack_min_p": 0.1, "enemy_aggression": 0.2, "fort_turns": 2},
}
DEFAULT_PERSONALITY = "balanced"

CONTINENT_OF = {name: continent for continent, members in CONTINENTS.items() for name in members}

RESOURCES = ("food", "wood", "steel", "oil", "nuclear")
TRADE_MULT = {reward: mult for _, reward, mult in CardMenu.TRADE_OPTIONS}
CARD_VALUE = 3      # a card, in troops: a third of a set, which buys ~15
TANK_STEEL = 20
NUKE_NUCLEAR = 5


# --- combat odds ---------------------------------------------------------

@lru_cache(maxsize=None)
def _round_outcomes(na, nd, a_all, a_high, d_all, d_high):
    """((attacker losses, defender losses, probability), ...) for one roll
    of na attack dice against nd defence dice. a_all/d_all are added to
    every die, a_high/d_high to the highest one (tanks) -- the same
    arithmetic as AttackPhase._apply_combat_results."""
    counts = {}
    for att in itertools.product(range(1, 7), repeat=na):
        A = [x + a_all for x in sorted(att)]
        A[-1] += a_high
        for de in itertools.product(range(1, 7), repeat=nd):
            D = [x + d_all for x in sorted(de)]
            D[-1] += d_high
            n = min(na, nd)
            lost = sum(A[-1 - i] <= D[-1 - i] for i in range(n))
            counts[(lost, n - lost)] = counts.get((lost, n - lost), 0) + 1
    total = 6 ** (na + nd)
    return tuple((al, dl, c / total) for (al, dl), c in counts.items())


@lru_cache(maxsize=None)
def battle(attackers, defenders, mods=(0, 0, 0, 0)):
    """How an attack by `attackers` rolling troops (up to 3 dice a roll) on
    `defenders` (up to 2 dice) ends if it's kept up to the end:
    (chance the defenders are wiped out, attackers left on average --
    counting 0 when they lose --, defenders killed on average)."""
    if defenders <= 0:
        return 1.0, float(attackers), 0.0
    if attackers <= 0:
        return 0.0, 0.0, 0.0
    attackers, defenders = min(attackers, 60), min(defenders, 60)
    win = survivors = killed = 0.0
    for al, dl, p in _round_outcomes(min(attackers, 3), min(defenders, 2), *mods):
        w, s, k = battle(attackers - al, defenders - dl, mods)
        win += p * w
        survivors += p * s
        killed += p * (dl + k)
    return win, survivors, killed


def conquer_probability(attackers, defenders, mods=(0, 0, 0, 0)):
    """Chance that `attackers` rolling troops wipe out `defenders` if the
    attack is kept up to the end."""
    return battle(attackers, defenders, mods)[0]


def bot_params(player):
    """`player`'s tunables: their level's (LEVELS), shifted by their
    personality (PERSONALITIES)."""
    level = getattr(player, "bot_level", DEFAULT_LEVEL)
    personality = getattr(player, "bot_personality", DEFAULT_PERSONALITY)
    key = (level, personality)
    if key not in _PARAMS:
        params = dict(LEVELS.get(level, LEVELS[DEFAULT_LEVEL]))
        for name, shift in PERSONALITIES.get(personality, {}).items():
            params[name] = max(0, params[name] + shift)
        _PARAMS[key] = params
    return _PARAMS[key]


_PARAMS = {}


class BotController:

    def __init__(self, manager):
        self.manager = manager
        # Headless bot-vs-bot games: no pauses at all.
        self.fast = False
        self._next_at = 0
        self._last_state = None
        self._turn_key = None
        self._done = set()     # things already dealt with this turn
        self._failed = set()   # attacks (from, to) that didn't start or were called off
        # What the bot is doing, shown at the bottom of the screen during
        # its turn (see _say).
        self.status = ""
        # Worked-out facts about the board, valid for one decision (the
        # board changes with every action).
        self._cache = {}
        self._acting = None
        # For the random slips of the lower levels (see _jitter); its own,
        # so it doesn't disturb the game's dice.
        self.rng = random.Random(0)

    def _say(self, text):
        """What the bot is doing now, for the status line."""
        self.status = text

    def _draw_status(self):
        """The bot's status line: a box at the bottom middle of the screen,
        in the player's colour."""
        if self.fast or not self.status:
            return
        engine = self.engine
        view, player = engine.view, engine.players[engine.turn]
        text = engine.font.render("{}: {}".format(player.name, self.status), True, (0, 0, 0))
        w, h = text.get_width() + 24, text.get_height() + 12
        rect = pg.Rect(view.WIDTH // 2 - w // 2, view.HEIGHT - h - 14, w, h)
        pg.draw.rect(view.screen, light_tint(player.color), rect)
        pg.draw.rect(view.screen, (0, 0, 0), rect, 2)
        view.screen.blit(text, (rect.x + 12, rect.y + 6))

    def _jitter(self, score):
        """`score` nudged up or down at random by the level's noise (lower
        levels sometimes prefer a lesser option); unchanged at noise 0."""
        noise = self.params["noise"]
        return score * math.exp(noise * self.rng.gauss(0, 1)) if noise else score

    def _cached(self, key, compute):
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]

    @property
    def engine(self):
        return self.manager.engine

    @property
    def player(self):
        """Whose decision it is: the current player, or whoever _acting_as
        says."""
        return self._acting or self.engine.players[self.engine.turn]

    @contextmanager
    def _acting_as(self, player):
        """Decide for `player`, who may not be the current player (e.g. an
        event's pick during someone else's turn)."""
        self._acting, self._cache = player, {}
        try:
            yield
        finally:
            self._acting, self._cache = None, {}

    def _pace(self, ms):
        if self.fast:
            return 0
        return int(ms * FAST_BOTS) if self.engine.settings.get("fast_bots") else ms

    @property
    def notice_ms(self):
        return self._pace(NOTICE_MS)

    @property
    def dice_ms(self):
        return self._pace(DICE_MS)

    @property
    def params(self):
        """The deciding bot's tunables: its level's, shifted by its
        personality."""
        return bot_params(self.player)

    # --- decisions on someone else's turn ------------------------------------

    def defence_tanks(self, country):
        """How many of its tanks the bot owning `country` uses to defend it
        against an attack (1 oil each)."""
        return min(country.tanks, country.owner.oil)

    def pick_country(self, player, countries, event=None):
        """The country `player` (a bot) picks from `countries` when `event`
        makes them pick one -- by what the pick is for (see
        Event.bot_pick_goal)."""
        goal = event.bot_pick_goal() if event is not None else None
        with self._acting_as(player):
            own = [c for c in countries if c.owner is player]
            if goal == "strike":
                others = [c for c in countries if c.owner is not player]
                if others:
                    return max(others, key=lambda c: (self._nuke_value(c), c.units))
                return min(countries, key=lambda c: (self._hold_value(c), c.units))
            if goal == "lose" and own:
                return min(own, key=lambda c: (self._hold_value(c), c.units))
            if goal == "plane" and own:
                return max(own, key=lambda c: (self._plane_value(c), c.units))
            if own:
                return max(own, key=lambda c: (self._hold_value(c), c.units))
            return max(countries, key=lambda c: (self._target_value(c), c.units))

    # --- per-frame driver --------------------------------------------------

    def update(self):
        engine, manager, player = self.engine, self.manager, self.player
        key = (manager.turn_num, engine.turn)
        if key != self._turn_key:
            self._turn_key = key
            self._done = set()
            self._failed = set()
            personality = getattr(player, "bot_personality", DEFAULT_PERSONALITY)
            self._say("{} bot{}, thinking".format(
                getattr(player, "bot_level", DEFAULT_LEVEL),
                "" if personality == DEFAULT_PERSONALITY else ", " + personality))

        phase = manager.phases.get(player.attack)
        if self._human_defending() or self._human_picking() or player.attack == 6:
            # Their tank/dice choice or event pick, with the mouse; an
            # event's mouse attack (attack 6) runs itself.
            phase.update()
            self._draw_status()
            return

        # Draw the phase as usual, but it gets no clicks: the bot plays.
        io = engine.io
        clicks = io.left_pressed, io.right_clicked
        io.left_pressed, io.right_clicked = 0, False
        if phase is not None and not manager.must_trade(player):
            phase.update()
        io.left_pressed, io.right_clicked = clicks

        if self.player is not player:
            return  # the phase ended the turn (e.g. nothing left to feed)
        self._draw_status()
        if not self._ready(player):
            return
        self._act(player)
        self._next_at = pg.time.get_ticks() + self._pace(STEP_MS)

    def _ready(self, player):
        """Pace the bot: a pause after every action, and a longer one while
        freshly rolled dice are on screen."""
        if self.fast:
            return True
        now = pg.time.get_ticks()
        state = (player.attack, player.subattack)
        if state != self._last_state:
            self._last_state = state
            wait = self.dice_ms if state == (1, 4) else self._pace(STEP_MS)
            self._next_at = max(self._next_at, now + wait)
        return now >= self._next_at

    def _human_defending(self):
        """A human's country is under attack and it's their pick: the
        tanks panel, or which defence dice to throw."""
        player = self.player
        attack = self.manager.phases[1]
        if player.attack != 1 or player.subattack not in (3, 8) or attack.defence_country is None:
            return False
        owner = self.engine.countries[attack.defence_country].owner
        if owner is self.engine.default_player or owner.is_bot:
            return False
        return player.subattack == 8 or len(attack.defence_dice) > 1

    def _human_picking(self):
        """An event has a human pick a country during the bot's turn (e.g.
        Verkeerde knop's Noord-Korea owner choosing where the nuke goes)."""
        chooser = self.manager.phases[5].chooser
        return self.player.attack == 5 and chooser is not None and not chooser.is_bot

    def _act(self, player):
        self._cache = {}
        if self.manager.must_trade(player):
            self._trade(forced=True)
            return
        handler = {
            0: self._reinforce,
            1: self._attack,
            2: self._move,
            3: lambda: self.manager.close_shop(),  # e.g. a save made in the shop
            4: self._recruit,
            5: self._event_pick,
        }.get(player.attack)
        if handler is not None:
            handler()

    # --- board helpers -------------------------------------------------------

    def _links(self, name):
        """{neighbour: "land" or "sea"} (land wins if both exist)."""
        def adjacency():
            links = {n: {} for n in self.engine.countries}
            for c in self.engine.connections:
                a, b = tuple(c.connection)
                for x, y in ((a, b), (b, a)):
                    if links[x].get(y) != "land":
                        links[x][y] = c.kind
            return links
        return self._cached("links", adjacency)[name]

    def _owned(self, player=None):
        player = player or self.player
        return [c for c in self.engine.countries.values() if c.owner is player]

    def _is_real(self, player):
        return player is not self.engine.default_player

    def _frontier(self, name):
        """Whether `name` borders anything the bot doesn't own."""
        return any(self.engine.countries[o].owner is not self.player for o in self._links(name))

    def _combat_mods(self, from_c, target, active_tanks):
        engine, event = self.engine, self.manager.current_event
        a_all, d_all = 0, target.fort_lvl
        if event is not None:
            a_all += event.attack_bonus(engine, from_c) - event.dice_penalty(engine, self.player)
            d_all -= event.dice_penalty(engine, target.owner)
        d_high = 0
        if self._is_real(target.owner):
            d_high = self.manager.defending_tanks.get(
                target.name, min(target.tanks, target.owner.oil))
        return int(a_all), int(active_tanks), int(d_all), int(d_high)

    def _win_probability(self, from_c, target, attackers=None, active_tanks=None):
        event = self.manager.current_event
        if event is not None and from_c.units > 1 and event.free_claim_allowed(self.engine, target):
            return 1.0
        if attackers is None:
            attackers = from_c.units - 1
        if active_tanks is None:
            active_tanks = min(from_c.tanks, self.player.oil)
        mods = self._combat_mods(from_c, target, active_tanks)
        return conquer_probability(attackers, target.units, mods)

    # --- economy -------------------------------------------------------------
    # Food is what caps an army: at the start of a turn every troop beyond
    # the food in stock starves (that turn's harvest only comes in after),
    # so over time an army can't outgrow its food income. Everything below
    # is valued in troops.

    def _economy(self, player=None):
        """Where `player` stands. units: troops on the board plus any still
        to be placed this turn; food: the stock that has to feed them all
        at their next turn start; starving: how many of them that stock
        can't feed; *_income: what their countries yield a turn;
        reinforce: the troops their next turn brings."""
        player = player or self.player

        def compute():
            manager = self.manager
            production = self.engine.production(player)
            owned = self._owned(player)
            on_board = sum(c.units for c in owned)
            pending = 0
            if player is self.engine.players[self.engine.turn]:
                if player.attack == 0 and player.subattack in (1, 2):
                    pending += manager.reinforcements + manager.pending_troops
                elif player.attack == 4:
                    pending += manager.phases[4].pool
            units = on_board + pending
            economy = {r + "_income": production[r] for r in RESOURCES}
            economy["food_income"] = production["food"] + on_board  # production() is net of upkeep
            economy.update(
                units=units,
                food=player.food,
                starving=max(0, units - player.food),
                reinforce=production["helmets"] // 3 + 3,
                tanks=sum(c.tanks for c in owned),
                planes=sum(c.planes for c in owned),
            )
            return economy
        return self._cached(("economy", player.name), compute)

    def _weights(self):
        """What one unit of each resource is worth to the bot now, in troops
        -- as income per turn, or in stock. Food counts for a whole troop
        while the army is at or over what food can carry, much less when
        there's plenty; oil only runs tanks, planes and rails, so a big
        stock of it is worth next to nothing; helmets (reinforcements) only
        help while the troops they bring can be fed."""
        def compute():
            e = self._economy()
            army = e["units"] + e["reinforce"]
            cover = (e["food"] + 2 * e["food_income"]) / max(2 * army, 1)
            food = 1.0 if cover <= 1 else max(0.25, 1.0 - 0.5 * (cover - 1))
            oil_use = 1 + e["tanks"] + e["planes"]
            oil_turns = (self.player.oil + 2 * e["oil_income"]) / oil_use
            oil = 0.4 if oil_turns <= 4 else max(0.03, 1.6 / oil_turns)
            return {
                "food": food, "wood": 0.3, "steel": 0.4, "oil": oil, "nuclear": 0.6,
                # 3 helmets bring 1 troop a turn.
                "troops": 0.33 if food < 0.6 else 0.15,
            }
        return self._cached("weights", compute)

    def _income_value(self, country):
        """What `country` yields a turn, in troops."""
        w = self._weights()
        mult = 2 if country.developed else 1
        if country.radioactive:
            # Nothing but helmets until it heals.
            mult *= max(0, self.params["horizon"] - country.radioactive) / self.params["horizon"]
        return w["troops"] * country.troops + mult * sum(w[r] * getattr(country, r) for r in RESOURCES)

    def _loot_value(self, loser):
        """What eliminating `loser` hands over: their wood, steel, nuclear,
        oil and cards."""
        w = self._weights()
        value = sum(w[r] * getattr(loser, r) for r in ("wood", "steel", "nuclear", "oil")) \
            + CARD_VALUE * len(loser.cards)
        event = self.manager.current_event
        if event is not None:
            value += sum(w[r] * n for r, n in event.bot_extra_loot(self.engine, loser).items())
        return value

    def _target_value(self, target):
        """What taking `target` is worth, in troops."""
        engine, manager, player = self.engine, self.manager, self.player
        value = 1.0 + self.params["horizon"] * self._income_value(target)
        if target.airport:
            value += 1.0
        continent = CONTINENT_OF.get(target.name)
        if continent is not None:
            bonus = CONTINENT_CARD_BONUS.get(continent, 0)
            members = CONTINENTS[continent]
            others = [engine.countries[n] for n in members if n != target.name]
            if all(c.owner is player for c in others):
                value += 3 + CARD_VALUE * self.params["horizon"] * bonus
            elif self._is_real(target.owner) and all(c.owner is target.owner for c in others):
                value += 2 + CARD_VALUE * bonus  # breaks their continent
        event = manager.current_event
        if event is not None:
            value += event.bot_country_value(engine, player, target)
        if self._is_real(target.owner):
            value += self.params["leader_bias"] * self._lead(target.owner)
            value += 0.5 if manager.conquered_enemy_this_turn else CARD_VALUE  # the turn's card
            left = sum(1 for c in engine.countries.values() if c.owner is target.owner)
            if left == 1:
                value += 6 + self._loot_value(target.owner)  # eliminates them
            elif target.owner in self._hunt():
                # A step towards finishing them off this turn.
                value += (6 + self._loot_value(target.owner)) * self._hunt()[target.owner] / left
        return value

    def _lead(self, player):
        """How far `player` is ahead of an even share of all the players'
        strength (troops, plus 3 a country): negative when behind."""
        def compute():
            strength = {}
            for c in self.engine.countries.values():
                if self._is_real(c.owner):
                    strength[c.owner] = strength.get(c.owner, 0) + c.units + 3
            total = sum(strength.values())
            return {p: s / total - 1 / len(strength) for p, s in strength.items()} if total else {}
        return self._cached("lead", compute).get(player, 0.0)

    def _hunt(self):
        """{player: chance}: other players the bot can likely wipe out this
        turn -- a few countries, each within reach of one of our stacks."""
        def compute():
            engine, player = self.engine, self.player
            hunted = {}
            for other in engine.players:
                if other is player or other.eliminated:
                    continue
                theirs = self._owned(other)
                if not theirs or len(theirs) > 3:
                    continue
                chance = 1.0
                for country in theirs:
                    best = 0.0
                    for name, kind in self._links(country.name).items():
                        own = engine.countries[name]
                        if own.owner is player and own.units > 1 and self._can_reach(own, kind):
                            best = max(best, self._win_probability(own, country))
                    chance *= best
                if chance >= self.params["hunt_min_p"]:
                    hunted[other] = chance
            return hunted
        return self._cached("hunt", compute)

    def _attack_ev(self, from_c, target, attackers, active_tanks=None, depth=2, seen=()):
        """What attacking `target` from `from_c` with `attackers` rolling
        troops is worth on average, in troops: the target's value times the
        chance of taking it, plus enemy troops killed, minus our troops lost
        (troops that starve anyway cost nothing) -- and, `depth` conquests
        deep, part of the best the survivors can then take from there."""
        if attackers < 1:
            return float("-inf")
        key = ("ev", from_c.name, target.name, attackers, active_tanks, depth, seen)

        def compute():
            engine, player, event = self.engine, self.player, self.manager.current_event
            if event is not None and event.free_claim_allowed(engine, target):
                chance, left, killed = 1.0, float(attackers), 0.0
            else:
                tanks = min(from_c.tanks, player.oil) if active_tanks is None else active_tanks
                chance, left, killed = battle(attackers, target.units, self._combat_mods(from_c, target, tanks))
            starving = self._economy()["starving"]
            troop_cost = 1 - min(1.0, starving / attackers)
            kill_value = self.params["kill_value"] if self._is_real(target.owner) else 0
            ev = chance * self._target_value(target) + kill_value * killed - troop_cost * (attackers - left)
            if depth > 1 and chance > 0.05:
                # The survivors move in (one stays behind) and go on.
                onward = int(left / chance) - 1
                seen_now = seen + (from_c.name, target.name)
                best = 0.0
                for name, kind in self._links(target.name).items():
                    nxt = engine.countries[name]
                    if kind != "land" or nxt.owner is player or name in seen_now:
                        continue
                    if event is not None and not event.can_attack_target(engine, nxt):
                        continue
                    best = max(best, self._attack_ev(target, nxt, onward, active_tanks, depth - 1, seen_now))
                ev += chance * self.params["follow_discount"] * best
            return ev
        return self._cached(key, compute)

    def _can_reach(self, from_c, kind):
        """Whether an attack from from_c over a `kind` link can be made."""
        return kind == "land" or from_c.ships > 0 or (from_c.planes > 0 and self.player.oil >= 1)

    def _targets_from(self, from_c, ships=None, planes=None):
        """[(target, kind)]: what an attack from `from_c` can go for -- over
        sea only with a ship there, or a plane and oil to fly it (`ships`/
        `planes` pretend a different number is there)."""
        ships = from_c.ships if ships is None else ships
        planes = from_c.planes if planes is None else planes

        def compute():
            engine, player = self.engine, self.player
            event = self.manager.current_event
            if event is not None and not event.can_attack_from(engine, from_c):
                return []
            targets = []
            for other, kind in self._links(from_c.name).items():
                target = engine.countries[other]
                if target.owner is player:
                    continue
                if kind == "sea" and not (ships > 0 or (planes > 0 and player.oil >= 1)):
                    continue
                if event is not None and not event.can_attack_target(engine, target):
                    continue
                if kind == "sea" and event is not None and event.bot_sea_attack_loss(engine) > 0.2:
                    continue  # e.g. pirates: not worth a third of the army
                targets.append((target, kind))
            return targets
        return self._cached(("targets", from_c.name, ships, planes), compute)

    def _attack_options(self, extra=None):
        """(from, to, over_land) for every attack the bot could start now.
        `extra` ({name: troops}) pretends some troops were added first."""
        options = []
        for from_c in self._owned():
            if from_c.units + (extra or {}).get(from_c.name, 0) < 2:
                continue
            for target, kind in self._targets_from(from_c):
                options.append((from_c, target, kind == "land"))
        return options

    # --- defence and positioning ---------------------------------------------

    def _enemy_extra(self, owner):
        """Troops another player can add to one spot before attacking from
        it: half their next reinforcements, plus a card set if they hold
        three cards."""
        def compute():
            extra = (self.engine.production(owner)["helmets"] // 3 + 3) // 2
            if len(owner.cards) >= 3:
                extra += 6
            return extra
        return self._cached(("enemy_extra", owner.name), compute)

    def _danger(self, country, units=None, fort=None, tanks=None):
        """Chance another player takes `country` (with `units` troops, a
        `fort` level and `tanks`) before our next turn: the strongest attack
        a neighbour can make on it -- over sea only with a ship, or a plane
        and oil -- with what they can add there first, their tanks, and our
        fort and tanks against it."""
        units = country.units if units is None else units
        fort = country.fort_lvl if fort is None else fort
        tanks = country.tanks if tanks is None else tanks
        if units <= 0:
            return 1.0

        def compute():
            engine, player, event = self.engine, self.player, self.manager.current_event
            worst = 0.0
            for name, kind in self._links(country.name).items():
                enemy = engine.countries[name]
                owner = enemy.owner
                if owner is player or not self._is_real(owner):
                    continue
                if kind == "sea" and not (enemy.ships > 0 or (enemy.planes > 0 and owner.oil > 0)):
                    continue
                if event is not None and not (event.can_attack_from(engine, enemy)
                                              and event.can_attack_target(engine, country)):
                    continue
                a_all, d_all = 0, fort
                if event is not None:
                    a_all += event.attack_bonus(engine, enemy) - event.dice_penalty(engine, owner)
                    d_all -= event.dice_penalty(engine, player)
                mods = (int(a_all), min(enemy.tanks, owner.oil), int(d_all), min(tanks, player.oil))
                attackers = enemy.units - 1 + self._enemy_extra(owner)
                worst = max(worst, battle(attackers, units, mods)[0])
            return worst * self.params["enemy_aggression"]
        return self._cached(("danger", country.name, units, fort, tanks), compute)

    def _hold_value(self, country):
        """What keeping `country` is worth, in troops: what losing it costs."""
        def compute():
            value = 1.0 + self.params["horizon"] * self._income_value(country)
            if country.airport:
                value += 1.0
            continent = CONTINENT_OF.get(country.name)
            if continent is not None and self._holds_continent_of(country.name):
                value += 3 + CARD_VALUE * self.params["horizon"] * CONTINENT_CARD_BONUS.get(continent, 0)
            if len(self._owned()) == 1:
                value += 50  # the last one
            return value
        return self._cached(("hold", country.name), compute)

    def _best_attack_ev(self, country, units, depth=2, ships=None, planes=None, tanks=None):
        """The most an attack from `country` with `units` troops on it is
        worth (0 when nothing is)."""
        active = None if tanks is None else min(tanks, self.player.oil)
        best = 0.0
        for target, _ in self._targets_from(country, ships, planes):
            best = max(best, self._attack_ev(country, target, units - 1, active, depth))
        return best

    def _position_value(self, country, units, attack_weight=1.0, depth=2,
                        ships=None, planes=None, tanks=None, fort=None):
        """How good `units` troops on `country` are: what they can attack
        (times `attack_weight`) minus what could be lost there. `ships`,
        `planes`, `tanks` and `fort` pretend a different number is there."""
        value = -self._hold_value(country) * self._danger(country, units, fort, tanks)
        if units > 1 and attack_weight:
            value += attack_weight * self._best_attack_ev(country, units, depth, ships, planes, tanks)
        return value

    # --- reinforcement -------------------------------------------------------

    def _reinforce(self):
        player, manager = self.player, self.manager
        sub = player.subattack
        if sub in (3, 4):
            self._starve()
            return
        if sub not in (1, 2):
            return  # sub 0: the phase itself works out the income
        if self._trade():
            return
        if player.start_ship:
            self._deploy_boat()
            return
        if manager.reinforcements > 0:
            plan = self._deploy_plan(manager.reinforcements)
            for name, n in plan.items():
                self.engine.countries[name].units += n
            self._say(self._placed(manager.reinforcements, plan))
            manager.reinforcements = 0
            manager.all_reinforcements_deployed = True
            return
        if "shop" not in self._done:
            if not self._shop():
                self._done.add("shop")
            return
        manager.end_phase()

    @staticmethod
    def _placed(troops, plan):
        """E.g. "places 8 troops: Siberië 5, China 3" (the biggest three)."""
        parts = ["{} {}".format(n, k) for n, k in sorted(plan.items(), key=lambda x: -x[1])]
        return "places {} troops: {}".format(troops, ", ".join(parts[:3]) + (", ..." if len(parts) > 3 else ""))

    def _deploy_boat(self):
        """The free boat goes where a ship adds the most (see _shop)."""
        best = max(self._owned(), key=lambda c: (
            self._position_value(c, c.units, ships=c.ships + 1) - self._position_value(c, c.units), c.units))
        self.manager.phases[0].deploy_boat(best)
        self._say("puts its free boat on " + best.name)

    def _starve(self):
        """Starvation: the troops lost come off the stacks that miss them
        least (see _position_value). Only if every country is down to one troop are countries given up,
        the least valuable first -- never a food producer while there's
        another choice."""
        engine, manager, player = self.engine, self.manager, self.player
        phase = manager.phases[0]
        self._say("loses {} troops to hunger".format(phase.starved))
        for _ in range(phase.starved):
            owned = [c for c in self._owned() if c.units > 0]
            if not owned:
                break
            spare = [c for c in owned if c.units > 1]
            if spare:
                victim = min(spare, key=lambda c: self._position_value(c, c.units, 0.5)
                             - self._position_value(c, c.units - 1, 0.5))
            else:
                victim = min(owned, key=lambda c: (c.food > 0, self._income_value(c)))
            victim.units -= 1
        for country in self._owned():
            if country.units == 0:
                phase.abandon(country)
        manager.initial_units = {n: c.units for n, c in engine.countries.items()}
        player.subattack = 1

    def _deploy_plan(self, troops, names=None, base=None, attack_weight=1.0):
        """{country: troops}: troops go, a few at a time, where they add the
        most value per troop -- to an attack worth making (see _attack_ev)
        or to a border that could otherwise be lost (see _danger). `names`
        limits where they can go (default: the borders), `base` gives
        what's there before (default: what's on the board)."""
        engine = self.engine
        names = names or self._frontier_names() or [c.name for c in self._owned()]
        have = dict(base) if base else {n: engine.countries[n].units for n in names}
        plan = {}

        def value(name, units):
            return self._position_value(engine.countries[name], units, attack_weight)

        while troops > 0:
            best = None
            for name in names:
                units = have[name] + plan.get(name, 0)
                now = value(name, units)
                for k in sorted({1, 2, 3, 5, 8, 12, 20, troops}):
                    if k > troops:
                        break
                    gain = self._jitter((value(name, units + k) - now) / k)
                    if best is None or gain > best[0]:
                        best = (gain, name, k)
            gain, name, k = best
            if gain <= 0:
                # Nothing gains from more: the rest join the biggest stack.
                name = max(names, key=lambda n: have[n] + plan.get(n, 0))
                k = troops
            plan[name] = plan.get(name, 0) + k
            troops -= k
        return plan

    def _frontier_names(self):
        return [c.name for c in self._owned() if self._frontier(c.name)]

    # --- cards -----------------------------------------------------------

    def _trade(self, forced=False, need_troops=False):
        """Trade a set of cards if there is one worth trading now, for
        whatever helps most; True if it did. A set worth less than the best
        (10) is kept for later unless the hand is (nearly) full, troops are
        starving, or `need_troops` (e.g. a player to finish off)."""
        player, manager = self.player, self.manager
        if not manager.can_trade():
            return False
        menu = self.engine.card_menu
        menu.player = player
        menu.trade_mode = False
        for card in player.cards:
            card.use = False
        menu.use_cards_automatic()
        base = menu.selected_trade_value()
        if base is None:
            for card in player.cards:
                card.use = False
            return False
        urgent = forced or need_troops or len(player.cards) >= manager.MAX_CARDS \
            or self._economy()["starving"] > 0
        if base < 10 and self.params["hold_weak_sets"] and not urgent:
            for card in player.cards:
                card.use = False
            return False
        menu.trade_cards = [card for card in player.cards if card.use]
        reward = "helmets" if need_troops else self._trade_reward(base)
        amount = int(round(base * TRADE_MULT[reward]))
        menu._execute_trade(reward, amount)
        self._say("trades cards for {} {}".format(amount, "troops" if reward == "helmets" else reward))
        return True

    def _trade_reward(self, base):
        """The card-trade reward (a CardMenu.TRADE_OPTIONS resource) worth
        the most right now for a set worth `base`."""
        player, e, w = self.player, self._economy(), self._weights()
        shop = self.manager.phases[3]
        feedable = max(0, e["food"] - e["units"])
        tank_cost = shop._cost({"steel": TANK_STEEL})["steel"]
        nuke_cost = shop._cost({"nuclear": NUKE_NUCLEAR})["nuclear"]
        oil_for_tank = player.oil + e["oil_income"] > e["tanks"]

        def value(reward, n):
            if reward == "helmets":
                # Troops that can't be fed at the next turn start still
                # fight (and defend) for a round.
                fed = min(n, feedable)
                return fed + 0.5 * (n - fed)
            if reward == "food":
                saved = min(n, e["starving"])
                return saved + 0.3 * w["food"] * (n - saved)
            if reward == "steel":
                tanks = (player.steel + n) // tank_cost - player.steel // tank_cost
                return tanks * (5 if oil_for_tank else 2) + 0.1 * n
            if reward == "nuclear":
                nukes = (player.nuclear + n) // nuke_cost - player.nuclear // nuke_cost
                return nukes * self._nuke_worth() + 0.1 * n
            return w[reward] * n

        return max(TRADE_MULT, key=lambda r: value(r, int(round(base * TRADE_MULT[r]))))

    def _nuke_worth(self):
        """Roughly what one more nuke is worth: half the biggest enemy army
        next to us, dead."""
        engine, player = self.engine, self.player
        stacks = [engine.countries[o].units for c in self._owned() for o in self._links(c.name)
                  if engine.countries[o].owner is not player and self._is_real(engine.countries[o].owner)]
        return max(stacks, default=0) // 2

    def _recruit(self):
        """Troops from a card trade outside the reinforcement phase."""
        phase = self.manager.phases[4]
        plan = self._deploy_plan(phase.pool)
        for name, n in plan.items():
            self.engine.countries[name].units += n
        self._say(self._placed(phase.pool, plan))
        phase.pool = 0
        self.manager.end_trade_recruit()

    # --- shop ----------------------------------------------------------------
    # Everything the shop sells is scored the same way: what it adds to the
    # position (see _position_value) over the turns it lasts, against its
    # price in troops -- where a stockpile is cheap to spend (_stock_weight).

    def _stock_weight(self, resource):
        """What one unit of `resource` in stock costs to spend: its weight,
        falling off once more than a couple of purchases' worth is piled up."""
        typical = {"wood": 15, "steel": 20, "nuclear": 5, "oil": 10, "food": 20}[resource]
        return self._weights()[resource] * min(1.0, 2 * typical / max(getattr(self.player, resource), 1))

    def _price(self, cost):
        return sum(self._stock_weight(r) * n for r, n in cost.items())

    def _affordable(self, cost):
        return all(getattr(self.player, r) >= n for r, n in cost.items())

    @contextmanager
    def _what_if(self, *changes):
        """Look at the board with some values changed for a moment:
        `changes` are (object, attribute, value)."""
        saved = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in changes]
        for obj, attr, value in changes:
            setattr(obj, attr, value)
        self._cache = {}
        try:
            yield
        finally:
            for obj, attr, value in reversed(saved):
                setattr(obj, attr, value)
            self._cache = {}

    def _local_value(self, names):
        engine = self.engine
        return sum(self._position_value(engine.countries[n], engine.countries[n].units)
                   for n in names if engine.countries[n].owner is self.player)

    def _connection(self, a, b, kind):
        return next((c for c in self.engine.connections if {a, b} == set(c.connection) and c.kind == kind), None)

    def _shop(self):
        """Buy the one thing worth the most over its price (the shop is only
        used from the reinforcement phase, where everything can be bought).
        True if it bought something."""
        best = None
        for value, cost, action, text in self._shop_options():
            net = self._jitter(value - self.params["price_factor"] * self._price(cost))
            if net > 0 and (best is None or net > best[0]):
                best = (net, action, text)
        if best is None:
            return False
        best[1]()
        self._say(best[2])
        return True

    def _shop_options(self):
        """[(value, cost, buy, what)] for each purchase worth a look."""
        engine, player, p = self.engine, self.player, self.params
        shop = self.manager.phases[3]
        e = self._economy()
        frontier = [engine.countries[n] for n in self._frontier_names()]
        stacks = sorted(frontier, key=lambda c: -c.units)[:6]
        options = []

        def gain(country, **pretend):
            return self._position_value(country, country.units, **pretend) \
                - self._position_value(country, country.units)

        # Tanks, on the stacks that attack or hold a border.
        cost = shop._cost({"steel": TANK_STEEL})
        if self._affordable(cost):
            fuel = 1.0 if player.oil + 2 * e["oil_income"] > e["tanks"] else 0.3
            for c in stacks:
                options.append((fuel * p["asset_turns"] * gain(c, tanks=c.tanks + 1), cost,
                                lambda c=c, cost=cost: shop.place_unit("tanks", cost, c.name),
                                "buys a tank for " + c.name))

        # Forts, where a border could be lost.
        for c in frontier:
            cost = {"wood": shop.fort_cost(c)}
            if c.fort_lvl < 3 and self._affordable(cost) and self._danger(c) > 0.05:
                options.append((p["fort_turns"] * gain(c, fort=c.fort_lvl + 1), cost,
                                lambda c=c: shop.place_fort(c.name),
                                "builds a level {} fort on {}".format(c.fort_lvl + 1, c.name)))

        # A ship or a plane where it opens up attacks over sea; a plane also
        # makes the country an airport (troops move by air between them).
        ship_cost, plane_cost = shop._cost({"wood": 15}), shop._cost({"steel": 10})
        for c in stacks:
            if c.units < 2:
                continue
            if self._affordable(ship_cost) and not c.ships:
                options.append((p["asset_turns"] * gain(c, ships=1), ship_cost,
                                lambda c=c: shop.place_unit("ships", ship_cost, c.name),
                                "buys a ship for " + c.name))
            if self._affordable(plane_cost):
                options.append((self._plane_value(c), plane_cost,
                                lambda c=c: shop.place_unit("planes", plane_cost, c.name),
                                "buys a plane for " + c.name))

        # A bridge, where a stack faces the sea without a ship or plane.
        cost = shop._cost({"wood": 10})
        if self._affordable(cost):
            for c in stacks:
                if c.units < 3 or c.ships or c.planes:
                    continue
                for other, kind in self._links(c.name).items():
                    if kind != "sea" or engine.countries[other].owner is player:
                        continue
                    before = self._local_value([c.name])
                    with self._what_if((self._connection(c.name, other, "sea"), "kind", "land")):
                        after = self._local_value([c.name])
                    options.append((p["fort_turns"] * (after - before), cost,
                                    lambda c=c, other=other: shop.build_bridge(c.name, other),
                                    "builds a bridge from {} to {}".format(c.name, other)))

        # Rails, linking a stack with spare troops to a border.
        cost = shop._cost({"wood": 2, "steel": 1})
        if self._affordable(cost) and player.oil >= 2:
            links = []
            for c in engine.connections:
                a, b = (engine.countries[n] for n in c.connection)
                if c.kind == "land" and not c.rails and a.owner is player and b.owner is player \
                        and (self._frontier(a.name) or self._frontier(b.name)):
                    links.append((max(a.units, b.units), c, a.name, b.name))
            if links:
                phase = self.manager.phases[1]
                before = max(0.0, (self._best_redistribution(phase) or (0,))[0])
                for _, c, a, b in sorted(links, key=lambda x: -x[0])[:5]:
                    with self._what_if((c, "rails", True)):
                        after = max(0.0, (self._best_redistribution(phase) or (0,))[0])
                    options.append((p["asset_turns"] * (after - before), cost,
                                    lambda a=a, b=b: shop.build_rails(a, b),
                                    "lays rails from {} to {}".format(a, b)))

        # A nuke.
        cost = shop._cost({"nuclear": NUKE_NUCLEAR})
        if self._affordable(cost):
            for name in shop._nuke_targets():
                target = engine.countries[name]
                if target.units >= 2 or self._is_real(target.owner):
                    options.append((self._nuke_value(target), cost, lambda name=name: self._drop_nuke(name),
                                    "nukes " + name))
        return options

    def _plane_value(self, country):
        """What a plane on `country` adds over the turns it lasts: attacks
        over sea from there, and -- if that makes it a new airport -- moving
        troops by air between the airports."""
        turns = self.params["asset_turns"]
        value = turns * (self._position_value(country, country.units, planes=country.planes + 1)
                         - self._position_value(country, country.units))
        if not country.airport:
            before = self._air_gain()
            with self._what_if((country, "airport", True), (country, "planes", country.planes + 1)):
                value += turns * max(0.0, self._air_gain() - before)
        return value

    def _air_gain(self):
        """What sharing out the troops of the airport network would gain now."""
        best = self._best_redistribution(self.manager.phases[1], kinds=("air",))
        return max(0.0, best[0]) if best else 0.0

    def _nuke_value(self, target):
        """What a nuke on `target` is worth: a player's troops it kills, and
        what halving the garrison (or, if nobody survives, handing it back
        to the mouse) does for our attacks on it and our countries next to
        it -- plus their elimination if it was their last country."""
        engine, player = self.engine, self.player
        half = target.units // 2
        near = [n for n in self._links(target.name) if engine.countries[n].owner is player]
        before = self._local_value(near)
        changes = [(target, "radioactive", target.radioactive + 3), (target, "units", half)]
        if half == 0:
            changes += [(target, "owner", engine.default_player),
                        (target, "units", engine.initial_country_units.get(target.name, 2))]
        with self._what_if(*changes):
            value = self._local_value(near) - before
        if self._is_real(target.owner):
            value += self.params["kill_value"] * (target.units - half)
            if half == 0 and not any(c.owner is target.owner and c is not target for c in engine.countries.values()):
                value += 6 + self._loot_value(target.owner)
        return value

    def _drop_nuke(self, name):
        self.manager.phases[3].drop_nuke(name)
        self.manager.notices.append("{} nuked {}!".format(self.player.name, name))

    # --- attack --------------------------------------------------------------

    def _attack(self):
        player = self.player
        attack = self.manager.phases[1]
        sub = player.subattack
        if sub in (0, 1):
            if "redistribute attack" not in self._done:
                self._done.add("redistribute attack")
                if self._redistribute(attack):
                    return
            self._start_best_attack()
        elif sub == 6:
            player.subattack = 2
        elif sub == 2:
            from_c = self.engine.countries[attack.attack_from]
            target = self.engine.countries[attack.defence_country]
            chance = self._win_probability(from_c, target, active_tanks=attack.active_tanks)
            ev = self._attack_ev(from_c, target, from_c.units - 1, attack.active_tanks)
            if chance < self.params["retreat_p"] * (1 - self._free_share(from_c)) or ev < 0:
                self._say("calls off the attack on " + target.name)
                self._failed.add((from_c.name, target.name))
                attack.attack_from = attack.defence_country = None
                player.subattack = 0
            else:
                attack.roll_attack()
        elif sub == 4:
            attack._apply_combat_results()
            attack.timer = 0
        elif sub == 5:
            self._move_in()
        elif sub == 7:
            attack._cancel_redistribute()

    def _start_best_attack(self):
        player, manager = self.player, self.manager
        attack = manager.phases[1]
        if self._hunt() and self._trade(need_troops=True):
            self._say("trades cards for troops to finish off " + ", ".join(p.name for p in self._hunt()))
            return  # troops to finish someone off; placed first (RecruitPhase)
        best = None
        for from_c, target, land in self._attack_options():
            if (from_c.name, target.name) in self._failed:
                continue
            chance = self._win_probability(from_c, target)
            if chance < self._attack_min_p(from_c):
                continue
            score = self._jitter(self._attack_ev(from_c, target, from_c.units - 1))
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, from_c, target, land)
        if best is None:
            manager.end_phase()
            return
        _, from_c, target, land = best
        self._say("attacks {} from {} ({:.0%})".format(
            target.name, from_c.name, self._win_probability(from_c, target)))
        attack.attack_from = from_c.name
        attack._start_attack(target.name, land)
        if player.subattack == 5:
            return  # claimed for free (VOC deel 2): straight to moving in
        if player.subattack != 2:
            if target.owner is not player:
                self._failed.add((from_c.name, target.name))  # not allowed after all
            attack.attack_from = None
            return
        # Planes only when they're the way across (they cost oil), and
        # tanks -- while oil is short -- only if they make a real difference.
        if self._weights()["oil"] >= 0.2 and self._win_probability(from_c, target, active_tanks=0) >= 0.9:
            attack.active_tanks = 0
        if land or attack.selected_ships > 0:
            attack.selected_planes = 0
        else:
            # Over sea without a ship: one plane (1 oil) carries them.
            attack.selected_planes = 1
            attack.active_tanks = min(attack.active_tanks, max(player.oil - 1 + attack.prepaid_planes, 0))

    def _free_share(self, from_c):
        """How much of an attack from `from_c` is made with troops that
        starve at the next turn start anyway (0..1)."""
        attackers = from_c.units - 1
        return min(1.0, self._economy()["starving"] / attackers) if attackers > 0 else 0.0

    def _attack_min_p(self, from_c):
        """The chance an attack from `from_c` needs: lower the more of it is
        made with troops that would starve anyway."""
        p = self.params
        return p["attack_min_p"] - (p["attack_min_p"] - p["free_attack_min_p"]) * self._free_share(from_c)

    def _move_in(self):
        """After a conquest: split the troops between the old and the new
        country where they're worth the most (see _position_value)."""
        engine = self.engine
        attack = self.manager.phases[1]
        from_c = engine.countries[attack.attack_from]
        target = engine.countries[attack.defence_country]
        total = from_c.units + target.units
        least = attack.conquest_units
        if total <= least:
            moved = total
        else:
            step = max(1, (total - 1 - least) // 8)
            options = set(range(least, total, step)) | {least, total - 1}
            moved = max(options, key=lambda m: (
                self._position_value(target, m) + self._position_value(from_c, total - m), m))
        target.units, from_c.units = moved, total - moved
        self._say("takes {}, {} troops move in".format(target.name, moved))
        attack._finish_conquest(from_c)

    # --- movement ------------------------------------------------------------

    def _move(self):
        engine, player, manager = self.engine, self.player, self.manager
        phase = manager.phases[2]
        if player.subattack != 0:
            player.subattack = 0
            return

        if not player.developed_this_turn and "develop" not in self._done:
            self._done.add("develop")
            country = self._develop_choice(phase)
            if country is not None:
                phase.develop(country)
                self._say("develops " + country.name)
                return

        if not player.repositioned_this_turn and "redistribute" not in self._done:
            # Rails/airports first: once repositioned, no origin can be picked.
            self._done.add("redistribute")
            if self._redistribute(phase):
                return

        if not player.repositioned_this_turn and "reposition" not in self._done:
            self._done.add("reposition")
            if self._reposition(phase):
                return

        for name in sorted(manager.landmarks_owed):
            manager.place_landmark(name)
        manager.end_phase()

    def _develop_choice(self, phase):
        """The country most worth developing, or None. Developing costs one
        turn's yield of the country and (unless its whole continent is
        held) the next income, then doubles it: worth it for a country that
        stays safe for a few turns -- but not if paying the food makes
        troops starve."""
        player, e, w = self.player, self._economy(), self._weights()
        horizon = self.params["develop_horizon"]
        best, best_gain = None, 0
        for c in self._owned():
            cost = phase.develop_cost(c)
            if c.developed or c.radioactive or not sum(cost.values()) or self._danger(c) > 0.3:
                continue
            if any(getattr(player, r) < n for r, n in cost.items()):
                continue
            income = sum(w[r] * getattr(c, r) for r in RESOURCES)
            idle = 0 if self._holds_continent_of(c.name) else 1
            gain = income * (horizon - idle) * (1 - self._danger(c)) - sum(w[r] * n for r, n in cost.items())
            gain -= max(0, e["units"] - (player.food - cost["food"])) - e["starving"]
            if gain > best_gain:
                best, best_gain = c, gain
        return best

    def _holds_continent_of(self, name, player=None):
        player = player or self.player
        continent = CONTINENT_OF.get(name)
        return continent is not None and all(
            self.engine.countries[n].owner is player for n in CONTINENTS[continent])

    def _own_reach(self, origin):
        """The bot's countries reachable from `origin` without leaving its
        own territory (over any link)."""
        engine, player = self.engine, self.player
        seen, todo = {origin}, [origin]
        while todo:
            for other in self._links(todo.pop()):
                if other not in seen and engine.countries[other].owner is player:
                    seen.add(other)
                    todo.append(other)
        return seen

    def _reposition(self, phase):
        """The one move a turn: troops (and their tanks) from where they're
        worth least to where they're worth most (see _position_value), over
        land -- or over sea with a ship or plane going along; or a lone
        plane or ship to where it opens up attacks over sea. True if
        something moved."""
        engine, player = self.engine, self.player
        weight = self.params["next_turn_weight"]
        oil_cost = self._weights()["oil"]

        def value(country, units, ships=None, planes=None):
            return self._position_value(country, units, weight, 1, ships, planes)

        best_gain, best = self.params["reposition_min_gain"], None
        for origin in self._owned():
            spare = origin.units - 1
            if spare <= 0 and not origin.planes:
                continue
            reach = self._own_reach(origin.name) - {origin.name}
            targets = [engine.countries[n] for n in reach if self._frontier(n)]
            if not targets:
                continue
            land = phase._land_flood_fill(origin.name)
            by_sea = phase._sea_flood_fill(origin.name)
            now = value(origin, origin.units)
            planes = (0, 1) if origin.planes and player.oil >= 1 else (0,)
            ships = (0, 1) if origin.ships else (0,)
            for n in sorted({spare, spare // 2, min(spare, 3), 0}):
                for plane in planes:
                    for ship in ships:
                        if (n, plane, ship) == (0, 0, 0) or (ship and not n):
                            continue  # nothing moves / a ship needs a troop aboard
                        loss = now - value(origin, origin.units - n, origin.ships - ship, origin.planes - plane)
                        for target in targets:
                            if ship and target.name not in by_sea:
                                continue
                            if n and target.name not in land and not (ship or plane):
                                continue  # troops can't cross the sea alone
                            gain = self._jitter(
                                value(target, target.units + n, target.ships + ship, target.planes + plane)
                                - value(target, target.units) - loss - plane * oil_cost)
                            if gain > best_gain:
                                best_gain, best = gain, (origin, target, n, ship, plane)
        if best is None:
            return False
        origin, target, n, ship, plane = best
        tanks = origin.tanks if n and 2 * n >= origin.units - 1 else 0
        origin.units -= n
        target.units += n
        origin.tanks -= tanks
        target.tanks += tanks
        origin.ships -= ship
        target.ships += ship
        origin.planes -= plane
        target.planes += plane
        player.oil -= plane
        player.repositioned_this_turn = True
        extra = " with a plane" if plane else " by ship" if ship else ""
        self._say("moves {} troops from {} to {}{}".format(n, origin.name, target.name, extra) if n
                  else "moves a {} from {} to {}".format("plane" if plane else "ship", origin.name, target.name))
        return True

    def _best_redistribution(self, phase, kinds=("rails", "air")):
        """(gain, kind, origin, names, plan) for the rails or airport network
        whose troops would gain the most from being shared out afresh (as
        _deploy_plan would), or None."""
        engine, player = self.engine, self.player
        networks, seen = [], set()
        for country in self._owned() if "rails" in kinds else ():
            if country.name in seen:
                continue
            network = phase._compute_rail_network(country.name, player)
            seen |= network
            if len(network) > 1:
                networks.append(("rails", country.name, network))
        airports = sorted(n for n, c in engine.countries.items() if c.owner is player and c.airport)
        if "air" in kinds and len(airports) > 1 and any(engine.countries[n].planes > 0 for n in airports):
            networks.append(("air", airports[0], set(airports)))
        weight = 1.0 if player.attack in (0, 1) else self.params["next_turn_weight"]

        best = None
        for kind, origin, network in networks:
            names = sorted(network)
            pool = sum(engine.countries[n].units - 1 for n in names)
            if pool <= 0:
                continue
            plan = self._deploy_plan(pool, names, {n: 1 for n in names}, weight)
            gain = sum(self._position_value(engine.countries[n], 1 + plan.get(n, 0), weight)
                       - self._position_value(engine.countries[n], engine.countries[n].units, weight)
                       for n in names)
            if best is None or gain > best[0]:
                best = (gain, kind, origin, names, plan)
        return best

    def _redistribute(self, phase):
        """The rails or airport button: for 1 oil, share out the troops of
        one network (rails, or all airports while a plane stands at one),
        tanks going with the biggest stack -- if that's clearly worth it.
        True if it did."""
        engine, player = self.engine, self.player
        if player.oil < 1:
            return False
        best = self._best_redistribution(phase)
        if best is None or best[0] < self.params["redistribute_min_gain"] + self._weights()["oil"]:
            return False

        _, kind, origin, names, plan = best
        # As with the button: an origin selected, then the redistribute screen.
        if player.attack == 1:
            phase.attack_from = origin
        else:
            phase.origin_country = origin
        player.subattack = 1
        phase._enter_redistribute(set(names), kind)
        tanks = sum(engine.countries[n].tanks for n in names)
        for n in names:
            engine.countries[n].units = 1 + plan.get(n, 0)
            engine.countries[n].tanks = 0
        engine.countries[max(names, key=lambda n: engine.countries[n].units)].tanks = tanks
        phase._finish_redistribute()
        self._say("moves troops around by " + ("rail" if kind == "rails" else "air"))
        if player.attack == 1:
            phase.attack_from = None
        else:
            phase.origin_country = None
        player.subattack = 0
        return True

    # --- event picks -----------------------------------------------------------

    def _event_pick(self):
        engine, player = self.engine, self.player
        phase = self.manager.phases[5]
        if phase.predicate is None:
            return  # the phase bails out on its own
        valid = [c for c in engine.countries.values() if phase.predicate(c)]
        if valid:
            phase.pick(self.pick_country(player, valid, self.manager.current_event))
