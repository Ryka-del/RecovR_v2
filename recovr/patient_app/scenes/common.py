"""
Shared look-and-feel helpers for the patient-facing information screens
(welcome / waiting / instructions / session end / calibrating).

These screens are plain: fill a background, stack some centred lines of text.
Kept separate from the games -- games own their own rendering entirely.
"""

import os
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


_grad_cache: dict = {}
_bg_img_cache: dict = {}


def recovr_gradient(w: int, h: int) -> pygame.Surface:
    """The background behind the Waiting Screen and the patient Dashboard --
    one shared implementation so both screens stay visually identical instead
    of drifting apart. Uses the uploaded pd_bg_light.png / pd_bg_dark.png
    artwork (scaled to fill exactly w x h) for the active theme, falling
    back to the programmatic pastel gradient below only if that asset is
    ever missing."""
    dark = PALETTE["bg"][0] < 40
    img = _pd_bg_image(w, h, dark)
    if img is not None:
        return img
    key = (w, h, dark)
    g = _grad_cache.get(key)
    if g is not None:
        return g
    sw, sh = max(2, w // 6), max(2, h // 6)
    s = pygame.Surface((sw, sh)).convert()
    if dark:
        white, pblue, ppurp = (24, 26, 40), (26, 40, 74), (44, 28, 66)
    else:
        white, pblue, ppurp = (255, 255, 255), (185, 215, 255), (225, 185, 255)
    wf = sw * 0.75
    for y in range(sh):
        for x in range(sw):
            wb = max(0.0, 1.0 - (x + y) / wf)
            wp = max(0.0, 1.0 - ((sw - x) + (sh - y)) / wf)
            tc = wb + wp
            if tc > 1.0:
                wb /= tc; wp /= tc; ww = 0.0
            else:
                ww = 1.0 - tc
            s.set_at((x, y), (
                min(255, int(pblue[0] * wb + ppurp[0] * wp + white[0] * ww)),
                min(255, int(pblue[1] * wb + ppurp[1] * wp + white[1] * ww)),
                min(255, int(pblue[2] * wb + ppurp[2] * wp + white[2] * ww))))
    g = pygame.transform.smoothscale(s, (w, h))
    if len(_grad_cache) > 6:
        _grad_cache.clear()
    _grad_cache[key] = g
    return g


def _pd_bg_image(w: int, h: int, dark: bool):
    """The uploaded pd_bg_light.png / pd_bg_dark.png background artwork for
    the active theme, scaled to fill exactly w x h and cached per (w, h,
    dark). Returns None (silently) if the file is missing, so
    recovr_gradient() falls back to the programmatic gradient instead of
    crashing."""
    key = (w, h, dark)
    img = _bg_img_cache.get(key)
    if img is None and key not in _bg_img_cache:
        name = "pd_bg_dark.png" if dark else "pd_bg_light.png"
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert()
            img = pygame.transform.smoothscale(raw, (w, h))
        except Exception:
            img = None
        if len(_bg_img_cache) > 6:
            _bg_img_cache.clear()
        _bg_img_cache[key] = img
    return img


def fit_font(make_font, text, max_w, max_h, lo=8, hi=400):
    """Largest font from `make_font(px)` whose `text` fits max_w x max_h.
    Identical technique to scenes/therapist_welcome.py's `_fit_font`."""
    best = make_font(lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = make_font(mid)
        w, h = f.size(text)
        if w <= max_w and h <= max_h:
            best, lo = f, mid + 1
        else:
            hi = mid - 1
    return best


_wordmark_font_cache: dict = {}


def draw_recovr_wordmark(surface: pygame.Surface, center_x: int, top_y: int,
                          box_w: int, box_h: int) -> int:
    """The existing RecovR wordmark from the therapist Welcome page, reused
    verbatim: arialblack, two-tone 'Recov' (white) + 'R' (red), black outline.
    Not the reference image's hand icon, not a new logo. Returns the y just
    below the rendered wordmark so callers can lay out what comes next."""
    key = (box_w, box_h)
    font = _wordmark_font_cache.get(key)
    if font is None:
        font = fit_font(lambda px: pygame.font.SysFont("arialblack", px), "RecovR", box_w, box_h)
        if len(_wordmark_font_cache) > 6:
            _wordmark_font_cache.clear()
        _wordmark_font_cache[key] = font

    part1, part2 = "Recov", "R"
    COLOR_WHITE, COLOR_RED, COLOR_OUTLINE = (255, 255, 255), (220, 40, 40), (0, 0, 0)
    tw1, th = font.size(part1)
    tw2, _ = font.size(part2)
    start_x = center_x - (tw1 + tw2) // 2
    o = max(2, int(th * 0.035))

    def draw_outlined(text, x, color):
        for dx in (-o, 0, o):
            for dy in (-o, 0, o):
                if dx or dy:
                    surface.blit(font.render(text, True, COLOR_OUTLINE), (x + dx, top_y + dy))
        surface.blit(font.render(text, True, color), (x, top_y))

    draw_outlined(part1, start_x, COLOR_WHITE)
    draw_outlined(part2, start_x + tw1, COLOR_RED)
    return top_y + th


def draw_glass_card(surface: pygame.Surface, rect: pygame.Rect, radius_frac: float = 0.09,
                     fill_alpha: int = 26, border_alpha: int = 120, shadow_alpha: int = 16,
                     fill_color=(255, 255, 255), border_color=(255, 255, 255),
                     shadow_color=(20, 24, 40), alpha_scale: float = 1.0,
                     glow_alpha: int = 0, glow_color=(255, 255, 255), glow_layers: int = 4,
                     glow_spread_frac: float = 0.05) -> int:
    """The shared frosted-glass card shell (soft single shadow + low-alpha
    translucent fill + a brighter hairline border) used by both the Waiting
    Screen and the patient Dashboard, so the two stay visually consistent
    without either one copying the other's drawing code. Returns the corner
    radius used, in case a caller needs it for inner-content layout.

    `glow_alpha` (0 by default, i.e. no change for existing callers) adds a
    soft outward white halo -- several progressively larger, progressively
    fainter rounded-rect outlines drawn before the shadow/fill, approximating
    a blur with no blur filter available. Opt-in only: the patient Dashboard's
    existing draw_glass_card() calls pass no glow and render exactly as
    before."""
    H = surface.get_height()
    rad = max(6, int(rect.height * radius_frac))

    if glow_alpha > 0:
        step = max(2, int(rect.height * glow_spread_frac / glow_layers))
        for i in range(glow_layers, 0, -1):
            gr = rect.inflate(step * i * 2, step * i * 2)
            a = max(0, int(glow_alpha * alpha_scale * (i / glow_layers) * 0.5))
            if a <= 0:
                continue
            gl = pygame.Surface((gr.width, gr.height), pygame.SRCALPHA)
            pygame.draw.rect(gl, (*glow_color, a), gl.get_rect(), border_radius=rad + step * i)
            surface.blit(gl, gr.topleft)

    sr = rect.inflate(int(rect.height * 0.03), int(rect.height * 0.03)).move(0, int(rect.height * 0.025))
    sh = pygame.Surface((sr.width, sr.height), pygame.SRCALPHA)
    pygame.draw.rect(sh, (*shadow_color, max(0, int(shadow_alpha * alpha_scale))),
                     sh.get_rect(), border_radius=rad + 4)
    surface.blit(sh, sr.topleft)

    card = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(card, (*fill_color, max(0, int(fill_alpha * alpha_scale))),
                     card.get_rect(), border_radius=rad)
    pygame.draw.rect(card, (*border_color, max(0, int(border_alpha * alpha_scale))),
                     card.get_rect(), max(1, int(H * 0.0022)), border_radius=rad)
    surface.blit(card, rect.topleft)
    return rad


_IMG_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "assets", "images"))
_sprite_raw_cache: dict = {}
_sprite_scaled_cache: dict = {}


