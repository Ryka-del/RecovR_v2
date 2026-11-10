"""
Plant the Garden — Triple Skill (Wrist Movement + Finger Flexion + Grip Strength) game (1920x1080)

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
import random
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler
from audio import (start_music, stop_music, pause_music, resume_music,
                    game_bgm_path, play_completion, play_click, play_success)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.round_complete import draw_round_complete_overlay

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
GOAL            = {"Easy": 5,    "Medium": 10,   "Hard": 15}     # Target Mode: plants to grow to complete
DURATION        = {"Easy": 120,  "Medium": 100,  "Hard": 80}     # Timed Mode: session length in seconds
GRIP_THRESHOLD  = {"Easy": 0.30, "Medium": 0.45, "Hard": 0.60}   # calibrated grip (0-1) to grab/hold the can
FLEX_THRESHOLD  = {"Easy": 0.20, "Medium": 0.30, "Hard": 0.40}   # calibrated flex (0-1) to pick up/plant a seed
MOVE_DEADZONE   = {"Easy": 0.05, "Medium": 0.08, "Hard": 0.12}   # wrist tilt magnitude before the hand moves
# px radius of every interaction zone. Unlike Feed the Cat's 3 zones spread
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

# ── plant rarity ─────────────────────────────────────────────────────────────
COMMON_PLANTS = ["tomato", "eggplant", "chili", "basil", "cucumber"]
RARE_PLANTS   = ["pumpkin", "jackfruit", "grapes"]
EPIC_PLANTS   = ["starfruit"]

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
    rolled -- a fresh independent roll each time, never a fixed sequence."""
    r = random.random()
    if r < 0.70:
        return random.choice(COMMON_PLANTS)
    elif r < 0.90:
        return random.choice(RARE_PLANTS)
    return random.choice(EPIC_PLANTS)


# on-screen target box each sprite is cropped-to-content and fit within
# (aspect ratio preserved, never stretched) -- see _load_image_fit.
HAND_BOX   = (420, 620)
CRATE_BOX  = (260, 130)   # the 5 new crate sprites are much wider/shallower
                          # than the old single crate -- width-constrained at
                          # every one of their aspect ratios, so all 5 render
                          # at the same 260px width regardless of each one's
                          # own height, per "maintain consistent visual sizes
                          # ... while respecting differences in the artwork."
SOURCE_BOX = (230, 300)
CAN_BOX    = (260, 300)
PLANT_BOX  = (190, 240)
WATER_IND_BOX = (80, 80)

GROUND_Y   = int(GAME_H * 0.82)   # seed source / watering can rest here
# The 5 crates (+ whatever is planted in them + their water-needed indicator)
# sit between the original too-low position and the previous revision's
# too-high one -- a ~46px downward move from the prior 0.64, matching the
# therapist's "30-50px at 1650x927" starting-point request scaled to this
# game's actual 1920x1080 canvas (40px at 927 -> ~46px at 1080). The seed
# source/watering can keep GROUND_Y unchanged.
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
SPOUT_FRAC     = (0.96, 0.17)   # the watering can's pouring spout, once held

SEED_PICKUP_MARGIN = 90    # px of forgiveness around the seed box's own visible rect
PLANT_TOLERANCE     = 60   # px of forgiveness around each crate's own soil region

# One sprite per plot position, left to right -- matches PLOT_XS's own
# ascending order, so CRATE_ASSETS[i] is always plot i's crate.
CRATE_ASSETS = [
    "leftmost_crate_plant_the_garden.png",
    "left_crate_plant_the_garden.png",
    "center_crate_plant_the_garden.png",
    "right_crate_plant_the_garden.png",
    "rightmost_crate_plant_the_garden.png",
]

HAND_MIN_X = CAN_X - 40
HAND_MAX_X = SEED_X + 40

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


