# Graph Report - oil_board-Master  (2026-11-06)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2339 nodes · 5517 edges · 121 communities (39 shown, 82 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 230 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4408c96c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- t
- Viewer
- Event
- AttackPhase
- .player
- phases.py
- Tutorial
- net.py
- bot_selfplay.py
- ._cached
- .engine
- CardMenu
- relay.py
- Controls
- tutorial.py
- .player
- Chat
- event_checks.py
- .io
- OilSharePhase
- BotController
- .__init__
- events.py
- ._links
- ._install
- Sandbox
- sounds.py
- Phase
- updater.py
- ._weights
- with
- ._draw_settings_menu
- RoomBrowser
- online.py
- bot_checks.py
- _linked
- ._resolve_combat
- .engine
- ._say
- Msg
- build.py
- bot_fork.py
- Engine
- .update_turn
- Country
- Position
- play
- ._install
- online_checks.py
- MarchedThrough
- Gui
- HostSession
- ._position_value
- EvilSpirits
- os
- bot_report.py
- .draw_gui
- math
- Io
- bootstrap.py
- UpdateState
- Pad
- Ebola
- WrongButton
- .draw_cursors
- EventTargetPhase
- ._changed
- TurnManager
- GasInRoubles
- GreenlandNotForSale
- IsraelVictim
- test_state
- test_chat
- ._punish_landmark
- Woke
- Kaertske
- DiceSmash
- RemotePointer
- .update
- EmperorsHonor
- Pilgrimage
- PirateWheel
- ChildLabor
- JapanGoesCrazy
- NativesFightBack
- Slavery
- Wire
- .close
- ClimateHoax
- .wrap
- DeviceConn
- DevelopmentAid
- StormAtSea
- Button
- HarshWinter
- NuclearWinter
- TrumpWall
- _FakeController
- PutinsWar
- hashlib
- install.sh script
- _least_in

## God Nodes (most connected - your core abstractions)
1. `BotController` - 129 edges
2. `t()` - 119 edges
3. `Engine` - 112 edges
4. `Position` - 76 edges
5. `Phase` - 71 edges
6. `Msg` - 67 edges
7. `Event` - 63 edges
8. `HostSession` - 63 edges
9. `TurnManager` - 55 edges
10. `play()` - 52 edges

## Surprising Connections (you probably didn't know these)
- `compute()` --indirect_call--> `owner()`  [INFERRED]
  bot.py → packaging/build.py
- `compute()` --indirect_call--> `owner()`  [INFERRED]
  bot.py → packaging/build.py
- `compute()` --indirect_call--> `owner()`  [INFERRED]
  bot.py → packaging/build.py
- `Viewer` --uses--> `Engine`  [INFERRED]
  viewer.py → engine.py
- `Engine` --uses--> `Button`  [INFERRED]
  engine.py → models.py

## Import Cycles
- None detected.

## Communities (121 total, 82 thin omitted)

### Community 0 - "t"
Cohesion: 0.07
Nodes (34): game_font(), t(), _draw_pad_button(), _draw_room(), _draw_seat(), host_game(), _layout(), _new_seats() (+26 more)

### Community 1 - "Viewer"
Cohesion: 0.05
Nodes (3): cursor_spot(), _valid_cursor(), Viewer

### Community 6 - "phases.py"
Cohesion: 0.08
Nodes (12): _connection_segments(), find_spot(), _segment_distances(), Image, random_card_type(), Shop, View, draw_cancel_button() (+4 more)

### Community 7 - "Tutorial"
Cohesion: 0.08
Nodes (5): Tutorial, counted(), ours(), rigged_cast(), rigged_roll()

### Community 8 - "net.py"
Cohesion: 0.07
Nodes (12): _join(), connect(), ConnectError, Connection, device_id(), Found, _read_message(), _recv_exactly() (+4 more)

### Community 9 - "bot_selfplay.py"
Cohesion: 0.08
Nodes (17): _init(), end_phase(), main(), _plain(), _play(), _record(), _alarm(), _init_worker() (+9 more)

