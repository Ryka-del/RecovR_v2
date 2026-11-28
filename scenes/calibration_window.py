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
    sensitivity → prep → baseline → ready → countdown → recording → trial_done
        → (loop "ready"→"countdown"→"recording"→"trial_done" ×3) → complete → results
"""

import pygame
from scenes.drag_scroll import DragScroller
from scenes import calibration_validation as validation
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
        "sensor_name": "Tilt Sensor",
        "key_hint":    "[ Hold LEFT / RIGHT arrow to simulate rotation ]",
        "read":        lambda s: abs(s["tilt_x"]),
    },
}

# Whack-a-Mole and Tile Rush each calibrate their 5 fingers independently
# (one multi-sensor pass per finger, reusing the exact same sensitivity/
# countdown/recording/trial_done engine as every other sensor -- see
# MULTI_SENSOR_CALIBRATION below) instead of sharing the single generic
# "Finger Flexion" entry Garden Wonders/Steady Aim still use, so adding it
# can never change those two games' calibration.
_FINGER_FLEX_KEYS = [
    "Thumb Flexion", "Index Flexion", "Middle Flexion", "Ring Flexion", "Pinky Flexion",
]
for _i, _key in enumerate(_FINGER_FLEX_KEYS):
    SENSOR_CFG[_key] = {
        "sensor_name": f"{_key.split()[0]} Flex Sensor",
        "key_hint":    f"[ Hold number key {_i + 1} to simulate {_key.split()[0]} flex ]",
        "read":        (lambda s, _i=_i: s["finger_flex"][_i]),
    }
del _i, _key


def _toy_factory_vertical_read(s):
    """Toy Factory's "Wrist Vertical" calibration pass -- GENUINE MPU6050 Y
    axis on real hardware, never input_handler's own state["tilt_y"] (which
    carries the Flex Sensor there -- see games/steady_aim.py's own
    _vertical_raw(), duplicated here since this module shares no import
    point with games/*.py). In Test Mode (no BLE), state["tilt_y"] IS
    legitimately driven by the UP/DOWN arrow keys (see
    sensors/input_handler.py's _update_keyboard()), so that path is used
    as-is."""
    if input_handler.connected:
        try:
            from sensors.ble_receiver import ble_receiver as _ble_v
            return abs(_ble_v.get_latest()["accel_y"] / 16384.0)
        except Exception:
            return 0.0
    return abs(s.get("tilt_y", 0.0))


# Toy Factory calibrates its two wrist axes independently -- NOT the single
# shared "Wrist Rotation" entry Key & Lock/Apple Catching/Steady Aim use, so
# none of those games' calibration is affected. "Wrist Horizontal" reads the
# exact same abs(tilt_x) "Wrist Rotation" already does; "Wrist Vertical"
# needs the genuine-accel_y helper above.
SENSOR_CFG["Wrist Horizontal"] = {
    "sensor_name": "Tilt Sensor (Horizontal)",
    "key_hint":    "[ Hold LEFT / RIGHT arrow to simulate wrist movement ]",
    "read":        lambda s: abs(s["tilt_x"]),
}
SENSOR_CFG["Wrist Vertical"] = {
    "sensor_name": "Tilt Sensor (Vertical)",
    "key_hint":    "[ Hold UP / DOWN arrow to simulate wrist movement ]",
    "read":        _toy_factory_vertical_read,
}

# A patient's relaxed resting position rarely reads as a true sensor 0 (a
# flex sensor still bends somewhat with the hand at rest, FSR402 can carry a
# light resting preload, a wrist's "neutral" angle isn't always exactly 0) --
# the baseline phase below measures that resting value per sensor so every
# trial/threshold downstream can treat it as the real 0 instead of eating
# into the patient's usable range. Applies uniformly to all 3 sensor types;
# for a sensor that genuinely rests at 0 this is a no-op.
#
# Short, operational THERAPIST-facing instructions, one per calibration
# stage -- shown on screen only, NEVER spoken (the patient hears a longer,
# reassuring narration instead -- see recovr/patient_app/scenes/
# calibrating.py's own cue tables/audio). Deliberately generic across sensor
# types except "recording" (below), since the patient already hears which
# specific movement to perform.
THERAPIST_CUES = {
    "prep":     "Prepare the patient for calibration. Ensure the hand is comfortably relaxed.",
    "baseline": "Maintain the patient's resting position while the system records baseline sensor readings.",
    "ready":    "Guide the patient through the upcoming movement.",
    "between":  "Allow the patient to rest before proceeding.",
    "complete": "Calibration is complete. Review the recommended setting based on the results before you start the game.",
    "validation_retry":   "Repeating the 3 trials.",
    "validation_rebase":  "Check the sensor connection and keep the hand relaxed. The resting position will be measured again.",
    "validation_warning": "Retry again, or continue with a warning on the Results screen.",
}

# Recording-phase therapist instruction depends on which movement is being
# measured right now.
_RECORDING_CUES = {
    "Grip Strength":  "Ask the patient to perform their maximum comfortable grip.",
    "Finger Flexion": "Ask the patient to bend their fingers to their maximum comfortable range.",
    "Wrist Rotation": "Ask the patient to rotate their wrist to their maximum comfortable range.",
}


# Passes whose trials are checked by scenes/calibration_validation.py: the
# FSR402 grip sensor and every flex sensor. MPU6050 (wrist) passes are not.
_FLEX_KEYS      = {"Finger Flexion", *_FINGER_FLEX_KEYS}
_VALIDATED_KEYS = _FLEX_KEYS | {"Grip Strength"}
# Longest gap between 50 Hz controller packets before a capture is distrusted.
_STALE_SIGNAL_SEC = 0.5


def _recording_cue_for(game_type):
    """Maps any SENSOR_CFG key -- including the 5 independent per-finger
    passes and Toy Factory's two wrist axes -- to one of the 3 recording
    instructions above, since the instruction to the therapist is the same
    regardless of which specific finger or axis is currently being
    captured."""
    if game_type == "Grip Strength":
        return _RECORDING_CUES["Grip Strength"]
    if game_type in ("Wrist Rotation", "Wrist Horizontal", "Wrist Vertical"):
        return _RECORDING_CUES["Wrist Rotation"]
    return _RECORDING_CUES["Finger Flexion"]


# Difficulty presets — threshold_pct is applied to the calibrated average
DIFFICULTY_PRESETS = {
    "Easy": {
        # 30/70/90 -- matches the required-performance band each difficulty
        # represents (0-50% / 51-80% / 81-100% of the patient's own
        # calibrated range), same anchor every GAME_PARAM_SCHEMA "Required
        # Grip Strength"/"Required Finger Flexion"/"Required Wrist Rotation"
        # row uses.
        "threshold_pct": 30,
        "speed":         "Slow",
        "duration":      "60 s",
        "difficulty":    "Easy",
        "desc":          "Wide range, slow pace — ideal for early rehabilitation",
        "color":         (60, 180, 100),
    },
    "Medium": {
        "threshold_pct": 70,
        "speed":         "Normal",
        "duration":      "120 s",
        "difficulty":    "Medium",
        "desc":          "Balanced challenge — recommended for most patients",
        "color":         (60, 130, 220),
    },
    "Hard": {
        "threshold_pct": 90,
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

RECORD_DURATION   = 3.0
# 5 full seconds, matching the visible 5-4-3-2-1 countdown and the spoken
# "keep your hand relaxed" cue -- both sized so the patient has real time to
# settle into a resting position before baseline sampling begins (see
# _draw_prep/_draw_baseline below).
BASELINE_DURATION = 5.0
COUNTDOWN_STEPS   = 3
TRIAL_DONE_PAUSE  = 1.5
# Fixed-length announcement screens (prep / complete) auto-advance once their
# own spoken clip has had time to finish -- sized from the LONGER of the
# English/Filipino rendered clip lengths (assets/audio/calibration_prep[_fil]
# .mp3: en 6.88s / fil 8.70s; calibration_complete[_fil].mp3: en 5.08s / fil
# 7.39s -- see generate_calibration_audio.py) plus a small buffer, not a
# guess, so neither language's instruction is ever cut off and the next
# stage never starts over it. "ready" (the
# per-trial Start-button screen) deliberately has NO timer here -- the
# therapist advances it manually.
PREP_DURATION     = 9.3
COMPLETE_DURATION = 8.0
# How long the auto-retry explanation ("direction_retry") stays on screen
# before the 3 trials restart on their own -- no button, same idea as prep/
# complete above, just long enough to read a 1-2 sentence explanation.
DIRECTION_RETRY_DURATION = 4.0

# ── per-game Advanced Settings parameters ──────────────────────────────────────
# Each entry is a real, independently-overridable constant read by that game's
# own on_enter() (see games/<name>.py) -- not an invented control. "presets"
# gives that param's value under each difficulty (matching the game's own
# hardcoded Easy/Medium/Hard dict), used both as the starting value when a
# preset card is picked and to restore via "Reset to Preset". "key" is the
# calibration_result["params"] key the game checks (falling back to its own
# difficulty dict when absent, so normal non-customized sessions are
# unaffected). Every game has a schema entry here. Every "Required Grip Strength"/
# "Required Finger Flexion"/"Required Wrist Rotation" row across every game
# uses the same Easy=30%/Medium=70%/Hard=90% anchor: the % a patient must
# reach, relative to THEIR OWN calibrated resting->peak range, not a raw
# sensor value.
GAME_PARAM_SCHEMA = {
    "Basketball": [
        {"key": "bb_goal",            "label": "Target Score",            "unit": "pts", "is_goal": True,
         "min": 10, "max": 300, "step": 5,
         "presets": {"Easy": 50,   "Medium": 75,   "Hard": 100}},
        {"key": "bb_zone_width",      "label": "Target Zone Size",        "unit": "%",
         "min": 5,  "max": 35,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 25,   "Medium": 16,   "Hard": 9}},
        {"key": "bb_grip_threshold",  "label": "Required Grip Strength",  "unit": "%",
         "min": 10, "max": 95,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,   "Medium": 70,   "Hard": 90}},
        {"key": "bb_pointer_speed",   "label": "Pointer Speed",           "unit": "/s",
         "min": 0.2, "max": 2.0, "step": 0.05,
         "presets": {"Easy": 0.5,  "Medium": 0.8,  "Hard": 1.1}},
    ],
    "Lemonade": [
        {"key": "lem_target",         "label": "Target Score",             "unit": "pts", "is_goal": True,
         "min": 10, "max": 300, "step": 5,
         "presets": {"Easy": 50,   "Medium": 75,   "Hard": 100}},
        {"key": "lem_grip_threshold", "label": "Required Grip Strength",   "unit": "%",
         "min": 10,  "max": 95,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,   "Medium": 70,   "Hard": 90}},
        {"key": "lem_hold_duration",  "label": "Squeeze Hold Duration",   "unit": "s",
         "min": 0.5, "max": 5.0, "step": 0.1,
         "presets": {"Easy": 0.8,  "Medium": 1.2,  "Hard": 1.6}},
    ],
    "Tile Rush": [
        {"key": "pt_goal",            "label": "Target Score",              "unit": "pts", "is_goal": True,
         "min": 10, "max": 300, "step": 5,
         "presets": {"Easy": 50,    "Medium": 75,   "Hard": 100}},
        {"key": "pt_tile_speed",      "label": "Tile Speed",                 "unit": "px/s",
         "min": 120, "max": 700, "step": 10,
         "presets": {"Easy": 260,   "Medium": 340,  "Hard": 420}},
        {"key": "pt_spawn_rate",      "label": "Tile Spawn Interval",       "unit": "s",
         "min": 0.2, "max": 2.0, "step": 0.05,
         "presets": {"Easy": 1.0,  "Medium": 0.7,  "Hard": 0.45}},
        # Fallback only -- Tile Rush calibrates its 5 fingers independently
        # (see MULTI_SENSOR_CALIBRATION in scenes/therapist_dashboard.py),
        # each pass already produces its own real calibration-relative
        # threshold via the generic adv_threshold_pct mechanism above. This
        # single override only applies when a finger has no calibration at
        # all to fall back on.
        {"key": "pt_flex_threshold",  "label": "Required Finger Flexion",   "unit": "%",
         "min": 10,  "max": 95,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,   "Medium": 70,   "Hard": 90}},
    ],
    "Whack-a-Mole": [
        {"key": "wm_goal",            "label": "Target Score",               "unit": "pts", "is_goal": True,
         "min": 10,  "max": 300, "step": 5,
         "presets": {"Easy": 50,    "Medium": 75,   "Hard": 100}},
        {"key": "wm_mole_duration",   "label": "Mole Appearance Duration",   "unit": "s",
         "min": 2.0, "max": 3.0, "step": 0.1,
         "presets": {"Easy": 3.0,   "Medium": 2.5,  "Hard": 2.0}},
        {"key": "wm_simultaneous",    "label": "Simultaneous Mole Count",    "unit": "moles",
         "min": 1,   "max": 3,   "step": 1,
         "presets": {"Easy": 1,     "Medium": 1,    "Hard": 2}},
        # Fallback only -- same per-finger-calibration reasoning as Tile
        # Rush above (Whack-a-Mole calibrates its 5 fingers independently
        # too).
        {"key": "wm_flex_threshold",  "label": "Required Finger Flexion",    "unit": "%",
         "min": 10,  "max": 95,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
    ],
    "Apple Catching": [
        {"key": "ac_goal",        "label": "Target Score",                "unit": "pts", "is_goal": True,
         "min": 10,  "max": 300,  "step": 5,
         "presets": {"Easy": 50,     "Medium": 75,    "Hard": 100}},
        {"key": "ac_apple_speed", "label": "Apple Falling Speed",          "unit": "px/s",
         "min": 100, "max": 800,  "step": 10,
         "presets": {"Easy": 260,   "Medium": 380,   "Hard": 520}},
        {"key": "ac_simultaneous","label": "Simultaneous Object Count",    "unit": "objects",
         "min": 1,   "max": 3,    "step": 1,
         "presets": {"Easy": 1,     "Medium": 1,     "Hard": 2}},
        {"key": "ac_move_speed",  "label": "Basket Movement Sensitivity",  "unit": "px/s",
         "min": 300, "max": 1500, "step": 10,
         "presets": {"Easy": 750,   "Medium": 900,   "Hard": 1050}},
        {"key": "ac_wrist_requirement", "label": "Required Wrist Rotation", "unit": "%",
         "min": 10,  "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,    "Hard": 90}},
    ],
    "Key and Lock": [
        {"key": "kl_goal",      "label": "Target Score",             "unit": "pts", "is_goal": True,
         "min": 10,  "max": 400, "step": 5,
         "presets": {"Easy": 80,   "Medium": 120,  "Hard": 160}},
        {"key": "kl_tolerance", "label": "Wrist Angle Tolerance",   "unit": "°",
         "min": 2,   "max": 30,  "step": 1,
         "presets": {"Easy": 15,   "Medium": 8,    "Hard": 3}},
        {"key": "kl_hold_time", "label": "Required Hold Duration", "unit": "s",
         "min": 0.2, "max": 4.0, "step": 0.1,
         # Uniform 2 continuous seconds across every difficulty, per spec --
         # still overridable here.
         "presets": {"Easy": 2.0,  "Medium": 2.0,  "Hard": 2.0}},
        {"key": "kl_wrist_requirement", "label": "Required Wrist Rotation", "unit": "%",
         "min": 10,  "max": 95,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,   "Medium": 70,   "Hard": 90}},
    ],
    # Grip threshold and both wrist-movement requirements are deliberately
    # NOT schema'd here -- they come straight from the patient's own
    # calibration (see games/toy_factory.py's on_enter()). GAME_PARAM_SCHEMA
    # always supplies a preset value for every key it lists (see
    # _apply_preset below), which would silently override real per-patient
    # calibration data every session instead of only when the therapist
    # explicitly customizes it -- these rows cover only the pure gameplay
    # dials that have no calibration source of their own, plus a cosmetic-
    # only Finger Flexion slider (NOT wired into the real grab gate, which
    # stays grip-only -- see games/toy_factory.py's on_enter() comment).
    "Toy Factory": [
        {"key": "tf_goal", "label": "Target Score", "unit": "pts", "is_goal": True,
         "min": 10,  "max": 300, "step": 5,
         "presets": {"Easy": 50,   "Medium": 75,   "Hard": 100}},
        {"key": "tf_conveyor_speed",   "label": "Conveyor Speed",          "unit": "px/s",
         "min": 60,  "max": 260, "step": 10,
         "presets": {"Easy": 90,    "Medium": 140,  "Hard": 200}},
        {"key": "tf_pickup_tolerance", "label": "Pickup Tolerance",        "unit": "px",
         "min": 40,  "max": 160, "step": 5,
         "presets": {"Easy": 110,   "Medium": 85,   "Hard": 65}},
        {"key": "tf_box_tolerance",    "label": "Box-Placement Tolerance", "unit": "%",
         "min": 50,  "max": 150, "step": 5, "scale": 0.01,
         "presets": {"Easy": 125,   "Medium": 100,  "Hard": 80}},
        {"key": "tf_flex_threshold",   "label": "Required Finger Flexion", "unit": "%",
         "min": 10,  "max": 95,  "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
    ],
    "Steady Aim": [
        {"key": "sa_goal",       "label": "Target Score",           "unit": "pts", "is_goal": True,
         "min": 10,  "max": 400,  "step": 5,
         "presets": {"Easy": 80,    "Medium": 120,  "Hard": 160}},
        # Aim Tolerance (the hold-still precision radius) is a frozen,
        # non-difficulty constant -- see steady_aim.py's AIM_TOLERANCE_R.
        # The spec defines exactly one Advanced Settings parameter for this
        # game (Required Wrist Rotation), so no row for it exists here.
        {"key": "sa_cursor_spd", "label": "Cursor Sensitivity",    "unit": "",
         "min": 500, "max": 1500, "step": 10,
         "presets": {"Easy": 900,   "Medium": 1000, "Hard": 1100}},
        {"key": "sa_hold_time",  "label": "Required Hold Duration","unit": "s",
         "min": 0.5, "max": 4.0,  "step": 0.1,
         "presets": {"Easy": 3.0,   "Medium": 3.0,  "Hard": 3.0}},
        {"key": "sa_arrows",     "label": "Arrows Available",      "unit": "arrows",
         "min": 5,   "max": 40,   "step": 1,
         "presets": {"Easy": 20,    "Medium": 16,   "Hard": 14}},
        {"key": "sa_wrist_requirement", "label": "Required Wrist Rotation", "unit": "%",
         "min": 10,  "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
    ],
    "Purrfect Feast": [
        {"key": "ftc_grip_threshold", "label": "Required Grip Strength",    "unit": "%",
         "min": 10,   "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
        {"key": "ftc_move_deadzone",  "label": "Wrist Movement Sensitivity","unit": "%",
         "min": 2,    "max": 25,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 5,     "Medium": 8,    "Hard": 12}},
        # Presets match ZONE_TOLERANCE in feed_the_cat.py exactly -- the
        # game dict is the real fallback actually read, so these must stay
        # in sync with it.
        {"key": "ftc_zone_tolerance", "label": "Positioning Tolerance",     "unit": "px",
         "min": 40,   "max": 220,  "step": 5,
         "presets": {"Easy": 180,   "Medium": 135,  "Hard": 95}},
        {"key": "ftc_target_cats",   "label": "Target Score",              "unit": "pts", "is_goal": True,
         "min": 10,   "max": 300,  "step": 5,
         "presets": {"Easy": 50,    "Medium": 75,   "Hard": 100}},
        {"key": "ftc_flex_threshold", "label": "Required Finger Flexion",   "unit": "%",
         "min": 10,   "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
    ],
    "Garden Wonders": [
        {"key": "ptg_goal",            "label": "Target Score",              "unit": "pts", "is_goal": True,
         "min": 10,   "max": 400,  "step": 5,
         "presets": {"Easy": 80,    "Medium": 120,  "Hard": 160}},
        {"key": "ptg_grip_threshold",  "label": "Required Grip Strength",    "unit": "%",
         "min": 10,   "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
        {"key": "ptg_flex_threshold",  "label": "Required Finger Flexion",   "unit": "%",
         "min": 10,   "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
        {"key": "ptg_move_deadzone",   "label": "Wrist Movement Sensitivity","unit": "%",
         "min": 2,    "max": 25,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 5,     "Medium": 8,    "Hard": 12}},
        {"key": "ptg_zone_tolerance",  "label": "Positioning Tolerance",     "unit": "px",
         "min": 40,   "max": 140,  "step": 5,
         "presets": {"Easy": 130,   "Medium": 100,  "Hard": 70}},
        {"key": "ptg_water_hold",      "label": "Watering Hold Duration",    "unit": "s",
         "min": 0.5,  "max": 3.0,  "step": 0.1,
         "presets": {"Easy": 0.8,   "Medium": 1.2,  "Hard": 1.6}},
        # Watering is gated by wrist rotation (a pouring-motion gesture),
        # not grip; grip is used only for can/seed pickup. See
        # games/plant_the_garden.py's on_enter()/_update_watering().
        {"key": "ptg_wrist_requirement", "label": "Required Wrist Rotation", "unit": "%",
         "min": 10,   "max": 95,   "step": 1, "scale": 0.01,
         "presets": {"Easy": 30,    "Medium": 70,   "Hard": 90}},
    ],
}
# Games that read the generic Speed (Slow/Normal/Fast) setting at all --
# shown as its own Advanced Settings row only for these (showing it for a
# game that ignores it would be a non-functional control).
GAMES_USING_SPEED = {"Basketball", "Tile Rush"}


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
        # single combined Results screen. Only "Garden Wonders" is
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

        # ── 5-finger flex group (Whack-a-Mole / Tile Rush) ────────────
        # Normally each entry in self.game_types runs its OWN full
        # sensitivity->prep->baseline->ready->countdown->recording->
        # trial_done cycle. The 5 finger-flexion entries are the one
        # exception: when self.game_types contains all 5 of
        # _FINGER_FLEX_KEYS back to back, they run through that cycle
        # TOGETHER, ONCE -- every frame's self.cfg["read"] is replaced with
        # a read of all 5 channels at once (state["finger_flex"]), so one
        # shared baseline and the same 3 trials cover all 5 fingers
        # simultaneously instead of 15 separate trials. See
        # _is_finger_group_start/_finish_finger_group. self.peak_values
        # mirrors self.peak_value but per-finger; harmless/unused outside
        # group mode.
        self._finger_group_active = False
        self.peak_values           = [0.0] * len(_FINGER_FLEX_KEYS)
        # Trial validation (see scenes/calibration_validation.py). A pass
        # that fails once repeats on its own; failing again opens the
        # "direction_warning" screen. (The two "direction_*" phase names are
        # kept from the earlier direction-only check.)
        self._validation_retry_count = 0
        self._validation_issues      = {}     # sensor key -> failed outcome
        self._validation_outcomes    = {}     # sensor key -> every outcome
        self.sensor_noise            = {}     # sensor key -> resting std dev
        self._trial_trackers         = {}
        self._capture_live           = False  # readings come from the controller
        self._baseline_lost          = False
        self._trial_lost             = False

        # ── resting-baseline capture (see THERAPIST_CUES above) ────────
        # One measured resting value per sensor type, keyed exactly like
        # self.sensor_results -- {} for every sensor whose baseline hasn't
        # been captured yet (including every sensor on a brand-new window),
        # so every .get(..., 0.0) downstream is a safe, correction-free
        # no-op until a real baseline phase actually runs.
        self.sensor_baseline  = {}
        self.baseline_t       = 0.0
        self._baseline_samples = []

        # ── fixed-length announcement screens ("prep" before baseline,
        # "complete" after the last trial) -- see PREP_DURATION/
        # COMPLETE_DURATION above. "ready" (the per-trial Start-button
        # screen between baseline/trial_done and the next countdown) needs
        # no timer -- it waits for self._start_trial_rect instead.
        self._prep_t     = 0.0
        self._complete_t = 0.0
        self._direction_retry_t = 0.0
        self._start_trial_rect = pygame.Rect(0, 0, 1, 1)
        self._direction_retry_rect    = pygame.Rect(0, 0, 1, 1)
        self._direction_continue_rect = pygame.Rect(0, 0, 1, 1)

        # ── results-phase: preset & advanced settings ─────────────────
        self.selected_preset     = "Medium"   # Easy / Medium / Hard
        self.recommended_preset  = "Medium"   # from _recommend_difficulty(); never
                                               # changed by the therapist's own pick
        self.customized          = False      # True once a game-specific param has
                                               # been edited away from its preset value

        # advanced settings (start at Moderate defaults)
        self.adv_threshold_pct = 70           # int, one of THRESHOLD_PCTS -- Medium's anchor
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
        # A flat H/1080 (or W/1920) ratio is correct for a 1080p desktop
        # window but renders everything roughly 44% of its intended size on
        # the actual 800x480 touch panel this runs on in production. Below a
        # touch-sized window, scale against a much smaller reference (400
        # tall / 680 wide) instead of 1080/1920 -- deliberately well past a
        # bare 2x fix, since the physical 7" panel still reads too small at
        # that scale -- capped so a taller touch window doesn't blow up
        # disproportionately; a genuine desktop-sized window (height > 820)
        # keeps the original H/1080 behaviour.
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
            # Smaller than "big" -- used only for the baseline countdown
            # digit, which needs to free up vertical room for the Resting
            # Reading card below it, not the full 86px "big" size other
            # screens' reading cards use.
            "count_sm": pygame.font.Font(_F("GravitasOne-Regular.ttf"), self._sc(40)),
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

        # ── Close confirmation overlay (see _draw_close_confirm) ────────
        # Clicking the Close button (self._cancel_rect) opens this
        # confirmation instead of exiting calibration immediately.
        # Confirming sets self.cancelled; Cancel just dismisses the overlay,
        # leaving the in-progress calibration's phase/trials/baseline
        # untouched.
        self._close_confirm_open      = False
        self._close_confirm_yes_rect  = pygame.Rect(0, 0, 1, 1)
        self._close_confirm_no_rect   = pygame.Rect(0, 0, 1, 1)

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
        self._scroller           = DragScroller()
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
            for key, data in self.sensor_results.items():
                self.sensor_baseline[key] = data.get("baseline", 0.0)
            self._advance_sensor_idx(0)
            if self.phase == "complete":
                # Nothing was actually just measured THIS window (every
                # sensor came from reused_sensors) -- the "Calibration
                # complete" announcement describes trials that didn't just
                # happen here, so skip straight to Results instead.
                self._enter_results()
        else:
            # Fresh start, sensor_idx 0 -- _advance_sensor_idx isn't called
            # in this case (nothing to skip past), so arm the 5-finger group
            # here instead if game_types opens with one (Whack-a-Mole /
            # Tile Rush) -- see _is_finger_group_start.
            self._finger_group_active = self._is_finger_group_start(0)

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

    def _wrap_text(self, text, font, max_w):
        """Split `text` into lines that each fit max_w at `font`'s size,
        breaking on word boundaries. A single word wider than max_w on its
        own is kept whole on its own line (never mid-word-broken)."""
        words = str(text).split()
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if font.size(trial)[0] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _fit_title(self, text, max_w, color, min_size=20):
        """Header title -- shrinks only if too wide for the room actually
        left beside it (e.g. a long sensor name next to the Light/Dark
        toggle + Close button)."""
        return self._fit_text(self._title_font_path, self._sc(44), text, max_w, color, min_size)

    # Same (stage -> label, dot_color) source and labels as
    # scenes/therapist_dashboard.py's own `_CTRL_LOOK` sidebar controller
    # monitor -- a small, deliberate copy (not an import, which would be
    # circular: that file imports THIS one) so calibration shows the exact
    # same controller vocabulary rather than inventing a new one. Omits
    # that file's dual-monitor BLE-handoff-specific stages
    # (handed_off/handed_off_lost/handoff_stuck) -- those only apply to its
    # own Session-in-Progress panel, which calibration never reaches.
    _CTRL_LOOK = {
        "connected":     ("Controller connected", (40, 190, 90)),
        "stalled":       ("Signal stalled",       (230, 165, 30)),
        "connecting":    ("Connecting…",          (230, 165, 30)),
        "scanning":      ("Searching…",           (230, 165, 30)),
        "idle":          ("Controller idle",      (172, 184, 198)),
        "disabled":      ("Controller off",       (172, 184, 198)),
        "not_found":     ("Not found",            (215, 60, 55)),
        "old_firmware":  ("Old firmware",         (215, 60, 55)),
        "bluetooth_off": ("Bluetooth is off",     (215, 60, 55)),
        "no_bleak":      ("bleak not installed",  (215, 60, 55)),
        "no_permission": ("No BLE permission",    (215, 60, 55)),
        "error":         ("Controller error",     (215, 60, 55)),
    }

    def _draw_controller_status(self, surface, right_x, cy, max_w, C):
        """Compact dot+label controller-status indicator for the
        calibration header, right-aligned to `right_x`. Reads the same
        ble_receiver singleton therapist_dashboard.py's own controller
        monitor reads -- this is "read the same thing," not a second
        connection-monitoring mechanism."""
        try:
            from sensors.ble_receiver import ble_receiver
            stage = (ble_receiver.status() or {}).get("stage", "error")
        except Exception:
            stage = "error"
        label, dot_col = self._CTRL_LOOK.get(stage, self._CTRL_LOOK["error"])

        dot_r = max(4, self._sc(6))
        txt_s = self._fit_text(self._bold_font_path, self._sc(17), label,
                                max(self._scw(20), max_w - dot_r * 2 - self._scw(8)),
                                C["text"], self._sc(11))
        total_w = dot_r * 2 + self._scw(8) + txt_s.get_width()
        x0 = right_x - total_w
        pygame.draw.circle(surface, dot_col, (x0 + dot_r, cy), dot_r)
        surface.blit(txt_s, (x0 + dot_r * 2 + self._scw(8), cy - txt_s.get_height() // 2))

    # ── event handling ────────────────────────────────────────────────────────

    def handle_event(self, event):
        # Close confirmation overlay -- swallows ALL input until resolved,
        # exactly like the results-screen scroll gesture is scoped below but
        # higher priority: the confirmation must win even over a drag that
        # started on the results viewport before Close was clicked.
        if self._close_confirm_open:
            pos = None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                raw = event.pos
                pos = builtins.normalise_pos(raw) if hasattr(builtins, "normalise_pos") else raw
            elif event.type == pygame.FINGERDOWN:
                pos = (int(event.x * self.W), int(event.y * self.H))
            if pos is not None:
                if self._close_confirm_yes_rect.collidepoint(pos):
                    self._close_confirm_open = False
                    self.cancelled = True
                elif self._close_confirm_no_rect.collidepoint(pos):
                    self._close_confirm_open = False
            return

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
            self._close_confirm_open = True
            return

        if self.phase == "sensitivity":
            if self._begin_rect.collidepoint(pos):
                self._start_prep()

        elif self.phase == "ready":
            if self._start_trial_rect.collidepoint(pos):
                self._start_countdown()

        elif self.phase == "direction_warning":
            if self._direction_retry_rect.collidepoint(pos):
                self._reset_trials()
                self._restart_after_issue()
            elif self._direction_continue_rect.collidepoint(pos):
                self._finish_validated_pass()

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
        """Results-screen wheel + drag scrolling (see scenes/drag_scroll.py).
        Returns True if the event was consumed. Presses inside the viewport
        are captured even when nothing overflows, because the preset cards
        there are only reachable through _dispatch_results_tap."""
        consumed, self._results_scroll_y, tap = self._scroller.handle(
            event, key="results", viewport=self._results_viewport,
            scroll=self._results_scroll_y,
            max_scroll=max(0, self._results_content_h - self._results_viewport.height),
            size=(self.W, self.H), wheel_step=self._sc(40), threshold=self._sc(16),
            wheel_anywhere=False, capture_unscrollable=True)
        if tap is not None:
            self._dispatch_results_tap(tap)
        return consumed

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

        if self.phase == "prep":
            self._prep_t += dt
            if self._prep_t >= PREP_DURATION:
                self._start_baseline()

        elif self.phase == "baseline":
            if self._finger_group_active:
                raw5 = [min(1.0, max(0.0, v)) for v in state["finger_flex"]]
                self.live_value = raw5[0]   # representative only -- see _draw_baseline
                self._baseline_samples.append(raw5)
                self.baseline_t += dt
                self._baseline_lost |= self._signal_lost()
                if self.baseline_t >= BASELINE_DURATION:
                    for i, name in enumerate(_FINGER_FLEX_KEYS):
                        mean, noise = validation.rest_stats(
                            [s[i] for s in self._baseline_samples])
                        self.sensor_baseline[name] = round(mean, 4)
                        self.sensor_noise[name]    = noise
                    self._start_ready()
            else:
                raw = min(1.0, max(0.0, self.cfg["read"](state)))
                self.live_value = raw
                self._baseline_samples.append(raw)
                self.baseline_t += dt
                self._baseline_lost |= self._signal_lost()
                if self.baseline_t >= BASELINE_DURATION:
                    mean, noise = validation.rest_stats(self._baseline_samples)
                    self.sensor_baseline[self.game_type] = round(mean, 4)
                    self.sensor_noise[self.game_type]    = noise
                    self._start_ready()

        elif self.phase == "ready":
            pass   # waits for the therapist to tap Start -- see handle_event

        elif self.phase == "countdown":
            self.countdown_t += dt
            if self.countdown_t >= 1.0:
                self.countdown_t -= 1.0
                self.countdown   -= 1
                if self.countdown <= 0:
                    self.phase       = "recording"
                    self.record_t    = 0.0
                    self._start_trial_capture()

        elif self.phase == "recording":
            self._trial_lost |= self._signal_lost()
            if self._finger_group_active:
                raw5 = [min(1.0, max(0.0, v)) for v in state["finger_flex"]]
                self.live_value  = raw5[0]   # representative only -- see _draw_finger_group_readings
                for i, (key, value) in enumerate(zip(_FINGER_FLEX_KEYS, raw5)):
                    self.peak_values[i] = self._track(key, value)
                self.peak_value  = max(self.peak_values)
                self.record_t   += dt
                if self.record_t >= RECORD_DURATION:
                    self.trial_results.append([round(v, 4) for v in self.peak_values])
                    self.phase   = "trial_done"
                    self.pause_t = 0.0
            else:
                self.live_value  = min(1.0, max(0.0, self.cfg["read"](state)))
                if self.game_type in _VALIDATED_KEYS:
                    self.peak_value = self._track(self.game_type, self.live_value)
                else:
                    self.peak_value = max(self.peak_value, self.live_value)
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
                    self._validate_pass()
                else:
                    # Another trial remains for this sensor -- wait on the
                    # "ready" screen (rest cue + Start button) rather than
                    # auto-continuing, so the therapist confirms the patient
                    # is ready before every trial, not just the first.
                    self._start_ready()

        elif self.phase == "direction_retry":
            self._direction_retry_t += dt
            if self._direction_retry_t >= DIRECTION_RETRY_DURATION:
                self._restart_after_issue()

        elif self.phase == "direction_warning":
            pass   # waits for the therapist to tap Retry Again / Continue
                   # Anyway -- see handle_event

        elif self.phase == "complete":
            self._complete_t += dt
            if self._complete_t >= COMPLETE_DURATION:
                self._enter_results()

    # ── internal transitions ──────────────────────────────────────────────────

    def _finish_sensor(self):
        """Multi-sensor calibration only. Store the sensor just finished,
        then either move on to the next sensor that still needs calibrating
        (skipping any already reused -- see _advance_sensor_idx) or, once
        every sensor in self.game_types is accounted for, enter the one
        combined Results screen."""
        self._store_sensor_result()
        self._advance_sensor_idx(self.sensor_idx + 1)

    def _store_sensor_result(self):
        avg = sum(self.trial_results) / len(self.trial_results) if self.trial_results else 0.0
        self.sensor_results[self.game_type] = {
            "sensor_name": self.cfg["sensor_name"],
            "trials":      list(self.trial_results),
            "average":     round(avg, 4),
            "baseline":    self.sensor_baseline.get(self.game_type, 0.0),
            **self._status_fields(self.game_type),
        }

    def _is_finger_group_start(self, idx):
        """True when game_types[idx : idx+5] is exactly the 5 finger-
        flexion entries (Whack-a-Mole / Tile Rush), in order, and NONE of
        them has already been recorded (a reused-sensor seed never seeds
        just some of the 5 in practice, but if it ever did, falling back to
        the plain one-at-a-time path for the remainder is the safe
        choice -- see the comment by self._finger_group_active)."""
        end = idx + len(_FINGER_FLEX_KEYS)
        if end > len(self.game_types):
            return False
        if self.game_types[idx:end] != _FINGER_FLEX_KEYS:
            return False
        return not any(k in self.sensor_results for k in _FINGER_FLEX_KEYS)

    # ── capture + validation ──────────────────────────────────────────────

    def _signal_lost(self):
        """True when a capture that began on the real controller has since
        disconnected or stopped receiving packets (the reading then freezes or
        falls back to keyboard zeros)."""
        if not self._capture_live:
            return False
        if not input_handler.connected:
            return True
        try:
            from sensors.ble_receiver import ble_receiver
            age = ble_receiver.status().get("data_age")
        except Exception:
            return False
        return age is not None and age > _STALE_SIGNAL_SEC

    def _start_trial_capture(self):
        self._trial_trackers = {}
        if self.current_trial == 0:
            self._trial_lost = False
        if input_handler.connected and not self._capture_live:
            # Resting values came from keyboard fallback, not this controller.
            self._capture_live = self._baseline_lost = True
        keys = _FINGER_FLEX_KEYS if self._finger_group_active else [self.game_type]
        rest = [self.sensor_baseline.get(k, 0.0) if k in _VALIDATED_KEYS else 0.0
                for k in keys]
        self.peak_values = (rest if self._finger_group_active
                            else [0.0] * len(_FINGER_FLEX_KEYS))
        self.peak_value  = max(rest)

    def _track(self, key, value):
        """Adds a sample and returns this trial's effort reading so far."""
        tracker = self._trial_trackers.setdefault(key, validation.TrialTracker())
        tracker.add(value)
        return tracker.peak(self.sensor_baseline.get(key, 0.0), key in _FLEX_KEYS)

    def _validate_pass(self):
        """Runs after the third trial: judge each sensor in this pass, then
        either finish it, repeat it, or ask the therapist."""
        keys = _FINGER_FLEX_KEYS if self._finger_group_active else [self.game_type]
        self._validation_outcomes = {}
        for i, key in enumerate(keys):
            if key not in _VALIDATED_KEYS:
                continue
            trials = ([t[i] for t in self.trial_results] if self._finger_group_active
                      else list(self.trial_results))
            baseline = self.sensor_baseline.get(key, 0.0)
            noise    = self.sensor_noise.get(key, 0.0)
            outcome  = validation.evaluate(
                trials, baseline, noise, bidirectional=key in _FLEX_KEYS,
                live=self._capture_live,
                signal_lost=self._baseline_lost or self._trial_lost)
            print(validation.format_log(key, trials, baseline, noise, outcome))
            self._validation_outcomes[key] = outcome

        self._validation_issues = {
            k: o for k, o in self._validation_outcomes.items()
            if o["status"] != validation.PASSED}
        if not self._validation_issues:
            self._finish_validated_pass()
        elif self._validation_retry_count == 0:
            self._validation_retry_count = 1
            self._start_direction_retry()
        else:
            self._start_direction_warning()

    def _needs_new_baseline(self):
        return any(o["baseline_fault"] for o in self._validation_issues.values())

    def _reset_trials(self):
        self.trial_results = []
        self.current_trial = 0
        self.peak_values   = [0.0] * len(_FINGER_FLEX_KEYS)
        self.peak_value    = 0.0

    def _restart_after_issue(self):
        """The resting position is measured again only when it was the fault."""
        if self._needs_new_baseline():
            self._start_baseline()
        else:
            self._start_ready()

    def _start_direction_retry(self):
        """1st failed validation of this pass -- reset the 3 trials and show a
        brief explanation before they restart on their own. A 2nd failure goes
        to _start_direction_warning() instead of retrying forever."""
        self._reset_trials()
        self.phase              = "direction_retry"
        self._direction_retry_t = 0.0

    def _start_direction_warning(self):
        """2nd failed validation -- let the therapist choose, via
        handle_event: "Retry Again", or "Continue Anyway" (keeps the data, and
        each affected sensor stays flagged on the Results screen)."""
        self.phase = "direction_warning"

    def _status_fields(self, key):
        outcome = self._validation_outcomes.get(key)
        if not outcome:
            return {}
        return {"status": outcome["status"], "status_detail": outcome["detail"]}

    def _finish_validated_pass(self):
        self._validation_retry_count = 0
        self._validation_issues      = {}
        if self._finger_group_active:
            self._finish_finger_group()
        elif len(self.game_types) > 1:
            self._finish_sensor()
        else:
            if self.game_type in _VALIDATED_KEYS:
                self._store_sensor_result()
            self._enter_complete()

    def _finish_finger_group(self):
        """Counterpart to _finish_sensor() for the 5-finger group -- splits
        the 3 shared trials (each trial_results entry is a 5-long list, one
        peak per finger -- see update()'s "recording" branch) back into 5
        independent sensor_results rows, one per finger, in EXACTLY the
        shape _finish_sensor() itself produces. Everything downstream
        (_advance_sensor_idx's terminal branch, _enter_results,
        _recommend_difficulty, _accept_multi_sensor, the Results screen)
        already expects that shape and needs no group-specific handling at
        all once this has run. Each finger keeps its own validation status."""
        for i, name in enumerate(_FINGER_FLEX_KEYS):
            trials_i = [round(t[i], 4) for t in self.trial_results]
            avg_i = sum(trials_i) / len(trials_i) if trials_i else 0.0
            self.sensor_results[name] = {
                "sensor_name": SENSOR_CFG[name]["sensor_name"],
                "trials":      trials_i,
                "average":     round(avg_i, 4),
                "baseline":    self.sensor_baseline.get(name, 0.0),
                **self._status_fields(name),
            }
        self._finger_group_active = False
        self._advance_sensor_idx(self.sensor_idx + len(_FINGER_FLEX_KEYS))

    def _advance_sensor_idx(self, start_idx):
        """Move to the next sensor in game_types (from start_idx onward)
        that still needs live trials, skipping any sensor already present
        in self.sensor_results -- whether pre-seeded via reused_sensors at
        construction or just finished live in this same multi-sensor run.
        Lands that sensor on its own fresh "sensitivity" screen -- or, if it
        starts a 5-finger group (see _is_finger_group_start), arms
        self._finger_group_active so update()/draw read/show all 5 channels
        together instead of just self.game_type's own one. Once every
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
            self.sensor_idx           = idx
            self.game_type             = self.game_types[idx]
            self.cfg                    = SENSOR_CFG.get(self.game_type, SENSOR_CFG["Grip Strength"])
            self._finger_group_active = self._is_finger_group_start(idx)
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
        self._finger_group_active = False
        self._enter_complete()

    def _start_prep(self):
        self.phase   = "prep"
        self._prep_t = 0.0

    def _start_baseline(self):
        self.phase           = "baseline"
        self.baseline_t       = 0.0
        self.live_value       = 0.0
        self._baseline_samples = []
        self._capture_live     = input_handler.connected
        self._baseline_lost    = False

    def _start_ready(self):
        self.phase = "ready"

    def _start_countdown(self):
        self.phase       = "countdown"
        self.countdown   = COUNTDOWN_STEPS
        self.countdown_t = 0.0

    def _enter_complete(self):
        """Brief spoken+visual confirmation (see THERAPIST_CUES["complete"]
        and assets/audio/calibration_complete[_fil].mp3) shown once, right after
        the LAST sensor's last trial -- not after every sensor in a
        multi-sensor run, only the final one -- before the Results screen
        itself opens. Auto-advances after COMPLETE_DURATION; see update()."""
        self.phase       = "complete"
        self._complete_t = 0.0

    @staticmethod
    def _rescale(raw, baseline):
        """Rescales a raw 0-1 sensor reading so the patient's own relaxed
        resting position reads as 0 and their calibrated max still reads as
        1, instead of a resting bend/preload eating into the usable range.
        A no-op (returns raw unchanged, clamped) when baseline is 0.

        Direction-independent: some flex sensors read LOWER, not higher,
        when the finger bends (never verified in hardware, so both must be
        supported -- see the per-finger press_threshold_pct fix in
        games/whack_mole.py etc.). When raw lands below baseline, this
        rescales against the 0.0 floor instead of the 1.0 ceiling, mirroring
        the increasing-direction case exactly."""
        if raw >= baseline:
            denom = 1.0 - baseline
            if denom <= 1e-6:
                return max(0.0, min(1.0, raw - baseline))
            return max(0.0, min(1.0, (raw - baseline) / denom))
        denom = baseline
        if denom <= 1e-6:
            return max(0.0, min(1.0, baseline - raw))
        return max(0.0, min(1.0, (baseline - raw) / denom))

    @staticmethod
    def _baseline_threshold(avg, baseline, pct):
        """threshold_pct applied to the RANGE between the resting baseline
        and the calibrated average -- so a sensor with a nonzero resting
        value (e.g. a flex sensor that still reads something with the hand
        at rest) doesn't give the patient "free" progress toward the
        threshold just for resting. Reduces exactly to the original
        `avg * pct / 100` when baseline is 0.

        Direction-independent: if avg reads BELOW baseline (this sensor's
        raw value decreases when flexed), the threshold is placed the same
        fraction of the way BELOW baseline instead of collapsing to exactly
        baseline -- collapsing to baseline would make a decreasing-direction
        sensor's threshold equal to its own resting value, which raw could
        never cross while flexed (permanent "Idle"). This value is still
        saved/shown for display (Results screen "Active threshold", saved DB
        row) -- see games/whack_mole.py etc. for the runtime path, which
        computes its own direction-independent percentage directly from
        baseline/average instead of comparing raw against this single
        scalar."""
        span = avg - baseline
        sign = 1.0 if span >= 0 else -1.0
        span = abs(span)
        if span <= 1e-6:
            return round(baseline, 4)
        return round(baseline + sign * span * pct / 100.0, 4)

    def _enter_results(self):
        self.phase = "results"
        self._results_scroll_y = 0
        # Recommended difficulty is based on how far through the sensor's
        # own 0-1 range the patient's average trial reached. Low average ->
        # limited strength/range -> Easy; high average -> strong/full range
        # -> Hard. Simple, explainable, and driven entirely by the real
        # calibration data, never hardcoded.
        self.recommended_preset = self._recommend_difficulty()
        self._apply_preset(self.recommended_preset)

    def _recommend_difficulty(self):
        """Easy = 0-50%, Medium = 51-80%, Hard = 81-100% of the patient's own
        calibrated resting->peak range -- the same bands every difficulty
        parameter in GAME_PARAM_SCHEMA is anchored to (see the 30/70/90
        presets there)."""
        avg = (sum(self.trial_results) / len(self.trial_results)
               if self.trial_results else 0.0)
        baseline = self.sensor_baseline.get(self.game_type, 0.0)
        # Rounded to 6dp -- sum()/len() on 3 trials that are each exactly at
        # a boundary (e.g. three 0.80 trials) can land on 0.8000000000000002
        # from ordinary float summation drift, which silently failed the
        # "<= 0.80" check below and recommended Hard instead of Medium for
        # a patient who measured exactly at the Medium boundary. Rounding
        # removes that drift without changing the 50%/80% bands themselves.
        effective_avg = round(self._rescale(avg, baseline), 6)
        if effective_avg <= 0.50:
            return "Easy"
        if effective_avg <= 0.80:
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
        avg      = sum(self.trial_results) / len(self.trial_results) if self.trial_results else 0.0
        baseline = self.sensor_baseline.get(self.game_type, 0.0)
        threshold = self._baseline_threshold(avg, baseline, self.adv_threshold_pct)
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
            "baseline":    baseline,
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
        just Garden Wonders). Builds TWO things:
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
                "sensor_name": SENSOR_CFG[sensor_type]["sensor_name"], "trials": [], "average": 0.0,
                "baseline": 0.0}
            avg      = data["average"]
            baseline = data.get("baseline", 0.0)
            thr = self._baseline_threshold(avg, baseline, threshold_pct)
            row_params = dict(shared_params)
            row_params["threshold"] = thr
            self.multi_sensor_results.append({
                "game_type":   sensor_type,
                "game_name":   self.game_name,
                "sensor":      data["sensor_name"],
                "sensitivity": self.sensitivity,
                "trials":      data["trials"],
                "average":     avg,
                "baseline":    baseline,
                "threshold":   thr,
                "preset":      self.selected_preset,
                "recommended": self.recommended_preset,
                "customized":  self.customized,
                "dark_mode":   self.dark_mode,
                "params":      row_params,
            })
            sensors_block[sensor_type] = {"average": avg, "baseline": baseline,
                                           "threshold": thr, "trials": data["trials"]}

            # grip_rest/wrist_min/wrist_max below feed every game's existing
            # _normalize_grip/_normalize_tilt (see games/*.py) unchanged --
            # those already compute (raw - rest) / (mx - rest) /
            # (raw - wmin) / (wmax - wmin); plugging the real measured
            # baseline in here is all those formulas need to use the
            # patient's own calibration instead of a hardcoded 0.0/symmetric
            # range.
            if sensor_type == "Grip Strength":
                extra["grip_rest"] = baseline
                extra["grip_max"]  = max(avg, baseline + 0.05)
            elif sensor_type == "Wrist Rotation":
                half_range = max(avg - baseline, 0.05)
                extra["wrist_min"] = -half_range
                extra["wrist_max"] =  half_range
            elif sensor_type == "Finger Flexion":
                extra["flex_threshold"] = thr if thr > 0 else input_handler.FLEX_THRESH

        primary = sensors_block.get(self.game_type,
                                     {"average": 0.0, "baseline": 0.0, "threshold": 0.0, "trials": []})
        merged_params = dict(shared_params)
        merged_params["threshold"] = primary["threshold"]

        self.calibration_result = {
            "game_type":   "Multi-skill",
            "game_name":   self.game_name,
            "sensor":      " + ".join(SENSOR_CFG[t]["sensor_name"] for t in self.game_types),
            "sensitivity": self.sensitivity,
            "trials":      primary["trials"],
            "average":     primary["average"],
            "baseline":    primary.get("baseline", 0.0),
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
        # Resting position may have shifted since the last attempt (e.g. a
        # regrip, a different arm rest) -- recapture it fresh rather than
        # reusing a stale baseline.
        self.sensor_baseline  = {}
        self.sensor_noise     = {}
        self._validation_retry_count = 0
        self._validation_issues      = {}
        self._validation_outcomes    = {}
        self._prep_t          = 0.0
        self._complete_t      = 0.0
        self._finger_group_active = self._is_finger_group_start(0)

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
            # Wider than the toggle/back buttons -- this is a labeled pill,
            # not a square icon (see the close_r drawing below).
            close_w = self._scw(170)
            close_r = pygame.Rect(W - pad_r - close_w, top_h // 2 - row_h // 2, close_w, row_h)
            toggle_right = close_r.left - gap
        else:
            close_r = None
            toggle_right = W - pad_r
        controls_left_x = toggle_right - tog_w
        title_avail_right = controls_left_x - gap

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
                                       title_avail_right - back_r.right - self._scw(24), C["text"])
            surface.blit(title_s, (back_r.right + self._scw(16),
                                    top_h // 2 - title_s.get_height() // 2))
            if self.game_name:
                gn_avail = title_avail_right - (back_r.right + self._scw(16) + title_s.get_width()
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
            if self._finger_group_active:
                # All 5 fingers calibrate together as ONE step (see
                # _finish_finger_group) -- "(1 of 5)" would misreport it as
                # 5 separate sequential passes.
                title_txt = "Sensor Calibration — All Finger Flex Sensors"
            else:
                # A per-finger pass that falls back to the one-at-a-time
                # path (see _is_finger_group_start) uses the generic "Flex
                # Sensors" label rather than the SPECIFIC finger's own
                # sensor_name (e.g. "Pinky Flex Sensor"), which would read
                # as a confusing/unexpected label -- consistent with the
                # grouped path's own "All Finger Flex Sensors" title.
                sensor_label = ("Flex Sensors" if self.game_type in _FINGER_FLEX_KEYS
                                else self.cfg['sensor_name'])
                title_txt = f"Sensor Calibration — {sensor_label}"
                if len(self.game_types) > 1:
                    title_txt += f"  ({self.sensor_idx + 1} of {len(self.game_types)})"
            title_s = self._fit_title(title_txt, title_avail_right - self._scw(32) - self._scw(16), C["text"])
            surface.blit(title_s, (self._scw(32),
                                    top_h // 2 - title_s.get_height() // 2))

        # ── Light/Dark toggle (EXACT same sliding track+knob component as
        # therapist_dashboard.py's own top-right bar) + a dedicated "Close"
        # button for calibration. Deliberately NOT the plain close_button.png
        # X used elsewhere in the dashboard -- calibration can be mid-
        # measurement when a therapist needs to back out fast (e.g. patient
        # discomfort), and a small corner X is both easy to miss and easy to
        # mistake for "close this view" the way it behaves everywhere else in
        # the app. Clicking it opens a confirmation dialog (see
        # _close_confirm_open / _draw_close_confirm) rather than exiting
        # immediately -- only confirming there sets self.cancelled (-> return
        # to Game Configuration / Patient Dashboard, see handle_event and
        # therapist_dashboard.py's own win.cancelled handling).
        if close_r is not None:
            pygame.draw.rect(surface, C["red"], close_r, border_radius=close_r.height // 2)
            pygame.draw.rect(surface, (255, 255, 255), close_r,
                             max(1, int(2 * self._FS)), border_radius=close_r.height // 2)
            ex_s = self._fit_text(self._bold_font_path, self._sc(21), "Close",
                                  close_r.width - self._scw(16), (255, 255, 255), self._sc(13))
            surface.blit(ex_s, ex_s.get_rect(center=close_r.center))
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
            "prep":         self._draw_prep,
            "baseline":     self._draw_baseline,
            "ready":        self._draw_ready,
            "countdown":    self._draw_countdown,
            "recording":    self._draw_recording,
            "trial_done":   self._draw_trial_done,
            "direction_retry":   self._draw_direction_retry,
            "direction_warning": self._draw_direction_warning,
            "complete":     self._draw_complete,
            "results":      self._draw_results,
            "advanced":     self._draw_advanced_settings,
        }.get(self.phase, lambda s, a, c: None)(surface, content, C)

        # Controller (BLE) status, shown in the lower-right corner of the
        # screen. Drawn after the phase content (not inside the top bar) so
        # it stays on top of whatever that phase renders, same as the
        # close-confirmation overlay below.
        # Not on Results / Advanced Settings: no live reading happens there.
        if self.phase not in ("results", "advanced"):
            ctrl_w = self._scw(150)
            self._draw_controller_status(surface, W - self._scw(20), H - self._sc(24), ctrl_w, C)

        # ── Close confirmation overlay -- drawn last so it covers everything
        # above, including whichever phase screen is currently showing. ────
        if self._close_confirm_open:
            self._draw_close_confirm(surface)

    def _dialog_fonts(self):
        """The font set draw_confirm_dialog needs, from this window's OWN
        Lexend-based font set (self.fnt) -- not therapist_dashboard.py's
        Poppins one, so the confirmation stays visually consistent with the
        rest of THIS screen's own typography."""
        return {"title": self.fnt["head2"], "body": self.fnt["body"], "btn": self.fnt["bold"]}

    def _draw_close_confirm(self, surface):
        """Confirms before actually closing calibration (see handle_event's
        _cancel_rect handling) -- reuses therapist_dashboard.py's own
        standardized draw_confirm_dialog for the same dim-overlay/icon/
        title/body/button layout and interaction pattern every other
        confirmation in RecovR uses. Imported lazily: therapist_dashboard.py
        is what imports CalibrationWindow (not the other way around), so a
        module-level import here would be circular -- by the time any
        CalibrationWindow instance actually draws, that module is already
        fully loaded."""
        from scenes.therapist_dashboard import draw_confirm_dialog
        cr, xr = draw_confirm_dialog(
            surface, self.W, self.H, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="warning", accent=(205, 45, 45),
            title="Close Calibration?",
            body="This will interrupt the ongoing calibration. Any progress "
                 "on the current sensor will be lost.",
            confirm_label="Close", cancel_label="Cancel",
            confirm_hov=self._close_confirm_yes_rect.collidepoint(pygame.mouse.get_pos()),
            cancel_hov=self._close_confirm_no_rect.collidepoint(pygame.mouse.get_pos()))
        self._close_confirm_yes_rect, self._close_confirm_no_rect = cr, xr

    # ── phases: sensitivity / countdown / recording / trial_done ───────────────
    # All four share one compact 800x480 monitoring layout (therapist-facing:
    # trial progress, live/peak raw readings, recording countdown, controller
    # status, trial indicators) -- only the live values and status label
    # change per phase. "sensitivity" is just this same layout before Trial 1
    # starts (Begin Calibration button, nothing recorded yet); there is no
    # more separate Low/Medium/High sensitivity-picker screen.

    def _draw_sensitivity(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Waiting", show_begin=True)

    def _draw_cue_box(self, surface, lx, cy, rw, C, text, label="Therapist cue:", gap_after=14):
        """Shared box used by the prep/baseline/ready/complete announcement
        screens -- a short, ON-SCREEN-ONLY operational instruction for the
        THERAPIST (see THERAPIST_CUES), never spoken aloud. The patient
        hears a longer, separate narration instead (see
        recovr/patient_app/scenes/calibrating.py). Wraps onto as many lines
        as the cue text actually needs (THERAPIST_CUES entries are full
        sentences, often too long for one line even at the font's floor
        size) instead of a fixed height that could clip them. Returns the y
        position immediately below the box."""
        pad = self._scw(16)
        size = self._sc(23)
        min_size = self._sc(16)
        max_text_w = rw - pad * 2
        cue_font = None
        lines = [text]
        while True:
            key = (self._bold_font_path, size)
            cue_font = self._fit_font_cache.get(key)
            if cue_font is None:
                cue_font = pygame.font.Font(self._bold_font_path, size)
                self._fit_font_cache[key] = cue_font
            lines = self._wrap_text(text, cue_font, max_text_w)
            widest = max(cue_font.size(ln)[0] for ln in lines)
            if widest <= max_text_w or size <= min_size:
                break
            size -= 2

        cue_lbl = self.fnt["smallb"].render(label, True, C["sub"])
        line_h = cue_font.get_linesize()
        text_block_h = len(lines) * line_h
        cue_h = (self._sc(8) + cue_lbl.get_height() + self._sc(2)
                 + text_block_h + self._sc(10))
        cue_r = pygame.Rect(lx, cy, rw, cue_h)
        pygame.draw.rect(surface, C["panel2"], cue_r, border_radius=12)
        pygame.draw.rect(surface, C["accent"], cue_r, 1, border_radius=12)
        surface.blit(cue_lbl, (cue_r.x + pad, cue_r.y + self._sc(8)))
        ty = cue_r.y + self._sc(8) + cue_lbl.get_height() + self._sc(2)
        for ln in lines:
            ln_s = cue_font.render(ln, True, C["text"])
            surface.blit(ln_s, (cue_r.x + pad, ty))
            ty += line_h
        return cy + cue_h + self._sc(gap_after)

    def _draw_timer_bar(self, surface, lx, cy, rw, C, remaining, total):
        """Thin progress bar + "X.Xs" readout shared by every fixed-length
        auto-advancing screen (prep / baseline / complete)."""
        frac = 1.0 - (remaining / total if total else 0.0)
        bar_w = rw - self._scw(90)
        bar_h = self._sc(18)
        self._draw_bar(surface, lx, cy, bar_w, bar_h, frac, C)
        tm_s = self.fnt["bold"].render(f"{remaining:.1f}s", True, C["text"])
        surface.blit(tm_s, (lx + bar_w + self._scw(14), cy + (bar_h - tm_s.get_height()) // 2))

    def _draw_prep(self, surface, area, C):
        """Preparation announcement, before the baseline countdown starts --
        gives the patient (and the therapist) real time to get ready before
        anything is measured (see PREP_DURATION). Auto-advances into
        "baseline" on its own; no button needed here."""
        W, H = self.W, self.H
        lx = self._scw(40)
        rw = W - lx * 2
        cy = area.y + self._sc(6)

        tl_s = self.fnt["head2"].render("Preparing for Calibration", True, C["text"])
        surface.blit(tl_s, (lx, cy))
        st_s = self.fnt["head2"].render("Preparation", True, C["accent"])
        surface.blit(st_s, st_s.get_rect(topright=(lx + rw, cy)))
        cy += tl_s.get_height() + self._sc(14)

        cy = self._draw_cue_box(surface, lx, cy, rw, C, THERAPIST_CUES["prep"])
        cy += self._sc(10)
        self._draw_timer_bar(surface, lx, cy, rw, C,
                             max(0.0, PREP_DURATION - self._prep_t), PREP_DURATION)

    def _draw_baseline(self, surface, area, C):
        """Resting-baseline capture -- a visible 5-4-3-2-1 countdown (see
        BASELINE_DURATION) while the patient's resting sensor value is
        continuously sampled; the digit shown and the sampling window are
        driven by this same self.baseline_t, so they can never drift apart.
        On-screen only; see THERAPIST_CUES["baseline"]."""
        W, H = self.W, self.H
        lx = self._scw(40)
        rw = W - lx * 2
        cy = area.y + self._sc(6)

        tl_s = self.fnt["head2"].render("Establishing Resting Baseline", True, C["text"])
        surface.blit(tl_s, (lx, cy))
        st_s = self.fnt["head2"].render("Baseline", True, C["accent"])
        surface.blit(st_s, st_s.get_rect(topright=(lx + rw, cy)))
        cy += tl_s.get_height() + self._sc(6)

        # Tighter trailing gap than prep/ready/complete -- this screen has
        # the most stacked above the Resting Reading card (title + cue +
        # countdown digit) and the least room to spare on the touch panel.
        cy = self._draw_cue_box(surface, lx, cy, rw, C, THERAPIST_CUES["baseline"], gap_after=6)

        count = max(1, int(BASELINE_DURATION) - int(min(self.baseline_t, BASELINE_DURATION - 1e-3)))
        count_s = self.fnt["count_sm"].render(str(count), True, C["accent"])
        surface.blit(count_s, count_s.get_rect(midtop=(lx + rw // 2, cy)))
        cy += count_s.get_height()

        # No countdown/progress-bar readout below the card -- it's taller
        # instead, giving "Resting Reading" real room rather than leaving it
        # empty. The 5-4-3-2-1 digit above (self.baseline_t-driven) is the
        # only countdown shown on this screen.
        card_h = self._sc(110)
        live_r = pygame.Rect(lx, cy, rw, card_h)
        self._draw_reading_card(surface, live_r, C, "Resting Reading",
                                f"{self.live_value:.3f}", C["accent"], font=self.fnt["big2"])

    def _draw_ready(self, surface, area, C):
        """Waits for the therapist to confirm the patient is ready before
        EVERY trial, not just the first -- see THERAPIST_CUES["ready"]/
        ["between"] and the Start button below. Entered once right after
        baseline (trial 1) and again after each completed trial that isn't
        the sensor's last (trials 2 and 3)."""
        W, H = self.W, self.H
        cx = area.centerx
        lx = self._scw(40)
        rw = W - lx * 2
        cy = area.y + self._sc(6)

        is_first = self.current_trial == 0
        tl_s = self.fnt["head2"].render(
            f"Ready for Trial {self.current_trial + 1} of 3", True, C["text"])
        surface.blit(tl_s, (lx, cy))
        st_s = self.fnt["head2"].render("Waiting", True, C["sub"])
        surface.blit(st_s, st_s.get_rect(topright=(lx + rw, cy)))
        cy += tl_s.get_height() + self._sc(10)

        cue = THERAPIST_CUES["ready"] if is_first else THERAPIST_CUES["between"]
        cy = self._draw_cue_box(surface, lx, cy, rw, C, cue)

        dot_r = self._sc(10)   # must match _draw_trial_dots' own internal dot_r
        label_h = self.fnt["small"].get_height()
        self._draw_trial_dots(surface, cx, cy + dot_r, C, current=self.current_trial)
        cy += dot_r * 2 + self._sc(4) + label_h + self._sc(16)

        start_h = self._tt(44)
        start_r = pygame.Rect(cx - self._scw(190), cy, self._scw(380), start_h)
        pygame.draw.rect(surface, C["accent"], start_r, border_radius=14)
        b_s = self.fnt["bold"].render(f"Start Trial {self.current_trial + 1}", True, C["white"])
        surface.blit(b_s, b_s.get_rect(center=start_r.center))
        self._start_trial_rect = start_r

    def _issue_title(self):
        statuses = {o["status"] for o in self._validation_issues.values()}
        if len(statuses) == 1:
            return {validation.NO_MOVEMENT:  "No Movement Detected",
                    validation.INCONSISTENT: "Inconsistent Movement",
                    validation.UNRELIABLE:   "Unreliable Sensor Reading"}[statuses.pop()]
        return "Check Sensor Readings"

    def _issue_lines(self):
        """One line per problem type (at most three), naming the sensors that
        share it; the detail is shown when they all share that too."""
        grouped = {}
        for key, o in self._validation_issues.items():
            name = key.split()[0] if key in _FINGER_FLEX_KEYS else SENSOR_CFG[key]["sensor_name"]
            names, details = grouped.setdefault(o["status"], ([], set()))
            names.append(name)
            details.add(o["detail"])
        lines = []
        for status, (names, details) in grouped.items():
            line = f"{', '.join(names)}: {validation.STATUS_LABELS[status]}"
            if len(details) == 1:
                line += f" ({details.pop()})"
            lines.append(line)
        return lines

    def _draw_issue_screen(self, surface, area, C, state_text, state_col, cue):
        """Shared header + problem list + cue; returns the y below them."""
        lx = self._scw(40)
        rw = self.W - lx * 2
        cy = area.y + self._sc(6)
        st_s = self.fnt["head2"].render(state_text, True, state_col)
        surface.blit(st_s, st_s.get_rect(topright=(lx + rw, cy)))
        tl_s = self._fit_text(self._bold_font_path, self._sc(25), self._issue_title(),
                              rw - st_s.get_width() - self._scw(16), C["text"], self._sc(16))
        surface.blit(tl_s, (lx, cy))
        cy += max(tl_s.get_height(), st_s.get_height()) + self._sc(8)
        for line in self._issue_lines():
            s = self._fit_text(self._small_font_path, self._sc(18), line, rw,
                               C["text"], self._sc(12))
            surface.blit(s, (lx, cy))
            cy += s.get_height() + self._sc(2)
        return self._draw_cue_box(surface, lx, cy + self._sc(6), rw, C, cue)

    def _draw_direction_retry(self, surface, area, C):
        """1st failed validation -- a brief, auto-advancing explanation, same
        layout family as _draw_prep/_draw_complete."""
        lx = self._scw(40)
        rw = self.W - lx * 2
        cue = THERAPIST_CUES["validation_rebase" if self._needs_new_baseline()
                             else "validation_retry"]
        cy = self._draw_issue_screen(surface, area, C, "Retrying", C["accent"], cue)
        self._draw_timer_bar(surface, lx, cy + self._sc(8), rw, C,
                             max(0.0, DIRECTION_RETRY_DURATION - self._direction_retry_t),
                             DIRECTION_RETRY_DURATION)

    def _draw_direction_warning(self, surface, area, C):
        """2nd failed validation -- the therapist chooses via the two buttons
        below (see handle_event's "direction_warning" branch)."""
        lx = self._scw(40)
        rw = self.W - lx * 2
        cy = self._draw_issue_screen(surface, area, C, "Action Needed", C["yellow"],
                                     THERAPIST_CUES["validation_warning"])
        btn_h = self._tt(44)
        gap   = self._scw(16)
        btn_w = (rw - gap) // 2
        # Never pushed off the screen by a long list of affected sensors.
        by      = min(cy + self._sc(10), self.H - btn_h - self._sc(44))
        retry_r = pygame.Rect(lx, by, btn_w, btn_h)
        cont_r  = pygame.Rect(lx + btn_w + gap, by, btn_w, btn_h)
        pygame.draw.rect(surface, C["panel2"], retry_r, border_radius=14)
        pygame.draw.rect(surface, C["accent"], retry_r, 2, border_radius=14)
        pygame.draw.rect(surface, C["accent"], cont_r, border_radius=14)
        r_s = self.fnt["bold"].render("Retry Again", True, C["accent"])
        c_s = self.fnt["bold"].render("Continue Anyway", True, C["white"])
        surface.blit(r_s, r_s.get_rect(center=retry_r.center))
        surface.blit(c_s, c_s.get_rect(center=cont_r.center))
        self._direction_retry_rect    = retry_r
        self._direction_continue_rect = cont_r

    def _draw_countdown(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Waiting")

    def _draw_recording(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Recording")

    def _draw_trial_done(self, surface, area, C):
        self._draw_live_monitor(surface, area, C, "Completed")

    def _draw_complete(self, surface, area, C):
        """Brief "Calibration complete" confirmation shown once, right after
        the LAST sensor's last trial -- not after every sensor in a
        multi-sensor run, only the final one -- before the Results screen
        opens (see THERAPIST_CUES["complete"] / COMPLETE_DURATION). Auto-
        advances; no button needed here."""
        W, H = self.W, self.H
        lx = self._scw(40)
        rw = W - lx * 2
        cy = area.y + self._sc(20)

        tl_s = self.fnt["med"].render("Calibration Complete!", True, C["green"])
        surface.blit(tl_s, tl_s.get_rect(midtop=(lx + rw // 2, cy)))
        cy += tl_s.get_height() + self._sc(18)

        cy = self._draw_cue_box(surface, lx, cy, rw, C, THERAPIST_CUES["complete"],
                                label="Next step:")
        cy += self._sc(10)
        self._draw_timer_bar(surface, lx, cy, rw, C,
                             max(0.0, COMPLETE_DURATION - self._complete_t), COMPLETE_DURATION)

    def _draw_live_monitor(self, surface, area, C, status, show_begin=False):
        """Flow layout (each row positioned from the actual rendered height
        of the row above it, not a fixed design-space offset table) so this
        never depends on hand-tuned constants staying in sync with the
        current font/card sizes -- fixed offsets calibrated for a smaller
        scale risk overflowing the bottom of the 800x480 panel. Live
        Reading / Peak Reading sit side by side (not stacked) specifically
        to use this screen's generous WIDTH and ease the tight HEIGHT
        budget."""
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

        # row 1b -- recording-only therapist cue (see THERAPIST_CUES /
        # _recording_cue_for). One compact line, not the larger boxed cue
        # the prep/baseline/ready/complete screens use, so this stays
        # within the tight 800x480 height budget documented above.
        if status == "Recording":
            cue_s = self._fit_text(self._bold_font_path, self._sc(21),
                                   _recording_cue_for(self.game_type), rw, C["accent"], self._sc(15))
            surface.blit(cue_s, (lx, cy))
            cy += cue_s.get_height() + self._sc(5)

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

        if self._finger_group_active:
            # All 5 fingers read simultaneously -- self.live_value/
            # peak_value are scalars here (see update()'s "recording"
            # branch) so they can't drive the normal Live/Peak cards
            # without losing 4 of the 5 readings; show all 5 instead.
            self._draw_finger_group_readings(surface, lx, live_r.y, rw, card_h, C, status)
        elif is_wrist:
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
            self._draw_reading_card(surface, live_r, C, "Live Reading", live_txt,
                                    C["accent"], font=self.fnt["big2"],
                                    tag=live_tag, tag_col=tag_col)
            self._draw_reading_card(surface, peak_r, C, "Peak Reading", peak_txt,
                                    C["green"], font=self.fnt["big2"])
        else:
            live_val = self.live_value if status == "Recording" else None
            peak_val = (self.trial_results[-1] if status == "Completed" and self.trial_results
                        else self.peak_value if status == "Recording" else None)
            live_txt = f"{live_val:.3f}" if live_val is not None else "—"
            peak_txt = f"{peak_val:.3f}" if peak_val is not None else "—"
            self._draw_reading_card(surface, live_r, C, "Live Reading", live_txt,
                                    C["accent"], font=self.fnt["big2"])
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

    def _draw_finger_group_readings(self, surface, lx, cy, rw, card_h, C, status):
        """5-at-once equivalent of the Live/Peak reading cards above, used
        only while self._finger_group_active (Whack-a-Mole / Tile Rush) --
        one compact card per finger showing its own live + peak reading, so
        the therapist can see all 5 channels moving together instead of
        just one representative scalar (self.live_value/peak_value)."""
        names = ["Thumb", "Index", "Middle", "Ring", "Pinky"]
        gap = self._scw(10)
        card_w = (rw - gap * (len(names) - 1)) // len(names)
        live_vals = (input_handler.get_state()["finger_flex"] if status == "Recording" else None)
        peak_vals = (self.trial_results[-1] if status == "Completed" and self.trial_results
                     else self.peak_values if status == "Recording" else None)
        pad = self._scw(10)
        for i, nm in enumerate(names):
            r = pygame.Rect(lx + i * (card_w + gap), cy, card_w, card_h)
            pygame.draw.rect(surface, C["panel"], r, border_radius=12)
            pygame.draw.rect(surface, C["border"], r, 1, border_radius=12)
            lbl_s = self.fnt["small"].render(nm, True, C["sub"])
            surface.blit(lbl_s, (r.x + pad, r.y + self._sc(8)))
            lv_txt = f"{live_vals[i]:.2f}" if live_vals is not None else "—"
            pv_txt = f"peak {peak_vals[i]:.2f}" if peak_vals is not None else "peak —"
            lv_s = self.fnt["bold"].render(lv_txt, True, C["accent"])
            surface.blit(lv_s, (r.x + pad, r.y + self._sc(8) + lbl_s.get_height() + self._sc(4)))
            pv_s = self.fnt["small"].render(pv_txt, True, C["green"])
            surface.blit(pv_s, (r.x + pad,
                                r.y + self._sc(8) + lbl_s.get_height() + lv_s.get_height() + self._sc(8)))

    # ── phase: results ────────────────────────────────────────────────────────

    def _fmt_value_for(self, sensor_type, val):
        """Same formatting _fmt_trial applies for self.game_type, but for
        an arbitrary sensor_type -- needed by _draw_multi_sensor_results,
        which displays every sensor in self.game_types at once rather than
        just whichever one self.game_type currently points at."""
        if sensor_type == "Wrist Rotation":
            return f"{val * 90:.0f}°"
        return f"{val:.3f}"

    def _fmt_trial(self, val):
        """Display text for one trial/average value, in the real unit for
        this sensor -- degrees (magnitude) for Wrist Rotation using the same
        tilt->angle formula as the live monitor/games/key_lock.py, the raw
        0-1 scale (3dp, matching the rest of the app) for Grip/Flex."""
        return self._fmt_value_for(self.game_type, val)

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
        flagged = any(d.get("status") not in (None, validation.PASSED)
                      for d in self.sensor_results.values())
        ban_col = C["orange"] if flagged else C["green"]
        pygame.draw.rect(surface, C["panel"], ban_r, border_radius=12)
        pygame.draw.rect(surface, ban_col, ban_r, 2, border_radius=12)
        hd_s = self.fnt["head2"].render("Calibration Complete!", True, ban_col)
        surface.blit(hd_s, (ban_r.x + u(16), ban_r.y + u(12)))
        sub_s = self._fit_text(
            self._small_font_path, self._sc(18),
            "Some sensors were accepted with a warning. Check them below."
            if flagged else "All required sensors have been successfully calibrated.",
            rw - u(32), C["sub"], self._sc(12))
        surface.blit(sub_s, (ban_r.x + u(16),
                              ban_r.y + u(12) + hd_s.get_height() + u(2)))
        y += ban_h + u(16)

        # ── B. Calibration Results card(s) ──────────────────────────────
        # Single-sensor games (len(self.game_types) == 1): one card, see
        # _multi_card_eligible below.
        #
        # Multi-CATEGORY games (Garden Wonders/Purrfect Feast -- game_types
        # drawn from Grip Strength/Finger Flexion (for Garden Wonders, its
        # own 5-finger group)/Wrist Rotation): self.game_type/self.cfg/
        # self.trial_results only ever reflect the LAST sensor calibrated,
        # so showing just this one card would hide every other sensor's
        # results -- _draw_multi_sensor_results below instead loops
        # self.sensor_results, which has a complete, correctly shaped entry
        # for every sensor in self.game_types. _collapse_finger_group folds
        # a contiguous 5-finger run into one "Finger Flexion" placeholder
        # before checking eligibility, so Garden Wonders' 7-entry list (1
        # Grip + 5 fingers + 1 Wrist) is recognized as the same 3 categories
        # this section already groups -- Whack-a-Mole/Tile Rush's 5-ENTRIES-
        # ALONE list collapses to a single "Finger Flexion" placeholder
        # (len 1, not > 1), so _is_finger_group_alone is checked explicitly
        # below rather than relying on the len > 1 test, which would
        # otherwise route them to the single-sensor card below instead --
        # that card only ever shows self.game_type/self.trial_results, i.e.
        # whichever finger was calibrated LAST (e.g. "Pinky Flex Sensor (5
        # of 5)" showing just Pinky's own result). _draw_finger_group_card
        # instead reads every one of the 5 fingers' own self.sensor_results
        # entry independently, showing all 5 correctly.
        _collapsed = self._collapse_finger_group(self.game_types)
        _is_finger_group_alone = (_collapsed == ["Finger Flexion"])
        _multi_card_eligible = _is_finger_group_alone or (
            len(_collapsed) > 1 and all(t in self._MULTI_RESULTS_HEADING for t in _collapsed))
        if not _multi_card_eligible:
            # Height is sized for the base card content, plus extra headroom
            # when the "Resting baseline removed" line below actually draws
            # (only when baseline > 0, checked here too, not just where it's
            # drawn) so the card is grown by exactly that line's real height
            # instead of guessing and letting the line run past the card's
            # own bottom edge.
            _baseline_for_sizing = self.sensor_baseline.get(self.game_type, 0.0)
            _status_data = self.sensor_results.get(self.game_type) or {}
            res_h = (u(250) + (u(30) if _baseline_for_sizing > 0 else 0)
                     + (u(52) if _status_data.get("status") else 0))
            res_r = pygame.Rect(lx, y, rw, res_h)
            pygame.draw.rect(surface, C["panel"],  res_r, border_radius=12)
            pygame.draw.rect(surface, C["border"], res_r, 1, border_radius=12)

            rh_s = self.fnt["bold"].render("Calibration Results", True, C["text"])
            surface.blit(rh_s, (res_r.x + u(14), res_r.y + u(8)))
            # Same generic "Flex Sensors" relabel as the live calibration
            # title, for the rare case this single-card fallback is showing
            # one specific finger (e.g. "Sensor: Pinky Flex Sensor
            # (Pinky Flexion)") instead of the combined 5-row card.
            _sensor_label = ("Flex Sensors" if self.game_type in _FINGER_FLEX_KEYS
                             else self.cfg['sensor_name'])
            sn_s = self._fit_text(self._small_font_path, self._sc(18),
                                   f"Sensor: {_sensor_label} ({self.game_type})",
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

            # The divider sits at u(160) by default, but moves right if the
            # Average value itself (rendered at a large, unclamped font -- e.g.
            # a Wrist Rotation degree reading can be wider than a 0-1 decimal)
            # would otherwise run into it.
            left_col_w = max(av_lbl_s.get_width(), avl_s.get_width())
            divx = max(res_r.x + u(160), res_r.x + u(14) + left_col_w + u(16))
            status_room = u(52) if _status_data.get("status") else 0
            pygame.draw.line(surface, C["border"], (divx, strip_y),
                             (divx, res_r.bottom - u(10) - status_room), 1)
            if status_room:
                self._draw_status_line(surface, _status_data, res_r.x + u(14),
                                       res_r.bottom - u(28), res_r.width - u(28), C)

            baseline = self.sensor_baseline.get(self.game_type, 0.0)
            thr_now = self._baseline_threshold(avg, baseline, self.adv_threshold_pct)
            thr_disp = self._fmt_trial(thr_now)
            surface.blit(self.fnt["smallb"].render(f"Sensitivity: {self.sensitivity}", True, C["sub"]),
                         (divx + u(16), strip_y + u(4)))
            surface.blit(self.fnt["body"].render(f"Active threshold: {thr_disp}", True, C["accent"]),
                         (divx + u(16), strip_y + u(32)))
            if baseline > 0:
                base_disp = self._fmt_trial(baseline)
                surface.blit(self.fnt["small"].render(f"Resting baseline removed: {base_disp}", True, C["sub"]),
                             (divx + u(16), strip_y + u(58)))
            y += res_h + u(16)
        else:
            y = self._draw_multi_sensor_results(surface, lx, y, rw, C)

        # ── C. Select Difficulty (3 compact cards) ────────────────────
        dh_s = self.fnt["bold"].render("Select Difficulty", True, C["text"])
        surface.blit(dh_s, (lx, y))
        y += dh_s.get_height() + u(8)
        cards_h = self._draw_difficulty_cards(surface, lx, y, rw, C)
        y += cards_h + u(16)

        # ── D. Selected Preset Summary ─────────────────────────────────
        y = self._draw_preset_summary(surface, lx, y, rw, C)
        y += u(16)

        # Real content height (independent of this frame's scroll offset,
        # so next frame's clamping/scrollbar math is correct), then restore
        # the surface's own clip and draw the fixed footer below it.
        # content_top already has -self._results_scroll_y baked in, so
        # y - content_top is already scroll-independent on its own --
        # adding scroll_y again here would make content_h grow by whatever
        # it was just scrolled by, compounding every frame the view wasn't
        # at the very top.
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

    # Category heading shown per sensor on the multi-sensor Results screen --
    # "Grip Strength"/"Finger Flexion" read naturally as-is, but "Wrist
    # Rotation" is the movement, not the hardware; heading it as "Tilt
    # Sensor" matches the terminology already used everywhere else (see
    # SENSOR_CFG["Wrist Rotation"]["sensor_name"]) without renaming the
    # "Wrist Rotation" game_type/SENSOR_CFG key itself.
    _MULTI_RESULTS_HEADING = {
        "Grip Strength":  "Grip Strength",
        "Finger Flexion": "Finger Flexion",
        "Wrist Rotation":  "Tilt Sensor",
    }

    # Display names for the Results screen's Finger Flexion sub-rows --
    # matches the wording asked for (Thumb/Index Finger/Middle Finger/Ring
    # Finger/Little Finger), distinct from _FINGER_FLEX_KEYS' own
    # SENSOR_CFG-key spelling ("Thumb Flexion" etc.).
    _FINGER_DISPLAY_NAMES = {
        "Thumb Flexion":  "Thumb",
        "Index Flexion":  "Index Finger",
        "Middle Flexion": "Middle Finger",
        "Ring Flexion":   "Ring Finger",
        "Pinky Flexion":  "Little Finger",
    }

    @staticmethod
    def _collapse_finger_group(game_types):
        """Replaces a contiguous run exactly matching _FINGER_FLEX_KEYS with
        one "Finger Flexion" placeholder -- lets _draw_results' eligibility
        check treat Garden Wonders' 7-entry (Grip + 5 fingers + Wrist) list
        as the same 3 categories Purrfect Feast/the old Garden Wonders
        already used, without actually renaming anything in
        self.game_types itself (the real per-finger keys are still what
        _draw_multi_sensor_results/_advance_sensor_idx/etc. all walk)."""
        gt = list(game_types)
        n = len(_FINGER_FLEX_KEYS)
        for i in range(len(gt) - n + 1):
            if gt[i:i + n] == _FINGER_FLEX_KEYS:
                return gt[:i] + ["Finger Flexion"] + gt[i + n:]
        return gt

    @staticmethod
    def _status_text(data):
        label = validation.STATUS_LABELS.get(data.get("status"), "")
        detail = data.get("status_detail")
        return f"Check: {label} ({detail})" if detail else f"Check: {label}"

    def _draw_status_line(self, surface, data, x, y, max_w, C):
        """Draws one sensor's validation result; returns the height used."""
        ok = data.get("status") == validation.PASSED
        s = self._fit_text(self._bold_font_path, self._sc(16),
                           "Check: Passed" if ok else self._status_text(data),
                           max_w, C["green"] if ok else C["orange"], self._sc(12))
        surface.blit(s, (x, y))
        return s.get_height()

    def _draw_finger_group_card(self, surface, lx, y, rw, C, header="Finger Flexion"):
        """One combined card for a 5-finger flex group. Shared by two
        callers (see _draw_multi_sensor_results): Garden Wonders, where
        this card is one of several categories (Grip/Fingers/Wrist) and
        keeps the "Finger Flexion" header to match the others -- and
        Whack-a-Mole/Tile Rush, whose game_types is ONLY these 5 entries
        with nothing else, which passes header="Flex Sensors" instead
        since there's no other category it needs to read consistently
        alongside. Each of the 5 rows comes from that
        finger's own self.sensor_results entry, populated by
        _finish_finger_group -- never a shared/averaged value. Height is
        measured from the real wrapped lines before anything is drawn,
        matching every other card here."""
        u = self._sc
        f_small = self.fnt["small"]
        row_max_w = rw - u(28)

        hd_s = self.fnt["bold"].render(header, True, C["text"])
        sn_s = self.fnt["small"].render(
            "Sensor: Flex Sensors (5 independent channels)", True, C["sub"])

        rows = []
        for key in _FINGER_FLEX_KEYS:
            data = self.sensor_results.get(key)
            avg      = data["average"]  if data else 0.0
            baseline = data["baseline"] if data else 0.0
            name = self._FINGER_DISPLAY_NAMES.get(key, key)
            thr = self._baseline_threshold(avg, baseline, self.adv_threshold_pct)
            line = (f"{name}: Average {self._fmt_value_for(key, avg)}  ·  "
                    f"Threshold {self._fmt_value_for(key, thr)}")
            if baseline > 0:
                line += f"  ·  Baseline {self._fmt_value_for(key, baseline)}"
            # This finger's own validation result (see _validate_pass).
            if data and data.get("status"):
                line += f"  ·  {self._status_text(data)}"
            rows.append(self._wrap_text(line, f_small, row_max_w))

        note_lines = self._wrap_text(
            "Gameplay note: any ONE of the 5 fingers reaching its OWN "
            "threshold above triggers the action -- no single finger is "
            "required, and the other 4 are never averaged in or allowed "
            "to block it.",
            f_small, row_max_w)

        top_pad    = u(8)
        header_h   = hd_s.get_height() + u(2) + sn_s.get_height() + u(10)
        line_h     = f_small.get_height() + u(2)
        rows_h     = sum(len(lines) * line_h for lines in rows) + u(4) * len(rows)
        note_h     = u(10) + len(note_lines) * line_h
        bottom_pad = u(10)
        card_h = top_pad + header_h + rows_h + note_h + bottom_pad

        r = pygame.Rect(lx, y, rw, card_h)
        pygame.draw.rect(surface, C["panel"],  r, border_radius=12)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=12)

        ty = r.y + top_pad
        surface.blit(hd_s, (r.x + u(14), ty))
        ty += hd_s.get_height() + u(2)
        surface.blit(sn_s, (r.x + u(14), ty))
        ty += sn_s.get_height() + u(10)

        for key, lines in zip(_FINGER_FLEX_KEYS, rows):
            data = self.sensor_results.get(key) or {}
            col = (C["orange"] if data.get("status") not in (None, validation.PASSED)
                   else C["text"])
            for ln in lines:
                ls = f_small.render(ln, True, col)
                surface.blit(ls, (r.x + u(14), ty))
                ty += line_h
            ty += u(4)

        ty += u(6)
        pygame.draw.line(surface, C["border"], (r.x + u(14), ty - u(5)),
                         (r.right - u(14), ty - u(5)), 1)
        for ln in note_lines:
            ls = f_small.render(ln, True, C["sub"])
            surface.blit(ls, (r.x + u(14), ty))
            ty += line_h

        return y + card_h + u(14)

    def _draw_multi_sensor_results(self, surface, lx, y, rw, C):
        """Multi-sensor Results (Garden Wonders' 3 sensors today, Purrfect
        Feast's 2): one card per sensor in self.game_types, each built from
        that sensor's own self.sensor_results entry -- never
        self.trial_results/self.sensor_baseline/self.game_type, which after
        a multi-sensor run only ever reflect whichever sensor was
        calibrated LAST, which would otherwise show only that one sensor.
        Height is measured from each card's own real content (including the
        wrapped Finger Flexion gameplay note) before anything is drawn, so
        nothing here can overflow its own card. Returns the y position
        immediately below the last card."""
        u = self._sc
        f_small = self.fnt["small"]
        note_max_w = rw - u(28)
        _FLEX_NOTE = (
            "Gameplay note: this game accepts input from any of the 5 flex "
            "sensors (Thumb / Index / Middle / Ring / Pinky) each cycle -- "
            "whichever one reads highest is checked against the threshold "
            "below. No single finger is required, and a low reading on the "
            "other 4 never blocks it."
        )
        idx = 0
        n_types = len(self.game_types)
        n_grp   = len(_FINGER_FLEX_KEYS)
        while idx < n_types:
            # One combined card with 5 sub-rows for any 5-finger run, not 5
            # separate cards (see _draw_finger_group_card). Two shapes
            # reach here: Garden Wonders (this is ONE of several categories
            # alongside Grip/Wrist -- keeps the "Finger Flexion" header to
            # read consistently next to those) and Whack-a-Mole/Tile Rush
            # (game_types is ONLY these 5 entries, nothing else -- uses the
            # generic "Flex Sensors" header instead).
            if self.game_types[idx:idx + n_grp] == _FINGER_FLEX_KEYS:
                header = "Finger Flexion" if n_types > n_grp else "Flex Sensors"
                y = self._draw_finger_group_card(surface, lx, y, rw, C, header=header)
                idx += n_grp
                continue
            sensor_type = self.game_types[idx]
            idx += 1
            data = self.sensor_results.get(sensor_type)
            trials      = data["trials"]      if data else []
            avg         = data["average"]     if data else 0.0
            baseline    = data["baseline"]    if data else 0.0
            sensor_name = data["sensor_name"] if data else SENSOR_CFG[sensor_type]["sensor_name"]
            heading     = self._MULTI_RESULTS_HEADING.get(sensor_type, sensor_type)

            hd_s = self.fnt["bold"].render(heading, True, C["text"])
            sub  = f"Sensor: {sensor_name}"
            if trials:
                sub += f"  ·  {len(trials)} trial(s) recorded"
            sn_s = self._fit_text(self._small_font_path, self._sc(16), sub,
                                   rw - u(28), C["sub"], self._sc(12))
            av_s  = self.fnt["med"].render(self._fmt_value_for(sensor_type, avg), True, C["text"])
            avl_s = self.fnt["small"].render("Average", True, C["sub"])
            thr_now = self._baseline_threshold(avg, baseline, self.adv_threshold_pct)
            thr_s = self.fnt["body"].render(
                f"Active threshold: {self._fmt_value_for(sensor_type, thr_now)}", True, C["accent"])
            base_s = None
            if baseline > 0:
                base_s = self.fnt["small"].render(
                    f"Resting baseline removed: {self._fmt_value_for(sensor_type, baseline)}",
                    True, C["sub"])
            note_lines = (self._wrap_text(_FLEX_NOTE, f_small, note_max_w)
                          if sensor_type == "Finger Flexion" else [])

            top_pad    = u(8)
            header_h   = hd_s.get_height() + u(2) + sn_s.get_height() + u(10)
            row_h      = max(av_s.get_height() + u(2) + avl_s.get_height(),
                             thr_s.get_height() + u(4) + (base_s.get_height() if base_s else 0))
            note_h     = (u(10) + len(note_lines) * (f_small.get_height() + u(2))) if note_lines else 0
            bottom_pad = u(10)
            has_status = bool(data and data.get("status"))
            status_h = (self._sc(24)) if has_status else 0
            card_h = top_pad + header_h + row_h + status_h + note_h + bottom_pad

            r = pygame.Rect(lx, y, rw, card_h)
            pygame.draw.rect(surface, C["panel"],  r, border_radius=12)
            pygame.draw.rect(surface, C["border"], r, 1, border_radius=12)

            ty = r.y + top_pad
            surface.blit(hd_s, (r.x + u(14), ty))
            ty += hd_s.get_height() + u(2)
            surface.blit(sn_s, (r.x + u(14), ty))
            ty += sn_s.get_height() + u(10)

            row_y = ty
            surface.blit(av_s, (r.x + u(14), row_y))
            surface.blit(avl_s, (r.x + u(14), row_y + av_s.get_height() + u(2)))

            left_col_w = max(av_s.get_width(), avl_s.get_width())
            divx = max(r.x + u(150), r.x + u(14) + left_col_w + u(16))
            pygame.draw.line(surface, C["border"], (divx, row_y), (divx, row_y + row_h), 1)

            surface.blit(thr_s, (divx + u(16), row_y))
            if base_s:
                surface.blit(base_s, (divx + u(16), row_y + thr_s.get_height() + u(4)))

            if has_status:
                self._draw_status_line(surface, data, r.x + u(14), row_y + row_h + u(4),
                                       r.width - u(28), C)

            if note_lines:
                note_y = row_y + row_h + status_h + u(10)
                pygame.draw.line(surface, C["border"], (r.x + u(14), note_y - u(5)),
                                 (r.right - u(14), note_y - u(5)), 1)
                for ln in note_lines:
                    ls = f_small.render(ln, True, C["sub"])
                    surface.blit(ls, (r.x + u(14), note_y))
                    note_y += ls.get_height() + u(2)

            y += card_h + u(14)
        return y

    def _draw_difficulty_cards(self, surface, lx, ry, rw, C):
        """Easy/Medium/Hard cards. Height is measured from the tallest
        card's own content (name + optional RECOMMENDED badge + the FULL
        description, never truncated to a fixed line count -- a truncated
        description could cut off mid-word) and shared by all 3, so a short
        card isn't cramped and a long one isn't clipped. Returns the row
        height actually used, so the caller can lay out whatever comes next
        at the right y."""
        n   = len(PRESET_ORDER)
        gap = self._scw(12)
        cw  = (rw - gap * (n - 1)) // n
        f_small = self.fnt["small"]
        desc_max_w = cw - self._scw(20)

        # ── measure pass: every card's own content height ──
        cards_info = []
        max_content_h = 0
        for name in PRESET_ORDER:
            p = DIFFICULTY_PRESETS[name]
            rec = (self.recommended_preset == name)
            nm_h = self.fnt["bold"].get_height()
            content_h = self._sc(8) + nm_h + self._sc(4)

            rc_s = None
            if rec:
                rc_s = self._fit_text(self._bold_font_path, self._sc(20), "RECOMMENDED",
                                       cw - self._scw(16), C["white"], self._sc(12))
                content_h += rc_s.get_height() + self._sc(4) + self._sc(4)

            thr_val = round(p["threshold_pct"], 0)
            dt = f"Threshold {int(thr_val)}%  ·  {p['desc'].split('—')[0].strip()}"
            lines = self._wrap_text(dt, f_small, desc_max_w)
            content_h += self._sc(2) + len(lines) * (f_small.get_height() + self._sc(2)) + self._sc(8)

            cards_info.append((name, p, rec, rc_s, lines))
            max_content_h = max(max_content_h, content_h)

        ch = max_content_h

        # ── draw pass: every card at the one shared height ──
        self._preset_card_rects = {}
        for i, (name, p, rec, rc_s, lines) in enumerate(cards_info):
            cr  = pygame.Rect(lx + i * (cw + gap), ry, cw, ch)
            sel = (self.selected_preset == name)
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
                rc_r = pygame.Rect(0, 0, rc_s.get_width() + self._scw(10),
                                   rc_s.get_height() + self._sc(4))
                rc_r.topleft = (cr.x + self._scw(10), next_y)
                pygame.draw.rect(surface, C["green"], rc_r, border_radius=self._sc(6))
                surface.blit(rc_s, rc_s.get_rect(center=rc_r.center))
                next_y = rc_r.bottom + self._sc(4)

            ty = next_y + self._sc(2)
            for ln in lines:
                ls = f_small.render(ln, True, C["sub"])
                surface.blit(ls, (cr.x + self._scw(10), ty))
                ty += ls.get_height() + self._sc(2)

            self._preset_card_rects[name] = cr

        return ch

    # Groups a GAME_PARAM_SCHEMA row under the sensor its own label names --
    # there's no structured sensor tag on these entries, only this label-text
    # convention (every game's "Required Grip Strength"/"Required Finger
    # Flexion"/"Required Wrist Rotation" row already follows it -- see the
    # schema above). Anything that doesn't name a specific sensor (goal
    # score, speeds, hold durations, tolerances...) falls back to the
    # generic "Game Parameters" bucket.
    @staticmethod
    def _categorize_param(label):
        low = label.lower()
        if "grip strength" in low:
            return "Grip Strength"
        if "finger flexion" in low:
            return "Finger Flexion"
        if "wrist" in low:
            return "Tilt Sensor"
        return "Game Parameters"

    def _draw_preset_summary(self, surface, lx, cy, rw, C):
        """Section D/E: EVERY setting the therapist can actually customize
        for this game + the selected difficulty preset -- not just the
        game's own GAME_PARAM_SCHEMA rows, but also the generic
        Difficulty/Speed/Session Duration preset fields and the Activation
        Threshold % (the stepper in Advanced Settings), grouped into
        category headings so a Multi-Skill game's settings are clearly
        attributed to the sensor they actually affect -- never merging the
        generic Activation Threshold % with a game's own distinctly-keyed
        "Required <Sensor>" param, even though both happen to be percentages.
        Every row's text is wrapped up front and the box height measured
        from those exact wrapped lines, so nothing drawn below can ever
        disagree with what was measured. Height grows with however many
        rows this game actually has -- Calibration Results is a scrollable
        page, so there's no reason to force everything into a cramped box.
        Returns the y position immediately below the box."""
        def u(n): return self._sc(n)
        f_small = self.fnt["small"]
        text_max_w = rw - u(14) - u(24) - u(14)

        multi = len(self.game_types) > 1
        headings = ([self._MULTI_RESULTS_HEADING.get(t, t) for t in self.game_types] if multi
                    else [self._MULTI_RESULTS_HEADING.get(self.game_type, self.game_type)])

        raw_sections = []

        diff_rows = [f"Difficulty: {self.selected_preset}"]
        if self.game_name in GAMES_USING_SPEED:
            diff_rows.append(f"Speed: {self.adv_speed}")
        diff_rows.append(f"Session Duration: {self.adv_duration}")
        raw_sections.append(("Difficulty Configuration", diff_rows))

        if multi:
            raw_sections.append(("Sensor Thresholds", [
                f"Activation Threshold: {self.adv_threshold_pct}% of each sensor's own "
                f"calibrated range (applies to {', '.join(headings)})"]))
        else:
            raw_sections.append(("Sensor Thresholds", [
                f"Activation Threshold: {self.adv_threshold_pct}% of calibrated range"]))

        by_cat = {}
        for spec in self.param_schema:
            cat = self._categorize_param(spec["label"])
            by_cat.setdefault(cat, []).append(f"{spec['label']}: {self._fmt_chip(spec)}")
        for cat in ("Grip Strength", "Finger Flexion", "Tilt Sensor", "Game Parameters"):
            if by_cat.get(cat):
                raw_sections.append((cat, by_cat[cat]))

        sections = [(cat, [self._wrap_text(row, f_small, text_max_w) for row in rows])
                    for cat, rows in raw_sections]

        hd_s = self.fnt["bold"].render(f"Selected Preset ({self.selected_preset})",
                                       True, C["text"])
        line_h   = f_small.get_height() + u(2)
        header_h = u(10) + hd_s.get_height() + u(10)
        body_h = 0
        for _cat, rows in sections:
            body_h += self.fnt["smallb"].get_height() + u(6)
            for lines in rows:
                body_h += len(lines) * line_h
            body_h += u(6)
        box_h = header_h + body_h + u(6)

        r = pygame.Rect(lx, cy, rw, box_h)
        pygame.draw.rect(surface, C["panel"],  r, border_radius=12)
        pygame.draw.rect(surface, C["border"], r, 1, border_radius=12)
        surface.blit(hd_s, (r.x + u(14), r.y + u(10)))

        badge_txt = "● CUSTOMIZED" if self.customized else "DEFAULT PRESET"
        badge_col = C["orange"] if self.customized else C["accent"]
        bd_s = self.fnt["tag"].render(badge_txt, True, C["white"])
        bd_r = pygame.Rect(0, 0, bd_s.get_width() + u(16), bd_s.get_height() + u(8))
        bd_r.topright = (r.right - u(12), r.y + u(8))
        pygame.draw.rect(surface, badge_col, bd_r, border_radius=u(6))
        surface.blit(bd_s, bd_s.get_rect(center=bd_r.center))

        ty = r.y + header_h
        for cat, rows in sections:
            cs = self.fnt["smallb"].render(cat, True, C["accent"])
            surface.blit(cs, (r.x + u(14), ty))
            ty += cs.get_height() + u(6)
            for lines in rows:
                for ln in lines:
                    ls = f_small.render(ln, True, C["sub"])
                    surface.blit(ls, (r.x + u(24), ty))
                    ty += line_h
            ty += u(6)
        return cy + box_h

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
            _adv_avg = (sum(self.trial_results) / len(self.trial_results)
                        if self.trial_results else 0.0)
            thr_now = self._baseline_threshold(
                _adv_avg, self.sensor_baseline.get(self.game_type, 0.0), self.adv_threshold_pct)
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
            # Finger-group trials store a 5-long list (one peak per finger,
            # see update()'s "recording" branch) -- no single number
            # summarizes that, so show "Done" instead of trying to format
            # a list as a float.
            if i < len(self.trial_results):
                val = self.trial_results[i]
                lbl = "Done" if isinstance(val, list) else f"{val:.2f}"
            else:
                lbl = f"Trial {i + 1}"
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
