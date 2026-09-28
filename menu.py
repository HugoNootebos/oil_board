"""
Main menu shown before the game starts: "New Game" (jumps straight into
the default game mode) vs "Continue" (pick the autosave or a named save
slot, loaded onto a freshly built default-mode game). Runs as its own small pygame loop, before an
Engine exists yet -- it only needs a window and a font, not the game
itself.
"""

import os
import pygame as pg
from player_colors import COUNT_MODE_COLORS, light_tint
from save_load import AUTOSAVE_PATH, SAVE_SLOT_COUNT, slot_path, read_save_name


# The menus are laid out at 960x640 like the game, but shown in a smaller
# window: drawn on an off-screen canvas, scaled down by MENU_SCALE.
MENU_SCALE = 0.75


def _open_window(width, height):
    """Open the (smaller) menu window; returns the full-size canvas to draw on."""
    pg.display.set_mode((round(width * MENU_SCALE), round(height * MENU_SCALE)))
    return pg.Surface((width, height))


def _present(canvas):
    window = pg.display.get_surface()
    window.blit(pg.transform.smoothscale(canvas, window.get_size()), (0, 0))
    pg.display.flip()


def _mouse_pos():
    """Mouse position in canvas (960x640) coordinates."""
    x, y = pg.mouse.get_pos()
    return round(x / MENU_SCALE), round(y / MENU_SCALE)


def _save_entries():
    """(label, path, name-or-None) for the autosave and each save slot."""
    entries = [("Autosave", AUTOSAVE_PATH, read_save_name(AUTOSAVE_PATH) and "Autosave")]
    for i in range(SAVE_SLOT_COUNT):
        path = slot_path(i)
        entries.append(("Slot {}".format(i + 1), path, read_save_name(path)))
    return entries


def run_main_menu(width=960, height=640):
    """Blocks until the player picks an option. Returns "new" or
    "continue". The Continue button is disabled (and unclickable) if no
    save file exists yet."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption("Main Menu")
    title_font = pg.font.SysFont("Times New Roman", 48)
    button_font = pg.font.SysFont("Times New Roman", 32)
    hint_font = pg.font.SysFont("Times New Roman", 18)

    has_save = any(os.path.isfile(path) for _, path, _ in _save_entries())

    button_w, button_h = 300, 70
    new_game_rect = pg.Rect(width // 2 - button_w // 2, height // 2 - 90, button_w, button_h)
    continue_rect = pg.Rect(width // 2 - button_w // 2, height // 2 + 20, button_w, button_h)

    clock = pg.time.Clock()
    while True:
        mouse_pos = _mouse_pos()
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

        title = title_font.render("OIL", True, (255, 255, 255))
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
            hint = hint_font.render("No saved game found", True, (200, 200, 200))
            screen.blit(hint, (width // 2 - hint.get_width() // 2, continue_rect.bottom + 10))

        _present(screen)
        clock.tick(60)


def run_load_menu(width=960, height=640):
    """Shown after "Continue": the autosave plus the save slots, each with
    its name. Returns the path of the one picked, or None for Back."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption("Continue")
    title_font = pg.font.SysFont("Times New Roman", 40)
    label_font = pg.font.SysFont("Times New Roman", 18)
    name_font = pg.font.SysFont("Times New Roman", 28)
    button_font = pg.font.SysFont("Times New Roman", 30)

    entries = _save_entries()
    row_w, row_h, gap = 420, 62, 12
    start_y = 130
    rows = [pg.Rect(width // 2 - row_w // 2, start_y + i * (row_h + gap), row_w, row_h) for i in range(len(entries))]
    back_rect = pg.Rect(width // 2 - 110, rows[-1].bottom + 30, 220, 56)

    clock = pg.time.Clock()
    while True:
        mouse_pos = _mouse_pos()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                pg.quit()
                raise SystemExit
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                for rect, (_, path, name) in zip(rows, entries):
                    if name and rect.collidepoint(mouse_pos):
                        return path
                if back_rect.collidepoint(mouse_pos):
                    return None

        screen.fill((30, 30, 40))
        title = title_font.render("Continue", True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, 50))

        for rect, (label, _, name) in zip(rows, entries):
            hovered = bool(name) and rect.collidepoint(mouse_pos)
            color = (150, 200, 245) if name else (110, 110, 110)
            if hovered:
                color = tuple(min(255, c + 25) for c in color)
            pg.draw.rect(screen, color, rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 3)
            screen.blit(label_font.render(label, True, (40, 40, 40)), (rect.x + 12, rect.y + 5))
            text = name_font.render(name or "(empty)", True, (0, 0, 0) if name else (60, 60, 60))
            screen.blit(text, (rect.x + 12, rect.y + 25))

        _draw_button(screen, button_font, back_rect, "Back", (220, 220, 220),
                     hovered=back_rect.collidepoint(mouse_pos))

        _present(screen)
        clock.tick(60)


def _draw_button(screen, font, rect, label, color, hovered):
    if hovered:
        color = tuple(min(255, c + 25) for c in color)
    pg.draw.rect(screen, color, rect)
    pg.draw.rect(screen, (0, 0, 0), rect, 3)
    text = font.render(label, True, (0, 0, 0))
    screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))


