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

Requirements: `pygame-ce>=2.5`, `numpy>=1.19.3`, `matplotlib>=3.3.3`
(this Mac: Python 3.9 with numpy 1.19.3; the game also runs on a current
Python with numpy 2). The only automated checks are `event_checks.py` (events),
`bot_checks.py` (bot decisions on small boards), `bot_selfplay.py` (bots
against each other) and `bot_golden.py` (did a change leave the bots' play
exactly as it was).

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
the Python 3.9 that made them. numpy 2 is fine.

## Files

| File | What's in it |
|---|---|
| `runner.py` | Entry point: start menus → `play(app)` loop. "Exit Game" returns to the start menu; closing the window quits. F5/F9 quicksave/quickload (autosave file), Esc toggles fullscreen. |
| `menu.py` | Start menu (with the language flag), new-game menu, player-name entry (with controller pairing), Continue/load screen (autosave + 4 named slots). Each is its own small pygame loop. |
| `controls.py` | Game controllers, one per player, each with its own cursor (`Pad`). `Controls` (one, `controls.get()`) reads them, pairs them with players, decides which may click (`frame`) and draws the cursors. See Game controllers below. |
| `lang.py` | Dutch/English: `t(text)`, `Msg`/`Join` (log text translated when drawn), the current `language`, `set_language` (saved in `saves/settings.json`), the `NL` (English source → Dutch) and `EN` (Dutch source → English) tables. |
| `engine.py` | `Engine`: window/view, cached map layer rendering, troop markers, HUD buttons, settings menu (Exit Game, Save As, display toggles), fonts/images, player setup. |
| `phases.py` | All game rules as a state machine: `Phase` base class, one class per phase, and `TurnManager` (turn order, events schedule, eliminations, notices/dialogs). ~2,400 lines. |
| `models.py` | `Player`, `Country` (drawing incl. troop markers + fort badges), `Connection` (routes, dotted sea routes, waypoint curves), `Dice`, `Io` (mouse input + hover/hit tests), `View`, `Gui` (side panels), `CardMenu`, `Kaertske`, `Button`. |
| `board.py` | The map: `CONTINENTS`, `get_countries(default_player)` (resources/start units per country), `get_connections()` (land/sea links). |
| `events.py` | World events: `Event` base class with hooks, one subclass per event, `EVENTS` list (23). |
| `bot.py` | Computer player: `BotController` (plays a bot's turn step by step, values everything in troops), exact combat odds (`battle`), difficulty `LEVELS` and `PERSONALITIES`. |
| `bot_selfplay.py` | Headless bot-vs-bot games and A/B tests for tuning bots: `python3 bot_selfplay.py [games] [players] [--vs FILE / --botA FILE / --tweakA k=v / --tweakB k=v / --personality p] [--jobs N] [--maxturns N] [--out FILE]`. Reproducible (same seed, same game); players can be a list (`3,4,5,6`); one JSON line per game (the file is appended to, so a rerun into the same file adds to it); runs `bot_report.py` at the end. `--refund-assets A` is a research oracle (side A gets the price of every ship/tank/plane/fort it loses back). See its docstring. |
| `bot_report.py` | Tables from `bot_selfplay.py` results (`python3 bot_report.py FILE.jsonl`): pair-level A-B contrasts (win, placement, loot legacy and market, eliminations), game length, KPIs per behaviour. |
| `bot_kpi.py` | The KPI recorder behind those tables (first ship, water protection, retention, cards, emptied countries, hoards, spend-down, assets bought/destroyed and why, what the one move a turn moves). Wraps game methods; changes no play. |
| `bot_fork.py` | Forked what-ifs: play a game, fork it at a moment (e.g. the leader's turn once 2 players are left) and let one seat continue with different tunables (`--arm NAME:KEY=VALUE,...`), same board and dice for every arm. Resolves a behaviour that matters within a few turns (a strike, the endgame) with a few hundred forks, where whole games need thousands. `python3 bot_fork.py OUT.jsonl 4 SEED GAMES --stage 2:0,2 --min-share 0.5 --arm off:endgame_alive=0 --arm on:` then `--report OUT.jsonl`; run several in parallel. |
| `bot_checks.py` | Headless PASS/FAIL checks of bot decisions on small boards (exposure, retention, strike step, finisher): `python3 bot_checks.py [filter]`. Add a check there when adding a bot behaviour. |
| `bot_golden.py`, `golden_traces.json`, `golden_traces_new.json` | Golden traces: 12 whole games boiled down to an md5 per game. `python3 bot_golden.py` says whether the bots still play exactly like the traces in `golden_traces.json` (those of `old_bot.py`, before the retraining; only matches with the new tunables off, see below); `python3 bot_golden.py --golden golden_traces_new.json` compares with the bot as it was left after the retraining (rewrite it with `--update` when play is changed on purpose); `--bot FILE`, `--tweak k=v` to vary. |
| `old_bot.py` | Frozen copy of bot.py from 2 Oct 2026, before the retraining: the baseline every A/B test and the golden traces compare against. |
| `bot_research/` | Reports and prototype scripts of the research behind the bot retraining (reports in `bot_research/reports/`; `backup_before_wp0/` holds the files as they were before it started; `compare_assets.py` puts several A/B result files side by side). Not used by the game. |
| `event_sandbox.py` | Interactive test board for events: `python3 event_sandbox.py`. Fixed 4-player board, events only when picked (F2), shows what each start/end changed; keys for editing the board (see its docstring / F1). Saves go to temp files. |
| `event_checks.py` | Headless PASS/FAIL checks per event through the real game code: `python3 event_checks.py [filter]`. Add a test there when adding an event. |
| `save_load.py` | JSON save/load, save paths (`saves/autosave.json`, `saves/slot1-4.json`), legacy `savegame.json` migration. |
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
| 1 | `AttackPhase` | 0/1 pick attacker/target · 2 choose attack dice · 3 defender rolls · 4 resolve combat · 5 move troops in after a conquest · 6 asset panel (ships/tanks/planes) · 7 rail redistribution |
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
  `discount_shop_cost`, `on_turn_start`, ...) rather than special-casing
  events in phases.py (or bot.py: bots see an event through those hooks,
  plus the `bot_*` hints for what they can't work out from them).

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
owner of a country the mouse attacks); the other cursors are drawn faded.
On a bot's turn every paired controller clicks. The mouse always works.
In the start menus every controller clicks (`menu._input`).
Pairing: the controller buttons on the player-names screen, or the
Controllers panel (`Engine._draw_pairing`), which opens by itself when a
game starts (or an unpaired controller presses A) while a controller
nobody has is connected, and from the settings menu. Pairings are by
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
- The project folder is not tracked in git (the repo root is the parent
  folder), so there's no history to fall back on — be careful with
  destructive edits.

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
--tweak asset_hold=0 --tweak asset_move=0 --tweak asset_attack=0 --tweak asset_carry=0`
reproduces the traces of `old_bot.py`).
