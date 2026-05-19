"""
scenes/calibration_window.py — Full-screen calibration overlay.

Opened from the Start Session panel when the "Calibrate" button is clicked.

Usage by TherapistDashboardScene:
    win = CalibrationWindow(W, H, game_type)
    # each frame:
    for event in events:
        win.handle_event(event)
    win.update(dt_ms)
    win.draw(surface)
    if win.done:       use win.calibration_result
    if win.cancelled:  close without saving

Phases:
    sensitivity → countdown → recording → trial_done → (×3) → results
"""

import pygame
import math
import builtins
import os

from sensors.input_handler import input_handler


# ── sensor/game-type config ────────────────────────────────────────────────────

SENSOR_CFG = {
    "Grip Strength": {
        "sensor_name": "Force Sensor",
        "instruction": "Squeeze the grip controller as firmly as possible",
        "hold_hint":   "Squeeze and HOLD at your maximum!",
        "key_hint":    "[ Hold SPACE to simulate grip ]",
        "read":        lambda s: s["grip"],
    },
    "Finger Flexion": {
        "sensor_name": "Flex Sensors",
        "instruction": "Curl all fingers as far down as possible",
        "hold_hint":   "Curl fingers fully and HOLD!",
        "key_hint":    "[ Hold DOWN arrow to simulate flex ]",
        "read":        lambda s: max(0.0, -s["tilt_y"]),
    },
    "Wrist Rotation": {
        "sensor_name": "Motion Sensor",
        "instruction": "Rotate your wrist to its full comfortable range",
        "hold_hint":   "Rotate and HOLD at maximum!",
        "key_hint":    "[ Hold LEFT / RIGHT arrow to simulate rotation ]",
        "read":        lambda s: abs(s["tilt_x"]),
    },
}

SENSITIVITY_DESCS = {
    "Low":    "For limited range of motion. Lower threshold needed to trigger actions.",
    "Medium": "Standard setting — recommended for most patients.",
    "High":   "For full range of motion. Higher threshold for more precision.",
}

# Difficulty presets — threshold_pct is applied to the calibrated average
DIFFICULTY_PRESETS = {
    "Easy": {
        "threshold_pct": 40,
        "speed":         "Slow",
        "duration":      "60 seconds",
        "difficulty":    "Easy",
        "desc":          "Wide range, slow pace — ideal for early rehabilitation",
        "color":         (60, 180, 100),
    },
    "Moderate": {
        "threshold_pct": 60,
        "speed":         "Normal",
        "duration":      "120 seconds",
        "difficulty":    "Moderate",
        "desc":          "Balanced challenge — recommended for most patients",
        "color":         (60, 130, 220),
    },
    "Hard": {
        "threshold_pct": 80,
        "speed":         "Fast",
        "duration":      "180 seconds",
        "difficulty":    "Hard",
        "desc":          "High precision, faster pace — for advanced recovery",
        "color":         (220, 90, 60),
    },
}

PRESET_ORDER     = ["Easy", "Moderate", "Hard"]
SPEED_OPTS       = ["Slow", "Normal", "Fast"]
DIFFICULTY_OPTS  = ["Easy", "Moderate", "Hard"]
DURATION_OPTS    = ["60 seconds", "120 seconds", "180 seconds", "Custom"]
THRESHOLD_PCTS   = [30, 40, 50, 60, 70, 80, 90]

RECORD_DURATION  = 3.0
COUNTDOWN_STEPS  = 3
TRIAL_DONE_PAUSE = 1.5


# ── CalibrationWindow ──────────────────────────────────────────────────────────

