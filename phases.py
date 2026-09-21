"""
Turn-phase state machine, rewritten from the procedural running.py loop.

Each game phase (reinforcement, attack, movement, shop) is a
`Phase` subclass with an `update()` method that is called once per frame. A
`TurnManager` owns all phases, shared per-turn state, and the small amount of
global logic (end-turn buttons, the "too many cards" warning, opening/closing
the shop from anywhere).

Country/connection lookups use country *names* (dict keys), matching
board.py / models.py, instead of the list indices running.py used.
"""

import numpy as np

from models import Position, Dice, Kaertske


class Phase:
    """Base class for a single turn-phase (a value of player.attack)."""

    def __init__(self, manager):
        self.manager = manager

    @property
    def engine(self):
        return self.manager.engine

    @property
    def player(self):
        return self.engine.players[self.engine.turn]

    @property
    def io(self):
        return self.engine.io

    @property
    def view(self):
        return self.engine.view

    # --- small drawing/input helpers -------------------------------------

    def mouse_in(self, x0, y0, x1, y1):
        p = self.io.mouse_position
        return x0 <= p.x <= x1 and y0 <= p.y <= y1

    def clicked(self, x0, y0, x1, y1):
        return self.io.left_pressed and self.mouse_in(x0, y0, x1, y1)

    def draw_rect(self, color, x, y, w, h, width=0):
        import pygame as pg
        pg.draw.rect(self.view.screen, color, pg.Rect(x, y, w, h), width)

    def draw_circle(self, color, cx, cy, radius, width=0):
        import pygame as pg
        pg.draw.circle(self.view.screen, color, (int(cx), int(cy)), radius, width)

    def in_circle(self, cx, cy, radius):
        p = self.io.mouse_position
        return (p.x - cx) ** 2 + (p.y - cy) ** 2 <= radius ** 2

    def clicked_circle(self, cx, cy, radius):
        return self.io.left_pressed and self.in_circle(cx, cy, radius)

    def blit_text(self, text, x, y, color=(0, 0, 0)):
        self.view.screen.blit(self.engine.font.render(text, False, color), (x, y))

    def connected(self, a, b, kind=None):
        for c in self.engine.connections:
            if a in c and b in c and (kind is None or c.kind == kind):
                return True
        return False

    def abandon(self, country):
        """Hand a country over to the neutral default_player. Nobody is
        left to crew/maintain any ships, tanks, planes, forts or nukes
        sitting there, so they're destroyed along with the ownership
        change, and its garrison resets to whatever board.py originally
        put there (some countries start at 1, not the usual 2)."""
        country.owner = self.engine.default_player
        country.units = self.engine.initial_country_units.get(country.name, 2)
        country.ships = 0
        country.tanks = 0
        country.planes = 0
        country.fort_lvl = 0
        country.radioactive = 0

    # --- rail network redistribution ---------------------------------
    # Shared by any phase with a notion of a currently-selected origin
    # country (AttackPhase.attack_from, MovementPhase.origin_country):
    # a circular button pops up to spend 1 oil and freely redistribute
    # troops among every one of the player's countries reachable purely
    # by hopping along built rails.

    def _init_rail_state(self):
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_pool = 0
        self.rail_transfer_mode = 1
        self._rail_return_subattack = 0
        self._rail_mode_subattack = None  # subclasses set this

    def _compute_rail_network(self, origin, player):
        """Countries owned by `player` reachable from `origin` by hopping
        only along rail connections. Travel may pass freely through
        default_player (unclaimed) territory, but is blocked as soon as it
        would have to cross a country owned by another player."""
        engine = self.engine
        visited = {origin}
        frontier = {origin}
        while frontier:
            next_frontier = set()
            for name in frontier:
                for c in engine.connections:
                    if not getattr(c, "rails", False) or name not in c:
                        continue
                    for other in c.connection:
                        if other == name or other in visited:
                            continue
                        owner = engine.countries[other].owner
                        if owner == player or owner == engine.default_player:
                            visited.add(other)
                            next_frontier.add(other)
            frontier = next_frontier
        return {name for name in visited if engine.countries[name].owner == player}

    def _draw_rails_button(self, origin, allowed_subs):
        player = self.player
        if origin is None or player.subattack not in allowed_subs:
            return
        network = self._compute_rail_network(origin, player)
        if len(network) <= 1:
            return

        import pygame as pg
        view = self.view
        center = (int(view.WIDTH * 0.5), 45)
        radius = 30
        mouse = self.io.mouse_position
        hovered = (mouse.x - center[0]) ** 2 + (mouse.y - center[1]) ** 2 <= radius ** 2

        pg.draw.circle(view.screen, (215, 215, 215) if hovered else (235, 235, 235), center, radius)
        pg.draw.circle(view.screen, (0, 0, 0), center, radius, 3)
        self.engine.images["spr_rails"].draw(view.screen, Position(center[0] - 15, center[1] - 15))

        if hovered and self.io.left_pressed and player.oil > 1:
            player.oil -= 1
            self.rail_network = sorted(network)
            self.rail_initial_units = {name: self.engine.countries[name].units for name in self.rail_network}
            self.rail_pool = 0
            self.rail_transfer_mode = 1
            self._rail_return_subattack = player.subattack
            player.subattack = self._rail_mode_subattack

    def _redistribute_rails(self):
        engine = self.engine
        player = self.player
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT

        self.blit_text("Redistribute along rails", 25, HEIGHT - 300)
        self.blit_text("Pool: {}".format(self.rail_pool), 25, HEIGHT - 270)

        add_x, add_y = 25, HEIGHT - 240
        remove_x, remove_y = 25, HEIGHT - 180
        self.draw_rect((0, 170, 0), add_x, add_y, 50, 50)
        self.draw_rect((0, 0, 0), add_x, add_y, 50, 50, 3 if self.rail_transfer_mode == 1 else 1)
        self.draw_rect((170, 0, 0), remove_x, remove_y, 50, 50)
        self.draw_rect((0, 0, 0), remove_x, remove_y, 50, 50, 3 if self.rail_transfer_mode == 2 else 1)
        if self.clicked(add_x, add_y, add_x + 50, add_y + 50):
            self.rail_transfer_mode = 1
        elif self.clicked(remove_x, remove_y, remove_x + 50, remove_y + 50):
            self.rail_transfer_mode = 2

        hover = self.io.hover_country
        if self.io.left_pressed and hover in self.rail_network:
            country = engine.countries[hover]
            if self.rail_transfer_mode == 1 and self.rail_pool > 0:
                country.units += 1
                self.rail_pool -= 1
            elif self.rail_transfer_mode == 2 and country.units > 0:
                country.units -= 1
                self.rail_pool += 1

        done_x, done_y = 25, HEIGHT - 50
        done_active = self.rail_pool == 0
        self.draw_rect((100, 100, 255) if done_active else (170, 170, 170), done_x, done_y, 120, 40)
        self.draw_rect((0, 0, 0), done_x, done_y, 120, 40, 3)
        self.blit_text("Done", done_x + 35, done_y + 10)
        if done_active and self.clicked(done_x, done_y, done_x + 120, done_y + 40):
            for name in self.rail_network:
                country = engine.countries[name]
                if country.units == 0:
                    self.abandon(country)
            player.subattack = self._rail_return_subattack
            self.rail_network = []
            self.rail_initial_units = {}

    def update(self):
        raise NotImplementedError


