"""
Patient Waiting Screen  --  the calm, informational carousel shown on the
patient monitor while the system is waiting for the therapist (no patient
selected yet, or on the Login page).

PURE VIEW + SELF-CONTAINED ANIMATION.
  * `draw(surface, snapshot)` only reads the snapshot (theme is taken from
    constants.get_theme() via scenes.common.PALETTE) and paints a frame.
  * The carousel is driven purely by wall-clock time (pygame.time.get_ticks()):
    every call to draw() renders the frame for "now". It NEVER sleeps, blocks,
    reads events, or issues session commands, so it cannot interfere with the
    patient application's event loop or the dual-monitor sync.
  * Session/patient state -> which screen is shown lives in
    recovr/patient_app/patient_main.py (`_reconcile_dual` / `_draw`). This file
    is only ever asked to draw; it never decides its own visibility and never
    starts a game.

Everything you might want to tweak later -- the instruction text, timings,
card geometry, typography, colours, shadow, number of instructions -- is a
plain module-level constant below. Add/'edit/remove entries in
WAITING_INSTRUCTIONS with no other changes.
"""

import os
import pygame
from recovr.patient_app.scenes.common import PALETTE


# ── EDIT ME: the instructions, shown one at a time, looping forever ──────────
WAITING_INSTRUCTIONS = [
    "Position yourself comfortably.",
    "Keep your elbow at approximately 90°.",
    "Put on your gloves. Ask for assistance.",
    "Relax and take a deep breath.",
]

# ── EDIT ME: carousel timing (milliseconds) ───────────────────────────────
ENTER_MS   = 950     # slide in from the left edge -> centre (eased)
HOLD_MS    = 3200    # stay centred (reading time)
EXIT_MS    = 950     # slide centre -> off the left edge (eased)
OVERLAP_MS = 650     # the next card starts entering this long before the
                     # current one has finished leaving -> continuous motion

# ── EDIT ME: layout / look (fractions of the patient display) ─────────────
CARD_W_FRAC        = 0.66
CARD_H_FRAC        = 0.55
CARD_CENTER_Y_FRAC = 0.50
CARD_RADIUS_FRAC   = 0.055   # of the card height
SIDE_CARD_PEEK_FRAC = 0.075  # how much of each side card shows past the edge
TEXT_SIZE_FRAC     = 0.175   # of the card height (large -> short lines wrap x2)
LINE_GAP_FRAC      = 0.26    # extra gap between wrapped lines (of line height)
CARD_FILL_ALPHA    = 20      # glass fill (kept faint so the gradient shows through)
CARD_BORDER_ALPHA  = 100
SHADOW_ALPHA       = 34


_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "assets", "font"))
_font_cache: dict = {}
_grad_cache: dict = {}


def _font(size, italic=True):
    key = (size, italic)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = pygame.font.Font(os.path.join(_FONT_DIR, "Sora-Medium.ttf"), size)
        except Exception:
            f = pygame.font.SysFont("lexend,arial,dejavusans", size)
        f.set_italic(bool(italic))
        _font_cache[key] = f
    return f


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def _ease_out(p):   # decelerate into the centre
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def _ease_in(p):    # accelerate out of the centre
    p = max(0.0, min(1.0, p))
    return p ** 3


