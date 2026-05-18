"""
Basketball — Grip Strength game (1920x1080)

Mechanic:
  - Needle rises SLOWLY as you squeeze (ramp), falls slowly when released
  - Green zone is in the upper portion of the bar
  - When needle is inside green zone, needle turns GREEN
  - RELEASE (raw drops) while needle is in green zone → SCORE + ball arcs to hoop
  - Release while needle is in red → MISS
  - Easy: zone static. Medium/Hard: zone moves while relaxed, freezes while squeezing.
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

# Ramp speeds — how fast needle rises/falls (units per second, 0.0–1.0 scale)
RAMP_UP   = 0.6   # ~1.7s to reach full grip
RAMP_DOWN = 0.9   # ~1.1s to fully release

BAR_W, BAR_H = 60, 500
BAR_X = GAME_W - 140
BAR_Y = (GAME_H - BAR_H) // 2

HOOP_W   = 140
HOOP_H   = 14
BALL_R   = 30
GRAVITY  = 900.0


class BasketballGame(FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self.exercise   = "grip"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.goal       = GOALS[self.difficulty]
        self.zone_w     = ZONE_WIDTH[self.difficulty]
        self.zone_speed = ZONE_SPEED[self.difficulty]
        self.time_start = TIME_START[self.difficulty]
        self.time_bonus = TIME_BONUS[self.difficulty]

        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4

        self._font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 26)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)

        self._init_fatigue()
        self._reset()
        start_music()

    # ------------------------------------------------------------------ #

    def _reset(self):
        self.score       = 0
        self.reps        = 0
        self.time_left   = float(self.time_start)
        self.start_time  = pygame.time.get_ticks()

        # Green zone lives in upper half (needle goes up when squeezing)
        self.zone_pos    = random.uniform(0.15, 0.50)
        self.zone_dir    = 1

        self._grip       = 0.0   # smoothed grip 0.0–1.0
        self._squeezing  = False  # True while raw input is held
        self._cooldown   = 0.0

        self.ball_x      = float(GAME_W // 2)
        self.ball_y      = float(GAME_H - 160)
        self.ball_vx     = 0.0
        self.ball_vy     = 0.0
        self.ball_active = False

        self.hoop_x      = random.randint(300, GAME_W - 500)
        self.hoop_y      = random.randint(100, 400)
        self._next_hoop  = None   # queued after ball lands

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
        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"):
                self._resume_fatigue()
            return
        if self.paused:
            self._pause_handle(event)
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
            if self.pause_sel == 0:   self.paused = False
            elif self.pause_sel == 1: self._reset(); self.paused = False
            elif self.pause_sel == 2: self.vol_active = True
            else:                     self._exit_to_menu()

    # ------------------------------------------------------------------ #

    def update(self, dt):
        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0:
            self._end_game(); return

        raw = self._normalize(self._state["grip"])

        # ── Ramp grip smoothly ──
        if raw > 0.1:
            self._grip = min(1.0, self._grip + RAMP_UP * dt)
        else:
            self._grip = max(0.0, self._grip - RAMP_DOWN * dt)

        # needle: 0.0 = top of bar (full grip), 1.0 = bottom (no grip)
        needle = 1.0 - self._grip

        half    = self.zone_w / 2
        in_zone = (self.zone_pos - half) <= needle <= (self.zone_pos + half)

        # ── Zone movement (Medium/Hard): moves only while relaxed ──
        if self.zone_speed > 0 and raw <= 0.1:
            self.zone_pos += self.zone_dir * self.zone_speed * dt
            if self.zone_pos > 0.55: self.zone_dir = -1
            if self.zone_pos < 0.10: self.zone_dir =  1

        # ── Release detection ──
        was_squeezing = self._squeezing
        self._squeezing = raw > 0.1

        if not self.ball_active and self._cooldown <= 0:
            # Detect the moment of release
            if was_squeezing and not self._squeezing:
                if in_zone:
                    self._shoot()
                else:
                    self.feedback = ("MISSED — release in the GREEN zone!", (255, 60, 80), 1.5)
                    play_error()
                self._cooldown = 0.6

        if self._cooldown > 0:
            self._cooldown -= dt

        # ── Ball physics ──
        if self.ball_active:
            self.ball_vy += GRAVITY * dt
            self.ball_x  += self.ball_vx * dt
            self.ball_y  += self.ball_vy * dt

            # Check if ball passed through hoop
            hcx = self.hoop_x + HOOP_W // 2
            hcy = self.hoop_y + HOOP_H // 2
            if (abs(self.ball_x - hcx) < HOOP_W // 2 and
                    abs(self.ball_y - hcy) < 40 and self.ball_vy > 0):
                self.ball_active = False
                self._advance_hoop()
            elif self.ball_y > GAME_H + 80 or self.ball_x < -80 or self.ball_x > GAME_W + 80:
                self.ball_active = False
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
        self.score      += 1
        self.reps       += 1
        self.time_left  += self.time_bonus
        self.score_flash = 0.6
        self._cooldown   = 0.6
        self.feedback    = (f"+{self.time_bonus}s  PERFECT!", (0, 255, 160), 1.5)
        play_success()

        # Launch from ball rest position toward hoop center
        # Use a fixed arc height to guarantee a nice parabola
        bx0 = float(GAME_W // 2)
        by0 = float(GAME_H - 160)
        hcx = float(self.hoop_x + HOOP_W // 2)
        hcy = float(self.hoop_y + HOOP_H // 2)

        # Pick flight time based on horizontal distance so arc looks natural
        dist = math.hypot(hcx - bx0, hcy - by0)
        t    = max(0.5, min(1.0, dist / 1200.0))

        self.ball_x      = bx0
        self.ball_y      = by0
        self.ball_vx     = (hcx - bx0) / t
        self.ball_vy     = (hcy - by0 - 0.5 * GRAVITY * t * t) / t
        self.ball_active = True

        # Queue next hoop — only appears after ball lands
        self._next_hoop  = (random.randint(300, GAME_W - 500),
                            random.randint(100, 400))
        self.zone_pos    = random.uniform(0.15, 0.50)

    # ------------------------------------------------------------------ #

    def _exit_to_menu(self):
        stop_music()
        self.manager.go_to("exercise_menu",
                           account_id=self.account_id, account=self.account)

    def _end_game(self):
        stop_music()
        duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="basketball",
            difficulty=self.difficulty, score=self.score,
            reps=self.reps, duration_sec=duration,
            max_score=self.goal, back_screen="game_select")

    # ------------------------------------------------------------------ #

    def draw(self, surface):
        T = get_theme()
        surface.fill(T["BG"])

        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)

        font_hud = self._font_hud
        font_sm  = self._font_sm

        # ── Hoop ──
        hx, hy = self.hoop_x, self.hoop_y
        pygame.draw.rect(surface, T["GRAY"],   (hx + HOOP_W//2 - 10, hy - 60, 20, 60))
        pygame.draw.rect(surface, T["ACCENT"],  (hx, hy, HOOP_W, HOOP_H), border_radius=6)
        pygame.draw.rect(surface, T["ACCENT2"], (hx, hy, HOOP_W, HOOP_H), 3, border_radius=6)

        # ── Ball ──
        bx = int(self.ball_x) if self.ball_active else GAME_W // 2
        by = int(self.ball_y) if self.ball_active else GAME_H - 160
        pygame.draw.circle(surface, T["ORANGE"], (bx, by), BALL_R)
        pygame.draw.circle(surface, T["TEXT"],   (bx, by), BALL_R, 3)
        pygame.draw.arc(surface, T["TEXT"],
                        pygame.Rect(bx-BALL_R, by-BALL_R, BALL_R*2, BALL_R*2),
                        0.5, 2.6, 2)

        # ── Grip bar ──
        needle  = 1.0 - self._grip
        half    = self.zone_w / 2
        in_zone = (self.zone_pos - half) <= needle <= (self.zone_pos + half)

        # Red background
        pygame.draw.rect(surface, T["RED"],   (BAR_X, BAR_Y, BAR_W, BAR_H), border_radius=8)
        # Green zone
        gz_y = BAR_Y + int((self.zone_pos - half) * BAR_H)
        gz_h = max(6, int(self.zone_w * BAR_H))
        pygame.draw.rect(surface, T["GREEN"], (BAR_X, gz_y, BAR_W, gz_h), border_radius=4)
        # Needle — turns green when inside zone
        needle_y   = BAR_Y + int(needle * BAR_H)
        needle_col = T["GREEN"] if in_zone else T["WHITE"]
        pygame.draw.rect(surface, needle_col,
                         (BAR_X - 16, needle_y - 6, BAR_W + 32, 12), border_radius=6)
        # Bar border
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

        # ── Top HUD ──
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

        # Feedback
        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, GAME_H // 2 - 60))

        # Hint
        if self.difficulty == "Easy":
            hint = "Squeeze slowly into the GREEN zone, then RELEASE to shoot  |  ESC = Pause"
        else:
            hint = "Zone moves while relaxed — squeeze to freeze it, release in GREEN to shoot  |  ESC = Pause"
        surface.blit(font_sm.render(hint, True, T["GRAY"]), (80, GAME_H - 44))

        # Debug
        dbg = pygame.font.SysFont("monospace", 20)
        raw_v = self._state.get("grip", -1)
        surface.blit(dbg.render(
            f"diff={self.difficulty}  raw={raw_v:.2f}  grip={self._grip:.2f}  squeezing={self._squeezing}  paused={self.paused}  fatigue={self.fatigue_paused}  cooldown={self._cooldown:.2f}",
            True, (255,255,0)), (80, GAME_H - 70))

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)
