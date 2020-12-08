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
        pg.draw.circle(screen, (0,0,0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x - 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x, y), 3)
    elif eyes == 6:
        pg.draw.circle(screen, (0,0,0), (x - 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y + 12), 3)
        pg.draw.circle(screen, (0,0,0), (x - 12, y - 12), 3)
        pg.draw.circle(screen, (0,0,0), (x - 12, y), 3)
        pg.draw.circle(screen, (0,0,0), (x + 12, y), 3)


class Player:
    def __init__(self, name, cards = [0,2,1,1,1,1,2,2], food = 45, wood = 100, steel = 100, nuclear = 100, oil = 100, color = None, troops = 0, start_ship = True):
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
    def __init__(self, name, polygon, food = 0, wood = 0, steel = 0, nuclear = 0, oil = 0, owner = default_player, troops = 0, units = 2, ships = 0, planes = 0, tanks = 0, fort_lvl = 0, radioactive = 0, developed = False):
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
        center = np.average(np.array([np.average(p, axis = 0) for p in polygon]), axis = 0)
        if name in ["Sri Lanka", "Japan", "Cuba", "Pearl Harbor"]:
            center += np.array([0, 20])
        if name == "IJsland":
            center += np.array([-10, 10])
        if name == "Canada":
            center += np.array([-30,30])
        self.mass_center = (int(center[0]), int(center[1]))
        
class Connection:
    def __init__(self, connection, kind, rails = False):
        self.connection = connection
        self.kind = kind
        self.rails = rails
    def __contains__(self, other):
        return other in self.connection


def init():
    pg.init()

    pg.font.init()
    myfont = pg.font.SysFont('Times New Roman', 20)

    WIDTH = 960
    HEIGHT = 640

    zoom = 1.21
    xoffset = -401
    yoffset = -240
    mouse_position = (0, 0)
    mouse_state = (0, 0, 0)

    screen = pg.display.set_mode([WIDTH, HEIGHT])

    #–––––––––––––––––––––––––– change the directories depending on user ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

    spr_nuclear = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/nuclear.png")
    spr_nuclear.convert()
    spr_food = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/food.png")
    spr_food.convert()
    spr_troops = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/troops.png")
    spr_troops.convert()
    spr_wood = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/wood.png")
    spr_wood.convert()
    spr_oil = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/oil.png")
    spr_oil.convert()
    spr_steel = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/steel.png")
    spr_steel.convert()
    spr_nuclear = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/nuclear.png")
    spr_nuclear.convert()
    spr_shop = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/shop.png")
    spr_shop.convert()
    spr_cards = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/cards.png")
    spr_cards.convert()
    spr_card0 = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/card0.png")
    spr_card0.convert()
    spr_card1 = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/card1.png")
    spr_card1.convert()
    spr_card2 = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/card2.png")
    spr_card2.convert()
    spr_bridge = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/bridge.png")
    spr_bridge.convert()
    spr_ship = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/ship.png")
    spr_ship.convert()
    spr_plane = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/plane.png")
    spr_plane.convert()
    spr_tank = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/tank.png")
    spr_tank.convert()
    spr_rails = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/rails.png")
    spr_rails.convert()
    spr_fort = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/fort.png")
    spr_fort.convert()
    spr_nuke = pg.image.load("/Users/hugo.nootebos019/Desktop/oil_app/oil_images/nuke.png")
    spr_nuke.convert()

    #–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

    #colour settings
    card_background = (240,240,240)
    card_selected = (200,200,200)
    red_button = (245,150,150)
    green_button = (150,245,150)

    running = True

    default_player = Player("mouse", color = (200,200,200))
    players = []
    reinforcements = 0
    all_reinforcements_deployed = True
    checked = False
    attacked = []
    turn_num = 0
    card_limit = 0
    defaultTrue = input("Play default? ")
    if defaultTrue == "yes" or defaultTrue == "y" or defaultTrue == "Y" or defaultTrue == "YES":
        player_num = 3
        players = [Player("Hugo"), Player("Joeri"), Player("Tètè")]
    else:
        player_num = int(input("How many players? "))
        for i in range(player_num):
            players += [Player(input("Player " + str(i + 1) + "'s name? "))]

    turn = np.random.randint(player_num)

    i = 0
    for country in np.random.choice(countries, player_num, replace = False):
        country.owner = players[i]
        country.units = 15
        i += 1
    
