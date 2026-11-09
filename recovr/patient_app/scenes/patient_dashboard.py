"""
Patient Dashboard  --  the patient monitor view shown while a patient is
selected (before / between sessions).

PURE VIEW. `draw(surface, snapshot)` only *reads* the shared session snapshot:
  snapshot["selected_patient"] -> {
      "id", "full_name", "sex",
      "history": [{game, played_at, difficulty, score, status, goal,
                   completed_reps, duration_sec, session_mode,
                   configured_duration_seconds}, ...],   # newest first
      "stats":   {total_sessions, games_played,
                   goals_assigned, goals_completed} | None,
  }
  snapshot["config"] -> therapist_name (display only)
  theme              -> constants.get_theme() via scenes.common.PALETTE

`history` and `stats` are real database.py columns/queries (see
database.py's `sessions` table and `get_patient_progress_summary()`), pushed
by scenes/therapist_dashboard.py's `_push_selected_patient()` and carried
verbatim through recovr/shared/session_state.py -- nothing here is invented.
The one card with no backing data at all (Rehabilitation Progress's
Grip Strength / Finger Control / Wrist Movement sub-metrics -- there is no
per-session sensor-performance persistence anywhere in the app, only a
one-time calibration baseline and transient live telemetry that is never
saved) is drawn in an explicit "not yet available" state rather than a
fabricated percentage.

It holds NO session / game / auth / comms logic, so the whole look here can
be redesigned without touching patient_main.py, the state machine or the
dual-monitor sync. Session-state -> screen routing lives in
recovr/patient_app/patient_main.py (`_reconcile_dual` / `_draw`); the patient
Dashboard is only ever shown when a patient is actually selected.

Full-width layout (no sidebar): a header row (logo / live clock / welcome
card) above a 2x2 grid of cards -- Rehabilitation Progress, Rehabilitation
Summary, Latest Session, Next Session -- sharing the same pastel-gradient +
frosted-glass-card visual language as the Waiting Screen
(scenes/common.py: recovr_gradient, draw_glass_card, draw_recovr_wordmark).
"""

import os
import math
import datetime
import pygame

from recovr.patient_app.scenes.common import (
    PALETTE, recovr_gradient, draw_recovr_wordmark, draw_glass_card,
    sprite as _sprite,
)
from recovr.patient_app.scenes.waiting_screen import NAVY_TEXT

_SEX_SPRITES = {"male": "patient_male.png", "female": "patient_female.png"}

# game= string (exactly as games/*.py _save_session() writes it) -> its own
# icon asset and the game-specific result-metric label its Round Complete
# screen already uses (see games/*.py _draw_results()).
_GAME_ICONS = {
    "Basketball":        "basketball_icon.png",
    "Piano Tiles":        "piano_tiles_icon.png",
    "Lemonade":           "lemonade_icon.png",
    "Apple Catching":     "apple_catching_icon.png",
    "Key and Lock":       "key_and_lock_icon.png",
    "Plant the Garden":   "plant_the_garden_icon.png",
    "Steady Aim":         "steady_aim_icon.png",
    "Catch 'n Grab":      "catch_n_grab_icon.png",
    "Feed the Cat":       "feed_the_cat_icon.png",
}
_GAME_METRIC_LABELS = {
    "Basketball":        "Shots Made",
    "Piano Tiles":        "Tiles Hit",
    "Lemonade":           "Lemons Squeezed",
    "Apple Catching":     "Apples Caught",
    "Key and Lock":       "Locks Opened",
    "Plant the Garden":   "Plants Grown",
    "Steady Aim":         "Shots Fired",
    "Catch 'n Grab":      "Caught",
    "Feed the Cat":       "Cats Fed",
}

# Real icon assets for the Rehabilitation Progress sub-metric rows and the
# Rehabilitation Summary rows -- replaces the hand-drawn _draw_icon()
# vector glyphs for these specific rows only (their card-title icons, e.g.
# Next Session's "calendar" glyph, are untouched). Falls back to the vector
# glyph if an asset is ever missing, same graceful-degradation pattern used
# everywhere else image assets are loaded in this app.
_PROGRESS_ICON_ASSETS = {
    "hand":   "hand_mobility.png",
    "finger": "finger_control.png",
    "wrist":  "wrist_movement.png",
}
_SUMMARY_ICON_ASSETS = {
    "calendar":   "total_sessions.png",
    "controller": "games_played.png",
    "target":     "goals_completed.png",
}

