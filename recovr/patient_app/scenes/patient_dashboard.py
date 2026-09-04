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

Layout follows the provided reference: a fixed left sidebar (RecovR mark, clock,
a prominent Welcome card, Session History) beside a large, calm main area with a
centred "please wait" message. Everything is proportional to the real patient
display size and theme-aware.
"""

import os
import datetime
import pygame

from recovr.patient_app.scenes.common import PALETTE

_FONT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "assets", "font"))
_font_cache: dict = {}
_grad_cache: dict = {}


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


def _main_gradient(w, h, bg, accent):
    """A soft 2x2 bilinear wash for the main area -- lighter top-left, a faint
    accent tint bottom-right (matches the reference's calm background)."""
    key = (w, h, bg, accent)
    g = _grad_cache.get(key)
    if g is None:
        s = pygame.Surface((2, 2))
        s.set_at((0, 0), _mix(bg, (255, 255, 255), 0.55))
        s.set_at((1, 0), _mix(bg, (255, 255, 255), 0.35))
        s.set_at((0, 1), _mix(bg, (255, 255, 255), 0.28))
        s.set_at((1, 1), _mix(bg, accent, 0.20))
        g = pygame.transform.smoothscale(s, (max(2, w), max(2, h)))
        _grad_cache.clear() if len(_grad_cache) > 6 else None
        _grad_cache[key] = g
    return g


class PatientDashboardScreen:

    def draw(self, surface: pygame.Surface, snapshot: dict | None = None):
        W, H = surface.get_size()
        snap = snapshot or {}
        sel = snap.get("selected_patient") or {}
        cfg = snap.get("config") or {}

        name = (sel.get("full_name") or cfg.get("patient_name") or "Patient").strip() or "Patient"
        history = sel.get("history") or []
        therapist = (cfg.get("therapist_name") or "").strip()
        game = (cfg.get("selected_game") or "").strip()

        BG, PANEL = PALETTE["bg"], PALETTE["panel"]
        TEXT, MUTED, ACCENT = PALETTE["text"], PALETTE["muted"], PALETTE["accent"]

        # ── main area background (calm wash) ─────────────────────────
        surface.fill(BG)
        rail_w = int(W * 0.235)
        surface.blit(_main_gradient(W - rail_w, H, BG, ACCENT), (rail_w, 0))

        # ── left sidebar ────────────────────────────────────────────
        pygame.draw.rect(surface, _mix(PANEL, ACCENT, 0.10), (0, 0, rail_w, H))
        pygame.draw.rect(surface, _mix(PANEL, (255, 255, 255), 0.5), (0, 0, rail_w, max(3, int(H*0.006))))
        pygame.draw.line(surface, _mix(ACCENT, PANEL, 0.35), (rail_w, 0), (rail_w, H), 2)

        pad = int(rail_w * 0.12)

        # RecovR mark
        logo_sz = int(H * 0.058)
        f_logo = _font("GravitasOne-Regular.ttf", logo_sz)
        s1 = f_logo.render("Recov", True, _mix(TEXT, (0, 0, 0), 0.15))
        s2 = f_logo.render("R", True, (215, 40, 40))
        ly = int(H * 0.045)
        surface.blit(s1, (pad, ly))
        surface.blit(s2, (pad + s1.get_width(), ly))

        # clock + date
        now = datetime.datetime.now()
        f_time = _font("ZenDots-Regular.ttf", int(H * 0.030))
        f_date = _font("Lexend-Light.ttf", int(H * 0.020))
        ty = ly + s1.get_height() + int(H * 0.028)
        surface.blit(f_time.render(now.strftime("%I:%M %p"), True, _mix(TEXT, MUTED, 0.15)),
                     (pad + int(rail_w * 0.02), ty))
        surface.blit(f_date.render(now.strftime("%b %d, %Y"), True, MUTED),
                     (pad + int(rail_w * 0.02), ty + int(H * 0.040)))

        # Welcome card
        card = pygame.Rect(int(rail_w * 0.045), int(H * 0.235),
                           int(rail_w * 0.91), int(H * 0.16))
        pygame.draw.rect(surface, _mix(PANEL, ACCENT, 0.18), card, border_radius=int(H * 0.018))
        pygame.draw.rect(surface, _mix(ACCENT, PANEL, 0.30), card, 1, border_radius=int(H * 0.018))
        f_hi   = _font("FjallaOne-Regular.ttf", int(H * 0.040))
        w_line = f_hi.render("Welcome,", True, _mix(TEXT, MUTED, 0.1))
        max_nw = card.width - int(rail_w * 0.10)
        n_col  = _mix(TEXT, ACCENT, 0.18)
        n_txt  = f"{name}!"
        n_line = None
        for px in (int(H * 0.046), int(H * 0.040), int(H * 0.034), int(H * 0.028)):
            f_name = _font("FjallaOne-Regular.ttf", px)
            n_line = f_name.render(n_txt, True, n_col)
            if n_line.get_width() <= max_nw:
                break
        if n_line.get_width() > max_nw:            # still too long -> ellipsize
            t = name
            while t and f_name.size(t + "…!")[0] > max_nw:
                t = t[:-1]
            n_line = f_name.render((t + "…!") if t else "!", True, n_col)
        gap = int(H * 0.010)
        block_h = w_line.get_height() + gap + n_line.get_height()
        yy = card.y + (card.height - block_h) // 2
        surface.blit(w_line, w_line.get_rect(midtop=(card.centerx, yy)))
        surface.blit(n_line, n_line.get_rect(midtop=(card.centerx, yy + w_line.get_height() + gap)))

        # divider
        dv_y = card.bottom + int(H * 0.030)
        pygame.draw.line(surface, _mix(MUTED, PANEL, 0.55),
                         (int(rail_w * 0.06), dv_y), (rail_w - int(rail_w * 0.06), dv_y), 1)

        # Session History
        f_sh = _font("Lexend-SemiBold.ttf", int(H * 0.026))
        sh_y = dv_y + int(H * 0.020)
        surface.blit(f_sh.render("Session History", True, _mix(TEXT, MUTED, 0.2)),
                     (int(rail_w * 0.07), sh_y))

        list_top = sh_y + f_sh.get_height() + int(H * 0.016)
        row_h    = max(int(H * 0.048), 24)
        f_row    = _font("Lexend-Regular.ttf", int(H * 0.022))
        f_meta   = _font("Lexend-Light.ttf", int(H * 0.018))
        clip = pygame.Rect(0, list_top, rail_w, H - list_top - int(H * 0.02))
        prev_clip = surface.get_clip()
        surface.set_clip(clip)
        if not history:
            surface.blit(f_meta.render("No sessions recorded yet.", True, MUTED),
                         (int(rail_w * 0.07), list_top + int(H * 0.006)))
        else:
            for i, h in enumerate(history):
                ry = list_top + i * row_h
                if ry + row_h > clip.bottom:
                    break
                r = pygame.Rect(int(rail_w * 0.04), ry, rail_w - int(rail_w * 0.08), row_h - int(H * 0.006))
                if i % 2 == 0:
                    pygame.draw.rect(surface, _mix(PANEL, ACCENT, 0.06), r, border_radius=6)
                pygame.draw.rect(surface, _mix(ACCENT, PANEL, 0.7), r, 1, border_radius=6)
                gs = f_row.render(str(h.get("game", "-")), True, _mix(TEXT, MUTED, 0.08))
                surface.blit(gs, gs.get_rect(midleft=(r.x + int(rail_w * 0.04), r.centery)))
                dt = str(h.get("played_at", ""))[:10]
                if dt:
                    ds = f_meta.render(dt, True, MUTED)
                    if gs.get_width() + ds.get_width() + int(rail_w * 0.10) < r.width:
                        surface.blit(ds, ds.get_rect(midright=(r.right - int(rail_w * 0.04), r.centery)))
        surface.set_clip(prev_clip)

        # ── main content: calm "please wait" messaging ──────────────
        mcx = rail_w + (W - rail_w) // 2
        f_msg = _font("Sora-Light.ttf", int(H * 0.048), italic=True)
        lines = ["Your therapy is preparing your session.", "Please wait…"]
        rendered = [f_msg.render(t, True, _mix(TEXT, MUTED, 0.28)) for t in lines]
        lg = int(H * 0.014)
        total = sum(s.get_height() for s in rendered) + lg * (len(rendered) - 1)
        my = int(H * 0.5) - total // 2
        for s in rendered:
            surface.blit(s, s.get_rect(midtop=(mcx, my)))
            my += s.get_height() + lg

        f_sub = _font("Lexend-Light.ttf", int(H * 0.024))
        sub = (f"Upcoming activity:  {game}" if game
               else "Your therapist will begin the session shortly.")
        surface.blit(f_sub.render(sub, True, MUTED),
                     f_sub.render(sub, True, MUTED).get_rect(midtop=(mcx, my + int(H * 0.02))))
        if therapist:
            f_th = _font("Lexend-Light.ttf", int(H * 0.022))
            ts = f_th.render(f"Therapist:  {therapist}", True, _mix(MUTED, ACCENT, 0.3))
            surface.blit(ts, ts.get_rect(midbottom=(mcx, H - int(H * 0.06))))
