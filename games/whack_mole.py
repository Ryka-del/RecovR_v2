"""
Whack-a-Mole — Finger Flexion game (1920x1080)

Mechanic:
  - 5 mole holes are always visible, compactly arranged on the forest
    background's dirt patch, one per finger (Thumb/Index/Middle/Ring/Pinky
    -- see HOLE_CONFIG). ONLY ONE mole is active at a time, regardless of
    difficulty -- it appears in a randomly chosen hole (never the same hole
    twice in a row) and must be hit with that hole's own finger within a
    flat 3-second hit window (MOLE_HIT_WINDOW_SEC) before it retreats.
  - Every mole that appears is a valid target -- there is no red/green
    Go/No-Go distinction.
  - A mole animates rising out of its hole (head first, then upper body,
    bottom concealed behind the hole's near edge) and sinking back down the
    same way when hit or missed -- see Mole.reveal_progress()/_draw_mole().
    This is done entirely by clipping the existing mole art against a fixed
    ground line, never by faking it with a fade/scale/teleport.
  - A successful hit swings the (enlarged) hammer from its resting corner
    over to the mole's hole, rotating head-first into it, before returning
    -- see _trigger_hammer()/_update_hammer()/_draw_hammer(). Purely visual;
    it never gates or delays sensor processing (scoring/feedback/sound fire
    immediately on the input, same as always). The MOLE's own reaction is
    synced to the swing, though: a correctly-hit mole stays in its normal
    pose through the whole swing (Mole.phase "hit_wait") and only flips to
    its dizzy sprite at the instant the hammer actually lands (see
    Mole.apply_impact(), called from _update_hammer()'s swing->hold
    transition) -- never the moment the input itself is registered.
  - All 5 Flex Sensors (sensors.input_handler's state["finger_flex"]) are
    read every frame regardless of which single hole is currently active,
    each with its own independent calibrated threshold and press/release
    (hysteresis) state machine -- see _update_fingers(). A finger already
    held above its threshold when a mole appears cannot auto-hit it; it
    must release and re-flex.
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
                    game_bgm_path, play_success, play_error, play_completion, play_click)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.hud import draw_target_pill, TARGET_POS
from games.round_complete import draw_round_complete_overlay

# ── difficulty-scaled parameters ────────────────────────────────────────────
GOAL          = {"Easy": 15,  "Medium": 15,  "Hard": 15}    # Target Mode: moles to hit
DURATION      = {"Easy": 45,  "Medium": 40,  "Hard": 35}    # Timed Mode: session length (s)
SPAWN_GAP     = {"Easy": 0.5, "Medium": 0.35, "Hard": 0.25}  # pause between moles
DEFAULT_THRESHOLD = {"Easy": 0.35, "Medium": 0.45, "Hard": 0.55}  # used if calibration is absent
RELEASE_MARGIN = 0.65   # release threshold = press threshold * this (must release below it to re-arm)

# Every mole stays up for exactly this long regardless of difficulty -- the
# "3-second timer" is the mole's available hit window, not the session
# length (see DURATION/GOAL above for that).
MOLE_HIT_WINDOW_SEC = 3.0
RISE_TIME_SEC   = 0.15   # spawn animation: fully hidden -> fully risen
SINK_TIME_SEC   = 0.18   # disappearance animation: fully risen -> fully hidden
HIT_FLASH_SEC   = 0.45   # dizzy sprite hold time after a successful hit, before sinking
HIT_WAIT_SAFETY_SEC = 1.0   # Mole.apply_impact() safety-net timeout -- see Mole.update()

# Hole index -> (finger name, x-fraction of the screen, row). Compactly
# clustered on the background art's dirt patch -- front row sits lower/
# bigger (closer to camera), back row higher/smaller (further away). Only
# this table needs editing if the real glove's physical finger layout ever
# differs from the proposed one -- nothing else in the file hardcodes which
# finger goes with which hole.
HOLE_CONFIG = [
    ("Thumb",  0.28, "front"),
    ("Index",  0.39, "back"),
    ("Middle", 0.50, "front"),
    ("Ring",   0.61, "back"),
    ("Pinky",  0.72, "front"),
]

FRONT_Y_FRAC, BACK_Y_FRAC = 0.824, 0.690
FRONT_RADIUS, BACK_RADIUS = 100, 78

_MOLE_SPRITES = ["mole1", "mole2", "mole3", "rare_mole", "epic_mole"]
_MOLE_WEIGHTS = [34, 34, 24, 5, 3]   # rare/epic are cosmetic variety only, no bonus scoring

# Hammer -- a TRUE pivot swing: a fixed invisible "grip" point (HAMMER_PIVOT
# FRAC, measured off the art -- the handle's own butt end) stays anchored at
# HAMMER_PIVOT_SCREEN the whole time, and the whole sprite only ever rotates
# + uniformly scales (never translates independently, never stretches)
# around it, exactly like games/toy_factory.py's arm. This is what makes it
# read as swinging an arc, not sliding. HAMMER_HEAD_FRAC is the drum/head's
# own center -- the broad, flat-ish striking mass (as opposed to the thin
# handle) -- which is what gets aimed at the mole, so the head (never an
# edge or the handle) is what visually contacts it. Both fractions are
# measured directly off the cropped art (see the hammer_whack_a_mole.png
# grid-overlay reference used to find them).
HAMMER_PIVOT_FRAC  = (0.2034, 0.9029)   # handle grip, i.e. where a hand holds it
HAMMER_HEAD_FRAC   = (0.5747, 0.2580)   # drum/head centre
HAMMER_REST_PIVOT_SCREEN_FRAC = (1.02, 1.02)  # the fixed grip point while idle -- just past the
                                               # bottom-right corner, matching the reference
                                               # "resting" photo exactly
HAMMER_REST_TARGET_FRAC  = (0.938, 0.768)  # idle pose aims the head here -- a modest, mostly
                                            # on-screen lean near the corner (reference photo 1),
                                            # not cropped/oversized
# The SWING uses a different (below-screen-centre) pivot than the rest pose
# -- the reference "swing" photo only shows one hole (Ring) being hit, and
# a literal corner pivot makes the 5 holes' reach distances vary enormously
# (Thumb is ~2.3x farther from the corner than Pinky is), which either
# strands far holes short of the clamp or balloons the hammer to an absurd
# size reaching them. This below-centre pivot keeps every hole's reach
# comfortably clustered so the swing always actually connects, at a
# consistently dramatic (never absurd) size -- see HAMMER_SCALE_CLAMP. The
# hammer's PIVOT POINT ITSELF is interpolated between the two (alongside
# rotation/scale) during swing/return, so the handoff from the corner-
# anchored idle lean into the swing is one continuous motion, never a pop.
HAMMER_SWING_PIVOT_SCREEN_FRAC = (0.50, 1.148)
HAMMER_BASE_LOAD_FRAC    = 0.50            # base texture height, as a fraction of GAME_H
HAMMER_SCALE_CLAMP = (0.6, 1.6)
HAMMER_SWING_SEC   = 0.14
HAMMER_HOLD_SEC    = 0.16
HAMMER_RETURN_SEC  = 0.22

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


def _ease(t):
    """Smoothstep -- cheap, dependency-free easing for the hammer swing."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _rotate_scale_anchored(image, angle, scale, local_point, target_pos):
    """Rotate `image` by `angle` degrees and uniformly scale it by `scale`
    (never a non-uniform stretch), returning (surface, rect) such that
    `local_point` -- given in the image's own unrotated, unscaled pixel
    coordinates -- lands exactly at `target_pos` on screen. The hammer's
    pivot/swing system anchors on its GRIP point this way (see
    _draw_hammer) -- identical technique to games/toy_factory.py's arm."""
    w, h = image.get_size()
    offset = pygame.math.Vector2((w / 2 - local_point[0]) * scale,
                                  (h / 2 - local_point[1]) * scale)
    rotated_offset = offset.rotate(-angle)
    if scale != 1.0:
        image = pygame.transform.smoothscale(
            image, (max(1, int(w * scale)), max(1, int(h * scale))))
    rotated = pygame.transform.rotate(image, angle)
    rect = rotated.get_rect(center=(target_pos[0] + rotated_offset.x,
                                     target_pos[1] + rotated_offset.y))
    return rotated, rect


