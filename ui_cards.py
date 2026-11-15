"""
Shared "state card" visual language for the patient-facing break / pause /
stopped notices (Take a Break, Game Paused, Game Stopped).

One shared drawing routine so all three stay visually consistent (same
rounded card, same navy/blue surface, same Poppins typography, same icon
treatment) without each call site re-deriving its own layout. Self-contained
(no dependency on recovr/patient_app) so games/fatigue.py -- used by BOTH the
single-process app's games and the dual-monitor patient process's wrapped
games -- can use it exactly like recovr/patient_app/game_runner.py and
recovr/patient_app/scenes/stopped.py do.
"""

import os
import pygame

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "font")

_font_cache: dict = {}

BREAK_ACCENT = (74, 163, 230)    # blue -- informational / resting
PAUSE_ACCENT = (240, 180, 41)    # amber -- held, awaiting the therapist
STOP_ACCENT  = (205, 70, 60)     # muted red -- session ended

PANEL_COLOR  = (22, 32, 58)      # soft navy card surface (fixed, both themes)


def font(name: str, size) -> pygame.font.Font:
    """A cached Poppins-family font (any .ttf in assets/font/), falling back
    to a bold system font if the file is ever missing."""
    size = max(1, int(size))
    key = (name, size)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = pygame.font.Font(os.path.join(_FONT_DIR, name), size)
        except Exception:
            f = pygame.font.SysFont("arial", size, bold=True)
        _font_cache[key] = f
    return f


_font = font   # internal alias used throughout this module


