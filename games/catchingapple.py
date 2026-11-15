"""
Apple Catching — Wrist Rotation game (1920x1080)

Mechanic:
  - Apples fall from the top of the screen
  - tilt_x (wrist left/right rotation) moves the basket
  - Catch the apple in the basket to score
  - Runs for the configured session duration, then shows results
"""

import os
import pygame
import random
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler
from audio import (start_music, stop_music, pause_music, resume_music,
                    game_bgm_path, play_completion, play_click)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.hud import (draw_target_pill, TARGET_POS, draw_tutorial_badge,
                        draw_controls_panel, controls_panel_rect)
from games.tutorial_hints import TutorialHints, TutorialStep
from games.round_complete import draw_round_complete_overlay
from i18n import tr

APPLE_SPEED  = {"Easy": 260, "Medium": 380, "Hard": 520}
MOVE_SPEED   = {"Easy": 750, "Medium": 900, "Hard": 1050}
APPLE_GOAL   = {"Easy": 50,  "Medium": 75,  "Hard": 100}  # Target Mode: points (see APPLE_TYPES/INSECT_POINTS)
DURATION     = {"Easy": 300, "Medium": 420, "Hard": 600}  # Timed Mode: session length in seconds
# "Required Wrist Rotation" -- how far (as a fraction of the patient's own
# calibrated resting<->peak wrist range, via _normalize_tilt below) the
# wrist must rotate before basket movement registers at all. Same 30/70/90%
# anchor as every other rebanded threshold in this task. Applied identically
# whether BLE-connected or in keyboard Test Mode (see update()) -- there
# used to be no registration threshold at all on the BLE path and a
# hardcoded, non-calibrated 0.1 on the keyboard path; this replaces both.
WRIST_REQUIREMENT = {"Easy": 0.30, "Medium": 0.70, "Hard": 0.90}
# "Simultaneous Object Count" -- how many falling objects may be active at
# once. Easy/Medium keep the original single-object feel; Hard allows 2.
SIMULTANEOUS = {"Easy": 1, "Medium": 1, "Hard": 2}

# basket_back_apple_catching.png / basket_front_apple_catching.png are each
# one fused illustration -- woven basket AND the hands holding it, baked
# into the same sprite (no separate hand-only asset exists). So "enlarge
# the hands" means enlarging this whole sprite, both layers together --
# they stay perfectly matched since _load_image_cropped already fits both
# to this same box from the same shared crop rect. Sized + anchored (see
# BASKET_BOTTOM_MARGIN / _basket_rect) so the sprite's own cut-off forearm
# tail lands safely past the screen's bottom edge, hiding it.
BASKET_SIZE = (345, 345)
APPLE_SIZE  = (120, 120)
INSECT_SIZE = (100, 100)

SHAKE_DURATION = 0.30
# How long a caught object rests visibly inside the basket (sandwiched
# between the back/front layers) before the next one spawns.
CATCH_HOLD_DURATION = 0.80
# px the basket sprite's own bottom edge (where it's cut off) extends past
# the screen's actual bottom edge, so that cut-off is never visible.
BASKET_BOTTOM_MARGIN = 40

# ── apple tiers / insects ───────────────────────────────────────────────────
# (type name, asset filename, points). A fresh independent roll each spawn
# via the FLAT, top-level cumulative probabilities below (_spawn_object) --
# insect/normal/golden/rainbow sum to 100% directly, not a nested "insect
# chance, then split the remainder" roll like before.
APPLE_TYPES = [
    ("normal",  "normal_apple_apple_catching.png",  1),
    ("golden",  "golden_apple_apple_catching.png",  3),
    ("rainbow", "rainbow_apple_apple_catching.png", 5),
]
INSECT_TYPES = [
    ("caterpillar", "caterpillar_apple_catching.png"),
    ("ladybug",     "ladybug_apple_catching.png"),
    ("wasp",        "wasp_apple_catching.png"),
]
INSECT_POINTS = -2   # a caught insect is a PENALTY now, not a bonus
# Flat top-level spawn probabilities (cumulative thresholds used directly in
# _spawn_object): Insect 15%, Normal apple 70%, Golden apple 10%, Rainbow
# apple 5% -- sums to exactly 100%.
INSECT_CHANCE  = 0.15
NORMAL_CHANCE  = 0.70
GOLDEN_CHANCE  = 0.10
RAINBOW_CHANCE = 0.05

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}


