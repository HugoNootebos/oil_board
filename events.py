"""World events: randomly drawn, board-wide effects that come and go on
their own schedule (see TurnManager's event-scheduling code in phases.py
for the timing rules). This module only holds *what* an event is and
does -- one `Event` per entry in EVENTS -- not *when* it runs.

To add an event, add an `Event(...)` to EVENTS below. `on_start(engine)`
runs once, the moment the event becomes active (right as the affected
round's first turn begins); `on_end(engine)` runs once, the moment its
round is over. An effect that needs to change something every turn while
active (e.g. a production penalty) should hook into the relevant game
logic directly (income calc, combat, etc.) and check whether it's the
active event there, via `engine.turn_manager.current_event`, rather than
trying to do everything from on_start/on_end -- for example:

    class Drought(Event):
        def is_active(self, engine):
            return engine.turn_manager.current_event is self

Then in ReinforcementPhase._start_turn, wherever food is added:
    if not DROUGHT.is_active(engine):
        player.food += country.food * mult
"""

import numpy as np

from board import CONTINENTS


class Event:
    def __init__(self, name, description=""):
        self.name = name
        self.description = description

    def on_start(self, engine):
        """Called once, when this event becomes the active one."""

    def on_end(self, engine):
        """Called once, when this event's round is over."""

    def modify_income(self, engine, country, player, amounts):
        """Called for every one of `player`'s countries as their income is
        worked out (and again for the sidebar's live preview), only while
        this event is the active one. `amounts` is {resource: amount}
        about to be credited to `player` (the country's owner) this turn
        -- already past the radioactive/idle/developed multiplier, so an
        event that only redirects or reshapes income doesn't need to
        redo any of that. Return (target_player, amounts): who the
        amounts should actually go to, and what they should be. The
        default leaves both unchanged."""
        return player, amounts

    def on_conquest(self, engine, player, country, previous_owner):
        """Called once for every successful conquest -- interactive attack
        or scripted event-attack alike -- while this event is the active
        one, with the player who just took `country` and whoever (a real
        player, or engine.default_player) held it right before. The
        default does nothing."""

    def on_turn_start(self, engine, player):
        """Called once at the very start of `player`'s turn (before income
        is worked out), while this event is the active one. An event that
        needs to force the player into some other action -- e.g. picking
        a target -- can set player.attack/subattack here to divert them
        (see WrongButton for the pattern, using EventTargetPhase). The
        default does nothing."""

    def attack_bonus(self, engine, attack_from):
        """Extra amount added to every one of the attacker's dice when
        attacking from the country `attack_from`, while this event is the
        active one -- stacks with the active-tanks bonus (which only
        boosts the single highest die). The default is 0."""
        return 0

    def sea_attack_check(self, engine):
        """Called right as the dice are about to be rolled for an attack
        launched over a sea route (never for a land attack, or for the
        Movement phase's peaceful repositioning), while this event is the
        active one. Return True to have the attacker's whole committed
        force for this roll wiped out instead of anything being rolled at
        all. The default never intervenes."""
        return False

    def on_player_eliminated(self, engine, victor, loser):
        """Called once, from within a normal interactive conquest, when it
        happens to eliminate `loser` (whoever conquered the finishing
        blow is `victor`), while this event is the active one. The game's
        own resource/card loot (everything but food) already happens
        regardless. The default does nothing."""

    def free_claim_allowed(self, engine, country):
        """Called (only for a country the attacking player could
        otherwise normally reach -- adjacency is already checked) to ask
        whether `country` can be claimed outright instead of fighting for
        it, while this event is the active one. The default is always
        False."""
        return False

    def can_attack_from(self, engine, country):
        """Whether `country` may be used as an attacker's origin, while
        this event is the active one. The default is always True."""
        return True

    def can_attack_target(self, engine, country):
        """Whether `country` may be attacked, while this event is the
        active one. The default is always True."""
        return True

    def discount_shop_cost(self, engine, cost):
        """`cost` is a {resource: amount} dict for something in the shop
        (a base price, never an already-adjusted one). Return the cost to
        actually display and charge, while this event is the active one.
        The default leaves it unchanged."""
        return cost

    def reinforcement_override(self, engine, player, reinforcements):
        """Called once per player's turn, right after their normal
        reinforcement count (troops // 3 + 3) is computed, while this
        event is the active one. Return the count to actually use. The
        default leaves it unchanged."""
        return reinforcements

    def abandoned_units(self, engine, country, units):
        """Called when `country` falls back to engine.default_player
        (Phase.abandon), with `units` the garrison it would normally reset
        to (its board.py starting troops), while this event is the active
        one. Return the garrison to actually use. The default leaves it
        unchanged."""
        return units

    def dice_penalty(self, engine, player):
        """How much to subtract from every one of `player`'s dice --
        attacking or defending alike -- while this event is the active
        one. engine.default_player never has a penalty applied, even if
        it technically "owns" whatever the check is based on. The default
        is always 0."""
        return 0

    def check_pending(self, engine, player):
        """Called every frame at a calm point of the current `player`'s
        turn (see TurnManager._check_event_pending), while this event is
        the active one. An effect that couldn't happen when the event
        started -- its country still belonged to mouse, or there was a
        tie -- happens here the moment that changes, with a notice in
        engine.turn_manager.notices for the pop-up. Once the event has
        ended this is never called again, so the chance is gone. Return
        True if anything happened. The default does nothing."""
        return False

    def save_state(self, engine):
        """JSON-able state this event needs kept across a save/load while
        it's the active one (by name, never object references)."""
        return {}

    def load_state(self, engine, data):
        """Restore what save_state returned (`data` is {} for an older
        save)."""

    def __repr__(self):
        return "Event({!r})".format(self.name)