def _draw_counter_box(surface, x, y, w, h, font_lbl, font_num, label, value):
    """"Plants grown" counter -- a rounded purple-to-blue gradient card,
    matching the same counter style Feed the Cat already established."""
    grad = pygame.Surface((w, h), pygame.SRCALPHA)
    top_col, bot_col = (124, 92, 226), (70, 150, 221)
    for yy in range(h):
        t = yy / max(1, h - 1)
        col = (int(top_col[0] + (bot_col[0] - top_col[0]) * t),
               int(top_col[1] + (bot_col[1] - top_col[1]) * t),
               int(top_col[2] + (bot_col[2] - top_col[2]) * t), 255)
        pygame.draw.line(grad, col, (0, yy), (w, yy))
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=24)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(grad, (x, y))

    lbl_s = font_lbl.render(label, True, (255, 255, 255))
    max_lbl_w = int(w * 0.88)
    if lbl_s.get_width() > max_lbl_w:
        scale = max_lbl_w / lbl_s.get_width()
        lbl_s = pygame.transform.smoothscale(
            lbl_s, (max(1, int(lbl_s.get_width() * scale)),
                    max(1, int(lbl_s.get_height() * scale))))
    num_s = font_num.render(f"{value:02d}", True, (255, 255, 255))
    surface.blit(lbl_s, lbl_s.get_rect(centerx=x + w // 2, y=y + int(h * 0.22)))
    surface.blit(num_s, num_s.get_rect(centerx=x + w // 2, y=y + int(h * 0.48)))


class Plot:
    """One of the 5 planting plots. state: "empty" | "planted" | "watered_once" | "grown"."""
    def __init__(self, x):
        self.x = x
        self.state = "empty"
        self.plant = None   # the randomly-selected grown-plant name, once grown


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
        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="ptg_goal")
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
        self._hold_can_img    = _load_image_scaled("hold_watering_can_plant_the_garden.png", hand_scale)
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
        self._new_plant_img   = _load_image_fit("new_plant_plant_the_garden.png", *PLANT_BOX)
        self._small_plant_img = _load_image_fit("small_plant_plant_the_garden.png", *PLANT_BOX)
        self._need_water_img  = _load_image_fit("need_water_plant_the_garden.png", *WATER_IND_BOX)
        self._grown_imgs = {name: _load_image_fit(fname, *PLANT_BOX) for name, fname in _GROWN_ASSET.items()}

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)
        self._font_fb  = pygame.font.SysFont("monospace", 44, bold=True)
        font_path = os.path.join(_ROOT, "assets", "font", "Fredoka-Regular.ttf")
        try:
            self._font_counter_lbl = pygame.font.Font(font_path, 30)
            self._font_counter_lbl.set_bold(True)
            self._font_counter_num = pygame.font.Font(font_path, 52)
            self._font_counter_num.set_bold(True)
        except Exception:
            self._font_counter_lbl = pygame.font.SysFont("arial", 30, bold=True)
            self._font_counter_num = pygame.font.SysFont("arial", 52, bold=True)

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
        self._flex_need_release = False
        self._grip_need_release = False
        self._water2_need_release = False
        self.water_progress  = 0.0
        self.watering_plot   = None     # plot index currently accumulating water_progress

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

    def _normalize_tilt(self, raw, axis=None):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return raw
        return max(-1.0, min(1.0, (raw - wmin) / (wmax - wmin) * 2.0 - 1.0))

    def _vertical_input(self):
        """+1 = down, -1 = up (same sign convention tilt_y already has).
        Test Mode: input_handler's own UP/DOWN-driven tilt_y (DOWN no longer
        means flex in THIS game -- see update()'s flex_raw). Real sensor
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

    def _hand_sprite_point(self, img, frac):
        """Screen position of a (fx, fy) fractional point within `img`'s own
        bounding box, given the current hand anchor -- img is always
        midtop-anchored at (self.hand_x, self.hand_y), see draw()."""
        if img is None:
            return (self.hand_x, self.hand_y)
        left = self.hand_x - img.get_width() / 2
        return (left + img.get_width() * frac[0], self.hand_y + img.get_height() * frac[1])

    def _fingertip_point(self):
        """The idle hand's own raised-fingertip point -- used to judge
        whether the hand (not yet holding anything) is close enough to the
        seed box to pick one up."""
        return self._hand_sprite_point(self._hand_img, FINGERTIP_FRAC)

    def _held_seed_point(self):
        """Where the held seed actually is on screen, for planting
        eligibility -- not the hand sprite's own center."""
        return self._hand_sprite_point(self._hold_seed_img, SEED_HOLD_FRAC)

    def _spout_point(self):
        """Where the watering can's actual pouring spout is on screen, for
        watering eligibility -- not the hand/can sprite's own center."""
        return self._hand_sprite_point(self._hold_can_img, SPOUT_FRAC)

    def _seed_box_rect(self):
        """The seed box's own visible rect, inflated by a forgiving margin --
        the real pickup zone, instead of an arbitrary radius hung off
        SEED_X regardless of what is actually on screen there."""
        if self._seed_img is None:
            return pygame.Rect(0, 0, 1, 1)
        r = self._seed_img.get_rect(midbottom=(int(SEED_X), GROUND_Y))
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
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Plant the Garden"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Plant the Garden"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Plant the Garden"))),
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
        if self._show_instructions or self.game_over:
            return

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        if self._session_tick(dt):
            self._end_game()
            return

        if self._cycle_pause_t > 0:
            self._cycle_pause_t -= dt
            if self._cycle_pause_t <= 0:
                self._start_new_cycle()
            if self.feedback:
                self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
                if self.feedback[2] <= 0:
                    self.feedback = None
            return

        # ── wrist movement -- horizontal AND vertical ──────────────────
        tx = self._normalize_tilt(self._state["tilt_x"])
        if abs(tx) > self.move_deadzone:
            self.hand_x += self.move_speed * dt * tx
        self.hand_x = max(HAND_MIN_X, min(HAND_MAX_X, self.hand_x))

        ty = self._vertical_input()
        if abs(ty) > self.move_deadzone:
            self.hand_y += self.move_speed * dt * ty
        self.hand_y = max(self._hand_top_min, min(self._hand_top_max, self.hand_y))

        grip = self._normalize_grip(self._state["grip"])
        grip_valid = grip >= self.grip_threshold
        if not grip_valid:
            self._grip_need_release = False
            if self._water2_need_release:
                self._water2_need_release = False

        if input_handler.connected:
            flex_raw = max(0.0, min(1.0, self._state.get("tilt_y", 0.0)))
        else:
            # Test Mode: F is the ONLY flex trigger here -- tilt_y (driven by
            # UP/DOWN in keyboard mode) now means vertical hand movement for
            # this game, so DOWN must no longer also register as flex.
            flex_raw = 1.0 if pygame.key.get_pressed()[pygame.K_f] else 0.0
        flex_press = flex_raw >= self.flex_threshold and not self._flex_need_release
        self._flex_need_release = flex_raw >= self.flex_threshold

        if self.carrying is None:
            if self._seed_box_rect().collidepoint(self._fingertip_point()) and flex_press:
                self.carrying = "seed"
                self._grip_need_release = True   # a lingering squeeze shouldn't instantly grab the can later
            elif self._near(self.hand_x, CAN_X) and grip_valid and not self._grip_need_release:
                self.carrying = "can"
                self._grip_need_release = True

        elif self.carrying == "seed":
            over_plot = self._crate_at(self._held_seed_point())
            if (over_plot is not None and self.plots[over_plot].state == "empty"
                    and flex_press):
                self.plots[over_plot].state = "planted"
                self.carrying = None
                self.feedback = ("Seed planted!", (120, 220, 255), FEEDBACK_DURATION)

        elif self.carrying == "can":
            # The can now stays attached regardless of grip -- grip only
            # triggers the watering action itself (see _update_watering). It
            # detaches on its own once the targeted plant finishes growing.
            self._update_watering(dt, self._spout_point(), grip_valid)

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

    def _near(self, hand_x, target_x):
        return abs(hand_x - target_x) <= self.zone_tolerance

    def _update_watering(self, dt, spout_point, grip_valid):
        """`spout_point` is the can's actual pouring position (see
        _spout_point), matched against each crate's own soil zone (see
        _crate_at) -- not the hand/can sprite's center and not the old
        hand_x-only zone. The can itself never drops here any more; grip
        now only gates whether THIS frame's hold-progress advances."""
        over_plot = self._crate_at(spout_point)
        if over_plot is None or self.plots[over_plot].state not in ("planted", "watered_once"):
            # Not correctly positioned over a plant that needs water --
            # pause progress (do not discard the plot's own growth state).
            self.water_progress = 0.0
            self.watering_plot  = None
            return

        plot = self.plots[over_plot]
        # First watering needs an explicit release since pickup (so the grab
        # itself can never silently count as watering); second watering
        # needs a release between the two stages, same as before.
        needs_release = ((plot.state == "planted" and self._grip_need_release) or
                          (plot.state == "watered_once" and self._water2_need_release))
        if not grip_valid or needs_release:
            if self.watering_plot == over_plot:
                self.water_progress = 0.0
            return

        if self.watering_plot != over_plot:
            self.watering_plot  = over_plot
            self.water_progress = 0.0

        self.water_progress += dt
        if self.water_progress < self.water_hold:
            return

        self.water_progress = 0.0
        self.watering_plot  = None

        if plot.state == "planted":
            plot.state = "watered_once"
            self._water2_need_release = True   # must release before stage 2 can start
            self.feedback = ("First watering done!", (120, 220, 255), FEEDBACK_DURATION)
        else:   # "watered_once" -> fully grown
            plot.plant = _pick_random_plant()
            plot.state = "grown"
            self.carrying = None   # the can "returns" -- detaches once this plant is done
            self.score += 1
            self.reps  += 1
            self.feedback = (f"{plot.plant.title()} grown! +1", (255, 220, 80), FEEDBACK_DURATION)
            play_success()
            if self._session_target_reached():
                self._end_game()
                return
            if all(p.state == "grown" for p in self.plots):
                self._cycle_pause_t = CYCLE_PAUSE_DURATION

    def _start_new_cycle(self):
        self.plots = [Plot(x) for x in PLOT_XS]
        self.carrying = None
        self.water_progress  = 0.0
        self.watering_plot   = None

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
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id     = patient_id,
                therapist_id   = self.account_id,
                game           = "Plant the Garden",
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

        font_sm = self._font_sm

        # Watering can, resting -- hidden while carried
        if self.carrying != "can" and self._can_img is not None:
            r = self._can_img.get_rect(midbottom=(int(CAN_X), GROUND_Y))
            surface.blit(self._can_img, r)

        # Seed source, always visible and fixed
        if self._seed_img is not None:
            r = self._seed_img.get_rect(midbottom=(int(SEED_X), GROUND_Y))
            surface.blit(self._seed_img, r)

        # Five plots: crate + whatever is planted + water-needed indicator.
        # Each plot always draws with its own assigned crate sprite (index i
        # -> CRATE_ASSETS[i]), fixed for the whole session.
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
            if plant_img is not None:
                pr = plant_img.get_rect(midbottom=(int(plot.x), soil_y))
                surface.blit(plant_img, pr)

            if plot.state in ("planted", "watered_once") and self._need_water_img is not None:
                wr = self._need_water_img.get_rect(midbottom=(int(plot.x), water_ind_y))
                surface.blit(self._need_water_img, wr)

        # Hand -- default, or holding whatever is being carried. Anchored by
        # its TOP at (self.hand_x, self.hand_y), both now patient-controlled
        # (see update()'s vertical movement + self._hand_top_min/_max).
        hand_img = self._hand_img
        if self.carrying == "seed":
            hand_img = self._hold_seed_img
        elif self.carrying == "can":
            hand_img = self._hold_can_img
        if hand_img is not None:
            r = hand_img.get_rect(midtop=(int(self.hand_x), int(self.hand_y)))
            surface.blit(hand_img, r)

        if DEBUG_HITBOXES:
            self._draw_debug_hitboxes(surface)

        # Plants grown counter (top-left, below the header)
        cx = int(40 * GAME_W / 1920)
        cy = HEADER_BOTTOM + int(20 * GAME_H / 1080)
        cw = int(240 * GAME_W / 1920)
        ch = int(190 * GAME_H / 1080)
        _draw_counter_box(surface, cx, cy, cw, ch,
                          self._font_counter_lbl, self._font_counter_num,
                          "Plants grown", self.reps)

        draw_game_header(surface, "Plant the Garden", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        prog_s = font_sm.render(self._session_progress_text("plants"), True, T["TEXT"])
        surface.blit(prog_s, (cx, cy + ch + int(10 * GAME_H / 1080)))

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, int(GAME_H * 0.12)))

        hints = {
            "Easy":   "Tilt wrist to move   •   Flex to plant, squeeze to water",
            "Medium": "Tilt wrist to move   •   Water twice — release grip between waterings",
            "Hard":   "Tilt wrist to move   •   Precise positioning + sustained grip required",
        }
        surface.blit(font_sm.render(hints[self.difficulty], True, T["GRAY"]),
                     (GAME_W // 2 - 380, GAME_H - 44))

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

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_debug_hitboxes(self, surface):
        """Development-only overlay (see DEBUG_HITBOXES) -- draws every
        interaction region/point described in the game's design spec, so
        hitbox placement can be checked visually against the rendered
        sprites without guessing from coordinates alone."""
        pygame.draw.rect(surface, (255, 0, 0), self._seed_box_rect(), 2)
        pygame.draw.circle(surface, (255, 0, 0), self._fingertip_point(), 10, 2)
        pygame.draw.circle(surface, (0, 255, 0), self._held_seed_point(), 10, 2)
        pygame.draw.circle(surface, (0, 180, 255), self._spout_point(), 10, 2)
        can_zone = pygame.Rect(0, 0, self.zone_tolerance * 2, 200)
        can_zone.midbottom = (int(CAN_X), GROUND_Y)
        pygame.draw.rect(surface, (255, 255, 0), can_zone, 2)
        for i in range(len(self.plots)):
            pygame.draw.rect(surface, (255, 0, 255), self._crate_plant_rect(i), 2)

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        card_name = f"plant_the_garden_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
        # Same outer card box as _draw_results' Round Complete card -- the
        # two screens read as stages of one interface.
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        bottom_y = GAME_H // 2
        if card is not None:
            cr = card.get_rect(midtop=(GAME_W // 2, top_margin))
            surface.blit(card, cr)
            bottom_y = cr.bottom

        # No "press any key" prompt -- the patient never starts the game
        # themselves, only the therapist's own START control does.
        f_info = pygame.font.SysFont("monospace", 22, bold=True)
        sess_txt = (f"Goal: Grow {self.goal} plants" if self.session_mode == "target" else
                    f"Duration: {int(self.timed_duration)}s — grow as many plants as you can")
        info = f_info.render(f"{sess_txt}   ·   Difficulty: {self.difficulty}", True, T["WHITE"])
        info_r = info.get_rect(centerx=GAME_W // 2, top=bottom_y + 14)
        surface.blit(info, info_r)

    def _draw_results(self, surface):
        T = get_theme()
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="plant_the_garden", duration_sec=self.game_over_duration,
            score_text=self._session_count_text(), load_fit=_load_image_fit)

        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

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