### Community 10 - "._cached"
Cohesion: 0.08
Nodes (8): bot_params(), compute(), compute(), compute(), compute(), compute(), compute(), value()

### Community 12 - "CardMenu"
Cohesion: 0.09
Nodes (7): CardMenu, Reinforcement, update_use_automatic(), image_button_shape(), _hold(), hold(), _tank_hold()

### Community 13 - "relay.py"
Cohesion: 0.09
Nodes (12): _clean_info(), _Client, _log(), main(), run(), pack(), pack_json(), _read() (+4 more)

### Community 14 - "Controls"
Cohesion: 0.08
Nodes (3): Controls, _Parked, _stick()

### Community 15 - "tutorial.py"
Cohesion: 0.07
Nodes (18): _attack_marks(), marks(), _mine(), _move_marks(), _moved_by(), _moved_in(), new_game(), _picked() (+10 more)

### Community 17 - "Chat"
Cohesion: 0.08
Nodes (6): wrap(), wrapper(), call(), Chat, clean_text(), valid_line()

### Community 18 - "event_checks.py"
Cohesion: 0.12
Nodes (21): activate(), bonus_test(), check(), country(), fight(), finish(), generic(), income() (+13 more)

### Community 20 - "OilSharePhase"
Cohesion: 0.09
Nodes (6): BidPhase, draw_eye_button(), EventChoicePhase, OilSharePhase, RecruitPhase, TurnOrderPhase

### Community 22 - ".__init__"
Cohesion: 0.06
Nodes (9): ChildSoldiers, Covid, Drugs, EndOfHumanity, GoodEconomy, Immigration, Inflation, Looting (+1 more)

### Community 23 - "events.py"
Cohesion: 0.09
Nodes (8): get_connections(), get_countries(), frame(), main(), setup_board(), Connection, Player, stable_hash()

### Community 24 - "._links"
Cohesion: 0.08
Nodes (12): battle(), compute(), compute(), compute(), compute(), compute(), compute(), compute() (+4 more)

### Community 26 - "Sandbox"
Cohesion: 0.14
Nodes (4): diff(), _route_list(), Sandbox, snapshot()

### Community 27 - "sounds.py"
Cohesion: 0.10
Nodes (16): run_online_menu(), choose_game(), choose_online(), new_game(), play(), _play(), click_pressed(), _fingerprint() (+8 more)

### Community 29 - "updater.py"
Cohesion: 0.12
Nodes (19): _build_update(), _copy(), _data_dir(), _game_dir(), _get(), _install_libraries(), installed(), _lines() (+11 more)

### Community 31 - "with"
Cohesion: 0.09
Nodes (29): GH_TOKEN, jobs, linux, mac, release, windows, runs-on, steps (+21 more)

### Community 33 - "RoomBrowser"
Cohesion: 0.10
Nodes (8): join_game(), beacons(), _Beacons, find_main_relay(), parse_address(), RoomBrowser, server_address(), test_discovery()

### Community 34 - "online.py"
Cohesion: 0.09
Nodes (7): cursor_sprite(), get(), open_window(), _start(), apply_update(), _overlay(), run()

### Community 35 - "bot_checks.py"
Cohesion: 0.22
Nodes (21): check(), links(), main(), own(), reset(), _strike_board(), test_asset_wipe(), test_assets() (+13 more)

### Community 36 - "_linked"
Cohesion: 0.17
Nodes (16): _both(), check(), _device_click(), _frame(), _game(), _linked(), _session(), test_clicks() (+8 more)

### Community 40 - "Msg"
Cohesion: 0.12
Nodes (7): Join, _load_language(), Msg, read_settings(), set_language(), write_setting(), read_log_line()

### Community 42 - "build.py"
Cohesion: 0.22
Nodes (11): build_linux(), build_mac(), build_windows(), copy_game(), install_libraries(), make_icns(), run(), runtime() (+3 more)