class CalibrationWindow:

    def __init__(self, width, height, game_type, dark_mode=True):
        self.W         = width
        self.H         = height
        self.game_type = game_type
        self.dark_mode = dark_mode
        self.cfg       = SENSOR_CFG.get(game_type, SENSOR_CFG["Grip Strength"])

        # ── phase state ───────────────────────────────────────────────
        self.phase         = "sensitivity"
        self.sensitivity   = "Medium"
        self.current_trial = 0
        self.trial_results = []
        self.countdown     = COUNTDOWN_STEPS
        self.countdown_t   = 0.0
        self.record_t      = 0.0
        self.peak_value    = 0.0
        self.pause_t       = 0.0
        self.live_value    = 0.0

        # ── results-phase: preset & advanced settings ─────────────────
        self.selected_preset   = "Moderate"   # Easy / Moderate / Hard / Custom
        self.advanced_open     = False

        # advanced settings (start at Moderate defaults)
        self.adv_threshold_pct = 60           # int, one of THRESHOLD_PCTS
        self.adv_speed         = "Normal"
        self.adv_duration      = "120 seconds"
        self.adv_difficulty    = "Moderate"
        self.adv_custom_dur    = ""           # text when duration == "Custom"
        self.adv_dur_active    = False        # custom duration field focused

        # ── outcome ───────────────────────────────────────────────────
        self.done               = False
        self.cancelled          = False
        self.calibration_result = None

        # ── fonts ─────────────────────────────────────────────────────
        H = height
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(name): return os.path.join(_fd, name)
        self.fnt = {
            "title":  pygame.font.Font(_F("FjallaOne-Regular.ttf"),    int(44 * (H / 1080))),
            "sub":    pygame.font.Font(_F("Sora-Light.ttf"),            int(27 * (H / 1080))),
            "body":   pygame.font.Font(_F("Lexend-Regular.ttf"),        int(25 * (H / 1080))),
            "bold":   pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(25 * (H / 1080))),
            "small":  pygame.font.Font(_F("Lexend-Light.ttf"),          int(21 * (H / 1080))),
            "smallb": pygame.font.Font(_F("Lexend-Medium.ttf"),         int(21 * (H / 1080))),
            "btn":    pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(24 * (H / 1080))),
            "big":    pygame.font.Font(_F("GravitasOne-Regular.ttf"),   int(68 * (H / 1080))),
            "med":    pygame.font.Font(_F("FjallaOne-Regular.ttf"),     int(42 * (H / 1080))),
            "tag":    pygame.font.Font(_F("Lexend-Medium.ttf"),         int(20 * (H / 1080))),
            "head2":  pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(25 * (H / 1080))),
            "sym44":  pygame.font.SysFont("segoeuisymbol",              int(44 * (H / 1080))),
            "sym25":  pygame.font.SysFont("segoeuisymbol",              int(25 * (H / 1080))),
            "sym22":  pygame.font.SysFont("segoeuisymbol",              int(22 * (H / 1080))),
        }

        # ── interaction rects (updated each draw) ─────────────────────
        self._sens_rects       = {}
        self._begin_rect       = pygame.Rect(0, 0, 1, 1)
        self._cancel_rect      = pygame.Rect(0, 0, 1, 1)
        self._accept_rect      = pygame.Rect(0, 0, 1, 1)
        self._retry_rect       = pygame.Rect(0, 0, 1, 1)
        self._toggle_rect      = pygame.Rect(0, 0, 1, 1)
        self._preset_card_rects = {}          # {"Easy": Rect, ...}
        self._adv_toggle_rect  = pygame.Rect(0, 0, 1, 1)
        # advanced settings button groups: key → list of (value, Rect)
        self._adv_rects        = {}
        self._adv_dur_rect     = pygame.Rect(0, 0, 1, 1)

    # ── colour palette ────────────────────────────────────────────────────────

    @property
    def C(self):
        if self.dark_mode:
            return dict(
                bg      = (12,  14,  22),
                bg2     = (18,  22,  36),
                panel   = (28,  34,  52),
                panel2  = (20,  25,  40),
                border  = (55,  75, 115),
                accent  = (80, 160, 230),
                accent2 = (50, 120, 190),
                text    = (220, 230, 245),
                sub     = (140, 155, 185),
                green   = (50,  200,  80),
                yellow  = (255, 220,  60),
                orange  = (255, 140,  30),
                red     = (220,  60,  60),
                white   = (255, 255, 255),
            )
        else:
            return dict(
                bg      = (238, 244, 255),
                bg2     = (225, 235, 252),
                panel   = (255, 255, 255),
                panel2  = (228, 238, 252),
                border  = (185, 210, 240),
                accent  = (40,  120, 200),
                accent2 = (20,   80, 160),
                text    = (18,   28,  50),
                sub     = (80,  100, 135),
                green   = (30,  160,  60),
                yellow  = (180, 130,   0),
                orange  = (190,  90,   0),
                red     = (180,  40,  40),
                white   = (255, 255, 255),
            )

    # ── event handling ────────────────────────────────────────────────────────

    def handle_event(self, event):
        # ── keyboard: custom duration field ──────────────────────────
        if event.type == pygame.KEYDOWN and self.adv_dur_active:
            if event.key == pygame.K_BACKSPACE:
                self.adv_custom_dur = self.adv_custom_dur[:-1]
            elif event.key == pygame.K_RETURN:
                self.adv_dur_active = False
            elif event.unicode.isdigit() and len(self.adv_custom_dur) < 4:
                self.adv_custom_dur += event.unicode
            return

        pos = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            raw = event.pos
            pos = builtins.normalise_pos(raw) if hasattr(builtins, "normalise_pos") else raw
        elif event.type == pygame.FINGERDOWN:
            pos = (int(event.x * self.W), int(event.y * self.H))

        if pos is None:
            return

        # top-bar controls always available
        if self._toggle_rect.collidepoint(pos):
            self.dark_mode = not self.dark_mode
            return
        if self._cancel_rect.collidepoint(pos):
            self.cancelled = True
            return

        if self.phase == "sensitivity":
            for name, r in self._sens_rects.items():
                if r.collidepoint(pos):
                    self.sensitivity = name
                    return
            if self._begin_rect.collidepoint(pos):
                self._start_countdown()

        elif self.phase == "results":
            # preset card selection
            for name, r in self._preset_card_rects.items():
                if r.collidepoint(pos):
                    self._apply_preset(name)
                    return

            # advanced toggle
            if self._adv_toggle_rect.collidepoint(pos):
                self.advanced_open = not self.advanced_open
                return

            # advanced settings buttons
            if self.advanced_open:
                # threshold % buttons
                for val, r in self._adv_rects.get("threshold_pct", []):
                    if r.collidepoint(pos):
                        self.adv_threshold_pct = val
                        self.selected_preset   = "Custom"
                        return
                # speed buttons
                for val, r in self._adv_rects.get("speed", []):
                    if r.collidepoint(pos):
                        self.adv_speed       = val
                        self.selected_preset = "Custom"
                        return
                # duration buttons
                for val, r in self._adv_rects.get("duration", []):
                    if r.collidepoint(pos):
                        self.adv_duration    = val
                        self.selected_preset = "Custom"
                        if val != "Custom":
                            self.adv_dur_active = False
                        return
                # custom duration text field
                if self.adv_duration == "Custom":
                    if self._adv_dur_rect.collidepoint(pos):
                        self.adv_dur_active = True
                        return
                    else:
                        self.adv_dur_active = False
                # difficulty buttons
                for val, r in self._adv_rects.get("difficulty", []):
                    if r.collidepoint(pos):
                        self.adv_difficulty  = val
                        self.selected_preset = "Custom"
                        return

            if self._accept_rect.collidepoint(pos):
                self._accept()
            elif self._retry_rect.collidepoint(pos):
                self._retry()

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, dt_ms):
        dt    = dt_ms / 1000.0
        state = input_handler.get_state()

        if self.phase == "countdown":
            self.countdown_t += dt
            if self.countdown_t >= 1.0:
                self.countdown_t -= 1.0
                self.countdown   -= 1
                if self.countdown <= 0:
                    self.phase      = "recording"
                    self.record_t   = 0.0
                    self.peak_value = 0.0

        elif self.phase == "recording":
            self.live_value  = min(1.0, max(0.0, self.cfg["read"](state)))
            self.peak_value  = max(self.peak_value, self.live_value)
            self.record_t   += dt
            if self.record_t >= RECORD_DURATION:
                self.trial_results.append(round(self.peak_value, 4))
                self.phase   = "trial_done"
                self.pause_t = 0.0

        elif self.phase == "trial_done":
            self.pause_t += dt
            if self.pause_t >= TRIAL_DONE_PAUSE:
                self.current_trial += 1
                if self.current_trial >= 3:
                    self._enter_results()
                else:
                    self._start_countdown()

    # ── internal transitions ──────────────────────────────────────────────────

    def _start_countdown(self):
        self.phase       = "countdown"
        self.countdown   = COUNTDOWN_STEPS
        self.countdown_t = 0.0

    def _enter_results(self):
        self.phase = "results"
        # seed advanced settings from Moderate preset scaled to actual average
        self._apply_preset("Moderate")

    def _apply_preset(self, name):
        self.selected_preset = name
        if name in DIFFICULTY_PRESETS:
            p = DIFFICULTY_PRESETS[name]
            self.adv_threshold_pct = p["threshold_pct"]
            self.adv_speed         = p["speed"]
            self.adv_duration      = p["duration"]
            self.adv_difficulty    = p["difficulty"]
            self.adv_custom_dur    = ""
            self.adv_dur_active    = False

    def _accept(self):
        avg = sum(self.trial_results) / len(self.trial_results) if self.trial_results else 0.0
        threshold = round(avg * self.adv_threshold_pct / 100.0, 4)
        dur_display = (self.adv_custom_dur + " seconds"
                       if self.adv_duration == "Custom" and self.adv_custom_dur
                       else self.adv_duration)
        self.calibration_result = {
            "game_type":   self.game_type,
            "sensor":      self.cfg["sensor_name"],
            "sensitivity": self.sensitivity,
            "trials":      list(self.trial_results),
            "average":     round(avg, 4),
            "threshold":   threshold,
            "preset":      self.selected_preset,
            "params": {
                "threshold":     threshold,
                "threshold_pct": self.adv_threshold_pct,
                "speed":         self.adv_speed,
                "duration":      dur_display,
                "difficulty":    self.adv_difficulty,
                "sensitivity":   self.sensitivity,
            },
        }
        self.done = True

    def _retry(self):
        self.current_trial = 0
        self.trial_results = []
        self.advanced_open = False
        self.phase         = "sensitivity"

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface):
        C = self.C
        W, H = self.W, self.H

        surface.fill(C["bg"])

        # ── top bar ───────────────────────────────────────────────────
        top_h = int(68 * H / 1080)
        pygame.draw.rect(surface, C["panel"], (0, 0, W, top_h))
        pygame.draw.line(surface, C["border"], (0, top_h), (W, top_h), 1)

        title_s = self.fnt["title"].render("Sensor Calibration", True, C["text"])
        surface.blit(title_s, (int(32 * W / 1920),
                                top_h // 2 - title_s.get_height() // 2))

        gt_s  = self.fnt["tag"].render(f"  {self.game_type}  ", True, C["white"])
        gt_r  = gt_s.get_rect(midleft=(int(380 * W / 1920), top_h // 2))
        badge = gt_r.inflate(10, 8)
        pygame.draw.rect(surface, C["accent2"], badge, border_radius=10)
        surface.blit(gt_s, gt_r)

        sen_s = self.fnt["tag"].render(f"  {self.cfg['sensor_name']}  ", True, C["text"])
        sen_r = sen_s.get_rect(midleft=(badge.right + int(12 * W / 1920), top_h // 2))
        sen_b = sen_r.inflate(10, 8)
        pygame.draw.rect(surface, C["panel2"], sen_b, border_radius=10)
        pygame.draw.rect(surface, C["border"],  sen_b, 1, border_radius=10)
        surface.blit(sen_s, sen_r)

        tog_s = self.fnt["sym25"].render("☀" if self.dark_mode else "☽", True, C["text"])
        tg_r  = pygame.Rect(W - int(148 * W / 1920), top_h // 2 - int(18 * H / 1080),
                            int(132 * W / 1920), int(36 * H / 1080))
        pygame.draw.rect(surface, C["panel2"], tg_r, border_radius=10)
        pygame.draw.rect(surface, C["border"], tg_r, 1, border_radius=10)
        surface.blit(tog_s, tog_s.get_rect(center=tg_r.center))
        self._toggle_rect = tg_r

        cx_s  = self.fnt["sym25"].render("✕", True, C["sub"])
        cx_r  = pygame.Rect(W - int(296 * W / 1920), top_h // 2 - int(18 * H / 1080),
                            int(132 * W / 1920), int(36 * H / 1080))
        pygame.draw.rect(surface, C["panel2"], cx_r, border_radius=10)
        pygame.draw.rect(surface, C["border"], cx_r, 1, border_radius=10)
        surface.blit(cx_s, cx_s.get_rect(center=cx_r.center))
        self._cancel_rect = cx_r

        # ── content ───────────────────────────────────────────────────
        content = pygame.Rect(0, top_h + int(14 * H / 1080),
                              W, H - top_h - int(14 * H / 1080))
        {
            "sensitivity":  self._draw_sensitivity,
            "countdown":    self._draw_countdown,
            "recording":    self._draw_recording,
            "trial_done":   self._draw_trial_done,
            "results":      self._draw_results,
        }.get(self.phase, lambda s, a, c: None)(surface, content, C)

    # ── phase: sensitivity ────────────────────────────────────────────────────

    def _draw_sensitivity(self, surface, area, C):
        W, H = self.W, self.H
        cx   = area.centerx

        step_s = self.fnt["bold"].render("Step 1 of 2 — Set Sensitivity", True, C["sub"])
        surface.blit(step_s, step_s.get_rect(center=(cx, area.y + int(28 * H / 1080))))

        sen_s = self.fnt["title"].render(
            f"{self.cfg['sensor_name']} Calibration", True, C["text"])
        surface.blit(sen_s, sen_s.get_rect(center=(cx, area.y + int(76 * H / 1080))))

        ins_s = self.fnt["body"].render(self.cfg["instruction"], True, C["sub"])
        surface.blit(ins_s, ins_s.get_rect(center=(cx, area.y + int(122 * H / 1080))))

        diag_r = pygame.Rect(int(60 * W / 1920),  area.y + int(158 * H / 1080),
                             int(520 * W / 1920),  int(370 * H / 1080))
        self._draw_sensor_diagram(surface, diag_r, C, live=False)

        sens_r = pygame.Rect(int(660 * W / 1920), area.y + int(158 * H / 1080),
                             int(780 * W / 1920),  int(370 * H / 1080))
        self._draw_sensitivity_panel(surface, sens_r, C)

        kh_s = self.fnt["small"].render(self.cfg["key_hint"], True, C["sub"])
        surface.blit(kh_s, kh_s.get_rect(center=(cx, area.y + int(570 * H / 1080))))

        begin_r = pygame.Rect(cx - int(170 * W / 1920), area.y + int(620 * H / 1080),
                              int(340 * W / 1920),       int(54 * H / 1080))
        pygame.draw.rect(surface, C["accent"], begin_r, border_radius=14)
        b_s = self.fnt["btn"].render("Begin Calibration  →", True, C["white"])
        surface.blit(b_s, b_s.get_rect(center=begin_r.center))
        self._begin_rect = begin_r

    def _draw_sensitivity_panel(self, surface, r, C):
        W, H = self.W, self.H
        pygame.draw.rect(surface, C["panel"],  r, border_radius=16)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=16)

        head_s = self.fnt["bold"].render("Select Sensitivity", True, C["text"])
        surface.blit(head_s, head_s.get_rect(midtop=(r.centerx, r.y + int(14 * H / 1080))))

        opts  = ["Low", "Medium", "High"]
        btn_w = int(182 * W / 1920)
        btn_h = int(46  * H / 1080)
        gap   = int(16  * W / 1920)
        total = len(opts) * btn_w + (len(opts) - 1) * gap
        sx    = r.centerx - total // 2
        by    = r.y + int(68 * H / 1080)

        self._sens_rects = {}
        for i, opt in enumerate(opts):
            bx  = sx + i * (btn_w + gap)
            br  = pygame.Rect(bx, by, btn_w, btn_h)
            sel = (self.sensitivity == opt)
            pygame.draw.rect(surface, C["accent"] if sel else C["panel2"], br, border_radius=12)
            pygame.draw.rect(surface, C["accent"] if sel else C["border"], br, 2, border_radius=12)
            ls  = self.fnt["btn"].render(opt, True, C["white"] if sel else C["sub"])
            surface.blit(ls, ls.get_rect(center=br.center))
            self._sens_rects[opt] = br

        desc  = SENSITIVITY_DESCS.get(self.sensitivity, "")
        words = desc.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if self.fnt["small"].size(test)[0] > r.width - int(32 * W / 1920):
                if cur:
                    lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)

        dy = by + btn_h + int(20 * H / 1080)
        for line in lines:
            ls = self.fnt["small"].render(line, True, C["sub"])
            surface.blit(ls, ls.get_rect(midtop=(r.centerx, dy)))
            dy += int(26 * H / 1080)

        iy = r.y + int(200 * H / 1080)
        surface.blit(self.fnt["smallb"].render("What calibration does:", True, C["text"]),
                     (r.x + int(16 * W / 1920), iy))
        for k, ln in enumerate([
            "• Runs 3 trials — measures your maximum effort",
            "• Calculates the average of all 3 trials",
            "• Recommends parameters per difficulty level",
            "• Sets a personalised activation threshold",
        ]):
            surface.blit(self.fnt["small"].render(ln, True, C["sub"]),
                         (r.x + int(16 * W / 1920),
                          iy + int(30 * H / 1080) + k * int(26 * H / 1080)))

    # ── phase: countdown ──────────────────────────────────────────────────────

    def _draw_countdown(self, surface, area, C):
        W, H = self.W, self.H
        cx   = area.centerx

        diag_r = pygame.Rect(cx - int(300 * W / 1920), area.y + int(28 * H / 1080),
                             int(600 * W / 1920),       int(310 * H / 1080))
        self._draw_sensor_diagram(surface, diag_r, C, live=False)

        tl_s = self.fnt["bold"].render(
            f"Trial {self.current_trial + 1} of 3 — Get Ready!", True, C["text"])
        surface.blit(tl_s, tl_s.get_rect(center=(cx, area.y + int(388 * H / 1080))))

        num_s = self.fnt["big"].render(str(self.countdown), True, C["yellow"])
        surface.blit(num_s, num_s.get_rect(center=(cx, area.y + int(496 * H / 1080))))

        ins_s = self.fnt["body"].render(self.cfg["instruction"], True, C["sub"])
        surface.blit(ins_s, ins_s.get_rect(center=(cx, area.y + int(612 * H / 1080))))

    # ── phase: recording ──────────────────────────────────────────────────────

    def _draw_recording(self, surface, area, C):
        W, H = self.W, self.H
        cx   = area.centerx

        diag_r = pygame.Rect(cx - int(310 * W / 1920), area.y + int(18 * H / 1080),
                             int(620 * W / 1920),       int(280 * H / 1080))
        self._draw_sensor_diagram(surface, diag_r, C, live=True, value=self.live_value)

        tl_s = self.fnt["bold"].render(
            f"Trial {self.current_trial + 1} of 3 — Recording", True, C["text"])
        surface.blit(tl_s, tl_s.get_rect(center=(cx, area.y + int(336 * H / 1080))))

        hi_s = self.fnt["title"].render(self.cfg["hold_hint"], True, C["yellow"])
        surface.blit(hi_s, hi_s.get_rect(center=(cx, area.y + int(388 * H / 1080))))

        bx = int(180 * W / 1920)
        by = area.y + int(452 * H / 1080)
        bw = W - int(360 * W / 1920)
        bh = int(38 * H / 1080)
        self._draw_bar(surface, bx, by, bw, bh, self.live_value, C,
                       label=f"Live: {self.live_value:.2f}   Peak: {self.peak_value:.2f}")

        remaining = max(0.0, RECORD_DURATION - self.record_t)
        tim_s = self.fnt["body"].render(
            f"Recording…  {remaining:.1f} s remaining", True, C["sub"])
        surface.blit(tim_s, tim_s.get_rect(center=(cx, area.y + int(520 * H / 1080))))

        self._draw_trial_dots(surface, cx, area.y + int(580 * H / 1080), C,
                              current=self.current_trial)

    # ── phase: trial_done ─────────────────────────────────────────────────────

    def _draw_trial_done(self, surface, area, C):
        W, H  = self.W, self.H
        cx    = area.centerx
        val   = self.trial_results[-1] if self.trial_results else 0.0
        trial = len(self.trial_results)

        done_s = self.fnt["bold"].render(
            f"Trial {trial} of 3 — Complete!", True, C["green"])
        surface.blit(done_s, done_s.get_rect(center=(cx, area.centery - int(96 * H / 1080))))

        val_s = self.fnt["big"].render(f"{val:.3f}", True, C["text"])
        surface.blit(val_s, val_s.get_rect(center=(cx, area.centery - int(4 * H / 1080))))

        bx = int(220 * W / 1920)
        by = area.centery + int(68 * H / 1080)
        self._draw_bar(surface, bx, by, W - int(440 * W / 1920),
                       int(32 * H / 1080), val, C)

        nxt = "→ Preparing next trial…" if trial < 3 else "→ Calculating results…"
        surface.blit(self.fnt["body"].render(nxt, True, C["sub"]),
                     self.fnt["body"].render(nxt, True, C["sub"])
                     .get_rect(center=(cx, by + int(54 * H / 1080))))

    # ── phase: results ────────────────────────────────────────────────────────

    def _draw_results(self, surface, area, C):
        W, H = self.W, self.H
        avg  = (sum(self.trial_results) / len(self.trial_results)
                if self.trial_results else 0.0)

        # ─── LEFT column: trial summary ──────────────────────────────
        lx = int(40 * W / 1920)
        lw = int(800 * W / 1920)
        ly = area.y + int(18 * H / 1080)

        # heading
        hd = self.fnt["sym44"].render("✓  Calibration Complete!", True, C["green"])
        surface.blit(hd, (lx, ly))

        # trial bars
        bar_x  = lx + int(80 * W / 1920)
        bar_w  = lw - int(160 * W / 1920)
        bar_h  = int(28 * H / 1080)
        by_cur = ly + int(72 * H / 1080)
        for i, val in enumerate(self.trial_results):
            lbl = self.fnt["bold"].render(f"Trial {i + 1}:", True, C["text"])
            surface.blit(lbl, lbl.get_rect(midright=(bar_x - int(10 * W / 1920),
                                                      by_cur + bar_h // 2)))
            self._draw_bar(surface, bar_x, by_cur, bar_w, bar_h, val, C,
                           label=f"{val:.3f}")
            by_cur += int(56 * H / 1080)

        # average / sensitivity summary box
        sum_r = pygame.Rect(lx, by_cur + int(12 * H / 1080),
                            lw, int(120 * H / 1080))
        pygame.draw.rect(surface, C["panel"],  sum_r, border_radius=14)
        pygame.draw.rect(surface, C["accent"], sum_r, 2,  border_radius=14)

        av_s = self.fnt["med"].render(f"{avg:.3f}", True, C["text"])
        surface.blit(av_s, av_s.get_rect(
            midright=(sum_r.centerx - int(16 * W / 1920), sum_r.centery)))
        surface.blit(self.fnt["bold"].render("Average", True, C["sub"]),
                     self.fnt["bold"].render("Average", True, C["sub"])
                     .get_rect(midright=(sum_r.centerx - int(16 * W / 1920),
                                         sum_r.centery + int(30 * H / 1080))))

        pygame.draw.line(surface, C["border"],
                         (sum_r.centerx, sum_r.y + int(10 * H / 1080)),
                         (sum_r.centerx, sum_r.bottom - int(10 * H / 1080)), 1)

        surface.blit(self.fnt["bold"].render(f"Sensitivity: {self.sensitivity}",
                                              True, C["sub"]),
                     (sum_r.centerx + int(16 * W / 1920),
                      sum_r.y + int(22 * H / 1080)))
        thr_now = round(avg * self.adv_threshold_pct / 100.0, 3)
        surface.blit(self.fnt["body"].render(f"Active threshold: {thr_now:.3f}",
                                              True, C["accent"]),
                     (sum_r.centerx + int(16 * W / 1920),
                      sum_r.y + int(60 * H / 1080)))

        # ─── RIGHT column: preset + advanced ─────────────────────────
        rx = int(880 * W / 1920)
        rw = W - rx - int(40 * W / 1920)
        ry = area.y + int(18 * H / 1080)

        rec_s = self.fnt["head2"].render("Recommended Parameters", True, C["text"])
        surface.blit(rec_s, (rx, ry))

        ry2 = ry + rec_s.get_height() + int(14 * H / 1080)
        self._draw_preset_cards(surface, rx, ry2, rw, C, avg)

        # advanced settings toggle button
        adv_y = ry2 + int(230 * H / 1080)
        adv_lbl = ("▲  Advanced Settings (Custom)" if self.advanced_open
                   else "▼  Advanced Settings")
        adv_col = C["accent2"] if self.advanced_open else C["panel2"]
        adv_r   = pygame.Rect(rx, adv_y, rw, int(40 * H / 1080))
        pygame.draw.rect(surface, adv_col, adv_r, border_radius=10)
        pygame.draw.rect(surface, C["border"], adv_r, 1, border_radius=10)
        adv_s = self.fnt["btn"].render(adv_lbl, True, C["text"])
        surface.blit(adv_s, adv_s.get_rect(midleft=(adv_r.x + int(16 * W / 1920),
                                                      adv_r.centery)))
        self._adv_toggle_rect = adv_r

        if self.advanced_open:
            ap_r = pygame.Rect(rx, adv_y + int(46 * H / 1080),
                               rw, int(224 * H / 1080))
            self._draw_advanced_panel(surface, ap_r, C, avg)

        # ─── bottom buttons ───────────────────────────────────────────
        btn_y    = area.bottom - int(72 * H / 1080)
        retry_r  = pygame.Rect(W // 2 - int(340 * W / 1920), btn_y,
                               int(240 * W / 1920), int(52 * H / 1080))
        accept_r = pygame.Rect(W // 2 + int(96 * W / 1920),  btn_y,
                               int(260 * W / 1920), int(52 * H / 1080))

        pygame.draw.rect(surface, C["panel2"], retry_r,  border_radius=13)
        pygame.draw.rect(surface, C["border"], retry_r,  1, border_radius=13)
        surface.blit(self.fnt["sym25"].render("↺  Retry", True, C["sub"]),
                     self.fnt["sym25"].render("↺  Retry", True, C["sub"])
                     .get_rect(center=retry_r.center))
        self._retry_rect = retry_r

        pygame.draw.rect(surface, C["green"],  accept_r, border_radius=13)
        surface.blit(self.fnt["sym25"].render("✓  Accept & Continue", True, C["white"]),
                     self.fnt["sym25"].render("✓  Accept & Continue", True, C["white"])
                     .get_rect(center=accept_r.center))
        self._accept_rect = accept_r

    def _draw_preset_cards(self, surface, rx, ry, rw, C, avg):
        W, H  = self.W, self.H
        n     = len(PRESET_ORDER)
        gap   = int(14 * W / 1920)
        cw    = (rw - gap * (n - 1)) // n
        ch    = int(212 * H / 1080)

        self._preset_card_rects = {}
        for i, name in enumerate(PRESET_ORDER):
            p   = DIFFICULTY_PRESETS[name]
            cx2 = rx + i * (cw + gap)
            cr  = pygame.Rect(cx2, ry, cw, ch)
            sel = (self.selected_preset == name)

            # card background
            base_col = p["color"]
            bg_col   = (*base_col, 55) if not sel else (*base_col, 120)
            bg_surf  = pygame.Surface((cw, ch), pygame.SRCALPHA)
            bg_surf.fill(bg_col)
            surface.blit(bg_surf, cr.topleft)

            border_w = 3 if sel else 1
            pygame.draw.rect(surface, base_col, cr, border_w, border_radius=14)

            if sel:
                tick_s = self.fnt["smallb"].render("● Selected", True, base_col)
                surface.blit(tick_s, tick_s.get_rect(
                    topright=(cr.right - int(10 * W / 1920),
                              cr.y + int(10 * H / 1080))))

            # difficulty label
            nm_s = self.fnt["head2"].render(name.upper(), True,
                                             base_col if sel else C["text"])
            surface.blit(nm_s, (cr.x + int(14 * W / 1920),
                                 cr.y + int(14 * H / 1080)))

            # parameters table
            thr_val = round(avg * p["threshold_pct"] / 100.0, 3)
            rows = [
                ("Threshold",  f"{p['threshold_pct']}% = {thr_val:.3f}"),
                ("Speed",      p["speed"]),
                ("Duration",   p["duration"]),
                ("Difficulty", p["difficulty"]),
            ]
            ty = cr.y + int(56 * H / 1080)
            for label, val in rows:
                lbl_s = self.fnt["smallb"].render(f"{label}:", True, C["sub"])
                val_s = self.fnt["small"].render(val, True, C["text"])
                surface.blit(lbl_s, (cr.x + int(14 * W / 1920), ty))
                surface.blit(val_s, (cr.x + int(14 * W / 1920) + lbl_s.get_width() + int(6 * W / 1920), ty))
                ty += int(36 * H / 1080)

            # description
            desc_words = p["desc"].split()
            desc_lines, cur = [], ""
            for w in desc_words:
                test = (cur + " " + w).strip()
                if self.fnt["small"].size(test)[0] > cw - int(28 * W / 1920):
                    if cur:
                        desc_lines.append(cur)
                    cur = w
                else:
                    cur = test
            if cur:
                desc_lines.append(cur)
            dy2 = cr.bottom - int(14 * H / 1080) - len(desc_lines) * int(22 * H / 1080)
            for dl in desc_lines:
                ds = self.fnt["small"].render(dl, True, C["sub"])
                surface.blit(ds, (cr.x + int(14 * W / 1920), dy2))
                dy2 += int(22 * H / 1080)

            self._preset_card_rects[name] = cr

        # "Custom" indicator when in custom mode
        if self.selected_preset == "Custom":
            cust_s = self.fnt["smallb"].render(
                "● Custom settings active", True, C["orange"])
            surface.blit(cust_s, cust_s.get_rect(
                midtop=(rx + rw // 2, ry + ch + int(6 * H / 1080))))

    def _draw_advanced_panel(self, surface, r, C, avg):
        W, H = self.W, self.H
        pygame.draw.rect(surface, C["panel"],  r, border_radius=12)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=12)

        self._adv_rects = {"threshold_pct": [], "speed": [],
                           "duration": [], "difficulty": []}

        row_h   = int(46 * H / 1080)
        col_lbl = int(180 * W / 1920)      # label column width
        lx      = r.x + int(14 * W / 1920)
        rx2     = r.x + col_lbl + int(22 * W / 1920)
        gap_btn = int(8 * W / 1920)
        row_gap = int(52 * H / 1080)
        cy      = r.y + int(14 * H / 1080)

        def row_label(text, y):
            s = self.fnt["smallb"].render(text, True, C["sub"])
            surface.blit(s, s.get_rect(midleft=(lx, y + row_h // 2)))

        def option_buttons(key, opts, current, y, btn_w_override=None):
            bw = btn_w_override or int(78 * W / 1920)
            bh = int(34 * H / 1080)
            x  = rx2
            rects = []
            for opt in opts:
                br  = pygame.Rect(x, y + (row_h - bh) // 2, bw, bh)
                sel = (str(current) == str(opt))
                pygame.draw.rect(surface, C["accent"] if sel else C["panel2"],
                                 br, border_radius=8)
                pygame.draw.rect(surface, C["accent"] if sel else C["border"],
                                 br, 1, border_radius=8)
                s = self.fnt["tag"].render(str(opt), True,
                                            C["white"] if sel else C["sub"])
                surface.blit(s, s.get_rect(center=br.center))
                rects.append((opt, br))
                x += bw + gap_btn
            self._adv_rects[key] = rects

        # threshold %
        row_label("Threshold %:", cy)
        option_buttons("threshold_pct", THRESHOLD_PCTS,
                       self.adv_threshold_pct, cy, btn_w_override=int(64 * W / 1920))
        # live preview of threshold
        thr_val = round(avg * self.adv_threshold_pct / 100.0, 3)
        pv_s = self.fnt["small"].render(f"= {thr_val:.3f}", True, C["accent"])
        last_r = self._adv_rects["threshold_pct"][-1][1] if self._adv_rects["threshold_pct"] else None
        if last_r:
            surface.blit(pv_s, (last_r.right + int(12 * W / 1920),
                                  cy + row_h // 2 - pv_s.get_height() // 2))
        cy += row_gap

        # speed
        row_label("Speed:", cy)
        option_buttons("speed", SPEED_OPTS, self.adv_speed, cy,
                       btn_w_override=int(90 * W / 1920))
        cy += row_gap

        # duration
        row_label("Duration:", cy)
        option_buttons("duration", DURATION_OPTS, self.adv_duration, cy,
                       btn_w_override=int(112 * W / 1920))
        if self.adv_duration == "Custom":
            # custom text field
            last_dur_r = self._adv_rects["duration"][-1][1]
            fi_r = pygame.Rect(last_dur_r.right + int(10 * W / 1920),
                               cy + (row_h - 32) // 2,
                               int(90 * W / 1920), int(32 * H / 1080))
            fi_col = C["accent"] if self.adv_dur_active else C["border"]
            pygame.draw.rect(surface, C["panel2"], fi_r, border_radius=6)
            pygame.draw.rect(surface, fi_col, fi_r, 2, border_radius=6)
            txt = self.adv_custom_dur or "sec"
            fi_s = self.fnt["tag"].render(txt, True,
                                           C["text"] if self.adv_custom_dur else C["sub"])
            surface.blit(fi_s, fi_s.get_rect(midleft=(fi_r.x + int(6 * W / 1920),
                                                        fi_r.centery)))
            self._adv_dur_rect = fi_r
        cy += row_gap

        # difficulty
        row_label("Difficulty:", cy)
        option_buttons("difficulty", DIFFICULTY_OPTS, self.adv_difficulty, cy,
                       btn_w_override=int(108 * W / 1920))

    # ── sensor diagrams ───────────────────────────────────────────────────────

    def _draw_sensor_diagram(self, surface, r, C, live=False, value=0.0):
        gt = self.game_type
        if gt == "Grip Strength":
            self._draw_grip_diagram(surface, r, C, live, value)
        elif gt == "Finger Flexion":
            self._draw_flex_diagram(surface, r, C, live, value)
        else:
            self._draw_wrist_diagram(surface, r, C, live, value)

    def _draw_grip_diagram(self, surface, r, C, live, value):
        W, H = self.W, self.H
        cx, cy = r.centerx, r.centery

        bg = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
        bg.fill((*C["panel"], 210))
        surface.blit(bg, r.topleft)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=14)

        ts = self.fnt["smallb"].render("Force Sensor  —  Grip Strength", True, C["accent"])
        surface.blit(ts, ts.get_rect(midtop=(cx, r.y + int(10 * H / 1080))))

        gw = int(r.width  * 0.22)
        gh = int(r.height * 0.54)
        gx = cx - gw // 2
        gy = r.y + int(r.height * 0.24)
        grip_rect = pygame.Rect(gx, gy, gw, gh)
        body_col  = C["accent"] if (live and value > 0.05) else C["panel2"]
        pygame.draw.rect(surface, body_col, grip_rect, border_radius=int(gw * 0.45))
        pygame.draw.rect(surface, C["border"], grip_rect, 2, border_radius=int(gw * 0.45))

        cols, rows = 4, 5
        sx2 = gw // (cols + 1)
        sy2 = gh // (rows + 1)
        for row in range(rows):
            for col in range(cols):
                act = live and value > (col / cols * 0.4)
                pygame.draw.circle(surface,
                                   C["white"] if act else C["border"],
                                   (gx + sx2 * (col + 1), gy + sy2 * (row + 1)),
                                   int(3 * H / 1080))

        arr_y   = gy + gh // 2
        arr_len = int(r.width * 0.10)
        for side in (-1, 1):
            base_x = cx + side * (gw // 2 + int(10 * W / 1920))
            col_a  = C["orange"] if (live and value > 0.05) else C["sub"]
            for k in range(3):
                ox    = base_x + side * k * int(10 * W / 1920)
                tip_x = ox - side * arr_len
                pygame.draw.line(surface, col_a,
                                 (ox, arr_y - int(10 * H / 1080)), (tip_x, arr_y), 2)
                pygame.draw.line(surface, col_a,
                                 (ox, arr_y + int(10 * H / 1080)), (tip_x, arr_y), 2)

        sq_s = self.fnt["small"].render("SQUEEZE", True, C["sub"])
        surface.blit(sq_s, sq_s.get_rect(midtop=(cx, gy + gh + int(6 * H / 1080))))

    def _draw_flex_diagram(self, surface, r, C, live, value):
        W, H = self.W, self.H
        cx, cy = r.centerx, r.centery

        bg = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
        bg.fill((*C["panel"], 210))
        surface.blit(bg, r.topleft)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=14)

        ts = self.fnt["smallb"].render("Flex Sensors  —  Finger Flexion", True, C["accent"])
        surface.blit(ts, ts.get_rect(midtop=(cx, r.y + int(10 * H / 1080))))

        palm_w = int(r.width  * 0.54)
        palm_h = int(r.height * 0.20)
        palm_x = cx - palm_w // 2
        palm_y = r.y + int(r.height * 0.68)
        palm_c = C["accent2"] if (live and value > 0.05) else C["panel2"]
        pygame.draw.rect(surface, palm_c,
                         (palm_x, palm_y, palm_w, palm_h), border_radius=8)
        pygame.draw.rect(surface, C["border"],
                         (palm_x, palm_y, palm_w, palm_h), 1, border_radius=8)

        n_fin  = 5
        fin_w  = int(r.width * 0.07)
        fin_h  = int(r.height * 0.38)
        fin_gap = (palm_w - n_fin * fin_w) // (n_fin + 1)
        curl   = value if live else 0.0

        for i in range(n_fin):
            fx      = palm_x + fin_gap + i * (fin_w + fin_gap)
            curl_px = int(curl * fin_h * 0.80)
            fy_top  = palm_y - fin_h + curl_px
            fin_col = C["accent"] if (live and value > 0.05) else C["panel2"]
            pygame.draw.rect(surface, fin_col,
                             (fx, fy_top, fin_w, fin_h - curl_px + 4),
                             border_radius=int(fin_w * 0.45))
            pygame.draw.rect(surface, C["border"],
                             (fx, fy_top, fin_w, fin_h - curl_px + 4),
                             1, border_radius=int(fin_w * 0.45))

        curl_s = self.fnt["small"].render("CURL  ▼", True, C["sub"])
        surface.blit(curl_s, curl_s.get_rect(
            midtop=(cx, palm_y + palm_h + int(6 * H / 1080))))

    def _draw_wrist_diagram(self, surface, r, C, live, value):
        W, H = self.W, self.H
        cx, cy = r.centerx, r.centery

        bg = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
        bg.fill((*C["panel"], 210))
        surface.blit(bg, r.topleft)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=14)

        ts = self.fnt["smallb"].render("Motion Sensor  —  Wrist Rotation", True, C["accent"])
        surface.blit(ts, ts.get_rect(midtop=(cx, r.y + int(10 * H / 1080))))

        arc_cx = cx
        arc_cy = r.y + int(r.height * 0.66)
        arc_r2 = int(min(r.width, r.height) * 0.28)

        arc_rect = pygame.Rect(arc_cx - arc_r2, arc_cy - arc_r2,
                               arc_r2 * 2, arc_r2 * 2)
        pygame.draw.arc(surface, C["border"], arc_rect,
                        math.radians(0), math.radians(180), int(6 * H / 1080))

        if live and value > 0.01:
            col_a = C["orange"] if value > 0.7 else C["accent"]
            pygame.draw.arc(surface, col_a, arc_rect,
                            math.radians(0), math.radians(value * 180),
                            int(8 * H / 1080))

        arm_angle = math.radians(value * 180) if live else math.radians(90)
        arm_len   = arc_r2 - int(6 * W / 1920)
        arm_ex    = arc_cx + int(arm_len * math.cos(arm_angle))
        arm_ey    = arc_cy - int(arm_len * math.sin(arm_angle))
        arm_col   = C["accent"] if (live and value > 0.05) else C["sub"]
        pygame.draw.line(surface, arm_col, (arc_cx, arc_cy), (arm_ex, arm_ey), 5)
        pygame.draw.circle(surface, arm_col, (arc_cx, arc_cy), int(7 * H / 1080))

        surface.blit(self.fnt["small"].render("0°", True, C["sub"]),
                     (arc_cx + arc_r2 + int(4 * W / 1920),
                      arc_cy - self.fnt["small"].get_height() // 2))
        max_s = self.fnt["small"].render("180°", True, C["sub"])
        surface.blit(max_s,
                     (arc_cx - arc_r2 - max_s.get_width() - int(4 * W / 1920),
                      arc_cy - max_s.get_height() // 2))

        rot_s = self.fnt["sym22"].render("◄  ROTATE WRIST  ►", True, C["sub"])
        surface.blit(rot_s, rot_s.get_rect(
            midtop=(cx, arc_cy + arc_r2 + int(8 * H / 1080))))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _draw_bar(self, surface, x, y, w, h, value, C, label=""):
        value = max(0.0, min(1.0, value))
        pygame.draw.rect(surface, C["panel2"], (x, y, w, h), border_radius=h // 2)
        fw = int(value * w)
        if fw > 1:
            col = (C["green"] if value < 0.70
                   else C["orange"] if value < 0.90
                   else C["red"])
            pygame.draw.rect(surface, col, (x, y, fw, h), border_radius=h // 2)
        pygame.draw.rect(surface, C["border"], (x, y, w, h), 1, border_radius=h // 2)
        if label:
            ls = self.fnt["small"].render(label, True, C["text"])
            surface.blit(ls, (x + w + int(14 * self.W / 1920),
                               y + h // 2 - ls.get_height() // 2))

    def _draw_trial_dots(self, surface, cx, y, C, current=0):
        dot_r = int(10 * self.H / 1080)
        gap   = int(56 * self.W / 1920)
        total = 3 * dot_r * 2 + 2 * gap
        sx    = cx - total // 2
        for i in range(3):
            dx = sx + i * (dot_r * 2 + gap) + dot_r
            col = (C["green"] if i < len(self.trial_results)
                   else C["yellow"] if i == current
                   else C["panel2"])
            pygame.draw.circle(surface, col,   (dx, y), dot_r)
            pygame.draw.circle(surface, C["border"], (dx, y), dot_r, 1)
            lbl = (f"{self.trial_results[i]:.2f}" if i < len(self.trial_results)
                   else f"Trial {i + 1}")
            ls = self.fnt["small"].render(lbl, True, C["sub"])
            surface.blit(ls, ls.get_rect(midtop=(dx, y + dot_r + int(4 * self.H / 1080))))