class ReinforcementPhase(Phase):
    """player.attack == 0"""

    def _start_turn(self):
        engine = self.engine
        player = self.player
        manager = self.manager

        manager.initial_units = {name: c.units for name, c in engine.countries.items()}
        player.troops = 0
        units = 0
        new_food = 0
        for country in engine.countries.values():
            if country.owner == player:
                units += country.units
                if country.radioactive == 0:
                    player.troops += country.troops
                    player.food += country.food
                    new_food += country.food
                    player.wood += country.wood
                    player.steel += country.steel
                    player.oil += country.oil
                    player.nuclear += country.nuclear
                else:
                    country.radioactive -= 1
        player.food -= units

        if units == 0:
            manager.next_turn()
            return False

        starved = 0
        if player.food - new_food < 0:
            starved = -(player.food - new_food)
            player.food = 0

        manager.reinforcements = int((player.troops - player.troops % 3) / 3 + 3) - starved
        manager.all_reinforcements_deployed = False
        manager.attacked = []
        manager.conquered_enemy_this_turn = False
        player.subattack = 1
        return True

    def update(self):
        player = self.player
        engine = self.engine
        manager = self.manager
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT

        if player.subattack == 0:
            if not self._start_turn():
                return

        self.draw_rect((0, 170, 0), WIDTH - 935, HEIGHT - 270, 50, 50)
        self.blit_text("+ " + str(manager.reinforcements), WIDTH - 920, HEIGHT - 200)
        self.draw_rect((170, 0, 0), WIDTH - 935, HEIGHT - 160, 50, 50)

        hover = self.io.hover_country
        if player.subattack == 1:
            self.draw_rect((0, 0, 0), 25, HEIGHT - 270, 50, 50, 3)
            self.draw_rect((0, 0, 0), 25, HEIGHT - 160, 50, 50, 1)
            if manager.reinforcements <= 0:
                manager.all_reinforcements_deployed = True
            if self.io.left_pressed and hover is not None:
                if engine.countries[hover].owner == player and not manager.all_reinforcements_deployed:
                    engine.countries[hover].units += 1
                    manager.reinforcements -= 1
            elif self.clicked(25, HEIGHT - 160, 75, HEIGHT - 110):
                player.subattack = 2
        elif player.subattack == 2:
            self.draw_rect((0, 0, 0), 25, HEIGHT - 270, 50, 50, 1)
            self.draw_rect((0, 0, 0), 25, HEIGHT - 160, 50, 50, 3)
            if self.io.left_pressed and hover is not None:
                country = engine.countries[hover]
                if country.owner == player and country.units > manager.initial_units.get(hover, 0):
                    country.units -= 1
                    manager.reinforcements += 1
                    manager.all_reinforcements_deployed = False
            elif self.clicked(25, HEIGHT - 270, 75, HEIGHT - 220):
                player.subattack = 1


