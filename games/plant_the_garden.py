"""
Garden Wonders — Triple Skill (Wrist Movement + Finger Flexion + Grip Strength) game (1920x1080)

Mechanic:
  - Tilt wrist LEFT/RIGHT/UP/DOWN to move the hand across and over the garden
    (two-axis MPU6050; Test Mode: arrow keys). Vertical range is clamped so
    the hand's own cut-off forearm tail can never rise into view -- see
    self._hand_top_min/_hand_top_max.
  - Flex a finger (release required between presses; Test Mode: F -- NOT the
    DOWN arrow, which is vertical movement here) while the hand's fingertip
    is near the seed box to pick up a seed, then again while the HELD SEED's
    own position (not the hand's center) is over an EMPTY plot's soil to
    plant it.
  - Grip (squeeze >= the calibrated threshold) near the watering can to pick
    it up. Once picked up, the can stays attached to the hand regardless of
    grip state -- grip only gates the watering action itself, checked at the
    can's actual spout position, not an unrelated sprite-center point.
  - Water a plant TWICE, each a separate sustained-grip hold with a release
    required in between (and a release required after pickup before the
    first one): the first watering grows it to its small stage; the second
    grows it fully into a randomly-selected plant (70% common / 20% rare /
    10% epic), scores one point, and detaches the can.
  - Five plots fill up, then the garden briefly shows its completed state and
    clears for a new cycle -- repeating until the session goal is reached.
"""

import os
import math
import random
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler, FINGER_NAMES
from audio import (start_music, stop_music, pause_music, resume_music,
                    game_bgm_path, play_completion, play_click, play_success)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.hud import (draw_target_pill, TARGET_POS, draw_tutorial_badge, draw_feedback_banner,
                        draw_controls_panel, controls_panel_rect)
from games.tutorial_hints import TutorialHints, TutorialStep
from games.round_complete import draw_round_complete_overlay, get_mono_font
from i18n import tr

# Real MPU6050 Y-axis tilt (accel_y) -- the firmware already transmits it
# (ble_receiver.py's PACKET_FORMAT), but input_handler.py's own "tilt_y"
# field carries the Flex Sensor instead (see SENSOR_CFG["Finger Flexion"] in
# scenes/calibration_window.py, which every other game also relies on), so
# it is never exposed through get_state(). Reading it directly here --
# scoped to this one file -- adds real two-axis MPU6050 movement without
# touching that shared field or any other game's controls.
try:
    from sensors.ble_receiver import ble_receiver as _ble
except Exception:
    _ble = None

# Set True only for local development -- draws the hand/seed/crate/can
# interaction hitboxes described in the game's design spec. Always False in
# normal gameplay.
DEBUG_HITBOXES = False

# ── difficulty-scaled parameters ────────────────────────────────────────────
# Reuses the same real, independently-read value pattern as every other
# RecovR game; Advanced Settings can override each one via the
# "ptg_*" keys in scenes/calibration_window.py's GAME_PARAM_SCHEMA.
GOAL            = {"Easy": 80,   "Medium": 120,  "Hard": 160}    # Target Mode: points
DURATION        = {"Easy": 300,  "Medium": 420,  "Hard": 600}    # Timed Mode: session length (s) -- 5/7/10 min
# 30/70/90% -- same Easy/Medium/Hard anchor used for every "Required Grip
# Strength"/"Required Finger Flexion"/"Required Wrist Rotation" parameter
# across every game (the % of the patient's own calibrated range required).
GRIP_THRESHOLD  = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}   # calibrated grip (0-1) to grab/hold the can
FLEX_THRESHOLD  = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}   # fallback flex threshold -- see on_enter()'s press_threshold
# Per-finger press/release hysteresis margin -- same value and mechanism as
# games/whack_mole.py's own RELEASE_MARGIN: a finger must drop back below
# press_threshold[i] * this (not just below press_threshold[i] itself)
# before it can register another press.
FLEX_RELEASE_MARGIN = 0.65
MOVE_DEADZONE   = {"Easy": 0.05, "Medium": 0.08, "Hard": 0.12}   # wrist tilt magnitude before the hand moves
# Watering is gated by wrist rotation, not grip (grip only gates can pickup
# -- see on_enter()/update()/_update_watering()) -- a calibration-relative
# magnitude of horizontal wrist tilt, same 30/70/90% anchor, sustained for
# `water_hold` seconds to register one watering.
WRIST_REQUIREMENT = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}
# px radius of every interaction zone. Unlike Purrfect Feast's 3 zones spread
# across the whole screen, this game packs 5 plots PLOT_COUNT-wide into the
# play area (288px apart at the default margins) -- the tolerance is capped
# well under half that spacing so adjacent plot zones never overlap, even on
# Easy, which would otherwise let the hand ambiguously register over the
# wrong neighboring plot.
ZONE_TOLERANCE  = {"Easy": 130,  "Medium": 100,  "Hard": 70}
WATER_HOLD      = {"Easy": 0.8,  "Medium": 1.2,  "Hard": 1.6}    # seconds of sustained grip per watering stage
MOVE_SPEED      = {"Easy": 700,  "Medium": 850,  "Hard": 1000}   # hand px/s per unit tilt

CYCLE_PAUSE_DURATION = 2.0   # seconds the completed 5-plot garden is shown before clearing
FEEDBACK_DURATION    = 1.0
PLANT_FADE_SEC       = 0.4   # cross-fade duration when a plant's own sprite changes stage

# ── plant rarity ─────────────────────────────────────────────────────────────
COMMON_PLANTS = ["tomato", "eggplant", "chili", "basil", "cucumber"]
RARE_PLANTS   = ["pumpkin", "jackfruit", "grapes"]
EPIC_PLANTS   = ["starfruit"]

# How many successful waterings a plot needs before it's fully grown, and how
# many points it scores then -- both keyed by the SAME rarity roll, made once
# at planting time (see _pick_random_plant/the "carrying == seed" branch in
# update()), not re-rolled at growth time.
WATER_COUNT     = {"common": 2, "rare": 3, "epic": 5}
SCORE_BY_RARITY = {"common": 3, "rare": 5, "epic": 7}

# Exact on-disk filenames (several carry a "palnt" typo and basil a double
# underscore -- used verbatim rather than the idealized names, since that is
# what actually exists in assets/images).
_GROWN_ASSET = {
    "tomato":    "tomato_grown_palnt_plant_the_garden.png",
    "eggplant":  "eggplant_grown_palnt_plant_the_garden.png",
    "chili":     "chili_grown_palnt_plant_the_garden.png",
    "basil":     "basil__grown_palnt_plant_the_garden.png",
    "cucumber":  "cucumber_grown_palnt_plant_the_garden.png",
    "pumpkin":   "pumpkin_grown_palnt_plant_the_garden.png",
    "jackfruit": "jackfruit_grown_palnt_plant_the_garden.png",
    "grapes":    "grapes_grown_palnt_plant_the_garden.png",
    "starfruit": "starfruit_grown_palnt_plant_the_garden.png",
}


def _pick_random_plant():
    """70% common / 20% rare / 10% epic, uniform within whichever tier is
    rolled -- a fresh independent roll each time, never a fixed sequence.
    Returns (rarity, plant_name); rolled once at PLANTING time (not growth
    time) so the required water count and the eventual score/sprite all
    agree with the same roll -- see the "carrying == seed" branch below."""
    r = random.random()
    if r < 0.70:
        return "common", random.choice(COMMON_PLANTS)
    elif r < 0.90:
        return "rare", random.choice(RARE_PLANTS)
    return "epic", random.choice(EPIC_PLANTS)


# on-screen target box each sprite is cropped-to-content and fit within
# (aspect ratio preserved, never stretched) -- see _load_image_fit.
HAND_BOX   = (420, 620)
CRATE_BOX  = (260, 130)   # width-constrained at each sprite's own aspect
                          # ratio, so all 5 crates render at the same 260px
                          # width regardless of each one's own height --
                          # keeps visual sizes consistent across the artwork.
SOURCE_BOX = (230, 300)
CAN_BOX    = (260, 300)
# Sized (and verified by rendering all 11 plant sprites on all 5 crates) so
# every grown-plant sprite, width-constrained like the crates above, stays
# within each crate's own soil-trapezoid region with real margin -- the
# vine/bush-stage plants (grapes, starfruit) are the widest cases.
PLANT_BOX  = (150, 190)
WATER_IND_BOX = (80, 80)

