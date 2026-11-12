"""
Toy Factory — Dual Skill (Wrist Movement + Grip Strength) game (1920x1080)

Mechanic (see the spec this file implements -- "Complete Replacement of
Catch 'n Grab with Toy Factory"):
  - Toys spawn at the left edge of a conveyor and travel right. The patient
    moves a hand/arm with GENUINE two-axis MPU6050 wrist movement (left/
    right AND up/down -- see _vertical_raw() below), positions it over a
    toy, and squeezes the FSR402 glove past its calibrated threshold to
    grab it.
  - A held toy follows the hand exactly (no auto-transport). Relaxing the
    grip below the release threshold opens the hand; the toy then falls
    STRAIGHT DOWN from wherever it was released (no auto-redirect) and is
    sorted into whichever box's opening its fall path actually passes
    through -- Plushies (purple/left), Puzzles (green/center), Random
    (red/right). Landing in the matching box scores a point and a
    successful repetition; the wrong box or missing every box scores
    nothing (the attempt still consumed a grab/release cycle).
  - Grip uses a press/release hysteresis band (grab_threshold / a lower
    release_threshold) so sensor noise right at the threshold can't chatter
    the hand open/closed, and a grab is only ATTEMPTED on the open->closed
    transition (one deliberate squeeze = one grab attempt), never on a
    continuous hold -- see _update_grip().
  - Vertical wrist control reads the REAL MPU6050 Y axis directly off the
    BLE packet in live hardware mode, exactly like games/steady_aim.py's
    own _vertical_raw() -- input_handler.py's state["tilt_y"] carries the
    Flex Sensor on real hardware, not vertical tilt, so it is never used
    for movement here except in Test Mode (keyboard UP/DOWN, which DOES
    legitimately drive that same field -- see sensors/input_handler.py's
    _update_keyboard()).
"""

import os
import math
import random
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler
from audio import (start_music, stop_music, pause_music, resume_music,
                    game_bgm_path, play_success, play_error, play_completion, play_click)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.hud import draw_target_pill, TARGET_POS
from games.round_complete import draw_round_complete_overlay

# Real MPU6050 Y-axis tilt (accel_y) -- see games/steady_aim.py's own copy
# of this exact import/rationale. Scoped to this file only.
try:
    from sensors.ble_receiver import ble_receiver as _ble
except Exception:
    _ble = None

# ── difficulty-scaled parameters ────────────────────────────────────────────
GOAL      = {"Easy": 15, "Medium": 20, "Hard": 25}   # Target Mode: toys to sort
DURATION  = {"Easy": 90, "Medium": 75, "Hard": 60}   # Timed Mode: session length (s)

CONVEYOR_SPEED_PRESET    = {"Easy": 90,  "Medium": 140, "Hard": 200}  # px/s, Advanced-Settings-overridable
# Wide enough that only ~5 toys are ever on the belt at once: a toy travels
# ~2220px (spawn point to the miss line, see Toy/_spawn_toy/update() below)
# at `conveyor_speed`, so spawn_gap = that travel time / 5 for every
# difficulty -- faster belts get a proportionally shorter gap, not a fixed
# one, so the on-screen count stays ~5 regardless of difficulty.
SPAWN_GAP                = {"Easy": 4.9, "Medium": 3.2, "Hard": 2.2}  # seconds between toy spawns
PICKUP_TOLERANCE_PRESET  = {"Easy": 110, "Medium": 85,  "Hard": 65}   # px radius, Advanced-Settings-overridable
BOX_TOLERANCE_PRESET     = {"Easy": 1.25,"Medium": 1.0, "Hard": 0.8}  # multiplier on the box opening half-width

# Grip: a real calibrated threshold is used whenever available (see
# on_enter()) -- these are only the fallback if calibration was skipped.
DEFAULT_GRIP_THRESHOLD = {"Easy": 0.30, "Medium": 0.45, "Hard": 0.60}
RELEASE_MARGIN = 0.70   # release threshold = grab threshold * this

