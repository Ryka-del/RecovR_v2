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
import builtins
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.input_handler import input_handler


# ── sensor/game-type config ────────────────────────────────────────────────────

SENSOR_CFG = {
    "Grip Strength": {
        "sensor_name": "Force Sensor",
        "key_hint":    "[ Hold SPACE to simulate grip ]",
        "read":        lambda s: s["grip"],
    },
    "Finger Flexion": {
        "sensor_name": "Flex Sensors",
        "key_hint":    "[ Hold DOWN arrow to simulate flex ]",
        "read":        lambda s: max(0.0, s["tilt_y"]),
    },
    "Wrist Rotation": {
        "sensor_name": "Motion Sensor",
        "key_hint":    "[ Hold LEFT / RIGHT arrow to simulate rotation ]",
        "read":        lambda s: abs(s["tilt_x"]),
    },
}

# Difficulty presets — threshold_pct is applied to the calibrated average
DIFFICULTY_PRESETS = {
    "Easy": {
        "threshold_pct": 40,
        "speed":         "Slow",
        "duration":      "60 s",
        "difficulty":    "Easy",
        "desc":          "Wide range, slow pace — ideal for early rehabilitation",
        "color":         (60, 180, 100),
    },
    "Medium": {
        "threshold_pct": 60,
        "speed":         "Normal",
        "duration":      "120 s",
        "difficulty":    "Medium",
        "desc":          "Balanced challenge — recommended for most patients",
        "color":         (60, 130, 220),
    },
    "Hard": {
        "threshold_pct": 80,
        "speed":         "Fast",
        "duration":      "180 s",
        "difficulty":    "Hard",
        "desc":          "High precision, faster pace — for advanced recovery",
        "color":         (220, 90, 60),
    },
}

PRESET_ORDER     = ["Easy", "Medium", "Hard"]
SPEED_OPTS       = ["Slow", "Normal", "Fast"]
DIFFICULTY_OPTS  = ["Easy", "Medium", "Hard"]
THRESHOLD_PCTS   = [30, 40, 50, 60, 70, 80, 90]

RECORD_DURATION  = 3.0
COUNTDOWN_STEPS  = 3
TRIAL_DONE_PAUSE = 1.5

# ── per-game Advanced Settings parameters ──────────────────────────────────────
# Each entry is a real, independently-overridable constant read by that game's
# own on_enter() (see games/<name>.py) -- not an invented control. "presets"
# gives that param's value under each difficulty (matching the game's own
# hardcoded Easy/Medium/Hard dict), used both as the starting value when a
# preset card is picked and to restore via "Reset to Preset". "key" is the
# calibration_result["params"] key the game checks (falling back to its own
# difficulty dict when absent, so normal non-customized sessions are
# unaffected). Games not listed here (Gravity Catch, Catch the Falling
# Object, Whack-a-Mole Twist) have not been individually audited for
# overridable constants, so they get no game-specific rows -- only the
# generic Speed/Duration controls that already apply to every game.
GAME_PARAM_SCHEMA = {
    "Basketball": [
        {"key": "bb_goal",       "label": "Target Score",       "unit": "pts",
         "min": 5,  "max": 30,  "step": 1,
         "presets": {"Easy": 10,   "Medium": 15,   "Hard": 20}},
        {"key": "bb_zone_width", "label": "Target Zone Size",   "unit": "%",
         "min": 5,  "max": 35,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 25,   "Medium": 16,   "Hard": 9}},
    ],
    "Lemonade": [
        {"key": "lem_target",         "label": "Lemons Required",         "unit": "lemons",
         "min": 5,   "max": 100, "step": 1,
         "presets": {"Easy": 15,   "Medium": 30,   "Hard": 50}},
        {"key": "lem_grip_threshold", "label": "Grip Threshold",          "unit": "%",
         "min": 20,  "max": 90,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 35,   "Medium": 45,   "Hard": 55}},
        {"key": "lem_hold_duration",  "label": "Squeeze Hold Duration",   "unit": "s",
         "min": 0.5, "max": 5.0, "step": 0.1,
         "presets": {"Easy": 0.8,  "Medium": 1.2,  "Hard": 1.6}},
    ],
    "Piano Tiles": [
        {"key": "pt_spawn_rate", "label": "Tile Spawn Interval", "unit": "s",
         "min": 0.2, "max": 2.0, "step": 0.05,
         "presets": {"Easy": 1.0,  "Medium": 0.7,  "Hard": 0.45}},
    ],
    "Apple Catching": [
        {"key": "ac_apple_speed", "label": "Apple Falling Speed",          "unit": "px/s",
         "min": 100, "max": 800,  "step": 10,
         "presets": {"Easy": 260,   "Medium": 380,   "Hard": 520}},
        {"key": "ac_move_speed",  "label": "Basket Movement Sensitivity",  "unit": "px/s",
         "min": 300, "max": 1500, "step": 10,
         "presets": {"Easy": 750,   "Medium": 900,   "Hard": 1050}},
    ],
    "Key and Lock": [
        {"key": "kl_tolerance", "label": "Wrist Angle Tolerance",   "unit": "°",
         "min": 2,   "max": 30,  "step": 1,
         "presets": {"Easy": 15,   "Medium": 8,    "Hard": 3}},
        {"key": "kl_hold_time", "label": "Required Hold Duration", "unit": "s",
         "min": 0.2, "max": 3.0, "step": 0.1,
         # the game's HOLD_TIME is currently one fixed constant (0.5s) for
         # every difficulty -- not yet difficulty-scaled, so all 3 presets
         # start at that same real value instead of inventing variation.
         "presets": {"Easy": 0.5,  "Medium": 0.5,  "Hard": 0.5}},
    ],
    "Steady Aim": [
        {"key": "sa_goal",       "label": "Target Hits Required",  "unit": "hits",
         "min": 3,   "max": 25,   "step": 1,
         "presets": {"Easy": 8,     "Medium": 10,   "Hard": 12}},
        {"key": "sa_circle_r",   "label": "Target Size",           "unit": "px",
         "min": 30,  "max": 160,  "step": 5,
         "presets": {"Easy": 120,   "Medium": 80,   "Hard": 45}},
        {"key": "sa_cursor_spd", "label": "Cursor Sensitivity",    "unit": "",
         "min": 500, "max": 1500, "step": 10,
         "presets": {"Easy": 900,   "Medium": 1000, "Hard": 1100}},
        {"key": "sa_hold_time",  "label": "Required Hold Duration","unit": "s",
         "min": 0.5, "max": 4.0,  "step": 0.1,
         "presets": {"Easy": 1.5,   "Medium": 2.0,  "Hard": 2.5}},
    ],
    "Feed the Cat": [
        {"key": "ftc_grip_threshold", "label": "Grip Threshold",            "unit": "%",
         "min": 15,   "max": 85,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 45,   "Hard": 60}},
        {"key": "ftc_move_deadzone",  "label": "Wrist Movement Sensitivity","unit": "%",
         "min": 2,    "max": 25,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 5,     "Medium": 8,    "Hard": 12}},
        {"key": "ftc_zone_tolerance", "label": "Positioning Tolerance",     "unit": "px",
         "min": 40,   "max": 200,  "step": 5,
         "presets": {"Easy": 150,   "Medium": 110,  "Hard": 75}},
    ],
}
# Games that read the generic Speed (Slow/Normal/Fast) setting at all --
# shown as its own Advanced Settings row only for these (showing it for a
# game that ignores it would be a non-functional control).
GAMES_USING_SPEED = {"Basketball", "Piano Tiles"}


