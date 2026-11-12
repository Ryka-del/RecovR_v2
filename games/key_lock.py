"""
Key & Lock — Wrist Rotation game (1920x1080)

Mechanic:
  - One lock hangs on the stone archway at a time -- 80% Normal (Blue/Pink/
    Green, +1 point), 20% Legendary (Glowing Purple, +5 points), rolled once
    per round and fixed for that round's entire sequence of turns.
  - A matching key hangs in front of it, tip "inserted" at the keyhole. Wrist
    rotation (MPU6050, calibrated) turns the key: a fresh target angle is
    rolled for each turn, alternating left/right where possible. Reaching
    the target angle (within the difficulty's tolerance) and holding it for
    HOLD_TIME continuous seconds completes that turn; leaving the tolerance
    zone resets hold progress to zero instantly. The patient must return to
    neutral before the next turn can begin (reusing this codebase's
    "_need_release" edge-detection idiom, applied to wrist angle instead of
    grip/flex).
  - Completing every required turn (difficulty + lock-type dependent) opens
    the lock: a brief glow/animation plays, points are awarded exactly once,
    and the next round's lock+key pair is chosen.

Visual key rotation: the key is drawn procedurally (see _draw_key) rather
than as a sprite, so it can show a genuine twist instead of a flat swing.
It's treated as a flat 3D card spinning around its own LONGITUDINAL axis --
the vertical line running from tip to bow, which is exactly where the key's
local origin sits. Rotating a flat object around an axis that lies ON it
means every point on that axis stays put (the tip never moves off the
keyhole) while everything OFF that axis (the width of the shaft and bow)
visually foreshortens toward the viewer, collapsing to an edge-on sliver at
90/270 degrees and reappearing mirrored (the "back" of the key) past 90
degrees -- exactly how a real object looks when twisted around an axis
pointing at the camera, and NOT a flat pygame.transform.rotate of a whole
sprite (which would swing the tip away from the keyhole and never looks
like a genuine twist). Implemented as a horizontal-only scale by
cos(current_angle) applied to every local point/circle before it's drawn
(cos's own sign handles the mirror once it goes negative, with no separate
flip needed); height (the tip-to-bow extent, along the rotation axis) never
changes. Gameplay's wrist range is the calibrated +/-90 degrees set by
MAX_DISPLAY_ANGLE (TARGET_ANGLE_RANGE/TOLERANCE are unaffected -- they're
well within it) -- the full 0-360 degree behaviour only shows up if
current_angle is driven past that range (e.g. directly, for verification).
"""

import os
import random
import math
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler
from audio import (play_success, play_click, play_completion, start_music, stop_music,
                    pause_music, resume_music, game_bgm_path)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.hud import draw_target_pill, TARGET_POS
from games.round_complete import draw_round_complete_overlay

# ── difficulty-scaled parameters ────────────────────────────────────────────
TOLERANCE  = {"Easy": 15, "Medium": 8, "Hard": 3}     # degrees -- how close to the target counts as aligned
LOCK_GOAL  = {"Easy": 10, "Medium": 15, "Hard": 20}   # Target Mode: LOCKS (not turns) to open to complete
DURATION   = {"Easy": 60, "Medium": 50, "Hard": 40}   # Timed Mode: session length in seconds
HOLD_TIME_DEFAULT = 2.0   # seconds -- uniform per spec ("2 continuous seconds"), overridable via kl_hold_time
NEUTRAL_TOLERANCE  = 6    # degrees -- how close to 0 counts as "back at neutral" between turns
TEST_RAMP_RATE     = 0.5  # normalized units/second (-1..1 range) -- Keyboard Test Mode's
                           # LEFT/RIGHT ramp speed; reaches full deflection in ~2s of holding

# Magnitude range (degrees) a turn's target angle is rolled from -- always
# comfortably inside the +/-90 degree calibrated display range (see
# MAX_DISPLAY_ANGLE), so a generated target is never unreachable.
TARGET_ANGLE_RANGE = {"Easy": (15, 28), "Medium": (20, 34), "Hard": (26, 42)}
MAX_DISPLAY_ANGLE  = 90.0   # the gauge's own +/-90 degree span; also the degrees-per-normalized-unit scale

