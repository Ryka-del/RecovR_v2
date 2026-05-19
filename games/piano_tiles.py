"""
Piano Tiles — Finger Flexion game (1920x1080)
5 lanes across the full width, mapped to 5 fingers (A S D F G / arcade buttons).
Tiles fall from top; press the correct finger when tile reaches the hit zone.
Timed session. Score = tiles hit. Misses tracked.
Adaptive: spawn rate increases as score grows.
"""

import pygame
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import *

DURATIONS   = {"Easy": 30, "Medium": 45, "Hard": 60}
BASE_SPEED  = {"Easy": 280, "Medium": 420, "Hard": 580}
BASE_SPAWN  = {"Easy": 1.0, "Medium": 0.7, "Hard": 0.45}
FINGER_KEYS = [pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f, pygame.K_g]
LANE_LABELS = ["A", "S", "D", "F", "G"]
LANE_COLORS = [(255,80,120),(0,210,255),(180,0,255),(0,255,160),(255,200,0)]

LANE_COUNT  = 5
LANE_W      = GAME_W // LANE_COUNT   # 384px each
HIT_Y       = GAME_H - 180
TILE_H      = 100

class Tile:
    def __init__(self, lane, speed):
        self.lane  = lane
        self.y     = -TILE_H
        self.speed = speed
        self.hit   = False
        self.miss  = False

    @property
    def x(self):
        return self.lane * LANE_W

    def update(self, dt):
        self.y += self.speed * dt
        if self.y > HIT_Y + 80 and not self.hit:
            self.miss = True

    def draw(self, surface):
        if self.hit or self.miss:
            return
        color = LANE_COLORS[self.lane]
        rect  = pygame.Rect(self.x + 8, int(self.y), LANE_W - 16, TILE_H)
        pygame.draw.rect(surface, color, rect, border_radius=12)
        pygame.draw.rect(surface, WHITE, rect, 3, border_radius=12)

class PianoTilesGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self.exercise   = "finger"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.duration   = DURATIONS[self.difficulty]
        self.speed      = BASE_SPEED[self.difficulty]
        self.spawn_rate = BASE_SPAWN[self.difficulty]

        self._init_fatigue()
        start_music()
        self._reset()
        self.paused    = False
        self.pause_sel = 0

    def _reset(self):
        self.tiles       = []
        self.score       = 0
        self.misses      = 0
        self.reps        = 0
        self.spawn_timer = 0.0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.flash       = {}   # lane → timer

    def handle_event(self, event):
        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"):
                self._resume_fatigue()
            return
        if self.paused:
            if input_handler.was_pressed(event, "up"):
                self.pause_sel = max(0, self.pause_sel - 1)
            elif input_handler.was_pressed(event, "down"):
                self.pause_sel = min(2, self.pause_sel + 1)
            elif input_handler.was_pressed(event, "action"):
                if self.pause_sel == 0: self.paused = False
                elif self.pause_sel == 1: self._reset(); self.paused = False
                else: self._end_game()
            return

        if event.type == pygame.KEYDOWN:
            if event.key in FINGER_KEYS:
                self._hit_lane(FINGER_KEYS.index(event.key))
            elif event.key == pygame.K_ESCAPE:
                self.paused = True

    def _hit_lane(self, lane):
        self.flash[lane] = 0.15
        for tile in self.tiles:
            if tile.lane == lane and not tile.hit and not tile.miss:
                if HIT_Y - 80 < tile.y + TILE_H < HIT_Y + 80:
                    tile.hit = True
                    self.score += 1
                    self.reps  += 1
                    return

    def update(self, dt):
        state = input_handler.get_state()

        # Finger button polling (hardware or stub)
        for i, pressed in enumerate(state["fingers"]):
            if pressed:
                self._hit_lane(i)

        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0:
            self._end_game()
            return

        # Adaptive spawn rate: speeds up every 10 points
        bonus = (self.score // 10) * 0.05
        effective_spawn = max(0.25, self.spawn_rate - bonus)

        self.spawn_timer += dt
        if self.spawn_timer >= effective_spawn:
            self.spawn_timer = 0.0
            self.tiles.append(Tile(random.randint(0, 4), self.speed))

        miss_count = 0
        for tile in self.tiles:
            tile.update(dt)
            if tile.miss:
                miss_count += 1
        self.misses += miss_count
        self.tiles = [t for t in self.tiles if not t.hit and not t.miss]

        for lane in list(self.flash):
            self.flash[lane] -= dt
            if self.flash[lane] <= 0:
                del self.flash[lane]

    def _end_game(self):
        stop_music()
        duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="piano_tiles",
            difficulty=self.difficulty, score=self.score,
            reps=self.reps, duration_sec=duration,
            max_score=None, back_screen="game_select")

    def draw(self, surface):
        font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        font_sm  = pygame.font.SysFont("monospace", 28)
        font_key = pygame.font.SysFont("monospace", 40, bold=True)

        # Lane backgrounds
        for i in range(LANE_COUNT):
            lx = i * LANE_W
            pygame.draw.rect(surface, PANEL, (lx, 0, LANE_W - 2, GAME_H))
            # Hit zone
            hz_color = LANE_COLORS[i] if i in self.flash else GRAY
            pygame.draw.rect(surface, hz_color,
                             (lx + 8, HIT_Y, LANE_W - 16, 20), border_radius=6)
            # Key label
            lbl = font_key.render(LANE_LABELS[i], True, LANE_COLORS[i])
            surface.blit(lbl, (lx + LANE_W//2 - lbl.get_width()//2, HIT_Y + 30))

        # Tiles
        for tile in self.tiles:
            tile.draw(surface)

        # HUD overlay bar
        pygame.draw.rect(surface, (0, 0, 0, 180),
                         pygame.Rect(0, 0, GAME_W, 80))
        surface.blit(font_hud.render(f"Score: {self.score}", True, ACCENT), (40, 20))
        surface.blit(font_hud.render(f"Time: {max(0, int(self.time_left))}s", True, TEXT),
                     (GAME_W - 280, 20))
        surface.blit(font_sm.render(f"Misses: {self.misses}", True, RED), (GAME_W//2 - 80, 24))
        surface.blit(font_sm.render("Press A S D F G when tile reaches the line  ESC=Pause",
                                    True, GRAY), (40, GAME_H - 40))

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

    def _draw_pause(self, surface):
        font = pygame.font.SysFont("monospace", 44, bold=True)
        overlay = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        surface.blit(overlay, (0, 0))
        for i, opt in enumerate(["Resume", "Restart", "Exit"]):
            col = ACCENT if i == self.pause_sel else TEXT
            lbl = font.render(opt, True, col)
            surface.blit(lbl, (GAME_W//2 - lbl.get_width()//2, GAME_H//2 - 80 + i * 80))
