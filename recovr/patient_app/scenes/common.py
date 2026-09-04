"""
Shared look-and-feel helpers for the patient-facing information screens
(welcome / waiting / instructions / session end / calibrating).

These screens are plain: fill a background, stack some centred lines of text.
Kept separate from the games -- games own their own rendering entirely.
"""

import pygame

# The patient info screens follow the SAME light/dark theme as the games:
# constants.get_theme() (driven by constants.set_dark_mode(), which patient_main
# keeps in sync with the therapist's choice). PALETTE is a live view of it, so no
# scene file needs to change. Falls back to the original dark values if constants
# is unavailable (keeps the prototype identical).
try:
    from constants import get_theme as _get_theme
except Exception:                       # pragma: no cover
    _get_theme = None

_DARK_FALLBACK = {
    "bg":     (14, 18, 28),
    "panel":  (27, 35, 50),
    "text":   (219, 228, 243),
    "muted":  (133, 149, 176),
    "accent": (74, 163, 230),
    "good":   (55, 201, 122),
    "warn":   (240, 180, 41),
    "bad":    (230, 88, 74),
}
_THEME_MAP = {
    "bg": "BG", "panel": "PANEL", "text": "TEXT", "muted": "GRAY",
    "accent": "ACCENT", "good": "GREEN", "warn": "YELLOW", "bad": "RED",
}


class _Palette:
    def __getitem__(self, key):
        if _get_theme is not None:
            try:
                return _get_theme()[_THEME_MAP[key]]
            except Exception:
                pass
        return _DARK_FALLBACK[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except Exception:
            return default


PALETTE = _Palette()

_font_cache: dict = {}


def font(size: int, bold: bool = True) -> pygame.font.Font:
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = pygame.font.SysFont("consolas,dejavusansmono,monospace", size, bold=bold)
    return _font_cache[key]


def fill_bg(surface: pygame.Surface):
    surface.fill(PALETTE["bg"])
    # thin accent strip along the top so the screen never looks "dead"
    w = surface.get_width()
    pygame.draw.rect(surface, PALETTE["panel"], (0, 0, w, 6))
    pygame.draw.rect(surface, PALETTE["accent"], (0, 0, int(w * 0.28), 6))


def draw_lines(surface: pygame.Surface, lines, top_frac: float = 0.5):
    """Draw a vertical stack of centred lines.

    `lines` is a list of (text, size, color) tuples. The stack is vertically
    centred on `top_frac` of the surface height.
    """
    rendered = [(font(sz).render(txt, True, col), sz) for (txt, sz, col) in lines]
    gap = 16
    total_h = sum(s.get_height() for s, _ in rendered) + gap * (len(rendered) - 1)
    cx = surface.get_width() // 2
    y = int(surface.get_height() * top_frac) - total_h // 2
    for surf, _ in rendered:
        surface.blit(surf, surf.get_rect(midtop=(cx, y)))
        y += surf.get_height() + gap


def draw_banner(surface: pygame.Surface, text: str, color=None):
    """A full-width strip at the bottom -- used for the 'reconnecting' notice."""
    color = color or PALETTE["bad"]
    w, h = surface.get_size()
    strip_h = max(34, h // 18)
    strip = pygame.Surface((w, strip_h), pygame.SRCALPHA)
    strip.fill((*color, 40))
    surface.blit(strip, (0, h - strip_h))
    pygame.draw.line(surface, color, (0, h - strip_h), (w, h - strip_h), 2)
    label = font(max(16, strip_h // 2)).render(text, True, color)
    surface.blit(label, label.get_rect(center=(w // 2, h - strip_h // 2)))


def draw_progress(surface: pygame.Surface, frac: float, y_frac: float = 0.62):
    frac = max(0.0, min(1.0, frac))
    w, h = surface.get_size()
    bar_w = int(w * 0.5)
    bar_h = max(10, h // 60)
    x = (w - bar_w) // 2
    y = int(h * y_frac)
    pygame.draw.rect(surface, PALETTE["panel"], (x, y, bar_w, bar_h), border_radius=bar_h // 2)
    pygame.draw.rect(surface, PALETTE["accent"], (x, y, int(bar_w * frac), bar_h), border_radius=bar_h // 2)
