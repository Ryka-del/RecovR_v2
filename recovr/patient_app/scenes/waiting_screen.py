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
# Each entry is (primary, secondary, sprite_name): the bold headline, an
# optional lighter supporting line (None if there isn't one), and the sprite
# illustration shown beside it (filename inside assets/images/). Sprites are
# the real uploaded PNGs -- no generic icons, nothing drawn from scratch.
WAITING_INSTRUCTIONS = [
    ("Position yourself comfortably.",       None,                    "waiting_screen_comfortably.png"),
    ("Relax and take a deep breath.",        None,                    "waiting_screen_breath.png"),
    ("Put on your rehabilitation glove.",    "Ask for assistance.",   "waiting_screen_gloves.png"),
    ("Keep your elbow at approximately 90°.", None,                   "waiting_screen_elbow.png"),
]

# ── EDIT ME: carousel timing (milliseconds) ───────────────────────────────
HOLD_MS       = 3200   # stay centred (reading time)
TRANSITION_MS = 900    # synchronized swipe: current card slides out to the
                        # left while the next slides in from the right, both
                        # moving together at the same speed (see
                        # common.carousel_frame) -- a clean linked swap, not
                        # two independently-timed slides that can overlap

# ── EDIT ME: layout / look (fractions of the patient display) ─────────────
LOGO_H_FRAC        = 0.14    # wordmark box height -- ~24% smaller than before,
                              # so the instruction card (not the logo) dominates
CARD_W_FRAC        = 0.82
CARD_H_FRAC        = 0.46
CARD_CENTER_Y_FRAC = 0.520   # pulled up, right under the logo
CARD_RADIUS_FRAC   = 0.13    # of the card height
CARD_PAD_X_FRAC    = 0.05    # left/right inner padding, of the card width
CARD_PAD_Y_FRAC    = 0.06    # top/bottom inner padding, of the card height
ICON_FRAC          = 0.82    # sprite size, of the card's inner (padded) height --
                              # large; paired with sprite(..., crop=True) so this
                              # is the size of the actual artwork, not its canvas
ICON_TEXT_GAP_FRAC = 0.065   # gap between sprite and the divider+text, of the card width
TEXT_SIZE_FRAC     = 0.225   # primary line height, of the card height -- large
SECONDARY_SIZE_FRAC = 0.145  # secondary line height, of the card height
LINE_GAP_FRAC      = 0.30    # gap between wrapped lines (of line height)
CARD_FILL_ALPHA    = 70      # frosted-glass fill -- translucent, gradient shows through
CARD_BORDER_ALPHA  = 190     # thin, bright white border
SHADOW_ALPHA       = 22      # soft shadow
GLOW_ALPHA         = 55      # soft outward white glow around the card
DOT_GAP_FRAC       = 0.06    # gap between the card's bottom edge and the dots, of H
DOT_R_FRAC         = 0.009   # dot radius, of H
DOT_SPACING_FRAC   = 0.034   # centre-to-centre spacing between dots, of W

NAVY_TEXT        = (7, 23, 71)          # #071747 -- primary/secondary text, light theme
DIVIDER_COLOR    = (176, 196, 221, 170) # thin light blue-gray vertical rule


_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "assets", "font"))
_font_cache: dict = {}


def _poppins_path(weight):
    return os.path.join(_FONT_DIR, f"Poppins-{weight}.ttf")


