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

Everything you might want to tweak later -- the instruction text/sprite pairs,
timings, card geometry, typography, colours, shadow, number of instructions --
is a plain module-level constant below. Add/edit/remove entries in
WAITING_INSTRUCTIONS with no other changes.
"""

import os
import pygame
from recovr.patient_app.scenes.common import (
    PALETTE, recovr_gradient, draw_recovr_wordmark, draw_glass_card,
    carousel_frame, icon_text_geometry, draw_icon_text_card,
)


# ── EDIT ME: the instructions, shown one at a time, looping forever ──────────
# Each entry pairs the on-screen text with the sprite illustration shown above
# it (filename inside assets/images/). Sprites are the real uploaded PNGs --
# no generic icons, nothing drawn from scratch.
WAITING_INSTRUCTIONS = [
    ("Position yourself comfortably.",              "waiting_screen_comfortably.png"),
    ("Relax and take a deep breath.",                "waiting_screen_breath.png"),
    ("Put on your gloves. Ask for assistance.",      "waiting_screen_gloves.png"),
    ("Keep your elbow at approximately 90°.",        "waiting_screen_elbow.png"),
]

# ── EDIT ME: carousel timing (milliseconds) ───────────────────────────────
ENTER_MS   = 950     # slide in from the left edge -> centre (eased)
HOLD_MS    = 3200    # stay centred (reading time)
EXIT_MS    = 950     # slide centre -> off the left edge (eased)
OVERLAP_MS = 650     # the next card starts entering this long before the
                     # current one has finished leaving -> continuous motion

# ── EDIT ME: layout / look (fractions of the patient display) ─────────────
LOGO_TOP_FRAC      = 0.022   # margin above the RecovR wordmark
LOGO_H_FRAC        = 0.185   # wordmark box height -- large, anchors the top area
CARD_W_FRAC        = 0.82
CARD_H_FRAC        = 0.46
CARD_CENTER_Y_FRAC = 0.520   # pulled up, right under the logo
CARD_RADIUS_FRAC   = 0.09    # of the card height
CARD_PAD_X_FRAC    = 0.04    # left/right inner padding, of the card width
CARD_PAD_Y_FRAC    = 0.065   # top/bottom inner padding, of the card height
ICON_FRAC          = 0.94    # sprite size, of the card's inner (padded) height -- large
ICON_TEXT_GAP_FRAC = 0.045   # gap between sprite and text, of the card width
TEXT_SIZE_FRAC     = 0.27    # of the card height -- much larger instruction text
LINE_GAP_FRAC      = 0.26    # extra gap between wrapped lines (of line height)
CARD_FILL_ALPHA    = 26      # frosted-glass fill -- translucent, gradient shows through
CARD_BORDER_ALPHA  = 120
SHADOW_ALPHA       = 16      # single soft shadow, kept light so it never looks muddy
DOT_GAP_FRAC       = 0.06    # gap between the card's bottom edge and the dots, of H
DOT_R_FRAC         = 0.009   # dot radius, of H
DOT_SPACING_FRAC   = 0.034   # centre-to-centre spacing between dots, of W


_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "assets", "font"))
_font_cache: dict = {}


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

    def _draw_logo(self, surface, W, H):
        """The existing RecovR wordmark, shared with the patient Dashboard via
        scenes/common.py -- not a new logo and not the reference image's hand
        icon. See common.draw_recovr_wordmark for the actual technique (it
        matches scenes/therapist_welcome.py's arialblack two-tone treatment)."""
        return draw_recovr_wordmark(surface, W // 2, int(H * LOGO_TOP_FRAC),
                                    int(W * 0.7), int(H * LOGO_H_FRAC))

    def _draw_card(self, surface, rect, text_col, text, sprite_name=None, alpha_scale=1.0):
        """Icon-left / text-right instruction card: [ LARGE SPRITE ] [ TEXT ],
        both vertically centred on the card so they read as one combined
        icon-text unit. The card itself is a soft, translucent frosted panel --
        a single light shadow plus a low-alpha fill, so the pastel gradient
        keeps showing through instead of a heavy/opaque (or muddy) block."""
        # Wrap-and-shrink-to-fit needs the text column's width *before* the
        # shared draw call, so ask the shared geometry helper for it first --
        # the actual icon+text painting is then one call, shared with the
        # patient Dashboard's card (common.draw_icon_text_card).
        _, _, text_max_w = icon_text_geometry(
            rect, CARD_PAD_X_FRAC, CARD_PAD_Y_FRAC, ICON_FRAC, ICON_TEXT_GAP_FRAC,
            has_icon=bool(sprite_name))

        text_items = []
        if text:
            key = (text, rect.width, rect.height)
            rendered = self._text_cache.get(key)
            if rendered is None:
                fsz = max(14, int(rect.height * TEXT_SIZE_FRAC))
                f = _font(fsz)
                lines = _wrap(text, f, text_max_w)
                while len(lines) > 2 and fsz > 26:               # keep it to <= 2 lines
                    fsz = int(fsz * 0.9); f = _font(fsz)
                    lines = _wrap(text, f, text_max_w)
                rendered = [f.render(ln, True, (255, 255, 255)) for ln in lines]
                self._text_cache[key] = rendered
                if len(self._text_cache) > 24:
                    self._text_cache = dict(list(self._text_cache.items())[-16:])
            text_items = [(s, text_col) for s in rendered]

        draw_icon_text_card(surface, rect, sprite_name, text_items,
                            radius_frac=CARD_RADIUS_FRAC, pad_x_frac=CARD_PAD_X_FRAC,
                            pad_y_frac=CARD_PAD_Y_FRAC, icon_frac=ICON_FRAC,
                            gap_frac=ICON_TEXT_GAP_FRAC, line_gap_frac=LINE_GAP_FRAC,
                            fill_alpha=CARD_FILL_ALPHA, border_alpha=CARD_BORDER_ALPHA,
                            shadow_alpha=SHADOW_ALPHA, alpha_scale=alpha_scale)

    def _draw_dots(self, surface, card, active_idx, N):
        H, W = surface.get_size()[1], surface.get_size()[0]
        r = max(3, int(H * DOT_R_FRAC))
        spacing = int(W * DOT_SPACING_FRAC)
        cy = card.bottom + int(H * DOT_GAP_FRAC)
        total_w = spacing * (N - 1)
        cx0 = card.centerx - total_w // 2
        for i in range(N):
            cx = cx0 + i * spacing
            if i == active_idx:
                pygame.draw.circle(surface, (255, 255, 255), (cx, cy), int(r * 1.35))
            else:
                dim = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(dim, (255, 255, 255, 130), (r, r), r)
                surface.blit(dim, (cx - r, cy - r))

    # -- main -------------------------------------------------------
    def draw(self, surface: pygame.Surface, snapshot: dict | None = None):
        W, H = surface.get_size()
        now = pygame.time.get_ticks()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0

        surface.blit(recovr_gradient(W, H), (0, 0))

        dark = PALETTE["bg"][0] < 40
        text_col = PALETTE["text"] if dark else (92, 94, 104)

        self._draw_logo(surface, W, H)

        card = self._card_rect(W, H)
        N = len(WAITING_INSTRUCTIONS) or 1

        # No static side rectangles -- only the animated instruction card(s)
        # are drawn; the dot row below is the sole "more to come" cue. Motion
        # comes from the shared common.carousel_frame() -- the same slide-in
        # -> hold -> slide-out math the patient Dashboard's card also uses.
        frame = carousel_frame(t, W, card.width, N, enter_ms=ENTER_MS, hold_ms=HOLD_MS,
                               exit_ms=EXIT_MS, overlap_ms=OVERLAP_MS)
        for idx, x, a in frame:
            r = card.copy(); r.centerx = x
            text, sprite_name = WAITING_INSTRUCTIONS[idx]
            self._draw_card(surface, r, text_col, text, sprite_name=sprite_name, alpha_scale=a)

        cycle = max(1, ENTER_MS + HOLD_MS + EXIT_MS - OVERLAP_MS)
        self._draw_dots(surface, card, (t // cycle) % N, N)
