"""
Shared RecovR game header -- GameName | Difficulty | Time | Score.

Built from the provided asset set (header_bg.png + easy/medium/hard_
difficulty.png + time_game.png + score_game.png) so every game shows the
same header instead of each drawing its own ad hoc HUD bar.

Usage (inside a game's draw(surface)):

    from games.game_header import draw_game_header, HEADER_BOTTOM
    draw_game_header(surface, "Basketball", self.difficulty,
                      self.time_left, self.score, GAME_W, GAME_H)

difficulty must be one of "Easy" / "Medium" / "Hard" (falls back to Easy's
asset for any other value rather than crashing).

The header floats: it's inset from the top and both side edges rather than
spanning the full screen width, so HEADER_TOP / HEADER_SIDE / HEADER_BOTTOM
are exported (and also returned) for a game to position its own pause
button below it.
"""

import os
import pygame
from constants import GAME_W as _GAME_W, GAME_H as _GAME_H

_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IMG_DIR = os.path.join(_ROOT, "assets", "images")
_cache   = {}

# The header floats as an inset, rounded bar rather than a full-width banner
# flush against the screen edge.
HEADER_H      = int(_GAME_H * 0.105)
HEADER_TOP    = int(_GAME_H * 0.025)
HEADER_SIDE   = int(_GAME_W * 0.02)
HEADER_BOTTOM = HEADER_TOP + HEADER_H

_DIFF_ASSET = {
    "Easy":   "easy_difficulty.png",
    "Medium": "medium_difficulty.png",
    "Hard":   "hard_difficulty.png",
}

_fonts = {}


def _font(name, size, bold=False):
    key = (name, size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont(name, size, bold=bold)
    return _fonts[key]


def _load_fit(name, w, h):
    """Crop an asset to its own opaque content, then scale to fit within
    w x h preserving its aspect ratio (never stretched/distorted)."""
    key = ("fit", name, w, h)
    if key not in _cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
            cw, ch = cropped.get_size()
            scale = min(w / cw, h / ch)
            _cache[key] = pygame.transform.smoothscale(
                cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
        except Exception:
            _cache[key] = None
    return _cache[key]


def _load_stretch(name, w, h):
    """The header bar itself -- a plain gradient pill with no fine detail,
    so stretching its own content (cropped out of the much taller source
    canvas first) to exactly fill w x h is visually fine and guarantees it
    spans the full game width."""
    key = ("stretch", name, w, h)
    if key not in _cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
            _cache[key] = pygame.transform.smoothscale(cropped, (w, h))
        except Exception:
            _cache[key] = None
    return _cache[key]


def draw_game_header(surface, game_name, difficulty, time_left, score, game_w, game_h):
    header_h = int(game_h * 0.105)
    top      = int(game_h * 0.025)
    side     = int(game_w * 0.02)
    header_w = game_w - side * 2
    pad      = int(game_w * 0.02)   # internal left/right padding inside the pill

    bg = _load_stretch("header_bg.png", header_w, header_h)
    if bg is not None:
        surface.blit(bg, (side, top))
    else:
        # fallback if the asset is ever missing -- a plain bar, old style
        pygame.draw.rect(surface, (20, 140, 165), (side, top, header_w, header_h), border_radius=header_h // 2)
        pygame.draw.rect(surface, (255, 255, 255), (side, top, header_w, header_h), 1, border_radius=header_h // 2)

    badge_h   = int(header_h * 0.74)
    title_gap = int(game_w * 0.02)
    inter_gap = int(game_w * 0.006)   # tight spacing between Difficulty/Time/Score

    # Badge sizes are fixed regardless of the game name, so every game's
    # header reads consistently -- only the title (which varies in length)
    # flexes to make room.
    diff_img = _load_fit(_DIFF_ASSET.get(difficulty, "easy_difficulty.png"),
                         int(game_w * 0.19), badge_h)
    time_img = _load_fit("time_game.png", int(game_w * 0.155), badge_h)
    score_img = _load_fit("score_game.png", int(game_w * 0.15), badge_h)

    f_val = _font("arial", int(badge_h * 0.66), bold=True)

    mins, secs = divmod(max(0, int(time_left)), 60)
    time_text  = f"{mins:02d}:{secs:02d}"
    score_text = f"{int(score):03d}"

    def _badge_w(img, text, label_frac):
        """The image only bakes in the icon + label; the live value is drawn
        in the blank space to its right. Measure the ACTUAL rendered value
        text so the badge's reserved width always covers it -- a wide score
        (growing digit count) or a wide time string never overflows past the
        badge or the header's own edge."""
        if img is None:
            return 0
        val_w   = f_val.size(text)[0]
        right_pad = int(img.get_width() * 0.06)
        needed  = int(img.get_width() * label_frac) + val_w + right_pad
        return max(img.get_width(), needed)

    diff_w  = diff_img.get_width() if diff_img is not None else 0
    time_w  = _badge_w(time_img, time_text, 0.58)
    score_w = _badge_w(score_img, score_text, 0.68)

    badge_widths = [w for w in (diff_w, time_w, score_w) if w > 0]
    group_w = sum(badge_widths) + inter_gap * max(0, len(badge_widths) - 1)

    avail_start = side + pad
    avail_end   = side + header_w - pad

    # Game title -- significantly larger than before, scaled down only if it
    # would otherwise exceed the header's own height or crowd the badges.
    f_title = _font("arialblack", int(header_h * 0.62))
    title_s = f_title.render(game_name, True, (255, 255, 255))
    max_title_h = int(header_h * 0.78)
    max_title_w = max(40, avail_end - avail_start - title_gap - group_w)
    scale = min(max_title_h / title_s.get_height(), max_title_w / title_s.get_width(), 1.0)
    if scale < 1.0:
        tw = max(1, int(title_s.get_width() * scale))
        th = max(1, int(title_s.get_height() * scale))
        title_s = pygame.transform.smoothscale(title_s, (tw, th))
    surface.blit(title_s, title_s.get_rect(midleft=(avail_start, top + header_h // 2)))

    # Difficulty / Time / Score now sit as one tight cluster pushed toward
    # the right edge of the pill, instead of spread evenly across the
    # leftover width -- closer together, and further right.
    x = max(avail_start + title_s.get_width() + title_gap, avail_end - group_w)
    if diff_img is not None:
        surface.blit(diff_img, (int(x), top + header_h // 2 - diff_img.get_height() // 2))
        x += diff_img.get_width() + inter_gap

    def _value_badge(img, text, label_frac, reserved_w):
        nonlocal x
        if img is None:
            return
        y = top + header_h // 2 - img.get_height() // 2
        surface.blit(img, (int(x), y))
        # the asset only bakes in the icon + label; the live value is drawn
        # in the blank space to its right.
        vs = f_val.render(text, True, (255, 255, 255))
        vx = int(x) + int(img.get_width() * label_frac)
        surface.blit(vs, vs.get_rect(midleft=(vx, y + img.get_height() // 2)))
        # advance by the MEASURED badge width (>= the image's own width),
        # not just the image's width, so a long value never overlaps/overflows
        # into the next badge or past the header's edge.
        x += reserved_w + inter_gap

    _value_badge(time_img, time_text, 0.58, time_w)
    _value_badge(score_img, score_text, 0.68, score_w)

    return HEADER_BOTTOM