def _font(size, weight="Regular"):
    """Poppins at the given weight ("SemiBold" for the primary instruction,
    "Regular" for the lighter supporting line) -- the project's own Poppins
    family (assets/font/), the same loading pattern scenes/therapist_dashboard.py
    uses for its own Poppins text, never a substitute font."""
    key = (size, weight)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = pygame.font.Font(_poppins_path(weight), size)
        except Exception:
            f = pygame.font.SysFont("arial,dejavusans", size, bold=(weight != "Regular"))
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

    def _draw_logo(self, surface, W, H, card_top):
        """The existing RecovR wordmark, shared with the patient Dashboard via
        scenes/common.py -- not a new logo and not the reference image's hand
        icon. See common.draw_recovr_wordmark for the actual technique (it
        matches scenes/therapist_welcome.py's arialblack two-tone treatment).
        Positioned so its vertical center sits at the midpoint between the
        screen's top edge and the top of the instruction card below it, per
        the requested layout -- same size/aspect ratio, just recentered in
        the space above the card instead of a fixed top margin."""
        box_w, box_h = int(W * 0.7), int(H * LOGO_H_FRAC)
        top_y = (card_top // 2) - box_h // 2
        return draw_recovr_wordmark(surface, W // 2, top_y, box_w, box_h)

    def _draw_card(self, surface, rect, text_col, primary, secondary=None,
                   sprite_name=None, alpha_scale=1.0):
        """Icon-left / text-right instruction card: [ pale circle + sprite ]
        [ divider ] [ bold primary line(s) + lighter secondary line ], all
        vertically centred so they read as one combined unit. The card itself
        is a soft, translucent frosted-glass panel with a bright hairline
        border and a faint outward glow, so the pastel gradient keeps showing
        through instead of a heavy/opaque block."""
        # Wrap-and-shrink-to-fit needs the text column's width *before* the
        # shared draw call, so ask the shared geometry helper for it first --
        # the actual icon+text painting is then one call, shared with the
        # patient Dashboard's card (common.draw_icon_text_card).
        _, _, text_max_w = icon_text_geometry(
            rect, CARD_PAD_X_FRAC, CARD_PAD_Y_FRAC, ICON_FRAC, ICON_TEXT_GAP_FRAC,
            has_icon=bool(sprite_name))

        text_items = []
        key = (primary, secondary, rect.width, rect.height)
        rendered = self._text_cache.get(key)
        if rendered is None:
            rendered = []
            if primary:
                fsz = max(14, int(rect.height * TEXT_SIZE_FRAC))
                f = _font(fsz, "SemiBold")
                lines = _wrap(primary, f, text_max_w)
                while len(lines) > 2 and fsz > 20:            # natural wrap, not excessive shrink
                    fsz = int(fsz * 0.92); f = _font(fsz, "SemiBold")
                    lines = _wrap(primary, f, text_max_w)
                rendered += [f.render(ln, True, (255, 255, 255)) for ln in lines]
            if secondary:
                fsz = max(12, int(rect.height * SECONDARY_SIZE_FRAC))
                f = _font(fsz, "Regular")
                lines = _wrap(secondary, f, text_max_w)
                while len(lines) > 2 and fsz > 16:
                    fsz = int(fsz * 0.92); f = _font(fsz, "Regular")
                    lines = _wrap(secondary, f, text_max_w)
                rendered += [f.render(ln, True, (255, 255, 255)) for ln in lines]
            self._text_cache[key] = rendered
            if len(self._text_cache) > 24:
                self._text_cache = dict(list(self._text_cache.items())[-16:])
        text_items = [(s, text_col) for s in rendered]

        draw_icon_text_card(surface, rect, sprite_name, text_items,
                            radius_frac=CARD_RADIUS_FRAC, pad_x_frac=CARD_PAD_X_FRAC,
                            pad_y_frac=CARD_PAD_Y_FRAC, icon_frac=ICON_FRAC,
                            gap_frac=ICON_TEXT_GAP_FRAC, line_gap_frac=LINE_GAP_FRAC,
                            fill_alpha=CARD_FILL_ALPHA, border_alpha=CARD_BORDER_ALPHA,
                            shadow_alpha=SHADOW_ALPHA, alpha_scale=alpha_scale,
                            glow_alpha=GLOW_ALPHA, divider_color=DIVIDER_COLOR)

    def _draw_dots(self, surface, card, active_idx, N, dot_col):
        H, W = surface.get_size()[1], surface.get_size()[0]
        r = max(3, int(H * DOT_R_FRAC))
        spacing = int(W * DOT_SPACING_FRAC)
        cy = card.bottom + int(H * DOT_GAP_FRAC)
        total_w = spacing * (N - 1)
        cx0 = card.centerx - total_w // 2
        for i in range(N):
            cx = cx0 + i * spacing
            if i == active_idx:
                pygame.draw.circle(surface, dot_col, (cx, cy), int(r * 1.35))
            else:
                dim = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(dim, (*dot_col, 130), (r, r), r)
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
        # Deep navy Poppins text on the light pastel card, per the reference;
        # dark theme (no reference provided for it) keeps the theme's own
        # light-on-dark text colour so it stays legible against the dark bg.
        text_col = PALETTE["text"] if dark else NAVY_TEXT
        dot_col = PALETTE["text"] if dark else NAVY_TEXT

        card = self._card_rect(W, H)
        self._draw_logo(surface, W, H, card.top)

        N = len(WAITING_INSTRUCTIONS) or 1

        # No static side rectangles -- only the animated instruction card(s)
        # are drawn; the dot row below is the sole "more to come" cue. Motion
        # comes from the shared common.carousel_frame() -- the same hold ->
        # synchronized-swipe math the patient Dashboard's card also uses.
        #
        # Everything belonging to a card -- its glass shell, icon, divider
        # and text -- is painted by one call (_draw_card -> draw_icon_text_card)
        # using the SAME rect, so it all moves together as one unit. The clip
        # is a belt-and-braces guard (never strictly needed once the two
        # cards' motion is properly synchronized -- see carousel_frame -- but
        # guarantees nothing from a card can ever paint outside the carousel
        # band regardless): the carousel's own vertical band, full width.
        prev_clip = surface.get_clip()
        clip_pad = int(H * 0.02)
        surface.set_clip(pygame.Rect(0, card.top - clip_pad, W, card.height + clip_pad * 2))

        frame = carousel_frame(t, W, card.width, N, hold_ms=HOLD_MS, transition_ms=TRANSITION_MS)
        for idx, x, a in frame:
            r = card.copy(); r.centerx = x
            primary, secondary, sprite_name = WAITING_INSTRUCTIONS[idx]
            self._draw_card(surface, r, text_col, primary, secondary,
                            sprite_name=sprite_name, alpha_scale=a)

        surface.set_clip(prev_clip)

        cycle = max(1, HOLD_MS + TRANSITION_MS)
        self._draw_dots(surface, card, (t // cycle) % N, N, dot_col)