TURNS_REQUIRED = {
    "Easy":   {"normal": 1, "legendary": 3},
    "Medium": {"normal": 2, "legendary": 4},
    "Hard":   {"normal": 3, "legendary": 5},
}

LEGENDARY_CHANCE = 0.20
POINTS           = {"normal": 1, "legendary": 5}

LEGENDARY_POPUP_DURATION = 1.8
UNLOCK_ANIM_DURATION     = 1.3

# (lock asset, color name) -- rolled once per Normal round. The key is no
# longer an asset (see _draw_key) -- it's drawn procedurally, in the same
# color as its matching lock.
NORMAL_PAIRS = [
    ("lock1_key_and_lock.png", "Pink"),
    ("lock2_key_and_lock.png", "Green"),
    ("lock3_key_and_lock.png", "Blue"),
]
LEGENDARY_PAIR = ("legend_lock_key_and_lock.png", "Purple")

# Procedural key colors -- brushed-gold metal (matching the lock art) plus a
# color-coded gem, same pairing as the original key sprites.
KEY_GOLD        = (235, 185, 55)
KEY_GOLD_LIGHT  = (255, 225, 140)
KEY_GOLD_DARK   = (62, 40, 8)   # darker + thicker outline -- see _draw_key
KEY_SHINE       = (255, 250, 225)  # small specular highlights -- "shines like the lock"
KEY_GEM_COLORS  = {
    "Pink":   (255, 45, 165),
    "Green":  (35, 235, 110),
    "Blue":   (40, 150, 255),
    "Purple": (190, 80, 255),
}

LOCK_BOX = (320, 460)

LOCK_X = GAME_W // 2
# Leaves room above for the turn-progress dots, and keeps the key (which
# hangs down from the keyhole, roughly another ~290px) from reaching too
# far into the lower gauge area.
LOCK_Y = HEADER_BOTTOM + 95

# Key rotation (see module docstring) -- the art's own tip-to-head axis
# IS the longitudinal rotation axis, so no base re-orientation is needed.

GAUGE_CENTER = (GAME_W // 2, GAME_H - 90)   # lower on screen -- more breathing
                                             # room above it (see _draw_gauge)
GAUGE_RADIUS = 145

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}


def _load_image_fit(name, w, h):
    """Crop to the asset's own opaque content, then scale to fit within
    w x h preserving its aspect ratio. Returns None if missing so a caller
    can skip drawing instead of crashing."""
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


def _keyhole_center_frac(name):
    """Where the lock's own keyhole sits, as a (fx, fy) fraction of its
    cropped content -- the DARK, near-black interior of the keyhole is
    detected directly from the art (restricted to the central band, to
    avoid picking up unrelated dark trim elsewhere on the lock) rather than
    assumed from the sprite's geometric center."""
    key = ("keyhole", name)
    if key in _img_cache:
        return _img_cache[key]
    try:
        raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
        br = raw.get_bounding_rect(min_alpha=10)
        w, h = br.width, br.height
        xs, ys = [], []
        for y in range(int(h * 0.35), int(h * 0.80)):
            for x in range(int(w * 0.25), int(w * 0.75)):
                r, g, b, a = raw.get_at((br.x + x, br.y + y))
                if a > 200 and r < 60 and g < 60 and b < 60:
                    xs.append(x)
                    ys.append(y)
        frac = (sum(xs) / len(xs) / w, sum(ys) / len(ys) / h) if xs else (0.5, 0.58)
    except Exception:
        frac = (0.5, 0.58)
    _img_cache[key] = frac
    return frac