def sprite(name: str, size: int, crop: bool = False):
    """A square illustration from assets/images/, scaled uniformly to
    `size x size` (never distorted). Shared by the Waiting Screen and the
    patient Dashboard so both draw the exact same asset-loading path.

    `crop` (opt-in, False by default so the patient Dashboard's own sprite()
    calls render exactly as before) first crops to the asset's own opaque
    bounding box before scaling -- several of the waiting-screen illustrations
    ship with a lot of transparent canvas padding, which otherwise makes the
    actual artwork look much smaller than the requested `size` once scaled.
    The cropped content is fit (not stretched) and centred on a transparent
    size x size canvas, so callers that position this square by its edges
    (e.g. icon_rect midleft) see no difference in behaviour."""
    size = max(1, int(size))
    key = (name, size, crop)
    img = _sprite_scaled_cache.get(key)
    if img is None:
        raw = _sprite_raw_cache.get(name)
        if name not in _sprite_raw_cache:
            try:
                raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            except Exception:
                raw = None
            _sprite_raw_cache[name] = raw
        if raw is None:
            return None
        if crop:
            bbox = raw.get_bounding_rect(min_alpha=10)
            content = raw.subsurface(bbox).copy() if bbox.width and bbox.height else raw
            cw, ch = content.get_size()
            scale = size / max(cw, ch)
            sw, sh = max(1, int(cw * scale)), max(1, int(ch * scale))
            scaled = pygame.transform.smoothscale(content, (sw, sh))
            img = pygame.Surface((size, size), pygame.SRCALPHA)
            img.blit(scaled, ((size - sw) // 2, (size - sh) // 2))
        else:
            img = pygame.transform.smoothscale(raw, (size, size))
        _sprite_scaled_cache[key] = img
        if len(_sprite_scaled_cache) > 32:
            _sprite_scaled_cache.clear()
    return img


def _ease_in_out_carousel(p):   # smoothstep -- symmetric accelerate/decelerate
    p = max(0.0, min(1.0, p))
    return p * p * (3.0 - 2.0 * p)


def carousel_frame(t: int, w: int, card_w: int, n: int = 1, *,
                    hold_ms: int = 3200, transition_ms: int = 900, margin_frac: float = 0.06):
    """The Waiting Screen's endless hold -> synchronized swipe motion, shared
    so any screen can show a card 'moving just like the Waiting Screen'
    without re-deriving or copying the timing/easing math.

    While holding, only the current card is drawn, centred. During a
    transition, the outgoing card (sliding centre -> fully off-screen-left)
    and the incoming card (sliding fully off-screen-right -> centre) use the
    SAME progress `p` and the SAME ease-in-out curve, so they move at
    identical speed and stay a constant horizontal distance apart -- a clean
    linked swap, never two independently-timed cards that can linger near
    each other at once (that mismatch used to let a mostly-arrived incoming
    card overlap an outgoing card that had barely started leaving).

    Returns a list of (item_index, center_x, alpha) for the 1-2 card
    instances to draw "now" -- alpha is always 1.0 (no fade: a card is either
    not yet on-screen, visibly sliding, or has fully left, so hiding it via
    alpha was never actually needed and caller-side clipping covers the
    rest). `t` is elapsed ms since that screen's own t0; `w`/`card_w` are in
    the same coordinate space the caller will draw in."""
    cycle = max(1, hold_ms + transition_ms)
    margin = int(w * margin_frac)
    off_left_cx  = -card_w // 2 - margin
    off_right_cx = w + card_w // 2 + margin
    cx = w // 2
    n = max(1, n)

    j = t // cycle
    local = t - j * cycle
    cur_idx = int(j % n)

    if local < hold_ms:
        return [(cur_idx, cx, 1.0)]

    p = _ease_in_out_carousel((local - hold_ms) / transition_ms)
    nxt_idx = int((j + 1) % n)
    old_x = cx + (off_left_cx - cx) * p
    new_x = off_right_cx + (cx - off_right_cx) * p
    return [(cur_idx, int(old_x), 1.0), (nxt_idx, int(new_x), 1.0)]


def icon_text_geometry(rect: pygame.Rect, pad_x_frac: float = 0.04, pad_y_frac: float = 0.065,
                        icon_frac: float = 0.94, gap_frac: float = 0.045, has_icon: bool = True):
    """Where the icon and text go in an icon-left/text-right card, WITHOUT
    drawing anything -- callers that need to wrap/size their text before
    rendering (the Waiting Screen shrinks its font to fit) call this first,
    then draw_icon_text_card() with the same fractions for the actual paint."""
    pad_x = int(rect.width * pad_x_frac)
    pad_y = int(rect.height * pad_y_frac)
    inner_h = rect.height - 2 * pad_y
    icon_size = int(inner_h * icon_frac)
    if has_icon:
        text_left = rect.left + pad_x + icon_size + int(rect.width * gap_frac)
    else:
        text_left = rect.left + pad_x
    text_max_w = max(20, rect.right - pad_x - text_left)
    return icon_size, text_left, text_max_w


def draw_icon_text_card(surface: pygame.Surface, rect: pygame.Rect, sprite_name: str | None,
                         text_items: list, *, radius_frac: float = 0.09, pad_x_frac: float = 0.04,
                         pad_y_frac: float = 0.065, icon_frac: float = 0.94, gap_frac: float = 0.045,
                         line_gap_frac: float = 0.26, fill_alpha: int = 26, border_alpha: int = 120,
                         shadow_alpha: int = 16, alpha_scale: float = 1.0,
                         glow_alpha: int = 0, icon_bg_color: tuple | None = None,
                         icon_bg_scale: float = 1.32, divider_color: tuple | None = None,
                         divider_inset_frac: float = 0.16, divider_width: int = 2):
    """The Waiting Screen's "[ LARGE SPRITE ] [ text ]" instruction card,
    shared so any screen can show the same icon-text combination without
    copying the layout: a frosted glass shell (draw_glass_card), a large
    sprite on the left, and a stacked text block on the right, both vertically
    centred on the card so they read as one unit.

    `text_items` is a list of (white_surface, color) pairs -- render each
    line's text in WHITE first (font.render(text, True, (255,255,255))); the
    multiply-tint here reproduces `color` exactly and adds the same faint
    legibility shadow the Waiting Screen uses, so callers can mix fonts/colors
    per line (e.g. a bold accent-coloured line among plain ones) while still
    sharing the actual drawing code. Returns the icon's on-screen rect (or
    None if there was no sprite).

    `icon_bg_color` (opt-in, None by default) draws a pale circle behind the
    sprite, `divider_color` (opt-in, None by default) draws a thin vertical
    rule between the icon and the text column inset from the card's own top
    /bottom edges -- both match the Waiting Screen's card reference and are
    no-ops for any other existing caller that doesn't pass them."""
    H = surface.get_height()
    draw_glass_card(surface, rect, radius_frac=radius_frac, fill_alpha=fill_alpha,
                    border_alpha=border_alpha, shadow_alpha=shadow_alpha, alpha_scale=alpha_scale,
                    glow_alpha=glow_alpha)

    icon_size, text_left, _ = icon_text_geometry(
        rect, pad_x_frac, pad_y_frac, icon_frac, gap_frac, has_icon=bool(sprite_name))

    icon_rect = None
    if sprite_name:
        pad_x = int(rect.width * pad_x_frac)

        if icon_bg_color is not None:
            d = int(icon_size * icon_bg_scale)
            a = max(0, min(255, int((icon_bg_color[3] if len(icon_bg_color) > 3 else 255) * alpha_scale)))
            circ = pygame.Surface((d, d), pygame.SRCALPHA)
            pygame.draw.circle(circ, (*icon_bg_color[:3], a), (d // 2, d // 2), d // 2)
            surface.blit(circ, circ.get_rect(center=(rect.left + pad_x + icon_size // 2, rect.centery)))

        spr = sprite(sprite_name, icon_size, crop=True)
        if spr is not None:
            if alpha_scale < 1.0:
                spr = spr.copy()
                spr.fill((255, 255, 255, max(0, min(255, int(255 * alpha_scale)))),
                         special_flags=pygame.BLEND_RGBA_MULT)
            icon_rect = spr.get_rect(midleft=(rect.left + pad_x, rect.centery))
            surface.blit(spr, icon_rect)

    if divider_color is not None and sprite_name:
        icon_right = rect.left + int(rect.width * pad_x_frac) + icon_size
        dx = (icon_right + text_left) // 2
        inset = int(rect.height * divider_inset_frac)
        a = max(0, min(255, int((divider_color[3] if len(divider_color) > 3 else 255) * alpha_scale)))
        dv = pygame.Surface((divider_width, rect.height - inset * 2), pygame.SRCALPHA)
        dv.fill((*divider_color[:3], a))
        surface.blit(dv, (dx, rect.top + inset))

    if not text_items:
        return icon_rect

    line_gap = int(text_items[0][0].get_height() * line_gap_frac)
    total = sum(s.get_height() for s, _ in text_items) + line_gap * (len(text_items) - 1)
    y = rect.centery - total // 2
    a = max(0, min(255, int(255 * alpha_scale)))
    shadow_a = max(0, min(255, int(90 * alpha_scale)))
    for s, color in text_items:
        shadow = s.copy()
        shadow.fill((10, 12, 20, 255), special_flags=pygame.BLEND_RGBA_MULT)
        shadow.fill((255, 255, 255, shadow_a), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(shadow, shadow.get_rect(
            midleft=(text_left, y + s.get_height() // 2)).move(0, max(1, int(H * 0.0025))))

        tint = s.copy()
        tint.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        if a < 255:
            tint.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(tint, tint.get_rect(midleft=(text_left, y + s.get_height() // 2)))
        y += s.get_height() + line_gap
    return icon_rect


def draw_progress(surface: pygame.Surface, frac: float, y_frac: float = 0.62):
    frac = max(0.0, min(1.0, frac))
    w, h = surface.get_size()
    bar_w = int(w * 0.5)
    bar_h = max(10, h // 60)
    x = (w - bar_w) // 2
    y = int(h * y_frac)
    pygame.draw.rect(surface, PALETTE["panel"], (x, y, bar_w, bar_h), border_radius=bar_h // 2)
    pygame.draw.rect(surface, PALETTE["accent"], (x, y, int(bar_w * frac), bar_h), border_radius=bar_h // 2)
