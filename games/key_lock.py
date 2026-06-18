"""
Key & Lock — Wrist Rotation game (1920x1080)

Mechanic:
  - A key on screen rotates with the patient's wrist (MPU6050 tilt_x)
  - A lock shows the TARGET angle
  - Patient rotates wrist to align key with lock within tolerance
  - Hold alignment for 0.5s → lock opens → next lock appears
  - Runs for the configured session duration, then shows results

Difficulty:
  EASY   — Greenhouse Gate: static lock, ±15° tolerance, color matching hint
  MEDIUM — Library Cabinet: sequence of 3 locks in order, ±8° tolerance
  HARD   — The Clockmaker: lock wobbles/drifts, ±3° tolerance, only unlock when green

Low-pass filter applied to wrist angle to smooth tremors.
"""

import pygame
import math
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, start_music, stop_music, play_completion, play_click
from constants import get_theme, GAME_W, GAME_H

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
        self._patient   = data.get("patient")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.tolerance = TOLERANCE[self.difficulty]

        dur = data.get("duration_sec")
        self.duration = int(dur) if dur else DURATION[self.difficulty]

        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4

        self._pause_btn_rect     = pygame.Rect(GAME_W - 90, 13, 70, 46)
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)
        self._font_key = pygame.font.SysFont("monospace", 22, bold=True)

        # Low-pass filter state
        self._smooth_angle = 0.0
        self._lp_alpha     = 0.15
        self._state        = {"tilt_x": 0.0}

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    def _reset(self):
        self.game_over          = False
        self.game_over_duration = 0
        self.paused      = False
        self.pause_sel   = 0
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

        state = input_handler.get_state()
        self._state = state
        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused: return

        self.time_left -= dt
        if self.time_left <= 0:
            self._end_game(); return

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
        self.reps += 1
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
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id   = patient_id,
                therapist_id = self.account_id,
                game         = "Key and Lock",
                score        = self.reps,
                duration_sec = self.game_over_duration,
                difficulty   = self.difficulty,
            )
        except Exception:
            pass
        self.game_over = True

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
                "A lock shows a TARGET angle — rotate your wrist to match it.",
                "Hold the alignment briefly to unlock, then the next lock appears.",
            ]),
            ("CONTROLS", [
                "Rotate wrist LEFT / RIGHT to turn the key.",
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

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W//2 - msg.get_width()//2, CENTER_Y - 300))

        surface.blit(font_sm.render(
            "← → Rotate wrist to align with TARGET",
            True, T["GRAY"]), (GAME_W//2 - 280, GAME_H - 110))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

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

    def _draw_results(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        mw, mh = 640, 360
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

        mins, secs = divmod(self.game_over_duration, 60)
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, T["TEXT"])
        surface.blit(du_s, du_s.get_rect(midleft=(mx + 80, my + 150)))

        dif_s = f_sm.render(f"Difficulty: {self.difficulty}", True, T["GRAY"])
        surface.blit(dif_s, dif_s.get_rect(midleft=(mx + 80, my + 198)))

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
