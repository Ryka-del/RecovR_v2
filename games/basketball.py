"""
Basketball — Grip Strength game (1920x1080)
"""

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import get_theme, GAME_W, GAME_H

GOALS      = {"Easy": 10, "Medium": 15, "Hard": 20}
ZONE_WIDTH = {"Easy": 0.25, "Medium": 0.16, "Hard": 0.09}
ZONE_SPEED = {"Easy": 0.0,  "Medium": 0.18, "Hard": 0.28}
TIME_START = {"Easy": 40,   "Medium": 35,   "Hard": 30}
TIME_BONUS = {"Easy": 6,    "Medium": 5,    "Hard": 4}

RAMP_UP = 0.6   # grip rises at 0.6 units/sec while squeezing

BAR_W, BAR_H = 60, 500
BAR_X = GAME_W - 140
BAR_Y = (GAME_H - BAR_H) // 2

HOOP_W  = 140
HOOP_RX = HOOP_W // 2   # 70 — x-radius of rim ellipse
HOOP_RY = 10             # y-radius (perspective flattening)

BALL_R  = 30
GRAVITY = 900.0

_RIM_COL   = (220,  85,  20)
_RIM_DARK  = (140,  50,  10)
_BOARD_COL = (245, 245, 252)
_BOARD_EDG = ( 70,  75,  95)
_NET_COL   = (210, 205, 190)
_BRKT_COL  = (110, 115, 130)
_BALL_COL  = (210,  95,  20)
_BALL_SEAM = ( 20,  10,   5)
_BALL_HI   = (240, 135,  55)