class Mole:
    """One active mole: which hole it's in, and its own rise/active/
    hit-wait/hit-flash/retreat phase timeline (see module docstring). Every
    mole is a valid target -- there is no red/green distinction any more."""

    def __init__(self, hole_idx, sprite_key):
        self.hole_idx   = hole_idx
        self.sprite_key = sprite_key
        self.phase      = "rising"   # rising -> active -> hit_wait -> hit_flash -> retreating -> done
        self.timer      = 0.0
        self.hit        = False

    def is_hittable(self):
        return self.phase == "active"

    @property
    def done(self):
        return self.phase == "done"

    def register_hit(self):
        """Called by the game once a correct, newly-armed finger press is
        confirmed against this mole. No-ops (returns False) if the mole
        isn't currently hittable -- callers don't need to check phase
        themselves. Scoring/feedback/sound fire immediately on this, same
        as ever -- but the mole itself stays in its normal (non-dizzy) pose,
        "hit_wait"ing for apply_impact() once the swinging hammer actually
        lands, exactly like the reference reaction footage (mole stays
        put/happy through the whole swing, only flinches on contact)."""
        if self.phase != "active":
            return False
        self.phase = "hit_wait"
        self.timer = 0.0
        return True

    def apply_impact(self):
        """Called by the game the instant the hammer's swing animation
        actually reaches this mole (see _update_hammer's swing->hold
        transition) -- this, not register_hit(), is what flips the sprite
        to its dizzy version and starts the HIT_FLASH_SEC hold."""
        if self.phase != "hit_wait":
            return
        self.hit   = True
        self.phase = "hit_flash"
        self.timer = 0.0

    def update(self, dt, hit_window):
        """Advance this mole's phase timeline. Returns "missed" on the
        single frame its hit window runs out unhit, else None -- the game
        uses that to count a miss exactly once."""
        event = None
        self.timer += dt
        if self.phase == "rising":
            if self.timer >= RISE_TIME_SEC:
                self.phase, self.timer = "active", 0.0
        elif self.phase == "active":
            if self.timer >= hit_window:
                event = "missed"
                self.phase, self.timer = "retreating", 0.0
        elif self.phase == "hit_wait":
            # Normally ended by apply_impact() within one short hammer
            # swing (HAMMER_SWING_SEC) -- this is only a safety net so a
            # mole can never get stuck in its "waiting to flinch" pose if
            # that signal is somehow missed.
            if self.timer >= HIT_WAIT_SAFETY_SEC:
                self.apply_impact()
        elif self.phase == "hit_flash":
            if self.timer >= HIT_FLASH_SEC:
                self.phase, self.timer = "retreating", 0.0
        elif self.phase == "retreating":
            if self.timer >= SINK_TIME_SEC:
                self.phase = "done"
        return event

    def reveal_progress(self):
        """0 = fully hidden in the hole, 1 = fully risen at rest."""
        if self.phase == "rising":
            return max(0.0, min(1.0, self.timer / RISE_TIME_SEC))
        if self.phase in ("active", "hit_wait", "hit_flash"):
            return 1.0
        if self.phase == "retreating":
            return max(0.0, 1.0 - self.timer / SINK_TIME_SEC)
        return 0.0

    def sprite_name(self):
        return f"{self.sprite_key}_dizzy_whack_a_mole.png" if self.hit \
            else f"{self.sprite_key}_whack_a_mole.png"


