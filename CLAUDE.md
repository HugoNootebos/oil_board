# OIL board game

A Risk-like strategy board game in Python + pygame-ce: 3–6 players conquer
countries on a world map, collect resources (food, wood, steel, oil,
nuclear, troops), build in a shop, trade cards ("kaertskes") and deal with
random world events. Country names, event names and event texts are Dutch
(e.g. "Sovjet-Rusland", "Nazi-Duitsland", "Belgisch Congo"); most UI
messages are English. The neutral player is called **mouse**
(`engine.default_player`).

The user writes in English and Dutch; answer in the language they use.

## Running

```bash
python3 runner.py
```

Requirements: `pygame-ce>=2.5`, `numpy==1.19.3`, `matplotlib~=3.3.3`
(Python 3.9). There are no automated tests.

## Files

| File | What's in it |
|---|---|
| `runner.py` | Entry point: start menus → `play(app)` loop. "Exit Game" returns to the start menu; closing the window quits. F5/F9 quicksave/quickload (autosave file), Esc toggles fullscreen. |
| `menu.py` | Start menu, new-game menu, player-name entry, Continue/load screen (autosave + 4 named slots). Each is its own small pygame loop. |
| `engine.py` | `Engine`: window/view, cached map layer rendering, troop markers, HUD buttons, settings menu (Exit Game, Save As, display toggles), fonts/images, player setup. |
| `phases.py` | All game rules as a state machine: `Phase` base class, one class per phase, and `TurnManager` (turn order, events schedule, eliminations, notices/dialogs). ~2,400 lines. |
| `models.py` | `Player`, `Country` (drawing incl. troop markers + fort badges), `Connection` (routes, dotted sea routes, waypoint curves), `Dice`, `Io` (mouse input + hover/hit tests), `View`, `Gui` (side panels), `CardMenu`, `Kaertske`, `Button`. |
| `board.py` | The map: `CONTINENTS`, `get_countries(default_player)` (resources/start units per country), `get_connections()` (land/sea links). |
| `events.py` | World events: `Event` base class with hooks, one subclass per event, `EVENTS` list (23). |
| `bot.py` | Computer player: `BotController` (plays a bot's turn step by step, values everything in troops), exact combat odds (`battle`), difficulty `LEVELS` and `PERSONALITIES`. |
| `bot_selfplay.py` | Headless bot-vs-bot games and A/B tests for tuning bots: `python3 bot_selfplay.py [games] [players] [--vs FILE / --levels a,b / --tweak k=v / --personality p] [--jobs N]`. |
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
  can't outgrow its food income for long. A player who starves while
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
  antialiased edges. Borders: grey 80%. Connections: 60%.
- Map style: sea routes are evenly spaced dots (`Connection.DOT_STEP`), land
  routes solid green with black outline; curved routes via
  `Connection.WAYPOINTS`. Troop markers: light tint of owner colour, white
  edge, black number; square for airport countries; white lines for assets
  (ship "/", tank "—", plane "\"); forts as white badges with 2/4/8
  battlements (rounded bottom under circles, square under squares).
- Mouse's colour is (140, 140, 140).

## Saves

Saves store state by **name** (players, countries, events), so they survive
code changes; unknown names are dropped rather than failing. New mutable
state on players/countries/connections/TurnManager must be added to both
`save_game` and `load_game` (use `.get(key, default)` when loading so old
saves still work). A save always resumes at `subattack = 0` of its phase.
Players' `is_bot`, `bot_level` and `bot_personality` are saved.

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
the button cycles Human → Bot (normal) → Bot (hard) → Bot (easy); saved)
is played by `bot.py`. On their turn `TurnManager.update` calls
`BotController.update` instead of the normal phase handling: the phase
still draws itself but gets no clicks, and the bot makes one decision per
step (`STEP_MS`/`DICE_MS` pauses, shortened by the settings menu's "Fast
bots"; `bot.fast = True` for headless games), calling the same methods the
buttons use (`AttackPhase.roll_attack`, `ShopPhase.place_unit/place_fort/
build_rails/build_bridge/drop_nuke`, `MovementPhase.develop`,
`Phase._enter_redistribute`, `EventTargetPhase.pick`,
`TurnManager.end_phase`). A status line at the bottom of the screen says
what it's doing. Messages on a bot's turn close by themselves after
`NOTICE_MS`. A bot attacking a human waits for the human's defence
tanks/dice; a bot being attacked decides those itself
(`BotController.defence_tanks`), as it does an event's pick for it on
someone else's turn (`pick_country`). The shop and card buttons are
disabled during a bot's turn.

How it decides: everything is valued in troops. `_weights` prices each
resource by need (food fully while the army is at what food can carry;
oil hardly once there's a stock), `_target_value`/`_hold_value` price
countries, `battle` gives exact odds, survivors and kills, `_attack_ev` an
attack's expected value with a conquest of lookahead, `_danger` the chance
a neighbour takes a country before the bot's next turn, and
`_position_value` combines those per country. Deployment, moving in, the
one move a turn, rail/air redistribution, starvation, card trades
(`_trade_reward`) and the shop (`_shop_options`: value over the turns an
item lasts minus its price) all compare position values. Hitting whoever leads is
worth a bit extra (`leader_bias`), so bots don't just pile onto the
weakest player. Tunables live in
`BASE`/`LEVELS` (easy/normal/hard; lower levels add `noise`) and
`PERSONALITIES` (one at random per bot: balanced/aggressive/builder/turtle).

New player decisions in phases.py need a bot counterpart in bot.py.
After changing a bot, A/B test it against the previous version before
keeping it, e.g. `git show HEAD:bot.py > /tmp/old_bot.py; python3
bot_selfplay.py 400 4 --vs /tmp/old_bot.py --jobs 4` (±5% at 400 games,
about 10 minutes on 4 cores).
