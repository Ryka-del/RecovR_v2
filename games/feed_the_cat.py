"""
Feed the Cat — Dual Skill (Wrist Movement + Grip Strength) game (1920x1080)

Mechanic:
  - Tilt wrist LEFT/RIGHT to move the hand.
  - Grip (squeeze >= the calibrated threshold) while the hand is over the
    resting bowl to grab it. The hand and bowl then move together.
  - Carry the empty bowl to the food, keep squeezing, and the bowl fills --
    no release needed to collect food.
  - Carry the filled bowl to the cat, keep squeezing, to feed it and score.
  - If grip drops below the threshold while carrying, the bowl returns to
    its resting spot in whatever state it was in (still empty, or still
    filled) and the hand must grab it again.
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

# ── difficulty-scaled parameters ────────────────────────────────────────────
# All four are real, independently read values (not cosmetic labels) --
# Advanced Settings can override grip threshold / movement sensitivity /
# positioning tolerance per the calibration screen's GAME_PARAM_SCHEMA
# ("ftc_*" keys in scenes/calibration_window.py); travel distance is
# difficulty-only, matching the spec's Advanced Settings list exactly.
GRIP_THRESHOLD = {"Easy": 0.30, "Medium": 0.45, "Hard": 0.60}   # calibrated grip (0-1) to grab/hold
MOVE_DEADZONE  = {"Easy": 0.05, "Medium": 0.08, "Hard": 0.12}   # wrist tilt magnitude before the hand moves
ZONE_TOLERANCE = {"Easy": 150,  "Medium": 110,  "Hard": 75}     # px radius of the bowl/food/cat interaction zones
TRAVEL_SCALE   = {"Easy": 0.75, "Medium": 1.0,  "Hard": 1.3}    # food/cat distance from the bowl, relative to base
MOVE_SPEED     = {"Easy": 700,  "Medium": 850,  "Hard": 1000}   # hand px/s per unit tilt
GOAL           = {"Easy": 5,    "Medium": 7,    "Hard": 10}     # Target Mode: cats to feed to complete
DURATION       = {"Easy": 60,   "Medium": 50,   "Hard": 40}     # Timed Mode: session length in seconds

# The resting bowl's own grab zone is more forgiving than the shared
# food/cat zone_tolerance -- patients with limited wrist/grip control don't
# need to land on it precisely to pick it up. 25% extra margin, comfortably
# inside the food/cat travel distance at every difficulty (see
# HAND_MOVE_RANGE below) so it can never reach into those zones.
BOWL_GRAB_TOLERANCE_SCALE = 1.25

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

TRAVEL_BASE     = GAME_W * 0.28   # base food/cat distance from the bowl before TRAVEL_SCALE
# Must comfortably reach the food/cat zone at every difficulty -- sized off
# the actual TRAVEL_SCALE/ZONE_TOLERANCE values rather than a guessed
# constant, so it can never fall short of what Hard difficulty requires.
HAND_MOVE_RANGE = TRAVEL_BASE * max(TRAVEL_SCALE.values()) + max(ZONE_TOLERANCE.values()) + 60

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


def _draw_counter_box(surface, x, y, w, h, font_lbl, font_num, label, value):
    """The "Cats fed" counter -- a rounded purple-to-blue gradient card,
    label and number centered, matching the reference screenshot."""
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
        self.bowl_grab_tolerance = self.zone_tolerance * BOWL_GRAB_TOLERANCE_SCALE
        self.move_speed     = MOVE_SPEED[self.difficulty]
        self._session_init(data, GOAL, DURATION, self.difficulty, cal_goal_key="ftc_target_cats")

        travel = TRAVEL_SCALE[self.difficulty]
        self.food_x = BOWL_X - TRAVEL_BASE * travel
        self.cat_x  = BOWL_X + TRAVEL_BASE * travel

        self._bg_img         = _load_image_cover("bg_feed_the_cat.png", GAME_W, GAME_H)
        self._hand_img       = _load_image_fit("hand_feed_the_cat.png", *HAND_BOX)
        self._grab_empty_img = _load_image_fit("grab_empty_bowl_feed_the_cat.png", *GRABBOWL_BOX)
        self._grab_food_img  = _load_image_fit("grab_food_bowl_feed_the_cat.png", *GRABBOWL_BOX)
        self._empty_bowl_img = _load_image_fit("empty_bowl_feed_the_cat.png", *BOWL_BOX)
        self._food_bowl_img  = _load_image_fit("food_bowl_feed_the_cat.png", *BOWL_BOX)
        self._food_img       = _load_image_fit("food_feed_the_cat.png", *FOOD_BOX)
        self._cat_pairs      = _discover_cat_pairs()
        self._cat_idx        = 0
        self._cat_hungry_img = None
        self._cat_food_img   = None

        self._font_hud     = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm      = pygame.font.SysFont("monospace", 24)
        self._font_fb      = pygame.font.SysFont("monospace", 44, bold=True)
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

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Feed the Cat"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Feed the Cat"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Feed the Cat"))),
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

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        if self._session_tick(dt):
            self._end_game()
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

        if self.bowl_carried:
            if not grip_valid:
                # Grip insufficient -- drop. The bowl keeps whatever fill
                # state it had; it is NOT reset to empty.
                self.bowl_carried = False
                self.feedback = ("Bowl dropped — grab it again!", (255, 170, 60), FEEDBACK_DURATION)
            elif not self.bowl_filled:
                if abs(self.hand_x - self.food_x) <= self.zone_tolerance:
                    self.bowl_filled = True
                    self.feedback = ("Food collected!", (120, 220, 255), FEEDBACK_DURATION)
            else:
                # Feeding is disabled while the previous/next cat is
                # sliding -- the patient just waits a beat with the bowl.
                if self._cat_state == "idle" and abs(self.hand_x - self.cat_x) <= self.zone_tolerance:
                    self._feed_cat()
        else:
            if grip_valid and not self._need_release:
                if abs(self.hand_x - BOWL_X) <= self.bowl_grab_tolerance:
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

    def _cats_remaining(self):
        """Target Mode only -- how many more cats to reach the goal. Timed
        Mode has no goal, so this is meaningless there (callers show the
        plain fed-so-far count instead, see draw())."""
        return max(0, self.goal - self.reps) if self.session_mode == "target" else 0

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
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id     = patient_id,
                therapist_id   = self.account_id,
                game           = "Feed the Cat",
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

        # Cats counter (top-left, below the header) -- Target Mode counts
        # down to the goal; Timed Mode has no goal, so it counts fed-so-far.
        cx = int(40 * GAME_W / 1920)
        cy = HEADER_BOTTOM + int(20 * GAME_H / 1080)
        cw = int(330 * GAME_W / 1920)
        ch = int(260 * GAME_H / 1080)
        if self.session_mode == "target":
            counter_label, counter_val = "Cats Left to Feed", self._cats_remaining()
        else:
            counter_label, counter_val = "Cats Fed", self.reps
        _draw_counter_box(surface, cx, cy, cw, ch,
                          self._font_counter_lbl, self._font_counter_num,
                          counter_label, counter_val)

        draw_game_header(surface, "Feed the Cat", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, int(GAME_H * 0.12)))

        hints = {
            "Easy":   "Tilt wrist to move   •   Squeeze to grab, carry & feed",
            "Medium": "Tilt wrist to move   •   Hold your grip while carrying the bowl",
            "Hard":   "Tilt wrist to move   •   Precise positioning + sustained grip required",
        }
        surface.blit(font_sm.render(hints[self.difficulty], True, T["GRAY"]),
                     (GAME_W // 2 - 360, GAME_H - 44))

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

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        card_name = f"feed_the_cat_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.07)
        card = _load_image_fit(card_name, int(GAME_W * 0.60), GAME_H - top_margin - bottom_reserved)
        bottom_y = GAME_H // 2
        if card is not None:
            cr = card.get_rect(midtop=(GAME_W // 2, top_margin))
            surface.blit(card, cr)
            bottom_y = cr.bottom

        # No "press any key" prompt -- the patient never starts the game
        # themselves, only the therapist's own START control does.
        f_info = pygame.font.SysFont("monospace", 22, bold=True)
        sess_txt = (f"Goal: Feed {self.goal} cats" if self.session_mode == "target" else
                    f"Duration: {int(self.timed_duration)}s — feed as many cats as you can")
        info = f_info.render(f"{sess_txt}   ·   Difficulty: {self.difficulty}", True, T["WHITE"])
        info_r = info.get_rect(centerx=GAME_W // 2, top=bottom_y + 14)
        surface.blit(info, info_r)

    def _draw_results(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        card_name = f"feed_the_cat_round_complete_{'dark' if is_dark_mode() else 'light'}.png"
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        bottom_y = GAME_H // 2
        if card is not None:
            cr = card.get_rect(midtop=(GAME_W // 2, top_margin))
            surface.blit(card, cr)
            bottom_y = cr.bottom

            num_col = T["WHITE"] if not is_dark_mode() else (20, 80, 150)
            f_num = pygame.font.SysFont("monospace", max(18, int(cr.height * 0.075)), bold=True)
            num_s = f_num.render(self._session_count_text(), True, num_col)
            surface.blit(num_s, num_s.get_rect(
                center=(cr.x + int(cr.width * 0.81), cr.y + int(cr.height * 0.80))))

        f_sm  = pygame.font.SysFont("monospace", 24)
        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        mins, secs = divmod(self.game_over_duration, 60)
        mode_lbl = "Target Mode" if self.session_mode == "target" else "Timed Mode"
        du_s = f_sm.render(
            f"Elapsed Time: {mins:02d}:{secs:02d}   ·   {self.difficulty} · {mode_lbl}",
            True, T["WHITE"])
        du_r = du_s.get_rect(centerx=GAME_W // 2, top=bottom_y + 16)
        surface.blit(du_s, du_r)

        mp  = pygame.mouse.get_pos()
        bw, bh = 220, 52
        by  = du_r.bottom + 20

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
