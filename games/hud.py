"""
Shared "target tracker" pill -- the one live progress readout every game
shows during play (e.g. "3/15 shots", "0 sorted", "12 fed"). One shared
implementation, so every game's progress readout reads as the same
interface.

Usage (inside a game's draw(surface), with its own self._font_target --
pygame.font.SysFont("monospace", 54, bold=True) -- already created in
on_enter()):

    from games.hud import draw_target_pill, TARGET_POS
    draw_target_pill(surface, self._session_progress_text("shots"),
                      TARGET_POS, T["ACCENT"], self._font_target)
"""

import math
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


# ── "TUTORIAL" badge -- the one on-screen cue that a run is a practice
# session (real gameplay/sensors, but SessionModeMixin._session_should_save()
# skips the save, so it never reaches the patient's history/reports). Every
# game that reads self.tutorial (see games/session_mode.py) draws this with:
#     if self.tutorial:
#         draw_tutorial_badge(surface)
# Owns its own small font lazily so no game needs to create one for it. ──
TUTORIAL_BADGE_POS   = (GAME_W // 2, int(34 * GAME_H / 1080))
TUTORIAL_BADGE_COLOR = (255, 200, 60)
_tutorial_badge_font = None


def draw_feedback_banner(surface, feedback, font, center_pos):
    """feedback = (text, color, remaining_seconds), the exact tuple every
    game already keeps in self.feedback (decremented once per frame; this
    function only changes how it's drawn, not that data model). Draws a
    bordered rounded banner (border = the feedback's own color) behind
    bold, outlined text, with a continuous breathing pulse and a fade-out
    over the final ~0.25s of remaining_seconds -- remaining_seconds alone
    is enough to drive the fade, no extra per-game state needed."""
    text, color, remaining = feedback
    if remaining <= 0:
        return
    fade  = min(1.0, remaining / 0.25)
    pulse = 1.0 + 0.045 * math.sin(pygame.time.get_ticks() / 130.0)

    # Outline (8-direction offset, near-black) behind the feedback-colored
    # fill -- keeps the text legible against any game background.
    pad = 3
    fill    = font.render(text, True, color)
    outline = font.render(text, True, (10, 10, 14))
    base = pygame.Surface((fill.get_width() + pad * 2, fill.get_height() + pad * 2), pygame.SRCALPHA)
    for dx, dy in ((-pad, 0), (pad, 0), (0, -pad), (0, pad),
                   (-pad, -pad), (pad, -pad), (-pad, pad), (pad, pad)):
        base.blit(outline, (pad + dx, pad + dy))
    base.blit(fill, (pad, pad))

    bg_r = base.get_rect().inflate(44, 28)
    banner = pygame.Surface(bg_r.size, pygame.SRCALPHA)
    pygame.draw.rect(banner, (12, 14, 22, 215), (0, 0, *bg_r.size), border_radius=20)
    pygame.draw.rect(banner, color, (0, 0, *bg_r.size), 4, border_radius=20)
    banner.blit(base, base.get_rect(center=(bg_r.width // 2, bg_r.height // 2)))

    scaled = pygame.transform.smoothscale(
        banner, (max(1, int(bg_r.width * pulse)), max(1, int(bg_r.height * pulse))))
    if fade < 1.0:
        scaled.set_alpha(int(255 * fade))
    surface.blit(scaled, scaled.get_rect(center=center_pos))


def draw_tutorial_badge(surface):
    global _tutorial_badge_font
    if _tutorial_badge_font is None:
        _tutorial_badge_font = pygame.font.SysFont("arial", int(26 * GAME_H / 1080), bold=True)
    s = _tutorial_badge_font.render("TUTORIAL", True, (40, 30, 0))
    bg_r = s.get_rect(center=TUTORIAL_BADGE_POS).inflate(36, 18)
    bg_s = pygame.Surface(bg_r.size, pygame.SRCALPHA)
    pygame.draw.rect(bg_s, (*TUTORIAL_BADGE_COLOR, 235), (0, 0, *bg_r.size), border_radius=14)
    surface.blit(bg_s, bg_r.topleft)
    pygame.draw.rect(surface, (120, 90, 0), bg_r, 2, border_radius=14)
    surface.blit(s, s.get_rect(center=bg_r.center))


# ── "Controls" supplement panel for the How-To-Play screen ──────────────
# Every game's illustrated "How To Play" card (assets/images/*_how_to_play_
# *.png) is pre-made art with its own baked-in title/steps/tip -- fully out
# of reach for code to edit, and it only ever shows the headline 1-2-3 loop.
# It can miss secondary or less obvious actions a patient still needs to
# know (which finger goes with which hole/lane, a flex-sensor release, a
# "hold steady to fire" mechanic with no squeeze at all, ...). This panel is
# the code-drawn supplement that sits in the screen's own side margin next
# to that card (see each game's _draw_instructions for its call site) and
# spells out EVERY control action in plain text, action-by-action, without
# touching the artwork at all.
#
# Usage:
#     from games.hud import draw_controls_panel, controls_panel_rect
#     draw_controls_panel(surface, controls_panel_rect(top_margin, bottom_reserved), [
#         ("Squeeze", "Squeeze your hand to raise the grip bar."),
#         ("Release", "Release your grip to shoot, then repeat."),
#     ])
_CP_ACCENT = (120, 195, 255)


def controls_panel_rect(top_margin, _bottom_reserved_unused=None):
    """The fixed right-side strip reserved for the panel -- deliberately
    independent of any one card's actual (aspect-ratio-dependent) drawn
    width, so it never has to know or care how wide a specific card image
    happened to render at. Cards are capped at 50% of GAME_W and centered,
    so their right edge never passes GAME_W//2 + 25%; this starts just
    past that, with a small margin on both sides.

    Height ignores `bottom_reserved` (that reserve only exists so the card
    matches the Round Complete card's proportions -- nothing else occupies
    that space on THIS screen) and instead runs almost to the bottom of
    the screen, so the panel gets the extra room its bigger text needs."""
    gap = int(GAME_W * 0.015)
    x = GAME_W // 2 + int(GAME_W * 0.25) + gap
    bottom_margin = int(GAME_H * 0.03)
    return pygame.Rect(x, top_margin, GAME_W - x - gap, GAME_H - top_margin - bottom_margin)


def _wrap_text(text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or font.size(trial)[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_controls_panel(surface, panel_rect, entries, title="Controls"):
    """entries: list of (action_label, description) pairs, in the order a
    patient actually performs them. Drawn as its own rounded, translucent
    card -- reads as a supplement sitting beside the illustrated card, not
    a replacement for it."""
    pad = int(20 * GAME_H / 1080)
    f_title  = pygame.font.SysFont("arial", int(52 * GAME_H / 1080), bold=True)
    f_action = pygame.font.SysFont("arial", int(42 * GAME_H / 1080), bold=True)
    f_desc   = pygame.font.SysFont("arial", int(34 * GAME_H / 1080))

    panel = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, (16, 24, 40, 235), (0, 0, *panel_rect.size), border_radius=18)
    pygame.draw.rect(panel, _CP_ACCENT, (0, 0, *panel_rect.size), 2, border_radius=18)

    y = pad
    title_s = f_title.render(title, True, (255, 255, 255))
    panel.blit(title_s, (pad, y))
    y += title_s.get_height() + pad // 2
    pygame.draw.line(panel, _CP_ACCENT, (pad, y), (panel_rect.width - pad, y), 2)
    y += int(pad * 0.8)

    indent = int(16 * GAME_H / 1080)
    max_w  = panel_rect.width - pad * 2 - indent
    for action, desc in entries:
        dot_r = max(2, f_action.get_height() // 7)
        pygame.draw.circle(panel, _CP_ACCENT, (pad + dot_r, y + f_action.get_height() // 2), dot_r)
        a_s = f_action.render(action, True, (255, 225, 140))
        panel.blit(a_s, (pad + indent, y))
        y += a_s.get_height() + 2
        for line in _wrap_text(desc, f_desc, max_w):
            d_s = f_desc.render(line, True, (222, 230, 245))
            panel.blit(d_s, (pad + indent, y))
            y += d_s.get_height() + 1
        y += int(pad * 0.45)

    surface.blit(panel, panel_rect.topleft)