class KeyLockGame(SessionModeMixin, FatigueMixin, BaseScreen):
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
        self._session_init(data, LOCK_GOAL, DURATION, self.difficulty, cal_goal_key="kl_goal")
        self.tolerance   = cal_params.get("kl_tolerance", TOLERANCE[self.difficulty])
        self.hold_time   = cal_params.get("kl_hold_time", HOLD_TIME_DEFAULT)

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self.vol_active = False
        self.pause_vol  = 0.4
        self._font_hud     = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_target  = pygame.font.SysFont("monospace", 54, bold=True)
        self._font_sm      = pygame.font.SysFont("monospace", 24)
        self._font_fb      = pygame.font.SysFont("monospace", 46, bold=True)
        self._font_gauge   = pygame.font.SysFont("monospace", 40, bold=True)
        self._font_panel_l = pygame.font.SysFont("monospace", 30, bold=True)
        self._font_panel_n = pygame.font.SysFont("monospace", 44, bold=True)

        self._bg_img = _load_image_cover("bg_key_and_lock.png", GAME_W, GAME_H)
        self._legendary_popup_img = _load_image_fit("legendary_key_and_lock.png", 760, 260)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True
        self._pause_btn_rect    = pygame.Rect(GAME_W - 90, HEADER_BOTTOM + 14, 70, 46)

    def _reset(self):
        self._init_fatigue()
        self.paused     = False
        self.pause_sel  = 0
        self.game_over  = False
        self.score      = 0
        self.reps       = 0        # = locks fully opened this session
        self._session_reset()
        self.start_time = pygame.time.get_ticks()

        self._tilt_smooth  = 0.0
        self.current_angle = 0.0
        self._test_tilt_raw = 0.0   # Keyboard Test Mode's own gradual LEFT/RIGHT ramp (-1..1)

        self.streak = 0
        self.phase  = "legendary_popup"   # "legendary_popup" | "playing" | "unlocking"
        self.legendary_popup_t = 0.0
        self.unlock_t = 0.0
        self.last_round_points = 0

        self.feedback = None
        self._state   = {"tilt_x": 0.0}

        self._last_pair_idx = None
        self._spawn_round()

    # ── round / turn setup ──────────────────────────────────────────────

    def _spawn_round(self):
        if random.random() < LEGENDARY_CHANCE:
            lock_name, color = LEGENDARY_PAIR
            self.lock_type = "legendary"
        else:
            idx = random.randrange(len(NORMAL_PAIRS))
            if len(NORMAL_PAIRS) > 1:
                while idx == self._last_pair_idx:
                    idx = random.randrange(len(NORMAL_PAIRS))
            self._last_pair_idx = idx
            lock_name, color = NORMAL_PAIRS[idx]
            self.lock_type = "normal"

        self.color_name  = color
        self._lock_img = _load_image_fit(lock_name, *LOCK_BOX)
        kf = _keyhole_center_frac(lock_name)
        lock_rect = self._lock_img.get_rect(midtop=(LOCK_X, LOCK_Y)) if self._lock_img is not None \
            else pygame.Rect(0, 0, *LOCK_BOX)
        self.keyhole_pos = (lock_rect.left + kf[0] * lock_rect.width,
                             lock_rect.top + kf[1] * lock_rect.height)
        self.lock_rect = lock_rect

        self.turns_required = TURNS_REQUIRED[self.difficulty][self.lock_type]
        self.turns_done = 0
        self._last_sign = 0
        self._need_neutral = False
        self.hold_timer = 0.0
        self._pick_next_target()

        if self.lock_type == "legendary":
            self.phase = "legendary_popup"
            self.legendary_popup_t = LEGENDARY_POPUP_DURATION
        else:
            self.phase = "playing"

    def _pick_next_target(self):
        lo, hi = TARGET_ANGLE_RANGE[self.difficulty]
        mag = random.uniform(lo, hi)
        sign = -self._last_sign if self._last_sign != 0 else random.choice([-1, 1])
        self._last_sign = sign
        self.target_angle = sign * mag
        self.hold_timer = 0.0

    def _normalize_tilt(self, raw):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return raw
        return max(-1.0, min(1.0, (raw - wmin) / (wmax - wmin) * 2.0 - 1.0))

    def _test_mode_tilt_x(self, dt):
        """Keyboard Test Mode's own gradual LEFT/RIGHT ramp, independent of
        input_handler's instant -1/0/+1 keyboard fallback. Holding a key
        ramps _test_tilt_raw toward +/-1 at a constant, frame-rate-
        independent rate; releasing freezes it in place (no snap back to
        0); the opposite key ramps it back down through 0 and on into the
        other direction. Real MPU6050 input never calls this -- see
        update()'s input_handler.connected branch."""
        keys = pygame.key.get_pressed()
        d = 0.0
        if keys[pygame.K_RIGHT]:
            d += 1.0
        if keys[pygame.K_LEFT]:
            d -= 1.0
        self._test_tilt_raw = max(-1.0, min(1.0, self._test_tilt_raw + d * TEST_RAMP_RATE * dt))
        return self._test_tilt_raw

    # ── events ───────────────────────────────────────────────────────────

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Key and Lock"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Key and Lock"))
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
            lambda: (self._reset(), start_music(game_bgm_path("Key and Lock"))),
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
        if self.fatigue_paused or self.paused: return

        if self._session_tick(dt):
            self._end_game("completed")
            return

        raw_tilt_x = self._state["tilt_x"] if input_handler.connected else self._test_mode_tilt_x(dt)
        tx = self._normalize_tilt(raw_tilt_x)
        smooth_k = min(1.0, dt * 10.0)
        self._tilt_smooth += (tx - self._tilt_smooth) * smooth_k
        self.current_angle = self._tilt_smooth * MAX_DISPLAY_ANGLE

        if self.phase == "legendary_popup":
            self.legendary_popup_t -= dt
            if self.legendary_popup_t <= 0:
                self.phase = "playing"

        elif self.phase == "playing":
            dist    = abs(self.current_angle - self.target_angle)
            aligned = dist <= self.tolerance

            if self._need_neutral:
                self.hold_timer = 0.0
                if abs(self.current_angle) <= NEUTRAL_TOLERANCE:
                    self._need_neutral = False
            elif aligned:
                self.hold_timer += dt
                if self.hold_timer >= self.hold_time:
                    self._complete_turn()
            else:
                self.hold_timer = 0.0

        elif self.phase == "unlocking":
            self.unlock_t -= dt
            if self.unlock_t <= 0:
                self._after_unlock()

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None

    def _complete_turn(self):
        self.turns_done += 1
        self._need_neutral = True
        self.hold_timer = 0.0
        if self.turns_done >= self.turns_required:
            play_success()
            self.phase = "unlocking"
            self.unlock_t = UNLOCK_ANIM_DURATION
            self.last_round_points = POINTS[self.lock_type]
        else:
            play_click()
            self._pick_next_target()

    def _after_unlock(self):
        self.score += self.last_round_points
        self.reps  += 1   # one lock fully opened
        self.streak += 1
        self.feedback = (f"+{self.last_round_points}",
                          (180, 120, 255) if self.lock_type == "legendary" else (255, 210, 60),
                          1.1)
        if self._session_target_reached():
            self._end_game("completed")
            return
        self._spawn_round()

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
                game           = "Key and Lock",
                score          = self.score,
                difficulty     = self.difficulty,
                status         = status,
                **self._session_result_fields(),
            )
        except Exception:
            pass

    def _end_game(self, status="completed"):
        if self.game_over:
            return
        stop_music()
        play_completion()
        self.game_over_duration = int(round(self.elapsed))
        self.game_over_score    = self.score
        self._save_session(status=status)
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

        self._draw_lock(surface)
        if self.phase != "unlocking":   # key is removed while the lock breaks open and fades
            self._draw_key(surface)
        self._draw_turn_progress(surface)

        if self.phase == "playing":
            self._draw_angle_panels(surface)
            self._draw_gauge(surface)
            self._draw_hold_indicator(surface)

        if self.phase == "legendary_popup" and self._legendary_popup_img is not None:
            r = self._legendary_popup_img.get_rect(center=(GAME_W // 2, 300))
            surface.blit(self._legendary_popup_img, r)

        draw_game_header(surface, "Key and Lock", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        prog_bg = draw_target_pill(surface, self._session_progress_text("locks"),
                                    TARGET_POS, T["ACCENT"], self._font_target)

        if self.streak >= 2:
            streak_s = font_sm.render(f"{self.streak}-Lock Streak", True, T["YELLOW"])
            surface.blit(streak_s, (prog_bg.left, prog_bg.bottom + 10))

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

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, msg.get_rect(center=(self.lock_rect.centerx, self.lock_rect.top - 40)))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_lock(self, surface):
        if self._lock_img is None:
            return

        if self.phase == "unlocking":
            # frac: 0 at the instant it unlocks -> 1 at the end of the
            # animation. The lock splits into its two halves, which drift
            # apart and fade out together -- this is the ONLY lock drawing
            # during "unlocking"; the whole/unsplit lock never reappears
            # until the next round's _spawn_round() swaps in a fresh pair.
            frac = 1.0 - max(0.0, min(1.0, self.unlock_t / UNLOCK_ANIM_DURATION))
            col = (190, 110, 255) if self.lock_type == "legendary" else (255, 215, 90)
            glow_amt = 1.0 - frac
            if glow_amt > 0:
                glow = pygame.Surface((self.lock_rect.width + 80, self.lock_rect.height + 80), pygame.SRCALPHA)
                pygame.draw.ellipse(glow, (*col, int(140 * glow_amt)), glow.get_rect())
                surface.blit(glow, glow.get_rect(center=self.lock_rect.center))

            w, h = self._lock_img.get_size()
            half_w = w // 2
            left_half  = self._lock_img.subsurface((0, 0, half_w, h)).copy()
            right_half = self._lock_img.subsurface((half_w, 0, w - half_w, h)).copy()

            sep   = int(frac * 70)
            alpha = int(255 * (1.0 - frac))
            left_half.set_alpha(alpha)
            right_half.set_alpha(alpha)

            cx, cy = self.lock_rect.center
            surface.blit(left_half,  left_half.get_rect(midright=(cx - sep, cy)))
            surface.blit(right_half, right_half.get_rect(midleft=(cx + sep, cy)))
            return

        surface.blit(self._lock_img, self._lock_img.get_rect(center=self.lock_rect.center))

    # Procedural key -- replaces the old key1/2/3/legend_key sprites so the
    # key can show genuine foreshortening (see module docstring) instead of
    # a rigid sprite swing. Drawn fresh every frame as plain gold shapes in
    # the key's own LOCAL coordinates (origin = the tip, +y running down
    # the shaft toward the bow, exactly the sprites' own layout/angle), each
    # point/circle transformed by the same screen-space rule: x compresses
    # by cos(current_angle) (the shaft/bow's width, perpendicular to the
    # rotation axis) while y (along the axis) never changes, and the tip
    # (local 0,0) always lands exactly on self.keyhole_pos. Because it's
    # redrawn from this fixed local model every frame rather than rotating a
    # pre-lit bitmap, there's no baked-in highlight to look wrong at an
    # angle -- the shaft's sheen stripe is just part of the same rotating
    # geometry, so it reads as real metal turning in place.
    def _draw_key(self, surface):
        cs = math.cos(math.radians(self.current_angle))
        kx, ky = self.keyhole_pos

        def pt(x, y):
            return (kx + x * cs, ky + y)

        def poly(points, fill, outline=None, owidth=6):
            p = [pt(x, y) for x, y in points]
            pygame.draw.polygon(surface, fill, p)
            if outline:
                pygame.draw.polygon(surface, outline, p, owidth)

        def circle(cx_, cy_, r, fill=None, owidth=0, ring=0):
            w = max(2, int(round(2 * r * abs(cs))))
            h = int(round(2 * r))
            rect = pygame.Rect(0, 0, w, h)
            rect.center = pt(cx_, cy_)
            if ring:
                pygame.draw.ellipse(surface, fill, rect, ring)
                # Outline both edges of the ring (not just the flat fill) so
                # it reads as a distinct outlined band, not a soft blob.
                pygame.draw.ellipse(surface, KEY_GOLD_DARK, rect, 5)
                inner = rect.inflate(-2 * ring, -2 * ring)
                if inner.width > 2 and inner.height > 2:
                    pygame.draw.ellipse(surface, KEY_GOLD_DARK, inner, 5)
            else:
                pygame.draw.ellipse(surface, fill, rect)
                if owidth:
                    pygame.draw.ellipse(surface, KEY_GOLD_DARK, rect, owidth)

        def shine(cx_, cy_, w_, h_, ang_deg=-35):
            # A small bright specular streak -- a thin rotated ellipse --
            # the same "glossy highlight" trick the lock's own art already
            # uses, so the procedural key reads as shiny metal too, not
            # flat paint. Width compresses with the key's own foreshortening
            # (abs(cs)) like every other shape here.
            w_ = max(2, int(round(w_ * abs(cs))))
            surf = pygame.Surface((w_, h_), pygame.SRCALPHA)
            pygame.draw.ellipse(surf, (*KEY_SHINE, 235), surf.get_rect())
            surf = pygame.transform.rotate(surf, ang_deg)
            r = surf.get_rect(center=pt(cx_, cy_))
            surface.blit(surf, r)

        gem = KEY_GEM_COLORS.get(self.color_name, KEY_GOLD_LIGHT)

        if self.lock_type == "legendary":
            for r, a in ((95, 35), (72, 55), (50, 80)):
                w = max(2, int(round(2 * r * abs(cs))))
                h = int(round(2 * r))
                glow = pygame.Surface((w, h), pygame.SRCALPHA)
                pygame.draw.ellipse(glow, (*gem, a), glow.get_rect())
                surface.blit(glow, glow.get_rect(center=pt(0, 150)))

        SHAFT_W = 15
        # shaft + rounded tip cap
        poly([(-SHAFT_W, 0), (SHAFT_W, 0), (SHAFT_W, 150), (-SHAFT_W, 150)],
             KEY_GOLD, KEY_GOLD_DARK)
        poly([(-4, 0), (2, 0), (2, 150), (-4, 150)], KEY_GOLD_LIGHT)   # sheen stripe
        circle(0, 10, 16, KEY_GOLD, owidth=6)
        shine(-5, 3, 10, 16)

        # single flag-like tooth/bit, sticking left off the shaft
        poly([(-SHAFT_W, 48), (-33, 48), (-33, 66), (-SHAFT_W, 66)], KEY_GOLD, KEY_GOLD_DARK)
        poly([(-SHAFT_W, 70), (-26, 70), (-26, 85), (-SHAFT_W, 85)], KEY_GOLD, KEY_GOLD_DARK)

        # small gem collar above the bow
        poly([(0, 93), (20, 112), (0, 131), (-20, 112)], gem, KEY_GOLD_DARK, owidth=5)
        shine(-6, 105, 8, 12)
        circle(0, 145, 23, KEY_GOLD, ring=16)
        shine(-10, 136, 12, 18)

        # ornate bow -- three gold rings (quatrefoil-ish) + bead accents +
        # a larger central gem, echoing the original art's bow shape
        circle(-39, 206, 38, KEY_GOLD, ring=22)
        shine(-50, 192, 16, 22)
        circle(39, 206, 38, KEY_GOLD, ring=22)
        shine(28, 192, 16, 22)
        circle(0, 245, 31, KEY_GOLD, ring=18)
        shine(-10, 235, 12, 16)
        for bx, by, r in ((-20, 172, 9), (20, 172, 9), (0, 157, 9), (-20, 242, 8), (20, 242, 8)):
            circle(bx, by, r, KEY_GOLD, owidth=4)
        poly([(0, 173), (33, 206), (0, 239), (-33, 206)], gem, KEY_GOLD_DARK, owidth=6)
        shine(-8, 196, 10, 14)

    def _draw_angle_panels(self, surface):
        """Current Angle (left of the lock) / Target Angle (right) -- kept
        beside the lock itself (not the lower gauge) so they stay readable
        regardless of how far down the key currently hangs."""
        T = get_theme()
        dist = abs(self.current_angle - self.target_angle)
        if dist <= self.tolerance:
            cur_col = T["GREEN"]
        elif dist <= self.tolerance * 2.2:
            cur_col = T["YELLOW"]
        else:
            cur_col = T["ACCENT"]
        cy = self.lock_rect.centery

        def panel(cx, label, value, val_col):
            # The label always sits on a fixed dark-navy chip background
            # regardless of theme (so it reads against any background art),
            # so its own color must be fixed-light too -- T["TEXT"] is
            # near-black in Light theme (the product default) and was
            # nearly invisible here.
            lbl_s = self._font_panel_l.render(label, True, (225, 232, 245))
            val_s = self._font_panel_n.render(value, True, val_col)
            w = max(lbl_s.get_width(), val_s.get_width()) + 36
            h = lbl_s.get_height() + val_s.get_height() + 26
            box = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(box, (15, 20, 36, 195), box.get_rect(), border_radius=14)
            pygame.draw.rect(box, T["ACCENT"], box.get_rect(), 4, border_radius=14)
            box.blit(lbl_s, lbl_s.get_rect(centerx=w // 2, top=12))
            box.blit(val_s, val_s.get_rect(centerx=w // 2, top=16 + lbl_s.get_height()))
            surface.blit(box, box.get_rect(center=(cx, cy)))

        panel(self.lock_rect.left - 190, "Current Angle", f"{self.current_angle:+.0f}°", cur_col)
        panel(self.lock_rect.right + 190, "Target Angle", f"{self.target_angle:+.0f}°", T["YELLOW"])

    def _draw_turn_progress(self, surface):
        T = get_theme()
        n = self.turns_required
        r = 16
        gap = 16
        total_w = n * (r * 2) + (n - 1) * gap
        x0 = self.lock_rect.centerx - total_w // 2
        y = self.lock_rect.top - 38
        for i in range(n):
            cx = x0 + r + i * (r * 2 + gap)
            done = i < self.turns_done
            col = T["GREEN"] if done else T["PANEL"]
            pygame.draw.circle(surface, col, (cx, y), r)
            pygame.draw.circle(surface, T["ACCENT"], (cx, y), r, 4)
        lbl = self._font_panel_l.render(f"{self.turns_done} / {n} Turns", True, T["TEXT"])
        surface.blit(lbl, lbl.get_rect(centerx=self.lock_rect.centerx, bottom=y - r - 4))

    def _draw_gauge(self, surface):
        T = get_theme()
        cx, cy = GAUGE_CENTER
        r = GAUGE_RADIUS

        def ang_to_pt(deg, radius):
            # -90 at left, 0 at top, +90 at right
            a = math.radians(-90 + deg)
            return (cx + radius * math.cos(a), cy + radius * math.sin(a))

        # Dark backing panel -- the dial used to sit directly on the (often
        # busy) background art with nothing behind it; a fixed-dark card,
        # same family as the angle panels/HUD pill elsewhere, makes the
        # whole gauge read as one deliberate instrument instead of loose
        # lines floating over the scene.
        pad_x, pad_top, pad_bot = 110, 95, 35
        panel = pygame.Rect(cx - r - pad_x, cy - r - pad_top, 2 * (r + pad_x), r + pad_top + pad_bot)
        panel_s = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(panel_s, (15, 20, 36, 200), panel_s.get_rect(), border_radius=24)
        surface.blit(panel_s, panel.topleft)
        pygame.draw.rect(surface, KEY_GOLD_DARK, panel, 4, border_radius=24)

        # Background track -- the dial's full -90..+90 sweep, drawn via the
        # same ang_to_pt mapping as everything else on this gauge (NOT
        # pygame.draw.arc's own angle convention, which sweeps the opposite
        # half of the circle and used to render a disconnected sliver below
        # the dial instead of the track actually under the numbers/needle).
        # Gold, not a generic gray -- matches the key/lock's own metal, and
        # thick enough (18px, a dark-gold base stroke under a slightly
        # narrower bright-gold one) to read as a real dial groove.
        track_pts = [ang_to_pt(d, r) for d in range(-90, 91, 2)]
        pygame.draw.lines(surface, KEY_GOLD_DARK, False, track_pts, 18)
        pygame.draw.lines(surface, KEY_GOLD, False, track_pts, 12)

        # acceptable tolerance band around the target
        band_pts = [ang_to_pt(d, r) for d in
                    range(int(self.target_angle - self.tolerance), int(self.target_angle + self.tolerance) + 1)]
        if len(band_pts) > 1:
            pygame.draw.lines(surface, T["YELLOW"], False, band_pts, 14)

        # target marker
        tx, ty = ang_to_pt(self.target_angle, r)
        pygame.draw.circle(surface, T["YELLOW"], (int(tx), int(ty)), 14)
        pygame.draw.circle(surface, KEY_GOLD_DARK, (int(tx), int(ty)), 14, 4)

        dist = abs(self.current_angle - self.target_angle)
        if dist <= self.tolerance:
            cur_col = T["GREEN"]
        elif dist <= self.tolerance * 2.2:
            cur_col = T["YELLOW"]
        else:
            cur_col = T["ACCENT"]

        # current-angle needle -- thicker, gold-outlined shaft with a small
        # diamond tip ornament (echoing the key's own gem motifs) instead of
        # a plain line, and a gold-rimmed hub.
        nx, ny = ang_to_pt(max(-90, min(90, self.current_angle)), r - 16)
        pygame.draw.line(surface, KEY_GOLD_DARK, (cx, cy), (int(nx), int(ny)), 16)
        pygame.draw.line(surface, cur_col, (cx, cy), (int(nx), int(ny)), 10)
        ang = math.atan2(ny - cy, nx - cx)
        tip_len = 16
        px, py = -math.sin(ang), math.cos(ang)
        diamond = [(nx + tip_len * math.cos(ang), ny + tip_len * math.sin(ang)),
                   (nx + 8 * px, ny + 8 * py),
                   (nx - tip_len * 0.4 * math.cos(ang), ny - tip_len * 0.4 * math.sin(ang)),
                   (nx - 8 * px, ny - 8 * py)]
        pygame.draw.polygon(surface, cur_col, diamond)
        pygame.draw.polygon(surface, KEY_GOLD_DARK, diamond, 3)
        pygame.draw.circle(surface, cur_col, (cx, cy), 14)
        pygame.draw.circle(surface, KEY_GOLD_DARK, (cx, cy), 14, 4)

        for deg, lbl in ((-90, "-90°"), (0, "0°"), (90, "+90°")):
            lx, ly = ang_to_pt(deg, r + 30)
            s = self._font_gauge.render(lbl, True, (225, 232, 245))
            surface.blit(s, s.get_rect(center=(int(lx), int(ly))))

    def _draw_hold_indicator(self, surface):
        T = get_theme()
        cx, cy = GAUGE_CENTER[0] + GAUGE_RADIUS + 200, GAUGE_CENTER[1] - 90
        ring_r = 60
        dist = abs(self.current_angle - self.target_angle)
        aligned = dist <= self.tolerance and not self._need_neutral

        pygame.draw.circle(surface, T["PANEL"], (cx, cy), ring_r, 9)
        if aligned:
            prog = min(1.0, self.hold_timer / self.hold_time)
            if prog > 0:
                arc_rect = pygame.Rect(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
                end_angle = -math.pi / 2 + 2 * math.pi * prog
                pygame.draw.arc(surface, T["GREEN"], arc_rect, -math.pi / 2, end_angle, 9)
            label = "Hold Steady"
            timer_s = f"{self.hold_timer:0.1f} / {self.hold_time:0.1f}s"
        elif self._need_neutral:
            label, timer_s = "Return to Neutral", None
        else:
            label, timer_s = "Hold", None

        lines = [self._font_panel_l.render(label, True, (255, 255, 255))]
        if timer_s:
            lines.append(self._font_panel_l.render(timer_s, True, (225, 225, 225)))
        chip_w = max(s.get_width() for s in lines) + 30
        chip_h = sum(s.get_height() for s in lines) + 18
        chip = pygame.Surface((chip_w, chip_h), pygame.SRCALPHA)
        pygame.draw.rect(chip, (15, 20, 36, 200), chip.get_rect(), border_radius=12)
        pygame.draw.rect(chip, T["ACCENT"], chip.get_rect(), 3, border_radius=12)
        yy = 9
        for s in lines:
            chip.blit(s, s.get_rect(centerx=chip_w // 2, top=yy))
            yy += s.get_height() + 2
        surface.blit(chip, chip.get_rect(centerx=cx, top=cy + ring_r + 14))

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
        card_name = f"key_and_lock_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
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
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="key_and_lock", duration_sec=self.game_over_duration,
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