def most_stationed_troops(engine, continent_name):
    """The real player (never engine.default_player) with the most units
    stationed across a continent's countries, or None if no real player
    holds any of it yet -- or if there's a tie for the most, which counts
    as no clear leader rather than arbitrarily picking one."""
    totals = {}
    for name in CONTINENTS[continent_name]:
        country = engine.countries[name]
        if country.owner is engine.default_player:
            continue
        totals[country.owner] = totals.get(country.owner, 0) + country.units
    if not totals:
        return None
    best = max(totals.values())
    leaders = [p for p, n in totals.items() if n == best]
    return leaders[0] if len(leaders) == 1 else None


class JapanGoesCrazy(Event):
    def __init__(self):
        super().__init__(
            name="De Japanners worden gek",
            description="Japan krijgt 5 extra troepen en er ontstaan landroutes tussen Japan en elk ander land.",
        )
        # The +5 troops (permanent) go to whoever holds Japan -- never to
        # mouse: with Japan still mouse's they go to the first player to
        # take it during the event (check_pending). The land routes are
        # only for the round. What each of Japan's own routes was before (by the name of
        # the country at the other end, so it survives a save/load) is
        # remembered here so on_end can put it back.
        self.original_kinds = {}
        self.troops_pending = False

    def on_start(self, engine):
        from models import Connection
        japan = engine.countries["Japan"]
        self.troops_pending = japan.owner is engine.default_player
        if not self.troops_pending:
            japan.units += 5
        self.original_kinds = {}
        linked = set()
        for connection in engine.connections:
            if "Japan" in connection:
                other = next(n for n in connection.connection if n != "Japan")
                self.original_kinds[other] = connection.kind
                connection.kind = "land"
                linked |= connection.connection
        # Plus a land route to every country Japan isn't already linked to,
        # only for the round (removed again in on_end, and kept across a
        # save/load).
        for name in engine.countries:
            if name != "Japan" and name not in linked:
                route = Connection({"Japan", name}, "land")
                route.temporary = True
                engine.connections.add(route)

    def on_end(self, engine):
        from board import get_connections
        # A save from mid-event made before this was remembered: fall back
        # to how the map in board.py defines the route.
        board_kinds = {next(n for n in c.connection if n != "Japan"): c.kind
                       for c in get_connections() if "Japan" in c}
        for connection in engine.connections:
            if "Japan" in connection and not getattr(connection, "temporary", False):
                other = next(n for n in connection.connection if n != "Japan")
                connection.kind = self.original_kinds.get(other, board_kinds.get(other, connection.kind))
        self.original_kinds = {}
        self.troops_pending = False
        # Removed by flag rather than a remembered list, so this also works
        # after the game was saved and loaded mid-event.
        for connection in [c for c in engine.connections if getattr(c, "temporary", False)]:
            engine.connections.discard(connection)

    def check_pending(self, engine, player):
        japan = engine.countries["Japan"]
        if not self.troops_pending or japan.owner is engine.default_player:
            return False
        self.troops_pending = False
        japan.units += 5
        engine.turn_manager.notices.append([self.name, "{} took Japan: +5 troops there".format(japan.owner.name)])
        return True

    def save_state(self, engine):
        return {"original_kinds": dict(self.original_kinds), "troops_pending": self.troops_pending}

    def load_state(self, engine, data):
        self.original_kinds = {n: k for n, k in data.get("original_kinds", {}).items() if n in engine.countries}
        self.troops_pending = data.get("troops_pending", False)