class WhackMoleGame(SessionModeMixin, FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "finger"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="wam_goal")
        self.spawn_gap       = SPAWN_GAP[self.difficulty]
        self.mole_hit_window = MOLE_HIT_WINDOW_SEC

        # Per-finger calibrated press threshold (0-1), from the 5 independent
        # "<Finger> Flexion" calibration passes (see MULTI_SENSOR_CALIBRATION
        # in scenes/therapist_dashboard.py / SENSOR_CFG in
        # scenes/calibration_window.py) -- falls back to a difficulty default
        # for any finger never actually calibrated (e.g. calibration skipped).
        sensors_cal = self.cal.get("sensors", {})
        default_thr = DEFAULT_THRESHOLD[self.difficulty]
        self.press_threshold = []
        for name in FINGER_NAMES:
            entry = sensors_cal.get(f"{name} Flexion")
            thr = entry.get("threshold") if entry else None
            self.press_threshold.append(thr if thr and thr > 0 else default_thr)
        self.release_threshold = [t * RELEASE_MARGIN for t in self.press_threshold]

        W, H = GAME_W, GAME_H
        front_y = int(H * FRONT_Y_FRAC)
        back_y  = int(H * BACK_Y_FRAC)
        self._hole_pos    = []
        self._hole_finger = []
        for name, x_frac, row in HOLE_CONFIG:
            x = int(W * x_frac)
            y = front_y if row == "front" else back_y
            r = FRONT_RADIUS if row == "front" else BACK_RADIUS
            self._hole_pos.append((x, y, r))
            self._hole_finger.append(name)

        self._bg_img = _load_image_cover("bg_whack_a_mole.png", W, H)
        self._hole_img = {}
        for _x, _y, r in self._hole_pos:
            d = r * 2
            if d not in self._hole_img:
                self._hole_img[d] = _load_image_fit("hole_whack_a_mole.png", d, d)

        hammer_load_h = int(HAMMER_BASE_LOAD_FRAC * H)
        self._hammer_img = _load_image_fit("hammer_whack_a_mole.png", W, hammer_load_h)
        if self._hammer_img is not None:
            hw, hh = self._hammer_img.get_size()
            self._hammer_pivot_local = (HAMMER_PIVOT_FRAC[0] * hw, HAMMER_PIVOT_FRAC[1] * hh)
            head_local = (HAMMER_HEAD_FRAC[0] * hw, HAMMER_HEAD_FRAC[1] * hh)
            dx = head_local[0] - self._hammer_pivot_local[0]
            dy = head_local[1] - self._hammer_pivot_local[1]
            self._hammer_natural_reach = math.hypot(dx, dy) or 1.0
            self._hammer_natural_angle = math.degrees(math.atan2(dy, dx))
        else:
            self._hammer_pivot_local = (0.0, 0.0)
            self._hammer_natural_reach = 1.0
            self._hammer_natural_angle = -60.0
        self._hammer_rest_pivot_screen = (W * HAMMER_REST_PIVOT_SCREEN_FRAC[0],
                                          H * HAMMER_REST_PIVOT_SCREEN_FRAC[1])
        self._hammer_swing_pivot_screen = (W * HAMMER_SWING_PIVOT_SCREEN_FRAC[0],
                                           H * HAMMER_SWING_PIVOT_SCREEN_FRAC[1])
        # The idle/rest pose is fixed and computed directly (bypassing
        # _hammer_aim's clamp, which exists only to keep SWING targets --
        # the 5 holes -- from rendering absurdly large/small) so the
        # hammer leans in the lower-right corner at its own natural size,
        # matching the reference "resting" photo, instead of being forced
        # into whatever range the swing clamp allows.
        rest_target = (W * HAMMER_REST_TARGET_FRAC[0], H * HAMMER_REST_TARGET_FRAC[1])
        rdx = rest_target[0] - self._hammer_rest_pivot_screen[0]
        rdy = rest_target[1] - self._hammer_rest_pivot_screen[1]
        rest_angle = math.degrees(math.atan2(rdy, rdx))
        self._hammer_rest_rot   = rest_angle - self._hammer_natural_angle
        self._hammer_rest_scale = (math.hypot(rdx, rdy) or 1.0) / self._hammer_natural_reach

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_target = pygame.font.SysFont("monospace", 54, bold=True)
        self._font_obj = pygame.font.SysFont("monospace", 22, bold=True)
        self._font_fb  = pygame.font.SysFont("monospace", 48, bold=True)

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

        self.score  = 0
        self.reps   = 0    # successful hits
        self.missed = 0    # moles that retreated unhit
        self._session_reset()
        self.start_time = pygame.time.get_ticks()

        self._mole = None
        self._last_hole_idx  = None
        self.required_finger = None   # therapist-monitoring: which finger the active mole needs
        self._spawn_timer = 0.0
        self.feedback = None

        self._hammer_phase = "idle"
        self._hammer_timer = 0.0
        self._hammer_from_rot, self._hammer_from_scale = self._hammer_rest_rot, self._hammer_rest_scale
        self._hammer_from_pivot = self._hammer_rest_pivot_screen
        self._hammer_to_rot, self._hammer_to_scale     = self._hammer_rest_rot, self._hammer_rest_scale

        # Per-finger press/release (hysteresis) state. "armed" starts True
        # only if the finger is NOT already held above its own release
        # threshold right now -- a finger already flexed before the session
        # begins (or before it's next needed) must release once before it
        # can register a press, exactly like mid-session.
        state = input_handler.get_state()
        flex = state.get("finger_flex", [0.0] * 5)
        self._armed = [flex[i] < self.release_threshold[i] for i in range(5)]
        self._state = {"finger_flex": list(flex), "fingers": [False] * 5}

    def _normalize_finger(self, index, raw):
        """Used by recovr/patient_app/games/generic_adapter.py's therapist
        telemetry -- "calibrated" reading is whether THIS finger is
        currently above ITS OWN calibrated threshold, the same value the
        press/release state machine itself acts on."""
        return 1.0 if raw >= self.press_threshold[index] else 0.0

    # ── input: 5 independent finger channels, always live ──────────────────

    def _update_fingers(self, dt):
        flex = self._state.get("finger_flex", [0.0] * 5)
        for i in range(5):
            f = flex[i]
            if self._armed[i]:
                if f >= self.press_threshold[i]:
                    self._armed[i] = False
                    self._on_finger_press(i)
            else:
                if f <= self.release_threshold[i]:
                    self._armed[i] = True

    def _on_finger_press(self, finger_index):
        mole = self._mole
        if mole is None or not mole.is_hittable():
            return
        if self._hole_finger[mole.hole_idx] != FINGER_NAMES[finger_index]:
            return   # wrong finger for the active mole -- no effect
        if mole.register_hit():
            self.score += 1
            self.reps  += 1
            self.feedback = ("HIT!", (0, 220, 140), 0.6)
            play_success()
            self._trigger_hammer(mole.hole_idx)
            if self._session_target_reached():
                self._end_game()

    # ── hammer swing: a true pivot swing, purely cosmetic, never gates
    # input/sensor handling ──────────────────────────────────────────────

    def _hammer_aim(self, target):
        """(rotation_degrees, scale) that, pivoting on self._hammer_swing_
        pivot_screen (fixed), points the hammer's own HEAD centre exactly
        at `target` -- the single source of truth every strike uses, so
        there is only one aiming formula in the file. (The idle/rest pose
        uses its own separate corner pivot -- see on_enter -- since the
        two poses are governed by different reference photos.)"""
        dx = target[0] - self._hammer_swing_pivot_screen[0]
        dy = target[1] - self._hammer_swing_pivot_screen[1]
        reach = math.hypot(dx, dy) or 1.0
        angle = math.degrees(math.atan2(dy, dx))
        scale = reach / self._hammer_natural_reach
        scale = max(HAMMER_SCALE_CLAMP[0], min(HAMMER_SCALE_CLAMP[1], scale))
        rot = angle - self._hammer_natural_angle
        return rot, scale

    def _hammer_current(self):
        """(rotation, scale, pivot_screen) for whatever the hammer is doing
        RIGHT NOW -- used both to draw it and, on a new hit, as the swing's
        own "from" so retriggering mid-animation never jumps/snaps. The
        PIVOT itself is interpolated too (idle leans from the corner pivot;
        swinging/holding/returning pivots from the swing pivot -- see the
        module docstring), in lockstep with rotation/scale, so switching
        between the two is one continuous motion, never a pop."""
        if self._hammer_phase == "swing":
            t = _ease(self._hammer_timer / HAMMER_SWING_SEC)
        elif self._hammer_phase == "return":
            t = _ease(self._hammer_timer / HAMMER_RETURN_SEC)
        else:
            t = 1.0
        if self._hammer_phase == "swing":
            r0, s0, p0 = self._hammer_from_rot, self._hammer_from_scale, self._hammer_from_pivot
            r1, s1, p1 = self._hammer_to_rot, self._hammer_to_scale, self._hammer_swing_pivot_screen
        elif self._hammer_phase == "return":
            r0, s0, p0 = self._hammer_to_rot, self._hammer_to_scale, self._hammer_swing_pivot_screen
            r1, s1, p1 = self._hammer_rest_rot, self._hammer_rest_scale, self._hammer_rest_pivot_screen
        elif self._hammer_phase == "hold":
            return self._hammer_to_rot, self._hammer_to_scale, self._hammer_swing_pivot_screen
        else:
            return self._hammer_rest_rot, self._hammer_rest_scale, self._hammer_rest_pivot_screen
        return (r0 + (r1 - r0) * t, s0 + (s1 - s0) * t,
                (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))

    def _trigger_hammer(self, hole_idx):
        x, y, r = self._hole_pos[hole_idx]
        cur_rot, cur_scale, cur_pivot = self._hammer_current()
        self._hammer_from_rot, self._hammer_from_scale, self._hammer_from_pivot = cur_rot, cur_scale, cur_pivot
        # Aimed a bit above the hole, not dead-centre on it -- at this
        # hammer's (large, at-impact) scale, centring on the hole would
        # bury the mole entirely under the head. The reference "swing"
        # photo shows the dizzy mole still clearly visible beside the
        # hammer at the moment of impact, not hidden behind it.
        self._hammer_to_rot, self._hammer_to_scale = self._hammer_aim((x, y - int(r * 0.7)))
        self._hammer_phase = "swing"
        self._hammer_timer = 0.0

    def _update_hammer(self, dt):
        if self._hammer_phase == "idle":
            return
        self._hammer_timer += dt
        if self._hammer_phase == "swing" and self._hammer_timer >= HAMMER_SWING_SEC:
            self._hammer_phase, self._hammer_timer = "hold", 0.0
            # The instant the swing actually lands -- this, not the input
            # press back in _on_finger_press(), is what flips the mole to
            # its dizzy sprite (see Mole.apply_impact()).
            if self._mole is not None and self._mole.phase == "hit_wait":
                self._mole.apply_impact()
        elif self._hammer_phase == "hold" and self._hammer_timer >= HAMMER_HOLD_SEC:
            self._hammer_phase, self._hammer_timer = "return", 0.0
        elif self._hammer_phase == "return" and self._hammer_timer >= HAMMER_RETURN_SEC:
            self._hammer_phase, self._hammer_timer = "idle", 0.0

    # ── lifecycle ────────────────────────────────────────────────────────

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Whack-a-Mole"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Whack-a-Mole"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Whack-a-Mole"))),
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

        live = input_handler.get_state()
        flex = live.get("finger_flex", [0.0] * 5)
        self._state = {"finger_flex": list(flex),
                        "fingers": [f > 0.1 for f in flex]}   # fatigue-activity proxy only
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        # Finger press/release state always runs, independent of mole state
        # or session pause-for-countdown (the dual-monitor host freezes
        # update() entirely during the 3-2-1 countdown, so this never fires
        # mid-countdown -- see GameRunner.counting_down).
        self._update_fingers(dt)
        self._update_hammer(dt)

        if self._session_tick(dt):
            self._end_game()
            return

        if self._mole is not None:
            event = self._mole.update(dt, self.mole_hit_window)
            if event == "missed":
                self.missed += 1
                self.feedback = ("Missed!", (255, 170, 60), 0.6)
            if self._mole.done:
                self._mole = None
                self.required_finger = None
                self._spawn_timer = 0.0
        else:
            self._spawn_timer += dt
            if self._spawn_timer >= self.spawn_gap:
                self._spawn_mole()

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

    def _spawn_mole(self):
        choices = [i for i in range(5) if i != self._last_hole_idx]
        hole_idx = random.choice(choices)
        self._last_hole_idx = hole_idx
        sprite_key = random.choices(_MOLE_SPRITES, weights=_MOLE_WEIGHTS, k=1)[0]
        self._mole = Mole(hole_idx, sprite_key)
        self.required_finger = self._hole_finger[hole_idx]

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
                game         = "Whack-a-Mole",
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

        for i, (x, y, r) in enumerate(self._hole_pos):
            mole = self._mole if (self._mole is not None and self._mole.hole_idx == i
                                   and not self._mole.done) else None
            d = r * 2
            hole_img = self._hole_img.get(d)
            if hole_img is not None:
                surface.blit(hole_img, hole_img.get_rect(center=(x, y)))
            else:
                pygame.draw.ellipse(surface, (60, 40, 20), (x - r, y - int(r*0.5), r*2, int(r*0.9)))

            if mole is not None:
                self._draw_mole(surface, mole, x, y, r)

        self._draw_hammer(surface)

        draw_game_header(surface, "Whack-a-Mole", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        draw_target_pill(surface, self._session_progress_text("moles hit"),
                          TARGET_POS, T["ACCENT"], self._font_target)

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

    def _draw_mole(self, surface, mole, x, y, r):
        """Clip-reveal animation: the sprite's bottom edge is pinned to a
        fixed ground line (its normal resting midbottom anchor) and only
        the top `reveal_progress()` fraction of it is ever blitted, so a
        rising mole shows its head first with the rest concealed below the
        hole's near edge, and a retreating one sinks back the same way --
        never a fade/scale/teleport."""
        name = mole.sprite_name()
        box = int(r * 1.7)
        img = _load_image_fit(name, box, box)
        progress = mole.reveal_progress()
        if progress <= 0.0:
            return
        if img is None:
            col = (150, 150, 150) if mole.hit else (120, 80, 50)
            pygame.draw.circle(surface, col, (x, y - int(r*0.1)), int(r * (0.1 + 0.5 * progress)))
            return
        rest_rect = img.get_rect(midbottom=(x, y + int(r * 0.3)))
        ground_y  = rest_rect.bottom
        full_h    = rest_rect.height
        shifted_top = rest_rect.top + int(full_h * (1 - progress))
        visible_h = max(0, min(full_h, ground_y - shifted_top))
        if visible_h <= 0:
            return
        sub = img.subsurface((0, 0, rest_rect.width, visible_h))
        surface.blit(sub, (rest_rect.left, shifted_top))

    def _draw_hammer(self, surface):
        img = self._hammer_img
        if img is None:
            return
        rot, scale, pivot = self._hammer_current()
        rotated, rect = _rotate_scale_anchored(
            img, -rot, scale, self._hammer_pivot_local, pivot)
        surface.blit(rotated, rect)

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
        card_name = f"whack_a_mole_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
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
        # Just the card, centered -- no extra text/descriptions (Moles
        # Missed etc. are no longer shown here; the HUD's own live counter
        # during gameplay already covers progress).
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="whack_a_mole", duration_sec=self.game_over_duration,
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
