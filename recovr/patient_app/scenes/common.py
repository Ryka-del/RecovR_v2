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
    of drifting apart. Light theme uses the uploaded pd_bg.png artwork
    (scaled to fill exactly w x h); dark theme keeps the programmatic pastel
    gradient below, since no dark variant of that artwork exists and the
    light image would look washed out/out of place there."""
    dark = PALETTE["bg"][0] < 40
    if not dark:
        img = _pd_bg_image(w, h)
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


def _pd_bg_image(w: int, h: int):
    """The uploaded pd_bg.png background artwork, scaled to fill exactly
    w x h and cached. Returns None (silently) if the file is missing, so
    recovr_gradient() falls back to the programmatic gradient instead of
    crashing."""
    key = (w, h)
    img = _bg_img_cache.get(key)
    if img is None and key not in _bg_img_cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, "pd_bg.png")).convert()
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
                     shadow_color=(20, 24, 40), alpha_scale: float = 1.0) -> int:
    """The shared frosted-glass card shell (soft single shadow + low-alpha
    translucent fill + a brighter hairline border) used by both the Waiting
    Screen and the patient Dashboard, so the two stay visually consistent
    without either one copying the other's drawing code. Returns the corner
    radius used, in case a caller needs it for inner-content layout."""
    H = surface.get_height()
    rad = max(6, int(rect.height * radius_frac))

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


def sprite(name: str, size: int):
    """A square illustration from assets/images/, scaled uniformly to
    `size x size` (never distorted). Shared by the Waiting Screen and the
    patient Dashboard so both draw the exact same asset-loading path."""
    size = max(1, int(size))
    key = (name, size)
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
        img = pygame.transform.smoothscale(raw, (size, size))
        _sprite_scaled_cache[key] = img
        if len(_sprite_scaled_cache) > 32:
            _sprite_scaled_cache.clear()
    return img


def _ease_out_carousel(p):   # decelerate into the centre
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def _ease_in_carousel(p):    # accelerate out of the centre
    p = max(0.0, min(1.0, p))
    return p ** 3


def carousel_frame(t: int, w: int, card_w: int, n: int = 1, *,
                    enter_ms: int = 950, hold_ms: int = 3200, exit_ms: int = 950,
                    overlap_ms: int = 650, margin_frac: float = 0.06):
    """The Waiting Screen's endless slide-in -> hold -> slide-out motion,
    shared so any screen can show a card 'moving just like the Waiting
    Screen' without re-deriving or copying the timing/easing math.

    Returns a list of (item_index, center_x, alpha) for the 1-2 card
    instances that should be drawn "now" (an entering one can overlap a
    still-exiting one). `t` is elapsed ms since that screen's own t0;
    `w`/`card_w` are in the same coordinate space the caller will draw in."""
    span = enter_ms + hold_ms + exit_ms
    cycle = max(1, span - overlap_ms)
    margin = int(w * margin_frac)
    off_left_cx  = -card_w // 2 - margin
    off_right_cx = w + card_w // 2 + margin
    cx = w // 2
    j_now = t // cycle
    n = max(1, n)

    out = []
    for j in (j_now - 1, j_now):
        if j < 0:
            continue
        local = t - j * cycle
        if local < 0 or local >= span:
            continue
        if local < enter_ms:
            p = _ease_out_carousel(local / enter_ms)
            x = off_right_cx + (cx - off_right_cx) * p
            a = min(1.0, local / 240.0)
        elif local < enter_ms + hold_ms:
            x, a = cx, 1.0
        else:
            p = _ease_in_carousel((local - enter_ms - hold_ms) / exit_ms)
            x = cx + (off_left_cx - cx) * p
            a = max(0.0, 1.0 - (local - enter_ms - hold_ms) / exit_ms)
        if a <= 0.01:
            continue
        out.append((int(j % n), int(x), a))
    return out


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
                         shadow_alpha: int = 16, alpha_scale: float = 1.0):
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
    None if there was no sprite)."""
    H = surface.get_height()
    draw_glass_card(surface, rect, radius_frac=radius_frac, fill_alpha=fill_alpha,
                    border_alpha=border_alpha, shadow_alpha=shadow_alpha, alpha_scale=alpha_scale)

    icon_size, text_left, _ = icon_text_geometry(
        rect, pad_x_frac, pad_y_frac, icon_frac, gap_frac, has_icon=bool(sprite_name))

    icon_rect = None
    if sprite_name:
        pad_x = int(rect.width * pad_x_frac)
        spr = sprite(sprite_name, icon_size)
        if spr is not None:
            if alpha_scale < 1.0:
                spr = spr.copy()
                spr.fill((255, 255, 255, max(0, min(255, int(255 * alpha_scale)))),
                         special_flags=pygame.BLEND_RGBA_MULT)
            icon_rect = spr.get_rect(midleft=(rect.left + pad_x, rect.centery))
            surface.blit(spr, icon_rect)

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
