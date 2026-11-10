"""
Calibration screen -- the patient side of the CALIBRATE command.

Two call paths:

  * Prototype (not DUAL): `draw(surface, frac, message)` -- a short generic
    progress bar while patient_main self-acks a stub result after a few
    seconds. Unchanged from before this file's redesign.

  * Production dual-monitor: the real CalibrationWindow runs on the
    therapist monitor (scenes/calibration_window.py); `draw_live(surface,
    progress)` mirrors its live sensor/step/attempt/reading state onto a
    polished, patient-friendly screen -- RecovR wordmark, a "CALIBRATION •
    STEP X of Y" pill, a per-sensor heading/instruction/illustration (the
    grip.png / flex.png / wrist.png artwork, used verbatim), a live
    feedback bar, and 3 attempt dots. `progress` is exactly the
    `calibration_progress` dict from the shared session-state snapshot
    (recovr/shared/session_state.py) -- this file never computes its own
    calibration state, only renders what the therapist side already
    computed and pushed (see CalibrationWindow._cal_progress_payload() /
    therapist_link.set_calibration_progress() in
    scenes/therapist_dashboard.py).
"""

import os
import pygame

from recovr.patient_app.scenes.common import (
    PALETTE, fill_bg, draw_lines, draw_progress,
    recovr_gradient, draw_recovr_wordmark, draw_glass_card, _IMG_DIR,
)

# ── per-sensor content (exact wording from the approved reference designs) ──
_SENSOR_CONTENT = {
    "grip": {
        "asset":           "grip.png",
        "heading":         "Let's check your grip!",
        "instruction":     "Squeeze your hand when your therapist tells you.",
        "feedback_label":  "Your squeeze",
        "feedback_msg":    "Keep going!",
    },
    "flex": {
        "asset":           "flex.png",
        "heading":         "Let's check your finger movement!",
        "instruction":     "Bend your fingers, then relax when your therapist tells you.",
        "feedback_label":  "Finger movement",
        "feedback_msg":    "Keep going!",
    },
    "wrist": {
        "asset":           "wrist.png",
        "heading":         "Let's check your wrist movement!",
        "instruction":     "Slowly move your wrist to the left and right when your therapist tells you.",
        "feedback_label":  "Wrist angle",
        "feedback_msg":    "Move left and right!",
    },
}

NAVY_TEXT   = (7, 23, 71)          # primary heading/label text, light theme
SUB_TEXT    = (74, 92, 128)        # secondary instruction line, light theme
ACCENT_BLUE = (40, 120, 210)       # pill text, bar fill, feedback message
PILL_BG     = (213, 231, 252)      # pale pill background

# ── layout (fractions of the patient display) -- flows top to bottom, with
# the illustration taking up whatever room is left between the instruction
# text and the feedback card, so it stays "large and clearly visible"
# (spec) on any actual monitor resolution/aspect instead of a fixed size. ──
TOP_PAD_FRAC     = 0.022
LOGO_H_FRAC      = 0.058
GAP_LOGO_PILL    = 0.016
PILL_H_FRAC      = 0.044
GAP_PILL_HEAD    = 0.020
HEAD_SIZE_FRAC   = 0.054
GAP_HEAD_SUB     = 0.010
SUB_SIZE_FRAC    = 0.024
GAP_SUB_ILLU     = 0.014
GAP_ILLU_CARD    = 0.016
CARD_W_FRAC      = 0.74
CARD_H_FRAC      = 0.16
GAP_CARD_DOTS    = 0.020
DOTS_H_FRAC      = 0.042
BOTTOM_PAD_FRAC  = 0.025

_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "assets", "font"))
_font_cache: dict = {}


def _poppins_path(weight):
    return os.path.join(_FONT_DIR, f"Poppins-{weight}.ttf")


def _font(size, weight="Regular"):
    """Poppins at the given weight -- the project's own font family, same
    loading pattern as waiting_screen.py / therapist_dashboard.py."""
    size = max(1, int(size))
    key = (size, weight)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = pygame.font.Font(_poppins_path(weight), size)
        except Exception:
            f = pygame.font.SysFont("arial,dejavusans", size, bold=(weight not in ("Regular", "Light")))
        _font_cache[key] = f
    return f


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


_asset_raw_cache: dict = {}
_asset_fit_cache: dict = {}