def _load_image_fit(name, w, h):
    """Crop to the asset's own opaque content, then scale to fit within
    w x h preserving its aspect ratio (never stretched/distorted). Returns
    None if missing so a caller can skip drawing instead of crashing."""
    key = ("fit", name, w, h)
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


def _load_image_cropped(name, crop_rect, w, h):
    """Crop to an EXPLICIT rect (not the asset's own bounding box), then
    scale to fit within w x h. Used so two layered sprites drawn from the
    same original canvas -- the basket's back/front layers -- share one
    coordinate frame and stay registered with each other, instead of each
    independently cropping to its own content and drifting apart (the front
    layer only shows the near rim, so its own bounding box is a different,
    smaller rect than the back layer's)."""
    key = ("crop", name, tuple(crop_rect), w, h)
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            cropped = raw.subsurface(pygame.Rect(crop_rect)).copy()
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


def _load_sound(name):
    try:
        return pygame.mixer.Sound(os.path.join(_ROOT, "assets", "audio", name))
    except Exception:
        return None


class AppleCatchingGame(SessionModeMixin, FatigueMixin, BaseScreen):
    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "wrist"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        # Advanced Settings overrides (set by the therapist on the
        # calibration Advanced Settings screen) take priority; absent an
        # override, fall back to the normal per-difficulty preset.
        cal_params       = self.cal.get("params", {})
        self.apple_speed = cal_params.get("ac_apple_speed", APPLE_SPEED[self.difficulty])
        self.move_speed  = cal_params.get("ac_move_speed", MOVE_SPEED[self.difficulty])
        self.wrist_requirement = cal_params.get("ac_wrist_requirement", WRIST_REQUIREMENT[self.difficulty])
        self.simultaneous = int(cal_params.get("ac_simultaneous", SIMULTANEOUS[self.difficulty]))
        self._session_init(data, APPLE_GOAL, DURATION, self.difficulty, cal_goal_key="ac_goal")
        # Every session gets a minimum read time on the How-To-Play screen --
        # a curious first tilt shouldn't be able to skip past the
        # instructions before the patient has had any chance to read them
        # (the patient's own sensor input can dismiss this screen even in
        # the dual-monitor production flow -- see
        # recovr/patient_app/games/generic_adapter.py's handle_event()).
        self._instructions_min_t = 2.5

        self._bg_img = _load_image_cover("bg_apple_catching.png", GAME_W, GAME_H)

        # Basket: both layers must share one crop/scale registration (the
        # back layer's own bounding box) so the front rim stays visually
        # aligned over the back basket -- see _load_image_cropped.
        back_raw = pygame.image.load(
            os.path.join(_ROOT, "assets", "images", "basket_back_apple_catching.png")).convert_alpha()
        basket_crop = back_raw.get_bounding_rect(min_alpha=10)
        self._basket_back_img  = _load_image_cropped(
            "basket_back_apple_catching.png",  basket_crop, *BASKET_SIZE)
        self._basket_front_img = _load_image_cropped(
            "basket_front_apple_catching.png", basket_crop, *BASKET_SIZE)

        self._apple_imgs  = {name: _load_image_fit(fname, *APPLE_SIZE)
                              for name, fname, _ in APPLE_TYPES}
        self._insect_imgs = {name: _load_image_fit(fname, *INSECT_SIZE)
                              for name, fname in INSECT_TYPES}

        self._catch_sound = _load_sound("catch_sound_effect.wav")

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)
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
            TutorialStep(lambda g: tr("applecatching.tut.1", g.language),
                         anchor=lambda g: (int(g.basket_x), int(GAME_H * 0.78)),
                         done=lambda g, t: g.reps >= 1),
            TutorialStep(lambda g: tr("applecatching.tut.2", g.language),
                         done=lambda g, t: t >= 3.0),
            TutorialStep(lambda g: (tr("applecatching.tut.3.target", g.language, goal=g.goal)
                                     if g.session_mode == "target" else
                                     tr("applecatching.tut.3.timed", g.language))),
        ]) if self.tutorial else None

    def _reset(self):
        self.game_over          = False
        self.game_over_score    = 0
        self.game_over_duration = 0
        self.paused      = False
        self.pause_sel   = 0
        self.score       = 0
        self.reps        = 0
        self._session_reset()
        self.start_time  = pygame.time.get_ticks()
        self.basket_x    = float(GAME_W // 2)
        self._basket_opening_rect = pygame.Rect(0, 0, 1, 1)
        self._objects = []   # up to self.simultaneous concurrent falling objects
        while len(self._objects) < self.simultaneous:
            self._spawn_object()

        self.shaking      = False
        self.shake_timer   = 0.0
        self.shake_offset = 0

        self._state = {"tilt_x": 0.0}

    def _spawn_object(self):
        """Append one new falling object -- an apple tier or, independently,
        an insect -- to self._objects, at its own spawn position. A FLAT,
        top-level cumulative roll now decides which (Insect 15% / Normal
        70% / Golden 10% / Rainbow 5%), not a nested "insect chance, then
        split the apple remainder" roll. An apple's rotation is rolled
        fresh here and held fixed for as long as it falls; insects are not
        rotated, per spec."""
        obj = {"caught_active": False, "caught_timer": 0.0}
        r = random.random()
        if r < INSECT_CHANCE:
            name, _ = random.choice(INSECT_TYPES)
            obj["kind"]   = "insect"
            obj["type"]   = name
            obj["points"] = INSECT_POINTS
            base_img      = self._insect_imgs.get(name)
            obj["angle"]  = 0.0
        elif r < INSECT_CHANCE + NORMAL_CHANCE:
            name, _, points = APPLE_TYPES[0]   # "normal"
            obj["kind"], obj["type"], obj["points"] = "apple", name, points
            base_img      = self._apple_imgs.get(name)
            obj["angle"]  = random.uniform(0.0, 360.0)
        elif r < INSECT_CHANCE + NORMAL_CHANCE + GOLDEN_CHANCE:
            name, _, points = APPLE_TYPES[1]   # "golden"
            obj["kind"], obj["type"], obj["points"] = "apple", name, points
            base_img      = self._apple_imgs.get(name)
            obj["angle"]  = random.uniform(0.0, 360.0)
        else:
            name, _, points = APPLE_TYPES[2]   # "rainbow"
            obj["kind"], obj["type"], obj["points"] = "apple", name, points
            base_img      = self._apple_imgs.get(name)
            obj["angle"]  = random.uniform(0.0, 360.0)

        # Rotate once per spawn (not per frame) around the unrotated image's
        # own center -- pygame.transform.rotate's returned surface is
        # re-centered automatically, so blitting it via get_rect(center=..)
        # keeps the apple's position from shifting when it is rotated.
        if base_img is not None and obj["angle"]:
            obj["draw_img"] = pygame.transform.rotate(base_img, obj["angle"])
        else:
            obj["draw_img"] = base_img

        draw_w = obj["draw_img"].get_width()  if obj["draw_img"] is not None else APPLE_SIZE[0]
        draw_h = obj["draw_img"].get_height() if obj["draw_img"] is not None else APPLE_SIZE[1]
        # Clamp to the ROTATED (possibly wider) bounding box so a
        # diagonally-rotated apple can never spawn clipped off-screen.
        obj["x"] = float(random.randint(0, max(0, GAME_W - draw_w)))
        obj["y"] = -float(draw_h)
        self._objects.append(obj)

    def _basket_rect(self):
        """The whole fused sprite (basket + hands baked into one image),
        bottom-anchored past the screen's own bottom edge by
        BASKET_BOTTOM_MARGIN so its own cut-off forearm tail is never
        visible -- see BASKET_SIZE's comment."""
        img  = self._basket_back_img
        rect = img.get_rect() if img is not None else pygame.Rect(0, 0, *BASKET_SIZE)
        rect.centerx = int(self.basket_x) + self.shake_offset
        rect.bottom  = GAME_H + BASKET_BOTTOM_MARGIN
        return rect

    def _opening_rect(self, basket_rect):
        """The basket's actual opening (the rim's oval mouth) -- a smaller
        zone than the basket's full visual footprint, used for catch
        detection per spec instead of the old full-basket collision rect."""
        w = int(basket_rect.width * 0.72)
        h = int(basket_rect.height * 0.32)
        r = pygame.Rect(0, 0, w, h)
        r.centerx = basket_rect.centerx
        r.top     = basket_rect.top
        return r

    def _obj_rect(self, obj):
        img = obj["draw_img"]
        w = img.get_width()  if img is not None else APPLE_SIZE[0]
        h = img.get_height() if img is not None else APPLE_SIZE[1]
        return pygame.Rect(int(obj["x"]), int(obj["y"]), w, h)

    def _caught_draw_pos(self, basket_rect):
        """Where a caught object sits while the catch animation plays --
        tracks the basket (so it moves with it instead of being left behind
        at the exact catch instant). The front layer is the basket's near
        wall, covering most of its height, so a position much lower than
        the rim would be almost entirely hidden behind it; staying near the
        opening keeps the object visibly nestled just inside the rim,
        matching the reference screenshot, with only its lower portion
        tucked behind the front layer."""
        return (basket_rect.centerx, basket_rect.top + int(basket_rect.height * 0.16))

    def _normalize_tilt(self, raw):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return 0.0
        norm = (raw - wmin) / (wmax - wmin)
        return max(-1.0, min(1.0, (norm - 0.5) * 2.0))

    def handle_event(self, event):
        if self._show_instructions:
            if self._instructions_min_t <= 0 and (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Apple Catching"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Apple Catching"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Apple Catching"))),
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

        # Required Wrist Rotation: _normalize_tilt already maps raw tilt to
        # a signed -1..1 fraction of the patient's own calibrated range
        # (identity when no calibration exists -- its default wrist_min/max
        # of -1.0/1.0 makes it a no-op), so the SAME calibration-relative
        # deadzone now gates BOTH the BLE-connected and keyboard Test-Mode
        # paths identically -- there used to be no registration threshold
        # at all on the BLE path and a hardcoded, uncalibrated 0.1 on the
        # keyboard path.
        tilt_norm = self._normalize_tilt(self._state["tilt_x"])
        if abs(tilt_norm) >= self.wrist_requirement:
            self.basket_x += self.move_speed * dt * tilt_norm
        self.basket_x = max(BASKET_SIZE[0]//2,
                             min(GAME_W - BASKET_SIZE[0]//2, self.basket_x))

        basket_rect = self._basket_rect()
        self._basket_opening_rect = self._opening_rect(basket_rect)

        for obj in list(self._objects):
            if obj["caught_active"]:
                # The caught object stays glued to the basket (see draw()'s
                # _caught_draw_pos, keyed off basket_rect) instead of
                # falling, so it never visually drops through the bottom,
                # until the catching animation finishes.
                obj["caught_timer"] -= dt
                if obj["caught_timer"] <= 0:
                    self._objects.remove(obj)
                continue

            obj["y"] += self.apple_speed * dt
            obj_rect = self._obj_rect(obj)

            if self._basket_opening_rect.colliderect(obj_rect):
                self.score += obj["points"]
                self.reps  += 1
                obj["caught_active"] = True
                obj["caught_timer"]  = CATCH_HOLD_DURATION
                # Catch sound plays for apples only -- insects are caught
                # silently (per spec).
                if obj["kind"] == "apple" and self._catch_sound:
                    self._catch_sound.play()
                # Basket shake: an insect being CAUGHT is one of exactly two
                # shake triggers (the other is an apple-type MISS, below) --
                # never on an apple catch, never on an insect miss.
                if obj["kind"] == "insect":
                    self.shaking     = True
                    self.shake_timer = SHAKE_DURATION
                if self._session_target_reached():
                    self._end_game()
                    return
            elif obj["y"] > GAME_H:
                # Missed -- it simply falls out of view and is replaced, no
                # sound/blast effect (removed per spec). The basket shake is
                # an apple-type-miss cue only -- insects were never meant to
                # be caught, so missing one isn't a "miss" and shouldn't
                # shake the basket.
                missed_kind = obj["kind"]
                self._objects.remove(obj)
                if missed_kind == "apple":
                    self.shaking     = True
                    self.shake_timer = SHAKE_DURATION

        while len(self._objects) < self.simultaneous:
            self._spawn_object()

        if self.shaking:
            self.shake_timer -= dt
            if self.shake_timer > 0:
                self.shake_offset = random.randint(-6, 6)
            else:
                self.shaking      = False
                self.shake_offset = 0

        if self._tutorial_hints:
            self._tutorial_hints.update(self, dt)

        # Checked LAST, after this frame's own catch logic has already run
        # -- Timed Mode's duration expiring on the exact same frame as a
        # catch must never preempt it (the old position, before that
        # logic, could do exactly that and silently drop the final point).
        # time_left is floored at 0 by _session_tick() itself, so this
        # still ends the session on every subsequent frame.
        if self._session_tick(dt):
            self._end_game()

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
                game           = "Apple Catching",
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

    def draw(self, surface):
        T = get_theme()
        if self._bg_img is not None:
            surface.blit(self._bg_img, (0, 0))
        else:
            surface.fill(T["BG"])

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        font_sm  = self._font_sm

        basket_rect = self._basket_rect()

        # Back layer first (the whole open basket, hands included -- one
        # fused sprite, see BASKET_SIZE's comment).
        if self._basket_back_img is not None:
            surface.blit(self._basket_back_img, basket_rect)

        # ...then the falling/caught objects, so a caught one is sandwiched
        # behind the front rim (see item 3 of the spec: behind front, in
        # front of back)...
        for obj in self._objects:
            img = obj["draw_img"]
            if img is None:
                continue
            if obj["caught_active"]:
                r = img.get_rect(center=self._caught_draw_pos(basket_rect))
                surface.blit(img, r)
            else:
                surface.blit(img, (int(obj["x"]), int(obj["y"])))

        # ...then the front rim on top, so it occludes a caught object
        # exactly like the real rim would.
        if self._basket_front_img is not None:
            surface.blit(self._basket_front_img, basket_rect)

        draw_game_header(surface, "Apple Catching", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)
        if self.tutorial:
            draw_tutorial_badge(surface)

        draw_target_pill(surface, self._session_progress_text("apples"),
                          TARGET_POS, T["ACCENT"], self._font_target)

        # Pause button — two solid bars
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

        # Fully designed "How To Play" card art (title, numbered steps, tip
        # banner all baked in) -- replaces the hand-drawn panel. Per-theme,
        # cropped to its own opaque content then fit preserving aspect
        # ratio. Same outer card box (position + max size) as _draw_results'
        # Round Complete card -- the two screens read as stages of one
        # interface rather than two differently-proportioned popups.
        card_name = (f"apple_catching_how_to_play_{'dark' if is_dark_mode() else 'light'}"
                     f"{'_fil' if self.language == 'fil' else ''}.png")
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        if card is not None:
            cr = card.get_rect(center=(GAME_W // 2, GAME_H // 2))
            surface.blit(card, cr)
        # Code-drawn "Controls" supplement in the card's own side margin --
        # spells out the same loop the card already shows, in plain text.
        # No "press any key" prompt -- the patient never starts the game
        # themselves, only the therapist's own START control does.
        lang = self.language
        draw_controls_panel(surface, controls_panel_rect(top_margin, bottom_reserved), [
            (tr("applecatching.ctrl.tilt.action", lang), tr("applecatching.ctrl.tilt.desc", lang)),
            (tr("applecatching.ctrl.catch.action", lang), tr("applecatching.ctrl.catch.desc", lang)),
        ])

    def _draw_results(self, surface):
        T = get_theme()
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="apple_catch", duration_sec=self.game_over_duration,
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