def run_new_game_menu(width=960, height=640):
    """Shown after "New Game" is picked. Blocks until the player chooses
    either the named default game ("De 3 Neven") or a plain N-player game.
    Returns "default" or an int player count (3-6)."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption("New Game")
    title_font = pg.font.SysFont("Times New Roman", 40)
    button_font = pg.font.SysFont("Times New Roman", 32)
    count_font = pg.font.SysFont("Times New Roman", 36)

    card_icon = pg.transform.scale(pg.image.load("./images/card0.png").convert_alpha(), (40, 74))

    default_w, default_h = 300, 70
    default_rect = pg.Rect(width // 2 - default_w // 2, height // 2 - 140, default_w, default_h)

    count_w, count_h = 130, 90
    gap = 30
    total_w = 4 * count_w + 3 * gap
    start_x = width // 2 - total_w // 2
    count_y = height // 2 + 10
    count_rects = [
        pg.Rect(start_x + i * (count_w + gap), count_y, count_w, count_h) for i in range(4)
    ]
    player_counts = [3, 4, 5, 6]

    clock = pg.time.Clock()
    while True:
        mouse_pos = _mouse_pos()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                pg.quit()
                raise SystemExit
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                if default_rect.collidepoint(mouse_pos):
                    return "default"
                for rect, count in zip(count_rects, player_counts):
                    if rect.collidepoint(mouse_pos):
                        return count

        screen.fill((30, 30, 40))

        title = title_font.render("New Game", True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, height // 2 - 220))

        _draw_button(
            screen, button_font, default_rect, "De 3 Neven",
            (150, 245, 150), hovered=default_rect.collidepoint(mouse_pos),
        )

        for rect, count in zip(count_rects, player_counts):
            hovered = rect.collidepoint(mouse_pos)
            color = (150, 200, 245)
            if hovered:
                color = tuple(min(255, c + 25) for c in color)
            pg.draw.rect(screen, color, rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 3)
            digit = count_font.render(str(count), True, (0, 0, 0))
            content_w = digit.get_width() + 8 + card_icon.get_width()
            cx = rect.centerx - content_w // 2
            screen.blit(digit, (cx, rect.centery - digit.get_height() // 2))
            screen.blit(card_icon, (cx + digit.get_width() + 8, rect.centery - card_icon.get_height() // 2))

        _present(screen)
        clock.tick(60)


def run_player_names_menu(count, width=960, height=640):
    """Shown after a 3/4/5/6-player game is picked. One text box per
    player, focus advances with Tab or Return; "Start Game" only works
    once every box has something in it. The button next to each box
    switches that player between human and bot, and the bot's difficulty
    (human -> normal -> hard -> easy -> human; a bot left unnamed is called
    "Bot N"). Returns (names, bots), both in order: a bot's level, or False
    for a human."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption("Player Names")
    title_font = pg.font.SysFont("Times New Roman", 40)
    label_font = pg.font.SysFont("Times New Roman", 26)
    button_font = pg.font.SysFont("Times New Roman", 30)

    names = [""] * count
    bots = [False] * count
    cycle = [False, "normal", "hard", "easy"]
    active = 0

    def final_names():
        return [name.strip() or "Bot {}".format(i + 1) for i, name in enumerate(names)]

    box_w, box_h, gap = 320, 50, 18
    total_h = count * box_h + (count - 1) * gap
    start_y = height // 2 - total_h // 2 - 30
    boxes = [pg.Rect(width // 2 - box_w // 2, start_y + i * (box_h + gap), box_w, box_h) for i in range(count)]
    bot_rects = [pg.Rect(box.right + 15, box.y, 170, box_h) for box in boxes]

    start_w, start_h = 220, 60
    start_rect = pg.Rect(width // 2 - start_w // 2, boxes[-1].bottom + 40, start_w, start_h)

    clock = pg.time.Clock()
    while True:
        all_filled = all(name.strip() or bot for name, bot in zip(names, bots))
        mouse_pos = _mouse_pos()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                pg.quit()
                raise SystemExit
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                for i, box in enumerate(boxes):
                    if box.collidepoint(mouse_pos):
                        active = i
                for i, rect in enumerate(bot_rects):
                    if rect.collidepoint(mouse_pos):
                        bots[i] = cycle[(cycle.index(bots[i]) + 1) % len(cycle)]
                if all_filled and start_rect.collidepoint(mouse_pos):
                    return final_names(), bots
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_TAB:
                    active = (active + 1) % count
                elif event.key == pg.K_RETURN:
                    if active < count - 1:
                        active += 1
                    elif all_filled:
                        return final_names(), bots
                elif event.key == pg.K_BACKSPACE:
                    names[active] = names[active][:-1]
            elif event.type == pg.TEXTINPUT:
                if len(names[active]) < 20:
                    names[active] += event.text

        screen.fill((30, 30, 40))
        title = title_font.render("Player Names", True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, start_y - 80))

        for i, box in enumerate(boxes):
            focused = i == active
            # Tinted the color that player will actually get in-game, so
            # what they see here while typing is what they'll play as.
            fill = light_tint(COUNT_MODE_COLORS[i % len(COUNT_MODE_COLORS)])
            pg.draw.rect(screen, fill, box)
            pg.draw.rect(screen, (0, 0, 0), box, 3 if focused else 2)
            label = label_font.render("Player {}:".format(i + 1), True, (255, 255, 255))
            screen.blit(label, (box.x - label.get_width() - 15, box.centery - label.get_height() // 2))
            if names[i] or not bots[i]:
                text = label_font.render(names[i], True, (0, 0, 0))
            else:
                text = label_font.render("Bot {}".format(i + 1), True, (110, 110, 110))
            screen.blit(text, (box.x + 10, box.centery - text.get_height() // 2))
            _draw_button(screen, label_font, bot_rects[i], "Bot ({})".format(bots[i]) if bots[i] else "Human",
                         (245, 200, 120) if bots[i] else (200, 200, 200),
                         hovered=bot_rects[i].collidepoint(mouse_pos))
            if focused and (pg.time.get_ticks() // 500) % 2 == 0:
                cursor_x = box.x + 10 + label_font.size(names[i])[0] + 2
                pg.draw.line(screen, (0, 0, 0), (cursor_x, box.y + 8), (cursor_x, box.bottom - 8), 2)

        _draw_button(
            screen, button_font, start_rect, "Start Game",
            (150, 245, 150) if all_filled else (110, 110, 110),
            hovered=all_filled and start_rect.collidepoint(mouse_pos),
        )

        _present(screen)
        clock.tick(60)
