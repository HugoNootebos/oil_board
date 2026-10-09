"""
Main menu shown before the game starts: "New Game" (jumps straight into
the default game mode) vs "Continue" (pick the autosave or a named save
slot, loaded onto a freshly built default-mode game). Runs as its own small pygame loop, before an
Engine exists yet -- it only needs a window and a font, not the game
itself.
"""

import os
import pygame as pg
import controls
import sounds
import lang
from fonts import game_font
from lang import t
from player_colors import COUNT_MODE_COLORS, light_tint
from save_load import AUTOSAVE_PATH, SAVE_SLOT_COUNT, slot_path, read_save_name


# The menus are laid out at 960x640 like the game, but shown in a smaller
# window: drawn on an off-screen canvas, scaled down by MENU_SCALE.
MENU_SCALE = 0.75

# Language flag in the main menu's top-right corner: the flag of the
# language in use; a click switches between Dutch and English (lang.py).
FLAG_IMAGES = {"nl": "./images/nl_flag.png", "en": "./images/uk_flag.png"}
FLAG_SIZE = (52, 36)


def _open_window(width, height):
    """Open the (smaller) menu window; returns the full-size canvas to draw on.
    Coming back from the game (Exit Game) the window may still be
    fullscreen or big: it's made windowed, menu-sized and centered again."""
    size = (round(width * MENU_SCALE), round(height * MENU_SCALE))
    current = pg.display.get_surface()
    resized = current is None or current.get_size() != size
    pg.display.set_mode(size)
    if resized:
        window = pg.Window.from_display_module()
        window.set_windowed()
        window.size = size
        window.position = pg.WINDOWPOS_CENTERED
    return pg.Surface((width, height))


def _present(canvas, looks=None):
    """Show the canvas, with the game controllers' cursors on top (looks:
    see controls.Controls.draw)."""
    controls.get().draw(canvas, looks=looks)
    window = pg.display.get_surface()
    window.blit(pg.transform.smoothscale(canvas, window.get_size()), (0, 0))
    pg.display.flip()


def _input():
    """This frame's events, the pointer position in canvas (960x640)
    coordinates -- the mouse's or a game controller's, whichever was used
    last -- and the clicks: (position, pad), pad None for the mouse. Every
    controller clicks in the menus. Closing the window quits."""
    events = pg.event.get()
    if any(event.type == pg.QUIT for event in events):
        pg.quit()
        raise SystemExit
    mouse_pos, clicks = controls.get().menu_input(events, MENU_SCALE)
    return events, mouse_pos, clicks


def _save_entries():
    """(label, path, name-or-None) for the autosave and each save slot."""
    entries = [("Autosave", AUTOSAVE_PATH, read_save_name(AUTOSAVE_PATH) and "Autosave")]
    for i in range(SAVE_SLOT_COUNT):
        path = slot_path(i)
        entries.append((t("Slot {}").format(i + 1), path, read_save_name(path)))
    return entries


