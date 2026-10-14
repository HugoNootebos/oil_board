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
    "Show assets": "Toon materieel",
    "Show sea connections": "Toon zeeroutes",
    "Show land connections": "Toon landroutes",
    "Show torii/pagoda": "Toon torii/pagode",
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
    "Taken from other players:": "Veroverd op andere spelers:",
    "{} cancelled for 1 round": "{} gecancelled voor 1 ronde",
    "Woke: {} cancelled for 1 round": "Woke: {} gecancelled voor 1 ronde",
    "{} is cancelled: they skip this turn": "{} is gecancelled: slaat deze beurt over",
    " is cancelled and skips this turn": " is gecancelled en slaat deze beurt over",
    "{} immigrant": "{} immigrant",
    "{} immigrants": "{} immigranten",
    "never moves": "beweegt nooit",
    "never move": "bewegen nooit",
    "{} pays {} food to keep {} developed": "{} betaalt {} voedsel om {} ontwikkeld te houden",
    "{} can't pay {} food: {} is no longer developed": "{} kan geen {} voedsel betalen: {} is niet meer ontwikkeld",
    " pays {} food to keep {} developed": " betaalt {} voedsel om {} ontwikkeld te houden",
    "{}: pay {} food to keep {} developed?": "{}: {} voedsel betalen om {} ontwikkeld te houden?",
    "{} doesn't pay: {} is no longer developed": "{} betaalt niet: {} is niet meer ontwikkeld",
    " lost the development of {}": " verloor de ontwikkeling van {}",
    "New turn order: {}": "Nieuwe speelvolgorde: {}",
    "(the others look away)": "(de anderen kijken weg)",
    "All": "Alles",
    "Bids: {}. No single highest bid: {} stays where it is":
        "Biedingen: {}. Geen enkel hoogste bod: {} blijft waar het is",
    "Bids: {}. {} buys {} for {} oil": "Biedingen: {}. {} koopt {} voor {} olie",
    "Nobody buys {}": "Niemand koopt {}",
    " buys {} for {} oil from ": " koopt {} voor {} olie van ",
    "Rest": "Rest",
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
    "{} took {}: all their troops move there, +5 troops": "{} veroverde {}: al zijn troepen gaan erheen, +5 troepen",

    # Continents
    "Africa": "Afrika",
    "Europe": "Europa",
    "Asia": "Azië",
    "Oceania": "Oceanië",
    "South America": "Zuid-Amerika",
    "North America": "Noord-Amerika",
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
    "Als Japan aanvalt mag het 1 optellen bij elke dobbelsteen.":
        "When Japan attacks it may add 1 to every die.",
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
    "De speler die Arabië bezit verplaatst al zijn troepen naar dat land en krijgt +5 troepen.":
        "The player who owns Arabia moves all their troops there and gets +5 troops.",
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
    "Alle West-Europese landen krijgen 3 troepen erbij die nooit kunnen bewegen of aanvallen.":
        "Every Western European country gets 3 extra troops that can never move or attack.",
    "Als je een Westers land bezit betaal je 2x zo veel in de sop. Belarus betaalt de helft, ook als je "
    "daarnaast een Westers land bezit.":
        "If you own a Western country you pay twice as much in the shop. Belarus pays half, even if you "
        "also own a Western country.",
    "Als Maleisië ontwikkeld is moet de speler die het bezit 10 voedsel betalen, anders word de ontwikkeling "
    "ongedaan gemaakt":
        "If Malaysia is developed, the player who owns it has to pay 10 food, or the development is undone",
    "De bezitter van het Ottomaanse Rijk bepaalt de nieuwe speelvolgorde":
        "The owner of the Ottoman Empire decides the new turn order",
    "Elke speler met een EU land ontvangt deze ronde geen voedsel en geen oil":
        "Every player with an EU country gets no food and no oil this round",
    "Spelers die sovjet, VS of Brazilië bezitten krijgen géén troepen.":
        "Players who own Soviet Russia, the US or Brazil get no troops.",
    "Als je de landen Venezuela, Mexico, Los Angeles, Siberië of Cuba bezit, "
    "haal dan 1 af van de waarde van elke dobbelsteen die je gooit.":
        "If you own Venezuela, Mexico, Los Angeles, Siberia or Cuba, subtract 1 from every die you throw.",
    "Als Nazi-Duitsland aanvalt mag het 1 optellen bij elke dobbelsteen.":
        "When Nazi Germany attacks it may add 1 to every die.",
}
