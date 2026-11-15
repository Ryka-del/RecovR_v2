"""
Purrfect Feast — Dual Skill (Wrist Movement + Grip Strength) game (1920x1080)

Mechanic:
  - Tilt wrist LEFT/RIGHT to move the hand.
  - Grip (squeeze >= the calibrated threshold) while the hand is over the
    resting bowl to grab it. The hand and bowl then move together.
  - Carry the empty bowl to the food, keep squeezing, and the bowl fills --
    no release needed to collect food.
  - Carry the filled bowl to the cat, then RELEASE the grip while over the
    cat to actually feed it and score -- the food is not dispensed while
    still squeezing, only on that deliberate release.
  - If grip is released anywhere else while carrying (not over the cat with
    a filled bowl), the bowl is simply dropped: it returns to its resting
    spot in whatever state it was in (still empty, or still filled) and the
    hand must grab it again.
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
from games.hud import (draw_target_pill, TARGET_POS, draw_tutorial_badge, draw_feedback_banner,
                        draw_controls_panel, controls_panel_rect)
from games.tutorial_hints import TutorialHints, TutorialStep
from games.round_complete import draw_round_complete_overlay
from i18n import tr

# ── difficulty-scaled parameters ────────────────────────────────────────────
# All four are real, independently read values (not cosmetic labels) --
# Advanced Settings can override grip threshold / movement sensitivity /
# positioning tolerance per the calibration screen's GAME_PARAM_SCHEMA
# ("ftc_*" keys in scenes/calibration_window.py); travel distance is
# difficulty-only, matching the spec's Advanced Settings list exactly.
GRIP_THRESHOLD = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}   # calibrated grip (0-1) to grab/hold
MOVE_DEADZONE  = {"Easy": 0.05, "Medium": 0.08, "Hard": 0.12}   # wrist tilt magnitude before the hand moves
# px radius of the bowl/food/cat interaction zones. Raised from the previous
# 150/110/75 -- measured against the actual sprites (empty_bowl/food/cat_
# hungry at their real rendered sizes: ~300x207, ~230x356, ~400x466), the old
# radii were well under half those sprites' own on-screen size, so a hand
# clearly hovering over the bowl/cat could still read as "out of range".
# Still keeps the same relative Easy>Medium>Hard shape as before.
ZONE_TOLERANCE = {"Easy": 180,  "Medium": 135,  "Hard": 95}
TRAVEL_SCALE   = {"Easy": 0.75, "Medium": 1.0,  "Hard": 1.3}    # food/cat distance from the bowl, relative to base
MOVE_SPEED     = {"Easy": 700,  "Medium": 850,  "Hard": 1000}   # hand px/s per unit tilt
GOAL           = {"Easy": 50,   "Medium": 75,   "Hard": 100}    # Target Mode: points
DURATION       = {"Easy": 300,  "Medium": 420,  "Hard": 600}    # Timed Mode: session length (s) -- 5/7/10 min

# Cosmetic-only Advanced Settings display value ("Required Finger Flexion")
# -- the real grab/hold/release gate stays grip-only (unchanged below); this
# exists so the setting is visible/editable in Advanced Settings without
# changing real gameplay behavior.
FLEX_THRESHOLD_DISPLAY = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}

# Affected-Hand Adaptation (see games/session_mode.py's self.affected_hand) --
# this game's unflipped art/layout depicts a LEFT hand. When the patient's
# affected hand is the opposite one, on_enter() mirrors: the hand/grab
# sprites, BOWL_CARRY_X_FRAC, the food_x/cat_x placement (spec: "Switch the
# placement of the food and the cat"), and every asymmetric tolerance pair
# below -- by swapping which scale each named self.* tolerance attribute
# gets, not by mirroring a coordinate (see on_enter's tolerance block).
DEFAULT_HAND = "left"

# The resting bowl's own grab zone is more forgiving than the shared
# food/cat zone_tolerance -- patients with limited wrist/grip control don't
# need to land on it precisely to pick it up. Comfortably inside the food/
# cat travel distance at every difficulty (see HAND_MOVE_RANGE below) so it
# can never reach into those zones. Asymmetric per the reference "grabbing"
# photo (fingers already making contact while the hand is still left of the
# bowl's own centre): generous on the hand's LEFT approach, tighter on the
# right, where there is nothing to reach for -- pushed further in both
# directions per spec (the hand must move further left to grab it).
BOWL_GRAB_TOLERANCE_LEFT_SCALE  = 1.5
BOWL_GRAB_TOLERANCE_RIGHT_SCALE = 0.5
# Same asymmetric idea for the cat specifically: a little extra allowance on
# its FRONT (the side the bowl actually approaches from -- the left, coming
# back through the bowl's own resting spot), not its rear, which widening
# symmetrically would otherwise extend uselessly past the cat into empty
# space.
CAT_FRONT_TOLERANCE_SCALE = 1.25
CAT_REAR_TOLERANCE_SCALE  = 0.8
# The food's own zone is asymmetric too, the opposite way round from the
# cat's: its FRONT -- the side the empty bowl actually approaches from,
# i.e. the RIGHT (coming from the bowl's resting spot toward food_x, which
# sits to the LEFT of it) -- gets the reduced allowance, specifically so the
# hand has to keep moving further left, past where it used to register,
# before the bowl fills. The LEFT side (beyond food_x, where there's
# nothing left to reach for) stays generous, matching the cat/bowl pattern.
FOOD_LEFT_TOLERANCE_SCALE  = 1.3
FOOD_RIGHT_TOLERANCE_SCALE = 0.4
# The bowl's own visual centre within the combined grab_*_bowl sprite --
# grid-overlay measured (color-isolated the blue bowl from the hand/arm):
# ~68% across the sprite's own width, NOT the sprite's geometric centre
# (where hand_x itself anchors). Comparing raw hand_x to food_x/cat_x put
# the real trigger point noticeably right of where the bowl visually was
# ("hitbox too far right from the sprite's actual position") -- see
# _carried_bowl_x(), which this is used to compute.
BOWL_CARRY_X_FRAC = 0.68

FEED_FLASH_DURATION = 1.1   # seconds the cat_food sprite stays up after a feed
FEEDBACK_DURATION   = 1.0

# Cat swap transition -- after the eating flash, the fed cat slides fully
# off the right edge, the next cat is picked, then it slides in from the
# right to the resting cat position. Each leg is its own fixed duration so
# the motion is frame-rate independent; an ease-out curve keeps it from
# feeling mechanical.
CAT_SLIDE_DURATION = 0.45   # seconds for each leg (exit, then enter)

# on-screen target box each sprite is cropped-to-content and fit within
# (aspect ratio preserved, never stretched) -- see _load_image_fit.
HAND_BOX     = (460, 640)
GRABBOWL_BOX = (560, 600)
BOWL_BOX     = (300, 220)
FOOD_BOX     = (230, 420)
CAT_BOX      = (400, 480)

BOWL_X        = GAME_W * 0.50
BOWL_BOTTOM_Y = int(GAME_H * 0.86)
FOOD_BOTTOM_Y = int(GAME_H * 0.86)
CAT_BOTTOM_Y  = int(GAME_H * 0.90)
# The hand/carried-bowl sprite's own art already extends well past the
# bottom of its cropped content (a forearm fading toward the viewer), so
# anchoring its bottom edge below the screen keeps that cut-off invisible
# per spec, instead of showing a hard horizontal edge.
HAND_BOTTOM_Y = GAME_H + 150

TRAVEL_BASE     = GAME_W * 0.30   # base food/cat distance from the bowl before TRAVEL_SCALE -- raised
                                   # from 0.28 so the food and cat sit farther apart, keeping their
                                   # (now larger) interaction zones comfortably clear of each other
                                   # and of the bowl's own resting spot.
# Extra push outward on top of TRAVEL_BASE -- the food moves further left of
# the bowl and the cat further right, per spec, independent of (and in
# addition to) the _carried_bowl_x() hitbox-accuracy fix below.
EXTRA_SPREAD_PX = 60
# How far right of hand_x (the combined grab sprite's own geometric centre)
# the bowl itself actually sits -- see BOWL_CARRY_X_FRAC. GRABBOWL_BOX's
# width is the binding (width-constrained) dimension for this art, so the
# rendered sprite is always exactly this wide regardless of instance state,
# making this safe to compute here rather than from a loaded image.
BOWL_CARRY_OFFSET_PX = GRABBOWL_BOX[0] * (BOWL_CARRY_X_FRAC - 0.5)
# Must comfortably reach the food/cat zone at every difficulty -- sized off
# the actual TRAVEL_SCALE/EXTRA_SPREAD_PX/BOWL_CARRY_OFFSET_PX values
# rather than a guessed constant, so it can never fall short of what Hard
# difficulty requires: the hand has to travel the full outward push PLUS
# the bowl's own rightward carry offset to make the bowl (not just hand_x)
# actually reach food_x. ZONE_TOLERANCE never makes this NEED more reach
# (reaching the exact target already succeeds; extra tolerance only ever
# makes success easier, not farther away), so it is deliberately left out
# of this sum -- including it nearly pushed the hand's clamp off-screen.
HAND_MOVE_RANGE = (TRAVEL_BASE * max(TRAVEL_SCALE.values())
                    + EXTRA_SPREAD_PX + BOWL_CARRY_OFFSET_PX + 30)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}

# ── cat breed variations ────────────────────────────────────────────────────
# The therapist may drop in additional cat art under these names (each a
# hungry/eating pair that must always be swapped together -- see module
# docstring). Only pairs that actually exist on disk are used; if none of
# them have been added yet, the game falls back to the single original cat
# asset pair unchanged, so nothing breaks before new art arrives.
_CAT_NAMES = ["ragdoll", "calico", "inky", "carrot", "kangkang",
              "maine", "persian", "siamese", "sphynx"]
_DEFAULT_CAT_PAIR = ("cat_hungry_feed_the_cat.png", "cat_food_feed_the_cat.png")
_cat_pairs_cache = None


def _discover_cat_pairs():
    """Return a list of (hungry_filename, eating_filename) pairs found on
    disk, matching this project's actual "{name}_cat_hungry_feed_the_cat.png"
    / "{name}_cat_food_feed_the_cat.png" asset-naming convention. A pair is
    only used when BOTH its images actually exist, so a half-uploaded breed
    is simply skipped rather than crashing or showing a mismatched cat. The
    original un-prefixed cat pair is included too (it is a complete, valid
    pair in its own right), so it joins the random rotation instead of only
    being used as an emergency fallback."""
    global _cat_pairs_cache
    if _cat_pairs_cache is not None:
        return _cat_pairs_cache
    img_dir = os.path.join(_ROOT, "assets", "images")
    pairs = []
    for name in _CAT_NAMES:
        hungry = f"{name}_cat_hungry_feed_the_cat.png"
        eat    = f"{name}_cat_food_feed_the_cat.png"
        if (os.path.isfile(os.path.join(img_dir, hungry)) and
                os.path.isfile(os.path.join(img_dir, eat))):
            pairs.append((hungry, eat))
    if (os.path.isfile(os.path.join(img_dir, _DEFAULT_CAT_PAIR[0])) and
            os.path.isfile(os.path.join(img_dir, _DEFAULT_CAT_PAIR[1]))):
        pairs.append(_DEFAULT_CAT_PAIR)
    _cat_pairs_cache = pairs if pairs else [_DEFAULT_CAT_PAIR]
    return _cat_pairs_cache


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



class FeedTheCatGame(SessionModeMixin, FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "dual"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        # Advanced Settings overrides (set by the therapist on the
        # calibration Advanced Settings screen) take priority; absent an
        # override, fall back to the normal per-difficulty preset.
        cal_params = self.cal.get("params", {})
        self.grip_threshold = cal_params.get("ftc_grip_threshold", GRIP_THRESHOLD[self.difficulty])
        self.move_deadzone  = cal_params.get("ftc_move_deadzone", MOVE_DEADZONE[self.difficulty])
        self.zone_tolerance = cal_params.get("ftc_zone_tolerance", ZONE_TOLERANCE[self.difficulty])
        self.move_speed     = MOVE_SPEED[self.difficulty]
        # Cosmetic-only -- exposed in Advanced Settings as "Required Finger
        # Flexion" but never read by the real grab/hold/release gate (grip
        # alone stays the sole gate).
        self.flex_threshold_display = cal_params.get(
            "ftc_flex_threshold", FLEX_THRESHOLD_DISPLAY[self.difficulty])
        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="ftc_target_cats")
        self.hand_flipped = bool(self.affected_hand) and self.affected_hand != DEFAULT_HAND

        # Each pair's two named scales swap which self.* attribute they land
        # in when flipped, rather than mirroring a coordinate -- every call
        # site below (_near_asym's tol_left/tol_right args) stays untouched;
        # only which physical scale backs "left"/"right" changes.
        if self.hand_flipped:
            self.bowl_grab_tolerance_left  = self.zone_tolerance * BOWL_GRAB_TOLERANCE_RIGHT_SCALE
            self.bowl_grab_tolerance_right = self.zone_tolerance * BOWL_GRAB_TOLERANCE_LEFT_SCALE
            self.cat_front_tolerance = self.zone_tolerance * CAT_REAR_TOLERANCE_SCALE
            self.cat_rear_tolerance  = self.zone_tolerance * CAT_FRONT_TOLERANCE_SCALE
            self.food_left_tolerance  = self.zone_tolerance * FOOD_RIGHT_TOLERANCE_SCALE
            self.food_right_tolerance = self.zone_tolerance * FOOD_LEFT_TOLERANCE_SCALE
            bowl_carry_x_frac = 1.0 - BOWL_CARRY_X_FRAC
        else:
            self.bowl_grab_tolerance_left  = self.zone_tolerance * BOWL_GRAB_TOLERANCE_LEFT_SCALE
            self.bowl_grab_tolerance_right = self.zone_tolerance * BOWL_GRAB_TOLERANCE_RIGHT_SCALE
            self.cat_front_tolerance = self.zone_tolerance * CAT_FRONT_TOLERANCE_SCALE
            self.cat_rear_tolerance  = self.zone_tolerance * CAT_REAR_TOLERANCE_SCALE
            self.food_left_tolerance  = self.zone_tolerance * FOOD_LEFT_TOLERANCE_SCALE
            self.food_right_tolerance = self.zone_tolerance * FOOD_RIGHT_TOLERANCE_SCALE
            bowl_carry_x_frac = BOWL_CARRY_X_FRAC
        # Per-instance (not the module constant) since it depends on
        # hand_flipped -- see _carried_bowl_x().
        self.bowl_carry_offset_px = GRABBOWL_BOX[0] * (bowl_carry_x_frac - 0.5)
        # Every session gets a minimum read time on the How-To-Play screen --
        # a curious first squeeze/tilt shouldn't be able to skip past the
        # instructions before the patient has had any chance to read them
        # (the patient's own sensor input can dismiss this screen even in
        # the dual-monitor production flow -- see
        # recovr/patient_app/games/generic_adapter.py's handle_event()).
        self._instructions_min_t = 2.5

        travel = TRAVEL_SCALE[self.difficulty]
        if self.hand_flipped:
            self.food_x = BOWL_X + TRAVEL_BASE * travel + EXTRA_SPREAD_PX
            self.cat_x  = BOWL_X - TRAVEL_BASE * travel - EXTRA_SPREAD_PX
        else:
            self.food_x = BOWL_X - TRAVEL_BASE * travel - EXTRA_SPREAD_PX
            self.cat_x  = BOWL_X + TRAVEL_BASE * travel + EXTRA_SPREAD_PX

        def _hand_art(name, box):
            """Loads a hand/arm sprite (unlike the bowl/cat/food art, these
            depict a specific hand, so they're the only sprites mirrored)."""
            img = _load_image_fit(name, *box)
            return pygame.transform.flip(img, True, False) if (img is not None and self.hand_flipped) else img

        self._bg_img         = _load_image_cover("bg_feed_the_cat.png", GAME_W, GAME_H)
        self._hand_img       = _hand_art("hand_feed_the_cat.png", HAND_BOX)
        self._grab_empty_img = _hand_art("grab_empty_bowl_feed_the_cat.png", GRABBOWL_BOX)
        self._grab_food_img  = _hand_art("grab_food_bowl_feed_the_cat.png", GRABBOWL_BOX)
        self._empty_bowl_img = _load_image_fit("empty_bowl_feed_the_cat.png", *BOWL_BOX)
        self._food_bowl_img  = _load_image_fit("food_bowl_feed_the_cat.png", *BOWL_BOX)
        self._food_img       = _load_image_fit("food_feed_the_cat.png", *FOOD_BOX)
        self._cat_pairs      = _discover_cat_pairs()
        self._cat_idx        = 0
        self._cat_hungry_img = None
        self._cat_food_img   = None

        self._font_hud     = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_fb      = pygame.font.SysFont("monospace", 44, bold=True)
        self._font_target  = pygame.font.SysFont("monospace", 54, bold=True)

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
            TutorialStep(lambda g: tr("feedcat.tut.1", g.language),
                         anchor=lambda g: (int(g.food_x), int(GAME_H * 0.65)),
                         done=lambda g, t: g.bowl_carried),
            TutorialStep(lambda g: tr("feedcat.tut.2", g.language),
                         anchor=lambda g: (int(g.food_x), int(GAME_H * 0.65)),
                         done=lambda g, t: g.bowl_filled),
            TutorialStep(lambda g: tr("feedcat.tut.3", g.language),
                         anchor=lambda g: (int(g.cat_x), int(GAME_H * 0.65)),
                         done=lambda g, t: g.score >= 1),
            TutorialStep(lambda g: (tr("feedcat.tut.4.target", g.language, goal=g.goal)
                                     if g.session_mode == "target" else
                                     tr("feedcat.tut.4.timed", g.language))),
        ]) if self.tutorial else None

    def _reset(self):
        self.game_over          = False
        self.game_over_score    = 0
        self.game_over_duration = 0
        self.paused     = False
        self.pause_sel  = 0

        self.score = 0
        self.reps  = 0          # = cats successfully fed this session
        self._session_reset()
        self.start_time = pygame.time.get_ticks()

        self.hand_x        = BOWL_X
        self.bowl_carried   = False
        self.bowl_filled    = False
        self._need_release  = False
        self._grip_active   = False
        self.feed_flash_t   = 0.0
        self._cat_exit_pending = False
        self.feedback       = None
        self._state = {"grip": 0.0, "tilt_x": 0.0}

        # Cat swap transition state -- "idle" (resting at cat_x, feedable),
        # "exit" (the just-fed cat sliding off the right edge), "enter" (the
        # newly-picked cat sliding in from the right). See _update_cat_anim.
        self._cat_state   = "idle"
        self._cat_anim_t  = 0.0
        self._cat_draw_x  = self.cat_x

        self._load_cat(self._pick_cat())

    def _pick_cat(self, exclude_idx=None):
        """Randomly choose a cat-pair index, avoiding an immediate repeat of
        exclude_idx when more than one variation is available."""
        n = len(self._cat_pairs)
        if n <= 1:
            return 0
        idx = random.randrange(n)
        while idx == exclude_idx:
            idx = random.randrange(n)
        return idx

    def _load_cat(self, idx):
        self._cat_idx = idx
        hungry, eat = self._cat_pairs[idx]
        self._cat_hungry_img = _load_image_fit(hungry, *CAT_BOX)
        self._cat_food_img   = _load_image_fit(eat, *CAT_BOX)

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

    def _carried_bowl_x(self):
        """x-position of the BOWL itself while carried -- not hand_x, which
        is the combined grab sprite's own geometric centre (see
        BOWL_CARRY_X_FRAC/self.bowl_carry_offset_px). Used for the food/cat
        proximity checks so they key off where the bowl visually is, not
        where the hand's own anchor point happens to be."""
        return self.hand_x + self.bowl_carry_offset_px

    @staticmethod
    def _near_asym(x, target, tol_left, tol_right):
        """True if x is within tol_left of target on its LEFT side, or
        tol_right on its RIGHT side -- an asymmetric replacement for
        abs(x - target) <= tol, used wherever one direction of approach
        deserves more forgiveness than the other (see BOWL_GRAB_TOLERANCE_*/
        CAT_*_TOLERANCE_SCALE)."""
        d = x - target
        return (-d <= tol_left) if d < 0 else (d <= tol_right)

    def handle_event(self, event):
        if self._show_instructions:
            if self._instructions_min_t <= 0 and (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Purrfect Feast"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Purrfect Feast"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Purrfect Feast"))),
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

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        # ── wrist movement -- horizontal only, per spec ────────────────
        tx = self._normalize_tilt(self._state["tilt_x"])
        if abs(tx) > self.move_deadzone:
            self.hand_x += self.move_speed * dt * tx
        lo, hi = BOWL_X - HAND_MOVE_RANGE, BOWL_X + HAND_MOVE_RANGE
        self.hand_x = max(lo, min(hi, self.hand_x))

        # ── grip state (calibrated input, not the raw reading) ─────────
        grip = self._normalize_grip(self._state["grip"])
        grip_valid = grip >= self.grip_threshold
        self._grip_active = grip_valid
        if not grip_valid:
            self._need_release = False

        bowl_x = self._carried_bowl_x()

        if self.bowl_carried:
            if not grip_valid:
                # Grip released while carrying. Over the cat with a filled
                # bowl (and no cat-swap animation in progress) this is the
                # deliberate feed -- the food is dispensed by the release
                # itself, never while still squeezing. Any other release is
                # just a drop: the bowl keeps whatever fill state it had; it
                # is NOT reset to empty.
                if (self.bowl_filled and self._cat_state == "idle"
                        and self._near_asym(bowl_x, self.cat_x,
                                             self.cat_front_tolerance, self.cat_rear_tolerance)):
                    self.bowl_carried = False
                    self._feed_cat()
                else:
                    self.bowl_carried = False
                    self.feedback = ("Bowl dropped — grab it again!", (255, 170, 60), FEEDBACK_DURATION)
            elif not self.bowl_filled:
                # Asymmetric: food_x sits LEFT of the bowl's resting spot,
                # so the bowl always approaches it from the right (its
                # "front") -- that side gets the reduced tolerance, forcing
                # the hand to keep moving left past where it used to
                # register; the far/left side (beyond the food, nothing to
                # reach for) stays generous.
                if self._near_asym(bowl_x, self.food_x,
                                    self.food_left_tolerance, self.food_right_tolerance):
                    self.bowl_filled = True
                    self.feedback = ("Food collected!", (120, 220, 255), FEEDBACK_DURATION)
            # else: filled bowl, still gripping -- wait for the release over
            # the cat above; squeezing alone never feeds it.
        else:
            if grip_valid and not self._need_release:
                if self._near_asym(self.hand_x, BOWL_X,
                                    self.bowl_grab_tolerance_left, self.bowl_grab_tolerance_right):
                    self.bowl_carried = True   # bowl_filled is preserved as-is

        if self.feed_flash_t > 0:
            self.feed_flash_t -= dt
            if self.feed_flash_t <= 0:
                if self._session_target_reached():
                    self._end_game()
                    return
                if self._cat_exit_pending:
                    self._cat_exit_pending = False
                    self._cat_state  = "exit"
                    self._cat_anim_t = 0.0
        self._update_cat_anim(dt)
        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

        if self._tutorial_hints:
            self._tutorial_hints.update(self, dt)

        # Checked LAST, after this frame's own grip/feed logic has already
        # run -- Timed Mode's duration expiring on the exact same frame as
        # a feed must never preempt it (the old position, before that
        # logic, could do exactly that and silently drop the final point).
        # time_left is floored at 0 by _session_tick() itself, so this
        # still ends the session on every subsequent frame.
        if self._session_tick(dt):
            self._end_game()

    def _update_cat_anim(self, dt):
        """Advance the exit/enter cat-swap slide (see _reset()'s _cat_state
        docstring). A no-op while idle. Each leg eases out over
        CAT_SLIDE_DURATION, frame-rate independent since it is driven by
        elapsed time, not a fixed per-frame step."""
        if self._cat_state == "idle":
            return
        self._cat_anim_t += dt
        t     = min(1.0, self._cat_anim_t / CAT_SLIDE_DURATION)
        eased = 1 - (1 - t) ** 2
        offscreen_x = GAME_W + CAT_BOX[0]

        if self._cat_state == "exit":
            self._cat_draw_x = self.cat_x + (offscreen_x - self.cat_x) * eased
            if t >= 1.0:
                # The previous cat has fully left before the next one is
                # even chosen, so the two sprites never overlap on screen.
                self._load_cat(self._pick_cat(exclude_idx=self._cat_idx))
                self._cat_draw_x = offscreen_x
                self._cat_state  = "enter"
                self._cat_anim_t = 0.0
        elif self._cat_state == "enter":
            self._cat_draw_x = offscreen_x + (self.cat_x - offscreen_x) * eased
            if t >= 1.0:
                self._cat_draw_x = self.cat_x
                self._cat_state  = "idle"
                self._cat_anim_t = 0.0

    def _feed_cat(self):
        self.score += 1
        self.reps  += 1
        self.feedback = ("Cat fed! +1", (255, 220, 80), FEEDBACK_DURATION)
        play_success()

        if self._session_target_reached():
            # Goal reached -- the session is complete regardless of how long
            # it took. Still show this cat's eating sprite/flash for a beat
            # before handing off to the results screen (see update()).
            self.feed_flash_t = FEED_FLASH_DURATION
            self._cat_exit_pending = False
            return

        self.feed_flash_t = FEED_FLASH_DURATION
        self._cat_exit_pending = True
        # Round reset -- a fresh empty bowl appears at the resting spot; a
        # new grip activation is required before it can be grabbed, even if
        # the patient never actually released this whole trip.
        self.bowl_carried  = False
        self.bowl_filled   = False
        self._need_release = True

    def _exit_to_game_config(self):
        import builtins
        stop_music()
        # The patient quit before reaching the goal -- still record the
        # attempt (elapsed time + partial progress) instead of silently
        # discarding it, as long as actual gameplay had started.
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
                game           = "Purrfect Feast",
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

        # Food (static, left side, resting on the table)
        if self._food_img is not None:
            r = self._food_img.get_rect(midbottom=(int(self.food_x), FOOD_BOTTOM_Y))
            surface.blit(self._food_img, r)

        # Cat -- sprite swaps hungry <-> fed while idle; during the swap
        # transition it slides at self._cat_draw_x instead of the fixed
        # resting self.cat_x (see _update_cat_anim).
        if self._cat_state == "exit":
            cat_img = self._cat_food_img      # leaves looking satisfied
        elif self._cat_state == "enter":
            cat_img = self._cat_hungry_img    # arrives hungry
        else:
            cat_img = self._cat_food_img if self.feed_flash_t > 0 else self._cat_hungry_img
        if cat_img is not None:
            r = cat_img.get_rect(midbottom=(int(self._cat_draw_x), CAT_BOTTOM_Y))
            surface.blit(cat_img, r)

        # Bowl (resting) + hand, OR hand+bowl combined while carried --
        # never both, never a duplicate bowl.
        if self.bowl_carried:
            img = self._grab_food_img if self.bowl_filled else self._grab_empty_img
            if img is not None:
                r = img.get_rect(midbottom=(int(self.hand_x), HAND_BOTTOM_Y))
                surface.blit(img, r)
        else:
            bowl_img = self._food_bowl_img if self.bowl_filled else self._empty_bowl_img
            if bowl_img is not None:
                r = bowl_img.get_rect(midbottom=(int(BOWL_X), BOWL_BOTTOM_Y))
                surface.blit(bowl_img, r)
            if self._hand_img is not None:
                r = self._hand_img.get_rect(midbottom=(int(self.hand_x), HAND_BOTTOM_Y))
                surface.blit(self._hand_img, r)

        draw_game_header(surface, "Purrfect Feast", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)
        if self.tutorial:
            draw_tutorial_badge(surface)

        draw_target_pill(surface, self._session_progress_text("cats"),
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

    def _draw_instructions(self, surface):
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        card_name = (f"feed_the_cat_how_to_play_{'dark' if is_dark_mode() else 'light'}"
                     f"{'_fil' if self.language == 'fil' else ''}.png")
        # Same outer card box as _draw_results' Round Complete card -- the
        # two screens read as stages of one interface.
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        if card is not None:
            cr = card.get_rect(center=(GAME_W // 2, GAME_H // 2))
            surface.blit(card, cr)
        # Code-drawn "Controls" supplement in the card's own side margin --
        # covers the filling step the card may gloss over. No "press any
        # key" prompt -- the patient never starts the game themselves, only
        # the therapist's own START control does.
        lang = self.language
        draw_controls_panel(surface, controls_panel_rect(top_margin, bottom_reserved), [
            (tr("feedcat.ctrl.tilt.action", lang), tr("feedcat.ctrl.tilt.desc", lang)),
            (tr("feedcat.ctrl.squeeze.action", lang), tr("feedcat.ctrl.squeeze.desc", lang)),
            (tr("feedcat.ctrl.release.action", lang), tr("feedcat.ctrl.release.desc", lang)),
        ])

    def _draw_results(self, surface):
        T = get_theme()
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="feed_the_cat", duration_sec=self.game_over_duration,
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