# Wrist: "how much of the patient's OWN calibrated average movement is
# required to reach full hand speed" -- Easy asks for well under their
# calibrated average (forgiving/sensitive), Hard asks for MORE than their
# calibrated average (must move further than they did in calibration), per
# spec 8's "greater wrist movement requirement". Falls back to a flat
# average if a wrist axis was never actually calibrated.
WRIST_REQUIREMENT_FRAC = {"Easy": 0.60, "Medium": 0.85, "Hard": 1.15}
DEFAULT_WRIST_AVG      = {"Easy": 0.35, "Medium": 0.45, "Hard": 0.55}
WRIST_DEADZONE = 0.08

MOVE_SPEED  = 1500   # px/s hand speed at full (1.0) normalized wrist tilt
FALL_SPEED  = 700     # px/s -- a released toy's constant straight-down fall
RETURN_DURATION = 0.5  # seconds -- a wrong-box/outside-box toy's smooth tween
                        # back to its own conveyor slot (see Toy.home_x/home_y
                        # and the "returning" phase in update())
ENTER_DURATION  = 0.35  # seconds -- a correctly-sorted toy's sink-into-the-box
                         # tween (see Toy._enter_from and the "entering" phase)
                         # before it's actually removed from play
BOX_RIM_FRAC    = 0.22  # fraction of BOX_HEIGHT down from the box's own top
                         # where its front wall visually occludes anything
                         # inside -- a toy past this line is clipped away
                         # (see _draw) so it reads as having gone IN the box,
                         # not just stopping on top of it

# ── toy categories (final mapping -- confirmed explicitly: Bear/Bunny/
# Robot/Dino -> Puzzles, Shape/Build/Circle/Square -> Plushies, do not
# reverse) ───────────────────────────────────────────────────────────────────
# The box label ART (plushie_box/puzzle_box_toy_factory.png) was edited to
# match this mapping -- each box's embedded toy icons were swapped between
# the two files (same cream label/dashed-border/rivets, just the icon
# illustrations relocated to the box whose category they actually belong
# to) so the printed label always agrees with what that box actually
# accepts.
TOY_CATEGORY = {
    "bear": "puzzles", "bunny": "puzzles", "robot": "puzzles", "dino": "puzzles",
    "shape": "plushies", "build": "plushies", "circle": "plushies", "square": "plushies",
    "caterpillar": "random", "train": "random", "pinwheel": "random", "drums": "random",
}
TOY_KEYS = list(TOY_CATEGORY.keys())

# category -> (box asset prefix, display name, rim colour, x-fraction of screen)
BOX_INFO = [
    ("plushies", "plushie_box_toy_factory", "Plushies", (150, 70, 190), 0.22),
    ("puzzles",  "puzzle_box_toy_factory",  "Puzzles",  (70, 160, 80),  0.50),
    ("random",   "random_box_toy_factory",  "Random",   (200, 60, 60),  0.78),
]

# ── screen geometry (1920x1080) ─────────────────────────────────────────────
# bg_toy_factory.png's own floor/baseboard line sits at ~67% of its height
# (measured directly off the art) -- the conveyor's legs are short stubs in
# the source art (they end abruptly, well short of the canvas edge), so
# the conveyor is positioned so those legs land exactly on that floor line
# instead of floating over the back wall.
FLOOR_Y_FRAC   = 0.69
CONVEYOR_ASPECT = 2956 / 420   # conveyor_toy_factory.png's own cropped w:h
CONVEYOR_H      = int(GAME_W / CONVEYOR_ASPECT)
CONVEYOR_BOTTOM_Y = int(FLOOR_Y_FRAC * GAME_H)
CONVEYOR_TOP_Y    = CONVEYOR_BOTTOM_Y - CONVEYOR_H

BOX_TOP_Y         = CONVEYOR_BOTTOM_Y
BOX_HEIGHT        = int(0.25 * GAME_H)
BOX_WIDTH         = int(BOX_HEIGHT * 1.5)
BOX_BOTTOM_Y      = BOX_TOP_Y + BOX_HEIGHT

HAND_X_MIN, HAND_X_MAX = int(0.045 * GAME_W), int(0.955 * GAME_W)
HAND_Y_MIN, HAND_Y_MAX = CONVEYOR_TOP_Y - int(0.09 * GAME_H), BOX_TOP_Y + int(BOX_HEIGHT * 0.22)

TOY_BOX = (150, 175)   # on-conveyor/held toy sprite bounding box
TOY_HELD_SCALE = 1.25  # a grabbed toy renders larger -- makes the grab read clearly

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}


def _load_image_fit(name, w, h):
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


