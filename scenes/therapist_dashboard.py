# =============================================================================
# scenes/therapist_dashboard.py
# =============================================================================
#
# CHANGES vs previous version:
#   1. Table column widths widened across Patients / Session History / Calibration
#       so longer Patient Names, IDs (10 chars), Severity, and Therapist all fit;
#       row heights and inter-row spacing increased to match the bigger font.
#   2. Register Patient row_gap increased (58→72px) and fh increased (36→40px)
#      to prevent field overlap
#   3. Register Patient dropdowns now draw in a second pass so they always
#      appear on top of all other fields (z-order fix)
#   4. Calibration bypass toggle added to Start Session panel for dev testing
#   5. Patients are now private per therapist — get_all_patients filters by
#      therapist_id so each therapist only sees their own patients plus those
#      explicitly shared with them
#   6. Share Patient modal — therapists can share a patient with another therapist
#      by searching their username; stored in patient_shares junction table
#
# FLOW:
#   Home (4 cards) → Patient List → [select patient] → Game Configuration
#                                 → [game set]       → Start Session
#   Home           → Session History
#   Home           → Analytics
#   Home           → Calibration Records
#
# NAV_IDX mapping (used internally):
#   0 = Patient List          (home card 0)
#   1 = Session History       (home card 1)
#   2 = Analytics             (home card 2)
#   3 = Calibration Records   (home card 3)
#   4 = Game Configuration    (NOT on home — reached via Patient List)
#   5 = Start Session         (NOT on home — reached via Game Config)
#   6 = Register Patient      (NOT on home — reached via Patient List)
# =============================================================================

import pygame
import sys, os, math, datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database, validate_username, username_char_allowed, MAX_USERNAME_LEN
from scenes.icon_renderer import draw_icon, ICONS
from scenes.calibration_window import CalibrationWindow, GAME_PARAM_SCHEMA, SENSOR_CFG
from audio import (play_confirm_alert, play_start_session, play_click,
                    start_lobby_music, stop_lobby_music)
from sensors.input_handler import input_handler
try:
    from sensors.ble_receiver import ble_receiver as _ble_receiver
except Exception:
    _ble_receiver = None

# ── Dual-monitor mode (opt-in via recovr/launch_production.py) ────────────
# When RECOVR_DUAL_MONITOR=1, "Start Session" hands the game to the patient
# window (a separate process on the other monitor) instead of switching this
# window to the game scene, and this dashboard stays live showing a small
# session-monitoring panel with Pause/Resume/Stop. Everything below is inert
# and this file behaves exactly as before when the flag is unset.
_DUAL_MONITOR = os.environ.get("RECOVR_DUAL_MONITOR") == "1"
if _DUAL_MONITOR:
    try:
        from recovr.therapist_link import therapist_link
        from recovr.shared import commands as _rc_cmd
    except Exception as _exc:               # pragma: no cover - defensive
        print(f"[recovr] dual-monitor link unavailable ({_exc}); staying single-window")
        _DUAL_MONITOR = False

# Development/testing only -- shows the "Test Mode (Bypass)" toggle on Start
# Session. Permanently on for this development phase (no env var / launch
# flag needed, so `python main.py` alone shows it); the toggle itself still
# defaults to OFF each run (self._test_mode_bypass below) and must be
# switched on by hand. Flip this back to False once testing is done.
_TEST_MODE_AVAILABLE = True

# ─────────────────────────────────────────────────────────────────────
#  NAV / PANEL CONSTANTS
# ─────────────────────────────────────────────────────────────────────

HOME_CARDS = [
    {"label": "Patient List",         "symbol": "👤", "idx": 0},
    {"label": "Session History",      "symbol": "📋", "idx": 1},
    {"label": "Analytics",            "symbol": "📊", "idx": 2},
    {"label": "Calibration Records",  "symbol": "🎯", "idx": 3},
]

HOME_COLORS = [
    (100, 180, 240),
    (240, 170,  90),
    (190, 130, 220),
    (235, 100, 120),
]

PANEL_TITLES = {
    0: "Patient List",
    1: "Session History",
    2: "Analytics",
    3: "Calibration Records",
    4: "Game Configuration",
    5: "Start Rehabilitation Session",
    6: "Register Patient",
    7: "Session in Progress",
    8: "Patient",
}

PANEL_COLORS = {
    0: (100, 180, 240),
    1: (240, 170,  90),
    2: (190, 130, 220),
    3: (235, 100, 120),
    4: ( 80, 195, 195),
    5: ( 60, 140, 220),
    6: (130, 200, 140),
    7: ( 60, 140, 220),
    8: (150, 130, 220),
}

# Sidebar navigation is now EMPTY. The Patient List is the Therapist Dashboard
# itself (panel 0, shown on load); Session History / Analytics / Calibration
# Records moved into the Patient Preview panel. Panels 0-3 draw methods are
# unchanged and still reachable code. Navigation back to the Patient List is via
# the standard Back buttons on each sub-panel.
SIDEBAR_NAV = []

ROLES = [
    "Physical Therapist",
    "Occupational Therapist",
    "Rehabilitation Specialist",
    "Neurological Rehab Therapist",
    "Other",
]

STROKE_TYPES  = ["Ischemic", "Hemorrhagic", "Unknown / Not Specified"]
SEX_OPTS      = ["Male", "Female"]
HAND_OPTS     = ["Left", "Right"]

SINGLE_SKILL_GAMES = [
    ("Catch 'n Grab",            "Grip Strength"),
    ("Whack-a-Mole",       "Finger Flexion"),
    ("Key & Lock",               "Wrist Rotation"),
]
INTEGRATED_GAMES = [
    ("Dual Skill",  "Dual Skill"),
    ("Multi-skill", "Multi-skill"),
]
ALL_GAMES = SINGLE_SKILL_GAMES + INTEGRATED_GAMES

# Game Configuration tile artwork -- each is a wide pill-shaped button with
# its label already baked into the image (assets/images/), replacing the
# old plain-color tile + drawn text label.
GAME_TILE_ASSETS = {
    "Grip Strength":  "gripstrength.png",
    "Finger Flexion": "fingerflexion.png",
    "Wrist Rotation": "wristrotation.png",
    "Dual Skill":     "dualskill.png",
    "Multi-skill":    "multiskill.png",
}

# Per-game icon for the Start Session screen's Game Information card -- one
# of the six currently-implemented games.
GAME_ICON_ASSET = {
    "Basketball":     "basketball_icon.png",
    "Lemonade":       "lemonade_icon.png",
    "Apple Catching": "apple_catching_icon.png",
    "Piano Tiles":    "piano_tiles_icon.png",
    "Key and Lock":   "key_and_lock_icon.png",
    "Steady Aim":     "steady_aim_icon.png",
    "Feed the Cat":   "feed_the_cat_icon.png",
    "Catch 'n Grab":  "catch_n_grab_icon.png",
    "Plant the Garden": "plant_the_garden_icon.png",
    # No dedicated icon asset exists yet for this game -- reuses the mole
    # hole art (already a small, roughly-square, game-representative image)
    # instead of leaving the Game Information card's icon chip blank.
    "Whack-a-Mole": "hole_whack_a_mole.png",
}

# Metrics tab hierarchy -- Main category -> Subcategory -> [game names],
# fixed by spec (deliberately NOT derived from SINGLE_SKILL_GAMES /
# INTEGRATED_GAMES above, which is Game Configuration's own game-picker --
# a different screen with its own, differently-grouped categorization that
# this doesn't touch). Every game name matches _GAME_SCENE_MAP exactly; no
# Gravity Catch (removed from the game roster already).
METRICS_TREE = [
    ("Single Skill", [
        ("Grip Strength",  ["Basketball", "Lemonade"]),
        ("Finger Flexion", ["Piano Tiles", "Whack-a-Mole"]),
        ("Wrist Rotation", ["Apple Catching", "Key and Lock", "Steady Aim"]),
    ]),
    ("Integrated", [
        ("Dual Skill",  ["Catch 'n Grab", "Feed the Cat"]),
        ("Multi Skill", ["Plant the Garden"]),
    ]),
]
METRICS_MODES = [("target", "Target Mode"), ("timed", "Timed Mode")]
# Subcategory tile art -- reuses the existing Game Configuration tile
# images (GAME_TILE_ASSETS above); "Multi Skill" here maps to that dict's
# "Multi-skill" key, the only naming mismatch between the two.
METRICS_SUB_ICON = {
    "Grip Strength":  GAME_TILE_ASSETS["Grip Strength"],
    "Finger Flexion": GAME_TILE_ASSETS["Finger Flexion"],
    "Wrist Rotation": GAME_TILE_ASSETS["Wrist Rotation"],
    "Dual Skill":     GAME_TILE_ASSETS["Dual Skill"],
    "Multi Skill":    GAME_TILE_ASSETS["Multi-skill"],
}

SKILL_GAMES = {
    "Grip Strength":  ["Basketball", "Lemonade"],
    "Finger Flexion": ["Piano Tiles", "Whack-a-Mole"],
    "Wrist Rotation": ["Apple Catching", "Key and Lock", "Steady Aim"],
    "Dual Skill":     ["Catch 'n Grab", "Feed the Cat"],
    "Multi-skill":    ["Plant the Garden"],
}

# Fixed sensor calibration order for every multi-sensor game: FSR402 ->
# Flex Sensors -> MPU6050. Only the sensors a given game actually needs are
# included (see MULTI_SENSOR_CALIBRATION/_required_sensors_for_game) -- this
# list is just the canonical ORDER those sensors are calibrated in whenever
# more than one is required.
SENSOR_ORDER = ["Grip Strength", "Finger Flexion", "Wrist Rotation"]

# Games whose calibration needs more than one sensor pass, in the exact
# sequence CalibrationWindow should calibrate them -- see
# CalibrationWindow.__init__'s game_types list param. Every game NOT listed
# here calibrates exactly as before (a single sensor pass); this is
# deliberately opt-in per game rather than derived from GAME_SENSOR_SPEC, so
# games not yet audited for a real multi-sensor calibration pass are
# unaffected. Every entry here is written in SENSOR_ORDER already (FSR402 ->
# Flex -> MPU6050), since CalibrationWindow walks this list in the order
# given.
#
# Feed the Cat and Catch 'n Grab are "Dual Skill" in SKILL_GAMES/
# GAME_SENSOR_SPEC (grip + wrist telemetry) but, before this entry existed,
# were never actually calibrated for both: "Dual Skill" isn't a SENSOR_CFG
# key, so CalibrationWindow silently fell back to a single Grip-Strength-only
# pass and the MPU6050 pass never ran. Listing them here is a real-logic fix,
# not a cosmetic one -- their gameplay wrist thresholds were previously left
# at CalibrationWindow's unset defaults.
MULTI_SENSOR_CALIBRATION = {
    "Plant the Garden": ["Grip Strength", "Finger Flexion", "Wrist Rotation"],
    "Feed the Cat":      ["Grip Strength", "Wrist Rotation"],
    "Catch 'n Grab":     ["Grip Strength", "Wrist Rotation"],
    # Whack-a-Mole's 5 fingers calibrate independently, one pass each
    # (see scenes/calibration_window.py's _FINGER_FLEX_KEYS) -- NOT the
    # single shared "Finger Flexion" pass Piano Tiles/Plant the Garden/
    # Steady Aim use, so none of those games' calibration is affected.
    "Whack-a-Mole": ["Thumb Flexion", "Index Flexion", "Middle Flexion",
                           "Ring Flexion", "Pinky Flexion"],
}


def _required_sensors_for_game(game_name, game_type):
    """Canonical (FSR402 -> Flex -> MPU6050), always-correctly-ordered list
    of sensor types `game_name` needs calibrated, whether it's a single- or
    multi-sensor game -- the one place calibration-reuse logic should ask
    "what does this game need", instead of each call site re-deriving it
    from MULTI_SENSOR_CALIBRATION/game_type separately."""
    multi = MULTI_SENSOR_CALIBRATION.get(game_name)
    if multi:
        return list(multi)
    return [game_type] if game_type in SENSOR_CFG else []

# CalibrationWindow's game_type strings -> the patient Calibration screen's
# asset/content key (see recovr/patient_app/scenes/calibrating.py). Dual
# monitor only -- pushed to the patient via therapist_link so its screen
# always mirrors whichever sensor CalibrationWindow is actually on.
_CAL_SENSOR_KEY = {
    "Grip Strength":  "grip",
    "Finger Flexion": "flex",
    "Wrist Rotation": "wrist",
    # Whack-a-Mole's 5 per-finger passes all reuse the same "flex"
    # patient-screen content as "Finger Flexion" above (the instruction is
    # the same gesture -- bend the finger); the therapist-side title still
    # shows which specific finger via SENSOR_CFG's own "sensor_name".
    "Thumb Flexion":  "flex",
    "Index Flexion":  "flex",
    "Middle Flexion": "flex",
    "Ring Flexion":   "flex",
    "Pinky Flexion":  "flex",
}

# Timed Mode's per-game, per-difficulty default session length (seconds) --
# mirrors each game's own DURATION dict (games/*.py), used only to seed the
# Session Settings screen's stepper with a sensible starting number; the
# game itself falls back to this exact same preset if the therapist leaves
# gc["duration_sec"] at None, so the two can never drift apart.
GAME_TIMED_DURATION_PRESETS = {
    "Basketball":        {"Easy": 40,  "Medium": 35,  "Hard": 30},
    "Lemonade":          {"Easy": 90,  "Medium": 120, "Hard": 150},
    "Piano Tiles":       {"Easy": 60,  "Medium": 60,  "Hard": 60},
    "Apple Catching":    {"Easy": 60,  "Medium": 50,  "Hard": 40},
    "Key and Lock":      {"Easy": 60,  "Medium": 50,  "Hard": 40},
    "Steady Aim":        {"Easy": 90,  "Medium": 75,  "Hard": 60},
    "Catch 'n Grab":     {"Easy": 60,  "Medium": 50,  "Hard": 40},
    "Feed the Cat":      {"Easy": 60,  "Medium": 50,  "Hard": 40},
    "Plant the Garden":  {"Easy": 120, "Medium": 100, "Hard": 80},
    "Whack-a-Mole": {"Easy": 45, "Medium": 40, "Hard": 35},
}
# Timed Mode's therapist-facing default/step on the Session Settings screen
# -- 7 minutes, adjusted 1 minute at a time (replaces the old per-game/
# difficulty seed above, which still exists ONLY as the dead-path fallback
# for a duration_sec that was never set at all, e.g. a session configured
# without ever opening Session Settings -- see _game_goal_text).
TIMED_DURATION_DEFAULT_SEC = 7 * 60
TIMED_DURATION_STEP_SEC    = 60
# TEMPORARY testing presets (10s / 30s) so a full session can be run end to
# end quickly during development without waiting out a real 7-minute timer.
# Remove this tuple (and its one call site in _draw_gc_step_settings /
# _gc_handle_settings_click) before final deployment.
TIMED_DURATION_TEST_PRESETS_SEC = (10, 30)
# Reverse of SKILL_GAMES -- game display name -> its exercise category, for
# the Session Information header (Session In Progress screen).
GAME_CATEGORY = {g: cat for cat, games in SKILL_GAMES.items() for g in games}

# Which sensor(s) the Session In Progress monitoring container shows for each
# game, in display order (raw/calibrated columns stay paired by this order).
# Each entry: (telemetry "sensors" key, display label, sensor hardware name,
# value format). Formats:
#   "pct"        0..1 value        -> shown as a plain 0-100 number
#   "pct_signed" -1..1 value       -> shown as a signed 0-100-ish number
#   "deg"        raw -1..1 (pct_signed), calibrated already in real degrees
#   "flex"       0..1 flex reading -> calibrated shown as Pressed/Idle against
#                the SAME InputHandler.FLEX_THRESH the game itself fires on
GAME_SENSOR_SPEC = {
    "Basketball":               [("grip",   "Grip Strength",      "FSR402",      "pct")],
    "Lemonade":                 [("grip",   "Grip Strength",      "FSR402",      "pct")],
    "Catch 'n Grab":             [("grip",   "Grip Strength",      "FSR402",      "pct"),
                                  ("tilt_x", "Wrist Movement",     "MPU6050",     "pct_signed")],
    "Feed the Cat":              [("grip",   "Grip Strength",      "FSR402",      "pct"),
                                  ("tilt_x", "Wrist Movement",     "MPU6050",     "pct_signed")],
    "Piano Tiles":                [("tilt_y", "Finger Flexion",     "Flex Sensor", "flex")],
    # 5 independent finger channels (see generic_adapter.py's
    # _sensor_telemetry "finger_*" keys and sensors/input_handler.py's
    # FINGER_NAMES) -- NOT the single shared tilt_y "Finger Flexion" row
    # Piano Tiles uses above, since Whack-a-Mole needs each finger shown
    # separately, not one combined reading.
    "Whack-a-Mole":         [("finger_thumb",  "Thumb",  "Flex Sensor", "flex"),
                                    ("finger_index",  "Index",  "Flex Sensor", "flex"),
                                    ("finger_middle", "Middle", "Flex Sensor", "flex"),
                                    ("finger_ring",   "Ring",   "Flex Sensor", "flex"),
                                    ("finger_pinky",  "Pinky",  "Flex Sensor", "flex")],
    "Apple Catching":             [("tilt_x", "Wrist Movement",     "MPU6050",     "pct_signed")],
    "Key and Lock":               [("tilt_x", "Wrist Rotation",     "MPU6050",     "deg")],
    "Steady Aim":                 [("tilt_x", "Wrist Movement (H)", "MPU6050",     "pct_signed"),
                                    ("tilt_y", "Wrist Movement (V)", "MPU6050",     "pct_signed")],
    "Plant the Garden":           [("tilt_x", "Wrist Movement",     "MPU6050",     "pct_signed"),
                                    ("tilt_y", "Finger Flexion",     "Flex Sensor", "flex"),
                                    ("grip",   "Grip Strength",      "FSR402",      "pct")],
}

DIFFICULTY_OPTS = ["Easy", "Medium", "Hard", "Custom"]
SMART_PRESETS   = {
    "Mild":     {"duration": "60 seconds", "speed": "Normal", "sensitivity": "Medium", "difficulty": "Medium"},
    "Moderate": {"duration": "60 seconds", "speed": "Normal", "sensitivity": "Medium", "difficulty": "Easy"},
}


# ─────────────────────────────────────────────────────────────────────
#  DRAW HELPERS
# ─────────────────────────────────────────────────────────────────────

def _card_bg(surface, rect, alpha=200, radius=14,
             border_col=(200, 218, 240), border_w=1):
    bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(bg, (232, 242, 255, alpha),
                     (0, 0, rect.width, rect.height), border_radius=radius)
    surface.blit(bg, rect.topleft)
    pygame.draw.rect(surface, border_col, rect, border_w, border_radius=radius)


def _grad_box(surface, rect, col_a, col_b, radius=10, border_col=None, border_w=1):
    """A rounded rect filled with a left-to-right linear gradient (col_a ->
    col_b), used for the sidebar's Active Patient / controller-status boxes
    per the reference mock (soft two-tone panels instead of a flat fill)."""
    w, h = max(1, rect.width), max(1, rect.height)
    grad = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(w):
        t = x / max(1, w - 1)
        col = tuple(int(col_a[i] + (col_b[i] - col_a[i]) * t) for i in range(3))
        pygame.draw.line(grad, (*col, 255), (x, 0), (x, h))
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, w, h), border_radius=radius)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(grad, rect.topleft)
    if border_col:
        pygame.draw.rect(surface, border_col, rect, border_w, border_radius=radius)


def _empty_state(surface, rect, icon_text, heading, subtext,
                 fnt_head, fnt_sub, action_label=None, fnt_btn=None):
    cx = rect.centerx
    cy = rect.centery - int(rect.height * 0.05)
    r  = int(min(rect.width, rect.height) * 0.09)
    pygame.draw.circle(surface, (228, 238, 252), (cx, cy - r // 2), r)
    ic = fnt_head.render(icon_text, True, (158, 183, 218))
    surface.blit(ic, ic.get_rect(center=(cx, cy - r // 2)))
    hs = fnt_head.render(heading, True, (108, 128, 158))
    surface.blit(hs, hs.get_rect(center=(cx, cy + int(r * 0.85))))
    ss = fnt_sub.render(subtext, True, (153, 170, 193))
    surface.blit(ss, ss.get_rect(center=(cx, cy + int(r * 0.85) + hs.get_height() + 6)))
    if action_label and fnt_btn:
        ar = pygame.Rect(0, 0, int(rect.width * 0.40), int(rect.height * 0.075))
        ar.center = (cx, cy + int(r * 0.85) + hs.get_height() + ss.get_height() + 26)
        pygame.draw.rect(surface, (198, 213, 233), ar, 1, border_radius=20)
        als = fnt_btn.render(action_label, True, (98, 133, 188))
        surface.blit(als, als.get_rect(center=ar.center))


def _btn(surface, rect, label, font, col_normal, col_hover, hovered, radius=10):
    pygame.draw.rect(surface, col_hover if hovered else col_normal, rect, border_radius=radius)
    s = font.render(label, True, (255, 255, 255))
    surface.blit(s, s.get_rect(center=rect.center))


def _img_btn(surface, rect, asset, enabled, hovered, fallback_label, font,
             col_normal=(40, 160, 80), col_disabled=(175, 188, 202), radius=10):
    """A button drawn from a pill-shaped asset (assets/images/), replacing
    the old colored-rect + text _btn() for these specific buttons. Falls
    back to the original _btn() look if the asset is ever missing."""
    img = _img_fit(asset, rect.width, rect.height)
    if img is not None:
        if not enabled:
            img = img.copy()
            img.set_alpha(120)
        surface.blit(img, img.get_rect(center=rect.center))
    else:
        col = col_normal if enabled else col_disabled
        colh = tuple(max(0, c - 15) for c in col_normal) if enabled else col_disabled
        _btn(surface, rect, fallback_label, font, col, colh, hovered and enabled, radius=radius)


_IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "images")
_img_cache: dict = {}


def _img(name, size=None):
    """A square illustration from assets/images/, uniformly scaled to
    `size x size` and cached. Returns None (silently) if the file is
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
    a square canvas (e.g. a wide pill-shaped button centered in a 3375x3375
    file) -- crops to the actual opaque content once, then scales it to fit
    within w x h preserving its own aspect ratio (never stretched into an
    oval/squished pill), centered by the caller via get_rect(center=...)."""
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


_shimmer_mask_cache: dict = {}


def _shimmer_mask(name, w, h):
    """A white-where-opaque / transparent-elsewhere stencil for the asset
    `_img_fit(name, w, h)` renders, cached per (name, w, h) alongside it.
    Used to clip the Controller Status shimmer to the asset's own card
    shape (incl. its rounded corners) instead of spilling a plain rectangle
    past them. Returns None if the asset itself is missing."""
    key = (name, w, h)
    if key in _shimmer_mask_cache:
        return _shimmer_mask_cache[key]
    img = _img_fit(name, w, h)
    result = (pygame.mask.from_surface(img).to_surface(
                  setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
              if img is not None else None)
    _shimmer_mask_cache[key] = result
    return result


def _draw_shimmer(surface, rect, mask_surf, t_ms, period_ms=1800):
    """Soft diagonal light-sweep across `rect` (the Controller Status card
    while it's searching), masked to the card art's own opaque shape so it
    never spills past its rounded corners. A handful of nested translucent
    parallelograms (cheap vector fills), not a per-pixel gradient -- stays
    light enough for a Raspberry Pi 4 every frame."""
    w, h = rect.size
    if w <= 1 or h <= 1 or mask_surf is None:
        return
    band = pygame.Surface((w, h), pygame.SRCALPHA)
    skew = int(h * 0.6)                          # diagonal lean
    bw   = max(8, int(w * 0.22))                  # outermost half-width
    frac = (t_ms % period_ms) / period_ms         # 0..1, loops forever
    cx   = -bw * 2 + frac * (w + bw * 4)          # sweeps fully across + margin
    for half_w, alpha in ((bw, 50), (bw * 0.6, 90), (bw * 0.28, 130)):
        pts = [(cx - half_w, 0), (cx + half_w, 0),
               (cx + half_w + skew, h), (cx - half_w + skew, h)]
        pygame.draw.polygon(band, (255, 255, 255, alpha), pts)
    band.blit(mask_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(band, rect.topleft)


def _img_cover(name, w, h):
    """A full-bleed background image scaled + center-cropped to exactly fill
    w x h (preserves aspect ratio -- no stretching/distortion). Returns None
    if the file is missing."""
    key = ("cover", name, w, h)
    if key in _img_fit_cache:
        return _img_fit_cache[key]
    try:
        raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert()
        rw, rh = raw.get_size()
        scale = max(w / rw, h / rh)
        sw, sh = max(1, int(rw * scale)), max(1, int(rh * scale))
        scaled = pygame.transform.smoothscale(raw, (sw, sh))
        x, y = (sw - w) // 2, (sh - h) // 2
        result = scaled.subsurface((x, y, w, h)).copy()
    except Exception:
        result = None
    _img_fit_cache[key] = result
    return result


# ─────────────────────────────────────────────────────────────────────
#  SHARED CONFIRMATION / WARNING DIALOG
#
#  One reusable, theme-aware popup used by EVERY confirm/cancel and
#  single-OK dialog in the therapist interface (Select/Deselect Patient,
#  Delete Patient, Delete Account, Logout, Calibration Mismatch, Session
#  Stopped, the Back-during-gameplay warning, Registration Success, and
#  -- via main.py, which has no TherapistDashboardScene instance to call
#  methods on -- the Close Application dialog). Takes plain tt/sc scale
#  functions and a small fonts dict instead of `self` so it works
#  identically from inside the scene and from main.py's module-level code.
# ─────────────────────────────────────────────────────────────────────

def _wrap_text(text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.size(t)[0] <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _truncate_text(text, font, max_w):
    """`text`, or the longest prefix of it (+ "…") that still fits max_w --
    for a single-line label (e.g. a patient-name subtitle) that must stay
    exactly one line regardless of how long the real name is, where
    wrapping would blow a tight modal's height budget and shrinking the
    font is explicitly off the table. A no-op whenever text already fits."""
    if font.size(text)[0] <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(text[:mid] + "…")[0] <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + "…") if lo > 0 else "…"


def _draw_dialog_icon(surface, center, r, icon, accent, dark):
    """The circular action icon near the dialog's top. Real project assets
    (patient.png + a plus/minus badge, the existing game_stop.png /
    close_button.png circular badges) where one fits the action; a small
    vector glyph on a plain accent-colored circle otherwise -- the same
    fallback style already used elsewhere in this file (the '!' / '✓'
    circles), never a second icon font dependency."""
    cx, cy = center
    white = (255, 255, 255)

    if icon in ("select", "deselect"):
        # patient.png (a real square illustration, not a text-baked pill
        # like select_patient.png/deselect_patient.png) + a small plus/minus
        # badge overlapping its bottom-right corner -- the same "avatar +
        # small overlapping status badge" pattern already used for the
        # sidebar profile/edit badge.
        d = int(r * 2.1)
        img = _img_fit("patient.png", d, d)
        if img is not None:
            surface.blit(img, img.get_rect(center=center))
        else:
            pygame.draw.circle(surface, accent, center, r)
        badge_r = max(6, int(r * 0.42))
        bx, by = cx + int(d * 0.30), cy + int(d * 0.30)
        badge_col = (45, 150, 95) if icon == "select" else (205, 70, 60)
        pygame.draw.circle(surface, white, (bx, by), badge_r + max(2, badge_r // 5))
        pygame.draw.circle(surface, badge_col, (bx, by), badge_r)
        bw = max(2, int(badge_r * 0.75))
        if icon == "select":
            pygame.draw.line(surface, white, (bx - badge_r*0.5, by), (bx + badge_r*0.5, by), bw)
            pygame.draw.line(surface, white, (bx, by - badge_r*0.5), (bx, by + badge_r*0.5), bw)
        else:
            pygame.draw.line(surface, white, (bx - badge_r*0.5, by), (bx + badge_r*0.5, by), bw)
        return

    if icon == "stop":
        img = _img_fit("game_stop.png", int(r * 2.2), int(r * 2.2))
        if img is not None:
            surface.blit(img, img.get_rect(center=center)); return

    if icon == "close":
        img = _img_fit("close_button.png", int(r * 2.2), int(r * 2.2))
        if img is not None:
            surface.blit(img, img.get_rect(center=center)); return

    # Plain accent-colored circle + vector glyph (trash / warning / check /
    # logout / info -- and the fallback if a real asset above is missing).
    pygame.draw.circle(surface, accent, center, r)
    if icon == "trash":
        bw_, bh_ = int(r * 0.9), int(r * 0.78)
        body = pygame.Rect(0, 0, bw_, bh_); body.midtop = (cx, cy - int(r*0.18))
        pygame.draw.rect(surface, white, body, border_radius=max(2, int(r*0.12)))
        lid = pygame.Rect(0, 0, int(bw_*1.25), max(2, int(r*0.16)))
        lid.midtop = (cx, body.top - max(2, int(r*0.08)))
        pygame.draw.rect(surface, white, lid, border_radius=max(2, int(r*0.06)))
        pygame.draw.rect(surface, accent, (cx - int(bw_*0.16), lid.top - int(r*0.14),
                                           int(bw_*0.32), int(r*0.16)), border_radius=2)
        lw = max(1, int(r * 0.07))
        for fx in (cx - bw_*0.2, cx, cx + bw_*0.2):
            pygame.draw.line(surface, accent, (fx, body.top + r*0.14), (fx, body.bottom - r*0.1), lw)
    elif icon == "warning":
        w_ = max(2, int(r * 0.16))
        pygame.draw.line(surface, white, (cx, cy - r*0.42), (cx, cy + r*0.08), w_)
        pygame.draw.circle(surface, white, (cx, int(cy + r*0.38)), max(2, int(w_*0.7)))
    elif icon == "check":
        w_ = max(2, int(r * 0.18))
        pts = [(cx - r*0.42, cy + r*0.02), (cx - r*0.1, cy + r*0.34), (cx + r*0.46, cy - r*0.34)]
        pygame.draw.lines(surface, white, False, pts, w_)
    elif icon == "logout":
        w_ = max(2, int(r * 0.14))
        door = pygame.Rect(0, 0, int(r*0.5), int(r*0.9)); door.midleft = (cx - r*0.45, cy)
        pygame.draw.rect(surface, white, door, w_, border_radius=3)
        pygame.draw.line(surface, white, (cx - r*0.15, cy), (cx + r*0.55, cy), w_)
        pygame.draw.line(surface, white, (cx + r*0.3, cy - r*0.3), (cx + r*0.58, cy), w_)
        pygame.draw.line(surface, white, (cx + r*0.3, cy + r*0.3), (cx + r*0.58, cy), w_)
    else:   # "info" / default
        pygame.draw.circle(surface, white, (cx, int(cy - r*0.34)), max(2, int(r*0.09)))
        pygame.draw.line(surface, white, (cx, cy - r*0.1), (cx, cy + r*0.4), max(2, int(r*0.16)))


def draw_confirm_dialog(surface, W, H, *, tt, sc, fonts, icon, accent,
                         title, body=None, confirm_label="Confirm",
                         cancel_label="Cancel", single_button=False,
                         confirm_hov=False, cancel_hov=False,
                         countdown=None, max_w_frac=0.82, show_icon=True,
                         fixed_size=None, pad_px=24, icon_r_px=32):
    """Draws the full dialog (dim overlay + card + icon + title/body +
    button(s)) and returns (confirm_rect, cancel_rect) for hit-testing --
    cancel_rect is a dead 1x1 rect in single_button mode, where
    confirm_label doubles as the one button's own label (e.g. "Okay").

    `countdown`, when not None, is the remaining seconds (float) of a
    mandatory safety delay before the confirm action may fire: the button
    renders disabled (grey, hover ignored) with "<label> (Ns)" while
    countdown > 0, then switches to its normal enabled appearance showing
    just `confirm_label`. The caller is responsible for actually refusing
    the click while countdown > 0 -- this function only draws the state.

    `show_icon=False` skips the icon circle and reclaims its vertical room
    for an unusually content-dense popup (e.g. a confirmation with several
    labeled detail lines below its body) that would otherwise not fit
    800x480 -- the top accent wave still shows, just shorter.

    `fixed_size=(mw, mh)`, when given, uses that exact outer card size
    instead of computing one from content -- for a family of popups that
    must all share identical outer dimensions regardless of how much each
    one has to show. The caller is responsible for making its title/body/
    buttons actually fit within it (font choice, truncation, wrapping).

    `pad_px`/`icon_r_px` default to this function's original padding/icon
    size; pass smaller values (matching draw_dialog_chrome's own for the
    same family of popups) to reclaim header height -- every caller in
    that family must pass the SAME values so their header heights match."""
    from constants import is_dark_mode
    dark = is_dark_mode()

    if dark:
        card_bg, card_bdr = (28, 36, 52), (58, 72, 96)
        title_col, body_col = (232, 238, 248), (168, 182, 204)
        wave_alpha, shadow_alpha = 55, 150
    else:
        card_bg, card_bdr = (250, 252, 255), (205, 218, 236)
        title_col, body_col = (34, 48, 72), (100, 116, 142)
        wave_alpha, shadow_alpha = 40, 70
    cancel_bg  = (92, 106, 130) if dark else (175, 190, 210)
    cancel_hi  = (112, 128, 154) if dark else (150, 166, 188)

    # ── dim overlay -- blocks + visually subdues the screen behind it ──
    ov = pygame.Surface((W, H), pygame.SRCALPHA)
    ov.fill((8, 12, 20, 165))
    surface.blit(ov, (0, 0))

    pad       = sc(pad_px)
    icon_r    = sc(icon_r_px)
    btn_h     = tt(50)
    btn_gap   = sc(16)
    f_title, f_body, f_btn = fonts["title"], fonts["body"], fonts["btn"]

    if fixed_size is not None:
        mw, mh = fixed_size
        max_content_w = mw - pad * 2
    else:
        max_w = int(W * max_w_frac)
        max_content_w = max_w - pad * 2

    title_font = f_title
    title_lines = _wrap_text(title, title_font, max_content_w)
    if len(title_lines) > 2 and fonts.get("title_small") is not None:
        title_font = fonts["title_small"]
        title_lines = _wrap_text(title, title_font, max_content_w)
    title_line_h = title_font.get_linesize()

    body_lines, body_line_h = [], 0
    if body:
        # Split on explicit newlines FIRST, then wrap each segment by width
        # -- a caller-inserted break (e.g. "...successfully.\nID: 123") is a
        # deliberate line break, not just more prose to reflow together.
        for raw in body.split("\n"):
            body_lines.extend(_wrap_text(raw, f_body, max_content_w))
        body_line_h = f_body.get_linesize()

    cd_active = countdown is not None and countdown > 0
    cd_i = max(1, int(math.ceil(countdown))) if cd_active else 0
    confirm_label_disp = f"{confirm_label} ({cd_i}s)" if cd_active else confirm_label
    # Size the button from the widest it will ever need to be ("(5s)" is the
    # longest the countdown suffix ever gets) so it never resizes/jitters as
    # the countdown ticks down from 5 to 1.
    confirm_label_wide = f"{confirm_label} (5s)" if countdown is not None else confirm_label

    confirm_w_needed = f_btn.size(confirm_label_wide)[0]
    cancel_w_needed  = f_btn.size(cancel_label)[0]
    if single_button:
        bw = max(confirm_w_needed + sc(50), sc(160))
    else:
        bw = max(max(confirm_w_needed, cancel_w_needed) + sc(40), sc(130))
    btn_row_w = bw if single_button else (bw * 2 + btn_gap)

    icon_block_h = (icon_r * 2 + sc(14)) if show_icon else sc(16)
    title_block_h = len(title_lines) * title_line_h
    body_block_h = (sc(10) + len(body_lines) * body_line_h) if body_lines else 0

    if fixed_size is not None:
        mw, mh = fixed_size
        mw = max(mw, btn_row_w + pad * 2)   # never let the button row itself overflow
    else:
        content_w = max([btn_row_w] +
                        [title_font.size(ln)[0] for ln in title_lines] +
                        [f_body.size(ln)[0] for ln in body_lines])
        mw = min(max(content_w + pad * 2, sc(340)), max_w)
        mh = (pad + icon_block_h + title_block_h + body_block_h + sc(22) + btn_h + pad)
        mh = min(mh, int(H * 0.92))

    mx, my = (W - mw) // 2, (H - mh) // 2
    mr = pygame.Rect(mx, my, mw, mh)

    # ── shadow (cheap: one soft offset rounded-rect, not a blur) ──
    shadow = pygame.Surface((mw + sc(16), mh + sc(16)), pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, shadow_alpha), (0, 0, mw + sc(16), mh + sc(16)),
                     border_radius=20)
    surface.blit(shadow, (mx - sc(8), my - sc(4) + sc(6)))

    # ── card + top wave accent ──
    ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
    pygame.draw.rect(ms, (*card_bg, 255), (0, 0, mw, mh), border_radius=18)
    wave_h = min(mh, icon_block_h + sc(18))
    wave = pygame.Surface((mw, wave_h), pygame.SRCALPHA)
    pygame.draw.rect(wave, (*accent, wave_alpha), (0, 0, mw, wave_h),
                     border_top_left_radius=18, border_top_right_radius=18)
    ms.blit(wave, (0, 0))
    surface.blit(ms, mr.topleft)
    pygame.draw.rect(surface, card_bdr, mr, 2, border_radius=18)

    # ── icon ──
    if show_icon:
        icon_cy = my + pad + icon_r
        _draw_dialog_icon(surface, (mr.centerx, icon_cy), icon_r, icon, accent, dark)
        ty = icon_cy + icon_r + sc(14)
    else:
        ty = my + pad + icon_block_h

    # ── title ──
    for ln in title_lines:
        s = title_font.render(ln, True, title_col)
        surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
        ty += title_line_h

    # ── body ──
    if body_lines:
        ty += sc(10)
        for ln in body_lines:
            s = f_body.render(ln, True, body_col)
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += body_line_h

    def _draw_btn_content(rect, label):
        # Text-only, centered -- these dialog buttons used to prefix a
        # check/X glyph from a "segoeuisymbol" SysFont, which is a
        # Windows-only font name; on the Raspberry Pi it silently falls
        # back to a font with no such glyph, so the icon simply never
        # rendered there (confirmed from the production LCD screenshots).
        # Dropping the glyph removes that platform dependency entirely
        # instead of hunting for a symbol font that's guaranteed present
        # on the Pi.
        if not label:
            return
        ls = f_btn.render(label, True, (255, 255, 255))
        surface.blit(ls, ls.get_rect(center=rect.center))

    # ── button(s) ──
    by = mr.bottom - pad - btn_h
    if single_button:
        confirm_r = pygame.Rect(mr.centerx - bw // 2, by, bw, btn_h)
        cancel_r  = pygame.Rect(0, 0, 1, 1)
    else:
        confirm_r = pygame.Rect(mr.centerx + btn_gap // 2, by, bw, btn_h)
        cancel_r  = pygame.Rect(mr.centerx - btn_gap // 2 - bw, by, bw, btn_h)
        c_col = cancel_hi if cancel_hov else cancel_bg
        pygame.draw.rect(surface, c_col, cancel_r, border_radius=12)
        _draw_btn_content(cancel_r, cancel_label)

    if cd_active:
        f_col = (90, 98, 112) if dark else (175, 183, 196)
    else:
        confirm_dim = tuple(max(0, c - 25) for c in accent)
        f_col = confirm_dim if confirm_hov else accent
    pygame.draw.rect(surface, f_col, confirm_r, border_radius=12)
    _draw_btn_content(confirm_r, confirm_label_disp)

    return confirm_r, cancel_r


def draw_dialog_chrome(surface, W, H, *, tt, sc, fonts, icon, accent, title,
                       body=None, extra_content_h=0, min_content_w=0,
                       max_w_frac=0.82, max_h_frac=0.92, fixed_size=None,
                       pad_px=24, icon_r_px=32):
    """The shared visual shell (dim overlay, drop shadow, rounded card with
    a tinted top accent, icon circle, title, optional body paragraph) that
    draw_confirm_dialog itself draws before adding its own 1-2 buttons --
    extracted here, as a pure ADDITION (draw_confirm_dialog's own code is
    untouched), for popups that need the exact same look but a different
    button layout than draw_confirm_dialog supports (e.g. three buttons, or
    an interactive form instead of buttons at all). `extra_content_h`
    reserves vertical room below the title/body for the caller's own
    content; the caller draws into that space itself. Returns
    (card_rect, content_y, theme) where theme = (card_bg, card_bdr,
    title_col, body_col, dark) for the caller's own additional styling.

    `fixed_size=(mw, mh)`, when given, uses that exact outer card size
    instead of computing one from content -- see draw_confirm_dialog's own
    fixed_size for the same idea; the caller must make its content fit.

    `pad_px`/`icon_r_px` default to this function's original padding/icon
    size; pass smaller values (matching draw_confirm_dialog's own
    pad_px/icon_r_px for the same family of popups) to reclaim header
    height for a content-dense, fixed-size popup -- every caller in that
    family must pass the SAME values so their header heights stay equal."""
    from constants import is_dark_mode
    dark = is_dark_mode()

    if dark:
        card_bg, card_bdr = (28, 36, 52), (58, 72, 96)
        title_col, body_col = (232, 238, 248), (168, 182, 204)
        wave_alpha, shadow_alpha = 55, 150
    else:
        card_bg, card_bdr = (250, 252, 255), (205, 218, 236)
        title_col, body_col = (34, 48, 72), (100, 116, 142)
        wave_alpha, shadow_alpha = 40, 70

    ov = pygame.Surface((W, H), pygame.SRCALPHA)
    ov.fill((8, 12, 20, 165))
    surface.blit(ov, (0, 0))

    pad    = sc(pad_px)
    icon_r = sc(icon_r_px)
    f_title, f_body = fonts["title"], fonts["body"]

    if fixed_size is not None:
        mw, mh = fixed_size
        max_content_w = mw - pad * 2
    else:
        max_w = int(W * max_w_frac)
        max_content_w = max_w - pad * 2

    title_font = f_title
    title_lines = _wrap_text(title, title_font, max_content_w)
    if len(title_lines) > 2 and fonts.get("title_small") is not None:
        title_font = fonts["title_small"]
        title_lines = _wrap_text(title, title_font, max_content_w)
    title_line_h = title_font.get_linesize()

    body_lines, body_line_h = [], 0
    if body:
        for raw in body.split("\n"):
            body_lines.extend(_wrap_text(raw, f_body, max_content_w))
        body_line_h = f_body.get_linesize()

    icon_block_h = icon_r * 2 + sc(14)
    title_block_h = len(title_lines) * title_line_h
    body_block_h = (sc(10) + len(body_lines) * body_line_h) if body_lines else 0

    if fixed_size is None:
        content_w = max([min_content_w] +
                        [title_font.size(ln)[0] for ln in title_lines] +
                        [f_body.size(ln)[0] for ln in body_lines])
        mw = min(max(content_w + pad * 2, sc(340)), max_w)
        mh = pad + icon_block_h + title_block_h + body_block_h + extra_content_h + pad
        mh = min(mh, int(H * max_h_frac))

    mx, my = (W - mw) // 2, (H - mh) // 2
    mr = pygame.Rect(mx, my, mw, mh)

    shadow = pygame.Surface((mw + sc(16), mh + sc(16)), pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, shadow_alpha), (0, 0, mw + sc(16), mh + sc(16)),
                     border_radius=20)
    surface.blit(shadow, (mx - sc(8), my - sc(4) + sc(6)))

    ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
    pygame.draw.rect(ms, (*card_bg, 255), (0, 0, mw, mh), border_radius=18)
    wave_h = min(mh, icon_block_h + sc(18))
    wave = pygame.Surface((mw, wave_h), pygame.SRCALPHA)
    pygame.draw.rect(wave, (*accent, wave_alpha), (0, 0, mw, wave_h),
                     border_top_left_radius=18, border_top_right_radius=18)
    ms.blit(wave, (0, 0))
    surface.blit(ms, mr.topleft)
    pygame.draw.rect(surface, card_bdr, mr, 2, border_radius=18)

    icon_cy = my + pad + icon_r
    _draw_dialog_icon(surface, (mr.centerx, icon_cy), icon_r, icon, accent, dark)

    ty = icon_cy + icon_r + sc(14)
    for ln in title_lines:
        s = title_font.render(ln, True, title_col)
        surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
        ty += title_line_h

    if body_lines:
        ty += sc(10)
        for ln in body_lines:
            s = f_body.render(ln, True, body_col)
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += body_line_h

    return mr, ty, (card_bg, card_bdr, title_col, body_col, dark)


# ─────────────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────────────

class TherapistDashboardScene:

    def __init__(self, screen, width, height, account=None):
        """
        Initialize the Therapist Dashboard Scene.

        Args:
            screen: pygame surface to draw on
            width: screen width in pixels
            height: screen height in pixels
            account: therapist account dict (optional, will load from DB if not provided)
        """
        # Store screen and display dimensions
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        # Initialize database connection for patient/therapist data
        self.db     = Database()

        # ── Account loading priority ──────────────────────────────────
        # Priority: 1) passed account param, 2) pending_account global, 3) last DB therapist, 4) default
        import builtins as _bi
        if account:
            self.account = account
        elif hasattr(_bi, 'pending_account') and _bi.pending_account:
            self.account = _bi.pending_account
            _bi.pending_account = None
        else:
            all_acc = self.db.get_all_therapists()
            self.account = all_acc[-1] if all_acc else {
                "id": 0, "full_name": "Therapist", "username": "user",
                "role": "Physical Therapist", "workplace": "RecovR Clinic",
                "icon_index": 1
            }

        # ── Touch / small-display mode ───────────────────────────────
        # The therapist dashboard also runs on a ~7-inch LCD touchscreen. On a
        # short display we scale UI up (larger fonts) and enforce minimum tap
        # target sizes, and the Patient List becomes scrollable. Desktop /
        # large-monitor layout is unchanged.
        H = height
        self._touch_ui = (H <= 820) or (os.environ.get("RECOVR_THERAPIST_TOUCH") == "1")
        # font scale factor: normal = H/1080; on the 7-inch panel we scale text
        # up relative to the screen so it reads from a distance and every tap
        # target clears ~48px.
        #   reference is H/512 -> 800x480 panel gives _fs = 0.9375 (27px body
        #   -> 25px). A plain H/1080 would give 0.44 here, i.e. 12px body text
        #   on a physically SMALLER screen. The 1.32 cap only bites above
        #   H=676, which no therapist panel reaches.
        _fs = min(H / 512.0, 1.32) if self._touch_ui else (H / 1080.0)
        self._fs = _fs
        # Narrow panel (the 800px-wide LCD): abbreviate labels that would
        # otherwise overrun a row. Checked wherever a row must fit several
        # controls side by side.
        self._narrow = width <= 900

        # ── Font dictionary (all fonts scaled by _fs) ──
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(name): return os.path.join(_fd, name)
        # Professional/clinical text system is Poppins throughout (uploaded
        # specifically to replace Lexend/FjallaOne in this role): SemiBold
        # for page titles, section headings and important values; Medium for
        # buttons, tabs, names and interface labels; Regular for body text
        # and secondary info. The small secondary Sora identity (Home tile
        # labels, greeting text, empty-state illustrations) and the symbol/
        # logo fonts are a deliberately different, narrow role untouched by
        # this -- see the font-consistency pass earlier in this file's
        # history for why those specific uses stay as they are.
        self.fnt = {
            "logo":        pygame.font.SysFont("arialblack",                 int((36 if self._touch_ui else 51)*_fs)),
            "nav":         pygame.font.Font(_F("Poppins-Medium.ttf"),        int(27*_fs)),
            "nav_sym":     pygame.font.SysFont("segoeuisymbol",              int(35*_fs)),
            "welcome":     pygame.font.Font(_F("Sora-Light.ttf"),            int(33*_fs)),
            "dash_title":  pygame.font.Font(_F("Poppins-SemiBold.ttf"),      int(60*_fs)),
            "panel_title": pygame.font.Font(_F("Poppins-SemiBold.ttf"),      int(36*_fs)),
            "body":        pygame.font.Font(_F("Poppins-Regular.ttf"),       int(27*_fs)),
            "body_b":      pygame.font.Font(_F("Poppins-SemiBold.ttf"),      int(27*_fs)),
            "small":       pygame.font.Font(_F("Poppins-Regular.ttf"),       int(25*_fs)),
            "small_i":     pygame.font.Font(_F("Sora-ExtraLight.ttf"),       int(25*_fs)),
            "label":       pygame.font.Font(_F("Poppins-Regular.ttf"),       int(25*_fs)),
            "input":       pygame.font.Font(_F("Poppins-Regular.ttf"),       int(25*_fs)),
            "btn":         pygame.font.Font(_F("Poppins-Medium.ttf"),        int(27*_fs)),
            "btn_lg":      pygame.font.Font(_F("Poppins-SemiBold.ttf"),      int(30*_fs)),
            "profile_nm":  pygame.font.Font(_F("Poppins-Medium.ttf"),        int(24*_fs)),
            "profile":     pygame.font.Font(_F("Poppins-Regular.ttf"),       int(22*_fs)),
            "card_lbl":    pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(25*_fs)),
            "card_sym":    pygame.font.SysFont("segoeuisymbol",              int(51*_fs)),
            "modal_head":  pygame.font.Font(_F("Poppins-SemiBold.ttf"),      int(42*_fs)),
            "modal_lbl":   pygame.font.Font(_F("Poppins-Medium.ttf"),        int(27*_fs)),
            "modal_inp":   pygame.font.Font(_F("Poppins-Regular.ttf"),       int(27*_fs)),
            "modal_err":   pygame.font.Font(_F("Poppins-Regular.ttf"),       int(23*_fs)),
            "empty_head":  pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(33*_fs)),
            "section":     pygame.font.Font(_F("Poppins-SemiBold.ttf"),      int(24*_fs)),
            "tag":         pygame.font.Font(_F("Poppins-Medium.ttf"),        int(22*_fs)),
            "eyebrow":     pygame.font.Font(_F("Poppins-Medium.ttf"),        int(19*_fs)),
            "time":        pygame.font.Font(_F("ZenDots-Regular.ttf"),       int(19*_fs)),
            "header_date": pygame.font.Font(_F("Poppins-Regular.ttf"),       int(16*_fs)),
            "breadcrumb":  pygame.font.Font(_F("Poppins-Regular.ttf"),       int(24*_fs)),
            "sym26":       pygame.font.SysFont("segoeuisymbol",              int(26*_fs)),
            "sym29":       pygame.font.SysFont("segoeuisymbol",              int(29*_fs)),
        }

        # Patient List scroll offset (touch: list scrolls instead of shrinking).
        self._pl_scroll     = 0
        self._pl_scroll_max  = 0
        self._pl_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._pl_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._pl_drag_y     = None

        # Session History (panel 1) scroll -- was a silent truncation before.
        self._sh_scroll     = 0
        self._sh_scroll_max = 0
        self._sh_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._sh_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._sh_drag_y     = None
        self._sh_row_rects  = []     # [(rect, session_record), ...] -- tap a row to open it
        # The full-page Session Details view, same pattern as Calibration
        # Record Details -- None = showing the list; set to a session dict
        # = showing that session's own page instead. A SEPARATE scroll/back
        # state from the list's own (_sh_scroll etc.) so leaving details
        # always restores the list's exact previous scroll position.
        self._sh_detail_record = None
        self._shd_scroll       = 0
        self._shd_scroll_max   = 0
        self._shd_up_rect      = pygame.Rect(0, 0, 1, 1)
        self._shd_down_rect    = pygame.Rect(0, 0, 1, 1)
        self._shd_drag_y       = None
        self._shd_back_rect    = pygame.Rect(0, 0, 1, 1)

        # Analytics / Metrics (panel 2) scroll -- an expandable tree now
        # (METRICS_TREE), not one fixed section per game.
        self._an_scroll     = 0
        self._an_scroll_max = 0
        self._an_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._an_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._an_drag_y     = None
        # Which tree nodes are expanded -- a set of path tuples, e.g.
        # ("Single Skill",), ("Single Skill","Grip Strength"),
        # ("Single Skill","Grip Strength","Basketball"),
        # ("Single Skill","Grip Strength","Basketball","target"). Empty by
        # default (collapsed view) per spec. A MODE path's membership also
        # controls whether its stats+chart block is shown.
        self._metrics_expanded  = set()
        self._metrics_row_rects = []   # [(rect, path), ...] -- tap any row to toggle it

        # Calibration Records (panel 3) scroll -- was truncated via max_rows.
        self._cr_scroll     = 0
        self._cr_scroll_max = 0
        self._cr_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._cr_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._cr_drag_y     = None
        self._cr_row_rects  = []     # [(rect, record), ...] -- tap a row to open it
        # The full-page Calibration Record Details view. None = showing the
        # list; set to a record dict = showing that record's own page
        # instead (see _draw_calibration_detail). A SEPARATE scroll/back-nav
        # state from the list's own (_cr_scroll etc.) so leaving the details
        # page always restores the list's exact previous scroll position.
        self._cr_detail_record = None
        self._crd_scroll       = 0
        self._crd_scroll_max   = 0
        self._crd_up_rect      = pygame.Rect(0, 0, 1, 1)
        self._crd_down_rect    = pygame.Rect(0, 0, 1, 1)
        self._crd_drag_y       = None
        self._crd_back_rect    = pygame.Rect(0, 0, 1, 1)

        # Shared Confirm/Cancel hit-rects for the 5 "standard" 2-button
        # modals (select/deselect/delete-patient/delete-account/logout) --
        # see _confirm_rects(). Content-sized by draw_confirm_dialog each
        # frame, not a fixed box.
        self._modal_confirm_rect = pygame.Rect(0, 0, 1, 1)
        self._modal_cancel_rect  = pygame.Rect(0, 0, 1, 1)

        # pd_bg.png background image; falls back to the old procedural
        # gradient if the asset is ever missing.
        self.background_surface = _img_cover("pd_bg.png", width, height) \
            or self._gradient(width, height)
        # Sidebar width: 20% desktop; narrower on the 7-inch panel (the nav list
        # was removed, so it only carries the profile + logout now).
        self.sidebar_w = int(width * (0.23 if self._touch_ui else 0.20))

        # ── Panel state tracking ──
        # active_panel: -1 = home, 0-6 = specific panels (see NAV_IDX mapping at top)
        self.active_panel = -1
        # Lobby music vs a launched game's own BGM -- see the
        # want_lobby/self._lobby_want toggle in update(). None so the very
        # first update() frame always fires the comparison (dashboard entry
        # after login starts lobby music).
        self._lobby_want = None
        # nav_hovered: which sidebar nav item is currently hovered (-1 = none)
        self.nav_hovered  = -1
        # nav_rects: list of pygame.Rect objects for sidebar navigation buttons
        self.nav_rects    = []
        # card_hovered: list of 4 booleans tracking hover state of home cards
        self.card_hovered = [False] * 4

        # ── Header/profile area interaction ──
        self.edit_link_hovered = False         # Is "Edit Profile" link hovered?
        self.logout_hovered    = False         # Is logout button hovered?
        self._edit_link_rect   = pygame.Rect(0, 0, 1, 1)  # Clickable rect for edit link
        self._back_btn_rect    = pygame.Rect(0, 0, 1, 1)  # Clickable rect for back button
        self._crumb_rects      = []                       # [(Rect, target)] clickable breadcrumbs

        # ── Modal state ──
        self.modal           = None            # Current modal: "edit_profile", "logout_confirm", "delete_confirm", "register_success", "transfer_success", None
        self.confirm_yes_hov = False           # Is "Yes" button hovered in confirmation modal?
        self.confirm_no_hov  = False           # Is "No" button hovered in confirmation modal?
        # Shared 5-second safety-delay timer for the 3 destructive-action
        # confirmations that require it (Delete Therapist Account, Delete
        # Patient Account, Transfer Patient) -- never more than one of those
        # confirmations can be open at once, so one timer covers all three.
        # Each entry point resets it to 5.0 when it opens its own dialog.
        self._danger_countdown = 0.0
        self._rp_success_msg = ""              # Text shown in register success popup
        self._rp_ok_rect     = pygame.Rect(0, 0, 1, 1)
        self._rp_ok_hov      = False

        # ── Patient selection state ──
        self.selected_patient = None           # Patient chosen (via SELECT + confirm) for this session
        self.patients         = []             # List of patients belonging to/shared with this therapist

        # ── Patient page (panel 8) state ──
        # preview_patient is the patient whose page is open -- opening it must NOT
        # select them. Its tabs reuse the per-patient Analytics / Calibration /
        # Session History panels via _view_patient(); Info shows every DB field.
        self.preview_patient          = None
        self._pv_tab                  = "info"     # info | analytics | calibration | history
        self._pv_tab_rects            = {}
        self._pv_select_rect          = pygame.Rect(0, 0, 1, 1)
        self._pv_edit_rect            = pygame.Rect(0, 0, 1, 1)   # legacy, now unused
        self._pv_sec_edit_rects       = {}     # {section_key: Rect} per-group Edit buttons
        self._pv_info_scroll          = 0
        self._pv_info_scroll_max      = 0
        self._pv_info_up_rect         = pygame.Rect(0, 0, 1, 1)
        self._pv_info_down_rect       = pygame.Rect(0, 0, 1, 1)
        self._rp_scroll               = 0          # Register Patient (touch) form scroll offset
        self._rp_scroll_max           = 0
        self._rp_drag_y               = None
        self._rp_up_rect              = pygame.Rect(0, 0, 1, 1)
        self._rp_down_rect            = pygame.Rect(0, 0, 1, 1)
        self._pending_select_patient  = None       # patient awaiting the SELECT confirm dialog
        self._pending_deselect_patient = None      # patient awaiting the DESELECT confirm dialog

        # ── Patient search state ──
        self._pt_search_text   = ""            # Current search text in patient list
        self._pt_search_active = False         # Whether search field has keyboard focus
        self._pt_search_rect   = pygame.Rect(0, 0, 1, 1)

        # Initialize state for Register Patient and Game Config panels
        self._init_register_state()
        self._init_game_config_state()

        # ── Calibration bypass for dev testing ────────────────────────
        # Allows therapists to bypass sensor calibration during development
        self.calibration_bypassed = False
        self._bypass_btn_rect     = pygame.Rect(0, 0, 1, 1)
        self._bypass_hov          = False

        # ── Real calibration state ─────────────────────────────────────
        self.calibration_done     = False       # True after CalibrationWindow accepted
        self.calibration_result   = None        # dict from CalibrationWindow
        self._cal_win             = None        # active CalibrationWindow instance (or None)
        self._calibrate_btn_rect  = pygame.Rect(0, 0, 1, 1)
        self._calibrate_hov       = False
        self._cal_progress_push_t = 0.0         # throttle timer for the patient-screen sync push
        self._cal_progress_last   = None        # last payload actually sent (skip duplicate posts)

        # ── Session-scoped calibration reuse cache ───────────────────────
        # sensor_type -> {"sensor_name","trials","average"} (the exact shape
        # CalibrationWindow.sensor_results already uses) for every sensor
        # successfully calibrated for the CURRENTLY SELECTED patient during
        # this continuous therapy session -- lets a later game that needs
        # the same sensor offer "Use Previous Calibration" instead of
        # forcing recalibration. Cleared whenever the selected patient
        # actually changes (see _set_selected_patient()); a fresh scene
        # instance (new login, app restart) starts with an empty cache for
        # free, since nothing persists it beyond this attribute.
        self._calibrated_sensors = {}
        # Pending launch info while the "Use Previous Calibration?" chooser
        # (self.modal == "reuse_calibration_choice") is up -- which game and
        # which of its required sensors are reusable right now.
        self._reuse_game_name       = None
        self._reuse_game_type       = None
        self._reuse_cal_types       = None     # str | list[str], as passed to CalibrationWindow
        self._reuse_available       = []       # sensor types with a valid cache hit, in SENSOR_ORDER
        self._reuse_needed          = []       # sensor types that still need live calibration
        self._reuse_use_rect        = pygame.Rect(0, 0, 1, 1)
        self._reuse_recal_rect      = pygame.Rect(0, 0, 1, 1)
        self._reuse_use_hov         = False
        self._reuse_recal_hov       = False

        # ── Dev/testing-only bypass (OFF by default; toggled by hand) ───
        self._test_mode_bypass   = False        # toggled on Start Session
        self._test_mode_btn_rect = pygame.Rect(0, 0, 1, 1)
        self._test_mode_hov      = False
        self._sm_test_mode       = False        # True while a bypassed session is live (panel 7 badge)

        # ── Calibration mismatch modal ─────────────────────────────────
        self._mismatch_cal_rect    = pygame.Rect(0, 0, 1, 1)
        self._mismatch_cancel_rect = pygame.Rect(0, 0, 1, 1)
        self._mismatch_cal_hov     = False
        self._mismatch_cancel_hov  = False

        # ── Session Details (panel 5) ───────────────────────────────────
        self._ss_scroll     = 0
        self._ss_scroll_max = 0
        self._ss_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._ss_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._ss_drag_y     = None

        # ── Interactive UI element rects ──
        # These store clickable areas for various buttons/interactive elements
        self._rp_btn_rect        = pygame.Rect(0, 0, 1, 1)  # Register patient submit button
        self._gc_next_rect       = pygame.Rect(0, 0, 1, 1)  # "Proceed to Start Session" button
        self._start_btn_rect     = pygame.Rect(0, 0, 1, 1)  # "Start Session" button
        self._register_link_rect = pygame.Rect(0, 0, 1, 1)  # Register patient link in patient list
        self._game_tiles         = []                        # List of (rect, game_tuple) for clickable game cards
        self._preset_btn_rect    = pygame.Rect(0, 0, 1, 1)  # Smart Preset button rect
        self._param_rects        = {}                        # Dict of parameter name -> rect for game config dropdowns

        # ── Hover state tracking for buttons ──
        self.rp_btn_hov        = False         # Is register patient button hovered?
        self.gc_next_hov       = False         # Is game config "next" button hovered?
        self.start_hov         = False         # Is start session button hovered?
        self.register_link_hov = False         # Is register patient link hovered?
        self.preset_hov        = False         # Is smart preset button hovered?

        # ── Edit patient modal state ──────────────────────────────────
        self._ep_modal_open   = False
        self._ep_patient      = None
        self._ep              = {}
        self._ep_active_key   = None
        self._ep_error        = ""
        self._ep_success      = ""
        self._ep_drop_open    = {}
        self._ep_drop_rects   = {}
        self._ep_confirm_del  = False
        self._ep_save_rect    = pygame.Rect(0, 0, 1, 1)
        self._ep_cancel_rect  = pygame.Rect(0, 0, 1, 1)
        self._ep_delete_rect  = pygame.Rect(0, 0, 1, 1)
        self._ep_save_hov     = False
        self._ep_cancel_hov   = False
        self._ep_delete_hov   = False
        self._ep_section      = None   # which Info group the edit modal is scoped to
        self._db_blocked_ok_rect = pygame.Rect(0, 0, 1, 1)   # "delete_blocked" dismiss
        self._transfer_ok_rect   = pygame.Rect(0, 0, 1, 1)   # "transfer_success" dismiss
        self._transfer_ok_hov    = False
        self._transfer_success_msg = ""

        # ── Share patient modal state ─────────────────────────────────
        # Allows therapists to share a patient with other therapists
        self.share_modal_patient  = None       # Patient dict being shared (None if modal closed)
        self._share_modal_open    = False      # Is share modal currently visible?
        self._share_input         = ""         # Username text being typed in search field
        self._share_error         = ""         # Error message to display
        self._share_success       = ""         # Success message to display
        self._share_results       = []         # List of therapist dicts matching search
        self._share_field_rect       = pygame.Rect(0, 0, 1, 1)
        self._share_search_rect      = pygame.Rect(0, 0, 1, 1)
        self._share_confirm_rect     = pygame.Rect(0, 0, 1, 1)
        self._share_close_rect       = pygame.Rect(0, 0, 1, 1)
        self._share_search_hov       = False
        self._share_confirm_hov      = False
        self._share_close_hov        = False
        self._share_suggestions      = []          # live-search results (list of therapist dicts)
        self._share_sugg_rects       = []          # list of (rect, therapist) for click handling
        self._share_shared_scroll     = 0          # "Currently shared with:" list scroll offset (px)
        self._share_shared_scroll_max = 0
        self._share_shared_viewport   = pygame.Rect(0, 0, 1, 1)
        self._share_shared_drag_y     = None       # finger-drag scroll tracking (touch)
        self._share_confirm_therapist = None       # therapist chosen from suggestions, pending confirm/choice
        # Stage machine for the modal: "pick" (typing/suggestions) ->
        # "choice" (SHARE or TRANSFER?) -> "confirm" (final Yes/Cancel, worded
        # for whichever action was chosen). Ownership does NOT change on Share;
        # it DOES change on Transfer -- see _do_share_or_transfer().
        self._share_stage            = "pick"
        self._share_pending_action   = None        # "share" | "transfer", set entering "confirm"
        self._share_choice_share_rect    = pygame.Rect(0, 0, 1, 1)
        self._share_choice_transfer_rect = pygame.Rect(0, 0, 1, 1)
        self._share_choice_share_hov     = False
        self._share_choice_transfer_hov  = False
        self._share_yes_rect         = pygame.Rect(0, 0, 1, 1)
        self._share_no_rect          = pygame.Rect(0, 0, 1, 1)
        self._share_yes_hov          = False
        self._share_no_hov           = False
        self._unshare_rects          = []

        # ── Edit profile modal state ──
        # Dedicated icon-picker popup (opened from the big preview / "Change
        # Icon" prompt inside Edit Profile) -- large, scrollable grid of all
        # 10 icons instead of the old cramped always-visible rail.
        self.edit_icon_picker_open = False
        self._eip_scroll     = 0
        self._eip_scroll_max = 0
        self._eip_drag_y     = None
        self._eip_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._eip_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._eip_done_rect  = pygame.Rect(0, 0, 1, 1)
        self._eip_circles    = []       # [(cx, cy, idx)] -- recomputed each draw (scroll-dependent)
        self._eip_r          = 0        # current icon radius in the popup (recomputed each draw)
        self.edit_change_icon_rect = pygame.Rect(0, 0, 1, 1)
        self._init_edit_fields()

        # ── Build layout rectangles ──
        self._build_nav_rects()                # Calculate positions for sidebar nav items
        self._build_card_rects()               # Calculate positions for 4 home cards

        # ── Page transition animation ──
        self.alpha        = 0                  # Current alpha for fade-in effect (0-255)
        self.fade_surface = pygame.Surface((width, height))  # White surface for fade transition
        self.fade_surface.fill((255, 255, 255))
        self.action_triggered = False          # Flag to trigger next scene transition

        # ── Dual-monitor "Session in Progress" (panel 7) state ──
        self._sm_state    = {}                 # latest broker snapshot
        self._sm_result   = None               # captured result on COMPLETE
        self._sm_btn_rects = {}                # {key: (Rect, enabled)} for the controls
        self._sm_started_ms = 0                # pygame ticks when "Start Session" was pressed
        self._sm_start_lock_ms = 5000          # START held for this long -> BLE handoff window
        self._ble_want    = None               # last enable/disable pushed to the BLE receiver
        self._sm_hover    = None
        self._sm_volume   = None               # music volume (lazy-init from broker state)
        self._sm_stopped_notice = False        # "Game Stopped" screen shown on panel 7
        self._sm_notice_continue_rect = pygame.Rect(0, 0, 1, 1)
        self._sm_notice_back_rect     = pygame.Rect(0, 0, 1, 1)
        self._sm_back_warning = False          # Back clicked while a game is RUNNING/PAUSED
        self._sm_warning_okay_rect = pygame.Rect(0, 0, 1, 1)
        # Light/dark theme -- one shared state (constants.get_theme()). Toggled
        # from the sidebar control; synchronised to the patient monitor.
        try:
            from constants import is_dark_mode as _is_dark
            self._applied_theme_dark = bool(_is_dark())
        except Exception:
            self._applied_theme_dark = True
        self._theme_btn_rect = pygame.Rect(0, 0, 1, 1)
        # Close (X) button -- main.py reads this each frame instead of a
        # fixed screen-corner rect, so it can sit beside the Light/Dark
        # toggle in the header row. Falls back to its own fixed corner rect
        # on scenes that never populate this (login, welcome, games).
        self._close_btn_rect = pygame.Rect(0, 0, 1, 1)
        self._ctrl_btn_rect  = pygame.Rect(0, 0, 1, 1)   # ESP32 status block (tap = rescan)
        self._active_patient_rect = pygame.Rect(0, 0, 1, 1)  # whole Active Patient box (tap -> Patient Info)
        self._ctrl_hov       = False
        self._theme_hov      = False
        if _DUAL_MONITOR:
            therapist_link.start()
            therapist_link.set_present(True)     # a therapist is logged in
            therapist_link.set_dark_mode(self._applied_theme_dark)   # start in sync

        # Restore state from a returning game session if set
        _panel   = getattr(_bi, 'pending_panel',   None)
        _patient = getattr(_bi, 'pending_patient', None)
        if _panel is not None:
            _bi.pending_panel = None
            if _patient is not None:
                self.selected_patient = _patient
                _bi.pending_patient = None
            self._open_panel(_panel)
        else:
            self._open_panel(0)

        if _DUAL_MONITOR:
            # Push the current selection to shared state so the patient monitor
            # shows its Dashboard only when a patient is actually selected
            # (fresh login -> none -> patient stays on the Waiting Screen).
            self._push_selected_patient()

    # ──────────────────────────────────────────────────────────────────
    #  STATE INITS
    # ──────────────────────────────────────────────────────────────────

    def _init_register_state(self):
        """
        Initialize state dict for Register Patient panel.
        Tracks patient information form data and UI state.
        """
        # Initialize all patient fields as empty strings
        self.rp = {k: "" for k in [
            "full_name",        # Patient's full name
            "age",              # Patient's age (numeric)
            "sex",              # Patient's sex (Male/Female) -- required
            "dominant_hand",    # Dominant hand (Left/Right)
            "affected_hand",    # Hand affected by stroke (Left/Right)
            "stroke_type",      # Type of stroke (Ischemic/Hemorrhagic/Unknown)
            "date_of_stroke",   # Date stroke occurred
            "months_stroke",    # Months since stroke
            "notes_stiffness",  # Notes about stiffness
            "notes_pain",       # Notes about pain
            "notes_therapist",  # General therapist notes
        ]}
        # Add UI state flags to the dict
        self.rp.update({
            "active_key": None,     # Currently focused text input field name
            "error": "",            # Error message to display
            "success": "",          # Success message to display
            "sex_open": False,      # Is sex dropdown menu open?
            "dominant_open": False, # Is dominant hand dropdown open?
            "affected_open": False, # Is affected hand dropdown open?
            "stroke_open": False,   # Is stroke type dropdown open?
            "invalid_keys": set(), # Keys that failed validation on the last submit attempt
        })
        # Dict to store the click-sensitive rectangles for all dropdown buttons
        self._rp_drop_rects = {}
        # Set by _rp_submit() to the first invalid field's key; the touch
        # form's draw pass consumes it once to scroll that field into view.
        self._rp_focus_key = None

    def _init_game_config_state(self):
        """
        Initialize state dict for Game Configuration panel.
        Tracks selected game and session parameters.
        """
        self.gc = {
            "selected_game": None,          # Tuple of (game_name, game_type) or None if not selected
            "difficulty": "Medium",         # Difficulty level (Easy/Medium/Hard/Custom)
            "session_mode": "target",       # "target" (set goal) or "timed" (set duration)
            "target_reps": None,            # Target Mode: None = use the game's own difficulty preset
            "duration_sec": None,           # Timed Mode: None = use TIMED_DURATION_DEFAULT_SEC (7 min)
            "speed": "Normal",              # Game speed (Slow/Normal/Fast)
            "sensitivity": "Medium",        # Input sensitivity (Low/Medium/High)
            "resistance": "Medium Ball",    # Ball resistance for games (Soft/Medium/Hard)
            "preset_applied": False,        # Has smart preset been applied?
        }
        # Track which parameter dropdown is currently open (None if all closed)
        # Format: (param_name, options_list) or None
        self._gc_open_param = None
        self._gc_skill_modal_open = False   # Is game-picker modal open?
        self._gc_skill_modal_type = None    # Skill type whose games are being shown
        self._gc_skill_modal_rects = []     # List of (rect, game_name) for click handling
        self._gc_skill_modal_close = pygame.Rect(0, 0, 1, 1)
        self._gc_active_tab = "single"      # "single" | "integrated" -- which tile row shows
        self._gc_tab_rects  = {}            # {"single"/"integrated": Rect} for click handling

        # Step-by-step Game Configuration workflow (800x480-friendly): the
        # single panel 4 now has 3 internal steps instead of one screen --
        # "game" (category + game picker, unchanged), "mode" (Target/Timed),
        # "settings" (difficulty + target reps or duration). Calibration and
        # the Session Readiness Checklist remain their own panels (5),
        # unchanged, reached after "settings".
        self._gc_step = "game"              # "game" | "mode" | "settings"
        self._gc_mode_rects = {}            # {"target"/"timed": Rect}
        self._gc_diff_rects = {}            # {"Easy"/"Medium"/"Hard": Rect}
        self._gc_val_minus_rect = pygame.Rect(0, 0, 1, 1)
        self._gc_val_plus_rect  = pygame.Rect(0, 0, 1, 1)
        self._gc_back_rect      = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  LAYOUT
    # ──────────────────────────────────────────────────────────────────

    def _build_nav_rects(self):
        """
        Calculate clickable rectangles for sidebar navigation items.
        Called once during __init__ to set up static nav button positions.
        """
        # Position nav items starting at 40% down the sidebar
        nav_top = int(self.HEIGHT * 0.40)
        # Each nav button height (scales with screen height)
        nav_h   = int(60 * (self.HEIGHT / 1080))
        # Vertical gap between nav buttons
        gap     = int(8  * (self.HEIGHT / 1080))
        # Build list of rectangles: one for each sidebar nav item
        # x=0 (left edge), y=nav_top + row*spacing, width=full sidebar width, height=nav_h
        self.nav_rects = [
            pygame.Rect(0, nav_top + i*(nav_h+gap), self.sidebar_w, nav_h)
            for i in range(len(SIDEBAR_NAV))
        ]

    def _build_card_rects(self):
        """
        Calculate positions for 4 home screen cards in 2x2 grid.
        Called once during __init__ to set up static card positions.
        """
        # Left margin (sidebar width + padding)
        mx     = self.sidebar_w + int(24*(self.WIDTH/1920))
        # Top margin (below logo/header area)
        my     = int(self.HEIGHT * 0.22)
        # Available width for cards (screen - margins)
        mw     = self.WIDTH - mx - int(24*(self.WIDTH/1920))
        # Available height for cards (screen - margins)
        mh     = self.HEIGHT - my - int(20*(self.HEIGHT/1080))
        # Horizontal gap between card columns
        gap    = int(20*(self.WIDTH/1920))
        # Calculate individual card width (half available width minus gap)
        card_w = (mw - gap) // 2
        # Calculate individual card height (half available height minus gap)
        card_h = (mh - gap) // 2
        # Build 2x2 grid of rectangles:
        # [0] Top-left    [1] Top-right
        # [2] Bottom-left [3] Bottom-right
        self.card_rects = [
            pygame.Rect(mx,            my,            card_w, card_h),  # Top-left
            pygame.Rect(mx+card_w+gap, my,            card_w, card_h),  # Top-right
            pygame.Rect(mx,            my+card_h+gap, card_w, card_h),  # Bottom-left
            pygame.Rect(mx+card_w+gap, my+card_h+gap, card_w, card_h),  # Bottom-right
        ]

    def _panel_area(self):
        """
        Get the main content area rectangle for panels (excluding sidebar and header).
        Returns a pygame.Rect defining the clickable/drawable panel area.
        """
        # Left edge: sidebar + padding
        mx = self.sidebar_w + int(24*(self.WIDTH/1920))
        # Top edge: below the header band (breadcrumb + Back live here).
        # On touch, the breadcrumb floats ABOVE this by (hdr_h + gap), so it
        # must clear the top-right clock/theme bar too, not just this rect.
        if self._touch_ui:
            bar_bottom = self._bar_top() + self._bar_height()
            hdr_h = max(int(50*(self.HEIGHT/1080)), self._tt(46))
            my = bar_bottom + self._sc(8) + hdr_h + int(10*self.HEIGHT/1080)
        else:
            my = int(self.HEIGHT * 0.15)
        # Width: full screen - sidebar - margins
        mw = self.WIDTH - mx - int(24*(self.WIDTH/1920))
        # Height: screen - top - bottom margins
        mh = self.HEIGHT - my - int(16*(self.HEIGHT/1080))
        return pygame.Rect(mx, my, mw, mh)

    def _bar_top(self):
        """Y where the top-right clock/theme/close bar (and, on touch,
        Patient List's own header row) starts. The close (X) button used to
        float above this row at a fixed screen position, so this returned
        room to clear it; now main.py reads the close button's rect FROM
        this bar (see _draw_top_right_bar), so it's just a plain top margin.
        Single source of truth so the bar, Patient List's header and
        _panel_area()'s margin can't drift apart from one another."""
        return self._sc(12)

    def _bar_height(self):
        """Tallest control _draw_top_right_bar draws -- the calendar/time
        pill, the Light/Dark toggle and the close button all share this same
        container height. _panel_area() uses this -- instead of a guess --
        to keep every other panel's header clear of this bar."""
        return self._sc(40)

    def _tt(self, px):
        """Touch-target size for an INTERACTIVE control: a 1080-referenced px,
        never below ~50px on the 7-inch panel so a fingertip clears it."""
        v = int(px * self._fs)
        if self._touch_ui:
            v = max(v, 50)
        return v

    def _sc(self, px):
        """Plain scaled size for a NON-interactive element (dot, row height,
        spacing) -- no tap-target floor."""
        return max(1, int(px * self._fs))

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE MODAL — Manages therapist profile editing interface
    # ──────────────────────────────────────────────────────────────────

    def _init_edit_fields(self):
        """Therapist profile editor. Sized from _fs/_tt so the controls stay
        finger-sized on the 800x480 panel.

        NOTE: there is deliberately no "New PIN" field. Changing a PIN goes
        through the forgot-PIN flow on the Login page and nowhere else."""
        W, H  = self.WIDTH, self.HEIGHT
        pad   = self._sc(18)
        fh    = self._tt(46)
        lbl_h = self.fnt["small"].get_height()
        # 2x2 field grid (not a single stacked column): 4 fields each floored at
        # a 50px touch target do not fit above the button row when stacked on a
        # 480px-tall screen even after the modal cap below. A 2-column grid
        # needs half the rows and fits with headroom to spare.
        row_h  = lbl_h + self._sc(4) + fh
        colgap = self._sc(14)
        rowgap = self._sc(14)
        btn_h = self._tt(46)
        icon_col_w = self._sc(170)   # wide enough for the big preview + "Change Icon"

        modal_w = min(int(W * 0.88), self._sc(720))
        modal_h = min(int(H * 0.94),
                      self.fnt["panel_title"].get_height() + self._sc(14)
                      + 2 * row_h + rowgap + btn_h + pad * 3)
        modal_x = (W - modal_w) // 2
        modal_y = (H - modal_h) // 2

        fx0 = modal_x + pad + icon_col_w
        fw  = (modal_w - pad * 2 - icon_col_w - colgap) // 2
        fy0 = modal_y + self.fnt["panel_title"].get_height() + self._sc(20) + lbl_h + self._sc(4)

        self.edit_modal_rect = pygame.Rect(modal_x, modal_y, modal_w, modal_h)
        _specs = [
            ("full_name", "Full Name",  self.account.get("full_name",""),  50, "Full name"),
            ("username",  "Username",   self.account.get("username",""),   MAX_USERNAME_LEN,
                                                                            "Letters, numbers, _ . @ # -"),
            ("role",      "Role",       self.account.get("role",""),        0, "Select role"),
            ("workplace", "Workplace",  self.account.get("workplace", self.account.get("clinic","")),
                                                                            60, "Workplace name"),
        ]
        self.edit_fields = []
        for i, (key, label, value, max_len, placeholder) in enumerate(_specs):
            col, row = i % 2, i // 2
            fx = fx0 + col * (fw + colgap)
            fy = fy0 + row * (row_h + rowgap)
            self.edit_fields.append({
                "key": key, "label": label, "value": value,
                "is_pin": False, "max_len": max_len, "placeholder": placeholder,
                "rect": pygame.Rect(fx, fy, fw, fh),
            })

        btn_y = modal_y + modal_h - btn_h - pad          # computed early for the icon budget below

        # Icon column: just the big preview + a "Change Icon" prompt. Picking
        # an icon now opens a dedicated, larger, SCROLLABLE picker popup
        # (_draw_icon_picker_popup) instead of cramming all 10 choices into
        # this narrow rail at a shrunk size -- see _open_icon_picker().
        icon_cx  = modal_x + pad + icon_col_w // 2
        avail_h  = btn_y - fy0 - self._sc(6)
        self.edit_big_r      = max(self._sc(30), min(int(avail_h * 0.34), self._sc(56)))
        self.edit_big_center = (icon_cx, fy0 + self.edit_big_r)
        chg_h = self._tt(40)
        chg_y = min(self.edit_big_center[1] + self.edit_big_r + self._sc(10),
                    btn_y - chg_h)
        chg_margin = self._sc(6)
        self.edit_change_icon_rect = pygame.Rect(
            modal_x + pad - chg_margin, chg_y, icon_col_w - 2 * pad + 2 * chg_margin, chg_h)
        # Kept for backward compatibility with any external reference; the
        # inline small-icon rail itself is gone (replaced by the picker popup).
        self.edit_small_r       = 0
        self.edit_small_circles = []

        self.edit_selected_icon = self.account.get("icon_index", 1)
        self.edit_active_field  = -1
        self.edit_error         = ""
        self.edit_role_open     = False

        role_rect = self.edit_fields[2]["rect"]
        opt_h     = self._tt(42)
        self.edit_role_options = [
            {"label": r,
             "rect": pygame.Rect(role_rect.x, role_rect.bottom+i*opt_h, fw, opt_h)}
            for i, r in enumerate(ROLES)
        ]

        btn_y = modal_y + modal_h - btn_h - pad
        bw2   = self._sc(120)
        dw2   = self.fnt["small"].size("Delete Account")[0] + self._sc(24)
        self.edit_save_rect   = pygame.Rect(modal_x+modal_w-pad-bw2,              btn_y, bw2, btn_h)
        self.edit_cancel_rect = pygame.Rect(self.edit_save_rect.x-self._sc(10)-bw2, btn_y, bw2, btn_h)
        self.edit_delete_rect = pygame.Rect(modal_x+pad,                          btn_y, dw2, btn_h)
        self.edit_save_hov = self.edit_cancel_hov = self.edit_delete_hov = False

    # ──────────────────────────────────────────────────────────────────
    #  EVENT HANDLING
    # ──────────────────────────────────────────────────────────────────

    def handle_event(self, event):
        """
        Main event dispatcher. Routes pygame events to appropriate handlers.
        Supports mouse clicks, touch/finger input, and keyboard input.
        """
        # If a scene transition is in progress, ignore all events
        if self.action_triggered:
            return None

        # ── "Session in Progress" screen (panel 7) owns all input ────
        if self.active_panel == 7:
            if event.type == pygame.FINGERDOWN:
                self._sm_handle_click((int(event.x * self.WIDTH), int(event.y * self.HEIGHT)))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                import builtins as _bi2
                _norm = getattr(_bi2, 'normalise_pos', lambda p: p)
                self._sm_handle_click(_norm(event.pos))
            return None

        # ── Calibration window intercepts all events when active ──────
        if self._cal_win is not None:
            self._cal_win.handle_event(event)
            return None

        # ── Share search popup: "Currently shared with:" list scroll
        #    (wheel + finger drag, same pattern as Register Patient below --
        #    FINGERDOWN does not return, so a plain tap still reaches the
        #    normal click dispatch later; only an actual drag's MOTION
        #    consumes the event and adjusts scroll). Checked here, ahead of
        #    the Patient List's own wheel handler below, because the share
        #    modal is a full-screen overlay on top of panel 0 (Patient
        #    List is always the active_panel underneath it) -- without this
        #    priority, every wheel event while the modal is open would
        #    scroll the hidden patient list instead of the popup on top of
        #    it. ──────────────────────────────────────────────────────────
        if self._share_modal_open and self._share_stage == "pick":
            if event.type == pygame.MOUSEWHEEL:
                if self._share_shared_viewport.collidepoint(pygame.mouse.get_pos()):
                    self._share_shared_scroll = max(0, min(
                        self._share_shared_scroll - event.y * self._tt(40),
                        self._share_shared_scroll_max))
                    return None
            elif event.type == pygame.FINGERDOWN:
                pos = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
                if self._share_shared_viewport.collidepoint(pos):
                    self._share_shared_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._share_shared_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._share_shared_scroll = max(0, min(
                    self._share_shared_scroll + (self._share_shared_drag_y - cy),
                    self._share_shared_scroll_max))
                self._share_shared_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._share_shared_drag_y = None

        # ── Patient List scrolling (wheel + touch drag) ──────────────
        if self.active_panel == 0:
            if event.type == pygame.MOUSEWHEEL:
                step = int(60 * self._fs)
                self._pl_scroll = max(0, min(self._pl_scroll - event.y * step,
                                             self._pl_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._pl_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._pl_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._pl_scroll = max(0, min(self._pl_scroll + (self._pl_drag_y - cy),
                                             self._pl_scroll_max))
                self._pl_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._pl_drag_y = None

        # ── Session Details scrolling (wheel + touch drag) ────────────
        # Metrics/Calibration Records/Session History are TABS inside panel 8
        # (self._pv_tab), not separate panels -- "active_panel == 1/2/3" below
        # can never be true (those panel numbers are unused), which silently
        # disabled wheel + touch-drag scrolling on all three tabs; only their
        # click-to-scroll arrow buttons worked. Gated on the real state now.
        if self.active_panel == 8 and self._pv_tab == "history" and self._sh_detail_record is not None:
            if event.type == pygame.MOUSEWHEEL:
                self._shd_scroll = max(0, min(self._shd_scroll - event.y * int(60 * self._fs),
                                              self._shd_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._shd_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._shd_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._shd_scroll = max(0, min(self._shd_scroll + (self._shd_drag_y - cy),
                                              self._shd_scroll_max))
                self._shd_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._shd_drag_y = None

        # ── Session History (list) scrolling (wheel + touch drag) ─────
        if self.active_panel == 8 and self._pv_tab == "history" and self._sh_detail_record is None:
            if event.type == pygame.MOUSEWHEEL:
                self._sh_scroll = max(0, min(self._sh_scroll - event.y * int(60 * self._fs),
                                             self._sh_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._sh_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._sh_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._sh_scroll = max(0, min(self._sh_scroll + (self._sh_drag_y - cy),
                                             self._sh_scroll_max))
                self._sh_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._sh_drag_y = None

        # ── Analytics (Metrics) scrolling (wheel + touch drag) ────────
        if self.active_panel == 8 and self._pv_tab == "analytics":
            if event.type == pygame.MOUSEWHEEL:
                self._an_scroll = max(0, min(self._an_scroll - event.y * int(60 * self._fs),
                                             self._an_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._an_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._an_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._an_scroll = max(0, min(self._an_scroll + (self._an_drag_y - cy),
                                             self._an_scroll_max))
                self._an_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._an_drag_y = None

        # ── Calibration Record Details scrolling (wheel + touch drag) ─
        if self.active_panel == 8 and self._pv_tab == "calibration" and self._cr_detail_record is not None:
            if event.type == pygame.MOUSEWHEEL:
                self._crd_scroll = max(0, min(self._crd_scroll - event.y * int(60 * self._fs),
                                              self._crd_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._crd_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._crd_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._crd_scroll = max(0, min(self._crd_scroll + (self._crd_drag_y - cy),
                                              self._crd_scroll_max))
                self._crd_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._crd_drag_y = None

        # ── Calibration Records (list) scrolling (wheel + touch drag) ─
        if self.active_panel == 8 and self._pv_tab == "calibration" and self._cr_detail_record is None:
            if event.type == pygame.MOUSEWHEEL:
                self._cr_scroll = max(0, min(self._cr_scroll - event.y * int(60 * self._fs),
                                             self._cr_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._cr_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._cr_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._cr_scroll = max(0, min(self._cr_scroll + (self._cr_drag_y - cy),
                                             self._cr_scroll_max))
                self._cr_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._cr_drag_y = None

        # ── Start Session scrolling (wheel + touch drag) ──────────────
        if self.active_panel == 5:
            if event.type == pygame.MOUSEWHEEL:
                self._ss_scroll = max(0, min(self._ss_scroll - event.y * int(60 * self._fs),
                                             self._ss_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._ss_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._ss_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._ss_scroll = max(0, min(self._ss_scroll + (self._ss_drag_y - cy),
                                             self._ss_scroll_max))
                self._ss_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._ss_drag_y = None

        # ── Patient page Info tab: scroll the field list ────────────
        if self.active_panel == 8 and self._pv_tab == "info":
            if event.type == pygame.MOUSEWHEEL:
                self._pv_info_scroll = max(0, min(
                    self._pv_info_scroll - event.y * int(60 * self._fs),
                    self._pv_info_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._pv_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and getattr(self, "_pv_drag_y", None) is not None:
                cy = event.y * self.HEIGHT
                self._pv_info_scroll = max(0, min(
                    self._pv_info_scroll + (self._pv_drag_y - cy), self._pv_info_scroll_max))
                self._pv_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._pv_drag_y = None

        # ── Register Patient (touch): scroll the form ───────────────
        if self.active_panel == 6 and self._touch_ui:
            if event.type == pygame.MOUSEWHEEL:
                self._rp_scroll = max(0, min(
                    self._rp_scroll - event.y * int(60 * self._fs),
                    self._rp_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._rp_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._rp_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._rp_scroll = max(0, min(
                    self._rp_scroll + (self._rp_drag_y - cy), self._rp_scroll_max))
                self._rp_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._rp_drag_y = None

        # ── Edit Profile: icon-picker popup scroll (wheel + finger drag) ──
        if self.modal == "edit_profile" and self.edit_icon_picker_open:
            if event.type == pygame.MOUSEWHEEL:
                self._eip_scroll = max(0, min(
                    self._eip_scroll - event.y * int(60 * self._fs), self._eip_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._eip_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._eip_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._eip_scroll = max(0, min(
                    self._eip_scroll + (self._eip_drag_y - cy), self._eip_scroll_max))
                self._eip_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._eip_drag_y = None

        # ── Touch screen input (mobile/tablet) ──
        if event.type == pygame.FINGERDOWN:
            # FINGERDOWN uses normalized coordinates (0.0-1.0), convert to pixels
            pos = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            return self._handle_click(pos)

        # ── Mouse click input (desktop) ──
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:  # 1 = left mouse button
            import builtins
            # Apply position normalization function if it exists (for coordinate mapping)
            norm = getattr(builtins, 'normalise_pos', lambda p: p)
            pos  = norm(event.pos)
            return self._handle_click(pos)

        # ── Keyboard input ──
        if event.type == pygame.KEYDOWN:
            # Share modal captures all keys first (highest priority)
            if self._share_modal_open:
                return self._handle_share_key(event)
            # Edit patient modal
            if self._ep_modal_open:
                self._ep_keydown(event); return None
            # Edit profile modal handles text input
            if self.modal == "edit_profile":
                if self.edit_icon_picker_open:
                    if event.key == pygame.K_ESCAPE:
                        self.edit_icon_picker_open = False
                    return None
                return self._handle_edit_key(event)
            # Patient search field
            if self.active_panel == 0 and self._pt_search_active:
                if event.key == pygame.K_BACKSPACE:
                    self._pt_search_text = self._pt_search_text[:-1]
                elif event.unicode and len(self._pt_search_text) < 40:
                    self._pt_search_text += event.unicode
                return None
            # Register patient panel handles text input
            if self.active_panel == 6 and self.rp.get("active_key"):
                self._rp_keydown(event)
                return None
            # (no ESC navigation — use mouse/touch only)

        return None

    def _handle_click(self, pos):
        """
        Process mouse/touch clicks. Routes clicks to appropriate handlers
        based on which UI element was clicked. Checked in priority order:
        share modal > other modals > sidebar > panels
        """
        # ── Edit patient modal ────────────────────────────────────────
        if self._ep_modal_open:
            # Delete-confirm / Save-confirm overlays sit on top — handled first
            if self.modal == "delete_patient_confirm":
                yr, nr = self._confirm_rects()
                if yr.collidepoint(pos) and self._danger_countdown <= 0:
                    play_click()
                    self._ep_delete()
                    self._ep_modal_open = False
                    self.modal = None
                elif nr.collidepoint(pos):
                    play_click()
                    self.modal = None
                return None
            if self.modal == "save_patient_confirm":
                yr, nr = self._confirm_rects()
                if yr.collidepoint(pos):
                    play_click()
                    self._ep_submit()
                    self.modal = None
                elif nr.collidepoint(pos):
                    play_click()
                    self.modal = None
                return None
            self._ep_handle_click(pos); return None

        # ── Share modal (checked before everything else - highest priority) ──
        # Each stage draws its own single dismiss button (Cancel on choice/
        # confirm, Close on the picker) -- checked per-stage below, not as
        # one extra blanket "Close" check on top of it, so there's never a
        # redundant second dismiss control active at once.
        if self._share_modal_open:
            # Final confirmation (worded for whichever action was chosen)
            if self._share_stage == "confirm":
                if self._share_yes_rect.collidepoint(pos):
                    # TRANSFER carries the mandatory 5-second safety delay;
                    # SHARE (non-destructive, doesn't change ownership) doesn't.
                    if (self._share_pending_action == "transfer"
                            and self._danger_countdown > 0):
                        return None
                    play_click()
                    self._do_share_or_transfer_confirm(); return None
                if self._share_no_rect.collidepoint(pos):
                    play_click()
                    self._share_stage = "choice"       # back one step, not all the way out
                    return None
                return None

            # SHARE | TRANSFER choice
            if self._share_stage == "choice":
                if self._share_choice_share_rect.collidepoint(pos):
                    play_click()
                    self._share_pending_action = "share"
                    self._share_stage = "confirm"
                    self._danger_countdown = 0.0
                    return None
                if self._share_choice_transfer_rect.collidepoint(pos):
                    play_click()
                    self._share_pending_action = "transfer"
                    self._share_stage = "confirm"
                    self._danger_countdown = 5.0
                    return None
                if self._share_no_rect.collidepoint(pos):   # "Cancel" back to the picker
                    play_click()
                    self._share_stage             = "pick"
                    self._share_confirm_therapist = None
                    return None
                return None

            # "pick" stage -- the therapist username search form.
            if self._share_close_rect.collidepoint(pos):
                play_click()
                self._share_modal_open = False; return None

            # Live suggestion item clicks -> SHARE|TRANSFER choice (not straight to confirm)
            for (sr, therapist) in self._share_sugg_rects:
                if sr.collidepoint(pos):
                    play_click()
                    self._share_confirm_therapist = therapist
                    self._share_stage             = "choice"
                    return None

            # Unshare/Revoke buttons
            for (ur, tid) in self._unshare_rects:
                if ur.collidepoint(pos):
                    play_click()
                    self.db.unshare_patient(self.share_modal_patient["id"], tid)
                    self._share_success = "Access revoked."
                    self._share_error   = ""
                    return None

            return None  # absorb all other clicks

        # ── "Use Previous Calibration?" reuse chooser ───────────────────
        if self.modal == "reuse_calibration_choice":
            if self._reuse_use_rect.collidepoint(pos):
                play_click()
                reused = {s: self._calibrated_sensors[s] for s in self._reuse_available}
                game_name, game_type, cal_types = (self._reuse_game_name,
                                                   self._reuse_game_type, self._reuse_cal_types)
                self.modal = None
                self._open_calibration_window(game_name, game_type, cal_types, reused=reused)
                return None
            if self._reuse_recal_rect.collidepoint(pos):
                play_click()
                game_name, game_type, cal_types = (self._reuse_game_name,
                                                   self._reuse_game_type, self._reuse_cal_types)
                self.modal = None
                self._open_calibration_window(game_name, game_type, cal_types, reused=None)
                return None
            return None  # absorb all other clicks

        # ── Calibration mismatch modal ────────────────────────────────
        if self.modal == "calibration_mismatch":
            if self._mismatch_cal_rect.collidepoint(pos):
                play_click()
                self.modal = None
                game_name, game_type = self.gc.get("selected_game") or (None, "Grip Strength")
                game_type  = game_type or "Grip Strength"
                self._launch_calibration(game_name, game_type)
                return None
            if self._mismatch_cancel_rect.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        # ── "Select a Game" skill picker modal ──────────────────────────
        # Checked here (ahead of Sidebar/Back/breadcrumbs/panel dispatch
        # below) so none of those can fire while it's open -- previously
        # only _gc_handle_click (reached far later, deep in the panel-4
        # dispatch) checked _gc_skill_modal_open, so Logout, the theme
        # toggle, panel nav, Back and breadcrumbs all still click-through
        # behind the modal. The app's top-right Close button is blocked
        # separately, in main.py, the same way the Share/Transfer popups
        # already block it (see _gc_skill_modal_open there).
        if self._gc_skill_modal_open:
            self._gc_handle_skill_modal_click(pos)
            return None

        # ── Other modals ──────────────────────────────────────────────
        if self.modal == "delete_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos) and self._danger_countdown <= 0:
                play_click()
                # _ep_delete() itself decides what closes: on success it clears
                # _ep_modal_open; on an ownership-check failure it leaves the
                # edit modal open (behind this confirm dialog) so the error is
                # visible, and here we only need to dismiss the confirm dialog.
                self._ep_delete()
                self.modal = None
            if nr.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        if self.modal == "delete_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos) and self._danger_countdown <= 0:
                play_click()
                if self.db.delete_therapist(self.account["id"]):
                    # Account gone -- invalidate this therapist's session the
                    # same way logging out does (dual-monitor presence state)
                    # and go straight to the login screen, not the splash.
                    if _DUAL_MONITOR:
                        therapist_link.set_present(False)
                        therapist_link.set_booting(True)
                    self.action_triggered = True
                    return "login"
                # Still owns patients -- refuse and explain instead of deleting.
                self.modal = "delete_blocked"
            if nr.collidepoint(pos):
                play_click()
                self.modal = "edit_profile"
            return None

        if self.modal == "save_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                play_click()
                self._ep_submit()
                self.modal = None
            if nr.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        if self.modal == "save_account_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                play_click()
                self._attempt_save()
            if nr.collidepoint(pos):
                play_click()
                self.modal = "edit_profile"
            return None

        if self.modal == "delete_blocked":
            # Single dismiss button: back to Edit Profile so the therapist can
            # go transfer their patients (Phase 4: Share icon -> TRANSFER).
            if self._db_blocked_ok_rect.collidepoint(pos):
                play_click()
                self.modal = "edit_profile"
            return None

        if self.modal == "register_success":
            if self._rp_ok_rect.collidepoint(pos):
                play_click()
                self.modal = None
                self._open_panel(0)
            return None

        if self.modal == "transfer_success":
            if self._transfer_ok_rect.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        if self.modal == "logout_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                play_click()
                stop_lobby_music()
                if _DUAL_MONITOR:
                    therapist_link.set_present(False)   # logged out ...
                    therapist_link.set_booting(True)    # ... back on the Login page -> patient Waiting Screen
                self.action_triggered = True
                return "login"
            if nr.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        if self.modal == "select_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):                    # CONFIRM
                play_click()
                self._confirm_select_patient()
            elif nr.collidepoint(pos):                  # CANCEL
                play_click()
                self._pending_select_patient = None
                self.modal = None
            return None

        if self.modal == "deselect_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):                    # CONFIRM -> clear the selection
                play_click()
                self._pending_deselect_patient = None
                self.modal = None
                self._set_selected_patient(None)
            elif nr.collidepoint(pos):                  # CANCEL -> keep it selected
                play_click()
                self._pending_deselect_patient = None
                self.modal = None
            return None

        if self.modal == "edit_profile":
            if self.edit_icon_picker_open:
                return self._handle_icon_picker_click(pos)
            return self._handle_edit_click(pos)

        # ── Sidebar ──────────────────────────────────────────────────
        if self._edit_link_rect.collidepoint(pos):
            play_click()
            self._init_edit_fields(); self.modal = "edit_profile"; return None

        if self._logout_rect().collidepoint(pos):
            play_confirm_alert()
            self.modal = "logout_confirm"; return None

        if self._theme_btn_rect.collidepoint(pos):
            play_click()
            self._apply_theme(not self._applied_theme_dark)   # -> therapist + patient
            return None

        # Active Patient box: the WHOLE container (label, name, padding) is
        # one tap target that opens that patient's Patient Info page -- not
        # just the name/icon text within it. Dead 1x1 rect when nobody is
        # selected, so this can never fire on an empty/invalid patient.
        if self._active_patient_rect.collidepoint(pos) and self.selected_patient:
            play_click()
            self.preview_patient   = self.selected_patient
            self._pv_tab           = "info"
            self._pv_info_scroll   = 0
            self._cr_detail_record = None
            self._sh_detail_record = None
            self._metrics_expanded = set()
            self._open_panel(8)
            return None

        # Controller monitor: tap to force a fresh BLE scan (manual retry).
        if self._ctrl_btn_rect.collidepoint(pos):
            play_click()
            if _ble_receiver is not None and (not _DUAL_MONITOR or self.selected_patient):
                try:
                    _ble_receiver.rescan()
                    self._ble_want = True        # keep the reconcile in step
                except Exception:
                    pass
            return None

        for i, r in enumerate(self.nav_rects):
            if r.collidepoint(pos):
                play_click()
                self._open_panel(SIDEBAR_NAV[i]["idx"]); return None

        # ── Back button ───────────────────────────────────────────────
        if self.active_panel != -1 and self._back_btn_rect.collidepoint(pos):
            play_click(); self._go_back(); return None

        # ── Clickable breadcrumbs ─────────────────────────────────────
        for hit, target in self._crumb_rects:
            if hit.collidepoint(pos):
                play_click()
                self._nav_breadcrumb(target)
                return None

        # ── Home cards ────────────────────────────────────────────────
        if self.active_panel == -1:
            for i, cr in enumerate(self.card_rects):
                if cr.collidepoint(pos):
                    play_click()
                    self._open_panel(HOME_CARDS[i]["idx"])
                    return None

        # ── Panel 0: Patient List ─────────────────────────────────────
        if self.active_panel == 0:
            if self._pl_up_rect.collidepoint(pos):
                play_click(); self._pl_scroll_by(-1); return None
            if self._pl_down_rect.collidepoint(pos):
                play_click(); self._pl_scroll_by(1); return None
            if self._pt_search_rect.collidepoint(pos):
                self._pt_search_active = True; return None
            else:
                self._pt_search_active = False
            if self._register_link_rect.collidepoint(pos):
                play_click(); self._open_panel(6); return None
            for row in self._patient_rows:
                btn_rect = row[0]
                patient  = row[1]
                action   = row[2] if len(row) > 2 else "name"
                if btn_rect.collidepoint(pos):
                    play_click()
                    if action == "share":
                        self._open_share_modal(patient)     # only right-side action left
                    else:   # "name" -- the row opens the patient's own page.
                        # Does NOT select the patient; selection happens there.
                        self.preview_patient = patient
                        self._pv_tab = "info"
                        self._pv_info_scroll = 0
                        self._cr_detail_record = None
                        self._sh_detail_record = None
                        self._metrics_expanded = set()
                        self._open_panel(8)
                    return None

        # ── Session History / Analytics / Calibration Records: scroll-arrow
        # clicks. These are TABS inside panel 8 (self._pv_tab), not separate
        # panels -- gating this on "active_panel == 1/2/3" (unused panel
        # numbers) meant the arrow buttons were drawn but never actually
        # clickable on any of the three tabs. Gated on the real state now.
        if self.active_panel == 8 and self._pv_tab == "history" and self._sh_detail_record is not None:
            # Session Details (full page, not a popup/modal) -- Back returns
            # to the list with its scroll position untouched (_sh_scroll was
            # never touched while the details page was up). Deliberately NO
            # catch-all "return None" below: the details view only replaces
            # the content area, not the whole Patient Profile interface, so
            # a click that misses all three of these must fall through to
            # the top nav tabs / Select-Deselect Patient handling further
            # down -- those were silently unclickable while a record was
            # open because this block used to swallow every click here.
            if self._shd_back_rect.collidepoint(pos):
                play_click(); self._sh_detail_record = None; return None
            if self._shd_up_rect.collidepoint(pos):
                play_click(); self._shd_scroll = max(0, self._shd_scroll - int(160*self._fs)); return None
            if self._shd_down_rect.collidepoint(pos):
                play_click()
                self._shd_scroll = min(self._shd_scroll_max, self._shd_scroll + int(160*self._fs))
                return None

        if self.active_panel == 8 and self._pv_tab == "history":
            if self._sh_up_rect.collidepoint(pos):
                play_click(); self._sh_scroll = max(0, self._sh_scroll - int(160*self._fs)); return None
            if self._sh_down_rect.collidepoint(pos):
                play_click()
                self._sh_scroll = min(self._sh_scroll_max, self._sh_scroll + int(160*self._fs))
                return None
            # Every session row is its own tap target, looked up by the
            # session's own DB id (via the stored record itself) -- not by
            # list position/index, which would point at the wrong record
            # once the list is scrolled.
            for row_r, sess in self._sh_row_rects:
                if row_r.collidepoint(pos):
                    play_click()
                    self._sh_detail_record = sess
                    self._shd_scroll = 0
                    return None

        if self.active_panel == 8 and self._pv_tab == "analytics":
            if self._an_up_rect.collidepoint(pos):
                play_click(); self._an_scroll = max(0, self._an_scroll - int(160*self._fs)); return None
            if self._an_down_rect.collidepoint(pos):
                play_click()
                self._an_scroll = min(self._an_scroll_max, self._an_scroll + int(160*self._fs))
                return None
            # Metrics tree: the WHOLE row (category/subcategory/game/mode),
            # not just a chevron, toggles that node's expand/collapse state.
            for row_r, path in self._metrics_row_rects:
                if row_r.collidepoint(pos):
                    play_click()
                    if path in self._metrics_expanded:
                        self._metrics_expanded.discard(path)
                    else:
                        self._metrics_expanded.add(path)
                    return None

        if self.active_panel == 8 and self._pv_tab == "calibration" and self._cr_detail_record is not None:
            # Calibration Record Details (full page, not a popup/modal) --
            # Back returns to the list with its scroll position untouched
            # (_cr_scroll was never touched while the details page was up).
            # Deliberately NO catch-all "return None" below -- see the
            # matching comment on Session Details above: a miss here must
            # fall through to the top nav tabs / Select-Deselect Patient.
            if self._crd_back_rect.collidepoint(pos):
                play_click(); self._cr_detail_record = None; return None
            if self._crd_up_rect.collidepoint(pos):
                play_click(); self._crd_scroll = max(0, self._crd_scroll - int(160*self._fs)); return None
            if self._crd_down_rect.collidepoint(pos):
                play_click()
                self._crd_scroll = min(self._crd_scroll_max, self._crd_scroll + int(160*self._fs))
                return None

        if self.active_panel == 8 and self._pv_tab == "calibration":
            if self._cr_up_rect.collidepoint(pos):
                play_click(); self._cr_scroll = max(0, self._cr_scroll - int(160*self._fs)); return None
            if self._cr_down_rect.collidepoint(pos):
                play_click()
                self._cr_scroll = min(self._cr_scroll_max, self._cr_scroll + int(160*self._fs))
                return None
            for row_r, rec in self._cr_row_rects:
                if row_r.collidepoint(pos):
                    play_click()
                    self._cr_detail_record = rec
                    self._crd_scroll = 0
                    return None

        # ── Panel 8: the patient's own page (info + records + selection) ──
        if self.active_panel == 8:
            if self._pv_info_up_rect.collidepoint(pos):
                play_click(); self._pv_info_scroll = max(0, self._pv_info_scroll - int(160*self._fs)); return None
            if self._pv_info_down_rect.collidepoint(pos):
                play_click()
                self._pv_info_scroll = min(self._pv_info_scroll_max, self._pv_info_scroll + int(160*self._fs))
                return None
            for key, r in self._pv_tab_rects.items():
                if r.collidepoint(pos):
                    play_click()
                    self._pv_tab = key
                    self._pv_info_scroll = 0
                    self._cr_detail_record = None
                    self._sh_detail_record = None
                    return None
            # Per-section Edit buttons on the Info tab (owner only).
            # "Record" deliberately has none -- it is always read-only.
            for sec, r in self._pv_sec_edit_rects.items():
                if r.collidepoint(pos) and self.preview_patient:
                    play_click()
                    self._open_ep_modal(self.preview_patient, section=sec)
                    return None
            if self._pv_select_rect.collidepoint(pos) and self.preview_patient:
                play_confirm_alert()
                if self._is_selected(self.preview_patient):
                    # DESELECT PATIENT -- confirm first, then clear (stay here).
                    self._pending_deselect_patient = self.preview_patient
                    self.modal = "deselect_patient_confirm"
                else:
                    # SELECT PATIENT -- confirm, then continue to Game Config.
                    self._pending_select_patient = self.preview_patient
                    self.modal = "select_patient_confirm"
                return None

        # ── Panel 6: Register Patient ─────────────────────────────────
        if self.active_panel == 6:
            if self._touch_ui:
                if self._rp_up_rect.collidepoint(pos):
                    play_click()
                    self._rp_scroll = max(0, self._rp_scroll - int(160 * self._fs))
                    return None
                if self._rp_down_rect.collidepoint(pos):
                    play_click()
                    self._rp_scroll = min(self._rp_scroll_max,
                                          self._rp_scroll + int(160 * self._fs))
                    return None
            self._rp_handle_click(pos)

        # ── Panel 4: Game Configuration -- 3 internal steps (see _gc_step) ──
        # Strict step-by-step Back: Settings -> Mode -> Game, never further
        # (Step 1/"game" has no Back button at all -- _gc_back_rect is a
        # dead 1x1 rect there, see _draw_gc_progress -- and never jumps out
        # to the Patient List or any other panel).
        if self.active_panel == 4:
            if self._gc_back_rect.collidepoint(pos):
                play_click()
                if self._gc_step == "settings":
                    self._gc_step = "mode"
                elif self._gc_step == "mode":
                    self._gc_step = "game"
                return None
            if self._gc_step == "mode":
                self._gc_handle_mode_click(pos)
            elif self._gc_step == "settings":
                self._gc_handle_settings_click(pos)
            else:
                self._gc_handle_click(pos)
            if self._gc_next_rect.collidepoint(pos):
                play_click()
                if self._gc_step == "game":
                    self._gc_step = "mode"
                elif self._gc_step == "mode":
                    self._gc_step = "settings"
                else:
                    self._open_panel(5)
                return None

        # ── Panel 5: Start Session -- a single CTA button that is EITHER
        # "Calibrate" (not ready yet) OR "Start Session" (ready); the draw
        # code sets exactly one of these two rects to the real button area
        # each frame and the other to a dead 1x1, so only one of the two
        # checks below can ever actually fire. ──
        if self.active_panel == 5:
            if _TEST_MODE_AVAILABLE and self._test_mode_btn_rect.collidepoint(pos):
                play_click()
                self._test_mode_bypass = not self._test_mode_bypass
                return None

            if self._calibrate_btn_rect.collidepoint(pos):
                play_click()
                game_name, game_type = self.gc.get("selected_game") or (None, "Grip Strength")
                game_type = game_type or "Grip Strength"
                self._launch_calibration(game_name, game_type)
                return None

            if self._start_btn_rect.collidepoint(pos):
                # _start_btn_rect is only ever live when the draw code's own
                # `ready` (which already accounts for Test Mode) was True, so
                # no separate _session_ready() re-check is needed here.
                test_mode_on = _TEST_MODE_AVAILABLE and self._test_mode_bypass
                if not test_mode_on and self._calibration_mismatched():
                    self.modal = "calibration_mismatch"
                    return None
                play_start_session()
                self._sm_test_mode = test_mode_on
                return self._launch_game(test_mode=test_mode_on)

        return None

    def _go_back(self):
        if self.active_panel == 6:   self._open_panel(0)
        elif self.active_panel == 4:
            if self._gc_step == "settings":
                self._gc_step = "mode"
            elif self._gc_step == "mode":
                self._gc_step = "game"
            else:
                self._open_panel(0)
        elif self.active_panel == 5:
            # Land back on the LAST Game Config step, not a fresh "game" pick.
            self.active_panel = 4
            self._gc_step      = "settings"
        elif self.active_panel == 8: self._open_panel(0)     # patient page -> Patient List
        elif self.active_panel == 7:
            # Session in Progress -> Game Configuration. If a game is actively
            # RUNNING or PAUSED, don't navigate (and don't stop/reset it) --
            # warn the therapist instead; they must stop it manually first.
            status = (self._sm_state or {}).get("status")
            if status in (_rc_cmd.RUNNING, _rc_cmd.PAUSED):
                self._sm_back_warning = True
                return
            # Terminate any active game/session first so no stale
            # patient-side state is left behind.
            self._sm_back()

    def _nav_breadcrumb(self, target):
        """Handle a click on a clickable breadcrumb item."""
        kind, val = target
        if kind == "panel":
            self._open_panel(val)
        elif kind == "patient" and val:
            self.preview_patient = val
            self._pv_tab = "info"
            self._pv_info_scroll = 0
            self._open_panel(8)

    def _view_patient(self):
        """Which patient the per-patient record panels (Analytics / Calibration /
        Session History) should display: the Preview target while reviewing on
        panel 8, otherwise the selected session patient."""
        if self.active_panel == 8:
            return self.preview_patient
        return self.selected_patient

    def _apply_theme(self, dark: bool, persist: bool = True):
        """One source of truth for the RecovR light/dark theme. Applies it on
        this side (constants.get_theme() drives the games / calibration window)
        AND pushes it to the patient monitor immediately -- no reload, no new
        session, works on whatever patient screen is showing.

        The theme belongs to the SELECTED PATIENT: whenever one is selected the
        new value is written to their row, so re-selecting them later restores
        it. `persist=False` is used when we are *restoring* a stored value and
        must not write it straight back."""
        if dark == self._applied_theme_dark:
            return
        self._applied_theme_dark = dark
        try:
            from constants import set_dark_mode
            set_dark_mode(dark)
        except Exception:
            pass
        if _DUAL_MONITOR:
            therapist_link.set_dark_mode(dark)
        if persist and self.selected_patient:
            pid = self.selected_patient.get("id")
            try:
                if pid is not None and hasattr(self.db, "set_patient_theme"):
                    self.db.set_patient_theme(pid, dark)
                    # keep the in-memory rows in step so a re-select reads it back
                    self.selected_patient["theme_dark"] = 1 if dark else 0
                    for p in (self.patients or []):
                        if p.get("id") == pid:
                            p["theme_dark"] = 1 if dark else 0
                    if self.preview_patient and self.preview_patient.get("id") == pid:
                        self.preview_patient["theme_dark"] = 1 if dark else 0
            except Exception:
                pass

    def _restore_patient_theme(self, patient):
        """Apply a patient's stored theme when they become the selected patient.
        Patients registered before the column existed default to Light."""
        dark = bool((patient or {}).get("theme_dark", 0))
        self._apply_theme(dark, persist=False)

    # ── selected-patient: ONE source of truth (self.selected_patient),
    #    mirrored into the shared session so every view + the patient monitor
    #    agree. Route ALL selection changes through _set_selected_patient(). ──
    def _is_selected(self, patient):
        return bool(patient and self.selected_patient
                    and self.selected_patient.get("id") == patient.get("id"))

    def _push_selected_patient(self):
        if not _DUAL_MONITOR:
            return
        p = self.selected_patient
        if not p:
            therapist_link.set_selected_patient(None)
            return
        # Attach the patient's recent session history (full per-session detail
        # -- not just game/date/difficulty/score -- so the Patient Dashboard's
        # Latest Session card can show the real game-specific result metric
        # (completed_reps), duration, and goal/session_mode, instead of only a
        # generic score) and an aggregate progress summary, so the patient
        # process can show both without any DB access of its own.
        hist = []
        stats = None
        try:
            if hasattr(self.db, "get_sessions"):
                for s in self.db.get_sessions(self.account["id"], patient_id=p["id"])[:20]:
                    hist.append({
                        "game":                       s.get("game", ""),
                        # Full timestamp (date AND time), not truncated to just
                        # the date -- the Patient Dashboard's Latest Session
                        # card shows both.
                        "played_at":                  str(s.get("played_at", "")),
                        "difficulty":                 s.get("difficulty", ""),
                        "score":                      s.get("score", ""),
                        "status":                     s.get("status", "completed"),
                        "goal":                       s.get("goal"),
                        "completed_reps":             s.get("completed_reps"),
                        "duration_sec":               s.get("duration_sec", 0),
                        "session_mode":               s.get("session_mode", "target"),
                        "configured_duration_seconds": s.get("configured_duration_seconds"),
                    })
            if hasattr(self.db, "get_patient_progress_summary"):
                stats = self.db.get_patient_progress_summary(p["id"])
        except Exception:
            pass
        therapist_link.set_selected_patient(
            {"id": p.get("id"), "full_name": p.get("full_name", ""),
             "sex": p.get("sex", ""), "history": hist, "stats": stats})

    def _set_selected_patient(self, patient):
        """Set (patient dict) or clear (None) the selected session patient and
        mirror it to shared state. The patient monitor shows its Dashboard only
        while this is set, and returns to the Waiting Screen when it is cleared.

        Selecting also restores that patient's saved theme; deselecting returns
        the interface to the Light default.

        The session-scoped calibration reuse cache (_calibrated_sensors)
        lives and dies with a single patient staying selected -- it's
        cleared here whenever the patient actually CHANGES (including to
        None), but survives re-confirming the SAME already-selected patient
        (e.g. navigating away and back), matching "the patient must be able
        to play multiple games consecutively... never allow calibration
        results from one patient to be reused for another"."""
        old_id = (self.selected_patient or {}).get("id")
        new_id = (patient or {}).get("id")
        if old_id != new_id:
            self._calibrated_sensors = {}
        self.selected_patient = patient or None
        self._push_selected_patient()
        if patient:
            self._restore_patient_theme(patient)
        else:
            self._apply_theme(False, persist=False)   # no patient -> Light

    def _pl_scroll_by(self, direction):
        """Scroll the Patient List (touchscreen ▲/▼ buttons and mouse wheel).
        `direction` is -1 (up) or +1 (down); each press moves ~3 rows."""
        step = int(120 * self._fs) * 3 * (1 if direction > 0 else -1)
        self._pl_scroll = max(0, min(self._pl_scroll + step, self._pl_scroll_max))

    def _confirm_select_patient(self):
        """The single place a patient actually becomes the session patient:
        reached only after the SELECT -> confirmation dialog is confirmed.
        Sets the patient and continues to Game Configuration."""
        patient = self._pending_select_patient
        self._pending_select_patient = None
        self.modal = None
        if not patient:
            return
        self._set_selected_patient(patient)
        self._init_game_config_state()
        self.calibration_done   = False
        self.calibration_result = None
        self._cal_win           = None
        self._open_panel(4)

    def _open_panel(self, idx):
        self.active_panel      = idx
        if idx == 4:
            self._gc_step = "game"
        if idx == 6:
            self._rp_scroll  = 0
            self._rp_drag_y  = None
        if idx == 0:
            self._pt_search_active = False
            self._pt_search_text   = ""
            self._pl_scroll        = 0
            self._pl_drag_y        = None
            try:
                self.patients = (
                    self.db.get_all_patients(therapist_id=self.account["id"])
                    if hasattr(self.db, 'get_all_patients') else []
                )
            except Exception:
                self.patients = []

    def _sync_dur_to_cal(self):
        """Push Session Details speed → newly opened CalibrationWindow
        Advanced Settings. (Sessions are goal-based now -- there is no
        duration to sync; see GAME_PARAM_SCHEMA's per-game goal param
        instead, which the Advanced Settings screen already surfaces.)"""
        if self._cal_win is None:
            return
        self._cal_win.adv_speed = self.gc.get("speed", "Normal")

    def _sync_dur_from_cal(self, cal_win):
        """Pull CalibrationWindow Advanced Settings speed → Session Details,
        so edits made there (e.g. the per-game Advanced Settings screen's
        Speed row) actually reach the launched game."""
        self.gc["speed"] = cal_win.adv_speed

    def _cal_progress_payload(self):
        """The live sensor/step/attempt/reading snapshot pushed to the
        patient's own Calibration screen -- read-only, straight off
        CalibrationWindow's own public state, never a second calculation of
        it. Returns {} while on the "results"/"advanced" phase (nothing is
        actively being measured then; the patient screen shows its own
        "reviewing results" message for those) or for a sensor this screen
        doesn't have art for (never true today, but a safe fallback)."""
        win = self._cal_win
        if win is None:
            return {}
        phase = win.phase
        if phase in ("results", "advanced"):
            return {"phase": phase}
        sensor = _CAL_SENSOR_KEY.get(win.game_type, "")
        if not sensor:
            return {}
        live_frac = None
        if phase == "recording":
            live_frac = round(win.live_value, 3)
        elif phase == "trial_done":
            live_frac = round(win.peak_value, 3)
        # Reused sensors never run a live trial, so the patient should never
        # see them counted as a step -- "Step X of Y" reflects only the
        # sensors actually being calibrated THIS window (spec: "show only
        # the remaining calibration steps"), not the game's full sensor
        # list. win.game_type is always one of these by construction (the
        # window auto-skips any pre-seeded/reused sensor -- see
        # CalibrationWindow._advance_sensor_idx), so .index() always finds it.
        remaining = [s for s in win.game_types if s not in win._initially_reused_sensors]
        if win.game_type not in remaining:
            remaining = [win.game_type]   # defensive fallback, not expected to trigger
        return {
            "sensor":        sensor,
            "step_index":    remaining.index(win.game_type) + 1,
            "step_count":    len(remaining),
            "attempt_index": min(win.current_trial + 1, 3),
            "attempt_count": 3,
            "phase":         phase,
            "live_frac":     live_frac,
        }

    def _session_ready(self):
        return (self.selected_patient is not None and
                self.gc["selected_game"] is not None and
                (self.calibration_done or self.calibration_bypassed))

    def _calibration_mismatched(self):
        """True when calibration_done but what was actually calibrated
        doesn't cover every sensor the currently selected game needs.

        A straight game_type string match (the original implementation)
        breaks the moment a multi-sensor result can come from a game whose
        own SKILL_GAMES category isn't literally "Multi-skill" (e.g. Feed
        the Cat / Catch 'n Grab are "Dual Skill", but
        CalibrationWindow._accept_multi_sensor() always stamps
        game_type="Multi-skill") -- that would flag every one of their own
        calibrations as mismatched against themselves. Comparing sensor SETS
        instead is correct for both single- and multi-sensor results, and
        for free also recognizes a multi-sensor calibration that happens to
        already cover a simpler game's single required sensor (e.g. Grip
        Strength, calibrated as part of Plant the Garden, satisfies
        Basketball too) instead of forcing a pointless recalibration."""
        if not self.calibration_done or self.calibration_bypassed:
            return False
        game_name, game_type = self.gc.get("selected_game") or (None, "")
        game_type = game_type or ""
        required = set(_required_sensors_for_game(game_name, game_type))
        if not required:
            return False
        res = self.calibration_result or {}
        calibrated = set(res["sensors"].keys()) if "sensors" in res else {res.get("game_type", "")}
        return not required.issubset(calibrated)

    # ── Calibration launch (shared by the Calibrate button and the
    #    mismatch modal's "Recalibrate") ─────────────────────────────────

    def _launch_calibration(self, game_name, game_type):
        """Single entry point for opening calibration. If any sensor this
        game needs already has a valid, reusable result for the currently
        selected patient from earlier in this same therapy session
        (self._calibrated_sensors), pause on the "Use Previous Calibration?"
        chooser instead of jumping straight into live trials -- see
        _draw_reuse_calibration_modal() / the "reuse_calibration_choice"
        click handler. With nothing reusable, behaves exactly as before."""
        cal_types = MULTI_SENSOR_CALIBRATION.get(game_name, game_type)
        required  = _required_sensors_for_game(game_name, game_type)
        available = [s for s in required if s in self._calibrated_sensors]
        if available:
            self._reuse_game_name = game_name
            self._reuse_game_type = game_type
            self._reuse_cal_types = cal_types
            self._reuse_available = available
            self._reuse_needed    = [s for s in required if s not in available]
            self.modal = "reuse_calibration_choice"
            return
        self._open_calibration_window(game_name, game_type, cal_types, reused=None)

    def _open_calibration_window(self, game_name, game_type, cal_types, reused):
        self._cal_win = CalibrationWindow(self.WIDTH, self.HEIGHT, cal_types,
                                          game_name=game_name, dark_mode=self._applied_theme_dark,
                                          reused_sensors=reused)
        if _DUAL_MONITOR:
            # Push the just-resolved sensor/phase BEFORE the CALIBRATE
            # command itself (not after, on the next throttled per-frame
            # tick) -- a fully-reused window already starts on "results", so
            # without this the patient screen could flash into Calibration
            # for a frame before flipping back to the Dashboard. See
            # patient_main.py's actively_calibrating gating, which requires
            # a real sensor to already be present before ever showing it.
            payload = self._cal_progress_payload()
            self._cal_progress_last = payload
            therapist_link.set_calibration_progress(payload)
            therapist_link.calibrate_begin(game_name or game_type)
        self._sync_dur_to_cal()

    # Maps the specific game name chosen in Game Config to a scene key in main.py
    _GAME_SCENE_MAP = {
        "Basketball": "basketball",
        "Lemonade": "lemonade",
        "Steady Aim": "steady_aim",
        "Piano Tiles": "piano_tiles",
        "Apple Catching": "catchingapple",
        "Catch 'n Grab": "catch_object",
        "Key and Lock": "key_lock",
        "Feed the Cat": "feed_the_cat",
        "Plant the Garden": "plant_the_garden",
    }

    def _game_goal_text(self, game_name):
        """Target Mode: 'Goal: <value><unit>', preferring the therapist's own
        Session Settings target_reps, then any Advanced Settings override,
        then the GAME_PARAM_SCHEMA is_goal preset for the selected difficulty.
        Timed Mode: 'Duration: MM:SS' from Session Settings / the game's own
        difficulty preset -- never a goal, since none exists in this mode."""
        difficulty = self.gc.get("difficulty", "Medium")
        if self.gc.get("session_mode", "target") == "timed":
            dur = self.gc.get("duration_sec") or \
                GAME_TIMED_DURATION_PRESETS.get(game_name, {}).get(difficulty, 60)
            mins, secs = divmod(int(dur), 60)
            return f"Duration: {mins}:{secs:02d}"

        spec = next((s for s in GAME_PARAM_SCHEMA.get(game_name, []) if s.get("is_goal")), None)
        if spec is None:
            return ""
        target = self.gc.get("target_reps")
        if target:
            shown = int(target)
        else:
            params = (self.calibration_result or {}).get("params", {})
            val = params.get(spec["key"], spec["presets"].get(difficulty, spec["presets"].get("Medium")))
            scale = spec.get("scale")
            shown = val / scale if scale else val
            if isinstance(shown, float) and shown.is_integer():
                shown = int(shown)
        return f"Goal: {CalibrationWindow._fmt_unit(shown, spec['unit'])}"

    def _game_goal_default(self, game_name, difficulty):
        """The raw integer target-reps preset for this game/difficulty, from
        the same GAME_PARAM_SCHEMA is_goal entry -- used to seed the Session
        Settings stepper (step 2b) before the therapist adjusts it, and as
        its floor/ceiling range."""
        spec = next((s for s in GAME_PARAM_SCHEMA.get(game_name, []) if s.get("is_goal")), None)
        if spec is None:
            return 10, 3, 50
        val = spec["presets"].get(difficulty, spec["presets"].get("Medium"))
        scale = spec.get("scale")
        shown = val / scale if scale else val
        shown = int(shown) if isinstance(shown, float) and shown.is_integer() else shown
        return int(shown), int(spec["min"]), int(spec["max"])

    def _launch_game(self, test_mode=False):
        import builtins
        game_name = (self.gc.get("selected_game") or (None,))[0]
        scene_key = self._GAME_SCENE_MAP.get(game_name)
        if not scene_key and not _DUAL_MONITOR:
            return None  # game not yet implemented (single-window path)
        raw_diff  = self.gc.get("difficulty", "Easy")
        game_diff = raw_diff

        # Test Mode (dev-only) only bypasses the Session Readiness Checklist
        # gate above -- the game itself launches through
        # this exact same path with the real patient_id/account_id attached,
        # so it saves, scores, and reports exactly like a normal session.
        patient_id   = (self.selected_patient or {}).get("id")
        account_id   = self.account.get("id")

        # ── Dual-monitor "START SESSION": send the config, fire START_SESSION   ──
        # ── (patient Welcome/Waiting -> How to Play; game NOT running), and     ──
        # ── navigate to the "Session in Progress" screen (panel 7). The actual  ──
        # ── game starts later, when the therapist clicks START there.           ──
        if _DUAL_MONITOR:
            # Same payload the standalone app puts in builtins.pending_game_data,
            # so the real game on the patient monitor behaves identically.
            therapist_link.configure({
                "selected_game":  game_name,
                "difficulty":     game_diff,
                "session_mode":   self.gc.get("session_mode", "target"),
                "target_reps":    self.gc.get("target_reps"),
                "duration_sec":   self.gc.get("duration_sec"),
                "speed":          self.gc.get("speed", "Normal"),
                "calibration":    self.calibration_result or {},
                # the SELECTED PATIENT's theme -- not the calibration snapshot, which
                # would clobber it at session start (set_config mirrors this
                # onto the live shared dark_mode).
                "dark_mode":      self._applied_theme_dark,
                "patient_id":     patient_id,
                "patient_name":   (self.selected_patient or {}).get("full_name", ""),
                "therapist_name": self.account.get("full_name", ""),
                "account_id":     account_id,
            })
            therapist_link.command(_rc_cmd.START_SESSION)
            self._sm_result = None
            self._sm_volume = None
            self._sm_stopped_notice = False
            self._sm_started_ms = pygame.time.get_ticks()   # START locked for the BLE handoff window
            self._open_panel(7)
            return None                      # do NOT switch this window to a game scene

        builtins.pending_game_data = {
            "account_id":   account_id,
            "account":      self.account,
            "patient":      self.selected_patient,
            "difficulty":   game_diff,
            "session_mode": self.gc.get("session_mode", "target"),
            "target_reps":  self.gc.get("target_reps"),
            "duration_sec": self.gc.get("duration_sec"),
            "speed":        self.gc.get("speed", "Normal"),
            "calibration":  self.calibration_result or {},
            "dark_mode":    self._applied_theme_dark,
        }
        # Re-set pending_account so the dashboard gets the right therapist when recreated
        builtins.pending_account = self.account
        self.action_triggered = True
        return scene_key

    # ══════════════════════════════════════════════════════════════════
    #  PANEL 7 — "SESSION IN PROGRESS"  (dual-monitor; RECOVR_DUAL_MONITOR=1)
    #
    #  A real dashboard screen (not a pop-up). ONE state-driven control button
    #  START → PAUSE → RESUME → PAUSE ... → RESTART, plus Volume; the standard
    #  dashboard Back button in the header leaves the screen (no separate Exit),
    #  plus a separate red emergency STOP at the lower-right of the interface.
    #  (START SESSION already sent the config + START_SESSION; the patient is now
    #  on How to Play. This button's START sends START_GAME -> the game runs.)
    # ══════════════════════════════════════════════════════════════════

    _SM_VOL_STEPS = [0.0, 0.25, 0.5, 0.75, 1.0]
    # Session-in-Progress control button artwork -- icon-only now (captions
    # removed); "start" also covers RESUME (same play-triangle asset).
    _SM_BTN_ASSETS = {
        "start":   "game_start.png",
        "pause":   "game_pause.png",
        "restart": "game_restart.png",
        "stop":    "game_stop.png",
    }

    def _sm_update(self, mouse_pos):
        st = therapist_link.get_state() or {}
        self._sm_state = st
        status = st.get("status", "")
        if status == _rc_cmd.COMPLETE and self._sm_result is None:
            self._sm_result = dict(st.get("result") or {}) or {"score": "-"}
        if status in (_rc_cmd.RUNNING, _rc_cmd.PAUSED):
            self._sm_result = None
        if self._sm_volume is None:
            try:
                self._sm_volume = float(st.get("volume", 0.4))
            except (TypeError, ValueError):
                self._sm_volume = 0.4
        self._sm_hover = None
        for key, (r, enabled) in self._sm_btn_rects.items():
            if enabled and r.collidepoint(mouse_pos):
                self._sm_hover = key
        if self._sm_notice_continue_rect.collidepoint(mouse_pos):
            self._sm_hover = "notice_continue"
        if self._sm_notice_back_rect.collidepoint(mouse_pos):
            self._sm_hover = "notice_back"
        if self._sm_warning_okay_rect.collidepoint(mouse_pos):
            self._sm_hover = "warning_okay"

    def _sm_primary(self, status):
        """(icon, label, command) for the single state-driven control button."""
        if status == _rc_cmd.RUNNING:
            return ("pause",  "PAUSE",   _rc_cmd.PAUSE_GAME)
        if status == _rc_cmd.PAUSED:
            return ("start",  "RESUME",  _rc_cmd.RESUME_GAME)
        if status == _rc_cmd.COMPLETE:
            return ("restart", "RESTART", _rc_cmd.RESTART_GAME)
        return ("start", "START", _rc_cmd.START_GAME)   # READY / connecting

    def _sm_leave(self):
        """Clear the session and return to Game Configuration."""
        therapist_link.reset()
        self._sm_result = None
        self._sm_volume = None
        self._sm_stopped_notice = False
        # Dev-only bypass auto-disables the moment a (possibly bypassed)
        # session ends, so the next one always starts from normal validation.
        self._test_mode_bypass = False
        self._sm_test_mode     = False
        self._open_panel(4)                 # -> Game Configuration (NOT Patient List)

    def _sm_back(self):
        """The standard dashboard Back button on panel 7: stop any active game
        and navigate to Game Configuration -- no stale session left behind."""
        st = self._sm_state or {}
        if st.get("status") in (_rc_cmd.RUNNING, _rc_cmd.PAUSED):
            therapist_link.command(_rc_cmd.STOP_GAME)
        self._sm_leave()

    def _sm_emergency_stop(self):
        """Red STOP: HOLD the game (pause it -- state preserved) and open the
        'Game Stopped' decision screen on BOTH monitors. The game is NOT
        terminated yet; the therapist still chooses CONTINUE or BACK."""
        st = self._sm_state or {}
        if st.get("status") == _rc_cmd.RUNNING:
            therapist_link.command(_rc_cmd.PAUSE_GAME)   # freeze; keep the instance
        therapist_link.set_stop_pending(True)            # -> decision state, both monitors
        self._sm_stopped_notice = True

    def _sm_continue(self):
        """CONTINUE: resume the SAME game and stay on Session in Progress.
        No teardown, no navigation."""
        self._sm_stopped_notice = False
        therapist_link.set_stop_pending(False)
        if (self._sm_state or {}).get("status") == _rc_cmd.PAUSED:
            therapist_link.command(_rc_cmd.RESUME_GAME)  # patient resumes the same game

    def _sm_end_session(self):
        """BACK: end the current game/session -- terminate + clean up, then
        therapist -> Game Configuration (patient -> Patient Dashboard / Waiting)."""
        self._sm_stopped_notice = False
        therapist_link.set_stop_pending(False)
        if (self._sm_state or {}).get("status") in (
                _rc_cmd.RUNNING, _rc_cmd.PAUSED, _rc_cmd.READY):
            therapist_link.command(_rc_cmd.STOP_GAME)
        self._sm_leave()                                 # reset() + _open_panel(4)

    def _sm_handle_click(self, pos):
        # "Game Stopped" decision screen -> CONTINUE (resume) | BACK (end session).
        if self._sm_stopped_notice:
            if self._sm_notice_continue_rect.collidepoint(pos):
                play_click(); self._sm_continue()
            elif self._sm_notice_back_rect.collidepoint(pos):
                play_click(); self._sm_end_session()
            return
        # Back warning ("a game is in progress") -- only Okay is clickable;
        # closes the pop-up and returns to the (still-running) game screen.
        if self._sm_back_warning:
            if self._sm_warning_okay_rect.collidepoint(pos):
                play_click(); self._sm_back_warning = False
            return
        # the standard dashboard Back button (drawn by _draw_panel_shell)
        if self._back_btn_rect.collidepoint(pos):
            play_click()
            self._go_back()
            return
        for key, (r, enabled) in list(self._sm_btn_rects.items()):
            if not r.collidepoint(pos) or not enabled:
                continue
            play_click()
            if key == "primary":
                _icon, _lbl, command = self._sm_primary((self._sm_state or {}).get("status", ""))
                therapist_link.command(command)
                if command == _rc_cmd.RESTART_GAME:
                    self._sm_result = None
            elif key == "stop":
                self._sm_emergency_stop()
            elif key == "volume":
                cur = self._sm_volume if self._sm_volume is not None else 0.4
                idx = min(range(len(self._SM_VOL_STEPS)),
                          key=lambda i: abs(self._SM_VOL_STEPS[i] - cur))
                self._sm_volume = self._SM_VOL_STEPS[(idx + 1) % len(self._SM_VOL_STEPS)]
                therapist_link.set_volume(self._sm_volume)
            return

    # -- draw one vector control glyph inside a button ---------------
    def _sm_icon(self, surface, kind, cx, cy, s, col):
        w = max(3, int(s * 0.30))
        if kind == "pause":
            bw = max(3, int(s * 0.34)); bh = int(s * 1.4); g = int(s * 0.34)
            pygame.draw.rect(surface, col, (cx - g - bw, cy - bh // 2, bw, bh), border_radius=3)
            pygame.draw.rect(surface, col, (cx + g,      cy - bh // 2, bw, bh), border_radius=3)
        elif kind == "start":                       # play triangle (START / RESUME)
            pygame.draw.polygon(surface, col, [
                (cx - int(s * 0.55), cy - int(s * 0.75)),
                (cx - int(s * 0.55), cy + int(s * 0.75)),
                (cx + int(s * 0.80), cy)])
        elif kind == "restart":
            import math as _m
            rr = pygame.Rect(cx - s, cy - s, 2 * s, 2 * s)
            pygame.draw.arc(surface, col, rr, _m.radians(70), _m.radians(360), w)
            ax, ay = cx + int(s * 0.34), cy - int(s * 0.94)
            pygame.draw.polygon(surface, col, [
                (ax, ay - int(s * 0.10)),
                (ax + int(s * 0.55), ay + int(s * 0.05)),
                (ax + int(s * 0.02), ay + int(s * 0.55))])
        elif kind == "volume":
            pygame.draw.polygon(surface, col, [
                (cx - int(s * 0.95), cy - int(s * 0.30)),
                (cx - int(s * 0.45), cy - int(s * 0.30)),
                (cx + int(s * 0.05), cy - int(s * 0.80)),
                (cx + int(s * 0.05), cy + int(s * 0.80)),
                (cx - int(s * 0.45), cy + int(s * 0.30)),
                (cx - int(s * 0.95), cy + int(s * 0.30))])
            vol = self._sm_volume if self._sm_volume is not None else 0.4
            arcs = int(round(vol * 3))
            if arcs == 0:
                mx = cx + int(s * 0.35)
                pygame.draw.line(surface, col, (mx, cy - int(s * 0.4)),
                                 (mx + int(s * 0.55), cy + int(s * 0.4)), w)
                pygame.draw.line(surface, col, (mx, cy + int(s * 0.4)),
                                 (mx + int(s * 0.55), cy - int(s * 0.4)), w)
            else:
                import math as _m
                for i in range(arcs):
                    rad = int(s * (0.45 + 0.42 * i))
                    ar = pygame.Rect(cx + int(s * 0.1) - rad, cy - rad, 2 * rad, 2 * rad)
                    pygame.draw.arc(surface, col, ar, _m.radians(-45), _m.radians(45), w)
        elif kind == "exit":
            x0, x1 = cx - int(s * 0.85), cx + int(s * 0.05)
            y0, y1 = cy - int(s * 0.85), cy + int(s * 0.85)
            pygame.draw.lines(surface, col, False,
                              [(x1, y0), (x0, y0), (x0, y1), (x1, y1)], w)
            pygame.draw.line(surface, col, (cx - int(s * 0.25), cy),
                             (cx + int(s * 0.85), cy), w)
            pygame.draw.polygon(surface, col, [
                (cx + int(s * 0.55), cy - int(s * 0.42)),
                (cx + int(s * 1.02), cy),
                (cx + int(s * 0.55), cy + int(s * 0.42))])
        elif kind == "stop":                        # filled square (emergency stop)
            pygame.draw.rect(surface, col, (cx - int(s * 0.7), cy - int(s * 0.7),
                                            int(s * 1.4), int(s * 1.4)), border_radius=4)

    def _sm_draw_info_header(self, surface, pa, x0, y, cfg):
        """Session In Progress's Game Session Information header -- three
        columns (Game | Patient | Difficulty) separated by thin vertical
        dividers, replacing the old plain game-name title + Patient/
        Difficulty rows with the single structured header. Returns the y
        just below it, for whatever the caller draws next (the Score row)."""
        F = self.fnt
        W, H = self.WIDTH, self.HEIGHT

        def _fit(txt, fnt, avail):
            txt = str(txt)
            if fnt.size(txt)[0] <= avail:
                return txt
            while txt and fnt.size(txt + "…")[0] > avail:
                txt = txt[:-1]
            return (txt + "…") if txt else "…"

        game_name = cfg.get("selected_game") or "Session"
        category  = GAME_CATEGORY.get(game_name, "")
        category_disp = f"{category} Exercise" if category else ""

        sel = self.selected_patient or {}
        patient_name = cfg.get("patient_name") or sel.get("full_name") or "-"
        patient_id   = sel.get("patient_id_str") or "-"
        difficulty   = cfg.get("difficulty") or "-"

        header_h = max(int(118 * H / 1080), self._tt(108))
        pad_r    = int(44 * (W / 1920))
        hdr_r    = pygame.Rect(x0, y, (pa.right - pad_r) - x0, header_h)
        inner_pad = self._sc(14)
        sec_w = hdr_r.width // 3
        s1 = pygame.Rect(hdr_r.x, hdr_r.y, sec_w, hdr_r.height)
        s2 = pygame.Rect(s1.right, hdr_r.y, sec_w, hdr_r.height)
        s3 = pygame.Rect(s2.right, hdr_r.y, hdr_r.right - s2.right, hdr_r.height)

        f_big   = F["panel_title"]
        f_bold  = F["body_b"]
        f_muted = F["small"]
        c_main, c_muted = (28, 42, 64), (130, 145, 168)

        # ── Section 1: Game name + exercise category (left-aligned) ──
        avail1 = s1.width - inner_pad
        name_s = f_big.render(_fit(game_name, f_big, avail1), True, c_main)
        cat_s  = f_muted.render(_fit(category_disp, f_muted, avail1), True, c_muted) if category_disp else None
        gap1   = self._sc(2)
        block1_h = name_s.get_height() + (gap1 + cat_s.get_height() if cat_s else 0)
        gy = s1.y + (s1.height - block1_h) // 2
        surface.blit(name_s, (s1.x, gy))
        if cat_s:
            surface.blit(cat_s, (s1.x, gy + name_s.get_height() + gap1))

        # ── Section 2: Patient label / name / ID (centered) ──
        avail2 = s2.width - inner_pad * 2
        lbl2_s  = f_muted.render("Patient", True, c_muted)
        pname_s = f_bold.render(_fit(patient_name, f_bold, avail2), True, c_main)
        pid_s   = f_muted.render(_fit(patient_id, f_muted, avail2), True, c_muted)
        gap2 = self._sc(2)
        block2_h = lbl2_s.get_height() + gap2 + pname_s.get_height() + gap2 + pid_s.get_height()
        py = s2.y + (s2.height - block2_h) // 2
        for s in (lbl2_s, pname_s, pid_s):
            surface.blit(s, s.get_rect(midtop=(s2.centerx, py)))
            py += s.get_height() + gap2

        # ── Section 3: Difficulty label + rounded badge (centered) ──
        lbl3_s = f_muted.render("Difficulty", True, c_muted)
        badge_txt = f_bold.render(_fit(difficulty, f_bold, s3.width - inner_pad * 2), True, (30, 110, 190))
        badge_pad_x, badge_pad_y = self._sc(16), self._sc(6)
        badge_r = pygame.Rect(0, 0, badge_txt.get_width() + badge_pad_x * 2,
                              badge_txt.get_height() + badge_pad_y * 2)
        gap3 = self._sc(6)
        block3_h = lbl3_s.get_height() + gap3 + badge_r.height
        dy = s3.y + (s3.height - block3_h) // 2
        surface.blit(lbl3_s, lbl3_s.get_rect(midtop=(s3.centerx, dy)))
        badge_r.midtop = (s3.centerx, dy + lbl3_s.get_height() + gap3)
        pygame.draw.rect(surface, (224, 238, 252), badge_r, border_radius=badge_r.height // 2)
        pygame.draw.rect(surface, (180, 212, 238), badge_r, 1, border_radius=badge_r.height // 2)
        surface.blit(badge_txt, badge_txt.get_rect(center=badge_r.center))

        # ── thin vertical dividers between the three sections ──
        div_col = (212, 222, 236)
        div_top, div_bot = hdr_r.y + self._sc(8), hdr_r.bottom - self._sc(8)
        for dx in (s1.right, s2.right):
            pygame.draw.line(surface, div_col, (dx, div_top), (dx, div_bot), 1)

        return hdr_r.bottom + self._sc(14)

    @staticmethod
    def _sm_fmt_mmss(seconds):
        try:
            total = max(0, int(round(float(seconds))))
        except (TypeError, ValueError):
            total = 0
        return f"{total // 60:02d}:{total % 60:02d}"

    def _sm_draw_session_cards(self, surface, pa, x0, y, row_h, elapsed_sec, score_val,
                                reps_val=None, goal_val=None, session_mode="target",
                                remaining_sec=None):
        """Time (blue) / Progress-or-Reps (purple) / Score (green) cards,
        side by side. All values come straight from the active session's own
        telemetry (the SAME reps/score the game itself is tracking, the SAME
        timer) -- this only adds the display, no independent timer/scoring/
        goal logic.

        Target Mode: "Elapsed Time" (counts up) + "Progress" (reps/goal).
        Timed Mode:  "Time Remaining" (counts down) + "Reps" (plain count,
        no goal exists in this mode). Returns the y just below the row."""
        W, H = self.WIDTH, self.HEIGHT
        pad_r = int(44 * (W / 1920))
        row_w = (pa.right - pad_r) - x0
        gap   = self._sc(14)
        is_timed = (session_mode == "timed")
        show_progress = is_timed or goal_val not in (None, "", 0)
        n_cards = 3 if show_progress else 2
        card_w = (row_w - gap * (n_cards - 1)) // n_cards

        def _clock_icon(surface, cx, cy, r, col):
            pygame.draw.circle(surface, col, (cx, cy), r, max(2, int(r * 0.14)))
            lw = max(2, int(r * 0.16))
            pygame.draw.line(surface, col, (cx, cy), (cx, cy - int(r * 0.55)), lw)
            pygame.draw.line(surface, col, (cx, cy), (cx + int(r * 0.4), cy + int(r * 0.12)), lw)

        def _trophy_icon(surface, cx, cy, r, col):
            cup = pygame.Rect(0, 0, int(r * 1.3), int(r * 1.0))
            cup.center = (cx, cy - int(r * 0.15))
            pygame.draw.rect(surface, col, cup, border_radius=int(r * 0.3))
            ear_r = max(2, int(r * 0.32))
            pygame.draw.circle(surface, col, (cup.left, cup.centery - int(r*0.1)), ear_r, max(2, int(r*0.12)))
            pygame.draw.circle(surface, col, (cup.right, cup.centery - int(r*0.1)), ear_r, max(2, int(r*0.12)))
            stem = pygame.Rect(0, 0, max(2, int(r * 0.22)), int(r * 0.4))
            stem.midtop = (cx, cup.bottom - 1)
            pygame.draw.rect(surface, col, stem)
            base = pygame.Rect(0, 0, int(r * 0.9), max(2, int(r * 0.18)))
            base.midtop = (cx, stem.bottom - 1)
            pygame.draw.rect(surface, col, base, border_radius=int(r * 0.08))

        def _target_icon(surface, cx, cy, r, col):
            pygame.draw.circle(surface, col, (cx, cy), r, max(2, int(r * 0.14)))
            pygame.draw.circle(surface, col, (cx, cy), int(r * 0.62), max(2, int(r * 0.12)))
            pygame.draw.circle(surface, col, (cx, cy), int(r * 0.24))

        def _card(cx0, bg, border, icon_bg, icon_col, icon_fn, label, value_txt):
            r = pygame.Rect(cx0, y, card_w, row_h)
            pygame.draw.rect(surface, bg, r, border_radius=14)
            pygame.draw.rect(surface, border, r, 1, border_radius=14)

            # Icon sits in its own rounded-square chip (a clearly more
            # saturated tint than the card itself) -- a fixed, comfortable
            # size rather than one that grows with the card, so the chip
            # stays proportionate instead of ballooning on a roomy screen.
            sq = min(self._sc(40), row_h - self._sc(16))
            sq_r = pygame.Rect(0, 0, sq, sq)
            sq_r.x = r.x + self._sc(14)
            sq_r.centery = r.centery
            pygame.draw.rect(surface, icon_bg, sq_r, border_radius=int(sq * 0.26))
            icon_fn(surface, sq_r.centerx, sq_r.centery, int(sq * 0.32), icon_col)

            tx = sq_r.right + self._sc(14)
            avail_w = r.right - self._sc(12) - tx

            f_lbl = self.fnt["small"]
            f_val = self.fnt["panel_title"]
            lbl_s = f_lbl.render(label, True, (90, 105, 128))
            val_s = f_val.render(value_txt, True, (30, 42, 62))

            # Render at the font's own natural size -- prominent but not
            # inflated -- and only ever SHRINK (never grow) if the card ends
            # up too small to hold it; then vertically center the stack.
            gap_v = self._sc(2)
            target_h = max(1, row_h - self._sc(14))
            natural_h = lbl_s.get_height() + gap_v + val_s.get_height()
            scale = min(1.0, target_h / natural_h,
                       avail_w / max(1, max(val_s.get_width(), lbl_s.get_width())))
            if scale < 0.97:
                lbl_s = pygame.transform.smoothscale(
                    lbl_s, (max(1, int(lbl_s.get_width()*scale)), max(1, int(lbl_s.get_height()*scale))))
                val_s = pygame.transform.smoothscale(
                    val_s, (max(1, int(val_s.get_width()*scale)), max(1, int(val_s.get_height()*scale))))
            stack_h = lbl_s.get_height() + gap_v + val_s.get_height()
            sy = r.centery - stack_h // 2
            surface.blit(lbl_s, (tx, sy))
            surface.blit(val_s, (tx, sy + lbl_s.get_height() + gap_v))

        if is_timed:
            time_lbl, time_val = "Time Remaining", self._sm_fmt_mmss(remaining_sec or 0)
        else:
            time_lbl, time_val = "Elapsed Time", self._sm_fmt_mmss(elapsed_sec)
        _card(x0, (228, 240, 253), (196, 220, 244), (205, 228, 250), (35, 110, 190), _clock_icon,
              time_lbl, time_val)
        if show_progress:
            mid_lbl = "Reps" if is_timed else "Progress"
            mid_val = str(reps_val or 0) if is_timed else f"{reps_val or 0}/{goal_val}"
            _card(x0 + card_w + gap, (238, 231, 252), (213, 199, 243), (225, 213, 249), (120, 70, 200),
                  _target_icon, mid_lbl, mid_val)
            _card(x0 + 2 * (card_w + gap), (226, 247, 233), (188, 228, 202), (203, 240, 217), (30, 150, 90),
                  _trophy_icon, "Score", str(score_val))
        else:
            _card(x0 + card_w + gap, (226, 247, 233), (188, 228, 202), (203, 240, 217), (30, 150, 90),
                  _trophy_icon, "Score", str(score_val))

        return y + row_h + self._sc(10)

    def _sm_draw_sensor_monitor(self, surface, pa, x0, y, box_h, sensor_spec, sensors_tel,
                                 active_label=None):
        """Adaptive Raw Sensor Input / Calibrated Game Input container --
        shows exactly the sensor(s) GAME_SENSOR_SPEC says the active game
        uses (1 for single-skill, 2+ for dual/triple-skill), paired row for
        row between the two columns. Values come straight from telemetry's
        "sensors" dict (posted by the patient-side adapter, computed by each
        game's OWN existing _normalize*/_normalize_tilt method) -- no second
        calibration calculation is performed here, except the Pressed/Idle
        read for finger-flexion games, which reuses the SAME FLEX_THRESH
        constant the sensor pipeline itself fires lane presses on."""
        W, H = self.WIDTH, self.HEIGHT
        pad_r = int(44 * (W / 1920))
        box_w = (pa.right - pad_r) - x0
        box_r = pygame.Rect(x0, y, box_w, box_h)
        pygame.draw.rect(surface, (250, 251, 253), box_r, border_radius=14)
        pygame.draw.rect(surface, (222, 230, 242), box_r, 1, border_radius=14)

        mid_x = box_r.centerx
        pygame.draw.line(surface, (222, 230, 242), (mid_x, box_r.y + self._sc(6)),
                         (mid_x, box_r.bottom - self._sc(6)), 1)

        inner_pad = self._sc(10)
        col_w = box_r.width // 2
        left_x  = box_r.x + inner_pad
        right_x = mid_x + inner_pad
        max_w   = col_w - inner_pad - self._sc(6)

        # Render header + one row per sensor at their natural (readable) base
        # size first, THEN see whether the whole stack fits the box this
        # game's sensor count was given. The box itself is already sized to
        # its content by the caller (not stretched to fill leftover screen
        # space), so this only ever needs to SHRINK -- on the tightest
        # touch-panel case (3 sensors) -- never grow past natural size.
        f_hdr = self.fnt["small"]
        f_row = self.fnt["label"]
        gap_row = self._sc(4)
        hdr_l = f_hdr.render("Raw Sensor Input", True, (46, 110, 180))
        hdr_r = f_hdr.render("Calibrated Game Input", True, (46, 110, 180))
        rows = []
        for key, label, _hw, fmt in sensor_spec:
            entry = sensors_tel.get(key)
            raw = entry.get("raw") if entry else None
            cal = entry.get("calibrated") if entry else None
            raw_txt, cal_txt = self._sm_fmt_sensor(raw, cal, fmt)
            # Whack-a-Mole: bold + accent-colored row for whichever
            # finger the active mole currently requires, so the therapist
            # can tell at a glance which reading matters right now among
            # the 5 always-live channels. Every other game leaves
            # active_label None and this is identical to before.
            is_active = active_label is not None and label == active_label
            row_col = (30, 150, 80) if is_active else (40, 55, 75)
            prefix  = "> " if is_active else ""
            rows.append((f_row.render(f"{prefix}{label}: {raw_txt}", True, row_col),
                        f_row.render(f"{prefix}{label}: {cal_txt}", True, row_col)))

        pad_v = self._sc(12)
        hdr_gap = self._sc(6)
        natural_h = (hdr_l.get_height() + hdr_gap
                    + sum(r[0].get_height() + gap_row for r in rows))
        avail_h = max(1, box_h - pad_v * 2)
        # Shrink-only: the box is already sized to fit this content, so
        # vscale is 1.0 in the normal case and only drops below 1 on the
        # tightest touch-panel / multi-sensor combinations.
        vscale = min(1.0, avail_h / natural_h) if natural_h > 0 else 1.0
        if vscale < 0.97:
            def _shr(s):
                return pygame.transform.smoothscale(
                    s, (max(1, int(s.get_width()*vscale)), max(1, int(s.get_height()*vscale))))
            hdr_l, hdr_r = _shr(hdr_l), _shr(hdr_r)
            rows = [(_shr(rs), _shr(cs)) for rs, cs in rows]
            hdr_gap, gap_row = int(hdr_gap*vscale), int(gap_row*vscale)

        def _fit_w(s):
            if s.get_width() > max_w and max_w > 0:
                sc_ = max_w / s.get_width()
                return pygame.transform.smoothscale(
                    s, (max(1, int(s.get_width()*sc_)), max(1, int(s.get_height()*sc_))))
            return s

        content_h = hdr_l.get_height() + hdr_gap + sum(r[0].get_height() + gap_row for r in rows)
        ry = box_r.y + max(pad_v, (box_h - content_h) // 2)
        surface.blit(_fit_w(hdr_l), (left_x, ry))
        surface.blit(_fit_w(hdr_r), (right_x, ry))
        ry += hdr_l.get_height() + hdr_gap
        for rs, cs in rows:
            surface.blit(_fit_w(rs), (left_x, ry))
            surface.blit(_fit_w(cs), (right_x, ry))
            ry += rs.get_height() + gap_row

    @staticmethod
    def _sm_fmt_sensor(raw, cal, fmt):
        """(raw_text, calibrated_text) for one sensor row. `raw`/`cal` are the
        normalised floats already computed by the real sensor pipeline (see
        _sensor_telemetry in recovr/patient_app/games/generic_adapter.py) --
        this only formats them for display, it does not recompute them."""
        def pct(v):
            return "—" if v is None else f"{round(float(v) * 100)}"
        def pct_signed(v):
            if v is None:
                return "—"
            n = round(float(v) * 100)
            return f"{'+' if n > 0 else ''}{n}"

        if raw is None:
            return "—", "—"
        if fmt == "pct":
            return pct(raw), pct(cal)
        if fmt == "pct_signed":
            return pct_signed(raw), pct_signed(cal)
        if fmt == "deg":
            raw_txt = pct_signed(raw)
            cal_txt = "—" if cal is None else f"{round(float(cal))}°"
            return raw_txt, cal_txt
        if fmt == "flex":
            raw_txt = pct(raw)
            if cal is None:
                cal = 1.0 if float(raw) > input_handler.FLEX_THRESH else 0.0
            cal_txt = "Pressed" if float(cal) > 0.5 else "Idle"
            return raw_txt, cal_txt
        return pct(raw), pct(cal)

    def _sm_draw(self, surface, pa):
        """Panel-7 drawer: (surface, panel-area rect). Also draws the separate
        emergency STOP button at the lower-right of the whole interface."""
        F = self.fnt
        W, H = self.WIDTH, self.HEIGHT
        st  = self._sm_state or {}
        status = st.get("status", "connecting")
        tel = st.get("telemetry") or {}
        cfg = st.get("config") or {}

        sm_test_mode = getattr(self, "_sm_test_mode", False)
        # Dev-only: a red card border costs no extra layout space at all
        # (800x480 has none to spare here), so it's the PRIMARY always-safe
        # Test Mode cue; a small "TEST" chip adds a second, textual one using
        # the least height that still reads clearly. This session was
        # launched via the Test Mode bypass -- no real patient/therapist id
        # was attached to it (see _launch_game), so nothing about it gets
        # saved as a real rehabilitation session.
        _card_bg(surface, pa, alpha=140, radius=16,
                 border_col=(205, 55, 50) if sm_test_mode else (200, 218, 240),
                 border_w=2 if sm_test_mode else 1)
        pad = int(44 * (W / 1920))
        x0  = pa.x + pad
        y   = pa.y + pad

        if sm_test_mode:
            # 800x480 has no vertical budget to spare below this (the
            # sensor-monitor box already sizes itself down to a hard floor
            # on this screen) -- so the tag sits ON the card's own top
            # border, like a flag, instead of reserving a row of its own.
            # `y` is deliberately left untouched.
            tb_s = self.fnt["eyebrow"].render("TEST MODE", True, (255, 255, 255))
            tb_r = pygame.Rect(0, 0, tb_s.get_width() + self._sc(12), tb_s.get_height() + self._sc(4))
            tb_r.center = (pa.right - self._sc(10) - tb_r.width // 2, pa.y)
            pygame.draw.rect(surface, (205, 55, 50), tb_r, border_radius=self._sc(5))
            surface.blit(tb_s, tb_s.get_rect(center=tb_r.center))

        y = self._sm_draw_info_header(surface, pa, x0, y, cfg)

        # Elapsed Time / Score cards, then the adaptive Raw/Calibrated sensor
        # monitor -- both come from the SAME telemetry the old single "Score"
        # row already used (no second timer/scoring system); once the session
        # completes, Score falls back to the final recorded value so the
        # number doesn't disappear the moment the game ends.
        score_val = tel.get("score")
        if score_val in (None, ""):
            score_val = (self._sm_result or {}).get("score", "-")
        elapsed_val = tel.get("elapsed_sec")
        if elapsed_val in (None, ""):
            elapsed_val = (self._sm_result or {}).get("duration_sec", 0)
        reps_val = tel.get("reps")
        if reps_val in (None, ""):
            reps_val = (self._sm_result or {}).get("reps")
        goal_val = tel.get("goal")
        if goal_val in (None, ""):
            goal_val = (self._sm_result or {}).get("goal")
        session_mode = tel.get("session_mode") or cfg.get("session_mode") \
            or (self._sm_result or {}).get("session_mode", "target")
        remaining_val = tel.get("remaining_sec")
        if remaining_val in (None, ""):
            remaining_val = (self._sm_result or {}).get("configured_duration_seconds")

        # How much vertical room is actually left before the control row, so
        # the cards + sensor monitor always size themselves to fit -- critical
        # on the 800x480 touch panel where this screen is tightest.
        bs  = max(int(108 * (H / 1080)), self._tt(104))
        brow_y = pa.y + pa.height - bs - int(64 * (H / 1080))
        avail_bottom_h = max(self._sc(60), brow_y - y - self._sc(10))

        game_name   = cfg.get("selected_game") or ""
        sensor_spec = GAME_SENSOR_SPEC.get(game_name, [])
        sensors_tel = tel.get("sensors") or {}

        # Both the cards row and the sensor box are sized from their OWN
        # content (icon/text at natural size + fixed padding), never
        # stretched to consume whatever vertical room happens to be left --
        # that's what previously produced a mostly-empty container on a
        # roomy screen. Leftover space (if any) is left as plain margin
        # above the control row instead of being poured into either box.
        gap_mid = self._sc(10)
        lbl_h, val_h, row_fh = (self.fnt["small"].get_height(),
                                self.fnt["panel_title"].get_height(),
                                self.fnt["label"].get_height())
        cards_content_h = lbl_h + self._sc(2) + val_h
        cards_h = max(self._sc(64), min(self._sc(104), cards_content_h + self._sc(18)))

        if sensor_spec:
            n_rows = len(sensor_spec)
            sensor_content_h = lbl_h + self._sc(6) + n_rows * (row_fh + self._sc(4))
            sensor_h = sensor_content_h + self._sc(24)
        else:
            sensor_h = 0

        total_needed = cards_h + (gap_mid + sensor_h if sensor_spec else 0)
        if total_needed > avail_bottom_h:
            # Tightest touch-panel case (e.g. a 3-sensor game on 800x480):
            # shrink both proportionally rather than overlapping the
            # control row; each box's own renderer shrinks its text to fit
            # whatever height it is actually given.
            shrink = max(0.3, avail_bottom_h / max(1, total_needed))
            cards_h = max(self._sc(40), int(cards_h * shrink))
            if sensor_spec:
                sensor_h = max(self._sc(28), avail_bottom_h - cards_h - gap_mid)
            else:
                cards_h = avail_bottom_h

        y = self._sm_draw_session_cards(surface, pa, x0, y, cards_h, elapsed_val, score_val,
                                         reps_val, goal_val, session_mode, remaining_val)
        if sensor_spec:
            self._sm_draw_sensor_monitor(surface, pa, x0, y, sensor_h, sensor_spec, sensors_tel,
                                          active_label=tel.get("required_finger"))

        # ── control row: [ primary(START/PAUSE/RESUME/RESTART) ] [ STOP ] [ VOLUME ] ──
        # Icon-only now (word captions removed); STOP used to be a separate
        # wide red button anchored to the lower-right corner of the whole
        # interface -- it now lives in this same row, right after primary.
        # (EXIT removed -- use the standard dashboard Back button in the header)
        gap = int(34 * (W / 1920))
        p_icon, _p_label, _p_cmd = self._sm_primary(status)
        # The initial START is held for a few seconds after "Start Session" so the
        # BLE controller can move from this process to the patient process before
        # the game runs. RESUME / RESTART / PAUSE are never locked.
        lock_ms_left = self._sm_start_lock_ms - (pygame.time.get_ticks() - self._sm_started_ms)
        primary_locked = (
            _p_cmd == _rc_cmd.START_GAME
            and status in (_rc_cmd.READY, _rc_cmd.IDLE, "connecting")
            and lock_ms_left > 0
        )
        specs = [
            ("primary", p_icon,   not primary_locked),
            ("stop",    "stop",   True),
            ("volume",  "volume", True),
        ]
        total = bs * len(specs) + gap * (len(specs) - 1)
        bx = pa.x + (pa.width - total) // 2
        brow_y = pa.y + pa.height - bs - int(64 * (H / 1080))
        self._sm_btn_rects = {}
        for key, icon, enabled in specs:
            r = pygame.Rect(bx, brow_y, bs, bs)
            self._sm_btn_rects[key] = (r, bool(enabled))
            hovered = self._sm_hover == key and enabled
            asset = self._SM_BTN_ASSETS.get(icon)
            img = _img(asset, bs) if asset else None
            if img is not None:
                if not enabled:
                    img = img.copy()
                    img.set_alpha(120)
                surface.blit(img, r.topleft)
            else:
                # volume has no asset -- a circular badge + the vector glyph,
                # kept round to match the two image buttons beside it
                if hovered:
                    fill, ic = (223, 235, 249), (30, 48, 78)
                else:
                    fill, ic = (236, 242, 250), (36, 54, 86)
                pygame.draw.circle(surface, fill, r.center, bs // 2)
                pygame.draw.circle(surface, (95, 145, 212), r.center, bs // 2, 2)
                self._sm_icon(surface, icon, r.centerx, r.centery, int(bs * 0.28), ic)
            if key == "primary" and primary_locked:
                # BLE handoff countdown -- a numeric overlay, not a word
                # caption, so it stays even with the labels removed.
                lock_s = str(lock_ms_left // 1000 + 1)
                dim = pygame.Surface((bs, bs), pygame.SRCALPHA)
                pygame.draw.circle(dim, (20, 26, 38, 150), (bs // 2, bs // 2), bs // 2)
                surface.blit(dim, r.topleft)
                ls = F["panel_title"].render(lock_s, True, (255, 255, 255))
                surface.blit(ls, ls.get_rect(center=r.center))
            bx += bs + gap

        # ── "Game Stopped" screen (both monitors show this) ──
        if self._sm_stopped_notice:
            self._sm_draw_stopped_notice(surface)
        else:
            self._sm_notice_continue_rect = pygame.Rect(0, 0, 1, 1)
            self._sm_notice_back_rect     = pygame.Rect(0, 0, 1, 1)

        # ── Back-button warning: a game is RUNNING/PAUSED, Back was clicked ──
        if self._sm_back_warning:
            self._sm_draw_back_warning(surface)
        else:
            self._sm_warning_okay_rect = pygame.Rect(0, 0, 1, 1)

    def _sm_draw_stopped_notice(self, surface):
        """The 'Game Stopped' decision screen: Continue resumes the same
        game; End Session ends it -> Game Configuration / Patient
        Dashboard. "End Session" is the destructive choice (ends the
        session for good) so it gets the red "Stop Session" accent/confirm
        slot; Continue -- the safe default -- is the neutral/cancel slot.
        Same left=Continue / right=End Session layout as before, just
        restyled through the standardized dialog."""
        back_r, cont_r = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="stop", accent=(214, 48, 44),
            title="Session Stopped",
            body="Continue resumes the current game, or end the session "
                 "and return to Game Configuration.",
            confirm_label="End Session", cancel_label="Continue",
            confirm_hov=(self._sm_hover == "notice_back"),
            cancel_hov=(self._sm_hover == "notice_continue"))
        self._sm_notice_back_rect, self._sm_notice_continue_rect = back_r, cont_r

    def _sm_draw_back_warning(self, surface):
        """Back was clicked while a game is RUNNING/PAUSED -- block navigation
        and tell the therapist to stop the game first. Informational only (not
        an error state like 'Game Stopped'), so it uses the brand blue accent
        and a single OKAY button that just closes the pop-up; the game behind
        it keeps running untouched."""
        cr, _ = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="info", accent=(60, 140, 220),
            title="Game Session in Progress",
            body="A game is currently in progress. Please stop the game or "
                 "wait until the session finishes before going back.",
            confirm_label="Okay", single_button=True,
            confirm_hov=(self._sm_hover == "warning_okay"))
        self._sm_warning_okay_rect = cr


    # ──────────────────────────────────────────────────────────────────
    #  SHARE MODAL HELPERS
    # ──────────────────────────────────────────────────────────────────

    def _open_share_modal(self, patient):
        self.share_modal_patient      = patient
        self._share_modal_open        = True
        self._share_input             = ""
        self._share_error             = ""
        self._share_success           = ""
        self._share_results           = []
        self._unshare_rects           = []
        self._share_suggestions       = []
        self._share_sugg_rects        = []
        self._share_confirm_therapist = None
        self._share_stage             = "pick"
        self._share_pending_action    = None
        self._share_shared_scroll     = 0
        self._share_shared_drag_y     = None

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PATIENT MODAL — helpers
    # ──────────────────────────────────────────────────────────────────

    def _open_ep_modal(self, patient, section=None):
        """Open the edit-patient modal. `section` limits it to one Info group
        ("info" / "stroke" / "notes"); None edits every field (legacy path).

        Refuses outright for a non-owner -- a shared patient is read-only."""
        if not self._is_owner(patient):
            return
        self._ep_patient     = patient
        self._ep_section     = section
        self._ep_modal_open  = True
        self._ep_confirm_del = False
        self._ep_error       = ""
        self._ep_success     = ""
        self._ep_active_key  = None
        self._ep_drop_open   = {k: False for k in
                                ["sex","dominant_hand","affected_hand","stroke_type"]}
        self._ep_drop_rects  = {}
        self._ep = {k: str(patient.get(k, "") or "")
                    for k in ["full_name","age","sex","dominant_hand","affected_hand",
                               "stroke_type","date_of_stroke","months_stroke",
                               "notes_stiffness","notes_pain","notes_therapist"]}

    def _ep_fields(self):
        """(key, label, kind, opts) for the fields this modal is editing."""
        SPEC = {
            "full_name":       ("Full Name",            "text", None),
            "age":             ("Age",                  "text", None),
            "sex":             ("Sex",                  "drop", SEX_OPTS),
            "stroke_type":     ("Stroke Type",          "drop", STROKE_TYPES),
            "date_of_stroke":  ("Stroke Onset Date",    "text", None),
            "months_stroke":   ("Months Since Stroke",  "text", None),
            "dominant_hand":   ("Dominant Hand",        "drop", HAND_OPTS),
            "affected_hand":   ("Affected Hand",        "drop", HAND_OPTS),
            "notes_stiffness": ("Muscle Stiffness",     "text", None),
            "notes_pain":      ("Pain Level",           "text", None),
            "notes_therapist": ("Therapist Comments",   "text", None),
        }
        # A single "edit everything at once" view is no longer part of this
        # UI (it's 3 section-scoped edits now) and its 11 fields do not fit
        # the 800x480 modal budget. An invalid/missing section defaults to
        # "info" -- the smallest, always-present section -- rather than
        # silently falling back to the old all-fields layout.
        sec = getattr(self, "_ep_section", None)
        if sec not in self._PV_SECTIONS:
            sec = "info"
        keys = self._PV_SECTIONS[sec][1]
        return [(k,) + SPEC[k] for k in keys if k in SPEC]

    def _ep_title(self):
        sec = getattr(self, "_ep_section", None)
        if sec and sec in self._PV_SECTIONS:
            return f"Edit {self._PV_SECTIONS[sec][0]}"
        return "Edit Patient"

    def _ep_handle_click(self, pos):
        W, H = self.WIDTH, self.HEIGHT
        if self._ep_cancel_rect.collidepoint(pos):
            play_click()
            self._ep_modal_open = False; return
        if self._ep_save_rect.collidepoint(pos):
            play_click()
            err = self._ep_validate()
            if err:
                self._ep_error = err
            else:
                self._ep_error = ""
                self.modal = "save_patient_confirm"
            return
        if self._ep_delete_rect.collidepoint(pos):
            play_confirm_alert()
            self.modal = "delete_patient_confirm"
            self._danger_countdown = 5.0
            return

        # Dropdown option selection
        for key, is_open in list(self._ep_drop_open.items()):
            if is_open:
                info = self._ep_drop_rects.get(key)
                if info:
                    _, opt_rects, opts = info
                    for or_, opt_val in zip(opt_rects, opts):
                        if or_.collidepoint(pos):
                            play_click()
                            self._ep[key] = opt_val
                            self._ep_drop_open[key] = False
                            return
                self._ep_drop_open[key] = False
                return

        # Dropdown toggle
        drop_fields = {
            "sex": SEX_OPTS, "dominant_hand": HAND_OPTS,
            "affected_hand": HAND_OPTS, "stroke_type": STROKE_TYPES,
        }
        for key, opts in drop_fields.items():
            info = self._ep_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                play_click()
                for k in self._ep_drop_open: self._ep_drop_open[k] = False
                self._ep_drop_open[key] = True
                return

        # Text field focus
        for key in ["full_name","age","date_of_stroke","months_stroke",
                     "notes_stiffness","notes_pain","notes_therapist"]:
            info = self._ep_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                self._ep_active_key = key; return
        self._ep_active_key = None

    def _ep_keydown(self, event):
        if event.key == pygame.K_ESCAPE:
            if self._ep_active_key:
                self._ep_active_key = None
            else:
                self._ep_modal_open = False
            return
        if event.key == pygame.K_RETURN:
            self._ep_active_key = None; return
        key = self._ep_active_key
        if not key: return
        if event.key == pygame.K_BACKSPACE:
            self._ep[key] = self._ep[key][:-1]; self._ep_error = ""
        elif event.unicode:
            if key == "age" and (not event.unicode.isdigit() or len(self._ep[key]) >= 3):
                return
            self._ep[key] += event.unicode; self._ep_error = ""

    def _ep_validate(self):
        """Returns an error message, or None if the Edit Patient fields are
        valid -- checked both before opening the Save confirmation dialog
        and again inside _ep_submit() itself (cheap, side-effect-free)."""
        ep = self._ep
        if not ep["full_name"].strip():
            return "Full Name is required."
        if ep["age"] and not ep["age"].isdigit():
            return "Age must be a number."
        return None

    def _ep_submit(self):
        ep = self._ep
        err = self._ep_validate()
        if err:
            self._ep_error = err; return
        # The edit modal only ever opens for the owner (_open_ep_modal refuses
        # otherwise), but the write is ownership-checked here too -- a shared
        # (non-owner) therapist must never be able to edit patient info, even
        # if that UI gate were ever bypassed.
        ok = self.db.update_patient(self._ep_patient["id"], ep,
                                    acting_therapist_id=self.account["id"])
        if not ok:
            self._ep_error = "You no longer own this patient."
            return
        # Refresh patient name if selected
        if self.selected_patient and self.selected_patient["id"] == self._ep_patient["id"]:
            self.selected_patient["full_name"] = ep["full_name"].strip()
            self._push_selected_patient()
        self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                         if hasattr(self.db, "get_all_patients") else [])
        self._ep_success = "Patient updated successfully."
        self._ep_error   = ""

    def _ep_delete(self):
        pid = self._ep_patient["id"]
        ok = self.db.delete_patient(pid, acting_therapist_id=self.account["id"])
        if not ok:
            self._ep_error = "You no longer own this patient."
            self.modal = None
            return
        if self.selected_patient and self.selected_patient.get("id") == pid:
            self._set_selected_patient(None)
        self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                         if hasattr(self.db, "get_all_patients") else [])
        self._ep_modal_open = False

    def _draw_edit_patient_modal(self, surface):
        """Section-scoped patient editor, sized from _fs/_tt so the controls stay
        finger-sized on the 800x480 panel (the old layout computed everything
        from H/1080 and produced 18px boxes here)."""
        W, H = self.WIDTH, self.HEIGHT
        fields  = self._ep_fields()
        two_col = len(fields) > 3
        pad     = self._sc(18)
        fh      = self._tt(46)
        lbl_h   = self.fnt["small"].get_height()
        row_h   = lbl_h + self._sc(4) + fh + self._sc(14)
        rows    = (len(fields) + 1) // 2 if two_col else len(fields)
        btn_h   = self._tt(46)

        head_h  = self.fnt["panel_title"].get_height() + self._sc(14)
        mw = min(int(W * 0.86), self._sc(700))
        mh = min(int(H * 0.92),
                 head_h + rows * row_h + btn_h + pad * 3 + self.fnt["modal_err"].get_height())
        mx = (W - mw) // 2;  my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (228, 238, 252, 252), (0, 0, mw, mh), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), mr, 1, border_radius=16)

        # Title -- names the section being edited
        surface.blit(self.fnt["panel_title"].render(self._ep_title(), True, (38, 52, 78)),
                     (mr.x + pad, mr.y + self._sc(10)))
        hl_y = mr.y + head_h
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + pad, hl_y), (mr.right - pad, hl_y), 1)

        colgap = self._sc(14)
        fw  = (mw - 2 * pad - colgap) // 2 if two_col else (mw - 2 * pad)
        fy0 = hl_y + self._sc(12)
        self._ep_drop_rects = {}

        def _draw_ep_field(key, lbl, kind, opts, idx):
            col = idx % 2 if two_col else 0
            row = idx // 2 if two_col else idx
            fx  = mr.x + pad + col * (fw + colgap)
            fy  = fy0 + row * row_h + lbl_h + self._sc(4)
            fr  = pygame.Rect(fx, fy, fw, fh)
            self._ep_drop_rects[key] = (fr, [], opts or [])

            active = (self._ep_active_key == key)
            surface.blit(self.fnt["small"].render(lbl, True, (70, 88, 112)),
                         (fx, fy - lbl_h - self._sc(4)))
            pygame.draw.rect(surface, (250, 252, 255), fr, border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220) if active else (180, 205, 232),
                             fr, 2 if active else 1, border_radius=9)

            val = self._ep.get(key, "")
            if kind == "drop":
                disp = val or "Select"
                ts = self.fnt["input"].render(disp, True,
                                              (40, 50, 65) if val else (170, 185, 205))
                surface.blit(ts, ts.get_rect(midleft=(fr.x + self._sc(12), fr.centery)))
                chev = self.fnt["sym26"].render("▼", True, (90, 110, 140))
                surface.blit(chev, chev.get_rect(midright=(fr.right - self._sc(12), fr.centery)))
            else:
                ph = "Optional" if key.startswith("notes_") else ""
                ts = (self.fnt["input"].render(val, True, (40, 50, 65)) if val
                      else self.fnt["input"].render(ph, True, (185, 198, 215)))
                surface.blit(ts, ts.get_rect(midleft=(fr.x + self._sc(12), fr.centery)))
                if active and val:
                    cx2 = fr.x + self._sc(12) + ts.get_width() + 2
                    pygame.draw.line(surface, (40, 160, 220),
                                     (cx2, fr.centery - self._sc(10)),
                                     (cx2, fr.centery + self._sc(10)), 2)

        for i, (key, lbl, kind, opts) in enumerate(fields):
            _draw_ep_field(key, lbl, kind, opts, i)

        # Buttons -- Delete lives on the Patient Information section only.
        btn_y = mr.bottom - btn_h - pad
        bw    = self._sc(120)
        self._ep_save_rect   = pygame.Rect(mr.right - pad - bw, btn_y, bw, btn_h)
        self._ep_cancel_rect = pygame.Rect(self._ep_save_rect.x - self._sc(10) - bw,
                                           btn_y, bw, btn_h)
        if getattr(self, "_ep_section", None) in (None, "info"):
            dw = self.fnt["small"].size("Delete Patient")[0] + self._sc(24)
            self._ep_delete_rect = pygame.Rect(mr.x + pad, btn_y, dw, btn_h)
        else:
            self._ep_delete_rect = pygame.Rect(0, 0, 1, 1)

        msg = self._ep_error or self._ep_success
        if msg:
            mc = (210, 50, 50) if self._ep_error else (50, 175, 75)
            surface.blit(self.fnt["modal_err"].render(msg, True, mc),
                         (mr.x + pad, btn_y - self.fnt["modal_err"].get_height() - self._sc(4)))

        btns = [(self._ep_save_rect,   (40,160,220), (25,125,180), self._ep_save_hov,   "Save",   self.fnt["btn"]),
                (self._ep_cancel_rect, (160,175,195),(130,145,165),self._ep_cancel_hov, "Cancel", self.fnt["btn"])]
        if self._ep_delete_rect.width > 1:
            btns.append((self._ep_delete_rect, (200,50,50), (165,28,28),
                         self._ep_delete_hov, "Delete Patient", self.fnt["small"]))
        for rect, cn, ch, hov, lbl, fnt in btns:
            pygame.draw.rect(surface, ch if hov else cn, rect, border_radius=10)
            s = fnt.render(lbl, True, (255, 255, 255))
            surface.blit(s, s.get_rect(center=rect.center))

        # Open dropdown last so it paints over the fields; flips upward when it
        # would fall off the bottom of the modal.
        for key, (fr, _r, opts) in list(self._ep_drop_rects.items()):
            if not self._ep_drop_open.get(key) or not opts:
                continue
            opt_h = self._tt(42)
            lst_h = len(opts) * opt_h + 4
            base  = fr.top - lst_h if fr.bottom + lst_h > mr.bottom else fr.bottom
            pygame.draw.rect(surface, (244, 250, 255),
                             pygame.Rect(fr.x, base, fr.width, lst_h), border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220),
                             pygame.Rect(fr.x, base, fr.width, lst_h), 2, border_radius=9)
            opt_rects, mp = [], pygame.mouse.get_pos()
            for j, ov in enumerate(opts):
                orr = pygame.Rect(fr.x, base + j * opt_h, fr.width, opt_h)
                if orr.collidepoint(mp):
                    pygame.draw.rect(surface, (214, 234, 255), orr, border_radius=7)
                ts2 = self.fnt["input"].render(ov, True, (40, 50, 65))
                surface.blit(ts2, ts2.get_rect(midleft=(orr.x + self._sc(12), orr.centery)))
                opt_rects.append(orr)
            self._ep_drop_rects[key] = (fr, opt_rects, opts)

    def _handle_share_key(self, event):
        if event.key == pygame.K_ESCAPE:
            if self._share_stage == "confirm":
                self._share_stage = "choice"           # back one step
            elif self._share_stage == "choice":
                self._share_stage             = "pick"
                self._share_confirm_therapist = None
            else:
                self._share_modal_open = False
            return None
        if self._share_stage != "pick":
            return None  # swallow all other keys once past the picker
        if event.key == pygame.K_BACKSPACE:
            self._share_input   = self._share_input[:-1]
            self._share_error   = ""
            self._share_success = ""
            self._live_share_search()
        elif event.unicode and len(self._share_input) < MAX_USERNAME_LEN:
            if username_char_allowed(event.unicode):
                self._share_input  += event.unicode
                self._share_error  = ""
                self._share_success = ""
                self._live_share_search()
        return None

    def _live_share_search(self):
        prefix = self._share_input.strip()
        if not prefix:
            self._share_suggestions = []; return
        results = self.db.search_therapists_by_prefix(prefix, self.account["id"])
        if self.share_modal_patient:
            already = {t["id"] for t in
                       self.db.get_shared_therapists(self.share_modal_patient["id"])}
            results = [t for t in results if t["id"] not in already]
        self._share_suggestions = results[:3]

    def _do_share_search(self):
        self._share_error   = ""
        self._share_success = ""
        self._share_results = []
        uname = self._share_input.strip()
        if not uname:
            self._share_error = "Enter a username to search."; return
        if uname == self.account["username"]:
            self._share_error = "That's your own account."; return
        t = self.db.get_therapist_by_username(uname)
        if not t:
            self._share_error = f"No therapist found: '{uname}'."; return
        if self.share_modal_patient:
            already = self.db.get_shared_therapists(self.share_modal_patient["id"])
            if any(a["id"] == t["id"] for a in already):
                self._share_error = f"Already shared with {t['full_name']}."; return
        self._share_results = [t]

    def _do_share_or_transfer_confirm(self):
        """Final Yes on the confirm screen. SHARE and TRANSFER are genuinely
        different operations at the data layer, not two flavours of the same
        call: share_patient() only ever inserts a patient_shares row (the
        owner is unchanged); transfer_patient() reassigns patients.therapist_id
        itself, so the target becomes the new owner and this therapist loses
        owner permissions on this patient."""
        target = self._share_confirm_therapist
        patient = self.share_modal_patient
        if not target or not patient:
            self._share_error = "No therapist selected."; return

        is_transfer = (self._share_pending_action == "transfer")
        if is_transfer:
            ok = self.db.transfer_patient(patient["id"], target["id"],
                                          acting_therapist_id=self.account["id"])
            if ok:
                patient["therapist_id"] = target["id"]      # keep the in-memory row in step
                if self.selected_patient and self.selected_patient.get("id") == patient["id"]:
                    self._set_selected_patient(None)          # no longer ours to run sessions with
                self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                                 if hasattr(self.db, "get_all_patients") else self.patients)
            else:
                self._share_error = "Transfer failed. Try again."
        else:
            ok = self.db.share_patient(patient["id"], target["id"], self.account["id"])
            if ok:
                self._share_success = f"Shared with {target['full_name']}."
            else:
                self._share_error = "Share failed. Try again."

        self._share_stage             = "pick"
        self._share_pending_action    = None
        self._share_confirm_therapist = None
        self._share_suggestions       = []
        self._share_input             = ""
        if ok:
            self._share_error = ""
            # A successful TRANSFER ends this therapist's access to the
            # patient outright -- close the picker (it can no longer do
            # anything useful for a non-owner) and hand off to a dedicated
            # success acknowledgment instead of a message that would be
            # drawn on a window already closing. A successful SHARE doesn't
            # change ownership, so that window intentionally stays open
            # (with its own inline success text) for further sharing.
            if is_transfer:
                self._share_modal_open     = False
                self._transfer_success_msg = ("The patient has been successfully "
                                              "transferred to the selected therapist.")
                self.modal = "transfer_success"

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE EVENTS
    # ──────────────────────────────────────────────────────────────────

    def _handle_edit_click(self, pos):
        if self.edit_role_open:
            for opt in self.edit_role_options:
                if opt["rect"].collidepoint(pos):
                    self.edit_fields[2]["value"] = opt["label"]
                    self.edit_role_open = False; return None
            self.edit_role_open = False; return None

        # Tapping the big preview (or the "Change Icon" prompt beneath it)
        # opens the dedicated picker popup instead of an inline rail.
        bcx, bcy = self.edit_big_center
        if math.hypot(pos[0]-bcx, pos[1]-bcy) <= self.edit_big_r + self._sc(10):
            play_click()
            self._open_icon_picker(); return None
        if self.edit_change_icon_rect.collidepoint(pos):
            play_click()
            self._open_icon_picker(); return None

        clicked = False
        for i, field in enumerate(self.edit_fields):
            if field["rect"].inflate(8,8).collidepoint(pos):
                if field["key"] == "role":
                    self.edit_role_open    = not self.edit_role_open
                    self.edit_active_field = -1
                else:
                    self.edit_active_field = i
                    self.edit_role_open    = False
                clicked = True; break
        if not clicked:
            self.edit_active_field = -1; self.edit_role_open = False

        if self.edit_save_rect.collidepoint(pos):
            play_click()
            err = self._edit_validate()
            if err:
                self.edit_error = err
            else:
                self.edit_error = ""
                self.modal = "save_account_confirm"
            return None
        if self.edit_cancel_rect.collidepoint(pos):
            play_click()
            self.modal = None
        if self.edit_delete_rect.collidepoint(pos):
            play_confirm_alert(); self.modal = "delete_confirm"
            self._danger_countdown = 5.0
        return None

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE — ICON PICKER POPUP
    #  A dedicated, larger, scrollable grid of all 10 icons, opened from the
    #  big preview / "Change Icon" prompt in the main Edit Profile modal.
    #  Tapping an icon sets edit_selected_icon immediately (same underlying
    #  state and _attempt_save() persistence as before -- only HOW the icon
    #  is chosen changed, not what happens with the choice).
    # ──────────────────────────────────────────────────────────────────

    def _open_icon_picker(self):
        self.edit_icon_picker_open = True
        self._eip_scroll = 0
        self._eip_drag_y = None

    def _handle_icon_picker_click(self, pos):
        if self._eip_up_rect.collidepoint(pos):
            play_click()
            self._eip_scroll = max(0, self._eip_scroll - int(160 * self._fs))
            return None
        if self._eip_down_rect.collidepoint(pos):
            play_click()
            self._eip_scroll = min(self._eip_scroll_max, self._eip_scroll + int(160 * self._fs))
            return None
        if self._eip_done_rect.collidepoint(pos):
            play_click()
            self.edit_icon_picker_open = False
            return None
        for (cx, cy, idx) in self._eip_circles:
            if math.hypot(pos[0] - cx, pos[1] - cy) <= self._eip_r:
                play_click()
                self.edit_selected_icon = idx
                return None
        return None

    def _handle_edit_key(self, event):
        if event.key == pygame.K_ESCAPE: self.modal = None; return None
        if self.edit_active_field < 0:   return None
        f = self.edit_fields[self.edit_active_field]
        if event.key == pygame.K_BACKSPACE:
            f["value"] = f["value"][:-1]; self.edit_error = ""
        elif event.key == pygame.K_TAB:
            nxt = (self.edit_active_field+1) % len(self.edit_fields)
            self.edit_active_field = 3 if nxt==2 else nxt
        elif event.key == pygame.K_RETURN:
            err = self._edit_validate()
            if err:
                self.edit_error = err
            else:
                self.edit_error = ""
                self.modal = "save_account_confirm"
            return None
        elif event.unicode:
            self._edit_type(f, event.unicode); self.edit_error = ""
        return None

    def _edit_type(self, field, char):
        if field["is_pin"]:
            if char.isdigit() and len(field["value"]) < 4: field["value"] += char
        elif field["key"] == "username":
            if username_char_allowed(char) and len(field["value"]) < MAX_USERNAME_LEN:
                field["value"] += char
        else:
            if field["max_len"] <= 0 or len(field["value"]) < field["max_len"]:
                field["value"] += char

    def _edit_validate(self):
        """Returns an error message, or None if the Edit Profile (therapist
        account) fields are valid -- checked both before opening the Save
        confirmation dialog and again inside _attempt_save() itself."""
        fn=self.edit_fields[0]["value"].strip(); un=self.edit_fields[1]["value"].strip()
        role=self.edit_fields[2]["value"].strip(); wp=self.edit_fields[3]["value"].strip()
        idx=self.edit_selected_icon
        if not fn:   return "Full Name required."
        ok_un, msg = validate_username(un)
        if not ok_un: return msg
        if not role: return "Please select a role."
        if not wp:   return "Workplace required."
        if idx==0:   return "Please choose an icon."
        if un!=self.account["username"] and self.db.username_exists(un):
            return "Username already taken."
        return None

    def _attempt_save(self):
        err = self._edit_validate()
        if err:
            self.edit_error = err; return None
        fn=self.edit_fields[0]["value"].strip(); un=self.edit_fields[1]["value"].strip()
        role=self.edit_fields[2]["value"].strip(); wp=self.edit_fields[3]["value"].strip()
        idx=self.edit_selected_icon
        # new_pin is intentionally never passed here -- the PIN is only
        # changeable through the forgot-PIN flow on the Login page.
        ok=self.db.update_therapist(self.account["id"],fn,un,role,wp,idx,
                                    new_pin=None)
        if ok:
            self.account=self.db.get_therapist_by_id(self.account["id"]); self.modal=None
        else:
            self.edit_error="Save failed."
        return None

    # ──────────────────────────────────────────────────────────────────
    #  REGISTER PATIENT EVENTS
    # ──────────────────────────────────────────────────────────────────

    def _rp_handle_click(self, pos):
        rp = self.rp

        if self._rp_btn_rect.collidepoint(pos):
            play_click()
            self._rp_submit(); return

        for key in ["sex_open","dominant_open","affected_open","stroke_open"]:
            if rp[key]:
                field_key = key.replace("_open","")
                if field_key == "dominant": field_key = "dominant_hand"
                if field_key == "affected": field_key = "affected_hand"
                if field_key == "stroke":   field_key = "stroke_type"
                info = self._rp_drop_rects.get(field_key)
                if info:
                    _, opt_rects, opts = info
                    for j, (or_, opt_val) in enumerate(zip(opt_rects, opts)):
                        if or_.collidepoint(pos):
                            play_click()
                            rp[field_key] = opt_val
                            rp[key] = False
                            rp["invalid_keys"].discard(field_key)
                            return
                rp[key] = False
                return

        drop_map = [
            ("sex",           "sex_open",      SEX_OPTS),
            ("dominant_hand", "dominant_open", HAND_OPTS),
            ("affected_hand", "affected_open", HAND_OPTS),
            ("stroke_type",   "stroke_open",   STROKE_TYPES),
        ]
        for (field_key, open_key, opts) in drop_map:
            info = self._rp_drop_rects.get(field_key)
            if info:
                field_rect = info[0]
                if field_rect.collidepoint(pos):
                    play_click()
                    for _, ok2, _ in drop_map:
                        rp[ok2] = False
                    rp[open_key] = not rp[open_key]
                    return

        text_keys = ["full_name","age","date_of_stroke","months_stroke",
                     "notes_stiffness","notes_pain","notes_therapist"]
        for key in text_keys:
            info = self._rp_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                rp["active_key"] = key
                return
        rp["active_key"] = None

    # Registration must ask for every field the Patient Info page shows.
    # Patient Information + Stroke & Therapy are required; Clinical Notes are
    # optional (notes_* are deliberately absent from this list).
    _RP_REQUIRED = [
        ("full_name",      "Full Name"),
        ("age",            "Age"),
        ("sex",            "Sex"),
        ("stroke_type",    "Stroke Type"),
        ("date_of_stroke", "Stroke Onset Date"),
        ("months_stroke",  "Months Since Stroke"),
        ("dominant_hand",  "Dominant Hand"),
        ("affected_hand",  "Affected Hand"),
    ]

    def _rp_submit(self):
        rp = self.rp
        missing = [key for key, _label in self._RP_REQUIRED
                   if not str(rp.get(key, "")).strip()]
        if missing:
            rp["invalid_keys"] = set(missing)
            label = dict(self._RP_REQUIRED)[missing[0]]
            rp["error"] = f"{label} is required."
            rp["active_key"]  = missing[0]
            self._rp_focus_key = missing[0]
            return
        if not rp["age"].strip().isdigit():
            rp["invalid_keys"] = {"age"}
            rp["error"] = "Age must be a number."
            rp["active_key"] = "age"; self._rp_focus_key = "age"
            return
        if not rp["months_stroke"].strip().isdigit():
            rp["invalid_keys"] = {"months_stroke"}
            rp["error"] = "Months Since Stroke must be a number."
            rp["active_key"] = "months_stroke"; self._rp_focus_key = "months_stroke"
            return
        rp["invalid_keys"] = set()
        name = rp["full_name"].strip()
        try:
            pid = self.db.create_patient(rp, self.account["id"]) if hasattr(self.db, 'create_patient') else None
            if pid is None:
                rp["error"] = "Registration failed. Please try again."
                return
            self.patients = (
                self.db.get_all_patients(therapist_id=self.account["id"])
                if hasattr(self.db, 'get_all_patients') else []
            )
        except Exception:
            rp["error"] = "An error occurred. Please try again."
            return
        self._init_register_state()
        self._rp_success_msg = f"Patient '{name}' registered successfully.\nID: {pid}"
        self.modal = "register_success"

    def _rp_keydown(self, event):
        rp  = self.rp
        key = rp["active_key"]
        if not key: return
        if event.key == pygame.K_BACKSPACE:
            rp[key] = rp[key][:-1]; rp["error"] = ""
        elif event.key == pygame.K_RETURN:
            rp["active_key"] = None
        elif event.key == pygame.K_ESCAPE:
            rp["active_key"] = None
        elif event.unicode:
            if key in ("age", "months_stroke") and (
                    not event.unicode.isdigit() or len(rp[key]) >= 3):
                return
            rp[key] += event.unicode; rp["error"] = ""
            rp["invalid_keys"].discard(key)

    # ──────────────────────────────────────────────────────────────────
    #  GAME CONFIG EVENTS
    # ──────────────────────────────────────────────────────────────────

    def _gc_handle_skill_modal_click(self, pos):
        """The "Select a Game -- <skill>" modal's own click handling,
        called early (from _handle_click, ahead of Sidebar/Back/panel
        dispatch) while it's open, so it has exclusive input focus."""
        gc = self.gc
        if self._gc_skill_modal_close.collidepoint(pos):
            play_click()
            self._gc_skill_modal_open = False
            return
        for (gr, game_name) in self._gc_skill_modal_rects:
            if gr.collidepoint(pos):
                play_click()
                gc["selected_game"] = (game_name, self._gc_skill_modal_type)
                gc["preset_applied"] = False
                self._gc_skill_modal_open = False
                return
        self._gc_skill_modal_open = False   # tap outside the modal dismisses it

    def _gc_handle_click(self, pos):
        gc = self.gc

        # ── Single Skill / Integrated Games tab switch ─────────────────
        for key, r in self._gc_tab_rects.items():
            if r.collidepoint(pos):
                play_click()
                self._gc_active_tab = key
                return

        for (tr, game_tuple) in self._game_tiles:
            if tr.collidepoint(pos):
                play_click()
                skill_type = game_tuple[1]
                if skill_type in SKILL_GAMES:
                    self._gc_skill_modal_type = skill_type
                    self._gc_skill_modal_open = True
                    self._gc_skill_modal_rects = []
                else:
                    gc["selected_game"] = game_tuple
                return

    # ──────────────────────────────────────────────────────────────────
    #  UPDATE
    # ──────────────────────────────────────────────────────────────────

    def update(self, mouse_pos, dt):
        """
        Update hover states for all interactive UI elements.
        Called once per frame to check which buttons/elements are under the mouse.
        Also handles fade-in animation on scene load.

        Args:
            mouse_pos: (x, y) tuple of current mouse position in pixels
            dt: delta time since last frame, in MILLISECONDS (main.py passes
                pygame.time.Clock.tick()'s return value straight through --
                see self._cal_win.update(dt) below, which already divides by
                1000 itself)
        """
        # ── Destructive-action safety-delay countdown ──
        if self._danger_countdown > 0:
            self._danger_countdown = max(0.0, self._danger_countdown - dt / 1000.0)

        # ── "Session in Progress" screen (panel 7) ──
        if self.active_panel == 7:
            self._sm_update(mouse_pos)

        # ── Lobby music (idle dashboard) vs the launched game's own BGM ──
        # Both ultimately share one pygame.mixer.music channel (a game's
        # start_music()/stop_music() calls stop whatever is already playing
        # first), so the two can never overlap -- this just keeps lobby
        # music topped up whenever Session in Progress (panel 7) isn't
        # active, mirroring the BLE-ownership edge-detect pattern just
        # below. Edge-triggered on actually CHANGING panels, not every
        # frame, so switching between ordinary dashboard sections (Patient
        # List, Game Configuration, etc.) never restarts the track.
        want_lobby = (self.active_panel != 7)
        if want_lobby != self._lobby_want:
            self._lobby_want = want_lobby
            (start_lobby_music if want_lobby else stop_lobby_music)()

        # ── BLE controller ownership (dual-monitor) ──
        # The therapist process holds the controller while a patient is selected
        # and we are NOT on "Session in Progress" (select -> Game Config ->
        # calibration all read the live sensor here). Entering panel 7 releases
        # it so the patient process can take it for the game; leaving panel 7
        # with a patient still selected reclaims it. Deselect always releases.
        if _DUAL_MONITOR and _ble_receiver is not None:
            want_ble = bool(self.selected_patient) and self.active_panel != 7
            if want_ble != self._ble_want:
                self._ble_want = want_ble
                try:
                    _ble_receiver.set_enabled(want_ble)
                except Exception:
                    pass

        # ── Sidebar navigation hover ──
        # Reset to -1, then check each nav item for collision with mouse
        self.nav_hovered = -1
        for i, r in enumerate(self.nav_rects):
            if r.collidepoint(mouse_pos):
                self.nav_hovered = i  # Store which nav item is hovered
                break

        # ── Header/profile area hover ──
        self.edit_link_hovered = self._edit_link_rect.collidepoint(mouse_pos)
        self.logout_hovered    = self._logout_rect().collidepoint(mouse_pos)
        self._theme_hov        = self._theme_btn_rect.collidepoint(mouse_pos)
        self._ctrl_hov         = self._ctrl_btn_rect.collidepoint(mouse_pos)

        # ── Panel interactive elements hover ──
        self.rp_btn_hov        = self._rp_btn_rect.collidepoint(mouse_pos)         # Register Patient submit
        self.gc_next_hov       = self._gc_next_rect.collidepoint(mouse_pos)        # Game Config "next" button
        self.start_hov         = self._start_btn_rect.collidepoint(mouse_pos)      # Start Session button
        self.register_link_hov = self._register_link_rect.collidepoint(mouse_pos)  # Patient list "register" link
        self.preset_hov        = self._preset_btn_rect.collidepoint(mouse_pos)     # Smart Preset button
        self._bypass_hov      = self._bypass_btn_rect.collidepoint(mouse_pos)      # Calibration bypass toggle
        self._calibrate_hov   = self._calibrate_btn_rect.collidepoint(mouse_pos)  # Real Calibrate button
        self._test_mode_hov   = self._test_mode_btn_rect.collidepoint(mouse_pos)  # Dev-only Test Mode toggle

        # ── Calibration window update (delegates sensor + phase logic) ──
        if self._cal_win is not None:
            self._cal_win.update(dt)
            # Light/dark toggle inside the calibration window -> sync BOTH
            # interfaces immediately (no reload / new session / navigation).
            self._apply_theme(bool(self._cal_win.dark_mode))

            # Mirror the live sensor/step/attempt/reading onto the patient's
            # own Calibration screen. Throttled (10 Hz is plenty smooth for a
            # progress bar) and skipped entirely when nothing actually
            # changed, so a steady phase doesn't spam the broker with
            # identical POSTs every frame.
            if _DUAL_MONITOR:
                self._cal_progress_push_t += dt / 1000.0
                if self._cal_progress_push_t >= 0.1:
                    self._cal_progress_push_t = 0.0
                    payload = self._cal_progress_payload()
                    if payload != self._cal_progress_last:
                        self._cal_progress_last = payload
                        therapist_link.set_calibration_progress(payload)

            if self._cal_win.done:
                self.calibration_done   = True
                self.calibration_result = self._cal_win.calibration_result
                multi_sensor_rows        = list(self._cal_win.multi_sensor_results)
                reused_this_run          = set(self._cal_win._initially_reused_sensors)
                single_sensor_reused     = (len(self._cal_win.game_types) == 1
                                            and self._cal_win.game_type in reused_this_run)
                # Cache every sensor this window ends with (freshly-run AND
                # reused-passthrough alike) for later games in the same
                # session -- see _launch_calibration()/_set_selected_patient.
                if self._cal_win.sensor_results:
                    for sensor_type, data in self._cal_win.sensor_results.items():
                        self._calibrated_sensors[sensor_type] = dict(data)
                else:
                    self._calibrated_sensors[self._cal_win.game_type] = {
                        "sensor_name": self.calibration_result.get("sensor", ""),
                        "trials":      list(self.calibration_result.get("trials", [])),
                        "average":     self.calibration_result.get("average", 0.0),
                    }
                self._sync_dur_from_cal(self._cal_win)
                self._cal_win           = None
                if _DUAL_MONITOR:
                    therapist_link.calibrate_end()
                pt_id = (self.selected_patient or {}).get("id")
                if pt_id and hasattr(self.db, "save_calibration"):
                    game_name = (self.gc.get("selected_game") or (None,))[0] or ""
                    if multi_sensor_rows:
                        # One sensor calibrated at a time (see
                        # MULTI_SENSOR_CALIBRATION) -> one DB row per sensor,
                        # same shape/call as a normal single-sensor pass.
                        # Skip any sensor that was reused rather than
                        # actually just measured, so reusing a calibration
                        # doesn't fabricate a duplicate history record.
                        for row in multi_sensor_rows:
                            if row.get("game_type") in reused_this_run:
                                continue
                            self.db.save_calibration(
                                pt_id, self.account["id"], row, game_name=game_name,
                            )
                    elif not single_sensor_reused:
                        self.db.save_calibration(
                            pt_id, self.account["id"],
                            self.calibration_result,
                            game_name=game_name,
                        )
            elif self._cal_win.cancelled:
                self._cal_win = None
                if _DUAL_MONITOR:
                    therapist_link.calibrate_end()

        # ── Share modal hover states ──
        self._share_search_hov  = self._share_search_rect.collidepoint(mouse_pos)
        self._share_confirm_hov = self._share_confirm_rect.collidepoint(mouse_pos)
        self._share_close_hov   = self._share_close_rect.collidepoint(mouse_pos)
        self._share_yes_hov     = self._share_yes_rect.collidepoint(mouse_pos)
        self._share_no_hov      = self._share_no_rect.collidepoint(mouse_pos)
        self._share_choice_share_hov    = self._share_choice_share_rect.collidepoint(mouse_pos)
        self._share_choice_transfer_hov = self._share_choice_transfer_rect.collidepoint(mouse_pos)

        # ── Edit patient modal hover ──
        if self._ep_modal_open:
            self._ep_save_hov   = self._ep_save_rect.collidepoint(mouse_pos)
            self._ep_cancel_hov = self._ep_cancel_rect.collidepoint(mouse_pos)
            self._ep_delete_hov = self._ep_delete_rect.collidepoint(mouse_pos)

        # ── Edit profile modal hover ──
        if self.modal == "edit_profile":
            self.edit_save_hov   = self.edit_save_rect.collidepoint(mouse_pos)
            self.edit_cancel_hov = self.edit_cancel_rect.collidepoint(mouse_pos)
            self.edit_delete_hov = self.edit_delete_rect.collidepoint(mouse_pos)

        # ── Register success popup hover ──
        if self.modal == "register_success":
            self._rp_ok_hov = self._rp_ok_rect.collidepoint(mouse_pos)

        # ── Transfer success popup hover ──
        if self.modal == "transfer_success":
            self._transfer_ok_hov = self._transfer_ok_rect.collidepoint(mouse_pos)

        # ── Confirmation modal hover ──
        if self.modal in ("logout_confirm","delete_confirm","delete_patient_confirm",
                          "select_patient_confirm","deselect_patient_confirm",
                          "save_account_confirm","save_patient_confirm"):
            yr, nr = self._confirm_rects()
            self.confirm_yes_hov = yr.collidepoint(mouse_pos)
            self.confirm_no_hov  = nr.collidepoint(mouse_pos)

        # ── Calibration mismatch modal hover ──
        if self.modal == "calibration_mismatch":
            self._mismatch_cal_hov    = self._mismatch_cal_rect.collidepoint(mouse_pos)
            self._mismatch_cancel_hov = self._mismatch_cancel_rect.collidepoint(mouse_pos)

        # ── Reuse calibration chooser hover ──
        if self.modal == "reuse_calibration_choice":
            self._reuse_use_hov   = self._reuse_use_rect.collidepoint(mouse_pos)
            self._reuse_recal_hov = self._reuse_recal_rect.collidepoint(mouse_pos)

        # ── Home card hover ──
        for i, cr in enumerate(self.card_rects):
            self.card_hovered[i] = (self.active_panel == -1 and cr.collidepoint(mouse_pos))

        # ── Page transition fade-in animation ──
        # Fade in over several frames (alpha goes from 0→255, +4 per frame = ~64 frames at 60FPS = 1 second)
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    # ──────────────────────────────────────────────────────────────────
    #  DRAW — TOP LEVEL — Main rendering function called each frame
    # ──────────────────────────────────────────────────────────────────

    def draw(self, surface):
        """
        Main draw function. Renders entire UI each frame in the following order:
        1. Background gradient
        2. Sidebar (navigation, profile)
        3. Home screen (if active_panel == -1) OR Panel content + shell
        4. Modals (if any)
        5. Fade transition animation

        Args:
            surface: pygame.Surface to draw on (usually the main screen)
        """
        # ── Background layer ──
        # Draw pre-rendered gradient background for visual depth
        surface.blit(self.background_surface, (0, 0))

        # ── Sidebar (always visible) ──
        # Contains profile info, edit link, logout, and navigation menu
        self._draw_sidebar(surface)

        # ── Main content area ──
        # Dispatch to the active panel (Patient List shown by default on load)
        panel_drawers = {
            0: self._draw_patient_list,
            1: self._draw_session_history,
            2: self._draw_analytics,
            3: self._draw_calibration,
            4: self._draw_game_config,
            5: self._draw_start_session,
            6: self._draw_register_patient,
            7: self._sm_draw,               # dual-monitor "Session in Progress"
            8: self._draw_patient_preview,  # review a patient (does NOT select them)
        }
        if self.active_panel in panel_drawers:
            # Panel 0 (Patient List) is the dashboard home now -- no Back button,
            # no breadcrumb shell; it draws its own header and gets the full
            # height (reclaim the header band the other panels reserve).
            pa = self._panel_area()
            if self.active_panel != 0:
                self._draw_panel_shell(surface, self.active_panel)
            else:
                # Touch: the card itself still starts right under the close
                # (X) button -- only its header CONTENT is padded down away
                # from that top edge (see _draw_patient_list's head_y), to
                # match the top-right bar without shrinking the card itself.
                top = (46 + self._sc(10)) if self._touch_ui else int(self.HEIGHT * 0.06)
                pa = pygame.Rect(pa.x, top, pa.width,
                                 self.HEIGHT - top - int(self.HEIGHT * 0.025))
            panel_drawers[self.active_panel](surface, pa)

        # Clock/date + theme toggle float above the panel's own content
        # (painted after it, not inside _draw_sidebar) so no panel's
        # background card can ever wash them out. Always present now --
        # _panel_area()/panel 0's own header both clear this bar's height.
        self._draw_top_right_bar(surface)

        # Note: draw_confirm_dialog (used by every one of these except
        # edit_profile/edit_patient/icon-picker, which keep their own
        # unrelated modal styling) draws its OWN dim overlay internally --
        # an extra self._draw_overlay() here would stack two overlays and
        # darken the background far more than the "subdued, not blacked
        # out" design calls for.
        if self.modal == "edit_profile":
            self._draw_overlay(surface); self._draw_edit_modal(surface)
            if self.edit_icon_picker_open:
                self._draw_overlay(surface); self._draw_icon_picker_popup(surface)
        elif self.modal in ("logout_confirm","delete_confirm","save_account_confirm"):
            self._draw_confirm_modal(surface)
        elif self.modal == "select_patient_confirm":
            self._draw_select_confirm_modal(surface)
        elif self.modal == "deselect_patient_confirm":
            self._draw_deselect_confirm_modal(surface)
        elif self.modal == "register_success":
            self._draw_register_success_modal(surface)
        elif self.modal == "transfer_success":
            self._draw_transfer_success_modal(surface)
        elif self.modal == "reuse_calibration_choice":
            self._draw_reuse_calibration_modal(surface)
        elif self.modal == "calibration_mismatch":
            self._draw_calibration_mismatch_modal(surface)
        elif self.modal == "delete_blocked":
            self._draw_delete_blocked_modal(surface)

        # Edit patient modal
        if self._ep_modal_open:
            self._draw_overlay(surface)
            self._draw_edit_patient_modal(surface)
            if self.modal in ("delete_patient_confirm", "save_patient_confirm"):
                self._draw_confirm_modal(surface)

        # Skill game picker modal (game config panel)
        if self.active_panel == 4 and self._gc_skill_modal_open:
            self._draw_overlay(surface)
            self._draw_skill_game_modal(surface)

        # Share modal drawn on top of everything
        if self._share_modal_open:
            self._draw_overlay(surface)
            self._draw_share_modal(surface)

        # Calibration window (full-screen, drawn last so it covers everything)
        if self._cal_win is not None:
            self._cal_win.draw(surface)

        # (Session in Progress = panel 7, drawn via panel_drawers above)

        if self.alpha < 255:
            self.fade_surface.set_alpha(255-self.alpha)
            surface.blit(self.fade_surface, (0,0))

    # ──────────────────────────────────────────────────────────────────
    #  SIDEBAR
    # ──────────────────────────────────────────────────────────────────

    def _draw_sidebar(self, surface):
        W, H, sw = self.WIDTH, self.HEIGHT, self.sidebar_w
        # Solid (opaque) panel -- was a translucent wash over the gradient.
        sb = pygame.Surface((sw, H), pygame.SRCALPHA)
        sb.fill((230, 240, 252, 255)); surface.blit(sb, (0,0))
        hl = pygame.Surface((sw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200)); surface.blit(hl, (0, 0))
        pygame.draw.line(surface, (200, 216, 236), (sw,0), (sw,H), 1)

        # Logo centred in the rail -- the clock/date used to sit beside/under
        # it (now moved to the top-right, alongside the theme toggle), which
        # left the wordmark looking off-balance pinned to the left edge.
        ly = int(H*0.05)
        s1 = self.fnt["logo"].render("Recov", True, (45,60,80))
        s2 = self.fnt["logo"].render("R",     True, (215,40,40))
        logo_w = s1.get_width() + s2.get_width()
        lx = (sw - logo_w) // 2
        surface.blit(s1, s1.get_rect(midleft=(lx, ly)))
        surface.blit(s2, s2.get_rect(midleft=(lx+s1.get_width(), ly)))

        # "Hand Rehabilitation System" removed from under the wordmark -- the
        # logo now flows straight into the profile card below it.
        stack_y = ly + s1.get_height() // 2

        if self._touch_ui:
            # Big centered avatar + a small edit badge overlapping its
            # bottom-right corner, name centered below it -- sized here so
            # the card height (pc_h) actually fits that vertical stack,
            # rather than the old fixed-height row.
            pc_pad_c    = self._sc(10)
            pc_ir       = self._sc(30)
            pc_badge_r  = max(self._sc(11), int(pc_ir * 0.42))
            pc_name_gap = self._sc(6)
            pc_h = pc_pad_c + pc_ir * 2 + pc_name_gap + self.fnt["profile_nm"].get_height() + pc_pad_c
            # Flow from the measured bottom of the clock/date block. The old
            # fixed 0.205*H put the card at y=98 while the date ran to y=105,
            # so the two overlapped on the 480px-tall panel.
            pc_y = stack_y + self._sc(10)
        else:
            pc_y = int(H*0.11); pc_h = int(H*0.13)
        pc_r = pygame.Rect(int(sw*0.05), pc_y, int(sw*0.90), pc_h)
        # White card behind the avatar + name, per the reference mock.
        pygame.draw.rect(surface, (255, 255, 255), pc_r, border_radius=14)
        pygame.draw.rect(surface, (222, 232, 246), pc_r, 1, border_radius=14)
        f_nm  = self.fnt["profile_nm"]
        f_sub = self.fnt["profile"]

        def _fit(txt, fnt, avail):
            if fnt.size(txt)[0] <= avail:
                return txt
            while txt and fnt.size(txt + "…")[0] > avail:
                txt = txt[:-1]
            return txt + "…"

        if self._touch_ui:
            # Avatar-first layout (matches the reference mock): big centered
            # icon, a small round edit badge overlapping its bottom-right
            # edge (tapping the badge opens Edit Profile -- the separate
            # "Edit Profile" text link is gone; the Role line stays dropped
            # here, same as before -- it's still editable in the modal).
            icon_cx = pc_r.centerx
            icon_cy = pc_r.y + pc_pad_c + pc_ir
            draw_icon(surface, self.account.get("icon_index", 1), icon_cx, icon_cy, pc_ir, shadow=True)

            badge_cx = icon_cx + int(pc_ir * 0.72)
            badge_cy = icon_cy + int(pc_ir * 0.72)
            ring_r = pc_badge_r + self._sc(3)
            pygame.draw.circle(surface, (255, 255, 255), (badge_cx, badge_cy), ring_r)
            badge_img = _img("edit_profile.png", pc_badge_r * 2)
            if badge_img is not None:
                surface.blit(badge_img, badge_img.get_rect(center=(badge_cx, badge_cy)))
            else:
                ec = (25, 130, 185) if self.edit_link_hovered else (40, 160, 220)
                pygame.draw.circle(surface, ec, (badge_cx, badge_cy), pc_badge_r)

            name_y = icon_cy + pc_ir + pc_name_gap
            ns = f_nm.render(_fit(self.account["full_name"], f_nm, pc_r.width - 2 * pc_pad_c),
                             True, (40, 55, 75))
            surface.blit(ns, ns.get_rect(midtop=(pc_r.centerx, name_y)))

            tap_d = self._tt(pc_badge_r * 2 + 14)
            self._edit_link_rect = pygame.Rect(0, 0, tap_d, tap_d)
            self._edit_link_rect.center = (badge_cx, badge_cy)
        else:
            ir = int(44*(H/1080))
            iy = pc_r.centery
            gap_icon_text = int(12*(W/1920))
            pad_side = int(20*W/1920)

            # Icon anchored at a fixed, comfortable left inset -- the icon
            # and the name/role/Edit Profile block that follows it read as
            # one left-aligned group, instead of being centered as a unit
            # (which, depending on text length, could leave the icon sitting
            # noticeably right of the card's left edge).
            max_text_w = max(20, pc_r.width - pad_side - ir*2 - gap_icon_text - int(8*W/1920))
            name_s = f_nm.render(_fit(self.account["full_name"], f_nm, max_text_w), True, (40,55,75))
            role_s = f_sub.render(_fit(self.account.get("role",""), f_sub, max_text_w), True, (100,115,140))
            ec  = (50,120,200) if self.edit_link_hovered else (75,140,210)
            edit_s = f_sub.render("Edit Profile", True, ec)

            ix = pc_r.x + pad_side + ir
            draw_icon(surface, self.account.get("icon_index",1), ix, iy, ir, shadow=False)
            tx = ix + ir + gap_icon_text

            line_gap = self._sc(4)
            block_h  = name_s.get_height() + line_gap + role_s.get_height() + line_gap + edit_s.get_height()
            y = iy - block_h // 2
            surface.blit(name_s, (tx, y)); y += name_s.get_height() + line_gap
            surface.blit(role_s, (tx, y)); y += role_s.get_height() + line_gap
            ep = (tx, y)
            surface.blit(edit_s, ep)
            self._edit_link_rect = pygame.Rect(ep[0]-int(8*W/1920), ep[1]-int(8*H/1080),
                                               edit_s.get_width()+int(16*W/1920),
                                               edit_s.get_height()+int(16*H/1080))

        for i, item in enumerate(SIDEBAR_NAV):
            r       = self.nav_rects[i]
            col     = PANEL_COLORS[item["idx"]]
            active  = (self.active_panel == item["idx"])
            if active:
                bg = pygame.Surface((sw, r.height), pygame.SRCALPHA)
                bg.fill((*col, 55)); surface.blit(bg, r.topleft)
                hl_nav = pygame.Surface((sw, 2), pygame.SRCALPHA)
                hl_nav.fill((255, 255, 255, 160)); surface.blit(hl_nav, r.topleft)
                pygame.draw.rect(surface, col, pygame.Rect(0,r.y,int(4*W/1920),r.height))
            px  = int(sw*0.10)
            sym = self.fnt["nav_sym"].render(item["symbol"],True,col if active else (120,140,165))
            lbl = self.fnt["nav"].render(item["label"],True,col if active else (60,78,100))
            surface.blit(sym, sym.get_rect(midleft=(px, r.centery)))
            surface.blit(lbl, lbl.get_rect(midleft=(px + sym.get_width() + int(10*W/1920), r.centery)))

        # ── Active Patient (gradient box, centered text), THEN the
        #    controller/connection status below it -- per the reference
        #    mock, patient identity now reads before the live status. ──
        stack_y = pc_r.bottom + (self._sc(10) if self._touch_ui else int(20*H/1080))
        self._active_patient_rect = pygame.Rect(0, 0, 1, 1)   # no patient -> not clickable

        if self.selected_patient:
            bpad = self._sc(8) if self._touch_ui else int(12*W/1920)
            label_max_w = int(sw * 0.90) - bpad * 2
            f_bl = self.fnt["eyebrow"] if self._touch_ui else self.fnt["small"]
            f_bl_txt = _fit("ACTIVE PATIENT", f_bl, label_max_w)
            pn = (self.fnt["body_b"] if self._touch_ui else self.fnt["label"])
            pname = self.selected_patient.get("full_name", "—")
            _wrapped = self._wrap(pname, pn, label_max_w)
            name_lines = _wrapped[:2]
            if len(_wrapped) > 2:                    # 3rd+ line -- ellipsize the 2nd
                name_lines[1] = name_lines[1] + "…"
            # _wrap() only breaks BETWEEN words -- a single long word (e.g. a
            # hyphenated surname like "Villanueva-Santos") can still come
            # back wider than the box, so ellipsize every line as a backstop.
            name_lines = [_fit(ln, pn, label_max_w) for ln in name_lines]

            badge_y = stack_y
            line_h = pn.get_height()
            name_block_h = line_h * len(name_lines)
            bh = (self._sc(8) + f_bl.get_height() + self._sc(4) + name_block_h + self._sc(8))
            bh = max(bh, self._tt(60) if self._touch_ui else int(60*H/1080))
            badge_r = pygame.Rect(int(sw*0.05), badge_y, int(sw*0.90), bh)
            _grad_box(surface, badge_r, (204, 224, 250), (224, 205, 246),
                     radius=10, border_col=(178, 196, 232), border_w=1)
            lbl_s = f_bl.render(f_bl_txt, True, (55, 105, 170))
            surface.blit(lbl_s, lbl_s.get_rect(midtop=(badge_r.centerx, badge_r.y + self._sc(6))))
            ny = badge_r.bottom - self._sc(8) - name_block_h
            for ln in name_lines:
                ls = pn.render(ln, True, (55, 60, 95))
                surface.blit(ls, ls.get_rect(midtop=(badge_r.centerx, ny)))
                ny += line_h
            # Whole box (label + name + padding) is one tap target -> Patient Info,
            # not just the name/icon text within it.
            self._active_patient_rect = badge_r
            stack_y = badge_r.bottom + (self._sc(10) if self._touch_ui else int(20*H/1080))

        stack_y = self._draw_controller_monitor(surface, sw, stack_y)

        lr = self._logout_rect()
        # The old sidebar-bottom theme button is gone -- the icon-based
        # toggle in _draw_top_right_bar (called from draw(), on every panel)
        # is now the only theme control.

        logout_img = _img_fit("logout_button.png", lr.width, lr.height)
        if logout_img is not None:
            surface.blit(logout_img, logout_img.get_rect(center=lr.center))
        else:
            lc = (165,25,25) if self.logout_hovered else (205,45,45)
            pygame.draw.rect(surface, lc, lr, border_radius=10)
            ls = self.fnt["btn"].render("Logout", True, (255,255,255))
            surface.blit(ls, ls.get_rect(center=lr.center))

    def _draw_top_right_bar(self, surface):
        """Calendar/time pill + the Light/Dark theme toggle + the close (X)
        button's reserved slot, top-right of the whole window -- moved out
        of the sidebar so the wordmark could be centred. All three share one
        container height (_bar_height()) and sit in one row, left to right:
        [date/time pill] [Light/Dark toggle] [close button].

        The close (X) button itself is drawn by main.py (always on top, so
        it still works over modals/overlays) -- this method only reserves
        and publishes self._close_btn_rect, which main.py reads each frame
        instead of using a fixed screen-corner position. That rect is
        published unconditionally (not patient-dependent), since the close
        button must always be reachable.

        The theme toggle keeps its exact original behaviour: it belongs to
        the selected patient, so with nobody selected it is not drawn and
        self._theme_btn_rect collapses to (0,0,1,1) so a stray tap can't
        fire it -- only WHERE/HOW it is drawn changed, not the logic.
        """
        top    = self._bar_top()
        # Right edge = the panel card's own right edge (not the raw screen
        # edge), inset enough to stay clear of its rounded corner -- this is
        # what keeps the row from visually spilling past the card.
        card_right = self._panel_area().right
        pad_r  = self._sc(20)
        gap    = self._sc(10)
        row_h  = self._bar_height()      # shared container height for all three controls

        # ── Close (X) button slot -- always reserved, rightmost ──────────
        close_r = pygame.Rect(card_right - pad_r - row_h, top, row_h, row_h)
        self._close_btn_rect = close_r

        # ── Light | Dark toggle -- icons only now, sized to just fit the
        #    two knob positions ("shorten the toggle to fit just the
        #    circles" instead of the old label-driven width) ──────────────
        track_h = row_h
        if self.selected_patient:
            dark = self._applied_theme_dark
            tog_w = track_h * 2
            tr = pygame.Rect(close_r.left - gap - tog_w, top, tog_w, track_h)
            self._theme_btn_rect = tr

            track_col = (34, 46, 66) if dark else (210, 222, 240)
            pygame.draw.rect(surface, track_col, tr, border_radius=track_h // 2)
            pygame.draw.rect(surface, (255, 255, 255) if not self._theme_hov else (235, 240, 248),
                             tr, max(1, int(2 * self._fs)), border_radius=track_h // 2)
            knob_d  = track_h - self._sc(6)
            knob_cx = (tr.right - track_h // 2) if dark else (tr.left + track_h // 2)
            knob_img = _img("dark_mode.png" if dark else "light_mode.png", knob_d)
            if knob_img is not None:
                surface.blit(knob_img, knob_img.get_rect(center=(knob_cx, tr.centery)))
            else:
                pygame.draw.circle(surface, (255, 255, 255), (knob_cx, tr.centery), knob_d // 2)
                pygame.draw.circle(surface, (190, 200, 215), (knob_cx, tr.centery), knob_d // 2, 1)
            anchor_left = tr.left
        else:
            self._theme_btn_rect = pygame.Rect(0, 0, 1, 1)
            anchor_left = close_r.left

        # Date/time pill -- calendar icon + two stacked lines, sized with its
        # OWN small fonts (not fonts sized for other controls) so both lines
        # sit fully inside the pill instead of touching its top/bottom edge.
        pill_h = row_h
        now = datetime.datetime.now()
        f_time = pygame.font.SysFont("segoeui,arial", int(16 * self._fs), bold=True)
        f_date = pygame.font.SysFont("segoeui,arial", int(12 * self._fs))
        t_surf = f_time.render(now.strftime("%I:%M %p"), True, (55, 74, 104))
        d_surf = f_date.render(now.strftime("%b %d, %Y"), True, (110, 128, 150))
        cal_sz = int(pill_h * 0.55)
        gap_in = self._sc(8)
        text_w = max(t_surf.get_width(), d_surf.get_width())
        pill_w = self._sc(12) + cal_sz + gap_in + text_w + self._sc(14)
        pill_r = pygame.Rect(0, top, pill_w, pill_h)
        pill_r.right = anchor_left - gap

        pygame.draw.rect(surface, (255, 255, 255), pill_r, border_radius=pill_h // 2)
        pygame.draw.rect(surface, (222, 232, 246), pill_r, 1, border_radius=pill_h // 2)
        cal_img = _img("calendar.png", cal_sz)
        cx = pill_r.x + self._sc(12)
        if cal_img is not None:
            surface.blit(cal_img, cal_img.get_rect(midleft=(cx, pill_r.centery)))
            cx += cal_sz + gap_in
        line_gap = self._sc(2)
        block_h = t_surf.get_height() + line_gap + d_surf.get_height()
        ty = pill_r.centery - block_h // 2
        surface.blit(t_surf, (cx, ty))
        surface.blit(d_surf, (cx, ty + t_surf.get_height() + line_gap))

    # ──────────────────────────────────────────────────────────────────
    #  ESP32 CONTROLLER CONNECTION MONITOR
    # ──────────────────────────────────────────────────────────────────

    #   stage -> (label, dot colour, text colour)
    _CTRL_LOOK = {
        "connected":     ("Controller connected", (40, 190, 90),  (28, 130, 66)),
        "stalled":       ("Signal stalled",       (230, 165, 30), (166, 112, 12)),
        "connecting":    ("Connecting…",     (230, 165, 30), (166, 112, 12)),
        "scanning":      ("Searching…",      (230, 165, 30), (166, 112, 12)),
        "handed_off":    ("On patient screen",    (60, 140, 225), (40, 100, 175)),
        "idle":          ("Controller idle",      (172, 184, 198), (118, 132, 150)),
        "disabled":      ("Controller off",       (172, 184, 198), (118, 132, 150)),
        "old_firmware":  ("Old firmware",         (215, 60, 55),  (170, 40, 36)),
        "bluetooth_off": ("Bluetooth is off",     (215, 60, 55),  (170, 40, 36)),
        "no_bleak":      ("bleak not installed",  (215, 60, 55),  (170, 40, 36)),
        "no_permission": ("No BLE permission",    (215, 60, 55),  (170, 40, 36)),
        "error":         ("Controller error",     (215, 60, 55),  (170, 40, 36)),
    }

    def _controller_status(self):
        """(stage, label, detail, dot_col, txt_col) for the controller monitor.

        Handoff-aware: with RECOVR_DUAL_MONITOR the therapist process gives the
        controller up on purpose (no patient selected, or the patient process is
        running the game), so 'not connected' there is normal, not a fault."""
        st = {}
        if _ble_receiver is not None:
            try:
                st = _ble_receiver.status()
            except Exception:
                st = {}

        # Keep every detail line short -- the sidebar rail is ~200 px wide.
        if _DUAL_MONITOR and self.active_panel == 7:
            stage, detail = "handed_off", "used by the game"
        elif _DUAL_MONITOR and not self.selected_patient:
            stage, detail = "idle", "select a patient"
        else:
            stage  = st.get("stage", "error")
            detail = st.get("detail", "")
            if stage == "connected":
                age = st.get("data_age")
                if age is not None and age > 2.0:
                    stage, detail = "stalled", f"no data {age:.0f}s"
                else:
                    detail = st.get("device") or "sensor live"
            elif stage == "scanning":
                n = len(st.get("seen") or [])
                s = st.get("scans", 0)
                detail = f"scan {s} · {n} nearby" if n else f"scan {s} · none nearby"
            elif stage == "connecting":
                detail = st.get("device") or "pairing"
            elif stage == "bluetooth_off":
                detail = "turn Bluetooth on"
            elif stage == "no_permission":
                detail = "see console hint"
            elif stage == "no_bleak":
                detail = "pip install bleak"
            elif stage == "old_firmware":
                detail = "re-flash the ESP32"

        label, dot, txt = self._CTRL_LOOK.get(stage, self._CTRL_LOOK["error"])
        return stage, label, detail, dot, txt

    def _draw_controller_monitor(self, surface, sw, top_y):
        """Compact always-visible ESP32 status block, now positioned right
        under the profile card (top-anchored -- grows downward from `top_y`)
        so it reads ABOVE Active Patient. Tapping it forces a fresh BLE scan.
        Returns the y just below the block for whatever comes next."""
        H = self.HEIGHT
        stage, _label, _detail, _dot_col, _txt_col = self._controller_status()

        # "actively searching for or attempting to connect" covers both the
        # scan loop and an in-progress pairing attempt.
        if stage in ("scanning", "connecting"):
            asset = "controller_search.png"
        elif stage == "connected":
            asset = "controller_connected.png"
        else:
            asset = "controller_not_connected.png"

        # Use the sidebar's width effectively (small, consistent margin each
        # side) and let the height follow from the asset's own aspect ratio
        # instead of capping it to a short fixed box -- a fixed ~60px cap is
        # what was making it render small with empty space on either side on
        # a wide sidebar. All three assets share the same aspect ratio, so
        # this box is identical regardless of which one is showing.
        margin = self._sc(10)
        max_w  = max(1, sw - margin * 2)
        img = _img_fit(asset, max_w, max_w)   # tall allowance; width binds
        if img is not None:
            w, h = img.get_size()
        else:
            w, h = max_w, self._tt(60) if self._touch_ui else int(60 * H / 1080)
        r = pygame.Rect(sw // 2 - w // 2, top_y, w, h)
        self._ctrl_btn_rect = r

        if img is not None:
            surface.blit(img, r.topleft)
            # Searching-only shimmer -- a soft moving highlight, stopped the
            # instant the stage leaves "scanning"/"connecting" (Connected and
            # Not Connected never animate). Clipped to this exact asset's own
            # opaque shape, so the card's size/corners/icon/colors are all
            # otherwise untouched.
            if stage in ("scanning", "connecting"):
                mask_surf = _shimmer_mask(asset, w, h)
                _draw_shimmer(surface, r, mask_surf, pygame.time.get_ticks())
        return r.bottom

    def _share_icon(self, surface, cx, cy, s, col):
        """A right-pointing arrow whose shaft arches gently upward -- 'send this
        patient onward to another therapist'. Icon-only, vector-drawn to match
        the rest of the RecovR glyphs."""
        lw = max(2, int(s * 0.16))
        # shaft: quadratic Bezier from the left, bowed upward, meeting the tip
        tip = (cx + s * 0.92, cy - s * 0.16)          # tip -- a hair above centre
        p0  = (cx - s * 0.98, cy + s * 0.10)
        p1  = (cx - s * 0.05, cy - s * 0.88)          # control -> the upward arch
        p2  = (tip[0] - s * 0.28, tip[1] + s * 0.04)
        pts = []
        for i in range(15):
            t = i / 14.0
            u = 1.0 - t
            pts.append((int(u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0]),
                        int(u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1])))
        pts.append((int(tip[0]), int(tip[1])))
        pygame.draw.lines(surface, col, False, pts, lw)
        # arrowhead -- points to the RIGHT (wings back toward upper-left / lower-left)
        hl, hw = s * 0.58, s * 0.52
        pygame.draw.line(surface, col, (int(tip[0]), int(tip[1])),
                         (int(tip[0] - hl), int(tip[1] - hw)), lw)
        pygame.draw.line(surface, col, (int(tip[0]), int(tip[1])),
                         (int(tip[0] - hl), int(tip[1] + hw)), lw)

    def _sun_moon_icon(self, surface, cx, cy, s, dark, col):
        """Small ☀ (light selected) / ☾ (dark selected) glyph."""
        if dark:
            pygame.draw.circle(surface, col, (cx, cy), s, 2)
            pygame.draw.circle(surface, (236, 242, 250), (cx + int(s * 0.55), cy - int(s * 0.35)),
                               int(s * 0.85))
        else:
            pygame.draw.circle(surface, col, (cx, cy), int(s * 0.6), 2)
            for k in range(8):
                import math
                a = k * math.pi / 4
                x1 = cx + int(math.cos(a) * s * 0.85); y1 = cy + int(math.sin(a) * s * 0.85)
                x2 = cx + int(math.cos(a) * s * 1.15); y2 = cy + int(math.sin(a) * s * 1.15)
                pygame.draw.line(surface, col, (x1, y1), (x2, y2), 2)

    # ──────────────────────────────────────────────────────────────────
    #  HOME
    # ──────────────────────────────────────────────────────────────────

    def _draw_home(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mx   = self.sidebar_w + int(24*(W/1920))
        wc_y = int(H*0.05)
        wname = self.account["full_name"].split()[0]
        surface.blit(self.fnt["welcome"].render(f"Welcome back, {wname} 👋",True,(75,135,200)),(mx,wc_y))
        surface.blit(self.fnt["dash_title"].render("Dashboard",True,(28,42,62)),(mx,wc_y+int(48*(H/1080))))
        for i, card in enumerate(HOME_CARDS):
            self._draw_home_card(surface, self.card_rects[i], card, HOME_COLORS[i],
                                 self.card_hovered[i])

    def _draw_home_card(self, surface, rect, card, color, hovered):
        H, W = self.HEIGHT, self.WIDTH
        lift = int(5*(H/1080)) if hovered else 0
        dr   = pygame.Rect(rect.x, rect.y-lift, rect.width, rect.height)
        sh   = pygame.Surface((dr.width,dr.height), pygame.SRCALPHA)
        sh.fill((0,0,0,22 if hovered else 10)); surface.blit(sh, (dr.x+3,dr.y+6))
        _card_bg(surface, dr, alpha=228,
                 border_col=color if hovered else (215,222,232),
                 border_w=2 if hovered else 1)
        pygame.draw.rect(surface, color,
                         pygame.Rect(dr.x, dr.y+int(14*H/1080), int(4*W/1920),
                                     dr.height-int(28*H/1080)), border_radius=3)
        sym = self.fnt["card_sym"].render(card["symbol"], True, color)
        surface.blit(sym, sym.get_rect(center=(dr.centerx, dr.centery-int(20*H/1080))))
        words = card["label"].split()
        mid   = max(1, len(words)//2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words)>2 else [card["label"],""]
        lh    = self.fnt["card_lbl"].get_linesize()
        ly    = dr.centery + int(14*H/1080)
        for ln in lines:
            if ln:
                s = self.fnt["card_lbl"].render(ln, True, (42,58,80))
                surface.blit(s, s.get_rect(center=(dr.centerx, ly))); ly += lh

    # ──────────────────────────────────────────────────────────────────
    #  PANEL SHELL
    # ──────────────────────────────────────────────────────────────────

    def _draw_panel_shell(self, surface, idx):
        pa   = self._panel_area()
        W, H = self.WIDTH, self.HEIGHT

        hdr_h = max(int(50*(H/1080)), self._tt(46))
        hdr = pygame.Rect(pa.x, pa.y-hdr_h-int(10*(H/1080)), pa.width, hdr_h)

        if idx in (4, 5, 6, 7, 8):
            back_w = max(int(140*(W/1920)), self._tt(128))
            back_r = pygame.Rect(hdr.x, hdr.y, back_w, hdr.height)
            back_img = _img_fit("back_button_therapist.png", back_r.width, back_r.height)
            if back_img is not None:
                surface.blit(back_img, back_img.get_rect(center=back_r.center))
            else:
                glass_back = pygame.Surface((back_r.width, back_r.height), pygame.SRCALPHA)
                glass_back.fill((225, 238, 255, 180)); surface.blit(glass_back, back_r.topleft)
                pygame.draw.rect(surface, (150,180,215), back_r, 2, border_radius=8)
                bs = self.fnt["btn"].render("Back", True, (60,100,165))
                surface.blit(bs, bs.get_rect(center=back_r.center))
            self._back_btn_rect = back_r
            crumb_x = back_r.right + int(20*(W/1920))
        else:
            self._back_btn_rect = pygame.Rect(0, 0, 1, 1)
            crumb_x = hdr.x + int(12*(W/1920))

        crumbs = self._breadcrumb(idx)          # list of (label, target|None)
        self._crumb_rects = []
        # on the 7-inch panel the chain must not clip -> smaller crumb font,
        # tight separators, big (full-height) hit rects still.
        cf   = self.fnt["breadcrumb"] if self._touch_ui else self.fnt["breadcrumb"]
        sep_f = self.fnt["breadcrumb"]
        sep_txt = " › " if self._touch_ui else "  ›  "
        cx   = crumb_x
        last = len(crumbs) - 1
        for j, (label, target) in enumerate(crumbs):
            clickable = target is not None          # any crumb with a target navigates
            if clickable:
                col = (55, 110, 185)
            else:
                col = (26, 40, 60) if j == last else (135, 150, 175)
            cs = cf.render(label, True, col)
            tx = cx
            ty = hdr.centery - cs.get_height() // 2
            surface.blit(cs, (tx, ty))
            if clickable:
                pygame.draw.line(surface, col, (tx, ty + cs.get_height() + 1),
                                 (tx + cs.get_width(), ty + cs.get_height() + 1), 2)
                hit = pygame.Rect(tx - int(8*W/1920), hdr.y,
                                  cs.get_width() + int(16*W/1920), hdr.height)
                self._crumb_rects.append((hit, target))
            cx += cs.get_width()
            if j < last:
                sp = sep_f.render(sep_txt, True, (180, 195, 215))
                surface.blit(sp, (cx, hdr.centery - sp.get_height() // 2))
                cx += sp.get_width()

    # Breadcrumb items as (label, target). target: None = current page (not
    # clickable); ("panel", n) = open panel n; ("patient", pt) = open that
    # patient's page (panel 8). There is NO "Preview" level any more.
    def _breadcrumb(self, idx):
        # Abbreviate only when the header is genuinely narrow (the 7-inch panel).
        # A 1280-wide touch laptop keeps the full labels.
        t = self.WIDTH <= 1080
        L_GC   = "Game Config" if t else "Game Configuration"
        L_SS   = "Start" if t else "Start Session"
        L_SIP  = "Session" if t else "Session in Progress"
        # The leading "Patient List" crumb (beside the Back button) has been
        # removed -- Back already returns there, so naming the page a second
        # time was redundant. Every other crumb/level is unchanged.
        if idx == 6:
            return [("Register" if t else "Register Patient", None)]
        if idx == 8:
            name = (self.preview_patient or {}).get("full_name", "Patient")
            crumbs = [(self._crumb_name(name), None)]
            # Game Configuration stays reachable as long as a patient is selected
            # -- from Info / Analytics / Calibration / Session History alike.
            if self.selected_patient:
                crumbs.append((L_GC, ("panel", 4)))
            return crumbs
        sel = self.selected_patient or {}
        pt_crumb = (self._crumb_name(sel.get("full_name", "Patient")),
                    ("patient", sel) if sel else None)
        if idx == 4:
            return [pt_crumb, (L_GC, None)]
        if idx == 5:
            return [pt_crumb, (L_GC, ("panel", 4)), (L_SS, None)]
        if idx == 7:
            # Active session: breadcrumb is display-only. Leaving a running
            # session goes through the panel-7 Back / STOP flow so nothing is
            # left stale.
            return [(self._crumb_name(sel.get("full_name", "Patient")), None),
                    (L_GC, None), (L_SIP, None)]
        return [(PANEL_TITLES.get(idx, ""), None)]

    def _crumb_name(self, name):
        name = (name or "Patient").strip() or "Patient"
        limit = 13 if self.WIDTH <= 1080 else 22
        return name if len(name) <= limit else name[:limit - 1] + "…"

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 0: PATIENT LIST
    # ──────────────────────────────────────────────────────────────────

    def _draw_patient_list(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=130)
        self._patient_rows = []
        self._back_btn_rect = pygame.Rect(0, 0, 1, 1)   # panel 0 has no Back
        self._crumb_rects   = []                        # ... and no breadcrumb

        touch   = self._touch_ui
        pad     = int(16*W/1920)
        # Extra left inset for the "Patient List" column header and each row's
        # name text specifically (not the search bar/Register button, which
        # keep the tighter `pad`) -- flush against the card's rounded left
        # edge looked cramped.
        list_pad = pad + self._sc(20)
        head_y = self._bar_top() if touch else (pa.y + int(10*H/1080))
        # Touch: cut the old 20px top gap down to a minimal 8px -- the 7-inch
        # panel can't spare more than that above the header row.
        title_top = (pa.y + self._sc(8)) if touch else head_y

        if touch:
            # ── 800x480 LCD: compact header (title + Register on one row),
            # no subtitle, no stat cards -- the patient list needs the
            # vertical room those used to consume far more than this screen
            # can afford (see git history: previously only ~1 row visible).
            f_title = self.fnt["panel_title"]
            title_s = f_title.render("Patient Management", True, (38, 52, 78))

            reg_h = self._sc(40)
            reg_text_w = self.fnt["small"].size("+ Register Patient")[0]
            reg_w = max(self._sc(120), min(reg_text_w + self._sc(26),
                        pa.width - pad*2 - title_s.get_width() - self._sc(16)))
            reg_x = pa.right - pad - reg_w
            header_row_h = max(title_s.get_height(), reg_h)

            surface.blit(title_s, (pa.x+pad, title_top + (header_row_h - title_s.get_height())//2))
            reg_r = pygame.Rect(reg_x, title_top + (header_row_h - reg_h)//2, reg_w, reg_h)
            # Drawn ~13% smaller than the touch target itself (centered), so
            # the icon/button reads slightly less oversized while the tap
            # area stays exactly the same comfortable size as before.
            reg_draw_r = reg_r.inflate(-int(reg_r.width * 0.13), -int(reg_r.height * 0.13))
            _img_btn(surface, reg_draw_r, "reg_pat_therapist.png", True, self.register_link_hov,
                    "+ Register", self.fnt["small"],
                    col_normal=(20,150,165), radius=int(reg_h*0.3))
            self._register_link_rect = reg_r

            # ── Total Patients / Assigned to Me -- a single compact inline
            # line (not the desktop stat cards, which this 7-inch panel
            # can't spare the height for) so both counters are restored
            # without taking back the vertical room freed up for the
            # patient list rows. Real DB values, same ownership rule the
            # desktop stat cards use below.
            total_n    = len(self.patients)
            assigned_n = sum(1 for p in self.patients
                             if p.get("therapist_id") == self.account["id"])
            f_stat   = self.fnt["eyebrow"]
            stats_y  = title_top + header_row_h + self._sc(3)
            stat_s   = f_stat.render(
                f"Total Patients: {total_n}      Assigned to Me: {assigned_n}",
                True, (105, 122, 148))
            surface.blit(stat_s, (pa.x+pad, stats_y))
            stats_h  = stat_s.get_height() + self._sc(5)

            # ── Compact search bar, immediately below the header row ────
            sb_h = self._sc(42)   # ~38-42px at the 7-inch panel's own scale
            search_y = title_top + header_row_h + stats_h + self._sc(6)
            hint_r = pygame.Rect(pa.x+pad, search_y, pa.width - pad*2, sb_h)
            self._pt_search_rect = hint_r
            s_active = self._pt_search_active
            pygame.draw.rect(surface, (248,251,255), hint_r, border_radius=int(sb_h*0.4))
            s_border = (40,160,220) if s_active else (195,210,228)
            pygame.draw.rect(surface, s_border, hint_r, 2 if s_active else 1, border_radius=int(sb_h*0.4))
            # Enlarged (was self._sc(5)) -- noticeably bigger magnifying-glass,
            # still vertically centered in the bar and left-padded the same
            # way; text_x is derived from gr so it keeps clearing the icon.
            gr = max(4, self._sc(8))
            gcx, gcy = hint_r.x + self._sc(12) + gr, hint_r.centery - int(gr*0.3)
            pygame.draw.circle(surface, (150, 168, 190), (gcx, gcy), gr, max(1, self._sc(3)))
            pygame.draw.line(surface, (150, 168, 190),
                             (gcx + int(gr*0.7), gcy + int(gr*0.7)),
                             (gcx + int(gr*1.6), gcy + int(gr*1.6)), max(1, self._sc(3)))
            text_x = gcx + int(gr*1.6) + self._sc(8)
            _ty = hint_r.y + (sb_h - self.fnt["input"].get_height()) // 2
            s_text = self._pt_search_text
            if s_text:
                s_surf = self.fnt["input"].render(s_text, True, (40, 55, 75))
                surface.blit(s_surf, (text_x, _ty))
                if s_active:
                    cx_s = text_x + s_surf.get_width() + 2
                    pygame.draw.line(surface, (40,160,220),
                                     (cx_s, hint_r.y+self._sc(6)),
                                     (cx_s, hint_r.bottom-self._sc(6)), 2)
            else:
                ph_txt = "Search patient" if not s_active else ""
                surface.blit(self.fnt["input"].render(ph_txt, True, (170,185,205)),
                             (text_x, _ty))

            hdr_y = hint_r.bottom + self._sc(10)

        else:
            # ── Desktop: unchanged -- title + subtitle, Total Patients /
            # Assigned to Me stat cards, Register Patient, search bar ────
            f_title = self.fnt["panel_title"]
            title_s = f_title.render("Patient Management", True, (38, 52, 78))
            max_title_w = pa.width - pad * 2
            if title_s.get_width() > max_title_w:
                scale = max_title_w / title_s.get_width()
                title_s = pygame.transform.smoothscale(
                    title_s, (max(1, int(title_s.get_width()*scale)),
                              max(1, int(title_s.get_height()*scale))))
            surface.blit(title_s, (pa.x+pad, title_top))

            sub_y = title_top + title_s.get_height() + self._sc(2)
            sub_s = self.fnt["body"].render(
                "Search, select, or register a patient to start a rehabilitation session.",
                True, (126, 142, 166))
            if sub_s.get_width() > max_title_w:
                scale = max_title_w / sub_s.get_width()
                sub_s = pygame.transform.smoothscale(
                    sub_s, (max(1, int(sub_s.get_width()*scale)),
                            max(1, int(sub_s.get_height()*scale))))
            surface.blit(sub_s, (pa.x+pad, sub_y))

            # ── Stat cards (Total Patients / Assigned to Me) + Register Patient,
            #    one row, above the search bar ───────────────────────────────
            stats_y  = sub_y + sub_s.get_height() + self._sc(16)
            stat_h   = self._tt(78)
            card_gap = self._sc(14)

            total_n    = len(self.patients)
            assigned_n = sum(1 for p in self.patients
                             if p.get("therapist_id") == self.account["id"])

            # Register Patient is sized to its own text content (not stretched
            # to fill leftover space) and anchored flush to the panel's right
            # edge -- it's placed first so the stat cards below can never push
            # it past that edge.
            reg_text_w = self.fnt["btn"].size("+ Register Patient")[0]
            reg_w  = min(reg_text_w + self._sc(40), pa.width - pad*2)
            reg_x  = max(pa.x+pad, pa.right - pad - reg_w)

            # Card width is sized from its own content (icon + widest possible
            # label) rather than a fixed fraction of the panel, so the text
            # always has room regardless of screen size/font scale -- but never
            # wider than the row actually has left after the button, so the
            # pair can't push into (or past) it either.
            icon_sz      = stat_h - self._sc(22)
            icon_pad_l   = self._sc(11)
            icon_txt_gap = self._sc(12)
            card_pad_r   = self._sc(16)
            # Was fnt["empty_head"] (Sora) -- the matching stat-value font on the
            # Analytics screen is Lexend; fnt["btn_lg"] (Lexend-Bold, previously
            # unused) gives the same bold prominence in that same family instead.
            f_val, f_lbl = self.fnt["btn_lg"], self.fnt["label"]
            text_w = max(f_lbl.size("Total Patients")[0], f_lbl.size("Assigned to Me")[0],
                         f_val.size("99")[0])
            ideal_card_w = icon_pad_l + icon_sz + icon_txt_gap + text_w + card_pad_r
            cards_avail  = (reg_x - card_gap) - (pa.x+pad)
            # Floor includes the icon-to-text gap and a minimum text allowance --
            # not just the icon -- so avail_w below can never work out negative
            # (which would push the label past the card's own right edge).
            min_card_w = icon_pad_l + icon_sz + icon_txt_gap + self._sc(40) + card_pad_r
            card_w = max(min_card_w, min(ideal_card_w, (cards_avail - card_gap) // 2))

            def _stat_card(x, icon_name, value, label):
                r = pygame.Rect(x, stats_y, card_w, stat_h)
                _card_bg(surface, r, alpha=255, radius=14, border_col=(222,232,245))
                icon_x = r.x + icon_pad_l
                icon_y = r.y + (stat_h - icon_sz)//2
                # _img_fit crops to the icon's own (square) opaque content first,
                # instead of squashing its wider padded canvas into a square --
                # keeps the icon's true square proportions undistorted.
                img = _img_fit(icon_name, icon_sz, icon_sz)
                if img is not None:
                    surface.blit(img, img.get_rect(center=(icon_x+icon_sz//2, icon_y+icon_sz//2)))
                txt_x   = icon_x + icon_sz + icon_txt_gap
                # True remaining room (no artificial floor) -- an avail_w that
                # lies about having space is exactly what let labels spill past
                # the card edge before.
                avail_w = max(1, r.right - self._sc(8) - txt_x)
                vs = f_val.render(str(value), True, (24, 36, 58))
                if vs.get_width() > avail_w:
                    scale = avail_w / vs.get_width()
                    vs = pygame.transform.smoothscale(
                        vs, (max(1, int(vs.get_width()*scale)),
                             max(1, int(vs.get_height()*scale))))
                ls = f_lbl.render(label, True, (120, 136, 160))
                if ls.get_width() > avail_w:
                    scale = avail_w / ls.get_width()
                    ls = pygame.transform.smoothscale(
                        ls, (max(1, int(ls.get_width()*scale)),
                             max(1, int(ls.get_height()*scale))))

                # Vertically fit the number+label stack inside the card height --
                # shrink both together (same ratio, so one doesn't dwarf the
                # other) only if they don't fit at full size, then center the
                # whole stack so neither line is ever pushed past the card's own
                # top/bottom edge the way a fixed top offset could.
                pad_v   = self._sc(6)
                gap_v   = self._sc(2)
                avail_h = max(1, stat_h - pad_v * 2)
                stack_h = vs.get_height() + gap_v + ls.get_height()
                if stack_h > avail_h:
                    vscale = avail_h / stack_h
                    vs = pygame.transform.smoothscale(
                        vs, (max(1, int(vs.get_width()*vscale)),
                             max(1, int(vs.get_height()*vscale))))
                    ls = pygame.transform.smoothscale(
                        ls, (max(1, int(ls.get_width()*vscale)),
                             max(1, int(ls.get_height()*vscale))))
                    stack_h = vs.get_height() + gap_v + ls.get_height()
                start_y = r.y + (stat_h - stack_h) // 2
                surface.blit(vs, (txt_x, start_y))
                surface.blit(ls, (txt_x, start_y + vs.get_height() + gap_v))
                return r.right

            _stat_card(pa.x+pad, "total_patients.png", total_n, "Total Patients")
            _stat_card(pa.x+pad+card_w+card_gap, "assigned_to_me.png", assigned_n, "Assigned to Me")

            # Register Patient -- far right of the row, flush with the panel's
            # own right edge; it can't extend past it (reg_x/reg_w computed above).
            reg_r = pygame.Rect(reg_x, stats_y, reg_w, stat_h)
            _img_btn(surface, reg_r, "reg_pat_therapist.png", True, self.register_link_hov,
                    "+ Register Patient", self.fnt["btn"],
                    col_normal=(20,150,165), radius=int(stat_h*0.3))
            self._register_link_rect = reg_r

            top_y = stats_y + stat_h + self._sc(18)

            sb_h    = self._tt(60)
            # Now spans most of the row -- the Register Patient button moved up
            # into the stat-card row above, so it no longer has to share this one.
            hint_w  = int(pa.width * 0.62)
            hint_r  = pygame.Rect(pa.x+pad, top_y, hint_w, sb_h)
            self._pt_search_rect = hint_r
            s_active = self._pt_search_active
            pygame.draw.rect(surface, (248,251,255), hint_r, border_radius=int(sb_h*0.4))
            s_border = (40,160,220) if s_active else (195,210,228)
            pygame.draw.rect(surface, s_border, hint_r, 2 if s_active else 1, border_radius=int(sb_h*0.4))
            # a small drawn magnifying-glass (no font-glyph dependency)
            gr = max(3, self._sc(6))
            gcx, gcy = hint_r.x + int(16*W/1920) + gr, hint_r.centery - int(gr*0.3)
            pygame.draw.circle(surface, (150, 168, 190), (gcx, gcy), gr, max(1, self._sc(2)))
            pygame.draw.line(surface, (150, 168, 190),
                             (gcx + int(gr*0.7), gcy + int(gr*0.7)),
                             (gcx + int(gr*1.6), gcy + int(gr*1.6)), max(1, self._sc(2)))
            text_x = gcx + int(gr*1.6) + int(10*W/1920)
            _ty = hint_r.y + (sb_h - self.fnt["input"].get_height()) // 2
            s_text = self._pt_search_text
            if s_text:
                s_surf = self.fnt["input"].render(s_text, True, (40, 55, 75))
                surface.blit(s_surf, (text_x, _ty))
                if s_active:
                    cx_s = text_x + s_surf.get_width() + 2
                    pygame.draw.line(surface, (40,160,220),
                                     (cx_s, hint_r.y+int(10*H/1080)),
                                     (cx_s, hint_r.bottom-int(10*H/1080)), 2)
            else:
                ph_txt = "Search patient" if not s_active else ""
                surface.blit(self.fnt["input"].render(ph_txt, True, (170,185,205)),
                             (text_x, _ty))

            hdr_y  = hint_r.bottom + int(20*H/1080)
        # Columns: just Name on the 7-inch panel -- Therapist/ownership moved
        # to Patient -> Info -> Record (everything else already lived on the
        # patient's own page); the full set (desktop only) still shows it.
        if touch:
            cols   = ["Patient List"]
            col_xs = [pa.x+list_pad]
        else:
            cols   = ["Patient List", "Patient ID", "Therapist", ""]
            # Patient ID pushed further right of Patient Name -- more room
            # before a longer name could run into it.
            col_xs = [pa.x+int(16*W/1920),  pa.x+int(480*W/1920),
                      pa.x+int(940*W/1920), pa.x+int(1160*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c,True,(85,105,135)), (cx, hdr_y))
        pygame.draw.line(surface, (200,212,228),
                         (pa.x+pad, hdr_y+self.fnt["section"].get_height()+int(6*H/1080)),
                         (pa.right-pad, hdr_y+self.fnt["section"].get_height()+int(6*H/1080)), 1)

        q = self._pt_search_text.strip().lower()
        visible_patients = [p for p in self.patients
                            if not q or q in p.get("full_name","").lower()
                            or q in p.get("patient_id_str","").lower()]

        if not self.patients or not visible_patients:
            self._pl_scroll_max = 0
            self._pl_up_rect = self._pl_down_rect = pygame.Rect(0, 0, 1, 1)
            icon, head, sub = (("👤", "No patients registered yet",
                                'Tap "+ Register Patient" above to add your first patient.')
                               if not self.patients else
                               ("🔍", f'No results for "{self._pt_search_text}"',
                                "Try a different name or patient ID."))
            _empty_state(surface,
                         pygame.Rect(pa.x, hdr_y+int(30*H/1080), pa.width,
                                     pa.bottom-hdr_y-int(60*H/1080)),
                         icon, head, sub, self.fnt["empty_head"], self.fnt["small_i"])
            return

        # ── scrollable row area ─────────────────────────────────────
        list_top    = hdr_y + self.fnt["section"].get_height() + int(14*H/1080)
        list_bottom = pa.bottom - int(10*H/1080)
        view_h      = list_bottom - list_top
        # Touch: compact 48-54px rows (was 84px, the single biggest cause of
        # the list only fitting ~1 full row on the real 800x480 panel).
        row_h       = self._tt(54) if touch else int(72*H/1080)
        content_h   = len(visible_patients) * row_h
        self._pl_scroll_max = max(0, content_h - view_h)
        self._pl_scroll     = max(0, min(self._pl_scroll, self._pl_scroll_max))
        scrollable          = self._pl_scroll_max > 0

        arrow_w = self._tt(50) if scrollable else 0
        # keep a clear gap between the Share icons and the scroll arrows.
        # (_sc, not _tt -- this is spacing, not a tap target: _tt would floor to 50 px
        #  and squeeze the Therapist column out of the row.)
        arrow_gap = self._sc(16) if (scrollable and touch) else 0
        btn_x_r = pa.right - pad - arrow_w - arrow_gap   # right edge available to Share icon
        bgap    = self._tt(18) if touch else int(10*W/1920)
        f_name  = self.fnt["body_b"] if touch else self.fnt["body"]
        f_ther  = self.fnt["body"]   if touch else self.fnt["tag"]

        mp = pygame.mouse.get_pos()
        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, list_top, pa.width-2, view_h))
        for k, pt in enumerate(visible_patients):
            ry = list_top + k*row_h - self._pl_scroll
            if ry + row_h <= list_top or ry >= list_bottom:
                continue

            is_owner = (pt.get("therapist_id") == self.account["id"])
            if is_owner:
                ther_label, ther_col = self.account.get("full_name", "You"), (46, 150, 95)
            else:
                _o = self.db.get_therapist_by_id(pt.get("therapist_id"))
                ther_label = _o["full_name"] if _o else "Unknown"
                ther_col = (55, 120, 215)

            # zebra fill + a clean full-width divider under each row
            if k % 2 == 1:
                bg = pygame.Surface((pa.width - 2*pad, row_h), pygame.SRCALPHA)
                bg.fill((236, 243, 255, 150)); surface.blit(bg, (pa.x + pad, ry))
            pygame.draw.line(surface, (208, 218, 234),
                             (pa.x + pad, ry + row_h), (pa.right - pad, ry + row_h), 1)

            # Share button -- the ONLY right-side action. Large touch target,
            # clearly separated from the name.
            ic = self._tt(52)
            shr_r = pygame.Rect(btn_x_r - ic, ry + (row_h - ic)//2, ic, ic)
            right_x = shr_r.x - bgap

            # Patient name -- the primary tap target (opens the patient's
            # page; does NOT select). The "SELECTED" pill is gone -- the
            # currently-selected patient's name turns blue instead (readable
            # in both themes; ownership/sharing no longer tints it at all).
            name_val = pt.get("full_name", "—")
            name_r = pygame.Rect(pa.x + pad, ry, right_x - (pa.x + pad), row_h)
            # Clamp the hit area to the visible list band: a row scrolled
            # half-off must not be tappable in the space below the list.
            hit_r = name_r.clip(pygame.Rect(pa.x, list_top, pa.width,
                                            list_bottom - list_top))
            # Only register a scrolled-partial row as tappable once a real
            # touch-sized sliver of it is showing -- a few stray pixels
            # peeking past the edge must not become an undersized tap target.
            if hit_r.height >= self._tt(44):
                self._patient_rows.append((hit_r, pt, "name"))
            n_col = (35, 110, 220) if self._is_selected(pt) else (34, 46, 66)
            if name_r.collidepoint(mp):
                n_col = tuple(min(255, c + 25) for c in n_col)

            # Small patient icon immediately before the name, vertically
            # centered on the row -- same spot the name used to start at;
            # the name itself now starts after it, with a little breathing
            # room so the two don't crowd together.
            icon_d   = min(row_h - self._sc(10), self._sc(42))
            icon_gap = self._sc(8)
            icon_x0  = (pa.x + list_pad) if touch else col_xs[0]
            # _img_fit crops to the icon's own opaque content first, instead
            # of squashing its wider padded canvas into a square -- keeps the
            # icon's true proportions undistorted.
            icon_img = _img_fit("patient_icon_dashboard.png", icon_d, icon_d)
            if icon_img is not None:
                surface.blit(icon_img, icon_img.get_rect(
                    center=(icon_x0 + icon_d//2, ry + row_h//2)))
            text_x0 = icon_x0 + icon_d + icon_gap

            if touch:
                # Ellipsize before the Share button -- the Therapist column
                # is gone, so the name now has the full row width to itself.
                name_x = text_x0
                max_name_w = right_x - self._sc(10) - name_x
            else:
                name_x = text_x0
                max_name_w = col_xs[1] - self._sc(16) - name_x
            fit_name = name_val
            if f_name.size(fit_name)[0] > max_name_w:
                while fit_name and f_name.size(fit_name + "…")[0] > max_name_w:
                    fit_name = fit_name[:-1]
                fit_name = (fit_name + "…") if fit_name else "…"
            ns = f_name.render(fit_name, True, n_col)
            surface.blit(ns, (name_x, ry + (row_h - ns.get_height())//2))

            # Patient ID / Therapist columns -- desktop only now.
            if not touch:
                tya = ry + (row_h - self.fnt["body"].get_height())//2
                pid_val = pt.get("patient_id_str", "—")
                if col_xs[1] + self.fnt["body"].size(str(pid_val))[0] < right_x:
                    surface.blit(self.fnt["body"].render(pid_val, True, (40,55,75)), (col_xs[1], tya))
                if col_xs[2] + self.fnt["tag"].size(ther_label)[0] < right_x:
                    surface.blit(self.fnt["tag"].render(ther_label, True, ther_col), (col_xs[2], tya))

            enabled = is_owner
            hov = shr_r.collidepoint(mp) and enabled
            share_img = _img("share_button.png", ic)
            if share_img is not None:
                if not enabled:
                    share_img = share_img.copy()
                    share_img.set_alpha(100)
                surface.blit(share_img, shr_r.topleft)
            else:
                # fallback if the asset is ever missing -- the original
                # vector-drawn button, unchanged
                if not enabled:
                    shr_col = (170, 174, 184)
                elif hov:
                    shr_col = (110, 168, 235)
                else:
                    shr_col = (90, 150, 220)
                pygame.draw.rect(surface, shr_col, shr_r, border_radius=12)
                self._share_icon(surface, shr_r.centerx, shr_r.centery,
                                 int(ic * 0.32), (255, 255, 255))
            if enabled:
                self._patient_rows.append((shr_r, pt, "share"))
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when the list overflows) ────────────
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - pad - arrow_w
            self._pl_up_rect   = pygame.Rect(ax, list_top, arrow_w, ah)
            self._pl_down_rect = pygame.Rect(ax, list_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._pl_up_rect, "▲", self._pl_scroll > 0),
                               (self._pl_down_rect, "▼", self._pl_scroll < self._pl_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
            # thumb
            tb_x = ax + arrow_w + int(4*W/1920)
            track_h = view_h
            th = max(int(28*H/1080), int(track_h * view_h / max(content_h, 1)))
            ty0 = list_top + int((track_h - th) * (self._pl_scroll / self._pl_scroll_max))
            pygame.draw.rect(surface, (150,175,210),
                             pygame.Rect(tb_x, ty0, int(6*W/1920), th), border_radius=3)
        else:
            self._pl_up_rect = self._pl_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  SHARE PATIENT MODAL
    # ──────────────────────────────────────────────────────────────────

    def _draw_share_modal(self, surface):
        """Dispatches to whichever of the three Patient Sharing/Transferring
        popups the current stage needs. All three (and the Share/Transfer
        confirmations, drawn via draw_confirm_dialog) share the same
        draw_dialog_chrome look as every other standardized RecovR
        confirmation popup in this file -- rounded card, dim overlay,
        shadow, icon circle, Poppins type, theme-aware colors -- instead of
        the old hand-rolled flat box this modal used to draw."""
        if self._share_stage == "choice" and self._share_confirm_therapist:
            self._draw_share_select_modal(surface)
        elif self._share_stage == "confirm" and self._share_confirm_therapist:
            self._draw_share_or_transfer_confirm_modal(surface)
        else:
            self._draw_share_search_modal(surface)

    def _draw_share_select_modal(self, surface):
        """"Share Patient" selection popup: Patient / Therapist / "What
        would you like to do?" + SHARE | TRANSFER side by side + one
        centered Cancel underneath. Three buttons don't fit
        draw_confirm_dialog's 1-or-2-button layout, so this uses the shared
        draw_dialog_chrome for the identical card/overlay/icon/title look
        and lays out its own button row. Fixed-size, same as the other
        three Patient Sharing/Transferring popups."""
        W, H = self.WIDTH, self.HEIGHT
        pt_name = (self.share_modal_patient or {}).get("full_name", "Patient")
        t_name  = (self._share_confirm_therapist or {}).get("full_name", "Therapist")
        body = f"Patient: {pt_name}\nTherapist: {t_name}\n\nWhat would you like to do?"

        pad_px, icon_r_px = self._share_header_metrics()
        pad      = self._sc(pad_px)
        btn_h    = self._tt(52)
        cancel_h = self._tt(46)
        gap      = self._sc(22)
        extra_h  = gap + btn_h + gap + cancel_h + self._sc(6)

        mr, content_y, _theme = draw_dialog_chrome(
            surface, W, H, tt=self._tt, sc=self._sc, fonts=self._share_dialog_fonts(),
            icon="info", accent=(60, 140, 220), title="Share Patient", body=body,
            extra_content_h=extra_h, fixed_size=self._share_popup_size(),
            pad_px=pad_px, icon_r_px=icon_r_px)

        content_y += gap
        bw2 = (mr.width - pad * 2 - self._sc(16)) // 2
        self._share_choice_share_rect    = pygame.Rect(mr.x + pad, content_y, bw2, btn_h)
        self._share_choice_transfer_rect = pygame.Rect(
            mr.x + pad + bw2 + self._sc(16), content_y, bw2, btn_h)
        _btn(surface, self._share_choice_share_rect, "SHARE", self.fnt["btn"],
             (40, 160, 90), (28, 130, 70), self._share_choice_share_hov, radius=12)
        _btn(surface, self._share_choice_transfer_rect, "TRANSFER", self.fnt["btn"],
             (215, 140, 30), (180, 112, 15), self._share_choice_transfer_hov, radius=12)
        content_y += btn_h + gap

        cancel_w = self._sc(200)
        self._share_no_rect = pygame.Rect(mr.centerx - cancel_w // 2, content_y,
                                          cancel_w, cancel_h)
        _btn(surface, self._share_no_rect, "Cancel", self.fnt["btn"],
             (160, 175, 195), (130, 148, 168), self._share_no_hov, radius=10)

        # Dead rects for the stages this popup doesn't draw.
        self._share_close_rect = pygame.Rect(0, 0, 1, 1)
        self._share_yes_rect   = pygame.Rect(0, 0, 1, 1)
        self._share_field_rect = pygame.Rect(0, 0, 1, 1)

    def _draw_share_or_transfer_confirm_modal(self, surface):
        """Share Confirmation / Transfer Patient Confirmation -- both are a
        plain title + description (+ detail lines, for Transfer) + two
        buttons, so both go straight through the existing, already-
        standardized draw_confirm_dialog, at the same fixed_size as the
        other two Patient Sharing/Transferring popups, rather than a
        bespoke layout.

        Titles are never truncated -- both repeat the patient/therapist
        names in full and let draw_confirm_dialog's own wrap-then-shrink-
        to-title_small fallback handle an unusually long one (spec:
        "titles should wrap... before considering a small font
        reduction"). Transfer's three labeled detail lines ARE each capped
        to one line (ellipsis, never a smaller font) since those are
        fixed-width label: value rows, not a heading -- wrapping one would
        misalign the whole block. Transfer additionally drops the icon
        (the tinted top band still shows) -- a full warning paragraph plus
        three detail lines under a two-line dynamic title is simply more
        text than fits alongside one at this popup's shared fixed size;
        Share keeps its icon since its body is a single short paragraph
        with room to spare."""
        pt_name = (self.share_modal_patient or {}).get("full_name", "Patient")
        t_name  = (self._share_confirm_therapist or {}).get("full_name", "Therapist")
        cur_name = self.account.get("full_name", "—")
        is_transfer = (self._share_pending_action == "transfer")

        mw, mh = self._share_popup_size()
        pad_px, icon_r_px = self._share_header_metrics()
        pad = self._sc(pad_px)
        max_content_w = mw - pad * 2
        dlg_fonts = self._share_dialog_fonts()
        body_font = dlg_fonts["body"]

        if is_transfer:
            title = f"Transfer {pt_name} with {t_name}?"
            detail = ("You are about to transfer this patient to another therapist. "
                     "After the transfer, you may lose access to the patient's "
                     "account and rehabilitation records. Please verify the "
                     "information below before proceeding.")
            # Each detail line is capped to one line: the widest label
            # ("Receiving Therapist: ") sets how much width is left for the
            # name that follows it. These are fixed label:value rows, not
            # prose, so a truncated name here (not the title, which wraps
            # instead) keeps the block legible rather than forcing a
            # 2nd line that breaks the label/value alignment.
            label_w = body_font.size("Receiving Therapist: ")[0]
            name_budget = max(self._sc(100), max_content_w - label_w)
            details = (
                f"Patient Name: {_truncate_text(pt_name, body_font, name_budget)}\n"
                f"Current Therapist: {_truncate_text(cur_name, body_font, name_budget)}\n"
                f"Receiving Therapist: {_truncate_text(t_name, body_font, name_budget)}")
            # A single newline (not a blank-line double newline) separates
            # the warning paragraph from the detail block -- still a clear
            # visual break (a fresh line of label:value rows right under a
            # paragraph reads as its own group) without spending a full
            # blank line's height this popup's fixed size doesn't have.
            body = f"{detail}\n{details}"
            confirm_label = "Transfer Patient"
            icon, accent = "warning", (215, 140, 30)
            countdown = self._danger_countdown if self._danger_countdown > 0 else None
            show_icon = False
        else:
            title = f"Share {pt_name} with {t_name}?"
            body = ("The receiving therapist will be able to access the patient's "
                    "information and assist with therapy sessions according to their "
                    "shared-patient permissions. They will not become the owner and "
                    "cannot edit the patient's information.")
            confirm_label = "Yes, Share"
            icon, accent = "check", (40, 160, 90)
            countdown = None
            show_icon = True

        cr, xr = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=dlg_fonts, icon=icon, accent=accent,
            title=title, body=body, confirm_label=confirm_label, cancel_label="Cancel",
            confirm_hov=self._share_yes_hov, cancel_hov=self._share_no_hov,
            countdown=countdown, show_icon=show_icon, fixed_size=(mw, mh),
            pad_px=pad_px, icon_r_px=icon_r_px)
        self._share_yes_rect, self._share_no_rect = cr, xr

        # Dead rects for the stages this popup doesn't draw.
        self._share_close_rect           = pygame.Rect(0, 0, 1, 1)
        self._share_choice_share_rect    = pygame.Rect(0, 0, 1, 1)
        self._share_choice_transfer_rect = pygame.Rect(0, 0, 1, 1)
        self._share_field_rect           = pygame.Rect(0, 0, 1, 1)

    def _draw_share_search_modal(self, surface):
        """Therapist username search popup (the "pick" stage): title +
        patient name/ID, a "Share with:" input filling the available
        width, live suggestions (or an empty-state hint), a two-column
        "currently shared with" list (name/username left, a fixed-width
        Revoke column right, scrollable when it has more rows than fit),
        and a single Close button -- all at this family's shared fixed
        outer size."""
        W, H = self.WIDTH, self.HEIGHT
        pad_px, icon_r_px = self._share_header_metrics()
        pad   = self._sc(pad_px)
        fh    = self._tt(46)
        btn_h = self._tt(50)
        lbl_h = self.fnt["small"].get_height()

        from constants import is_dark_mode
        dark = is_dark_mode()
        if dark:
            label_col, muted_col = (180, 194, 216), (150, 164, 188)
            input_bg, input_bdr = (36, 46, 66), (70, 86, 112)
            input_text_col, input_ph_col = (225, 232, 244), (120, 134, 156)
            sugg_bg, sugg_bg_hov, sugg_bdr = (36, 46, 66), (48, 62, 90), (70, 86, 112)
            sugg_text_col = (140, 180, 255)
            shared_label_col, shared_text_col = (160, 174, 198), (205, 215, 232)
        else:
            label_col, muted_col = (80, 95, 115), (155, 168, 188)
            input_bg, input_bdr = (248, 252, 255), (40, 160, 220)
            input_text_col, input_ph_col = (40, 50, 65), (175, 188, 205)
            sugg_bg, sugg_bg_hov, sugg_bdr = (248, 252, 255), (206, 228, 255), (190, 212, 238)
            sugg_text_col = (40, 75, 140)
            shared_label_col, shared_text_col = (85, 105, 135), (50, 65, 90)

        pt_name = (self.share_modal_patient or {}).get("full_name", "Patient")
        pt_id   = (self.share_modal_patient or {}).get("patient_id_str", "")
        disp    = self._share_input

        mw, mh = self._share_popup_size()
        dlg_fonts = self._share_dialog_fonts()
        max_content_w = mw - pad * 2

        # Truncate the NAME, never the ID -- RCVR-#### is short, fixed-width,
        # and the more reliable identifier when a name is this long anyway.
        id_suffix = f" · {pt_id}" if pt_id else ""
        name_budget = max_content_w - dlg_fonts["body"].size(id_suffix)[0]
        subtitle = _truncate_text(pt_name, dlg_fonts["body"], name_budget) + id_suffix

        mr, content_y, _theme = draw_dialog_chrome(
            surface, W, H, tt=self._tt, sc=self._sc, fonts=dlg_fonts,
            icon="info", accent=(60, 140, 220), title="Share Patient",
            body=subtitle, fixed_size=(mw, mh), pad_px=pad_px, icon_r_px=icon_r_px)

        content_y += self._sc(8)

        # "Share with:" label sits INLINE to the left of the input (one row,
        # not two) -- this popup already has a label, an input, live
        # suggestions AND a shared-with list to fit in a fixed-height card;
        # a label row of its own was the single biggest reclaimable chunk.
        lbl_s = self.fnt["small"].render("Share with:", True, label_col)
        lbl_w = lbl_s.get_width() + self._sc(10)
        row_r = pygame.Rect(mr.x + pad, content_y, mr.width - pad * 2, fh)
        surface.blit(lbl_s, lbl_s.get_rect(midleft=(row_r.x, row_r.centery)))
        sf_r = pygame.Rect(row_r.x + lbl_w, row_r.y, row_r.width - lbl_w, fh)
        pygame.draw.rect(surface, input_bg, sf_r, border_radius=12)
        pygame.draw.rect(surface, input_bdr, sf_r, 2, border_radius=12)
        ts_inp = (self.fnt["input"].render(disp, True, input_text_col) if disp
                  else self.fnt["input"].render("Enter username", True, input_ph_col))
        surface.blit(ts_inp, ts_inp.get_rect(midleft=(sf_r.x + self._sc(12), sf_r.centery)))
        if disp:
            curs_x = sf_r.x + self._sc(12) + ts_inp.get_width() + 2
            pygame.draw.line(surface, input_bdr,
                             (curs_x, sf_r.centery - self._sc(10)),
                             (curs_x, sf_r.centery + self._sc(10)), 2)
        self._share_field_rect = sf_r
        content_y = row_r.bottom + self._sc(8)

        close_top = mr.bottom - btn_h - pad          # everything must stay above this

        # ── Live suggestions take over the rest of the card while active --
        # an autocomplete list and the persistent "currently shared with"
        # list both wanting room at once is exactly what squeezed the
        # shared-with viewport down to nothing (or a row clipped mid-
        # height) before: while the therapist is actively typing a new
        # username, seeing who the patient is ALREADY shared with isn't
        # the priority, so suggestions get the full remaining height and
        # the shared-with section simply isn't drawn for that one frame
        # (it reappears the moment the input is cleared or a suggestion is
        # picked -- nothing about the list itself changes). ──────────────
        self._share_sugg_rects = []
        self._unshare_rects = []
        if self._share_suggestions:
            self._share_shared_viewport = pygame.Rect(0, 0, 1, 1)
            opt_h = self._tt(44)
            max_sugg_rows = 4
            for i, t in enumerate(self._share_suggestions[:max_sugg_rows]):
                sr = pygame.Rect(mr.x + pad, content_y + i * (opt_h + self._sc(6)),
                                 mr.width - pad * 2, opt_h)
                if sr.bottom > close_top:
                    break
                if sr.collidepoint(pygame.mouse.get_pos()):
                    pygame.draw.rect(surface, sugg_bg_hov, sr, border_radius=10)
                else:
                    pygame.draw.rect(surface, sugg_bg, sr, border_radius=10)
                pygame.draw.rect(surface, sugg_bdr, sr, 1, border_radius=10)
                row_lbl = _truncate_text(f"@{t['username']}  ·  {t['full_name']}",
                                         self.fnt["body"], sr.width - self._sc(24))
                rs = self.fnt["body"].render(row_lbl, True, sugg_text_col)
                surface.blit(rs, rs.get_rect(midleft=(sr.x + self._sc(12), sr.centery)))
                self._share_sugg_rects.append((sr, t))
            # ── Single Close button (suggestions branch ends here) ──────
            bw_c = self._sc(160)
            clos_r = pygame.Rect(mr.centerx - bw_c // 2, close_top, bw_c, btn_h)
            _btn(surface, clos_r, "Close", self.fnt["btn"],
                 (160, 175, 195), (130, 148, 168), self._share_close_hov, radius=12)
            self._share_close_rect = clos_r
            self._share_yes_rect             = pygame.Rect(0, 0, 1, 1)
            self._share_choice_share_rect    = pygame.Rect(0, 0, 1, 1)
            self._share_choice_transfer_rect = pygame.Rect(0, 0, 1, 1)
            return

        # Only error/success feedback reserves its own line here -- the
        # generic "type a username..." hint was redundant with the input's
        # own "Enter username" placeholder, and removing it hands that
        # room straight to the shared-with list below, which needs it far
        # more (it's the persistent content; the hint was only ever filler
        # for an otherwise-empty moment).
        if self._share_error:
            msg, mc = self._share_error, (210, 50, 50)
        elif self._share_success:
            msg, mc = self._share_success, (50, 175, 75)
        else:
            msg, mc = "", None
        if msg:
            for ln in self._wrap(msg, self.fnt["small"], mr.width - pad * 2):
                surface.blit(self.fnt["small"].render(ln, True, mc),
                             (mr.x + pad, content_y))
                content_y += self.fnt["small"].get_height() + self._sc(2)
            content_y += self._sc(4)

        # ── Currently shared-with: two columns (name/username left, a
        #    fixed-width Revoke column right, with a clear gap between
        #    them), in a scrollable viewport so an arbitrarily long list
        #    degrades to scrolling instead of overflowing or getting cut
        #    off mid-row. ──────────────────────────────────────────────
        try:
            shared = (self.db.get_shared_therapists(self.share_modal_patient["id"])
                      if self.share_modal_patient else [])
        except Exception:
            shared = []

        surface.blit(self.fnt["tag"].render(
            "Currently shared with:", True, shared_label_col), (mr.x + pad, content_y))
        content_y += self.fnt["tag"].get_height() + self._sc(3)

        viewport = pygame.Rect(mr.x + pad, content_y, mr.width - pad * 2,
                               max(0, close_top - content_y))
        self._share_shared_viewport = viewport

        if not shared:
            self._share_shared_scroll = self._share_shared_scroll_max = 0
            surface.blit(self.fnt["small"].render(
                "Not shared with anyone yet.", True, muted_col), (viewport.x, viewport.y))
        else:
            row_h    = self._tt(46)
            row_gap  = self._sc(8)
            rev_w    = max(self.fnt["tag"].size("Revoke")[0] + self._sc(28), self._sc(96))
            col_gap  = self._sc(16)
            name_col_w = max(self._sc(80), viewport.width - rev_w - col_gap)

            total_h = len(shared) * (row_h + row_gap) - row_gap
            self._share_shared_scroll_max = max(0, total_h - viewport.height)
            self._share_shared_scroll = max(0, min(self._share_shared_scroll,
                                                    self._share_shared_scroll_max))

            prev_clip = surface.get_clip()
            surface.set_clip(viewport)
            y = viewport.y - self._share_shared_scroll
            for t in shared:
                row_top = y
                visible = (row_top + row_h >= viewport.top) and (row_top <= viewport.bottom)
                if visible:
                    name_txt = _truncate_text(f"{t['full_name']} (@{t['username']})",
                                              self.fnt["small"], name_col_w)
                    ts_l = self.fnt["small"].render(name_txt, True, shared_text_col)
                    surface.blit(ts_l, (viewport.x, row_top + (row_h - ts_l.get_height()) // 2))

                    rev_r = pygame.Rect(viewport.x + name_col_w + col_gap, row_top, rev_w, row_h)
                    pygame.draw.rect(surface, (210, 60, 60), rev_r, border_radius=10)
                    rev_s = self.fnt["tag"].render("Revoke", True, (255, 255, 255))
                    surface.blit(rev_s, rev_s.get_rect(center=rev_r.center))
                    self._unshare_rects.append((rev_r, t["id"]))
                y += row_h + row_gap
            surface.set_clip(prev_clip)

            # Minimal scroll affordance: a thin track + thumb along the
            # viewport's right edge, only drawn when there's more to see.
            if self._share_shared_scroll_max > 0:
                track_w = self._sc(5)
                track_r = pygame.Rect(viewport.right - track_w, viewport.top,
                                      track_w, viewport.height)
                pygame.draw.rect(surface, shared_label_col, track_r, border_radius=track_w // 2)
                thumb_h = max(self._sc(24), int(viewport.height *
                             (viewport.height / (total_h if total_h else 1))))
                thumb_y = viewport.top + int((viewport.height - thumb_h) *
                         (self._share_shared_scroll / self._share_shared_scroll_max))
                thumb_r = pygame.Rect(track_r.x, thumb_y, track_w, thumb_h)
                pygame.draw.rect(surface, (*((140, 180, 255) if dark else (40, 120, 200)),),
                                 thumb_r, border_radius=track_w // 2)

        # ── Single Close button ──────────────────────────────────────
        bw_c = self._sc(160)
        clos_r = pygame.Rect(mr.centerx - bw_c // 2, close_top, bw_c, btn_h)
        _btn(surface, clos_r, "Close", self.fnt["btn"],
             (160, 175, 195), (130, 148, 168), self._share_close_hov, radius=12)
        self._share_close_rect = clos_r

        # Dead rects for the stages this popup doesn't draw.
        self._share_yes_rect             = pygame.Rect(0, 0, 1, 1)
        self._share_choice_share_rect    = pygame.Rect(0, 0, 1, 1)
        self._share_choice_transfer_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 6: REGISTER PATIENT
    # ──────────────────────────────────────────────────────────────────

    def _draw_register_patient(self, surface, pa):
        if self._touch_ui:
            self._draw_register_patient_touch(surface, pa)
            return
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=130)
        rp = self.rp
        self._rp_drop_rects = {}

        col1_x = pa.x + int(20*W/1920)
        col2_x = pa.centerx + int(10*W/1920)
        fw      = pa.width//2 - int(36*W/1920)
        fh      = int(40*H/1080)
        lbl_off = int(34*H/1080)
        row_gap = int(80*H/1080)
        top_y   = pa.y + int(34*H/1080)

        field_defs = []

        def _register_field(key, lbl, col_x, row_i, placeholder="", is_drop=False, opts=None):
            fy = top_y + row_i * row_gap
            fr = pygame.Rect(col_x, fy, fw, fh)
            field_defs.append((key, lbl, fr, placeholder, is_drop, opts or []))
            self._rp_drop_rects[key] = (fr, [], opts or [])

        # Field order follows the logical sequence a therapist fills the form
        # in: identification/personal (name, age, sex) -> hand information
        # (dominant, affected -- the stroke-affected side) -> stroke/therapy
        # details (type, onset date, months since) -> optional clinical
        # notes. Matches the touch layout below so both forms ask for the
        # same information in the same order.
        _register_field("full_name",     "Full Name",                   col1_x, 0, "Enter Full Name")
        _register_field("age",           "Age",                         col1_x, 1, "Enter Age")
        _register_field("sex",           "Sex",                         col1_x, 2, is_drop=True, opts=SEX_OPTS)
        _register_field("dominant_hand", "Dominant Hand",               col1_x, 3, is_drop=True, opts=HAND_OPTS)
        _register_field("affected_hand", "Affected Hand (Stroke Side)", col1_x, 4, is_drop=True, opts=HAND_OPTS)
        _register_field("stroke_type",   "Stroke Type",                 col2_x, 0, is_drop=True, opts=STROKE_TYPES)
        _register_field("date_of_stroke","Stroke Onset Date",           col2_x, 1, "MM-DD-YY")
        _register_field("months_stroke", "Months Since Stroke",         col2_x, 2, "e.g. 6")

        notes_y = top_y + 4*row_gap + int(8*H/1080)
        note_fields_def = [
            ("Muscle Stiffness Notes", "notes_stiffness"),
            ("Pain Level Notes",       "notes_pain"),
            ("Therapist Comments",     "notes_therapist"),
        ]
        for i, (nl, nk) in enumerate(note_fields_def):
            ny  = notes_y + int(64*H/1080) + i*row_gap
            fr2 = pygame.Rect(col2_x, ny, fw, fh)
            field_defs.append((nk, nl, fr2, "Optional", False, []))
            self._rp_drop_rects[nk] = (fr2, [], [])

        # ── PASS 1: labels + field boxes ─────────────────────────────
        surface.blit(self.fnt["section"].render("Clinical Notes", True, (85,105,135)),
                     (col2_x, notes_y))

        for (key, lbl, fr, placeholder, is_drop, opts) in field_defs:
            active = (rp["active_key"] == key)
            invalid = (not active) and (key in rp.get("invalid_keys", ()))
            surface.blit(self.fnt["label"].render(lbl, True, (80,95,115)),
                         (fr.x, fr.y - lbl_off))
            pygame.draw.rect(surface, (255,255,255), fr, border_radius=8)
            border_col = (40,160,220) if active else ((210,70,70) if invalid else (190,205,225))
            pygame.draw.rect(surface, border_col, fr,
                             2 if (active or invalid) else 1, border_radius=8)
            val = rp.get(key, "")
            if is_drop:
                disp = val or "Select"
                tc   = (40,50,65) if val else (175,188,205)
                ts   = self.fnt["input"].render(disp, True, tc)
                surface.blit(ts, ts.get_rect(midleft=(fr.x+int(10*W/1920), fr.centery)))
                chev = self.fnt["sym26"].render("▼", True, (90,110,140))
                surface.blit(chev, chev.get_rect(midright=(fr.right-int(10*W/1920), fr.centery)))
            else:
                ts = (self.fnt["input"].render(val, True, (40,50,65)) if val
                      else self.fnt["input"].render(placeholder, True, (185,198,215)))
                surface.blit(ts, ts.get_rect(midleft=(fr.x+int(10*W/1920), fr.centery)))

        # ── PASS 2: open dropdowns drawn on top of everything ─────────
        open_key_map = {
            "sex":           "sex_open",
            "dominant_hand": "dominant_open",
            "affected_hand": "affected_open",
            "stroke_type":   "stroke_open",
        }
        for (key, lbl, fr, placeholder, is_drop, opts) in field_defs:
            if not is_drop or not opts:
                continue
            open_flag = open_key_map.get(key)
            if open_flag and rp.get(open_flag):
                opt_h  = int(38*H/1080)
                opt_rs = []
                dp_bg  = pygame.Rect(fr.x, fr.bottom - 1, fw, len(opts)*opt_h + 4)
                pygame.draw.rect(surface, (248,251,255), dp_bg, border_radius=8)
                pygame.draw.rect(surface, (40,160,220),  dp_bg, 2, border_radius=8)
                for j, ov in enumerate(opts):
                    or_ = pygame.Rect(fr.x, fr.bottom + j*opt_h, fw, opt_h)
                    mp  = pygame.mouse.get_pos()
                    if or_.collidepoint(mp):
                        pygame.draw.rect(surface, (220,236,255), or_, border_radius=6)
                    ts2 = self.fnt["input"].render(ov, True, (40,50,65))
                    surface.blit(ts2, ts2.get_rect(midleft=(or_.x+int(10*W/1920), or_.centery)))
                    opt_rs.append(or_)
                self._rp_drop_rects[key] = (fr, opt_rs, opts)

        # ── Messages + submit button ──────────────────────────────────
        msg_y = pa.bottom - int(90*H/1080)
        if rp["error"]:
            surface.blit(self.fnt["modal_err"].render(rp["error"], True, (210,50,50)),
                         (pa.centerx - int(140*W/1920), msg_y))
        if rp["success"]:
            surface.blit(self.fnt["modal_err"].render(rp["success"], True, (50,175,75)),
                         (pa.centerx - int(140*W/1920), msg_y))

        rb = pygame.Rect(pa.centerx - int(130*W/1920), pa.bottom - int(62*H/1080),
                         int(260*W/1920), int(46*H/1080))
        _btn(surface, rb, "Register Patient", self.fnt["btn"],
             (40,160,220), (25,130,190), self.rp_btn_hov, radius=12)
        self._rp_btn_rect = rb

    def _draw_register_patient_touch(self, surface, pa):
        """Single-column, finger-scrollable registration form for the 1024x600
        panel. Reuses self._rp_drop_rects / self._rp_btn_rect so the existing
        _rp_handle_click / _rp_submit logic works unchanged -- only the layout
        and the vertical scroll are new."""
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=130)
        rp = self.rp
        self._rp_drop_rects = {}

        pad = self._sc(16)
        x0  = pa.x + pad
        fw  = pa.width - 2 * pad
        fh  = self._tt(50)
        lbl_h = self.fnt["small"].get_height()
        row_h = lbl_h + int(4 * H / 1080) + fh + self._sc(16)

        FIELDS = [
            ("full_name",      "Full Name *",                   "text", None),
            ("age",            "Age *",                         "text", None),
            ("sex",            "Sex *",                         "drop", SEX_OPTS),
            ("dominant_hand",  "Dominant Hand *",               "drop", HAND_OPTS),
            ("affected_hand",  "Affected Hand (Stroke Side) *", "drop", HAND_OPTS),
            ("stroke_type",    "Stroke Type",                   "drop", STROKE_TYPES),
            ("date_of_stroke", "Stroke Onset Date *",           "text", None),
            ("months_stroke",  "Months Since Stroke *",         "text", None),
            ("notes_stiffness","Muscle Stiffness Notes",        "text", None),
            ("notes_pain",     "Pain Level Notes",              "text", None),
            ("notes_therapist","Therapist Comments",            "text", None),
        ]
        PLACEHOLD = {"full_name": "Enter full name", "age": "Enter age",
                     "date_of_stroke": "MM-DD-YY", "months_stroke": "e.g. 6"}
        open_flag_map = {"sex": "sex_open", "dominant_hand": "dominant_open",
                         "affected_hand": "affected_open", "stroke_type": "stroke_open",
                         }

        # fixed footer: message line + Register button (always on screen)
        btn_h = self._tt(56)
        rb = pygame.Rect(x0, pa.bottom - pad - btn_h, fw, btn_h)
        footer_top = rb.top - int(8 * H / 1080)
        if rp["error"]:
            msg, mcol = rp["error"], (205, 55, 55)
        elif rp["success"]:
            msg, mcol = rp["success"], (40, 165, 80)
        else:
            msg, mcol = "", None

        top    = pa.y + int(12 * H / 1080)
        bottom = footer_top - int(6 * H / 1080)
        if msg:
            bottom -= self.fnt["small"].get_height() + int(4 * H / 1080)
        view_h = bottom - top
        total  = len(FIELDS) * row_h + self._sc(10)
        self._rp_scroll_max = max(0, total - view_h)
        self._rp_scroll = max(0, min(self._rp_scroll, self._rp_scroll_max))
        arrow_w = self._tt(46) if self._rp_scroll_max > 0 else 0
        field_w = fw - (arrow_w + int(8 * W / 1920) if arrow_w else 0)

        # The first invalid field from the last failed submit attempt is
        # scrolled into view once (then the request is cleared) -- bringing
        # it on-screen is what "focus or scroll to the first invalid field"
        # means on a form taller than the viewport.
        focus_key = getattr(self, "_rp_focus_key", None)
        if focus_key is not None:
            idx = next((i for i, (k, *_r) in enumerate(FIELDS) if k == focus_key), None)
            if idx is not None:
                focus_top = top - self._rp_scroll + idx * row_h
                focus_bottom = focus_top + row_h
                if focus_top < top:
                    self._rp_scroll = max(0, self._rp_scroll - (top - focus_top))
                elif focus_bottom > bottom:
                    self._rp_scroll = min(self._rp_scroll_max,
                                          self._rp_scroll + (focus_bottom - bottom))
            self._rp_focus_key = None

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x + 1, top, pa.width - 2, view_h))
        y = top - self._rp_scroll
        open_overlay = None
        for key, label, kind, opts in FIELDS:
            fr = pygame.Rect(x0, y + lbl_h + int(4 * H / 1080), field_w, fh)
            visible = fr.bottom >= top and fr.top <= bottom
            self._rp_drop_rects[key] = ((fr if visible else pygame.Rect(-9, -9, 1, 1)),
                                        [], opts or [])
            if visible:
                active = (rp["active_key"] == key)
                invalid = (not active) and (key in rp.get("invalid_keys", ()))
                surface.blit(self.fnt["small"].render(label, True, (78, 95, 118)), (x0, y))
                pygame.draw.rect(surface, (255, 255, 255), fr, border_radius=9)
                border_col = ((40, 160, 220) if active else
                             ((210, 70, 70) if invalid else (188, 205, 226)))
                pygame.draw.rect(surface, border_col, fr,
                                 2 if (active or invalid) else 1, border_radius=9)
                val = rp.get(key, "")
                if kind == "drop":
                    disp = val or "Select"
                    tc   = (40, 52, 68) if val else (170, 185, 202)
                    ds   = self.fnt["input"].render(disp, True, tc)
                    surface.blit(ds, ds.get_rect(midleft=(fr.x + int(12 * W / 1920),
                                                          fr.centery)))
                    chev = self.fnt["sym26"].render("▼", True, (95, 115, 145))
                    surface.blit(chev, chev.get_rect(
                        midright=(fr.right - int(12 * W / 1920), fr.centery)))
                    if rp.get(open_flag_map[key]):
                        open_overlay = (fr, opts, key)
                else:
                    ph = PLACEHOLD.get(key, "Optional")
                    vs = (self.fnt["input"].render(val, True, (40, 52, 68)) if val
                          else self.fnt["input"].render(ph, True, (183, 197, 214)))
                    surface.blit(vs, vs.get_rect(midleft=(fr.x + int(12 * W / 1920),
                                                          fr.centery)))
            y += row_h
        surface.set_clip(prev_clip)

        if self._rp_scroll_max > 0:
            ax = pa.right - int(8 * W / 1920) - arrow_w
            ah = view_h // 2 - int(4 * H / 1080)
            self._rp_up_rect   = pygame.Rect(ax, top, arrow_w, ah)
            self._rp_down_rect = pygame.Rect(ax, top + ah + int(8 * H / 1080), arrow_w, ah)
            for r, tri, on in ((self._rp_up_rect, "▲", self._rp_scroll > 0),
                               (self._rp_down_rect, "▼",
                                self._rp_scroll < self._rp_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244),
                                 r, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r, 1, border_radius=8)
                g = self.fnt["nav_sym"].render(tri, True,
                                               (45, 90, 150) if on else (188, 196, 206))
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._rp_up_rect = self._rp_down_rect = pygame.Rect(0, 0, 1, 1)

        if open_overlay:
            fr, opts, fkey = open_overlay
            opt_h = self._tt(46)
            lst_h = len(opts) * opt_h + 4
            # Flip the list upward whenever it would otherwise spill past the
            # fixed footer (message + Register button) -- comparing against
            # pa.bottom (the whole card) instead of footer_top let the open
            # list sit on top of the Register button when a field sat low in
            # the scroll view, e.g. Sex right above the footer.
            base_y = fr.top - lst_h if fr.bottom + lst_h > footer_top else fr.bottom
            dp = pygame.Rect(fr.x, base_y, fr.width, lst_h)
            pygame.draw.rect(surface, (248, 251, 255), dp, border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220), dp, 2, border_radius=9)
            opt_rs, mp = [], pygame.mouse.get_pos()
            for j, ov in enumerate(opts):
                orr = pygame.Rect(fr.x, base_y + j * opt_h, fr.width, opt_h)
                if orr.collidepoint(mp):
                    pygame.draw.rect(surface, (220, 236, 255), orr, border_radius=6)
                os_ = self.fnt["input"].render(ov, True, (40, 52, 68))
                surface.blit(os_, os_.get_rect(midleft=(orr.x + int(12 * W / 1920),
                                                        orr.centery)))
                opt_rs.append(orr)
            self._rp_drop_rects[fkey] = (fr, opt_rs, opts)

        if msg:
            surface.blit(self.fnt["small"].render(msg, True, mcol),
                         (x0, footer_top - self.fnt["small"].get_height()
                          - int(2 * H / 1080)))
        _btn(surface, rb, "Register Patient", self.fnt["btn"],
             (40, 160, 220), (25, 130, 190), self.rp_btn_hov, radius=12)
        self._rp_btn_rect = rb


    # ──────────────────────────────────────────────────────────────────
    #  PANEL 8: THE PATIENT'S OWN PAGE  (breadcrumb: Patient List > <Name>)
    #
    #  Reached by clicking a patient row in the Patient List (that click does
    #  NOT select the patient). Hosts the per-patient records (Info / Analytics
    #  / Calibration Records / Session History) AND the only SELECT PATIENT /
    #  DESELECT PATIENT control -- both go through a confirmation dialog.
    # ──────────────────────────────────────────────────────────────────

    _PV_TABS = ["info", "analytics", "calibration", "history"]
    # (clicked asset, not-clicked asset) -- each pair already bakes in its
    # own icon + label, so the tab no longer draws any text of its own.
    _PV_TAB_ASSETS = {
        "info":        ("patient_info_clicked.png",        "patient_info_not_clicked.png"),
        "analytics":   ("metrics_clicked.png",              "metrics_not_clicked.png"),
        "calibration": ("calibration_records_clicked.png",  "calibration_records_not_clicked.png"),
        "history":     ("session_history_clicked.png",      "session_history_not_clicked.png"),
    }

    def _draw_patient_preview(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        pt = self.preview_patient or {}
        is_sel = self._is_selected(self.preview_patient)

        # ── header row: tab strip (left) + Select/Deselect button (right) ──
        # No Edit button here any more -- editing moved to a per-section Edit
        # button on each Info group (Patient Information / Stroke & Therapy /
        # Clinical Notes). Record stays read-only.
        self._pv_edit_rect = pygame.Rect(0, 0, 1, 1)

        strip_h = max(int(46 * H / 1080), self._tt(46))
        # Width budget for the Select/Deselect button -- no longer drawn
        # text, but kept as a stand-in gauge so the button's footprint (and
        # the room it leaves the four tabs below) is unchanged.
        sel_gauge = "DESELECT" if self._narrow else "DESELECT PATIENT"
        sel_w = self.fnt["label"].size(sel_gauge)[0] + self._sc(40)
        self._pv_tab_rects = {}
        gap   = self._sc(8)
        ntabs = len(self._PV_TABS)
        # Width-driven (not font-driven) now that each tab is a fixed-aspect
        # image -- shrinking the tab height to fit would shrink all four by
        # the same amount anyway, so sizing from the available width and
        # fitting each image into that box (preserving its own aspect ratio)
        # gets the same result without ever stretching/cropping the asset.
        tab_w = max(self._sc(40), (pa.width - gap * ntabs - sel_w) // ntabs)

        # Subtle backdrop behind all five buttons (the four nav tabs AND
        # Select/Deselect) as one continuous strip -- a soft RecovR-blue
        # tint, low enough opacity that it never competes with the button
        # art drawn on top of it.
        bg_pad = self._sc(6)
        nav_bg_r = pygame.Rect(pa.x - bg_pad, pa.y - bg_pad,
                               pa.width + bg_pad * 2, strip_h + bg_pad * 2)
        nav_bg = pygame.Surface(nav_bg_r.size, pygame.SRCALPHA)
        pygame.draw.rect(nav_bg, (40, 150, 220, 26), nav_bg.get_rect(), border_radius=10)
        surface.blit(nav_bg, nav_bg_r.topleft)

        tx = pa.x
        for key in self._PV_TABS:
            r = pygame.Rect(tx, pa.y, tab_w, strip_h)
            active = (self._pv_tab == key)
            clicked_asset, not_clicked_asset = self._PV_TAB_ASSETS[key]
            img = _img_fit(clicked_asset if active else not_clicked_asset, tab_w, strip_h)
            if img is not None:
                surface.blit(img, img.get_rect(center=r.center))
            self._pv_tab_rects[key] = r
            tx += tab_w + gap

        sel_r = pygame.Rect(pa.right - sel_w, pa.y, sel_w, strip_h)
        sel_img = _img_fit("deselect_patient.png" if is_sel else "select_patient.png",
                           sel_r.width, sel_r.height)
        if sel_img is not None:
            surface.blit(sel_img, sel_img.get_rect(center=sel_r.center))
        self._pv_select_rect = sel_r

        # ── content area below the strip ──
        sub = pygame.Rect(pa.x, pa.y + strip_h + int(14 * H / 1080),
                          pa.width, pa.height - strip_h - int(14 * H / 1080))
        if self._pv_tab == "analytics":
            self._draw_analytics(surface, sub)
        elif self._pv_tab == "calibration":
            self._draw_calibration(surface, sub)
        elif self._pv_tab == "history":
            self._draw_session_history(surface, sub)
        else:
            self._pv_draw_info(surface, sub, pt)

    def _is_owner(self, pt):
        """True when the logged-in therapist OWNS this patient (not merely
        shared with them). Only the owner may edit, share or transfer."""
        if not pt:
            return False
        return pt.get("therapist_id") == self.account.get("id")

    # Section key -> the patient fields it owns. Drives both the Info groups and
    # the per-section edit modal, so the two can never drift apart.
    # "record" is absent on purpose: it is derived data and never editable.
    _PV_SECTIONS = {
        "info":   ("Patient Information", ["full_name", "age", "sex"]),
        "stroke": ("Stroke & Therapy",
                   ["stroke_type", "date_of_stroke", "months_stroke",
                    "dominant_hand", "affected_hand"]),
        "notes":  ("Clinical Notes",
                   ["notes_stiffness", "notes_pain", "notes_therapist"]),
    }

    def _pv_info_fields(self, pt):
        """Every stored patient field, grouped. Sourced from the `patients` table
        (database.py) -- nothing invented.

        Each group carries its section key so the renderer can attach the right
        Edit button; `None` means the group is read-only (Record)."""
        def g(k):
            v = pt.get(k)
            return "—" if v is None or str(v).strip() == "" else str(v)
        owner = "—"
        try:
            o = self.db.get_therapist_by_id(pt.get("therapist_id"))
            if o:
                owner = o.get("full_name", "—")
        except Exception:
            pass
        return [
            ("Patient Information", "info", [
                ("Patient ID",   g("patient_id_str")),   # generated, not editable
                ("Full Name",    g("full_name")),
                ("Age",          g("age")),
                ("Sex",          g("sex")),
            ]),
            ("Stroke & Therapy", "stroke", [
                ("Stroke Type",         g("stroke_type")),
                ("Stroke Onset Date",   g("date_of_stroke")),
                ("Months Since Stroke", g("months_stroke")),
                ("Dominant Hand",       g("dominant_hand")),
                ("Affected Hand",       g("affected_hand")),
            ]),
            ("Clinical Notes", "notes", [
                ("Stiffness",       g("notes_stiffness")),
                ("Pain",            g("notes_pain")),
                ("Therapist Notes", g("notes_therapist")),
            ]),
            ("Record", None, [            # read-only: no Edit button, ever
                ("Registered By", owner),
                ("Registered On", str(pt.get("created_at", "—"))[:16] or "—"),
            ]),
        ]

    def _wrap(self, text, font, max_w):
        words, lines, cur = str(text).split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if font.size(t)[0] <= max_w or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _pv_draw_info(self, surface, pa, pt):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=130)
        x0    = pa.x + int(30 * W / 1920)
        val_x = x0 + max(int(300 * W / 1920), self._tt(250))
        # Field rows are plain text, not tap targets -- _tt()'s 50px touch
        # floor doesn't belong here; _sc() gives a compact row without it.
        lh    = max(int(34 * H / 1080), self._sc(32))
        # Reserved unconditionally (not only once scrolling is confirmed
        # needed) -- wrap width and scroll-need are circular otherwise:
        # text wrapped against the FULL width could measure as fitting
        # without scrolling, then overlap the arrows once they appear
        # because THEY reserve space the wrap never accounted for. This is
        # what let "Unknown / Not Specified" run under the scrollbar before.
        arrow_w = self._tt(44)
        val_w = pa.right - int(30 * W / 1920) - (arrow_w + self._sc(8)) - val_x

        # Only the OWNER may edit. A shared patient is read-only here, so the
        # per-section Edit buttons are simply not drawn for a non-owner.
        can_edit = self._is_owner(pt)
        # Small square pencil icon beside each heading (not a wide "Edit"
        # pill) -- the dedicated edit_patient_info.png asset (separate from
        # edit_profile.png, which stays on the sidebar's own profile-edit
        # badge), clamped to the ~36-40px comfortable touch target this is
        # meant to be.
        edit_h = max(36, min(40, self._sc(38)))

        # measure -> total content height
        groups = self._pv_info_fields(pt)
        blocks = []   # (kind, *payload)
        for title, sec, fields in groups:
            blocks.append(("hdr", title, sec))
            for lbl, val in fields:
                wl = self._wrap(val, self.fnt["body"], val_w)
                blocks.append(("row", lbl, wl))
        def block_h(b):
            if b[0] == "hdr":
                # header rows carry an Edit button, so they need its height
                return max(lh, edit_h) + self._sc(6)
            return lh * len(b[2]) + self._sc(3)
        total = sum(block_h(b) for b in blocks) + self._sc(10)

        top    = pa.y + int(16 * H / 1080)
        bottom = pa.bottom - self._sc(14)
        view_h = bottom - top
        self._pv_info_scroll_max = max(0, total - view_h)
        self._pv_info_scroll = max(0, min(self._pv_info_scroll, self._pv_info_scroll_max))

        self._pv_sec_edit_rects = {}
        right_edge = pa.right - int(30 * W / 1920) - (arrow_w + self._sc(8))

        prev = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x + 1, top, pa.width - 2, view_h))
        y = top - self._pv_info_scroll
        for b in blocks:
            if y + block_h(b) >= top and y <= bottom:
                if b[0] == "hdr":
                    hdr_s = self.fnt["body_b"].render(b[1], True, (46, 110, 180))
                    surface.blit(hdr_s, (x0, y))
                    sec = b[2]
                    if sec and can_edit:
                        # Immediately beside the heading, small consistent
                        # gap, vertically centered on the heading text.
                        ex = x0 + hdr_s.get_width() + self._sc(10)
                        vcenter = y + hdr_s.get_height() // 2
                        edit_img = _img_fit("edit_patient_info.png", edit_h, edit_h)
                        if edit_img is not None:
                            drawn_r = edit_img.get_rect(midleft=(ex, vcenter))
                            if drawn_r.right > right_edge:   # never spill past the arrows
                                drawn_r.right = right_edge
                            surface.blit(edit_img, drawn_r)
                        else:
                            drawn_r = pygame.Rect(ex, 0, edit_h, edit_h)
                            drawn_r.centery = vcenter
                            pygame.draw.circle(surface, (40, 150, 170), drawn_r.center, edit_h // 2)
                            es = self.fnt["sym26"].render("✎", True, (255, 255, 255))
                            surface.blit(es, es.get_rect(center=drawn_r.center))
                        # The icon itself is small, but the tap target stays
                        # comfortable via this padding, not by enlarging the
                        # icon's own rendered size.
                        if drawn_r.top >= top and drawn_r.bottom <= bottom:
                            self._pv_sec_edit_rects[sec] = drawn_r.inflate(self._sc(14), self._sc(14))
                    hl_y = y + max(lh, edit_h) - int(4 * H / 1080)
                    pygame.draw.line(surface, (200, 214, 232),
                                     (x0, hl_y), (pa.right - int(30 * W / 1920), hl_y), 1)
                else:
                    surface.blit(self.fnt["small"].render(b[1], True, (120, 135, 160)), (x0, y))
                    yy = y
                    for ln in b[2]:
                        surface.blit(self.fnt["body"].render(ln, True, (40, 55, 75)), (val_x, yy))
                        yy += lh
            y += block_h(b)
        surface.set_clip(prev)

        if self._pv_info_scroll_max > 0:
            ax = pa.right - int(8 * W / 1920) - arrow_w
            ah = view_h // 2 - int(4 * H / 1080)
            self._pv_info_up_rect   = pygame.Rect(ax, top, arrow_w, ah)
            self._pv_info_down_rect = pygame.Rect(ax, top + ah + int(8 * H / 1080), arrow_w, ah)
            for r, tri, on in ((self._pv_info_up_rect, "▲", self._pv_info_scroll > 0),
                               (self._pv_info_down_rect, "▼", self._pv_info_scroll < self._pv_info_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244), r, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r, 1, border_radius=8)
                g = self.fnt["nav_sym"].render(tri, True, (45, 90, 150) if on else (185, 193, 203))
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._pv_info_up_rect = self._pv_info_down_rect = pygame.Rect(0, 0, 1, 1)
        # The bottom instructional hint ("Selected -- use DESELECT PATIENT
        # above.") was removed -- selection state is already shown via the
        # SELECT/DESELECT button itself and the sidebar's Active Patient card.

    def _dialog_fonts(self):
        """The Poppins font set draw_confirm_dialog needs, at this scene's
        own _fs scale -- shared by every standardized confirm/warning
        dialog so they all read as one consistent type system."""
        return {"title": self.fnt["modal_head"], "title_small": self.fnt["modal_lbl"],
                "body": self.fnt["modal_lbl"], "btn": self.fnt["btn"]}

    # ── Patient Sharing/Transferring popups: one shared sizing system ───
    # All four (therapist search, SHARE|TRANSFER chooser, Share confirm,
    # Transfer confirm) share the exact same outer card size and the same
    # title/body font choices, via draw_dialog_chrome's/draw_confirm_
    # dialog's fixed_size param -- never four independently-sized popups.

    def _share_popup_size(self):
        """~620x420 at the 800x480 reference LCD, expressed as a fraction
        of the actual screen so it scales proportionally on any other
        resolution instead of drifting from the non-proportional _sc/_tt
        control-sizing curve those functions otherwise use.

        The spec target was ~620x380, but the Transfer confirmation's own
        content -- a full warning paragraph, three labeled detail lines,
        AND a dynamic title repeating both names -- genuinely does not fit
        380px even after every reasonable optimization (a denser shared
        body font, no mid-paragraph blank line, no icon for this one
        popup): it needs ~400-410px, measured directly against real font
        metrics, not estimated. 420 gives a small safety margin while
        still leaving ~30px of comfortable top+bottom screen margin --
        the "adjusting only if necessary" the spec itself allows for,
        rather than truncating names or shrinking fonts further to force
        a tighter number.

        The search popup's own content (label+input row, live suggestions
        OR the persistent shared-with list, a scrollable two-column list)
        pushed this up further still, to ~0.93 -- at 0.88 the shared-with
        viewport came out under one full touch-sized row even in its best
        case (no live suggestions competing for room), which fails "make
        the shared-with list scrollable" in practice (nothing usable to
        scroll). 0.93 leaves the list genuinely usable (about two rows)
        while keeping ~17px of top+bottom screen margin -- tight, but
        still a real margin, not edge-to-edge."""
        return int(self.WIDTH * 0.775), int(self.HEIGHT * 0.93)

    def _share_dialog_fonts(self):
        """Same title font as every other standard dialog, but a smaller,
        denser body font than draw_confirm_dialog's default (modal_lbl) --
        shared by all four of these popups specifically (not just the ones
        that strictly need it) so "same body font size" actually holds
        across the family, and so the fixed card size has room for what
        the busiest of the four (Transfer) needs to show."""
        f = dict(self._dialog_fonts())
        f["body"] = self.fnt["tag"]
        return f

    def _share_header_metrics(self):
        """pad_px/icon_r_px for all four Patient Sharing/Transferring
        popups -- smaller than draw_confirm_dialog's/draw_dialog_chrome's
        own defaults (24/32), passed identically to every one of the four
        so their header heights stay equal ("same header height" per
        spec) while reclaiming the room this content-dense family of
        popups needs within its shared fixed outer size."""
        return 14, 20   # (pad_px, icon_r_px)

    def _draw_choice_modal(self, surface, title, body, icon, accent):
        """Shared CANCEL | CONFIRM dialog (used for SELECT and DESELECT),
        via the standardized draw_confirm_dialog. Stores the real drawn
        button rects so every existing click/hover handler (_confirm_rects)
        keeps working unchanged."""
        cr, xr = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon=icon, accent=accent,
            title=title, body=body, confirm_label="Confirm", cancel_label="Cancel",
            confirm_hov=self.confirm_yes_hov, cancel_hov=self.confirm_no_hov)
        self._modal_confirm_rect, self._modal_cancel_rect = cr, xr

    def _draw_select_confirm_modal(self, surface):
        name = (self._pending_select_patient or {}).get("full_name", "this patient")
        self._draw_choice_modal(
            surface, f"Select {name} for this session?",
            "You will continue to Game Configuration.",
            "select", (45, 150, 95))

    def _draw_deselect_confirm_modal(self, surface):
        name = (self._pending_deselect_patient or {}).get("full_name", "this patient")
        self._draw_choice_modal(
            surface, f"Deselect {name}?",
            "The patient monitor returns to the Waiting Screen.",
            "deselect", (200, 70, 60))

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 1: SESSION HISTORY
    # ──────────────────────────────────────────────────────────────────

    def _draw_session_history(self, surface, pa):
        if self._sh_detail_record is not None:
            self._draw_session_detail(surface, pa)
            return
        W, H = self.WIDTH, self.HEIGHT
        touch = self._touch_ui
        _card_bg(surface, pa, alpha=130)
        table_y = pa.y + self._sc(12)
        # Simplified to the 3 fields that identify a session at a glance --
        # Score/Duration/Difficulty/Stopped-status moved into the full-page
        # Session Details screen (tap a row), same on touch and desktop now
        # (matches Calibration Records' own simplification).
        cols = ["Date", "Game", "Therapist"]
        if touch:
            seg_w = (pa.width - int(32*W/1920)) // len(cols)
            col_xs = [pa.x + int(16*W/1920) + i*seg_w for i in range(len(cols))]
        else:
            col_xs = [pa.x+int(16*W/1920), pa.x+int(230*W/1920), pa.x+int(900*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c, True, (85,105,135)), (cx, table_y))
        # Underline sits below the header's actual rendered height (not a
        # raw H/1080 guess, which was less than the touch-scaled font's real
        # height and let the first data row visually overlap the headers).
        hdr_line_y = table_y + self.fnt["section"].get_height() + self._sc(6)
        pygame.draw.line(surface, (210,218,230),
                         (pa.x+int(16*W/1920), hdr_line_y),
                         (pa.right-int(16*W/1920), hdr_line_y), 1)

        pt = self._view_patient()
        if not pt:
            _empty_state(surface,
                         pygame.Rect(pa.x, hdr_line_y+self._sc(12), pa.width,
                                     pa.bottom-hdr_line_y-self._sc(12)),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view their session history.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._sh_up_rect = self._sh_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        sessions = (self.db.get_sessions(self.account["id"], patient_id=pt["id"])
                    if hasattr(self.db, "get_sessions") else [])
        if not sessions:
            _empty_state(surface,
                         pygame.Rect(pa.x, hdr_line_y+self._sc(12), pa.width,
                                     pa.bottom-hdr_line_y-self._sc(12)),
                         "📋", "No sessions recorded yet",
                         f"No sessions found for {pt.get('full_name', 'this patient')}.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._sh_up_rect = self._sh_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        view_top    = hdr_line_y + self._sc(8)
        view_bottom = pa.bottom - int(10*H/1080)
        view_h      = view_bottom - view_top
        row_pad     = self._sc(14)
        row_line_h  = self.fnt["small"].get_height()
        arrow_w     = self._tt(44)
        content_right = pa.right - int(8*W/1920) - (arrow_w + self._sc(8))

        # Build each session's row values once, wrapping long cells onto
        # multiple lines (touch only) instead of the old ellipsis, so a long
        # game/therapist name is fully readable instead of cut off or
        # overlapping the next column. Row height grows to fit whichever
        # cell wrapped the most, same approach as Calibration Records.
        row_data = []   # (wrapped_cols, row_h, session)
        for s in sessions:
            date_str = str(s.get("played_at",""))[:10 if touch else 16]
            # Mode stays beside the game name (e.g. "Piano Tiles (Target)")
            # -- only the inline "· Stopped" flag moves to Session Details,
            # since status alone (without score/duration/difficulty) isn't
            # useful at a glance and was what overlapped neighboring columns.
            mode = s.get("session_mode") or "target"
            mode_lbl = "Timed" if mode == "timed" else "Target"
            game_str = f"{s.get('game', '—')} ({mode_lbl})"
            # "or" (not .get's default) -- a row whose therapist_id is NULL
            # (LEFT JOIN) hands back a real None, not a missing key, which
            # .get(key, "—") does not catch and str()'s into a literal "None".
            vals = [date_str, game_str, s.get("therapist_name") or "—"]
            # Wrapped on both touch and desktop now (not touch-only) -- 3
            # wider columns still need this for a very long game/therapist
            # name so it never extends into the next column.
            wrapped = []
            for i, v in enumerate(vals):
                avail = (col_xs[i+1] if i+1 < len(col_xs) else content_right) - col_xs[i] - self._sc(8)
                wrapped.append(self._wrap(v, self.fnt["small"], max(avail, self._sc(20))))
            rh = max(len(w) for w in wrapped) * row_line_h + row_pad
            row_data.append((wrapped, rh, s))

        content_h = sum(rh for _, rh, _ in row_data)
        self._sh_scroll_max = max(0, content_h - view_h)
        self._sh_scroll     = max(0, min(self._sh_scroll, self._sh_scroll_max))
        scrollable  = self._sh_scroll_max > 0
        arrow_w     = arrow_w if scrollable else 0
        content_right = pa.right - int(8*W/1920) - (arrow_w + self._sc(8) if scrollable else 0)

        # Every record row is its own tap target -> opens the full-page
        # Session Details view (see _draw_session_detail / the
        # _sh_detail_record dispatch at the top of this function). Looked up
        # by the session's own DB id, never by list position/index.
        mp = pygame.mouse.get_pos()
        self._sh_row_rects = []
        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, view_top, content_right - pa.x - 1, view_h))
        ry = view_top - self._sh_scroll
        for k, (wrapped, rh, s) in enumerate(row_data):
            if ry + rh >= view_top and ry <= view_bottom:
                row_r = pygame.Rect(pa.x+int(10*W/1920), ry, pa.width-int(20*W/1920), rh - 4)
                hovered = row_r.collidepoint(mp)
                bg = pygame.Surface((row_r.width, row_r.height), pygame.SRCALPHA)
                if hovered:
                    bg.fill((205, 228, 255, 190))          # subtle pressed/selected tint
                elif k % 2 == 0:
                    bg.fill((240, 246, 255, 180))
                else:
                    bg.fill((0, 0, 0, 0))
                surface.blit(bg, row_r.topleft)
                pygame.draw.rect(surface, (120,170,230) if hovered else (215,225,240),
                                 row_r, 1 if not hovered else 2, border_radius=8)
                for i, (cx, lines) in enumerate(zip(col_xs, wrapped)):
                    block_h = len(lines) * row_line_h
                    ty = row_r.centery - block_h // 2       # vertically centered, not top-anchored
                    for ln in lines:
                        surface.blit(self.fnt["small"].render(ln, True, (40,55,75)), (cx, ty))
                        ty += row_line_h
                # Clamp the hit area to the visible list band -- a row
                # scrolled half-off must not be tappable below the list
                # (same guard the Patient List / Calibration rows use).
                hit_r = row_r.clip(pygame.Rect(pa.x, view_top, pa.width, view_h))
                if hit_r.height >= self._tt(32):
                    self._sh_row_rects.append((hit_r, s))
            ry += rh
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when the history overflows) ──────────
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - int(8*W/1920) - arrow_w
            self._sh_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._sh_down_rect = pygame.Rect(ax, view_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._sh_up_rect, "▲", self._sh_scroll > 0),
                               (self._sh_down_rect, "▼", self._sh_scroll < self._sh_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._sh_up_rect = self._sh_down_rect = pygame.Rect(0, 0, 1, 1)

    def _draw_session_detail(self, surface, pa):
        """Full-page Session Details (NOT a popup/modal) -- the actual
        recorded result for this one session, looked up by its own DB id.
        Reached by tapping a row in Session History; Back returns there
        with its scroll position untouched (see the _sh_detail_record
        dispatch in _draw_session_history). Mirrors
        _draw_calibration_detail's layout/styling for consistency."""
        W, H = self.WIDTH, self.HEIGHT
        s = self._sh_detail_record or {}
        _card_bg(surface, pa, alpha=130)
        pad = self._sc(14)

        # ── header: Back + title ──────────────────────────────────────
        # Round icon-only asset (simple_back_button.png), not the wide
        # pill back_button_therapist.png the main dashboard/Game
        # Configuration back buttons use -- scoped to this record-detail
        # page only, per spec.
        back_d = self._tt(40)
        back_r = pygame.Rect(pa.x + pad, pa.y + self._sc(10), back_d, back_d)
        back_img = _img_fit("simple_back_button.png", back_r.width, back_r.height)
        if back_img is not None:
            surface.blit(back_img, back_img.get_rect(center=back_r.center))
        else:
            pygame.draw.circle(surface, (255, 255, 255), back_r.center, back_d // 2)
            pygame.draw.circle(surface, (205, 218, 236), back_r.center, back_d // 2, 1)
            bk_s = self.fnt["small"].render("←", True, (70, 88, 112))
            surface.blit(bk_s, bk_s.get_rect(center=back_r.center))
        self._shd_back_rect = back_r

        title_s = self.fnt["section"].render("Session Details", True, (38, 52, 78))
        surface.blit(title_s, (back_r.right + self._sc(14),
                               back_r.centery - title_s.get_height() // 2))

        view_top    = back_r.bottom + self._sc(14)
        view_bottom = pa.bottom - self._sc(10)
        view_h      = max(1, view_bottom - view_top)
        arrow_w     = self._tt(44)

        def _fmt(v):
            return "Not Available" if v is None or v == "" else str(v)

        pt = self._view_patient() or {}
        date_raw = str(s.get("played_at", "") or "")
        date_disp = date_raw[:10] if date_raw else "Not Available"
        time_disp = date_raw[11:16] if len(date_raw) >= 16 else "Not Available"
        mode = s.get("session_mode") or "target"
        mode_disp = "Timed" if mode == "timed" else "Target"
        status = s.get("status") or "completed"
        status_disp = "Stopped" if status == "stopped" else "Completed"

        goal = s.get("goal")
        reps = s.get("completed_reps", s.get("score"))
        if mode == "target" and goal not in (None, ""):
            score_disp = f"{_fmt(reps)}/{goal}"
        else:
            score_disp = _fmt(reps if reps is not None else s.get("score"))

        dur_sec = s.get("duration_sec")
        if dur_sec is None:
            dur_disp = "Not Available"
        else:
            mins, secs = divmod(int(dur_sec), 60)
            dur_disp = f"{mins}min {secs}s" if mins else f"{secs}s"

        sections = [
            ("Session Information", [
                ("Game",      _fmt(s.get("game"))),
                ("Game Mode", mode_disp),
                ("Date",      date_disp),
                ("Time",      time_disp),
                ("Therapist", _fmt(s.get("therapist_name"))),
            ]),
            ("Session Results", [
                ("Status",     status_disp),
                ("Score",      score_disp),
                ("Duration",   dur_disp),
                ("Difficulty", _fmt(s.get("difficulty"))),
            ]),
            ("Patient", [
                ("Patient Name", _fmt(pt.get("full_name") or s.get("patient_name"))),
                ("Patient ID",   _fmt(pt.get("patient_id_str"))),
            ]),
        ]

        f_hdr = self.fnt["body_b"]
        f_lbl = self.fnt["body"]
        f_val = self.fnt["body_b"]
        row_h = f_lbl.get_height() + self._sc(10)
        hdr_h = f_hdr.get_height() + self._sc(10)
        val_x = pa.x + pa.width // 2

        content_h = sum(hdr_h + row_h * len(rows) + self._sc(8) for _, rows in sections)
        self._shd_scroll_max = max(0, content_h - view_h)
        self._shd_scroll     = max(0, min(self._shd_scroll, self._shd_scroll_max))
        scrollable = self._shd_scroll_max > 0
        arrow_w    = arrow_w if scrollable else 0
        content_right = pa.right - pad - (arrow_w + self._sc(8) if scrollable else 0)

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x + 1, view_top, content_right - pa.x - 1, view_h))
        y = view_top - self._shd_scroll
        for title, rows in sections:
            if y + hdr_h + row_h * len(rows) >= view_top and y <= view_bottom:
                surface.blit(f_hdr.render(title, True, (40, 150, 170)), (pa.x + pad, y))
                pygame.draw.line(surface, (210, 224, 240),
                                 (pa.x + pad, y + hdr_h - self._sc(4)),
                                 (content_right, y + hdr_h - self._sc(4)), 1)
            ry = y + hdr_h
            for lbl, val in rows:
                if ry + row_h >= view_top and ry <= view_bottom:
                    surface.blit(f_lbl.render(lbl, True, (100, 116, 140)), (pa.x + pad, ry))
                    surface.blit(f_val.render(str(val), True, (35, 48, 70)), (val_x, ry))
                ry += row_h
            y = ry + self._sc(8)
        surface.set_clip(prev_clip)

        if scrollable:
            ah = view_h // 2 - self._sc(4)
            ax = pa.right - pad - arrow_w
            self._shd_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._shd_down_rect = pygame.Rect(ax, view_top + ah + self._sc(8), arrow_w, ah)
            for r, tri, on in ((self._shd_up_rect, "▲", self._shd_scroll > 0),
                               (self._shd_down_rect, "▼", self._shd_scroll < self._shd_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._shd_up_rect = self._shd_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 2: ANALYTICS
    # ──────────────────────────────────────────────────────────────────

    def _metrics_mode_stats(self, sessions, mode):
        """Sessions/Best/Average/Elapsed Time for ONE game's ONE session_mode,
        computed ONLY from that game+mode's own sessions -- Target Mode and
        Timed Mode are never combined into one set of numbers.

        Different configured goals (Target Mode) or durations (Timed Mode)
        are different tasks -- "10 shots" and "30 shots" (or "1 minute" and
        "5 minutes") are not comparable by raw elapsed time / rep count
        alone. Best/Average are therefore computed only across the group of
        COMPLETED sessions that share the single most-common goal/duration
        in this history (not blindly pooling every goal together, and never
        comparing across them) -- a manually-stopped session never counts as
        a completed target, so it can never win "Best" or skew "Average".
        Sessions/Elapsed Time count every recorded session in this mode
        (completed AND stopped), since those are just totals, not a
        same-task comparison."""
        mode_sessions = [s for s in sessions if (s.get("session_mode") or "target") == mode]
        total = len(mode_sessions)
        completed = [s for s in mode_sessions if s.get("status") != "stopped"]

        def _mmss(sec):
            sec = int(round(sec))
            m, s = divmod(sec, 60)
            return f"{m}m {s}s" if m else f"{s}s"

        if mode == "target":
            by_goal = defaultdict(list)
            for s in completed:
                g = s.get("goal")
                if g:
                    by_goal[g].append(s)
            comparable = max(by_goal.values(), key=len) if by_goal else []
            times = [s.get("duration_sec", 0) for s in comparable]
            best_str = _mmss(min(times)) if times else "—"
            avg_str  = _mmss(sum(times) / len(times)) if times else "—"
        else:
            by_dur = defaultdict(list)
            for s in completed:
                d = s.get("configured_duration_seconds")
                if d:
                    by_dur[d].append(s)
            comparable = max(by_dur.values(), key=len) if by_dur else []
            reps = [s.get("completed_reps", s.get("score", 0)) or 0 for s in comparable]
            best_str = f"{max(reps)} reps" if reps else "—"
            avg_str  = f"{(sum(reps)/len(reps)):.1f} reps" if reps else "—"

        elapsed_total = sum(s.get("duration_sec", 0) for s in mode_sessions)
        elapsed_str = _mmss(elapsed_total)

        # Chart: last 8 sessions in this mode, oldest -> newest (mode_sessions
        # is newest-first, matching database.get_sessions()'s own ordering).
        chart = []
        for s in list(reversed(mode_sessions))[-8:]:
            stopped = s.get("status") == "stopped"
            if mode == "target":
                val = s.get("duration_sec", 0)
                lbl = _mmss(val)
            else:
                val = s.get("completed_reps", s.get("score", 0)) or 0
                lbl = str(val)
            chart.append((val, lbl, stopped))

        return {"total": total, "best": best_str, "avg": avg_str,
                "elapsed": elapsed_str, "chart": chart}

    def _metrics_stat_box_h(self):
        """The 4 metric cards' own height -- a single shared source so
        _metrics_build_rows (reserved scroll height) and
        _metrics_draw_mode_stats (what's actually drawn) can never drift
        out of sync with each other."""
        pad_v = self._sc(18)
        gap_v = self._sc(10)
        return pad_v * 2 + self.fnt["tag"].get_height() + gap_v + self.fnt["btn_lg"].get_height()

    def _metrics_build_rows(self, sessions_by_game, W, H, content_w):
        """Flatten METRICS_TREE into render blocks honoring
        self._metrics_expanded -- collapsed branches simply never produce
        rows, so building this list IS the expand/collapse logic. Each
        block: (kind, path, height, data, gap_after) -- gap_after is the
        vertical space reserved AFTER this row, before the next one.

        Spacing is deliberately generous (not just "not cramped") -- a
        prior pass that tried to merely fix overlap ended up reading as
        MORE compressed than before, which is the opposite of the goal:
        every one of these gaps exists to make the hierarchy level and the
        boundary between sibling rows unmistakable at a glance, even
        scrolled past the fold, not to fit more onto one screen."""
        row_h_cat  = self._tt(50)
        row_h_sub  = self._tt(46)
        row_h_game = self._tt(44)
        row_h_mode = self._tt(42)
        gap_after = {
            "cat":   self._sc(18),
            "sub":   self._sc(16),
            "game":  self._sc(16),
            "mode":  self._sc(14),   # mode row -> its own stats block right below it
            "stats": self._sc(34),   # a finished stats block -> whatever comes next
        }

        rows = []
        for cat, subs in METRICS_TREE:
            cat_path = (cat,)
            rows.append(("cat", cat_path, row_h_cat, None, gap_after["cat"]))
            if cat_path not in self._metrics_expanded:
                continue
            for sub, games in subs:
                sub_path = (cat, sub)
                rows.append(("sub", sub_path, row_h_sub, None, gap_after["sub"]))
                if sub_path not in self._metrics_expanded:
                    continue
                for game in games:
                    game_path = (cat, sub, game)
                    rows.append(("game", game_path, row_h_game, None, gap_after["game"]))
                    if game_path not in self._metrics_expanded:
                        continue
                    g_sessions = sessions_by_game.get(game, [])
                    for mode_key, mode_label in METRICS_MODES:
                        mode_path = (cat, sub, game, mode_key)
                        rows.append(("mode", mode_path, row_h_mode, mode_label, gap_after["mode"]))
                        if mode_path not in self._metrics_expanded:
                            continue
                        stats = self._metrics_mode_stats(g_sessions, mode_key)
                        rows.append(("stats", mode_path, self._metrics_stat_box_h(),
                                     stats, gap_after["stats"]))
        return rows

    def _draw_analytics(self, surface, pa):
        """Metrics: an expandable tree (Main category -> Subcategory -> Game
        -> Session Mode), collapsed by default. Tapping any row -- not just
        a chevron -- toggles that node; a Session Mode's own 4 metric cards
        (no chart) only render while IT is expanded (see
        _metrics_build_rows)."""
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=130)
        lx = pa.x + int(16*W/1920)
        ly = pa.y + int(14*H/1080)
        pad = self._sc(10)
        indent = self._sc(40)   # per-level indent -- wide enough each level reads clearly

        pt = self._view_patient()
        if not pt:
            _empty_state(surface, pygame.Rect(pa.x, ly, pa.width, pa.bottom-ly),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view their analytics.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._an_up_rect = self._an_down_rect = pygame.Rect(0, 0, 1, 1)
            self._metrics_row_rects = []
            return

        sessions = (self.db.get_sessions(self.account["id"], patient_id=pt["id"])
                    if hasattr(self.db, "get_sessions") else [])

        by_game = defaultdict(list)
        for s in sessions:
            by_game[s.get("game", "Unknown")].append(s)

        view_top    = ly
        view_bottom = pa.bottom - int(10*H/1080)
        view_h      = view_bottom - view_top
        arrow_w     = self._tt(44)
        content_right = pa.right - int(16*W/1920) - (arrow_w + self._sc(8))

        row_data = self._metrics_build_rows(by_game, W, H, content_right - lx)
        content_h = sum(h + gap for _, _, h, _, gap in row_data)
        self._an_scroll_max = max(0, content_h - view_h)
        self._an_scroll     = max(0, min(self._an_scroll, self._an_scroll_max))
        scrollable  = self._an_scroll_max > 0
        arrow_w     = arrow_w if scrollable else 0
        content_right = pa.right - int(16*W/1920) - (arrow_w + self._sc(8) if scrollable else 0)

        CAT_COL  = (40, 110, 180)
        SUB_COL  = (45, 140, 150)
        GAME_COL = (55, 70, 95)
        MODE_COL = (80, 95, 120)

        self._metrics_row_rects = []
        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, view_top, content_right - pa.x - 1, view_h))
        cy = view_top - self._an_scroll
        for kind, path, h, data, gap in row_data:
            depth = len(path) - (1 if kind == "stats" else 0)
            row_x = lx + indent * (depth - 1 if depth > 0 else 0)
            visible = (cy + h >= view_top and cy <= view_bottom)

            if kind == "stats":
                if visible:
                    self._metrics_draw_mode_stats(surface, row_x, cy, content_right, data)
            else:
                row_r = pygame.Rect(pa.x + pad, cy, content_right - pa.x - pad, h)
                if visible:
                    expanded = path in self._metrics_expanded
                    chev = "▼" if expanded else "▶"
                    col, font = {
                        "cat":  (CAT_COL,  self.fnt["section"]),
                        "sub":  (SUB_COL,  self.fnt["body_b"]),
                        "game": (GAME_COL, self.fnt["body_b"]),
                        "mode": (MODE_COL, self.fnt["body"]),
                    }[kind]
                    if kind in ("cat", "sub", "game"):
                        bg = pygame.Surface((row_r.width, row_r.height), pygame.SRCALPHA)
                        shade = {"cat": 40, "sub": 26, "game": 16}[kind]
                        pygame.draw.rect(bg, (*col, shade), (0, 0, row_r.width, row_r.height),
                                         border_radius=8)
                        surface.blit(bg, row_r.topleft)
                    # Chevron sits in a fixed-width column (not packed
                    # right against the text that follows it) so every
                    # level's arrow lines up consistently regardless of
                    # glyph width, matching "align expand/collapse arrows
                    # consistently." Measured from the actual rendered
                    # glyph (not a guessed constant) plus a clear margin --
                    # a guessed column narrower than the real glyph is
                    # exactly what let the arrow touch the text.
                    chev_col_w = max(self.fnt["nav_sym"].size("▼")[0],
                                     self.fnt["nav_sym"].size("▶")[0]) + self._sc(12)
                    cx = row_x + self._sc(8)
                    chev_s = self.fnt["nav_sym"].render(chev, True, col)
                    surface.blit(chev_s, (cx, row_r.centery - chev_s.get_height()//2))
                    cx = row_x + self._sc(8) + chev_col_w
                    icon_sz = row_r.height - self._sc(10)
                    asset = (METRICS_SUB_ICON.get(path[-1]) if kind == "sub"
                             else GAME_ICON_ASSET.get(path[-1]) if kind == "game" else None)
                    if asset:
                        img = _img_fit(asset, icon_sz, icon_sz)
                        if img is not None:
                            surface.blit(img, img.get_rect(midleft=(cx, row_r.centery)))
                            cx += icon_sz + self._sc(10)
                    if kind == "cat":
                        label = path[-1].upper()
                    elif kind == "mode":
                        label = data   # "Target Mode" / "Timed Mode" (path[-1] is the raw key)
                    else:
                        label = path[-1]
                    lbl_s = font.render(label, True, col)
                    surface.blit(lbl_s, (cx, row_r.centery - lbl_s.get_height()//2))
                self._metrics_row_rects.append((row_r, path))
            cy += h + gap
        surface.set_clip(prev_clip)

        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - int(8*W/1920) - arrow_w
            self._an_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._an_down_rect = pygame.Rect(ax, view_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._an_up_rect, "▲", self._an_scroll > 0),
                               (self._an_down_rect, "▼", self._an_scroll < self._an_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._an_up_rect = self._an_down_rect = pygame.Rect(0, 0, 1, 1)

    def _metrics_draw_mode_stats(self, surface, x, y, content_right, stats):
        """The 4 metric cards (Sessions / Best / Average / Elapsed Time) for
        one expanded Session Mode row -- no chart/graph underneath, by
        spec. Missing data already reads as "—" / "0s" inside the cards
        themselves, so there's no separate empty-state line to draw either
        -- these 4 cards are the ENTIRE contents of a "stats" block. See
        _metrics_mode_stats for how the numbers are computed, and
        _metrics_stat_box_h for the shared height both this and
        _metrics_build_rows's scroll-height reservation are computed from."""
        pad_v = self._sc(18)
        pad_h = self._sc(16)
        gap_v = self._sc(10)
        gap_h = self._sc(16)   # between adjacent cards
        f_lbl, f_val = self.fnt["tag"], self.fnt["btn_lg"]
        stat_box_h = self._metrics_stat_box_h()
        accent = (60, 140, 210)

        stat_items = [("Sessions", str(stats["total"])), ("Best", stats["best"]),
                      ("Average", stats["avg"]), ("Elapsed Time", stats["elapsed"])]
        sw = max(1, (content_right - x - gap_h * 3) // 4)
        for si, (lbl, val) in enumerate(stat_items):
            sx = x + si * (sw + gap_h)
            box = pygame.Rect(sx, y, sw, stat_box_h)
            _card_bg(surface, box, alpha=235, border_col=(*accent, 255), border_w=1)
            lbl_s = f_lbl.render(lbl, True, (100, 120, 150))
            lbl_h = lbl_s.get_height()   # kept fixed even if the label itself shrinks below
            if lbl_s.get_width() > sw - pad_h * 2:
                scale = max(0.5, (sw - pad_h * 2) / lbl_s.get_width())
                lbl_s = pygame.transform.smoothscale(
                    lbl_s, (max(1, int(lbl_s.get_width()*scale)), max(1, int(lbl_s.get_height()*scale))))
            surface.blit(lbl_s, (sx + pad_h, y + pad_v))
            val_s = f_val.render(val, True, accent)
            if val_s.get_width() > sw - pad_h * 2:
                scale = max(0.5, (sw - pad_h * 2) / val_s.get_width())
                val_s = pygame.transform.smoothscale(
                    val_s, (max(1, int(val_s.get_width()*scale)), max(1, int(val_s.get_height()*scale))))
            surface.blit(val_s, (sx + pad_h, y + pad_v + lbl_h + gap_v))

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 3: CALIBRATION RECORDS
    # ──────────────────────────────────────────────────────────────────

    def _draw_calibration(self, surface, pa):
        if self._cr_detail_record is not None:
            self._draw_calibration_detail(surface, pa)
            return
        W, H = self.WIDTH, self.HEIGHT
        touch = self._touch_ui
        _card_bg(surface, pa, alpha=130)
        table_y = pa.y + self._sc(12)

        pt = self._view_patient()
        if not pt:
            _empty_state(surface,
                         pygame.Rect(pa.x, table_y+self.fnt["section"].get_height()+self._sc(18), pa.width,
                                     pa.bottom-table_y-self.fnt["section"].get_height()-self._sc(18)),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view calibration records.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._cr_up_rect = self._cr_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        records = (self.db.get_calibrations(self.account["id"],
                                             patient_id=pt["id"])
                   if hasattr(self.db, "get_calibrations") else [])

        # Simplified to the 4 fields that identify a record at a glance --
        # Average/Threshold/Sensitivity moved into the full-page Calibration
        # Record Details screen (tap a row), same on touch and desktop now.
        cols = ["Date", "Sensor", "Game", "Therapist"]
        if touch:
            seg_w = (pa.width - int(32*W/1920)) // len(cols)
            col_xs = [pa.x + int(16*W/1920) + i*seg_w for i in range(len(cols))]
        else:
            col_xs = [pa.x+int(16*W/1920),  pa.x+int(230*W/1920),
                      pa.x+int(560*W/1920), pa.x+int(900*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c, True, (85,105,135)), (cx, table_y))
        # Underline sits below the header's actual rendered height, same fix
        # as Session History (the old raw H/1080 gap was shorter than the
        # touch-scaled font, so the first record row overlapped the headers).
        hdr_line_y = table_y + self.fnt["section"].get_height() + self._sc(6)
        pygame.draw.line(surface, (210,218,230),
                         (pa.x+int(16*W/1920), hdr_line_y),
                         (pa.right-int(16*W/1920), hdr_line_y), 1)

        if not records:
            _empty_state(surface,
                         pygame.Rect(pa.x, hdr_line_y+self._sc(12), pa.width,
                                     pa.bottom-hdr_line_y-self._sc(12)),
                         "🎯", "No calibration records yet",
                         f"No calibration data found for {pt.get('full_name', 'this patient')}.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._cr_up_rect = self._cr_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        view_top    = hdr_line_y + self._sc(8)
        view_bottom = pa.bottom - int(10*H/1080)
        view_h      = view_bottom - view_top
        row_pad     = self._sc(10)
        row_line_h  = self.fnt["body"].get_height()
        arrow_w     = self._tt(44)
        content_right = pa.right - int(8*W/1920) - (arrow_w + self._sc(8))

        # Build each record's row values once, wrapping long cells onto
        # multiple lines (touch only -- desktop's columns are wide enough
        # that this was never needed there) instead of the old ellipsis,
        # so e.g. a long game name is fully readable instead of cut to
        # "Grip Stren…". Row height grows to fit whichever cell wrapped the
        # most, matching the Patient Information tab's own approach.
        row_data = []   # (wrapped_cols, row_h, record)
        for rec in records:
            date_str  = str(rec.get("calibrated_at", ""))[:10]
            game_disp = rec.get("game_name") or rec.get("game_type", "—")
            # "or" (not .get's default) -- a NULL therapist_id (LEFT JOIN)
            # hands back a real None, not a missing key, which
            # .get(key, "—") does not catch and str()'s into a literal "None".
            vals = [date_str, rec.get("sensor") or "—", game_disp,
                    rec.get("therapist_name") or "—"]
            if touch:
                wrapped = []
                for i, v in enumerate(vals):
                    avail = (col_xs[i+1] if i+1 < len(col_xs) else content_right) - col_xs[i] - self._sc(8)
                    wrapped.append(self._wrap(v, self.fnt["body"], max(avail, self._sc(20))))
                rh = max(len(w) for w in wrapped) * row_line_h + row_pad
            else:
                wrapped = [[v] for v in vals]
                rh = row_line_h + row_pad
            row_data.append((wrapped, rh, rec))

        content_h = sum(rh for _, rh, _ in row_data)
        self._cr_scroll_max = max(0, content_h - view_h)
        self._cr_scroll     = max(0, min(self._cr_scroll, self._cr_scroll_max))
        scrollable  = self._cr_scroll_max > 0
        arrow_w     = arrow_w if scrollable else 0
        content_right = pa.right - int(8*W/1920) - (arrow_w + self._sc(8) if scrollable else 0)

        # Every record row is its own tap target -> opens the full-page
        # Calibration Record Details view (see _draw_calibration_detail /
        # the _cr_detail_record dispatch at the top of this function).
        self._cr_row_rects = []
        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, view_top, content_right - pa.x - 1, view_h))
        ry = view_top - self._cr_scroll
        for j, (wrapped, rh, rec) in enumerate(row_data):
            if ry + rh >= view_top and ry <= view_bottom:
                row_r = pygame.Rect(pa.x+int(8*W/1920), ry, pa.width-int(16*W/1920), rh)
                if j % 2 == 0:
                    bg = pygame.Surface((row_r.width, row_r.height), pygame.SRCALPHA)
                    pygame.draw.rect(bg, (240,246,255,160),
                                     (0,0,row_r.width,row_r.height), border_radius=6)
                    surface.blit(bg, row_r.topleft)
                for i, (cx, lines) in enumerate(zip(col_xs, wrapped)):
                    ty = ry + row_pad // 2
                    for ln in lines:
                        surface.blit(self.fnt["body"].render(ln, True, (40,55,75)), (cx, ty))
                        ty += row_line_h
                # Clamp the hit area to the visible list band -- a row
                # scrolled half-off must not be tappable below the list
                # (same guard the Patient List rows use).
                hit_r = row_r.clip(pygame.Rect(pa.x, view_top, pa.width, view_h))
                if hit_r.height >= self._tt(32):
                    self._cr_row_rects.append((hit_r, rec))
            ry += rh
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when records overflow the viewport) ──
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - int(8*W/1920) - arrow_w
            self._cr_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._cr_down_rect = pygame.Rect(ax, view_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._cr_up_rect, "▲", self._cr_scroll > 0),
                               (self._cr_down_rect, "▼", self._cr_scroll < self._cr_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._cr_up_rect = self._cr_down_rect = pygame.Rect(0, 0, 1, 1)

    def _draw_calibration_detail(self, surface, pa):
        """Full-page Calibration Record Details (NOT a popup/modal/accordion)
        -- the historical result actually saved for this one record, never
        recalculated against today's settings. Reached by tapping a row in
        Calibration Records; Back returns there with its scroll position
        untouched (see the _cr_detail_record dispatch in _draw_calibration)."""
        W, H = self.WIDTH, self.HEIGHT
        rec = self._cr_detail_record or {}
        _card_bg(surface, pa, alpha=130)
        pad = self._sc(14)

        # ── header: Back + title ──────────────────────────────────────
        # Round icon-only asset (simple_back_button.png), not the wide
        # pill back_button_therapist.png the main dashboard/Game
        # Configuration back buttons use -- scoped to this record-detail
        # page only, per spec.
        back_d = self._tt(40)
        back_r = pygame.Rect(pa.x + pad, pa.y + self._sc(10), back_d, back_d)
        back_img = _img_fit("simple_back_button.png", back_r.width, back_r.height)
        if back_img is not None:
            surface.blit(back_img, back_img.get_rect(center=back_r.center))
        else:
            pygame.draw.circle(surface, (255, 255, 255), back_r.center, back_d // 2)
            pygame.draw.circle(surface, (205, 218, 236), back_r.center, back_d // 2, 1)
            bk_s = self.fnt["small"].render("←", True, (70, 88, 112))
            surface.blit(bk_s, bk_s.get_rect(center=back_r.center))
        self._crd_back_rect = back_r

        title_s = self.fnt["section"].render("Calibration Record Details", True, (38, 52, 78))
        surface.blit(title_s, (back_r.right + self._sc(14),
                               back_r.centery - title_s.get_height() // 2))

        view_top    = back_r.bottom + self._sc(14)
        view_bottom = pa.bottom - self._sc(10)
        view_h      = max(1, view_bottom - view_top)
        arrow_w     = self._tt(44)

        def _fmt(v, suffix=""):
            return "Not recorded" if v is None or v == "" else f"{v}{suffix}"

        def _fmt_num(v, digits=3, suffix=""):
            return "Not recorded" if v is None else f"{v:.{digits}f}{suffix}"

        pt = self._view_patient() or {}
        date_raw = str(rec.get("calibrated_at", "") or "")
        date_disp = date_raw[:16].replace("T", " ") if date_raw else "Not recorded"
        game_disp = rec.get("game_name") or rec.get("game_type") or "Not recorded"
        threshold_pct = rec.get("threshold_pct")

        sections = [
            ("Patient", [
                ("Patient Name", _fmt(pt.get("full_name") or rec.get("patient_name"))),
                ("Patient ID",   _fmt(pt.get("patient_id_str"))),
            ]),
            ("Session", [
                ("Game",             _fmt(game_disp)),
                ("Sensor",           _fmt(rec.get("sensor"))),
                ("Calibration Date", date_disp),
                ("Therapist",        _fmt(rec.get("therapist_name"))),
            ]),
            ("Trial Readings", [
                ("Trial 1", _fmt_num(rec.get("trial1"))),
                ("Trial 2", _fmt_num(rec.get("trial2"))),
                ("Trial 3", _fmt_num(rec.get("trial3"))),
                ("Average / Baseline", _fmt_num(rec.get("average"))),
            ]),
            ("Calibration Result", [
                ("Active Threshold", _fmt_num(rec.get("threshold"))),
                ("Threshold %", _fmt(threshold_pct, "%") if threshold_pct not in (None, "", 0) else "Not recorded"),
                ("Sensitivity", _fmt(rec.get("sensitivity"))),
                ("Difficulty",  _fmt(rec.get("difficulty"))),
            ]),
            ("Advanced Settings", [
                ("Preset",   _fmt(rec.get("preset"))),
                ("Speed",    _fmt(rec.get("speed"))),
                ("Duration", _fmt(rec.get("duration"))),
            ]),
            ("Sensor-Specific Calibration Values", [
                # Per-sensor raw values (grip rest/max, wrist min/max, flex
                # threshold) are computed live for the game at calibration
                # time but were never written to the calibrations table --
                # only the derived average/threshold above were. Shown
                # honestly as not recorded rather than recalculated or
                # invented for a historical row.
                ("Raw sensor calibration values", "Not recorded"),
            ]),
        ]

        f_hdr = self.fnt["body_b"]
        f_lbl = self.fnt["body"]
        f_val = self.fnt["body_b"]
        row_h = f_lbl.get_height() + self._sc(10)
        hdr_h = f_hdr.get_height() + self._sc(10)
        val_x = pa.x + pa.width // 2

        content_h = sum(hdr_h + row_h * len(rows) + self._sc(8) for _, rows in sections)
        self._crd_scroll_max = max(0, content_h - view_h)
        self._crd_scroll     = max(0, min(self._crd_scroll, self._crd_scroll_max))
        scrollable = self._crd_scroll_max > 0
        arrow_w    = arrow_w if scrollable else 0
        content_right = pa.right - pad - (arrow_w + self._sc(8) if scrollable else 0)

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x + 1, view_top, content_right - pa.x - 1, view_h))
        y = view_top - self._crd_scroll
        for title, rows in sections:
            if y + hdr_h + row_h * len(rows) >= view_top and y <= view_bottom:
                surface.blit(f_hdr.render(title, True, (40, 150, 170)), (pa.x + pad, y))
                pygame.draw.line(surface, (210, 224, 240),
                                 (pa.x + pad, y + hdr_h - self._sc(4)),
                                 (content_right, y + hdr_h - self._sc(4)), 1)
            ry = y + hdr_h
            for lbl, val in rows:
                if ry + row_h >= view_top and ry <= view_bottom:
                    surface.blit(f_lbl.render(lbl, True, (100, 116, 140)), (pa.x + pad, ry))
                    surface.blit(f_val.render(str(val), True, (35, 48, 70)), (val_x, ry))
                ry += row_h
            y = ry + self._sc(8)
        surface.set_clip(prev_clip)

        if scrollable:
            ah = view_h // 2 - self._sc(4)
            ax = pa.right - pad - arrow_w
            self._crd_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._crd_down_rect = pygame.Rect(ax, view_top + ah + self._sc(8), arrow_w, ah)
            for r, tri, on in ((self._crd_up_rect, "▲", self._crd_scroll > 0),
                               (self._crd_down_rect, "▼", self._crd_scroll < self._crd_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._crd_up_rect = self._crd_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 4: GAME CONFIGURATION
    # ──────────────────────────────────────────────────────────────────

    def _draw_gc_progress(self, surface, pa, step_num, step_label):
        """Compact "Step N of 3 · <label>" indicator, plus a Back button on
        every step EXCEPT Step 1 (there is no earlier step to return to) --
        shared by all 3 Game Configuration steps. Returns the y just below
        it, so each step's own content starts underneath."""
        W, H = self.WIDTH, self.HEIGHT
        pad = int(16 * W / 1920)
        y = pa.y + self._sc(10)

        bw = bh = self._tt(38)
        if step_num > 1:
            back_r = pygame.Rect(pa.x + pad, y, bw, bh)
            back_img = _img_fit("simple_back_button.png", back_r.width, back_r.height)
            if back_img is not None:
                surface.blit(back_img, back_img.get_rect(center=back_r.center))
            else:
                pygame.draw.rect(surface, (255, 255, 255), back_r, border_radius=8)
                pygame.draw.rect(surface, (205, 218, 236), back_r, 1, border_radius=8)
                bk_s = self.fnt["small"].render("← Back", True, (70, 88, 112))
                surface.blit(bk_s, bk_s.get_rect(center=back_r.center))
            self._gc_back_rect = back_r
            row_cy = back_r.centery
            row_bottom = back_r.bottom
        else:
            self._gc_back_rect = pygame.Rect(0, 0, 1, 1)   # Step 1 -- no Back button at all
            row_cy = y + bh // 2
            row_bottom = y + bh

        prog_txt = f"Step {step_num} of 3  ·  {step_label}"
        prog_s = self.fnt["small"].render(prog_txt, True, (90, 105, 128))
        surface.blit(prog_s, prog_s.get_rect(midright=(pa.right - pad, row_cy)))

        # 3 small dots under the row, filled up to the current step.
        dot_r  = self._sc(4)
        dot_gap = self._sc(10)
        dots_w = 3 * dot_r * 2 + 2 * dot_gap
        dx = pa.centerx - dots_w // 2 + dot_r
        for i in range(3):
            col = (40, 160, 80) if i < step_num else (205, 218, 236)
            pygame.draw.circle(surface, col, (dx + i * (2 * dot_r + dot_gap), row_bottom + self._sc(10)), dot_r)

        return row_bottom + self._sc(26)

    def _draw_game_config(self, surface, pa):
        _card_bg(surface, pa, alpha=130)
        if self._gc_step == "mode":
            self._draw_gc_step_mode(surface, pa)
        elif self._gc_step == "settings":
            self._draw_gc_step_settings(surface, pa)
        else:
            self._draw_gc_step_game(surface, pa)

    def _draw_gc_step_game(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        gc   = self.gc
        touch = self._touch_ui
        self._game_tiles = []
        pad = int(16*W/1920)

        content_y = self._draw_gc_progress(surface, pa, 1, "Choose Category & Game")

        # ── Single Skill Games / Integrated Games tab switch ───────────
        # Replaces the old "Configuring for: <patient> / Patient ID: ..."
        # banner (redundant with the sidebar's own Active Patient badge and
        # controller-status block, both always visible) and the old
        # always-both-visible stacked rows -- only one group's tiles show
        # at a time now, Single Skill Games shown by default.
        tab_h  = self._tt(44) if touch else int(40*H/1080)
        tab_gap = self._sc(10)
        f_tab  = self.fnt["body_b"] if touch else self.fnt["body"]
        tab_y  = content_y
        tab_x  = pa.x + pad
        self._gc_tab_rects = {}
        for key, label in (("single", "Single Skill Games"), ("integrated", "Integrated Games")):
            tab_w = f_tab.size(label)[0] + self._sc(28)
            tr_tab = pygame.Rect(tab_x, tab_y, tab_w, tab_h)
            active = (self._gc_active_tab == key)
            pygame.draw.rect(surface, (35, 45, 65) if active else (255, 255, 255),
                             tr_tab, border_radius=10)
            if not active:
                pygame.draw.rect(surface, (205, 218, 236), tr_tab, 1, border_radius=10)
            lbl = f_tab.render(label, True, (255, 255, 255) if active else (70, 88, 112))
            surface.blit(lbl, lbl.get_rect(center=tr_tab.center))
            self._gc_tab_rects[key] = tr_tab
            tab_x = tr_tab.right + tab_gap

        # ── Game tiles (whichever group is active) ──────────────────────
        # No card/box behind the sprite any more -- it IS the button now.
        # Selection is shown with a soft glow behind the sprite (never a
        # hard-edged container) plus the same "which specific game" caption
        # as before.
        tg = int(14*W/1920)
        if touch:
            tw = (pa.width - 2*pad - 2*tg) // 3
            th = self._tt(150)
        else:
            tw = int(460*W/1920); th = int(170*H/1080)

        ty = tab_y + tab_h + int((20 if touch else 24)*H/1080)
        active_games = SINGLE_SKILL_GAMES if self._gc_active_tab == "single" else INTEGRATED_GAMES
        idx_offset = 0 if self._gc_active_tab == "single" else len(SINGLE_SKILL_GAMES)

        total_w = len(active_games) * tw + (len(active_games) - 1) * tg
        start_x = pa.x + (pa.width - total_w) // 2
        img_pad = self._sc(4)
        for i, (gname, gtype) in enumerate(active_games):
            tx  = start_x + i * (tw + tg)
            tr  = pygame.Rect(tx, ty, tw, th)
            sel = gc["selected_game"] and gc["selected_game"][1] == gtype
            bc  = PANEL_COLORS.get(idx_offset + i, (180,200,220))

            # When selected, the image shrinks a little to leave dedicated
            # room for the "which specific game" caption below it (Wrist
            # Rotation maps to several games) -- the caption used to overlay
            # the image directly and collide with its own baked-in label.
            cap_h = (self.fnt["small"].get_height() + self._sc(6)) if (sel and gc["selected_game"]) else 0
            img = _img_fit(GAME_TILE_ASSETS.get(gtype), tw - 2*img_pad, th - 2*img_pad - cap_h)
            if img is not None:
                img_r = img.get_rect()
                img_r.centerx = tr.centerx
                img_r.top = tr.y + img_pad
                if sel:
                    # soft glow, not a box -- several progressively larger,
                    # more transparent rounded rects behind the sprite
                    for k in range(4, 0, -1):
                        infl = k * self._sc(5)
                        glow_r = img_r.inflate(infl * 2, infl * 2)
                        glow_s = pygame.Surface(glow_r.size, pygame.SRCALPHA)
                        pygame.draw.rect(glow_s, (*bc, max(12, 55 // k)),
                                         (0, 0, *glow_r.size), border_radius=glow_r.height // 2)
                        surface.blit(glow_s, glow_r.topleft)
                surface.blit(img, img_r)
            else:
                # fallback if an asset is ever missing -- the original text tile
                _fg = self.fnt["label"] if touch else self.fnt["body_b"]
                lbl_s = _fg.render(gtype, True, (55,72,95))
                img_r = lbl_s.get_rect(center=tr.center)
                surface.blit(lbl_s, img_r)

            if sel and gc["selected_game"]:
                cap_txt = self.fnt["small"].render(gc["selected_game"][0], True, (255, 255, 255))
                cap_r = pygame.Rect(0, 0, cap_txt.get_width() + self._sc(14), cap_txt.get_height() + self._sc(6))
                cap_r.midtop = (tr.centerx, img_r.bottom + self._sc(4))
                cap_bg = pygame.Surface(cap_r.size, pygame.SRCALPHA)
                pygame.draw.rect(cap_bg, (*bc, 235), (0, 0, *cap_r.size), border_radius=cap_r.height // 2)
                surface.blit(cap_bg, cap_r.topleft)
                surface.blit(cap_txt, cap_txt.get_rect(center=cap_r.center))

            self._game_tiles.append((tr, (gname, gtype)))

        # ── Proceed to Session Mode button ───────────────────────
        game_chosen = gc["selected_game"] is not None
        if touch:
            bw = self.fnt["btn"].size("Next →")[0] + self._tt(40)
            next_r = pygame.Rect(pa.right - pad - bw, pa.bottom - self._tt(60) - int(8*H/1080),
                                 bw, self._tt(58))
        else:
            next_r = pygame.Rect(pa.right-int(260*W/1920), pa.bottom-int(60*H/1080),
                                 int(244*W/1920), int(46*H/1080))
        _img_btn(surface, next_r, "next_button.png", game_chosen, self.gc_next_hov,
                "Next →", self.fnt["btn"], col_normal=(40,160,80),
                col_disabled=(175,188,202), radius=12)
        self._gc_next_rect = next_r if game_chosen else pygame.Rect(0,0,1,1)

    def _draw_gc_step_mode(self, surface, pa):
        """Step 2: Target Mode vs Timed Mode -- two big selectable cards,
        per spec ("Display the two options as clear, selectable cards.
        Only one mode may be selected at a time")."""
        W, H = self.WIDTH, self.HEIGHT
        pad = int(16 * W / 1920)
        content_y = self._draw_gc_progress(surface, pa, 2, "Session Mode")
        content_y += self._sc(6)

        # The "How should this session end?" heading is gone -- the two
        # mode cards move up into the space it used to occupy and grow to
        # fill it, instead of sitting in a fixed-height box sized for the
        # heading-present layout.
        bw, bh = self.fnt["btn"].size("Next →")[0] + self._tt(40), self._tt(58)
        next_r = pygame.Rect(pa.right - pad - bw, pa.bottom - bh - int(8 * H / 1080), bw, bh)

        cards = [
            ("target", "Target Mode", "Complete a set goal",
             "The patient works toward a set number of successful reps."),
            ("timed",  "Timed Mode",  "Play for a set duration",
             "The patient performs as many successful reps as possible."),
        ]
        gap = self._sc(18)
        card_w = (pa.width - 2 * pad - gap) // 2
        card_h = max(self._tt(150), next_r.top - self._sc(14) - content_y)
        self._gc_mode_rects = {}
        for i, (key, title, sub, desc) in enumerate(cards):
            cx = pa.x + pad + i * (card_w + gap)
            cr = pygame.Rect(cx, content_y, card_w, card_h)
            sel = (self.gc.get("session_mode") == key)
            pygame.draw.rect(surface, (235, 247, 238) if sel else (255, 255, 255), cr, border_radius=14)
            pygame.draw.rect(surface, (40, 160, 80) if sel else (205, 218, 236),
                             cr, 3 if sel else 1, border_radius=14)

            # Render every line first so the whole text block's real height
            # is known, then vertically center it in the (now taller) card
            # instead of always hugging the top -- the same measure-then-
            # position approach ui_cards.draw_state_card() uses.
            t_s = self.fnt["body_b"].render(title, True, (30, 45, 70))
            s_s = self.fnt["small"].render(sub, True, (40, 160, 80) if sel else (90, 105, 128))
            desc_lines = self._wrap(desc, self.fnt["small"], card_w - self._sc(32))
            line_h = self.fnt["small"].get_height()
            block_h = (t_s.get_height() + self._sc(4) + s_s.get_height() + self._sc(10)
                      + len(desc_lines) * (line_h + self._sc(2)))
            ty = max(cr.y + self._sc(16), cr.centery - block_h // 2)

            surface.blit(t_s, (cr.x + self._sc(16), ty))
            ty += t_s.get_height() + self._sc(4)
            surface.blit(s_s, (cr.x + self._sc(16), ty))
            ty += s_s.get_height() + self._sc(10)
            for line in desc_lines:
                ln_s = self.fnt["small"].render(line, True, (90, 105, 128))
                surface.blit(ln_s, (cr.x + self._sc(16), ty))
                ty += ln_s.get_height() + self._sc(2)
            if sel:
                ck_r = pygame.Rect(0, 0, self._sc(22), self._sc(22))
                ck_r.topright = (cr.right - self._sc(12), cr.y + self._sc(12))
                pygame.draw.circle(surface, (40, 160, 80), ck_r.center, self._sc(11))
                pygame.draw.lines(surface, (255, 255, 255), False, [
                    (ck_r.centerx - ck_r.width*0.22, ck_r.centery),
                    (ck_r.centerx - ck_r.width*0.05, ck_r.centery + ck_r.height*0.18),
                    (ck_r.centerx + ck_r.width*0.24, ck_r.centery - ck_r.height*0.18),
                ], max(1, self._sc(2)))
            self._gc_mode_rects[key] = cr

        _img_btn(surface, next_r, "next_button.png", True, self.gc_next_hov,
                "Next →", self.fnt["btn"], col_normal=(40, 160, 80), radius=12)
        self._gc_next_rect = next_r

    def _gc_handle_mode_click(self, pos):
        for key, r in self._gc_mode_rects.items():
            if r.collidepoint(pos):
                play_click()
                self.gc["session_mode"] = key
                return

    def _draw_gc_step_settings(self, surface, pa):
        """Step 3: difficulty + (Target reps XOR Duration), per spec
        ("Do not show both target and duration fields simultaneously")."""
        W, H = self.WIDTH, self.HEIGHT
        gc = self.gc
        pad = int(16 * W / 1920)
        content_y = self._draw_gc_progress(surface, pa, 3, "Session Settings")
        content_y += self._sc(10)

        game_name = (gc.get("selected_game") or (None,))[0] or "—"

        # ── Difficulty pills ────────────────────────────────────────────
        lbl_s = self.fnt["body_b"].render("Difficulty", True, (55, 72, 95))
        surface.blit(lbl_s, (pa.x + pad, content_y))
        content_y += lbl_s.get_height() + self._sc(8)

        self._gc_diff_rects = {}
        pw = self._tt(110)
        ph = self._tt(44)
        pgap = self._sc(10)
        for i, diff in enumerate(("Easy", "Medium", "Hard")):
            pr = pygame.Rect(pa.x + pad + i * (pw + pgap), content_y, pw, ph)
            sel = (gc.get("difficulty") == diff)
            pygame.draw.rect(surface, (40, 160, 80) if sel else (255, 255, 255), pr, border_radius=10)
            if not sel:
                pygame.draw.rect(surface, (205, 218, 236), pr, 1, border_radius=10)
            d_s = self.fnt["body_b"].render(diff, True, (255, 255, 255) if sel else (70, 88, 112))
            surface.blit(d_s, d_s.get_rect(center=pr.center))
            self._gc_diff_rects[diff] = pr
        content_y += ph + self._sc(22)

        # ── Target reps XOR Duration stepper ────────────────────────────
        mode = gc.get("session_mode", "target")
        difficulty = gc.get("difficulty", "Medium")
        if mode == "target":
            default_val, lo, hi = self._game_goal_default(game_name, difficulty)
            field_lbl = "Target repetitions"
        else:
            default_val = TIMED_DURATION_DEFAULT_SEC
            lo, hi = min(TIMED_DURATION_TEST_PRESETS_SEC), 600
            field_lbl = "Session duration"

        key = "target_reps" if mode == "target" else "duration_sec"
        if gc.get(key) is None:
            gc[key] = default_val
        gc[key] = max(lo, min(hi, gc[key]))

        lbl_s = self.fnt["body_b"].render(field_lbl, True, (55, 72, 95))
        surface.blit(lbl_s, (pa.x + pad, content_y))
        content_y += lbl_s.get_height() + self._sc(10)

        bw2 = self._tt(44)
        vw  = self._tt(140)
        mrect = pygame.Rect(pa.x + pad, content_y, bw2, bw2)
        vrect = pygame.Rect(mrect.right + self._sc(6), content_y, vw, bw2)
        prect = pygame.Rect(vrect.right + self._sc(6), content_y, bw2, bw2)
        for rct, lbl in ((mrect, "–"), (prect, "+")):
            pygame.draw.rect(surface, (255, 255, 255), rct, border_radius=8)
            pygame.draw.rect(surface, (205, 218, 236), rct, 1, border_radius=8)
            ls = self.fnt["body_b"].render(lbl, True, (40, 55, 80))
            surface.blit(ls, ls.get_rect(center=rct.center))
        pygame.draw.rect(surface, (235, 247, 238), vrect, border_radius=8)
        pygame.draw.rect(surface, (40, 160, 80), vrect, 1, border_radius=8)
        if mode == "target":
            val_txt = f"{gc[key]}"
        else:
            # Seconds for the short testing presets, minutes for a normal
            # (>= 1 minute) duration -- a flat "M:SS" made "0:10" read like
            # a stopwatch about to run out, not a quick dev-only preset.
            val_txt = (f"{gc[key]}s" if gc[key] < 60 else
                       (f"{gc[key] // 60} min" if gc[key] % 60 == 0 else
                        f"{gc[key] // 60}m {gc[key] % 60}s"))
        vs = self.fnt["body_b"].render(val_txt, True, (30, 45, 70))
        surface.blit(vs, vs.get_rect(center=vrect.center))
        self._gc_val_minus_rect = mrect
        self._gc_val_plus_rect  = prect
        content_y += bw2 + self._sc(14)

        # TEMPORARY testing presets (10s / 30s) -- lets a full session run
        # end to end in seconds instead of waiting out a real 7-minute
        # timer. Remove this block (and the matching branch in
        # _gc_handle_settings_click) before final deployment.
        self._gc_test_preset_rects = {}
        if mode == "timed" and TIMED_DURATION_TEST_PRESETS_SEC:
            tp_lbl = self.fnt["small"].render("Testing only:", True, (160, 110, 20))
            surface.blit(tp_lbl, (pa.x + pad, content_y))
            tpx = pa.x + pad + tp_lbl.get_width() + self._sc(8)
            tph = self._tt(32)
            for secs in TIMED_DURATION_TEST_PRESETS_SEC:
                tp_s = self.fnt["small"].render(f"{secs}s", True, (160, 110, 20))
                tpw = tp_s.get_width() + self._sc(18)
                tpr = pygame.Rect(tpx, content_y - self._sc(3), tpw, tph)
                pygame.draw.rect(surface, (255, 243, 210), tpr, border_radius=8)
                pygame.draw.rect(surface, (225, 185, 90), tpr, 1, border_radius=8)
                surface.blit(tp_s, tp_s.get_rect(center=tpr.center))
                self._gc_test_preset_rects[secs] = tpr
                tpx = tpr.right + self._sc(8)
            content_y += tph + self._sc(4)

        bw, bh = self.fnt["btn"].size("Next →")[0] + self._tt(40), self._tt(58)
        next_r = pygame.Rect(pa.right - pad - bw, pa.bottom - bh - int(8 * H / 1080), bw, bh)
        _img_btn(surface, next_r, "next_button.png", True, self.gc_next_hov,
                "Next →", self.fnt["btn"], col_normal=(40, 160, 80), radius=12)
        self._gc_next_rect = next_r

    def _gc_handle_settings_click(self, pos):
        gc = self.gc
        for diff, r in self._gc_diff_rects.items():
            if r.collidepoint(pos):
                play_click()
                gc["difficulty"] = diff
                return
        mode = gc.get("session_mode", "target")
        key = "target_reps" if mode == "target" else "duration_sec"
        step = 1 if mode == "target" else TIMED_DURATION_STEP_SEC
        if self._gc_val_minus_rect.collidepoint(pos):
            play_click()
            gc[key] = max(0, (gc.get(key) or 0) - step)
            return
        if self._gc_val_plus_rect.collidepoint(pos):
            play_click()
            gc[key] = (gc.get(key) or 0) + step
            return
        # TEMPORARY testing presets -- remove alongside the draw-side block
        # in _draw_gc_step_settings before final deployment.
        if mode == "timed":
            for secs, r in getattr(self, "_gc_test_preset_rects", {}).items():
                if r.collidepoint(pos):
                    play_click()
                    gc[key] = secs
                    return

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 5: START SESSION
    # ──────────────────────────────────────────────────────────────────

    def _draw_start_session(self, surface, pa):
        """Redesigned Start Session screen: Game Information card, Patient
        Information card, a Session Readiness Checklist, and a single CTA
        button at the bottom -- "Calibrate →" until the session is ready,
        then "Start Session →". One responsive layout (via self._sc/_tt)
        for both desktop and the 800x480 touch panel, sized so everything
        -- including the button -- always fits without scrolling."""
        _card_bg(surface, pa, alpha=130)
        gc = self.gc
        pt = self.selected_patient or {}

        cal_done     = self.calibration_done or self.calibration_bypassed
        cal_mismatch = self._calibration_mismatched()

        pad    = self._sc(14)
        x0     = pa.x + pad
        card_w = pa.width - 2 * pad

        # ── bottom CTA button geometry, computed first so the content
        # above always stops clear of it ──
        btn_h = self._tt(52)
        btn_r = pygame.Rect(x0, pa.bottom - pad - btn_h, card_w, btn_h)
        content_bottom = btn_r.top - self._sc(10)

        y = pa.y + pad
        icon_d = self._sc(50)

        # ── A. Game Information card ──────────────────────────────────
        game_name = gc["selected_game"][0] if gc["selected_game"] else None
        if game_name:
            game_cat = GAME_CATEGORY.get(game_name, "")
            hw_seen = []
            for _k, _lbl, hw, _fmt in GAME_SENSOR_SPEC.get(game_name, []):
                if hw not in hw_seen:
                    hw_seen.append(hw)
            goal_txt = self._game_goal_text(game_name)
            sub = "  •  ".join(p for p in (game_cat, " + ".join(hw_seen), goal_txt) if p)
        else:
            game_name, sub = "No game selected", "Configure a game first"

        gcard_h = icon_d + self._sc(18)
        gcard = pygame.Rect(x0, y, card_w, gcard_h)
        _card_bg(surface, gcard, alpha=235, border_col=(185, 210, 240), border_w=1)
        chip = pygame.Rect(0, 0, icon_d, icon_d)
        chip.midleft = (gcard.x + self._sc(10), gcard.centery)
        pygame.draw.rect(surface, (255, 247, 222), chip, border_radius=self._sc(12))
        pygame.draw.rect(surface, (235, 205, 120), chip, 1, border_radius=self._sc(12))
        icon_asset = GAME_ICON_ASSET.get(game_name)
        icon_im = _img_fit(icon_asset, chip.width - self._sc(10), chip.height - self._sc(10)) \
            if icon_asset else None
        if icon_im is not None:
            surface.blit(icon_im, icon_im.get_rect(center=chip.center))
        tx = chip.right + self._sc(12)
        name_s = self.fnt["body_b"].render(game_name, True, (38, 52, 78))
        sub_s  = self.fnt["small"].render(sub, True, (110, 125, 150))
        gty = gcard.centery - (name_s.get_height() + self._sc(2) + sub_s.get_height()) // 2
        surface.blit(name_s, (tx, gty))
        surface.blit(sub_s, (tx, gty + name_s.get_height() + self._sc(2)))
        y += gcard_h + self._sc(8)

        # ── B. Patient Information card ───────────────────────────────
        pcard_h = icon_d + self._sc(14)
        pcard = pygame.Rect(x0, y, card_w, pcard_h)
        _card_bg(surface, pcard, alpha=235, border_col=(185, 210, 240), border_w=1)
        pchip_d = int(icon_d * 0.86)
        pchip_c = (pcard.x + self._sc(10) + pchip_d // 2, pcard.centery)
        pygame.draw.circle(surface, (222, 236, 252), pchip_c, pchip_d // 2)
        pim = _img_fit("patient_icon_dashboard.png", pchip_d - self._sc(8), pchip_d - self._sc(8))
        if pim is not None:
            surface.blit(pim, pim.get_rect(center=pchip_c))
        ptx = pchip_c[0] + pchip_d // 2 + self._sc(12)
        pname = pt.get("full_name") or "No patient selected"
        pid   = pt.get("patient_id_str") or "—"
        pname_s = self.fnt["body_b"].render(pname, True, (38, 52, 78))
        pid_s   = self.fnt["small"].render(pid, True, (110, 125, 150))
        pty = pcard.centery - (pname_s.get_height() + self._sc(2) + pid_s.get_height()) // 2
        surface.blit(pname_s, (ptx, pty))
        surface.blit(pid_s, (ptx, pty + pname_s.get_height() + self._sc(2)))
        y += pcard_h + self._sc(8)

        # ── C. Session Readiness Checklist -- sized from its own content
        # (a capped, comfortable row height), never stretched to consume
        # 100% of whatever space is left above the button -- that was
        # leaving the 4 rows scattered across a mostly-empty card on a
        # roomy desktop window. Any leftover room just becomes blank
        # margin before the button instead.
        # "Game Configured" -- true once the session's settings have actually
        # been confirmed through the calibration flow's results screen
        # (self.calibration_result["params"], populated whichever way the
        # therapist finished it: the Recommended preset left as-is, or
        # Advanced Settings customized -- both end in the same _accept()
        # that fills "params"), not merely once a game has been picked.
        # Bypass skips that whole screen, so it counts too -- there is no
        # params set to confirm in that path.
        game_configured = self.calibration_bypassed or bool(
            (self.calibration_result or {}).get("params"))
        # "Patient Selected" / "Game Selected" are still REQUIRED for the
        # session to be ready -- the game-config flow already can't reach
        # this screen without both -- but are no longer shown as rows in the
        # visible checklist (which only needs to surface the three steps the
        # therapist still has to actively do here). `steps` (hidden + shown)
        # is still what the readiness gate below is computed from; only
        # `display_steps` drives the on-screen rows/spacing.
        _hidden_requirements = [
            ("Patient Selected", self.selected_patient is not None),
            ("Game Selected",    gc["selected_game"] is not None),
        ]
        display_steps = [
            ("Game Configured",      game_configured),
            ("Controller Connected", self._controller_status()[0] == "connected"),
            ("Sensor Calibrated",    cal_done and not cal_mismatch),
        ]
        steps = _hidden_requirements + display_steps
        # The CTA button only becomes "Start Session" once every item above
        # is checked -- the checklist IS the readiness gate now, not a
        # separate self._session_ready() computation. The dev-only Test Mode
        # toggle's whole purpose is letting a developer launch a game without
        # having completed any of the hardware/prep-heavy steps, so it treats
        # Sensor Calibrated, Game Configured, AND Controller Connected as
        # satisfied for THIS gate -- it never touches what the checklist
        # itself displays, so e.g. a disconnected controller still correctly
        # shows as disconnected even while the CTA reads "Start Session".
        _bypassable = {"Sensor Calibrated", "Game Configured", "Controller Connected"}
        test_mode_on = _TEST_MODE_AVAILABLE and self._test_mode_bypass
        if test_mode_on:
            ready = all(ok or lbl in _bypassable for lbl, ok in steps)
        else:
            ready = all(ok for _, ok in steps)
        hpad = self._sc(10)
        head_s = self.fnt["section"].render("Session Readiness Checklist", True, (75, 95, 125))
        # More room between the heading and the first row, and a taller cap
        # per row, now that only 3 rows (not 5) need to share the available
        # height -- both freed up by dropping the two hidden rows above.
        head_gap = self._sc(16)
        avail_rows_h = max(1, content_bottom - (y + hpad + head_s.get_height() + head_gap) - hpad)
        row_h = min(self._sc(62), avail_rows_h / len(display_steps))
        checklist_h = hpad + head_s.get_height() + head_gap + row_h * len(display_steps) + hpad
        checklist_r = pygame.Rect(x0, y, card_w, min(checklist_h, content_bottom - y))
        _card_bg(surface, checklist_r, alpha=235, border_col=(185, 210, 240), border_w=1)
        surface.blit(head_s, (checklist_r.x + hpad, checklist_r.y + hpad))

        # Dev-only "Test Mode" toggle, tucked into the checklist header row
        # next to its title -- permanently shown for this development phase
        # (_TEST_MODE_AVAILABLE), remove that flag once testing is done.
        if _TEST_MODE_AVAILABLE:
            tm_lbl = "TEST MODE ON" if self._test_mode_bypass else "Test Mode (Bypass)"
            tm_s = self.fnt["tag"].render(tm_lbl, True, (255, 255, 255))
            tm_w = tm_s.get_width() + self._sc(16)
            tm_h = max(self._sc(22), tm_s.get_height() + self._sc(8))
            tm_r = pygame.Rect(checklist_r.right - hpad - tm_w, checklist_r.y + hpad, tm_w, tm_h)
            tm_col = ((170, 40, 40) if self._test_mode_hov else (200, 60, 55)) \
                if self._test_mode_bypass else \
                ((90, 100, 115) if self._test_mode_hov else (110, 120, 136))
            pygame.draw.rect(surface, tm_col, tm_r, border_radius=self._sc(6))
            surface.blit(tm_s, tm_s.get_rect(center=tm_r.center))
            self._test_mode_btn_rect = tm_r
        else:
            self._test_mode_btn_rect = pygame.Rect(0, 0, 1, 1)

        rows_top = checklist_r.y + hpad + head_s.get_height() + head_gap
        dot_r    = self._sc(9)
        for i, (lbl, ok) in enumerate(display_steps):
            cy = int(rows_top + i * row_h + row_h / 2)
            cx = checklist_r.x + hpad + dot_r
            if ok:
                pygame.draw.circle(surface, (55, 175, 95), (cx, cy), dot_r)
                k = dot_r * 0.55
                pygame.draw.lines(surface, (255, 255, 255), False,
                    [(cx - k, cy), (cx - k * 0.2, cy + k), (cx + k, cy - k)], 2)
            else:
                pygame.draw.circle(surface, (203, 212, 226), (cx, cy), dot_r)
            tcol = (40, 55, 75) if ok else (130, 145, 165)
            s = self.fnt["body"].render(lbl, True, tcol)
            surface.blit(s, (cx + dot_r + self._sc(10), cy - s.get_height() // 2))

        # ── D. Single CTA button -- "Calibrate →" until ready, then
        # "Start Session →"; reuses the two EXISTING click-handled rects
        # (only one is ever live at a time) so the click logic for both
        # actions -- opening calibration, launching the game -- is
        # completely unchanged. ──
        if ready:
            label = "Start Session"
            self._start_btn_rect     = btn_r
            self._calibrate_btn_rect = pygame.Rect(0, 0, 1, 1)
            hovered = self.start_hov
        else:
            label = "Re-Calibrate" if cal_mismatch else "Calibrate"
            self._calibrate_btn_rect = btn_r
            self._start_btn_rect     = pygame.Rect(0, 0, 1, 1)
            hovered = self._calibrate_hov
        pygame.draw.rect(surface, (28, 150, 176) if hovered else (34, 170, 198),
                         btn_r, border_radius=self._sc(14))
        # Text-only, centered -- this used to append a "→" rendered with a
        # "segoeuisymbol" SysFont (Windows-only; on the Pi it silently
        # falls back to a font without that glyph, so the arrow never
        # rendered there, same root cause as the Confirm/Cancel dialog
        # icons above).
        lbl_s = self.fnt["btn"].render(label, True, (255, 255, 255))
        surface.blit(lbl_s, lbl_s.get_rect(center=btn_r.center))

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE MODAL
    # ──────────────────────────────────────────────────────────────────

    def _draw_overlay(self, surface):
        ov = pygame.Surface((self.WIDTH,self.HEIGHT), pygame.SRCALPHA)
        ov.fill((12,18,32,172)); surface.blit(ov,(0,0))

    def _draw_edit_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mr   = self.edit_modal_rect
        ms   = pygame.Surface((mr.width,mr.height), pygame.SRCALPHA)
        pygame.draw.rect(ms, (228, 238, 252, 252), (0, 0, mr.width, mr.height), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface,(175,205,235),mr,1,border_radius=16)
        hs = self.fnt["panel_title"].render("Edit Profile",True,(38,52,78))
        surface.blit(hs,(mr.x+self._sc(18), mr.y+self._sc(10)))

        bcx,bcy = self.edit_big_center
        draw_icon(surface,self.edit_selected_icon,bcx,bcy,self.edit_big_r,shadow=True,
                  border_color=(40,160,220), border_width=3)
        # "Change Icon" -- opens the dedicated picker popup (large, scrollable)
        cr = self.edit_change_icon_rect
        pygame.draw.rect(surface, (236, 242, 250), cr, border_radius=9)
        pygame.draw.rect(surface, (95, 130, 175), cr, 2, border_radius=9)
        chg_lbl = "Change Icon"
        cs = self.fnt["tag"].render(chg_lbl, True, (60, 95, 150))
        if cs.get_width() > cr.width - self._sc(8):
            cs = self.fnt["tag"].render("Change", True, (60, 95, 150))
        surface.blit(cs, cs.get_rect(center=cr.center))

        for i,field in enumerate(self.edit_fields):
            active=(i==self.edit_active_field)
            rect=field["rect"]
            surface.blit(self.fnt["small"].render(field["label"],True,(80,95,115)),
                         (rect.x, rect.y-self.fnt["small"].get_height()-self._sc(4)))
            bc=(40,160,220) if active else (185,205,228)
            pygame.draw.rect(surface,(255,255,255),rect,border_radius=9)
            pygame.draw.rect(surface,bc,rect,3 if active else 1,border_radius=9)
            if field["key"]=="role":
                val=field["value"] or field["placeholder"]
                ts=self.fnt["input"].render(val,True,(40,50,65) if field["value"] else (175,188,205))
                surface.blit(ts,ts.get_rect(midleft=(rect.x+self._sc(12),rect.centery)))
                chev=self.fnt["sym26"].render("▼",True,(95,115,145))
                surface.blit(chev,chev.get_rect(midright=(rect.right-self._sc(12),rect.centery)))
            else:
                val=field["value"]
                ts=(self.fnt["input"].render("•"*len(val) if field["is_pin"] else val,
                    True,(40,50,65)) if val else
                    self.fnt["input"].render(field["placeholder"],True,(175,188,205)))
                surface.blit(ts,ts.get_rect(midleft=(rect.x+self._sc(12),rect.centery)))
                if active and val:
                    cx2=rect.x+self._sc(12)+ts.get_width()+2
                    pygame.draw.line(surface,(40,160,220),
                                     (cx2,rect.centery-int(9*H/1080)),
                                     (cx2,rect.centery+int(9*H/1080)),2)

        if self.edit_role_open:
            rf=self.edit_fields[2]["rect"]
            oh=self.edit_role_options[0]["rect"].height
            pr=pygame.Rect(rf.x,rf.bottom-1,rf.width,len(ROLES)*oh+4)
            pygame.draw.rect(surface,(248,251,255),pr,border_radius=9)
            pygame.draw.rect(surface,(40,160,220),pr,2,border_radius=9)
            for opt in self.edit_role_options:
                ts=self.fnt["input"].render(opt["label"],True,(40,50,65))
                surface.blit(ts,ts.get_rect(midleft=(opt["rect"].x+self._sc(12),opt["rect"].centery)))

        if self.edit_error:
            es=self.fnt["modal_err"].render(self.edit_error,True,(210,50,50))
            surface.blit(es,(mr.x+self._sc(18),
                             self.edit_save_rect.y-es.get_height()-self._sc(6)))

        for rect,cn,ch,hov,lbl,fnt in [
            (self.edit_save_rect,  (40,160,220),(25,125,180),self.edit_save_hov,  "Save",           self.fnt["btn"]),
            (self.edit_cancel_rect,(175,190,210),(148,162,180),self.edit_cancel_hov,"Cancel",        self.fnt["btn"]),
            (self.edit_delete_rect,(200,50,50),(165,28,28),self.edit_delete_hov,"Delete Account",    self.fnt["small"]),
        ]:
            pygame.draw.rect(surface,ch if hov else cn,rect,border_radius=10)
            s=fnt.render(lbl,True,(255,255,255))
            surface.blit(s,s.get_rect(center=rect.center))

    def _draw_icon_picker_popup(self, surface):
        """Dedicated icon-selection popup: bigger than the old inline rail,
        icons sized generously from the popup's own width (not shrunk to
        force all 10 to fit at once), and scrollable when they don't."""
        W, H = self.WIDTH, self.HEIGHT
        pad = self._sc(20)
        pw = min(int(W * 0.92), self._sc(560))
        ph = min(int(H * 0.94), self._sc(440))
        px = (W - pw) // 2
        py = (H - ph) // 2
        pr = pygame.Rect(px, py, pw, ph)

        ms = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(ms, (250, 252, 255, 255), (0, 0, pw, ph), border_radius=18)
        surface.blit(ms, pr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), pr, 2, border_radius=18)

        title = self.fnt["panel_title"].render("Choose Profile Icon", True, (38, 52, 78))
        surface.blit(title, (pr.x + pad, pr.y + self._sc(12)))
        hl_y = pr.y + self._sc(12) + title.get_height() + self._sc(8)
        pygame.draw.line(surface, (200, 218, 240), (pr.x + pad, hl_y), (pr.right - pad, hl_y), 1)

        btn_h = self._tt(48)
        top = hl_y + self._sc(14)
        bottom = pr.bottom - pad - btn_h - self._sc(10)
        view_h = bottom - top

        # Icons sized from the popup's own width -- comfortably large and
        # spaced, but pulled in a bit from the earlier oversized cap -- with
        # however many rows that takes, scrolling if they don't all fit
        # rather than shrinking them back down to the old cramped size.
        cols = 3
        gap = self._sc(18)
        avail_w = pw - 2 * pad
        r = max(self._sc(24), min(self._sc(46), (avail_w - (cols - 1) * gap) // (2 * cols)))
        self._eip_r = r
        step = 2 * r + gap
        rows_n = (12 + cols - 1) // cols
        total_h = rows_n * step - gap
        self._eip_scroll_max = max(0, total_h - view_h)
        self._eip_scroll = max(0, min(self._eip_scroll, self._eip_scroll_max))
        arrow_w = self._tt(40) if self._eip_scroll_max > 0 else 0
        grid_w = cols * step - gap
        grid_cx = pr.x + pad + (avail_w - (arrow_w + self._sc(8) if arrow_w else 0)) // 2

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pr.x, top, pw, view_h))
        self._eip_circles = []
        y0 = top - self._eip_scroll
        for i in range(12):
            idx = i + 1
            col, row = i % cols, i // cols
            cx = grid_cx + (col - (cols - 1) / 2) * step
            cy = y0 + r + row * step
            if cy + r < top or cy - r > bottom:
                continue
            self._eip_circles.append((int(cx), int(cy), idx))
            sel = (self.edit_selected_icon == idx)
            draw_icon(surface, idx, int(cx), int(cy), r, shadow=True,
                     border_color=(40, 160, 220) if sel else None,
                     border_width=max(3, self._sc(4)) if sel else 0)
        surface.set_clip(prev_clip)

        if self._eip_scroll_max > 0:
            ax = pr.right - pad - arrow_w
            ah = view_h // 2 - self._sc(4)
            self._eip_up_rect = pygame.Rect(ax, top, arrow_w, ah)
            self._eip_down_rect = pygame.Rect(ax, top + ah + self._sc(8), arrow_w, ah)
            for r2, tri, on in ((self._eip_up_rect, "▲", self._eip_scroll > 0),
                               (self._eip_down_rect, "▼",
                                self._eip_scroll < self._eip_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244),
                                 r2, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r2, 1, border_radius=8)
                g = self.fnt["sym26"].render(tri, True,
                                             (45, 90, 150) if on else (188, 196, 206))
                surface.blit(g, g.get_rect(center=r2.center))
        else:
            self._eip_up_rect = self._eip_down_rect = pygame.Rect(0, 0, 1, 1)

        done_w = self._sc(160)
        self._eip_done_rect = pygame.Rect(pr.centerx - done_w // 2,
                                          pr.bottom - pad - btn_h, done_w, btn_h)
        hov = self._eip_done_rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, (25, 130, 185) if hov else (40, 160, 220),
                         self._eip_done_rect, border_radius=10)
        ds = self.fnt["btn"].render("Done", True, (255, 255, 255))
        surface.blit(ds, ds.get_rect(center=self._eip_done_rect.center))

    def _draw_skill_game_modal(self, surface):
        # Sized from _sc/_tt so rows and the Close button stay finger-sized on
        # the 800x480 panel -- the old H/1080-only math produced ~21px rows
        # and a ~16px-tall Close button here.
        W, H = self.WIDTH, self.HEIGHT

        # Dim the background -- matches every other modal's visual language
        # and makes it visually obvious the rest of the screen is inert
        # while this is open (the actual input-blocking itself is handled
        # in _handle_click / main.py, not by this overlay).
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((8, 12, 20, 140))
        surface.blit(ov, (0, 0))

        skill = self._gc_skill_modal_type or ""
        games = SKILL_GAMES.get(skill, [])

        pad      = self._sc(22)
        item_gap = self._sc(8)
        item_h   = self._tt(52)
        btn_h    = self._tt(44)
        header_h = self.fnt["modal_lbl"].get_height() + self._sc(20)
        footer_h = self._sc(16) + btn_h + self._sc(16)

        ts = self.fnt["modal_lbl"].render(f"Select a Game  —  {skill}", True, (38, 52, 78))
        row_w_needed = max((self.fnt["body_b"].size(g)[0] for g in games), default=0) + self._sc(32)
        mw = min(max(ts.get_width() + pad * 2, row_w_needed + pad * 2, self._sc(360)), int(W * 0.9))
        mh = min(header_h + len(games) * (item_h + item_gap) + footer_h, int(H * 0.92))
        mx = (W - mw) // 2
        my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (245, 249, 255, 255), (0, 0, mw, mh), border_radius=14)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (100, 160, 220), mr, 2, border_radius=14)

        # Title
        surface.blit(ts, ts.get_rect(midleft=(mr.x + pad, mr.y + header_h // 2)))
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + pad, mr.y + header_h),
                         (mr.right - pad, mr.y + header_h), 1)

        # Game option rows
        self._gc_skill_modal_rects = []
        mp = pygame.mouse.get_pos()
        for j, game_name in enumerate(games):
            gr = pygame.Rect(mr.x + pad,
                             mr.y + header_h + j * (item_h + item_gap),
                             mw - pad * 2, item_h)
            is_cur = (self.gc.get("selected_game") or (None,))[0] == game_name
            hov    = gr.collidepoint(mp)
            if is_cur:
                pygame.draw.rect(surface, (210, 235, 255), gr, border_radius=10)
                pygame.draw.rect(surface, (60, 140, 220), gr, 2, border_radius=10)
            elif hov:
                pygame.draw.rect(surface, (228, 242, 255), gr, border_radius=10)
            else:
                pygame.draw.rect(surface, (238, 244, 252), gr, border_radius=10)
                pygame.draw.rect(surface, (200, 215, 235), gr, 1, border_radius=10)
            g_col = (35, 110, 200) if is_cur else (40, 55, 80)
            gs    = self.fnt["body_b"].render(game_name, True, g_col)
            surface.blit(gs, gs.get_rect(midleft=(gr.x + self._sc(16), gr.centery)))
            self._gc_skill_modal_rects.append((gr, game_name))

        # Close / Cancel button
        close_r = pygame.Rect(mr.centerx - self._sc(70), mr.bottom - self._sc(16) - btn_h,
                              self._sc(140), btn_h)
        self._gc_skill_modal_close = close_r
        close_hov = close_r.collidepoint(mp)
        close_col = (145, 158, 178) if not close_hov else (118, 130, 150)
        pygame.draw.rect(surface, close_col, close_r, border_radius=10)
        cls = self.fnt["btn"].render("Cancel", True, (255, 255, 255))
        surface.blit(cls, cls.get_rect(center=close_r.center))

    def _draw_register_success_modal(self, surface):
        cr, _ = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="check", accent=(60, 185, 100),
            title="Registration Successful", body=self._rp_success_msg,
            confirm_label="OK", single_button=True, confirm_hov=self._rp_ok_hov)
        self._rp_ok_rect = cr

    def _draw_transfer_success_modal(self, surface):
        cr, _ = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="check", accent=(60, 185, 100),
            title="Patient Successfully Transferred!", body=self._transfer_success_msg,
            confirm_label="Okay", single_button=True, confirm_hov=self._transfer_ok_hov)
        self._transfer_ok_rect = cr

    def _draw_reuse_calibration_modal(self, surface):
        avail_names  = [SENSOR_CFG.get(s, {}).get("sensor_name", s) for s in self._reuse_available]
        needed_names = [SENSOR_CFG.get(s, {}).get("sensor_name", s) for s in self._reuse_needed]
        lines = [f"Reusable: {', '.join(avail_names)}"]
        if needed_names:
            lines.append(f"Still needs calibration: {', '.join(needed_names)}")
        else:
            lines.append("All required sensors are already calibrated.")
        body = "\n".join(lines)
        cr, xr = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="check", accent=(60, 160, 220),
            title="Use Previous Calibration?", body=body,
            confirm_label="Use Previous Calibration", cancel_label="Recalibrate",
            confirm_hov=self._reuse_use_hov, cancel_hov=self._reuse_recal_hov)
        self._reuse_use_rect, self._reuse_recal_rect = cr, xr

    def _draw_calibration_mismatch_modal(self, surface):
        res       = self.calibration_result or {}
        cal_type  = res.get("game_type", "—")
        cal_sens  = res.get("sensor",    "—")
        need_type = (self.gc.get("selected_game") or (None, "—"))[1] or "—"
        SENSOR_FOR = {"Grip Strength":  "Force Sensor",
                      "Finger Flexion": "Flex Sensors",
                      "Wrist Rotation": "Motion Sensor",
                      "Dual Skill":     "Force + Motion Sensors"}
        need_sens  = SENSOR_FOR.get(need_type, "—")

        body = ("The sensor calibration on file does not match the selected "
                "exercise type. Please recalibrate.\n\n"
                f"Calibrated for: {cal_type} ({cal_sens})\n"
                f"Required for: {need_type} ({need_sens})")

        cr, xr = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="warning", accent=(220, 145, 30),
            title="Sensor Mismatch", body=body,
            confirm_label="Calibrate Now", cancel_label="Cancel",
            confirm_hov=self._mismatch_cal_hov, cancel_hov=self._mismatch_cancel_hov)
        self._mismatch_cal_rect, self._mismatch_cancel_rect = cr, xr

    def _draw_confirm_modal(self, surface):
        """Delete Patient / Delete Account / Logout / Save Account / Save
        Patient -- via the standardized draw_confirm_dialog. Delete actions
        are destructive (red, trash icon); Logout and the two Save
        confirmations aren't data-destructive, so they get the neutral
        "non-destructive confirmation" blue instead of red, per the "don't
        use red for every confirmation" rule. Delete Patient / Delete
        Account additionally carry the mandatory 5-second safety-delay
        countdown (Transfer Patient's own countdown lives in the share
        modal's own draw function, not here)."""
        is_logout   = (self.modal == "logout_confirm")
        is_del_pt   = (self.modal == "delete_patient_confirm")
        is_del_acct = (self.modal == "delete_confirm")
        is_save_pt  = (self.modal == "save_patient_confirm")
        is_save_acc = (self.modal == "save_account_confirm")
        pt_name = ((self._ep_patient or {}).get("full_name", "this patient")
                   if (is_del_pt or is_save_pt) else "")

        if is_logout:
            icon, accent = "logout", (60, 140, 220)
            title = "Log out of RecovR?"
            body  = "You will be returned to the login screen."
            yes_l = "Logout"
        elif is_save_pt:
            icon, accent = "check", (60, 140, 220)
            title = "Save Patient Changes?"
            body  = "Are you sure you want to save the changes made to this patient's information?"
            yes_l = "Save Changes"
        elif is_save_acc:
            icon, accent = "check", (60, 140, 220)
            title = "Save Account Changes?"
            body  = "Are you sure you want to save the changes made to your therapist account?"
            yes_l = "Save Changes"
        elif is_del_pt:
            icon, accent = "trash", (205, 45, 45)
            title = f"Delete {pt_name}?"
            body  = ("This action cannot be undone and may affect associated rehabilitation "
                     "records. Please review this warning carefully before proceeding.")
            yes_l = "Delete Patient"
        else:   # delete_confirm -- therapist's own account
            icon, accent = "trash", (205, 45, 45)
            title = "Delete Therapist Account?"
            body  = ("Are you sure you want to permanently delete your therapist account? "
                     "This action cannot be undone. Please review this warning carefully "
                     "before proceeding.")
            yes_l = "Delete Account"

        countdown = self._danger_countdown if (is_del_pt or is_del_acct) else None

        cr, xr = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon=icon, accent=accent,
            title=title, body=body, confirm_label=yes_l, cancel_label="Cancel",
            confirm_hov=self.confirm_yes_hov, cancel_hov=self.confirm_no_hov,
            countdown=countdown)
        self._modal_confirm_rect, self._modal_cancel_rect = cr, xr

    def _draw_delete_blocked_modal(self, surface):
        """Shown instead of deleting the account when the therapist still
        CURRENTLY owns patients (database.delete_therapist refused). A single
        dismiss button -- this is information, not a yes/no choice."""
        title = "Patients not yet transferred"
        msg = ("There are patient accounts that have not been transferred yet. "
               "Please transfer all patients currently under your ownership "
               "before deleting your account.")
        ok_hov = self._db_blocked_ok_rect.collidepoint(pygame.mouse.get_pos())
        cr, _ = draw_confirm_dialog(
            surface, self.WIDTH, self.HEIGHT, tt=self._tt, sc=self._sc,
            fonts=self._dialog_fonts(), icon="warning", accent=(225, 165, 60),
            title=title, body=msg, confirm_label="Got it", single_button=True,
            confirm_hov=ok_hov)
        self._db_blocked_ok_rect = cr

    # ──────────────────────────────────────────────────────────────────
    #  UTILITIES
    # ──────────────────────────────────────────────────────────────────

    def _confirm_rects(self):
        """The Confirm/Cancel rects for whichever of the 5 "standard"
        2-button modals (select/deselect/delete-patient/delete-account/
        logout) is currently showing -- these all share draw_confirm_dialog
        via _draw_choice_modal/_draw_confirm_modal, which store the actual
        drawn geometry here each frame (content-sized, not a fixed box), so
        every existing click/hover handler keeps working unchanged."""
        return self._modal_confirm_rect, self._modal_cancel_rect

    def _logout_rect(self):
        lw=int(self.WIDTH*(0.13 if self._touch_ui else 0.11))
        lh=max(int(self.HEIGHT*0.046), self._tt(44))
        lx=(self.sidebar_w-lw)//2; ly=self.HEIGHT-lh-int(20*self.HEIGHT/1080)
        return pygame.Rect(lx,ly,lw,lh)

    def _gradient(self, width, height):
        scale=4; sw=width//scale; sh=height//scale
        s=pygame.Surface((sw,sh),depth=32).convert()
        w=(255,255,255); pb=(185,215,255); pp=(225,185,255); wf=sw*0.75
        for y in range(sh):
            for x in range(sw):
                wb=max(0,1.0-(x+y)/wf); wp=max(0,1.0-((sw-x)+(sh-y))/wf)
                tc=wb+wp
                if tc>1.0: wb/=tc;wp/=tc;ww=0.0
                else: ww=1.0-tc
                r=min(255,max(0,int(pb[0]*wb+pp[0]*wp+w[0]*ww)))
                g=min(255,max(0,int(pb[1]*wb+pp[1]*wp+w[1]*ww)))
                b=min(255,max(0,int(pb[2]*wb+pp[2]*wp+w[2]*ww)))
                s.set_at((x,y),s.map_rgb((r,g,b)))
        return pygame.transform.smoothscale(s,(width,height))