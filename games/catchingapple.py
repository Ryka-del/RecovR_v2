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

APPLE_SPEED  = {"Easy": 260, "Medium": 380, "Hard": 520}
MOVE_SPEED   = {"Easy": 750, "Medium": 900, "Hard": 1050}
APPLE_GOAL   = {"Easy": 15,  "Medium": 25,  "Hard": 35}   # Target Mode: apples to catch to complete
DURATION     = {"Easy": 60,  "Medium": 50,  "Hard": 40}   # Timed Mode: session length in seconds

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
# (type name, asset filename, points, probability among apples -- the three
# probabilities sum to 1.0). A fresh independent roll each spawn.
APPLE_TYPES = [
    ("normal",  "normal_apple_apple_catching.png",  1, 0.60),
    ("golden",  "golden_apple_apple_catching.png",  3, 0.30),
    ("rainbow", "rainbow_apple_apple_catching.png", 5, 0.10),
]
INSECT_TYPES = [
    ("caterpillar", "caterpillar_apple_catching.png"),
    ("ladybug",     "ladybug_apple_catching.png"),
    ("wasp",        "wasp_apple_catching.png"),
]
INSECT_POINTS = 3
# Insects are a separate category layered on top of the apple draw above
# (the spec gives apple tiers explicit probabilities but no insect
# probability) -- each spawn has this independent chance of being an insect
# instead of rolling an apple tier at all.
INSECT_SPAWN_CHANCE = 0.15

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
        self._session_init(data, APPLE_GOAL, DURATION, self.difficulty, cal_goal_key="ac_goal")

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
                              for name, fname, _, _ in APPLE_TYPES}
        self._insect_imgs = {name: _load_image_fit(fname, *INSECT_SIZE)
                              for name, fname in INSECT_TYPES}

        self._catch_sound = _load_sound("catch_sound_effect.wav")

        self._font_hud = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 24)

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
        self.paused      = False
        self.pause_sel   = 0
        self.score       = 0
        self.reps        = 0
        self._session_reset()
        self.start_time  = pygame.time.get_ticks()
        self.basket_x    = float(GAME_W // 2)
        self.caught_active = False
        self.caught_timer  = 0.0
        self._basket_opening_rect = pygame.Rect(0, 0, 1, 1)
        self._spawn_object()

        self.shaking      = False
        self.shake_timer   = 0.0
        self.shake_offset = 0

        self._state = {"tilt_x": 0.0}

    def _spawn_object(self):
        """Pick the next falling object -- an apple tier (60/30/10 -> +1/+3/+5)
        or, independently, an insect (+3) -- and its spawn position. An
        apple's rotation is rolled fresh here and then held fixed for as
        long as it falls (see update(), which never touches obj_angle
        again); insects are not rotated, per spec."""
        if random.random() < INSECT_SPAWN_CHANCE:
            name, _ = random.choice(INSECT_TYPES)
            self.obj_kind   = "insect"
            self.obj_type   = name
            self.obj_points = INSECT_POINTS
            base_img        = self._insect_imgs.get(name)
            self.obj_angle  = 0.0
        else:
            r, cum, chosen = random.random(), 0.0, APPLE_TYPES[-1]
            for tier in APPLE_TYPES:
                cum += tier[3]
                if r < cum:
                    chosen = tier
                    break
            name, _, points, _ = chosen
            self.obj_kind   = "apple"
            self.obj_type   = name
            self.obj_points = points
            base_img        = self._apple_imgs.get(name)
            self.obj_angle  = random.uniform(0.0, 360.0)

        # Rotate once per spawn (not per frame) around the unrotated image's
        # own center -- pygame.transform.rotate's returned surface is
        # re-centered automatically, so blitting it via get_rect(center=..)
        # keeps the apple's position from shifting when it is rotated.
        if base_img is not None and self.obj_angle:
            self.obj_draw_img = pygame.transform.rotate(base_img, self.obj_angle)
        else:
            self.obj_draw_img = base_img

        draw_w = self.obj_draw_img.get_width()  if self.obj_draw_img is not None else APPLE_SIZE[0]
        draw_h = self.obj_draw_img.get_height() if self.obj_draw_img is not None else APPLE_SIZE[1]
        # Clamp to the ROTATED (possibly wider) bounding box so a
        # diagonally-rotated apple can never spawn clipped off-screen.
        self.obj_x = float(random.randint(0, max(0, GAME_W - draw_w)))
        self.obj_y = -float(draw_h)

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

    def _obj_rect(self):
        img = self.obj_draw_img
        w = img.get_width()  if img is not None else APPLE_SIZE[0]
        h = img.get_height() if img is not None else APPLE_SIZE[1]
        return pygame.Rect(int(self.obj_x), int(self.obj_y), w, h)

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
            if (event.type == pygame.KEYDOWN or
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
        if self._show_instructions or self.game_over:
            return

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        if self._session_tick(dt):
            self._end_game()
            return

        if input_handler.connected:
            tilt_norm = self._normalize_tilt(self._state["tilt_x"])
            self.basket_x += self.move_speed * dt * tilt_norm
        else:
            tx = self._state["tilt_x"]
            if abs(tx) > 0.1:
                self.basket_x += self.move_speed * dt * tx
        self.basket_x = max(BASKET_SIZE[0]//2,
                             min(GAME_W - BASKET_SIZE[0]//2, self.basket_x))

        basket_rect = self._basket_rect()
        self._basket_opening_rect = self._opening_rect(basket_rect)

        if self.caught_active:
            # The caught object stays glued to the basket (see draw()'s
            # _caught_draw_pos, keyed off basket_rect) instead of falling,
            # so it never visually drops through the bottom, until the
            # catching animation finishes.
            self.caught_timer -= dt
            if self.caught_timer <= 0:
                self.caught_active = False
                self._spawn_object()
        else:
            self.obj_y += self.apple_speed * dt
            obj_rect = self._obj_rect()

            if self._basket_opening_rect.colliderect(obj_rect):
                self.score += self.obj_points
                self.reps  += 1
                self.caught_active = True
                self.caught_timer  = CATCH_HOLD_DURATION
                # Catch sound plays for apples only -- insects are caught
                # silently (per spec).
                if self.obj_kind == "apple" and self._catch_sound:
                    self._catch_sound.play()
                if self._session_target_reached():
                    self._end_game()
                    return
            elif self.obj_y > GAME_H:
                # Missed -- it simply falls out of view and is replaced, no
                # sound/blast effect (removed per spec). The basket shake is
                # an apple-miss cue only -- insects were never meant to be
                # caught, so missing one isn't a "miss" and shouldn't shake
                # the basket. Read obj_kind BEFORE respawning, since
                # _spawn_object() immediately overwrites it for the next one.
                missed_kind = self.obj_kind
                self._spawn_object()
                if missed_kind == "apple":
                    self.shaking     = True
                    self.shake_timer = SHAKE_DURATION

        if self.shaking:
            self.shake_timer -= dt
            if self.shake_timer > 0:
                self.shake_offset = random.randint(-6, 6)
            else:
                self.shaking      = False
                self.shake_offset = 0

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

        # ...then the falling/caught object, so a caught one is sandwiched
        # behind the front rim (see item 3 of the spec: behind front, in
        # front of back)...
        if self.obj_draw_img is not None:
            if self.caught_active:
                r = self.obj_draw_img.get_rect(center=self._caught_draw_pos(basket_rect))
                surface.blit(self.obj_draw_img, r)
            else:
                surface.blit(self.obj_draw_img, (int(self.obj_x), int(self.obj_y)))

        # ...then the front rim on top, so it occludes a caught object
        # exactly like the real rim would.
        if self._basket_front_img is not None:
            surface.blit(self._basket_front_img, basket_rect)

        draw_game_header(surface, "Apple Catching", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        prog_s = font_sm.render(self._session_progress_text("apples"), True, T["TEXT"])
        surface.blit(prog_s, (int(40 * GAME_W / 1920), HEADER_BOTTOM + int(20 * GAME_H / 1080)))

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

        surface.blit(font_sm.render(
            "Tilt wrist LEFT/RIGHT to move basket",
            True, T["GRAY"]), (GAME_W // 2 - 220, GAME_H - 50))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 860, 540
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (252,), (0, 0, pw, ph), border_radius=16)
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, T["ACCENT"], pygame.Rect(px, py, pw, ph), 2, border_radius=16)

        f_title = pygame.font.SysFont("monospace", 36, bold=True)
        f_head  = pygame.font.SysFont("monospace", 22, bold=True)
        f_body  = pygame.font.SysFont("monospace", 19)

        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        title = f_title.render("How to Play", True, diff_col)
        surface.blit(title, title.get_rect(centerx=GAME_W // 2, top=py + 26))
        pygame.draw.line(surface, T["ACCENT"], (px + 40, py + 78), (px + pw - 40, py + 78), 1)

        y = py + 96
        for header, lines in [
            ("OBJECTIVE", [
                "Apples fall from the top of the screen.",
                "Move the basket underneath to catch them and score.",
                "Normal +1  •  Golden +3  •  Rainbow +5  •  Insects +3",
            ]),
            ("CONTROLS", [
                "Tilt wrist LEFT / RIGHT to move the basket.",
            ]),
            ("THIS SESSION", [
                (f"Goal:       Catch {self.goal} apples" if self.session_mode == "target" else
                 f"Duration:   {int(self.timed_duration)} seconds — catch as many apples as you can"),
                f"Difficulty: {self.difficulty}",
            ]),
        ]:
            surface.blit(f_head.render(header, True, T["ACCENT"]), (px + 48, y))
            y += 30
            for line in lines:
                surface.blit(f_body.render(line, True, T["TEXT"]), (px + 64, y))
                y += 26
            y += 14
        # No "press any key" prompt -- the patient never starts the game
        # themselves, only the therapist's own START control does.

    def _draw_results(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        card_name = f"apple_catch_round_complete_{'dark' if is_dark_mode() else 'light'}.png"
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
