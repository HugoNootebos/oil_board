"""
The game's language: Dutch ("nl") or English ("en"), switched with the
flag in the main menu and remembered in saves/settings.json.

Everything on screen goes through t() (or Msg, for the action log, which
translates whenever it's drawn): UI text is written in English in
the code and NL gives its Dutch; the board and the events are written in
Dutch and EN gives their English. Formatted text is translated before
it's formatted, e.g. t("{} wins!").format(name), and names that are also
identifiers (countries, continents, events, cards) only at the moment
they're shown -- the game itself keeps using the original names.

New text on screen: wrap it in t() and add it to NL (English source) or
EN (Dutch source).
"""

import json
import os

# Next to the saves (save_load.SAVE_DIR), so the app keeps it on the device too.
SETTINGS_PATH = os.path.join(os.environ.get("OIL_SAVES_DIR") or "saves", "settings.json")
LANGUAGES = ("nl", "en")
DEFAULT_LANGUAGE = "nl"


def read_settings():
    """Everything in saves/settings.json (the language, and online play's
    device id and server address, see net.py); {} if there's nothing."""
    try:
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def write_setting(key, value):
    """Remember `key` in saves/settings.json, keeping the other settings."""
    settings = read_settings()
    settings[key] = value
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f)
    except OSError:
        pass  # still in effect for this session


def _load_language():
    code = read_settings().get("language")
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


language = _load_language()


def set_language(code):
    """Switch to `code` and remember it for the next time the game starts."""
    global language
    language = code
    write_setting("language", code)


def t(text):
    """`text` in the current language (unchanged when there's no translation)."""
    if language == "nl":
        return NL.get(text, text)
    return EN.get(text, text)


class Msg:
    """Text that is translated each time it's shown rather than once, for
    the action log (which is saved, and may be read in the other language
    later): str(Msg(" took {} from ", "Spanje")) is
    t(" took {} from ").format(t("Spanje")). Arguments: numbers as they
    are, strings through t() (country names, resource words), Msgs as
    their own str()."""

    def __init__(self, template, *args):
        self.template = template
        self.args = args

    @staticmethod
    def _arg(arg):
        if isinstance(arg, Msg):
            return str(arg)
        if isinstance(arg, str):
            return t(arg)
        return arg

    def __str__(self):
        return t(self.template).format(*(self._arg(a) for a in self.args))

    def to_json(self):
        return {"msg": self.template, "args": [a.to_json() if isinstance(a, Msg) else a for a in self.args]}

    @staticmethod
    def from_json(data):
        """A Msg back from to_json; anything else (text from an older save) as it was."""
        if not isinstance(data, dict):
            return data
        if "join" in data:
            return Join([Msg.from_json(a) for a in data["join"]], data.get("sep", ", "), data.get("last"))
        return Msg(data.get("msg", ""), *(Msg.from_json(a) for a in data.get("args", [])))


class Join(Msg):
    """`items` (as Msg arguments) joined by `sep`, the last one by `last`
    (e.g. " and ") if given."""

    def __init__(self, items, sep=", ", last=None):
        super().__init__("")
        self.items, self.sep, self.last = list(items), sep, last

    def __str__(self):
        items = [str(self._arg(item)) for item in self.items]
        if self.last is None or len(items) < 2:
            return t(self.sep).join(items)
        return t(self.sep).join(items[:-1]) + t(self.last) + items[-1]

    def to_json(self):
        return {"join": [a.to_json() if isinstance(a, Msg) else a for a in self.items],
                "sep": self.sep, "last": self.last}


# --- English source -> Dutch ------------------------------------------------