def _load_image_cover(name, w, h):
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


class Toy:
    """One toy: its category/sprite, where it is, and its lifecycle phase
    (belt -> held -> falling -> gone, or falling -> returning -> belt again
    when a drop isn't a successful delivery -- see _resolve_sort/_check_landing).

    home_x/home_y is this toy's own conveyor slot -- wherever it was on the
    belt the instant it was last grabbed (see _try_grab) -- so a wrong-box
    or outside-every-box drop can send it smoothly back to THAT spot (never
    reset to the far-left spawn point, never dropped onto another toy's
    slot) instead of being discarded, exactly like a toy that was simply
    never picked up."""

    def __init__(self, key):
        self.key      = key
        self.category = TOY_CATEGORY[key]
        self.phase    = "belt"
        self.x        = -TOY_BOX[0]
        self.y        = 0.0
        self.home_x   = self.x
        self.home_y   = self.y
        self._return_from = (0.0, 0.0)
        self._return_t    = 0.0
        self._enter_from  = (0.0, 0.0)
        self._enter_to    = (0.0, 0.0)
        self._enter_t     = 0.0


class ToyFactoryGame(SessionModeMixin, FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        cal_params = self.cal.get("params", {})
        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="tf_goal")

        self.conveyor_speed   = cal_params.get("tf_conveyor_speed", CONVEYOR_SPEED_PRESET[self.difficulty])
        self.spawn_gap        = SPAWN_GAP[self.difficulty]
        self.pickup_tolerance = cal_params.get("tf_pickup_tolerance", PICKUP_TOLERANCE_PRESET[self.difficulty])
        self.box_tolerance    = cal_params.get("tf_box_tolerance", BOX_TOLERANCE_PRESET[self.difficulty])

        # Grip + wrist requirements come from the patient's OWN calibration
        # (see scenes/calibration_window.py's MULTI_SENSOR_CALIBRATION
        # ["Toy Factory"] = ["Grip Strength", "Wrist Horizontal",
        # "Wrist Vertical"]) -- never a fixed clinical value, with a
        # difficulty default only if a sensor was never actually
        # calibrated. These are deliberately NOT also in
        # GAME_PARAM_SCHEMA -- that mechanism always supplies a preset
        # value for every schema'd key (see CalibrationWindow._apply_preset),
        # which would silently override real calibration data every single
        # session instead of only when the therapist explicitly customizes
        # it.
        sensors_cal = self.cal.get("sensors", {})

        def _cal_val(name, field, default):
            entry = sensors_cal.get(name)
            v = entry.get(field) if entry else None
            return v if v else default

        self.grab_threshold = _cal_val("Grip Strength", "threshold", DEFAULT_GRIP_THRESHOLD[self.difficulty])
        self.release_threshold = self.grab_threshold * RELEASE_MARGIN

        wh_avg = _cal_val("Wrist Horizontal", "average", DEFAULT_WRIST_AVG[self.difficulty])
        wv_avg = _cal_val("Wrist Vertical", "average", DEFAULT_WRIST_AVG[self.difficulty])
        frac = WRIST_REQUIREMENT_FRAC[self.difficulty]
        self.wrist_h_range = max(0.05, wh_avg * frac)
        self.wrist_v_range = max(0.05, wv_avg * frac)

        W, H = GAME_W, GAME_H
        self._bg_img       = _load_image_cover("bg_toy_factory.png", W, H)
        self._conveyor_img = _load_image_fit("conveyor_toy_factory.png", W, int(H * 0.30))
        self.conveyor_h    = self._conveyor_img.get_height() if self._conveyor_img is not None else int(H * 0.22)

        self._box_imgs = {}
        self._box_pos  = {}
        for cat, asset, _label, _color, x_frac in BOX_INFO:
            self._box_imgs[cat] = _load_image_fit(f"{asset}.png", BOX_WIDTH, BOX_HEIGHT)
            self._box_pos[cat]  = (int(W * x_frac), BOX_TOP_Y)

        self._toy_imgs = {key: _load_image_fit(f"{key}_toy_factory.png", *TOY_BOX) for key in TOY_KEYS}
        held_box = (int(TOY_BOX[0] * TOY_HELD_SCALE), int(TOY_BOX[1] * TOY_HELD_SCALE))
        self._toy_imgs_held = {key: _load_image_fit(f"{key}_toy_factory.png", *held_box) for key in TOY_KEYS}

        # Direct 1:1 cursor, same movement/render model as games/
        # plant_the_garden.py's own hand -- a fixed-size sprite that just
        # translates with hand_x/hand_y, never rotated or rescaled. The
        # fingertip point (where a toy attaches / where grabs are judged)
        # is measured directly off the artwork as a fraction of this
        # loaded image, and is what gets pinned to (hand_x, hand_y) --
        # see _draw_hand().
        hand_ref_h = int(H * 0.62)
        self._hand_imgs = {
            "open": _load_image_fit("hand_toy_factory.png", int(hand_ref_h * 0.75), hand_ref_h),
            "grab": _load_image_fit("hand_grab_toy_factory.png", int(hand_ref_h * 0.75), hand_ref_h),
        }
        ref = self._hand_imgs["open"]
        if ref is not None:
            rw, rh = ref.get_size()
            self._hand_tip_local = (0.789 * rw, 0.087 * rh)
            # A held toy is centred in the PINCER GAP between the index
            # fingertip (_hand_tip_local) and the thumb tip (also measured
            # off the art), not pinned to the index tip alone -- that's
            # what makes it read as cradled BETWEEN the fingers (per the
            # reference photo) instead of floating off to one side of them.
            thumb_tip_local = (1.0 * rw, 0.185 * rh)
            self._toy_hold_offset = ((thumb_tip_local[0] - self._hand_tip_local[0]) / 2,
                                      (thumb_tip_local[1] - self._hand_tip_local[1]) / 2)
        else:
            self._hand_tip_local = (0.0, 0.0)
            self._toy_hold_offset = (0.0, 0.0)

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_target = pygame.font.SysFont("monospace", 54, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)
        self._font_fb  = pygame.font.SysFont("monospace", 46, bold=True)

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
        self.paused    = False
        self.pause_sel = 0

        self.score   = 0
        self.reps    = 0    # successful sorts
        self.missed  = 0    # toys that reached the belt's end unhit
        self.wrong   = 0    # sorted into the wrong box
        self._session_reset()
        self.start_time = pygame.time.get_ticks()

        self.toys = []
        self._held_toy  = None
        self._gripping  = False
        self.spawn_timer = 0.0
        self.feedback = None

        self.hand_x = GAME_W / 2.0
        self.hand_y = (HAND_Y_MIN + HAND_Y_MAX) / 2.0
        self._tilt_x_smooth = 0.0
        self._tilt_y_smooth = 0.0

        self._state = {"grip": 0.0, "tilt_x": 0.0, "tilt_y": 0.0}

    # ── sensor input ─────────────────────────────────────────────────────

    def _vertical_raw(self):
        """Real MPU6050 Y axis on actual hardware; UP/DOWN-arrow-driven
        tilt_y in Test Mode (see module docstring / games/steady_aim.py)."""
        if input_handler.connected:
            if _ble is None:
                return 0.0
            try:
                return max(-1.0, min(1.0, _ble.get_latest()["accel_y"] / 16384.0))
            except Exception:
                return 0.0
        return self._state.get("tilt_y", 0.0)

    def _normalize_wrist(self, raw, axis_range):
        v = max(-1.0, min(1.0, raw / axis_range))
        return v if abs(v) > WRIST_DEADZONE else 0.0

    def _normalize_grip(self, raw):
        """Used by generic_adapter.py's therapist telemetry -- "calibrated"
        is whether grip is currently at/above the grab threshold, the same
        value _update_grip() itself acts on."""
        return 1.0 if raw >= self.grab_threshold else 0.0

    def _normalize_tilt(self, raw, axis):
        """Same telemetry contract as every other game's _normalize_tilt --
        called by generic_adapter.py with (raw, axis_letter)."""
        rng = self.wrist_h_range if axis == "x" else self.wrist_v_range
        return self._normalize_wrist(raw, rng)

    # ── lifecycle / events ───────────────────────────────────────────────

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Toy Factory"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Toy Factory"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Toy Factory"))),
            lambda: setattr(self, "vol_active", True),
            self._exit_to_game_config,
        ]
        for i, action in enumerate(opts_actions):
            oy = GAME_H // 2 - 160 + i * 96
            if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                play_click()
                action()
                return

    # ── update ───────────────────────────────────────────────────────────

    def update(self, dt):
        if self._show_instructions or self.game_over:
            return

        live = input_handler.get_state()
        ty_raw = self._vertical_raw()
        self._state = dict(live)
        self._state["tilt_y"] = ty_raw   # real accel_y, visible to therapist telemetry too

        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        if self._session_tick(dt):
            self._end_game()
            return

        self._update_hand(dt)
        self._update_grip()

        # Spawn
        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_gap:
            self.spawn_timer = 0.0
            self._spawn_toy()

        # Advance every toy's own lifecycle
        for toy in list(self.toys):
            if toy.phase == "belt":
                toy.x += self.conveyor_speed * dt
                if toy.x > GAME_W + TOY_BOX[0]:
                    toy.phase = "gone"
                    self.missed += 1
            elif toy.phase == "held":
                toy.x, toy.y = self._hand_grab_point()
            elif toy.phase == "falling":
                toy.y += FALL_SPEED * dt
                self._check_landing(toy)
            elif toy.phase == "returning":
                toy._return_t += dt
                f = min(1.0, toy._return_t / RETURN_DURATION)
                fx, fy = toy._return_from
                toy.x = fx + (toy.home_x - fx) * f
                toy.y = fy + (toy.home_y - fy) * f
                if f >= 1.0:
                    toy.x, toy.y = toy.home_x, toy.home_y
                    toy.phase = "belt"
            elif toy.phase == "entering":
                toy._enter_t += dt
                f = min(1.0, toy._enter_t / ENTER_DURATION)
                fx, fy = toy._enter_from
                tx, ty = toy._enter_to
                toy.x = fx + (tx - fx) * f
                toy.y = fy + (ty - fy) * f
                if f >= 1.0:
                    toy.phase = "gone"
        self.toys = [t for t in self.toys if t.phase != "gone"]

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

    def _spawn_toy(self):
        key = random.choice(TOY_KEYS)
        toy = Toy(key)
        toy.y = float(CONVEYOR_TOP_Y)
        self.toys.append(toy)

    def _update_hand(self, dt):
        tx = self._normalize_wrist(self._state.get("tilt_x", 0.0), self.wrist_h_range)
        ty = self._normalize_wrist(self._state.get("tilt_y", 0.0), self.wrist_v_range)
        # Light smoothing damps minor sensor jitter without adding
        # noticeable delay to deliberate movement -- same technique/constant
        # as games/steady_aim.py's own cursor smoothing.
        smooth_k = min(1.0, dt * 10.0)
        self._tilt_x_smooth += (tx - self._tilt_x_smooth) * smooth_k
        self._tilt_y_smooth += (ty - self._tilt_y_smooth) * smooth_k
        tx, ty = self._tilt_x_smooth, self._tilt_y_smooth
        if tx:
            self.hand_x += MOVE_SPEED * dt * tx
        if ty:
            self.hand_y += MOVE_SPEED * dt * ty
        self.hand_x = max(HAND_X_MIN, min(HAND_X_MAX, self.hand_x))
        self.hand_y = max(HAND_Y_MIN, min(HAND_Y_MAX, self.hand_y))

    def _hand_grab_point(self):
        """Where a held toy attaches -- the hand's own position (the
        gameplay/collision authority), not a recomputed sprite pixel."""
        return self.hand_x, self.hand_y

    # ── grip: press/release hysteresis, one grab attempt per squeeze ──────

    def _update_grip(self):
        grip = self._state.get("grip", 0.0)
        if not self._gripping:
            if grip >= self.grab_threshold:
                self._gripping = True
                self._try_grab()
        else:
            if grip <= self.release_threshold:
                self._gripping = False
                self._try_release()

    def _try_grab(self):
        if self._held_toy is not None:
            return
        hx, hy = self.hand_x, self.hand_y
        best, best_d = None, self.pickup_tolerance
        for toy in self.toys:
            if toy.phase != "belt":
                continue
            d = math.hypot(toy.x - hx, toy.y - hy)
            if d <= best_d:
                best, best_d = toy, d
        if best is not None:
            best.home_x, best.home_y = best.x, best.y   # this toy's own conveyor slot
            best.phase = "held"
            self._held_toy = best
            play_click()

    def _try_release(self):
        toy = self._held_toy
        if toy is None:
            return
        self._held_toy = None
        toy.phase = "falling"
        # toy.x/.y already sit at the release point (set every frame while held)

    def _check_landing(self, toy):
        for cat, _asset, _label, _color, _xf in BOX_INFO:
            bx, by = self._box_pos[cat]
            half_w = (BOX_WIDTH * 0.34) * self.box_tolerance
            open_top = by + BOX_HEIGHT * 0.06
            open_bot = by + BOX_HEIGHT * 0.34
            if open_top <= toy.y <= open_bot and abs(toy.x - bx) <= half_w:
                self._resolve_sort(toy, cat)
                return
        if toy.y > BOX_BOTTOM_Y + 40:
            self._return_toy(toy)   # released outside every box -- unsuccessful attempt, no score

    def _return_toy(self, toy):
        """A failed delivery (wrong box, or outside every box) never removes
        the toy -- it tweens smoothly back to its own conveyor slot
        (home_x/home_y) and resumes belt travel from there, so the patient
        can grab and re-attempt the exact same toy."""
        toy._return_from = (toy.x, toy.y)
        toy._return_t = 0.0
        toy.phase = "returning"

    def _resolve_sort(self, toy, box_cat):
        if toy.category == box_cat:
            # Keeps falling (a bit further, toward the box's own centre)
            # instead of vanishing the instant it crosses the rim -- clipped
            # away by the box's front wall as it goes (see draw()) so it
            # visually lands INSIDE the box, not just disappears on top of it.
            bx, by = self._box_pos[box_cat]
            toy._enter_from = (toy.x, toy.y)
            toy._enter_t = 0.0
            toy._enter_to = (bx, by + BOX_HEIGHT * 0.55)
            toy.phase = "entering"
            self.score += 1
            self.reps  += 1
            self.feedback = ("Sorted!", (0, 220, 140), 0.7)
            play_success()
            if self._session_target_reached():
                self._end_game()
        else:
            self.wrong += 1
            self.feedback = ("Wrong box!", (255, 90, 90), 0.8)
            play_error()
            self._return_toy(toy)

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
                patient_id   = patient_id,
                therapist_id = self.account_id,
                game         = "Toy Factory",
                score        = self.score,
                difficulty   = self.difficulty,
                status       = status,
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

        if self._conveyor_img is not None:
            surface.blit(self._conveyor_img, (0, CONVEYOR_TOP_Y))

        for cat, _asset, label, _color, _xf in BOX_INFO:
            img = self._box_imgs.get(cat)
            bx, by = self._box_pos[cat]
            if img is not None:
                r = img.get_rect(midtop=(bx, by))
                surface.blit(img, r)
            lbl = font_sm.render(label, True, (255, 255, 255))
            lr = lbl.get_rect(center=(bx, by + BOX_HEIGHT + 20))
            bgr = lr.inflate(16, 8)
            bgs = pygame.Surface(bgr.size, pygame.SRCALPHA)
            pygame.draw.rect(bgs, (20, 20, 30, 170), (0, 0, *bgr.size), border_radius=8)
            surface.blit(bgs, bgr.topleft)
            surface.blit(lbl, lr)

        for toy in self.toys:
            if toy.phase == "gone":
                continue
            if toy.phase == "held":
                # Bigger (TOY_HELD_SCALE), and centred in the pincer gap
                # between the hand's index fingertip and thumb tip
                # (_toy_hold_offset) rather than pinned to the fingertip
                # alone -- it reads as cradled BETWEEN the fingers (per the
                # reference photo) instead of floating off to one side of
                # the hand. The hand is drawn next, on top, so its fingers
                # naturally overlap the near edge of the toy, reading as an
                # actual grip.
                img = self._toy_imgs_held.get(toy.key)
                if img is not None:
                    hold_pos = (toy.x + self._toy_hold_offset[0], toy.y + self._toy_hold_offset[1])
                    surface.blit(img, img.get_rect(center=hold_pos))
                continue
            img = self._toy_imgs.get(toy.key)
            if img is None:
                continue
            if toy.phase == "entering":
                # Clipped against the box's own front-wall line as it sinks
                # in (same clip-reveal technique as games/whack_mole.py's
                # moles) -- without this it just stops on TOP of the box
                # instead of visibly going inside it.
                rect = img.get_rect(center=(int(toy.x), int(toy.y)))
                _bx, by = self._box_pos[toy.category]
                rim_y = by + int(BOX_HEIGHT * BOX_RIM_FRAC)
                visible_h = max(0, min(rect.height, rim_y - rect.top))
                if visible_h > 0:
                    sub = img.subsurface((0, 0, rect.width, visible_h))
                    surface.blit(sub, (rect.left, rect.top))
                continue
            surface.blit(img, img.get_rect(center=(int(toy.x), int(toy.y))))

        self._draw_hand(surface)

        draw_game_header(surface, "Toy Factory", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        # Lower than the header, like every other game's tracker, but NOT
        # all the way down at the shared TARGET_POS -- the delivery boxes
        # occupy that whole band here, so the pill sits just above them.
        draw_target_pill(surface, self._session_progress_text("sorted"),
                          (TARGET_POS[0], BOX_TOP_Y - 110), T["ACCENT"], self._font_target)

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, int(GAME_H * 0.10)))

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

    def _draw_hand(self, surface):
        """Direct 1:1 cursor -- same model as games/plant_the_garden.py's
        own hand: a fixed-size sprite that only ever translates, never
        rotated or rescaled. The sprite's own fingertip point (measured off
        the artwork) is pinned exactly to (hand_x, hand_y), so the drawn
        position always matches the real gameplay/collision point exactly
        (no rotation/scale approximation to drift out of sync with it)."""
        key = "grab" if (self._gripping or self._held_toy is not None) else "open"
        img = self._hand_imgs.get(key) or self._hand_imgs.get("open")
        if img is None:
            pygame.draw.circle(surface, (240, 200, 170), (int(self.hand_x), int(self.hand_y)), 30)
            return
        topleft = (self.hand_x - self._hand_tip_local[0],
                   self.hand_y - self._hand_tip_local[1])
        surface.blit(img, topleft)

    def _draw_instructions(self, surface):
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        # Fully designed "How To Play" card art (title, numbered steps, tip
        # banner all baked in) -- replaces the hand-drawn panel. Per-theme,
        # cropped to its own opaque content then fit preserving aspect
        # ratio. Same outer card box (position + max size) as _draw_results'
        # Round Complete card -- the two screens read as stages of one
        # interface rather than two differently-proportioned popups.
        card_name = f"toy_factory_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        if card is not None:
            cr = card.get_rect(center=(GAME_W // 2, GAME_H // 2))
            surface.blit(card, cr)
        # Just the card, centered -- no extra text/descriptions. No "press
        # any key" prompt either -- the patient never starts the game
        # themselves, only the therapist's own START control does.

    def _draw_results(self, surface):
        T = get_theme()
        # Just the card, centered -- no extra text/descriptions (Wrong Box
        # / Missed are no longer shown here; the HUD's own live counter
        # during gameplay already covers progress).
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="toy_factory", duration_sec=self.game_over_duration,
            score_text=self._session_count_text(), load_fit=_load_image_fit)

        f_btn = pygame.font.SysFont("monospace", 28, bold=True)
        mp = pygame.mouse.get_pos()
        bw, bh = 220, 52
        by = bottom_y + 20

        again_r = pygame.Rect(GAME_W // 2 - bw - 16, by, bw, bh)
        exit_r  = pygame.Rect(GAME_W // 2 + 16,       by, bw, bh)
        self._results_again_rect = again_r
        self._results_exit_rect  = exit_r

        ag_col = (55, 170, 100) if again_r.collidepoint(mp) else (40, 140, 80)
        ex_col = (75, 110, 190) if exit_r.collidepoint(mp)  else (55,  85, 160)
        pygame.draw.rect(surface, ag_col, again_r, border_radius=10)
        pygame.draw.rect(surface, ex_col, exit_r,  border_radius=10)
        surface.blit(f_btn.render("Play Again", True, T["WHITE"]), f_btn.render("Play Again", True, T["WHITE"]).get_rect(center=again_r.center))
        surface.blit(f_btn.render("Exit",       True, T["WHITE"]), f_btn.render("Exit",       True, T["WHITE"]).get_rect(center=exit_r.center))

    def _apply_vol(self):
        try:
            pygame.mixer.music.set_volume(self.pause_vol)
            from db.database import set_volume
            set_volume(self.pause_vol)
        except Exception:
            pass
