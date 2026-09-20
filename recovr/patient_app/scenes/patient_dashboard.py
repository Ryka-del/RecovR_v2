"""
Patient Dashboard  --  the patient monitor view shown while a patient is
selected (before / between sessions).

PURE VIEW. `draw(surface, snapshot)` only *reads* the shared session snapshot:
  snapshot["selected_patient"]  -> {"id", "full_name", "history":[{game,played_at,
                                    difficulty,score}, ...]}  (single source of
                                    truth, set by the therapist's SELECT PATIENT)
  snapshot["config"]            -> selected_game / therapist_name (display only)
  theme                         -> constants.get_theme() via scenes.common.PALETTE

It holds NO session / game / auth / comms logic, so the whole look here can be
redesigned without touching patient_main.py, the state machine or the
dual-monitor sync. Session-state -> screen routing lives in
recovr/patient_app/patient_main.py (`_reconcile_dual` / `_draw`); the patient
Dashboard is only ever shown when a patient is actually selected.

Same left sidebar (RecovR mark, clock, Welcome card, Session History) beside a
calm main "please wait" area, now sharing the Waiting Screen's visual language
(scenes/common.py: recovr_gradient, draw_recovr_wordmark, draw_glass_card) --
pastel gradient backdrop, translucent frosted cards, and the same reused
RecovR wordmark -- so the two patient-facing screens read as one product
instead of two different UI styles bolted together.
"""

import os
import datetime
import pygame

from recovr.patient_app.scenes.common import (
    PALETTE, recovr_gradient, draw_recovr_wordmark, draw_glass_card,
    carousel_frame, sprite as _sprite,
)
# The exact same card "rectangle" (geometry + timing) as the Waiting Screen's
# instruction cards -- imported, not re-derived, so both screens use one
# definition and can never quietly drift apart. WAITING_INSTRUCTIONS and the
# WaitingScreen class itself (for its already-built wrap/shrink _draw_card,
# which already knows its own card geometry/style constants) are reused too,
# so the Dashboard's carousel shows the exact same instruction cards --
# sprite + wording + look -- as the Waiting Screen.
from recovr.patient_app.scenes.waiting_screen import (
    WaitingScreen, WAITING_INSTRUCTIONS,
    ENTER_MS as _CARD_ENTER_MS, HOLD_MS as _CARD_HOLD_MS,
    EXIT_MS as _CARD_EXIT_MS, OVERLAP_MS as _CARD_OVERLAP_MS,
    CARD_W_FRAC, CARD_H_FRAC,
)

_SEX_SPRITES = {"male": "patient_male.png", "female": "patient_female.png"}

_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "assets", "font"))
_font_cache: dict = {}


def _font(name, size, italic=False, bold=False):
    key = (name, size, italic, bold)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = pygame.font.Font(os.path.join(_FONT_DIR, name), size)
        except Exception:
            f = pygame.font.SysFont("lexend,arial,dejavusans", size, bold=bold)
        f.set_italic(bool(italic))
        try:
            f.set_bold(bool(bold) and "Bold" not in name and "Black" not in name)
        except Exception:
            pass
        _font_cache[key] = f
    return f


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


