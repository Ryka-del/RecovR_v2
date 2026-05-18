"""
Whack-A-Mole — Finger Flexion game (1920x1080)

Mechanic:
  - 5 mole holes, one per finger (index→pinky + thumb)
  - A mole pops up in a hole; patient presses the matching finger button
  - EASY:   Classic — just hit the lit mole. 2 fingers active at a time.
  - MEDIUM: Go/No-Go — GREEN mole = hit it, RED mole = ignore it.
  - HARD:   Inhibitory — hit unless a warning symbol appears (Stroop-style).

Anti-spasticity: mass flexion (all 5 buttons at once) is ignored.
Goal: hit 15 correct moles OR reach 80% accuracy within 20–30 seconds.
"""

import pygame
import random
import time
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import get_theme, GAME_W, GAME_H

GOALS        = {"Easy": 15, "Medium": 15, "Hard": 15}
DURATION     = {"Easy": 45, "Medium": 40, "Hard": 35}
MOLE_TIME    = {"Easy": 3.0, "Medium": 2.2, "Hard": 1.4}   # seconds mole stays up
ACTIVE_LANES = {"Easy": 2,   "Medium": 5,   "Hard": 5}

FINGER_LABELS = ["Index", "Middle", "Ring", "Pinky", "Thumb"]
FINGER_KEYS   = [pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f, pygame.K_g]