def _fit_illustration(name, max_w, max_h):
    """grip.png / flex.png / wrist.png, cropped to their own opaque content
    (they ship with extra transparent canvas padding) then scaled to fit
    within max_w x max_h preserving aspect ratio -- never stretched or
    cropped, per spec. Colors/transparency are the raw asset, untouched."""
    max_w, max_h = max(1, int(max_w)), max(1, int(max_h))
    key = (name, max_w, max_h)
    img = _asset_fit_cache.get(key)
    if img is not None or key in _asset_fit_cache:
        return img
    cropped = _asset_raw_cache.get(name)
    if cropped is None and name not in _asset_raw_cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            bbox = raw.get_bounding_rect(min_alpha=10)
            cropped = raw.subsurface(bbox).copy() if bbox.width and bbox.height else raw
        except Exception:
            cropped = None
        _asset_raw_cache[name] = cropped
    if cropped is None:
        _asset_fit_cache[key] = None
        return None
    cw, ch = cropped.get_size()
    scale = min(max_w / cw, max_h / ch)
    img = pygame.transform.smoothscale(cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
    if len(_asset_fit_cache) > 24:
        _asset_fit_cache.clear()
    _asset_fit_cache[key] = img
    return img


class CalibratingScreen:

    def draw(self, surface, frac=None, message=None):
        """Prototype-only generic progress screen -- unchanged."""
        fill_bg(surface)
        draw_lines(surface, [
            ("Calibrating sensor", 48, PALETTE["text"]),
            (message or "Hold still and follow the on-screen guide", 24, PALETTE["muted"]),
        ], top_frac=0.42)
        if frac is not None:
            draw_progress(surface, frac, y_frac=0.6)

    # ------------------------------------------------------------------
    #  Production dual-monitor: live, per-sensor calibration screen
    # ------------------------------------------------------------------

    def draw_live(self, surface: pygame.Surface, progress: dict | None):
        W, H = surface.get_size()
        surface.blit(recovr_gradient(W, H), (0, 0))

        progress = progress or {}
        sensor = progress.get("sensor", "")
        content = _SENSOR_CONTENT.get(sensor)
        if content is None:
            # patient_main.py only switches the patient screen into
            # CALIBRATING once a real, known sensor is already live (see its
            # "actively_calibrating" gating) -- an unresolved/results-phase/
            # between-sensors moment stays on the Patient Dashboard instead,
            # never here. This is a safety net for an unexpected stale frame,
            # not a screen the patient is meant to ever actually see, so it
            # draws nothing but the plain background rather than fabricating
            # a "getting ready" / "reviewing results" message.
            return

        dark = PALETTE["bg"][0] < 40
        head_col = PALETTE["text"] if dark else NAVY_TEXT
        sub_col  = PALETTE["text"] if dark else SUB_TEXT
        pill_bg  = (*PALETTE["panel"], 235) if dark else (*PILL_BG, 255)
        pill_fg  = PALETTE["accent"] if dark else ACCENT_BLUE
        bar_fill = PALETTE["accent"] if dark else ACCENT_BLUE

        y = int(H * TOP_PAD_FRAC)

        # -- logo --------------------------------------------------------
        logo_box_w, logo_box_h = int(W * 0.46), int(H * LOGO_H_FRAC)
        draw_recovr_wordmark(surface, W // 2, y, logo_box_w, logo_box_h)
        y += logo_box_h + int(H * GAP_LOGO_PILL)

        # -- "CALIBRATION • STEP X OF Y" pill ------------------------------
        step_idx = max(1, int(progress.get("step_index") or 1))
        step_cnt = max(1, int(progress.get("step_count") or 1))
        pill_font = _font(int(H * PILL_H_FRAC * 0.46), "SemiBold")
        pill_text = f"CALIBRATION • STEP {step_idx} OF {step_cnt}"
        pts = pill_font.render(pill_text, True, pill_fg)
        pill_h = int(H * PILL_H_FRAC)
        pill_w = pts.get_width() + int(pill_h * 1.1)
        pill = pygame.Rect(0, 0, pill_w, pill_h)
        pill.centerx = W // 2
        pill.top = y
        pygame.draw.rect(surface, pill_bg[:3], pill, border_radius=pill_h // 2)
        surface.blit(pts, pts.get_rect(center=pill.center))
        y = pill.bottom + int(H * GAP_PILL_HEAD)

        # -- heading -------------------------------------------------------
        head_font = _font(int(H * HEAD_SIZE_FRAC), "ExtraBold")
        head_max_w = int(W * 0.86)
        head_lines = _wrap(content["heading"], head_font, head_max_w)
        for ln in head_lines:
            s = head_font.render(ln, True, head_col)
            surface.blit(s, s.get_rect(midtop=(W // 2, y)))
            y += s.get_height()
        y += int(H * GAP_HEAD_SUB)

        # -- instruction subheading -----------------------------------------
        sub_font = _font(int(H * SUB_SIZE_FRAC), "Medium")
        sub_max_w = int(W * 0.78)
        sub_lines = _wrap(content["instruction"], sub_font, sub_max_w)
        for ln in sub_lines:
            s = sub_font.render(ln, True, sub_col)
            surface.blit(s, s.get_rect(midtop=(W // 2, y)))
            y += s.get_height()
        illu_top = y + int(H * GAP_SUB_ILLU)

        # -- feedback card + attempt dots are anchored to the BOTTOM, so the
        # illustration between them gets whatever room is left -- it stays
        # the dominant element regardless of exact text heights above. ----
        card_h = int(H * CARD_H_FRAC)
        dots_h = int(H * DOTS_H_FRAC)
        card_top = H - int(H * BOTTOM_PAD_FRAC) - dots_h - int(H * GAP_CARD_DOTS) - card_h
        illu_bottom = card_top - int(H * GAP_ILLU_CARD)

        # -- illustration (grip.png / flex.png / wrist.png, verbatim) -------
        illu_max_w = int(W * 0.70)
        illu_max_h = max(10, illu_bottom - illu_top)
        img = _fit_illustration(content["asset"], illu_max_w, illu_max_h)
        if img is not None:
            iw, ih = img.get_size()
            surface.blit(img, (W // 2 - iw // 2, illu_top + (illu_max_h - ih) // 2))

        # -- feedback container ------------------------------------------
        card = pygame.Rect(0, card_top, int(W * CARD_W_FRAC), card_h)
        card.centerx = W // 2
        draw_glass_card(surface, card, radius_frac=0.16,
                        fill_color=(255, 255, 255) if not dark else PALETTE["panel"],
                        fill_alpha=235, border_alpha=140, shadow_alpha=40,
                        border_color=(190, 210, 235) if not dark else PALETTE["accent"])

        pad_x = int(card.width * 0.055)
        pad_y = int(card.height * 0.16)
        lbl_font = _font(int(card.height * 0.21), "SemiBold")
        msg_font = _font(int(card.height * 0.21), "SemiBold")
        lbl_s = lbl_font.render(content["feedback_label"], True, head_col)
        msg_s = msg_font.render(content["feedback_msg"], True, bar_fill)
        row_y = card.top + pad_y
        surface.blit(lbl_s, (card.left + pad_x, row_y))
        surface.blit(msg_s, msg_s.get_rect(topright=(card.right - pad_x, row_y)))

        bar_top = row_y + lbl_s.get_height() + int(card.height * 0.10)
        bar_h = int(card.height * 0.22)
        bar_rect = pygame.Rect(card.left + pad_x, bar_top, card.width - pad_x * 2, bar_h)
        live_frac = progress.get("live_frac")
        frac = max(0.0, min(1.0, float(live_frac))) if live_frac is not None else 0.0
        track_col = (224, 232, 245) if not dark else PALETTE["panel"]
        pygame.draw.rect(surface, track_col, bar_rect, border_radius=bar_h // 2)
        if frac > 0.0:
            fill_w = max(bar_h, int(bar_rect.width * frac))
            fill_rect = pygame.Rect(bar_rect.left, bar_rect.top, fill_w, bar_h)
            pygame.draw.rect(surface, bar_fill, fill_rect, border_radius=bar_h // 2)

        # -- attempt dots + label ------------------------------------------
        attempt_idx = max(1, min(3, int(progress.get("attempt_index") or 1)))
        attempt_cnt = max(1, int(progress.get("attempt_count") or 3))
        self._draw_attempt_row(surface, W, card.bottom + int(H * GAP_CARD_DOTS),
                               dots_h, attempt_idx, attempt_cnt, head_col, bar_fill, dark)

    def _draw_attempt_row(self, surface, W, y, row_h, attempt_idx, attempt_cnt, text_col, accent, dark):
        """Three circles -- filled = completed, larger filled = the current
        attempt, hollow ring = upcoming -- plus a divider and "Attempt N of
        M" label, all centred as one horizontal group."""
        r = max(4, int(row_h * 0.26))
        gap = int(row_h * 0.55)
        n = max(1, attempt_cnt)
        side_gap = int(row_h * 0.35)
        divider_w = max(1, int(row_h * 0.08))

        label_font = _font(int(row_h * 0.46), "Medium")
        label = label_font.render(f"Attempt {attempt_idx} of {attempt_cnt}", True, text_col)

        dots_block_w = (n - 1) * gap + r * 2
        group_w = dots_block_w + side_gap + divider_w + side_gap + label.get_width()
        x0 = W // 2 - group_w // 2
        cy = y + row_h // 2

        cx = x0 + r
        for i in range(n):
            if i + 1 < attempt_idx:
                pygame.draw.circle(surface, accent, (cx, cy), r)
            elif i + 1 == attempt_idx:
                pygame.draw.circle(surface, accent, (cx, cy), int(r * 1.3))
            else:
                pygame.draw.circle(surface, accent, (cx, cy), r, max(1, int(r * 0.28)))
            cx += gap

        div_x = x0 + dots_block_w + side_gap
        dv = pygame.Surface((divider_w, int(row_h * 0.7)), pygame.SRCALPHA)
        dv.fill((*text_col[:3], 90))
        surface.blit(dv, (div_x, cy - dv.get_height() // 2))

        surface.blit(label, label.get_rect(midleft=(div_x + divider_w + side_gap, cy)))
