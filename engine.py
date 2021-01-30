import pygame as pg
import numpy as np
from board import get_connections, get_countries
from models import Position, Image, Player, Io, View, Gui, Shop, Button, CardMenu, Kaertske
from random import sample


class Engine:

    def __init__(self, width=960, height=640):
        pg.init()
        pg.font.init()
        self.font = pg.font.SysFont('Times New Roman', 20)
        self.view = View(
            screen=pg.display.set_mode([width, height]),
            zoom=1.21,
            offset=Position(-401, -240),
            WIDTH=width,
            HEIGHT=height,
        )

        self.io = Io()

        self.colors = {
            "card_background": (240, 240, 240),
            "card_selected": (200, 200, 200),
            "red_button": (245, 150, 150),
            "green_button": (150, 245, 150),
            "outlines": (0, 0, 0),
            "land": (0, 155, 0),
            "sea": (0, 150, 235),
            "rails": (100, 100, 100),
        }

        self.images = {
            "nuclear": Image("nuclear"),
            "spr_food": Image("food"),
            "spr_troops": Image("troops"),
            "spr_wood": Image("wood"),
            "spr_oil": Image("oil"),
            "spr_steel": Image("steel"),
            "spr_nuclear": Image("nuclear"),
            "spr_shop": Image("shop"),
            "spr_cards": Image("cards"),
            "spr_card0": Image("card0"),
            "spr_card1": Image("card1"),
            "spr_card2": Image("card2"),
            "spr_bridge": Image("bridge"),
            "spr_ship": Image("ship"),
            "spr_plane": Image("plane"),
            "spr_tank": Image("tank"),
            "spr_rails": Image("rails"),
            "spr_fort": Image("fort"),
            "spr_nuke": Image("nuke"),
        }

        self.gui = Gui(self.io, outline_color=self.colors["outlines"])

        self.default_player = Player("mouse", color=(200, 200, 200))
        self.players = self.get_players()
        self.countries = get_countries(self.default_player)
        self.connections = get_connections()

        self.reinforcements = 0
        self.all_reinforcements_deployed = True
        self.checked = False
        self.attacked = []
        self.turn_num = 0
        self.card_limit = 0
        self.turn = np.random.randint(len(self.players))

        self.card_menu = CardMenu(self.view, self.players[self.turn])

        for index, country in enumerate(sample(self.countries.keys(), len(self.players))):
            self.countries[country].owner = self.players[index]
            self.countries[country].units = 15

    def draw_world(self, background_color=(200, 200, 255)):
        self.view.screen.fill(background_color)
        for country in self.countries.values():
            country.draw(self.view, border_color=self.colors["outlines"])
        for connection in self.connections:
            connection.draw(self.countries, self.colors, self.view, outline_color=self.colors["outlines"])
        for country in self.countries.values():
            country.draw_troops(self.font, self.view, outline_color=self.colors["outlines"])
            country.draw_assets(
                view=self.view,
                img_ship=self.images["spr_ship"],
                img_plane=self.images["spr_plane"],
                img_fort=self.images["spr_fort"],
                img_tank=self.images["spr_tank"],
                img_nuclear=self.images["spr_nuke"],
            )

    def draw_gui(self):
        def handle_card_menu():
            self.card_menu.player = self.players[self.turn]
            self.card_menu.show = not self.card_menu.show
            self.card_menu.organize_cards()
            self.card_menu.use_cards_automatic()

        self.gui.draw_overlay(self.view)
        if self.io.hover_country is not None:
            self.gui.draw_country_stats(
                view=self.view,
                country=self.countries[self.io.hover_country],
                font=self.font,
                images=self.images,
            )
        self.gui.draw_player_stats(self.view, self.players[self.turn], self.font, self.images)
        self.gui.draw_attack_phase(self.view, self.players[self.turn], outline_color=self.colors["outlines"])
        card_menu_button = Button(
            pos=Position(100, 20),
            width=60,
            height=60,
            color=(100, 100, 255),
            image=self.images['spr_cards']
        )
        card_menu_button.draw(self.view, self.io)
        card_menu_button.release_button(handle_card_menu, self.io)
        shop_menu_button = Button(
            pos=Position(20, 20),
            width=60,
            height=60,
            color=(170, 230, 170),
            image=self.images['spr_shop'],
        )
        shop_menu_button.draw(self.view, self.io)
        shop_menu_button.release_button(lambda: Shop(), self.io)

    def control_card_menu(self):
        self.card_menu.draw_cards()
        self.card_menu.use_cards(self.io)
        self.card_menu.draw_trade_button(self.io, self.font)

    def io_handle(self):
        self.io.update(self.view, self.countries.values())
        self.view.offset = self.io.drag_map(self.view.offset)

    def get_players(self):
        default = input("Play default? ")
        if default in {"yes", "y", "Y", "YES"}:
            return [
                Player("Hugo", cards=[Kaertske(np.random.randint(4), images=self.images) for i in range(np.random.randint(6))]),
                Player("Joeri", cards=[Kaertske(np.random.randint(4), images=self.images) for i in range(np.random.randint(6))]),
                Player("Tètè", cards=[Kaertske(np.random.randint(4), images=self.images) for i in range(np.random.randint(6))]),
            ]
        else:
            while True:
                try:
                    player_num = int(input("How many players? "))
                    break
                except ValueError:
                    pass
            return [Player(input("Player {}'s name? ".format(i + 1))) for i in range(player_num)]
