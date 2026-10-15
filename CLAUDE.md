# OIL board game

A Risk-like strategy board game in Python + pygame-ce: 3–6 players conquer
countries on a world map, collect resources (food, wood, steel, oil,
nuclear, troops), build in a shop, trade cards ("kaertskes") and deal with
random world events. Country names, event names and event texts are Dutch
in the code (e.g. "Sovjet-Rusland", "Nazi-Duitsland", "Belgisch Congo");
UI messages are English in the code. The game is shown in Dutch or English
(the flag top right in the main menu, remembered in `saves/settings.json`):
every text on screen goes through `lang.t()` (see Translation below). The
neutral player is called **mouse** (`engine.default_player`).

The user writes in English and Dutch; answer in the language they use.

## Running

```bash
python3 runner.py
```

Requirements: `pygame-ce>=2.5`, `numpy>=1.19.3`, `matplotlib>=3.3.3`,
`certifi` (for the app's updater)
(this Mac: Python 3.9 with numpy 1.19.3; the game also runs on a current
Python with numpy 2). Players use the app instead (OIL.app / the Windows
installer, see "App & updates" below). The only automated checks are `event_checks.py` (events),
`bot_checks.py` (bot decisions on small boards), `bot_selfplay.py` (bots
against each other), `bot_golden.py` (did a change leave the bots' play
exactly as it was) and `online_checks.py` (online play).

**Windows:** the game runs as is: pygame-ce/SDL handles the window, sound
and controllers. Install Python from python.org, then in the game
folder run `py -m pip install -r requirements.txt` and `py runner.py` (or
double-click `runner.py`; a console window opens next to the game).
`runner.py` first switches to its own folder (images and `saves/` are
relative paths), so it can be started from anywhere. Controllers work as on
the Mac (SDL's game controller API: Xbox through XInput/raw input,
PlayStation and Switch Pro through HIDAPI). Not tried on real Windows
hardware: more than 4 Xbox controllers at once, and Steam Input taking
controllers over while Steam is running. Of the tools, `bot_selfplay.py`
(`signal.SIGALRM`) and `bot_fork.py` (`os.fork`) only run on macOS/Linux.
The golden traces depend on the Python version: from Python 3.11 on, strings
hash differently, so a few ties between equally good moves (the bot
iterating over sets of country names) go the other way. Compare them on
the Python that made them: since 14 Oct 2026 (after Update 4.10's eight new
events) both files were written on Windows with Python 3.12. numpy 2 is fine.

## Files

| File | What's in it |
|---|---|
| `runner.py` | Entry point: start menus → `play(app)` loop. "Exit Game" returns to the start menu; closing the window quits. F5/F9 quicksave/quickload (the game's autosave file, `Engine.save_path`), Esc toggles fullscreen. |
| `menu.py` | Start menu (with the language flag; Local Game / Online Game / Tutorial), new-game menu, player-name entry (with controller pairing), Continue/load screen (autosave + 4 named slots). Each is its own small pygame loop. |
| `tutorial.py` | The Tutorial (start menu): a local game on a fixed small board (the player in southern Africa, bots in New York and Siberië) with a guide panel that walks through the screen and the rules and plays the first turn along (`STEPS`: a page to read with Next, or a step that waits for the player's move, `done`, with Skip). It rings what a step is about (`Tutorial._shapes`), holds back the phase buttons and End turn unless the step asks for them, holds world events back until it's finished, and autosaves to a temp file. `runner.play` calls `Engine.tutorial.handle_input` after `io_handle` and `draw` before `present`. Texts are English source with their Dutch in `lang.NL`. When the game's screens or rules change, check the steps' texts and `_shapes` still fit. |
| `lobby.py` | Online Game's screens: Host (a new or saved game, then its lobby of seats) and Join (the games on every relay found, a game's lobby, then the viewer), plus a message screen. See Online play below. |
| `online.py` | The host's side of an online game: `HostSession` (seats, joined devices, who may click, the game's state and log for the devices, cursors, sounds, the host's own country info panel and menus), `RemotePointer` (a joined device's mouse or controller with its device's view, taken like a `controls.Pad`), `OverlayStream` (the game's layer as PNG tiles). |
| `viewer.py` | A joined device's side of an online game: its own copy of the game made from the host's state, drawn with its own view (pan/zoom), the host's game layer on top, its own HUD buttons, country info panel, action log and menus; sends its mouse and controllers, plays the host's sounds; its own Esc menu (leave, fullscreen) and chat. |
| `chat.py` | The online game's chat (`Chat`): messages, the button under the settings button with its unread badge, the panel, typing. One per device (host: `HostSession.chat`, a joined device: `Viewer.chat`). |
| `net.py` | Online plumbing (standard library only): `Connection` to a relay (send/receive threads), `RoomBrowser` (relays on this computer, the LAN and the main server, told apart by id), `find_main_relay`, `PROTOCOL`, `DEFAULT_SERVER`, `device_id`. |
| `relay.py` | The relay server: rooms, routing, LAN beacons. `python3 relay.py` on the home computer; `start_embedded` runs one inside a host's game for a LAN game. Standard library only and self-contained. |
| `online_checks.py` | Headless PASS/FAIL checks of online play (relay, discovery, the game's layer stream, seats, who clicks, the state on a device's copy and its own view, the chat, the hover panels, own menus, a whole game through a local relay): `python3 online_checks.py [filter]`. |
| `controls.py` | Game controllers, one per player, each with its own cursor (`Pad`). `Controls` (one, `controls.get()`) reads them, pairs them with players, decides which may click (`frame`) and draws the cursors. See Game controllers below. |
| `lang.py` | Dutch/English: `t(text)`, `Msg`/`Join` (log text translated when drawn), the current `language`, `set_language` (saved in `saves/settings.json`), the `NL` (English source → Dutch) and `EN` (Dutch source → English) tables. |
| `engine.py` | `Engine`: window/view, cached map layer rendering, troop markers, HUD buttons, settings menu (Exit Game, Save As, display toggles), online each device's own menus (`own_menus`), fonts/images, player setup. |
| `phases.py` | All game rules as a state machine: `Phase` base class, one class per phase, and `TurnManager` (turn order, events schedule, eliminations, notices/dialogs). ~2,400 lines. |
| `models.py` | `Player`, `Country` (drawing incl. troop markers + fort badges), `Connection` (routes, dotted sea routes, waypoint curves), `Dice`, `Io` (mouse input + hover/hit tests), `View`, `Gui` (side panels), `CardMenu`, `Kaertske`, `Button`. |
| `board.py` | The map: `CONTINENTS`, `get_countries(default_player)` (resources/start units per country), `get_connections()` (land/sea links). |
| `events.py` | World events: `Event` base class with hooks, one subclass per event, `EVENTS` list (31). |
| `bot.py` | Computer player: `BotController` (plays a bot's turn step by step, values everything in troops), exact combat odds (`battle`), difficulty `LEVELS` and `PERSONALITIES`. |
| `bot_selfplay.py` | Headless bot-vs-bot games and A/B tests for tuning bots: `python3 bot_selfplay.py [games] [players] [--vs FILE / --botA FILE / --tweakA k=v / --tweakB k=v / --personality p] [--jobs N] [--maxturns N] [--out FILE]`. Reproducible (same seed, same game); players can be a list (`3,4,5,6`); one JSON line per game (the file is appended to, so a rerun into the same file adds to it); runs `bot_report.py` at the end. `--refund-assets A` is a research oracle (side A gets the price of every ship/tank/plane/fort it loses back). See its docstring. |
| `bot_report.py` | Tables from `bot_selfplay.py` results (`python3 bot_report.py FILE.jsonl`): pair-level A-B contrasts (win, placement, loot legacy and market, eliminations), game length, KPIs per behaviour. |
| `bot_kpi.py` | The KPI recorder behind those tables (first ship, water protection, retention, cards, emptied countries, hoards, spend-down, assets bought/destroyed and why, what the one move a turn moves). Wraps game methods; changes no play. |
| `bot_fork.py` | Forked what-ifs: play a game, fork it at a moment (e.g. the leader's turn once 2 players are left) and let one seat continue with different tunables (`--arm NAME:KEY=VALUE,...`), same board and dice for every arm. Resolves a behaviour that matters within a few turns (a strike, the endgame) with a few hundred forks, where whole games need thousands. `python3 bot_fork.py OUT.jsonl 4 SEED GAMES --stage 2:0,2 --min-share 0.5 --arm off:endgame_alive=0 --arm on:` then `--report OUT.jsonl`; run several in parallel. |
| `bot_checks.py` | Headless PASS/FAIL checks of bot decisions on small boards (exposure, retention, strike step, finisher): `python3 bot_checks.py [filter]`. Add a check there when adding a bot behaviour. |
| `bot_golden.py`, `golden_traces.json`, `golden_traces_new.json` | Golden traces: 12 whole games boiled down to an md5 per game. `python3 bot_golden.py` says whether the bots still play exactly like the traces in `golden_traces.json` (those of `old_bot.py`, before the retraining; only matches with the new tunables off, see below, and not where the 4.10 events come up); `python3 bot_golden.py --golden golden_traces_new.json` compares with the bot as it was left after the retraining (rewrite it with `--update` when play is changed on purpose); `--bot FILE`, `--tweak k=v` to vary. |
| `old_bot.py` | Frozen copy of bot.py from 2 Oct 2026, before the retraining: the baseline every A/B test and the golden traces compare against. |
| `bot_research/` | Reports and prototype scripts of the research behind the bot retraining (reports in `bot_research/reports/`; `backup_before_wp0/` holds the files as they were before it started; `compare_assets.py` puts several A/B result files side by side). Not used by the game. |
| `event_sandbox.py` | Interactive test board for events: `python3 event_sandbox.py`. Fixed 4-player board, events only when picked (F2), shows what each start/end changed; keys for editing the board (see its docstring / F1). Saves go to temp files. |
| `event_checks.py` | Headless PASS/FAIL checks per event through the real game code: `python3 event_checks.py [filter]`. Add a test there when adding an event. |
| `save_load.py` | JSON save/load (`game_data` / `apply_data`: the state as a dict and back, also what an online host sends its devices), save paths (`saves/autosave.json`, `saves/slot1-4.json`; in the app `OIL_SAVES_DIR`), legacy `savegame.json` migration. |
| `updater.py` | The app's Update button (main menu): checks GitHub Master, downloads only the changed files into `game.new/` (pip-installs `libs.new/` when `requirements.txt` changed), marks it ready, restarts. Only active in the app (`managed()`). |
| `packaging/relay/` | The home relay: `install.sh` (Mac: a LaunchAgent; optionally DuckDNS), `nl.oil.relay.plist`, `install.ps1` + `oil_relay.pyw` (Windows: a Startup-folder shortcut to a windowless launcher that logs, keeps the PC awake, restarts the relay and optionally updates DuckDNS), `README.md` (firewall, router port, two routers, dynamic DNS, `net.DEFAULT_SERVER`). |
| `packaging/` | The app: `bootstrap.py` (the one fixed piece inside the app: puts an update in place, rolls back one that never reached the menu, starts `runner.py`), `build.py` (builds OIL.app / the Windows folder with python-build-standalone 3.12), `oil_installer.iss` (Windows installer), `make_icon.py` + `icon.png` (app icon; `images/icon.png` is the window icon), `release_notes.md`. |
| `.github/workflows/build-app.yml` | Builds the Mac zips and `OIL-Setup.exe` into a GitHub Release (Actions › Build app › Run workflow). |
| `player_colors.py` | Fixed player colours for N-player games, `light_tint`, `name_text_color` (black text on yellow). |
| `map_polygons.py` | Country outline data. |
| `outline_smoothing.py`, `landmark_placement.py` | Smoothed country outlines; where pagoda/torii landmark sprites go. |
| `gevoeligheden.txt` | Notes (Dutch) on sensitivities when playing the game. |
| `images/` | Sprites. |

`../oil_board-Master copy/` is an older snapshot of the game (as of 27 Sept 2026), not in use.

## Game state machine

Everything runs off two ints on the **current** player: `player.attack`
(which phase) and `player.subattack` (step within it). `TurnManager.phases`
maps `attack` → phase object; each frame `TurnManager.update()` calls that
phase's `update()`, which draws its UI and reacts to clicks.

| `attack` | Phase | Main `subattack` steps |
|---|---|---|
| 0 | `ReinforcementPhase` | 0 start of turn (income, continent cards, events' `on_turn_start`) · 1 deploy troops (left-click add, right-click remove; 2 is an old alias) · 3 starvation popup · 4 starvation: remove troops |
| 1 | `AttackPhase` | 0/1 pick attacker/target · 2 choose attack dice · 3 defender rolls · 4 resolve combat · 5 move troops in after a conquest · 6 asset panel (ships/tanks/planes) · 7 rail redistribution · 8 defender picks tanks · 9 the pirates' wheel spins (an event's `sea_attack_wheel`, "storm of zee"; skipped headless, `bot.fast`) |
| 2 | `MovementPhase` | 0 pick origin · 1 pick target · 2 adjust (troops/ships/tanks/planes) · 3 rails · 4 develop a country |
| 3 | `ShopPhase` | 1–7 selected item · 9–17 placing the bought item on the map |
| 4 | `RecruitPhase` | placing troops from a card trade outside the reinforcement phase |
| 5 | `EventTargetPhase` | an event makes the player pick a country (possibly another player, `chooser`) |
| 6 | `MouseAttackPhase` | an event's mouse attack shown round by round (inboorlingen vechten terug): 0 next target · 1 defender's tanks · 3 defender's dice · 4 resolve |

The shop remembers where it was opened from (`saved_attack/saved_subattack`)
and returns there. `TurnManager.attack_in_progress()` blocks the shop, card
menu and move phase once dice are cast.

## Rules worth knowing

- Combat is Risk-style: attacker up to 3 dice, defender up to 2, ties go to
  the defender. Fort level adds to every defence die; active tanks add to the
  attacker's highest die; events can add bonuses/penalties.
- By default one troop stays behind when attacking; with only one defence
  die the defender rolls automatically; move-in is automatic when there's no choice.
- Crossing water needs a ship or plane escort; a moved ship needs at least one troop with it.
- A failed attack roll destroys every asset brought along (ships, tanks,
  planes): rolling 1 die and losing it, or 2 dice and losing both. Over sea
  and (since 9 Oct 2026) over land, bridges and rails alike; 3 dice never do.
  Over sea (and by air) that also ends the battle: with the ship/plane gone
  the attacker goes back to picking an attacking country, even with troops
  left (a spare ship/plane there can start a new attack). Over land the
  attack may go on, but destroyed tanks no longer add their +1, and their
  paid oil is gone too (`tank_fee_paid` drops by the destroyed active
  tanks), so a tank brought in from home for the next round pays again.
- Immigrants (`Country.immigrants`, from the event "Immigratie", saved) are
  troops that never move or attack: part of `units` (they defend and eat),
  the last to die (and only starve once the player has no other troops
  left); setting `units` below them takes them along (a property
  setter), so a fallen country loses them. Attacks, move-in, moves and the
  rail/air screen leave them home; the bot counts `country.free` (troops
  that can leave) and `country.keep` (that stay) where it used `units - 1`
  and 1, which is the same without immigrants.
- Food caps armies: at the start of a turn every troop beyond the food *in
  stock* starves (that turn's harvest only comes in after), so an army
  can't outgrow its food income for long. When troops starve, the turn's production (and
  reinforcements) is worked out only after the player has chosen who dies
  (`ReinforcementPhase.finish_starvation`), so countries left empty give nothing.
  A player's very first turn gives no income at all. A player who starves while
  their income is 0 (e.g. under nucleaire winter) loses everything the
  turn after.
- Continents give cards at turn start (`CONTINENT_CARD_BONUS` in phases.py).
  Developed countries yield double, after one idle income — unless the owner
  still holds the whole continent at their next turn start.
- Eliminating a player (by conquest or nuke) gives the victor their
  wood/steel/nuclear/oil and cards (`Phase.take_last_country`).
- Events: drawn from a shuffled bag (each once per pass); schedule rules in
  `TurnManager._update_event_schedule`. Add one by subclassing `Event` in
  `events.py` and appending it to `EVENTS`; use the hooks (`on_start`,
  `on_end`, `modify_income`, `attack_bonus`, `dice_penalty`,
  `discount_shop_cost`, `on_turn_start`, `on_abandon`, `panel_lines` (extra
  lines in the event panel), ...) rather than special-casing
  events in phases.py (or bot.py: bots see an event through those hooks,
  plus the `bot_*` hints for what they can't work out from them).
- "storm of zee": when an attack over sea is confirmed, `sea_attack_check`
  decides at once whether pirates take the troops on the selected dice
  and everything brought along (ship/plane, tanks), which ends that battle;
  everyone first sees it on a wheel (`phases.PirateWheel`: 1 red pirate
  slice in 3) that lands accordingly, while `TurnManager.animating` keeps
  `runner.play` drawing frames.
- A cancelled turn (`TurnManager.skip_turns`, names, saved; "Woke") is
  skipped as the turn starts (`_skip_cancelled`): no income, nothing, and
  no event card is revealed on it.

## Translation

Text on screen is wrapped in `lang.t()`: `t("{} wins!").format(name)`
(translate the template, then format). English source text gets its
Dutch in `lang.NL`, Dutch source text (board, events, cards) its English
in `lang.EN`. Names that are identifiers -- countries, continents, event
names, card names, `LANDMARKS` values -- stay untranslated in the game
state and saves and get `t()` only where they're shown (e.g.
`t(country.name)` inside a message). Grammar that differs per language
gets a template per case (singular/plural, per verb) rather than words
glued together. Action-log lines are `lang.Msg(template, *args)` (lists
via `lang.Join`), not finished text: they're translated each time they're
drawn and saved as template + arguments, so the whole log follows the
language, also in a loaded save (logs from saves made before this are
plain text and stay as they were). Notices and hints are translated when
they're made. Bots' `_say` status lines aren't shown and aren't translated.

## Drawing conventions

- UI is laid out in a fixed **logical 960×640** space (`view.WIDTH/HEIGHT`)
  and scaled to the window. The map is drawn in real pixels on
  `view.map_surface`; multiply logical sizes by `view.draw_scale`.
  `Position.to_px(view)` converts map coordinates to pixels.
- The map layer (countries, borders, connections, landmarks) is **cached**
  in `Engine._render_layer`: a fast 1× version while panning/zooming, then a
  smooth 2× supersampled one. Changes to what it draws must be reflected in
  `Engine._map_keys()` or the cache won't refresh.
- The map wraps around east-west: `PACIFIC` (300) map units of sea lie
  between Siberië/Japan and the Americas, and the world repeats every
  `WORLD_WIDTH` (models.py). The map layer and troop markers are drawn once
  per copy on screen (`View.copies` / `View.shifted`, extent
  `Engine._world_extent`); `WRAP_ROUTES` (Alaska–Siberië, Japan–Pearl
  Harbor) are drawn east into the next copy; `Io.update` hit-tests every
  copy (`wrap_x`); `View.wrap` keeps `offset.x` within one copy. Pearl Harbor
  is moved out into the Pacific in `get_countries`.
- See-through drawing uses `Engine._blended(surface, opacity)` (snapshot then
  blend back), not a transparent layer — that leaves artifacts on
  antialiased edges. Borders: grey 80%. Connections: 70%.
- Map style: sea routes are evenly spaced dots (`Connection.DOT_STEP`), land
  routes solid green with black outline; curved routes via
  `Connection.WAYPOINTS`. Troop markers: light tint of owner colour, white
  edge, black number; square for airport countries; white lines for assets
  (ship "/", tank "—", plane "\"); forts as white badges with 2/4/8
  battlements (rounded bottom under circles, square under squares).
- Developed countries get a sun-yellow (255, 200, 40) band just inside the
  grey border (`Country.DEVELOPED_COLOR/DEVELOPED_BAND`), dotted while
  still being developed (`dormant_owner` set, `DEVELOPING_DOT_STEP`); radioactive
  countries a yellow/black hazard band. Both use `Country._band_alpha`.
- Mouse's colour is (140, 140, 140).
- Pop-ups without a Confirm button (the attack's asset panel, the
  defender's tanks) use `Phase.click_anywhere_popup`: light blue box,
  "Click anywhere to continue" hint, a click anywhere but on a button
  closes it. Open them with `Phase.open_popup(subattack)`, which starts
  a 500 ms grace period so a double click can't close them unseen.

## Saves

Saves store state by **name** (players, countries, events), so they survive
code changes; unknown names are dropped rather than failing. New mutable
state on players/countries/connections/TurnManager must be added to both
`save_game` and `load_game` (use `.get(key, default)` when loading so old
saves still work). A save always resumes at `subattack = 0` of its phase;
in the reinforcement phase `TurnManager.turn_started` keeps that from
running the turn start (feeding, income, reinforcements) a second time.
Players' `is_bot` and `bot_personality` are saved.

## App & updates

Players run OIL as an app: `OIL.app` (Mac) or the Windows installer, built by
`packaging/build.py` (locally, or by the GitHub workflow into a Release). The
app is a Python 3.12 (python-build-standalone, with pip) plus
`packaging/bootstrap.py`; it keeps everything in the device's data folder
(`~/Library/Application Support/OIL`, `%LOCALAPPDATA%\OIL`): `game/` (the
game files), `libs/` (libraries an update installed; until then the app's
own), `saves/` (saves + settings.json, which no update touches),
`crash.log`, `update.log`. The Update button (`updater.py`) brings in whatever
is on GitHub's `Master`: code, images, sounds and new libraries alike, so the
app itself only needs rebuilding to change Python or `bootstrap.py`
(keep that file small and backwards compatible). An update skips `saves/`,
`__pycache__/` and the dev-only folders (`updater.SKIP_DIRS`), and is refused
if it lacks `runner.py` or `updater.py` (it couldn't update itself again).
The game must keep running on the app's Python 3.12 as well as this Mac's 3.9.
Publishing a version = committing and pushing to `Master`.
Test the update flow without building: `OIL_DATA_DIR=<scratch folder>
python3 packaging/bootstrap.py` (this folder plays the app's bundled game).

## Game controllers

Every player can use their own game controller (`controls.py`, SDL's game
controller API through `pygame._sdl2.controller`, so Xbox/PlayStation/
Switch Pro all have the same layout): left stick moves that controller's
cursor, A/B are left/right click, the right stick pans, LB/RB zoom, Start
opens the settings menu. A controller is fed into the one `Io` as another
pointer (`Io.update(view, countries, source, fresh)`; `Io.source` is None
for the mouse), so phases can't tell the difference; `Io` follows whichever
of the mouse and the clicking controllers was used last. Only the acting
player's controller clicks (`TurnManager.acting_player`: the current
player, a human defender picking tanks/dice, an event's `chooser`, the
owner of a country the mouse attacks; online, that's also how a joined
device gets the click); the other cursors are drawn faded.
On a bot's turn every paired controller clicks. The mouse always works.
A player whose turn it isn't pressing A on a country hears its name;
online also clicking it with a mouse: a joined device's, or the host's own
while a joined device's player decides
(`Engine.bystander_clicks`, `sounds.play_country`: `sounds/countries/<country>.flac`,
matched ignoring case/accents/spaces/hyphens; pygame can't play .m4a, so
voice memos are converted with `afconvert -f flac -d flac@22050`).
In the start menus every controller clicks (`menu._input`).
Pairing: the controller buttons on the player-names screen, or the
Controllers panel (`Engine._draw_pairing`), which opens by itself when a
game starts (or an unpaired controller presses A) while a controller
nobody has is connected, and from the settings menu. Online it's each
device's own menu: it pairs that device's controllers with that device's
players (`Engine.local_players`), nobody else sees it and the game goes on
(a joined device's in `viewer.py`, which tells the host with pads{bind}).
Pairings are by
player name and aren't saved (SDL numbers controllers anew every session);
an unplugged controller plugged back in goes back to its player. A new
decision in phases.py made by someone other than the current player needs
a case in `acting_player`. Headless tools leave `engine.controls` None,
and then `Io.update` is called the old way (`bot_selfplay.py` stubs it with
that signature).

## Working with the user

- **Previews:** when the user asks to *see* how something would look, render
  it without touching the project: put a script in the scratchpad that
  monkeypatches the relevant drawing code, render headlessly, and send the
  image. Only change the real code when they say "implement". When they say
  to only preview for a while, keep doing that until told otherwise.
- **Headless rendering / testing:** run with `SDL_VIDEODRIVER=dummy`, build
  `Engine(mode="default")`, set up a demo board (give countries to players,
  add tanks/ships/planes/forts/airports), call `app.io_handle();
  app.draw_world(); app.present()` twice (second frame = smooth map), then
  `pg.image.save(pg.display.get_surface(), ...)`. For scratchpad scripts,
  run from the project root with `PYTHONPATH=.`.
- Verify logic changes with small headless scripts (stub out menus/events as
  needed); say clearly when something was only compiled or rendered, not
  played in the real window.
- Since 11 Oct 2026 this folder is a git working copy of
  `github.com/HugoNootebos/oil_board` (branch `Master`, which players' Update
  button installs). History only covers what has been committed, so still be
  careful with destructive edits. Commit or push only when the user asks:
  a push to Master is a release to every player.
- **Version numbers in commits:** every update committed for GitHub gets the
  next version: the previous one plus 0.1 (4.3 → 4.4 … 4.9 → 5.0); a bigger
  jump only when the user asks for it. Find the previous one with
  `git log --format=%s | grep -m1 "^Update [0-9]"`. The subject is
  `Update <version>: <name>`, the name being the user's name for the update
  (e.g. `Update 4.4: no audio fix`); the body lists the major changes, one
  `- ` bullet each, in plain words. The subject is what players see: the
  updater shows it on the Update button and as "Version:" in the main menu
  (`updater.UpdateState.check`, `.version`'s "title"). Up to 4.3 subjects
  were just `Update 4.3`; the commits after it (online play, "no audio fix")
  had no number, so the first numbered one after them is 4.4.

## Online play

Online Game › Host / Join (`lobby.py`). The host's computer plays the game
exactly as a local one (`runner.play`); a device that joined keeps a copy
of the game that it only draws, never plays (`viewer.py`: `Viewer.game`,
an `Engine` with `mirror` set), from the state the host sends it, and sends
its input back. So the rules run in one place, whatever works locally works
online, and a joined device's game version only has to have the same
`net.PROTOCOL` (and draw the same state). (Running the game on every device
in lockstep was rejected: bots iterate over sets of names, whose order
differs per process and Python version, and timers use `pg.time.get_ticks()`.)

- **Relays** (`relay.py`): everyone connects out to one; it lists the rooms
  and passes messages between a room's host and its members without reading
  them. The main relay runs on a computer at home
  (`packaging/relay/README.md`) at `net.DEFAULT_SERVER` (overridden by
  `OIL_SERVER` or `"online_server"` in settings.json). A host that can't
  reach it runs a LAN relay inside its own game. Relays announce themselves
  by UDP broadcast (port 47801); one found several ways (its id) is used the
  nearest way: this computer, the LAN, the internet.
- **Seats** (`online.Seat`, kept by the host): "host" (this computer),
  "bot", "remote" (a joined device) or "open". A device that drops out
  leaves its seats open (the host's mouse plays them) and gets them back
  when it joins again with the same `net.device_id()` (settings.json).
  Anyone can join a running game to take a free seat, or to watch.
- **Who clicks:** a joined device's mouse and controllers are
  `online.RemotePointer`s, which `Controls.frame` takes like controllers:
  they click when `acting_player()` is one of their players (on a bot's
  turn: everyone's), and then the host's own mouse doesn't
  (`Controls.mouse_ok`, `HostSession.mouse_allowed`) -- except for a device
  that dropped out, and once the game is won. Online the game-over Quit
  takes the host back to the menu. Every device pans and zooms its own map,
  so a pointer points at the map through its device's view
  (`RemotePointer.view` = `Member.view`, sent with every input message as
  `view: [zoom, x, y]`; `Io.update` uses a source's `view`); the host never
  pans or zooms for a joined pointer (`Engine._remote_pointer`), and a
  device sends no wheel, stick panning, LB/RB or Start.
- **The state** (`HostSession._sync_state`, from `pump`, at most every
  `STATE_MS`): `HostSession.game_state()` is `save_load.game_data` (as a
  save, without the log and the host's display settings) plus `online`:
  the players' `subattack`, the countries highlighted (`shade`: what the
  acting player picked), the acting player, whether a dialog is up, the
  pagoda/torii owed, the host's language and Fast bots. A device coming in
  gets all of it (`state{full, set}`, ~24 KB), then only what changed
  (`state{set, countries}`: changed top-level parts, changed countries; a
  conquest is a few hundred bytes). The device puts it on its copy with
  `save_load.apply_data(..., mirror=True)` (keeps its Player objects, its
  log, and makes its connections exactly the host's) and its own deep copies
  of the events (an event keeps state on itself). The action log goes on
  its own (`_sync_log`: the last `LOG_LINES` lines on coming in or when the
  log was replaced, then the new lines; `lang.Msg` as JSON, so it's
  translated on the device). New state that a device must draw goes into
  `game_data` (and so into saves) or `game_state`'s `online`.
- **The game's layer** (`online.OverlayStream`): everything the game draws
  over the map, `Engine.ui` in the logical 960x640 -- the HUD, dice,
  popups, dialogs, the event card coming up, the pagoda/torii notice --
  taken in `Engine.present` before the host's own action log is drawn on it
  (at most 20 a second), compared in 80 px tiles, and sent as PNG pieces
  with alpha (see-through where the map shows; ~40 KB the first time, then
  only what changed, at most 2 updates unacknowledged per device). A device
  lays it over its own map unchanged (`apply_update` replaces pixels), so it
  is as sharp as on the host, and panning sends nothing at all. Whatever
  the game draws must stay in screen coordinates (the map is each device's
  own): something tied to a country goes through the state instead (like
  `shade`).
- **A device's own** (`viewer.py`): over its map and the game's layer it
  draws, from its copy, the HUD buttons, the info panel of the country under
  its pointer (not through the game's layer: `Viewer._hovered` looks at its
  alpha), the action log (opened and scrolled on its own) and its own menus
  (`Engine._own_menu` with `Engine.mirror` standing in for the session:
  settings, the event card, a look at the shop, the cards of its player
  whose turn comes soonest, the Controllers panel for its own controllers
  and players, `Viewer.local_players`; it opens by itself as for the host).
  Its settings can't exit, save or change Fast bots, but what its map shows
  is its own. A click for
  any of that (`Viewer._local_at`) stays on the device; other clicks go to
  the host, and while a menu of its own is open none do (`menu: true` with
  its input: `Member.menu_open`, `HostSession.menu_blocks`). The pagoda/
  torii is dragged onto its own map and placed by the host
  (`landmark{name, on}`, only for the current player's device,
  `HostSession._landmark`). On its player's turn the shop and cards are the
  game's: the host draws them on that device's layer
  (`Engine.private_layer`) and sends it as a PNG (`menu{rect, png, dim}`,
  `HostSession.show_menus`, at most every `HOVER_MS`). It shows the game in
  the host's language (`lang.language`, put back when it leaves).
- **The host's own menus** (`Engine.own_menus`, online only): the host opens
  the settings, shop look, cards look, event card and Controllers panel
  (its own controllers and players) for itself at any
  time on its own screen (`online.Device` 0, `Engine.device_context`), the
  game going on meanwhile (online `modal_open` leaves them out); its own
  shop and cards on its turn are the game's, on its layer only.
- **Cursors** (at most 30 a second) and sounds (`sounds.listener`) go as
  messages; each device draws the others' cursors itself. A cursor is
  `[x, y, r, g, b, faded, member, number, map x, map y]`: over the map it's
  drawn at the same map point in each device's own view, over the game's
  layer at the same place on the screen (`online.cursor_spot`, also for the
  devices' cursors on the host).
- **The idle loop:** network threads post `online.NET_EVENT` to wake
  `pg.event.wait()`; a device's input draws `SETTLE_FRAMES`, its "got it"
  just one frame (which sends what's next). A device's loop draws only
  after an event, a message or a tilted stick (`Viewer.frame`).
- **The chat** (`chat.py`, online only: a local game has none): a button
  under the settings button (`images/chat.png`, a red badge counts unread
  messages) opens a panel to its right; while it's open every key is the
  chat's (Enter sends, Esc closes). It's each device's own, drawn outside
  the game's layer: the host's in `Engine.present` after `online.capture`
  (`HostSession.draw_chat`), a device's over its own screen
  (`viewer.py`). Its clicks and keys never reach the game: on the host
  `runner.play` hands it the events first and `Engine.io_handle` puts its
  shapes on top of the Io buttons (for the host's mouse only); a device
  doesn't send them (`Viewer._events`, `_swallowed`). The host stamps who
  said what (`HostSession.say`: the device's players' names, "Spectator"
  without one) and sends it to every device in the game; a device coming in
  gets the history (`old`, not counted as unread). Not saved; mouse and
  keyboard only. The host's own chat click isn't sent as a sound
  (`sounds.play(..., shared=False)`).
- **The host's country info panel** (top right) is its own too, online: the
  country its own pointer is over, left out of the game's layer
  (`draw_gui` skips it when `app.online`; a local game is unchanged).
  `HostSession.show_hovers` (from `Engine.present`, after `online.capture`)
  picks, of this computer's used pointers over a country
  (`device_country_at`: not through the buttons on screen, the chat, the
  shop menu or a dialog), the one whose player decides soonest
  (`_turn_rank`: the acting player, then by turns to go; no player last),
  between equals the one used last.
- Raise `net.PROTOCOL` whenever the messages between a host and its devices
  change, and `relay.RELAY_PROTOCOL` when the relay's do (then the home relay
  needs `packaging/relay/install.sh` again).

## Bots

A player with `is_bot` (set per player on the player-names screen, where
the button toggles Human ↔ Bot; saved)
is played by `bot.py`. On their turn `TurnManager.update` calls
`BotController.update` instead of the normal phase handling: the phase
still draws itself but gets no clicks, and the bot makes one decision per
step (`STEP_MS`/`DICE_MS` pauses, shortened by the settings menu's "Fast
bots"; `bot.fast = True` for headless games), calling the same methods the
buttons use (`AttackPhase.roll_attack`, `ShopPhase.place_unit/place_fort/
build_rails/build_bridge/drop_nuke`, `MovementPhase.develop`,
`Phase._enter_redistribute`, `EventTargetPhase.pick`,
`TurnManager.end_phase`). Its status line (`_draw_status`) is no longer drawn. Messages on a bot's turn close by themselves after
`NOTICE_MS`. A bot attacking a human waits for the human's defence
tanks/dice; a bot being attacked decides those itself
(`BotController.defence_tanks`, via `TurnManager.bot`), as it does an event's pick for it on
someone else's turn (`pick_country`). The shop and card buttons are
disabled during a bot's turn.

How it decides: everything is valued in troops. `_weights` prices each
resource by need (food fully while the army is at what food can carry;
oil hardly once there's a stock), `_target_value`/`_hold_value` price
countries, `battle` gives exact odds, survivors and kills, `_attack_ev` an
attack's expected value with a conquest of lookahead, `_danger` the chance
a neighbour takes a country before the bot's next turn, and
`_position_value` combines those per country. `_danger` is `_exposure`
(tunable `exposure`; 0 gives the old adjacent-stacks model): it also sees
chains (an enemy takes a mouse/other country on the way and strikes from
it: half of all losses), a crossing over water the enemy can still buy at
its next turn (a ship, bridge or plane) and enemies that haven't moved yet.
`_target_value` then counts a conquest only while it is kept
(`_retained_value`, tunable `retention`): bots used to lose 40% of what they
conquered before their next turn, and take islands and pockets (lost 4% a
round, against 25% for land-linked countries) now by themselves. Eliminations are judged
both ways: `_hunt` goes for a player when the chance of taking all their
countries this turn (`_campaign`) times the prize (their loot, one rival
less) beats the troops it costs and the danger it leaves the bot in; and
`_elimination_risk` is the chance another player wipes the bot out before
its next turn -- above `survival_risk` it plays safe (its countries count
for more, attacks count what they do to that risk, card sets go for
troops, resources get spent rather than left as loot, no developing).
Before trading, placing and buying, the strike step (`_strike_step`,
tunable `strike`) asks for each player it could finish off what its stock
buys -- nukes, a card set, a ship/plane/bridge, the new troops massed on one
stack -- and does it if `_hunt_worth` says so; `_finish_step` fires the
nukes of a sure elimination (floor(log2 troops) + 1 per country). Saving
resources up for a strike doesn't pay (measured), so there are no reserves.
Deployment, moving in, the
one move a turn, rail/air redistribution, starvation, card trades
(`_trade_reward`) and the shop (`_shop_options`: value over the turns an
item lasts minus its price) all compare position values. Hitting whoever leads is
worth a bit extra (`leader_bias`), so bots don't just pile onto the
weakest player. There is one bot level (the easy and normal ones were
removed): its tunables live in `BASE` (`LEVELS["hard"]`; the tuning tools add
tweaked copies to `LEVELS` and point a player's `bot_level` at one) and
`PERSONALITIES` (one at random per bot: balanced/aggressive/builder/turtle).
`noise` (random slips, `_jitter`) is 0 and only there for noise-matched A/B
controls. Two tunables ship off: `extra_exposure` (price the conquests after
the turn's card; only pays when every bot does it), `buffer` (empty a thin
exposed country into the mouse's hands, `_buffer_run`; measured about worth
nothing under the current rules). The asset care (`asset_hold` 1, `asset_move` 1,
`asset_attack` 1, `asset_carry` 1) ships ON, at the owner's request, although no gain
was measured. The rules destroy the ships, tanks, planes and
forts of a country when it falls and the bots lose two thirds of what they buy
(88% of ships, 83% of planes, 57% of forts, 55% of tanks), which `_hold_value`
never counted. `asset_hold` (x their price in troops, `_asset_price`) counts it
in `_position_value`, so deployment, the shop and the move of the turn guard
them; `asset_move` lets `_reposition` take tanks alone, a plane or a ship with
one troop to any country of the bot's (not only to a border); `asset_attack`
and `asset_carry` price and trim what an attack carries onto the conquered
country. Measured (`bot_research/README.md`): with `asset_hold=2, asset_move=1`
the losses by conquest fall by a quarter and the share of assets lost between
turns from 10.9% to 6.8%, but 150 pairs show no gain (placement +0.007 +-0.034,
win -4.7 +-9.8 points), and even refunding every lost asset (the oracle) is
worth it only because it makes assets free (the bot then buys 2.3x as many).
`asset_wipe` 1 (`_wipe_check`): before a roll of 1 or 2 dice, which destroys
the assets brought along if every die loses, the bot takes that risk off the
attack's value, leaves the tanks home when the attack is worth more without
them, and calls it off when it no longer pays.
`endgame_*` (`_endgame`) makes the leader
spend its stock once at most 2 players are left or it holds 70% of the
strength: leftover wood/steel/nuclear falls by half; oil and food can't be
spent.
`python3 bot_checks.py` checks them on small boards.

New player decisions in phases.py need a bot counterpart in bot.py.
After changing a bot, A/B test it against the previous version before
keeping it. A "smarter" bot wins more, and by the criterion A/B tests
print: it steals more by eliminating players (loot score: the loser's
resources plus `CARD_LOOT` per card) without being eliminated more often
itself. `old_bot.py` is the frozen baseline (copy bot.py aside before
changing it again; this folder isn't in git), then
`python3 bot_selfplay.py 400 4 --vs old_bot.py --jobs 8`. Count on about
1,400 games an hour on 8 cores, so 400 games take about 17 minutes and only
tell sides apart that differ by ~7 points of win rate (±5%): judge a change
by the KPI it should move first (`bot_report.py`) and only confirm with win
rate. An A/B of a change that merely perturbs a few choices still moves the
placement a little; compare against a noise-matched control
(`--tweakA noise=0.02 --tweakB noise=0.02`), not against zero. Games are
reproducible, so two identical bots play identical pairs.
Anything that should leave play unchanged must keep `python3 bot_golden.py`
green (the new tunables off: `--tweak exposure=0 --tweak retention=0 --tweak
strike=0 --tweak finish_max=0 --tweak endgame_alive=0 --tweak endgame_lead=1.1
--tweak asset_hold=0 --tweak asset_move=0 --tweak asset_attack=0 --tweak asset_carry=0
--tweak asset_wipe=0`
reproduces the traces of `old_bot.py`) -- except for 5 of the 12 games
since Update 4.10: `old_bot.py` doesn't know the rules its events brought
(immigrants who must stay put, `Country.free`/`keep`; the "give back"
move), and the decisions it has no method for (`share_oil`, `bid_for`,
`keep_development`, `turn_order`) are made by today's bot with its
tunables on (bot_selfplay's fallback). So for a change that should leave
play unchanged, `--golden golden_traces_new.json` (12 of 12) is the check;
the 7 games that still match are the old-bot check.