GROUND_Y   = int(GAME_H * 0.82)   # seed source / watering can rest here
# The 5 crates (+ whatever is planted in them + their water-needed indicator)
# sit higher than the seed source/watering can, per the therapist's
# requested vertical placement scaled to this game's 1920x1080 canvas.
CRATE_GROUND_Y = int(GAME_H * 0.683)
# Where a plant anchors within a crate -- the soil surface, not the crate
# sprite's own bottom edge. The new crates are drawn at a shallow angle (soil
# visible as a trapezoid in the sprite's upper ~55%, the front wooden wall
# below it), so "soil surface" is this fraction down from the crate image's
# own top edge, not a fixed pixel offset from its bottom -- measured directly
# off the cropped sprite's own content, so it already accounts for each
# crate's own transparent padding.
CRATE_SOIL_FRAC = 0.35
# The hand sprite's own art extends well past the bottom of its cropped
# content (a forearm fading toward the viewer), so anchoring its bottom edge
# below the screen keeps that cut-off invisible, per the established pattern
# every other dual/triple-skill game already uses.
HAND_BOTTOM_Y = GAME_H + 150

SEED_X = GAME_W * 0.92
CAN_X  = GAME_W * 0.08
PLOT_COUNT = 5
_plot_margin = GAME_W * 0.20
PLOT_XS = [_plot_margin + i * (GAME_W - 2 * _plot_margin) / (PLOT_COUNT - 1) for i in range(PLOT_COUNT)]

# ── interaction points, as a fraction (x, y) of each sprite's own cropped
# bounding box -- measured directly off the actual artwork (not guessed from
# the sprite's center), so hitboxes track where the hand/seed/spout really
# are on screen instead of an unrelated anchor point.
FINGERTIP_FRAC = (0.80, 0.03)   # idle hand's raised index fingertip -- used for seed-box pickup
SEED_HOLD_FRAC = (0.93, 0.22)   # the seed, once held, pinched between thumb/finger
SPOUT_FRAC     = (0.96, 0.17)   # the watering can's actual pouring tip, once held -- the ONLY
                                # point that may be inside a plant's hitbox for watering to count

# The watering-can-in-hand sprite, enlarged beyond the shared hand_scale
# every other hand state uses (see on_enter) so the can itself reads as
# noticeably bigger, not just the same size as the idle/seed-holding hand.
CAN_EXTRA_SCALE = 1.3
# Raises just the can-carrying hand's own render/hit-test anchor (not its
# movement RANGE or speed) so the can sits with real clearance above every
# crate's own top edge, instead of hugging the soil line. Sized so the
# actual watering hit-test point's (SPOUT_FRAC/_can_tip_point's) full
# reachable range, across the hand's normal vertical travel, lands centred
# inside every crate's own soil zone (with its existing PLANT_TOLERANCE
# margin either side).
CAN_LIFT_PX = 40

# Two-pour watering animation: the held can tilts forward (pouring), holds,
# then eases back upright. The hand and can are always one merged sprite --
# there is no separately-drawn hand, so they can never move independently
# of each other; rotating that one image is the only thing this animation
# ever does. Pivot is the can's own barrel centre (grid-overlay measured),
# not the far-away wrist/forearm corner -- pivoting out at the wrist turned
# even a modest angle into the whole arm swinging the can through a huge
# arc (the spout sits ~900px from the wrist on this enlarged sprite), which
# read as the can flying off rather than tipping. Pivoting on the can itself
# keeps the hand/arm essentially in place while the barrel visibly rotates,
# exactly like someone tipping a can they're holding steady.
CAN_PIVOT_FRAC   = (0.58, 0.35)
CAN_TILT_MAX_DEG = 35      # forward tilt while actively pouring
CAN_TILT_RATE    = 140     # deg/sec eased toward the current target -- fast enough to read as
                           # deliberate, slow enough to never snap

SEED_PICKUP_MARGIN = 90    # px of forgiveness around the seed box's own visible rect
PLANT_TOLERANCE     = 60   # px of forgiveness around each crate's own soil region

# The can's own GRAB zone (picking it up off the ground at CAN_X, before
# carrying) is asymmetric: an ENLARGED zone approaching from the LEFT, a
# sharply reduced one approaching from the right -- the hand has to
# actually move in past the can from its left side to grab it (even
# comfortably past, not merely adjacent), rather than drifting near it
# from either direction. The right side keeps only a sliver (never quite
# zero, so standing exactly on CAN_X still always works).
CAN_GRAB_TOLERANCE_LEFT_SCALE  = 1.8
CAN_GRAB_TOLERANCE_RIGHT_SCALE = 0.05

# One sprite per plot position, left to right -- matches PLOT_XS's own
# ascending order, so CRATE_ASSETS[i] is always plot i's crate.
CRATE_ASSETS = [
    "leftmost_crate_plant_the_garden.png",
    "left_crate_plant_the_garden.png",
    "center_crate_plant_the_garden.png",
    "right_crate_plant_the_garden.png",
    "rightmost_crate_plant_the_garden.png",
]

HAND_MIN_X = CAN_X - 40   # fallback only -- on_enter overrides this with self._hand_min_x,
                          # letting the hand travel far enough left that half of it is
                          # off-screen, so the can (right at the screen's edge) is reachable.
HAND_MAX_X = SEED_X + 40

# Affected-hand adaptation: this game's art/positions default to a LEFT-hand
# configuration (seed box right, watering can left). See
# games/session_mode.py's self.affected_hand -- set once in on_enter as
# self.hand_flipped, never recomputed mid-session.
DEFAULT_HAND = "left"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}


