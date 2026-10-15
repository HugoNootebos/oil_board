"""
The chat of an online game (a local game has none).

Every device draws its own chat over the game: the host after the picture
for the devices is taken (online.HostSession.draw_chat, from
Engine.present), a joined device over the host's picture (viewer.py). So
an open chat, or a message being typed, is nobody else's business. The
button sits under the settings button (images/chat.png); a click opens the
panel to its right: the messages, newest at the bottom (the wheel scrolls
back), and a line to type in. While it's open the keyboard belongs to it:
Enter sends, Esc closes. A red badge counts the messages that came in while
it was closed. Mouse and keyboard only: game controllers can't type.

The host keeps the messages and stamps who said what
(online.HostSession.say): a joined device sends chat{text}, the host sends
the devices chat{lines} (a line: [member (0: the host), name, [r, g, b],
text]) and a device coming into the game the HISTORY so far (old: true;
that doesn't count as unread).
"""

import pygame as pg

import sounds
from fonts import game_font
from lang import t
from player_colors import light_tint

TEXT_MAX = 120   # characters in one message
NAME_MAX = 40
HISTORY = 100    # messages kept (and given to a device that comes in)
COLOR = (245, 200, 215)        # the button: pale pink, no other HUD button's colour
NO_COLOR = (200, 200, 200)     # someone without a player (watching)
BUTTON = pg.Rect(10, 60, 44, 44)    # under the settings button (Engine.BUTTON_STEP lower, as big)
PANEL = pg.Rect(60, 60, 400, 270)   # opens to the right of it
SPRITE = 38      # the sprite on the button, as on the other top-left buttons
MARGIN = 14      # room around the button for its hover growth and the badge
ROW_H = 22
INPUT_H = 32
NAME_TINT = 0.35  # names as light as the action log's


