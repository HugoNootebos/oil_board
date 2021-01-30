import numpy as np
import pygame as pg
from matplotlib.path import Path


class Player:

    def __init__(
            self,
            name,
            cards=None,
            food=45,
            wood=100,
            steel=100,
            nuclear=100,
            oil=100,
            color=None,
            troops=0,
            start_ship=True,
    ):
        if cards is None:
            cards = list()
        self.name = name
        self.cards = cards
        self.food = food
        self.wood = wood
        self.steel = steel
        self.nuclear = nuclear
        self.oil = oil
        self.color = color
        self.troops = troops
        self.attack = 0
        self.subattack = 0
        self.start_ship = start_ship
        if self.color is None:
            self.color = 255 * np.random.rand(3)


class Kaertske:

    def __init__(
            self,
            type,
            images,
            width=75,
            height=150,
            color=(200, 200, 255),
            outline_color=(0, 0, 0),
            outline_width=2
    ):
        self.name_mapping = {
            0: 'Menneke',
            1: 'Paerd',
            2: 'Vliegtuig',
            3: 'Joker',
        }
        self.sprite_mapping = {
            0: images['spr_card0'],
            1: images['spr_card1'],
            2: images['spr_card2'],
            3: images['spr_nuke']
        }
        self.name = self.name_mapping[type]
        self.type = type
        self.use = False
        self.width = width
        self.height = height
        self.color = color
        self.outline_color = outline_color
        self.use_height = 20
        self.pos = Position(0, 0)
        self.outline_width = outline_width

    def draw(self, view):
        pg.draw.rect(
            view.screen,
            self.color,
            pg.Rect(self.pos.x, self.pos.y - self.use_height * self.use, self.width, self.height),
        )
        pg.draw.rect(
            view.screen,
            self.outline_color,
            pg.Rect(self.pos.x, self.pos.y - self.use_height * self.use, self.width, self.height),
            self.outline_width,
        )
        self.sprite_mapping[self.type].draw(view.screen, self.pos - Position(0, self.use_height * self.use))

    def update_use_manual(self, io):
        h = self.use_height * self.use
        if (
                self.pos.x < io.mouse_position.x < self.pos.x + self.width and
                self.pos.y - h < io.mouse_position.y < self.pos.y - h + self.height and
                io.left_pressed
        ):
            self.use = not self.use


class Country:

    def __init__(
            self,
            name,
            polygon,
            owner,
            food=0,
            wood=0,
            steel=0,
            nuclear=0,
            oil=0,
            troops=0,
            units=2,
            ships=0,
            planes=0,
            tanks=0,
            fort_lvl=0,
            radioactive=0,
            developed=False,
            shade=0,
    ):
        self.raw_polygon = polygon
        # Transform python tuples to Position object:
        self.polygon = [
            [
                Position(point[0], point[1]) for point in pol
            ] for pol in polygon
        ]
        # Pass other variables to object
        self.name = name
        self.food = food
        self.wood = wood
        self.steel = steel
        self.nuclear = nuclear
        self.oil = oil
        self.owner = owner
        self.troops = troops
        self.units = units
        self.ships = ships
        self.planes = planes
        self.tanks = tanks
        self.fort_lvl = fort_lvl
        self.radioactive = radioactive
        self.developed = developed
        self.shade = shade

        center = np.average(np.array([np.average(p, axis=0) for p in polygon]), axis=0)
        if name in ["Sri Lanka", "Japan", "Cuba", "Pearl Harbor"]:
            center += np.array([0, 20])
        if name == "IJsland":
            center += np.array([-10, 10])
        if name == "Canada":
            center += np.array([-30, 30])
        self.mass_center = Position(int(center[0]), int(center[1]))

    def point_in_country(self, point):
        for pol in self.raw_polygon:
            if Path(pol).contains_point((point.x, point.y)):
                return True
        return False

    def draw(
            self,
            view,
            shading_factor=50,
            border_width=2,
            border_color=(0, 0, 0)
    ):
        for pol in self.polygon:
            transformed_coordinates = [
                point.transform_coordinates(
                    view
                ).to_tuple() for point in pol
            ]
            pg.draw.polygon(
                view.screen,
                np.clip(self.owner.color + self.shade * shading_factor * np.array([1, 1, 1]), 0, 255),
                transformed_coordinates,
            )
            pg.draw.polygon(view.screen, border_color, transformed_coordinates, border_width)

    def draw_troops(
            self,
            font,
            view,
            circle_color=(255, 255, 255),
            circle_radius=14,
            outline_color=(0, 0, 0),
            outline_width=2,
    ):
        pos = self.mass_center.transform_coordinates(view).to_tuple()
        pg.draw.circle(view.screen, outline_color, pos, circle_radius)
        pg.draw.circle(view.screen, circle_color, pos, circle_radius - outline_width)
        view.screen.blit(font.render(str(self.units), False, outline_color), (pos[0] - 9, pos[1] - 10))

    def draw_assets(self, view, img_ship, img_tank, img_plane, img_fort, img_nuclear):
        pos = self.mass_center.transform_coordinates(view)
        if self.ships > 0:
            img_ship.draw(view.screen, pos + Position(-19, -20))
        if self.tanks > 0:
            img_tank.draw(view.screen, pos + Position(-14, -10))
        if self.planes > 0:
            img_plane.draw(view.screen, pos + Position(-9, 0))
        if self.fort_lvl > 0:
            img_fort.draw(view.screen, pos + Position(-4, 10))
        if self.radioactive > 0:
            img_nuclear.draw(view.screen, pos + Position(1, 20))


