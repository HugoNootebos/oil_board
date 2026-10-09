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
    _position_value);
  - an elimination by the chance of pulling it off this turn times its
    loot, against the troops it costs and the danger it leaves the bot in
    (_hunt, _campaign) -- and the bot's own survival by the chance another
    player wipes it out before its next turn (_elimination_risk): while
    that's real, it holds back and builds up.

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

How it plays is set by its tunables (LEVELS) and personality
(PERSONALITIES).
"""

import itertools
import math
import random
from contextlib import contextmanager
from functools import lru_cache

import pygame as pg

from board import CONTINENTS
from lang import t, Msg, Join
from models import CardMenu
from player_colors import light_tint
from phases import CONTINENT_CARD_BONUS

# Pauses (ms) so a bot's turn can be followed on screen.
STEP_MS = 400      # between actions
DICE_MS = 900      # how long a roll stays visible before it's resolved
NOTICE_MS = 2500   # a message on a bot's turn closes by itself after this
FAST_BOTS = 0.3    # all of these, with "Fast bots" on in the settings menu

# What a bot weighs its decisions with. There is one bot (LEVELS["hard"]);
# its personality (`bot_personality`) shifts a few of those values (see
# BotController.params). The tuning tools (bot_selfplay.py, bot_checks.py,
# bot_fork.py, bot_golden.py) add tweaked copies to LEVELS and point a
# player's `bot_level` at one.
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
    "hunt_min_p": 0.3,        # go for an elimination only this likely at least
    "hunt_max_countries": 4,  # ... of a player down to this many countries
    "loot_weight": 1.0,       # how much an eliminated player's loot counts
    # Being wiped out costs the game (this much, in troops) plus all the
    # bot holds; while the chance of it is above survival_risk the bot
    # plays for survival, and its countries count survival_weight x that
    # chance more.
    "survival_value": 40.0,
    "survival_risk": 0.15,
    "survival_weight": 3.0,
    "horizon": 3,             # turns a conquered country's income is counted for
    "develop_horizon": 4,     # turns a development is expected to pay out
    "hold_weak_sets": True,   # keep a card set worth less than 10 unless it's needed
    # How likely a country is to be taken before the bot's next turn (_danger).
    # 0: only the stacks next to it count, over sea only with a ship or plane
    # in place. 1: also chains (an enemy takes a country on the way and
    # strikes from there: half of all losses), sea strikes the enemy can still
    # buy a crossing for, and enemies that have not moved yet.
    "exposure": 1,
    "chain_weight": 0.5,      # a strike out of a country the enemy conquers on the way counts this much
    "chain_depth": 2,         # conquests an enemy chains on the way
    "chain_min_win": 0.25,    # ... each of them at least this likely
    "chain_sea_weight": 0.5,  # a chain whose last hop is over sea counts this much of that
    "chain_buy_weight": 0.4,  # ... and this much per crossing the enemy still has to buy
    "sea_buy_weight": 0.2,    # a sea strike the enemy can buy a crossing for counts this much
    "exposure_scale": 1.0,    # scales enemy_aggression for all of the above
    # 1: the chance of being wiped out (_elimination_risk) comes from the same
    # exposure of every country (all of them have to fall) instead of from
    # neighbours that border every part of the bot's territory -- which missed
    # chains: players down to 3 countries rated safe were wiped out 14% of the
    # time. Needs "exposure". 0: the old model.
    "risk_exposure": 0,
    # What a conquest is worth only counts while it is kept (_target_value),
    # with e the exposure of the country held by conquest_garrison troops.
    # 1: its income counts for the sum of (1-e)^k over the horizon instead of
    # the whole horizon (a country about to be lost yields nothing). 2: the
    # value without the card is multiplied by 1 - retention_weight x e. 0: off.
    # Needs "exposure".
    "retention": 1,
    "retention_weight": 1.0,
    "conquest_garrison": 2,
    # The strike step (_strike_step): at the start of the reinforcement phase,
    # against a player down to hunt_max_countries countries, the cheapest mix
    # of nukes, card sets, a crossing and massing the new troops that makes
    # taking all their countries this turn worth it -- by the measure _hunt
    # uses -- is bought and played before trade, deploy and shop. 0: off.
    # (Saving resources up for it does not pay: holding a stock back cost as
    # much as it gained, a card set cannot wait more than ~2 turns, and a
    # nuke's worth of nuclear is at hand in a third of all turns anyway.)
    "strike": 1,
    "strike_min_net": 1.0,    # worth at least this, after what it costs
    "strike_max_nukes": 3,
    "strike_max_tanks": 0,    # tanks bought for it (2 tanks add ~4 points of chance: not worth it)
    "strike_place": 0,        # 1: also plans that only mass the new troops (no nuke, set or crossing)
    "strike_troop_cost": 0.5, # per new troop taken off the borders
    "strike_filter": 0.15,    # skip players the best case gives less than this chance against
    # A player whose nukes can bring every country of a player to nothing (it takes
    # floor(log2 troops) + 1 nukes per country) does so, up to this many nukes: a
    # sure elimination. 0: off.
    "finish_max": 8,
    "loot_card": 3.0,         # a card in an eliminated player's loot, in troops (measured ~4.2)
    "rival_value": 6.0,       # an elimination's prize on top of the loot: one rival less
    # Endgame (_endgame): the leader, once at most endgame_alive players are left
    # or it holds endgame_lead of all strength, spends: the shop's price factor
    # is multiplied by endgame_price (0: buy anything that is worth something)
    # and weak card sets are traded at once. Only the leader has stock left at
    # the end (a trailer's survival logic already spends everything). 0 / 1.1: off.
    "endgame_alive": 2,
    "endgame_lead": 0.70,
    "endgame_price": 0.0,
    # Conquests after the turn's card (_attack_ev): each costs the exposure it
    # creates -- the troops stranded on it and the card handed to whoever takes
    # it back (extra_gift), and the origin stack left weaker (extra_origin) --
    # times extra_exposure. The card conquest and mouse land stay free (pricing
    # them cut card turns by 13-19 points for nothing). Needs "exposure"; pays
    # only when all bots do it (a lone restrained bot loses ground). 0: off.
    "extra_exposure": 0.0,
    "extra_origin": 1.0,
    "extra_gift": 0.3,
    # Emptying a thin country on purpose (_buffer_run): its troops walk to another
    # country and it goes back to the mouse with its native 1-2 troops, which
    # gives whoever takes it no card. Measured: about worth nothing under the
    # current rules (the mouse garrison is too thin a wall, and what is saved
    # is almost exactly what is lost), so it ships off (0).
    "buffer": 0,
    "buffer_max_units": 2,       # only countries holding at most this many troops
    "buffer_min_exposure": 0.5,  # ... that are probably lost anyway (_danger)
    "buffer_card_value": 4.2,    # what a card is worth, in troops
    "buffer_card_weight": 0.4,   # how much of the card the taker would have earned counts
    "buffer_min_gain": 1.0,      # the gain it has to show
    "buffer_keep": 3,            # the bot keeps at least this many countries
    "buffer_cool": 2,            # rounds the bot leaves an emptied country alone, while it is exposed
    # Ships, tanks, planes and forts are destroyed with their country, which what a
    # country's loss costs (_hold_value) never counted: bots left them next to a big
    # enemy army with one troop on guard. asset_hold: they count at their price in
    # troops (times this) in that loss (_position_value), so troops go to defend
    # them, the shop does not buy them for a country about to fall and the one
    # move a turn can take them out of reach. asset_move: 1 lets that move also
    # take tanks alone, a plane or a ship with one troop to any country of the bot's
    # (not only to a border), and counts the tanks that go with a stack. 0: off.
    # (Measured: they save a quarter of the assets lost to conquest but no gain in
    # wins was shown; they are on because the owner asked for it. See
    # bot_research/README.md, "Assets".)
    "asset_hold": 1.0,
    "asset_move": 1,
    # An attack carries its assets onto the conquered country, where they are lost
    # with it (a ship or plane over sea, the tanks): asset_attack (x asset_hold) takes
    # that expected loss off the attack's value (_attack_ev). asset_carry: 1 brings
    # only the tanks that fight (the oil-paid ones) -- the rest stay and guard the
    # country they came from. 0: off.
    "asset_attack": 1.0,
    "asset_carry": 1,
    # How much its choices are off, at random (0: never); only for A/B tests'
    # noise-matched controls.
    "noise": 0.0,
}
LEVELS = {
    "hard": dict(BASE),
}
DEFAULT_LEVEL = "hard"

# Shifts on top of the tunables, so bots still play differently.
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


def card_sets(cards):
    """The base value of every set of cards that could be traded now (a
    mirror of CardMenu.use_cards_automatic): 10 for three different, 2m + 4
    for three of type m; a Joker (3) counts as any."""
    types = [c.type for c in cards]
    bases = []
    while len(types) >= 3:
        same = [i for i in range(3) if sum(1 for t in types if t in (i, 3)) >= 3]
        different = len(set(t for t in types if t != 3)) + sum(1 for t in types if t == 3) >= 3
        if different:
            for i in range(3):
                types.remove(i if i in types else 3)
            bases.append(10)
        elif same:
            m = max(same)
            for _ in range(3):
                types.remove(m if m in types else 3)
            bases.append(2 * m + 4)
        else:
            break
    return bases


def bot_params(player):
    """`player`'s tunables: their level's (LEVELS; "hard" unless a tuning
    tool says otherwise), shifted by their personality (PERSONALITIES)."""
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
        self._endgame_params = {}  # level params -> the same with the endgame's changes
        self._risk_frozen = None   # while set, _elimination_risk is this (see _buffer_best)
        self._vacated = {}         # country -> turn_num the bot emptied it on purpose
        self._strike_turn = None   # (turn, player) the strike queue is for
        self._strike_queue = None  # what's left of this turn's strike, one action a step
        # What the bot is doing, shown at the bottom of the screen during
        # its turn (see _say).
        self.status = ""
        # Worked-out facts about the board, valid for one decision (the
        # board changes with every action).
        self._cache = {}
        self._acting = None
        # For the random slips of a noisy bot (see _jitter); its own, so it
        # doesn't disturb the game's dice.
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
        """`score` nudged up or down at random by the bot's noise (it
        sometimes prefers a lesser option); unchanged at noise 0."""
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
        personality -- and, for the leader once the game is nearly over, the
        endgame's (see _endgame)."""
        base = bot_params(self.player)
        if not self._endgame():
            return base
        overlay = self._endgame_params.get(id(base))
        if overlay is None:
            overlay = dict(base, price_factor=base["price_factor"] * base["endgame_price"], hold_weak_sets=False)
            self._endgame_params[id(base)] = overlay
        return overlay

    def _endgame(self):
        """Whether the deciding bot is the strongest player (strength: 3 a
        country plus its troops) at a time the game is nearly over: at most
        endgame_alive players left, or a share of all strength of at least
        endgame_lead. Measured: alive <= 2 comes 4-6 rounds before the end
        (94% of games), the share is the steadiest sign across bots; alive <= 3
        comes 11-15 rounds too early."""
        def compute():
            engine = self.engine
            base = bot_params(self.player)
            strength = {}
            for c in engine.countries.values():
                if self._is_real(c.owner) and not c.owner.eliminated:
                    strength[c.owner] = strength.get(c.owner, 0) + 3 + c.units
            mine = strength.get(self.player, 0)
            top = max(strength.values(), default=0)
            if mine <= 0 or mine < top:
                return False
            alive = sum(1 for q in engine.players if not q.eliminated)
            share = top / (sum(strength.values()) or 1)
            return bool((base["endgame_alive"] and alive <= base["endgame_alive"]) or share >= base["endgame_lead"])
        return self._cached("endgame", compute)

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
            self._cache = {}
            self._say("{}{}".format(
                "" if personality == DEFAULT_PERSONALITY else personality + ", ",
                "playing it safe" if self._in_danger() else "thinking"))

        phase = manager.phases.get(player.attack)
        if self._human_defending() or self._human_picking() or player.attack == 6:
            # Their tank/dice choice or event pick, with the mouse; an
            # event's mouse attack (attack 6) runs itself.
            phase.update()
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
            + self.params["loot_card"] * len(loser.cards)
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
                value += self._prize(target.owner)  # eliminates them
            elif target.owner in self._hunt():
                # A step towards finishing them off this turn.
                value += self._prize(target.owner) * self._hunt()[target.owner] / left
        if self.params["retention"] and self.params["exposure"] and target.owner is not player:
            value = self._retained_value(target, value)
        return value

    def _retained_value(self, target, value):
        """`value` of taking `target`, counting only what is kept: of the
        conquests the bots made, 40% were lost before their next turn
        (islands 4%, countries with three land links 48%), and the value did
        not know."""
        p = self.params
        exposure = self._danger(target, units=p["conquest_garrison"], fort=0, tanks=0)
        if p["retention"] == 2:
            card = (0.5 if self.manager.conquered_enemy_this_turn else CARD_VALUE) if self._is_real(target.owner) else 0.0
            return (value - card) * (1 - p["retention_weight"] * exposure) + card
        horizon = p["horizon"]
        kept = sum((1 - exposure) ** k for k in range(1, horizon + 1))
        return value + self._income_value(target) * (kept - horizon)

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

    # --- eliminations: ours of others, and others' of us ----------------------
    # Wiping a player out hands over their wood, steel, nuclear, oil and
    # cards; being wiped out ends the game. So the bot goes for an
    # elimination when the chance of pulling it off, times what it brings,
    # beats the troops it costs and the danger it leaves the bot in -- and
    # while another player could wipe the bot out, it holds back and builds
    # up instead (see _elimination_risk).

    def _prize(self, loser):
        """What eliminating `loser` brings: their loot, and one rival less."""
        return self.params["rival_value"] + self.params["loot_weight"] * self._loot_value(loser)

    def _campaign(self, victim):
        """(chance, troops lost) for taking every country `victim` holds
        this turn: each in turn falls to the strongest stack next to it --
        one of ours, or the survivors in a country just taken (they move
        in, one stays behind, and go on over land)."""
        engine, player = self.engine, self.player
        free = {c.name: c.units - 1 for c in self._owned() if c.units > 1}
        remaining = self._owned(victim)
        chance, lost = 1.0, 0.0
        while remaining:
            best = None
            for target in remaining:
                for name, kind in self._links(target.name).items():
                    if free.get(name, 0) < 1:
                        continue
                    origin = engine.countries[name]
                    ours = origin.owner is player
                    if (ours and not self._can_reach(origin, kind)) or (not ours and kind != "land"):
                        continue
                    tanks = min(origin.tanks, player.oil) if ours else 0
                    p, left, _ = battle(free[name], target.units, self._combat_mods(origin, target, tanks))
                    if best is None or p > best[0]:
                        best = (p, left, name, target)
            if best is None or best[0] <= 0:
                return 0.0, lost
            p, left, name, target = best
            chance *= p
            lost += free[name] - left
            free[name] = 0
            free[target.name] = int(left / p) - 1
            remaining.remove(target)
        return chance, lost

    def _hunt(self):
        """{player: chance}: other players worth wiping out this turn -- the
        chance of taking all their countries (see _campaign) times the prize
        beats the troops it costs and the extra danger of being wiped out
        ourselves once they're spent."""
        def compute():
            engine, player, p = self.engine, self.player, self.params
            e = self._economy()
            troop_cost = 1 - min(1.0, e["starving"] / max(e["units"], 1))
            risk = self._elimination_risk()
            hunted = {}
            for other in engine.players:
                if other is player or other.eliminated:
                    continue
                theirs = self._owned(other)
                if not theirs or len(theirs) > p["hunt_max_countries"]:
                    continue
                chance, lost = self._campaign(other)
                if chance < p["hunt_min_p"]:
                    continue
                if self._hunt_worth(other, chance, lost, risk, troop_cost) > 0:
                    hunted[other] = chance
            return hunted
        return self._cached("hunt", compute)

    def _hunt_worth(self, victim, chance, lost, risk=None, troop_cost=None):
        """What going for `victim` is worth, in troops, given the `chance` of
        taking all their countries this turn and the troops `lost` doing it:
        chance x prize, less the troops it costs and the extra danger of being
        wiped out ourselves once they're spent."""
        if troop_cost is None:
            e = self._economy()
            troop_cost = 1 - min(1.0, e["starving"] / max(e["units"], 1))
        risk = self._elimination_risk() if risk is None else risk
        # Once wiped out, they're no threat to us any more.
        gone = {victim: sum(c.units for c in self._owned(victim)) + 99}
        return chance * self._prize(victim) - troop_cost * lost \
            - self._survival_value() * (self._elimination_risk(lost, gone) - risk)

    # --- the strike step -------------------------------------------------------
    # Eliminating a player is what decides games (a player that makes 0 / 1 / 2
    # / 3 eliminations wins 2 / 28 / 73 / 100% of the time in a 4-player game),
    # but the bot only looked at what the board allowed at the moment it started
    # attacking, after it had traded, placed and bought. The step works backwards:
    # for each player it could finish off, what does the stock it holds buy --
    # nukes (half a garrison each, nothing to roll), a card set (troops), a ship,
    # plane or bridge where water is in the way, the new troops massed on one
    # stack -- and is that worth it by the measure of _hunt? Then do it first.

    def _hypo_campaign(self, victim, troops=None, tanks=None, nukes=(), reach=()):
        """(chance, lost) of _campaign(victim) with something added: `troops` and
        `tanks` {country: n}, `nukes` country names (one entry per nuke), `reach`
        [("ship" | "plane", country) | ("bridge", (a, b))]."""
        engine = self.engine
        changes = []
        for name, n in (troops or {}).items():
            c = engine.countries[name]
            changes.append((c, "units", c.units + n))
        for name, n in (tanks or {}).items():
            c = engine.countries[name]
            changes.append((c, "tanks", c.tanks + n))
        for kind, what in reach:
            if kind == "ship":
                c = engine.countries[what]
                changes.append((c, "ships", c.ships + 1))
            elif kind == "plane":
                c = engine.countries[what]
                changes.append((c, "planes", c.planes + 1))
            elif kind == "bridge":
                link = self._connection(what[0], what[1], "sea")
                if link is not None:
                    changes.append((link, "kind", "land"))
        if nukes:
            state = {}
            for name in nukes:
                c = engine.countries[name]
                units, owner, radioactive = state.get(name, (c.units, c.owner, c.radioactive))
                units //= 2
                radioactive += 3
                if units == 0 and owner is not engine.default_player:
                    owner, units = engine.default_player, engine.initial_country_units.get(name, 2)
                state[name] = (units, owner, radioactive)
            for name, (units, owner, radioactive) in state.items():
                c = engine.countries[name]
                changes += [(c, "units", units), (c, "owner", owner), (c, "radioactive", radioactive)]
        with self._what_if(*changes):
            if not self._owned(victim):
                return 1.0, 0.0
            return self._campaign(victim)

    def _strike_victims(self):
        """The other players with at most hunt_max_countries countries."""
        limit = self.params["hunt_max_countries"]
        return [other for other in self.engine.players
                if other is not self.player and not other.eliminated and 1 <= len(self._owned(other)) <= limit]

    def _best_lump(self, victim, troops=0, tanks=0, nukes=(), reach=()):
        """(chance, lost, recipient): the added troops and tanks all go to ONE
        own stack next to the victim, the one that does the most."""
        engine = self.engine
        names = set()
        for target in self._owned(victim):
            for other in self._links(target.name):
                if engine.countries[other].owner is self.player:
                    names.add(other)
        candidates = sorted(names, key=lambda n: (-engine.countries[n].units, n))[:4] or [None]
        for kind, what in reach:
            if kind in ("ship", "plane") and what not in candidates:
                candidates.append(what)
        best = None
        for name in candidates:
            chance, lost = self._hypo_campaign(
                victim, {name: troops} if name and troops else None, {name: tanks} if name and tanks else None,
                nukes, reach)
            if best is None or (chance, -lost) > (best[0], -best[1]):
                best = (chance, lost, name)
        return best

    def _reach_candidates(self, victim, ship_ok, plane_ok, bridge_ok):
        """Crossings that would open a sea link from an own stack (2+ troops) to a
        country of the victim: [("ship" | "plane", country) | ("bridge", (a, b))]."""
        engine = self.engine
        items, seen = [], set()
        for target in self._owned(victim):
            for other, kind in self._links(target.name).items():
                origin = engine.countries[other]
                if kind != "sea" or origin.owner is not self.player or origin.units < 2:
                    continue
                if ship_ok and not origin.ships and ("ship", other) not in seen:
                    items.append(("ship", other))
                    seen.add(("ship", other))
                if plane_ok and not origin.planes and ("plane", other) not in seen:
                    items.append(("plane", other))
                    seen.add(("plane", other))
                if bridge_ok and ("bridge", (other, target.name)) not in seen:
                    items.append(("bridge", (other, target.name)))
                    seen.add(("bridge", (other, target.name)))
        return items

    def _strike_ceiling(self, victim, reinforcements):
        """The best chance of taking all the victim's countries this turn with
        everything held converted: the new troops, every card set traded for
        troops, nukes, and one crossing."""
        player = self.player
        card_troops = int(round(sum(card_sets(player.cards))))
        tanks = player.steel // TANK_STEEL if self.params["strike_max_tanks"] else 0
        best = self._best_lump(victim, reinforcements + card_troops, tanks)
        nukes = []
        names = sorted(n.name for n in self._owned(victim)
                       if any(self.engine.countries[o].owner is player for o in self._links(n.name)))
        for _ in range(int(player.nuclear // NUKE_NUCLEAR)):
            step = None
            for name in names:
                trial = self._best_lump(victim, reinforcements + card_troops, tanks, nukes + [name])
                if step is None or (trial[0], -trial[1]) > (step[0][0], -step[0][1]):
                    step = (trial, name)
            if step is None or step[0][0] <= best[0] + 1e-9:
                break
            best = step[0]
            nukes.append(step[1])
        ship_ok = bool(player.start_ship) or player.wood >= 15
        for item in self._reach_candidates(victim, ship_ok, player.steel >= 10 and player.oil >= 1, player.wood >= 10):
            trial = self._best_lump(victim, reinforcements + card_troops, tanks, nukes, (item,))
            if (trial[0], -trial[1]) > (best[0], -best[1]):
                best = trial
        return best[0]

    def _strike_bundle(self, victim, bundle, pool, risk):
        """(net, chance, lost, recipient, troops) of `bundle` against `victim`:
        the best share of the troop pool to mass on one stack, and what that
        is worth after the troops and resources it uses."""
        p = self.params
        troops_in_pool = pool + (bundle["card_troops"] if bundle["cards"] else 0)
        best = None
        for k in sorted({0, troops_in_pool // 4, troops_in_pool // 2, 3 * troops_in_pool // 4, troops_in_pool}) \
                if troops_in_pool > 0 else [0]:
            chance, lost, recipient = self._best_lump(victim, k, bundle["tanks"], bundle["nukes"], bundle["reach"])
            net = self._hunt_worth(victim, chance, lost, risk) - p["strike_troop_cost"] * k - bundle["price"]
            if chance < p["hunt_min_p"]:
                net = -1e9
            if best is None or net > best[0]:
                best = (net, chance, lost, recipient, k)
        return best

    def _strike_plan(self):
        """(victim, bundle, evaluation) of the strike worth the most, or None."""
        player, manager, p = self.player, self.manager, self.params
        shop = manager.phases[3]
        pool = int(manager.reinforcements)
        sets = card_sets(player.cards)
        card_troops = int(round(sum(sets)))
        tank_cost = shop._cost({"steel": TANK_STEEL})["steel"]
        nuke_cost = shop._cost({"nuclear": NUKE_NUCLEAR})["nuclear"]
        ship_cost = shop.ship_cost()["wood"]
        plane_cost = shop._cost({"steel": 10})["steel"]
        bridge_cost = shop._cost({"wood": 10})["wood"]
        risk = self._elimination_risk()
        found = None
        for victim in self._strike_victims():
            if self._strike_ceiling(victim, pool) < p["strike_filter"]:
                continue
            adjacent = [c.name for c in self._owned(victim)
                        if any(self.engine.countries[o].owner is player for o in self._links(c.name))]
            bundle = dict(cards=False, tanks=0, nukes=[], reach=[], price=0.0, card_troops=card_troops)
            current = self._strike_bundle(victim, bundle, pool, risk)
            for _ in range(10):  # hill climbing: one more item at a time while it pays
                moves = []
                if sets and not bundle["cards"]:
                    moves.append(dict(bundle, cards=True))
                if bundle["tanks"] < p["strike_max_tanks"] and player.oil >= 1 \
                        and player.steel >= (bundle["tanks"] + 1) * tank_cost:
                    moves.append(dict(bundle, tanks=bundle["tanks"] + 1,
                                      price=bundle["price"] + self._price({"steel": tank_cost})))
                if len(bundle["nukes"]) < p["strike_max_nukes"] \
                        and player.nuclear >= (len(bundle["nukes"]) + 1) * nuke_cost:
                    for name in adjacent:
                        moves.append(dict(bundle, nukes=bundle["nukes"] + [name],
                                          price=bundle["price"] + self._price({"nuclear": nuke_cost})))
                if not bundle["reach"]:
                    ship_ok = bool(player.start_ship) or player.wood >= ship_cost
                    plane_ok = player.steel - bundle["tanks"] * tank_cost >= plane_cost and player.oil >= 1
                    for item in self._reach_candidates(victim, ship_ok, plane_ok, player.wood >= bridge_cost):
                        cost = {"ship": {"wood": ship_cost}, "plane": {"steel": plane_cost},
                                "bridge": {"wood": bridge_cost}}[item[0]]
                        moves.append(dict(bundle, reach=[item], price=bundle["price"] + self._price(cost)))
                best_move = None
                for move in moves:
                    evaluation = self._strike_bundle(victim, move, pool, risk)
                    if evaluation[0] > current[0] + 1e-6 and (best_move is None or evaluation[0] > best_move[1][0]):
                        best_move = (move, evaluation)
                if best_move is None:
                    break
                bundle, current = best_move
            uses_chest = bundle["cards"] or bundle["tanks"] or bundle["nukes"] or bundle["reach"]
            if current[0] > p["strike_min_net"] and (uses_chest or p["strike_place"]):
                if found is None or current[0] > found[2][0]:
                    found = (victim, bundle, current)
        return found

    def _strike_actions(self, victim, bundle, evaluation):
        """The plan as [(what it says, action)], one carried out per bot step."""
        actions = []
        recipient = evaluation[3]
        for name in bundle["nukes"]:
            actions.append(("nuke " + name, lambda name=name: self._strike_nuke(name)))
        if bundle["tanks"] and recipient:
            for _ in range(bundle["tanks"]):
                actions.append(("tank", lambda: self._strike_buy("tanks", {"steel": TANK_STEEL}, recipient)))
        for kind, what in bundle["reach"]:
            if kind == "ship":
                actions.append(("ship", lambda what=what: self._strike_buy("ships", None, what)))
            elif kind == "plane":
                actions.append(("plane", lambda what=what: self._strike_buy("planes", {"steel": 10}, what)))
            else:
                actions.append(("bridge", lambda what=what: self._strike_bridge(what)))
        if bundle["cards"]:
            actions.append(("trade", self._strike_trade))
        actions.append(("deploy", lambda: self._strike_deploy(victim)))
        return actions

    def _strike_nuke(self, name):
        shop = self.manager.phases[3]
        if self.player.nuclear >= shop._cost({"nuclear": NUKE_NUCLEAR})["nuclear"] and name in shop._nuke_targets():
            self._drop_nuke(name)
            self._say("strikes " + name)

    def _strike_buy(self, attr, cost, name):
        shop = self.manager.phases[3]
        cost = shop.ship_cost() if attr == "ships" else shop._cost(cost)
        if self.engine.countries[name].owner is self.player and all(getattr(self.player, r) >= n for r, n in cost.items()):
            shop.place_unit(attr, cost, name)
            self._say("buys a {} for the strike".format(attr[:-1]))

    def _strike_bridge(self, ends):
        if self.manager.phases[3].build_bridge(ends[0], ends[1]):
            self._say("builds a bridge for the strike")

    def _strike_trade(self):
        while self.manager.can_trade() and self._trade(need_troops=True):
            pass

    def _strike_deploy(self, victim):
        """Mass the new troops on the stack the strike works best from."""
        manager = self.manager
        pool = int(manager.reinforcements)
        if pool > 0:
            risk = self._elimination_risk()
            best = None
            for k in sorted({0, pool // 4, pool // 2, 3 * pool // 4, pool}):
                chance, lost, recipient = self._best_lump(victim, k, 0, ())
                net = self._hunt_worth(victim, chance, lost, risk) - self.params["strike_troop_cost"] * k
                if best is None or net > best[0]:
                    best = (net, k, recipient)
            _, k, recipient = best
            if k > 0 and recipient:
                self.engine.countries[recipient].units += k
                manager.reinforcements -= k
                self._say("masses {} troops on {} against {}".format(k, recipient, victim.name))
        self._strike_queue = []

    def _finish_step(self):
        """Fire ONE nuke of a sure elimination: a player whose every country
        the nukes in stock can bring to 0 troops (floor(log2 troops) + 1 each,
        no dice). True if it fired."""
        shop = self.manager.phases[3]
        player, engine = self.player, self.engine
        cost = shop._cost({"nuclear": NUKE_NUCLEAR})["nuclear"]
        have = player.nuclear // cost if cost else 0
        if have < 1:
            return False
        targets = shop._nuke_targets()
        best = None
        for victim in engine.players:
            if victim is player or victim.eliminated:
                continue
            owned = [c for c in engine.countries.values() if c.owner is victim and c.units > 0]
            if not owned or any(c.name not in targets for c in owned):
                continue
            plan = []
            for c in owned:
                plan += [c.name] * int(c.units).bit_length()  # floor(log2 units) + 1 (units can be a numpy int)
            if len(plan) <= have and len(plan) <= self.params["finish_max"] and (best is None or len(plan) < len(best)):
                best = plan
        if best is None:
            return False
        self._drop_nuke(best[0])
        self._say("wipes a player out with {} nukes".format(len(best)))
        return True

    def _strike_step(self):
        """One bot step of the strike (see above): True if it did something."""
        player, manager = self.player, self.manager
        if self.params["finish_max"] and self._finish_step():
            return True
        if not self.params["strike"] or "strike" in self._done:
            return False
        turn = (manager.turn_num, player.name)
        if self._strike_turn != turn:
            self._strike_turn, self._strike_queue = turn, None
        if self._strike_queue is None:
            plan = self._strike_plan()
            if plan is None:
                self._done.add("strike")
                return True  # looking for a plan took this step
            self._strike_queue = self._strike_actions(*plan)
            return True  # planning took this step
        if self._strike_queue:
            self._strike_queue.pop(0)[1]()
            return True
        self._strike_queue = None
        self._done.add("strike")
        return False

    def _territory_parts(self):
        """The bot's countries, in groups connected through its own territory."""
        def compute():
            parts, seen = [], set()
            for country in self._owned():
                if country.name not in seen:
                    part = self._own_reach(country.name)
                    seen |= part
                    parts.append(part)
            return parts
        return self._cached("parts", compute)

    def _elimination_risk(self, lost=0, killed=None):
        """Chance another player wipes the bot out before its next turn --
        with `lost` of our troops gone (negative: added), and `killed`
        ({player: troops}) of theirs. A neighbour that borders every part of
        the bot's territory throws everything it has there, plus its next
        reinforcements and a card set, at all of the bot's troops."""
        if self._risk_frozen is not None:
            return 1.0 if lost >= 10 ** 6 else self._risk_frozen
        if self.params["risk_exposure"] and self.params["exposure"]:
            return self._exposure_risk(lost, killed)
        killed = killed or {}
        lost = int(round(lost))
        key = ("doom", lost, tuple(sorted((p.name, int(round(n))) for p, n in killed.items())))

        def compute():
            engine, player = self.engine, self.player
            owned = self._owned()
            troops = sum(c.units for c in owned)
            defenders = troops - lost
            if defenders <= 0:
                return 1.0
            fort = round(sum(c.fort_lvl * c.units for c in owned) / max(troops, 1))
            parts = self._territory_parts()
            safe = 1.0
            for enemy in engine.players:
                if enemy is player or enemy.eliminated:
                    continue
                stacks, touched = {}, set()
                for i, part in enumerate(parts):
                    for name in part:
                        for other, kind in self._links(name).items():
                            c = engine.countries[other]
                            if c.owner is not enemy or c.units < 2:
                                continue
                            if kind == "sea" and not (c.ships or (c.planes and enemy.oil)):
                                continue
                            stacks[other] = c
                            touched.add(i)
                if not stacks or len(touched) < len(parts):
                    continue
                extra = self.engine.production(enemy)["helmets"] // 3 + 3 + (10 if len(enemy.cards) >= 3 else 0)
                attackers = sum(c.units - 1 for c in stacks.values()) + extra - int(round(killed.get(enemy, 0)))
                tanks = max(min(c.tanks, enemy.oil) for c in stacks.values())
                wiped = battle(attackers, defenders, (0, tanks, fort, 0))[0]
                safe *= 1 - wiped * self.params["enemy_aggression"]
            return 1 - safe
        return self._cached(key, compute)

    def _in_danger(self):
        """Whether the bot plays for survival: another player could well
        wipe it out before its next turn."""
        return self._elimination_risk() > self.params["survival_risk"]

    def _survival_value(self):
        """What being wiped out costs, in troops: the game itself, plus all
        the bot holds -- which the one who does it takes."""
        def compute():
            return self.params["survival_value"] + sum(self._hold_value(c) for c in self._owned()) \
                + self._loot_value(self.player)
        return self._cached("survival", compute)

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
            tanks = min(from_c.tanks, player.oil) if active_tanks is None else active_tanks
            if event is not None and event.free_claim_allowed(engine, target):
                chance, left, killed = 1.0, float(attackers), 0.0
            else:
                chance, left, killed = battle(attackers, target.units, self._combat_mods(from_c, target, tanks))
            starving = self._economy()["starving"]
            troop_cost = 1 - min(1.0, starving / attackers)
            kill_value = self.params["kill_value"] if self._is_real(target.owner) else 0
            ev = chance * self._target_value(target) + kill_value * killed - troop_cost * (attackers - left)
            if not seen and self.params["survival_value"]:
                # What the fight does to our own chance of being wiped out:
                # our troops lost against theirs killed.
                theirs = {target.owner: killed} if self._is_real(target.owner) else None
                ev -= self._survival_value() * (
                    self._elimination_risk(attackers - left, theirs) - self._elimination_risk())
            if not seen and chance > 0.05 and self.params["extra_exposure"] and self.params["exposure"] \
                    and self._is_real(target.owner) and self.manager.conquered_enemy_this_turn:
                ev -= self.params["extra_exposure"] * chance * self._extra_cost(
                    from_c, target, attackers, left, chance, troop_cost)
            if not seen and chance > 0.05 and self.params["asset_attack"] and self.params["asset_hold"]:
                ev -= self.params["asset_attack"] * chance * self._carried_loss(from_c, target, tanks)
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

    def _carried_loss(self, from_c, target, active_tanks):
        """What the assets that go along on an attack on `target` are likely to
        cost: they land on the conquered country, and go down with it."""
        p = self.params
        sea = self._links(from_c.name).get(target.name) == "sea"
        ships = from_c.ships if sea else 0
        planes = 1 if sea and not ships and from_c.planes else 0
        tanks = active_tanks if p["asset_carry"] else from_c.tanks
        price = self._asset_price(ships, tanks, planes, 0)
        if not price:
            return 0.0
        return p["asset_hold"] * price * self._danger(target, p["conquest_garrison"], 0, 0)

    def _extra_cost(self, from_c, target, attackers, left, chance, troop_cost):
        """What taking `target` from `from_c` exposes, in troops: the dice of the
        winning roll (up to 3) have to move in and are likely to be lost with
        it, and so is a card for whoever takes it back; plus how much weaker
        that leaves `from_c`."""
        p = self.params
        total = int(round(left / chance)) + 1      # troops on the target and the origin together after a win
        moved = max(1, min(3, total - 1, attackers))
        exposure = self._danger(target, moved, 0, 0)
        cost = exposure * (moved * troop_cost + p["extra_gift"] * CARD_VALUE)
        rest = total - moved
        if rest >= 1:
            weaker = self._danger(from_c, rest) - self._danger(from_c, attackers + 1)
            cost += p["extra_origin"] * max(0.0, weaker) * self._hold_value(from_c)
        return cost

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
        if self._vacated:
            options = [o for o in options if self._retake_ok(o[1])]
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
        `fort` level and `tanks`) before our next turn: _exposure, or with
        the "exposure" tunable at 0 the old model, _danger_adjacent."""
        if self.params["exposure"]:
            return self._exposure(country, units, fort, tanks)
        return self._danger_adjacent(country, units, fort, tanks)

    def _danger_adjacent(self, country, units=None, fort=None, tanks=None):
        """The old model of _danger: the strongest attack a neighbour can
        make on `country` -- over sea only with a ship, or a plane and oil --
        with what they can add there first, their tanks, and our fort and
        tanks against it. It misses what has not happened yet: strikes from
        a country the enemy takes first (half of all losses), a crossing the
        enemy can still buy, and enemies that have not moved."""
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

    # --- exposure: the chance a country is taken before our next turn ---------
    # Measured on whole games, the chance of losing a country had little to do
    # with the stacks next to it: 51% of losses were a chain (the enemy first
    # takes a mouse or other country the same turn and strikes from there),
    # 37% a direct land attack, and only ~2% a ship or plane already in
    # place. So for every other player the exposure takes the strongest of
    #   - a stack next to the country over land (weight 1),
    #   - over sea with a crossing in place (1), or one the player can still
    #     get at their next turn (sea_buy_weight),
    #   - a chain: they conquer up to chain_depth countries on the way (each
    #     at least chain_min_win likely) and strike from the last one
    #     (chain_weight, less over sea or with a crossing still to buy),
    # and the players combine as independent chances.

    def _not_moved_yet(self, owner):
        """Whether `owner` has not had their first turn yet (they still hold
        their start stack and a free ship, and have no income)."""
        manager, engine = self.manager, self.engine
        count = len(engine.players)
        if manager.turn_num >= count:
            return False
        first = (engine.turn - manager.turn_num) % count  # the seat that moved first
        return (engine.players.index(owner) - first) % count > manager.turn_num

    def _crossing_means(self, owner):
        """(ship, bridge, plane): whether `owner` can get that crossing over
        water at their next turn start -- the free first ship, wood for a
        ship (15) or a bridge (10), steel (10) and oil for a plane. Income
        arrives at the turn start, but not on a first turn."""
        def compute():
            first_turn = self._not_moved_yet(owner)
            income = self.engine.production(owner)
            wood = owner.wood + (0 if first_turn else income["wood"])
            steel = owner.steel + (0 if first_turn else income["steel"])
            oil = owner.oil + (0 if first_turn else income["oil"])
            return bool(owner.start_ship) or wood >= 15, wood >= 10, steel >= 10 and oil >= 1
        return self._cached(("means", owner.name), compute)

    def _chain_map(self, owner, ghost):
        """{country: (force, chance, last hop over sea, crossings bought)}: the
        strikes `owner` can make by first conquering at least one country on
        the way. `ghost` (country names) pretends those countries are ours,
        for a conquest being weighed."""
        def compute():
            engine, p = self.engine, self.params
            countries = engine.countries
            ghosts = set(ghost)
            extra = self._enemy_extra(owner)
            ship_ok, bridge_ok, plane_ok = self._crossing_means(owner)
            can_buy = ship_ok or bridge_ok or plane_ok
            buy = p["chain_buy_weight"]
            reach = {}
            for start, origin in countries.items():
                if origin.owner is not owner or start in ghosts:
                    continue
                force0 = origin.units - 1 + extra
                if force0 < 1:
                    continue
                carries = bool(origin.ships or (origin.planes and owner.oil))
                best = {start: (force0, 1.0, carries, 0)}
                depth = {start: 0}
                todo = [start]
                guard = 0
                while todo and guard < 300:
                    guard += 1
                    here = todo.pop()
                    force, chance, carried, bought = best[here]
                    if depth[here] > p["chain_depth"]:
                        continue
                    for there, kind in self._links(here).items():
                        if countries[there].owner is owner and there not in ghosts:
                            continue
                        hop_buy = 0
                        if kind == "sea" and not carried:
                            if not can_buy or here != start:
                                continue
                            hop_buy = 1
                        target = countries[there]
                        win, survivors, _ = battle(int(force), target.units,
                                                   (0, 0, target.fort_lvl if there not in ghosts else 0, 0))
                        if here != start:
                            current = reach.get(there)
                            score = force * chance * buy ** (bought + hop_buy)
                            if current is None or score > current[0] * current[1] * buy ** current[3]:
                                reach[there] = (int(force), chance, kind == "sea", bought + hop_buy)
                        if win < p["chain_min_win"]:
                            continue
                        onward = int(survivors / win) - 1
                        if onward < 1:
                            continue
                        onward_chance = chance * win
                        onward_carried = (carried or hop_buy == 1) if kind == "sea" else False
                        onward_bought = bought + hop_buy
                        old = best.get(there)
                        if old is None or onward * onward_chance * buy ** onward_bought \
                                > old[0] * old[1] * buy ** old[3] + 1e-9:
                            best[there] = (onward, onward_chance, onward_carried, onward_bought)
                            depth[there] = depth[here] + 1
                            todo.append(there)
            return reach
        return self._cached(("chain", owner.name, tuple(ghost)), compute)

    def _exposure(self, country, units=None, fort=None, tanks=None, skip=frozenset()):
        """Chance another player takes `country` (with `units` troops, a
        `fort` level and `tanks`) before our next turn, leaving the players in
        `skip` out of it; see above."""
        units = country.units if units is None else units
        fort = country.fort_lvl if fort is None else fort
        tanks = country.tanks if tanks is None else tanks
        if units <= 0:
            return 1.0

        def compute():
            engine, player, event = self.engine, self.player, self.manager.current_event
            p = self.params
            ghost = (country.name,) if country.owner is not player else ()
            safe = 1.0
            for owner in engine.players:
                if owner is player or owner.eliminated or owner in skip:
                    continue
                best = 0.0
                can_buy = any(self._crossing_means(owner))
                for name, kind in self._links(country.name).items():
                    enemy = engine.countries[name]
                    if enemy.owner is not owner:
                        continue
                    if event is not None and not (event.can_attack_from(engine, enemy)
                                                  and event.can_attack_target(engine, country)):
                        continue
                    weight = 1.0
                    if kind == "sea" and not (enemy.ships > 0 or (enemy.planes > 0 and owner.oil > 0)):
                        weight = p["sea_buy_weight"] if can_buy else 0.0
                    if weight <= 0:
                        continue
                    a_all, d_all = 0, fort
                    if event is not None:
                        a_all = event.attack_bonus(engine, enemy) - event.dice_penalty(engine, owner)
                        d_all = fort - event.dice_penalty(engine, player)
                    mods = (int(a_all), min(enemy.tanks, owner.oil), int(d_all), min(tanks, player.oil))
                    attackers = enemy.units - 1 + self._enemy_extra(owner)
                    best = max(best, weight * battle(attackers, units, mods)[0])
                hit = self._chain_map(owner, ghost).get(country.name)
                if hit is not None:
                    force, chance, via_sea, bought = hit
                    weight = p["chain_weight"] * chance * (p["chain_sea_weight"] if via_sea else 1.0) \
                        * p["chain_buy_weight"] ** bought
                    if event is not None and not event.can_attack_target(engine, country):
                        weight = 0.0
                    best = max(best, weight * battle(int(force), units, (0, 0, int(fort), min(tanks, player.oil)))[0])
                safe *= 1 - min(1.0, p["enemy_aggression"] * p["exposure_scale"] * best)
            return 1 - safe
        return self._cached(("exposure", country.name, units, fort, tanks, skip), compute)

    def _exposure_risk(self, lost=0, killed=None):
        """_elimination_risk from the exposure of the bot's countries: all of them
        have to fall, so the mean exposure to the power of their number (measured:
        AUC 0.92 for who gets wiped out, against 0.71 for the old model). `lost`
        troops are taken off the countries in proportion; a player in `killed`
        that is wiped out is no threat any more."""
        killed = killed or {}
        lost = int(round(lost))
        wiped = frozenset(p for p, n in killed.items() if n >= sum(c.units for c in self._owned(p)))
        key = ("doom_exposure", lost, wiped)

        def compute():
            owned = self._owned()
            troops = sum(c.units for c in owned)
            if not owned or troops - lost <= 0:
                return 1.0
            scale = (troops - lost) / troops
            exposures = [self._exposure(c, max(1, int(round(c.units * scale))), skip=wiped) for c in owned]
            return (sum(exposures) / len(exposures)) ** len(exposures)
        return self._cached(key, compute)

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
            return value * (1 + self.params["survival_weight"] * self._elimination_risk())
        return self._cached(("hold", country.name), compute)

    def _asset_price(self, ships, tanks, planes, fort):
        """What the assets on a country cost to replace, in troops: they go with it."""
        w = self._weights()
        wood = 15 * ships + sum(10 + 5 * k for k in range(fort))
        steel = TANK_STEEL * tanks + 10 * planes
        return w["wood"] * wood + w["steel"] * steel

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
        danger = self._danger(country, units, fort, tanks)
        value = -self._hold_value(country) * danger
        if self.params["asset_hold"]:
            value -= self.params["asset_hold"] * danger * self._asset_price(
                country.ships if ships is None else ships, country.tanks if tanks is None else tanks,
                country.planes if planes is None else planes, country.fort_lvl if fort is None else fort)
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
        if self._strike_step():
            return
        if self._trade():
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
        phase.finish_starvation()

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
            or self._economy()["starving"] > 0 or self._in_danger()
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
                # fight (and defend) for a round -- which counts all the
                # more while the bot could be wiped out.
                fed = min(n, feedable)
                safer = self._elimination_risk() - self._elimination_risk(lost=-n)
                return fed + 0.5 * (n - fed) + self._survival_value() * safer
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
            # Whatever is left when the bot is wiped out goes to the one who
            # does it: the more likely that is, the cheaper spending it.
            price = self._price(cost) * (1 - self._elimination_risk())
            net = self._jitter(value - self.params["price_factor"] * price)
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
        ship_cost, plane_cost = shop.ship_cost(), shop._cost({"steel": 10})
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
        self.manager.notices.append(t("{} nuked {}!").format(self.player.name, t(name)))

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
        self._say("attacks {} from {} ({:.0%}){}".format(
            target.name, from_c.name, self._win_probability(from_c, target),
            " to finish off " + target.owner.name if target.owner in self._hunt() else ""))
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
            attack.active_tanks = min(attack.tank_fee_paid, attack.active_tanks)  # paid ones are free
        if land or attack.selected_ships > 0:
            attack.selected_planes = 0
        else:
            # Over sea without a ship: one plane (1 oil) carries them.
            attack.selected_planes = 1
            attack.active_tanks = min(attack.active_tanks,
                                      max(player.oil - 1 + attack.prepaid_planes, 0) + attack.tank_fee_paid)
        if self.params["asset_carry"]:
            attack.selected_tanks = min(attack.selected_tanks, attack.active_tanks)

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
        if self._in_danger():
            return None  # the resources go on surviving
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

    # --- emptying a country on purpose (off by default) -----------------------
    # The rules let a player empty a country (moving the last troop out in the move
    # phase); it goes back to the mouse with its native garrison, and taking it
    # earns nobody a card. A country that is probably lost anyway, held by a
    # troop or two, is then worth more as a mouse country than as a card for the
    # enemy -- on paper. In play it comes out about even (see "buffer" in BASE).

    def _buffer_event_ok(self):
        """No event that changes what an abandoned country becomes (VOC part 2)."""
        event = self.manager.current_event
        if event is None:
            return True
        from events import Event
        return type(event).abandoned_units is Event.abandoned_units

    def _buffer_eligible(self, country):
        p = self.params
        if country.owner is not self.player or country.units <= 0 or country.units > p["buffer_max_units"]:
            return False
        if country.fort_lvl or country.tanks or country.ships or country.planes or country.developed \
                or country.radioactive or country.landmark_owner is not None:
            return False  # abandoning destroys these, and a developed country pays double to the next owner
        return not self._holds_continent_of(country.name)

    def _buffer_best(self, phase):
        """(gain, country to empty, country the troops go to, troops) of the best
        vacate, or None."""
        engine, player, p = self.engine, self.player, self.params
        owned = self._owned()
        if len(owned) < p["buffer_keep"] or not self._buffer_event_ok():
            return None
        weight = p["next_turn_weight"]
        risk = self._elimination_risk()
        best = None
        for country in owned:
            if not self._buffer_eligible(country):
                continue
            exposure = self._danger(country)
            if exposure < p["buffer_min_exposure"]:
                continue
            reachable = phase._land_flood_fill(country.name) - {country.name}
            if not reachable:
                continue
            troops = country.units
            hold = self._hold_value(country)
            near = {n for n in self._links(country.name) if engine.countries[n].owner is player}
            garrison = engine.initial_country_units.get(country.name, 2)
            for name in sorted(reachable, key=lambda n: (-(n in near), -engine.countries[n].units, n))[:6]:
                target = engine.countries[name]
                names = near | {name}

                def value(n):
                    return self._position_value(engine.countries[n], engine.countries[n].units, weight, 1)
                before = sum(value(n) for n in names | {country.name})
                # The elimination model only sees adjacent enemy stacks: emptying the front country
                # would make the bot "safe" in its own eyes. Keep the risk fixed so the what-if
                # measures the buffer, not that blind spot.
                self._risk_frozen = risk
                try:
                    with self._what_if((country, "owner", engine.default_player), (country, "units", garrison),
                                       (target, "units", target.units + troops)):
                        after = sum(value(n) for n in names if engine.countries[n].owner is player)
                finally:
                    self._risk_frozen = None
                    self._cache = {}
                # what is gained: the troops (and the card the taker would have earned); what is lost: the country
                gain = after - before - hold + exposure * p["buffer_card_weight"] * p["buffer_card_value"]
                if best is None or gain > best[0]:
                    best = (gain, country, target, troops)
        return best

    def _buffer_run(self, phase):
        """Empty the best candidate as the turn's one move. True if it did."""
        best = self._buffer_best(phase)
        if best is None or best[0] <= self.params["buffer_min_gain"]:
            return False
        gain, country, target, troops = best
        target.units += troops
        country.units = 0
        self._vacated[country.name] = self.manager.turn_num
        phase.abandon(country)
        self.player.repositioned_this_turn = True
        self.engine.log_action(self.player, Msg(" withdrew {} troops from {} to {}",
                                                troops, country.name, target.name))
        self._say("withdraws from {} (mouse buffer, {:+.1f})".format(country.name, gain))
        return True

    def _retake_ok(self, target):
        """A country the bot emptied is left alone for a few rounds while it is exposed."""
        since = self._vacated.get(target.name)
        if since is None or self.manager.turn_num - since >= self.params["buffer_cool"] * len(self.engine.players):
            return True
        return self._danger(target, 2, 0, 0) <= self.params["buffer_min_exposure"]

    def _reposition(self, phase):
        """The one move a turn: troops (and their tanks) from where they're
        worth least to where they're worth most (see _position_value), over
        land -- or over sea with a ship or plane going along; or a lone
        plane or ship to where it opens up attacks over sea. True if
        something moved."""
        engine, player = self.engine, self.player
        if self.params["buffer"] and self._buffer_run(phase):
            return True
        weight = self.params["next_turn_weight"]
        oil_cost = self._weights()["oil"]
        move_assets = self.params["asset_move"]

        def value(country, units, ships=None, planes=None, tanks=None):
            return self._position_value(country, units, weight, 1, ships, planes, tanks)

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
                # The stack's tanks go along when about half of it does.
                tk = origin.tanks if n and 2 * n >= origin.units - 1 else 0
                for plane in planes:
                    for ship in ships:
                        if (n, plane, ship) == (0, 0, 0) or (ship and not n):
                            continue  # nothing moves / a ship needs a troop aboard
                        loss = now - (value(origin, origin.units - n, origin.ships - ship, origin.planes - plane,
                                            origin.tanks - tk if move_assets else None))
                        for target in targets:
                            if ship and target.name not in by_sea:
                                continue
                            if n and target.name not in land and not (ship or plane):
                                continue  # troops can't cross the sea alone
                            gain = self._jitter(
                                value(target, target.units + n, target.ships + ship, target.planes + plane,
                                      target.tanks + tk if move_assets else None)
                                - value(target, target.units) - loss - plane * oil_cost)
                            if gain > best_gain:
                                best_gain, best = gain, (origin, target, n, ship, plane, tk)
        if move_assets:
            # Assets alone: tanks, a plane, or a ship with one troop to steer it, to
            # wherever they are worth the most -- out of reach of the enemy, say.
            for origin in self._owned():
                if not (origin.ships or origin.tanks or origin.planes):
                    continue
                reach = sorted(self._own_reach(origin.name) - {origin.name})
                if not reach:
                    continue
                by_sea = phase._sea_flood_fill(origin.name)
                now = value(origin, origin.units, origin.ships, origin.planes, origin.tanks)
                for ship in ((0, 1) if origin.ships and origin.units >= 2 else (0,)):
                    for tk in ((0, origin.tanks) if origin.tanks else (0,)):
                        for plane in ((0, 1) if origin.planes and player.oil >= 1 else (0,)):
                            if not (ship or tk or plane):
                                continue
                            loss = now - value(origin, origin.units - ship, origin.ships - ship,
                                               origin.planes - plane, origin.tanks - tk)
                            for name in reach:
                                if ship and name not in by_sea:
                                    continue
                                target = engine.countries[name]
                                gain = self._jitter(
                                    value(target, target.units + ship, target.ships + ship, target.planes + plane,
                                          target.tanks + tk)
                                    - value(target, target.units, target.ships, target.planes, target.tanks)
                                    - loss - plane * oil_cost)
                                if gain > best_gain:
                                    best_gain, best = gain, (origin, target, ship, ship, plane, tk)
        if best is None:
            return False
        origin, target, n, ship, plane, tanks = best
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
        # Logged like MovementPhase._log_move does for a human's move.
        moved = [Msg("{} {}", k, word) for k, word in
                 ((n, "troops"), (tanks, "tanks"), (ship, "ships"), (plane, "planes")) if k]
        engine.log_action(player, Msg(" moved {} from {} to {}", Join(moved), origin.name, target.name))
        extra =" with a plane" if plane else " by ship" if ship else ""
        self._say("moves {} troops from {} to {}{}".format(n, origin.name, target.name, extra) if n > ship
                  else "moves {} from {} to {}".format(
                      ", ".join("{} {}".format(k, word) for k, word in
                                ((tanks, "tanks"), (ship, "ship"), (plane, "plane")) if k), origin.name, target.name))
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