class NativesFightBack(Event):
    def __init__(self):
        super().__init__(
            name="inboorlingen vechten terug",
            description="Mouse vecht met 5 troepen tegen de landen: China, Outback, Sovjet-Unie, Peru en Canada.",
        )

    # "Sovjet-Unie" in the description is this board's "Sovjet-Rusland".
    TARGETS = ("China", "Outback", "Sovjet-Rusland", "Peru", "Canada")
    TROOPS = 5

    # Mouse attacks each target like a player would, one at a time, on
    # screen (phases.MouseAttackPhase, attack == 6): `queue` is what's
    # still to be attacked, `return_to` where the current player goes
    # back to afterwards. A target mouse still holds is left alone for
    # now (`pending`): it's attacked the moment a player takes it.
    queue = ()
    pending = ()
    return_to = (0, 0)

    def on_start(self, engine):
        self.pending, self.queue = [], []
        for name in self.TARGETS:
            if engine.countries[name].owner is engine.default_player:
                self.pending.append(name)
            else:
                self.queue.append(name)

    def check_pending(self, engine, player):
        for name in list(self.pending):
            country = engine.countries[name]
            if country.owner is engine.default_player:
                continue
            self.pending.remove(name)
            self.queue.append(name)
            engine.turn_manager.notices.append([
                self.name, "{} took {}: the natives attack it with {} troops".format(
                    country.owner.name, name, self.TROOPS)])
        if not self.queue or player.attack == 6:
            return False
        self.return_to = (player.attack, player.subattack if player.attack == 0 else 0)
        player.attack, player.subattack = 6, 0
        return True

    def on_end(self, engine):
        self.pending, self.queue = [], []

    def save_state(self, engine):
        return {"pending": list(self.pending), "queue": list(self.queue), "return_to": list(self.return_to)}

    def load_state(self, engine, data):
        self.pending = [n for n in data.get("pending", []) if n in engine.countries]
        self.queue = [n for n in data.get("queue", []) if n in engine.countries]
        self.return_to = tuple(data.get("return_to", (0, 0)))


class DevelopmentAid(Event):
    def __init__(self):
        super().__init__(
            name="Ontwikkelingshulp",
            description="Alle grondstoffen van Europa gaan naar de speler met de meeste Afrikaanse troepen.",
        )

    def modify_income(self, engine, country, player, amounts):
        if country.name not in CONTINENTS["Europe"]:
            return player, amounts
        beneficiary = most_stationed_troops(engine, "Africa")
        return (beneficiary, amounts) if beneficiary is not None else (player, amounts)