class PatientDashboardScreen:

    def __init__(self):
        self._t0 = None      # first-draw timestamp for the card's own animation clock
        # Reused only for its _draw_card() (wrap-to-fit text + icon-left/
        # text-right rendering, with its own text cache) -- never .draw()n;
        # this is what lets the Dashboard's carousel show the exact same
        # instruction cards as the Waiting Screen instead of a re-implementation.
        self._instr_card = WaitingScreen()

    def draw(self, surface: pygame.Surface, snapshot: dict | None = None):
        W, H = surface.get_size()
        snap = snapshot or {}
        sel = snap.get("selected_patient") or {}
        cfg = snap.get("config") or {}

        name = (sel.get("full_name") or cfg.get("patient_name") or "Patient").strip() or "Patient"
        history = sel.get("history") or []
        therapist = (cfg.get("therapist_name") or "").strip()
        sex_sprite = _SEX_SPRITES.get(str(sel.get("sex") or "").strip().lower())

        now = pygame.time.get_ticks()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0

        TEXT, MUTED, ACCENT = PALETTE["text"], PALETTE["muted"], PALETTE["accent"]
        dark = PALETTE["bg"][0] < 40

        # ── shared pastel backdrop (identical to the Waiting Screen) ────
        surface.blit(recovr_gradient(W, H), (0, 0))

        margin = int(W * 0.02)
        gap    = int(W * 0.022)

        # ── left sidebar: solid, flush against the edges -- same treatment
        #    as the therapist dashboard's sidebar (no rounded corners, no
        #    margin/floating, no shadow; just an opaque panel + a thin top
        #    highlight and a right-edge border line).
        rail_w = int(W * 0.27)
        rail = pygame.Rect(0, 0, rail_w, H)
        # PALETTE["panel"] is pure white in light mode -- same as the white
        # corner of the gradient behind it, so a technically-opaque fill
        # still looked like the gradient was showing through. Use the same
        # distinct light blue-grey the therapist dashboard's sidebar uses
        # (dark mode's panel colour is already distinct from its background).
        rail_fill = PALETTE["panel"] if dark else (230, 240, 252)
        surface.fill(rail_fill, rail)
        hl = pygame.Surface((rail_w, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200)); surface.blit(hl, (0, 0))
        pygame.draw.line(surface, _mix(rail_fill, (0, 0, 0), 0.12),
                         (rail_w, 0), (rail_w, H), 1)

        pad = int(rail.width * 0.11)

        # RecovR mark -- the same reused wordmark as the Waiting Screen /
        # Welcome page, sized to fit the sidebar instead of the full screen.
        logo_bottom = draw_recovr_wordmark(
            surface, rail.centerx, rail.top + int(rail.height * 0.035),
            int(rail.width * 0.82), int(rail.height * 0.075))

        # clock + date
        now = datetime.datetime.now()
        f_time = _font("ZenDots-Regular.ttf", int(H * 0.030))
        f_date = _font("Lexend-Light.ttf", int(H * 0.020))
        ty = logo_bottom + int(H * 0.026)
        t_time = f_time.render(now.strftime("%I:%M %p"), True, _mix(TEXT, MUTED, 0.15))
        t_date = f_date.render(now.strftime("%b %d, %Y"), True, MUTED)
        surface.blit(t_time, t_time.get_rect(midtop=(rail.centerx, ty)))
        date_y = ty + t_time.get_height() + int(H * 0.006)
        surface.blit(t_date, t_date.get_rect(midtop=(rail.centerx, date_y)))

        # Welcome card -- a slightly warmer frosted card nested in the rail.
        # The patient's own male/female illustration sits to the LEFT of
        # their name (same placement as the reference mock-up); falls back
        # to the previous centred text if the patient has no sex on file.
        card = pygame.Rect(rail.x + int(rail.width * 0.045),
                           date_y + t_date.get_height() + int(H * 0.03),
                           int(rail.width * 0.91), int(H * 0.155))
        draw_glass_card(surface, card, radius_frac=0.16, fill_alpha=60, border_alpha=110,
                        shadow_alpha=0, fill_color=_mix((255, 255, 255), ACCENT, 0.12))

        pad_c = int(card.width * 0.07)
        text_left = card.left + pad_c
        if sex_sprite:
            icon_size = int(card.height * 0.68)
            spr = _sprite(sex_sprite, icon_size)
            if spr is not None:
                surface.blit(spr, spr.get_rect(midleft=(card.left + pad_c, card.centery)))
                text_left = card.left + pad_c + icon_size + int(card.width * 0.06)

        f_hi   = _font("FjallaOne-Regular.ttf", int(H * 0.036))
        w_line = f_hi.render("Welcome,", True, _mix(TEXT, MUTED, 0.1))
        max_nw = card.right - int(card.width * 0.06) - text_left
        n_col  = _mix(TEXT, ACCENT, 0.22)
        n_txt  = f"{name}!"
        n_line = None
        for px in (int(H * 0.042), int(H * 0.036), int(H * 0.030), int(H * 0.025)):
            f_name = _font("FjallaOne-Regular.ttf", px)
            n_line = f_name.render(n_txt, True, n_col)
            if n_line.get_width() <= max_nw:
                break
        if n_line.get_width() > max_nw:            # still too long -> ellipsize
            t = name
            while t and f_name.size(t + "…!")[0] > max_nw:
                t = t[:-1]
            n_line = f_name.render((t + "…!") if t else "!", True, n_col)
        vgap = int(H * 0.010)
        block_h = w_line.get_height() + vgap + n_line.get_height()
        yy = card.centery - block_h // 2
        if sex_sprite:
            surface.blit(w_line, (text_left, yy))
            surface.blit(n_line, (text_left, yy + w_line.get_height() + vgap))
        else:
            surface.blit(w_line, w_line.get_rect(midtop=(card.centerx, yy)))
            surface.blit(n_line, n_line.get_rect(midtop=(card.centerx, yy + w_line.get_height() + vgap)))

        # Session History -- same list, restyled as light translucent chips
        f_sh = _font("Lexend-SemiBold.ttf", int(H * 0.025))
        sh_y = card.bottom + int(H * 0.032)
        surface.blit(f_sh.render("Session History", True, _mix(TEXT, MUTED, 0.2)),
                     (rail.x + int(rail.width * 0.07), sh_y))

        list_top = sh_y + f_sh.get_height() + int(H * 0.016)
        row_h    = max(int(H * 0.048), 24)
        f_row    = _font("Lexend-Regular.ttf", int(H * 0.021))
        f_meta   = _font("Lexend-Light.ttf", int(H * 0.017))
        clip = pygame.Rect(rail.x, list_top, rail.width, rail.bottom - list_top - int(H * 0.02))
        prev_clip = surface.get_clip()
        surface.set_clip(clip)
        if not history:
            surface.blit(f_meta.render("No sessions recorded yet.", True, MUTED),
                         (rail.x + int(rail.width * 0.07), list_top + int(H * 0.006)))
        else:
            row_gap = max(1, int(H * 0.006))
            for i, h in enumerate(history):
                ry = list_top + i * row_h
                if ry + row_h > clip.bottom:
                    break
                r = pygame.Rect(rail.x + int(rail.width * 0.045), ry,
                                rail.width - int(rail.width * 0.09), row_h - row_gap)
                # Was barely-there (alpha 26/12) against a near-white rail;
                # raised so each row reads as a clearly visible chip in light mode.
                chip_alpha = 150 if i % 2 == 0 else 90
                draw_glass_card(surface, r, radius_frac=0.28, fill_alpha=chip_alpha,
                                border_alpha=100, shadow_alpha=0)
                gs = f_row.render(str(h.get("game", "-")), True, _mix(TEXT, MUTED, 0.08))
                surface.blit(gs, gs.get_rect(midleft=(r.x + int(rail.width * 0.045), r.centery)))
                dt = str(h.get("played_at", ""))[:10]
                if dt:
                    ds = f_meta.render(dt, True, MUTED)
                    if gs.get_width() + ds.get_width() + int(rail.width * 0.10) < r.width:
                        surface.blit(ds, ds.get_rect(midright=(r.right - int(rail.width * 0.045), r.centery)))
        surface.set_clip(prev_clip)

        # ── main area: a STILL, centred title sitting above a carousel of
        #    cards -- the exact same "rectangle" recipe as the Waiting Screen
        #    (same geometry fractions, same frosted-glass shell, same
        #    slide-in/hold/slide-out motion). The cards themselves are the
        #    SAME four preparation instructions -- text and sprite -- shown on
        #    the Waiting Screen (WAITING_INSTRUCTIONS), reusing WaitingScreen's
        #    own _draw_card so they are pixel-identical, not a
        #    re-implementation. No personalised/sex-icon card here anymore. ──
        main_x = rail.right + gap
        main = pygame.Rect(main_x, margin, W - main_x - margin, H - 2 * margin)

        f_wait = _font("Sora-Light.ttf", int(H * 0.026), italic=True)
        # darken the accent slightly in light mode for contrast against the
        # pale gradient backdrop; dark mode keeps the accent as-is (already light)
        accent_col = ACCENT if dark else _mix(ACCENT, (10, 20, 45), 0.28)
        # matches the Waiting Screen's own instruction-card text colour exactly
        instr_text_col = TEXT if dark else (92, 94, 104)

        # One line, one style (same bold + accent look "preparing your
        # session." used to have alone) -- shrink-to-fit so it never wraps.
        head_txt  = "Your therapist is preparing your session."
        head_size = int(H * 0.043)
        max_head_w = int(main.width * 0.96)
        f_head = _font("Sora-Bold.ttf", head_size, bold=True)
        l1 = f_head.render(head_txt, True, accent_col)
        while l1.get_width() > max_head_w and head_size > 14:
            head_size -= 1
            f_head = _font("Sora-Bold.ttf", head_size, bold=True)
            l1 = f_head.render(head_txt, True, accent_col)
        l3 = f_wait.render("Please wait…", True, MUTED)

        ty2 = main.top + int(H * 0.075)   # a little lower than before
        for line in (l1, l3):
            surface.blit(line, line.get_rect(midtop=(main.centerx, ty2)))
            ty2 += line.get_height() + int(H * 0.012)
        title_bottom = ty2 + int(H * 0.015)

        # the carousel of instruction cards, sized/positioned in the space
        # left below the still title (and above the therapist line at the
        # very bottom), using the Waiting Screen's own proportions
        card_w = int(main.width * CARD_W_FRAC)
        avail_bottom = main.bottom - int(H * 0.06)
        card_h = min(int(main.height * CARD_H_FRAC), max(1, avail_bottom - title_bottom))
        card_y = title_bottom + max(0, (avail_bottom - title_bottom - card_h) // 2)
        card = pygame.Rect(0, card_y, card_w, card_h)

        N = len(WAITING_INSTRUCTIONS)
        frame = carousel_frame(t, main.width, card_w, N, enter_ms=_CARD_ENTER_MS,
                               hold_ms=_CARD_HOLD_MS, exit_ms=_CARD_EXIT_MS,
                               overlap_ms=_CARD_OVERLAP_MS)
        for idx, x, a in frame:
            r = card.copy()
            r.centerx = main.left + x
            instr_text, instr_sprite = WAITING_INSTRUCTIONS[idx]
            self._instr_card._draw_card(surface, r, instr_text_col, instr_text,
                                        sprite_name=instr_sprite, alpha_scale=a)

        if therapist:
            f_th = _font("Lexend-Light.ttf", int(H * 0.021))
            ts = f_th.render(f"Therapist:  {therapist}", True, _mix(MUTED, ACCENT, 0.3))
            surface.blit(ts, ts.get_rect(midbottom=(main.centerx, main.bottom - int(H * 0.015))))
