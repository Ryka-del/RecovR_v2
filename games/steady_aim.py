"""
Steady Aim — Wrist Rotation game (1920x1080)

Mechanic (Osu-style):
  - Circles appear randomly on screen
  - Patient controls a cursor with wrist tilt (tilt_x = left/right, tilt_y = up/down)
  - Cursor must enter and stay inside the circle for HOLD_TIME seconds
  - On success: circle disappears, new one appears elsewhere
  - Difficulty controls circle size and hold time

Difficulty:
  Easy   — large circles (r=120), hold 1.5s
  Medium — medium circles (r=80), hold 2.0s
  Hard   — small circles (r=45), hold 2.5s

Goal: hit 8/10/12 circles within the time limit.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, start_music, stop_music
from constants import get_theme, GAME_W, GAME_H

GOALS      = {"Easy": 8,   "Medium": 10, "Hard": 12}
DURATION   = {"Easy": 90,  "Medium": 75, "Hard": 60}
CIRCLE_R   = {"Easy": 120, "Medium": 80, "Hard": 45}
HOLD_TIME  = {"Easy": 1.5, "Medium": 2.0, "Hard": 2.5}
CURSOR_SPD = {"Easy": 900, "Medium": 1000, "Hard": 1100}  # faster = more responsive

# Keep circles away from HUD and edges
MARGIN = 160
CX_MIN, CX_MAX = MARGIN, GAME_W - MARGIN
CY_MIN, CY_MAX = MARGIN, GAME_H - MARGIN


class SteadyAimGame(FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.goal       = GOALS[self.difficulty]
        dur_override    = data.get("duration_sec")
        self.duration   = dur_override if dur_override else DURATION[self.difficulty]
        self.circle_r   = CIRCLE_R[self.difficulty]
        self.hold_time  = HOLD_TIME[self.difficulty]
        self.cursor_spd = CURSOR_SPD[self.difficulty]

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_back_rect  = pygame.Rect(0, 0, 1, 1)

        self.vol_active = False
        self.pause_vol  = 0.4
        self._font_hud  = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm   = pygame.font.SysFont("monospace", 24)
        self._font_fb   = pygame.font.SysFont("monospace", 52, bold=True)

        self._init_fatigue()
        start_music()
        self._reset()
        self._show_instructions = True
        self._pause_btn_rect    = pygame.Rect(GAME_W - 90, 13, 70, 46)

    def _reset(self):
        self._init_fatigue()
        self.paused      = False
        self.pause_sel   = 0
        self.game_over   = False
        self.score       = 0
        self.reps        = 0
        self.time_left   = float(self.duration)
        self.start_time  = pygame.time.get_ticks()
        self.cursor_x    = float(GAME_W // 2)
        self.cursor_y    = float(GAME_H // 2)
        self.hold_timer  = 0.0
        self.feedback    = None
        self.flash_timer = 0.0
        self._state      = {"tilt_x": 0.0, "tilt_y": 0.0}
        self._spawn_circle()

    def _spawn_circle(self):
        # Keep new circle away from cursor to avoid instant hits
        for _ in range(20):
            x = random.randint(CX_MIN, CX_MAX)
            y = random.randint(CY_MIN, CY_MAX)
            if math.hypot(x - self.cursor_x, y - self.cursor_y) > self.circle_r * 2:
                break
        self.circle_x = float(x)
        self.circle_y = float(y)
        self.hold_timer = 0.0

    def _normalize_tilt(self, raw, axis):
        if axis == "x":
            wmin = self.cal.get("wrist_min", -1.0)
            wmax = self.cal.get("wrist_max",  1.0)
            if wmax == wmin:
                return raw
            return max(-1.0, min(1.0, (raw - wmin) / (wmax - wmin) * 2.0 - 1.0))
        # y axis: no wrist cal, use raw directly
        return max(-1.0, min(1.0, raw))

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    self._reset()
                elif self._results_back_rect.collidepoint(event.pos):
                    self._exit_to_game_config()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_game_config()
            return

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
                if self.pause_sel == 0: self.paused = False
                elif self.pause_sel == 1: self._reset(); self.paused = False
                elif self.pause_sel == 2: self.vol_active = True
                else: self._exit_to_game_config()
            return
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._pause_btn_rect.collidepoint(event.pos)):
            self.paused = True
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True

    def update(self, dt):
        if self._show_instructions or self.game_over:
            return

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused: return

        self.time_left -= dt
        if self.time_left <= 0:
            self._end_game(); return

        # Move cursor with wrist tilt
        tx = self._normalize_tilt(self._state["tilt_x"], "x")
        ty = self._normalize_tilt(self._state["tilt_y"], "y")
        if abs(tx) > 0.05:
            self.cursor_x += self.cursor_spd * dt * tx
        if abs(ty) > 0.05:
            self.cursor_y += self.cursor_spd * dt * ty
        self.cursor_x = max(0, min(GAME_W, self.cursor_x))
        self.cursor_y = max(0, min(GAME_H, self.cursor_y))

        # Check if cursor is inside circle
        dist = math.hypot(self.cursor_x - self.circle_x, self.cursor_y - self.circle_y)
        inside = dist <= self.circle_r

        if inside:
            self.hold_timer += dt
            if self.hold_timer >= self.hold_time:
                self.score += 1
                self.reps  += 1
                self.flash_timer = 0.4
                self.feedback = ("LOCKED!", (0,255,160), 0.8)
                play_success()
                self._spawn_circle()
        else:
            self.hold_timer = max(0.0, self.hold_timer - dt * 1.5)

        if self.flash_timer > 0:
            self.flash_timer -= dt
        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None

    def _exit_to_game_config(self):
        import builtins
        stop_music()
        builtins.pending_panel   = 4
        builtins.pending_patient = self._patient
        builtins.pending_account = self.account
        self.manager.go_to("therapist_dashboard")

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 860, 570
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill((18, 26, 46, 252))
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
                "Move the arrow inside circle.",
                "Hold inside until the arc fills completely -- then you score!",
            ]),
            ("CONTROLS", [
                "Tilt hand LEFT / RIGHT to move arrow horizontally.",
                "Tilt hand UP / DOWN to move arrow vertically.",
            ]),
            ("THIS SESSION", [
                f"Hold time per circle:  {self.hold_time:.1f} seconds",
                f"Duration:              {int(self.duration)} seconds",
                f"Difficulty:            {self.difficulty}",
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

    def _end_game(self):
        stop_music()
        self.game_over_duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.game_over_score    = self.score
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id   = patient_id,
                therapist_id = self.account_id,
                game         = "Steady Aim",
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

        # Grid
        for y in range(0, GAME_H, 60):
            pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)
        for x in range(0, GAME_W, 80):
            pygame.draw.line(surface, T["PANEL"], (x, 0), (x, GAME_H), 1)

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        font_hud = self._font_hud
        font_sm  = self._font_sm

        # Determine if cursor is inside circle
        dist   = math.hypot(self.cursor_x - self.circle_x, self.cursor_y - self.circle_y)
        inside = dist <= self.circle_r
        prog   = min(1.0, self.hold_timer / self.hold_time)

        # Circle
        cx, cy = int(self.circle_x), int(self.circle_y)
        r = self.circle_r
        circle_col = T["GREEN"] if inside else T["ACCENT"]

        # Outer glow
        glow_surf = pygame.Surface((r*2+40, r*2+40), pygame.SRCALPHA)
        alpha = int(40 + 30 * math.sin(pygame.time.get_ticks() / 300))
        pygame.draw.circle(glow_surf, (*circle_col, alpha), (r+20, r+20), r+16)
        surface.blit(glow_surf, (cx - r - 20, cy - r - 20))

        # Main circle
        pygame.draw.circle(surface, circle_col, (cx, cy), r, 5)

        # Hold progress arc
        if inside and prog > 0:
            arc_rect = pygame.Rect(cx - r + 8, cy - r + 8, (r-8)*2, (r-8)*2)
            end_angle = -math.pi/2 + 2*math.pi*prog
            pygame.draw.arc(surface, T["GREEN"], arc_rect, -math.pi/2, end_angle, 8)

        # Approach indicator — line from cursor to circle center
        if not inside:
            pygame.draw.line(surface, (*T["GRAY"], 80) if len(T["GRAY"]) == 3 else T["GRAY"],
                             (int(self.cursor_x), int(self.cursor_y)), (cx, cy), 1)

        # Score flash
        if self.flash_timer > 0:
            alpha = int(80 * self.flash_timer / 0.4)
            fl = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
            fl.fill((0, 255, 160, alpha))
            surface.blit(fl, (0, 0))

        # Cursor — proper upward arrow
        cur_x, cur_y = int(self.cursor_x), int(self.cursor_y)
        cur_col    = T["GREEN"] if inside else T["WHITE"]
        cur_shadow = T["BG"]
        tip_w, shaft_w, head_h, shaft_h = 24, 8, 22, 22
        pts = [
            (cur_x,             cur_y),
            (cur_x + tip_w,     cur_y + head_h),
            (cur_x + shaft_w,   cur_y + head_h),
            (cur_x + shaft_w,   cur_y + head_h + shaft_h),
            (cur_x - shaft_w,   cur_y + head_h + shaft_h),
            (cur_x - shaft_w,   cur_y + head_h),
            (cur_x - tip_w,     cur_y + head_h),
        ]
        pygame.draw.polygon(surface, cur_col, pts)
        pygame.draw.polygon(surface, cur_shadow, pts, 2)

        # Top HUD
        pygame.draw.rect(surface, T["PANEL"], (0, 0, GAME_W, 72))
        pygame.draw.line(surface, T["ACCENT"], (0, 72), (GAME_W, 72), 1)
        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        surface.blit(font_hud.render(
            f"STEADY AIM  ·  {self.difficulty.upper()}", True, diff_col), (80, 18))
        surface.blit(font_hud.render(
            f"Score: {self.score:02d}", True, T["ACCENT"]),
            (GAME_W//2 - 80, 18))
        time_col = T["RED"] if self.time_left < 10 else T["TEXT"]
        surface.blit(font_hud.render(
            f"{max(0, int(self.time_left)):02d}s", True, time_col),
            (GAME_W - 160, 18))

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

        # Hold progress bar (below HUD)
        if inside:
            bw = 400
            bx = GAME_W//2 - bw//2
            pygame.draw.rect(surface, T["PANEL"], (bx, 80, bw, 12), border_radius=6)
            pygame.draw.rect(surface, T["GREEN"], (bx, 80, int(bw*prog), 12), border_radius=6)

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W//2 - msg.get_width()//2, GAME_H//2 - 80))

        surface.blit(font_sm.render(
            "Tilt wrist to move cursor — hold inside the circle   ESC=Pause",
            True, T["GRAY"]), (80, GAME_H - 44))

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
        bg.fill((28, 34, 52, 245))
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, T["ACCENT"], mr, 2, border_radius=16)

        f_big = pygame.font.SysFont("monospace", 48, bold=True)
        f_mid = pygame.font.SysFont("monospace", 32, bold=True)
        f_sm  = pygame.font.SysFont("monospace", 24)
        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        title = f_big.render("Session Complete!", True, T["YELLOW"])
        surface.blit(title, title.get_rect(center=(mr.centerx, my + 60)))

        sc_s = f_mid.render(f"Score:    {self.game_over_score}", True, T["WHITE"])
        surface.blit(sc_s, sc_s.get_rect(midleft=(mx + 80, my + 140)))

        mins, secs = divmod(self.game_over_duration, 60)
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, T["WHITE"])
        surface.blit(du_s, du_s.get_rect(midleft=(mx + 80, my + 185)))

        dif_s = f_sm.render(f"Difficulty: {self.difficulty}", True, T["GRAY"])
        surface.blit(dif_s, dif_s.get_rect(midleft=(mx + 80, my + 230)))

        mp = pygame.mouse.get_pos()
        bw, bh = 220, 52

        again_r = pygame.Rect(mx + 60,         my + mh - 80, bw, bh)
        back_r  = pygame.Rect(mx + mw - 60 - bw, my + mh - 80, bw, bh)
        self._results_again_rect = again_r
        self._results_back_rect  = back_r

        ag_col = (55, 170, 100) if again_r.collidepoint(mp) else (40, 140, 80)
        bk_col = (75, 110, 190) if back_r.collidepoint(mp)  else (55, 85, 160)

        pygame.draw.rect(surface, ag_col, again_r, border_radius=10)
        pygame.draw.rect(surface, bk_col, back_r,  border_radius=10)

        surface.blit(f_btn.render("Play Again", True, T["WHITE"]),
                     f_btn.render("Play Again", True, T["WHITE"]).get_rect(center=again_r.center))
        surface.blit(f_btn.render("Exit", True, T["WHITE"]),
                     f_btn.render("Exit", True, T["WHITE"]).get_rect(center=back_r.center))