### Community 43 - "bot_fork.py"
Cohesion: 0.14
Nodes (11): child_done(), Fork, ForkBot, _give_up(), install_counters(), main(), parse_stages(), register_arm() (+3 more)

### Community 48 - "play"
Cohesion: 0.12
Nodes (3): play(), MixedBots, play_game()

### Community 49 - "._install"
Cohesion: 0.14
Nodes (6): Stats, bought(), current(), eliminated(), turn_end(), wrap()

### Community 50 - "online_checks.py"
Cohesion: 0.15
Nodes (6): _area(), _layer(), _same(), test_game(), test_stream(), OverlayStream

### Community 51 - "MarchedThrough"
Cohesion: 0.14
Nodes (3): JapaneseAggression, MarchedThrough, NaziExpansion

### Community 55 - "._position_value"
Cohesion: 0.14
Nodes (3): value(), compute(), gain()

### Community 58 - "os"
Cohesion: 0.17
Nodes (7): _color_to_list(), _country_to_dict(), game_data(), log_line(), migrate_legacy_save(), _NumpyEncoder, _player_to_dict()

### Community 59 - "bot_report.py"
Cohesion: 0.19
Nodes (7): contrast(), mean(), placement(), row(), sd(), seats(), side_metrics()

### Community 61 - "math"
Cohesion: 0.21
Nodes (7): _dedupe(), _junctions(), _key(), smooth_outlines(), _smooth_ring(), tangent(), draw()

### Community 63 - "bootstrap.py"
Cohesion: 0.22
Nodes (8): main(), bundled(), data_dir(), log(), main(), prepare(), put_update_in_place(), roll_back()

### Community 76 - "test_state"
Cohesion: 0.21
Nodes (6): _device_pos(), _Mouse, _spots(), hovered(), drag(), test_state()

### Community 77 - "test_chat"
Cohesion: 0.18
Nodes (5): _event(), FakeConn, _key(), test_chat(), _window_pos()

## Knowledge Gaps
- **82 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BotController` connect `BotController` to `Event`, `bot_checks.py`, `phases.py`, `._say`, `Msg`, `TurnManager`, `._cached`, `.engine`, `.player`, `Chat`, `OilSharePhase`, `._position_value`, `._links`, `._weights`?**
  _High betweenness centrality (0.166) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `BotController` (e.g. with `Event` and `Join`) actually correct?**
  _`BotController` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `t` be split into smaller, more focused modules?**
  _Cohesion score 0.07438596491228071 - nodes in this community are weakly interconnected._
- **Why does `Engine` connect `Engine` to `t`, `Viewer`, `phases.py`, `bot_selfplay.py`, `CardMenu`, `tutorial.py`, `event_checks.py`, `events.py`, `sounds.py`, `._draw_settings_menu`, `online.py`, `bot_checks.py`, `_linked`, `Msg`, `.scroll_action_log`, `bot_fork.py`, `.update_turn`, `Position`, `play`, `online_checks.py`, `Gui`, `._draw_turn_order`, `.draw_gui`, `Io`, `TurnManager`, `Button`, `.handle_events`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Engine` (e.g. with `install_refund()` and `Join`) actually correct?**
  _`Engine` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Should `Viewer` be split into smaller, more focused modules?**
  _Cohesion score 0.05427547363031234 - nodes in this community are weakly interconnected._
- **Why does `Msg` connect `Msg` to `t`, `AttackPhase`, `.player`, `phases.py`, `Tutorial`, `CardMenu`, `tutorial.py`, `.player`, `.io`, `BotController`, `events.py`, `Phase`, `._resolve_combat`, `.engine`, `._say`, `Engine`, `EvilSpirits`, `os`, `Ebola`, `TurnManager`, `.next_turn`, `GasInRoubles`, `GreenlandNotForSale`, `IsraelVictim`, `test_state`, `._punish_landmark`, `Woke`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._