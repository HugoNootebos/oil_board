"""
A basic heuristic computer player.

A player with `is_bot` set doesn't get mouse input: on their turn,
TurnManager.update hands control to BotController.update, which still lets
the current phase draw itself (with all clicks withheld) and then makes one
decision at a time, with a short pause in between so people can follow
along. It works through the same phase methods the buttons use
(AttackPhase.roll_attack, ShopPhase.place_unit, TurnManager.end_phase, ...),
so the rules stay in phases.py.

The one moment a bot's turn waits on someone else is a human defender
picking their tanks / defence dice; that phase screen then runs normally.
The other way round, a bot that's attacked picks its defending tanks in
defence_tanks() and always rolls every defence die.

The strategy, per phase:
  - reinforce: trade a card set (for food when about to starve, otherwise
    troops), put the troops where they make the best attack likely (or,
    failing that, on the most threatened border), then buy something;
  - attack: keep making the attack with the best chance x value (exact
    Risk odds incl. forts, tanks and event bonuses), as long as the chance
    is good enough, and back off when a fight turns bad;
  - move: develop a safe country if affordable, move the biggest idle
    garrison to the border that needs it most, and place any owed
    pagoda/torii.
"""

import itertools
from functools import lru_cache

import pygame as pg

from board import CONTINENTS
from events import WrongButton, Ebola, ClimateHoax
from models import CardMenu
from phases import CONTINENT_CARD_BONUS

# Pauses (ms) so a bot's turn can be followed on screen.
STEP_MS = 400      # between actions
DICE_MS = 900      # how long a roll stays visible before it's resolved
NOTICE_MS = 2500   # a message on a bot's turn closes by itself after this

ATTACK_MIN_P = 0.65   # start an attack only with at least this chance
RETREAT_P = 0.25      # call a running attack off below this chance
DEPLOY_TARGET_P = 0.8  # reinforce an attack until it's this likely

CONTINENT_OF = {name: continent for continent, members in CONTINENTS.items() for name in members}


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
def conquer_probability(attackers, defenders, mods=(0, 0, 0, 0)):
    """Chance that `attackers` rolling troops (up to 3 dice a roll) wipe out
    `defenders` (up to 2 dice) if the attack is kept up to the end."""
    if defenders <= 0:
        return 1.0
    if attackers <= 0:
        return 0.0
    attackers, defenders = min(attackers, 60), min(defenders, 60)
    return sum(
        p * conquer_probability(attackers - al, defenders - dl, mods)
        for al, dl, p in _round_outcomes(min(attackers, 3), min(defenders, 2), *mods)
    )