class EmperorsHonor(Event):
    def __init__(self):
        super().__init__(
            name="Eer van de keizer",
            description="De speler die deze ronde de meeste gebieden verovert claimt alle landen om Japan heen.",
        )
        self.conquest_counts = {}

    def on_start(self, engine):
        self.conquest_counts = {}  # fresh tally for this round

    def on_conquest(self, engine, player, country, previous_owner):
        if player is engine.default_player:
            return
        self.conquest_counts[player] = self.conquest_counts.get(player, 0) + 1

    def on_end(self, engine):
        if not self.conquest_counts:
            return  # nobody conquered anything this round
        best = max(self.conquest_counts.values())
        leaders = [p for p, n in self.conquest_counts.items() if n == best]
        if len(leaders) != 1:
            return  # tied -- nothing happens
        winner = leaders[0]
        for connection in engine.connections:
            if "Japan" not in connection:
                continue
            for name in connection.connection:
                if name == "Japan":
                    continue
                country = engine.countries[name]
                # Wiped out the same way a regular conquest wipes out
                # whatever the previous owner had stationed there (see
                # AttackPhase._conquer) -- radioactivity, if any, is left
                # alone, matching that too.
                country.owner = winner
                country.units = 1
                country.ships = 0
                country.tanks = 0
                country.planes = 0
                country.fort_lvl = 0


class WrongButton(Event):
    def __init__(self):
        super().__init__(
            name="Verkeerde knop",
            description="Noord-Korea gooit per ongeluk een atoombom op een land in Azië.",
        )
        self.triggered = False

    # Whoever holds Noord-Korea fires the moment the event starts -- even
    # outside their own turn -- or, if mouse holds it, whoever takes it
    # while the event lasts, the moment they do (check_pending). Once per
    # event: `triggered` is only set once the target is actually picked,
    # so a save loaded mid-pick asks again.

    def on_start(self, engine):
        self.triggered = False
        owner = engine.countries["Noord-Korea"].owner
        if owner is not engine.default_player:
            current = engine.players[engine.turn]
            self._launch(engine, owner, (current.attack, current.subattack),
                         "{} controls Noord-Korea".format(owner.name))

    def check_pending(self, engine, player):
        owner = engine.countries["Noord-Korea"].owner
        if self.triggered or owner is engine.default_player:
            return False
        return_to = (player.attack, player.subattack if player.attack == 0 else 0)
        self._launch(engine, owner, return_to, "{} took Noord-Korea".format(owner.name))
        return True

    def save_state(self, engine):
        return {"triggered": self.triggered}

    def load_state(self, engine, data):
        self.triggered = data.get("triggered", False)

    def _strike(self, engine, chooser, country):
        self.triggered = True
        country.units = country.units // 2  # rounded down
        country.radioactive += 3
        country.bombed_by = chooser
        if country.units == 0:
            # Same as the shop's nuke (ShopPhase.drop_nuke): nobody is left
            # to hold it, so it goes back to mouse; if it was a player's
            # last country, the chooser eliminated them.
            manager = engine.turn_manager
            phase = manager.phases[0]
            conquered = manager.conquered_enemy_this_turn
            phase.take_last_country(chooser, country)
            if chooser is not engine.players[engine.turn]:
                # The turn's conquest card belongs to whoever's turn it is.
                manager.conquered_enemy_this_turn = conquered
            phase.abandon(country)

    def _launch(self, engine, chooser, return_to, why):
        """`chooser` (Noord-Korea's owner) picks the Asian country to nuke:
        a bot straight away, a human on the pick screen -- which takes over
        the current turn for a moment if it isn't theirs."""
        manager = engine.turn_manager
        asia = [c for c in engine.countries.values() if c.name in CONTINENTS["Asia"]]
        if chooser.is_bot:
            # The biggest army that isn't theirs, preferably a player's.
            target = max(asia, key=lambda c: (c.owner is not chooser,
                                              c.owner is not engine.default_player, c.units))
            self._strike(engine, chooser, target)
            manager.notices.append([self.name, "{}: {} drops the nuke on {}".format(why, chooser.name, target.name)])
            return
        manager.notices.append([self.name, "{}: pick a country in Asia for the nuke".format(why)])
        manager.phases[5].start(
            predicate=lambda c: c.name in CONTINENTS["Asia"],
            on_pick=self._strike,
            prompt="{}: kies een land in Azie voor de atoombom".format(chooser.name),
            return_to=return_to,
            chooser=chooser,
        )
        current = engine.players[engine.turn]
        current.attack, current.subattack = 5, 0