class Connection:

    def __init__(self, connection, kind):
        self.connection = connection
        self.kind = kind

    def __contains__(self, other):
        return other in self.connection

    def draw(
            self,
            countries,
            connection_colors,
            view,
            outline_color=(0, 0, 0),
            line_width=5,
            outline_width=2,
    ):
        transformed_coordinates = [
            countries[country_name].mass_center.transform_coordinates(
                view
            ).to_tuple() for country_name in self.connection
        ]
        if {"Alaska", "Siberië"}.issubset(self.connection) or {"Japan", "Pearl Harbor"}.issubset(self.connection):
            swap = transformed_coordinates[0][0] < transformed_coordinates[0][1]
            transformed_coordinates = [
                transformed_coordinates[0],
                (view.WIDTH * (not swap), transformed_coordinates[0][1]),
                transformed_coordinates[1],
                (view.WIDTH * swap, transformed_coordinates[1][1]),
            ]
        for pos1, pos2 in zip(transformed_coordinates[0::2], transformed_coordinates[1::2]):
            pg.draw.line(
                view.screen,
                outline_color,
                pos1,
                pos2,
                line_width,
            )
            pg.draw.line(
                view.screen,
                connection_colors[self.kind],
                pos1,
                pos2,
                line_width - outline_width,
            )


