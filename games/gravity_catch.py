import pygame
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import start_music, stop_music
from constants import get_theme, GAME_W, GAME_H

CATCHER_SPEED = {"Easy": 500, "Medium": 700, "Hard": 900}
FALL_SPEED    = {"Easy": 200, "Medium": 340, "Hard": 500}
SPAWN_RATE    = {"Easy": 1.6, "Medium": 1.0, "Hard": 0.6}
DURATION      = {"Easy": 40,  "Medium": 50,  "Hard": 60}

CATCHER_W = 200
CATCHER_Y = GAME_H - 120


class FallingObject:
    def __init__(self, speed, colors):
        self.x     = random.randint(60, GAME_W - 60)
        self.y     = -30.0
        self.speed = speed + random.uniform(-40, 40)
        self.color = random.choice(colors)
        self.r     = random.randint(20, 36)

    def update(self, dt):
        self.y += self.speed * dt

    def draw(self, surface, white):
        pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), self.r)
        pygame.draw.circle(surface, white,       (int(self.x), int(self.y)), self.r, 3)


class GravityCatchGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id    = data.get("account_id")
        self.account       = data.get("account")
        self.exercise      = "wrist"
        self.difficulty    = data.get("difficulty", "Easy")
        self.cal           = data.get("calibration", {})

        self.catcher_speed = CATCHER_SPEED[self.difficulty]
        self.fall_speed    = FALL_SPEED[self.difficulty]
        self.spawn_rate    = SPAWN_RATE[self.difficulty]
        self.duration      = DURATION[self.difficulty]

        self._init_fatigue()
        start_music()
        self._reset()
        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        self._state     = {"tilt_x": 0.0}
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4
        self._font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 28)

    def _reset(self):
        self.objects     = []
        self.score       = 0
        self.misses      = 0
        self.reps        = 0
        self.spawn_timer = 0.0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.catcher_x   = float(GAME_W // 2)

    def _normalize_tilt(self, raw):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin: return 0.5
        return max(0.0, min(1.0, (raw - wmin) / (wmax - wmin)))

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
            self.paused = True; self.pause_sel = 0

    def update(self, dt):
        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused: return

        self.time_left -= dt
        if self.time_left <= 0:
            self._end_game(); return

        if input_handler.connected:
            tilt_norm = self._normalize_tilt(self._state["tilt_x"])
            self.catcher_x = CATCHER_W//2 + tilt_norm * (GAME_W - CATCHER_W)
        else:
            tx = self._state["tilt_x"]
            if abs(tx) > 0.1:
                self.catcher_x += self.catcher_speed * dt * tx
        self.catcher_x = max(CATCHER_W//2, min(GAME_W - CATCHER_W//2, self.catcher_x))

        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_rate:
            self.spawn_timer = 0.0
            T = get_theme()
            colors = [T["ACCENT"], T["ACCENT2"], T["GREEN"], T["YELLOW"], T["RED"], T["ORANGE"]]
            self.objects.append(FallingObject(self.fall_speed, colors))

        caught, missed = [], []
        for obj in self.objects:
            obj.update(dt)
            if (obj.y + obj.r >= CATCHER_Y and
                    abs(obj.x - self.catcher_x) < CATCHER_W//2 + obj.r):
                caught.append(obj)
            elif obj.y > GAME_H + 40:
                missed.append(obj)

        self.score  += len(caught)
        self.reps   += len(caught)
        self.misses += len(missed)
        self.objects = [o for o in self.objects if o not in caught and o not in missed]

    def _exit_to_menu(self):
        stop_music()
        self.manager.go_to("exercise_menu",
                           account_id=self.account_id, account=self.account)

    def _end_game(self):
        stop_music()
        duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="gravity_catch",
            difficulty=self.difficulty, score=self.score,
            reps=self.reps, duration_sec=duration,
            max_score=None, back_screen="game_select")

    def draw(self, surface):
        T        = get_theme()
        font_hud = self._font_hud
        font_sm  = self._font_sm

        surface.fill(T["BG"])
        for gx in range(0, GAME_W + 1, 160):
            pygame.draw.line(surface, T["PANEL"], (gx, 0), (gx, GAME_H), 1)

        for obj in self.objects:
            obj.draw(surface, T["WHITE"])

        cx = int(self.catcher_x)
        pygame.draw.rect(surface, T["ACCENT"],
                         (cx - CATCHER_W//2, CATCHER_Y, CATCHER_W, 22), border_radius=8)
        pygame.draw.rect(surface, T["ACCENT2"],
                         (cx - CATCHER_W//2, CATCHER_Y, CATCHER_W, 22), 3, border_radius=8)

        tilt_norm = self._normalize_tilt(self._state.get("tilt_x", 0.0))
        ind_x = int(100 + tilt_norm * (GAME_W - 200))
        pygame.draw.rect(surface, T["PANEL"], (100, GAME_H - 60, GAME_W - 200, 16), border_radius=6)
        pygame.draw.circle(surface, T["ACCENT"], (ind_x, GAME_H - 52), 12)

        surface.blit(font_hud.render(f"Caught: {self.score}", True, T["ACCENT"]), (40, 30))
        surface.blit(font_hud.render(f"Time: {max(0, int(self.time_left))}s", True, T["TEXT"]),
                     (GAME_W - 280, 30))
        surface.blit(font_sm.render(f"Missed: {self.misses}", True, T["RED"]),
                     (GAME_W//2 - 80, 34))
        surface.blit(font_sm.render("Tilt wrist LEFT/RIGHT to move basket  ESC=Pause",
                                    True, T["GRAY"]), (40, GAME_H - 90))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)