# Filled in one at a time as they're described -- 23 total once complete.
class JapaneseAggression(Event):
    def __init__(self):
        super().__init__(
            name="japanse agressie",
            description="Als Japan aanvalt mag het 1 optellen bij elke dobbelsteen.",
        )

    def attack_bonus(self, engine, attack_from):
        return 1 if attack_from.name == "Japan" else 0


class StormAtSea(Event):
    def __init__(self):
        super().__init__(
            name="storm of zee",
            description="Piraten brengen alle legers om die over een zee-route reizen met een kans van 1/3.",
        )

    def sea_attack_check(self, engine):
        return np.random.random() < 1 / 3


class ChildSoldiers(Event):
    def __init__(self):
        super().__init__(
            name="kindsoldaten",
            description="Voor elk Afrikaans land dat een speler verovert ontvangt hij één extra kaertske (géén Mouse).",
        )

    def on_conquest(self, engine, player, country, previous_owner):
        if player is engine.default_player:
            return
        if previous_owner is engine.default_player:
            return  # "géén Mouse" -- taking it from nobody doesn't count
        if country.name not in CONTINENTS["Africa"]:
            return
        engine.turn_manager.pending_event_cards += 1


class Slavery(Event):
    def __init__(self):
        super().__init__(
            name="Slavernij",
            description="Per elk Afrikaans land dat je bezit wordt 1 slaaf toegevoegd.",
        )

    pending = ()

    def on_start(self, engine):
        # Mouse's African countries get their slave once a player takes
        # them during the event (check_pending).
        self.pending = []
        for name in CONTINENTS["Africa"]:
            country = engine.countries[name]
            if country.owner is not engine.default_player:
                country.units += 1
            else:
                self.pending.append(name)

    def check_pending(self, engine, player):
        happened = False
        for name in list(self.pending):
            country = engine.countries[name]
            if country.owner is engine.default_player:
                continue
            self.pending.remove(name)
            country.units += 1
            engine.turn_manager.notices.append([
                self.name, "{} took {}: 1 slave added there".format(country.owner.name, name)])
            happened = True
        return happened

    def on_end(self, engine):
        self.pending = []

    def save_state(self, engine):
        return {"pending": list(self.pending)}

    def load_state(self, engine, data):
        self.pending = [n for n in data.get("pending", []) if n in engine.countries]


class EndOfHumanity(Event):
    def __init__(self):
        super().__init__(
            name="Einde van de mensheid",
            description="Als je een speler uitroeit krijg je ook hun voedsel.",
        )

    def on_player_eliminated(self, engine, victor, loser):
        victor.food += loser.food
        loser.food = 0


class VOCPart2(Event):
    def __init__(self):
        super().__init__(
            name="maak van de VOC een deel 2",
            description="Alle mauses 1 troep minder.",
        )

    # Every country that actually lost a troop is marked (Country.
    # voc_weakened, saved with the game) so on_end can give it back.

    def on_start(self, engine):
        for country in engine.countries.values():
            if country.owner is engine.default_player and country.units > 0:
                country.units -= 1
                country.voc_weakened = True

    def on_end(self, engine):
        # Back to normal strength -- only for countries mouse still holds;
        # one claimed meanwhile was taken over as it was.
        for country in engine.countries.values():
            if country.voc_weakened and country.owner is engine.default_player:
                country.units += 1
            country.voc_weakened = False

    def abandoned_units(self, engine, country, units):
        # A country abandoned during the event gets the same -1 as the
        # mouse countries did when it started.
        country.voc_weakened = units > 0
        return max(units - 1, 0)

    def free_claim_allowed(self, engine, country):
        return country.owner is engine.default_player and country.units == 0


