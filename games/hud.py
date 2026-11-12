"""
Shared "target tracker" pill -- the one live progress readout every game
shows during play (e.g. "3/15 shots", "0 sorted", "12 fed"). Originally
reinvented per game (a plain unboxed line of text in some, a bespoke
gradient card in others, an image-backed box using a different font in
another), this is the single implementation now, so every game reads as
the same interface instead of ten different ones.

Usage (inside a game's draw(surface), with its own self._font_target --
pygame.font.SysFont("monospace", 54, bold=True) -- already created in
on_enter()):

    from games.hud import draw_target_pill, TARGET_POS
    draw_target_pill(surface, self._session_progress_text("shots"),
                      TARGET_POS, T["ACCENT"], self._font_target)
"""

import pygame
from constants import GAME_W, GAME_H

# Left-aligned, low on screen -- clear of every game's own playfield/header
# clutter, and identical across every game so the tracker always lands in
# the same place regardless of which game is running.
TARGET_POS = (int(48 * GAME_W / 1920), GAME_H - 150)

# The live readout's own text color -- fixed (not theme-dependent) since the
# pill's background is always this same fixed dark navy regardless of
# Light/Dark mode.
TARGET_TEXT_COLOR = (255, 235, 120)


def draw_target_pill(surface, text, pos, accent_col, font,
                      text_col=TARGET_TEXT_COLOR):
    """Draws `text` in a bordered, rounded, dark pill -- big and bold,
    first-class HUD element. Returns the pill's own rect so a caller can
    stack something else beneath/beside it if it ever needs to."""
    s = font.render(text, True, text_col)
    bg_r = s.get_rect(topleft=pos).inflate(40, 26)
    bg_s = pygame.Surface(bg_r.size, pygame.SRCALPHA)
    pygame.draw.rect(bg_s, (15, 18, 28, 190), (0, 0, *bg_r.size), border_radius=18)
    surface.blit(bg_s, bg_r.topleft)
    pygame.draw.rect(surface, accent_col, bg_r, 3, border_radius=18)
    surface.blit(s, pos)
    return bg_r
