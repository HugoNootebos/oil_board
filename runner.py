from engine import Engine
from menu import run_main_menu
from save_load import save_game, load_game
import pygame as pg

SAVE_PATH = "savegame.json"

# "New Game" and "Continue" both start the same default-mode game; Continue
# then immediately overwrites that freshly built state with the save file,
# since load_game expects an already-constructed engine to apply onto.
choice = run_main_menu(save_path=SAVE_PATH)
app = Engine(mode="default")
if choice == "continue":
    load_game(SAVE_PATH, app, app.turn_manager)

running = True
while running:
    app.io_handle()
    app.draw_world()
    app.draw_gui()
    app.update_turn()
    app.control_card_menu()
    for event in pg.event.get():
        if event.type == pg.QUIT:
            running = False
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 5:
            app.view.zoom_at(app.io.mouse_position, 1 / 1.1)
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 4:
            app.view.zoom_at(app.io.mouse_position, 1.1)
        if event.type == pg.KEYDOWN and event.key == pg.K_F5:
            save_game(app, app.turn_manager, SAVE_PATH)
        if event.type == pg.KEYDOWN and event.key == pg.K_F9:
            load_game(SAVE_PATH, app, app.turn_manager)

    pg.display.flip()

pg.quit()
