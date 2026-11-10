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

_IMG_DIR   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "images")
_img_cache: dict = {}


def _img(name, size=None):
    """A square icon from assets/images/, uniformly scaled to size x size
    and cached -- identical loader to therapist_dashboard.py's own _img(),
    so the Light/Dark toggle and Close button use the exact same asset
    pipeline as the rest of RecovR. Returns None (silently) if the file is
    missing, so a missing asset degrades gracefully instead of crashing."""
    key = (name, size)
    im = _img_cache.get(key)
    if im is None and key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            im = pygame.transform.smoothscale(raw, (size, size)) if size else raw
        except Exception:
            im = None
        _img_cache[key] = im
    return im


_img_bbox_cache: dict = {}
_img_fit_cache: dict = {}


def _img_fit(name, w, h):
    """Like _img(), but for assets that bake extra transparent padding into
    a square canvas -- crops to the actual opaque content once, then scales
    it to fit within w x h preserving its own aspect ratio. Identical to
    therapist_dashboard.py's own _img_fit()."""
    key = (name, w, h)
    if key in _img_fit_cache:
        return _img_fit_cache[key]
    cropped = _img_bbox_cache.get(name)
    if cropped is None and name not in _img_bbox_cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
        except Exception:
            cropped = None
        _img_bbox_cache[name] = cropped
    if cropped is None:
        _img_fit_cache[key] = None
        return None
    cw, ch = cropped.get_size()
    scale = min(w / cw, h / ch)
    result = pygame.transform.smoothscale(cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
    _img_fit_cache[key] = result
    return result


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
# unaffected). Games not listed here (Whack-a-Mole Twist) have not been
# individually audited for overridable constants, so they get no
# game-specific rows -- only the generic Speed control that already applies
# to the games listed in GAMES_USING_SPEED.
GAME_PARAM_SCHEMA = {
    "Basketball": [
        {"key": "bb_goal",       "label": "Target Score",       "unit": "pts", "is_goal": True,
         "min": 5,  "max": 30,  "step": 1,
         "presets": {"Easy": 10,   "Medium": 15,   "Hard": 20}},
        {"key": "bb_zone_width", "label": "Target Zone Size",   "unit": "%",
         "min": 5,  "max": 35,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 25,   "Medium": 16,   "Hard": 9}},
    ],
    "Lemonade": [
        {"key": "lem_target",         "label": "Lemons Required",         "unit": "lemons", "is_goal": True,
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
        {"key": "pt_goal",            "label": "Tiles Required",            "unit": "tiles", "is_goal": True,
         "min": 10,  "max": 80,  "step": 1,
         "presets": {"Easy": 20,    "Medium": 30,   "Hard": 40}},
        {"key": "pt_flex_threshold",  "label": "Finger Flexion Threshold",  "unit": "%",
         "min": 15,  "max": 85,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 35,    "Medium": 50,   "Hard": 65}},
        {"key": "pt_spawn_rate",      "label": "Tile Spawn Interval",       "unit": "s",
         "min": 0.2, "max": 2.0, "step": 0.05,
         "presets": {"Easy": 1.0,  "Medium": 0.7,  "Hard": 0.45}},
    ],
    "Apple Catching": [
        {"key": "ac_goal",        "label": "Apples Required",             "unit": "apples", "is_goal": True,
         "min": 5,   "max": 60,   "step": 1,
         "presets": {"Easy": 15,    "Medium": 25,    "Hard": 35}},
        {"key": "ac_apple_speed", "label": "Apple Falling Speed",          "unit": "px/s",
         "min": 100, "max": 800,  "step": 10,
         "presets": {"Easy": 260,   "Medium": 380,   "Hard": 520}},
        {"key": "ac_move_speed",  "label": "Basket Movement Sensitivity",  "unit": "px/s",
         "min": 300, "max": 1500, "step": 10,
         "presets": {"Easy": 750,   "Medium": 900,   "Hard": 1050}},
    ],
    "Key and Lock": [
        {"key": "kl_goal",      "label": "Locks Required",          "unit": "locks", "is_goal": True,
         "min": 5,   "max": 40,  "step": 1,
         "presets": {"Easy": 10,   "Medium": 15,   "Hard": 20}},
        {"key": "kl_tolerance", "label": "Wrist Angle Tolerance",   "unit": "°",
         "min": 2,   "max": 30,  "step": 1,
         "presets": {"Easy": 15,   "Medium": 8,    "Hard": 3}},
        {"key": "kl_hold_time", "label": "Required Hold Duration", "unit": "s",
         "min": 0.2, "max": 4.0, "step": 0.1,
         # Uniform 2 continuous seconds across every difficulty, per spec --
         # still overridable here.
         "presets": {"Easy": 2.0,  "Medium": 2.0,  "Hard": 2.0}},
    ],
    "Catch 'n Grab": [
        {"key": "cg_goal", "label": "Objects Required", "unit": "objects", "is_goal": True,
         "min": 5,  "max": 60,  "step": 1,
         "presets": {"Easy": 15,   "Medium": 25,   "Hard": 35}},
    ],
    "Steady Aim": [
        {"key": "sa_goal",       "label": "Target Shots Required",  "unit": "shots", "is_goal": True,
         "min": 3,   "max": 25,   "step": 1,
         "presets": {"Easy": 8,     "Medium": 10,   "Hard": 12}},
        {"key": "sa_circle_r",   "label": "Aim Tolerance",          "unit": "px",
         "min": 30,  "max": 160,  "step": 5,
         "presets": {"Easy": 120,   "Medium": 80,   "Hard": 45}},
        {"key": "sa_cursor_spd", "label": "Cursor Sensitivity",    "unit": "",
         "min": 500, "max": 1500, "step": 10,
         "presets": {"Easy": 900,   "Medium": 1000, "Hard": 1100}},
        {"key": "sa_hold_time",  "label": "Required Hold Duration","unit": "s",
         "min": 0.5, "max": 4.0,  "step": 0.1,
         "presets": {"Easy": 3.0,   "Medium": 3.0,  "Hard": 3.0}},
        {"key": "sa_arrows",     "label": "Arrows Available",      "unit": "arrows",
         "min": 5,   "max": 40,   "step": 1,
         "presets": {"Easy": 20,    "Medium": 16,   "Hard": 14}},
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
        {"key": "ftc_target_cats",   "label": "Cats to Feed",              "unit": "cats", "is_goal": True,
         "min": 3,    "max": 15,   "step": 1,
         "presets": {"Easy": 5,     "Medium": 7,    "Hard": 10}},
    ],
    "Plant the Garden": [
        {"key": "ptg_goal",            "label": "Plants to Grow",            "unit": "plants", "is_goal": True,
         "min": 3,    "max": 25,   "step": 1,
         "presets": {"Easy": 5,     "Medium": 10,   "Hard": 15}},
        {"key": "ptg_grip_threshold",  "label": "Grip Threshold",            "unit": "%",
         "min": 15,   "max": 85,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 45,   "Hard": 60}},
        {"key": "ptg_flex_threshold",  "label": "Finger Flexion Threshold",  "unit": "%",
         "min": 10,   "max": 70,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 20,    "Medium": 30,   "Hard": 40}},
        {"key": "ptg_move_deadzone",   "label": "Wrist Movement Sensitivity","unit": "%",
         "min": 2,    "max": 25,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 5,     "Medium": 8,    "Hard": 12}},
        {"key": "ptg_zone_tolerance",  "label": "Positioning Tolerance",     "unit": "px",
         "min": 40,   "max": 140,  "step": 5,
         "presets": {"Easy": 130,   "Medium": 100,  "Hard": 70}},
        {"key": "ptg_water_hold",      "label": "Watering Hold Duration",    "unit": "s",
         "min": 0.5,  "max": 3.0,  "step": 0.1,
         "presets": {"Easy": 0.8,   "Medium": 1.2,  "Hard": 1.6}},
    ],
}
# Games that read the generic Speed (Slow/Normal/Fast) setting at all --
# shown as its own Advanced Settings row only for these (showing it for a
# game that ignores it would be a non-functional control).
GAMES_USING_SPEED = {"Basketball", "Piano Tiles"}