NL = {
    # Menus
    "Main Menu": "Hoofdmenu",
    "Local Game": "Lokaal spel",
    "Online Game": "Online spel",
    "Coming soon": "Binnenkort",
    "Host": "Hosten",
    "Join": "Meedoen",
    "New Game": "Nieuw spel",
    "Continue": "Doorgaan",
    "No saved game found": "Geen opgeslagen spel gevonden",
    "Quit": "Afsluiten",
    "Slot {}": "Plek {}",
    "(empty)": "(leeg)",
    "Sure?": "Zeker?",
    "Back": "Terug",
    "Saved game": "Opgeslagen spel",
    "Player Names": "Spelersnamen",
    "Player {}:": "Speler {}:",
    "Human": "Mens",
    "Bot": "Bot",
    "Start Game": "Start spel",
    "Player {}": "Speler {}",

    # Online play (lobby.py, online.py, viewer.py)
    "Waiting for a player...": "Wachten op een speler...",
    "This computer": "Deze computer",
    "Open": "Open",
    "Joined": "Aangesloten",
    "Connecting...": "Verbinden...",
    "Everyone online can see this game and join it": "Iedereen online kan dit spel zien en meedoen",
    "The online server can't be reached: only your local network can see this game":
        "De online server is niet bereikbaar: alleen je lokale netwerk kan dit spel zien",
    "This game couldn't be opened to others": "Dit spel kon niet voor anderen worden geopend",
    "Waiting for the connection": "Wachten op de verbinding",
    "Every seat needs a player": "Elke plek heeft een speler nodig",
    "Two players have the same name": "Twee spelers hebben dezelfde naam",
    "No games yet: waiting for someone to host one...": "Nog geen spellen: wachten tot iemand er een host...",
    "No online server is set up: only games on your local network show up":
        "Er is geen online server ingesteld: alleen spellen op je lokale netwerk worden getoond",
    "Looking for the online server...": "Online server zoeken...",
    "The online server can't be reached right now: only games on your local network show up":
        "De online server is nu niet bereikbaar: alleen spellen op je lokale netwerk worden getoond",
    "Host's address:": "Adres van de host:",
    "e.g. 192.168.1.20": "bv. 192.168.1.20",
    "A game": "Een spel",
    "{}'s game": "Spel van {}",
    "Another version: update the game to join": "Andere versie: werk het spel bij om mee te doen",
    "Waiting for players": "Wacht op spelers",
    "Playing, 1 free seat": "Bezig, 1 vrije plek",
    "Playing, {} free seats": "Bezig, {} vrije plekken",
    "Playing (you can watch)": "Bezig (je kunt kijken)",
    "{} of {} players": "{} van {} spelers",
    "Online": "Online",
    "Local network": "Lokaal netwerk",
    "That game can't be reached": "Dat spel is niet bereikbaar",
    "That game is full": "Dat spel is vol",
    "That game is no longer open": "Dat spel is niet meer open",
    "The host doesn't answer": "De host antwoordt niet",
    "Joining...": "Meedoen...",
    "This game has already started: take a free seat, then Play":
        "Dit spel is al begonnen: neem een vrije plek en klik op Spelen",
    "Waiting for the host to start the game": "Wachten tot de host het spel start",
    "At the host": "Bij de host",
    "Other device": "Ander apparaat",
    "Take seat": "Plek nemen",
    "Leave seat": "Plek vrijgeven",
    "Play": "Spelen",
    "Watch": "Kijken",
    "Esc: menu (leave the game, fullscreen)": "Esc: menu (spel verlaten, volledig scherm)",
    "Back to game": "Terug naar het spel",
    "Fullscreen": "Volledig scherm",
    "Windowed": "In een venster",
    "Leave game": "Spel verlaten",
    "Waiting for the game...": "Wachten op het spel...",
    "The host": "De host",
    "Spectator": "Toeschouwer",
    "No messages yet": "Nog geen berichten",
    "Type a message (Enter: send, Esc: close)": "Typ een bericht (Enter: versturen, Esc: sluiten)",
    "The host ended the game": "De host heeft het spel beëindigd",
    "The host closed the game": "De host heeft het spel gesloten",
    "The host has left the game": "De host heeft het spel verlaten",
    "You were removed from the game": "Je bent uit het spel verwijderd",
    "The connection to the game was lost": "De verbinding met het spel is verbroken",
    "The online connection was lost": "De online verbinding is verbroken",
    "The game goes on here. To play on together, host it again: Online Game, Host, Continue":
        "Het spel gaat hier verder. Om samen verder te spelen, host het opnieuw: Online spel, Hosten, Doorgaan",

    # The app's Update button in the main menu (updater.py)
    "Update": "Bijwerken",
    "Checking...": "Controleren...",
    "Downloading {}%": "Downloaden {}%",
    "Installing libraries...": "Bibliotheken installeren...",
    "Restarting...": "Herstarten...",
    "Install {}": "Installeer {}",
    "Version: {}": "Versie: {}",
    "No internet connection": "Geen internetverbinding",
    "Update failed, try again later": "Bijwerken mislukt, probeer het later opnieuw",
    "The new version can't be installed": "De nieuwe versie kan niet worden geïnstalleerd",

    # Game controllers (controls.py): the names screen and the Controllers panel
    "Controllers": "Controllers",
    "Controller {}": "Controller {}",
    "No controller": "Geen controller",
    "Controllers: point at the button next to your name and press A":
        "Controllers: wijs de knop naast je naam aan en druk op A",
    "Point at your name and press A": "Wijs je naam aan en druk op A",
    "Done": "Klaar",

    # Settings menu
    "Settings": "Instellingen",
    "Exit Game": "Spel verlaten",
    "Save As": "Opslaan als",
    "Exit game?": "Spel verlaten?",
    "The host decides": "De host beslist",
    "Yes": "Ja",
    "No": "Nee",
    "Save": "Opslaan",
    "Click a slot to save there": "Klik op een plek om daar op te slaan",
    "Type a name -- overwrites this slot": "Typ een naam -- overschrijft deze plek",
    "Type a name, then Save or Enter": "Typ een naam, dan Opslaan of Enter",
    "Show continents": "Toon continenten",
    "Fast bots": "Snelle bots",

    # Event cards
    "No active event card": "Geen actieve gebeurteniskaart",
    "No more event cards": "Geen gebeurteniskaarten meer",
    "Next event card: next turn ({})": "Volgende gebeurteniskaart: volgende beurt ({})",
    "Next event card: in {} turns ({})": "Volgende gebeurteniskaart: over {} beurten ({})",
    "Event: {}": "Gebeurtenis: {}",
    "click anywhere to continue": "klik ergens om verder te gaan",
    "Click anywhere to continue": "Klik ergens om verder te gaan",

    # Panels and cards
    "End turn": "Einde beurt",
    "{} turn left": "nog {} beurt",
    "{} turns left": "nog {} beurten",
    "Trade cards for:": "Ruil kaarten voor:",
    "WARNING you currently hold too many cards": "LET OP: je hebt te veel kaarten",
    "Cards can only be traded in the recruitment phase": "Kaarten ruil je alleen in de rekruteringsfase",
    " traded {} cards ({}) for {} {}": " ruilde {} kaarten ({}) voor {} {}",
    "Free": "Gratis",

    # Resources and assets
    "food": "voedsel",
    "wood": "hout",
    "steel": "staal",
    "oil": "olie",
    "nuclear": "nucleair",
    "troops": "troepen",
    "cards": "kaarten",
    "ships": "schepen",
    "tanks": "tanks",
    "planes": "vliegtuigen",
    "ships ": "schepen ",
    "tanks ": "tanks ",
    "planes ": "vliegtuigen ",
    "pagoda": "pagode",
    "torii": "torii",

    # Assets destroyed (Engine.log_destroyed)
    "ship": "een schip",
    "tank": "een tank",
    "plane": "een vliegtuig",
    "fort": "het fort",
    "{} ships": "{} schepen",
    "{} tanks": "{} tanks",
    "{} planes": "{} vliegtuigen",
    " and ": " en ",
    "'s {} was destroyed in {}": " verloor {} in {}",
    "'s {} were destroyed in {}": " verloor {} in {}",

    # Turn start
    "You received {} card for having {}": "Je kreeg {} kaart voor het bezitten van {}",
    "You received {} cards for having {}": "Je kreeg {} kaarten voor het bezitten van {}",
    "Because you control {}, {} was developed instantly!": "Omdat je {} beheerst, is {} meteen ontwikkeld!",
    " lost {} troops to starvation": " verloor {} troepen door honger",
    " lost {} troop in {} due to ebola": " verloor {} troep in {} door ebola",
    " lost {} troops in {} due to ebola": " verloor {} troepen in {} door ebola",
    "{} troops starved to death": "{} troepen zijn verhongerd",

    # Attack
    "Tanks and planes in an emptied country are lost on Confirm":
        "Tanks en vliegtuigen in een leeg land gaan verloren bij bevestigen",
    " moved {}: {}": " verplaatste {}: {}",
    "by air": "per vliegtuig",
    "along rails": "per spoor",
    "nothing changed": "niets veranderd",
    "Air attack needs a plane in the launch airport": "Een luchtaanval heeft een vliegtuig nodig op het vertrekvliegveld",
    "Bring along from {}:": "Meenemen uit {}:",
    " (no boats over land)": " (geen boten over land)",
    "Needs a ship or plane to cross the sea": "Een schip of vliegtuig is nodig om de zee over te steken",
    "Active: {} / {}": "Actief: {} / {}",
    "{}: defend {} with tanks": "{}: verdedig {} met tanks",
    "{} units have been killed by pirates": "{} eenheden zijn door piraten gedood",
    "{} units and everything they brought along have been lost to pirates":
        "{} eenheden en alles wat ze meenamen zijn aan piraten verloren",
    "Lost at sea!": "Verloren op zee!",
    "Safe crossing": "Veilig overgestoken",
    "'s attack lost {} units to pirates": " verloor bij een aanval {} eenheden aan piraten",
    "{} lost, {} defeated": "{} verloren, {} verslagen",
    " took {} from ": " veroverde {} op ",
    " attacked ": " viel ",
    " in {}: {}": " aan in {}: {}",

    # Movement and developing
    " started developing {}": " begon {} te ontwikkelen",
    " moved: {}": " verplaatste: {}",
    "No unbroken sea route -- ships can't move here": "Geen doorlopende zeeroute -- schepen kunnen hier niet heen",
    "No land route -- bring a ship or plane to escort troops":
        "Geen landroute -- neem een schip of vliegtuig mee als escorte",
    "Planes cost 1 oil each to relocate": "Een vliegtuig verplaatsen kost 1 olie",
    "Emptied country will be abandoned on Confirm": "Een leeg land wordt bij bevestigen opgegeven",
    "Troops need a ship or plane to cross the sea": "Troepen hebben een schip of vliegtuig nodig om de zee over te steken",
    "A ship needs at least one troop moving with it": "Een schip heeft minstens één meereizende troep nodig",

    # Shop
    " built a bridge from {} to {}": " bouwde een brug van {} naar {}",
    " built rails from {} to {}": " legde spoor van {} naar {}",
    " nuked {}: {} casualty": " gooide een atoombom op {}: {} slachtoffer",
    " nuked {}: {} casualties": " gooide een atoombom op {}: {} slachtoffers",
    " placed a ship in {}": " plaatste een schip in {}",
    " placed a plane in {}": " plaatste een vliegtuig in {}",
    " placed a tank in {}": " plaatste een tank in {}",
    " built a fort in {}": " bouwde een fort in {}",

    # The natives' attack (inboorlingen vechten terug)
    "{}: mouse attacks {} of {} -- {} troops left": "{}: mouse valt {} van {} aan -- nog {} troepen",
    "{}: click dice to leave out, then roll": "{}: klik dobbelstenen weg en gooi dan",
    ": {} lost, {} defeated": ": {} verloren, {} verslagen",
    ": {} lost, {} destroyed": ": {} verloren, {} vernietigd",
    "The natives took {} from ": "De inboorlingen veroverden {} op ",
    "The natives took {} from {}{}": "De inboorlingen veroverden {} op {}{}",
    "{} defended {} from the natives{}": "{} verdedigde {} tegen de inboorlingen{}",
    " defended {} from the natives{}": " verdedigde {} tegen de inboorlingen{}",

    # Pagoda / torii
    "the {} belongs on {}, not {}": "de {} hoort in {}, niet in {}",
    "you forgot the {}": "je vergat de {}",
    " forgot the {}: {} was taken over by the mouse": " vergat de {}: {} is overgenomen door de mouse",
    " misplaced the {}: {} was taken over by the mouse": " zette de {} verkeerd: {} is overgenomen door de mouse",
    " forgot the {}: lost {} {} in {}": " vergat de {}: verloor {} {} in {}",
    " misplaced the {}: lost {} {} in {}": " zette de {} verkeerd: verloor {} {} in {}",
    "{}, {}, {} was taken over by the mouse": "{}, {}, {} is overgenomen door de mouse",
    "{}, {}, {} {} removed from {}": "{}, {}, {} {} weggehaald uit {}",
    "troop was": "troep is",
    "troops were": "troepen zijn",
    "troop": "troep",

    # Eliminations and the end
    "{} wins!": "{} wint!",
    "Nobody survived": "Niemand heeft het overleefd",
    " has been eliminated": " is uitgeschakeld",
    "{} has been eliminated": "{} is uitgeschakeld",
    "{} gained:": "{} kreeg:",
    "{} gained nothing": "{} kreeg niets",

    # Bots
    "{} nuked {}!": "{} gooide een atoombom op {}!",
    " withdrew {} troops from {} to {}": " trok {} troepen terug uit {} naar {}",
    " moved {} from {} to {}": " verplaatste {} van {} naar {}",

    # Event notices
    "{}: {} gets {} oil": "{}: {} krijgt {} olie",
    "{}: {} gets {} oil and shares out the others' oil: {}":
        "{}: {} krijgt {} olie en verdeelt de olie van de anderen: {}",
    "{}: {} gets {} oil and shares out the others' {} oil":
        "{}: {} krijgt {} olie en verdeelt de {} olie van de anderen",
    "{}: share out the other players' oil": "{}: verdeel de olie van de andere spelers",
    "{}: your blind bid in oil": "{}: je blinde bod in olie",
    "{}: {} sets the new turn order: {}": "{}: {} bepaalt de nieuwe speelvolgorde: {}",
    "{}: {} sets the new turn order": "{}: {} bepaalt de nieuwe speelvolgorde",
    "{}: drag the names into the new turn order": "{}: sleep de namen in de nieuwe speelvolgorde",
    "{} finishes this turn first": "{} maakt eerst deze beurt af",
    "now": "nu",
    "Immigrants only starve when no other troops are left": "Immigranten verhongeren pas als er geen andere troepen meer zijn",
    "Given back to the mouse:": "Teruggegeven aan de mouse:",
    "Also attacking with +1: {}": "Valt ook aan met +1: {}",
    "Taken from other players:": "Veroverd op andere spelers:",
    "{} cancelled for 1 round": "{} gecancelled voor 1 ronde",
    "Woke: {} cancelled for 1 round": "Woke: {} gecancelled voor 1 ronde",
    "{} is cancelled: they skip this turn": "{} is gecancelled: slaat deze beurt over",
    " is cancelled and skips this turn": " is gecancelled en slaat deze beurt over",
    "{} immigrant": "{} immigrant",
    "{} immigrants": "{} immigranten",
    "never moves": "beweegt nooit",
    "never move": "bewegen nooit",
    "{} pays {} food: the spirits leave": "{} betaalt {} voedsel: de geesten vertrekken",
    " pays {} food: the spirits leave": " betaalt {} voedsel: de geesten vertrekken",
    "No developed countries: the spirits leave": "Geen ontwikkelde landen: de geesten vertrekken",
    "{} can't pay {} food: every developed country goes back to developing":
        "{} kan geen {} voedsel betalen: alle ontwikkelde landen gaan terug naar ontwikkelen",
    "{} doesn't pay: every developed country goes back to developing":
        "{} betaalt niet: alle ontwikkelde landen gaan terug naar ontwikkelen",
    " doesn't pay: every developed country goes back to developing":
        " betaalt niet: alle ontwikkelde landen gaan terug naar ontwikkelen",
    "Nobody pays: every developed country goes back to developing":
        "Niemand betaalt: alle ontwikkelde landen gaan terug naar ontwikkelen",
    "Oh no, evil spirits from Malaysia have haunted all developed countries back to developing. "
    "{} please give us rice to drive the evil spirits away!":
        "Oh nee, boze geesten uit Maleisië hebben alle ontwikkelde landen teruggespookt naar ontwikkelen. "
        "{} geef ons alsjeblieft rijst om de boze geesten te verjagen!",
    "New turn order: {}": "Nieuwe speelvolgorde: {}",
    "(the others look away)": "(de anderen kijken weg)",
    "All": "Alles",
    "Bids: {}. No single highest bid: {} stays where it is":
        "Biedingen: {}. Geen enkel hoogste bod: {} blijft waar het is",
    "Bids: {}. {} buys {} for {} oil": "Biedingen: {}. {} koopt {} voor {} olie",
    "Nobody buys {}": "Niemand koopt {}",
    " buys {} for {} oil from ": " koopt {} voor {} olie van ",
    " takes {} oil from the other players (+{} oil)": " neemt {} olie van de andere spelers (+{} olie)",
    " gets {} oil": " krijgt {} olie",
    "{} took Japan: +5 troops there": "{} veroverde Japan: +5 troepen daar",
    "{} took {}: the natives attack it with {} troops": "{} veroverde {}: de inboorlingen vallen het aan met {} troepen",
    "{} controls {}": "{} bezit {}",
    "{} took {}": "{} veroverde {}",
    "{}: {} drops the nuke on {}": "{}: {} gooit de atoombom op {}",
    "{}: pick a country in Asia for the nuke": "{}: kies een land in Azië voor de atoombom",
    "{} took {}: 1 slave added there": "{} veroverde {}: 1 slaaf erbij",
    "{} took {}: +5 steel": "{} veroverde {}: +5 staal",
    "{} of {} now has the most troops in Africa: it goes to the mouse":
        "{} van {} heeft nu de meeste troepen in Afrika: het gaat naar de mouse",
    "{}: pick which of your countries is hit by ebola": "{}: kies welk van je landen door ebola getroffen wordt",
    "{} took {}: all their troops and assets move there, +5 troops":
        "{} veroverde {}: al zijn troepen, schepen, tanks en vliegtuigen gaan erheen, +5 troepen",

    # Continents
    "Africa": "Afrika",
    "Europe": "Europa",
    "Asia": "Azië",
    "Oceania": "Oceanië",
    "South America": "Zuid-Amerika",
    "North America": "Noord-Amerika",
    # Tutorial (tutorial.py)
    "Next": "Volgende",
    "Skip": "Overslaan",
    "Play on": "Verder spelen",
    "End tutorial": "Tutorial stoppen",
    "Welcome to OIL": "Welkom bij OIL",
    "This tutorial plays your first turn with you, one step at a time. You are the blue player, "
    "in the south of Africa. Two bots play far away, in North America and Siberia.\n"
    "Click Next to begin.":
        "Deze tutorial speelt je eerste beurt met je mee, stap voor stap. Jij bent de blauwe speler, "
        "in het zuiden van Afrika. Twee bots spelen ver weg, in Noord-Amerika en Siberië.\n"
        "Klik op Volgende om te beginnen.",
    "The map": "De kaart",
    "Every shape is a country, in the colour of its owner. Grey countries belong to nobody yet. "
    "The number on a country is its troops.\n"
    "Hold the right mouse button and drag to move the map; scroll to zoom in and out.":
        "Elke vorm is een land, in de kleur van zijn eigenaar. Grijze landen zijn nog van niemand. "
        "Het getal op een land is het aantal troepen.\n"
        "Houd de rechtermuisknop ingedrukt en sleep om de kaart te verschuiven; scroll om in en uit "
        "te zoomen.",
    "Routes": "Routes",
    "Countries are connected by routes: solid lines over land, dotted lines over sea. You can "
    "only attack and move along a route. To cross the sea you need a ship or a plane.":
        "Landen zijn verbonden door routes: doorgetrokken lijnen over land, stippellijnen over zee. "
        "Je kunt alleen langs een route aanvallen en verplaatsen. Om de zee over te steken heb je een "
        "schip of een vliegtuig nodig.",
    "Country info": "Landinfo",
    "Point at a country, for example {}. The panel at the top right shows what it gives its "
    "owner every turn: food, wood, steel, oil, nuclear and helmets. It also shows an airport "
    "or fort, if it has one.":
        "Wijs een land aan, bijvoorbeeld {}. Het paneel rechtsboven toont wat het zijn eigenaar elke "
        "beurt oplevert: voedsel, hout, staal, olie, nucleair en helmen. Ook een luchthaven of fort "
        "staat erbij, als het die heeft.",
    "Your stock": "Je voorraad",
    "The panel on the left shows your stock. The number in brackets next to it is what "
    "comes in at your next turn.\n"
    "At the start of every turn each troop eats 1 food (the red number); the green number is "
    "your harvest. Troops you can't feed starve.":
        "Het paneel links toont je voorraad. Het getal tussen haakjes ernaast is wat er bij je "
        "volgende beurt bijkomt.\n"
        "Aan het begin van elke beurt eet elke troep 1 voedsel (het rode getal); het groene getal is "
        "je oogst. Troepen die je niet kunt voeden, verhongeren.",
    "New troops": "Nieuwe troepen",
    "The helmets are the troop production of your countries. Every turn you get a third of "
    "your helmets plus 3 as new troops.":
        "De helmen zijn de troepenproductie van je landen. Elke beurt krijg je een derde van je "
        "helmen plus 3 als nieuwe troepen.",
    "The phases": "De fases",
    "Every turn has three phases: deploying troops (yellow), attacking (red) and moving "
    "(orange). The bright button is the phase you're in. End turn ends your turn.":
        "Elke beurt heeft drie fases: troepen plaatsen (geel), aanvallen (rood) en verplaatsen "
        "(oranje). De heldere knop is de fase waarin je zit. Met Einde beurt sluit je je beurt af.",
    "The buttons": "De knoppen",
    "At the top left: the settings (save, exit, display), the shop, your cards and the world "
    "event. You'll use the shop and the cards in a moment.":
        "Linksboven: de instellingen (opslaan, stoppen, weergave), de winkel, je kaarten en de "
        "wereldgebeurtenis. De winkel en de kaarten gebruik je zo meteen.",
    "Cards": "Kaarten",
    "You hold three cards. Three of a kind, or one of each, make a set, which you can trade "
    "for troops or resources, but only while deploying troops.\n"
    "Open your cards.":
        "Je hebt drie kaarten. Drie dezelfde, of van elk één, vormen een set die je kunt inruilen "
        "voor troepen of grondstoffen, maar alleen tijdens het plaatsen van troepen.\n"
        "Open je kaarten.",
    "Trade a set": "Een set inruilen",
    "Your three cards are already selected. Click the green button to trade them, then pick a "
    "reward. One of each is worth 10 troops (or 25 food, 30 wood, 20 steel, 20 oil or 10 "
    "nuclear).":
        "Je drie kaarten zijn al geselecteerd. Klik op de groene knop om ze in te ruilen en kies dan "
        "een beloning. Van elk één is 10 troepen waard (of 25 voedsel, 30 hout, 20 staal, 20 olie of "
        "10 nucleair).",
    "Getting cards": "Kaarten krijgen",
    "You get a card at the end of every turn in which you conquered a country of another "
    "player, and cards for holding a whole continent. Holding more than 4 cards forces you "
    "to trade.":
        "Je krijgt een kaart aan het eind van elke beurt waarin je een land van een andere speler "
        "veroverde, en kaarten voor het bezit van een heel continent. Met meer dan 4 kaarten moet je "
        "ruilen.",
    "Deploy your troops": "Plaats je troepen",
    "The number on the soldier at the left is how many new troops you can place. Left-click "
    "one of your countries to put a troop there, right-click to take it back.\n"
    "Put them in {}: you'll attack from there.":
        "Het getal op de soldaat links is hoeveel nieuwe troepen je kunt plaatsen. Klik met links op "
        "een van je landen om er een troep neer te zetten, met rechts haal je hem terug.\n"
        "Zet ze in {}: daar val je straks vanuit aan.",
    "The shop": "De winkel",
    "With wood, steel and nuclear you buy things in the shop: bridges and rails, nukes, and "
    "(only while deploying) ships, planes, tanks and forts. Ships and planes take troops across "
    "the sea, a tank adds 1 to your highest attack die, a fort adds to every defence die.":
        "Met hout, staal en nucleair koop je dingen in de winkel: bruggen en spoorwegen, atoombommen "
        "en (alleen tijdens het plaatsen) schepen, vliegtuigen, tanks en forten. Schepen en "
        "vliegtuigen brengen troepen over zee, een tank telt 1 op bij je hoogste aanvalsdobbelsteen, "
        "een fort bij elke verdedigingsdobbelsteen.",
    "Buy a ship": "Koop een schip",
    "Your first ship is free. Open the shop, click the ship, click the green button and then "
    "click {} to put the ship there.":
        "Je eerste schip is gratis. Open de winkel, klik op het schip, klik op de groene knop en klik "
        "dan op {} om het schip daar te zetten.",
    "On to the attack": "Op naar de aanval",
    "Click the red button to go to the attack phase.": "Klik op de rode knop om naar de aanvalsfase te gaan.",
    "Pick a target": "Kies een doelwit",
    "Click {} to attack from it, then {} to attack it.":
        "Klik op {} om ervandaan aan te vallen en dan op {} om dat aan te vallen.",
    "Rolling the dice": "Dobbelen",
    "You roll a die for every attacking troop, at most 3 (one troop stays home). The defender "
    "rolls up to 2. The highest dice are compared in pairs: the higher die wins, a tie goes to "
    "the defender, and the loser of each pair loses a troop.\n"
    "Click a die to leave it out, then click the green button to roll.":
        "Je gooit een dobbelsteen per aanvallende troep, hoogstens 3 (één troep blijft thuis). De "
        "verdediger gooit er hoogstens 2. De hoogste stenen worden per paar vergeleken: de hoogste "
        "wint, bij gelijkspel wint de verdediger, en wie een paar verliest, verliest een troep.\n"
        "Klik op een dobbelsteen om hem weg te laten en klik dan op de groene knop om te gooien.",
    "Conquer it": "Verover het",
    "After a roll, click anywhere to count the losses. Keep rolling until {} has no troops "
    "left: then it's yours. A fort adds to every defence die, an active tank adds 1 to your "
    "highest die.\n"
    "Careful: if you roll 1 or 2 dice and lose them all, the ships, tanks and planes you "
    "brought along are destroyed.":
        "Klik na een worp ergens om de verliezen te tellen. Blijf gooien tot {} geen troepen meer "
        "heeft: dan is het van jou. Een fort telt op bij elke verdedigingsdobbelsteen, een actieve "
        "tank telt 1 op bij je hoogste dobbelsteen.\n"
        "Opgelet: gooi je met 1 of 2 dobbelstenen en verlies je ze allemaal, dan worden de schepen, "
        "tanks en vliegtuigen die je meenam vernietigd.",
    "Move in": "Intrekken",
    "Your troops move into the conquered country, all but one. Click the country you "
    "attacked from to keep one more there, or the new country to send one more in. Then click "
    "the green button.":
        "Je troepen trekken het veroverde land in, op één na allemaal. Klik op het land waaruit je "
        "aanviel om er nog één te houden, of op het nieuwe land om er nog één heen te sturen. Klik "
        "dan op de groene knop.",
    "Conquests": "Veroveringen",
    "A conquered country gives you its production from your next turn on. You can attack as "
    "often as you like in this phase, as long as you have troops to spare.":
        "Een veroverd land levert je vanaf je volgende beurt zijn productie op. In deze fase kun je "
        "zo vaak aanvallen als je wilt, zolang je troepen over hebt.",
    "On to moving": "Op naar verplaatsen",
    "Click the orange button to go to the move phase.":
        "Klik op de oranje knop om naar de verplaatsfase te gaan.",
    "Move troops": "Troepen verplaatsen",
    "Once per turn you can move troops between two of your countries that are connected "
    "through your own countries. Click {}, then {}. Click a country to move a troop into it, "
    "then click the green button.":
        "Eén keer per beurt kun je troepen verplaatsen tussen twee van je landen die via je eigen "
        "landen verbonden zijn. Klik op {} en dan op {}. Klik op een land om er een troep heen te "
        "zetten en klik dan op de groene knop.",
    "Developing": "Ontwikkelen",
    "In this phase you can also develop one country per turn (the button at the bottom left). "
    "You pay what the country produces once; it then gives nothing at your next turn, and "
    "double from then on (right away if you hold its whole continent).":
        "In deze fase kun je ook één land per beurt ontwikkelen (de knop linksonder). Je betaalt "
        "eenmalig wat het land oplevert; bij je volgende beurt levert het dan niets op, en daarna "
        "voorgoed het dubbele (meteen als je het hele continent hebt).",
    "End your turn": "Beëindig je beurt",
    "Click End turn. The bots then play their turns.":
        "Klik op Einde beurt. Daarna spelen de bots hun beurten.",
    "The others play": "De anderen spelen",
    "The bots are playing now. Everything that happens appears at the bottom left: click that "
    "box to read the whole log.":
        "De bots spelen nu. Alles wat er gebeurt, verschijnt linksonder: klik op dat vak om het hele "
        "logboek te lezen.",
    "Your turn again": "Weer jouw beurt",
    "Your troops have eaten and your countries delivered their production: see your stock on "
    "the left. The soldier shows your new troops.":
        "Je troepen hebben gegeten en je landen hebben hun productie geleverd: zie je voorraad "
        "links. De soldaat toont je nieuwe troepen.",
    "Turn order": "Beurtvolgorde",
    "The boxes at the bottom right show the other players in turn order, the next one on top: "
    "their stock, their cards and who draws the next world event.":
        "De vakjes rechtsonder tonen de andere spelers in beurtvolgorde, de volgende bovenaan: "
        "hun voorraad, hun kaarten en wie de volgende wereldgebeurtenis trekt.",
    "skips": "slaat over",
    "World events": "Wereldgebeurtenissen",
    "Every few turns a world event is drawn: a card that changes the rules for a full round, "
    "such as income, attacks or prices. The event button shows the active one and when the "
    "next one comes. In this tutorial they were held back.":
        "Om de paar beurten wordt een wereldgebeurtenis getrokken: een kaart die een volle ronde de "
        "regels verandert, zoals de inkomsten, aanvallen of prijzen. De gebeurtenisknop toont de "
        "actieve en wanneer de volgende komt. In deze tutorial werden ze tegengehouden.",
    "More to discover": "Meer te ontdekken",
    "Rails let your troops travel far through your own countries. A bridge turns a sea route "
    "into a land route. Planes cross the sea for 1 oil, and give their country an airport. A "
    "nuke halves the troops of a country next to yours, which then produces nothing for 3 "
    "turns.":
        "Over spoorwegen reizen je troepen ver door je eigen landen. Een brug maakt van een zeeroute "
        "een landroute. Vliegtuigen steken de zee over voor 1 olie en geven hun land een luchthaven. "
        "Een atoombom halveert de troepen van een land naast het jouwe, dat daarna 3 beurten niets "
        "oplevert.",
    "Winning": "Winnen",
    "Take a player's last country and they're out: you get their wood, steel, oil, nuclear "
    "and cards. The last player left wins the game.":
        "Verover het laatste land van een speler en die ligt eruit: jij krijgt zijn hout, staal, "
        "olie, nucleair en kaarten. De laatste speler die overblijft, wint.",
    "That's it!": "Dat was het!",
    "You know the basics. Play on against the two bots in this game; world events are on from "
    "now. You can leave through the settings (top left): Exit Game.":
        "Je kent nu de basis. Speel verder tegen de twee bots in dit spel; vanaf nu doen "
        "wereldgebeurtenissen mee. Stoppen kan via de instellingen (linksboven): Spel verlaten.",
}