def _wrap(text: str, font: pygame.font.Font, max_w: int):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or font.size(trial)[0] <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_icon(surface, center, r, kind, accent, white=(255, 255, 255)):
    pygame.draw.circle(surface, accent, center, r)
    cx, cy = center
    if kind == "pause":
        bw = max(3, int(r * 0.24))
        bh = int(r * 0.92)
        gap = int(r * 0.22)
        for dx in (-gap // 2 - bw // 2, gap // 2 + bw // 2):
            bar = pygame.Rect(0, 0, bw, bh)
            bar.center = (cx + dx, cy)
            pygame.draw.rect(surface, white, bar, border_radius=max(1, bw // 3))
    elif kind == "stop":
        s = int(r * 1.0)
        box = pygame.Rect(0, 0, s, s)
        box.center = center
        pygame.draw.rect(surface, white, box, border_radius=max(2, int(r * 0.14)))
    else:   # "break" -- a simple resting "Zzz" glyph
        f1 = pygame.font.SysFont("arial", int(r * 0.86), bold=True)
        f2 = pygame.font.SysFont("arial", int(r * 0.56), bold=True)
        f3 = pygame.font.SysFont("arial", int(r * 0.36), bold=True)
        z1 = f1.render("Z", True, white)
        z2 = f2.render("Z", True, white)
        z3 = f3.render("Z", True, white)
        surface.blit(z1, z1.get_rect(center=(cx - r * 0.12, cy + r * 0.14)))
        surface.blit(z2, z2.get_rect(center=(cx + r * 0.26, cy - r * 0.14)))
        surface.blit(z3, z3.get_rect(center=(cx + r * 0.52, cy - r * 0.40)))


def draw_state_card(surface, *, title, subtitle, accent, kind="break", dim=True,
                     extra_lines=None, hint=None, panel_color=PANEL_COLOR,
                     title_color=(255, 255, 255), subtitle_color=(214, 223, 240)):
    """Draws the shared rounded "state" card (Take a Break / Game Paused /
    Game Stopped), centred on `surface`.

    `dim=True` darkens the surface first (for an overlay atop frozen
    gameplay -- Take a Break, Game Paused); `dim=False` leaves whatever
    background the caller already painted (the Game Stopped screen fills
    its own themed background first, matching the other patient info
    screens). `extra_lines` is an optional list of (text, color) secondary
    lines drawn below the subtitle in a smaller font (e.g. the fatigue
    overlay's "No activity detected..." context). `hint` is an optional
    single accent-colored line drawn last (e.g. the continuation prompt).
    Returns the card's Rect.
    """
    W, H = surface.get_size()

    if dim:
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((6, 10, 18, 175))
        surface.blit(ov, (0, 0))

    # Was far too wide relative to its own height (card_w up to 1.15x
    # card_h) -- a wide-short shape like that reads as cramped top-to-bottom
    # while wasting space left-to-right. card_w is fixed by the window size
    # alone (never by content), so text wrapping is always the same
    # regardless of how much vertical margin is added below -- ref_h is a
    # FIXED reference (not the final card height) that every font size,
    # the icon radius, and every inter-block gap scale from, so adding more
    # top/bottom margin can never also grow the text into wrapping harder
    # and overflowing -- it was exactly that coupling (margins and font
    # size both tied to one growing card_h) that caused the hint line to
    # spill past the card's own bottom edge the first time this was tuned.
    card_w = int(min(W * 0.52, H * 0.95))
    ref_h  = int(H * 0.56)

    icon_r = int(ref_h * 0.155)
    title_font = _font("Poppins-SemiBold.ttf", ref_h * 0.135)
    sub_font   = _font("Poppins-Regular.ttf", ref_h * 0.07)
    extra_font = _font("Poppins-Regular.ttf", ref_h * 0.052)
    hint_font  = _font("Poppins-Medium.ttf", ref_h * 0.055)
    max_text_w = int(card_w * 0.88)

    # Render every line now (so its real pixel height is known -- a font's
    # nominal point size understates its rendered height) to measure the
    # whole text block before laying anything out.
    blocks = []   # (surface, color) pairs in draw order, each with its own post-gap baked in via a sentinel None

    def _add(text, font, color, gap_before, gap_after):
        if not text:
            return
        if blocks and gap_before:
            blocks.append((None, gap_before))
        for line in _wrap(text, font, max_text_w):
            blocks.append((font.render(line, True, color), gap_after))

    _add(title, title_font, title_color, 0, int(ref_h * 0.015))
    _add(subtitle, sub_font, subtitle_color, int(ref_h * 0.03), int(ref_h * 0.018))
    if extra_lines:
        for i, (text, color) in enumerate(extra_lines):
            _add(text, extra_font, color, int(ref_h * 0.025) if i == 0 else 0, int(ref_h * 0.012))
    _add(hint, hint_font, accent, int(ref_h * 0.03), 0)
    text_h = sum((s.get_height() if s is not None else gap) for s, gap in blocks)

    # The card's own height is DERIVED from its content plus these two
    # explicit margins, rather than the other way around -- guarantees
    # real breathing room top and bottom, by construction, instead of a
    # fixed fraction that different amounts of content could overflow.
    top_margin    = int(H * 0.05)
    icon_gap      = int(ref_h * 0.095)   # icon bottom -> first text line
    bottom_margin = int(H * 0.075)
    card_h = top_margin + icon_r * 2 + icon_gap + text_h + bottom_margin
    card_w = max(card_w, int(ref_h * 1.3))   # stay sensible if content is short

    card = pygame.Rect(0, 0, card_w, card_h)
    card.center = (W // 2, H // 2)

    shadow = pygame.Surface((card.width + 24, card.height + 24), pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, 90), shadow.get_rect(), border_radius=int(ref_h * 0.12))
    surface.blit(shadow, (card.x - 12, card.y - 4))

    radius = int(ref_h * 0.11)
    pygame.draw.rect(surface, panel_color, card, border_radius=radius)
    pygame.draw.rect(surface, accent, card, max(2, int(ref_h * 0.012)), border_radius=radius)

    icon_cy = card.top + top_margin + icon_r
    _draw_icon(surface, (card.centerx, icon_cy), icon_r, kind, accent)

    ty = icon_cy + icon_r + icon_gap
    for s, gap in blocks:
        if s is None:
            ty += gap
            continue
        surface.blit(s, s.get_rect(midtop=(card.centerx, ty)))
        ty += s.get_height() + gap

    return card