def _recovr_gradient(w, h):
    """The RecovR pastel gradient -- the SAME blue / white / purple diagonal
    used on the therapist dashboard background. Cached per (w, h, dark)."""
    dark = PALETTE["bg"][0] < 40
    key = (w, h, dark)
    g = _grad_cache.get(key)
    if g is not None:
        return g
    sw, sh = max(2, w // 6), max(2, h // 6)
    s = pygame.Surface((sw, sh)).convert()
    if dark:
        white  = (24, 26, 40); pblue = (26, 40, 74); ppurp = (44, 28, 66)
    else:
        white  = (255, 255, 255); pblue = (185, 215, 255); ppurp = (225, 185, 255)
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
    if len(_grad_cache) > 4:
        _grad_cache.clear()
    _grad_cache[key] = g
    return g


def _wrap(text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if font.size(t)[0] <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = wd
    if cur:
        lines.append(cur)
    return lines or [""]


class WaitingScreen:

    def __init__(self):
        self._t0 = None                      # first-draw timestamp (deterministic start)
        self._text_cache: dict = {}          # (idx, key) -> pre-wrapped surfaces

    # -- helpers -------------------------------------------------------
    def _card_rect(self, W, H):
        cw, ch = int(W * CARD_W_FRAC), int(H * CARD_H_FRAC)
        return pygame.Rect((W - cw) // 2, int(H * CARD_CENTER_Y_FRAC) - ch // 2, cw, ch)

    def _draw_card(self, surface, rect, text_col, text, alpha_scale=1.0):
        W, H = surface.get_size()
        rad = max(8, int(rect.height * CARD_RADIUS_FRAC))

        # soft shadow -- a few stacked, expanding, translucent rounded rects
        for i, (dy, grow, a) in enumerate(((5, 2, 0.6), (10, 8, 0.35), (16, 14, 0.18))):
            sr = rect.inflate(int(grow), int(grow)).move(0, int(dy))
            sh = pygame.Surface((sr.width, sr.height), pygame.SRCALPHA)
            pygame.draw.rect(sh, (0, 0, 0, int(SHADOW_ALPHA * a * alpha_scale)),
                             sh.get_rect(), border_radius=rad + 6)
            surface.blit(sh, sr.topleft)

        # glass card
        card = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(card, (255, 255, 255, int(CARD_FILL_ALPHA * alpha_scale)),
                         card.get_rect(), border_radius=rad)
        pygame.draw.rect(card, (255, 255, 255, int(CARD_BORDER_ALPHA * alpha_scale)),
                         card.get_rect(), max(1, int(H * 0.002)), border_radius=rad)
        surface.blit(card, rect.topleft)

        if not text:
            return
        # wrapped, centred text (cached per instruction + card size)
        key = (text, rect.width, rect.height)
        rendered = self._text_cache.get(key)
        if rendered is None:
            fsz = max(14, int(rect.height * TEXT_SIZE_FRAC))
            f = _font(fsz)
            lines = _wrap(text, f, int(rect.width * 0.84))
            while len(lines) > 2 and fsz > 18:               # keep it to <= 2 lines
                fsz = int(fsz * 0.9); f = _font(fsz)
                lines = _wrap(text, f, int(rect.width * 0.84))
            rendered = [f.render(ln, True, (255, 255, 255)) for ln in lines]
            self._text_cache[key] = rendered
            if len(self._text_cache) > 24:
                self._text_cache = dict(list(self._text_cache.items())[-16:])
        lh = rendered[0].get_height()
        gap = int(lh * LINE_GAP_FRAC)
        total = sum(s.get_height() for s in rendered) + gap * (len(rendered) - 1)
        y = rect.centery - total // 2
        a = max(0, min(255, int(255 * alpha_scale)))
        for s in rendered:
            tint = s.copy()
            tint.fill((*text_col, 255), special_flags=pygame.BLEND_RGBA_MULT)
            if a < 255:
                tint.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(tint, tint.get_rect(midtop=(rect.centerx, y)))
            y += s.get_height() + gap

    # -- main -------------------------------------------------------
    def draw(self, surface: pygame.Surface, snapshot: dict | None = None):
        W, H = surface.get_size()
        now = pygame.time.get_ticks()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0

        surface.blit(_recovr_gradient(W, H), (0, 0))

        dark = PALETTE["bg"][0] < 40
        text_col = PALETTE["text"] if dark else (92, 94, 104)

        card = self._card_rect(W, H)
        margin = int(W * 0.06)
        off_left_cx  = -card.width // 2 - margin           # fully off the left edge
        off_right_cx = W + card.width // 2 + margin        # fully off the right edge
        cx = W // 2

        # ── decorative side cards (the "carousel, more to come" hint) ──
        peek = int(W * SIDE_CARD_PEEK_FRAC)
        left_side = card.copy();  left_side.right = peek        # only its right edge shows
        right_side = card.copy(); right_side.left = W - peek    # only its left edge shows
        for sr in (left_side, right_side):
            self._draw_card(surface, sr, text_col, "", alpha_scale=0.45)

        # ── moving instruction card(s) ──
        span = ENTER_MS + HOLD_MS + EXIT_MS
        cycle = max(1, span - OVERLAP_MS)
        N = len(WAITING_INSTRUCTIONS) or 1

        def card_x_and_alpha(local):
            """centre-x and 0..1 alpha for a card `local` ms into its life.
            The whole strip moves LEFT continuously: a card slides in from the
            right edge to the centre, holds, then slides off the left edge."""
            if local < ENTER_MS:
                p = _ease_out(local / ENTER_MS)
                x = off_right_cx + (cx - off_right_cx) * p
                a = min(1.0, local / 240.0)
            elif local < ENTER_MS + HOLD_MS:
                x, a = cx, 1.0
            else:
                p = _ease_in((local - ENTER_MS - HOLD_MS) / EXIT_MS)
                x = cx + (off_left_cx - cx) * p
                a = max(0.0, 1.0 - (local - ENTER_MS - HOLD_MS) / EXIT_MS)
            return int(x), a

        j_now = t // cycle
        for j in (j_now - 1, j_now):                       # previous (still leaving) + current
            if j < 0:
                continue
            local = t - j * cycle
            if local < 0 or local >= span:
                continue
            x, a = card_x_and_alpha(local)
            if a <= 0.01:
                continue
            r = card.copy(); r.centerx = x
            self._draw_card(surface, r, text_col,
                            WAITING_INSTRUCTIONS[j % N], alpha_scale=a)
