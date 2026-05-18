# =============================================================================
# scenes/icon_renderer.py
# =============================================================================
# Shared utility for drawing profile icons consistently across all scenes.
# Import and call draw_icon() wherever you need to render a profile circle.
#
# HOW TO USE:
#   from scenes.icon_renderer import draw_icon, ICONS
#   draw_icon(surface, icon_index, center_x, center_y, radius)
# =============================================================================

import pygame

# --- ICON PALETTE ---
# 10 icons total (indices 1-10). Index 0 = empty/unselected.
# Each entry: (background_color, symbol_character, symbol_color)
# To replace with image files later: swap draw_icon() to blit a Surface instead.
ICONS = {
    0:  ((200, 205, 215), "?",  (255, 255, 255)),   # unselected / fallback
    1:  ((100, 180, 240), "♥",  (255, 255, 255)),   # sky blue   — heart
    2:  ((130, 200, 140), "✦",  (255, 255, 255)),   # sage green — spark
    3:  ((240, 165, 90),  "★",  (255, 255, 255)),   # amber      — star
    4:  ((190, 130, 220), "♦",  (255, 255, 255)),   # lavender   — diamond
    5:  ((235, 100, 120), "✿",  (255, 255, 255)),   # rose       — flower
    6:  (( 80, 195, 195), "▲",  (255, 255, 255)),   # teal       — triangle
    7:  ((240, 180, 100), "●",  (255, 255, 255)),   # gold       — circle
    8:  ((100, 140, 220), "♠",  (255, 255, 255)),   # indigo     — spade
    9:  ((200,  90, 130), "✱",  (255, 255, 255)),   # raspberry  — burst
    10: (( 90, 180, 130), "⬟",  (255, 255, 255)),   # emerald    — pentagon
}

# Pre-built font cache so we don't recreate fonts on every draw call.
# Keys are font sizes; populated lazily on first use.
_font_cache = {}


def _get_font(size):
    if size not in _font_cache:
        _font_cache[size] = pygame.font.SysFont("segoeuisymbol", size)
    return _font_cache[size]


def draw_icon(surface, icon_index, cx, cy, radius,
              shadow=True, border_color=None, border_width=0):
    """
    Draws a circular profile icon onto `surface`.

    Parameters:
        surface      : pygame.Surface to draw onto
        icon_index   : int 0-10 (0 = empty placeholder)
        cx, cy       : center pixel coordinates
        radius       : circle radius in pixels
        shadow       : if True, draws a subtle drop shadow below the circle
        border_color : if not None, draws a border ring around the circle
        border_width : width of the border ring in pixels
    """
    icon_index = max(0, min(10, icon_index))
    bg_color, symbol, sym_color = ICONS[icon_index]

    # Shadow
    if shadow:
        shadow_col = tuple(max(0, c - 45) for c in bg_color)
        shadow_off = max(3, radius // 18)
        pygame.draw.circle(surface, shadow_col, (cx, cy + shadow_off), radius)

    # Main circle
    pygame.draw.circle(surface, bg_color, (cx, cy), radius)

    # Border ring
    if border_color and border_width > 0:
        pygame.draw.circle(surface, border_color, (cx, cy), radius, border_width)

    # Symbol
    font_size = max(10, int(radius * 0.85))
    font      = _get_font(font_size)
    sym_surf  = font.render(symbol, True, sym_color)
    surface.blit(sym_surf, sym_surf.get_rect(center=(cx, cy)))


def get_icon_color(icon_index):
    """Returns the background color tuple for a given icon_index."""
    return ICONS.get(icon_index, ICONS[0])[0]