def clean_text(text):
    """One line of printable text, spaces squeezed, at most TEXT_MAX long."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return " ".join(text.split())[:TEXT_MAX]


def valid_line(line):
    return (isinstance(line, list) and len(line) == 4
            and isinstance(line[0], int) and not isinstance(line[0], bool)
            and isinstance(line[1], str) and isinstance(line[3], str)
            and isinstance(line[2], list) and len(line[2]) == 3
            and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in line[2]))


class Chat:
    """One device's chat: the messages, the button and the panel.
    `send(text)` is what happens to a message typed here; `me` is this
    device's member number (0 on the host)."""

    def __init__(self, send, me=0):
        self.send = send
        self.me = me
        self.lines = []
        self.version = 0   # goes up with every message
        self.open = False
        self.draft = ""
        self.unread = 0
        self.scroll = 0    # rows scrolled back from the newest
        self._font = None
        self._sprite = None
        self._rows = (None, [])
        self._button = (None, None)
        self._panel = (None, None)

    # --- messages -----------------------------------------------------------------

    def add(self, lines, old=False):
        """Messages from the host (or, on the host, its own)."""
        added = []
        for line in lines if isinstance(lines, list) else []:
            if not valid_line(line):
                continue
            line = [line[0], line[1][:NAME_MAX], list(line[2]), clean_text(line[3])]
            if line[3]:
                added.append(line)
        if not added:
            return
        self.lines = (self.lines + added)[-HISTORY:]
        self.version += 1
        if not old and not self.open:
            self.unread += sum(line[0] != self.me for line in added)
        if self.scroll:
            self.scroll += sum(len(self._wrap(line)) for line in added)  # what's being read stays put

    @property
    def font(self):
        if self._font is None:  # (made when first needed: a session starts before pygame's fonts)
            self._font = game_font(17)
        return self._font

    def name(self, line):
        """Who said it: their player(s), else the host or someone watching."""
        return line[1] or (t("The host") if line[0] == 0 else t("Spectator"))

    # --- input -----------------------------------------------------------------------

    def covers(self, pos):
        """Whether `pos` (logical) is on the chat, out of the game's reach."""
        pos = (int(pos[0]), int(pos[1]))
        return BUTTON.collidepoint(pos) or (self.open and PANEL.collidepoint(pos))

    def shapes(self):
        """The chat as Io buttons (the map under it can't be clicked)."""
        shapes = [("r", BUTTON.x, BUTTON.y, BUTTON.w, BUTTON.h)]
        if self.open:
            shapes.append(("r", PANEL.x, PANEL.y, PANEL.w, PANEL.h))
        return shapes

    def toggle(self):
        self.open = not self.open
        self.scroll = 0
        if self.open:
            self.unread = 0
        sounds.play("click", shared=False)  # (not one for the devices to hear too)

    def handle(self, event, to_logical):
        """Take a pygame event if it's the chat's: True when it was (then the
        game mustn't get it). `to_logical` turns a window position into the
        game's 960x640."""
        if event.type == pg.MOUSEBUTTONDOWN:
            pos = to_logical(event.pos)
            if not self.covers(pos):
                return False
            if event.button == 1 and BUTTON.collidepoint(int(pos[0]), int(pos[1])):
                self.toggle()
            elif event.button in (4, 5) and self.open:
                self.scroll = max(0, self.scroll + (1 if event.button == 4 else -1))
            return True
        if not self.open:
            return False
        if event.type == pg.TEXTINPUT:
            self.draft = (self.draft + "".join(ch for ch in event.text if ch.isprintable()))[:TEXT_MAX]
            return True
        if event.type == pg.KEYDOWN:
            if event.key == pg.K_ESCAPE:
                self.toggle()
            elif event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                text = clean_text(self.draft)
                self.draft = ""
                self.scroll = 0
                if text:
                    self.send(text)
            elif event.key == pg.K_BACKSPACE:
                self.draft = self.draft[:-1]
            return True  # every key is the chat's while it's open (no F5, no fullscreen)
        return event.type == pg.KEYUP

    # --- drawing ------------------------------------------------------------------------

    def key(self, mouse):
        """What the chat looks like (a viewer redraws when it changes)."""
        return (self.open, self.unread, self.version, self.draft, self.scroll,
                mouse is not None and BUTTON.collidepoint(int(mouse[0]), int(mouse[1])))

    def draw(self, surface, scale, offset, mouse=None):
        """Draw it on `surface` (window pixels): the game's 960x640 is shown
        `scale` times that size at `offset`; `mouse` is logical or None."""
        hovered = self.key(mouse)[-1]
        key = (self.open, self.unread, hovered, scale)
        if self._button[0] != key:
            self._button = (key, self._scaled(self._draw_button(hovered), scale))
        surface.blit(self._button[1], (round(offset[0] + (BUTTON.x - MARGIN) * scale),
                                       round(offset[1] + (BUTTON.y - MARGIN) * scale)))
        if not self.open:
            return
        key = (self.version, self.draft, self.scroll, scale, t("The host"))
        if self._panel[0] != key:
            self._panel = (key, self._scaled(self._draw_panel(), scale))
        surface.blit(self._panel[1], (round(offset[0] + PANEL.x * scale), round(offset[1] + PANEL.y * scale)))

    @staticmethod
    def _scaled(image, scale):
        if scale == 1:
            return image
        size = (max(1, round(image.get_width() * scale)), max(1, round(image.get_height() * scale)))
        return pg.transform.smoothscale(image, size)

    def _draw_button(self, hovered):
        """Like the HUD's buttons (models.Button): grows a little under the
        mouse, a thicker edge while open; the badge on its corner."""
        if self._sprite is None:
            self._sprite = pg.transform.smoothscale(pg.image.load("./images/chat.png").convert_alpha(),
                                                    (SPRITE, SPRITE))
        image = pg.Surface((BUTTON.w + 2 * MARGIN, BUTTON.h + 2 * MARGIN), pg.SRCALPHA)
        rect = pg.Rect(MARGIN, MARGIN, BUTTON.w, BUTTON.h).inflate(6 * hovered, 6 * hovered)
        pg.draw.rect(image, COLOR, rect)
        pg.draw.rect(image, (0, 0, 0), rect, 4 if self.open else 2)
        image.blit(self._sprite, self._sprite.get_rect(center=rect.center))
        if self.unread:
            center = (MARGIN + BUTTON.w - 2, MARGIN + 2)
            pg.draw.circle(image, (210, 40, 40), center, 11)
            pg.draw.circle(image, (255, 255, 255), center, 11, 2)
            label = str(self.unread) if self.unread < 10 else "9+"
            text = game_font(15 if self.unread < 10 else 13, bold=True).render(label, True, (255, 255, 255))
            image.blit(text, text.get_rect(center=center))
        return image

    def _wrap(self, line):
        """A message as rows of (text, colour) pieces that fit the panel."""
        width = PANEL.w - 30
        font = self.font
        pieces = [(self.name(line) + ": ", light_tint(line[2], NAME_TINT))]
        pieces += [(word + " ", (255, 255, 255)) for word in line[3].split(" ")]
        rows, row, x = [], [], 0
        for text, color in pieces:
            w = font.size(text.rstrip())[0]
            if row and x + w > width:
                rows.append(row)
                row, x = [], 0
            while font.size(text.rstrip())[0] > width:  # one long word: broken up
                cut = len(text) - 1
                while cut > 1 and font.size(text[:cut])[0] > width - x:
                    cut -= 1
                row.append((text[:cut], color))
                rows.append(row)
                row, x, text = [], 0, text[cut:]
            row.append((text, color))
            x += font.size(text)[0]
        rows.append(row)
        return rows

    def _all_rows(self):
        key = (self.version, t("The host"))
        if self._rows[0] != key:
            self._rows = (key, [row for line in self.lines for row in self._wrap(line)])
        return self._rows[1]

    def _draw_panel(self):
        """Black 80% like the action log: the messages, the typing line."""
        font = self.font
        image = pg.Surface(PANEL.size, pg.SRCALPHA)
        pg.draw.rect(image, (0, 0, 0, 204), image.get_rect(), border_radius=6)
        area = pg.Rect(10, 8, PANEL.w - 26, PANEL.h - INPUT_H - 24)
        rows = self._all_rows()
        visible = area.h // ROW_H
        most = max(len(rows) - visible, 0)
        self.scroll = min(self.scroll, most)
        if not rows:
            text = font.render(t("No messages yet"), True, (170, 170, 170))
            image.blit(text, text.get_rect(center=area.center))
        end = len(rows) - self.scroll
        shown = rows[max(end - visible, 0):end]
        y = area.bottom - len(shown) * ROW_H
        for row in shown:
            x = area.x
            for text, color in row:
                piece = font.render(text, True, color)
                image.blit(piece, (x, y + (ROW_H - piece.get_height()) // 2))
                x += piece.get_width()
            y += ROW_H
        if most:
            track = pg.Rect(PANEL.w - 10, area.y, 4, area.h)
            pg.draw.rect(image, (255, 255, 255, 50), track, border_radius=2)
            thumb_h = max(18, track.h * visible // len(rows))
            room = track.h - thumb_h
            thumb_y = track.y + room - room * self.scroll // most
            pg.draw.rect(image, (255, 255, 255, 170), pg.Rect(track.x, thumb_y, 4, thumb_h), border_radius=2)
        box = pg.Rect(8, PANEL.h - INPUT_H - 8, PANEL.w - 16, INPUT_H)
        pg.draw.rect(image, (255, 255, 255, 235), box, border_radius=4)
        inner = box.inflate(-16, 0)
        if self.draft:
            text = font.render(self.draft + "|", True, (0, 0, 0))
            right = max(0, text.get_width() - inner.w)  # a long line shows its end
            image.blit(text, (inner.x, inner.centery - text.get_height() // 2), pg.Rect(right, 0, inner.w, text.get_height()))
        else:
            hint = font.render(t("Type a message (Enter: send, Esc: close)"), True, (120, 120, 120))
            caret = font.render("|", True, (0, 0, 0))
            image.blit(caret, (inner.x, inner.centery - caret.get_height() // 2))
            image.blit(hint, (inner.x + caret.get_width() + 2, inner.centery - hint.get_height() // 2),
                       pg.Rect(0, 0, inner.w - caret.get_width() - 2, hint.get_height()))
        return image