class AttackPhase(Phase):
    """player.attack == 1"""

    def __init__(self, manager):
        super().__init__(manager)
        self.attack_from = None
        self.defence_country = None
        self.attack_dice = None
        self.defence_dice = None
        self.timer = 0
        self.conquest_units = 0
        self.selected_ships = 0
        self.attack_via_land = False
        self.selected_tanks = 0
        self.active_tanks = 0
        self.selected_planes = 0
        self._init_rail_state()
        self._rail_mode_subattack = 7

    def reset(self):
        """Clear anything that would otherwise linger visually (mainly the
        shading _highlight_selection applies) from whoever last used this
        phase -- AttackPhase is a single shared instance across every
        player's turn, not one per player."""
        self.attack_from = None
        self.defence_country = None
        self.attack_dice = None
        self.defence_dice = None
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_pool = 0

    def update(self):
        player = self.player
        self._highlight_selection()
        self._draw_rails_button(self.attack_from, (1, 2, 6))
        sub = player.subattack
        if sub in (0, 1):
            self._select_target()
        elif sub == 6:
            self._select_asset_transport()
        elif sub == 2:
            self._choose_dice_count()
        elif sub == 3:
            self._roll_dice()
        elif sub == 4:
            self._resolve_combat()
        elif sub == 5:
            self._post_conquest()
        elif sub == 7:
            self._redistribute_rails()

    def _highlight_selection(self):
        engine = self.engine
        if self.player.subattack == 7:
            for name in self.rail_network:
                engine.countries[name].shade = 1
            return
        if self.attack_from is not None:
            engine.countries[self.attack_from].shade = 1
        if self.defence_country is not None:
            engine.countries[self.defence_country].shade = 1

    def _try_reselect(self):
        """While attacker/defender are chosen but dice haven't been cast yet,
        clicking the defending country again backs up to re-picking a target;
        clicking the attacking country again backs up to re-picking the
        attacker entirely."""
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return False
        if hover == self.attack_from:
            self.player.subattack = 0
            self.attack_from = None
            self.defence_country = None
            return True
        if self.defence_country is not None and hover == self.defence_country:
            self.player.subattack = 1
            self.defence_country = None
            return True
        return False

    def _select_target(self):
        engine = self.engine
        player = self.player
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if player.subattack == 0:
            if engine.countries[hover].owner == player:
                player.subattack = 1
                self.attack_from = hover
        else:
            if hover == self.attack_from:
                player.subattack = 0
                self.attack_from = None
                return
            if engine.countries[hover].owner == player:
                self.attack_from = hover
                return
            from_c = engine.countries[self.attack_from]
            is_land_route = self.connected(self.attack_from, hover, "land")
            can_attack = is_land_route or (
                self.connected(self.attack_from, hover, "sea") and (
                    from_c.ships > 0 or (from_c.planes > 0 and player.oil >= 1)
                )
            )
            if can_attack:
                self.defence_country = hover
                self.attack_dice = np.zeros(min(from_c.units, 3))
                self.defence_dice = np.zeros(min(engine.countries[hover].units, 2))
                # Default to bringing everything available; the player can
                # open the asset panel from the dice screen to dial it down.
                # A boat can never cross a land connection: attacking a
                # land-adjacent country automatically leaves the boats
                # behind, and the player can't bring any along afterwards
                # either (see the locked ships row in the asset panel).
                self.attack_via_land = is_land_route
                self.selected_ships = 0 if is_land_route else from_c.ships
                self.selected_tanks = from_c.tanks
                # Active tanks default to matching the tanks brought along,
                # capped by what oil can actually afford; tanks get first
                # claim on the oil budget, planes get whatever's left.
                self.active_tanks = min(self.selected_tanks, player.oil)
                self.selected_planes = min(from_c.planes, max(player.oil - self.active_tanks, 0))
                player.subattack = 2

    def _select_asset_transport(self):
        if self._try_reselect():
            return
        engine = self.engine
        player = self.player
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        from_c = engine.countries[self.attack_from]

        panel_x, panel_y, panel_w, panel_h = WIDTH * 0.5 - 220, HEIGHT * 0.5 - 180, 440, 360
        self.draw_rect((230, 170, 170), panel_x, panel_y, panel_w, panel_h)
        self.draw_rect((0, 0, 0), panel_x, panel_y, panel_w, panel_h, 3)
        self.blit_text("Bring along from {}:".format(self.attack_from), panel_x + 20, panel_y + 10)

        rows = [
            ("selected_ships", from_c.ships, engine.images["spr_ship"]),
            ("selected_tanks", from_c.tanks, engine.images["spr_tank"]),
            ("selected_planes", from_c.planes, engine.images["spr_plane"]),
        ]
        for i, (attr, available, sprite) in enumerate(rows):
            row_y = panel_y + 50 + i * 60
            sprite.draw(view.screen, Position(panel_x + 20, row_y))
            selected = getattr(self, attr)
            label = "{} / {}".format(selected, available)
            if attr == "selected_ships" and self.attack_via_land:
                label += " (no boats over land)"
            self.blit_text(label, panel_x + 70, row_y + 8)

            minus_x = panel_x + 180
            self.draw_rect((200, 100, 100), minus_x, row_y, 30, 30)
            self.draw_rect((0, 0, 0), minus_x, row_y, 30, 30, 2)
            self.blit_text("-", minus_x + 11, row_y + 4)
            if self.clicked(minus_x, row_y, minus_x + 30, row_y + 30) and selected > 0:
                setattr(self, attr, selected - 1)
                if attr == "selected_tanks":
                    # Decreasing tanks mirrors the decrease onto active
                    # tanks (and can never leave more active than brought).
                    self.active_tanks = min(max(self.active_tanks - 1, 0), self.selected_tanks)

            plus_x = panel_x + 220
            self.draw_rect((100, 200, 100), plus_x, row_y, 30, 30)
            self.draw_rect((0, 0, 0), plus_x, row_y, 30, 30, 2)
            self.blit_text("+", plus_x + 9, row_y + 4)
            # Planes cost 1 oil each, drawn from the same pool active tanks
            # (below) already reserve, so cap how many can be selected by
            # what's left.
            room_left = available
            if attr == "selected_planes":
                room_left = min(available, max(player.oil - self.active_tanks, 0))
            elif attr == "selected_ships" and self.attack_via_land:
                # A boat can't cross a land connection, so no ships can be
                # brought along on a land attack -- locked at 0.
                room_left = 0
            if self.clicked(plus_x, row_y, plus_x + 30, row_y + 30) and selected < room_left:
                setattr(self, attr, selected + 1)

        # A sea attack physically requires a ship or a fuelled plane to
        # cross the water. If the player deselects the last of both, the
        # attack can no longer happen at all -- bail all the way back out
        # to picking a fresh attack_from rather than leaving them stuck on
        # an impossible asset panel.
        if not self.attack_via_land and self.selected_ships == 0 and self.selected_planes == 0:
            self.attack_from = None
            self.defence_country = None
            self.attack_via_land = False
            player.subattack = 0
            return

        # Active tanks: an opt-in subset of the tanks brought along. Each
        # active tank costs 1 oil (shared with planes) and adds +1 to the
        # highest attack die every round of this combat, until the attack
        # ends or the territory is conquered.
        active_row_y = panel_y + 50 + len(rows) * 60
        engine.images["spr_tank"].draw(view.screen, Position(panel_x + 20, active_row_y))
        self.blit_text(
            "Active: {} / {} (1 oil each)".format(self.active_tanks, self.selected_tanks),
            panel_x + 70, active_row_y + 8,
        )

        active_minus_x = panel_x + 180
        self.draw_rect((200, 100, 100), active_minus_x, active_row_y, 30, 30)
        self.draw_rect((0, 0, 0), active_minus_x, active_row_y, 30, 30, 2)
        self.blit_text("-", active_minus_x + 11, active_row_y + 4)
        if self.clicked(active_minus_x, active_row_y, active_minus_x + 30, active_row_y + 30) and self.active_tanks > 0:
            self.active_tanks -= 1

        active_plus_x = panel_x + 220
        self.draw_rect((100, 200, 100), active_plus_x, active_row_y, 30, 30)
        self.draw_rect((0, 0, 0), active_plus_x, active_row_y, 30, 30, 2)
        self.blit_text("+", active_plus_x + 9, active_row_y + 4)
        active_room_left = min(self.selected_tanks, max(player.oil - self.selected_planes, 0))
        if self.clicked(active_plus_x, active_row_y, active_plus_x + 30, active_row_y + 30) and \
                self.active_tanks < active_room_left:
            self.active_tanks += 1

        # Reconcile the two oil-consuming selections regardless of which
        # one just moved, so neither can drift over the available budget.
        self.active_tanks = min(self.active_tanks, self.selected_tanks, max(player.oil - self.selected_planes, 0))
        self.selected_planes = min(self.selected_planes, max(player.oil - self.active_tanks, 0))

        confirm_x, confirm_y = panel_x + panel_w * 0.5 - 60, panel_y + panel_h - 50
        self.draw_rect((150, 245, 150), confirm_x, confirm_y, 120, 40)
        self.draw_rect((0, 0, 0), confirm_x, confirm_y, 120, 40, 2)
        self.blit_text("Confirm", confirm_x + 20, confirm_y + 10)
        if self.clicked(confirm_x, confirm_y, confirm_x + 120, confirm_y + 40):
            player.subattack = 2

    def _choose_dice_count(self):
        if self._try_reselect():
            return
        # NOTE: ported as-is from running.py, including the (fairly obscure)
        # original behaviour: an empty dice array short-circuits back to 0.
        if np.all(self.attack_dice):
            self.player.subattack = 0
            return
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        self.draw_rect((100, 100, 100), 25, HEIGHT - 50, 200, 40)
        self.draw_rect((0, 0, 0), 25, HEIGHT - 50, 200, 40, 3)

        assets_x, assets_y, assets_w, assets_h = WIDTH - 350, 20, 130, 40
        self.draw_rect((180, 180, 255), assets_x, assets_y, assets_w, assets_h)
        self.draw_rect((0, 0, 0), assets_x, assets_y, assets_w, assets_h, 2)
        self.blit_text("Assets", assets_x + 30, assets_y + 10)
        if self.clicked(assets_x, assets_y, assets_x + assets_w, assets_y + assets_h):
            self.player.subattack = 6
            return

        for i in range(len(self.attack_dice)):
            y = HEIGHT - 200 + 40 * self.attack_dice[i]
            x = WIDTH * 0.5 - 200 + 80 * i
            self.draw_rect((255, 50, 50), x, y, 70, 70)
            self.draw_rect((0, 0, 0), x, y, 70, 70, 3)
            if self.clicked(x, y, x + 70, y + 70):
                self.attack_dice[i] = not self.attack_dice[i]
        if self.clicked(25, HEIGHT - 50, 225, HEIGHT - 10):
            for i in range(len(self.attack_dice)):
                self.attack_dice[i] = (not self.attack_dice[i]) * np.random.randint(1, 7)
            self.player.subattack = 3

    def _roll_dice(self):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        self.draw_rect((100, 100, 100), 25, HEIGHT - 50, 200, 40)
        self.draw_rect((0, 0, 0), 25, HEIGHT - 50, 200, 40, 3)
        for i in range(len(self.attack_dice)):
            if self.attack_dice[i] > 0:
                x = int(WIDTH * 0.5) - 200 + 80 * i
                self.draw_rect((255, 50, 50), x, 20, 70, 70)
                self.draw_rect((0, 0, 0), x, 20, 70, 70, 3)
                Dice((255, 50, 50), eyes=int(self.attack_dice[i])).draw(view.screen, Position(x + 35, 55))
        defence = engine.countries[self.defence_country]
        for i in range(len(self.defence_dice)):
            y = HEIGHT - 200 + 40 * self.defence_dice[i]
            x = WIDTH * 0.5 - 200 + 80 * i
            self.draw_rect((0, 100, 255), x, y, 70, 70)
            self.draw_rect((0, 0, 0), x, y, 70, 70, 3)
            if defence.owner != engine.default_player and self.clicked(x, y, x + 70, y + 70):
                self.defence_dice[i] = not self.defence_dice[i]
        defender_cast = self.clicked(25, HEIGHT - 50, 225, HEIGHT - 10) and sum(
            not d for d in self.defence_dice
        ) != 0
        if defence.owner == engine.default_player or defender_cast:
            for i in range(len(self.defence_dice)):
                self.defence_dice[i] = (not self.defence_dice[i]) * np.random.randint(1, 7)
            self.player.subattack = 4
            self.timer = 0

    def _resolve_combat(self):
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        for i in range(len(self.attack_dice)):
            if self.attack_dice[i] > 0:
                x = int(WIDTH * 0.5) - 200 + 80 * i
                self.draw_rect((255, 50, 50), x, 20, 70, 70)
                self.draw_rect((0, 0, 0), x, 20, 70, 70, 3)
                Dice((255, 50, 50), eyes=int(self.attack_dice[i])).draw(view.screen, Position(x + 35, 55))
        for i in range(len(self.defence_dice)):
            if self.defence_dice[i] > 0:
                x = int(WIDTH * 0.5) - 200 + 80 * i
                self.draw_rect((0, 100, 255), x, 100, 70, 70)
                self.draw_rect((0, 0, 0), x, 100, 70, 70, 3)
                Dice((0, 100, 255), eyes=int(self.defence_dice[i])).draw(view.screen, Position(x + 35, 135))
        if self.io.left_pressed:
            self.timer = 150
        if self.timer != 150:
            return
        self._apply_combat_results()
        self.timer = 0

    def _apply_combat_results(self):
        engine = self.engine
        player = self.player
        manager = self.manager
        attack_from = engine.countries[self.attack_from]
        defence = engine.countries[self.defence_country]

        D = np.sort(self.defence_dice[self.defence_dice > 0]) + defence.fort_lvl
        A = np.sort(self.attack_dice[self.attack_dice > 0])
        if len(A) > 0:
            A[-1] += self.active_tanks
        if self.defence_country not in manager.attacked:
            player.oil -= self.active_tanks + self.selected_planes
        manager.attacked.append(self.defence_country)

        n = min(len(D), len(A))
        attack_loss = [A[-1 - i] <= D[-1 - i] for i in range(n)]
        attack_from.units -= sum(attack_loss)
        defence.units -= sum(not a for a in attack_loss)

        if defence.units <= 0:
            self.conquest_units = len(A)
            self._conquer(defence, attack_from)
            player.subattack = 5
        elif attack_from.units <= 0:
            # Attacker's stack is spent; nothing left to roll with, so back
            # out to re-picking an attacker instead of showing an empty
            # dice screen. With nobody left there to hold it, the country
            # they attacked from goes neutral, same as any other country
            # emptied out to 0.
            self.abandon(attack_from)
            player.subattack = 0
            self.attack_from = None
            self.defence_country = None
        else:
            # Defender survived and the attacker still has troops: stay on
            # the dice-select screen for another round against the same
            # target, re-sized to the troops that remain after this roll.
            self.attack_dice = np.zeros(min(attack_from.units, 3))
            self.defence_dice = np.zeros(min(defence.units, 2))
            player.subattack = 2

    def _conquer(self, defence, attack_from):
        engine = self.engine
        player = self.player
        manager = self.manager

        if defence.owner != engine.default_player:
            manager.conquered_enemy_this_turn = True

        # Conquest wipes out whatever the previous owner had stationed here
        # -- ships, tanks, planes, and (already handled below) the fort --
        # then whatever the attacker brought along replaces it. This has
        # to be unconditional: previously, bringing along zero of every
        # asset type left the defender's own assets untouched instead of
        # destroyed.
        defence.ships = self.selected_ships
        defence.planes = self.selected_planes
        defence.tanks = self.selected_tanks
        attack_from.ships -= self.selected_ships
        attack_from.planes -= self.selected_planes
        attack_from.tanks -= self.selected_tanks

        if defence.owner != engine.default_player:
            eliminated = not any(
                c.owner == defence.owner and c is not defence for c in engine.countries.values()
            )
            if eliminated:
                loser = defence.owner
                player.wood += loser.wood
                player.steel += loser.steel
                player.nuclear += loser.nuclear
                player.oil += loser.oil
                player.cards += loser.cards
                loser.wood = loser.steel = loser.nuclear = loser.oil = 0
                loser.cards = []

        defence.fort_lvl = 0
        defence.owner = player
        total_units = defence.units + attack_from.units
        # Default to moving as many troops as possible into the newly
        # conquered country, leaving just 1 behind to hold attack_from.
        # The post-conquest menu still lets the player fine-tune this,
        # so this is only the starting point.
        defence.units = max(total_units - 1, self.conquest_units)
        attack_from.units = total_units - defence.units

    def _post_conquest(self):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        attack_from = engine.countries[self.attack_from]
        defence = engine.countries[self.defence_country]

        self.draw_rect((100, 100, 100), 25, HEIGHT - 50, 200, 40)
        self.draw_rect((0, 0, 0), 25, HEIGHT - 50, 200, 40, 3)

        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None:
            total_units = defence.units + attack_from.units
            if hover == self.defence_country:
                if defence.units + 1 > total_units or attack_from.units - 1 < 0:
                    defence.units = self.conquest_units
                    attack_from.units = total_units - self.conquest_units
                else:
                    defence.units += 1
                    attack_from.units -= 1
            elif hover == self.attack_from:
                if defence.units - 1 < self.conquest_units or attack_from.units + 1 > total_units - self.conquest_units:
                    defence.units = total_units
                    attack_from.units = 0
                else:
                    defence.units -= 1
                    attack_from.units += 1

        if self.clicked(25, HEIGHT - 50, 225, HEIGHT - 10):
            self.player.subattack = 0
            if attack_from.units == 0:
                self.abandon(attack_from)
            self.attack_from = None
            self.defence_country = None