_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "assets", "font"))
_font_cache: dict = {}


def _font(weight, size):
    """Poppins only, per the dashboard's typography spec -- Bold for
    headings/values/time, SemiBold for secondary values, Medium for labels,
    Regular for supporting text."""
    key = (weight, size)
    f = _font_cache.get(key)
    if f is None:
        try:
            f = pygame.font.Font(os.path.join(_FONT_DIR, f"Poppins-{weight}.ttf"), size)
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


# pygame.draw.* silently IGNORES the alpha component of an (r,g,b,a) color
# when drawing directly onto a non-SRCALPHA surface (confirmed empirically --
# it draws fully opaque instead) -- every "subtle" translucent divider/track/
# chip in this file is drawn onto a small SRCALPHA surface first, then
# blitted, so its alpha actually takes effect.
def _alpha_line(surface, color4, p1, p2, width=1):
    pad = max(width, 1) * 2
    minx, maxx = min(p1[0], p2[0]) - pad, max(p1[0], p2[0]) + pad
    miny, maxy = min(p1[1], p2[1]) - pad, max(p1[1], p2[1]) + pad
    w, h = max(1, int(maxx - minx)), max(1, int(maxy - miny))
    tmp = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.line(tmp, color4, (p1[0] - minx, p1[1] - miny), (p2[0] - minx, p2[1] - miny), width)
    surface.blit(tmp, (minx, miny))


def _alpha_rect(surface, color4, rect, border_radius=0, width=0):
    tmp = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(tmp, color4, tmp.get_rect(), width, border_radius=border_radius)
    surface.blit(tmp, rect.topleft)


def _alpha_circle(surface, color4, center, radius, width=0):
    d = max(1, radius * 2)
    tmp = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(tmp, color4, (radius, radius), radius, width)
    surface.blit(tmp, (center[0] - radius, center[1] - radius))


def _fmt_duration(total_sec):
    total_sec = max(0, int(total_sec or 0))
    m, s = divmod(total_sec, 60)
    return f"{m:02d}:{s:02d}"


