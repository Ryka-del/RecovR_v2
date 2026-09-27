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

import os
import pygame

# --- ICON PALETTE ---
# 12 icons total (indices 1-12), one PNG each from assets/images/ (uploaded
# as therapis_profile_icon_1.png .. therapis_profile_icon_12.png). Index 0 =
# empty/unselected placeholder, drawn as a plain circle (no source image).
# A flat background colour is kept per icon (ICONS / get_icon_color) for
# styling elsewhere (e.g. list accents) that still wants a plain colour
# rather than the illustration itself.
ICONS = {
    0:  (200, 205, 215),   # unselected / fallback
    1:  (240, 200,  70),   # star
    2:  (100, 180, 240),
    3:  (130, 200, 140),
    4:  (190, 130, 220),
    5:  (235, 100, 120),
    6:  ( 80, 195, 195),
    7:  (240, 180, 100),
    8:  (100, 140, 220),
    9:  (200,  90, 130),
    10: ( 90, 180, 130),
    11: (220,  40,  40),
    12: (240, 130,  30),
}

_IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "images")
_icon_img_cache: dict = {}


def _icon_image(icon_index, diameter):
    """The therapis_profile_icon_N.png source, scaled to `diameter` and
    cached. Returns None for index 0 (placeholder) or a missing file."""
    if icon_index < 1:
        return None
    key = (icon_index, diameter)
    im = _icon_img_cache.get(key)
    if im is None and key not in _icon_img_cache:
        path = os.path.join(_IMG_DIR, f"therapis_profile_icon_{icon_index}.png")
        try:
            raw = pygame.image.load(path).convert_alpha()
            im = pygame.transform.smoothscale(raw, (diameter, diameter))
        except Exception:
            im = None
        _icon_img_cache[key] = im
    return im


def draw_icon(surface, icon_index, cx, cy, radius,
              shadow=True, border_color=None, border_width=0):
    """
    Draws a circular profile icon onto `surface`.

    Parameters:
        surface      : pygame.Surface to draw onto
        icon_index   : int 0-12 (0 = empty placeholder)
        cx, cy       : center pixel coordinates
        radius       : circle radius in pixels
        shadow       : if True, draws a subtle drop shadow below the circle
        border_color : if not None, draws a border ring around the circle
        border_width : width of the border ring in pixels
    """
    icon_index = max(0, min(12, icon_index))
    bg_color = ICONS[icon_index]

    # Shadow
    if shadow:
        shadow_col = tuple(max(0, c - 45) for c in bg_color)
        shadow_off = max(3, radius // 18)
        pygame.draw.circle(surface, shadow_col, (cx, cy + shadow_off), radius)

    img = _icon_image(icon_index, radius * 2)
    if img is not None:
        surface.blit(img, img.get_rect(center=(cx, cy)))
    else:
        # Placeholder (index 0) or a missing asset -- a plain filled circle
        # degrades gracefully instead of crashing.
        pygame.draw.circle(surface, bg_color, (cx, cy), radius)
        if icon_index == 0:
            font = pygame.font.SysFont("segoeuisymbol", max(10, int(radius * 0.85)))
            qs = font.render("?", True, (255, 255, 255))
            surface.blit(qs, qs.get_rect(center=(cx, cy)))

    # Border ring
    if border_color and border_width > 0:
        pygame.draw.circle(surface, border_color, (cx, cy), radius, border_width)


def get_icon_color(icon_index):
    """Returns the background/accent colour tuple for a given icon_index."""
    return ICONS.get(icon_index, ICONS[0])
