import pygame as pg
from board import get_connections, get_countries


def transform_coordinates(point, zoom, xoffset, yoffset):
    return int((point[0] + xoffset)*zoom + 0.5*WIDTH), int((point[1] + yoffset)*zoom + 0.5*HEIGHT)


def screen_to_coordinates(point, zoom, xoffset, yoffset):
    return int((point[0] - 0.5*WIDTH)/zoom - xoffset), int((point[1] - 0.5*HEIGHT)/zoom - yoffset)


def show_die(eyes, x, y):
    if eyes == 1:
        pg.draw.circle(screen, (0,0,0), (x, y), 3)
    elif eyes == 2:
        pg.draw.circle(screen, (0,0,0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y - 12), 3)
    elif eyes == 3:
        pg.draw.circle(screen, (0,0,0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x, y), 3)
    elif eyes == 4:
        pg.draw.circle(screen, (0,0,0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x - 12, y - 12), 3)
    elif eyes == 5:
        pg.draw.circle(screen, (0, 0, 0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0, 0, 0), (x + 12, y - 12), 3)
        pg.draw.circle(screen, (0, 0, 0), (x + 12, y + 12), 3)
        pg.draw.circle(screen, (0, 0, 0), (x - 12, y - 12), 3)
        pg.draw.circle(screen, (0, 0, 0), (x, y), 3)
    elif eyes == 6:
        pg.draw.circle(screen, (0,0,0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x - 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x - 12, y), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y), 3)


class Player:
    def __init__(
            self,
            name,
            cards=[],
            food=45,
            wood=100,
            steel=100,
            nuclear=100,
            oil=100,
            color=None,
            troops=0,
            start_ship=True,
    ):
        self.name = name
        self.cards = cards
        self.food = food
        self.wood = wood
        self.steel = steel
        self.nuclear = nuclear
        self.oil = oil
        self.color = color
        self.troops = troops
        self.attack = 6
        self.subattack = 0
        self.start_ship = start_ship
        if self.color is None:
            self.color = 255*np.random.rand(3)


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
    ):
        self.polygon = polygon
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

        center = np.average(np.array([np.average(p, axis=0) for p in polygon]), axis=0)
        if name in ["Sri Lanka", "Japan", "Cuba", "Pearl Harbor"]:
            center += np.array([0, 20])
        if name == "IJsland":
            center += np.array([-10, 10])
        if name == "Canada":
            center += np.array([-30, 30])
        self.mass_center = Position(int(center[0]), int(center[1]))


class Connection:

    def __init__(self, connection, kind, rails = False):
        self.connection = connection
        self.kind = kind
        self.rails = rails

    def __contains__(self, other):
        return other in self.connection


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


class Image:

    def __init__(self, name):
        self.image = pg.image.load("./images/{}.png".format(name)).convert()
        self.name = name

    def draw(self, screen, pos):
        screen.blit(self.image, (pos.x, pos.y))


class Engine:

    def __init__(self, width=960, height=640):
        pg.init()
        pg.fony.init()
        self.font = pg.font.SysFont('Times New Roman', 20)
        self.WIDTH = width
        self.HEIGHT = height
        self.zoom = 1.21
        self.offset = Position(-401, -240)
        self.mouse_position = Position(0, 0)
        self.mouse_state = (0, 0, 0)
        self.screen = pg.display.set_mode([self.WIDTH, self.HEIGHT])

        self.colors = {
            "card_background": (240, 240, 240),
            "card_selected": (200, 200, 200),
            "red_button": (245, 150, 150),
            "green_button": (150, 245, 150),
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
        self.default_player = Player("mouse", color=(200, 200, 200))
        self.players = get_players()
        self.countries = get_countries(self.default_player)
        self.connections = get_connections()

        self.reinforcements = 0
        self.all_reinforcements_deployed = True
        self.checked = False
        self.attacked = []
        self.turn_num = 0
        self.card_limit = 0
        self.turn = np.random.randint(len(self.players))


def get_players():
    default = input("Play default? ")
    if default in {"yes", "y", "Y", "YES"}:
        return [Player("Hugo"), Player("Joeri"), Player("Tètè")]
    else:
        while True:
            try:
                player_num = int(input("How many players? "))
                break
            except ValueError:
                pass
        return [Player(input("Player {}'s name? ".format(i + 1))) for i in range(player_num)]


def init():






    i = 0
    for country in np.random.choice(countries, player_num, replace = False):
        country.owner = players[i]
        country.units = 15
        i += 1
    