# ── CalibrationWindow ──────────────────────────────────────────────────────────

class CalibrationWindow:

    def __init__(self, width, height, game_type, game_name=None, dark_mode=True):
        self.W         = width
        self.H         = height
        self.game_type = game_type
        self.game_name = game_name            # specific game, e.g. "Lemonade" -- drives
                                               # which Advanced Settings rows are shown
        self.dark_mode = dark_mode
        self.cfg       = SENSOR_CFG.get(game_type, SENSOR_CFG["Grip Strength"])
        self.param_schema = GAME_PARAM_SCHEMA.get(game_name, [])

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
        self.selected_preset     = "Medium"   # Easy / Medium / Hard
        self.recommended_preset  = "Medium"   # from _recommend_difficulty(); never
                                               # changed by the therapist's own pick
        self.customized          = False      # True once a game-specific param has
                                               # been edited away from its preset value

        # advanced settings (start at Moderate defaults)
        self.adv_threshold_pct = 60           # int, one of THRESHOLD_PCTS
        self.adv_speed         = "Normal"
        self.adv_duration      = "120 s"
        self.adv_difficulty    = "Medium"
        self.adv_custom_dur    = ""           # text when duration == "Custom"
        self.adv_dur_active    = False        # custom duration field focused
        # game-specific overrides (see GAME_PARAM_SCHEMA), keyed by each
        # param's "key" -- empty/default means "use this preset's own value"
        self.custom_params     = {}

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
            "big":    pygame.font.Font(_F("GravitasOne-Regular.ttf"),   int(86 * (H / 1080))),
            "big2":   pygame.font.Font(_F("GravitasOne-Regular.ttf"),   int(58 * (H / 1080))),
            "med":    pygame.font.Font(_F("FjallaOne-Regular.ttf"),     int(42 * (H / 1080))),
            "tag":    pygame.font.Font(_F("Lexend-Medium.ttf"),         int(20 * (H / 1080))),
            "head2":  pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(25 * (H / 1080))),
            "sym44":  pygame.font.SysFont("segoeuisymbol",              int(44 * (H / 1080))),
            "sym25":  pygame.font.SysFont("segoeuisymbol",              int(25 * (H / 1080))),
        }

        # ── interaction rects (updated each draw) ─────────────────────
        self._begin_rect        = pygame.Rect(0, 0, 1, 1)
        self._cancel_rect       = pygame.Rect(0, 0, 1, 1)
        self._accept_rect       = pygame.Rect(0, 0, 1, 1)
        self._retry_rect        = pygame.Rect(0, 0, 1, 1)
        self._toggle_rect       = pygame.Rect(0, 0, 1, 1)
        self._preset_card_rects = {}          # {"Easy": Rect, ...}
        self._adv_open_rect     = pygame.Rect(0, 0, 1, 1)   # "Advanced Settings" button (results screen)
        # ── Advanced Settings screen (separate phase) ──────────────────
        self._adv_back_rect     = pygame.Rect(0, 0, 1, 1)
        self._adv_reset_rect    = pygame.Rect(0, 0, 1, 1)
        self._adv_apply_rect    = pygame.Rect(0, 0, 1, 1)
        # per-row stepper buttons: list of (minus_rect, plus_rect, param_spec)
        self._adv_param_rects    = []
        self._adv_speed_rects    = []          # [(opt, Rect), ...] when this game uses Speed
        self._adv_threshold_minus = pygame.Rect(0, 0, 1, 1)
        self._adv_threshold_plus  = pygame.Rect(0, 0, 1, 1)
        self._adv_dur_minus      = pygame.Rect(0, 0, 1, 1)
        self._adv_dur_plus       = pygame.Rect(0, 0, 1, 1)
        # editing snapshot: the configuration Advanced Settings opened with,
        # so Cancel/Back can discard unapplied edits (spec 6: "when returning
        # without applying, discard only unapplied edits")
        self._adv_snapshot      = None

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
            if self._begin_rect.collidepoint(pos):
                self._start_countdown()

        elif self.phase == "results":
            # preset card selection -- never touches recommended_preset, only
            # which one the therapist currently has selected.
            for name, r in self._preset_card_rects.items():
                if r.collidepoint(pos):
                    self._apply_preset(name)
                    return

            if self._adv_open_rect.collidepoint(pos):
                self._enter_advanced()
                return
            if self._accept_rect.collidepoint(pos):
                self._accept()
            elif self._retry_rect.collidepoint(pos):
                self._retry()

        elif self.phase == "advanced":
            if self._adv_back_rect.collidepoint(pos):
                self._leave_advanced(apply=False)
                return
            if self._adv_reset_rect.collidepoint(pos):
                self._apply_preset(self.selected_preset)   # restores this preset's own values
                return
            if self._adv_apply_rect.collidepoint(pos):
                self._leave_advanced(apply=True)
                return

            # generic Threshold % stepper
            if self._adv_threshold_minus.collidepoint(pos):
                self._step_threshold(-1); return
            if self._adv_threshold_plus.collidepoint(pos):
                self._step_threshold(+1); return

            # generic Duration stepper
            if self._adv_dur_minus.collidepoint(pos):
                self._step_duration(-10); return
            if self._adv_dur_plus.collidepoint(pos):
                self._step_duration(+10); return

            # Speed (Slow/Normal/Fast), only for games that use it
            for opt, r in self._adv_speed_rects:
                if r.collidepoint(pos):
                    if self.adv_speed != opt:
                        self.adv_speed = opt
                        self.customized = True
                    return

            # per-game parameter steppers
            for minus_r, plus_r, spec in self._adv_param_rects:
                if minus_r.collidepoint(pos):
                    self._step_param(spec, -1); return
                if plus_r.collidepoint(pos):
                    self._step_param(spec, +1); return

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, dt_ms):
        dt    = dt_ms / 1000.0
        input_handler.update(dt)
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
        # Recommended difficulty: new logic (none existed before) -- how far
        # through the sensor's own 0-1 range the patient's average trial
        # reached. Low average -> limited strength/range -> Easy; high
        # average -> strong/full range -> Hard. Simple, explainable, and
        # driven entirely by the real calibration data, never hardcoded.
        self.recommended_preset = self._recommend_difficulty()
        self._apply_preset(self.recommended_preset)

    def _recommend_difficulty(self):
        avg = (sum(self.trial_results) / len(self.trial_results)
               if self.trial_results else 0.0)
        if avg < 0.33:
            return "Easy"
        if avg < 0.66:
            return "Medium"
        return "Hard"

    def _apply_preset(self, name):
        self.selected_preset = name
        self.customized       = False
        if name in DIFFICULTY_PRESETS:
            p = DIFFICULTY_PRESETS[name]
            self.adv_threshold_pct = p["threshold_pct"]
            self.adv_speed         = p["speed"]
            self.adv_duration      = p["duration"]
            self.adv_difficulty    = p["difficulty"]
            self.adv_custom_dur    = ""
            self.adv_dur_active    = False
        # Reset every game-specific param back to this preset's own value.
        # "presets" holds values in DISPLAY units (e.g. 45 meaning 45%);
        # custom_params always stores the REAL unit the game reads (0.45),
        # so games never need to know about display scaling.
        self.custom_params = {}
        for spec in self.param_schema:
            disp  = spec["presets"].get(name, spec["presets"].get("Medium"))
            scale = spec.get("scale")
            self.custom_params[spec["key"]] = disp * scale if scale else disp

    def _enter_advanced(self):
        """Open Advanced Settings as its own screen (spec 2: not a popup/
        accordion over Results). Snapshot the current config so Back can
        discard unapplied edits without touching what's already selected."""
        self._adv_snapshot = (self.selected_preset, self.customized,
                              dict(self.custom_params), self.adv_threshold_pct,
                              self.adv_speed, self.adv_duration)
        self.phase = "advanced"

    def _leave_advanced(self, apply):
        if not apply and self._adv_snapshot is not None:
            (self.selected_preset, self.customized, self.custom_params,
             self.adv_threshold_pct, self.adv_speed,
             self.adv_duration) = self._adv_snapshot
        self._adv_snapshot = None
        self.phase = "results"

    def _step_threshold(self, direction):
        opts = THRESHOLD_PCTS
        i = opts.index(self.adv_threshold_pct) if self.adv_threshold_pct in opts else 2
        self.adv_threshold_pct = opts[max(0, min(len(opts) - 1, i + direction))]
        self.customized = True

    def _step_duration(self, delta_sec):
        try:
            cur = int(self.adv_duration.split()[0]) if self.adv_duration != "Custom" \
                else int(self.adv_custom_dur or 120)
        except (ValueError, IndexError):
            cur = 120
        cur = max(20, min(300, cur + delta_sec))
        self.adv_duration   = f"{cur} s"
        self.adv_custom_dur = ""
        self.adv_dur_active = False
        self.customized = True

    def _step_param(self, spec, direction):
        # Step in DISPLAY units (step/min/max are defined in display units,
        # e.g. whole percent) then convert back to the REAL unit the game
        # reads before storing, matching _apply_preset's convention.
        key, step, scale = spec["key"], spec["step"], spec.get("scale")
        lo, hi = spec["min"], spec["max"]
        cur_real = self.custom_params.get(key, spec["presets"].get(self.selected_preset, lo))
        cur_disp = cur_real / scale if scale else cur_real
        new_disp = round(cur_disp + direction * step, 4)
        new_disp = max(lo, min(hi, new_disp))
        new_real = new_disp * scale if scale else new_disp
        if isinstance(step, int) and float(new_real).is_integer():
            new_real = int(new_real)
        self.custom_params[key] = new_real
        self.customized = True

    def _accept(self):
        avg = sum(self.trial_results) / len(self.trial_results) if self.trial_results else 0.0
        threshold = round(avg * self.adv_threshold_pct / 100.0, 4)
        params = {
            "threshold":     threshold,
            "threshold_pct": self.adv_threshold_pct,
            "speed":         self.adv_speed,
            "duration":      self.adv_duration,
            "difficulty":    self.adv_difficulty,
            "sensitivity":   self.sensitivity,
        }
        params.update(self.custom_params)   # game-specific overrides, if any
        self.calibration_result = {
            "game_type":   self.game_type,
            "game_name":   self.game_name,
            "sensor":      self.cfg["sensor_name"],
            "sensitivity": self.sensitivity,
            "trials":      list(self.trial_results),
            "average":     round(avg, 4),
            "threshold":   threshold,
            "preset":      self.selected_preset,
            "recommended": self.recommended_preset,
            "customized":  self.customized,
            "dark_mode":   self.dark_mode,
            "params":      params,
        }
        self.done = True

    def _retry(self):
        self.current_trial = 0
        self.trial_results = []
        self.custom_params = {}
        self.customized     = False
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

        _bw = int(40 * W / 1920)
        _bh = int(36 * H / 1080)

        if self.phase == "advanced":
            # Advanced Settings is its own screen (spec 2) -- its own header:
            # Back arrow, "Advanced Settings", selected game name. No X here
            # (that would cancel the whole calibration); Back returns to
            # Results instead, discarding only unapplied edits.
            back_r = pygame.Rect(int(20 * W / 1920), top_h // 2 - _bh // 2, _bw, _bh)
            pygame.draw.rect(surface, C["panel2"], back_r, border_radius=8)
            pygame.draw.rect(surface, C["border"], back_r, 1, border_radius=8)
            bk_s = self.fnt["sym25"].render("←", True, C["text"])
            surface.blit(bk_s, bk_s.get_rect(center=back_r.center))
            self._adv_back_rect = back_r
            self._cancel_rect = pygame.Rect(0, 0, 1, 1)

            title_s = self.fnt["title"].render("Advanced Settings", True, C["text"])
            surface.blit(title_s, (back_r.right + int(16 * W / 1920),
                                    top_h // 2 - title_s.get_height() // 2))
            if self.game_name:
                gn_s = self.fnt["sub"].render(self.game_name, True, C["sub"])
                surface.blit(gn_s, (back_r.right + int(16 * W / 1920) + title_s.get_width()
                                     + int(14 * W / 1920),
                                     top_h // 2 - gn_s.get_height() // 2))
        else:
            title_s = self.fnt["title"].render(
                f"Sensor Calibration — {self.cfg['sensor_name']}", True, C["text"])
            surface.blit(title_s, (int(32 * W / 1920),
                                    top_h // 2 - title_s.get_height() // 2))

            cx_s  = self.fnt["sym25"].render("✕", True, C["sub"])
            cx_r  = pygame.Rect(W - int(100 * W / 1920), top_h // 2 - _bh // 2, _bw, _bh)
            pygame.draw.rect(surface, C["panel2"], cx_r, border_radius=8)
            pygame.draw.rect(surface, C["border"], cx_r, 1, border_radius=8)
            surface.blit(cx_s, cx_s.get_rect(center=cx_r.center))
            self._cancel_rect = cx_r

        tog_s = self.fnt["sym25"].render("☀" if self.dark_mode else "☽", True, C["text"])
        tg_r  = pygame.Rect(W - int(52 * W / 1920), top_h // 2 - _bh // 2, _bw, _bh)
        pygame.draw.rect(surface, C["panel2"], tg_r, border_radius=8)
        pygame.draw.rect(surface, C["border"], tg_r, 1, border_radius=8)
        surface.blit(tog_s, tog_s.get_rect(center=tg_r.center))
        self._toggle_rect = tg_r

        # ── content ───────────────────────────────────────────────────
        content = pygame.Rect(0, top_h + int(14 * H / 1080),
                              W, H - top_h - int(14 * H / 1080))
        {
            "sensitivity":  self._draw_sensitivity,
            "countdown":    self._draw_countdown,
            "recording":    self._draw_recording,
            "trial_done":   self._draw_trial_done,
            "results":      self._draw_results,
            "advanced":     self._draw_advanced_settings,
        }.get(self.phase, lambda s, a, c: None)(surface, content, C)

    # ── phases: sensitivity / countdown / recording / trial_done ───────────────
    # All four share one compact 800x480 monitoring layout (therapist-facing:
    # trial progress, live/peak raw readings, recording countdown, controller
    # status, trial indicators) -- only the live values and status label
    # change per phase. "sensitivity" is just this same layout before Trial 1
    # starts (Begin Calibration button, nothing recorded yet); there is no
    # more separate Low/Medium/High sensitivity-picker screen.

    def _draw_sensitivity(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Waiting", show_begin=True)

    def _draw_countdown(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Waiting")

    def _draw_recording(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Recording")

    def _draw_trial_done(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Completed")

    # Fixed design-space (1080-reference) offset of each row from the top of
    # `area`, measured with the Begin-Calibration button included -- the
    # tallest variant. Every phase uses these SAME offsets (not individually
    # re-centered) so the layout never jumps as the screen auto-advances
    # through Waiting -> Recording -> Completed; only the button row at the
    # bottom appears/disappears. Live Reading / Peak Reading always stack
    # vertically (full width, compact height) for every sensor type.
    _LM_NATURAL_H = 586

    def _draw_live_monitor(self, surface, area, C, status, show_begin=False):
        W, H = self.W, self.H
        cx   = area.centerx
        lx   = int(40 * W / 1920)
        rw   = W - lx * 2
        is_wrist = self.game_type == "Wrist Rotation"
        status_col = {"Waiting": C["sub"], "Recording": C["yellow"],
                      "Completed": C["green"]}[status]

        # Vertically center the (fixed-height) block in whatever room `area`
        # actually has -- compact on a roomy desktop window, snug on the
        # 800x480 touch panel -- instead of hugging the top with dead space
        # below it.
        ref_avail = area.height * 1080 / H
        base = max(14, (ref_avail - self._LM_NATURAL_H) / 2)

        def off(units):
            return area.y + int((base + units) * H / 1080)

        # row 1 -- trial progress + status
        row1_y = off(0)
        tl_s = self.fnt["head2"].render(f"Trial {self.current_trial + 1} of 3", True, C["text"])
        surface.blit(tl_s, (lx, row1_y))
        st_s = self.fnt["head2"].render(status, True, status_col)
        surface.blit(st_s, st_s.get_rect(topright=(lx + rw, row1_y)))

        # row 2 -- Live Reading / Peak Reading cards, stacked vertically
        # (full width, compact height) for every sensor. Grip/Flex show the
        # raw 0-1 sensor scale (no invented unit, no misleading "%" -- same
        # 3dp formatting the Results screen already uses). Wrist Rotation
        # shows the real calculated wrist angle in degrees instead -- the
        # SAME formula games/key_lock.py already uses to turn tilt_x into an
        # on-screen angle (tilt mapped linearly over its -1..1 range to
        # -90..+90 degrees), not a new/invented conversion -- plus which
        # direction (Left/Right) the wrist is currently rotated toward. The
        # existing abs()-based live_value/peak_value that actually drive
        # calibration (trial_results, threshold calc) are untouched; this
        # only changes how that same data is labeled on screen.
        cards_y  = off(58)
        card_h   = int(145 * H / 1080)
        card_gap = int(14 * H / 1080)
        live_r = pygame.Rect(lx, cards_y, rw, card_h)
        peak_r = pygame.Rect(lx, cards_y + card_h + card_gap, rw, card_h)

        if is_wrist:
            if status == "Recording":
                raw_tilt = input_handler.get_state()["tilt_x"]
                deadzone = 0.03
                direction = ("Right" if raw_tilt > deadzone else
                             "Left" if raw_tilt < -deadzone else "Center")
                live_txt = f"{abs(raw_tilt) * 90:.0f}°"
                # Lexend has no arrow glyph (tofu box) -- plain text reads
                # clearly at this size without needing a second symbol-font
                # blit for a small in-card tag.
                live_tag = ("RIGHT" if direction == "Right" else
                            "LEFT" if direction == "Left" else "CENTER")
            else:
                live_txt, live_tag = "—", None
            peak_deg = (self.trial_results[-1] * 90 if status == "Completed" and self.trial_results
                        else self.peak_value * 90 if status == "Recording" else None)
            peak_txt = f"{peak_deg:.0f}°" if peak_deg is not None else "—"
            tag_col = C["accent"]
        else:
            live_val = self.live_value if status == "Recording" else None
            peak_val = (self.trial_results[-1] if status == "Completed" and self.trial_results
                        else self.peak_value if status == "Recording" else None)
            live_txt = f"{live_val:.3f}" if live_val is not None else "—"
            peak_txt = f"{peak_val:.3f}" if peak_val is not None else "—"
            live_tag, tag_col = None, None

        self._draw_reading_card(surface, live_r, C, "Live Reading", live_txt,
                                C["accent"], font=self.fnt["big2"],
                                tag=live_tag, tag_col=tag_col)
        self._draw_reading_card(surface, peak_r, C, "Peak Reading", peak_txt,
                                C["green"], font=self.fnt["big2"])

        # row 3 -- recording countdown (existing RECORD_DURATION/record_t
        # timing, shown as real remaining seconds -- not a sensor percentage)
        timer_y = off(378)
        if status == "Recording":
            remaining = max(0.0, RECORD_DURATION - self.record_t)
            frac = 1.0 - (remaining / RECORD_DURATION if RECORD_DURATION else 0.0)
            bar_w = rw - int(90 * W / 1920)
            self._draw_bar(surface, lx, timer_y, bar_w, int(16 * H / 1080), frac, C)
            tm_s = self.fnt["bold"].render(f"{remaining:.1f}s", True, C["text"])
            surface.blit(tm_s, (lx + bar_w + int(14 * W / 1920), timer_y - int(5 * H / 1080)))
        elif status == "Waiting" and self.phase == "countdown":
            surface.blit(self.fnt["bold"].render(
                f"Starts in {self.countdown}s", True, C["sub"]), (lx, timer_y))
        elif status == "Completed":
            surface.blit(self.fnt["bold"].render(
                "Trial saved", True, C["green"]), (lx, timer_y))

        # row 4 -- controller status (simulation mode only shown when the
        # keyboard fallback -- the app's existing simulated-input path -- is
        # actually what's driving the reading)
        ctrl_y = off(428)
        if input_handler.connected:
            ctrl_txt, ctrl_col = "Controller Connected", C["green"]
        else:
            ctrl_txt, ctrl_col = f"Simulation Mode — {self.cfg['key_hint']}", C["orange"]
        ctrl_s = self.fnt["small"].render(ctrl_txt, True, ctrl_col)
        surface.blit(ctrl_s, (lx, ctrl_y))

        # row 5 -- trial indicators (completed / active / pending)
        dots_y = off(482)
        self._draw_trial_dots(surface, cx, dots_y, C, current=self.current_trial)

        # row 6 -- Begin Calibration (pre-trial-1 only)
        if show_begin:
            btn_y = off(532)
            begin_r = pygame.Rect(cx - int(170 * W / 1920), btn_y,
                                  int(340 * W / 1920), int(54 * H / 1080))
            pygame.draw.rect(surface, C["accent"], begin_r, border_radius=14)
            b_s = self.fnt["sym25"].render("Begin Calibration  →", True, C["white"])
            surface.blit(b_s, b_s.get_rect(center=begin_r.center))
            self._begin_rect = begin_r
        else:
            self._begin_rect = pygame.Rect(0, 0, 1, 1)

    def _draw_reading_card(self, surface, r, C, label, text, accent,
                           font=None, tag=None, tag_col=None):
        W, H = self.W, self.H
        pygame.draw.rect(surface, C["panel"],  r, border_radius=14)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=14)
        pad = int(18 * W / 1920)
        lbl_s = self.fnt["bold"].render(label, True, C["sub"])
        surface.blit(lbl_s, (r.x + pad, r.y + int(14 * H / 1080)))
        val_font = font or self.fnt["big"]
        val_col  = accent if text != "—" else C["sub"]
        val_s = val_font.render(text, True, val_col)
        val_y = r.y + int(14 * H / 1080) + lbl_s.get_height() + int(12 * H / 1080)
        surface.blit(val_s, (r.x + pad, val_y))
        if tag:
            tag_s = self.fnt["bold"].render(tag, True, tag_col or C["sub"])
            surface.blit(tag_s, (r.x + pad + val_s.get_width() + int(18 * W / 1920),
                                 val_y + val_s.get_height() - tag_s.get_height()))

    # ── phase: results ────────────────────────────────────────────────────────

    def _fmt_trial(self, val):
        """Display text for one trial/average value, in the real unit for
        this sensor -- degrees (magnitude) for Wrist Rotation using the same
        tilt->angle formula as the live monitor/games/key_lock.py, the raw
        0-1 scale (3dp, matching the rest of the app) for Grip/Flex."""
        if self.game_type == "Wrist Rotation":
            return f"{val * 90:.0f}°"
        return f"{val:.3f}"

    def _draw_results(self, surface, area, C):
        W, H = self.W, self.H
        avg  = (sum(self.trial_results) / len(self.trial_results)
                if self.trial_results else 0.0)
        lx = int(36 * W / 1920)
        rw = W - lx * 2

        def u(n): return int(n * H / 1080)

        # ── A. completion banner ───────────────────────────────────────
        y = area.y + u(14)
        ban_h = u(100)
        ban_r = pygame.Rect(lx, y, rw, ban_h)
        pygame.draw.rect(surface, C["panel"], ban_r, border_radius=12)
        pygame.draw.rect(surface, C["green"], ban_r, 2, border_radius=12)
        ck_s = self.fnt["sym44"].render("✓", True, C["green"])
        surface.blit(ck_s, (ban_r.x + u(16), ban_r.centery - ck_s.get_height() // 2))
        hd_s = self.fnt["head2"].render("Calibration Complete!", True, C["green"])
        surface.blit(hd_s, (ban_r.x + u(16) + ck_s.get_width() + int(12 * W / 1920),
                             ban_r.y + u(12)))
        sub_s = self.fnt["small"].render(
            "All required sensors have been successfully calibrated.",
            True, C["sub"])
        surface.blit(sub_s, (ban_r.x + u(16) + ck_s.get_width() + int(12 * W / 1920),
                              ban_r.y + u(12) + hd_s.get_height() + u(2)))
        y += ban_h + u(16)

        # ── B. Calibration Results card ────────────────────────────────
        res_h = u(230)
        res_r = pygame.Rect(lx, y, rw, res_h)
        pygame.draw.rect(surface, C["panel"],  res_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], res_r, 1, border_radius=12)

        rh_s = self.fnt["bold"].render("Calibration Results", True, C["text"])
        surface.blit(rh_s, (res_r.x + u(14), res_r.y + u(10)))
        sn_s = self.fnt["small"].render(f"Sensor: {self.cfg['sensor_name']} ({self.game_type})",
                                        True, C["sub"])
        surface.blit(sn_s, sn_s.get_rect(topright=(res_r.right - u(14), res_r.y + u(12))))

        bar_x  = res_r.x + u(100)
        bar_w  = res_r.width - u(100) - u(100)
        bar_h  = u(18)
        by_cur = res_r.y + u(46)
        trial_count = max(3, len(self.trial_results))
        for i in range(trial_count):
            val = self.trial_results[i] if i < len(self.trial_results) else 0.0
            lbl = self.fnt["smallb"].render(f"Trial {i + 1}", True, C["text"])
            surface.blit(lbl, lbl.get_rect(midright=(bar_x - u(8), by_cur + bar_h // 2)))
            self._draw_bar(surface, bar_x, by_cur, bar_w, bar_h, val, C,
                           label=self._fmt_trial(val))
            by_cur += u(34)

        # average / threshold strip, inside the same card (not a separate box)
        strip_y = by_cur + u(10)
        av_lbl_s = self.fnt["med"].render(self._fmt_trial(avg), True, C["text"])
        surface.blit(av_lbl_s, (res_r.x + u(14), strip_y))
        avl_s = self.fnt["small"].render("Average", True, C["sub"])
        surface.blit(avl_s, (res_r.x + u(14), strip_y + av_lbl_s.get_height() + u(2)))

        divx = res_r.x + u(160)
        pygame.draw.line(surface, C["border"], (divx, strip_y), (divx, res_r.bottom - u(10)), 1)

        thr_now = round(avg * self.adv_threshold_pct / 100.0, 3)
        thr_disp = self._fmt_trial(thr_now)
        surface.blit(self.fnt["smallb"].render(f"Sensitivity: {self.sensitivity}", True, C["sub"]),
                     (divx + u(16), strip_y + u(4)))
        surface.blit(self.fnt["body"].render(f"Active threshold: {thr_disp}", True, C["accent"]),
                     (divx + u(16), strip_y + u(32)))
        y += res_h + u(16)

        # ── C. Select Difficulty (3 compact cards) ────────────────────
        dh_s = self.fnt["bold"].render("Select Difficulty", True, C["text"])
        surface.blit(dh_s, (lx, y))
        y += dh_s.get_height() + u(8)
        cards_h = u(130)
        self._draw_difficulty_cards(surface, lx, y, rw, cards_h, C)
        y += cards_h + u(16)

        # ── D. Selected Preset Summary ─────────────────────────────────
        sum_h = u(110)
        self._draw_preset_summary(surface, pygame.Rect(lx, y, rw, sum_h), C)
        y += sum_h + u(16)

        # ── E. bottom actions ────────────────────────────────────────
        # sit right after the content, like the rest of this app's cards --
        # any true leftover room becomes trailing margin below, not a gap
        # pushing these actions down to the bottom.
        btn_y = min(y, area.bottom - u(60))
        btn_h = u(54)
        gap   = int(14 * W / 1920)
        bw    = (rw - gap * 2) // 3
        retry_r = pygame.Rect(lx, btn_y, bw, btn_h)
        adv_r   = pygame.Rect(lx + bw + gap, btn_y, bw, btn_h)
        acc_r   = pygame.Rect(lx + 2 * (bw + gap), btn_y, bw, btn_h)

        pygame.draw.rect(surface, C["panel2"], retry_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], retry_r, 1, border_radius=12)
        rt_s = self.fnt["sym25"].render("↺  Retry Calibration", True, C["sub"])
        surface.blit(rt_s, rt_s.get_rect(center=retry_r.center))
        self._retry_rect = retry_r

        pygame.draw.rect(surface, C["panel2"], adv_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], adv_r, 1, border_radius=12)
        av2_s = self.fnt["sym25"].render("⚙  Advanced Settings", True, C["text"])
        surface.blit(av2_s, av2_s.get_rect(center=adv_r.center))
        self._adv_open_rect = adv_r

        pygame.draw.rect(surface, C["green"], acc_r, border_radius=12)
        ac_s = self.fnt["sym25"].render("✓  Accept & Continue", True, C["white"])
        surface.blit(ac_s, ac_s.get_rect(center=acc_r.center))
        self._accept_rect = acc_r

    def _draw_difficulty_cards(self, surface, lx, ry, rw, ch, C):
        W, H  = self.W, self.H
        n     = len(PRESET_ORDER)
        gap   = int(12 * W / 1920)
        cw    = (rw - gap * (n - 1)) // n

        self._preset_card_rects = {}
        for i, name in enumerate(PRESET_ORDER):
            p   = DIFFICULTY_PRESETS[name]
            cr  = pygame.Rect(lx + i * (cw + gap), ry, cw, ch)
            sel = (self.selected_preset == name)
            rec = (self.recommended_preset == name)
            base_col = p["color"]

            bg_surf = pygame.Surface((cw, ch), pygame.SRCALPHA)
            bg_surf.fill((*base_col, 120 if sel else 50))
            surface.blit(bg_surf, cr.topleft)
            pygame.draw.rect(surface, base_col, cr, 3 if sel else 1, border_radius=12)

            nm_s = self.fnt["bold"].render(name.upper(), True,
                                           base_col if sel else C["text"])
            surface.blit(nm_s, (cr.x + int(10 * W / 1920), cr.y + int(8 * H / 1080)))

            if rec:
                rc_s = self.fnt["tag"].render("RECOMMENDED", True, C["white"])
                rc_r = pygame.Rect(0, 0, rc_s.get_width() + int(10 * W / 1920),
                                   rc_s.get_height() + int(4 * H / 1080))
                rc_r.topright = (cr.right - int(8 * W / 1920), cr.y + int(8 * H / 1080))
                pygame.draw.rect(surface, C["green"], rc_r, border_radius=int(6 * H / 1080))
                surface.blit(rc_s, rc_s.get_rect(center=rc_r.center))

            thr_val = round(DIFFICULTY_PRESETS[name]["threshold_pct"], 0)
            dt = f"Threshold {int(thr_val)}%  ·  {p['desc'].split('—')[0].strip()}"
            words, lines, cur = dt.split(), [], ""
            for w in words:
                test = (cur + " " + w).strip()
                if self.fnt["small"].size(test)[0] > cw - int(20 * W / 1920):
                    if cur: lines.append(cur)
                    cur = w
                else:
                    cur = test
            if cur: lines.append(cur)
            ty = cr.y + int(8 * H / 1080) + nm_s.get_height() + int(6 * H / 1080)
            for ln in lines[:2]:
                ls = self.fnt["small"].render(ln, True, C["sub"])
                surface.blit(ls, (cr.x + int(10 * W / 1920), ty))
                ty += ls.get_height() + int(2 * H / 1080)

            self._preset_card_rects[name] = cr

    def _draw_preset_summary(self, surface, r, C):
        """Section C: compact chip row of the GAME's own parameters (not the
        generic threshold/speed/duration) for the currently selected preset
        -- customized values if the therapist edited any in Advanced
        Settings, the preset's own defaults otherwise."""
        W, H = self.W, self.H
        def u(n): return int(n * H / 1080)
        pygame.draw.rect(surface, C["panel"],  r, border_radius=12)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=12)

        hd_s = self.fnt["bold"].render(f"Selected Preset ({self.selected_preset})",
                                       True, C["text"])
        surface.blit(hd_s, (r.x + u(14), r.y + u(10)))

        badge_txt = "● CUSTOMIZED" if self.customized else "DEFAULT PRESET"
        badge_col = C["orange"] if self.customized else C["accent"]
        bd_s = self.fnt["tag"].render(badge_txt, True, C["white"])
        bd_r = pygame.Rect(0, 0, bd_s.get_width() + u(16), bd_s.get_height() + u(8))
        bd_r.topright = (r.right - u(12), r.y + u(8))
        pygame.draw.rect(surface, badge_col, bd_r, border_radius=u(6))
        surface.blit(bd_s, bd_s.get_rect(center=bd_r.center))

        chips = [(spec["label"], self._fmt_chip(spec)) for spec in self.param_schema]
        chips.append(("Session Duration", self.adv_duration))
        if self.game_name in GAMES_USING_SPEED:
            chips.append(("Speed", self.adv_speed))

        cy = r.y + u(10) + hd_s.get_height() + u(8)
        cx = r.x + u(14)
        row_h = u(22)
        max_x = r.right - u(14)
        for label, val in chips:
            txt = f"{label}: {val}"
            ts  = self.fnt["small"].render(txt, True, C["sub"])
            if cx + ts.get_width() > max_x:
                cx = r.x + u(14)
                cy += row_h
            surface.blit(ts, (cx, cy))
            cx += ts.get_width() + int(22 * W / 1920)

    @staticmethod
    def _fmt_unit(shown, unit):
        # "%"/"°" read naturally butted against the number; any worded unit
        # (lemons, px/s, pts, hits...) needs a space to stay readable.
        sep = "" if unit in ("%", "°", "") else " "
        return f"{shown}{sep}{unit}"

    def _fmt_chip(self, spec):
        val = self.custom_params.get(spec["key"], spec["presets"].get(self.selected_preset))
        scale = spec.get("scale")
        shown = val / scale if scale else val
        if isinstance(shown, float) and shown.is_integer():
            shown = int(shown)
        elif isinstance(shown, float):
            shown = round(shown, 1)
        return self._fmt_unit(shown, spec["unit"])

    # ── Advanced Settings (separate screen, spec section 2) ────────────────────

    def _draw_advanced_settings(self, surface, area, C):
        W, H = self.W, self.H
        def u(n): return int(n * H / 1080)
        lx = int(36 * W / 1920)
        rw = W - lx * 2

        if self.game_name:
            gi_s = self.fnt["small"].render(
                f"Editing: {self.selected_preset} preset for {self.game_name}", True, C["sub"])
            surface.blit(gi_s, (lx, area.y + u(4)))

        rows_r = pygame.Rect(lx, area.y + u(30), rw, area.height - u(96))
        pygame.draw.rect(surface, C["panel"],  rows_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], rows_r, 1, border_radius=12)

        self._adv_param_rects = []
        self._adv_speed_rects = []
        row_h   = u(46)
        col_val = int(260 * W / 1920)     # stepper column width
        cy      = rows_r.y + u(10)
        max_rows_y = rows_r.bottom - u(8)

        def stepper(y, value_text, key_for_rect=None, spec=None, kind=None):
            bw = int(34 * W / 1920)
            vw = col_val - bw * 2 - int(8 * W / 1920)
            x  = rows_r.right - int(14 * W / 1920) - col_val
            minus_r = pygame.Rect(x, y, bw, row_h - u(10))
            val_r   = pygame.Rect(x + bw + int(4 * W / 1920), y, vw, row_h - u(10))
            plus_r  = pygame.Rect(x + bw + vw + int(8 * W / 1920), y, bw, row_h - u(10))
            for rct, lbl in ((minus_r, "–"), (plus_r, "+")):
                pygame.draw.rect(surface, C["panel2"], rct, border_radius=8)
                pygame.draw.rect(surface, C["border"], rct, 1, border_radius=8)
                ls = self.fnt["bold"].render(lbl, True, C["text"])
                surface.blit(ls, ls.get_rect(center=rct.center))
            pygame.draw.rect(surface, C["bg2"], val_r, border_radius=8)
            pygame.draw.rect(surface, C["border"], val_r, 1, border_radius=8)
            vs = self.fnt["smallb"].render(value_text, True, C["text"])
            surface.blit(vs, vs.get_rect(center=val_r.center))
            if kind == "threshold":
                self._adv_threshold_minus, self._adv_threshold_plus = minus_r, plus_r
            elif kind == "duration":
                self._adv_dur_minus, self._adv_dur_plus = minus_r, plus_r
            elif spec is not None:
                self._adv_param_rects.append((minus_r, plus_r, spec))

        def row_label(text, y, desc=None):
            s = self.fnt["smallb"].render(text, True, C["text"])
            surface.blit(s, (rows_r.x + u(14), y + (row_h - u(10)) // 2 - s.get_height() // 2))

        # per-game parameters (the actual "Required Information" for this screen)
        for spec in self.param_schema:
            if cy + row_h > max_rows_y:
                break
            row_label(spec["label"], cy)
            row_label_bottom = cy + row_h
            cur = self.custom_params.get(spec["key"], spec["presets"].get(self.selected_preset))
            shown = cur / spec["scale"] if spec.get("scale") else cur
            if isinstance(shown, float) and shown.is_integer():
                shown = int(shown)
            elif isinstance(shown, float):
                shown = round(shown, 1)
            stepper(cy, self._fmt_unit(shown, spec["unit"]), spec=spec)
            pygame.draw.line(surface, C["border"], (rows_r.x + u(10), row_label_bottom),
                             (rows_r.right - u(10), row_label_bottom), 1)
            cy += row_h

        # generic: Speed (only for games that actually use it)
        if self.game_name in GAMES_USING_SPEED and cy + row_h <= max_rows_y:
            row_label("Speed", cy)
            bw = int(74 * W / 1920)
            x  = rows_r.right - int(14 * W / 1920) - (bw * 3 + int(16 * W / 1920))
            self._adv_speed_rects = []
            for opt in SPEED_OPTS:
                br = pygame.Rect(x, cy, bw, row_h - u(10))
                sel = (self.adv_speed == opt)
                pygame.draw.rect(surface, C["accent"] if sel else C["panel2"], br, border_radius=8)
                pygame.draw.rect(surface, C["accent"] if sel else C["border"], br, 1, border_radius=8)
                os_ = self.fnt["tag"].render(opt, True, C["white"] if sel else C["sub"])
                surface.blit(os_, os_.get_rect(center=br.center))
                self._adv_speed_rects.append((opt, br))
                x += bw + int(8 * W / 1920)
            pygame.draw.line(surface, C["border"], (rows_r.x + u(10), cy + row_h),
                             (rows_r.right - u(10), cy + row_h), 1)
            cy += row_h

        # generic: Threshold %
        if cy + row_h <= max_rows_y:
            row_label("Threshold %", cy)
            thr_now = round((sum(self.trial_results) / len(self.trial_results)
                             if self.trial_results else 0.0) * self.adv_threshold_pct / 100.0, 3)
            stepper(cy, f"{self.adv_threshold_pct}% = {thr_now:.3f}", kind="threshold")
            pygame.draw.line(surface, C["border"], (rows_r.x + u(10), cy + row_h),
                             (rows_r.right - u(10), cy + row_h), 1)
            cy += row_h

        # generic: Session Duration
        if cy + row_h <= max_rows_y:
            row_label("Session Duration", cy)
            try:
                dur_val = int(self.adv_duration.split()[0]) if self.adv_duration != "Custom" \
                    else int(self.adv_custom_dur or 120)
            except (ValueError, IndexError):
                dur_val = 120
            stepper(cy, f"{dur_val} s", kind="duration")
            cy += row_h

        # ── bottom actions ──────────────────────────────────────────
        btn_y = area.bottom - u(56)
        btn_h = u(46)
        gap   = int(16 * W / 1920)
        bw    = (rw - gap) // 2
        reset_r = pygame.Rect(lx, btn_y, bw, btn_h)
        apply_r = pygame.Rect(lx + bw + gap, btn_y, bw, btn_h)

        pygame.draw.rect(surface, C["panel2"], reset_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], reset_r, 1, border_radius=12)
        rs_s = self.fnt["sym25"].render("↺  Reset to Preset", True, C["sub"])
        surface.blit(rs_s, rs_s.get_rect(center=reset_r.center))
        self._adv_reset_rect = reset_r

        pygame.draw.rect(surface, C["accent"], apply_r, border_radius=12)
        ap2_s = self.fnt["sym25"].render("✓  Apply Changes  →", True, C["white"])
        surface.blit(ap2_s, ap2_s.get_rect(center=apply_r.center))
        self._adv_apply_rect = apply_r


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
