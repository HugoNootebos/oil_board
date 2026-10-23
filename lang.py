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
    "nuclear": "uranium",
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
    "Welcome to OIL": "Welkom bij OIL",
    "You are the blue player and you are competing against red and green. The grey countries "
    "belong to the natives. You win by eliminating both other players.":
        "Jij bent de blauwe speler en je neemt het op tegen rood en groen. De grijze landen zijn "
        "van de inboorlingen. Je wint door beide andere spelers uit te schakelen.",
    "Your stock": "Je voorraad",
    "The bar at the top shows your stock: food, wood, steel, oil, uranium and troop "
    "production. The number in brackets is what you produce at the start of every turn. Food "
    "has two brackets: one for how much your army consumes every turn (= size of your army) "
    "and one for how much you produce.\n"
    "Be careful because in this game you have to feed your troops before you receive your "
    "production, so if you end your turn with less food than you have units on the board "
    "some of them will starve at the start of your next turn.":
        "De balk bovenaan toont je voorraad: voedsel, hout, staal, olie, uranium en "
        "troepenproductie. Het getal tussen haakjes is wat je aan het begin van elke beurt "
        "produceert. Voedsel heeft twee getallen tussen haakjes: een voor hoeveel je leger elke "
        "beurt eet (= de grootte van je leger) en een voor hoeveel je produceert.\n"
        "Let op: in dit spel voed je eerst je troepen en krijg je pas daarna je productie. Eindig "
        "je je beurt met minder voedsel dan je troepen op het bord hebt, dan verhongeren er een "
        "paar aan het begin van je volgende beurt.",
    "Place your troops": "Plaats je troepen",
    "After feeding your troops you receive new ones. How many you get is determined by the "
    "total number of helmets your countries provide, with every helmet being 1/3 troop. On top "
    "of that everyone always gets 3 bonus troops every round, so even if you have less than 3 "
    "helmets you still get fresh armies. Left-click {} three times to place your recruits.":
        "Nadat je troepen gegeten hebben, krijg je er nieuwe bij. Hoeveel, hangt af van het totale "
        "aantal helmen dat je landen opleveren: elke helm is 1/3 troep. Daarbovenop krijgt "
        "iedereen elke ronde altijd 3 extra troepen, dus ook met minder dan 3 helmen krijg je "
        "verse legers. Klik drie keer met links op {} om je rekruten te plaatsen.",
    "On to the attack": "Op naar de aanval",
    "Click the red button to go to the attack phase.":
        "Klik op de rode knop om naar de aanvalsfase te gaan.",
    "Attack Mexico": "Val Mexico aan",
    "Click {} to attack from it, then {} to attack it.":
        "Klik op {} om ervandaan aan te vallen en dan op {} om dat aan te vallen.",
    "Roll the dice": "Dobbelen",
    "For every unit in the country you are attacking from you can roll a die (at most 3). The "
    "defender has the same but can only roll up to 2 dice. The highest attack die is compared "
    "to the highest defense die and the highest one wins. Ties are won by the defense. The "
    "same is done for the second highest dice (if possible). Each die that loses reduces the "
    "army by one.\n"
    "Select how many dice you want to roll in this battle (3 is the smartest in this case but "
    "feel free to play around) and then click the green button.":
        "Voor elke troep in het land waaruit je aanvalt, mag je een dobbelsteen gooien "
        "(hoogstens 3). De verdediger ook, maar die gooit er hoogstens 2. De hoogste "
        "aanvalssteen wordt vergeleken met de hoogste verdedigingssteen en de hoogste wint. Bij "
        "gelijkspel wint de verdediging. Hetzelfde gebeurt met de op één na hoogste stenen (als "
        "dat kan). Elke steen die verliest, kost zijn leger één troep.\n"
        "Kies met hoeveel dobbelstenen je in dit gevecht wilt gooien (3 is hier het slimst, maar "
        "probeer gerust wat uit) en klik dan op de groene knop.",
    "Move into Mexico": "Trek Mexico in",
    "{} is yours. Now you get to choose how many troops to move in. {} Click on {} or {} until "
    "only 3 troops move into {}, then click the green button to confirm.":
        "{} is van jou. Nu kies je hoeveel troepen erin trekken. {} Klik op {} of {} tot er nog "
        "maar 3 troepen {} in trekken, en klik dan op de groene knop om te bevestigen.",
    "Since you rolled with 1 die, you must move in at least 1 troop.":
        "Omdat je met 1 dobbelsteen gooide, moet je er minstens 1 troep in zetten.",
    "Since you rolled with {} dice, you must move in at least {} troops.":
        "Omdat je met {} dobbelstenen gooide, moet je er minstens {} troepen in zetten.",
    "Attack Brazil": "Val Brazilië aan",
    "Attack {} from {} the same way: click {}, then {}, roll, and click to see the result.":
        "Val {} op dezelfde manier aan vanuit {}: klik op {}, dan op {}, gooi, en klik om de "
        "uitslag te zien.",
    "Everyone in": "Iedereen erin",
    "This time move all your troops into {}, leaving {} empty: click {} until {} has none "
    "left. Then click the green button.":
        "Zet deze keer al je troepen in {} en laat {} leeg: klik op {} tot er in {} niemand meer "
        "over is. Klik dan op de groene knop.",
    "The natives": "De inboorlingen",
    "Nobody holds {} now, so the natives took it back. Most native countries go back to 2 "
    "troops; a few are different. Countries that produce 3 or less resources have only 1 "
    "native defender.\n"
    "Have a look around the map to see for yourself. When you hover your mouse over a "
    "country you will see a panel appear on the top right with the resources it produces.":
        "Niemand heeft {} nu, dus de inboorlingen hebben het teruggenomen. De meeste landen van de "
        "inboorlingen krijgen weer 2 troepen; een paar zijn anders. Landen die 3 of minder "
        "grondstoffen opleveren, hebben maar 1 inboorling als verdediger.\n"
        "Kijk zelf maar eens rond op de kaart. Als je met je muis boven een land hangt, verschijnt "
        "rechtsboven een paneel met de grondstoffen die het oplevert.",
    "Attack Peru": "Val Peru aan",
    "Now attack {} from {}: click {}, then {}, roll, and click to see the result.":
        "Val nu {} aan vanuit {}: klik op {}, dan op {}, gooi, en klik om de uitslag te zien.",
    "Move in 5 troops": "Trek met 5 troepen in",
    "Move 5 troops into {}: click {} or {} until {} has 5, then click the green button.":
        "Zet 5 troepen in {}: klik op {} of {} tot {} er 5 heeft, en klik dan op de groene knop.",
    "On to moving": "Op naar verplaatsen",
    "Click the orange button to go to the move phase.":
        "Klik op de oranje knop om naar de verplaatsfase te gaan.",
    "Move 2 troops": "Verplaats 2 troepen",
    "Once per turn you can move troops between two of your countries. Click {}, then {}, then "
    "click {} twice to move 2 troops there, and click the green button.":
        "Eén keer per beurt kun je troepen verplaatsen tussen twee van je landen. Klik op {}, dan "
        "op {}, klik dan twee keer op {} om er 2 troepen heen te zetten, en klik op de groene "
        "knop.",
    "Cut off": "Afgesneden",
    "{} and {} are both yours, but you can't move troops between them: moves only go through "
    "your own countries, and the way runs through {}, which the natives hold now.":
        "{} en {} zijn allebei van jou, maar je kunt geen troepen tussen ze verplaatsen: "
        "verplaatsen gaat alleen via je eigen landen, en de weg loopt via {}, dat nu van de "
        "inboorlingen is.",
    "End your turn": "Beëindig je beurt",
    "Click End turn. Then the others play.": "Klik op Einde beurt. Daarna spelen de anderen.",
    "Green's turn": "Groen is aan de beurt",
    "Green places 3 troops and a ship in {}, crosses the sea to attack {} and moves in, "
    "leaving 1 troop in {}.":
        "Groen zet 3 troepen en een schip in {}, steekt de zee over om {} aan te vallen en trekt "
        "erin, met 1 troep achter in {}.",
    "Red's turn": "Rood is aan de beurt",
    "Red adds 3 troops to {} and ends its turn.":
        "Rood zet 3 troepen bij in {} en beëindigt zijn beurt.",
    "Over the sea": "Over zee",
    "The dotted blue lines are sea routes. You can't cross them without something to carry "
    "your troops over the water: a ship, or a plane.":
        "De blauwe stippellijnen zijn zeeroutes. Die kun je niet over zonder iets om je troepen "
        "over het water te brengen: een schip, of een vliegtuig.",
    "Buy a ship": "Koop een schip",
    "Your first ship each game is free. Open the shop, click the ship, click the green button and then "
    "click {} to put it there.":
        "Je eerste schip van elk spel is gratis. Open de winkel, klik op het schip, klik op de groene knop en "
        "klik dan op {} om het daar te zetten.",
    "Put your 3 new troops in {} too.": "Zet je 3 nieuwe troepen ook in {}.",
    "A chance": "Een kans",
    "Green is spread thin: 1 troop in {}, 1 in {} and 4 in {}. If you bring your troops "
    "together, you can eliminate green this turn.":
        "Groen is dun verspreid: 1 troep in {}, 1 in {} en 4 in {}. Als je je troepen "
        "samenbrengt, kun je groen deze beurt uitschakelen.",
    "Retake Venezuela": "Herover Venezuela",
    "First attack {} from {}. When it's yours, move in all your troops but one.":
        "Val eerst {} aan vanuit {}. Is het van jou, zet er dan al je troepen op één na in.",
    "Rails": "Spoorwegen",
    "Rails let your troops ride from country to country in one go. Open the shop, pick the "
    "rails (2 wood, 1 steel), click the green button, then click {} and {}.":
        "Over spoorwegen rijden je troepen in één keer van land naar land. Open de winkel, kies "
        "de spoorweg (2 hout, 1 staal), klik op de groene knop en klik dan op {} en {}.",
    "More rails": "Meer spoorwegen",
    "Now lay rails from {} to {} the same way.":
        "Leg nu op dezelfde manier een spoorweg van {} naar {}.",
    "Take the train": "Neem de trein",
    "Click {}, then the train button at the bottom left (1 oil). Right-click {} and {} to "
    "take their troops out, leaving 1 in each, and left-click {} to put them all there. Then "
    "click the green button.":
        "Klik op {} en dan op de treinknop linksonder (1 olie). Klik met rechts op {} en {} om "
        "hun troepen eruit te halen, met 1 achter in elk, en klik met links op {} om ze daar "
        "allemaal neer te zetten. Klik dan op de groene knop.",
    "Across to Cuba": "Over naar Cuba",
    "Attack {} from {}: your ship carries the troops across. When it's yours, move every "
    "troop in and leave {} empty: keeping all your troops together gives the best chance to "
    "eliminate green this turn.":
        "Val {} aan vanuit {}: je schip brengt de troepen over. Is het van jou, zet er dan elke "
        "troep in en laat {} leeg: met al je troepen bij elkaar heb je de beste kans om groen "
        "deze beurt uit te schakelen.",
    "On to New York": "Op naar New York",
    "Attack {} from {}, and again move everyone in, leaving {} empty.":
        "Val {} aan vanuit {} en zet er weer iedereen in, zodat {} leeg blijft.",
    "Take London": "Neem Londen in",
    "Attack {}, green's last country, from {}. Roll until it's yours, then click the green "
    "button to move in.":
        "Val {}, het laatste land van groen, aan vanuit {}. Gooi tot het van jou is en klik dan "
        "op de groene knop om erin te trekken.",
    "Green is out": "Groen ligt eruit",
    "Taking a player's last country eliminates them, and you get their cards, wood, steel, "
    "oil and uranium, but not their food.":
        "Wie het laatste land van een speler verovert, schakelt die uit en krijgt zijn kaarten, "
        "hout, staal, olie en uranium, maar niet zijn voedsel.",
    "Sail back": "Vaar terug",
    "Move your ship and troops back to {}: click {}, then {}, and click {} until {} has 1 "
    "left. Then pick the ship on the left, click {} once and click the green button.":
        "Breng je schip en troepen terug naar {}: klik op {}, dan op {}, en klik op {} tot {} er "
        "nog 1 heeft. Kies dan links het schip, klik één keer op {} en klik op de groene knop.",
    "Click End turn.": "Klik op Einde beurt.",
    "Red adds 3 more troops to {}: 12 now, behind its fort.":
        "Rood zet nog 3 troepen bij in {}: nu 12, achter zijn fort.",
    "Put your 3 new troops in {}.": "Zet je 3 nieuwe troepen in {}.",
    "Buy a plane": "Koop een vliegtuig",
    "A plane carries troops across the sea, for 1 oil per attack, and makes its country an "
    "airport. Buy one (10 steel) and put it in {}.":
        "Een vliegtuig brengt troepen over zee, voor 1 olie per aanval, en maakt van zijn land "
        "een luchthaven. Koop er een (10 staal) en zet het in {}.",
    "Buy a tank": "Koop een tank",
    "A tank adds 1 to your highest die when you attack, for 1 oil per attack. Buy one (20 "
    "steel) and put it in {}.":
        "Een tank telt 1 op bij je hoogste dobbelsteen als je aanvalt, voor 1 olie per aanval. "
        "Koop er een (20 staal) en zet hem in {}.",
    "Trade cards": "Ruil kaarten",
    "Conquering a country of another player earns you a card at the end of your turn: with "
    "green's 3 cards you now hold 4. Three different cards make a set worth 10. Open your "
    "cards (the set is selected), click the green button and take 10 uranium: you'll need it "
    "later.":
        "Wie een land van een andere speler verovert, krijgt aan het eind van zijn beurt een "
        "kaart: met de 3 kaarten van groen heb je er nu 4. Drie verschillende kaarten vormen een "
        "set van 10. Open je kaarten (de set is al geselecteerd), klik op de groene knop en neem "
        "10 uranium: dat heb je straks nodig.",
    "The fort": "Het fort",
    "{} has a fort: it adds 1 to every die red defends with, and 12 troops stand behind it. "
    "That will be a hard fight.":
        "{} heeft een fort: het telt 1 op bij elke dobbelsteen waarmee rood verdedigt, en er "
        "staan 12 troepen achter. Dat wordt een zware strijd.",
    "Rails to Brazil": "Spoor naar Brazilië",
    "Lay rails between {} and {} too: open the shop, pick the rails, click the green button, "
    "then click {} and {}.":
        "Leg ook een spoorweg tussen {} en {}: open de winkel, kies de spoorweg, klik op de groene "
        "knop en klik dan op {} en {}.",
    "Gather by rail": "Verzamel per trein",
    "First bring your troops in South America together: click {}, then the train button, "
    "right-click {} and {} to remove troops there and left-click {} to place them down. Then "
    "click the green button.":
        "Breng eerst je troepen in Zuid-Amerika samen: klik op {}, dan op de treinknop, klik met "
        "rechts op {} en {} om er troepen weg te halen en met links op {} om ze neer te zetten. "
        "Klik dan op de groene knop.",
    "Fly to London": "Vlieg naar Londen",
    "Airports do the same thing as rails by connecting all of your airport countries together. "
    "As long as you have at least one airplane at one of your airports and 1 oil to pay for the "
    "flight, you can reposition troops and tanks between your airports as you like. Click on "
    "the plane button that appears when you have either {} or {} selected. Right-click to "
    "remove troops from {} until it is empty, then select the tank icon on the left and "
    "right-click {} again to remove the tank as well. Left-click on {} to place the tank and "
    "troops.":
        "Luchthavens doen hetzelfde als spoorwegen: ze verbinden al je landen met een luchthaven. "
        "Zolang je minstens één vliegtuig op een van je luchthavens hebt en 1 olie om de vlucht te "
        "betalen, kun je troepen en tanks tussen je luchthavens verplaatsen zoals je wilt. Klik op "
        "de vliegtuigknop die verschijnt als je {} of {} geselecteerd hebt. Klik met rechts om "
        "troepen uit {} weg te halen tot het leeg is, kies dan links het tankicoon en klik nog "
        "eens met rechts op {} om ook de tank weg te halen. Klik met links op {} om de tank en de "
        "troepen neer te zetten.",
    "Nuke Viking": "Bombardeer Viking",
    "A nuke kills half the troops of a country adjacent to yours. Buy one in the shop (5 uranium) "
    "and click {}. Then do it once more.":
        "Een atoombom doodt de helft van de troepen van een land dat aan het jouwe grenst. Koop er "
        "een in de winkel (5 uranium) en klik op {}. Doe het daarna nog een keer.",
    "Fallout": "Neerslag",
    "Two nukes brought {} from 12 troops down to 3. And while it's radioactive (3 turns per "
    "nuke) it produces nothing.":
        "Twee atoombommen brachten {} van 12 troepen terug naar 3. En zolang het radioactief is "
        "(3 beurten per bom) levert het niets op.",
    "Attack Viking": "Val Viking aan",
    "Attack {} from {}: the plane carries your troops across (1 oil) and the tank adds 1 to "
    "your highest die (1 oil). Roll until it's yours, then move all your troops in.":
        "Val {} aan vanuit {}: het vliegtuig brengt je troepen over (1 olie) en de tank telt 1 op "
        "bij je hoogste dobbelsteen (1 olie). Gooi tot het van jou is en zet er dan al je troepen "
        "in.",
    "Out of oil": "Geen olie meer",
    "Red's last country, {}, lies across the sea, and your oil is gone: the plane can't take "
    "your troops over.":
        "Het laatste land van rood, {}, ligt aan de overkant van de zee, en je olie is op: het "
        "vliegtuig kan je troepen niet overbrengen.",
    "Build a bridge": "Bouw een brug",
    "A bridge turns a sea route into a land route. Buy one (10 wood), then click {} and then {}.":
        "Een brug maakt van een zeeroute een landroute. Koop er een (10 hout) en klik dan op {} "
        "en daarna op {}.",
    "Eliminate red": "Schakel rood uit",
    "Bring or leave": "Meenemen of thuislaten",
    "Before you roll, the button at the top with a ship, a plane and a tank lets you choose "
    "which of them come along into the fight. What you bring moves into the country you "
    "conquer, but it's destroyed if you roll 1 or 2 dice and lose them all. Without oil your "
    "tank adds nothing to your dice, so leave it at home: click {}, then {}, then that button "
    "at the top.":
        "Voor je gooit, kies je met de knop bovenaan met een schip, een vliegtuig en een tank "
        "welke ervan meegaan in het gevecht. Wat je meeneemt, trekt mee het veroverde land in, "
        "maar gaat verloren als je met 1 of 2 dobbelstenen gooit en ze allemaal verliest. Zonder "
        "olie telt je tank niets op bij je dobbelstenen, dus laat hem thuis: klik op {}, dan op "
        "{} en dan op die knop bovenaan.",
    "Leave the tank": "Laat de tank thuis",
    "Click the red minus next to the tank until it says 0, then click anywhere to close this "
    "panel.":
        "Klik op het rode min-teken naast de tank tot er 0 staat en klik dan ergens om dit "
        "paneel te sluiten.",
    "Attack {} from {} by crossing your bridge, and win the game!":
        "Val {} aan vanuit {} door over je brug te gaan, en win het spel!",
    "Next": "Volgende",
    "Exit to title": "Naar titelscherm",
    " placed {} troops in {}": " zette {} troepen in {}",
    # (used outside the tutorial)
    "skips": "slaat over",
}


# --- Dutch source -> English ------------------------------------------------

EN = {
    # Menus
    "De 3 Neven": "The 3 Cousins",

    # The resource "nuclear" (its name in the code) is called uranium on screen.
    "nuclear": "uranium",

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
