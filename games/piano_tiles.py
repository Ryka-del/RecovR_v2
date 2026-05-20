"""
Piano Tiles — Finger Flexion game (1920x1080)
5 lanes mapped to 5 fingers (A S D F G keys / arcade buttons).
Tiles fall from top; press the matching key when tile reaches the hit zone.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, play_completion, start_music, stop_music, game_music_path, play_click
from constants import get_theme, GAME_W, GAME_H

BASE_SPEED  = {"Easy": 280, "Medium": 420, "Hard": 580}
BASE_SPAWN  = {"Easy": 1.0, "Medium": 0.7, "Hard": 0.45}
FINGER_KEYS = [pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_f, pygame.K_g]
LANE_LABELS = ["A", "S", "D", "F", "G"]
LANE_COLORS = [(255,80,120),(0,210,255),(180,0,255),(0,255,160),(255,200,0)]

LANE_COUNT = 5
LANE_W     = GAME_W // LANE_COUNT
HIT_Y      = GAME_H - 180
TILE_H     = 100


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
        T = get_theme()
        color = LANE_COLORS[self.lane]
        rect  = pygame.Rect(self.x + 8, int(self.y), LANE_W - 16, TILE_H)
        pygame.draw.rect(surface, color, rect, border_radius=12)
        pygame.draw.rect(surface, T["WHITE"], rect, 3, border_radius=12)


class PianoTilesGame(FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "finger"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        dur = data.get("duration_sec")
        self.duration  = int(dur) if dur else 60

        # Tile fall speed from Session Details speed setting
        _spd_map   = {"Slow": 280, "Normal": 420, "Fast": 580}
        self.speed = _spd_map.get(data.get("speed", "Normal"), 420)

        # Spawn rate from calibration difficulty
        cal_diff        = ((data.get("calibration") or {})
                           .get("params", {}).get("difficulty", self.difficulty))
        _spawn_map      = {"Easy": 1.0, "Medium": 0.7, "Hard": 0.45}
        self.spawn_rate = _spawn_map.get(cal_diff, 0.7)

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        self.pause_vol  = 0.4
        self._pause_btn_rect = pygame.Rect(GAME_W - 90, 13, 70, 46)

        self._font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 26)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    # ── state ──────────────────────────────────────────────────────────

    def _reset(self):
        self.game_over   = False
        self.tiles       = []
        self.score       = 0
        self.reps        = 0
        self.spawn_timer = 0.0
        self.time_left       = float(self.duration)
        self.start_time      = pygame.time.get_ticks()
        self.flash           = {}
        self._pre_complete   = False
        self._pre_complete_t = 0.0

    # ── events ─────────────────────────────────────────────────────────

    def handle_event(self, event):
        # How To Play — any key or click dismisses
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    event.type == pygame.FINGERDOWN or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_music_path("Piano Tiles", self.difficulty))
            return

        # Results screen — mouse click on buttons
        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(game_music_path("Piano Tiles", self.difficulty))
                elif self._results_exit_rect.collidepoint(event.pos):
                    play_click()
                    self._exit_to_game_config()
            elif event.type == pygame.FINGERDOWN:
                pos = (int(event.x * GAME_W), int(event.y * GAME_H))
                if self._results_again_rect.collidepoint(pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(game_music_path("Piano Tiles", self.difficulty))
                elif self._results_exit_rect.collidepoint(pos):
                    play_click()
                    self._exit_to_game_config()
            return

        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"):
                self._resume_fatigue()
            return

        if self.paused:
            self._pause_handle(event)
            return

        # Pause button (mouse click)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._pause_btn_rect.collidepoint(event.pos):
                self.paused = True
                return
        if event.type == pygame.FINGERDOWN:
            pos = (int(event.x * GAME_W), int(event.y * GAME_H))
            if self._pause_btn_rect.collidepoint(pos):
                self.paused = True
                return

        # Game controls — A S D F G keys
        if event.type == pygame.KEYDOWN and event.key in FINGER_KEYS:
            self._hit_lane(FINGER_KEYS.index(event.key))

    def _pause_handle(self, event):
        pos = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
        elif event.type == pygame.FINGERDOWN:
            pos = (int(event.x * GAME_W), int(event.y * GAME_H))
        if pos is None:
            return
        if self.vol_active:
            _bx = GAME_W // 2 - (10*30 + 9*6) // 2
            _by = GAME_H // 2 - 160 + 2 * 96 + 52
            for si in range(10):
                sx = _bx + si * (30 + 6)
                if pygame.Rect(sx, _by - 8, 30, 44).collidepoint(pos):
                    self.pause_vol = (si + 1) / 10
                    self._apply_vol()
                    return
            self.vol_active = False
            return
        opts_actions = [
            lambda: setattr(self, "paused", False),
            lambda: (self._reset(), setattr(self, "_show_instructions", False),
                     setattr(self, "paused", False),
                     start_music(game_music_path("Piano Tiles", self.difficulty))),
            lambda: setattr(self, "vol_active", True),
            self._exit_to_game_config,
        ]
        for i, action in enumerate(opts_actions):
            oy = GAME_H // 2 - 160 + i * 96
            if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                play_click()
                action()
                return

    # ── hit detection ──────────────────────────────────────────────────

    def _hit_lane(self, lane):
        self.flash[lane] = 0.15
        for tile in self.tiles:
            if tile.lane == lane and not tile.hit and not tile.miss:
                if HIT_Y - 80 < tile.y + TILE_H < HIT_Y + 80:
                    tile.hit   = True
                    self.score += 1
                    self.reps  += 1
                    play_success()
                    return

    # ── update ─────────────────────────────────────────────────────────

    def update(self, dt):
        if self._show_instructions or self.game_over:
            return

        state = input_handler.get_state()

        for i, pressed in enumerate(state["fingers"]):
            if pressed:
                self._hit_lane(i)

        # Keyboard presses count as activity so Take a Break doesn't trigger mid-game
        keys = pygame.key.get_pressed()
        if any(keys[k] for k in FINGER_KEYS):
            self.fatigue_timer = 0.0

        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0.0
            if not self._pre_complete:
                self._pre_complete   = True
                self._pre_complete_t = 0.8
                pygame.mixer.music.fadeout(800)
            else:
                self._pre_complete_t -= dt
                if self._pre_complete_t <= 0:
                    self._end_game()
            return

        # Adaptive spawn rate
        bonus = (self.score // 10) * 0.05
        effective_spawn = max(0.25, self.spawn_rate - bonus)
        self.spawn_timer += dt
        if self.spawn_timer >= effective_spawn:
            self.spawn_timer = 0.0
            self.tiles.append(Tile(random.randint(0, 4), self.speed))

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

    # ── game end ───────────────────────────────────────────────────────

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
        play_completion()
        self.game_over_duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.game_over_score    = self.score
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id   = patient_id,
                therapist_id = self.account_id,
                game         = "Piano Tiles",
                score        = self.score,
                duration_sec = self.game_over_duration,
                difficulty   = self.difficulty,
            )
        except Exception:
            pass
        self.game_over = True

    # ── draw ───────────────────────────────────────────────────────────

    def draw(self, surface):
        T = get_theme()
        surface.fill(T["BG"])

        # Background grid (matches other games)
        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        # Lane backgrounds + hit zones + key labels
        for i in range(LANE_COUNT):
            lx = i * LANE_W
            col = (*LANE_COLORS[i], 28)
            lane_surf = pygame.Surface((LANE_W - 2, GAME_H), pygame.SRCALPHA)
            lane_surf.fill(col)
            surface.blit(lane_surf, (lx, 0))
            pygame.draw.line(surface, T["PANEL"], (lx + LANE_W - 1, 0),
                             (lx + LANE_W - 1, GAME_H), 1)
            hz_color = LANE_COLORS[i] if i in self.flash else T["GRAY"]
            pygame.draw.rect(surface, hz_color,
                             (lx + 8, HIT_Y, LANE_W - 16, 20), border_radius=6)
            font_key = pygame.font.SysFont("monospace", 40, bold=True)
            lbl = font_key.render(LANE_LABELS[i], True, LANE_COLORS[i])
            surface.blit(lbl, (lx + LANE_W // 2 - lbl.get_width() // 2, HIT_Y + 30))

        for tile in self.tiles:
            tile.draw(surface)

        # HUD bar — same style as Basketball / Steady Aim
        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)
        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}.get(
            self.difficulty, T["ACCENT"])
        surface.blit(self._font_hud.render(
            f"PIANO TILES  ·  {self.difficulty.upper()}", True, diff_col), (80, 18))
        surface.blit(self._font_hud.render(
            f"Score: {self.score:02d}", True, T["ACCENT"]),
            (GAME_W // 2 - 60, 18))
        time_col = T["RED"] if self.time_left < 10 else T["TEXT"]
        surface.blit(self._font_hud.render(
            f"{max(0, int(self.time_left)):02d}s", True, time_col),
            (GAME_W - 160, 18))

        # Pause button — two solid bars (identical to Basketball / Steady Aim)
        pb     = self._pause_btn_rect
        pb_col = T["ACCENT"]
        pygame.draw.rect(surface, (15, 20, 36), pb, border_radius=8)
        pygame.draw.rect(surface, pb_col, pb, 2, border_radius=8)
        bw2, bh2 = 8, 22
        by2 = pb.top + (pb.height - bh2) // 2
        bx1 = pb.left + pb.width // 2 - bw2 - 4
        bx2 = pb.left + pb.width // 2 + 4
        pygame.draw.rect(surface, pb_col, (bx1, by2, bw2, bh2), border_radius=2)
        pygame.draw.rect(surface, pb_col, (bx2, by2, bw2, bh2), border_radius=2)

        # Bottom hint
        surface.blit(self._font_sm.render(
            "Press A S D F G when tile reaches the line",
            True, T["GRAY"]), (80, GAME_H - 44))

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    # ── How To Play (same format as Basketball / Steady Aim) ──────────

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 860, 560
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (252,), (0, 0, pw, ph), border_radius=16)
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, T["ACCENT"],
                         pygame.Rect(px, py, pw, ph), 2, border_radius=16)

        f_title = pygame.font.SysFont("monospace", 36, bold=True)
        f_head  = pygame.font.SysFont("monospace", 22, bold=True)
        f_body  = pygame.font.SysFont("monospace", 19)
        f_hint  = pygame.font.SysFont("monospace", 21, bold=True)

        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"],
                    "Hard": T["RED"]}.get(self.difficulty, T["ACCENT"])
        title = f_title.render("How to Play", True, diff_col)
        surface.blit(title, title.get_rect(centerx=GAME_W // 2, top=py + 26))
        pygame.draw.line(surface, T["ACCENT"],
                         (px + 40, py + 78), (px + pw - 40, py + 78), 1)

        y = py + 96
        for header, lines in [
            ("OBJECTIVE", [
                "Tiles fall from the top — hit each one as it reaches the line.",
                "Press the matching lane key to score a hit.",
            ]),
            ("CONTROLS", [
                "A  S  D  F  G  — press the key for that lane.",
                "Press when the tile overlaps the hit zone at the bottom.",
            ]),
            ("THIS SESSION", [
                f"Duration:   {int(self.duration)} seconds",
                f"Difficulty: {self.difficulty}",
                f"Speed:      {self.speed} px/s",
            ]),
        ]:
            surface.blit(f_head.render(header, True, T["ACCENT"]), (px + 48, y))
            y += 30
            for line in lines:
                surface.blit(f_body.render(line, True, T["TEXT"]), (px + 64, y))
                y += 26
            y += 14

        blink_col = (T["YELLOW"] if (pygame.time.get_ticks() // 600) % 2 == 0
                     else T["GRAY"])
        hint = f_hint.render("Press any key or click to begin", True, blink_col)
        surface.blit(hint, hint.get_rect(centerx=GAME_W // 2, bottom=py + ph - 20))

    # ── Session Complete (same format as Basketball / Steady Aim) ─────

    def _draw_results(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        mw, mh = 640, 400
        mx, my = (GAME_W - mw) // 2, (GAME_H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (245,), (0, 0, mw, mh), border_radius=16)
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, T["ACCENT"], mr, 2, border_radius=16)

        f_big = pygame.font.SysFont("monospace", 48, bold=True)
        f_mid = pygame.font.SysFont("monospace", 32, bold=True)
        f_sm  = pygame.font.SysFont("monospace", 24)
        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        title = f_big.render("Session Complete!", True, T["YELLOW"])
        surface.blit(title, title.get_rect(center=(mr.centerx, my + 60)))

        sc_s = f_mid.render(f"Score:    {self.game_over_score}", True, T["TEXT"])
        surface.blit(sc_s, sc_s.get_rect(midleft=(mx + 80, my + 140)))

        mins, secs = divmod(self.game_over_duration, 60)
        if mins and secs:
            dur_str = f"{mins}min {secs}s"
        elif mins:
            dur_str = f"{mins}min"
        else:
            dur_str = f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, T["TEXT"])
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