# --- Dutch source -> English ------------------------------------------------

EN = {
    # Menus
    "De 3 Neven": "The 3 Cousins",

    # Cards
    "Menneke": "Soldier",
    "Paerd": "Horse",
    "Vliegtuig": "Plane",

    # Countries
    "Madagaskar": "Madagascar",
    "Zuid-Afrika": "South Africa",
    "Belgisch Congo": "Belgian Congo",
    "Somalië": "Somalia",
    "IJsland": "Iceland",
    "Sovjet-Rusland": "Soviet Russia",
    "Nazi-Duitsland": "Nazi Germany",
    "Romeinse Rijk": "Roman Empire",
    "Spanje": "Spain",
    "Londen": "London",
    "Siberië": "Siberia",
    "Kazachstan": "Kazakhstan",
    "Mongolië": "Mongolia",
    "Noord-Korea": "North Korea",
    "Maleisië": "Malaysia",
    "Ottomaanse Rijk": "Ottoman Empire",
    "Arabië": "Arabia",
    "Nederlands-Indië": "Dutch East Indies",
    "Papoea Nieuw Guinea": "Papua New Guinea",
    "Argentinië": "Argentina",
    "Brazilië": "Brazil",
    "Groenland": "Greenland",

    # Event pick prompts
    "{}: kies een land in Azie voor de atoombom": "{}: pick a country in Asia for the nuke",
    "Kies welk land door ebola getroffen wordt": "Pick which country is hit by ebola",
    "Plaats een gratis vliegtuig in een van je landen": "Place a free plane in one of your countries",

    # Events: names
    "De Japanners worden gek": "The Japanese go crazy",
    "inboorlingen vechten terug": "The natives fight back",
    "Ontwikkelingshulp": "Development aid",
    "Eer van de keizer": "The emperor's honour",
    "Verkeerde knop": "Wrong button",
    "japanse agressie": "Japanese aggression",
    "storm of zee": "Storm at sea",
    "kindsoldaten": "Child soldiers",
    "Slavernij": "Slavery",
    "Einde van de mensheid": "End of humanity",
    "maak van de VOC een deel 2": "VOC part 2",
    "nucleaire winter": "Nuclear winter",
    "kinderarbeid": "Child labour",
    "ebola": "Ebola",
    "strenge winter": "Harsh winter",
    "bedevaart": "Pilgrimage",
    "plunderingen": "Looting",
    "klimaatverandering blijkt hoax": "Climate change turns out to be a hoax",
    "Muur van Trump": "Trump's wall",
    "goede economie": "Good economy",
    "covid": "Covid",
    "drugs": "Drugs",
    "de nazi's breiden uit": "The Nazis expand",
    "gas wordt betaald in roebels": "Gas is paid in roubles",
    "Groenland is niet te koop!": "Greenland is not for sale!",
    "Poetin's oorlog in Oekraïne": "Putin's war in Ukraine",
    "Israël is het slachtoffer": "Israel is the victim",
    "Boze geesten in Lara's huis": "Evil spirits in Lara's house",
    "inflatie (door Poetin)": "Inflation (by Putin)",
    "Immigratie": "Immigration",
    "Woke": "Woke",

    # Events: descriptions
    "Japan krijgt 5 extra troepen en er ontstaan landroutes tussen Japan en elk ander land.":
        "Japan gets 5 extra troops and land routes appear between Japan and every other country.",
    "Mouse vecht met 5 troepen tegen de landen: China, Outback, Sovjet-Unie, Peru en Canada.":
        "Mouse fights with 5 troops against the countries China, Outback, Soviet Russia, Peru and Canada.",
    "Alle grondstoffen van Europa gaan naar de speler met de meeste Afrikaanse troepen.":
        "All of Europe's resources go to the player with the most troops in Africa.",
    "De speler die deze ronde de meeste gebieden van andere spelers verovert claimt alle landen om Japan heen.":
        "The player who conquers the most territories from other players this round claims every country "
        "around Japan.",
    "Noord-Korea gooit per ongeluk een atoombom op een land in Azië.":
        "North Korea accidentally drops a nuke on a country in Asia.",
    "Elk leger dat in Japan begon of door Japan is getrokken mag 1 optellen bij elke aanvalsdobbelsteen.":
        "Every army that started in or passed through Japan may add 1 to every attack die.",
    "Piraten brengen alle legers om die over een zee-route reizen met een kans van 1/3.":
        "Pirates kill every army that travels over a sea route, with a chance of 1 in 3.",
    "Voor elk Afrikaans land dat een speler verovert ontvangt hij één extra kaertske (géén Mouse).":
        "For every African country a player conquers they get one extra card (not from Mouse).",
    "Per elk Afrikaans land dat je bezit wordt 1 slaaf toegevoegd.":
        "1 slave is added for every African country you own.",
    "Als je een speler uitroeit krijg je ook hun voedsel.":
        "If you wipe out a player you also get their food.",
    "Alle mauses 1 troep minder.":
        "Every mouse country has 1 troop less.",
    "Deze ronde géén voedsel productie.":
        "No food production this round.",
    "De landen India, Sri Lanka, Maleisië en Nederlands-Indië leveren 5 staal.":
        "India, Sri Lanka, Malaysia and the Dutch East Indies deliver 5 steel.",
    "Het land met de meeste legers in Afrika gaat naar Mouse.":
        "The country with the most armies in Africa goes to Mouse.",
    "De Noordelijkst gelegen landen mogen niet aangevallen worden of zelf aanvallen.":
        "The northernmost countries can't be attacked and can't attack.",
    "De speler die Arabië bezit verplaatst al zijn troepen, schepen, tanks en vliegtuigen naar dat land en krijgt +5 troepen.":
        "The player who owns Arabia moves all their troops, ships, tanks and planes there and gets +5 troops.",
    "Criminelen plunderen de shop en zetten alles voor de helft van het geld op marktplaats.":
        "Criminals loot the shop and sell everything on eBay for half the price.",
    "Iedereen een gratis vliegtuig. Hoe meer CO2 hoe beter!":
        "A free plane for everyone. The more CO2 the better!",
    "Je kan niet tussen de VS en Mexico reizen.":
        "You can't travel between the US and Mexico.",
    "De olieproducerende landen krijgen 1 extra olie per land.":
        "Oil-producing countries get 1 extra oil each.",
    "De speler die Sovjet-Unie bezit neemt alle oil van de andere spelers en herverdeeld dit onder hen. "
    "Die speler krijgt zelf 5 oil erbij.":
        "The player who owns the Soviet Union takes all the oil of the other players and shares it out "
        "among them. That player gets 5 oil on top.",
    "De spelers die niet Groenland bezitten bieden blind met oil. De hoogste bieder betaald zijn bod aan de "
    "vorige bezitter van Groenland en krijgt het land met alles wat daar staat (troepen, tanks, etc.)":
        "The players who don't own Greenland bid blind with oil. The highest bidder pays their bid to "
        "Greenland's previous owner and gets the country with everything on it (troops, tanks, etc.)",
    "De speler(s) die de minste landen aan Maus teruggeeft deze ronde wordt gecancelled voor 1 ronde":
        "The player(s) who give the fewest countries back to Mouse this round get cancelled for 1 round",
    "Alle West-Europese landen van spelers krijgen 3 troepen erbij die nooit kunnen bewegen of aanvallen.":
        "Every Western European country held by a player gets 3 extra troops that can never move or attack.",
    "Als je een Westers land bezit betaal je 2x zo veel in de sop. Belarus betaalt de helft, ook als je "
    "daarnaast een Westers land bezit.":
        "If you own a Western country you pay twice as much in the shop. Belarus pays half, even if you "
        "also own a Western country.",
    "De speler die Maleisië bezit mag 1 voedsel per ontwikkeld land betalen om de geesten te verjagen, "
    "anders gaan alle ontwikkelde landen op de kaart terug naar ontwikkelen (die van mouse niet)":
        "The player who owns Malaysia may pay 1 food per developed country to drive the spirits away, or "
        "else every developed country on the map goes back to developing (not the mouse's)",
    "De bezitter van het Ottomaanse Rijk bepaalt de nieuwe speelvolgorde":
        "The owner of the Ottoman Empire decides the new turn order",
    "Elke speler met een EU land ontvangt deze ronde geen voedsel en geen oil":
        "Every player with an EU country gets no food and no oil this round",
    "Spelers die sovjet, VS of Brazilië bezitten krijgen géén troepen.":
        "Players who own Soviet Russia, the US or Brazil get no troops.",
    "Als je de landen Venezuela, Mexico, Los Angeles, Siberië of Cuba bezit, "
    "haal dan 1 af van de waarde van elke dobbelsteen die je gooit.":
        "If you own Venezuela, Mexico, Los Angeles, Siberia or Cuba, subtract 1 from every die you throw.",
    "Elk leger dat in Nazi-Duitsland begon of door Nazi-Duitsland is getrokken mag 1 optellen bij elke "
    "aanvalsdobbelsteen.":
        "Every army that started in or passed through Nazi Germany may add 1 to every attack die.",
}