class NuclearWinter(Event):
    def __init__(self):
        super().__init__(
            name="nucleaire winter",
            description="Deze ronde géén voedsel productie.",
        )

    def modify_income(self, engine, country, player, amounts):
        amounts["food"] = 0
        return player, amounts


class ChildLabor(Event):
    COUNTRIES = ("India", "Sri Lanka", "Maleisië", "Nederlands-Indië")

    def __init__(self):
        super().__init__(
            name="kinderarbeid",
            description="De landen India, Sri Lanka, Maleisië en Nederlands-Indië leveren 5 staal.",
        )

    pending = ()

    def on_start(self, engine):
        # Mouse's countries deliver once a player takes them during the
        # event (check_pending).
        self.pending = []
        for name in self.COUNTRIES:
            country = engine.countries[name]
            if country.owner is not engine.default_player:
                country.owner.steel += 5
            else:
                self.pending.append(name)

    def check_pending(self, engine, player):
        happened = False
        for name in list(self.pending):
            country = engine.countries[name]
            if country.owner is engine.default_player:
                continue
            self.pending.remove(name)
            country.owner.steel += 5
            engine.turn_manager.notices.append([
                self.name, "{} took {}: +5 steel".format(country.owner.name, name)])
            happened = True
        return happened

    def on_end(self, engine):
        self.pending = []

    def save_state(self, engine):
        return {"pending": list(self.pending)}

    def load_state(self, engine, data):
        self.pending = [n for n in data.get("pending", []) if n in engine.countries]


class Ebola(Event):
    def __init__(self):
        super().__init__(
            name="ebola",
            description="Het land met de meeste legers in Afrika gaat naar Mouse.",
        )
        self.__init_state()

    def __init_state(self):
        self.chooser = None
        self.candidates = []
        # No clear target yet (Africa all mouse's, or a tie between
        # different players): check_pending strikes as soon as there is.
        self.pending = False

    def on_start(self, engine):
        self.__init_state()
        self._resolve(engine)

    def _resolve(self, engine):
        """Strike the African country with the most troops if there's a
        clear one (True); otherwise remember why not."""
        # Unclaimed (default_player) countries never count as candidates.
        africa = [n for n in CONTINENTS["Africa"] if engine.countries[n].owner is not engine.default_player]
        if not africa:
            self.pending = True
            return False
        best = max(engine.countries[n].units for n in africa)
        leaders = [n for n in africa if engine.countries[n].units == best]
        if len(leaders) == 1:
            self.pending = False
            self._strike(engine, engine.countries[leaders[0]])
            return True
        owners = {engine.countries[n].owner for n in leaders}
        if len(owners) != 1:
            self.pending = True  # tied between different players
            return False
        # One player holds every tied country: they pick which one is hit,
        # at the start of their next turn (see on_turn_start) -- or right
        # away if it's their turn now (check_pending).
        self.pending = False
        self.chooser = owners.pop()
        self.candidates = leaders
        return False

    def on_turn_start(self, engine, player):
        if self.chooser is not player:
            return
        self._launch_pick(engine, player, (player.attack, player.subattack))

    def check_pending(self, engine, player):
        if self.pending:
            country_owners = {n: engine.countries[n].owner for n in CONTINENTS["Africa"]}
            if self._resolve(engine):
                name = next(n for n in CONTINENTS["Africa"]
                            if country_owners[n] is not engine.countries[n].owner)
                engine.turn_manager.notices.append([
                    self.name, "{} of {} now has the most troops in Africa: it goes to the mouse".format(
                        name, country_owners[name].name)])
                return True
        if self.chooser is player:
            engine.turn_manager.notices.append([
                self.name, "{}: pick which of your countries is hit by ebola".format(player.name)])
            return self._launch_pick(engine, player, (player.attack, player.subattack if player.attack == 0 else 0))
        return False

    def _launch_pick(self, engine, player, return_to):
        candidates = [n for n in self.candidates if engine.countries[n].owner is player]
        self.chooser = None  # one-shot (this hook is called again once the pick is made)
        self.candidates = []
        if not candidates:
            return False
        engine.turn_manager.phases[5].start(
            predicate=lambda c: c.name in candidates and c.owner is player,
            on_pick=lambda engine, chooser, country: self._strike(engine, country),
            prompt="Kies welk land door ebola getroffen wordt",
            return_to=return_to,
        )
        player.attack, player.subattack = 5, 0
        return True

    def on_end(self, engine):
        self.__init_state()

    def save_state(self, engine):
        return {"pending": self.pending, "candidates": list(self.candidates),
                "chooser": self.chooser.name if self.chooser is not None else None}

    def load_state(self, engine, data):
        self.pending = data.get("pending", False)
        self.candidates = [n for n in data.get("candidates", []) if n in engine.countries]
        self.chooser = next((p for p in engine.players if p.name == data.get("chooser")), None)

    @staticmethod
    def _strike(engine, country):
        # Reuses Phase.abandon (any Phase instance will do -- it only
        # touches engine state) rather than duplicating the same
        # "hand back to Mouse" reset here.
        engine.turn_manager.phases[0].abandon(country)