def _load_image_fit(name, w, h):
    """Crop to the asset's own opaque content, then scale to fit within
    w x h preserving its aspect ratio. Returns None if missing so a caller
    can skip drawing instead of crashing."""
    key = (name, w, h)
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
            cw, ch = cropped.get_size()
            scale = min(w / cw, h / ch)
            _img_cache[key] = pygame.transform.smoothscale(
                cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
        except Exception:
            _img_cache[key] = None
    return _img_cache[key]


def _fit_scale(name, w, h):
    """The scale factor _load_image_fit(name, w, h) would use for this
    asset's own opaque content, without loading/caching the scaled image --
    lets another sprite that must share this one's real-world size (see
    _load_image_scaled) reuse the exact same number."""
    try:
        raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
        br = raw.get_bounding_rect(min_alpha=10)
        return min(w / br.width, h / br.height)
    except Exception:
        return 1.0


def _load_image_scaled(name, scale):
    """Crop to the asset's own opaque content, then scale by an EXPLICIT
    factor -- as opposed to _load_image_fit's independent fit-to-box, which
    scales a composite sprite purely by its own bounding box's aspect ratio.
    Used for a sprite set that must render at one shared real-world size
    (e.g. the hand across its idle/holding states): fitting each one to the
    same box independently scales them differently whenever a carried
    object (e.g. the watering can's spout) widens that sprite's own
    bounding box, which would otherwise shrink the hand itself."""
    key = ("scaled", name, round(scale, 6))
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
            cw, ch = cropped.get_size()
            _img_cache[key] = pygame.transform.smoothscale(
                cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
        except Exception:
            _img_cache[key] = None
    return _img_cache[key]


def _load_image_cover(name, w, h):
    """A full-bleed background scaled + center-cropped to exactly fill w x h,
    preserving aspect ratio (no stretching, no letterbox borders)."""
    key = ("cover", name, w, h)
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
            rw, rh = cropped.get_size()
            scale = max(w / rw, h / rh)
            sw, sh = max(1, int(rw * scale)), max(1, int(rh * scale))
            scaled = pygame.transform.smoothscale(cropped, (sw, sh))
            x, y = (sw - w) // 2, (sh - h) // 2
            _img_cache[key] = scaled.subsurface((x, y, w, h)).copy().convert()
        except Exception:
            _img_cache[key] = None
    return _img_cache[key]


def _rotate_anchored(image, angle, local_point, target_pos):
    """Rotate `image` by `angle` degrees (never a resize/stretch) so that
    `local_point` -- in the image's own unrotated pixel coordinates -- lands
    exactly at `target_pos` on screen. Same technique as games/whack_mole.py's
    hammer pivot, minus the scale term (the can never changes size while
    tilting)."""
    w, h = image.get_size()
    offset = pygame.math.Vector2(w / 2 - local_point[0], h / 2 - local_point[1])
    rotated_offset = offset.rotate(-angle)
    rotated = pygame.transform.rotate(image, angle)
    rect = rotated.get_rect(center=(target_pos[0] + rotated_offset.x,
                                     target_pos[1] + rotated_offset.y))
    return rotated, rect


class Plot:
    """One of the 5 planting plots. state: "empty" | "planted" | "watered_once" | "grown".
    "watered_once" covers every watering from the 1st through the 2nd-to-last
    required one (the sprite doesn't change again until "grown") -- see
    required_waters/waters_done, rolled once at planting time."""
    def __init__(self, x):
        self.x = x
        self.state = "empty"
        self.plant  = None   # the randomly-selected grown-plant name (rolled at planting)
        self.rarity = None   # "common" | "rare" | "epic" (rolled at planting, same roll as .plant)
        self.required_waters = 0   # from WATER_COUNT[self.rarity]
        self.waters_done      = 0


class PlantTheGardenGame(SessionModeMixin, FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "multi"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        # Advanced Settings overrides take priority; absent an override,
        # fall back to the normal per-difficulty preset.
        cal_params = self.cal.get("params", {})
        self.grip_threshold = cal_params.get("ptg_grip_threshold", GRIP_THRESHOLD[self.difficulty])
        self.flex_threshold = cal_params.get("ptg_flex_threshold", FLEX_THRESHOLD[self.difficulty])
        self.move_deadzone  = cal_params.get("ptg_move_deadzone", MOVE_DEADZONE[self.difficulty])
        self.zone_tolerance = cal_params.get("ptg_zone_tolerance", ZONE_TOLERANCE[self.difficulty])
        self.water_hold     = cal_params.get("ptg_water_hold", WATER_HOLD[self.difficulty])
        # Watering's real gate -- see _update_watering(). Grip stays only for
        # can pickup (below); seed pickup/planting stays flex-gated, unchanged.
        self.wrist_requirement = cal_params.get(
            "ptg_wrist_requirement", WRIST_REQUIREMENT[self.difficulty])

        # Per-finger calibrated press threshold (0-1), one of the 5
        # independent "<Finger> Flexion" calibration passes (see
        # MULTI_SENSOR_CALIBRATION in scenes/therapist_dashboard.py /
        # SENSOR_CFG + _FINGER_FLEX_KEYS in scenes/calibration_window.py)
        # -- same pattern as games/whack_mole.py's own press_threshold/
        # release_threshold. Falls back to the Advanced Settings "Required
        # Finger Flexion" override (ptg_flex_threshold) / difficulty
        # default for any finger never actually calibrated (e.g.
        # calibration skipped, or a record with no per-finger "sensors"
        # key at all -- .get() below falls through to the default exactly
        # as if that finger had never been calibrated).
        # Direction-independent: a flex sensor's raw reading may DECREASE,
        # not increase, when the finger bends (never verified in hardware).
        # A CALIBRATED finger's "how flexed is it right now" is therefore
        # computed as a 0-100% distance from its OWN resting baseline
        # toward its OWN calibrated peak average, using abs() on both sides
        # (see _finger_pct()) instead of comparing raw ADC values directly
        # against a single precomputed raw threshold. An UNCALIBRATED
        # finger has no baseline/peak to compute a percentage from, so it
        # keeps a plain raw-value comparison instead.
        sensors_cal   = self.cal.get("sensors", {})
        threshold_pct = self.cal.get("params", {}).get(
            "threshold_pct", FLEX_THRESHOLD[self.difficulty] * 100)
        self._finger_calibrated    = []
        self._finger_baseline      = []
        self._finger_peak          = []
        self.press_threshold_pct   = []
        self.release_threshold_pct = []
        self.press_threshold       = []   # raw-value fallback, uncalibrated fingers only
        self.release_threshold     = []   # raw-value fallback, uncalibrated fingers only
        for name in FINGER_NAMES:
            entry = sensors_cal.get(f"{name} Flexion")
            if entry and entry.get("average") is not None:
                self._finger_calibrated.append(True)
                self._finger_baseline.append(entry.get("baseline", 0.0))
                self._finger_peak.append(entry["average"])
                self.press_threshold_pct.append(threshold_pct)
                self.release_threshold_pct.append(threshold_pct * FLEX_RELEASE_MARGIN)
                self.press_threshold.append(0.0)
                self.release_threshold.append(0.0)
            else:
                self._finger_calibrated.append(False)
                self._finger_baseline.append(0.0)
                self._finger_peak.append(0.0)
                self.press_threshold_pct.append(0.0)
                self.release_threshold_pct.append(0.0)
                self.press_threshold.append(self.flex_threshold)
                self.release_threshold.append(self.flex_threshold * FLEX_RELEASE_MARGIN)

        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="ptg_goal")

        # Affected-hand adaptation -- mirror the hand sprite, its fractional
        # interaction points (see _hand_sprite_point), and the seed/can's
        # own left-right placement when the patient's affected hand is the
        # opposite of this game's default. Computed once here, never
        # changes mid-session. seed_x/can_x/hand_min_x/hand_max_x are the
        # flip-aware counterparts of the module-level SEED_X/CAN_X/
        # HAND_MAX_X/self._hand_min_x (left as-is below -- they stay the
        # fixed, UNflipped geometry every mirrored value is derived from).
        self.hand_flipped = bool(self.affected_hand) and self.affected_hand != DEFAULT_HAND
        if self.hand_flipped:
            self.seed_x     = GAME_W - SEED_X
            self.can_x      = GAME_W - CAN_X
        else:
            self.seed_x     = SEED_X
            self.can_x      = CAN_X
        # Every session gets a minimum read time on the How-To-Play screen --
        # a curious first tilt/squeeze shouldn't be able to skip past the
        # instructions before the patient has had any chance to read them
        # (the patient's own sensor input can dismiss this screen even in
        # the dual-monitor production flow -- see
        # recovr/patient_app/games/generic_adapter.py's handle_event()).
        self._instructions_min_t = 2.5
        self.move_speed      = MOVE_SPEED[self.difficulty]

        self._bg_img     = _load_image_cover("bg_plant_the_garden.png", GAME_W, GAME_H)
        # One distinct sprite per plot, left to right, per spec -- a fixed
        # list indexed the same way self.plots is, so plot i always draws
        # with crate asset i for the whole session (see draw()).
        self._crate_imgs = [_load_image_fit(name, *CRATE_BOX) for name in CRATE_ASSETS]
        self._seed_img   = _load_image_fit("seed_plant_the_garden.png", *SOURCE_BOX)
        self._can_img    = _load_image_fit("watering_can_plant_the_garden.png", *CAN_BOX)
        # All three hand sprites share the idle hand's own fit-to-box scale,
        # rather than each independently fitting HAND_BOX -- the watering
        # can's spout widens that sprite's bounding box well beyond the
        # hand/seed sprites', so fitting it independently shrank the whole
        # hand (and visibly dropped it, since it is bottom-anchored -- see
        # self._hand_top_max below) whenever the can was carried.
        hand_scale = _fit_scale("hand_plant_the_garden.png", *HAND_BOX)
        self._hand_img        = _load_image_scaled("hand_plant_the_garden.png", hand_scale)
        self._hold_seed_img   = _load_image_scaled("hold_seed_plant_the_garden.png", hand_scale)
        # The can-in-hand is the one deliberate exception to "every hand
        # state shares one scale" -- CAN_EXTRA_SCALE makes it noticeably
        # bigger on top of that shared base, per spec (see CAN_EXTRA_SCALE).
        self._hold_can_img    = _load_image_scaled("hold_watering_can_plant_the_garden.png",
                                                     hand_scale * CAN_EXTRA_SCALE)
        # Affected-hand adaptation -- mirror all three hand states together
        # so they stay visually consistent with each other. Done once here
        # (not cached in _img_cache, which is shared/unflipped across every
        # instance) rather than per-frame in draw().
        if self.hand_flipped:
            self._hand_img      = (pygame.transform.flip(self._hand_img, True, False)
                                    if self._hand_img is not None else None)
            self._hold_seed_img = (pygame.transform.flip(self._hold_seed_img, True, False)
                                    if self._hold_seed_img is not None else None)
            self._hold_can_img  = (pygame.transform.flip(self._hold_can_img, True, False)
                                    if self._hold_can_img is not None else None)
        # Anchor point for all three: the idle hand's own top edge (where the
        # raised fingers are -- consistent across all three sprites, unlike
        # the bottom edge, which varies with how much forearm/carried-object
        # each crop happens to include). Carrying something can now only
        # change what appears below/around the grip, never the hand's own
        # size. self.hand_y (vertical movement) ranges between these two:
        #   _hand_top_max -- the original resting/default position (today's
        #                    unchanged look); downward movement never goes
        #                    past this.
        #   _hand_top_min -- the highest allowed position: exactly where
        #                    this sprite's own BOTTOM edge lands on the
        #                    screen's own bottom edge, so moving any higher
        #                    would start exposing its cut-off forearm tail.
        # The idle hand is the tallest of the three states, so clamping to
        # its own height keeps the (always shorter or equal) seed/can
        # states safely within bounds too.
        hand_h = self._hand_img.get_height() if self._hand_img is not None else HAND_BOX[1]
        self._hand_top_max = HAND_BOTTOM_Y - hand_h
        self._hand_top_min = GAME_H - hand_h
        # The hand must be able to travel far enough left to grab the can
        # sitting right at the screen's own edge (CAN_X) -- specifically
        # until HALF of the idle hand sprite itself is off-screen, per
        # spec, rather than stopping well short of the edge. hand_x=0 puts
        # the sprite's own centre at the screen's left edge, i.e. exactly
        # half of it off-screen; this is comfortably far enough left that
        # reaching every plot with the carried can's own tip (see
        # SPOUT_FRAC/_can_tip_point) never becomes the binding limit.
        self._hand_min_x = 0.0
        # Flip-aware movement clamp used by update() -- mirrors the fixed
        # self._hand_min_x/HAND_MAX_X pair around the screen's own center so
        # the hand can still reach half off-screen past whichever side the
        # can ended up on, and up to the seed box on the other side.
        if self.hand_flipped:
            self.hand_min_x = GAME_W - HAND_MAX_X
            self.hand_max_x = GAME_W - self._hand_min_x
        else:
            self.hand_min_x = self._hand_min_x
            self.hand_max_x = HAND_MAX_X
        # Floored at CAN_X - self._hand_min_x (+10 margin): on Hard,
        # zone_tolerance is small enough that CAN_GRAB_TOLERANCE_LEFT_SCALE
        # alone would not reach all the way out to hand_x==0 -- this floor
        # guarantees hand_x==0 can always grab the can, at every difficulty,
        # regardless of how the per-difficulty scale happens to come out.
        self.can_grab_tolerance_left  = max(self.zone_tolerance * CAN_GRAB_TOLERANCE_LEFT_SCALE,
                                             CAN_X - self._hand_min_x + 10)
        self.can_grab_tolerance_right = self.zone_tolerance * CAN_GRAB_TOLERANCE_RIGHT_SCALE
        self._new_plant_img   = _load_image_fit("new_plant_plant_the_garden.png", *PLANT_BOX)
        self._small_plant_img = _load_image_fit("small_plant_plant_the_garden.png", *PLANT_BOX)
        self._need_water_img  = _load_image_fit("need_water_plant_the_garden.png", *WATER_IND_BOX)
        self._grown_imgs = {name: _load_image_fit(fname, *PLANT_BOX) for name, fname in _GROWN_ASSET.items()}
        self._new_plant_img   = _load_image_fit("new_plant_plant_the_garden.png", *PLANT_BOX)
        self._small_plant_img = _load_image_fit("small_plant_plant_the_garden.png", *PLANT_BOX)
        self._need_water_img  = _load_image_fit("need_water_plant_the_garden.png", *WATER_IND_BOX)
        self._grown_imgs = {name: _load_image_fit(fname, *PLANT_BOX) for name, fname in _GROWN_ASSET.items()}

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_fb  = pygame.font.SysFont("monospace", 44, bold=True)
        self._font_target = pygame.font.SysFont("monospace", 54, bold=True)

        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4

        self._pause_btn_rect     = pygame.Rect(GAME_W - 90, HEADER_BOTTOM + 14, 70, 46)
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

        # Tutorial-only: sequential on-screen coaching during actual
        # gameplay (see games/tutorial_hints.py), picking up once the
        # How-To-Play card is dismissed.
        self._tutorial_hints = TutorialHints([
            TutorialStep(lambda g: tr("plantgarden.tut.1", g.language),
                         anchor=lambda g: (int(g.seed_x), GROUND_Y),
                         done=lambda g, t: g.carrying == "seed"),
            TutorialStep(lambda g: tr("plantgarden.tut.2", g.language),
                         anchor=lambda g: g._crate_plant_rect(0).center,
                         done=lambda g, t: any(p.state != "empty" for p in g.plots)),
            TutorialStep(lambda g: tr("plantgarden.tut.3", g.language),
                         anchor=lambda g: (int(g.can_x), GROUND_Y),
                         done=lambda g, t: g.score >= 1),
            TutorialStep(lambda g: (tr("plantgarden.tut.4.target", g.language, goal=g.goal)
                                     if g.session_mode == "target" else
                                     tr("plantgarden.tut.4.timed", g.language))),
        ]) if self.tutorial else None

    def _reset(self):
        self.game_over          = False
        self.game_over_score    = 0
        self.game_over_duration = 0
        self.paused     = False
        self.pause_sel  = 0

        self.score = 0
        self.reps  = 0          # = plants successfully grown this session (all cycles)
        self._session_reset()
        self.start_time = pygame.time.get_ticks()

        self.hand_x   = GAME_W / 2
        self.hand_y   = self._hand_top_max   # resting/default vertical position
        self.carrying = None     # None | "seed" | "can"
        # Per-finger press/release (hysteresis) state -- same convention as
        # games/whack_mole.py's own self._armed seeding: a finger already
        # held above its own release threshold right now must release once
        # before it can register a press, exactly like mid-session.
        state0 = input_handler.get_state()
        flex0  = state0.get("finger_flex") or [0.0] * 5
        self._flex_armed = [self._finger_is_released(i, flex0[i]) for i in range(5)]
        self._grip_need_release = False
        self._wrist_need_release = False
        self._water2_need_release = False
        self.water_progress  = 0.0
        self.watering_plot   = None     # plot index currently accumulating water_progress
        self._water_hover_plot  = None  # plot index the can's tip is correctly positioned over right now
        self._water_tilt_angle  = 0.0   # current eased tilt, degrees (0 = upright)
        self._water_tilt_target = 0.0   # CAN_TILT_MAX_DEG while actively pouring, else 0
        self._can_returning     = False # True between the 2nd pour completing and the can actually detaching
        self._plant_fade        = {}    # plot index -> {"from","to","t"} -- see _start_plant_fade

        self.plots = [Plot(x) for x in PLOT_XS]
        self._cycle_pause_t = 0.0

        self.feedback = None
        self._state = {"grip": 0.0, "tilt_x": 0.0, "tilt_y": 0.0, "fingers": [False] * 5}

    def _normalize_grip(self, raw):
        rest = self.cal.get("grip_rest", 0.0)
        mx   = self.cal.get("grip_max",  1.0)
        if mx <= rest:
            return raw
        return max(0.0, min(1.0, (raw - rest) / (mx - rest)))

    def _finger_pct(self, index, raw):
        """Direction-independent 0-100 flexion percentage for a CALIBRATED
        finger -- distance from its own resting baseline toward its own
        calibrated peak average, using abs() on both sides since this
        sensor's raw reading may rise OR fall when the finger bends (never
        verified in hardware). Capped to [0, 100]. Only meaningful when
        self._finger_calibrated[index] is True. Mirrors
        games/whack_mole.py's own method of the same name/signature."""
        baseline = self._finger_baseline[index]
        peak     = self._finger_peak[index]
        span = abs(peak - baseline)
        if span <= 1e-6:
            return 0.0
        return max(0.0, min(100.0, abs(raw - baseline) / span * 100.0))

    def _finger_is_pressed(self, index, raw):
        if self._finger_calibrated[index]:
            return self._finger_pct(index, raw) >= self.press_threshold_pct[index]
        return raw >= self.press_threshold[index]

    def _finger_is_released(self, index, raw):
        if self._finger_calibrated[index]:
            return self._finger_pct(index, raw) <= self.release_threshold_pct[index]
        return raw <= self.release_threshold[index]

    def _normalize_finger(self, index, raw):
        """Used by recovr/patient_app/games/generic_adapter.py's therapist
        telemetry -- "calibrated" reading is whether THIS finger is
        currently above ITS OWN calibrated threshold, the same value the
        press/release state machine itself acts on. Mirrors
        games/whack_mole.py's own method of the same name/signature."""
        return 1.0 if self._finger_is_pressed(index, raw) else 0.0

    def _normalize_tilt(self, raw, axis=None):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return raw
        return max(-1.0, min(1.0, (raw - wmin) / (wmax - wmin) * 2.0 - 1.0))

    def _vertical_input(self):
        """+1 = down, -1 = up (same sign convention tilt_y already has).
        Test Mode: input_handler's own UP/DOWN-driven tilt_y (DOWN no longer
        means flex in THIS game -- see update()'s finger_flex/F-key check). Real sensor
        mode: the MPU6050's own Y axis, read directly off the BLE packet
        (see the _ble import comment at the top of this file) and passed
        through the same calibrated wrist_min/wrist_max range tilt_x uses,
        so it is equally calibrated, not a raw/uncalibrated value."""
        if input_handler.connected:
            if _ble is None:
                return 0.0
            try:
                raw = max(-1.0, min(1.0, _ble.get_latest()["accel_y"] / 16384.0))
            except Exception:
                return 0.0
            return self._normalize_tilt(raw, "y")
        return self._state.get("tilt_y", 0.0)

    def _hand_anchor_y(self):
        """self.hand_y, except while carrying the can -- raised by
        CAN_LIFT_PX so the can-in-hand sprite renders and hit-tests from
        that lifted point instead of the plain hand's own anchor (see
        CAN_LIFT_PX). self.hand_y itself, and its movement range/speed, are
        never touched -- only where the can-carrying sprite/hitbox sits
        relative to it."""
        return self.hand_y - CAN_LIFT_PX if self.carrying == "can" else self.hand_y

    def _hand_sprite_point(self, img, frac):
        """Screen position of a (fx, fy) fractional point within `img`'s own
        bounding box, given the current hand anchor -- img is always
        midtop-anchored at (self.hand_x, self._hand_anchor_y()), see
        draw(). Every fraction in this file (FINGERTIP_FRAC/SEED_HOLD_FRAC/
        SPOUT_FRAC) was measured against the UNflipped artwork, so when
        self.hand_flipped (and img has already been mirrored to match --
        see on_enter), the x-fraction is mirrored here too, in this one
        shared seam, rather than in each of the 3 callers."""
        if img is None:
            return (self.hand_x, self._hand_anchor_y())
        fx = 1.0 - frac[0] if self.hand_flipped else frac[0]
        left = self.hand_x - img.get_width() / 2
        return (left + img.get_width() * fx, self._hand_anchor_y() + img.get_height() * frac[1])

    def _fingertip_point(self):
        """The idle hand's own raised-fingertip point -- used to judge
        whether the hand (not yet holding anything) is close enough to the
        seed box to pick one up."""
        return self._hand_sprite_point(self._hand_img, FINGERTIP_FRAC)

    def _held_seed_point(self):
        """Where the held seed actually is on screen, for planting
        eligibility -- not the hand sprite's own center."""
        return self._hand_sprite_point(self._hold_seed_img, SEED_HOLD_FRAC)

    def _can_tip_point(self):
        """Where the watering can's actual pouring tip (the spout opening
        water comes out of -- SPOUT_FRAC) is on screen, for watering
        eligibility. This must be the TIP specifically, not the can's own
        body/barrel centre and not the hand/can sprite's own geometric
        centre -- per spec, if the can's body is over a plant's hitbox but
        the tip isn't, watering must NOT register; only the tip being
        inside counts. Always the UNROTATED position, same as every other
        sprite point in this file -- the tilt animation (see draw()/
        self._water_tilt_angle) is purely cosmetic and never feeds back
        into hit-testing, exactly like games/whack_mole.py's hammer swing.
        Coupling the hitbox to the animated tilt would make the pour's own
        success animation capable of knocking this point back out of the
        crate's zone mid-hold -- self-interrupting the very action it's
        celebrating."""
        return self._hand_sprite_point(self._hold_can_img, SPOUT_FRAC)

    def _seed_box_rect(self):
        """The seed box's own visible rect, inflated by a forgiving margin --
        the real pickup zone, instead of an arbitrary radius hung off
        SEED_X regardless of what is actually on screen there."""
        if self._seed_img is None:
            return pygame.Rect(0, 0, 1, 1)
        r = self._seed_img.get_rect(midbottom=(int(self.seed_x), GROUND_Y))
        return r.inflate(SEED_PICKUP_MARGIN * 2, SEED_PICKUP_MARGIN * 2)

    def _crate_plant_rect(self, i):
        """Plot i's own planting/watering zone -- the crate's actual visible
        SOIL region (see CRATE_SOIL_FRAC), not its full footprint (which
        includes the front wooden wall, where a seed should never register
        as "inside" the crate), inflated by a forgiving tolerance."""
        crate_img = self._crate_imgs[i] if i < len(self._crate_imgs) else None
        if crate_img is None:
            # Fallback when a crate sprite failed to load: a reasonable
            # zone around the plot's own nominal position.
            r = pygame.Rect(0, 0, CRATE_BOX[0], int(CRATE_BOX[1] * (CRATE_SOIL_FRAC + 0.25)))
            r.midbottom = (int(self.plots[i].x), CRATE_GROUND_Y)
            return r.inflate(PLANT_TOLERANCE * 2, PLANT_TOLERANCE * 2)
        r = crate_img.get_rect(midbottom=(int(self.plots[i].x), CRATE_GROUND_Y))
        soil_h = int(r.height * (CRATE_SOIL_FRAC + 0.25))
        zone = pygame.Rect(r.left, r.top, r.width, soil_h)
        return zone.inflate(PLANT_TOLERANCE * 2, PLANT_TOLERANCE * 2)

    def _crate_at(self, point):
        """Which plot's planting/watering zone contains `point`, if any --
        the closest one by center distance when more than one matches
        (adjacent crates' inflated zones normally don't overlap, but this
        mirrors _plot_at's own "closest, not just first" safety)."""
        best_i, best_d = None, None
        for i in range(len(self.plots)):
            zone = self._crate_plant_rect(i)
            if zone.collidepoint(point):
                d = (point[0] - zone.centerx) ** 2 + (point[1] - zone.centery) ** 2
                if best_d is None or d < best_d:
                    best_i, best_d = i, d
        return best_i

    def handle_event(self, event):
        if self._show_instructions:
            if self._instructions_min_t <= 0 and (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Garden Wonders"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Garden Wonders"))
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
            pause_music()
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True; self.pause_sel = 0
            pause_music()

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
            lambda: (setattr(self, "paused", False), resume_music()),
            lambda: (self._reset(), start_music(game_bgm_path("Garden Wonders"))),
            lambda: setattr(self, "vol_active", True),
            self._exit_to_game_config,
        ]
        for i, action in enumerate(opts_actions):
            oy = GAME_H // 2 - 160 + i * 96
            if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                play_click()
                action()
                return

    def _apply_vol(self):
        try:
            pygame.mixer.music.set_volume(self.pause_vol)
            from db.database import set_volume
            set_volume(self.pause_vol)
        except Exception:
            pass

    # ── update ───────────────────────────────────────────────────────────

    def update(self, dt):
        if self._show_instructions:
            self._instructions_min_t = max(0.0, self._instructions_min_t - dt)
            return
        if self.game_over:
            return

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        # _session_tick() advances elapsed/time_left here, but acting on
        # it -- actually ending the session -- is deferred to the end of
        # the function (or, in the cycle-pause branch below, to right
        # before ITS OWN early return), so Timed Mode's duration expiring
        # on the exact same frame as a plant finishing growing can never
        # preempt that already-earned point.
        time_up = self._session_tick(dt)

        if self._cycle_pause_t > 0:
            self._cycle_pause_t -= dt
            if self._cycle_pause_t <= 0:
                self._start_new_cycle()
            if self.feedback:
                self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
                if self.feedback[2] <= 0:
                    self.feedback = None
            if time_up:
                self._end_game()
            return

        # ── wrist movement -- horizontal AND vertical ──────────────────
        tx = self._normalize_tilt(self._state["tilt_x"])
        if abs(tx) > self.move_deadzone:
            self.hand_x += self.move_speed * dt * tx
        self.hand_x = max(self.hand_min_x, min(self.hand_max_x, self.hand_x))

        ty = self._vertical_input()
        if abs(ty) > self.move_deadzone:
            self.hand_y += self.move_speed * dt * ty
        self.hand_y = max(self._hand_top_min, min(self._hand_top_max, self.hand_y))

        grip = self._normalize_grip(self._state["grip"])
        grip_valid = grip >= self.grip_threshold
        if not grip_valid:
            self._grip_need_release = False

        # Watering's real gate is wrist rotation now, not grip -- reuses the
        # same horizontal tilt `tx` already computed above for hand movement
        # (this is a SEPARATE, generally higher threshold than move_deadzone,
        # only used to gate the watering hold, never movement itself).
        wrist_mag   = abs(tx)
        wrist_valid = wrist_mag >= self.wrist_requirement
        if not wrist_valid:
            self._wrist_need_release = False
            if self._water2_need_release:
                self._water2_need_release = False

        if input_handler.connected:
            # 5 independent flex channels (Thumb/Index/Middle/Ring/Pinky --
            # MUX channels C0-C4, see sensors/input_handler.py's
            # self._finger_flex), each checked below against ITS OWN
            # calibrated press_threshold (see on_enter()) -- never a shared
            # threshold, never averaged. The patient is never required to
            # use a specific finger, and a low reading on the other 4 can
            # never block a different finger's own press.
            finger_flex = self._state.get("finger_flex") or [0.0] * 5
        else:
            # Test Mode: F is the ONLY flex trigger here -- tilt_y (driven by
            # UP/DOWN in keyboard mode) now means vertical hand movement for
            # this game, so DOWN must no longer also register as flex. A
            # single F press/hold is mapped onto all 5 synthetic channels so
            # the same per-finger state machine below drives Test Mode
            # identically to real hardware (which specific finger "presses"
            # is irrelevant in Test Mode -- there is only the one key).
            f_held = 1.0 if pygame.key.get_pressed()[pygame.K_f] else 0.0
            finger_flex = [f_held] * 5

        # Per-finger press/release (hysteresis), same mechanism as
        # games/whack_mole.py's _update_fingers: a finger must cross ITS
        # OWN press_threshold to fire, then drop back below ITS OWN (lower)
        # release_threshold before it can fire again. All 5 are updated
        # every frame regardless of which one(s) fire, so each finger's own
        # armed state always stays accurate even if more than one crosses
        # in the same frame.
        flex_press = False
        for i in range(5):
            f = finger_flex[i]
            if self._flex_armed[i]:
                if self._finger_is_pressed(i, f):
                    self._flex_armed[i] = False
                    flex_press = True
            else:
                if self._finger_is_released(i, f):
                    self._flex_armed[i] = True

        if self.carrying is None:
            self._water_tilt_target = 0.0
            self._water_hover_plot  = None
            if self._seed_box_rect().collidepoint(self._fingertip_point()) and flex_press:
                self.carrying = "seed"
                self._grip_need_release = True   # a lingering squeeze shouldn't instantly grab the can later
            elif (self._near_asym(self.hand_x, self.can_x,
                                   self.can_grab_tolerance_right if self.hand_flipped
                                       else self.can_grab_tolerance_left,
                                   self.can_grab_tolerance_left if self.hand_flipped
                                       else self.can_grab_tolerance_right)
                    and grip_valid and not self._grip_need_release):
                self.carrying = "can"
                self._grip_need_release = True
                # A lingering wrist tilt at the moment of pickup shouldn't
                # instantly count as the first watering hold.
                self._wrist_need_release = True

        elif self.carrying == "seed":
            self._water_tilt_target = 0.0
            self._water_hover_plot  = None
            over_plot = self._crate_at(self._held_seed_point())
            if (over_plot is not None and self.plots[over_plot].state == "empty"
                    and flex_press):
                plot = self.plots[over_plot]
                plot.state = "planted"
                # Rarity (and the specific plant) is rolled ONCE here, at
                # planting time -- the required water count and the eventual
                # score/sprite at full growth all come from this same roll
                # (see _update_watering), never re-rolled at growth time.
                plot.rarity, plot.plant = _pick_random_plant()
                plot.required_waters = WATER_COUNT[plot.rarity]
                plot.waters_done = 0
                self.carrying = None
                self.feedback = ("Seed planted!", (120, 220, 255), FEEDBACK_DURATION)

        elif self.carrying == "can":
            if flex_press:
                # Deliberate release -- any flex sensor (F in Test Mode)
                # drops the can immediately, regardless of grip/position.
                # Lets the patient recover from an accidental grab (the
                # can's own zone -- see CAN_GRAB_TOLERANCE_* -- is wide on
                # its left side precisely so it's easy to brush against)
                # without having to carry it all the way through a full
                # watering cycle just to get rid of it.
                self.carrying = None
                self._water_tilt_target = 0.0
                self._water_hover_plot  = None
                self.water_progress = 0.0
                self.watering_plot  = None
                self._can_returning = False
                self._grip_need_release = True   # a lingering squeeze shouldn't instantly re-grab it
                self.feedback = ("Watering can released", (255, 200, 120), FEEDBACK_DURATION)
            else:
                # The can now stays attached regardless of grip -- grip only
                # gates picking it up. Watering itself is gated by wrist
                # rotation (see _update_watering). It detaches on its own
                # once the targeted plant finishes growing.
                self._update_watering(dt, self._can_tip_point(), wrist_valid)
                if self._can_returning and abs(self._water_tilt_angle) < 0.5:
                    self.carrying = None
                    self._can_returning = False

        # Two-pour tilt animation -- ease self._water_tilt_angle toward
        # whatever target _update_watering (or the resets above) just set,
        # at a fixed rate so it always reads as one smooth, deliberate
        # motion rather than snapping, in either direction.
        max_step = CAN_TILT_RATE * dt
        diff = self._water_tilt_target - self._water_tilt_angle
        if diff > max_step:
            self._water_tilt_angle += max_step
        elif diff < -max_step:
            self._water_tilt_angle -= max_step
        else:
            self._water_tilt_angle = self._water_tilt_target

        # Short cross-fade whenever a plot's plant sprite changes stage
        # (planted -> watered_once -> grown -- see _update_watering, which
        # populates this), so watering's own visible effect on the plant
        # reads as a deliberate transformation rather than an instant swap.
        for idx in list(self._plant_fade.keys()):
            fade = self._plant_fade[idx]
            fade["t"] += dt
            if fade["t"] >= PLANT_FADE_SEC:
                del self._plant_fade[idx]

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

        if self._tutorial_hints:
            self._tutorial_hints.update(self, dt)

        if time_up:
            self._end_game()

    @staticmethod
    def _near_asym(x, target, tol_left, tol_right):
        """True if x is within tol_left of target on its LEFT side, or
        tol_right on its RIGHT side -- an asymmetric replacement for
        abs(x - target) <= tol, used where one direction of approach
        deserves more forgiveness than the other (see
        CAN_GRAB_TOLERANCE_RIGHT_SCALE)."""
        d = x - target
        return (-d <= tol_left) if d < 0 else (d <= tol_right)

    def _update_watering(self, dt, can_point, wrist_valid):
        """`can_point` is the can's own pouring TIP position (see
        _can_tip_point), matched against each crate's own soil zone (see
        _crate_at) -- not the can's body, not the hand/can sprite's centre,
        and not the old hand_x-only zone. The can itself never drops here
        any more; sustained WRIST ROTATION (wrist_valid, a calibration-
        relative magnitude -- see self.wrist_requirement) now gates whether
        THIS frame's hold-progress advances, not grip."""
        # Default to upright -- only the one "actively accumulating
        # progress" path below (the real first/second pour) tilts it back
        # forward; every early-return here (wrong spot, waiting for
        # release, etc.) leaves it easing back up.
        self._water_tilt_target = 0.0

        over_plot = self._crate_at(can_point)
        if over_plot is None or self.plots[over_plot].state not in ("planted", "watered_once"):
            # Not correctly positioned over a plant that needs water --
            # pause progress (do not discard the plot's own growth state).
            self.water_progress = 0.0
            self.watering_plot  = None
            self._water_hover_plot = None
            return

        # Correctly positioned (tip inside this plot's own hitbox) --
        # tracked independently of grip/progress so the glow + ring (see
        # draw()) can guide the patient INTO position, not just celebrate
        # once they're already succeeding.
        self._water_hover_plot = over_plot

        plot = self.plots[over_plot]
        # First watering needs an explicit release since pickup (so the grab
        # itself can never silently count as watering); every watering after
        # that needs a release from the previous one -- same gating pattern
        # as before, now keyed off wrist rotation instead of grip.
        needs_release = ((plot.state == "planted" and self._wrist_need_release) or
                          (plot.state == "watered_once" and self._water2_need_release))
        if not wrist_valid or needs_release:
            if self.watering_plot == over_plot:
                self.water_progress = 0.0
            return

        if self.watering_plot != over_plot:
            self.watering_plot  = over_plot
            self.water_progress = 0.0

        # Actively pouring -- the can tilts forward over the plant for as
        # long as this stage's hold keeps accumulating (see CAN_TILT_*).
        self._water_tilt_target = CAN_TILT_MAX_DEG
        self.water_progress += dt
        if self.water_progress < self.water_hold:
            return

        self.water_progress = 0.0
        self.watering_plot  = None

        if plot.state == "planted":
            old_img = self._new_plant_img
            plot.waters_done = 1
            plot.state = "watered_once"
            self._water2_need_release = True   # must release before the next watering can start
            self.feedback = ("First watering done!", (120, 220, 255), FEEDBACK_DURATION)
            self._start_plant_fade(over_plot, old_img, self._small_plant_img)
        else:   # "watered_once" -- may need several more waterings depending on rarity
            plot.waters_done += 1
            self._water2_need_release = True   # a release is needed before every subsequent watering
            if plot.waters_done < plot.required_waters:
                self.feedback = ("Keep watering!", (120, 220, 255), FEEDBACK_DURATION)
                return
            # Final watering for this plot's rolled rarity -- fully grown.
            old_img = self._small_plant_img
            plot.state = "grown"
            # The can "returns" -- stays attached/visible (see
            # self._can_returning in update()) just long enough to ease
            # back upright (the animation's Final Return) before actually
            # detaching, instead of vanishing mid-tilt.
            self._can_returning = True
            points = SCORE_BY_RARITY[plot.rarity]
            self.score += points
            self.reps  += 1
            self.feedback = (f"{plot.plant.title()} grown! +{points}", (255, 220, 80), FEEDBACK_DURATION)
            play_success()
            self._start_plant_fade(over_plot, old_img, self._grown_imgs.get(plot.plant))
            if self._session_target_reached():
                self._end_game()
                return
            if all(p.state == "grown" for p in self.plots):
                self._cycle_pause_t = CYCLE_PAUSE_DURATION

    def _start_plant_fade(self, plot_idx, from_img, to_img):
        """Begin a short cross-fade for plot_idx's plant sprite, from
        from_img to to_img, over PLANT_FADE_SEC -- see draw()'s use of
        self._plant_fade for how it's actually rendered."""
        self._plant_fade[plot_idx] = {"from": from_img, "to": to_img, "t": 0.0}

    def _start_new_cycle(self):
        self.plots = [Plot(x) for x in PLOT_XS]
        self.carrying = None
        self.water_progress  = 0.0
        self.watering_plot   = None
        self._water_hover_plot  = None
        self._can_returning     = False
        self._water_tilt_angle  = 0.0
        self._water_tilt_target = 0.0
        self._plant_fade        = {}

    # ── session lifecycle ───────────────────────────────────────────────

    def _exit_to_game_config(self):
        import builtins
        stop_music()
        if not self.game_over and not self._show_instructions:
            self._save_session(status="stopped")
        builtins.pending_panel   = 4
        builtins.pending_patient = self._patient
        builtins.pending_account = self.account
        self.manager.go_to("therapist_dashboard")

    def _save_session(self, status):
        if not self._session_should_save():
            return
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id     = patient_id,
                therapist_id   = self.account_id,
                game           = "Garden Wonders",
                score          = self.score,
                difficulty     = self.difficulty,
                status         = status,
                **self._session_result_fields(),
            )
        except Exception:
            pass

    def _end_game(self):
        if self.game_over:
            return
        stop_music()
        play_completion()
        self.game_over_duration = int(round(self.elapsed))
        self.game_over_score    = self.score
        self._save_session(status="completed")
        self.game_over = True

    # ── draw ─────────────────────────────────────────────────────────────

    def draw(self, surface):
        T = get_theme()
        if self._bg_img is not None:
            surface.blit(self._bg_img, (0, 0))
        else:
            surface.fill(T["BG"])

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        # Watering can, resting -- hidden while carried
        if self.carrying != "can" and self._can_img is not None:
            r = self._can_img.get_rect(midbottom=(int(self.can_x), GROUND_Y))
            surface.blit(self._can_img, r)

        # Seed source, always visible and fixed
        if self._seed_img is not None:
            r = self._seed_img.get_rect(midbottom=(int(self.seed_x), GROUND_Y))
            surface.blit(self._seed_img, r)

        # Five plots: crate + whatever is planted + water-needed indicator.
        # Each plot always draws with its own assigned crate sprite (index i
        # -> CRATE_ASSETS[i]), fixed for the whole session.
        water_ring_pos = None   # set below if a plot is actively being watered this frame
        for i, plot in enumerate(self.plots):
            crate_img = self._crate_imgs[i] if i < len(self._crate_imgs) else None
            # Soil-surface anchor for this specific crate's own rendered
            # rect -- not a fixed offset from the crate's bottom edge, since
            # these sprites show the soil well above the bottom (the front
            # wooden wall sits below it). Falls back to the old
            # just-above-the-bottom anchor if the sprite failed to load.
            if crate_img is not None:
                r = crate_img.get_rect(midbottom=(int(plot.x), CRATE_GROUND_Y))
                surface.blit(crate_img, r)
                soil_y = r.top + int(r.height * CRATE_SOIL_FRAC)
                water_ind_y = r.top - 40
            else:
                soil_y = CRATE_GROUND_Y - 18
                water_ind_y = CRATE_GROUND_Y - 220

            plant_img = None
            if plot.state == "planted":
                plant_img = self._new_plant_img
            elif plot.state == "watered_once":
                plant_img = self._small_plant_img
            elif plot.state == "grown":
                plant_img = self._grown_imgs.get(plot.plant)

            # Soft green glow BEHIND the plant while the can's tip (not its
            # body) is correctly positioned inside this plot's own hitbox --
            # a "you're in the right spot" cue the patient sees before they
            # even need to squeeze, not only once watering is already
            # under way.
            if i == self._water_hover_plot and plant_img is not None:
                glow_r = max(plant_img.get_width(), plant_img.get_height()) // 2
                self._draw_plant_glow(surface, int(plot.x), soil_y - plant_img.get_height() // 2, glow_r)

            fade = self._plant_fade.get(i)
            if fade is not None:
                # Cross-fade the OLD stage out while the NEW one fades in,
                # both anchored at the same soil point -- .copy() each
                # frame rather than mutating the shared cached sprite's own
                # alpha, which every other plot showing that same stage
                # would otherwise instantly inherit.
                t = min(1.0, fade["t"] / PLANT_FADE_SEC)
                if fade["from"] is not None:
                    old = fade["from"].copy()
                    old.set_alpha(int(255 * (1 - t)))
                    surface.blit(old, old.get_rect(midbottom=(int(plot.x), soil_y)))
                if plant_img is not None:
                    new = plant_img.copy()
                    new.set_alpha(int(255 * t))
                    surface.blit(new, new.get_rect(midbottom=(int(plot.x), soil_y)))
            elif plant_img is not None:
                pr = plant_img.get_rect(midbottom=(int(plot.x), soil_y))
                surface.blit(plant_img, pr)

            if plot.state in ("planted", "watered_once") and self._need_water_img is not None:
                wr = self._need_water_img.get_rect(midbottom=(int(plot.x), water_ind_y))
                surface.blit(self._need_water_img, wr)
                if i == self._water_hover_plot:
                    water_ring_pos = wr.center

        # Hand -- default, or holding whatever is being carried. Anchored by
        # its TOP at (self.hand_x, self.hand_y) (seed/idle), or -- while
        # carrying the can -- the lifted anchor at CAN_LIFT_PX, tilted
        # forward around its own wrist pivot during the two-pour animation
        # (see _hand_anchor_y / CAN_PIVOT_FRAC / self._water_tilt_angle).
        hand_img = self._hand_img
        if self.carrying == "seed":
            hand_img = self._hold_seed_img
        elif self.carrying == "can":
            hand_img = self._hold_can_img
        if hand_img is not None:
            if self.carrying == "can":
                top = (int(self.hand_x - hand_img.get_width() / 2), int(self._hand_anchor_y()))
                # CAN_PIVOT_FRAC/the tilt's rotation sign were both measured
                # against the UNflipped art -- mirroring the sprite (see
                # on_enter) also mirrors its own chirality, so a flipped
                # hand needs both the pivot's x-fraction AND the rotation
                # direction mirrored to still read as "tipping forward"
                # rather than tipping the wrong way.
                pivot_x_frac = 1.0 - CAN_PIVOT_FRAC[0] if self.hand_flipped else CAN_PIVOT_FRAC[0]
                pivot_local  = (pivot_x_frac * hand_img.get_width(),
                                 CAN_PIVOT_FRAC[1] * hand_img.get_height())
                pivot_screen = (top[0] + pivot_local[0], top[1] + pivot_local[1])
                tilt_angle = self._water_tilt_angle if self.hand_flipped else -self._water_tilt_angle
                rotated, r = _rotate_anchored(hand_img, tilt_angle,
                                               pivot_local, pivot_screen)
                surface.blit(rotated, r)
            else:
                r = hand_img.get_rect(midtop=(int(self.hand_x), int(self.hand_y)))
                surface.blit(hand_img, r)

        # Watering progress ring -- drawn LAST (on top of the hand/can, not
        # underneath), so the can's own body -- now hovering right over
        # the plot it's watering, per spec -- can never cover it up.
        if water_ring_pos is not None:
            self._draw_watering_progress(surface, water_ring_pos[0], water_ring_pos[1],
                                          self.water_progress / self.water_hold)

        if DEBUG_HITBOXES:
            self._draw_debug_hitboxes(surface)

        draw_game_header(surface, "Garden Wonders", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)
        if self.tutorial:
            draw_tutorial_badge(surface)

        draw_target_pill(surface, self._session_progress_text("plants"),
                          TARGET_POS, T["ACCENT"], self._font_target)

        if self.feedback:
            draw_feedback_banner(surface, self.feedback, self._font_fb,
                                  (GAME_W // 2, int(GAME_H * 0.12)))

        # Pause button — two solid bars (same as every other game)
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

        if self._tutorial_hints:
            self._tutorial_hints.draw(surface, self)

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_plant_glow(self, surface, cx, cy, radius):
        """Soft green glow (a few low-alpha rings, same technique as
        lemonade's squeeze glow) behind a plant's own sprite -- the visual
        cue that the can's TIP is correctly positioned over it right now.
        A clearly different color from the blue progress ring so the two
        cues read as distinct ("in position" vs. "how much longer"), and
        green specifically since it's the one color this garden's own
        brown/blue/orange palette never otherwise uses on a plant."""
        for i, a in enumerate((60, 38, 18)):
            gr = radius + 14 + i * 14
            glow = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (70, 230, 110, a), (gr, gr), gr)
            surface.blit(glow, (cx - gr, cy - gr))

    def _draw_watering_progress(self, surface, cx, cy, progress):
        """Radial progress ring centred on the plot's own need-water
        indicator -- same purpose as games/lemonade.py's lemon-slice ring
        (showing how long the grip must stay squeezed to finish this
        stage), re-themed in cool water-blues rather than lemon-yellow so
        it still reads as distinct from that other game, and a dark
        backing disc behind it so it stays legible over both the bright
        sky and the dark soil this game's background mixes together."""
        progress = max(0.0, min(1.0, progress))
        r = int(WATER_IND_BOX[0] * 0.55) + 10

        backing = pygame.Surface((r * 2 + 10, r * 2 + 10), pygame.SRCALPHA)
        pygame.draw.circle(backing, (10, 30, 40, 160), (r + 5, r + 5), r + 5)
        surface.blit(backing, (cx - r - 5, cy - r - 5))

        DIM_RING  = (80, 120, 130)    # unfilled track -- visible but clearly inactive
        FILL_RING = (70, 200, 255)    # bright, cool, unmistakably "water" -- never confused
                                       # with the warm yellow/orange used elsewhere in this game
        pygame.draw.circle(surface, DIM_RING, (cx, cy), r, 7)
        if progress > 0:
            rect = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
            start = -math.pi / 2
            end   = start + progress * 2 * math.pi
            # pygame.draw.arc can't close a near-full circle cleanly with a
            # tiny remaining gap, so draw it in short steps -- always a
            # smooth, fully-connected arc regardless of thickness.
            steps = max(1, int(progress * 48))
            for s in range(steps):
                a0 = start + (end - start) * (s / steps)
                a1 = start + (end - start) * ((s + 1) / steps)
                pygame.draw.arc(surface, FILL_RING, rect, a0, a1, 7)
        pygame.draw.circle(surface, (235, 250, 255), (cx, cy), r, 2)   # crisp light rim

    def _draw_debug_hitboxes(self, surface):
        """Development-only overlay (see DEBUG_HITBOXES) -- draws every
        interaction region/point described in the game's design spec, so
        hitbox placement can be checked visually against the rendered
        sprites without guessing from coordinates alone."""
        pygame.draw.rect(surface, (255, 0, 0), self._seed_box_rect(), 2)
        pygame.draw.circle(surface, (255, 0, 0), self._fingertip_point(), 10, 2)
        pygame.draw.circle(surface, (0, 255, 0), self._held_seed_point(), 10, 2)
        pygame.draw.circle(surface, (0, 180, 255), self._can_tip_point(), 10, 2)
        tol_l = self.can_grab_tolerance_right if self.hand_flipped else self.can_grab_tolerance_left
        tol_r = self.can_grab_tolerance_left if self.hand_flipped else self.can_grab_tolerance_right
        can_zone_l = pygame.Rect(0, 0, tol_l, 200)
        can_zone_l.midright = (int(self.can_x), GROUND_Y - 100)
        can_zone_r = pygame.Rect(0, 0, tol_r, 200)
        can_zone_r.midleft = (int(self.can_x), GROUND_Y - 100)
        pygame.draw.rect(surface, (255, 255, 0), can_zone_l, 2)
        pygame.draw.rect(surface, (255, 180, 0), can_zone_r, 2)
        for i in range(len(self.plots)):
            pygame.draw.rect(surface, (255, 0, 255), self._crate_plant_rect(i), 2)

    def _draw_instructions(self, surface):
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        card_name = (f"plant_the_garden_how_to_play_{'dark' if is_dark_mode() else 'light'}"
                     f"{'_fil' if self.language == 'fil' else ''}.png")
        # Same outer card box as _draw_results' Round Complete card -- the
        # two screens read as stages of one interface.
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        if card is not None:
            cr = card.get_rect(center=(GAME_W // 2, GAME_H // 2))
            surface.blit(card, cr)
        # Code-drawn "Controls" supplement in the card's own side margin --
        # covers what the card doesn't: vertical movement, watering needing
        # a continued squeeze, and that a flex/wrist-down release works
        # anytime, not just at the plot. No "press any key" prompt -- the
        # patient never starts the game themselves, only the therapist's
        # own START control does.
        lang = self.language
        draw_controls_panel(surface, controls_panel_rect(top_margin, bottom_reserved), [
            (tr("plantgarden.ctrl.tilt.action", lang), tr("plantgarden.ctrl.tilt.desc", lang)),
            (tr("plantgarden.ctrl.grab.action", lang), tr("plantgarden.ctrl.grab.desc", lang)),
            (tr("plantgarden.ctrl.plant.action", lang), tr("plantgarden.ctrl.plant.desc", lang)),
            (tr("plantgarden.ctrl.water.action", lang), tr("plantgarden.ctrl.water.desc", lang)),
        ])

    def _draw_results(self, surface):
        T = get_theme()
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="plant_the_garden", duration_sec=self.game_over_duration,
            score_text=self._session_count_text(), load_fit=_load_image_fit)

        f_btn = get_mono_font(28)

        mp  = pygame.mouse.get_pos()
        bw, bh = 220, 52
        by  = bottom_y + 20

        again_r = pygame.Rect(GAME_W // 2 - bw - 16, by, bw, bh)
        exit_r  = pygame.Rect(GAME_W // 2 + 16,       by, bw, bh)
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
