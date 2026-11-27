"""
Shared "Round Complete" result-card overlay.

Every game that ships dedicated artwork loads its own
<prefix>_round_complete_{dark/light}.png -- title, wreath/game icon, stars
and "You are awesome!" are all baked into that image (see
assets/images/basketball_round_complete_light.png and the attached
round_complete_sample.png reference) -- and only needs to overlay the two
LIVE values the art leaves blank: elapsed TIME (left side of the bottom
panel) and the game's own SCORE/completed-count (right side). One shared
implementation here, used by every game.
"""

import pygame

from constants import GAME_W, GAME_H, is_dark_mode

# This overlay draws every frame for as long as the results screen is up.
# The dim layer is always the same GAME_W x GAME_H fill, and the number
# font only ever takes a handful of distinct sizes (one per card aspect
# ratio) -- cache both instead of rebuilding them every frame.
_dim_overlay = None
_mono_font_cache: dict = {}


def _get_dim_overlay():
    global _dim_overlay
    if _dim_overlay is None:
        _dim_overlay = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        _dim_overlay.fill((0, 0, 0, 185))
    return _dim_overlay


def get_mono_font(size):
    """Cached bold monospace font, shared by this overlay's own number
    labels and every game's Again/Exit results buttons -- one cache,
    keyed by size."""
    f = _mono_font_cache.get(size)
    if f is None:
        f = pygame.font.SysFont("monospace", size, bold=True)
        _mono_font_cache[size] = f
    return f


_get_num_font = get_mono_font   # internal alias used below


def draw_round_complete_overlay(surface, *, card_prefix, duration_sec, score_text,
                                 load_fit, dim=True):
    """Dims the game behind it (unless dim=False -- the caller already dimmed),
    loads <card_prefix>_round_complete_{dark/light}.png, and overlays the
    elapsed time (left slot) / score (right slot) into the card's own blank
    areas. `load_fit` is the CALLER's own asset-loading helper (every game
    defines an equivalent `_load_fit`/`_load_image_fit` that crops to opaque
    content then scales to fit preserving aspect ratio) -- passed in rather
    than imported here, so this has no dependency on which module defines it
    or how its cache is keyed.

    Returns (card_rect_or_None, bottom_y): bottom_y is GAME_H // 2 when the
    asset is missing, matching every game's own prior fallback so a caller's
    button-row layout below the card is unaffected either way.
    """
    if dim:
        surface.blit(_get_dim_overlay(), (0, 0))

    card_name = f"{card_prefix}_round_complete_{'dark' if is_dark_mode() else 'light'}.png"
    top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
    card = load_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
    if card is None:
        return None, GAME_H // 2

    # Centered on screen -- same box size as the How To Play card (see each
    # game's own _draw_instructions), so the two screens read as the same
    # size/placement, just different content.
    cr = card.get_rect(center=(GAME_W // 2, GAME_H // 2))
    surface.blit(card, cr)

    num_col = (255, 255, 255) if not is_dark_mode() else (20, 80, 150)
    # Large headline font for the two live numbers the card's own artwork
    # leaves blank, per the reference design.
    f_num = _get_num_font(max(18, int(cr.height * 0.10)))

    mins, secs = divmod(max(0, int(duration_sec)), 60)
    time_s = f_num.render(f"{mins:02d}:{secs:02d}", True, num_col)
    surface.blit(time_s, time_s.get_rect(
        center=(cr.x + int(cr.width * 0.195), cr.y + int(cr.height * 0.80))))

    score_s = f_num.render(str(score_text), True, num_col)
    surface.blit(score_s, score_s.get_rect(
        center=(cr.x + int(cr.width * 0.81), cr.y + int(cr.height * 0.80))))

    return cr, cr.bottom