class HarshWinter(Event):
    FROZEN = ("Alaska", "Canada", "Groenland", "Viking", "Sovjet-Rusland", "Siberië")

    def __init__(self):
        super().__init__(
            name="strenge winter",
            description="De Noordelijkst gelegen landen mogen niet aangevallen worden of zelf aanvallen.",
        )

    def can_attack_from(self, engine, country):
        return country.name not in self.FROZEN

    def can_attack_target(self, engine, country):
        return country.name not in self.FROZEN


class Pilgrimage(Event):
    def __init__(self):
        super().__init__(
            name="bedevaart",
            description="De speler die Arabië bezit verplaatst al zijn troepen naar dat land en krijgt +5 troepen.",
        )

    pending = False

    def on_start(self, engine):
        # With Arabië still mouse's, it happens the moment a player takes
        # it during the event (check_pending).
        self.pending = engine.countries["Arabië"].owner is engine.default_player
        if not self.pending:
            self._apply(engine)

    def check_pending(self, engine, player):
        owner = engine.countries["Arabië"].owner
        if not self.pending or owner is engine.default_player:
            return False
        self.pending = False
        self._apply(engine)
        engine.turn_manager.notices.append([
            self.name, "{} took Arabië: all their troops move there, +5 troops".format(owner.name)])
        return True

    def on_end(self, engine):
        self.pending = False

    def save_state(self, engine):
        return {"pending": self.pending}

    def load_state(self, engine, data):
        self.pending = data.get("pending", False)

    def _apply(self, engine):
        arabia = engine.countries["Arabië"]
        owner = arabia.owner
        abandon = engine.turn_manager.phases[0].abandon
        total = 0
        for country in list(engine.countries.values()):
            if country.owner is owner and country is not arabia:
                total += country.units
                abandon(country)  # goes to default_player as usual
        arabia.units += total + 5