# ── CalibrationWindow ──────────────────────────────────────────────────────────

class CalibrationWindow:

    def __init__(self, width, height, game_type, game_name=None, dark_mode=True,
                 reused_sensors=None):
        self.W         = width
        self.H         = height
        # game_type is normally a single sensor-type string (unchanged,
        # single-pass calibration for every existing game). Passing a LIST
        # instead opts into sequential multi-sensor calibration -- each
        # sensor runs through the exact same sensitivity->countdown->
        # recording->trial_done(x3) phases, one after another, before a
        # single combined Results screen. Only "Plant the Garden" is
        # launched with a list today (see therapist_dashboard.py); every
        # other game's single-string call site, and everything below that
        # only ever sees len(self.game_types) == 1, is unaffected.
        self.game_types = list(game_type) if isinstance(game_type, (list, tuple)) else [game_type]
        self.sensor_idx = 0
        self.game_type  = self.game_types[0]
        self.game_name  = game_name            # specific game, e.g. "Lemonade" -- drives
                                               # which Advanced Settings rows are shown
        self.dark_mode = dark_mode
        self.cfg       = SENSOR_CFG.get(self.game_type, SENSOR_CFG["Grip Strength"])
        self.param_schema = GAME_PARAM_SCHEMA.get(game_name, [])
        # Multi-sensor only: each finished sensor's own trial bucket, and the
        # flat per-sensor rows _accept_multi_sensor() builds for saving one DB
        # row per sensor. Both stay empty for every single-sensor game.
        #
        # reused_sensors (therapist_dashboard.py's session-scoped calibration
        # cache -- see _launch_calibration()) pre-seeds sensor_results with
        # sensor types the therapist chose NOT to recalibrate this time, in
        # the exact {"sensor_name","trials","average"} shape _finish_sensor()
        # itself produces. Nothing below the constructor needs to know
        # whether a sensor_results entry came from a live trial just now or
        # a reused one from earlier in the same therapy session -- _accept()/
        # _accept_multi_sensor() already read every sensor from this one
        # dict regardless.
        self.sensor_results      = dict(reused_sensors) if reused_sensors else {}
        self.multi_sensor_results = []
        # Which sensors were pre-seeded (never actually run live this
        # window) -- therapist_dashboard.py uses this to avoid writing a
        # fresh calibrations DB row for a sensor nothing was just measured
        # for (see its win.done handling).
        self._initially_reused_sensors = set(self.sensor_results.keys())

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

        # ── touch-aware scaling ─────────────────────────────────────────
        # Every size/position in this window used to scale off a flat
        # H/1080 (or W/1920) ratio, which is correct for a 1080p desktop
        # window but makes everything roughly 44% of its intended size on
        # the actual 800x480 touch panel this runs on in production --
        # that undersizing was the root cause of the "too small to read"
        # complaints. Below a touch-sized window, scale against a much
        # smaller reference (400 tall / 680 wide) instead of 1080/1920 --
        # deliberately well past a bare 2x fix (an earlier pass at 512/854
        # still read as too small on the physical 7" panel), capped so a
        # taller touch window doesn't blow up disproportionately; a genuine
        # desktop-sized window (height > 820) keeps the original H/1080
        # behaviour untouched.
        self._touch = height <= 820
        self._FS    = min(height / 400.0, 1.7) if self._touch else (height / 1080.0)
        self._FSW   = min(width  / 680.0, 1.7) if self._touch else (width  / 1920.0)

        # ── fonts ─────────────────────────────────────────────────────
        H = height
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(name): return os.path.join(_fd, name)
        self.fnt = {
            "title":  pygame.font.Font(_F("FjallaOne-Regular.ttf"),    self._sc(44)),
            "sub":    pygame.font.Font(_F("Sora-Light.ttf"),            self._sc(27)),
            "body":   pygame.font.Font(_F("Lexend-Regular.ttf"),        self._sc(25)),
            "bold":   pygame.font.Font(_F("Lexend-SemiBold.ttf"),       self._sc(25)),
            "small":  pygame.font.Font(_F("Lexend-Light.ttf"),          self._sc(21)),
            "smallb": pygame.font.Font(_F("Lexend-Medium.ttf"),         self._sc(21)),
            "big":    pygame.font.Font(_F("GravitasOne-Regular.ttf"),   self._sc(86)),
            "big2":   pygame.font.Font(_F("GravitasOne-Regular.ttf"),   self._sc(42)),
            "med":    pygame.font.Font(_F("FjallaOne-Regular.ttf"),     self._sc(42)),
            "tag":    pygame.font.Font(_F("Lexend-Medium.ttf"),         self._sc(20)),
            "head2":  pygame.font.Font(_F("Lexend-SemiBold.ttf"),       self._sc(25)),
        }
        self._title_font_path = _F("FjallaOne-Regular.ttf")
        self._small_font_path = _F("Lexend-Light.ttf")
        self._bold_font_path  = _F("Lexend-SemiBold.ttf")
        self._sub_font_path   = _F("Sora-Light.ttf")
        self._fit_font_cache  = {}

        # ── interaction rects (updated each draw) ─────────────────────
        self._begin_rect        = pygame.Rect(0, 0, 1, 1)
        self._cancel_rect       = pygame.Rect(0, 0, 1, 1)
        self._accept_rect       = pygame.Rect(0, 0, 1, 1)
        self._retry_rect        = pygame.Rect(0, 0, 1, 1)
        self._toggle_rect       = pygame.Rect(0, 0, 1, 1)
        self._preset_card_rects = {}          # {"Easy": Rect, ...}
        self._adv_open_rect     = pygame.Rect(0, 0, 1, 1)   # "Advanced Settings" button (results screen)

        # ── Results screen vertical scroll ──────────────────────────────
        # The results screen's content (banner + results card + difficulty
        # cards + preset summary) can be taller than the 800x480 panel --
        # scrolled, not shrunk, per spec. Drag-to-scroll needs real motion
        # tracking (down -> motion -> up) that the rest of this file's
        # fire-on-down click model doesn't have, so it's handled as its own
        # small state machine, scoped to pointer-downs that start inside
        # the results viewport -- every other button/phase keeps its
        # original immediate fire-on-down behaviour, untouched.
        self._results_scroll_y   = 0
        self._results_content_h  = 0
        self._results_viewport   = pygame.Rect(0, 0, 1, 1)
        self._scroll_drag_active   = False   # a pointer-down started inside the viewport
        self._scroll_is_dragging   = False   # that pointer has since moved past the drag threshold
        self._scroll_drag_start_pos   = (0, 0)
        self._scroll_drag_start_scroll = 0
        self._scroll_pending_tap_pos  = None  # resolved as a real tap only if released without dragging
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

        # If every sensor (or a leading run of them) was pre-seeded via
        # reused_sensors, skip straight past their live trials -- lands on
        # the first sensor that still needs calibrating, or straight into
        # Results if the whole game_types list was reused.
        if self.sensor_results:
            self._advance_sensor_idx(0)

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

    # ── touch-aware scaling helpers (see __init__) ─────────────────────────────

    def _sc(self, px):
        """Scale a height-relative size/position value for the actual window."""
        return max(1, int(px * self._FS))

    def _scw(self, px):
        """Scale a width-relative size/position value for the actual window."""
        return max(1, int(px * self._FSW))

    def _tt(self, px):
        """Like _sc, but floors interactive controls at a fingertip-sized
        50px on the touch panel (desktop/non-touch is unaffected)."""
        v = int(px * self._FS)
        return max(v, 50) if self._touch else v

    def _fit_text(self, font_path, base_size, text, max_w, color, min_size):
        """Render `text` at base_size, shrinking in steps only if this
        particular string is too wide for max_w -- every shorter string
        through the same call site keeps its full, normal size."""
        size = base_size
        while True:
            key = (font_path, size)
            f = self._fit_font_cache.get(key)
            if f is None:
                f = pygame.font.Font(font_path, size)
                self._fit_font_cache[key] = f
            s = f.render(text, True, color)
            if s.get_width() <= max_w or size <= min_size:
                return s
            size -= 2

    def _fit_title(self, text, max_w, color, min_size=20):
        """Header title -- shrinks only if too wide for the room actually
        left beside it (e.g. a long sensor name next to the Light/Dark
        toggle + Close button)."""
        return self._fit_text(self._title_font_path, self._sc(44), text, max_w, color, min_size)

    # ── event handling ────────────────────────────────────────────────────────

    def handle_event(self, event):
        # Results-screen drag-to-scroll needs real down -> motion -> up
        # tracking that this file's fire-on-down click model otherwise
        # doesn't have -- it's handled as its own small state machine,
        # scoped to pointer-downs starting inside the results viewport
        # (see _handle_results_scroll_event). Everything else below is
        # the original immediate fire-on-down behaviour, untouched.
        if self.phase == "results" and self._handle_results_scroll_event(event):
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
            if self._begin_rect.collidepoint(pos):
                self._start_countdown()

        elif self.phase == "results":
            # Only the fixed footer buttons reach here -- taps inside the
            # scrollable viewport (e.g. the preset cards) are handled by
            # _handle_results_scroll_event/_dispatch_results_tap instead,
            # so a card that happens to be scrolled near the footer can
            # never be hit by a tap actually meant for a footer button.
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

    def _handle_results_scroll_event(self, event):
        """Results-screen drag-to-scroll state machine. Returns True if this
        event was consumed (the generic handler above must not also act on
        it). A pointer-down inside the results viewport starts as a PENDING
        tap; if it moves past a small threshold before release, it becomes
        a scroll drag instead and the tap is cancelled -- released without
        ever crossing that threshold, it fires as a real tap via
        _dispatch_results_tap, same as every other button in this file."""
        if event.type == pygame.MOUSEWHEEL:
            mp = pygame.mouse.get_pos()
            mp = builtins.normalise_pos(mp) if hasattr(builtins, "normalise_pos") else mp
            if self._results_viewport.collidepoint(mp):
                max_scroll = max(0, self._results_content_h - self._results_viewport.height)
                self._results_scroll_y = max(0, min(max_scroll,
                                              self._results_scroll_y - event.y * self._sc(40)))
                return True
            return False

        pos, down = None, False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = builtins.normalise_pos(event.pos) if hasattr(builtins, "normalise_pos") else event.pos
            down = True
        elif event.type == pygame.FINGERDOWN:
            pos = (int(event.x * self.W), int(event.y * self.H))
            down = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = builtins.normalise_pos(event.pos) if hasattr(builtins, "normalise_pos") else event.pos
        elif event.type == pygame.FINGERUP:
            pos = (int(event.x * self.W), int(event.y * self.H))
        elif event.type == pygame.MOUSEMOTION:
            pos = builtins.normalise_pos(event.pos) if hasattr(builtins, "normalise_pos") else event.pos
        elif event.type == pygame.FINGERMOTION:
            pos = (int(event.x * self.W), int(event.y * self.H))
        else:
            return False

        if down:
            if not self._results_viewport.collidepoint(pos):
                return False
            self._scroll_drag_active       = True
            self._scroll_is_dragging       = False
            self._scroll_drag_start_pos    = pos
            self._scroll_drag_start_scroll = self._results_scroll_y
            self._scroll_pending_tap_pos   = pos
            return True

        if not self._scroll_drag_active:
            return False

        dx = pos[0] - self._scroll_drag_start_pos[0]
        dy = pos[1] - self._scroll_drag_start_pos[1]

        if event.type in (pygame.MOUSEMOTION, pygame.FINGERMOTION):
            if not self._scroll_is_dragging and (abs(dx) + abs(dy)) > 10:
                self._scroll_is_dragging     = True
                self._scroll_pending_tap_pos = None
            if self._scroll_is_dragging:
                max_scroll = max(0, self._results_content_h - self._results_viewport.height)
                self._results_scroll_y = max(0, min(max_scroll, self._scroll_drag_start_scroll - dy))
            return True

        # MOUSEBUTTONUP / FINGERUP -- resolve
        self._scroll_drag_active = False
        if not self._scroll_is_dragging and self._scroll_pending_tap_pos is not None:
            self._dispatch_results_tap(self._scroll_pending_tap_pos)
        self._scroll_is_dragging     = False
        self._scroll_pending_tap_pos = None
        return True

    def _dispatch_results_tap(self, pos):
        """A confirmed (non-drag) tap inside the results viewport -- only
        the preset cards live there."""
        for name, r in self._preset_card_rects.items():
            if r.collidepoint(pos):
                self._apply_preset(name)
                return

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
                    if len(self.game_types) > 1:
                        self._finish_sensor()
                    else:
                        self._enter_results()
                else:
                    self._start_countdown()

    # ── internal transitions ──────────────────────────────────────────────────

    def _finish_sensor(self):
        """Multi-sensor calibration only. Store the sensor just finished,
        then either move on to the next sensor that still needs calibrating
        (skipping any already reused -- see _advance_sensor_idx) or, once
        every sensor in self.game_types is accounted for, enter the one
        combined Results screen."""
        avg = sum(self.trial_results) / len(self.trial_results) if self.trial_results else 0.0
        self.sensor_results[self.game_type] = {
            "sensor_name": self.cfg["sensor_name"],
            "trials":      list(self.trial_results),
            "average":     round(avg, 4),
        }
        self._advance_sensor_idx(self.sensor_idx + 1)

    def _advance_sensor_idx(self, start_idx):
        """Move to the next sensor in game_types (from start_idx onward)
        that still needs live trials, skipping any sensor already present
        in self.sensor_results -- whether pre-seeded via reused_sensors at
        construction or just finished live in this same multi-sensor run.
        Lands that sensor on its own fresh "sensitivity" screen. Once every
        sensor is accounted for, enters the combined Results screen, first
        restoring self.trial_results from the LAST sensor in game_types
        order -- the same sensor whose trial_results _enter_results() would
        already be looking at right after a normal (fully live) run, so a
        partially- or fully-reused run drives _recommend_difficulty() / the
        Results screen's own trial display identically."""
        idx = start_idx
        while idx < len(self.game_types) and self.game_types[idx] in self.sensor_results:
            idx += 1
        if idx < len(self.game_types):
            self.sensor_idx     = idx
            self.game_type       = self.game_types[idx]
            self.cfg              = SENSOR_CFG.get(self.game_type, SENSOR_CFG["Grip Strength"])
            self.current_trial    = 0
            self.trial_results    = []
            self.phase             = "sensitivity"
            return
        last_sensor = self.game_types[-1]
        cached = self.sensor_results.get(last_sensor)
        if cached is not None:
            self.trial_results = list(cached["trials"])
        self.sensor_idx = len(self.game_types) - 1
        self.game_type   = last_sensor
        self.cfg          = SENSOR_CFG.get(self.game_type, SENSOR_CFG["Grip Strength"])
        self._enter_results()

    def _start_countdown(self):
        self.phase       = "countdown"
        self.countdown   = COUNTDOWN_STEPS
        self.countdown_t = 0.0

    def _enter_results(self):
        self.phase = "results"
        self._results_scroll_y = 0
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
        if len(self.game_types) > 1:
            self._accept_multi_sensor()
            return
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

    def _accept_multi_sensor(self):
        """Multi-sensor calibration only (len(self.game_types) > 1 -- today
        just Plant the Garden). Builds TWO things:
          - self.multi_sensor_results: one flat, save_calibration()-shaped
            row per sensor, so the dashboard can record one DB row per
            sensor exactly like a normal single-sensor calibration (no DB
            schema change needed).
          - self.calibration_result: the single combined dict the GAME
            itself reads. It also finally populates grip_rest/grip_max/
            wrist_min/wrist_max/flex_threshold from this session's real
            per-sensor trial data -- every game's existing
            _normalize_grip/_normalize_tilt already reads these exact keys
            with a hardcoded fallback, so this only ever takes effect for a
            game that actually goes through this multi-sensor path.
        """
        threshold_pct = self.adv_threshold_pct
        shared_params = {
            "threshold_pct": threshold_pct,
            "speed":         self.adv_speed,
            "duration":      self.adv_duration,
            "difficulty":    self.adv_difficulty,
            "sensitivity":   self.sensitivity,
        }
        shared_params.update(self.custom_params)   # game-specific overrides, if any

        self.multi_sensor_results = []
        sensors_block = {}
        extra = {}
        for sensor_type in self.game_types:
            data = self.sensor_results.get(sensor_type) or {
                "sensor_name": SENSOR_CFG[sensor_type]["sensor_name"], "trials": [], "average": 0.0}
            avg = data["average"]
            thr = round(avg * threshold_pct / 100.0, 4)
            row_params = dict(shared_params)
            row_params["threshold"] = thr
            self.multi_sensor_results.append({
                "game_type":   sensor_type,
                "game_name":   self.game_name,
                "sensor":      data["sensor_name"],
                "sensitivity": self.sensitivity,
                "trials":      data["trials"],
                "average":     avg,
                "threshold":   thr,
                "preset":      self.selected_preset,
                "recommended": self.recommended_preset,
                "customized":  self.customized,
                "dark_mode":   self.dark_mode,
                "params":      row_params,
            })
            sensors_block[sensor_type] = {"average": avg, "threshold": thr, "trials": data["trials"]}

            if sensor_type == "Grip Strength":
                extra["grip_rest"] = 0.0
                extra["grip_max"]  = max(avg, 0.05)
            elif sensor_type == "Wrist Rotation":
                extra["wrist_min"] = -max(avg, 0.05)
                extra["wrist_max"] =  max(avg, 0.05)
            elif sensor_type == "Finger Flexion":
                extra["flex_threshold"] = thr if thr > 0 else input_handler.FLEX_THRESH

        primary = sensors_block.get(self.game_type, {"average": 0.0, "threshold": 0.0, "trials": []})
        merged_params = dict(shared_params)
        merged_params["threshold"] = primary["threshold"]

        self.calibration_result = {
            "game_type":   "Multi-skill",
            "game_name":   self.game_name,
            "sensor":      " + ".join(SENSOR_CFG[t]["sensor_name"] for t in self.game_types),
            "sensitivity": self.sensitivity,
            "trials":      primary["trials"],
            "average":     primary["average"],
            "threshold":   primary["threshold"],
            "preset":      self.selected_preset,
            "recommended": self.recommended_preset,
            "customized":  self.customized,
            "dark_mode":   self.dark_mode,
            "params":      merged_params,
            "sensors":     sensors_block,
            **extra,
        }
        self.done = True

    def _retry(self):
        self.current_trial = 0
        self.trial_results = []
        self.custom_params = {}
        self.customized     = False
        self.phase         = "sensitivity"
        # Multi-sensor: Results only shows once every sensor is done, so
        # Retry restarts the whole sequence from the first sensor.
        self.sensor_idx      = 0
        self.game_type       = self.game_types[0]
        self.cfg              = SENSOR_CFG.get(self.game_type, SENSOR_CFG["Grip Strength"])
        self.sensor_results   = {}

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self, surface):
        C = self.C
        W, H = self.W, self.H

        surface.fill(C["bg"])

        # ── top bar ───────────────────────────────────────────────────
        top_h = self._sc(68)
        pygame.draw.rect(surface, C["panel"], (0, 0, W, top_h))
        pygame.draw.line(surface, C["border"], (0, top_h), (W, top_h), 1)

        _bw = self._tt(40)
        _bh = self._tt(40)

        # ── Light/Dark toggle + Close button geometry, upper right, in
        # that order -- computed FIRST so the title (below) knows exactly
        # how much room is actually left beside it and can shrink a long
        # sensor name instead of running underneath these controls.
        pad_r  = self._scw(20)
        gap    = self._scw(10)
        row_h  = _bh
        tog_w  = row_h * 2
        if self.phase != "advanced":
            close_r = pygame.Rect(W - pad_r - row_h, top_h // 2 - row_h // 2, row_h, row_h)
            toggle_right = close_r.left - gap
        else:
            close_r = None
            toggle_right = W - pad_r
        controls_left_x = toggle_right - tog_w

        if self.phase == "advanced":
            # Advanced Settings is its own screen (spec 2) -- its own header:
            # Back arrow, "Advanced Settings", selected game name. No X here
            # (that would cancel the whole calibration); Back returns to
            # Results instead, discarding only unapplied edits. Uses the
            # same back_button_therapist.png asset, at the same WIDE aspect
            # ratio therapist_dashboard.py's own back button uses it at (it's
            # a complete pill-shaped button with its own background baked
            # in, not a square glyph) -- not a Unicode arrow.
            back_w = self._tt(128)
            back_r = pygame.Rect(self._scw(20), top_h // 2 - _bh // 2, back_w, _bh)
            back_img = _img_fit("back_button_therapist.png", back_r.width, back_r.height)
            if back_img is not None:
                surface.blit(back_img, back_img.get_rect(center=back_r.center))
            else:
                pygame.draw.rect(surface, C["panel2"], back_r, border_radius=10)
                pygame.draw.rect(surface, C["border"], back_r, 1, border_radius=10)
                bk_s = self.fnt["bold"].render("Back", True, C["text"])
                surface.blit(bk_s, bk_s.get_rect(center=back_r.center))
            self._adv_back_rect = back_r
            self._cancel_rect = pygame.Rect(0, 0, 1, 1)

            title_s = self._fit_title("Advanced Settings",
                                       controls_left_x - back_r.right - self._scw(24), C["text"])
            surface.blit(title_s, (back_r.right + self._scw(16),
                                    top_h // 2 - title_s.get_height() // 2))
            if self.game_name:
                gn_avail = controls_left_x - (back_r.right + self._scw(16) + title_s.get_width()
                                               + self._scw(14)) - self._scw(10)
                if gn_avail > self._scw(40):
                    # Width-aware fit, not just a show/hide gate -- the toggle
                    # is drawn later in this same header row, so a subtitle
                    # left un-clamped here can run under it once the game
                    # name is long (e.g. "Steady Aim").
                    gn_s = self._fit_text(self._sub_font_path, self._sc(27), self.game_name,
                                           gn_avail, C["sub"], self._sc(16))
                    surface.blit(gn_s, (back_r.right + self._scw(16) + title_s.get_width()
                                         + self._scw(14),
                                         top_h // 2 - gn_s.get_height() // 2))
        else:
            title_txt = f"Sensor Calibration — {self.cfg['sensor_name']}"
            if len(self.game_types) > 1:
                title_txt += f"  ({self.sensor_idx + 1} of {len(self.game_types)})"
            title_s = self._fit_title(title_txt, controls_left_x - self._scw(32) - self._scw(16), C["text"])
            surface.blit(title_s, (self._scw(32),
                                    top_h // 2 - title_s.get_height() // 2))

        # ── Light/Dark toggle + Close button -- the EXACT same sliding
        # track+knob component and close_button.png asset as
        # therapist_dashboard.py's own top-right bar (see
        # _draw_top_right_bar there), not a separate implementation.
        if close_r is not None:
            close_img = _img("close_button.png", row_h)
            if close_img is not None:
                surface.blit(close_img, close_img.get_rect(center=close_r.center))
            else:
                pygame.draw.circle(surface, C["red"], close_r.center, row_h // 2)
            self._cancel_rect = close_r

        tr = pygame.Rect(controls_left_x, top_h // 2 - row_h // 2, tog_w, row_h)
        track_col = (34, 46, 66) if self.dark_mode else (210, 222, 240)
        pygame.draw.rect(surface, track_col, tr, border_radius=row_h // 2)
        pygame.draw.rect(surface, C["border"], tr, max(1, int(2 * self._FS)), border_radius=row_h // 2)
        knob_d  = row_h - self._sc(6)
        knob_cx = (tr.right - row_h // 2) if self.dark_mode else (tr.left + row_h // 2)
        knob_img = _img("dark_mode.png" if self.dark_mode else "light_mode.png", knob_d)
        if knob_img is not None:
            surface.blit(knob_img, knob_img.get_rect(center=(knob_cx, tr.centery)))
        else:
            pygame.draw.circle(surface, (255, 255, 255), (knob_cx, tr.centery), knob_d // 2)
        self._toggle_rect = tr

        # ── content ───────────────────────────────────────────────────
        content = pygame.Rect(0, top_h + self._sc(14),
                              W, H - top_h - self._sc(14))
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

    def _draw_live_monitor(self, surface, area, C, status, show_begin=False):
        """Flow layout (each row positioned from the actual rendered height
        of the row above it, not a fixed design-space offset table) so this
        never depends on hand-tuned constants staying in sync with the
        current font/card sizes -- it was exactly that kind of drift (fixed
        offsets calibrated for a smaller scale) that caused content to
        overflow the bottom of the 800x480 panel before. Live Reading /
        Peak Reading sit side by side (not stacked) specifically to use
        this screen's generous WIDTH and ease the tight HEIGHT budget."""
        W, H = self.W, self.H
        cx   = area.centerx
        lx   = self._scw(40)
        rw   = W - lx * 2
        is_wrist = self.game_type == "Wrist Rotation"
        status_col = {"Waiting": C["sub"], "Recording": C["yellow"],
                      "Completed": C["green"]}[status]

        cy = area.y + self._sc(6)

        # row 1 -- trial progress + status
        tl_s = self.fnt["head2"].render(f"Trial {self.current_trial + 1} of 3", True, C["text"])
        surface.blit(tl_s, (lx, cy))
        st_s = self.fnt["head2"].render(status, True, status_col)
        surface.blit(st_s, st_s.get_rect(topright=(lx + rw, cy)))
        cy += tl_s.get_height() + self._sc(5)

        # row 2 -- Live Reading / Peak Reading cards, SIDE BY SIDE. Grip/Flex
        # show the raw 0-1 sensor scale (no invented unit, no misleading
        # "%" -- same 3dp formatting the Results screen already uses).
        # Wrist Rotation shows the real calculated wrist angle in degrees
        # instead -- the SAME formula games/key_lock.py already uses to
        # turn tilt_x into an on-screen angle (tilt mapped linearly over
        # its -1..1 range to -90..+90 degrees), not a new/invented
        # conversion -- plus which direction (Left/Right) the wrist is
        # currently rotated toward. The existing abs()-based
        # live_value/peak_value that actually drive calibration
        # (trial_results, threshold calc) are untouched; this only changes
        # how that same data is laid out on screen.
        card_h   = self._sc(112)
        card_gap = self._scw(16)
        card_w   = (rw - card_gap) // 2
        live_r = pygame.Rect(lx, cy, card_w, card_h)
        peak_r = pygame.Rect(lx + card_w + card_gap, cy, card_w, card_h)
        cy += card_h + self._sc(5)

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
        row3_h = self._sc(22)
        if status == "Recording":
            remaining = max(0.0, RECORD_DURATION - self.record_t)
            frac = 1.0 - (remaining / RECORD_DURATION if RECORD_DURATION else 0.0)
            bar_w = rw - self._scw(90)
            bar_h = self._sc(18)
            self._draw_bar(surface, lx, cy + (row3_h - bar_h) // 2, bar_w, bar_h, frac, C)
            tm_s = self.fnt["bold"].render(f"{remaining:.1f}s", True, C["text"])
            surface.blit(tm_s, (lx + bar_w + self._scw(14), cy + (row3_h - tm_s.get_height()) // 2))
        elif status == "Waiting" and self.phase == "countdown":
            surface.blit(self.fnt["bold"].render(
                f"Starts in {self.countdown}s", True, C["sub"]), (lx, cy))
        elif status == "Completed":
            surface.blit(self.fnt["bold"].render(
                "Trial saved", True, C["green"]), (lx, cy))
        cy += row3_h + self._sc(5)

        # row 4 -- real controller status only. The Simulation Mode
        # instructional hint (the "[ Hold SPACE to simulate grip ]"-style
        # text) is UI narration, not calibration data -- removed per the
        # instructional-cleanup request. Test Mode / the keyboard fallback
        # itself is untouched (sensors/input_handler's own simulated-input
        # path keeps working exactly as before); this row simply has nothing
        # to show while it's active, so its space is reclaimed instead of
        # being spent on a row stating the obvious.
        if input_handler.connected:
            ctrl_s = self._fit_text(self._small_font_path, self._sc(21),
                                    "Controller Connected", rw, C["green"], self._sc(14))
            surface.blit(ctrl_s, (lx, cy))
            cy += ctrl_s.get_height() + self._sc(5)

        # row 5 -- trial indicators (completed / active / pending)
        dot_r = self._sc(10)   # must match _draw_trial_dots' own internal dot_r
        label_h = self.fnt["small"].get_height()
        self._draw_trial_dots(surface, cx, cy + dot_r, C, current=self.current_trial)
        cy += dot_r * 2 + self._sc(4) + label_h + self._sc(5)

        # row 6 -- Begin Calibration (pre-trial-1 only), touch-friendly size
        if show_begin:
            begin_h = self._tt(40)   # _tt floors to a 50px touch target regardless
            begin_r = pygame.Rect(cx - self._scw(190), cy, self._scw(380), begin_h)
            pygame.draw.rect(surface, C["accent"], begin_r, border_radius=14)
            b_s = self.fnt["bold"].render("Begin Calibration", True, C["white"])
            surface.blit(b_s, b_s.get_rect(center=begin_r.center))
            self._begin_rect = begin_r
        else:
            self._begin_rect = pygame.Rect(0, 0, 1, 1)

    def _draw_reading_card(self, surface, r, C, label, text, accent,
                           font=None, tag=None, tag_col=None):
        W, H = self.W, self.H
        pygame.draw.rect(surface, C["panel"],  r, border_radius=14)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=14)
        pad = self._scw(14)
        lbl_s = self.fnt["bold"].render(label, True, C["sub"])
        surface.blit(lbl_s, (r.x + pad, r.y + self._sc(7)))
        val_font = font or self.fnt["big"]
        val_col  = accent if text != "—" else C["sub"]
        val_s = val_font.render(text, True, val_col)
        val_y = r.y + self._sc(7) + lbl_s.get_height() + self._sc(4)
        surface.blit(val_s, (r.x + pad, val_y))
        if tag:
            tag_s = self.fnt["bold"].render(tag, True, tag_col or C["sub"])
            surface.blit(tag_s, (r.x + pad + val_s.get_width() + self._scw(18),
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
        lx = self._scw(36)
        rw = W - lx * 2

        def u(n): return self._sc(n)

        # The bottom actions (Retry / Advanced Settings / Accept & Continue)
        # are fixed -- reachable even when the content above is scrolled --
        # so their footer strip is reserved FIRST, and the scrollable
        # viewport is sized from whatever room is actually left.
        btn_h    = self._tt(54)
        footer_h = btn_h + u(22)
        viewport = pygame.Rect(area.x, area.y, area.width, area.height - footer_h)
        self._results_viewport = viewport

        max_scroll = max(0, self._results_content_h - viewport.height)
        self._results_scroll_y = max(0, min(self._results_scroll_y, max_scroll))

        prev_clip = surface.get_clip()
        surface.set_clip(viewport)

        # ── A. completion banner ───────────────────────────────────────
        content_top = viewport.y + u(14) - self._results_scroll_y
        y = content_top
        ban_h = u(100)
        ban_r = pygame.Rect(lx, y, rw, ban_h)
        pygame.draw.rect(surface, C["panel"], ban_r, border_radius=12)
        pygame.draw.rect(surface, C["green"], ban_r, 2, border_radius=12)
        hd_s = self.fnt["head2"].render("Calibration Complete!", True, C["green"])
        surface.blit(hd_s, (ban_r.x + u(16), ban_r.y + u(12)))
        sub_s = self.fnt["small"].render(
            "All required sensors have been successfully calibrated.",
            True, C["sub"])
        surface.blit(sub_s, (ban_r.x + u(16),
                              ban_r.y + u(12) + hd_s.get_height() + u(2)))
        y += ban_h + u(16)

        # ── B. Calibration Results card ────────────────────────────────
        res_h = u(230)
        res_r = pygame.Rect(lx, y, rw, res_h)
        pygame.draw.rect(surface, C["panel"],  res_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], res_r, 1, border_radius=12)

        rh_s = self.fnt["bold"].render("Calibration Results", True, C["text"])
        surface.blit(rh_s, (res_r.x + u(14), res_r.y + u(8)))
        sn_s = self._fit_text(self._small_font_path, self._sc(18),
                               f"Sensor: {self.cfg['sensor_name']} ({self.game_type})",
                               res_r.width - u(28), C["sub"], self._sc(12))
        surface.blit(sn_s, (res_r.x + u(14), res_r.y + u(8) + rh_s.get_height() + u(2)))

        bar_x  = res_r.x + u(100)
        bar_w  = res_r.width - u(100) - u(100)
        bar_h  = u(18)
        by_cur = res_r.y + u(8) + rh_s.get_height() + u(2) + sn_s.get_height() + u(10)
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

        # Real content height (independent of this frame's scroll offset,
        # so next frame's clamping/scrollbar math is correct), then restore
        # the surface's own clip and draw the fixed footer below it.
        # content_top already has -self._results_scroll_y baked in, so
        # y - content_top is already scroll-independent on its own; adding
        # scroll_y again here (an earlier bug) made content_h grow by
        # whatever it was just scrolled by, compounding on every frame the
        # view wasn't at the very top.
        self._results_content_h = y - content_top
        surface.set_clip(prev_clip)

        if max_scroll > 0:
            self._draw_scrollbar(surface, viewport, C, max_scroll)

        # ── E. bottom actions -- fixed below the viewport, never scrolls ──
        btn_y = viewport.bottom + u(12)
        gap   = self._scw(14)
        bw    = (rw - gap * 2) // 3
        retry_r = pygame.Rect(lx, btn_y, bw, btn_h)
        adv_r   = pygame.Rect(lx + bw + gap, btn_y, bw, btn_h)
        acc_r   = pygame.Rect(lx + 2 * (bw + gap), btn_y, bw, btn_h)

        btn_font_size = self._sc(25)
        btn_max_w     = bw - u(16)

        pygame.draw.rect(surface, C["panel2"], retry_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], retry_r, 1, border_radius=12)
        rt_s = self._fit_text(self._bold_font_path, btn_font_size, "Retry Calibration",
                               btn_max_w, C["sub"], self._sc(16))
        surface.blit(rt_s, rt_s.get_rect(center=retry_r.center))
        self._retry_rect = retry_r

        pygame.draw.rect(surface, C["panel2"], adv_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], adv_r, 1, border_radius=12)
        av2_s = self._fit_text(self._bold_font_path, btn_font_size, "Advanced Settings",
                                btn_max_w, C["text"], self._sc(16))
        surface.blit(av2_s, av2_s.get_rect(center=adv_r.center))
        self._adv_open_rect = adv_r

        pygame.draw.rect(surface, C["green"], acc_r, border_radius=12)
        ac_s = self._fit_text(self._bold_font_path, btn_font_size, "Accept & Continue",
                               btn_max_w, C["white"], self._sc(16))
        surface.blit(ac_s, ac_s.get_rect(center=acc_r.center))
        self._accept_rect = acc_r

    def _draw_difficulty_cards(self, surface, lx, ry, rw, ch, C):
        W, H  = self.W, self.H
        n     = len(PRESET_ORDER)
        gap   = self._scw(12)
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
            surface.blit(nm_s, (cr.x + self._scw(10), cr.y + self._sc(8)))
            next_y = cr.y + self._sc(8) + nm_s.get_height() + self._sc(4)

            if rec:
                # Its own row below the name, not overlapping it -- "RECOMMENDED"
                # is wide enough at this font size to cover a short name label
                # like "HARD" entirely if placed top-right beside it, and still
                # shrinks to fit this narrow a card as a last resort.
                rc_s = self._fit_text(self._bold_font_path, self._sc(20), "RECOMMENDED",
                                       cw - self._scw(16), C["white"], self._sc(12))
                rc_r = pygame.Rect(0, 0, rc_s.get_width() + self._scw(10),
                                   rc_s.get_height() + self._sc(4))
                rc_r.topleft = (cr.x + self._scw(10), next_y)
                pygame.draw.rect(surface, C["green"], rc_r, border_radius=self._sc(6))
                surface.blit(rc_s, rc_s.get_rect(center=rc_r.center))
                next_y = rc_r.bottom + self._sc(4)

            thr_val = round(DIFFICULTY_PRESETS[name]["threshold_pct"], 0)
            dt = f"Threshold {int(thr_val)}%  ·  {p['desc'].split('—')[0].strip()}"
            words, lines, cur = dt.split(), [], ""
            for w in words:
                test = (cur + " " + w).strip()
                if self.fnt["small"].size(test)[0] > cw - self._scw(20):
                    if cur: lines.append(cur)
                    cur = w
                else:
                    cur = test
            if cur: lines.append(cur)
            ty = next_y + self._sc(2)
            for ln in lines[:2]:
                ls = self.fnt["small"].render(ln, True, C["sub"])
                surface.blit(ls, (cr.x + self._scw(10), ty))
                ty += ls.get_height() + self._sc(2)

            self._preset_card_rects[name] = cr

    def _draw_preset_summary(self, surface, r, C):
        """Section C: compact chip row of the GAME's own parameters (not the
        generic threshold/speed/duration) for the currently selected preset
        -- customized values if the therapist edited any in Advanced
        Settings, the preset's own defaults otherwise."""
        W, H = self.W, self.H
        def u(n): return self._sc(n)
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
            cx += ts.get_width() + self._scw(22)

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
        def u(n): return self._sc(n)
        lx = self._scw(36)
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
        col_val = self._scw(260)     # stepper column width
        cy      = rows_r.y + u(10)
        max_rows_y = rows_r.bottom - u(8)

        def stepper(y, value_text, key_for_rect=None, spec=None, kind=None):
            bw = self._scw(34)
            vw = col_val - bw * 2 - self._scw(8)
            x  = rows_r.right - self._scw(14) - col_val
            minus_r = pygame.Rect(x, y, bw, row_h - u(10))
            val_r   = pygame.Rect(x + bw + self._scw(4), y, vw, row_h - u(10))
            plus_r  = pygame.Rect(x + bw + vw + self._scw(8), y, bw, row_h - u(10))
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
            bw = self._scw(74)
            x  = rows_r.right - self._scw(14) - (bw * 3 + self._scw(16))
            self._adv_speed_rects = []
            for opt in SPEED_OPTS:
                br = pygame.Rect(x, cy, bw, row_h - u(10))
                sel = (self.adv_speed == opt)
                pygame.draw.rect(surface, C["accent"] if sel else C["panel2"], br, border_radius=8)
                pygame.draw.rect(surface, C["accent"] if sel else C["border"], br, 1, border_radius=8)
                os_ = self.fnt["tag"].render(opt, True, C["white"] if sel else C["sub"])
                surface.blit(os_, os_.get_rect(center=br.center))
                self._adv_speed_rects.append((opt, br))
                x += bw + self._scw(8)
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

        # ── bottom actions ──────────────────────────────────────────
        btn_y = area.bottom - u(56)
        btn_h = u(46)
        gap   = self._scw(16)
        bw    = (rw - gap) // 2
        reset_r = pygame.Rect(lx, btn_y, bw, btn_h)
        apply_r = pygame.Rect(lx + bw + gap, btn_y, bw, btn_h)

        pygame.draw.rect(surface, C["panel2"], reset_r, border_radius=12)
        pygame.draw.rect(surface, C["border"], reset_r, 1, border_radius=12)
        rs_s = self.fnt["bold"].render("Reset to Preset", True, C["sub"])
        surface.blit(rs_s, rs_s.get_rect(center=reset_r.center))
        self._adv_reset_rect = reset_r

        pygame.draw.rect(surface, C["accent"], apply_r, border_radius=12)
        ap2_s = self.fnt["bold"].render("Apply Changes", True, C["white"])
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
            surface.blit(ls, (x + w + self._scw(14),
                               y + h // 2 - ls.get_height() // 2))

    def _draw_trial_dots(self, surface, cx, y, C, current=0):
        dot_r = self._sc(10)
        gap   = self._scw(56)
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
            surface.blit(ls, ls.get_rect(midtop=(dx, y + dot_r + self._sc(4))))

    def _draw_scrollbar(self, surface, viewport, C, max_scroll):
        """A thin, simple scroll-position indicator on the viewport's right
        edge -- only drawn when the results content is actually taller than
        the viewport, as a visual cue that more content is reachable by
        dragging."""
        w = self._scw(5)
        track = pygame.Rect(viewport.right - w - self._scw(4), viewport.y, w, viewport.height)
        pygame.draw.rect(surface, C["panel2"], track, border_radius=w // 2)
        frac = min(1.0, viewport.height / (self._results_content_h or viewport.height))
        thumb_h = max(self._sc(30), int(viewport.height * frac))
        thumb_y = viewport.y + int((viewport.height - thumb_h) *
                                    (self._results_scroll_y / max_scroll))
        pygame.draw.rect(surface, C["accent"], (track.x, thumb_y, w, thumb_h), border_radius=w // 2)
