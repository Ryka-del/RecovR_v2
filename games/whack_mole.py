"""
Whack-a-Mole — Finger Flexion game (1920x1080)

Mechanic:
  - 5 mole holes are always visible, compactly arranged on the forest
    background's dirt patch, one per finger (Thumb/Index/Middle/Ring/Pinky
    -- see HOLE_CONFIG). Up to `self.simultaneous` moles may be active at
    once (1 at Easy/Medium, 2 at Hard -- see SIMULTANEOUS) -- each appears
    in its own randomly chosen, currently-unoccupied hole (never the same
    hole as the one most recently vacated) and must be hit with that hole's
    own finger within `self.mole_hit_window` seconds (MOLE_DURATION, scales
    2.0-3.0s by difficulty) before it retreats.
  - Every mole that appears is a valid target -- there is no red/green
    Go/No-Go distinction. Each mole is one of 3 point tiers, rolled on
    spawn (see _MOLE_SPRITES/_MOLE_WEIGHTS/_MOLE_POINTS): Common (80%,
    1 point, sprites mole1/mole2/mole3), Rare (15%, 3 points, rare_mole),
    Epic (5%, 5 points, epic_mole).
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
from games.hud import (draw_target_pill, TARGET_POS, draw_tutorial_badge, draw_feedback_banner,
                        draw_controls_panel, controls_panel_rect)
from games.tutorial_hints import TutorialHints, TutorialStep
from games.round_complete import draw_round_complete_overlay
from i18n import tr

# ── difficulty-scaled parameters ────────────────────────────────────────────
GOAL          = {"Easy": 50,  "Medium": 75,  "Hard": 100}   # Target Mode: points (see _MOLE_POINTS)
DURATION      = {"Easy": 300, "Medium": 420, "Hard": 600}   # Timed Mode: session length (s)
SPAWN_GAP     = {"Easy": 0.5, "Medium": 0.35, "Hard": 0.25}  # pause between moles
DEFAULT_THRESHOLD = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}  # used if calibration is absent
RELEASE_MARGIN = 0.65   # release threshold = press threshold * this (must release below it to re-arm)

# A mole's available hit window -- how long it stays up before retreating
# unhit (the "Mole Appearance Duration" Advanced Settings parameter,
# "wm_mole_duration" in GAME_PARAM_SCHEMA). Used to be a flat 3.0s
# regardless of difficulty; now scales within the spec's 2-3s band.
MOLE_DURATION = {"Easy": 3.0, "Medium": 2.5, "Hard": 2.0}
# How many moles may be up at the same time ("Simultaneous Mole Count",
# "wm_simultaneous"). Easy/Medium stay at the original single-mole feel;
# Hard introduces a second concurrent mole.
SIMULTANEOUS = {"Easy": 1, "Medium": 1, "Hard": 2}
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
# 3 real point tiers now: the 3 "common" skins are cosmetic variety WITHIN
# that 80% bucket (chosen roughly evenly among themselves, same relative
# weighting as before -- 34/34/24 scaled down to sum to 80), rare_mole and
# epic_mole are their own tiers with real bonus scoring (see _MOLE_POINTS).
_MOLE_WEIGHTS = [30, 30, 20, 15, 5]   # sums to 100: 80% common, 15% rare, 5% epic
_MOLE_POINTS  = {"mole1": 1, "mole2": 1, "mole3": 1, "rare_mole": 3, "epic_mole": 5}

# Hammer -- a TRUE pivot swing: an invisible "grip" point (HAMMER_PIVOT_FRAC,
# measured off the art -- the handle's own butt end) is what the whole
# sprite rotates around; the sprite itself only ever rotates (never
# stretches) and NEVER changes size -- the swing is pure rotation + pivot
# translation, exactly the same scale the whole time. HAMMER_HEAD_FRAC is
# the far END-CAP face (the round striking tip) -- the point that must
# actually land on the mole. Both fractions are measured directly off the
# cropped art (see the hammer_whack_a_mole.png grid-overlay reference used
# to find them).
HAMMER_PIVOT_FRAC  = (0.2034, 0.9029)   # handle grip, i.e. where a hand holds it
# Drum/head centre -- the actual far END-CAP face (the round striking tip,
# with its own small star), NOT the big star decal on the drum's SIDE. The
# previous (0.5747, 0.2580) measurement landed on that side decal instead,
# so the swing was aiming the wrong point of the sprite at each mole --
# re-measured directly off the end-cap circle in hammer_whack_a_mole.png
# (grid-overlay check: the cap spans roughly x 0.70-0.80, y 0.19-0.55).
HAMMER_HEAD_FRAC   = (0.75, 0.37)
HAMMER_REST_PIVOT_SCREEN_FRAC = (1.02, 1.02)  # the fixed grip point while idle -- just past the
                                               # bottom-right corner, matching the reference
                                               # "resting" photo exactly
HAMMER_REST_TARGET_FRAC  = (0.938, 0.768)  # idle pose aims the head here -- a modest, mostly
                                            # on-screen lean near the corner (reference photo 1),
                                            # not cropped/oversized. This also fixes the hammer's
                                            # one constant on-screen size (HAMMER_REST scale) used
                                            # for every pose -- idle, wind-up and strike alike.
# How far above the hole CENTRE the actual strike point sits, in units of
# that hole's own radius -- approximates the TOP of a fully risen mole's
# head (see _draw_mole: sprite anchored at y + 0.3*r, box height ~1.7*r),
# so HAMMER_HEAD_FRAC's point lands on the mole's HEAD, not its middle.
HAMMER_STRIKE_HEIGHT_FRAC = 1.1
# Extra FIXED clearance stacked on top of the above (not scaled by the
# hole's own radius, unlike HAMMER_STRIKE_HEIGHT_FRAC) -- the hammer's own
# drawn size never changes regardless of which hole it's hitting, so the
# room it needs above the "top of head" point to stop clear of the mole
# (rather than resting down over its whole face, hiding the dizzy sprite
# the hit is supposed to reveal) is the same number of pixels at every
# hole, front row or back. Empirically set by rendering the strike pose
# against a real mole on both rows and checking the dizzy face stays
# fully visible underneath.
HAMMER_STRIKE_CLEARANCE_PX = 220
HAMMER_BASE_LOAD_FRAC    = 0.50            # base texture height, as a fraction of GAME_H
# Per the reference swing description: on a hit, the hammer winds up from
# its idle lean (tail lower-right/head upper-left) through vertical (head
# straight up) and on, past vertical by the same angle it started short of
# it, into a mirrored cocked-back lean (head upper-right/tail lower-left)
# -- see on_enter's _hammer_cocked_* -- while simultaneously translating
# from its idle corner position to directly above the target mole. From
# there it swings straight down (pivot now fixed) so the head lands exactly
# on the mole's head. Returning reverses the same rotation+translation back
# to idle. No phase ever changes scale (HAMMER_REST scale is used
# throughout) -- only position and orientation move.
HAMMER_WINDUP_SEC  = 0.22
HAMMER_SWING_SEC   = 0.12
HAMMER_HOLD_SEC    = 0.16
HAMMER_RETURN_SEC  = 0.30
# How much higher than the final strike pivot the hammer is raised to
# during wind-up, before the swing itself drops it back down (while also
# rotating) to actually land the hit -- so the strike reads as swinging
# down from well above the mole, not just rotating in place at the mole's
# own height. Only the PIVOT moves vertically here; HAMMER_REST scale
# still never changes.
HAMMER_RAISE_PX = 260

# Affected-Hand Adaptation: this game's spec default is Right-handed (the
# hammer rests/winds up/strikes from the right, per HAMMER_REST_PIVOT_
# SCREEN_FRAC/HAMMER_REST_TARGET_FRAC above). See on_enter's self.hand_flipped.
DEFAULT_HAND = "right"

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
        themselves. This only starts the hammer's swing -- scoring/
        feedback/sound are deliberately held back until apply_impact()
        actually fires (see _update_hammer's swing->hold transition), not
        this input moment, so the point only registers once the hammer
        visually lands. The mole itself stays in its normal (non-dizzy)
        pose, "hit_wait"ing for that same moment, exactly like the
        reference reaction footage (mole stays put/happy through the whole
        swing, only flinches on contact)."""
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
            # swing (HAMMER_SWING_SEC) -- this is also the real resolution
            # path whenever more than one mole is up at once (see
            # SIMULTANEOUS) and the single shared hammer is busy swinging
            # at a DIFFERENT mole when this one's own hit lands -- not just
            # a rare safety net any more. Returns "impact" so the caller
            # (WhackMoleGame.update) awards the score exactly once, the
            # same way a normal hammer-landed hit does.
            if self.timer >= HIT_WAIT_SAFETY_SEC:
                self.apply_impact()
                event = "impact"
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

        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="wm_goal")
        # Affected-Hand Adaptation: the hammer itself has no inherent
        # handedness in its artwork (no hand/glove is drawn holding it) --
        # only WHERE it rests and WHICH SIDE it swings from needs to mirror
        # to match the patient's affected hand. See the HAMMER_REST_*_FRAC
        # mirroring below and _trigger_hammer()'s reach-sign flip.
        self.hand_flipped = bool(self.affected_hand) and self.affected_hand != DEFAULT_HAND
        # Every session gets a minimum read time on the How-To-Play screen --
        # a curious first finger bend shouldn't be able to skip past the
        # instructions before the patient has had any chance to read them
        # (the patient's own sensor input can dismiss this screen even in
        # the dual-monitor production flow -- see
        # recovr/patient_app/games/generic_adapter.py's handle_event()).
        self._instructions_min_t = 2.5
        self.spawn_gap       = SPAWN_GAP[self.difficulty]
        cal_params = self.cal.get("params", {})
        self.mole_hit_window = cal_params.get("wm_mole_duration", MOLE_DURATION[self.difficulty])
        self.simultaneous    = int(cal_params.get("wm_simultaneous", SIMULTANEOUS[self.difficulty]))

        # Per-finger calibrated press threshold, from the 5 independent
        # "<Finger> Flexion" calibration passes (see MULTI_SENSOR_CALIBRATION
        # in scenes/therapist_dashboard.py / SENSOR_CFG in
        # scenes/calibration_window.py) -- falls back to the Advanced
        # Settings "Required Finger Flexion" override (wm_flex_threshold),
        # then to a hardcoded difficulty default, for any finger never
        # actually calibrated (e.g. calibration skipped).
        #
        # Direction-independent: a flex sensor's raw reading may DECREASE,
        # not increase, when the finger bends (never verified in hardware).
        # A CALIBRATED finger's "how flexed is it right now" is therefore
        # computed as a 0-100% distance from its OWN resting baseline
        # toward its OWN calibrated peak average, using abs() on both sides
        # (see _finger_pct()) instead of comparing raw ADC values directly
        # against a single precomputed raw threshold. An UNCALIBRATED
        # finger has no baseline/peak to compute a percentage from, so it
        # keeps the exact raw-value comparison this always used.
        sensors_cal   = self.cal.get("sensors", {})
        default_thr   = cal_params.get("wm_flex_threshold", DEFAULT_THRESHOLD[self.difficulty])
        threshold_pct = self.cal.get("params", {}).get(
            "threshold_pct", DEFAULT_THRESHOLD[self.difficulty] * 100)
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
                self.release_threshold_pct.append(threshold_pct * RELEASE_MARGIN)
                self.press_threshold.append(0.0)
                self.release_threshold.append(0.0)
            else:
                self._finger_calibrated.append(False)
                self._finger_baseline.append(0.0)
                self._finger_peak.append(0.0)
                self.press_threshold_pct.append(0.0)
                self.release_threshold_pct.append(0.0)
                self.press_threshold.append(default_thr)
                self.release_threshold.append(default_thr * RELEASE_MARGIN)

        W, H = GAME_W, GAME_H
        front_y = int(H * FRONT_Y_FRAC)
        back_y  = int(H * BACK_Y_FRAC)
        self._hole_pos    = []
        self._hole_finger = []
        # Which finger occupies which hole mirrors with self.hand_flipped --
        # HOLE_CONFIG's own x_frac/row positions (screen layout) never move,
        # only which finger name is assigned to each one. This is NOT
        # cosmetic: the physical MUX channel behind each finger ALSO flips
        # with affected hand (see firmware/recovr_controller/
        # recovr_controller.ino's GLOVE_RIGHT_HAND), so without this the
        # channel wired to the LEFTMOST hole would change depending on which
        # hand is affected. Mirroring the finger assignment here keeps the
        # channel<->screen-position mapping constant regardless of hand --
        # e.g. MUX channel C5 always ends up driving the RIGHTMOST hole,
        # never the leftmost, whichever hand the patient is using.
        hole_names = [name for name, _x, _row in HOLE_CONFIG]
        if self.hand_flipped:
            hole_names = list(reversed(hole_names))
        for (_, x_frac, row), name in zip(HOLE_CONFIG, hole_names):
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
        # Affected-Hand Adaptation: mirroring the rest corner and lean
        # target across the screen's vertical centerline (x-fraction ->
        # 1 - x-fraction, y unchanged) is ALL that's needed here -- every
        # angle derived below (_hammer_rest_angle, _hammer_cocked_angle)
        # is computed from these two points via atan2, so mirroring their
        # x automatically mirrors those angles too (atan2(dy, -dx) ==
        # 180 - atan2(dy, dx)), with no separate "re-derive the angle"
        # step needed for either of them.
        rest_pivot_x_frac = (1.0 - HAMMER_REST_PIVOT_SCREEN_FRAC[0]) if self.hand_flipped \
            else HAMMER_REST_PIVOT_SCREEN_FRAC[0]
        rest_target_x_frac = (1.0 - HAMMER_REST_TARGET_FRAC[0]) if self.hand_flipped \
            else HAMMER_REST_TARGET_FRAC[0]
        self._hammer_rest_pivot_screen = (W * rest_pivot_x_frac,
                                          H * HAMMER_REST_PIVOT_SCREEN_FRAC[1])
        # The idle/rest pose is fixed and computed directly, so the hammer
        # leans in the lower-right corner at its own natural size, matching
        # the reference "resting" photo. This also fixes HAMMER_REST scale
        # as the ONE scale used for every pose from here on -- idle,
        # wind-up and strike never change size, only rotate/translate.
        rest_target = (W * rest_target_x_frac, H * HAMMER_REST_TARGET_FRAC[1])
        rdx = rest_target[0] - self._hammer_rest_pivot_screen[0]
        rdy = rest_target[1] - self._hammer_rest_pivot_screen[1]
        self._hammer_rest_angle = math.degrees(math.atan2(rdy, rdx))
        self._hammer_rest_rot   = self._hammer_rest_angle - self._hammer_natural_angle
        self._hammer_rest_scale = (math.hypot(rdx, rdy) or 1.0) / self._hammer_natural_reach
        # Cocked-back wind-up pose: continue winding the SAME way the idle
        # lean already leans -- further left/up, away from vertical, by the
        # same amount idle itself sits short of vertical (straight up ==
        # -90 degrees in atan2 screen terms) -- rather than crossing over to
        # the right of vertical. idle and cocked are symmetric about
        # vertical, both on the left side (idle: 45ish degrees short of it;
        # cocked: 45ish degrees PAST it, continuing left). The pivot used
        # while cocked is per-hole (see _trigger_hammer), so only the angle
        # is precomputed here.
        self._hammer_cocked_angle = 2.0 * self._hammer_rest_angle + 90.0
        self._hammer_cocked_rot   = self._hammer_cocked_angle - self._hammer_natural_angle
        # The swing always ends with the pivot-to-head line pointing due
        # LEFT (180 degrees -- see _trigger_hammer's strike_pivot placement,
        # now to the RIGHT of the target instead of directly above it or to
        # its left). Pointing the pivot-to-head line horizontally (not
        # straight down) is what actually makes the drum's own long axis
        # end up vertical, striking down with its end -- the art's fixed
        # 3/4 camera angle meant a literal straight-down pivot-to-head line
        # left the drum lying on its SIDE at impact, reading as a side hit
        # rather than a top-down one; empirically verified by rendering
        # several candidates and comparing. Specifically LEFT (not right):
        # pointing right put the swing's final approach on the opposite
        # side from the wind-up's own "turn left" lean (see
        # _hammer_cocked_angle above), forcing a long way-round sweep back
        # through the right/up side and reading as a left-to-right hit;
        # pointing left keeps the swing a short, same-direction continuation
        # of that lean, reading right-to-left as intended. 180.0 itself
        # isn't a usable interpolation target from _hammer_cocked_angle's
        # own raw value -- it could be numerically on the "short way round"
        # through either side depending on exactly where cocked lands.
        # Picking whichever +-360 multiple of 180 is CLOSEST to cocked
        # guarantees the swing always sweeps the short way, through the
        # same side the wind-up just leaned into, never flipping through
        # the other.
        # Affected-Hand Adaptation: when flipped, the swing approaches from
        # the opposite side, so the pivot-to-head line must end up pointing
        # due RIGHT (0 degrees, the mirror of 180) instead -- the strike
        # pivot is then placed to the LEFT of the target instead of the
        # right (see the reach-sign flip in _trigger_hammer below). cos/sin
        # of 0 and of 180 are both exactly (+-1, 0), so this stays a pure
        # horizontal placement either way, never an oblique one.
        strike_target_angle = 0.0 if self.hand_flipped else 180.0
        self._hammer_strike_angle = (self._hammer_cocked_angle
                                      + ((strike_target_angle - self._hammer_cocked_angle + 180.0) % 360.0 - 180.0))
        # Fixed pivot-to-head reach at the one constant scale -- used so the
        # per-hole strike pivot can be placed exactly `reach` to the RIGHT
        # of the strike target (LEFT when hand_flipped -- see
        # _trigger_hammer), guaranteeing a pure-rotation swing lands
        # precisely on it without ever resizing the sprite.
        self._hammer_reach = self._hammer_natural_reach * self._hammer_rest_scale

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

        # Tutorial-only: sequential on-screen coaching during actual
        # gameplay (see games/tutorial_hints.py), picking up once the
        # How-To-Play card is dismissed.
        _mid_hole = self._hole_pos[2]
        self._tutorial_hints = TutorialHints([
            TutorialStep(lambda g: tr("whackmole.tut.1", g.language),
                         anchor=lambda g, p=_mid_hole: (p[0], p[1]),
                         done=lambda g, t: t >= 3.0),
            TutorialStep(lambda g: tr("whackmole.tut.2", g.language),
                         anchor=lambda g, p=_mid_hole: (p[0], p[1]),
                         done=lambda g, t: g.score >= 1),
            TutorialStep(lambda g: (tr("whackmole.tut.3.target", g.language, goal=g.goal)
                                     if g.session_mode == "target" else
                                     tr("whackmole.tut.3.timed", g.language))),
        ]) if self.tutorial else None

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

        self._moles = []             # up to self.simultaneous concurrent Mole instances
        self._last_hole_idx  = None
        self.required_finger = None   # therapist-monitoring: which finger(s) are needed right now
        self._spawn_timer = 0.0
        self.feedback = None
        self._hammer_target_hole = None   # which hole the hammer is currently swinging toward

        self._hammer_phase = "idle"
        self._hammer_timer = 0.0
        self._hammer_from_rot    = self._hammer_rest_rot
        self._hammer_from_pivot  = self._hammer_rest_pivot_screen
        self._hammer_strike_rot   = self._hammer_rest_rot
        self._hammer_strike_pivot = self._hammer_rest_pivot_screen
        self._hammer_raised_pivot = self._hammer_rest_pivot_screen

        # Per-finger press/release (hysteresis) state. "armed" starts True
        # only if the finger is NOT already held above its own release
        # threshold right now -- a finger already flexed before the session
        # begins (or before it's next needed) must release once before it
        # can register a press, exactly like mid-session.
        state = input_handler.get_state()
        flex = state.get("finger_flex", [0.0] * 5)
        self._armed = [self._finger_is_released(i, flex[i]) for i in range(5)]
        self._state = {"finger_flex": list(flex), "fingers": [False] * 5}

    def _finger_pct(self, index, raw):
        """Direction-independent 0-100 flexion percentage for a CALIBRATED
        finger -- distance from its own resting baseline toward its own
        calibrated peak average, using abs() on both sides since this
        sensor's raw reading may rise OR fall when the finger bends (never
        verified in hardware). Capped to [0, 100]. Only meaningful when
        self._finger_calibrated[index] is True."""
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
        press/release state machine itself acts on."""
        return 1.0 if self._finger_is_pressed(index, raw) else 0.0

    # ── input: 5 independent finger channels, always live ──────────────────

    def _update_fingers(self, dt):
        flex = self._state.get("finger_flex", [0.0] * 5)
        for i in range(5):
            f = flex[i]
            if self._armed[i]:
                if self._finger_is_pressed(i, f):
                    self._armed[i] = False
                    self._on_finger_press(i)
            else:
                if self._finger_is_released(i, f):
                    self._armed[i] = True

    def _on_finger_press(self, finger_index):
        finger_name = FINGER_NAMES[finger_index]
        for mole in self._moles:
            if not mole.is_hittable():
                continue
            if self._hole_finger[mole.hole_idx] != finger_name:
                continue   # wrong finger for this mole -- no effect
            if mole.register_hit():
                # Just starts the swing -- score/feedback/sound/goal-check
                # all happen on actual impact instead (see _update_hammer /
                # _award_hit), not at this input moment. Holes map 1:1 to
                # fingers and two moles never share a hole (see
                # _spawn_mole's occupied-hole exclusion), so at most one
                # mole can ever match this finger at a time.
                self._trigger_hammer(mole.hole_idx)
            return

    # ── hammer swing: a true pivot swing, purely cosmetic, never gates
    # input/sensor handling ──────────────────────────────────────────────

    def _hammer_current(self):
        """(rotation, scale, pivot_screen) for whatever the hammer is doing
        RIGHT NOW -- used both to draw it and, on a new hit, as the next
        wind-up's own "from" so retriggering mid-animation never jumps/
        snaps. Scale is always HAMMER_REST scale -- it never changes, only
        rotation and pivot (position) move. Phase timeline: idle -> windup
        (rotate idle->cocked while the pivot translates from the idle
        corner up to HAMMER_RAISE_PX above the target, well higher than
        the actual strike point) -> swing (rotate cocked->straight-down
        WHILE the pivot also drops from that raised point down to its
        final strike position, so the hit visibly swings down from above
        rather than just rotating in place) -> hold -> return (reverse
        straight back to idle)."""
        scale = self._hammer_rest_scale
        phase = self._hammer_phase
        if phase == "windup":
            t = _ease(self._hammer_timer / HAMMER_WINDUP_SEC)
            r0, p0 = self._hammer_from_rot, self._hammer_from_pivot
            r1, p1 = self._hammer_cocked_rot, self._hammer_raised_pivot
        elif phase == "swing":
            t = _ease(self._hammer_timer / HAMMER_SWING_SEC)
            r0, p0 = self._hammer_cocked_rot, self._hammer_raised_pivot
            r1, p1 = self._hammer_strike_rot, self._hammer_strike_pivot
        elif phase == "hold":
            return self._hammer_strike_rot, scale, self._hammer_strike_pivot
        elif phase == "return":
            t = _ease(self._hammer_timer / HAMMER_RETURN_SEC)
            r0, p0 = self._hammer_strike_rot, self._hammer_strike_pivot
            r1, p1 = self._hammer_rest_rot, self._hammer_rest_pivot_screen
        else:
            return self._hammer_rest_rot, scale, self._hammer_rest_pivot_screen
        return (r0 + (r1 - r0) * t, scale,
                (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))

    def _trigger_hammer(self, hole_idx):
        x, y, r = self._hole_pos[hole_idx]
        cur_rot, _cur_scale, cur_pivot = self._hammer_current()
        self._hammer_from_rot, self._hammer_from_pivot = cur_rot, cur_pivot
        # Strike target: comfortably ABOVE the top of the mole's head (see
        # HAMMER_STRIKE_HEIGHT_FRAC for the head-top term, plus the fixed
        # HAMMER_STRIKE_CLEARANCE_PX so the hammer's own fixed-size drum
        # stops clear of the mole's face instead of resting down over it),
        # not the hole's centre. The strike pivot sits exactly
        # self._hammer_reach to the RIGHT of that point (not straight
        # above it, and not to its left -- see _hammer_strike_angle in
        # on_enter for why), so the swing's pure rotation (no scale
        # change) always lands the head (HAMMER_HEAD_FRAC) precisely on
        # it, with the drum's own long axis ending up vertical -- striking
        # down with its end, approaching right-to-left, not lying on its
        # side and not swinging left-to-right.
        target = (x, y - r * HAMMER_STRIKE_HEIGHT_FRAC - HAMMER_STRIKE_CLEARANCE_PX)
        # Affected-Hand Adaptation: the pivot sits on the LEFT of the
        # target instead of the right when flipped, pairing with
        # _hammer_strike_angle's own 0-degree (mirror of 180) target above
        # -- the hole positions themselves (x, y) never move, only which
        # side the hammer swings in from.
        reach_signed = -self._hammer_reach if self.hand_flipped else self._hammer_reach
        self._hammer_strike_pivot = (target[0] + reach_signed, target[1])
        # Where the wind-up actually ends and the swing's own downward
        # drop begins -- directly above the strike pivot, not level with
        # it, so the swing has real vertical distance to fall through
        # while it rotates, rather than rotating in place at the mole's
        # own height. See HAMMER_RAISE_PX.
        self._hammer_raised_pivot = (self._hammer_strike_pivot[0],
                                      self._hammer_strike_pivot[1] - HAMMER_RAISE_PX)
        # self._hammer_strike_angle (precomputed in on_enter) is whichever
        # +-360 representation of that final angle is numerically closest
        # to the cocked angle, so the swing always sweeps the short way
        # through the same side the wind-up just leaned into.
        self._hammer_strike_rot = self._hammer_strike_angle - self._hammer_natural_angle
        self._hammer_phase = "windup"
        self._hammer_timer = 0.0
        # Which mole this swing is actually for -- used by _update_hammer's
        # swing->hold transition to resolve the RIGHT mole's impact (not
        # just "whichever one mole exists"), now that more than one can be
        # up at once. Retriggering mid-swing (e.g. a 2nd hit arrives before
        # this swing lands) simply retargets the hammer to the new hole;
        # the mole it was swinging toward stays "hit_wait" and resolves via
        # its own HIT_WAIT_SAFETY_SEC timeout instead (see Mole.update()).
        self._hammer_target_hole = hole_idx

    def _update_hammer(self, dt):
        if self._hammer_phase == "idle":
            return
        self._hammer_timer += dt
        if self._hammer_phase == "windup" and self._hammer_timer >= HAMMER_WINDUP_SEC:
            self._hammer_phase, self._hammer_timer = "swing", 0.0
        elif self._hammer_phase == "swing" and self._hammer_timer >= HAMMER_SWING_SEC:
            self._hammer_phase, self._hammer_timer = "hold", 0.0
            # The instant the swing actually lands -- this, not the input
            # press back in _on_finger_press(), is what flips the mole to
            # its dizzy sprite AND registers the score. Scoring on input
            # would count the point before the hammer has even reached the
            # mole; this way it only counts once the hit actually lands.
            # Resolve whichever mole this swing was actually targeting (see
            # _trigger_hammer) -- it may have already been resolved by its
            # own safety-net timeout if a 2nd hit retargeted the hammer
            # elsewhere first; _award_hit no-ops in that case.
            target = next((m for m in self._moles
                           if m.hole_idx == self._hammer_target_hole and m.phase == "hit_wait"), None)
            if target is not None:
                self._award_hit(target)
        elif self._hammer_phase == "hold" and self._hammer_timer >= HAMMER_HOLD_SEC:
            self._hammer_phase, self._hammer_timer = "return", 0.0
        elif self._hammer_phase == "return" and self._hammer_timer >= HAMMER_RETURN_SEC:
            self._hammer_phase, self._hammer_timer = "idle", 0.0

    def _award_hit(self, mole):
        """Score a mole's impact -- called from either the hammer's own
        swing->hold landing (the normal case) or a mole's own
        HIT_WAIT_SAFETY_SEC timeout (see Mole.update()'s "impact" event,
        which fires when the single shared hammer is busy with a different
        mole -- possible now that more than one mole can be up at once).
        `mole.hit` is the one authoritative "already scored" flag
        (apply_impact() sets it), so calling this twice for the same mole
        (e.g. the safety net firing a frame after the hammer already
        landed) is a safe no-op."""
        if mole.hit:
            return
        mole.apply_impact()
        self.score += _MOLE_POINTS.get(mole.sprite_key, 1)
        self.reps  += 1
        self.feedback = ("HIT!", (0, 220, 140), 0.6)
        play_success()
        if self._session_target_reached():
            self._end_game()

    # ── lifecycle ────────────────────────────────────────────────────────

    def handle_event(self, event):
        if self._show_instructions:
            if self._instructions_min_t <= 0 and (event.type == pygame.KEYDOWN or
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
        if self._show_instructions:
            self._instructions_min_t = max(0.0, self._instructions_min_t - dt)
            return
        if self.game_over:
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

        # A correct hit only actually scores once the swing lands (see
        # apply_impact(), called from _update_hammer()'s swing->hold
        # transition) -- the score itself, not just the end-game trigger,
        # is deferred behind that animation. If Timed Mode's duration runs
        # out while a hit is still mid-swing ("hit_wait"), ending right now
        # would silently drop that already-earned point/rep -- same
        # "let it finish instead of cutting it off" rule _advance_hoop()
        # already applies to Basketball's own made-shot flight. Time_left
        # is already floored at 0 by _session_tick() itself, so checking
        # again next frame (once the swing has resolved) ends it exactly
        # one frame later with the correct, already-updated score intact.
        pending_hit = any(m.phase == "hit_wait" for m in self._moles)
        if self._session_tick(dt) and not pending_hit:
            self._end_game()
            return

        for mole in self._moles:
            event = mole.update(dt, self.mole_hit_window)
            if event == "missed":
                self.missed += 1
                self.feedback = ("Missed!", (255, 170, 60), 0.6)
            elif event == "impact":
                self._award_hit(mole)
        if any(m.done for m in self._moles):
            self._moles = [m for m in self._moles if not m.done]
            self._update_required_finger()

        if len(self._moles) < self.simultaneous:
            self._spawn_timer += dt
            if self._spawn_timer >= self.spawn_gap:
                self._spawn_mole()
        else:
            self._spawn_timer = 0.0

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

        if self._tutorial_hints:
            self._tutorial_hints.update(self, dt)

    def _spawn_mole(self):
        # Never a hole already occupied by a still-active mole, and never
        # the single most-recently-vacated hole (same "no immediate repeat"
        # rule as before, now checked against the whole active set too --
        # matters once more than one mole can be up at once, see
        # SIMULTANEOUS).
        occupied = {m.hole_idx for m in self._moles if not m.done}
        choices = [i for i in range(5) if i not in occupied and i != self._last_hole_idx]
        if not choices:
            choices = [i for i in range(5) if i not in occupied]
        if not choices:
            return
        hole_idx = random.choice(choices)
        self._last_hole_idx = hole_idx
        sprite_key = random.choices(_MOLE_SPRITES, weights=_MOLE_WEIGHTS, k=1)[0]
        self._moles.append(Mole(hole_idx, sprite_key))
        self._update_required_finger()

    def _update_required_finger(self):
        """Therapist-monitoring display only -- which finger(s) are needed
        right now, for every currently-active mole (comma-joined when more
        than one mole is up at once)."""
        fingers = [self._hole_finger[m.hole_idx] for m in self._moles if not m.done]
        self.required_finger = ", ".join(fingers) if fingers else None

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
            mole = next((m for m in self._moles if m.hole_idx == i and not m.done), None)
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
        if self.tutorial:
            draw_tutorial_badge(surface)

        draw_target_pill(surface, self._session_progress_text("moles hit"),
                          TARGET_POS, T["ACCENT"], self._font_target)

        if self.feedback:
            draw_feedback_banner(surface, self.feedback, self._font_fb,
                                  (GAME_W // 2, int(GAME_H * 0.10)))

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
        card_name = (f"whack_a_mole_how_to_play_{'dark' if is_dark_mode() else 'light'}"
                     f"{'_fil' if self.language == 'fil' else ''}.png")
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        if card is not None:
            cr = card.get_rect(center=(GAME_W // 2, GAME_H // 2))
            surface.blit(card, cr)
        # Code-drawn "Controls" supplement in the card's own side margin --
        # covers the one thing the baked card art can't show on its own:
        # exactly which finger goes with which hole. No "press any key"
        # prompt -- the patient never starts the game themselves, only the
        # therapist's own START control does.
        lang = self.language
        draw_controls_panel(surface, controls_panel_rect(top_margin, bottom_reserved), [
            (tr("whackmole.ctrl.bend.action", lang), tr("whackmole.ctrl.bend.desc", lang)),
            (tr("whackmole.ctrl.hit.action", lang), tr("whackmole.ctrl.hit.desc", lang)),
        ])

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