def _parse_played_at(raw):
    raw = str(raw or "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw[:19], fmt)
        except Exception:
            continue
    return None


def _draw_icon(surface, kind, rect, color, width=None):
    """Small, simple vector icons drawn with primitives (no new asset files,
    no emoji/Unicode glyphs) -- category markers for card titles and summary
    rows, sized to fit `rect`."""
    cx, cy = rect.center
    s = min(rect.width, rect.height)
    w = width or max(2, int(s * 0.09))

    if kind == "chart":                          # Rehabilitation Progress
        bw = max(2, int(s * 0.18))
        gap = max(1, int(s * 0.08))
        heights = (0.42, 0.68, 1.0)
        total_w = bw * 3 + gap * 2
        x0 = cx - total_w // 2
        base = rect.bottom - int(s * 0.1)
        top = rect.top + int(s * 0.08)
        for i, hfrac in enumerate(heights):
            bh = max(2, int((base - top) * hfrac))
            bx = x0 + i * (bw + gap)
            pygame.draw.rect(surface, color, (bx, base - bh, bw, bh),
                             border_radius=max(1, bw // 3))
    elif kind == "clipboard":                     # Rehabilitation Summary
        bw, bh = int(s * 0.62), int(s * 0.78)
        br = pygame.Rect(0, 0, bw, bh); br.center = (cx, cy + int(s * 0.03))
        pygame.draw.rect(surface, color, br, w, border_radius=max(2, int(s * 0.1)))
        tw, th = int(bw * 0.42), max(2, int(s * 0.1))
        tr = pygame.Rect(0, 0, tw, th); tr.midtop = (cx, br.top - th // 2)
        pygame.draw.rect(surface, color, tr, border_radius=max(1, th // 2))
        for i in range(3):
            ly = br.top + int(bh * (0.32 + i * 0.22))
            pygame.draw.line(surface, color,
                             (br.left + int(bw * 0.18), ly), (br.right - int(bw * 0.18), ly), w)
    elif kind == "clock":                         # Latest Session
        r = int(s * 0.42)
        pygame.draw.circle(surface, color, (cx, cy), r, w)
        pygame.draw.line(surface, color, (cx, cy), (cx, cy - int(r * 0.6)), w)
        pygame.draw.line(surface, color, (cx, cy), (cx + int(r * 0.45), cy + int(r * 0.1)), w)
    elif kind == "calendar":                      # Next Session
        bw, bh = int(s * 0.74), int(s * 0.68)
        br = pygame.Rect(0, 0, bw, bh); br.center = (cx, cy + int(s * 0.04))
        pygame.draw.rect(surface, color, br, w, border_radius=max(2, int(s * 0.08)))
        band_y = br.top + int(bh * 0.28)
        pygame.draw.line(surface, color, (br.left, band_y), (br.right, band_y), w)
        for fx in (br.left + int(bw * 0.22), br.right - int(bw * 0.22)):
            pygame.draw.line(surface, color, (fx, br.top - int(bh * 0.14)), (fx, band_y), w)
    elif kind == "hand":                          # Grip Strength
        pw, ph = int(s * 0.5), int(s * 0.36)
        palm = pygame.Rect(0, 0, pw, ph); palm.midbottom = (cx, rect.bottom - int(s * 0.12))
        pygame.draw.rect(surface, color, palm, border_radius=int(ph * 0.4))
        fx0 = palm.left + int(pw * 0.12)
        for i in range(4):
            fx = fx0 + i * int(pw * 0.25)
            fy0 = palm.top
            fy1 = rect.top + int(s * 0.1) + (abs(i - 1.5) * int(s * 0.05))
            pygame.draw.line(surface, color, (fx, fy0), (fx, fy1), max(2, int(s * 0.1)))
            pygame.draw.circle(surface, color, (fx, fy1), max(2, int(s * 0.05)))
    elif kind == "finger":                        # Finger Control
        top = (cx, rect.top + int(s * 0.12))
        bot = (cx, rect.bottom - int(s * 0.12))
        pygame.draw.line(surface, color, bot, top, max(3, int(s * 0.14)))
        pygame.draw.circle(surface, color, top, max(3, int(s * 0.1)))
    elif kind == "wrist":                         # Wrist Movement
        r = int(s * 0.36)
        arc_rect = pygame.Rect(0, 0, r * 2, r * 2); arc_rect.center = (cx, cy)
        pygame.draw.arc(surface, color, arc_rect, math.radians(-40), math.radians(220), w)
        ang = math.radians(220)
        tip = (cx + int(r * math.cos(ang)), cy + int(r * math.sin(ang)))
        perp = ang - math.pi / 2
        a1 = (tip[0] - int(s * 0.12 * math.cos(ang - 0.6)), tip[1] - int(s * 0.12 * math.sin(ang - 0.6)))
        pygame.draw.line(surface, color, tip, a1, w)
    elif kind == "target":                        # Goals Completed
        for frac in (1.0, 0.62):
            pygame.draw.circle(surface, color, (cx, cy), int(s * 0.42 * frac), w)
        pygame.draw.circle(surface, color, (cx, cy), max(2, int(s * 0.1)))
    elif kind == "controller":                    # Games Played
        bw, bh = int(s * 0.78), int(s * 0.42)
        br = pygame.Rect(0, 0, bw, bh); br.center = (cx, cy)
        pygame.draw.rect(surface, color, br, w, border_radius=int(bh * 0.5))
        dr = max(2, int(s * 0.07))
        pygame.draw.circle(surface, color, (br.right - int(bw * 0.24), br.centery - int(bh * 0.12)), dr)
        pygame.draw.circle(surface, color, (br.right - int(bw * 0.12), br.centery + int(bh * 0.1)), dr)
        plx, ply = br.left + int(bw * 0.2), br.centery
        pygame.draw.line(surface, color, (plx - dr, ply), (plx + dr, ply), max(2, int(s * 0.05)))
        pygame.draw.line(surface, color, (plx, ply - dr), (plx, ply + dr), max(2, int(s * 0.05)))


class PatientDashboardScreen:

    def __init__(self):
        self._t0 = None   # first-draw timestamp (Next Session's spinner clock)

    # -- helpers -------------------------------------------------------
    def _card_shell(self, surface, rect, title, icon_kind, C, accent):
        """Glass card + title row (icon + heading). Returns the content Rect
        below the title for the caller to fill."""
        draw_glass_card(surface, rect, radius_frac=0.05, fill_alpha=C["card_fill"],
                        border_alpha=C["card_border"], shadow_alpha=20,
                        fill_color=C["card_color"], border_color=C["card_border_color"])

        pad_x = int(rect.width * 0.045)
        pad_y = int(rect.height * 0.055)
        f_title = _font("Bold", max(16, int(rect.height * 0.082)))
        icon_box = f_title.get_height()
        icon_rect = pygame.Rect(rect.left + pad_x, rect.top + pad_y, icon_box, icon_box)
        _draw_icon(surface, icon_kind, icon_rect, accent)

        t_s = f_title.render(title, True, C["heading"])
        surface.blit(t_s, (icon_rect.right + int(pad_x * 0.6),
                           icon_rect.centery - t_s.get_height() // 2))

        title_bottom = max(icon_rect.bottom, icon_rect.top + t_s.get_height())
        div_y = title_bottom + int(rect.height * 0.045)
        _alpha_line(surface, C["divider"], (rect.left + pad_x, div_y),
                   (rect.right - pad_x, div_y), 1)

        content_top = div_y + int(rect.height * 0.04)
        return pygame.Rect(rect.left + pad_x, content_top,
                           rect.width - 2 * pad_x, rect.bottom - pad_y - content_top)

    def _draw_progress_card(self, surface, rect, C, accent):
        content = self._card_shell(surface, rect, "Rehabilitation Progress", "chart", C, accent)

        ring_d = min(int(content.width * 0.34), content.height)
        ring_r = ring_d // 2
        ring_c = (content.left + ring_r, content.centery)
        ring_w = max(6, int(ring_d * 0.1))
        ring_rect = pygame.Rect(0, 0, ring_d - ring_w, ring_d - ring_w)
        ring_rect.center = ring_c
        _alpha_circle(surface, C["track"], ring_c, ring_r - ring_w // 2, ring_w)

        f_pct = _font("Bold", max(18, int(ring_d * 0.26)))
        f_sub = _font("Medium", max(11, int(ring_d * 0.09)))
        pct_s = f_pct.render("—", True, C["muted"])
        sub_s = f_sub.render("Not tracked yet", True, C["muted"])
        # The dash + label are one vertically-centred group inside the ring
        # (not two independently-placed lines) -- their combined height is
        # centred on the ring's own centre, so "Not tracked yet" can never
        # drift down toward the stroke regardless of font metrics.
        inner_gap = max(2, int(ring_d * 0.035))
        block_h = pct_s.get_height() + inner_gap + sub_s.get_height()
        block_top = ring_c[1] - block_h // 2
        surface.blit(pct_s, pct_s.get_rect(centerx=ring_c[0], top=block_top))
        surface.blit(sub_s, sub_s.get_rect(centerx=ring_c[0], top=block_top + pct_s.get_height() + inner_gap))

        rows_x = content.left + ring_d + int(content.width * 0.06)
        rows_w = content.right - rows_x
        rows = [("hand", "Grip Strength"), ("finger", "Finger Control"), ("wrist", "Wrist Movement")]
        row_h = content.height / len(rows)
        f_lbl = _font("Medium", max(13, int(row_h * 0.26)))
        f_val = _font("SemiBold", max(12, int(row_h * 0.22)))
        for i, (kind, label) in enumerate(rows):
            ry = content.top + int(row_h * i)
            icon_sz = int(row_h * 0.58)
            irect = pygame.Rect(rows_x, 0, icon_sz, icon_sz)
            irect.centery = int(ry + row_h / 2)
            asset = _PROGRESS_ICON_ASSETS.get(kind)
            spr = _sprite(asset, icon_sz, crop=True) if asset else None
            if spr is not None:
                surface.blit(spr, spr.get_rect(center=irect.center))
            else:
                _draw_icon(surface, kind, irect, _mix(accent, C["muted"], 0.35))

            lbl_x = irect.right + int(content.width * 0.025)
            lbl_s = f_lbl.render(label, True, C["body"])
            surface.blit(lbl_s, (lbl_x, ry + int(row_h * 0.06)))

            bar_y = ry + int(row_h * 0.06) + lbl_s.get_height() + int(row_h * 0.08)
            bar_w = rows_w - (lbl_x - rows_x)
            bar_h = max(6, int(row_h * 0.16))
            bar_r = pygame.Rect(lbl_x, bar_y, max(1, bar_w), bar_h)
            _alpha_rect(surface, C["track"], bar_r, border_radius=bar_h // 2)
            val_s = f_val.render("Not yet available", True, C["muted"])
            surface.blit(val_s, (lbl_x, bar_y + bar_h + int(row_h * 0.05)))

        note = _font("Regular", max(11, int(rect.height * 0.034))).render(
            "Detailed mobility metrics aren't tracked by the system yet.", True, C["muted"])
        if note.get_width() <= rect.width - int(rect.width * 0.09):
            surface.blit(note, (rect.left + int(rect.width * 0.045),
                                rect.bottom - int(rect.height * 0.05) - note.get_height()))

    def _draw_summary_card(self, surface, rect, C, accent, stats):
        content = self._card_shell(surface, rect, "Rehabilitation Summary", "clipboard", C, accent)

        total = stats.get("total_sessions") if stats else None
        games = stats.get("games_played") if stats else None
        g_done = stats.get("goals_completed") if stats else None
        g_assigned = stats.get("goals_assigned") if stats else None

        goals_txt = "Not Yet Available"
        goals_pill = False
        if stats is not None and (g_assigned or 0) > 0:
            goals_txt = f"{g_done}/{g_assigned}"
            goals_pill = True

        rows = [
            ("calendar", "Total Sessions", "Not Yet Available" if total is None else str(total), False),
            ("controller", "Games Played", "Not Yet Available" if games is None else str(games), False),
            ("target", "Goals Completed", goals_txt, goals_pill),
        ]
        row_h = content.height / len(rows)
        f_lbl = _font("Medium", max(14, int(row_h * 0.3)))
        f_val = _font("Bold", max(16, int(row_h * 0.36)))
        f_val_na = _font("SemiBold", max(12, int(row_h * 0.22)))
        for i, (kind, label, value, pill) in enumerate(rows):
            ry = int(content.top + row_h * i + row_h * 0.5)
            icon_sz = int(row_h * 0.64)
            irect = pygame.Rect(content.left, ry - icon_sz // 2, icon_sz, icon_sz)
            asset = _SUMMARY_ICON_ASSETS.get(kind)
            spr = _sprite(asset, icon_sz, crop=True) if asset else None
            if spr is not None:
                surface.blit(spr, spr.get_rect(center=irect.center))
            else:
                _draw_icon(surface, kind, irect, accent)

            lbl_s = f_lbl.render(label, True, C["body"])
            surface.blit(lbl_s, (irect.right + int(content.width * 0.04),
                                 ry - lbl_s.get_height() // 2))

            available = value != "Not Yet Available"
            vf = f_val if available else f_val_na
            vcol = accent if available else C["muted"]
            v_s = vf.render(value, True, (C["white"] if (pill and available) else vcol))
            if pill and available:
                chip_pad_x, chip_pad_y = int(row_h * 0.16), int(row_h * 0.1)
                chip = pygame.Rect(0, 0, v_s.get_width() + chip_pad_x * 2,
                                   v_s.get_height() + chip_pad_y * 2)
                chip.midright = (content.right, ry)
                pygame.draw.rect(surface, accent, chip, border_radius=chip.height // 2)
                surface.blit(v_s, v_s.get_rect(center=chip.center))
            elif available:
                chip_pad_x, chip_pad_y = int(row_h * 0.14), int(row_h * 0.08)
                chip = pygame.Rect(0, 0, v_s.get_width() + chip_pad_x * 2,
                                   v_s.get_height() + chip_pad_y * 2)
                chip.midright = (content.right, ry)
                _alpha_rect(surface, C["chip_bg"], chip, border_radius=int(chip.height * 0.3))
                surface.blit(v_s, v_s.get_rect(center=chip.center))
            else:
                surface.blit(v_s, v_s.get_rect(midright=(content.right, ry)))

    def _draw_latest_session_card(self, surface, rect, C, accent, history):
        content = self._card_shell(surface, rect, "Latest Session", "clock", C, accent)

        latest = next((h for h in (history or []) if h.get("status", "completed") == "completed"), None)
        if latest is None:
            f_empty = _font("Medium", max(14, int(rect.height * 0.055)))
            e_s = f_empty.render("No sessions completed yet.", True, C["muted"])
            surface.blit(e_s, e_s.get_rect(center=content.center))
            return

        game = str(latest.get("game", ""))
        icon_name = _GAME_ICONS.get(game)
        metric_label = _GAME_METRIC_LABELS.get(game, "Repetitions")

        # Left section: icon centred on top, game name / date / time stacked
        # below it on three separate lines, the whole block centred as one
        # unit (horizontally within the section, vertically within the card).
        left_w = int(content.width * 0.34)
        left_section = pygame.Rect(content.left, content.top, left_w, content.height)
        cx = left_section.centerx
        max_text_w = left_section.width - int(content.width * 0.015)

        icon_sz = int(content.height * 0.4)
        spr = _sprite(icon_name, icon_sz, crop=True) if icon_name else None

        f_name = None
        for px in range(int(content.height * 0.135), int(content.height * 0.07), -1):
            cand = _font("Bold", px).render(game or "Game", True, C["heading"])
            if cand.get_width() <= max_text_w:
                f_name = cand; break
        if f_name is None:
            f_name = _font("Bold", int(content.height * 0.07)).render(game or "Game", True, C["heading"])

        dt = _parse_played_at(latest.get("played_at"))
        f_date = _font("Medium", max(10, int(content.height * 0.065)))
        f_time = _font("Medium", max(10, int(content.height * 0.065)))
        date_s = f_date.render(dt.strftime("%b %d, %Y"), True, C["body"]) if dt else None
        time_s = f_time.render(dt.strftime("%I:%M %p"), True, C["muted"]) if dt else None

        line_gap = max(2, int(content.height * 0.018))
        icon_gap = max(4, int(content.height * 0.03))
        block_h = icon_sz + icon_gap + f_name.get_height()
        if date_s is not None:
            block_h += line_gap + date_s.get_height()
        if time_s is not None:
            block_h += line_gap + time_s.get_height()

        by = left_section.centery - block_h // 2
        if spr is not None:
            surface.blit(spr, spr.get_rect(center=(cx, by + icon_sz // 2)))
        by += icon_sz + icon_gap
        surface.blit(f_name, f_name.get_rect(centerx=cx, top=by))
        by += f_name.get_height()
        if date_s is not None:
            by += line_gap
            surface.blit(date_s, date_s.get_rect(centerx=cx, top=by))
            by += date_s.get_height()
        if time_s is not None:
            by += line_gap
            surface.blit(time_s, time_s.get_rect(centerx=cx, top=by))

        div_x = left_section.right + int(content.width * 0.02)
        _alpha_line(surface, C["divider"], (div_x, content.top), (div_x, content.bottom), 1)

        stat_x = div_x + int(content.width * 0.04)
        stat_w = content.right - stat_x
        completed_reps = latest.get("completed_reps")
        goal = latest.get("goal")
        if completed_reps is None:
            result_txt = "—"
        elif goal:
            result_txt = f"{completed_reps}/{goal}"
        else:
            result_txt = str(completed_reps)

        stats_rows = [
            ("Score", str(latest.get("score", "—"))),
            (metric_label, result_txt),
            ("Duration", _fmt_duration(latest.get("duration_sec", 0))),
        ]
        row_h = content.height / len(stats_rows)
        f_slbl = _font("Medium", max(13, int(row_h * 0.34)))
        f_sval = _font("Bold", max(14, int(row_h * 0.36)))
        for i, (lbl, val) in enumerate(stats_rows):
            ry = content.top + row_h * (i + 0.5)
            l_s = f_slbl.render(lbl, True, C["body"])
            surface.blit(l_s, (stat_x, ry - l_s.get_height() // 2))
            v_s = f_sval.render(val, True, accent)
            surface.blit(v_s, v_s.get_rect(midright=(stat_x + stat_w, ry)))
            if i < len(stats_rows) - 1:
                sep_y = content.top + row_h * (i + 1)
                _alpha_line(surface, C["divider"], (stat_x, sep_y), (stat_x + stat_w, sep_y), 1)

    def _draw_next_session_card(self, surface, rect, C, accent, t_ms):
        content = self._card_shell(surface, rect, "Next Session", "calendar", C, accent)

        f_sub = _font("Regular", max(13, int(rect.height * 0.055)))
        sub_lines = _wrap("Your therapist is preparing your session.", f_sub, content.width)
        sub_surfs = [f_sub.render(ln, True, C["body"]) for ln in sub_lines]
        for i, s in enumerate(sub_surfs):
            surface.blit(s, (content.left, content.top + i * s.get_height()))
        sub_h = sum(s.get_height() for s in sub_surfs)

        pill_top = content.top + sub_h + int(content.height * 0.08)
        avail_h = max(1, content.bottom - pill_top)
        pill_h = min(avail_h, max(1, int(rect.height * 0.42)))
        pill = pygame.Rect(content.left, pill_top + (avail_h - pill_h) // 2, content.width, pill_h)
        pygame.draw.rect(surface, C["pill_a"], pill, border_radius=int(pill_h * 0.3))
        shade = pygame.Surface(pill.size, pygame.SRCALPHA)
        pygame.draw.rect(shade, (*C["pill_b"], 120), shade.get_rect(), border_radius=int(pill_h * 0.3))
        surface.blit(shade, pill.topleft)

        spin_d = int(pill_h * 0.4)
        spin_c = (pill.left + int(pill.height * 0.55), pill.centery)
        ang = (t_ms / 900.0) % (2 * math.pi)
        spin_rect = pygame.Rect(0, 0, spin_d, spin_d); spin_rect.center = spin_c
        _alpha_circle(surface, (255, 255, 255, 90), spin_c, spin_d // 2, max(3, spin_d // 8))
        pygame.draw.arc(surface, (255, 255, 255), spin_rect, ang, ang + math.pi * 1.1, max(3, spin_d // 8))

        text_x = spin_c[0] + spin_d // 2 + int(pill.height * 0.22)
        max_text_w = pill.right - int(pill.height * 0.22) - text_x
        fsz = max(14, int(pill_h * 0.3))
        p_s = None
        while fsz >= 14:
            f_pill = _font("Bold", fsz)
            p_s = f_pill.render("Getting ready…", True, (255, 255, 255))
            if p_s.get_width() <= max_text_w:
                break
            fsz -= 1
        surface.blit(p_s, p_s.get_rect(midleft=(text_x, pill.centery)))

    # -- main -------------------------------------------------------
    def draw(self, surface: pygame.Surface, snapshot: dict | None = None):
        W, H = surface.get_size()
        now_ms = pygame.time.get_ticks()
        if self._t0 is None:
            self._t0 = now_ms
        t_ms = now_ms - self._t0

        snap = snapshot or {}
        sel = snap.get("selected_patient") or {}
        name = (sel.get("full_name") or "Patient").strip() or "Patient"
        history = sel.get("history") or []
        stats = sel.get("stats")
        sex_sprite = _SEX_SPRITES.get(str(sel.get("sex") or "").strip().lower())

        dark = PALETTE["bg"][0] < 40
        heading = PALETTE["text"] if dark else NAVY_TEXT
        body = PALETTE["text"] if dark else _mix(NAVY_TEXT, (255, 255, 255), 0.25)
        muted = (195, 215, 235) if dark else (80, 101, 137)
        accent = (18, 216, 230) if dark else (19, 193, 203)
        accent_blue = (35, 137, 245) if dark else (24, 120, 217)
        C = {
            "heading": heading, "body": body, "muted": muted, "white": (255, 255, 255),
            "divider": (255, 255, 255, 40) if dark else (24, 60, 110, 28),
            "track": (255, 255, 255, 35) if dark else (24, 60, 110, 22),
            "chip_bg": (255, 255, 255, 30) if dark else (24, 60, 110, 18),
            "card_fill": 46 if dark else 150, "card_border": 70 if dark else 110,
            "card_color": (120, 165, 235) if dark else (255, 255, 255),
            "card_border_color": (110, 150, 220) if dark else (170, 200, 235),
            "pill_a": accent_blue, "pill_b": (90, 60, 220) if dark else (100, 170, 250),
        }

        surface.blit(recovr_gradient(W, H), (0, 0))

        margin = int(W * 0.025)
        header_h = int(H * 0.135)

        # ── header: logo (left) | welcome card (centre) | time/date (right) ──
        logo_box_w = int(W * 0.16)
        draw_recovr_wordmark(surface, margin + logo_box_w // 2,
                             margin + int(header_h * 0.08),
                             logo_box_w, int(header_h * 0.6))
        logo_right = margin + logo_box_w

        # Time/date -- right-aligned block at the far right, time prominent
        # above the smaller date, same live-clock formatting as before.
        now_dt = datetime.datetime.now()
        f_time = _font("Bold", int(header_h * 0.36))
        f_date = _font("Regular", int(header_h * 0.17))
        time_s = f_time.render(now_dt.strftime("%I:%M %p"), True, heading)
        date_s = f_date.render(now_dt.strftime("%b %d, %Y"), True, muted)
        td_right = W - margin
        ty = margin + header_h // 2 - (time_s.get_height() + date_s.get_height()) // 2
        surface.blit(time_s, time_s.get_rect(topright=(td_right, ty)))
        surface.blit(date_s, date_s.get_rect(topright=(td_right, ty + time_s.get_height())))
        td_left = td_right - max(time_s.get_width(), date_s.get_width())

        # Welcome card -- centred in the space between the logo and the
        # time/date block, with a significantly larger profile icon and
        # patient-name type than before (it's the header's focal point now).
        side_gap = int(W * 0.02)
        mid_left = logo_right + side_gap
        mid_right = td_left - side_gap
        mid_w = max(10, mid_right - mid_left)

        icon_sz = int(header_h * 0.74)
        pad_in = int(header_h * 0.13)
        f_w1 = _font("Medium", max(10, int(header_h * 0.16)))
        w1_s = f_w1.render("Welcome,", True, body)

        reserved = (icon_sz + pad_in * 3 if sex_sprite else pad_in * 2)
        max_name_w = max(20, mid_w - reserved)
        w2_s = None
        for px in range(int(header_h * 0.32), int(header_h * 0.15), -1):
            cand = _font("Bold", px).render(f"{name}!", True, heading)
            if cand.get_width() <= max_name_w:
                w2_s = cand; break
        if w2_s is None:
            w2_s = _font("Bold", int(header_h * 0.15)).render(f"{name}!", True, heading)

        text_w = max(w1_s.get_width(), w2_s.get_width())
        card_w = min(mid_w, (icon_sz + pad_in * 3 + text_w) if sex_sprite else (text_w + pad_in * 2))
        card_h = int(header_h * 0.9)
        card = pygame.Rect(0, 0, card_w, card_h)
        card.center = ((mid_left + mid_right) // 2, margin + header_h // 2)
        draw_glass_card(surface, card, radius_frac=0.3, fill_alpha=C["card_fill"],
                        border_alpha=C["card_border"], shadow_alpha=16,
                        fill_color=C["card_color"], border_color=C["card_border_color"])
        tleft = card.left + pad_in
        if sex_sprite:
            spr = _sprite(sex_sprite, icon_sz, crop=True)
            if spr is not None:
                surface.blit(spr, spr.get_rect(midleft=(tleft, card.centery)))
                tleft += icon_sz + pad_in
        vgap = max(1, int(card_h * 0.04))
        block_h = w1_s.get_height() + vgap + w2_s.get_height()
        ty2 = card.centery - block_h // 2
        surface.blit(w1_s, (tleft, ty2))
        surface.blit(w2_s, (tleft, ty2 + w1_s.get_height() + vgap))

        # ── 2x2 card grid ───────────────────────────────────────────────
        grid_top = margin + header_h + int(H * 0.025)
        grid_bottom = H - margin
        row_gap = int(H * 0.025)
        col_gap = int(W * 0.02)
        content_w = W - 2 * margin
        left_w = int(content_w * 0.58)
        right_w = content_w - col_gap - left_w
        row_h = (grid_bottom - grid_top - row_gap) / 2

        progress_r = pygame.Rect(margin, int(grid_top), left_w, int(row_h))
        summary_r  = pygame.Rect(margin + left_w + col_gap, int(grid_top), right_w, int(row_h))
        row2_y = int(grid_top + row_h + row_gap)
        latest_r = pygame.Rect(margin, row2_y, left_w, int(row_h))
        next_r   = pygame.Rect(margin + left_w + col_gap, row2_y, right_w, int(row_h))

        self._draw_progress_card(surface, progress_r, C, accent)
        self._draw_summary_card(surface, summary_r, C, accent, stats)
        self._draw_latest_session_card(surface, latest_r, C, accent, history)
        self._draw_next_session_card(surface, next_r, C, accent_blue, t_ms)
