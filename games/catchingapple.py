"""
Apple Catching — Wrist Rotation game (1920x1080)

Mechanic:
  - Apples fall from the top of the screen
  - tilt_x (wrist left/right rotation) moves the basket
  - Catch the apple in the basket to score
  - Runs for the configured session duration, then shows results
"""

import os
import pygame
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import start_music, stop_music, play_completion, play_click
from constants import get_theme, GAME_W, GAME_H

APPLE_SPEED  = {"Easy": 260, "Medium": 380, "Hard": 520}
MOVE_SPEED   = {"Easy": 750, "Medium": 900, "Hard": 1050}
DURATION     = {"Easy": 60,  "Medium": 50,  "Hard": 40}

BASKET_SIZE = (200, 200)
APPLE_SIZE  = (100, 100)
BLAST_SIZE  = (160, 160)
TOAST_SIZE  = (340, 140)

SHAKE_DURATION = 0.30
BLAST_DURATION = 0.15
TOAST_DURATION = 0.80

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_image(name, size):
    path = os.path.join(_ROOT, "assets", "images", name)
    return pygame.transform.scale(pygame.image.load(path), size)


def _load_sound(name):
    try:
        return pygame.mixer.Sound(os.path.join(_ROOT, "assets", "audio", name))
    except Exception:
        return None


class AppleCatchingGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.apple_speed = APPLE_SPEED[self.difficulty]
        self.move_speed  = MOVE_SPEED[self.difficulty]

        dur = data.get("duration_sec")
        self.duration = int(dur) if dur else DURATION[self.difficulty]

        self._basket_img = _load_image("basket.png", BASKET_SIZE)
        self._apple_img  = _load_image("apple.png", APPLE_SIZE)
        self._blast_img  = _load_image("blast.png", BLAST_SIZE)
        self._toast_bg   = _load_image("cloud_message.png", TOAST_SIZE)

        self._catch_sound = _load_sound("catch_sound_effect.wav")
        self._blast_sound = _load_sound("blast_sound.wav")

        font_path = os.path.join(_ROOT, "assets", "font", "Fredoka-Regular.ttf")
        self._font_toast = pygame.font.Font(font_path, 34)
        self._font_toast.set_bold(True)
        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)

        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4

        self._pause_btn_rect     = pygame.Rect(GAME_W - 90, 13, 70, 46)
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    def _reset(self):
        self.game_over          = False
        self.game_over_score    = 0
        self.game_over_duration = 0
        self.paused      = False
        self.pause_sel   = 0
        self.score       = 0
        self.reps        = 0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.basket_x    = float(GAME_W // 2)
        self._spawn_apple()

        self.blast_active = False
        self.blast_timer  = 0.0
        self.blast_pos    = (0, 0)

        self.toast_active = False
        self.toast_timer   = 0.0

        self.shaking      = False
        self.shake_timer   = 0.0
        self.shake_offset = 0

        self._state = {"tilt_x": 0.0}

    def _spawn_apple(self):
        self.apple_x = float(random.randint(0, GAME_W - APPLE_SIZE[0]))
        self.apple_y = -float(APPLE_SIZE[1])

    def _normalize_tilt(self, raw):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return 0.0
        norm = (raw - wmin) / (wmax - wmin)
        return max(-1.0, min(1.0, (norm - 0.5) * 2.0))

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music()
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music()
                elif self._results_exit_rect.collidepoint(event.pos):
                    play_click()
                    self._exit_to_game_config()
            return

        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"): self._resume_fatigue()
            return
        if self.paused:
            self._pause_handle(event)
            return
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._pause_btn_rect.collidepoint(event.pos)):
            self.paused = True
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True; self.pause_sel = 0

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
            lambda: (self._reset(), start_music()),
            lambda: setattr(self, "vol_active", True),
            self._exit_to_game_config,
        ]
        for i, action in enumerate(opts_actions):
            oy = GAME_H // 2 - 160 + i * 96
            if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                play_click()
                action()
                return

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

        if input_handler.connected:
            tilt_norm = self._normalize_tilt(self._state["tilt_x"])
            self.basket_x += self.move_speed * dt * tilt_norm
        else:
            tx = self._state["tilt_x"]
            if abs(tx) > 0.1:
                self.basket_x += self.move_speed * dt * tx
        self.basket_x = max(BASKET_SIZE[0]//2,
                             min(GAME_W - BASKET_SIZE[0]//2, self.basket_x))

        self.apple_y += self.apple_speed * dt

        basket_rect = pygame.Rect(0, 0, BASKET_SIZE[0], BASKET_SIZE[1])
        basket_rect.centerx = int(self.basket_x)
        basket_rect.bottom  = GAME_H - 40
        apple_rect = pygame.Rect(int(self.apple_x), int(self.apple_y), *APPLE_SIZE)

        if basket_rect.colliderect(apple_rect):
            self.score += 1
            self.reps  += 1
            self.toast_active = True
            self.toast_timer  = TOAST_DURATION
            if self._catch_sound: self._catch_sound.play()
            self._spawn_apple()
        elif self.apple_y > GAME_H:
            missed_x = self.apple_x
            self._spawn_apple()

            self.blast_pos = (missed_x - (BLAST_SIZE[0] - APPLE_SIZE[0]) // 2,
                               GAME_H - BLAST_SIZE[1])
            self.blast_active = True
            self.blast_timer  = BLAST_DURATION
            if self._blast_sound: self._blast_sound.play()

            self.shaking     = True
            self.shake_timer = SHAKE_DURATION

        if self.shaking:
            self.shake_timer -= dt
            if self.shake_timer > 0:
                self.shake_offset = random.randint(-6, 6)
            else:
                self.shaking      = False
                self.shake_offset = 0

        if self.blast_active:
            self.blast_timer -= dt
            if self.blast_timer <= 0:
                self.blast_active = False

        if self.toast_active:
            self.toast_timer -= dt
            if self.toast_timer <= 0:
                self.toast_active = False

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
                game         = "Apple Catching",
                score        = self.score,
                duration_sec = self.game_over_duration,
                difficulty   = self.difficulty,
            )
        except Exception:
            pass
        self.game_over = True

    def draw(self, surface):
        T = get_theme()
        surface.fill(T["BG"])
        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)
        for x in range(0, GAME_W, 80):
            pygame.draw.line(surface, T["PANEL"], (x, 0), (x, GAME_H), 1)

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        font_hud = self._font_hud
        font_sm  = self._font_sm

        surface.blit(self._apple_img, (int(self.apple_x), int(self.apple_y)))

        basket_x = int(self.basket_x) - BASKET_SIZE[0] // 2 + self.shake_offset
        basket_y = GAME_H - 40 - BASKET_SIZE[1]
        surface.blit(self._basket_img, (basket_x, basket_y))

        if self.blast_active:
            surface.blit(self._blast_img, self.blast_pos)

        if self.toast_active:
            self._draw_toast(surface, basket_x + BASKET_SIZE[0] // 2, basket_y)

        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)
        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        surface.blit(font_hud.render(
            f"APPLE CATCHING  ·  {self.difficulty.upper()}", True, diff_col), (80, 18))
        surface.blit(font_hud.render(
            f"Score: {self.score:02d}", True, T["ACCENT"]),
            (GAME_W // 2 - 80, 18))
        time_col = T["RED"] if self.time_left < 10 else T["TEXT"]
        time_s = font_hud.render(f"{max(0, int(self.time_left)):02d}s", True, time_col)
        surface.blit(time_s, time_s.get_rect(right=self._pause_btn_rect.left - 24, y=18))

        # Pause button — two solid bars
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

        surface.blit(font_sm.render(
            "Tilt wrist LEFT/RIGHT to move basket",
            True, T["GRAY"]), (GAME_W // 2 - 220, GAME_H - 50))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 860, 540
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (252,), (0, 0, pw, ph), border_radius=16)
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, T["ACCENT"], pygame.Rect(px, py, pw, ph), 2, border_radius=16)

        f_title = pygame.font.SysFont("monospace", 36, bold=True)
        f_head  = pygame.font.SysFont("monospace", 22, bold=True)
        f_body  = pygame.font.SysFont("monospace", 19)
        f_hint  = pygame.font.SysFont("monospace", 21, bold=True)

        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        title = f_title.render("How to Play", True, diff_col)
        surface.blit(title, title.get_rect(centerx=GAME_W // 2, top=py + 26))
        pygame.draw.line(surface, T["ACCENT"], (px + 40, py + 78), (px + pw - 40, py + 78), 1)

        y = py + 96
        for header, lines in [
            ("OBJECTIVE", [
                "Apples fall from the top of the screen.",
                "Move the basket underneath to catch them and score.",
            ]),
            ("CONTROLS", [
                "Tilt wrist LEFT / RIGHT to move the basket.",
            ]),
            ("THIS SESSION", [
                f"Duration:   {self.duration} seconds",
                f"Difficulty: {self.difficulty}",
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

    def _draw_toast(self, surface, basket_centerx, basket_top):
        label = self._font_toast.render("Nice Catch +1", True, (0, 0, 0))
        panel_x = basket_centerx - TOAST_SIZE[0] // 2
        panel_y = basket_top - TOAST_SIZE[1] - 10
        surface.blit(self._toast_bg, (panel_x, panel_y))
        text_x = panel_x + (TOAST_SIZE[0] - label.get_width()) // 2
        text_y = panel_y + (TOAST_SIZE[1] - label.get_height()) // 2
        surface.blit(label, (text_x, text_y))

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
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
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