def run_main_menu(width=960, height=640):
    """Blocks until the player picks an option. Returns "new" or
    "continue". The Continue button is disabled (and unclickable) if no
    save file exists yet."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption(t("Main Menu"))
    title_font = game_font(48)
    button_font = game_font(32)
    hint_font = game_font(18)

    has_save = any(os.path.isfile(path) for _, path, _ in _save_entries())

    button_w, button_h = 300, 70
    new_game_rect = pg.Rect(width // 2 - button_w // 2, height // 2 - 120, button_w, button_h)
    continue_rect = pg.Rect(width // 2 - button_w // 2, height // 2 - 10, button_w, button_h)
    quit_rect = pg.Rect(width // 2 - button_w // 2, height // 2 + 180, button_w, button_h)
    flags = {
        key: pg.transform.smoothscale(pg.image.load(path).convert_alpha(), FLAG_SIZE)
        for key, path in FLAG_IMAGES.items()
    }
    flag_rect = pg.Rect(width - FLAG_SIZE[0] - 20, 20, *FLAG_SIZE)

    clock = pg.time.Clock()
    while True:
        _, mouse_pos, clicks = _input()
        for click, _ in clicks:
            if flag_rect.collidepoint(click):
                lang.set_language("en" if lang.language == "nl" else "nl")
                pg.display.set_caption(t("Main Menu"))
                sounds.play("click")
                continue
            sounds.play("error" if not has_save and continue_rect.collidepoint(click) else "click")
            if new_game_rect.collidepoint(click):
                return "new"
            if has_save and continue_rect.collidepoint(click):
                return "continue"
            if quit_rect.collidepoint(click):
                pg.quit()
                raise SystemExit

        screen.fill((30, 30, 40))

        title = title_font.render("OIL", True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, height // 2 - 230))

        _draw_button(
            screen, button_font, new_game_rect, t("New Game"),
            (150, 245, 150), hovered=new_game_rect.collidepoint(mouse_pos),
        )
        _draw_button(
            screen, button_font, continue_rect, t("Continue"),
            (150, 200, 245) if has_save else (110, 110, 110),
            hovered=has_save and continue_rect.collidepoint(mouse_pos),
        )
        if not has_save:
            hint = hint_font.render(t("No saved game found"), True, (200, 200, 200))
            screen.blit(hint, (width // 2 - hint.get_width() // 2, continue_rect.bottom + 10))
        _draw_button(
            screen, button_font, quit_rect, t("Quit"),
            (240, 100, 100), hovered=quit_rect.collidepoint(mouse_pos),
        )
        screen.blit(flags[lang.language], flag_rect)
        edge = (255, 255, 255) if flag_rect.collidepoint(mouse_pos) else (90, 90, 100)
        pg.draw.rect(screen, edge, flag_rect.inflate(4, 4), 2)

        _present(screen)
        clock.tick(60)


def run_load_menu(width=960, height=640):
    """Shown after "Continue": the autosave plus the save slots, each with
    its name. Returns the path of the one picked, or None for Back."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption(t("Continue"))
    title_font = game_font(40)
    label_font = game_font(18)
    name_font = game_font(28)
    button_font = game_font(30)

    entries = _save_entries()
    row_w, row_h, gap = 420, 62, 12
    start_y = 130
    rows = [pg.Rect(width // 2 - row_w // 2, start_y + i * (row_h + gap), row_w, row_h) for i in range(len(entries))]
    back_rect = pg.Rect(width // 2 - 110, rows[-1].bottom + 30, 220, 56)
    # An X right of each save deletes it; the first click arms it ("Sure?"),
    # the second deletes the file.
    delete_rects = [pg.Rect(rect.right + 12, rect.y + (row_h - 44) // 2, 44, 44) for rect in rows]
    armed = None

    clock = pg.time.Clock()
    while True:
        _, mouse_pos, clicks = _input()
        for click, _ in clicks:
            hit = next((i for i, (r, (_, _, name)) in enumerate(zip(delete_rects, entries))
                        if name and (r.inflate(46, 0).move(23, 0) if armed == i else r).collidepoint(click)),
                       None)
            if hit is not None:
                sounds.play("click")
                if armed == hit:
                    try:
                        os.remove(entries[hit][1])
                    except OSError:
                        pass
                    entries = _save_entries()
                    armed = None
                else:
                    armed = hit
                continue
            armed = None
            sounds.play("error" if any(not name and rect.collidepoint(click)
                                       for rect, (_, _, name) in zip(rows, entries)) else "click")
            for rect, (_, path, name) in zip(rows, entries):
                if name and rect.collidepoint(click):
                    return path
            if back_rect.collidepoint(click):
                return None

        screen.fill((30, 30, 40))
        title = title_font.render(t("Continue"), True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, 50))

        for rect, (label, _, name) in zip(rows, entries):
            hovered = bool(name) and rect.collidepoint(mouse_pos)
            color = (150, 200, 245) if name else (110, 110, 110)
            if hovered:
                color = tuple(min(255, c + 25) for c in color)
            pg.draw.rect(screen, color, rect)
            pg.draw.rect(screen, (0, 0, 0), rect, 3)
            screen.blit(label_font.render(label, True, (40, 40, 40)), (rect.x + 12, rect.y + 5))
            text = name_font.render(name or t("(empty)"), True, (0, 0, 0) if name else (60, 60, 60))
            screen.blit(text, (rect.x + 12, rect.y + 25))

        for i, (rect, (_, _, name)) in enumerate(zip(delete_rects, entries)):
            if not name:
                continue
            if armed == i:
                sure = pg.Rect(rect.x, rect.y, 90, rect.h)
                _draw_button(screen, label_font, sure, t("Sure?"), (240, 100, 100), hovered=sure.collidepoint(mouse_pos))
                continue
            _draw_button(screen, button_font, rect, "X", (240, 100, 100), hovered=rect.collidepoint(mouse_pos))

        _draw_button(screen, button_font, back_rect, t("Back"), (220, 220, 220),
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
    pg.display.set_caption(t("New Game"))
    title_font = game_font(40)
    button_font = game_font(32)
    count_font = game_font(36)

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
        _, mouse_pos, clicks = _input()
        for click, _ in clicks:
            sounds.play("click")
            if default_rect.collidepoint(click):
                return "default"
            for rect, count in zip(count_rects, player_counts):
                if rect.collidepoint(click):
                    return count

        screen.fill((30, 30, 40))

        title = title_font.render(t("New Game"), True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, height // 2 - 220))

        _draw_button(
            screen, button_font, default_rect, t("De 3 Neven"),
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
    player, focus advances with Tab or Return; a box left empty gives
    "Player N" ("Bot N" for a bot), so a game can be set up with game
    controllers alone. The button next to each box switches that player
    between Human and Bot. With game controllers connected each human row
    also gets a controller button: a controller clicking it (A) becomes
    that player's (controls.py), the mouse clicking it takes it away
    again. Returns (names, bots), both in order; bots[i] is True for a
    bot, False for a human."""
    pg.init()
    pg.font.init()
    screen = _open_window(width, height)
    pg.display.set_caption(t("Player Names"))
    title_font = game_font(40)
    label_font = game_font(26)
    button_font = game_font(30)
    hint_font = game_font(18)
    pads = controls.get()

    names = [""] * count
    bots = [False] * count
    row_pads = [None] * count  # the controller each row has, if any
    active = 0

    def default_name(i):
        return "Bot {}".format(i + 1) if bots[i] else t("Player {}").format(i + 1)

    def finish():
        final = [name.strip() or default_name(i) for i, name in enumerate(names)]
        pads.pair_all((pad, final[i]) for i, pad in enumerate(row_pads) if pad is not None)
        return final, bots

    box_w, box_h, gap = 320, 50, 18
    total_h = count * box_h + (count - 1) * gap
    start_y = height // 2 - total_h // 2 - 30
    start_w, start_h = 220, 60

    clock = pg.time.Clock()
    while True:
        # With controllers connected the rows make room for their buttons.
        with_pads = bool(pads.pads)
        box_x = width // 2 - box_w // 2 - (75 if with_pads else 0)
        boxes = [pg.Rect(box_x, start_y + i * (box_h + gap), box_w, box_h) for i in range(count)]
        bot_rects = [pg.Rect(box.right + 15, box.y, 130 if with_pads else 170, box_h) for box in boxes]
        pad_rects = [pg.Rect(rect.right + 10, rect.y, 190, box_h) for rect in bot_rects] if with_pads else []
        start_rect = pg.Rect(width // 2 - start_w // 2, boxes[-1].bottom + 40, start_w, start_h)
        row_pads = [pad if pad in pads.pads else None for pad in row_pads]  # unplugged

        events, mouse_pos, clicks = _input()
        for click, pad in clicks:
            sounds.play("click")
            for i, box in enumerate(boxes):
                if box.collidepoint(click):
                    active = i
            for i, rect in enumerate(bot_rects):
                if rect.collidepoint(click):
                    bots[i] = not bots[i]
                    row_pads[i] = None  # bots don't use controllers
            for i, rect in enumerate(pad_rects):
                if not bots[i] and rect.collidepoint(click):
                    row_pads = [None if p is pad else p for p in row_pads]
                    row_pads[i] = pad  # the mouse (None) takes it away
            if start_rect.collidepoint(click):
                return finish()
        for event in events:
            if event.type == pg.KEYDOWN:
                if event.key == pg.K_TAB:
                    active = (active + 1) % count
                elif event.key == pg.K_RETURN:
                    if active < count - 1:
                        active += 1
                    else:
                        return finish()
                elif event.key == pg.K_BACKSPACE:
                    names[active] = names[active][:-1]
            elif event.type == pg.TEXTINPUT:
                if len(names[active]) < 20:
                    names[active] += event.text

        screen.fill((30, 30, 40))
        title = title_font.render(t("Player Names"), True, (255, 255, 255))
        screen.blit(title, (width // 2 - title.get_width() // 2, start_y - 80))
        if with_pads:
            hint = hint_font.render(t("Controllers: point at the button next to your name and press A"),
                                    True, (200, 200, 200))
            screen.blit(hint, (width // 2 - hint.get_width() // 2, start_y - 32))

        looks = {}  # a paired controller's cursor (and light) in its row's colour
        for i, box in enumerate(boxes):
            focused = i == active
            # Tinted the color that player will actually get in-game, so
            # what they see here while typing is what they'll play as.
            color = COUNT_MODE_COLORS[i % len(COUNT_MODE_COLORS)]
            pg.draw.rect(screen, light_tint(color), box)
            pg.draw.rect(screen, (0, 0, 0), box, 3 if focused else 2)
            label = label_font.render(t("Player {}:").format(i + 1), True, (255, 255, 255))
            screen.blit(label, (box.x - label.get_width() - 15, box.centery - label.get_height() // 2))
            if names[i]:
                text = label_font.render(names[i], True, (0, 0, 0))
            else:
                text = label_font.render(default_name(i), True, (110, 110, 110))
            screen.blit(text, (box.x + 10, box.centery - text.get_height() // 2))
            _draw_button(screen, label_font, bot_rects[i], t("Bot") if bots[i] else t("Human"),
                         (245, 200, 120) if bots[i] else (200, 200, 200),
                         hovered=bot_rects[i].collidepoint(mouse_pos))
            if with_pads and not bots[i]:
                pad = row_pads[i]
                _draw_button(screen, label_font, pad_rects[i],
                             t("Controller {}").format(pad.number) if pad else t("No controller"),
                             light_tint(color) if pad else (160, 160, 160),
                             hovered=pad_rects[i].collidepoint(mouse_pos))
                if pad is not None:
                    looks[pad] = (color, False)
            if focused and (pg.time.get_ticks() // 500) % 2 == 0:
                cursor_x = box.x + 10 + label_font.size(names[i])[0] + 2
                pg.draw.line(screen, (0, 0, 0), (cursor_x, box.y + 8), (cursor_x, box.bottom - 8), 2)
        for pad in pads.pads:
            pad.set_led(looks.get(pad, (controls.UNPAIRED_COLOR,))[0])

        _draw_button(
            screen, button_font, start_rect, t("Start Game"),
            (150, 245, 150), hovered=start_rect.collidepoint(mouse_pos),
        )

        _present(screen, looks)
        clock.tick(60)
