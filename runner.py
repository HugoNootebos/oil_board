from engine import Engine
from menu import run_main_menu, run_new_game_menu, run_player_names_menu, run_load_menu
from save_load import save_game, load_game, migrate_legacy_save, AUTOSAVE_PATH
import pygame as pg

# Nothing in the game changes on its own -- only in response to input --
# so a frame is only drawn when some event arrives (the mouse moving or
# clicking, a key, the window being uncovered/resized...). A few frames
# keep being drawn after the last one: state a click changes is only
# drawn the frame after, and the smooth map replaces the fast one drawn
# while panning/zooming once the view has settled.
SETTLE_FRAMES = 5


def choose_game():
    """The start menus: returns a new or loaded game (an Engine)."""
    load_path = None
    while True:
        choice = run_main_menu()
        if choice == "new":
            break
        load_path = run_load_menu()
        if load_path is not None:
            break  # otherwise Back: show the main menu again

    if choice == "new":
        # "de Neven" is the named default trio; a number is a plain game with
        # that many players, named on the screen that follows.
        new_game_choice = run_new_game_menu()
        if new_game_choice == "default":
            return Engine(mode="default")
        player_names = run_player_names_menu(new_game_choice)
        # The first autosave happens once the first player ends their turn
        # (see TurnManager.next_turn); autosaves always go to AUTOSAVE_PATH.
        player_names, player_bots = player_names
        return Engine(mode="count", player_count=new_game_choice, player_names=player_names,
                      player_bots=player_bots)

    # Continue loads onto a freshly built default-mode game, since
    # load_game expects an already-constructed engine to apply onto.
    app = Engine(mode="default")
    load_game(load_path, app, app.turn_manager)
    return app


def play(app):
    """Runs the game until it's left. Returns "menu" for Exit Game (back to
    the start menu) or "quit" when the window is closed."""
    clock = pg.time.Clock()
    frame_count = 0
    frame_time_total = 0.0
    frames_left = SETTLE_FRAMES

    while True:
        if frames_left == 0:
            # Idle: sleep until the next event instead of redrawing.
            events = [pg.event.wait()] + pg.event.get()
        else:
            events = pg.event.get()
        if events or (app.bot_turn and not app.turn_manager.game_over):
            frames_left = SETTLE_FRAMES  # a bot plays on without any input

        zoom = 1.0
        # While a save name is being typed, keys belong to the name box (Escape
        # there backs out of it rather than toggling fullscreen).
        typing = app.typing_save_name
        app.handle_events(events)
        for event in events:
            if event.type == pg.QUIT:
                return "quit"
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 5:
                zoom /= 1.1
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 4:
                zoom *= 1.1
            if typing:
                continue
            if event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE:
                app.toggle_fullscreen()
            # Quicksave / quickload, using the autosave file.
            if event.type == pg.KEYDOWN and event.key == pg.K_F5:
                save_game(app, app.turn_manager, AUTOSAVE_PATH)
            if event.type == pg.KEYDOWN and event.key == pg.K_F9:
                load_game(AUTOSAVE_PATH, app, app.turn_manager)

        frames_left -= 1
        frame_start = pg.time.get_ticks()
        app.io_handle()
        if zoom != 1.0:
            # After io_handle, so it zooms around where the mouse is now.
            app.view.zoom_at(app.io.mouse_position, zoom)
        app.draw_world()
        app.draw_gui()
        app.update_turn()
        app.control_card_menu()
        if app.pending_quit:
            return "menu"

        app.present()
        pg.display.flip()

        # Frame time = work + flip, measured before tick() adds the sleep, so
        # it shows how much of the 16.7 ms budget (60 fps) a frame really uses.
        frame_time_total += pg.time.get_ticks() - frame_start
        frame_count += 1
        if frame_count == 60:
            print("avg frame time: {:.1f} ms".format(frame_time_total / frame_count))
            frame_count = 0
            frame_time_total = 0.0
        clock.tick(60)


migrate_legacy_save()
while play(choose_game()) == "menu":
    pass  # Exit Game: back to the start menu for a new or saved game
pg.quit()
