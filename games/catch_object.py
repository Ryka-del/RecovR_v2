"""
Catch the Falling Object — Dual Skill (Grip + Wrist) game (1920x1080)

Mechanic:
  - Objects fall from the top
  - Tilt wrist (← →) to move the catcher left/right
  - Grip (squeeze >= threshold) while an object is over the catcher to catch it
  - The red object marked with an X must NOT be caught — let it fall
"""

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, start_music, stop_music, play_completion, play_click
from constants import get_theme, GAME_W, GAME_H

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
        self.scored = False
        self.missed = False
        # Medium/Hard: some objects are invalid (red, marked X) — must not be caught
        if difficulty == "Easy":
            self.valid = True
        else:
            self.valid = random.random() > 0.3
            if not self.valid:
                self.color = (255, 60, 80)

    def update(self, dt):
        self.pulse += dt * 3
        self.y += self.speed * dt
        if self.y > GAME_H + 60:
            self.missed = True

    def draw(self, surface):
        if self.scored or self.missed:
            return
        cx, cy = int(self.x), int(self.y)
        pr = int(self.r + 4 * math.sin(self.pulse))
        pygame.draw.circle(surface, self.color, (cx, cy), pr, 3)
        pygame.draw.circle(surface, self.color, (cx, cy), self.r)
        if not self.valid:
            pygame.draw.line(surface, (255,255,255), (cx-12,cy-12),(cx+12,cy+12), 3)
            pygame.draw.line(surface, (255,255,255), (cx+12,cy-12),(cx-12,cy+12), 3)


class CatchObjectGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.threshold  = THRESHOLDS[self.difficulty]
        self.fall_speed = FALL_SPEEDS[self.difficulty]
        self.spawn_rate = SPAWN_RATES[self.difficulty]
        self.move_speed = MOVE_SPEED[self.difficulty]

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
        self._font_fb  = pygame.font.SysFont("monospace", 48, bold=True)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    def _reset(self):
        self.game_over          = False
        self.game_over_score    = 0
        self.game_over_duration = 0
        self.paused      = False
        self.pause_sel   = 0
        self.objects     = []
        self.score       = 0
        self.misses      = 0
        self.reps        = 0
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
            self.paused = True

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

        grip = self._normalize_grip(self._state["grip"])

        # Move catcher left/right with tilt_x
        tx = self._normalize_tilt(self._state["tilt_x"])
        if abs(tx) > 0.08:
            self.catcher_x += self.move_speed * dt * tx
        self.catcher_x = max(CATCHER_W//2, min(GAME_W - CATCHER_W//2, self.catcher_x))

        # Spawn
        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_rate:
            self.spawn_timer = 0.0
            self.objects.append(FallingObj(self.difficulty, self.fall_speed))

        for obj in self.objects:
            obj.update(dt)

        # Grip catches a valid object over the catcher — invalid (red X) ones are ignored
        if grip >= self.threshold:
            for obj in self.objects:
                if obj.scored or obj.missed or not obj.valid:
                    continue
                over_catcher = (abs(obj.x - self.catcher_x) < CATCHER_W//2 + obj.r and
                                CATCHER_Y - 60 < obj.y < CATCHER_Y + 30)
                if over_catcher:
                    obj.scored        = True
                    self.score       += 1
                    self.reps        += 1
                    self.score_flash  = 0.4
                    self.feedback     = ("SCORED!", (0,255,160), 0.8)
                    play_success()
                    break

        # Count misses
        new_misses = [o for o in self.objects if o.missed]
        self.misses += len(new_misses)
        self.objects = [o for o in self.objects if not o.missed and not o.scored]

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None
        if self.score_flash > 0:
            self.score_flash -= dt

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
                game         = "Catch the Falling Object",
                score        = self.score,
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

        pw, ph = 860, 560
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
                "Objects fall from the top of the screen.",
                "Catch them with the catcher to score.",
                "The red object marked with an X must NOT be caught.",
            ]),
            ("CONTROLS", [
                "Tilt wrist LEFT / RIGHT to move the catcher.",
                "Grip (squeeze) while a valid object is over the catcher to catch it.",
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
            f"Score: {self.score:02d}", True, T["ACCENT"]),
            (GAME_W//2 - 80, 18))
        time_col = T["RED"] if self.time_left < 10 else T["TEXT"]
        time_s = font_hud.render(f"{max(0, int(self.time_left)):02d}s", True, time_col)
        surface.blit(time_s, time_s.get_rect(right=self._pause_btn_rect.left - 24, y=18))

        surface.blit(font_sm.render(
            f"Missed {self.misses}", True, T["RED"]),
            (GAME_W - 220, GAME_H - 80))

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W//2 - msg.get_width()//2, GAME_H//2 - 80))

        hints = {"Easy":   "← → Tilt to move   GRIP to catch",
                 "Medium": "← → Tilt to move   GRIP to catch   Avoid the red ✕",
                 "Hard":   "← → Tilt to move   GRIP to catch   Avoid the red ✕"}
        surface.blit(font_sm.render(hints[self.difficulty], True, T["GRAY"]),
                     (GAME_W//2 - 380, GAME_H - 80))

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

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

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
