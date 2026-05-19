"""
Piano Tiles — Finger Flexion game (1920x1080)
5 lanes mapped to 5 fingers (A S D F G keys / arcade buttons).
Tiles fall from top; press the matching key when tile reaches the hit zone.
"""

import pygame
import random
import os
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import *

BASE_SPEED  = {"Easy": 280, "Medium": 420, "Hard": 580}
BASE_SPAWN  = {"Easy": 1.0, "Medium": 0.7, "Hard": 0.45}
FINGER_KEYS = [pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f, pygame.K_g]
LANE_LABELS = ["A", "S", "D", "F", "G"]
LANE_COLORS = [(255,80,120),(0,210,255),(180,0,255),(0,255,160),(255,200,0)]

LANE_COUNT = 5
LANE_W     = GAME_W // LANE_COUNT
HIT_Y      = GAME_H - 180
TILE_H     = 100

_FD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "font")
def _F(n): return os.path.join(_FD, n)


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
        self.patient    = data.get("patient", {})
        self.exercise   = "finger"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        # Duration from Start Session settings (issue 6)
        self.duration   = data.get("duration_sec", 60)
        self.speed      = BASE_SPEED.get(self.difficulty, 420)
        self.spawn_rate = BASE_SPAWN.get(self.difficulty, 0.7)

        self._init_fatigue()

        # Fonts
        H = GAME_H
        self.fnt_hud   = pygame.font.Font(_F("Lexend-SemiBold.ttf"), int(34 * H / 1080))
        self.fnt_title = pygame.font.Font(_F("FjallaOne-Regular.ttf"), int(52 * H / 1080))
        self.fnt_body  = pygame.font.Font(_F("Lexend-Regular.ttf"),   int(26 * H / 1080))
        self.fnt_btn   = pygame.font.Font(_F("Lexend-SemiBold.ttf"),  int(30 * H / 1080))
        self.fnt_key   = pygame.font.Font(_F("ZenDots-Regular.ttf"),  int(38 * H / 1080))
        self.fnt_big   = pygame.font.Font(_F("GravitasOne-Regular.ttf"), int(80 * H / 1080))

        # Interaction rects (set during draw, used in handle_event)
        self.howto_start_rect    = pygame.Rect(0, 0, 1, 1)
        self.pause_btn_rect      = pygame.Rect(0, 0, 1, 1)
        self.pause_menu_rects    = {}   # {"Resume": Rect, ...}
        self.complete_done_rect  = pygame.Rect(0, 0, 1, 1)

        self.phase   = "howto"   # howto → playing → complete
        self.paused  = False
        self._reset()

    # ── state ──────────────────────────────────────────────────────────

    def _reset(self):
        self.tiles       = []
        self.score       = 0
        self.reps        = 0
        self.spawn_timer = 0.0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.flash       = {}

    def _start_game(self):
        self._reset()
        self.phase  = "playing"
        self.paused = False
        start_music()

    # ── events ─────────────────────────────────────────────────────────

    def handle_event(self, event):
        # Fatigue break — any action resumes (keep for accessibility)
        if self.fatigue_paused:
            if (event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN)
                    or (event.type == pygame.KEYDOWN
                        and event.key in (pygame.K_RETURN, pygame.K_SPACE))):
                self._resume_fatigue()
            return

        pos = self._event_pos(event)

        # How To Play screen — click/touch "Start Game"
        if self.phase == "howto":
            if pos and self.howto_start_rect.collidepoint(pos):
                self._start_game()
            return

        # Session Complete — click/touch "Done"
        if self.phase == "complete":
            if pos and self.complete_done_rect.collidepoint(pos):
                self._end_game()
            return

        # Pause menu — click/touch buttons (issue 7: mouse/touch only)
        if self.paused:
            if pos:
                if self.pause_menu_rects.get("Resume", pygame.Rect(0,0,1,1)).collidepoint(pos):
                    self.paused = False
                elif self.pause_menu_rects.get("Restart", pygame.Rect(0,0,1,1)).collidepoint(pos):
                    self._start_game()
                elif self.pause_menu_rects.get("Exit", pygame.Rect(0,0,1,1)).collidepoint(pos):
                    stop_music()
                    self._end_game()
            return

        # Playing phase
        if self.phase == "playing":
            # Pause button click (issue 5)
            if pos and self.pause_btn_rect.collidepoint(pos):
                self.paused = True
                return

            # Game controls — A S D F G keys (these remain keyboard, issue 7 exception)
            if event.type == pygame.KEYDOWN and event.key in FINGER_KEYS:
                self._hit_lane(FINGER_KEYS.index(event.key))

    def _event_pos(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            import builtins
            norm = getattr(builtins, "normalise_pos", lambda p: p)
            return norm(event.pos)
        if event.type == pygame.FINGERDOWN:
            return (int(event.x * GAME_W), int(event.y * GAME_H))
        return None

    # ── hit detection ──────────────────────────────────────────────────

    def _hit_lane(self, lane):
        self.flash[lane] = 0.15
        for tile in self.tiles:
            if tile.lane == lane and not tile.hit and not tile.miss:
                if HIT_Y - 80 < tile.y + TILE_H < HIT_Y + 80:
                    tile.hit   = True
                    self.score += 1
                    self.reps  += 1
                    play_success()   # issue 3
                    return

    # ── update ─────────────────────────────────────────────────────────

    def update(self, dt):
        if self.phase != "playing":
            return

        state = input_handler.get_state()

        for i, pressed in enumerate(state["fingers"]):
            if pressed:
                self._hit_lane(i)

        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0:
            stop_music()
            self.phase = "complete"
            return

        # Adaptive spawn
        bonus = (self.score // 10) * 0.05
        effective_spawn = max(0.25, self.spawn_rate - bonus)
        self.spawn_timer += dt
        if self.spawn_timer >= effective_spawn:
            self.spawn_timer = 0.0
            self.tiles.append(Tile(random.randint(0, 4), self.speed))

        # Update tiles; fire error sound on any new misses (issue 3)
        any_miss = False
        for tile in self.tiles:
            tile.update(dt)
            if tile.miss:
                any_miss = True
        if any_miss:
            play_error()

        self.tiles = [t for t in self.tiles if not t.hit and not t.miss]

        for lane in list(self.flash):
            self.flash[lane] -= dt
            if self.flash[lane] <= 0:
                del self.flash[lane]

    def _end_game(self):
        stop_music()
        elapsed = (pygame.time.get_ticks() - self.start_time) // 1000
        self.manager.go_to("endgame",
            account_id=self.account_id, account=self.account,
            exercise=self.exercise, game="piano_tiles",
            difficulty=self.difficulty, score=self.score,
            reps=self.reps, duration_sec=elapsed,
            max_score=None, back_screen="game_select")

    # ── draw ───────────────────────────────────────────────────────────

    def draw(self, surface):
        if self.phase == "howto":
            self._draw_howto(surface)
            return

        self._draw_lanes(surface)
        self._draw_hud(surface)

        if self.phase == "complete":
            self._draw_session_complete(surface)
        elif self.paused:
            self._draw_pause(surface)
        else:
            self._draw_fatigue_overlay(surface)

    # ── lane / tile background ─────────────────────────────────────────

    def _draw_lanes(self, surface):
        for i in range(LANE_COUNT):
            lx = i * LANE_W
            pygame.draw.rect(surface, PANEL, (lx, 0, LANE_W - 2, GAME_H))
            hz_color = LANE_COLORS[i] if i in self.flash else GRAY
            pygame.draw.rect(surface, hz_color,
                             (lx + 8, HIT_Y, LANE_W - 16, 20), border_radius=6)
            lbl = self.fnt_key.render(LANE_LABELS[i], True, LANE_COLORS[i])
            surface.blit(lbl, (lx + LANE_W // 2 - lbl.get_width() // 2, HIT_Y + 30))

        for tile in self.tiles:
            tile.draw(surface)

    # ── HUD (score + timer + pause button) ────────────────────────────

    def _draw_hud(self, surface):
        pygame.draw.rect(surface, (0, 0, 0), pygame.Rect(0, 0, GAME_W, 70))

        # Score (no goals — issue 2)
        sc = self.fnt_hud.render(f"Score: {self.score}", True, ACCENT)
        surface.blit(sc, (40, 18))

        # Timer
        tm = self.fnt_hud.render(f"{max(0, int(self.time_left))}s", True, TEXT)
        surface.blit(tm, (GAME_W // 2 - tm.get_width() // 2, 18))

        # Pause button (issue 5) — "||" symbol top-right
        pbw, pbh = 60, 44
        pbx = GAME_W - pbw - 20
        pby = 13
        pb_r = pygame.Rect(pbx, pby, pbw, pbh)
        pygame.draw.rect(surface, (60, 70, 90), pb_r, border_radius=8)
        pygame.draw.rect(surface, (120, 140, 170), pb_r, 2, border_radius=8)
        ps = self.fnt_hud.render("||", True, (200, 215, 235))
        surface.blit(ps, ps.get_rect(center=pb_r.center))
        self.pause_btn_rect = pb_r

    # ── How To Play (issue 1) ──────────────────────────────────────────

    def _draw_howto(self, surface):
        surface.fill((18, 22, 36))

        cx = GAME_W // 2

        # Title
        title = self.fnt_title.render("How To Play", True, (130, 190, 255))
        surface.blit(title, title.get_rect(midtop=(cx, 40)))

        pygame.draw.line(surface, (55, 75, 115),
                         (cx - 420, 110), (cx + 420, 110), 1)

        sections = [
            ("Objective",
             ["Hit the falling tiles by pressing the matching lane key.",
              "Score as many hits as possible before time runs out."]),
            ("Controls",
             ["A · S · D · F · G  — press the key matching the lane",
              "                       when the tile reaches the hit zone."]),
            ("This Session",
             [f"Difficulty : {self.difficulty}",
              f"Duration   : {int(self.duration)} seconds",
              f"Speed      : {BASE_SPEED.get(self.difficulty, 420)} px/s"]),
        ]

        y = 130
        for heading, lines in sections:
            h_s = self.fnt_btn.render(heading, True, ACCENT)
            surface.blit(h_s, (cx - 420, y))
            y += h_s.get_height() + 8
            for line in lines:
                ls = self.fnt_body.render(line, True, (190, 210, 240))
                surface.blit(ls, (cx - 400, y))
                y += ls.get_height() + 6
            y += 22

        # Start button
        bw, bh = 280, 64
        btn_r = pygame.Rect(cx - bw // 2, GAME_H - 110, bw, bh)
        pygame.draw.rect(surface, (40, 160, 80), btn_r, border_radius=16)
        pygame.draw.rect(surface, (70, 210, 120), btn_r, 2, border_radius=16)
        bs = self.fnt_btn.render("Start Game", True, WHITE)
        surface.blit(bs, bs.get_rect(center=btn_r.center))
        self.howto_start_rect = btn_r

    # ── Pause menu (issue 5 — mouse/touch buttons, issue 7) ───────────

    def _draw_pause(self, surface):
        overlay = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        surface.blit(overlay, (0, 0))

        cx = GAME_W // 2
        title = self.fnt_title.render("Paused", True, WHITE)
        surface.blit(title, title.get_rect(midtop=(cx, GAME_H // 2 - 160)))

        options = ["Resume", "Restart", "Exit"]
        colors  = [(40, 160, 220), (180, 130, 30), (190, 50, 50)]
        self.pause_menu_rects = {}
        bw, bh = 240, 58
        for i, (opt, col) in enumerate(zip(options, colors)):
            r = pygame.Rect(cx - bw // 2, GAME_H // 2 - 60 + i * 80, bw, bh)
            pygame.draw.rect(surface, col, r, border_radius=14)
            ls = self.fnt_btn.render(opt, True, WHITE)
            surface.blit(ls, ls.get_rect(center=r.center))
            self.pause_menu_rects[opt] = r

    # ── Session Complete (issue 4) ─────────────────────────────────────

    def _draw_session_complete(self, surface):
        overlay = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        overlay.fill((10, 14, 26, 210))
        surface.blit(overlay, (0, 0))

        cx  = GAME_W // 2
        mw, mh = 640, 420
        mr = pygame.Rect(cx - mw // 2, GAME_H // 2 - mh // 2, mw, mh)
        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(bg, (28, 36, 58, 245), (0, 0, mw, mh), border_radius=20)
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, (60, 140, 220), mr, 2, border_radius=20)

        title = self.fnt_title.render("Session Complete!", True, (130, 200, 255))
        surface.blit(title, title.get_rect(midtop=(cx, mr.y + 28)))

        elapsed = max(1, (pygame.time.get_ticks() - self.start_time) // 1000)
        rows = [
            ("Score",      str(self.score)),
            ("Duration",   f"{elapsed}s"),
            ("Difficulty", self.difficulty),
        ]
        ry = mr.y + 110
        for label, val in rows:
            ls = self.fnt_body.render(label, True, (140, 165, 200))
            vs = self.fnt_btn.render(val, True, WHITE)
            surface.blit(ls, (mr.x + 60, ry))
            surface.blit(vs, (mr.right - 60 - vs.get_width(), ry))
            pygame.draw.line(surface, (45, 60, 90),
                             (mr.x + 40, ry + ls.get_height() + 4),
                             (mr.right - 40, ry + ls.get_height() + 4), 1)
            ry += 68

        bw, bh = 240, 58
        done_r = pygame.Rect(cx - bw // 2, mr.bottom - 82, bw, bh)
        pygame.draw.rect(surface, (40, 160, 80), done_r, border_radius=14)
        ds = self.fnt_btn.render("Done", True, WHITE)
        surface.blit(ds, ds.get_rect(center=done_r.center))
        self.complete_done_rect = done_r