def _draw_basketball(surface, cx, cy, r):
    pygame.draw.circle(surface, _BALL_COL, (cx, cy), r)
    pygame.draw.line(surface, _BALL_SEAM, (cx - r + 4, cy), (cx + r - 4, cy), 2)
    pts = []
    for i in range(21):
        t  = i / 20
        sy = int(cy - r + 2 * r * t)
        sx = int(cx - r * 0.44 * math.sin(t * math.pi))
        pts.append((sx, sy))
    if len(pts) > 1:
        pygame.draw.lines(surface, _BALL_SEAM, False, pts, 2)
    pts_r = [(2 * cx - x, y) for x, y in pts]
    if len(pts_r) > 1:
        pygame.draw.lines(surface, _BALL_SEAM, False, pts_r, 2)
    pygame.draw.circle(surface, _BALL_SEAM, (cx, cy), r, 2)
    pygame.draw.circle(surface, _BALL_HI, (cx - r // 3, cy - r // 3), max(1, r // 5))


def _draw_hoop_back(surface, hx, hy):
    """Backboard, bracket, net, and the BACK (far) arc of the rim."""
    hcx = hx + HOOP_RX
    hcy = hy

    # Backboard — centered ABOVE the rim
    bw, bh = 150, 75
    bx = hcx - bw // 2
    by = hcy - bh - HOOP_RY - 8   # 8 px gap above top of rim arc
    pygame.draw.rect(surface, _BOARD_COL, (bx, by, bw, bh), border_radius=4)
    pygame.draw.rect(surface, _BOARD_EDG, (bx, by, bw, bh), 3, border_radius=4)
    sq_m = 14
    sq_by = by + bh // 2
    sq_bh = bh // 2 - sq_m
    pygame.draw.rect(surface, _BOARD_EDG, (bx + sq_m, sq_by, bw - sq_m * 2, sq_bh), 2)

    # Vertical bracket connecting backboard bottom to rim top
    brkt_top = by + bh
    brkt_bot = hcy - HOOP_RY
    pygame.draw.rect(surface, _BRKT_COL,
                     (hcx - 5, brkt_top, 10, max(2, brkt_bot - brkt_top + 2)),
                     border_radius=2)

    # Net
    net_h   = 55
    base_rx = HOOP_RX // 2
    top_y   = hcy + HOOP_RY
    bot_y   = hcy + net_h
    for i in range(9):
        t     = i / 8
        top_x = int(hcx - HOOP_RX + t * HOOP_RX * 2)
        bot_x = int(hcx - base_rx  + t * base_rx  * 2)
        pygame.draw.line(surface, _NET_COL, (top_x, top_y), (bot_x, bot_y), 1)
    for j in range(1, 5):
        p     = j / 4
        y_l   = int(top_y + p * (bot_y - top_y))
        left  = int(hcx - HOOP_RX + p * (HOOP_RX - base_rx))
        right = int(hcx + HOOP_RX - p * (HOOP_RX - base_rx))
        pygame.draw.line(surface, _NET_COL, (left, y_l), (right, y_l), 1)

    # Back (top) arc of rim — darker, the far side
    rim_rect = pygame.Rect(hcx - HOOP_RX, hcy - HOOP_RY, HOOP_RX * 2, HOOP_RY * 2)
    pygame.draw.arc(surface, _RIM_DARK, rim_rect, 0, math.pi, 6)


def _draw_hoop_front(surface, hx, hy):
    """Front (near) arc of rim — drawn over the ball for depth."""
    hcx = hx + HOOP_RX
    hcy = hy
    rim_rect = pygame.Rect(hcx - HOOP_RX, hcy - HOOP_RY, HOOP_RX * 2, HOOP_RY * 2)
    pygame.draw.arc(surface, _RIM_COL, rim_rect, math.pi, 2 * math.pi, 6)


class BasketballGame(FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "grip"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.goal       = GOALS[self.difficulty]
        self.zone_w     = ZONE_WIDTH[self.difficulty]
        self.zone_speed = ZONE_SPEED[self.difficulty]
        self.time_bonus = TIME_BONUS[self.difficulty]

        dur = data.get("duration_sec")
        self.time_start = int(dur) if dur else TIME_START[self.difficulty]

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4
        self._pause_btn_rect = pygame.Rect(GAME_W - 90, 13, 70, 46)

        self._font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 26)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)

        self._init_fatigue()
        self._reset()
        start_music()
        self._show_instructions = True

    def _reset(self):
        self.game_over           = False
        self._pending_score      = False
        self._grip_ignore_timer  = 0.0
        self.score          = 0
        self.reps           = 0
        self.time_left      = float(self.time_start)
        self.start_time     = pygame.time.get_ticks()

        self.zone_pos = random.uniform(0.15, 0.50)
        self.zone_dir = 1

        self._grip      = 0.0
        self._squeezing = False
        self._cooldown  = 0.0

        self.ball_x      = float(GAME_W // 2)
        self.ball_y      = float(GAME_H - 160)
        self.ball_vx     = 0.0
        self.ball_vy     = 0.0
        self.ball_active = False

        self.hoop_x     = random.randint(300, GAME_W - 500)
        self.hoop_y     = random.randint(200, 400)
        self._next_hoop = None

        self.feedback    = None
        self.score_flash = 0.0
        self._state      = {"grip": 0.0}

    def _normalize(self, raw):
        rest = self.cal.get("grip_rest", 0.0)
        mx   = self.cal.get("grip_max",  1.0)
        if mx <= rest:
            return raw
        return max(0.0, min(1.0, (raw - rest) / (mx - rest)))

    # ------------------------------------------------------------------ #

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions    = False
                self.start_time            = pygame.time.get_ticks()
                self._grip                 = 0.0
                self._squeezing            = False
                self._grip_ignore_timer    = 0.8   # ignore grip for 0.8s so dismiss-squeeze doesn't charge bar
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    self._reset()
                    self._show_instructions = False
                elif self._results_exit_rect.collidepoint(event.pos):
                    self._exit_to_game_config()
            return

        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"):
                self._resume_fatigue()
            return
        if self.paused:
            self._pause_handle(event)
            return
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._pause_btn_rect.collidepoint(event.pos)):
            self.paused = True
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True

    def _pause_handle(self, event):
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
            if self.pause_sel == 0:
                self.paused = False
            elif self.pause_sel == 1:
                self._reset()
                self._show_instructions = False
                self.paused = False
            elif self.pause_sel == 2:
                self.vol_active = True
            else:
                self._exit_to_game_config()

    # ------------------------------------------------------------------ #

    def update(self, dt):
        if self._show_instructions or self.game_over:
            return

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0:
            self._end_game(); return

        raw = self._normalize(self._state["grip"])

        # Grace period after instructions dismissed — ignore grip so the dismiss-squeeze doesn't charge bar
        if self._grip_ignore_timer > 0:
            self._grip_ignore_timer -= dt
            raw = 0.0
            self._grip      = 0.0
            self._squeezing = False

        # Evaluate zone from CURRENT grip before updating it
        needle_now = 1.0 - self._grip
        half       = self.zone_w / 2
        in_zone    = (self.zone_pos - half) <= needle_now <= (self.zone_pos + half)

        was_squeezing   = self._squeezing
        self._squeezing = raw > 0.1

        # Release detection
        if not self.ball_active and self._cooldown <= 0:
            if was_squeezing and not self._squeezing:
                if in_zone:
                    self._shoot()
                else:
                    self.feedback = ("MISSED — release in the GREEN zone!", (255, 60, 80), 1.5)
                    play_error()
                self._cooldown = 0.6
                self._grip = 0.0   # reset needle immediately after shot or miss

        if self._cooldown > 0:
            self._cooldown -= dt

        # Zone movement — moves only while relaxed
        if self.zone_speed > 0 and raw <= 0.1:
            self.zone_pos += self.zone_dir * self.zone_speed * dt
            if self.zone_pos > 0.55: self.zone_dir = -1
            if self.zone_pos < 0.10: self.zone_dir =  1

        # Needle: rises while squeezing, drops to 0 instantly on release
        if raw > 0.1:
            self._grip = min(1.0, self._grip + RAMP_UP * dt)
        else:
            self._grip = 0.0

        # Ball physics
        if self.ball_active:
            self.ball_vy += GRAVITY * dt
            self.ball_x  += self.ball_vx * dt
            self.ball_y  += self.ball_vy * dt

            hcx = self.hoop_x + HOOP_RX
            hcy = self.hoop_y
            if (abs(self.ball_x - hcx) < HOOP_RX and
                    abs(self.ball_y - hcy) < BALL_R + HOOP_RY):
                if self._pending_score:
                    self.score       += 1
                    self.reps        += 1
                    self.score_flash  = 0.6
                    self.feedback     = ("PERFECT!", (0, 255, 160), 1.5)
                    play_success()
                    self._pending_score = False
                self.ball_active = False
                self._advance_hoop()
            elif (self.ball_y > GAME_H + 80 or
                  self.ball_x < -80 or self.ball_x > GAME_W + 80):
                self._pending_score = False
                self.ball_active    = False
                self._advance_hoop()

        if self.score >= self.goal:
            self._end_game()

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None
        if self.score_flash > 0:
            self.score_flash -= dt

    def _advance_hoop(self):
        if self._next_hoop:
            self.hoop_x, self.hoop_y = self._next_hoop
            self._next_hoop = None

    def _shoot(self):
        self._pending_score = True
        bx0 = float(GAME_W // 2)
        by0 = float(GAME_H - 160)
        hcx = float(self.hoop_x + HOOP_RX)
        hcy = float(self.hoop_y)

        dist = math.hypot(hcx - bx0, hcy - by0)
        t    = max(0.5, min(1.0, dist / 1200.0))

        self.ball_x      = bx0
        self.ball_y      = by0
        self.ball_vx     = (hcx - bx0) / t
        self.ball_vy     = (hcy - by0 - 0.5 * GRAVITY * t * t) / t
        self.ball_active = True

        self._next_hoop = (random.randint(300, GAME_W - 500),
                           random.randint(200, 400))
        self.zone_pos   = random.uniform(0.15, 0.50)

    # ------------------------------------------------------------------ #

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 860, 560
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill((18, 26, 46, 252))
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, T["ACCENT"], pygame.Rect(px, py, pw, ph), 2, border_radius=16)

        f_title = pygame.font.SysFont("monospace", 36, bold=True)
        f_head  = pygame.font.SysFont("monospace", 22, bold=True)
        f_body  = pygame.font.SysFont("monospace", 19)
        f_hint  = pygame.font.SysFont("monospace", 21, bold=True)

        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        title = f_title.render("BASKETBALL  --  How to Play", True, diff_col)
        surface.blit(title, title.get_rect(centerx=GAME_W // 2, top=py + 26))
        pygame.draw.line(surface, T["ACCENT"], (px + 40, py + 78), (px + pw - 40, py + 78), 1)

        y = py + 96
        for header, lines in [
            ("OBJECTIVE", [
                "Squeeze your hand to raise the needle on the grip bar.",
                "When the needle enters the GREEN zone, RELEASE to shoot!",
                "The ball must pass through the hoop to score a basket.",
            ]),
            ("CONTROLS", [
                "Squeeze hand  -- raises the needle (grip bar).",
                "Release hand  -- shoots when needle is in the GREEN zone.",
            ]),
            ("THIS SESSION", [
                f"Goal:          Score {self.goal} baskets",
                f"Starting time: {self.time_start} seconds",
                f"Difficulty:    {self.difficulty}",
            ]),
        ]:
            surface.blit(f_head.render(header, True, T["ACCENT"]), (px + 48, y))
            y += 30
            for line in lines:
                surface.blit(f_body.render(line, True, T["TEXT"]), (px + 64, y))
                y += 26
            y += 14

        blink_col = T["YELLOW"] if (pygame.time.get_ticks() // 600) % 2 == 0 else T["GRAY"]
        hint = f_hint.render("Press any key or click to begin", True, blink_col)
        surface.blit(hint, hint.get_rect(centerx=GAME_W // 2, bottom=py + ph - 20))

    def _exit_to_game_config(self):
        import builtins
        stop_music()
        builtins.pending_panel   = 4
        builtins.pending_patient = self._patient
        builtins.pending_account = self.account
        self.manager.go_to("therapist_dashboard")

    def _end_game(self):
        if self.game_over:
            return
        stop_music()
        self.game_over_duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.game_over_score    = self.score
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

    def _draw_results(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        mw, mh = 640, 400
        mx, my = (GAME_W - mw) // 2, (GAME_H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        bg.fill((28, 34, 52, 245))
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, T["ACCENT"], mr, 2, border_radius=16)

        f_big = pygame.font.SysFont("monospace", 48, bold=True)
        f_mid = pygame.font.SysFont("monospace", 32, bold=True)
        f_sm  = pygame.font.SysFont("monospace", 24)
        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        title = f_big.render("Session Complete!", True, T["YELLOW"])
        surface.blit(title, title.get_rect(center=(mr.centerx, my + 60)))

        sc_s = f_mid.render(f"Score:    {self.game_over_score} / {self.goal}", True, T["WHITE"])
        surface.blit(sc_s, sc_s.get_rect(midleft=(mx + 80, my + 140)))

        mins, secs = divmod(self.game_over_duration, 60)
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, T["WHITE"])
        surface.blit(du_s, du_s.get_rect(midleft=(mx + 80, my + 190)))

        dif_s = f_sm.render(f"Difficulty: {self.difficulty}", True, T["GRAY"])
        surface.blit(dif_s, dif_s.get_rect(midleft=(mx + 80, my + 238)))

        mp  = pygame.mouse.get_pos()
        bw, bh = 220, 52

        again_r = pygame.Rect(mx + 60,           my + mh - 80, bw, bh)
        exit_r  = pygame.Rect(mx + mw - 60 - bw, my + mh - 80, bw, bh)
        self._results_again_rect = again_r
        self._results_exit_rect  = exit_r

        ag_col = (55, 170, 100) if again_r.collidepoint(mp) else (40, 140, 80)
        ex_col = (75, 110, 190) if exit_r.collidepoint(mp)  else (55,  85, 160)

        pygame.draw.rect(surface, ag_col, again_r, border_radius=10)
        pygame.draw.rect(surface, ex_col, exit_r,  border_radius=10)

        ag_lbl = f_btn.render("Play Again", True, T["WHITE"])
        ex_lbl = f_btn.render("Exit",       True, T["WHITE"])
        surface.blit(ag_lbl, ag_lbl.get_rect(center=again_r.center))
        surface.blit(ex_lbl, ex_lbl.get_rect(center=exit_r.center))

    # ------------------------------------------------------------------ #

    def draw(self, surface):
        T = get_theme()
        surface.fill(T["BG"])

        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        font_hud = self._font_hud
        font_sm  = self._font_sm

        # Z-ordered drawing: back of hoop → ball → front of hoop
        _draw_hoop_back(surface, self.hoop_x, self.hoop_y)

        bx = int(self.ball_x) if self.ball_active else GAME_W // 2
        by = int(self.ball_y) if self.ball_active else GAME_H - 160
        _draw_basketball(surface, bx, by, BALL_R)

        _draw_hoop_front(surface, self.hoop_x, self.hoop_y)

        # Grip bar
        needle  = 1.0 - self._grip
        half    = self.zone_w / 2
        in_zone = (self.zone_pos - half) <= needle <= (self.zone_pos + half)

        pygame.draw.rect(surface, T["RED"], (BAR_X, BAR_Y, BAR_W, BAR_H), border_radius=8)
        gz_y = BAR_Y + int((self.zone_pos - half) * BAR_H)
        gz_h = max(6, int(self.zone_w * BAR_H))
        pygame.draw.rect(surface, T["GREEN"], (BAR_X, gz_y, BAR_W, gz_h), border_radius=4)
        needle_y   = BAR_Y + int(needle * BAR_H)
        needle_col = T["GREEN"] if in_zone else T["WHITE"]
        pygame.draw.rect(surface, needle_col,
                         (BAR_X - 16, needle_y - 6, BAR_W + 32, 12), border_radius=6)
        pygame.draw.rect(surface, T["WHITE"], (BAR_X, BAR_Y, BAR_W, BAR_H), 2, border_radius=8)
        surface.blit(font_sm.render("GRIP", True, T["GRAY"]),
                     (BAR_X - 8, BAR_Y - 34))
        surface.blit(font_sm.render(f"{int(self._grip * 100)}%", True, T["ACCENT"]),
                     (BAR_X - 8, BAR_Y + BAR_H + 8))

        # Score flash
        if self.score_flash > 0:
            alpha = int(80 * min(1.0, self.score_flash / 0.3))
            fl = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
            fl.fill((0, 255, 160, alpha))
            surface.blit(fl, (0, 0))

        # HUD
        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)
        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        surface.blit(font_hud.render(
            f"BASKETBALL  ·  {self.difficulty.upper()}", True, diff_col), (80, 18))
        surface.blit(font_hud.render(
            f"{self.score:02d} / {self.goal:02d}", True, T["ACCENT"]),
            (GAME_W // 2 - 60, 18))
        time_col = T["RED"] if self.time_left < 10 else T["TEXT"]
        surface.blit(font_hud.render(
            f"{max(0, int(self.time_left)):02d}s", True, time_col),
            (GAME_W - 160, 18))

        # Pause button — two solid bars
        pb     = self._pause_btn_rect
        pb_col = T["ACCENT"]
        pygame.draw.rect(surface, (15, 20, 36), pb, border_radius=8)
        pygame.draw.rect(surface, pb_col, pb, 2, border_radius=8)
        bw2, bh2 = 8, 22
        by2  = pb.top + (pb.height - bh2) // 2
        bx1  = pb.left + pb.width // 2 - bw2 - 4
        bx2  = pb.left + pb.width // 2 + 4
        pygame.draw.rect(surface, pb_col, (bx1, by2, bw2, bh2), border_radius=2)
        pygame.draw.rect(surface, pb_col, (bx2, by2, bw2, bh2), border_radius=2)

        # Feedback
        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, GAME_H // 2 - 60))

        # Hint
        if self.difficulty == "Easy":
            hint = "Squeeze into the GREEN zone, then RELEASE to shoot"
        else:
            hint = "Zone moves while relaxed -- squeeze to freeze, release in GREEN to shoot"
        surface.blit(font_sm.render(hint, True, T["GRAY"]), (80, GAME_H - 44))

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)
