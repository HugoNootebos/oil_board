from engine import Engine
import pygame as pg

# Initialize app
app = Engine()

running = True
while running:
    app.io_handle()
    app.draw_world()
    app.draw_gui()
    app.control_card_menu()
    for event in pg.event.get():
        if event.type == pg.QUIT:
            running = False
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 5:
            app.view.zoom /= 1.1
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 4:
            app.view.zoom *= 1.1

    pg.display.flip()

pg.quit()