class MovementPhase(Phase):
    """player.attack == 2"""

    def __init__(self, manager):
        super().__init__(manager)
        self.origin_country = None
        self.finished_list = set()
        self.target_country = None
        self.initial_origin = 0
        self.initial_target = 0
        # Which resource the origin/target click-to-shift applies to.
        self.move_resource = "units"
        self.initial_origin_ships = 0
        self.initial_target_ships = 0
        self.initial_origin_tanks = 0
        self.initial_target_tanks = 0
        self.initial_origin_planes = 0
        self.initial_target_planes = 0
        # Whether the origin and target are connected by an unbroken chain
        # of sea connections through the player's own territory -- boats
        # can't be moved between them otherwise.
        self.ships_via_sea = False
        # Whether NO all-land route exists between origin and target, so
        # troops need an escorting ship or (fuelled) plane to make the
        # crossing at all.
        self.troops_require_sea = False
        # Net oil spent moving planes this session, refunded on Cancel.
        self.oil_spent_on_planes = 0
        self._init_rail_state()
        self._rail_mode_subattack = 3

    def reset(self):
        """Clear anything that would otherwise linger visually (mainly the
        shading _highlight_selection applies) from whoever last used this
        phase -- MovementPhase is a single shared instance across every
        player's turn, not one per player."""
        self.origin_country = None
        self.target_country = None
        self.finished_list = set()
        self.rail_network = []
        self.rail_initial_units = {}
        self.rail_pool = 0

    def update(self):
        player = self.player
        self._highlight_selection()
        self._draw_rails_button(self.origin_country, (1, 2))
        sub = player.subattack
        if sub == 0:
            self._select_origin()
        elif sub == 1:
            self._select_target()
        elif sub == 2:
            self._adjust_units()
        elif sub == 3:
            self._redistribute_rails()

    def _highlight_selection(self):
        engine = self.engine
        if self.player.subattack == 3:
            for name in self.rail_network:
                engine.countries[name].shade = 1
            return
        if self.origin_country is not None:
            engine.countries[self.origin_country].shade = 1
        if self.target_country is not None:
            engine.countries[self.target_country].shade = 1

    def _select_origin(self):
        engine = self.engine
        player = self.player
        if player.repositioned_this_turn:
            self.blit_text(
                "Already repositioned this turn", 25, self.view.HEIGHT - 270,
            )
            return
        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None and engine.countries[hover].owner == player:
            self.origin_country = hover
            self._flood_fill()
            player.subattack = 1

    def _flood_fill(self):
        """Every country the player owns reachable from origin_country by
        hopping through any connection (land or sea), as long as each
        intermediate country along the way is also theirs."""
        engine = self.engine
        player = self.player
        finished = {self.origin_country}
        while True:
            size_before = len(finished)
            neighbours = set()
            for name in finished:
                for c in engine.connections:
                    if name in c:
                        neighbours.update(c.connection)
            finished |= {n for n in neighbours if engine.countries[n].owner == player}
            if len(finished) == size_before:
                break
        self.finished_list = finished

    def _sea_flood_fill(self, origin):
        """Like _flood_fill, but only hopping along sea connections --
        used to check whether ships can legally be moved to a target,
        since a boat can never travel a land connection."""
        engine = self.engine
        player = self.player
        finished = {origin}
        while True:
            size_before = len(finished)
            neighbours = set()
            for name in finished:
                for c in engine.connections:
                    if c.kind == "sea" and name in c:
                        neighbours.update(c.connection)
            finished |= {n for n in neighbours if engine.countries[n].owner == player}
            if len(finished) == size_before:
                break
        return finished

    def _land_flood_fill(self, origin):
        """Like _flood_fill, but only hopping along land connections --
        used to check whether troops can march the whole way unassisted.
        If a target isn't in here, at least one leg of every route to it
        crosses open sea, so troops need an escorting ship or plane."""
        engine = self.engine
        player = self.player
        finished = {origin}
        while True:
            size_before = len(finished)
            neighbours = set()
            for name in finished:
                for c in engine.connections:
                    if c.kind == "land" and name in c:
                        neighbours.update(c.connection)
            finished |= {n for n in neighbours if engine.countries[n].owner == player}
            if len(finished) == size_before:
                break
        return finished

    def _has_sea_escort(self, target):
        """Whether a ship or plane has actually been brought along (moved
        into target during this session) to escort troops across water."""
        return target.ships > self.initial_target_ships or target.planes > self.initial_target_planes

    def _select_target(self):
        engine = self.engine
        player = self.player
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.origin_country:
            self.origin_country = None
            player.subattack = 0
        elif hover in self.finished_list:
            origin = engine.countries[self.origin_country]
            target = engine.countries[hover]
            self.target_country = hover
            self.initial_origin = origin.units
            self.initial_target = target.units
            self.initial_origin_ships = origin.ships
            self.initial_target_ships = target.ships
            self.initial_origin_tanks = origin.tanks
            self.initial_target_tanks = target.tanks
            self.initial_origin_planes = origin.planes
            self.initial_target_planes = target.planes
            self.ships_via_sea = hover in self._sea_flood_fill(self.origin_country)
            self.troops_require_sea = hover not in self._land_flood_fill(self.origin_country)
            self.oil_spent_on_planes = 0
            self.move_resource = "units"
            player.subattack = 2

    def _shift_resource(self, origin, target, towards_origin):
        """Move 1 unit of self.move_resource between origin and target."""
        key = self.move_resource

        if key == "ships" and not self.ships_via_sea:
            return  # locked: no unbroken sea route between these two

        if key == "units":
            if self.troops_require_sea and not self._has_sea_escort(target):
                return  # troops can't cross open sea without an escort
            # Same bounded increment/decrement AttackPhase._post_conquest
            # uses while deciding how many troops move into a freshly
            # conquered country: 0 (or the full total) is a deliberate
            # endpoint you land on and stay at, not a value you flicker
            # through via modulo wraparound. This is what makes moving out
            # the very last troop a clean, intentional choice rather than
            # something that could accidentally cycle past 0.
            total_units = origin.units + target.units
            if towards_origin:
                if target.units - 1 < 0 or origin.units + 1 > total_units:
                    target.units = 0
                    origin.units = total_units
                else:
                    target.units -= 1
                    origin.units += 1
            else:
                if origin.units - 1 < 0 or target.units + 1 > total_units:
                    origin.units = 0
                    target.units = total_units
                else:
                    origin.units -= 1
                    target.units += 1
            return

        origin_val = getattr(origin, key)
        target_val = getattr(target, key)
        total = origin_val + target_val + 1
        if towards_origin:
            new_origin = (origin_val + 1) % total
            new_target = (target_val - 1) % total
        else:
            new_origin = (origin_val - 1) % total
            new_target = (target_val + 1) % total

        if key == "planes":
            # Every plane relocated (in either direction, relative to
            # where it started this session) costs 1 oil; moving one back
            # toward its starting country refunds the oil already spent
            # on it. Block the move outright if it would take oil below 0.
            old_delta = abs(target_val - self.initial_target_planes)
            new_delta = abs(new_target - self.initial_target_planes)
            cost_change = new_delta - old_delta
            if cost_change > 0 and self.player.oil < cost_change:
                return
            self.player.oil -= cost_change
            self.oil_spent_on_planes += cost_change

        setattr(origin, key, new_origin)
        setattr(target, key, new_target)

    def _cancel_adjustment(self, origin, target):
        origin.units, target.units = self.initial_origin, self.initial_target
        origin.ships, target.ships = self.initial_origin_ships, self.initial_target_ships
        origin.tanks, target.tanks = self.initial_origin_tanks, self.initial_target_tanks
        origin.planes, target.planes = self.initial_origin_planes, self.initial_target_planes
        self.player.oil += self.oil_spent_on_planes
        self.oil_spent_on_planes = 0
        self.player.subattack = 0

    def _adjust_units(self):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        origin = engine.countries[self.origin_country]
        target = engine.countries[self.target_country]

        # Resource selector: which of troops/ships/tanks/planes does
        # clicking origin/target currently move?
        resources = [
            ("units", "Troops"),
            ("ships", "Ships"),
            ("tanks", "Tanks"),
            ("planes", "Planes"),
        ]
        for i, (key, label) in enumerate(resources):
            x, y = 25 + i * 90, HEIGHT - 320
            selected = self.move_resource == key
            self.draw_rect((100, 100, 255) if selected else (200, 200, 200), x, y, 80, 40)
            self.draw_rect((0, 0, 0), x, y, 80, 40, 3)
            self.blit_text(label, x + 8, y + 12)
            if self.clicked(x, y, x + 80, y + 40):
                self.move_resource = key

        if self.move_resource == "ships" and not self.ships_via_sea:
            self.blit_text("No unbroken sea route -- ships can't move here", 25, HEIGHT - 270)
        elif self.move_resource == "units" and self.troops_require_sea and not self._has_sea_escort(target):
            self.blit_text("No land route -- bring a ship or plane to escort troops", 25, HEIGHT - 270)
        elif self.move_resource == "planes":
            self.blit_text("Planes cost 1 oil each to relocate", 25, HEIGHT - 270)

        if origin.units == 0 or target.units == 0:
            self.blit_text("Emptied country will be abandoned on Confirm", 25, HEIGHT - 240)

        self.draw_rect((170, 0, 0), 25, HEIGHT - 50, 100, 40)
        self.draw_rect((0, 0, 0), 25, HEIGHT - 50, 100, 40, 3)
        self.blit_text("Cancel", 45, HEIGHT - 40)

        self.draw_rect((150, 245, 150), 135, HEIGHT - 50, 100, 40)
        self.draw_rect((0, 0, 0), 135, HEIGHT - 50, 100, 40, 3)
        self.blit_text("Confirm", 148, HEIGHT - 40)

        hover = self.io.hover_country
        if self.io.left_pressed and hover == self.origin_country:
            self._shift_resource(origin, target, towards_origin=True)
        elif self.io.left_pressed and hover == self.target_country:
            self._shift_resource(origin, target, towards_origin=False)
        elif self.clicked(25, HEIGHT - 50, 125, HEIGHT - 10):
            self._cancel_adjustment(origin, target)
            return
        elif self.clicked(135, HEIGHT - 50, 235, HEIGHT - 10):
            # Only now -- on explicit confirmation -- does an emptied
            # country actually flip over to the neutral default_player.
            # Dragging a country's troops down to 0 mid-adjustment (or
            # cycling past 0 via the wraparound) no longer abandons it on
            # the spot.
            if origin.units == 0:
                self.abandon(origin)
            elif target.units == 0:
                self.abandon(target)
            # Only one confirmed reposition is allowed per turn.
            self.player.repositioned_this_turn = True
            self.player.subattack = 0


