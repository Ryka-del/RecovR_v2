"""
Catch the Falling Object — Grip Strength / Wrist game (1920x1080)

Mechanic (original):
  - Objects fall from the top
  - tilt_x (← →) moves the catcher left/right
  - SQUEEZE (grip >= threshold) to catch an object when it's over the catcher
  - RELEASE grip to score the caught object
  - Catching an invalid target (Medium/Hard) counts as an error
"""

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import get_theme, GAME_W, GAME_H

GOALS        = {"Easy": 8,   "Medium": 10, "Hard": 12}
THRESHOLDS   = {"Easy": 0.30, "Medium": 0.45, "Hard": 0.60}
FALL_SPEEDS  = {"Easy": 100, "Medium": 180, "Hard": 280}
SPAWN_RATES  = {"Easy": 2.8, "Medium": 2.0, "Hard": 1.2}
DURATION     = {"Easy": 60,  "Medium": 50,  "Hard": 40}
MOVE_SPEED   = {"Easy": 600, "Medium": 750, "Hard": 900}

CATCHER_Y = GAME_H - 120
CATCHER_W = 200
CATCHER_H = 20

OBJ_COLORS = [(0,210,255),(180,0,255),(0,255,160),(255,220,0),(255,140,0)]


class FallingObj:
    def __init__(self, difficulty, speed):
        self.x      = random.randint(100, GAME_W - 100)
        self.y      = -40.0
        self.speed  = speed + random.uniform(-20, 20)
        self.color  = random.choice(OBJ_COLORS)
        self.r      = 30
        self.pulse  = 0.0
        self.caught = False
        self.scored = False
        self.missed = False
        # Medium/Hard: some objects are invalid (red)
        if difficulty == "Easy":
            self.valid = True
        else:
            self.valid = random.random() > 0.3
            if not self.valid:
                self.color = (255, 60, 80)

    def update(self, dt):
        self.pulse += dt * 3
        if not self.caught:
            self.y += self.speed * dt
        if self.y > GAME_H + 60 and not self.caught:
            self.missed = True

    def draw(self, surface):
        if self.scored or self.missed:
            return
        cx, cy = int(self.x), int(self.y)
        pr = int(self.r + 4 * math.sin(self.pulse))
        pygame.draw.circle(surface, self.color, (cx, cy), pr, 3)
        pygame.draw.circle(surface, self.color, (cx, cy), self.r)
        if not self.valid:
            # X mark on invalid objects
            pygame.draw.line(surface, (255,255,255), (cx-12,cy-12),(cx+12,cy+12), 3)
            pygame.draw.line(surface, (255,255,255), (cx+12,cy-12),(cx-12,cy+12), 3)


class CatchObjectGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.threshold  = THRESHOLDS[self.difficulty]
        self.fall_speed = FALL_SPEEDS[self.difficulty]
        self.spawn_rate = SPAWN_RATES[self.difficulty]
        self.goal       = GOALS[self.difficulty]
        self.duration   = DURATION[self.difficulty]
        self.move_speed = MOVE_SPEED[self.difficulty]

        self._init_fatigue()
        start_music()
        self._reset()
        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4
        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)
        self._font_fb  = pygame.font.SysFont("monospace", 48, bold=True)

    def _reset(self):
        self.objects     = []
        self.score       = 0
        self.misses      = 0
        self.errors      = 0
        self.reps        = 0
        self.held_obj    = None
        self.spawn_timer = 0.0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.catcher_x   = float(GAME_W // 2)
        self.feedback    = None
        self.score_flash = 0.0
        self._state      = {"grip": 0.0, "tilt_x": 0.0}

    def _normalize_grip(self, raw):
        rest = self.cal.get("grip_rest", 0.0)
        mx   = self.cal.get("grip_max",  1.0)
        if mx <= rest:
            return raw
        return max(0.0, min(1.0, (raw - rest) / (mx - rest)))

    def _normalize_tilt(self, raw):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return raw
        return max(-1.0, min(1.0, (raw - wmin) / (wmax - wmin) * 2.0 - 1.0))

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
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True

    def update(self, dt):
        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0 or self.score >= self.goal:
            self._end_game(); return

        grip = self._normalize_grip(self._state["grip"])

        # Move catcher left/right with tilt_x
        tx = self._normalize_tilt(self._state["tilt_x"])
        if abs(tx) > 0.08:
            self.catcher_x += self.move_speed * dt * tx
        self.catcher_x = max(CATCHER_W//2, min(GAME_W - CATCHER_W//2, self.catcher_x))

        # Spawn
        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_rate and self.held_obj is None:
            self.spawn_timer = 0.0
            self.objects.append(FallingObj(self.difficulty, self.fall_speed))

        for obj in self.objects:
            obj.update(dt)

        # Try to catch — squeeze when object is over catcher
        if self.held_obj is None:
            for obj in self.objects:
                if obj.caught or obj.missed or obj.scored:
                    continue
                over_catcher = (abs(obj.x - self.catcher_x) < CATCHER_W//2 + obj.r and
                                CATCHER_Y - 60 < obj.y < CATCHER_Y + 30)
                if over_catcher and grip >= self.threshold:
                    if obj.valid:
                        obj.caught   = True
                        self.held_obj = obj
                        self.feedback = ("GRIPPED — Release to score!", (0,210,255), 1.2)
                    else:
                        obj.missed = True
                        self.errors += 1
                        self.feedback = ("WRONG TARGET!", (255,60,80), 1.0)
                        play_error()

        # Release to score
        if self.held_obj:
            self.held_obj.x = self.catcher_x
            self.held_obj.y = float(CATCHER_Y - 30)
            released = grip < (0.05 if not input_handler.connected else 0.15)
            if released:
                self.held_obj.scored = True
                self.held_obj = None
                self.score       += 1
                self.reps        += 1
                self.score_flash  = 0.4
                self.feedback     = ("SCORED!", (0,255,160), 0.8)
                play_success()

        # Count misses
        new_misses = [o for o in self.objects if o.missed]
        self.misses += len(new_misses)
        self.objects = [o for o in self.objects if not o.missed and not o.scored]

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None
        if self.score_flash > 0:
            self.score_flash -= dt

    def _exit_to_menu(self):
        stop_music()
        self.manager.go_to("exercise_menu",
                           account_id=self.account_id, account=self.account)

    def _end_game(self):
        stop_music()
        duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="catch_object",
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

        for obj in self.objects:
            obj.draw(surface)

        # Catcher
        cx = int(self.catcher_x)
        pygame.draw.rect(surface, T["ACCENT"],
                         (cx - CATCHER_W//2, CATCHER_Y, CATCHER_W, CATCHER_H),
                         border_radius=8)
        pygame.draw.rect(surface, T["ACCENT2"],
                         (cx - CATCHER_W//2, CATCHER_Y, CATCHER_W, CATCHER_H),
                         3, border_radius=8)
        pygame.draw.circle(surface, T["ACCENT2"], (cx - CATCHER_W//2, CATCHER_Y + CATCHER_H//2), 10)
        pygame.draw.circle(surface, T["ACCENT2"], (cx + CATCHER_W//2, CATCHER_Y + CATCHER_H//2), 10)

        # Held object glow
        if self.held_obj:
            pygame.draw.circle(surface, T["ACCENT"],
                               (int(self.held_obj.x), int(self.held_obj.y)), 50, 2)

        # Score flash
        if self.score_flash > 0:
            alpha = int(80 * self.score_flash / 0.4)
            fl = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
            fl.fill((0, 255, 160, alpha))
            surface.blit(fl, (0, 0))

        # Grip bar (left side)
        grip  = self._normalize_grip(self._state.get("grip", 0.0))
        bx, by, bw, bh = 30, GAME_H//2 - 200, 28, 400
        pygame.draw.rect(surface, T["PANEL"], (bx, by, bw, bh), border_radius=6)
        fill_h  = int(bh * grip)
        bar_col = T["GREEN"] if grip >= self.threshold else T["ACCENT"]
        pygame.draw.rect(surface, bar_col,
                         (bx, by + bh - fill_h, bw, fill_h), border_radius=6)
        th_y = by + bh - int(bh * self.threshold)
        pygame.draw.line(surface, T["YELLOW"], (bx - 10, th_y), (bx + bw + 10, th_y), 3)
        surface.blit(font_sm.render("GRIP", True, T["GRAY"]), (bx - 8, by - 28))
        surface.blit(font_sm.render(f"{int(grip*100)}%", True, bar_col), (bx - 8, by + bh + 6))

        # Tilt indicator (bottom)
        tx    = self._normalize_tilt(self._state.get("tilt_x", 0.0))
        ibw   = GAME_W - 200
        ibx   = 100
        iby   = GAME_H - 50
        pygame.draw.rect(surface, T["PANEL"], (ibx, iby, ibw, 12), border_radius=6)
        ind_x = int(ibx + (tx + 1) / 2 * ibw)
        pygame.draw.circle(surface, T["ACCENT"], (ind_x, iby + 6), 10)

        # Top HUD
        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)
        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        surface.blit(font_hud.render(
            f"CATCH OBJECT  ·  {self.difficulty.upper()}", True, diff_col), (80, 18))
        surface.blit(font_hud.render(
            f"{self.score:02d} / {self.goal:02d}", True, T["ACCENT"]),
            (GAME_W//2 - 60, 18))
        time_col = T["RED"] if self.time_left < 10 else T["TEXT"]
        surface.blit(font_hud.render(
            f"{max(0, int(self.time_left)):02d}s", True, time_col),
            (GAME_W - 160, 18))

        surface.blit(font_sm.render(
            f"Miss {self.misses}  Err {self.errors}", True, T["RED"]),
            (GAME_W - 260, GAME_H - 80))

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W//2 - msg.get_width()//2, GAME_H//2 - 80))

        hints = {"Easy":   "← → Tilt to move   SQUEEZE to catch   RELEASE to score",
                 "Medium": "← → Tilt to move   Catch GREEN only   Ignore RED (✕)",
                 "Hard":   "← → Tilt to move   Catch GREEN only   Ignore RED (✕)"}
        surface.blit(font_sm.render(hints[self.difficulty], True, T["GRAY"]),
                     (GAME_W//2 - 380, GAME_H - 80))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

    def _draw_pause(self, surface):
        T       = get_theme()
        font    = pygame.font.SysFont("monospace", 48, bold=True)
        font_sm = pygame.font.SysFont("monospace", 28)
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        surface.blit(ov, (0, 0))
        panel = pygame.Rect(GAME_W//2 - 260, GAME_H//2 - 200, 520, 420)
        pygame.draw.rect(surface, T["PANEL"], panel, border_radius=16)
        pygame.draw.rect(surface, T["ACCENT"], panel, 2, border_radius=16)
        for i, opt in enumerate(["RESUME", "RESTART", "VOLUME", "EXIT"]):
            col = T["ACCENT"] if i == self.pause_sel else T["GRAY"]
            lbl = font.render(opt, True, col)
            surface.blit(lbl, (GAME_W//2 - lbl.get_width()//2,
                               GAME_H//2 - 160 + i * 96))
            if opt == "VOLUME" and (i == self.pause_sel or self.vol_active):
                bw, bh = 360, 12
                bx = GAME_W//2 - bw//2
                by = GAME_H//2 - 160 + i * 96 + 52
                pygame.draw.rect(surface, T["PANEL"], (bx, by, bw, bh), border_radius=6)
                pygame.draw.rect(surface, T["GREEN"],
                                 (bx, by, int(bw * self.pause_vol), bh), border_radius=6)
                pct = font_sm.render(f"{int(self.pause_vol*100)}%", True, T["GREEN"])
                surface.blit(pct, (bx + bw + 10, by - 4))
