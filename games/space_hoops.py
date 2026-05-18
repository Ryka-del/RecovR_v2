"""
Space Hoops — Grip Strength game (1920x1080)
Mechanic:
  - A vertical grip bar on the right shows current grip pressure (0–100%)
  - A moving GREEN ZONE on the bar indicates the required grip range
  - When grip is in the green zone long enough, the ball charges and auto-shoots
  - Hoop position changes after each successful basket
  - Win: reach task goal (10/15/20 baskets)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import start_music, stop_music
from constants import *

GOALS = {"Easy": 10, "Medium": 15, "Hard": 20}
# Green zone width as fraction of bar (how precise grip must be)
ZONE_WIDTH = {"Easy": 0.30, "Medium": 0.20, "Hard": 0.12}
# Green zone moves speed (fraction/sec)
ZONE_SPEED = {"Easy": 0.15, "Medium": 0.25, "Hard": 0.38}
# Charge time needed while in zone (seconds)
CHARGE_TIME = {"Easy": 0.6, "Medium": 0.8, "Hard": 1.0}

BAR_X  = GAME_W - 120
BAR_Y  = 200
BAR_H  = 680
BAR_W  = 60

HOOP_COL   = (220, 90, 25)
HOOP_DARK  = (140, 50, 10)
HOOP_LIGHT = (240, 130, 55)
NET_COL    = (205, 200, 185)

BALL_COL   = (210, 95, 20)    # basketball orange
BALL_DARK  = (160, 60, 10)    # shaded underside
BALL_HILIT = (240, 135, 55)   # highlight
BALL_SEAM  = (20, 10, 5)      # near-black seam lines


def _draw_basketball(surface, cx, cy, r):
    """Draw a basketball with seam lines."""
    pygame.draw.circle(surface, BALL_COL, (cx, cy), r)

    # Horizontal equator seam
    pygame.draw.line(surface, BALL_SEAM, (cx - r + 3, cy), (cx + r - 3, cy), 2)

    # Left curved seam — polyline that bulges left from top to bottom
    pts_l = []
    for i in range(21):
        t  = i / 20.0
        sy = int(cy - r + 2 * r * t)
        sx = int(cx - r * 0.45 * math.sin(t * math.pi))
        pts_l.append((sx, sy))
    pygame.draw.lines(surface, BALL_SEAM, False, pts_l, 2)

    # Right curved seam — mirrors the left
    pts_r = [(2 * cx - x, y) for (x, y) in pts_l]
    pygame.draw.lines(surface, BALL_SEAM, False, pts_r, 2)

    # Outline
    pygame.draw.circle(surface, BALL_SEAM, (cx, cy), r, 2)

    # Small highlight for 3-D feel
    pygame.draw.circle(surface, BALL_HILIT, (cx - r // 3, cy - r // 3), r // 5)


def _draw_basketball_ring(surface, hx, hy, hw):
    """Draw a basketball ring with rim caps, 3-D shading, and a converging net."""
    rim_h  = 12
    net_h  = 55
    n_pts  = 10        # thread count (9 gaps)
    shrink = 0.55      # net bottom width as fraction of rim width

    # Left and right end-caps (give the ring depth)
    cap_w = 10; cap_h = 26
    for cx in (hx - cap_w, hx + hw):
        pygame.draw.rect(surface, HOOP_DARK, (cx, hy - 7, cap_w, cap_h), border_radius=3)

    # Rim body
    pygame.draw.rect(surface, HOOP_COL,   (hx, hy, hw, rim_h), border_radius=4)
    # Top highlight
    pygame.draw.rect(surface, HOOP_LIGHT, (hx + 3, hy + 2, hw - 6, 3), border_radius=2)
    # Bottom shadow
    pygame.draw.rect(surface, HOOP_DARK,  (hx + 3, hy + rim_h - 4, hw - 6, 4), border_radius=2)

    # Net — threads converge from rim width to shrink*width at bottom
    cx_mid = hx + hw / 2.0
    n      = n_pts - 1

    def tx(i, yf):
        xt = hx + (i / n) * hw
        xb = cx_mid + ((i / n) - 0.5) * hw * shrink
        return xt + (xb - xt) * yf

    # Vertical threads
    for i in range(n_pts):
        pygame.draw.line(surface, NET_COL,
                         (int(tx(i, 0)), hy + rim_h),
                         (int(tx(i, 1)), hy + rim_h + net_h), 1)

    # Horizontal rings at 4 heights
    for row in range(1, 5):
        yf  = row / 5.0
        y   = hy + rim_h + int(yf * net_h)
        xs  = [int(tx(i, yf)) for i in range(n_pts)]
        for i in range(n):
            pygame.draw.line(surface, NET_COL, (xs[i], y), (xs[i + 1], y), 1)


class SpaceHoopsGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id   = data.get("account_id")
        self.account      = data.get("account")
        self._patient     = data.get("patient")
        self.exercise     = "grip"
        self.difficulty   = data.get("difficulty", "Easy")
        self.cal          = data.get("calibration", {})
        self.duration_sec = data.get("duration_sec", 60)
        self.zone_w       = ZONE_WIDTH[self.difficulty]
        self.charge_need  = CHARGE_TIME[self.difficulty]

        self.game_over            = False
        self.game_over_score      = 0
        self.game_over_duration   = 0
        self._results_again_rect  = pygame.Rect(0, 0, 1, 1)
        self._results_back_rect   = pygame.Rect(0, 0, 1, 1)
        self.showing_instructions = True
        self.vol_active           = False
        self.pause_vol            = 0.4

        self._init_fatigue()
        start_music()
        self._reset()
        self.paused    = False
        self.pause_sel = 0

    def _reset(self):
        self._init_fatigue()   # clear fatigue/inactivity state on every restart
        self.paused      = False
        self.pause_sel   = 0
        self.game_over   = False
        self.score       = 0
        self.reps        = 0
        self.charge      = 0.0      # seconds in green zone
        self.ball_active = False
        self.ball_x      = float(GAME_W // 2)
        self.ball_y      = float(GAME_H - 200)
        self.ball_vx     = 0.0
        self.ball_vy     = 0.0
        self.hoop_x      = random.randint(300, GAME_W - 400)
        self.hoop_y      = random.randint(150, 400)
        self.hoop_w      = 160
        self.zone_pos         = random.uniform(self.zone_w / 2, 1.0 - self.zone_w / 2)
        self._score_flash     = 0.0   # countdown after scoring
        self._score_flash_pos = None  # (bx, by) where ball scored
        self.start_time  = pygame.time.get_ticks()
        self.elapsed     = 0

    def _normalize_grip(self, raw):
        rest = self.cal.get("grip_rest", 0.0)
        mx   = self.cal.get("grip_max",  1.0)
        if mx <= rest:
            return raw
        return max(0.0, min(1.0, (raw - rest) / (mx - rest)))

    def handle_event(self, event):
        # Instruction screen — any key or click dismisses it
        if self.showing_instructions:
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self.showing_instructions = False
                self.start_time = pygame.time.get_ticks()  # reset timer so countdown starts now
            return

        # Results screen — handle Play Again / Back to Config
        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    self._reset()
                    self.game_over = False
                elif self._results_back_rect.collidepoint(event.pos):
                    self._exit_to_game_config()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_game_config()
            return

        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"):
                self._resume_fatigue()
            return
        if self.paused:
            if self.vol_active:
                if input_handler.was_pressed(event, "left"):
                    self.pause_vol = max(0.0, self.pause_vol - 0.1); self._apply_vol()
                elif input_handler.was_pressed(event, "right"):
                    self.pause_vol = min(1.0, self.pause_vol + 0.1); self._apply_vol()
                elif (input_handler.was_pressed(event, "action") or
                      input_handler.was_pressed(event, "back")):
                    self.vol_active = False
                return
            if input_handler.was_pressed(event, "up"):
                self.pause_sel = max(0, self.pause_sel - 1)
            elif input_handler.was_pressed(event, "down"):
                self.pause_sel = min(3, self.pause_sel + 1)
            elif input_handler.was_pressed(event, "action"):
                if   self.pause_sel == 0: self.paused = False
                elif self.pause_sel == 1: self._reset(); self.paused = False
                elif self.pause_sel == 2: self.vol_active = True
                else:                     self._exit_to_game_config()
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True; self.pause_sel = 0

        # Release SPACE → always shoot; direction depends on whether grip is in zone
        if input_handler.was_released(event, "action") and not self.ball_active:
            grip    = self._normalize_grip(input_handler.get_state()["grip"])
            zone_lo = self.zone_pos - self.zone_w / 2
            zone_hi = self.zone_pos + self.zone_w / 2
            if zone_lo <= grip <= zone_hi:
                self._shoot_aimed()   # lands inside the ring → scores
            else:
                self._shoot_miss()    # flies wide → no score

    def update(self, dt):
        if self.showing_instructions or self.game_over:
            return

        state = input_handler.get_state()
        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused:
            return

        self.elapsed = (pygame.time.get_ticks() - self.start_time) // 1000

        # Score flash countdown — hoop/zone change deferred until flash ends
        if self._score_flash > 0:
            self._score_flash -= dt
            if self._score_flash <= 0:
                self._score_flash     = 0.0
                self._score_flash_pos = None
                self.hoop_x   = random.randint(300, GAME_W - 400)
                self.hoop_y   = random.randint(150, 400)
                self.zone_pos = random.uniform(self.zone_w / 2, 1.0 - self.zone_w / 2)

        if self.ball_active:
            # Ball physics
            self.ball_vy += 980 * dt
            self.ball_x  += self.ball_vx * dt
            self.ball_y  += self.ball_vy * dt

            # Hoop collision
            hcx = self.hoop_x + self.hoop_w // 2
            if (abs(self.ball_x - hcx) < self.hoop_w // 2 and
                    abs(self.ball_y - self.hoop_y) < 30 and self.ball_vy > 0):
                self.score           += 1
                self.reps            += 1
                self.ball_active      = False
                self.charge           = 0.0
                self._score_flash     = 0.55   # show flash for 0.55 s before moving hoop
                self._score_flash_pos = (int(self.ball_x), int(self.ball_y))

            if self.ball_y > GAME_H + 50 or self.ball_x < 0 or self.ball_x > GAME_W:
                self.ball_active = False
                self.charge = 0.0

        if self.elapsed >= self.duration_sec:
            self._end_game()

    def _launch(self, target_x, target_y):
        """Calculate and apply physics velocity to reach (target_x, target_y) in T seconds,
        arriving with downward velocity so the hoop collision check triggers."""
        T = 1.5   # fixed flight time — ball arcs up then falls through the hoop
        self.ball_x  = float(GAME_W // 2)
        self.ball_y  = float(GAME_H - 200)
        dx = target_x - self.ball_x
        dy = target_y - self.ball_y
        self.ball_vx = dx / T
        self.ball_vy = (dy - 0.5 * 980 * T * T) / T
        self.ball_active = True
        self.charge = 0.0

    def _shoot_aimed(self):
        """Release in zone → arc straight into the ring."""
        hcx = self.hoop_x + self.hoop_w // 2
        self._launch(hcx, self.hoop_y)

    def _shoot_miss(self):
        """Release outside zone → ball arcs wide of the ring."""
        hcx = self.hoop_x + self.hoop_w // 2
        # Offset target sideways past the rim edge so it clearly misses
        side   = random.choice([-1, 1])
        offset = self.hoop_w // 2 + random.randint(100, 220)
        self._launch(hcx + side * offset, self.hoop_y)

    def _end_game(self):
        stop_music()
        self.game_over_duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.game_over_score    = self.score
        # Save session to database
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id   = patient_id,
                therapist_id = self.account_id,
                game         = "Basketball",
                score        = self.score,
                duration_sec = self.game_over_duration,
                difficulty   = self.difficulty,
            )
        except Exception:
            pass
        self.game_over = True

    def draw(self, surface):
        font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        font_sm  = pygame.font.SysFont("monospace", 26)

        # Stars
        for sx, sy in [(100,60),(300,40),(600,80),(900,30),(1200,70),(1500,50),(1700,90),(200,300)]:
            pygame.draw.circle(surface, WHITE, (sx, sy), 2)

        # Basketball ring
        _draw_basketball_ring(surface, self.hoop_x, self.hoop_y, self.hoop_w)

        # Ball — stays at scored position during flash, otherwise uses physics
        if self._score_flash > 0 and self._score_flash_pos:
            bx, by = self._score_flash_pos
        elif self.ball_active:
            bx, by = int(self.ball_x), int(self.ball_y)
        else:
            bx, by = GAME_W // 2, GAME_H - 200
        _draw_basketball(surface, bx, by, 28)

        # Score flash effect
        if self._score_flash > 0:
            f_font = pygame.font.SysFont("monospace", 52, bold=True)
            f_alpha = int(220 * min(1.0, self._score_flash / 0.3))
            hcx = self.hoop_x + self.hoop_w // 2
            pygame.draw.circle(surface, GREEN, (hcx, self.hoop_y), self.hoop_w // 2 + 12, 4)
            f_s = f_font.render("SCORE!", True, YELLOW)
            f_s.set_alpha(f_alpha)
            surface.blit(f_s, f_s.get_rect(center=(hcx, self.hoop_y - 55)))

        # Grip bar background
        pygame.draw.rect(surface, PANEL, (BAR_X, BAR_Y, BAR_W, BAR_H), border_radius=8)

        # Current grip level — drawn first so the green zone appears on top
        state    = input_handler.get_state()
        grip     = self._normalize_grip(state["grip"])
        gy       = BAR_Y + int((1 - grip) * BAR_H)
        zone_lo  = self.zone_pos - self.zone_w / 2
        zone_hi  = self.zone_pos + self.zone_w / 2
        in_zone  = zone_lo <= grip <= zone_hi
        grip_col = GREEN if in_zone else ACCENT
        pygame.draw.rect(surface, grip_col,
                         (BAR_X, gy, BAR_W, BAR_Y + BAR_H - gy), border_radius=4)

        # Green zone drawn on top of the grip fill so it is always visible
        zy = BAR_Y + int((1 - zone_hi) * BAR_H)
        zh = max(4, int(self.zone_w * BAR_H))
        pygame.draw.rect(surface, GREEN, (BAR_X, zy, BAR_W, zh), border_radius=4)

        # Bar outline
        pygame.draw.rect(surface, WHITE, (BAR_X, BAR_Y, BAR_W, BAR_H), 2, border_radius=8)

        # "IN ZONE" label above bar when grip is matched
        if in_zone:
            iz_font = pygame.font.SysFont("monospace", 22, bold=True)
            iz_s = iz_font.render("IN ZONE!", True, GREEN)
            surface.blit(iz_s, iz_s.get_rect(center=(BAR_X + BAR_W // 2, BAR_Y - 24)))

        # Bottom hint — changes when grip is in the zone
        if not self.ball_active:
            in_zone_now = (self.zone_pos - self.zone_w / 2) <= grip <= (self.zone_pos + self.zone_w / 2)
            if in_zone_now and grip > 0.05:
                hint_txt = "RELEASE SPACE to shoot!"
                hint_col = GREEN
            else:
                hint_txt = "Hold SPACE to charge the bar, release when in GREEN ZONE"
                hint_col = GRAY
            hs = font_sm.render(hint_txt, True, hint_col)
            surface.blit(hs, hs.get_rect(center=(GAME_W // 2, GAME_H - 45)))

        # HUD
        remaining = max(0, self.duration_sec - self.elapsed)
        surface.blit(font_hud.render(f"Score: {self.score}", True, ACCENT), (40, 30))
        surface.blit(font_hud.render(f"Time: {remaining}s", True,
                     (220, 80, 50) if remaining <= 10 else TEXT), (GAME_W - 300, 30))

        # Pause overlay
        if self.paused:
            self._draw_pause(surface)

        self._draw_fatigue_overlay(surface)

        if self.showing_instructions:
            self._draw_instructions(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_instructions(self, surface):
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        mw, mh = 980, 540
        mx, my = (GAME_W - mw) // 2, (GAME_H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        bg.fill((20, 26, 44, 250))
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, GREEN, mr, 2, border_radius=18)

        f_title = pygame.font.SysFont("monospace", 46, bold=True)
        f_head  = pygame.font.SysFont("monospace", 28, bold=True)
        f_body  = pygame.font.SysFont("monospace", 24)
        f_hint  = pygame.font.SysFont("monospace", 22)

        title_s = f_title.render("HOW TO PLAY", True, YELLOW)
        surface.blit(title_s, title_s.get_rect(center=(mr.centerx, my + 52)))
        pygame.draw.line(surface, GREEN,
                         (mx + 40, my + 90), (mx + mw - 40, my + 90), 1)

        steps = [
            ("1.", "Hold SPACE to charge the grip bar on the right."),
            ("2.", "Watch the GREEN ZONE on the bar."),
            ("3.", "Release SPACE when the bar reaches the GREEN ZONE."),
            ("4.", "Released inside zone  →  ball flies into the ring  (SCORE!)"),
            ("5.", "Released outside zone  →  ball flies wide  (MISS)"),
            ("6.", "Score as many baskets as you can before time runs out!"),
        ]

        step_y = my + 112
        for icon, text in steps:
            icon_s = f_head.render(icon, True, GREEN)
            text_s = f_body.render(text, True, WHITE)
            surface.blit(icon_s, (mx + 48, step_y))
            surface.blit(text_s, (mx + 100, step_y + 2))
            step_y += 52

        pygame.draw.line(surface, GRAY,
                         (mx + 40, step_y + 8), (mx + mw - 40, step_y + 8), 1)

        blink = (pygame.time.get_ticks() // 500) % 2 == 0
        if blink:
            hint_s = f_hint.render("Press any key or click to begin", True, ACCENT)
            surface.blit(hint_s, hint_s.get_rect(center=(mr.centerx, step_y + 36)))

    def _exit_to_game_config(self):
        import builtins
        builtins.pending_panel   = 4            # open Game Configuration
        builtins.pending_patient = self._patient  # restore the selected patient
        self.manager.go_to("therapist_dashboard")

    def _draw_results(self, surface):
        W, H = GAME_W, GAME_H
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        mw, mh = 640, 400
        mx, my = (W - mw) // 2, (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        bg.fill((28, 34, 52, 245))
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, ACCENT, mr, 2, border_radius=16)

        f_big  = pygame.font.SysFont("monospace", 48, bold=True)
        f_mid  = pygame.font.SysFont("monospace", 32, bold=True)
        f_sm   = pygame.font.SysFont("monospace", 24)
        f_btn  = pygame.font.SysFont("monospace", 28, bold=True)

        title = f_big.render("Session Complete!", True, YELLOW)
        surface.blit(title, title.get_rect(center=(mr.centerx, my + 60)))

        sc_s = f_mid.render(f"Score:    {self.game_over_score}", True, WHITE)
        surface.blit(sc_s, sc_s.get_rect(midleft=(mx + 80, my + 140)))

        mins, secs = divmod(self.game_over_duration, 60)
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, WHITE)
        surface.blit(du_s, du_s.get_rect(midleft=(mx + 80, my + 185)))

        dif_s = f_sm.render(f"Difficulty: {self.difficulty}", True, GRAY)
        surface.blit(dif_s, dif_s.get_rect(midleft=(mx + 80, my + 230)))

        mp = pygame.mouse.get_pos()
        bw, bh = 220, 52

        again_r = pygame.Rect(mx + 60, my + mh - 80, bw, bh)
        back_r  = pygame.Rect(mx + mw - 60 - bw, my + mh - 80, bw, bh)
        self._results_again_rect = again_r
        self._results_back_rect  = back_r

        ag_col = (55, 170, 100) if again_r.collidepoint(mp) else (40, 140, 80)
        bk_col = (75, 110, 190) if back_r.collidepoint(mp) else (55, 85, 160)

        pygame.draw.rect(surface, ag_col, again_r, border_radius=10)
        pygame.draw.rect(surface, bk_col, back_r,  border_radius=10)

        ag_s = f_btn.render("Play Again", True, WHITE)
        bk_s = f_btn.render("Exit", True, WHITE)
        surface.blit(ag_s, ag_s.get_rect(center=again_r.center))
        surface.blit(bk_s, bk_s.get_rect(center=back_r.center))

    def _draw_pause(self, surface):
        from constants import get_theme
        T       = get_theme()
        font    = pygame.font.SysFont("monospace", 48, bold=True)
        font_sm = pygame.font.SysFont("monospace", 28)
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        surface.blit(ov, (0, 0))
        panel = pygame.Rect(GAME_W // 2 - 260, GAME_H // 2 - 220, 520, 460)
        pygame.draw.rect(surface, T["PANEL"],  panel, border_radius=16)
        pygame.draw.rect(surface, T["ACCENT"], panel, 2, border_radius=16)
        for i, opt in enumerate(["RESUME", "RESTART", "VOLUME", "EXIT"]):
            col = T["ACCENT"] if i == self.pause_sel else T["GRAY"]
            lbl = font.render(opt, True, col)
            surface.blit(lbl, (GAME_W // 2 - lbl.get_width() // 2,
                               GAME_H // 2 - 170 + i * 96))
            if opt == "VOLUME" and (i == self.pause_sel or self.vol_active):
                bw, bh = 360, 12
                bx = GAME_W // 2 - bw // 2
                by = GAME_H // 2 - 170 + i * 96 + 52
                pygame.draw.rect(surface, T["PANEL"], (bx, by, bw, bh), border_radius=6)
                pygame.draw.rect(surface, T["GREEN"],
                                 (bx, by, int(bw * self.pause_vol), bh), border_radius=6)
                pct = font_sm.render(f"{int(self.pause_vol * 100)}%", True, T["GREEN"])
                surface.blit(pct, (bx + bw + 10, by - 4))
                if self.vol_active:
                    hint = font_sm.render("← → adjust   ENTER done", True, T["GRAY"])
                    surface.blit(hint, (GAME_W // 2 - hint.get_width() // 2, by + 20))