def defence_tanks(engine, country):
    """How many of its tanks a bot defending `country` uses (1 oil each)."""
    return min(country.tanks, country.owner.oil)


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

    @property
    def engine(self):
        return self.manager.engine

    @property
    def player(self):
        return self.engine.players[self.engine.turn]

    @property
    def notice_ms(self):
        return 0 if self.fast else NOTICE_MS

    # --- per-frame driver --------------------------------------------------

    def update(self):
        engine, manager, player = self.engine, self.manager, self.player
        key = (manager.turn_num, engine.turn)
        if key != self._turn_key:
            self._turn_key = key
            self._done = set()
            self._failed = set()

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
        self._next_at = pg.time.get_ticks() + STEP_MS

    def _ready(self, player):
        """Pace the bot: a pause after every action, and a longer one while
        freshly rolled dice are on screen."""
        if self.fast:
            return True
        now = pg.time.get_ticks()
        state = (player.attack, player.subattack)
        if state != self._last_state:
            self._last_state = state
            wait = DICE_MS if state == (1, 4) else STEP_MS
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
        if self.manager.must_trade(player):
            self._trade()
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
        links = {}
        for c in self.engine.connections:
            if name in c.connection:
                for other in c.connection:
                    if other != name and links.get(other) != "land":
                        links[other] = c.kind
        return links

    def _owned(self, player=None):
        player = player or self.player
        return [c for c in self.engine.countries.values() if c.owner is player]

    def _is_real(self, player):
        return player is not self.engine.default_player

    def _threat(self, name):
        """Largest force another real player has next to `name`."""
        player = self.player
        worst = 0
        for other in self._links(name):
            c = self.engine.countries[other]
            if c.owner is not player and self._is_real(c.owner):
                worst = max(worst, c.units)
        return worst

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

    def _target_value(self, target):
        engine, manager, player = self.engine, self.manager, self.player
        value = 1.0
        if target.radioactive == 0:
            mult = 2 if target.developed else 1
            value += mult * (0.25 * target.food + 0.5 * target.wood + 0.6 * target.steel
                             + 0.7 * target.oil + 0.8 * target.nuclear)
        value += 0.4 * target.troops
        if target.airport:
            value += 0.5
        continent = CONTINENT_OF.get(target.name)
        if continent is not None:
            members = CONTINENTS[continent]
            others = [engine.countries[n] for n in members if n != target.name]
            if all(c.owner is player for c in others):
                value += 3 + 2 * CONTINENT_CARD_BONUS.get(continent, 0)
            elif self._is_real(target.owner) and all(c.owner is target.owner for c in others):
                value += 2  # breaks their continent
        if self._is_real(target.owner):
            value += 0.5 if manager.conquered_enemy_this_turn else 1.5  # the turn's card
            if not any(c.owner is target.owner and c is not target for c in engine.countries.values()):
                value += 4  # eliminates them: their resources and cards
        return value

    def _can_reach(self, from_c, kind):
        """Whether an attack from from_c over a `kind` link can be made."""
        return kind == "land" or from_c.ships > 0 or (from_c.planes > 0 and self.player.oil >= 1)

    def _attack_options(self, extra=None):
        """(from, to, over_land) for every attack the bot could start now.
        `extra` ({name: troops}) pretends some troops were added first."""
        engine, player = self.engine, self.player
        event = self.manager.current_event
        options = []
        for from_c in self._owned():
            units = from_c.units + (extra or {}).get(from_c.name, 0)
            if units < 2:
                continue
            if event is not None and not event.can_attack_from(engine, from_c):
                continue
            for other, kind in self._links(from_c.name).items():
                target = engine.countries[other]
                if target.owner is player or not self._can_reach(from_c, kind):
                    continue
                if event is not None and not event.can_attack_target(engine, target):
                    continue
                if kind == "sea" and type(event).__name__ == "StormAtSea":
                    continue  # pirates: not worth a third of the army
                options.append((from_c, target, kind == "land"))
        return options

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
            for name, n in self._deploy_plan(manager.reinforcements).items():
                self.engine.countries[name].units += n
            manager.reinforcements = 0
            manager.all_reinforcements_deployed = True
            return
        if "shop" not in self._done:
            if not self._shop():
                self._done.add("shop")
            return
        manager.end_phase()

    def _deploy_boat(self):
        """The free boat goes where it opens the most sea attacks: the
        country with the most sea routes to countries it doesn't own."""
        engine = self.engine

        def sea_targets(name):
            return sum(1 for c in engine.connections
                       if c.kind == "sea" and name in c
                       and any(engine.countries[o].owner is not self.player for o in c.connection if o != name))

        best = max(self._owned(), key=lambda c: (sea_targets(c.name), c.units))
        self.manager.phases[0].deploy_boat(best)

    def _starve(self):
        """Starvation: the troops lost come off the biggest, safest stacks."""
        engine, manager, player = self.engine, self.manager, self.player
        phase = manager.phases[0]
        for _ in range(phase.starved):
            owned = [c for c in self._owned() if c.units > 0]
            if not owned:
                break
            victim = max(owned, key=lambda c: (c.units - self._threat(c.name), c.units))
            victim.units -= 1
        for country in self._owned():
            if country.units == 0:
                phase.abandon(country)
        manager.initial_units = {n: c.units for n, c in engine.countries.items()}
        player.subattack = 1

    def _deploy_plan(self, troops):
        """{country: troops}: first make the most valuable attacks likely
        enough (cheapest first), then shore up the most threatened border."""
        plan = {}
        while troops > 0:
            best = None
            for from_c, target, _ in self._attack_options(extra={n: troops for n in self._frontier_names()}):
                have = from_c.units + plan.get(from_c.name, 0)
                value = self._target_value(target)
                if self._win_probability(from_c, target, attackers=have - 1) >= DEPLOY_TARGET_P:
                    continue  # likely enough already
                for k in range(1, troops + 1):
                    if self._win_probability(from_c, target, attackers=have + k - 1) >= DEPLOY_TARGET_P:
                        score = value / k
                        if best is None or score > best[0]:
                            best = (score, from_c.name, k)
                        break
            if best is None:
                break
            _, name, k = best
            plan[name] = plan.get(name, 0) + k
            troops -= k
            if len(plan) >= 3:
                break  # don't spread too thin
        if troops > 0:
            # What's left goes to the border facing the biggest enemy force
            # (or simply the biggest border stack).
            frontier = self._frontier_names() or [c.name for c in self._owned()]
            name = max(frontier, key=lambda n: (
                self._threat(n) - self.engine.countries[n].units - plan.get(n, 0),
                self.engine.countries[n].units))
            plan[name] = plan.get(name, 0) + troops
        return plan

    def _frontier_names(self):
        return [c.name for c in self._owned() if self._frontier(c.name)]

    # --- cards -----------------------------------------------------------

    def _trade(self):
        """Trade a set of cards if there is one; True if it did."""
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
        menu.trade_cards = [card for card in player.cards if card.use]
        production = self.engine.production(player)
        reward = "food" if player.food + 2 * production["food"] < 0 else "helmets"
        mult = dict((r, m) for _, r, m in CardMenu.TRADE_OPTIONS)[reward]
        menu._execute_trade(reward, int(round(base * mult)))
        return True

    def _recruit(self):
        """Troops from a card trade outside the reinforcement phase."""
        phase = self.manager.phases[4]
        for name, n in self._deploy_plan(phase.pool).items():
            self.engine.countries[name].units += n
        phase.pool = 0
        self.manager.end_trade_recruit()

    # --- shop ----------------------------------------------------------------

    def _shop(self):
        """Buy one thing (the shop is only used from the reinforcement
        phase, where everything can be bought). True if it bought something."""
        engine, player = self.engine, self.player
        shop = self.manager.phases[3]

        # Nuke the biggest enemy army next to us.
        if player.nuclear >= shop._cost({"nuclear": 5})["nuclear"]:
            targets = [engine.countries[n] for n in shop._nuke_targets()]
            targets = [c for c in targets if self._is_real(c.owner) and c.units >= 6]
            if targets:
                target = max(targets, key=lambda c: c.units)
                shop.drop_nuke(target.name)
                self.manager.notices.append("{} nuked {}!".format(player.name, target.name))
                return True

        frontier = [engine.countries[n] for n in self._frontier_names()]
        if not frontier:
            return False

        # A tank on the strongest attacker, if there's oil to run it.
        tank_cost = shop._cost({"steel": 20})
        tanks = sum(c.tanks for c in self._owned())
        if player.steel >= tank_cost["steel"] and player.oil + engine.production(player)["oil"] > tanks:
            best = max(frontier, key=lambda c: c.units)
            shop.place_unit("tanks", tank_cost, best.name)
            return True

        # A fort where another player threatens us most.
        threatened = [c for c in frontier if self._threat(c.name) > 0 and c.fort_lvl < 3
                      and player.wood >= shop.fort_cost(c)]
        if threatened:
            worst = max(threatened, key=lambda c: self._threat(c.name) - c.units)
            if shop.place_fort(worst.name):
                return True

        # A ship where the only way forward is over sea.
        ship_cost = shop._cost({"wood": 15})
        if player.wood >= ship_cost["wood"]:
            for c in sorted(frontier, key=lambda c: -c.units):
                links = self._links(c.name)
                open_land = any(k == "land" and engine.countries[o].owner is not player for o, k in links.items())
                open_sea = any(k == "sea" and engine.countries[o].owner is not player for o, k in links.items())
                if c.ships == 0 and open_sea and not open_land and c.units >= 4:
                    shop.place_unit("ships", ship_cost, c.name)
                    return True
        return False

    # --- attack --------------------------------------------------------------

    def _attack(self):
        player = self.player
        attack = self.manager.phases[1]
        sub = player.subattack
        if sub in (0, 1):
            self._start_best_attack()
        elif sub == 6:
            player.subattack = 2
        elif sub == 2:
            from_c = self.engine.countries[attack.attack_from]
            target = self.engine.countries[attack.defence_country]
            chance = self._win_probability(from_c, target, active_tanks=attack.active_tanks)
            if chance < RETREAT_P:
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
        best = None
        for from_c, target, land in self._attack_options():
            if (from_c.name, target.name) in self._failed:
                continue
            chance = self._win_probability(from_c, target)
            if chance < ATTACK_MIN_P:
                continue
            score = chance * self._target_value(target)
            if best is None or score > best[0]:
                best = (score, from_c, target, land)
        if best is None:
            manager.end_phase()
            return
        _, from_c, target, land = best
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
        # tanks only if they make a real difference.
        if self._win_probability(from_c, target, active_tanks=0) >= 0.9:
            attack.active_tanks = 0
        if land or attack.selected_ships > 0:
            attack.selected_planes = 0
        else:
            # Over sea without a ship: one plane (1 oil) carries them.
            attack.selected_planes = 1
            attack.active_tanks = min(attack.active_tanks, max(player.oil - 1 + attack.prepaid_planes, 0))

    def _move_in(self):
        """After a conquest: push forward, keeping back only what the old
        country needs against real players next to it."""
        engine = self.engine
        attack = self.manager.phases[1]
        from_c = engine.countries[attack.attack_from]
        target = engine.countries[attack.defence_country]
        total = from_c.units + target.units
        least = attack.conquest_units
        if not self._frontier(target.name):
            moved = least
        elif not self._frontier(from_c.name):
            moved = total - 1
        else:
            keep = min(self._threat(from_c.name), (total - 1) // 2)
            moved = total - 1 - keep
        moved = max(least, min(moved, total - 1)) if total > least else total
        target.units, from_c.units = moved, total - moved
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
            options = []
            for c in self._owned():
                cost = phase.develop_cost(c)
                if c.developed or not sum(cost.values()) or self._threat(c.name):
                    continue
                if all(getattr(player, r) >= n for r, n in cost.items()):
                    options.append(c)
            if options:
                phase.develop(max(options, key=lambda c: sum(phase.develop_cost(c).values())))
                return

        if not player.repositioned_this_turn and "reposition" not in self._done:
            self._done.add("reposition")
            if self._reposition(phase):
                return

        for name in sorted(manager.landmarks_owed):
            manager.place_landmark(name)
        manager.end_phase()

    def _reposition(self, phase):
        """The biggest garrison with nothing to fight marches (over land) to
        the border that needs it most. True if something moved."""
        engine = self.engine
        idle = [c for c in self._owned() if c.units > 1 and not self._frontier(c.name)]
        for origin in sorted(idle, key=lambda c: -c.units):
            reachable = phase._land_flood_fill(origin.name) - {origin.name}
            borders = [engine.countries[n] for n in reachable if self._frontier(n)]
            if not borders:
                continue
            target = max(borders, key=lambda c: (self._threat(c.name) - c.units, self._best_attack_value(c)))
            target.units += origin.units - 1
            origin.units = 1
            self.player.repositioned_this_turn = True
            return True
        return False

    def _best_attack_value(self, country):
        values = [self._target_value(self.engine.countries[o])
                  for o in self._links(country.name) if self.engine.countries[o].owner is not self.player]
        return max(values, default=0)

    # --- event picks -----------------------------------------------------------

    def _event_pick(self):
        engine, player = self.engine, self.player
        phase = self.manager.phases[5]
        if phase.predicate is None:
            return  # the phase bails out on its own
        valid = [c for c in engine.countries.values() if phase.predicate(c)]
        if not valid:
            return
        event = self.manager.current_event
        if isinstance(event, WrongButton):
            # A nuke: the biggest army that isn't ours, preferably a player's.
            choice = max(valid, key=lambda c: (c.owner is not player, self._is_real(c.owner), c.units))
        elif isinstance(event, Ebola):
            choice = min(valid, key=lambda c: (self._target_value(c), c.units))  # losing it anyway
        elif isinstance(event, ClimateHoax):
            choice = max(valid, key=lambda c: (self._frontier(c.name), c.units))  # a free plane
        else:
            choice = max(valid, key=lambda c: (c.owner is player, c.units))
        phase.pick(choice)