class Looting(Event):
    def __init__(self):
        super().__init__(
            name="plunderingen",
            description="Criminelen plunderen de shop en zetten alles voor de helft van het geld op marktplaats.",
        )

    def discount_shop_cost(self, engine, cost):
        # Half price, rounded up (e.g. 15 wood -> 8).
        return {resource: (amount + 1) // 2 for resource, amount in cost.items()}


class ClimateHoax(Event):
    def __init__(self):
        super().__init__(
            name="klimaatverandering blijkt hoax",
            description="Iedereen een gratis vliegtuig. Hoe meer CO2 hoe beter!",
        )
        self.placed_on_turn = {}  # player -> event_turn_index they last placed on

    def on_start(self, engine):
        self.placed_on_turn = {}

    def on_turn_start(self, engine, player):
        # Diverting into EventTargetPhase returns the player straight back
        # to (0, 0), which makes ReinforcementPhase call this again on the
        # very next frame -- guard on the turn index (unique and constant
        # for this whole turn) so that second call lets the turn proceed
        # instead of asking for a second plane.
        turn_index = engine.turn_manager.event_turn_index
        if self.placed_on_turn.get(player) == turn_index:
            return
        self.placed_on_turn[player] = turn_index

        def place_plane(engine, chooser, country):
            country.planes += 1
            country.airport = True

        engine.turn_manager.phases[5].start(
            predicate=lambda c: c.owner is player,
            on_pick=place_plane,
            prompt="Plaats een gratis vliegtuig in een van je landen",
            return_to=(player.attack, player.subattack),
        )
        player.attack, player.subattack = 5, 0


class TrumpWall(Event):
    # "redneck" is this board's own country name too.
    PAIRS = ({"Los Angeles", "Mexico"}, {"Redneck", "Mexico"})

    def __init__(self):
        super().__init__(
            name="Muur van Trump",
            description="Je kan niet tussen de VS en Mexico reizen.",
        )
        self.removed = []

    def on_start(self, engine):
        self.removed = [c for c in engine.connections if set(c.connection) in self.PAIRS]
        for connection in self.removed:
            engine.connections.discard(connection)

    def on_end(self, engine):
        for connection in self.removed:
            engine.connections.add(connection)
        self.removed = []


class GoodEconomy(Event):
    def __init__(self):
        super().__init__(
            name="goede economie",
            description="De olieproducerende landen krijgen 1 extra olie per land.",
        )

    def modify_income(self, engine, country, player, amounts):
        # Checked on the already-multiplied amount, not the country's raw
        # oil stat, so this only applies on a turn the country is actually
        # producing some (not idle after developing, not radioactive --
        # that case never reaches this hook at all).
        if amounts["oil"] > 0:
            amounts["oil"] += 1
        return player, amounts


class Covid(Event):
    # "VS" (the US) is spread across these four countries on this board.
    COUNTRIES = ("Sovjet-Rusland", "Pearl Harbor", "Los Angeles", "New York", "Redneck", "Brazilië")

    def __init__(self):
        super().__init__(
            name="covid",
            description="Spelers die sovjet, VS of Brazilië bezitten krijgen géén troepen.",
        )

    def reinforcement_override(self, engine, player, reinforcements):
        if any(engine.countries[name].owner is player for name in self.COUNTRIES):
            return 0
        return reinforcements


class Drugs(Event):
    COUNTRIES = ("Venezuela", "Mexico", "Los Angeles", "Siberië", "Cuba")

    def __init__(self):
        super().__init__(
            name="drugs",
            description="Als je de landen Venezuela, Mexico, Los Angeles, Siberië of Cuba bezit, "
                        "haal dan 1 af van de waarde van elke dobbelsteen die je gooit.",
        )

    def dice_penalty(self, engine, player):
        if player is engine.default_player:
            return 0
        return 1 if any(engine.countries[name].owner is player for name in self.COUNTRIES) else 0


class NaziExpansion(Event):
    def __init__(self):
        super().__init__(
            name="de nazi's breiden uit",
            description="Als Nazi-Duitsland aanvalt mag het 1 optellen bij elke dobbelsteen.",
        )

    def attack_bonus(self, engine, attack_from):
        return 1 if attack_from.name == "Nazi-Duitsland" else 0


EVENTS = [
    JapanGoesCrazy(),
    NativesFightBack(),
    DevelopmentAid(),
    EmperorsHonor(),
    WrongButton(),
    JapaneseAggression(),
    StormAtSea(),
    ChildSoldiers(),
    Slavery(),
    EndOfHumanity(),
    VOCPart2(),
    NuclearWinter(),
    ChildLabor(),
    Ebola(),
    HarshWinter(),
    Pilgrimage(),
    Looting(),
    ClimateHoax(),
    TrumpWall(),
    GoodEconomy(),
    Covid(),
    Drugs(),
    NaziExpansion(),
]