COL_W = GAME_W // 5   # 384px per column
# Hole centers: horizontally centered in each column, vertically centered in the play area
PLAY_TOP = 80    # below HUD bar
PLAY_BOT = GAME_H - 120  # above key labels
HOLE_Y   = (PLAY_TOP + PLAY_BOT) // 2
HOLE_POSITIONS = [
    (COL_W * i + COL_W // 2, HOLE_Y) for i in range(5)
]

class Mole:
    def __init__(self, lane, color, valid, lifetime):
        self.lane     = lane
        self.color    = color   # GREEN=go, RED=no-go
        self.valid    = valid   # True = should be hit
        self.lifetime = lifetime
        self.timer    = 0.0
        self.hit      = False
        self.expired  = False
        self.spawn_t  = time.time() * 1000   # for reaction time tracking

    def update(self, dt):
        if not self.hit:
            self.timer += dt
            if self.timer >= self.lifetime:
                self.expired = True

    def draw(self, surface, font, x, y, T):
        if self.expired and not self.hit:
            return
        radius = 54
        color = self.color if not self.hit else T["GRAY"]
        pygame.draw.circle(surface, T["PANEL"],  (x, y), radius)
        pygame.draw.circle(surface, color,  (x, y), radius, 6)
        if not self.hit:
            import math
            progress = 1.0 - (self.timer / self.lifetime)
            arc_rect = pygame.Rect(x-radius-10, y-radius-10, (radius+10)*2, (radius+10)*2)
            end_angle = -math.pi/2 + 2*math.pi*progress
            pygame.draw.arc(surface, T["YELLOW"], arc_rect, -math.pi/2, end_angle, 5)
            pygame.draw.circle(surface, color, (x, y), 16)
        else:
            pygame.draw.line(surface, T["GREEN"], (x-20, y-20), (x+20, y+20), 6)
            pygame.draw.line(surface, T["GREEN"], (x+20, y-20), (x-20, y+20), 6)
        lbl = font.render(FINGER_LABELS[self.lane][0], True, color)
        surface.blit(lbl, (x - lbl.get_width()//2, y + radius + 8))


class WhackMoleGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self.exercise   = "finger"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.goal        = GOALS[self.difficulty]
        self.duration    = DURATION[self.difficulty]
        self.mole_time   = MOLE_TIME[self.difficulty]
        self.active_lanes = list(range(ACTIVE_LANES[self.difficulty]))

        # Adaptive: use reaction baseline only to scale Easy slightly
        reaction_ms = self.cal.get("reaction_ms", 800)
        if self.difficulty == "Easy":
            self.mole_time = max(2.0, reaction_ms / 1000 * 2.0)

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
        self._font_obj = pygame.font.SysFont("monospace", 26, bold=True)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)

    def _reset(self):
        self.moles       = [None] * 5
        self.score       = 0
        self.errors      = 0
        self.reps        = 0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.spawn_timer = 0.0
        self.spawn_interval = self.mole_time * 0.7
        self.flash       = {}
        self.feedback    = None
        self.reaction_times = []
        self._prev_fingers  = [0] * 5

    def _spawn_mole(self):
        empty = [i for i in self.active_lanes if self.moles[i] is None]
        if not empty: return
        lane = random.choice(empty)
        T = get_theme()
        G, R = T["GREEN"], T["RED"]
        if self.difficulty == "Easy":
            color, valid = G, True
        elif self.difficulty == "Medium":
            color, valid = random.choice([(G, True), (G, True), (R, False)])
        else:
            color = G
            valid = random.random() > 0.3
            if not valid: color = R
        self.moles[lane] = Mole(lane, color, valid, self.mole_time)

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
                if self.pause_sel == 0: self.paused = False
                elif self.pause_sel == 1: self._reset(); self.paused = False
                elif self.pause_sel == 2: self.vol_active = True
                else: self._end_game()
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.paused = True; return
            if event.key in FINGER_KEYS:
                self._handle_press(FINGER_KEYS.index(event.key))

    def _handle_press(self, lane):
        # Mass flexion check — if all 5 pressed simultaneously, ignore
        state = input_handler.get_state()
        if sum(state["fingers"]) >= 5:
            return

        self.flash[lane] = 0.15
        mole = self.moles[lane]
        if mole and not mole.hit and not mole.expired:
            if mole.valid:
                reaction = (time.time()*1000 - mole.spawn_t)
                self.reaction_times.append(reaction)
                mole.hit = True
                self.score += 1
                self.reps  += 1
                self.feedback = ("HIT!", (0, 255, 160), 0.6)
                play_success()
            else:
                mole.hit = True
                self.errors += 1
                self.feedback = ("NO-GO! Penalty.", (255, 60, 80), 0.8)
                play_error()
        elif mole is None or mole.expired:
            # Pressed empty hole
            if self.difficulty != "Easy":
                self.errors += 1

    def update(self, dt):
        state = input_handler.get_state()

        # ESP32 hardware button polling — only fire on rising edge (press, not hold)
        if input_handler.connected:
            fingers = state["fingers"]
            if sum(fingers) < 5:   # ignore mass flexion
                for i, pressed in enumerate(fingers):
                    if pressed and not self._prev_fingers[i]:
                        self._handle_press(i)
            self._prev_fingers = list(fingers)

        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused: return

        self.time_left -= dt
        if self.time_left <= 0 or self.score >= self.goal:
            self._end_game(); return

        # Spawn
        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_interval:
            self.spawn_timer = 0.0
            self._spawn_mole()

        for i, mole in enumerate(self.moles):
            if mole:
                mole.update(dt)
                if mole.expired or mole.hit:
                    self.moles[i] = None

        for lane in list(self.flash):
            self.flash[lane] -= dt
            if self.flash[lane] <= 0: del self.flash[lane]

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None


    def _exit_to_menu(self):
        stop_music()
        self.manager.go_to("exercise_menu",
            account_id=self.account_id, account=self.account)

    def _end_game(self):
        stop_music()
        duration = (pygame.time.get_ticks() - self.start_time) // 1000
        total    = self.score + self.errors
        accuracy = int(self.score / total * 100) if total > 0 else 0
        avg_rt   = int(sum(self.reaction_times)/len(self.reaction_times)) if self.reaction_times else 0
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="whack_mole",
            difficulty=self.difficulty, score=self.score,
            reps=self.reps, duration_sec=duration,
            max_score=self.goal, back_screen="game_select",
            accuracy=accuracy, avg_reaction_ms=avg_rt)

    def draw(self, surface):
        T = get_theme()
        # Scanline grid
        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)
        for x in range(0, GAME_W, 80):
            pygame.draw.line(surface, T["PANEL"], (x, 0), (x, GAME_H), 1)

        font_hud = self._font_hud
        font_sm  = self._font_sm
        font_obj = self._font_obj

        # Target panels — 5 columns
        col_w = GAME_W // 5
        for i, (hx, hy) in enumerate(HOLE_POSITIONS):
            active = self.moles[i] is not None and not self.moles[i].expired
            flash  = i in self.flash
            col    = LANE_COLORS[i]

            col_surf = pygame.Surface((col_w - 20, PLAY_BOT - PLAY_TOP), pygame.SRCALPHA)
            col_surf.fill((col[0]//8, col[1]//8, col[2]//8, 180))
            surface.blit(col_surf, (i * col_w + 10, PLAY_TOP))
            pygame.draw.rect(surface, col if active else T["PANEL"],
                             (i * col_w + 10, PLAY_TOP, col_w - 20, PLAY_BOT - PLAY_TOP),
                             2, border_radius=8)

            ring_col = col if active else (40, 50, 80)
            pygame.draw.circle(surface, ring_col, (hx, hy), 70, 4)
            if active:
                pygame.draw.circle(surface, ring_col, (hx, hy), 50, 2)
                self.moles[i].draw(surface, font_obj, hx, hy, T)
            else:
                pygame.draw.line(surface, (40,50,80), (hx-20, hy), (hx+20, hy), 2)
                pygame.draw.line(surface, (40,50,80), (hx, hy-20), (hx, hy+20), 2)

            if flash:
                fl = pygame.Surface((col_w - 20, PLAY_BOT - PLAY_TOP), pygame.SRCALPHA)
                fl.fill((*col, 60))
                surface.blit(fl, (i * col_w + 10, PLAY_TOP))

            key_lbl = font_obj.render(["A","S","D","F","G"][i], True, col)
            surface.blit(key_lbl, (hx - key_lbl.get_width()//2, GAME_H - 100))
            finger_lbl = font_sm.render(FINGER_LABELS[i], True, T["GRAY"])
            surface.blit(finger_lbl, (hx - finger_lbl.get_width()//2, GAME_H - 68))

        # Top HUD bar
        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)

        diff_colors = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}
        themes = {"Easy": "FINGER FLEXION  ·  BASIC REACTION",
                  "Medium": "FINGER FLEXION  ·  GO / NO-GO",
                  "Hard": "FINGER FLEXION  ·  INHIBITORY CONTROL"}
        surface.blit(font_hud.render(themes[self.difficulty],
                     True, diff_colors[self.difficulty]), (80, 18))
        surface.blit(font_hud.render(
            f"{self.score:02d} / {self.goal:02d}", True, T["ACCENT"]),
            (GAME_W//2 - 60, 18))
        surface.blit(font_hud.render(
            f"{max(0, int(self.time_left)):02d}s", True, T["TEXT"]),
            (GAME_W - 160, 18))

        # Accuracy bar
        total = self.score + self.errors
        acc   = self.score / total if total > 0 else 1.0
        bw, bh = 400, 14
        bx = GAME_W//2 - bw//2
        pygame.draw.rect(surface, T["PANEL"], (bx, GAME_H - 44, bw, bh), border_radius=7)
        pygame.draw.rect(surface, T["GREEN"] if acc >= 0.8 else T["YELLOW"],
                         (bx, GAME_H - 44, int(bw * acc), bh), border_radius=7)
        surface.blit(font_sm.render(f"ACC {int(acc*100)}%", True, T["TEXT"]),
                     (bx + bw + 12, GAME_H - 48))
        surface.blit(font_sm.render(f"ERR {self.errors}", True, T["RED"]),
                     (bx - 100, GAME_H - 48))

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W//2 - msg.get_width()//2, GAME_H//2 - 60))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

    def _apply_vol(self):
        try:
            pygame.mixer.music.set_volume(self.pause_vol)
            from db.database import set_volume
            set_volume(self.pause_vol)
        except Exception:
            pass

# Lane colors for flash effect
LANE_COLORS = [(255,80,120),(0,210,255),(180,0,255),(0,255,160),(255,200,0)]