class Position:

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Position(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Position(self.x - other.x, self.y - other.y)

    def __str__(self):
        return "({}, {})".format(self.x, self.y)

    def transform_coordinates(self, view):
        return Position(
            int((self.x + view.offset.x) * view.zoom + 0.5 * view.WIDTH),
            int((self.y + view.offset.y) * view.zoom + 0.5 * view.HEIGHT),
        )

    def screen_to_coordinates(self, view):
        return Position(
            int((self.x - 0.5 * view.WIDTH) / view.zoom - view.offset.x),
            int((self.y - 0.5 * view.HEIGHT) / view.zoom - view.offset.y),
        )

    def to_tuple(self):
        return self.x, self.y


class Image:

    def __init__(self, name):
        self.image = pg.image.load("./images/{}.png".format(name)).convert()
        self.name = name

    def draw(self, screen, pos):
        screen.blit(self.image, (pos.x, pos.y))


class Dice:

    def __init__(self, color, used=0, eyes=0):
        self.color = color
        self.used = used
        self.eyes = eyes

    def draw(
            self,
            screen,
            pos,
            dot_color=(0, 0, 0),
            dot_width=3,
            size=70,
    ):
        # draw square
        square = pg.Rect(pos.x - 0.5 * size, pos.y - 0.5 * size, size, size)
        pg.draw.rect(screen, self.color, square)
        # Outline
        pg.draw.rect(screen, dot_color, square, dot_width)
        # Draw dots
        if self.eyes in {1, 3, 5}:
            pg.draw.circle(screen, dot_color, (pos.x, pos.y), dot_width)
        if self.eyes in {2, 3, 4, 5, 6}:
            pg.draw.circle(screen, dot_color, (pos.x - 12, pos.y + 12), dot_width)
            pg.draw.circle(screen, dot_color, (pos.x + 12, pos.y - 12), dot_width)
        if self.eyes in {4, 5, 6}:
            pg.draw.circle(screen, dot_color, (pos.x + 12, pos.y + 12), dot_width)
            pg.draw.circle(screen, dot_color, (pos.x - 12, pos.y - 12), dot_width)
        if self.eyes == 6:
            pg.draw.circle(screen, dot_color, (pos.x + 12, pos.y), dot_width)
            pg.draw.circle(screen, dot_color, (pos.x - 12, pos.y), dot_width)


class Io:

    def __init__(self):
        self.mouse_state = [0, 0, 0]
        self.previous_mouse_state = [0, 0, 0]
        self.left_pressed = 0
        self.mouse_position = Position(0, 0)
        self.transformed_mouse_position = Position(0, 0)
        self.previous_mouse_position = Position(0, 0)
        self.previous_transformed_mouse_position = Position(0, 0)
        self.hover_country = None

    def update(self, view, countries):
        self.previous_mouse_state = self.mouse_state
        self.mouse_state = pg.mouse.get_pressed()
        self.left_pressed = not self.previous_mouse_state[0] and self.mouse_state[0]
        self.previous_mouse_position = self.mouse_position
        current_pos = pg.mouse.get_pos()
        self.mouse_position = Position(current_pos[0], current_pos[1])
        self.transformed_mouse_position = self.mouse_position.screen_to_coordinates(view)
        self.previous_transformed_mouse_position = self.previous_mouse_position.screen_to_coordinates(view)
        # Update hover_country
        self.hover_country = None
        for country in countries:
            if country.point_in_country(self.transformed_mouse_position):
                self.hover_country = country.name

    def drag_map(self, offset):
        if self.mouse_state[1]:
            return offset + self.transformed_mouse_position - self.previous_transformed_mouse_position
        return offset


class View:

    def __init__(self, screen, zoom, offset, WIDTH, HEIGHT):
        self.screen = screen
        self.zoom = zoom
        self.offset = offset
        self.WIDTH = WIDTH
        self.HEIGHT = HEIGHT


class Button:

    def __init__(self, pos, width, height, color, outline_color=(0, 0, 0), outline_width=2, image=None):
        self.pos = pos
        self.width = width
        self.height = height
        self.color = color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.image = image

    def draw(self, view, io):
        mouse_in_button = (self.pos.x < io.mouse_position.x < self.pos.x + self.width and
                           self.pos.y < io.mouse_position.y < self.pos.y + self.height)
        w = 3 * mouse_in_button
        shade = 40 * (mouse_in_button and io.mouse_state[0])
        pg.draw.rect(
            view.screen,
            [max(col - shade, 0) for col in self.color],
            pg.Rect(self.pos.x - w, self.pos.y - w, self.width + 2 * w, self.height + 2 * w)),
        pg.draw.rect(
            view.screen,
            self.outline_color,
            pg.Rect(self.pos.x - w, self.pos.y - w, self.width + 2 * w, self.height + 2 * w),
            self.outline_width
        )
        if self.image is not None:
            self.image.draw(view.screen, self.pos)

    def release_button(self, function_to_execute, io):
        mouse_in_button = (self.pos.x < io.mouse_position.x < self.pos.x + self.width and
                           self.pos.y < io.mouse_position.y < self.pos.y + self.height)
        if mouse_in_button and io.left_pressed:
            function_to_execute()


class Gui:

    def __init__(
            self,
            io,
            gray1=(200, 200, 200),
            gray2=(150, 150, 150),
            width=210,
            height=400,
            outline_color=(0, 0, 0),
    ):
        self.gray1 = gray1
        self.gray2 = gray2
        self.width = width
        self.height = height
        self.outline_color = outline_color
        self.io = io

    def draw_overlay(self, view):
        pg.draw.rect(
            view.screen,
            self.gray1,
            pg.Rect(view.WIDTH - self.width, 0, self.width, view.HEIGHT - self.height),
        )
        pg.draw.rect(
            view.screen,
            self.gray2,
            pg.Rect(view.WIDTH - self.width, view.HEIGHT - self.height, self.width, view.HEIGHT),
        )

    def draw_country_stats(self, view, country, font, images):
        view.screen.blit(
            font.render(country.name, False, self.outline_color),
            (view.WIDTH - self.width + 10, 0),
        )
        image_list = [images["spr_food"]] * country.food + \
                     [images["spr_wood"]] * country.wood + \
                     [images["spr_steel"]] * country.steel + \
                     [images["spr_oil"]] * country.oil + \
                     [images["spr_nuclear"]] * country.nuclear + \
                     [images["spr_troops"]] * country.troops
        for index, image in enumerate(image_list):
            image.draw(
                view.screen,
                Position(
                    view.WIDTH - self.width + 10 + (index % 4) * 50,
                    30 + int(index / 4) * 50,
                )
            )

    def draw_player_stats(self, view, player, font, images):
        pg.draw.rect(
            view.screen,
            player.color,
            pg.Rect(view.WIDTH - self.width, view.HEIGHT - self.height, self.width, 20)
        )
        view.screen.blit(
            font.render(
                player.name,
                False,
                self.outline_color,
            ),
            (
                view.WIDTH - self.width + 10,
                view.HEIGHT - self.height
            ),
        )
        resource_stats = [
            (images["spr_food"], player.food, 0),
            (images["spr_wood"], player.wood, 1),
            (images["spr_steel"], player.steel, 2),
            (images["spr_oil"], player.oil, 3),
            (images["spr_nuclear"], player.nuclear, 4),
            (images["spr_troops"], player.troops, 5),
        ]
        for image, amount, index in resource_stats:
            pos = Position(
                view.WIDTH - self.width * 0.7,
                view.HEIGHT - self.height + (index + 1) * 50,
            )
            image.draw(view.screen, pos)
            view.screen.blit(
                font.render("X {}".format(amount), False, self.outline_color),
                (pos + Position(50, 0)).to_tuple()
            )

    def draw_attack_phase(
            self,
            view,
            player,
            outline_color=(0, 0, 0),
            colors=[(224, 224, 0), (255, 80, 79), (255, 165, 0)],
            outline_width=2,
    ):
        for index, color in enumerate(colors):
            Button(
                pos=Position(view.WIDTH - self.width + 5 + 70 * index, view.HEIGHT - 50),
                width=60,
                height=40,
                color=color,
                outline_color=outline_color,
                outline_width=outline_width if player.attack == index else 1,
                image=None,
            ).draw(view, self.io)


class Shop:
    def __init__(self):
        print('shop')


class CardMenu:

    def __init__(self, view, player):
        self.player = player
        self.view = view
        self.show = False
        self.organize_cards()
        self.use_cards_automatic()

    def organize_cards(self):
        for index, card in enumerate(self.player.cards):
            card.pos = Position(
                x=self.view.WIDTH * 0.5 - (card.width + 20) * len(self.player.cards) * 0.5 + (card.width + 20) * index,
                y=self.view.HEIGHT * 0.5 - card.height * 0.5,
            )
            card.use = False

    def draw_cards(self):
        if self.show:
            for card in self.player.cards:
                card.draw(self.view)

    def use_cards(self, io):
        if self.show:
            for card in self.player.cards:
                card.update_use_manual(io)

    def draw_trade_button(self, io, font):
        use_cards = [card for card in self.player.cards if card.use]
        if self.show and len(use_cards) == 3:
            possible_equal_sets, possible_different_set = self.check_set(use_cards)
            if possible_different_set or len(possible_equal_sets) > 0:
                pos = Position(self.view.WIDTH*0.5 - 100, self.view.HEIGHT - 100)
                button = Button(pos, 200, 50, (255, 0, 0))
                button.draw(self.view, io)
                trade_amount = 10 if possible_different_set else possible_equal_sets[0]*2 + 4
                self.view.screen.blit(
                    font.render("TRADE FOR {} ACCEPT".format(trade_amount), False, (0, 0, 0)),
                    (pos + Position(50, 0)).to_tuple()
                )

    def use_cards_automatic(self):
        possible_equal_sets, possible_different_set = self.check_set(self.player.cards)
        if possible_different_set:
            for i in range(3):
                found_i = False
                for card in self.player.cards:
                    if card.type == i:
                        found_i = True
                        card.use = True
                        break
                if not found_i:
                    for card in self.player.cards:
                        if card.type == 3 and not card.use:
                            card.use = True
                            break
        else:
            if len(possible_equal_sets) > 0:
                for i in range(3):
                    found = False
                    for card in self.player.cards:
                        if card.type == max(possible_equal_sets) and not card.use:
                            found = True
                            card.use = True
                            break
                    if not found:
                        for card in self.player.cards:
                            if card.type == 3 and not card.use:
                                card.use = True
                                break

    @staticmethod
    def check_set(cardlist):
        possible_equal_sets = [i for i in range(3) if sum([k.type in {i, 3} for k in cardlist]) >= 3]
        possible_different_set = len(set([k.type for k in cardlist if k.type != 3])) + len(
            [k.type for k in cardlist if k.type == 3]) >= 3
        return possible_equal_sets, possible_different_set


class Reinforcement:

    def cards(self):


        def update_use_automatic(card_list):
            possible_equal_sets, possible_different_set = check_set(card_list)


    def reinforce(self):
        self.check_warning()
        self.feed_troops()
        self.add_resources()
        self.deploy_troops()

    def add_troops(self):
        pass

    def feed_troops(self):
        pass