class ShopPhase(Phase):
    """player.attack == 3 -- building infrastructure and units."""

    def __init__(self, manager):
        super().__init__(manager)
        self.build_origin = None

    def update(self):
        player = self.player
        if player.subattack < 8:
            if self._draw_menu():
                return
        self._handle_placement()
        if player.subattack > 8:
            self._draw_cancel()

    def _draw_menu(self):
        """Returns True if the shop was closed this frame."""
        player = self.player
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        images = engine.images
        bg = engine.colors["card_background"]
        sel = engine.colors["card_selected"]

        self.draw_rect((0, 0, 0), WIDTH - 950, HEIGHT - 630, 60, 60, 2)
        self.draw_rect((170, 230, 170), WIDTH - 900, HEIGHT - 600, 640, 560)
        self.draw_rect((0, 0, 0), WIDTH - 900, HEIGHT - 600, 640, 560, 3)
        self.draw_rect((255, 120, 120), WIDTH - 300, HEIGHT - 590, 30, 30)
        self.draw_rect((0, 0, 0), WIDTH - 300, HEIGHT - 590, 30, 30, 3)
        if self.clicked(WIDTH - 300, HEIGHT - 590, WIDTH - 270, HEIGHT - 560):
            self.manager.close_shop()
            return True

        # Infrastructure: bridge / rails / nuke
        infra = [(1, WIDTH - 870, "spr_bridge"), (2, WIDTH - 720, "spr_rails"), (3, WIDTH - 570, "spr_nuke")]
        affordability = {
            1: player.wood >= 10,
            2: player.wood >= 2 and player.steel >= 1,
            3: player.nuclear >= 5,
        }
        for sub, x, sprite in infra:
            if affordability[sub] and self.clicked(x, HEIGHT - 570, x + 130, HEIGHT - 335):
                player.subattack = 0 if player.subattack == sub else sub
            self.draw_rect(sel if player.subattack == sub else bg, x, HEIGHT - 570, 130, 235)
            self.draw_rect((0, 0, 0), x, HEIGHT - 570, 130, 235, 3)
            images[sprite].draw(view.screen, Position(x + 5, HEIGHT - 565))
        self.blit_text("X 10", WIDTH - 795, HEIGHT - 405)
        images["spr_wood"].draw(view.screen, Position(WIDTH - 835, HEIGHT - 405))
        self.blit_text("X 2", WIDTH - 645, HEIGHT - 435)
        images["spr_wood"].draw(view.screen, Position(WIDTH - 685, HEIGHT - 435))
        self.blit_text("X 1", WIDTH - 645, HEIGHT - 385)
        images["spr_steel"].draw(view.screen, Position(WIDTH - 685, HEIGHT - 385))
        self.blit_text("X 5", WIDTH - 495, HEIGHT - 405)
        images["spr_nuclear"].draw(view.screen, Position(WIDTH - 535, HEIGHT - 405))

        # Units: only buildable when the shop was opened from the
        # reinforcement phase (mirrors running.py's `attack in (0, 4)` guard,
        # simplified since the legacy attack==4 card phase no longer exists).
        if self.manager.saved_attack == 0:
            units = [
                (4, WIDTH - 870, "spr_ship", player.wood >= 15),
                (5, WIDTH - 720, "spr_plane", player.steel >= 10),
                (6, WIDTH - 570, "spr_tank", player.steel >= 20),
                (7, WIDTH - 420, "spr_fort", player.wood >= 10),
            ]
            for sub, x, sprite, affordable in units:
                if affordable and self.clicked(x, HEIGHT - 305, x + 130, HEIGHT - 70):
                    player.subattack = 0 if player.subattack == sub else sub
                self.draw_rect(sel if player.subattack == sub else bg, x, HEIGHT - 305, 130, 235)
                self.draw_rect((0, 0, 0), x, HEIGHT - 305, 130, 235, 3)
                images[sprite].draw(view.screen, Position(x + 5, HEIGHT - 300))
            self.blit_text("X 15", WIDTH - 795, HEIGHT - 140)
            images["spr_wood"].draw(view.screen, Position(WIDTH - 835, HEIGHT - 140))
            self.blit_text("X 10", WIDTH - 645, HEIGHT - 140)
            images["spr_steel"].draw(view.screen, Position(WIDTH - 685, HEIGHT - 140))
            self.blit_text("X 20", WIDTH - 495, HEIGHT - 140)
            images["spr_steel"].draw(view.screen, Position(WIDTH - 535, HEIGHT - 140))
            self.blit_text("X 10/15/20", WIDTH - 400, HEIGHT - 120)
            images["spr_wood"].draw(view.screen, Position(WIDTH - 390, HEIGHT - 170))

        if 0 < player.subattack < 8:
            self.draw_rect((100, 100, 255), WIDTH - 935, HEIGHT - 85, 120, 60)
            self.draw_rect((0, 0, 0), WIDTH - 935, HEIGHT - 85, 120, 60, 3)
            if self.clicked(WIDTH - 935, HEIGHT - 85, WIDTH - 815, HEIGHT - 25):
                player.subattack += 8
        return False

    def _draw_cancel(self):
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        self.draw_rect((250, 100, 100), WIDTH - 935, HEIGHT - 155, 120, 60)
        self.draw_rect((0, 0, 0), WIDTH - 935, HEIGHT - 155, 120, 60, 3)
        if self.clicked(WIDTH - 935, HEIGHT - 155, WIDTH - 815, HEIGHT - 95):
            self.manager.close_shop()

    def _handle_placement(self):
        sub = self.player.subattack
        if sub == 9:
            self._pick_origin(16)
        elif sub == 16:
            self._build_link("sea", "land", cost={"wood": 10}, back=9)
        elif sub == 10:
            self._pick_origin(17)
        elif sub == 17:
            self._build_rails(back=10)
        elif sub == 11:
            self._pick_origin(18)
        elif sub == 18:
            self._build_nuke(back=11)
        elif sub == 12:
            self._build_unit("ships", {"wood": 15})
        elif sub == 13:
            self._build_unit("planes", {"steel": 10})
        elif sub == 14:
            self._build_unit("tanks", {"steel": 20})
        elif sub == 15:
            self._build_fort()

    def _pick_origin(self, next_sub):
        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None and self.engine.countries[hover].owner == self.player:
            self.build_origin = hover
            self.player.subattack = next_sub

    def _build_link(self, kind_from, kind_to, cost, back):
        if self.build_origin is not None:
            self.engine.countries[self.build_origin].shade = 1
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.build_origin:
            self.build_origin = None
            self.player.subattack = back
            return
        for c in self.engine.connections:
            if {self.build_origin, hover} == set(c.connection) and c.kind == kind_from:
                c.kind = kind_to
                self.player.wood -= cost["wood"]
                self.manager.close_shop()
                break

    def _build_rails(self, back):
        engine = self.engine
        view = self.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT

        if self.build_origin is not None:
            engine.countries[self.build_origin].shade = 1

        # Cancel while picking the second country: back out to re-picking
        # an origin without spending anything. Nothing has been charged
        # yet at this point (wood/steel are only deducted once a valid
        # pair is confirmed below), so cancelling here already amounts to
        # a full refund -- the player simply never pays.
        cancel_x, cancel_y = WIDTH - 935, HEIGHT - 225
        self.draw_rect((240, 190, 120), cancel_x, cancel_y, 120, 60)
        self.draw_rect((0, 0, 0), cancel_x, cancel_y, 120, 60, 3)
        self.blit_text("Cancel", cancel_x + 25, cancel_y + 20)
        if self.clicked(cancel_x, cancel_y, cancel_x + 120, cancel_y + 60):
            self.build_origin = None
            self.player.subattack = back
            return

        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.build_origin:
            self.build_origin = None
            self.player.subattack = back
            return
        if self.engine.countries[hover].owner != self.player:
            return
        for c in self.engine.connections:
            if {self.build_origin, hover} == set(c.connection) and c.kind == "land":
                c.rails = True  # draws grey (Connection.draw) and enables rail redistribution
                self.player.wood -= 2
                self.player.steel -= 1
                self.manager.close_shop()
                break

    def _build_nuke(self, back):
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        if hover == self.build_origin:
            self.player.subattack = back
            return
        target = self.engine.countries[hover]
        if target.owner != self.player and self.connected(self.build_origin, hover):
            target.radioactive += 3
            target.units = int(round(target.units / 2))
            if target.units == 0 and target.owner == self.engine.default_player:
                target.units = self.engine.initial_country_units.get(hover, 2)
            self.player.nuclear -= 5
            self.manager.close_shop()

    def _build_unit(self, attr, cost):
        hover = self.io.hover_country
        if self.io.left_pressed and hover is not None and self.engine.countries[hover].owner == self.player:
            country = self.engine.countries[hover]
            setattr(country, attr, getattr(country, attr) + 1)
            for resource, amount in cost.items():
                setattr(self.player, resource, getattr(self.player, resource) - amount)
            self.manager.close_shop()

    def _build_fort(self):
        hover = self.io.hover_country
        if not (self.io.left_pressed and hover is not None):
            return
        country = self.engine.countries[hover]
        cost = 10 + 5 * country.fort_lvl
        if country.owner == self.player and country.fort_lvl <= 2 and self.player.wood >= cost:
            self.player.wood -= cost
            country.fort_lvl += 1
            self.manager.close_shop()


