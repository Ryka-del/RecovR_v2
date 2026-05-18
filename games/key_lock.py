"""
Key & Lock — Wrist Rotation game (1920x1080)

Mechanic:
  - A key on screen rotates with the patient's wrist (MPU6050 tilt_x)
  - A lock shows the TARGET angle
  - Patient rotates wrist to align key with lock within tolerance
  - Hold alignment for 0.5s → lock opens → next lock

Difficulty:
  EASY   — Greenhouse Gate: static lock, ±15° tolerance, color matching hint
  MEDIUM — Library Cabinet: sequence of 3 locks in order, ±8° tolerance
  HARD   — The Clockmaker: lock wobbles/drifts, ±3° tolerance, only unlock when green

Goal: unlock 3–5 locks per round (30–60 seconds)
Low-pass filter applied to wrist angle to smooth tremors.
"""

import pygame
import math
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import get_theme, GAME_W, GAME_H

GOALS      = {"Easy": 3, "Medium": 4, "Hard": 5}
TOLERANCE  = {"Easy": 15, "Medium": 8, "Hard": 3}   # degrees
DURATION   = {"Easy": 60, "Medium": 50, "Hard": 40}
HOLD_TIME  = 0.5   # seconds to hold alignment before unlock

LOCK_COLORS = [(0,210,255),(0,255,160),(255,220,0),(180,0,255),(255,140,0)]

CENTER_X = GAME_W // 2
CENTER_Y = GAME_H // 2

class Lock:
    def __init__(self, target_angle, color, wobble=False):
        self.target  = target_angle   # degrees, 0=up, +right, -left
        self.color   = color
        self.wobble  = wobble
        self.wobble_t = 0.0
        self.active  = True
        self.unlocked = False
        self.is_green = True   # Hard mode: only unlock when True

    def update(self, dt):
        if self.wobble:
            self.wobble_t += dt
            self.target += math.sin(self.wobble_t * 2.5) * 0.8
            # Hard mode: toggle green/red every ~2s
            self.is_green = (int(self.wobble_t) % 4) < 2

    def effective_target(self):
        return self.target


class KeyLockGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.goal      = GOALS[self.difficulty]
        self.tolerance = TOLERANCE[self.difficulty]
        self.duration  = DURATION[self.difficulty]

        self._init_fatigue()
        start_music()
        self._reset()
        self.paused    = False
        self.pause_sel = 0
        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4
        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)
        self._font_key = pygame.font.SysFont("monospace", 22, bold=True)

        # Low-pass filter state
        self._smooth_angle = 0.0
        self._lp_alpha     = 0.15
        self._state        = {"tilt_x": 0.0}

    def _reset(self):
        self.score       = 0
        self.reps        = 0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.hold_timer  = 0.0
        self.feedback    = None
        self.unlock_anim = 0.0   # flash timer on unlock
        self._gen_locks()

    def _gen_locks(self):
        if self.difficulty == "Easy":
            angle = random.choice([-60, -30, 0, 30, 60, 90])
            self.locks = [Lock(angle, random.choice(LOCK_COLORS), wobble=False)]
        elif self.difficulty == "Medium":
            angles = random.sample([-60,-30,0,30,60,90,-90], 3)
            self.locks = [Lock(a, LOCK_COLORS[i], wobble=False) for i,a in enumerate(angles)]
            self.lock_idx = 0
        else:
            angles = random.sample([-60,-30,0,30,60,90,-90], 5)
            self.locks = [Lock(a, LOCK_COLORS[i], wobble=True) for i,a in enumerate(angles)]
            self.lock_idx = 0

    def _current_lock(self):
        if self.difficulty == "Easy":
            return self.locks[0] if self.locks else None
        else:
            if self.lock_idx < len(self.locks):
                return self.locks[self.lock_idx]
        return None

    def _normalize_tilt(self, raw):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin: return 0.0
        norm = (raw - wmin) / (wmax - wmin)   # 0–1
        return (norm - 0.5) * 180.0           # map to -90°..+90°

    def handle_event(self, event):
        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"): self._resume_fatigue()
            return
        if self.paused:
            if self.vol_active:
                if input_handler.was_pressed(event, "left"):
                    self.pause_vol = max(0.0, self.pause_vol - 0.1); self._apply_vol()
                elif input_handler.was_pressed(event, "right"):
                    self.pause_vol = min(1.0, self.pause_vol + 0.1); self._apply_vol()
                elif input_handler.was_pressed(event, "action") or input_handler.was_pressed(event, "back"):
                    self.vol_active = False
                return
            if input_handler.was_pressed(event, "up"):   self.pause_sel = max(0, self.pause_sel - 1)
            elif input_handler.was_pressed(event, "down"): self.pause_sel = min(3, self.pause_sel + 1)
            elif input_handler.was_pressed(event, "action"):
                if self.pause_sel == 0:   self.paused = False
                elif self.pause_sel == 1: self._reset(); self.paused = False
                elif self.pause_sel == 2: self.vol_active = True
                else:                     self._exit_to_menu()
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True; self.pause_sel = 0

    def update(self, dt):
        state = input_handler.get_state()
        self._state = state
        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused: return

        self.time_left -= dt
        if self.time_left <= 0: self._end_game(); return

        # Get wrist angle
        if input_handler.connected:
            raw_angle = self._normalize_tilt(state["tilt_x"])
        else:
            # Keyboard fallback: tilt_x from arrow keys (-1 to 1) → degrees
            raw_angle = self._smooth_angle + state["tilt_x"] * 90 * dt * 3
            raw_angle = max(-90, min(90, raw_angle))

        # Low-pass filter (tremor smoothing)
        self._smooth_angle += self._lp_alpha * (raw_angle - self._smooth_angle)

        lock = self._current_lock()
        if lock:
            lock.update(dt)
            diff = abs(self._smooth_angle - lock.effective_target())
            diff = min(diff, 360 - diff)   # handle wrap

            in_zone = diff <= self.tolerance
            can_unlock = in_zone and (self.difficulty != "Hard" or lock.is_green)

            if can_unlock:
                self.hold_timer += dt
                if self.hold_timer >= HOLD_TIME:
                    self._unlock(lock)
            else:
                self.hold_timer = max(0.0, self.hold_timer - dt * 2)

        if self.unlock_anim > 0:
            self.unlock_anim -= dt

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None

    def _unlock(self, lock):
        lock.unlocked = True
        self.score += 1
        self.reps  += 1
        self.hold_timer  = 0.0
        self.unlock_anim = 0.6
        self.feedback = ("UNLOCKED", (0, 255, 160), 1.0)
        play_success()
        if self.difficulty == "Easy":
            self._gen_locks()
        else:
            self.lock_idx += 1
            if self.lock_idx >= len(self.locks):
                self._gen_locks()
                self.lock_idx = 0
        if self.score >= self.goal:
            self._end_game()


    def _exit_to_menu(self):
        stop_music()
        self.manager.go_to("exercise_menu",
            account_id=self.account_id, account=self.account)

    def _end_game(self):
        stop_music()
        duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="key_lock",
            difficulty=self.difficulty, score=self.score,
            reps=self.reps, duration_sec=duration,
            max_score=self.goal, back_screen="game_select")

    def draw(self, surface):
        T = get_theme()
        surface.fill(T["BG"])
        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)
        for x in range(0, GAME_W, 80):
            pygame.draw.line(surface, T["PANEL"], (x, 0), (x, GAME_H), 1)

        font_hud = self._font_hud
        font_sm  = self._font_sm

        lock = self._current_lock()
        if lock:
            target_rad = math.radians(lock.effective_target())
            key_rad    = math.radians(self._smooth_angle)
            diff       = abs(self._smooth_angle - lock.effective_target())
            diff       = min(diff, 360 - diff)
            in_zone    = diff <= self.tolerance

            lock_color = lock.color
            if self.difficulty == "Hard":
                lock_color = T["GREEN"] if lock.is_green else T["RED"]

            pygame.draw.circle(surface, T["PANEL"], (CENTER_X, CENTER_Y), 220, 2)
            pygame.draw.circle(surface, T["ACCENT"], (CENTER_X, CENTER_Y), 220, 1)

            tol_rad  = math.radians(self.tolerance)
            arc_rect = pygame.Rect(CENTER_X - 180, CENTER_Y - 180, 360, 360)
            pygame.draw.arc(surface, lock_color, arc_rect,
                            -target_rad - tol_rad - math.pi/2,
                            -target_rad + tol_rad - math.pi/2, 8)

            self._draw_key(surface, CENTER_X + 320, CENTER_Y,
                           target_rad, lock_color, "TARGET", T)

            player_col = T["GREEN"] if in_zone else T["ACCENT"]
            self._draw_key(surface, CENTER_X - 320, CENTER_Y,
                           key_rad, player_col, "YOUR WRIST", T)

            line_col = T["GREEN"] if in_zone else (60, 80, 120)
            pygame.draw.line(surface, line_col,
                             (CENTER_X - 220, CENTER_Y), (CENTER_X + 220, CENTER_Y), 1)

            surface.blit(font_sm.render(
                f"{self._smooth_angle:+.1f}°  →  {lock.effective_target():+.1f}°  Δ{diff:.1f}°",
                True, T["ACCENT"]), (CENTER_X - 200, CENTER_Y + 260))

            if in_zone:
                prog = min(1.0, self.hold_timer / HOLD_TIME)
                hold_rect = pygame.Rect(CENTER_X - 40, CENTER_Y - 40, 80, 80)
                pygame.draw.arc(surface, T["GREEN"], hold_rect,
                                -math.pi/2, -math.pi/2 + 2*math.pi*prog, 8)

            if self.unlock_anim > 0:
                alpha = int(100 * self.unlock_anim / 0.6)
                fl = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
                fl.fill((0, 255, 160, alpha))
                surface.blit(fl, (0, 0))

            if self.difficulty in ("Medium", "Hard"):
                sx = GAME_W//2 - len(self.locks) * 35
                for i, lk in enumerate(self.locks):
                    active = (i == self.lock_idx)
                    col = T["ACCENT"] if active else (T["GREEN"] if lk.unlocked else T["GRAY"])
                    pygame.draw.circle(surface, col, (sx + i*70, GAME_H - 80), 16)
                    if active:
                        pygame.draw.circle(surface, T["ACCENT"], (sx + i*70, GAME_H - 80), 20, 2)

        tilt_norm = (self._smooth_angle + 90) / 180
        ind_x = int(120 + tilt_norm * (GAME_W - 240))
        pygame.draw.rect(surface, T["PANEL"], (120, GAME_H - 50, GAME_W - 240, 12), border_radius=6)
        pygame.draw.circle(surface, T["ACCENT"], (ind_x, GAME_H - 44), 10)

        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)
        diff_colors = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}
        themes = {"Easy": "WRIST ROTATION  ·  STATIC TARGET  ±15°",
                  "Medium": "WRIST ROTATION  ·  SEQUENCE  ±8°",
                  "Hard": "WRIST ROTATION  ·  PRECISION  ±3°"}
        surface.blit(font_hud.render(themes[self.difficulty],
                     True, diff_colors[self.difficulty]), (80, 18))
        surface.blit(font_hud.render(
            f"{self.score:02d} / {self.goal:02d}", True, T["ACCENT"]),
            (GAME_W//2 - 60, 18))
        surface.blit(font_hud.render(
            f"{max(0, int(self.time_left)):02d}s", True, T["TEXT"]),
            (GAME_W - 160, 18))

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W//2 - msg.get_width()//2, CENTER_Y - 300))

        surface.blit(font_sm.render(
            "← → Rotate wrist to align with TARGET  ESC=Pause",
            True, T["GRAY"]), (GAME_W//2 - 320, GAME_H - 110))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

    def _draw_key(self, surface, cx, cy, angle_rad, color, label, T):
        length = 120
        ex = cx + math.sin(angle_rad) * length
        ey = cy - math.cos(angle_rad) * length
        pygame.draw.line(surface, color, (cx, cy), (int(ex), int(ey)), 8)
        pygame.draw.circle(surface, color, (cx, cy), 24)
        pygame.draw.circle(surface, T["PANEL"], (cx, cy), 24, 4)
        for t in range(3):
            tx = cx + math.sin(angle_rad + math.pi/2) * (8 + t*14)
            ty = cy - math.cos(angle_rad + math.pi/2) * (8 + t*14)
            mx = tx + math.sin(angle_rad) * 16
            my = ty - math.cos(angle_rad) * 16
            pygame.draw.line(surface, color, (int(tx), int(ty)), (int(mx), int(my)), 5)
        lbl = self._font_key.render(label, True, color)
        surface.blit(lbl, (cx - lbl.get_width()//2, cy + 36))

