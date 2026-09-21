"""
Main menu shown before the game starts: "New Game" (jumps straight into
the default game mode) vs "Continue" (loads savegame.json onto a freshly
built default-mode game). Runs as its own small pygame loop, before an
Engine exists yet -- it only needs a window and a font, not the game
itself.
"""

import os
import pygame as pg


def run_main_menu(width=960, height=640, save_path="savegame.json"):
    """Blocks until the player picks an option. Returns "new" or
    "continue". The Continue button is disabled (and unclickable) if no
    save file exists yet."""
    pg.init()
    pg.font.init()
    screen = pg.display.set_mode([width, height])
    pg.display.set_caption("Main Menu")
    title_font = pg.font.SysFont("Times New Roman", 48)
    button_font = pg.font.SysFont("Times New Roman", 32)
    hint_font = pg.font.SysFont("Times New Roman", 18)

    has_save = os.path.isfile(save_path)

    button_w, button_h = 300, 70
    new_game_rect = pg.Rect(width // 2 - button_w // 2, height // 2 - 90, button_w, button_h)
    continue_rect = pg.Rect(width // 2 - button_w // 2, height // 2 + 20, button_w, button_h)

    clock = pg.time.Clock()
    while True:
        mouse_pos = pg.mouse.get_pos()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                pg.quit()
                raise SystemExit
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                if new_game_rect.collidepoint(mouse_pos):
                    return "new"
                if has_save and continue_rect.collidepoint(mouse_pos):
                    return "continue"

        screen.fill((30, 30, 40))

        title = title_font.render("OIL", False, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, height // 2 - 200))

        _draw_button(
            screen, button_font, new_game_rect, "New Game",
            (150, 245, 150), hovered=new_game_rect.collidepoint(mouse_pos),
        )
        _draw_button(
            screen, button_font, continue_rect, "Continue",
            (150, 200, 245) if has_save else (110, 110, 110),
            hovered=has_save and continue_rect.collidepoint(mouse_pos),
        )
        if not has_save:
            hint = hint_font.render("No saved game found", False, (200, 200, 200))
            screen.blit(hint, (width // 2 - hint.get_width() // 2, continue_rect.bottom + 10))

        pg.display.flip()
        clock.tick(60)


def _draw_button(screen, font, rect, label, color, hovered):
    if hovered:
        color = tuple(min(255, c + 25) for c in color)
    pg.draw.rect(screen, color, rect)
    pg.draw.rect(screen, (0, 0, 0), rect, 3)
    text = font.render(label, False, (0, 0, 0))
    screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))
