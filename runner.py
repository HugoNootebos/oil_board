import os

# Images and saves/ are looked up from the working directory: start in the
# game's folder however it was launched (a shortcut, an IDE, another folder).
# Before the imports: lang reads saves/settings.json when it's imported.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from engine import Engine
from menu import (run_main_menu, run_local_menu, run_online_menu, run_new_game_menu,
                  run_player_names_menu, run_load_menu)
from save_load import save_game, load_game, migrate_legacy_save
import pygame as pg
import controls
import lobby
import online
import sounds
import tutorial

# Nothing in the game changes on its own -- only in response to input --
# so a frame is only drawn when some event arrives (the mouse moving or
# clicking, a key, the window being uncovered/resized...). A few frames
# keep being drawn after the last one: state a click changes is only
# drawn the frame after, and the smooth map replaces the fast one drawn
# while panning/zooming once the view has settled.
SETTLE_FRAMES = 5


def choose_game():
    """The start menus: returns a new or loaded game (an Engine). Back goes
    one menu up."""
    while True:
        choice = run_main_menu()
        if choice == "tutorial":
            return tutorial.new_game()
        if choice == "online":
            app = choose_online()
            if app is not None:
                return app
            continue
        while True:
            choice = run_local_menu()
            if choice is None:
                break  # Back: show the main menu again
            if choice == "new":
                return new_game()
            load_path = run_load_menu()
            if load_path is not None:
                # Continue loads onto a freshly built default-mode game, since
                # load_game expects an already-constructed engine to apply onto.
                app = Engine(mode="default")
                load_game(load_path, app, app.turn_manager)
                return app
            # otherwise Back: show the local game menu again


def choose_online():
    """Online Game: Host returns the hosted game (an Engine with its
    online.HostSession) once it starts; a joined game is played right
    there (lobby.join_game). None for Back."""
    while True:
        choice = run_online_menu()
        if choice is None:
            return None
        if choice == "host":
            app = lobby.host_game()
            if app is not None:
                return app
        else:
            lobby.join_game()


def new_game():
    """"de Neven" is the named default trio; a number is a plain game with
    that many players, named on the screen that follows."""
    new_game_choice = run_new_game_menu()
    if new_game_choice == "default":
        return Engine(mode="default")
    player_names = run_player_names_menu(new_game_choice)
    # The first autosave happens once the first player ends their turn
    # (see TurnManager.next_turn); autosaves go to Engine.save_path.
    player_names, player_bots = player_names
    return Engine(mode="count", player_count=new_game_choice, player_names=player_names,
                  player_bots=player_bots)


def play(app):
    """Runs the game until it's left. Returns "menu" for Exit Game (back to
    the start menu) or "quit" when the window is closed. An online game
    (app.online, see online.py) ends for the devices that joined it too."""
    try:
        return _play(app)
    finally:
        if app.online is not None:
            app.online.close("ended")


def _play(app):
    clock = pg.time.Clock()
    frames_left = SETTLE_FRAMES

    sounds.start_background()
    app._owner_snapshot = None
    pads = controls.get()
    app.controls = pads
    if pads.needs_pairing(app.local_players()):
        app.open_pairing()  # e.g. a loaded game: who has which controller?
    while True:
        if frames_left == 0:
            # Idle: sleep until the next event instead of redrawing. In an
            # online game a device's input or its "got it" wakes it too
            # (online.NET_EVENT).
            event = pg.event.wait()
            events = ([event] if event.type != pg.NOEVENT else []) + pg.event.get()
        else:
            events = pg.event.get()
        pads.handle_events(events)
        session = app.online
        remote_input = session.update() if session is not None else False
        # A bot plays on without any input, and a tilted stick moves its
        # cursor without sending events. Only a device's "got it" draws just
        # the one frame (that sends it what's next).
        if any(e.type != online.NET_EVENT for e in events) or remote_input or pads.busy \
                or (app.bot_turn and not app.turn_manager.game_over):
            frames_left = SETTLE_FRAMES

        if session is not None and session.state == "game" and not app.typing_save_name:
            # Online: this computer's chat (chat.py) takes its clicks, and
            # every key while it's open, before the game sees them.
            view = app.view
            events = [e for e in events if not session.chat.handle(
                e, lambda pos: ((pos[0] - view.ox) / view.scale, (pos[1] - view.oy) / view.scale))]

        wheel = []  # +1 per wheel-up notch, -1 per wheel-down
        mouse_clicked = False
        # While a save name is being typed, keys belong to the name box (Escape
        # there backs out of it rather than toggling fullscreen).
        typing = app.typing_save_name
        app.handle_events(events)
        for event in events:
            if event.type == pg.QUIT:
                return "quit"
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                mouse_clicked = True
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 5:
                wheel.append(-1)
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 4:
                wheel.append(1)
            if typing:
                continue
            if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
                app.toggle_fullscreen()
            # Quicksave / quickload, using the autosave file (the tutorial's
            # own, in the tutorial).
            if event.type == pg.KEYDOWN and event.key == pg.K_F5:
                save_game(app, app.turn_manager, app.save_path)
            if event.type == pg.KEYDOWN and event.key == pg.K_F9:
                load_game(app.save_path, app, app.turn_manager)

        frames_left = max(0, frames_left - 1)
        if app.tutorial is not None and app.tutorial.active:
            frames_left = max(frames_left, 1)  # its rings pulse: no idling
        app.io_handle()
        if app.tutorial is not None:
            app.tutorial.handle_input()  # its panel's clicks, and those its step holds back
        if not pads.mouse_ok:
            # Online, while a player on another device decides: the mouse
            # here neither clicks nor zooms.
            mouse_clicked, wheel = False, []
        if mouse_clicked:
            sounds.click_pressed()
        # The controllers that may click this frame (see controls.py): a click
        # sound, Start for the settings menu, LB/RB for zooming.
        if any(pad.tapped(controls.A) for pad in pads.clickers):
            sounds.click_pressed()
        if any(pad.tapped(controls.START) for pad in pads.clickers) and not app.turn_manager.dialog_active \
                and app.online is None:
            app.toggle_settings()  # (online every device's Start opens its own: Engine.own_menus)
        wheel += [step for pad in pads.clickers for step in pad.zoom_steps]
        app.bystander_clicks()  # the other players' controllers (online: mice too) say a country's name
        if not app.modal_open and pads.needs_pairing(app.local_players()) and any(
                pad.tapped(controls.A) and pads.player_of(pad, app.local_players()) is None for pad in pads.pads):
            app.open_pairing()  # a controller nobody has yet wants in
        zoom = 1.0
        for step in wheel:
            # An open action log keeps the wheel for scrolling itself.
            if not app.scroll_action_log(step):
                zoom *= 1.1 ** step
        if zoom != 1.0:
            # After io_handle, so it zooms around where the mouse is now.
            app.view.zoom_at(app.io.mouse_position, zoom)
        click_state = sounds.frame_start(app)
        app.draw_world()
        app.draw_gui()
        app.update_turn()
        app.control_card_menu()
        sounds.frame_end(app, click_state)
        sounds.watch_owners(app)
        if app.pending_quit:
            return "menu"

        if app.tutorial is not None:
            app.tutorial.draw()
        app.present()
        pg.display.flip()
        if app.online is not None:
            app.online.pump()
            if app.online.busy:
                frames_left = max(frames_left, 1)  # a picture or cursors still owed to the devices
        clock.tick(60)


migrate_legacy_save()
while play(choose_game()) == "menu":
    pass  # Exit Game: back to the start menu for a new or saved game
pg.quit()