class TurnManager:
    """Owns all Phase instances and the small amount of cross-phase state."""

    def __init__(self, engine):
        self.engine = engine
        self.reinforcements = 0
        self.all_reinforcements_deployed = True
        self.attacked = []
        # Whether the player has conquered at least one non-neutral
        # (i.e. another player's) territory so far this turn -- checked
        # when the turn actually ends to award a card.
        self.conquered_enemy_this_turn = False
        self.turn_num = 0
        self.initial_units = {}
        self.saved_attack = 0
        self.saved_subattack = 0
        self.phases = {
            0: ReinforcementPhase(self),
            1: AttackPhase(self),
            2: MovementPhase(self),
            3: ShopPhase(self),
        }

    def open_shop(self):
        player = self.engine.players[self.engine.turn]
        if player.attack != 3:
            self.saved_attack = player.attack
            self.saved_subattack = player.subattack
            player.attack = 3
            player.subattack = 0

    def close_shop(self):
        player = self.engine.players[self.engine.turn]
        player.attack = self.saved_attack
        player.subattack = self.saved_subattack

    def next_turn(self):
        self.engine.turn = (self.engine.turn + 1) % len(self.engine.players)
        self.turn_num += 1

    def _handle_end_turn_button(self):
        engine = self.engine
        player = engine.players[engine.turn]
        view = engine.view
        WIDTH, HEIGHT = view.WIDTH, view.HEIGHT
        index = min(player.attack + 1, 2)
        x = WIDTH - 200 + 70 * index
        if self.all_reinforcements_deployed and engine.io.left_pressed and \
                x <= engine.io.mouse_position.x <= x + 60 and \
                HEIGHT - 50 <= engine.io.mouse_position.y <= HEIGHT - 10:
            player.attack = (player.attack + 1) % 3
            player.subattack = 0
            if player.attack == 1:
                self.phases[1].reset()
            if player.attack == 2:
                player.repositioned_this_turn = False
                self.phases[2].reset()
            if player.attack == 0:
                if self.conquered_enemy_this_turn:
                    player.cards.append(Kaertske(int(np.random.randint(0, 4)), images=engine.images))
                self.conquered_enemy_this_turn = False
                self.next_turn()

    def update(self):
        engine = self.engine
        player = engine.players[engine.turn]

        # Clear any highlighting a phase set last frame (e.g. attack/defence
        # selection) so it doesn't linger once no longer relevant.
        for country in engine.countries.values():
            country.shade = 0

        # Every player's very first turn (i.e. we haven't yet completed a
        # full round of turn_num increments) skips recruiting entirely and
        # starts straight in the attack phase, using whatever they started
        # the game with.
        if player.attack == 0 and player.subattack == 0 and self.turn_num < len(engine.players):
            player.attack = 1
            player.subattack = 0
            self.attacked = []
            self.conquered_enemy_this_turn = False
            self.phases[1].reset()

        # Too many cards: force the (existing) card menu open instead of the
        # legacy attack==4 integer-card phase from running.py.
        if ((player.attack == 0 and player.subattack == 1) or player.attack == 1) and len(player.cards) >= 5:
            engine.card_menu.show = True

        phase = self.phases.get(player.attack)
        if phase is not None:
            phase.update()

        self._handle_end_turn_button()
