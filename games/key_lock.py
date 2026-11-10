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

Visual key rotation: the key is treated as a flat 3D card spinning around
its own LONGITUDINAL axis -- the vertical line running from tip to head,
which is exactly where the art's tip already sits. Rotating a flat object
around an axis that lies ON it means every point on that axis stays put
(the tip never moves off the keyhole) while everything OFF that axis (the
width of the shaft and head) visually foreshortens toward the viewer,
collapsing to an edge-on sliver at 90/270 degrees and reappearing mirrored
(the "back" of the key) past 90 degrees -- exactly how a real object looks
when twisted around an axis pointing at the camera, and NOT a flat
pygame.transform.rotate of the whole sprite (which would swing the tip
away from the keyhole and never looks like a genuine twist). Implemented
as a horizontal-only scale by cos(current_angle), with a horizontal flip
once cos goes negative to show the mirrored "back" half; height (the
tip-to-head extent, along the rotation axis) never changes. Gameplay's
wrist range stays the existing calibrated +/-45 degrees (TARGET_ANGLE_RANGE,
TOLERANCE, the gauge, etc. are all unchanged) -- the full 0-360 degree
behaviour only shows up if current_angle is driven past that range (e.g.
directly, for verification).
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
# comfortably inside the +/-45 degree calibrated display range (see
# MAX_DISPLAY_ANGLE), so a generated target is never unreachable.
TARGET_ANGLE_RANGE = {"Easy": (15, 28), "Medium": (20, 34), "Hard": (26, 42)}
MAX_DISPLAY_ANGLE  = 45.0   # the gauge's own +/-45 degree span; also the degrees-per-normalized-unit scale

TURNS_REQUIRED = {
    "Easy":   {"normal": 1, "legendary": 3},
    "Medium": {"normal": 2, "legendary": 4},
    "Hard":   {"normal": 3, "legendary": 5},
}

LEGENDARY_CHANCE = 0.20
POINTS           = {"normal": 1, "legendary": 5}

LEGENDARY_POPUP_DURATION = 1.8
UNLOCK_ANIM_DURATION     = 1.3

# (key asset, lock asset, color name) -- rolled once per Normal round.
NORMAL_PAIRS = [
    ("key1_key_and_lock.png", "lock1_key_and_lock.png", "Pink"),
    ("key2_key_and_lock.png", "lock2_key_and_lock.png", "Green"),
    ("key3_key_and_lock.png", "lock3_key_and_lock.png", "Blue"),
]
LEGENDARY_PAIR = ("legend_key_key_and_lock.png", "legend_lock_key_and_lock.png", "Purple")

KEY_BOX  = (190, 290)
LOCK_BOX = (320, 460)

LOCK_X = GAME_W // 2
# Leaves room above for the turn-progress dots, and keeps the key (which
# hangs down from the keyhole, roughly another ~290px) from reaching too
# far into the lower gauge area.
LOCK_Y = HEADER_BOTTOM + 95

# Key rotation (see module docstring) -- the art's own tip-to-head axis
# IS the longitudinal rotation axis, so no base re-orientation is needed.

GAUGE_CENTER = (GAME_W // 2, GAME_H - 120)
GAUGE_RADIUS = 110

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


def _key_tip_frac(name):
    """Horizontal fraction (0-1) across the key's own cropped bounding box
    where its tip -- the topmost few rows of opaque content, the end that
    inserts into the keyhole -- actually sits. Measured directly from the
    art rather than assumed to be the bounding box's horizontal centre,
    since the much wider ornate bow at the other end can pull the overall
    bounding box off-centre relative to the narrow shaft/tip."""
    key = ("keytip", name)
    if key in _img_cache:
        return _img_cache[key]
    try:
        raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
        br = raw.get_bounding_rect(min_alpha=10)
        w, h = br.width, br.height
        xs = []
        rows = max(1, int(h * 0.02))
        for y in range(rows):
            for x in range(w):
                r, g, b, a = raw.get_at((br.x + x, br.y + y))
                if a > 120:
                    xs.append(x)
        frac = (sum(xs) / len(xs) / w) if xs else 0.5
    except Exception:
        frac = 0.5
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
        self._font_sm      = pygame.font.SysFont("monospace", 24)
        self._font_fb      = pygame.font.SysFont("monospace", 46, bold=True)
        self._font_gauge   = pygame.font.SysFont("monospace", 22, bold=True)
        self._font_panel_l = pygame.font.SysFont("monospace", 20, bold=True)
        self._font_panel_n = pygame.font.SysFont("monospace", 30, bold=True)

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
            key_name, lock_name, color = LEGENDARY_PAIR
            self.lock_type = "legendary"
        else:
            idx = random.randrange(len(NORMAL_PAIRS))
            if len(NORMAL_PAIRS) > 1:
                while idx == self._last_pair_idx:
                    idx = random.randrange(len(NORMAL_PAIRS))
            self._last_pair_idx = idx
            key_name, lock_name, color = NORMAL_PAIRS[idx]
            self.lock_type = "normal"

        self.color_name  = color
        self._key_img  = _load_image_fit(key_name, *KEY_BOX)
        self._lock_img = _load_image_fit(lock_name, *LOCK_BOX)
        self._key_tip_frac = _key_tip_frac(key_name)
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
            self._draw_arrows(surface)
            self._draw_gauge(surface)
            self._draw_hold_indicator(surface)

        if self.phase == "legendary_popup" and self._legendary_popup_img is not None:
            r = self._legendary_popup_img.get_rect(center=(GAME_W // 2, 300))
            surface.blit(self._legendary_popup_img, r)

        draw_game_header(surface, "Key and Lock", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        prog_s = font_sm.render(self._session_progress_text("locks"), True, T["TEXT"])
        surface.blit(prog_s, (int(40 * GAME_W / 1920), HEADER_BOTTOM + int(20 * GAME_H / 1080)))

        if self.streak >= 2:
            streak_s = font_sm.render(f"{self.streak}-Lock Streak", True, T["YELLOW"])
            surface.blit(streak_s, (int(40 * GAME_W / 1920), HEADER_BOTTOM + int(50 * GAME_H / 1080)))

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

        surface.blit(font_sm.render(
            "Tilt wrist LEFT/RIGHT to turn the key — hold on target to unlock",
            True, T["GRAY"]), (GAME_W // 2 - 340, GAME_H - 44))

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

    def _draw_key(self, surface):
        if self._key_img is None:
            return
        # Rigid rotation, pivoted at the tip -- see module docstring. This
        # is pygame.transform.rotate() on the unmodified sprite (its shape,
        # width and length are never altered -- no scaling, no squashing,
        # no flipping), just pivoted at the key's own measured tip point
        # instead of its centre, so that point -- and only that point --
        # stays fixed at the keyhole through the entire rotation while the
        # rest of the key (the head) swings around it.
        w, h = self._key_img.get_size()
        tip_local = (self._key_tip_frac * w, 0.0)   # tip sits at the top row
        offset = pygame.math.Vector2(w / 2 - tip_local[0], h / 2 - tip_local[1])
        rotated_offset = offset.rotate(self.current_angle)
        rotated = pygame.transform.rotate(self._key_img, -self.current_angle)
        rect = rotated.get_rect(center=(self.keyhole_pos[0] + rotated_offset.x,
                                         self.keyhole_pos[1] + rotated_offset.y))
        surface.blit(rotated, rect)

    def _draw_arrows(self, surface):
        T = get_theme()
        cy = self.lock_rect.centery
        want_right = self.target_angle > 0 and self.phase == "playing"
        want_left  = self.target_angle < 0 and self.phase == "playing"

        for side, cx, active in (("L", self.lock_rect.left - 50, want_left),
                                   ("R", self.lock_rect.right + 50, want_right)):
            col = T["GREEN"] if active else T["GRAY"]
            width = 8 if active else 3
            rect = pygame.Rect(0, 0, 100, 100)
            rect.center = (cx, cy)
            start = -0.9 if side == "L" else math.pi - 2.2
            end   = 0.9 if side == "L" else math.pi + 2.2
            try:
                pygame.draw.arc(surface, col, rect, start, end, width)
            except Exception:
                pass
            tip_angle = end if side == "L" else start
            tip = (cx + 50 * math.cos(tip_angle), cy + 50 * math.sin(tip_angle))
            perp = tip_angle + (math.pi / 2 if side == "L" else -math.pi / 2)
            p2 = (tip[0] + 14 * math.cos(perp), tip[1] + 14 * math.sin(perp))
            p3 = (tip[0] - 14 * math.cos(perp), tip[1] - 14 * math.sin(perp))
            pygame.draw.polygon(surface, col, [tip, p2, p3])

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
            lbl_s = self._font_panel_l.render(label, True, T["TEXT"])
            val_s = self._font_panel_n.render(value, True, val_col)
            w = max(lbl_s.get_width(), val_s.get_width()) + 32
            h = lbl_s.get_height() + val_s.get_height() + 22
            box = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(box, (15, 20, 36, 195), box.get_rect(), border_radius=12)
            pygame.draw.rect(box, T["ACCENT"], box.get_rect(), 2, border_radius=12)
            box.blit(lbl_s, lbl_s.get_rect(centerx=w // 2, top=10))
            box.blit(val_s, val_s.get_rect(centerx=w // 2, top=14 + lbl_s.get_height()))
            surface.blit(box, box.get_rect(center=(cx, cy)))

        panel(self.lock_rect.left - 170, "Current Angle", f"{self.current_angle:+.0f}°", cur_col)
        panel(self.lock_rect.right + 170, "Target Angle", f"{self.target_angle:+.0f}°", T["YELLOW"])

    def _draw_turn_progress(self, surface):
        T = get_theme()
        n = self.turns_required
        r = 11
        gap = 12
        total_w = n * (r * 2) + (n - 1) * gap
        x0 = self.lock_rect.centerx - total_w // 2
        y = self.lock_rect.top - 30
        for i in range(n):
            cx = x0 + r + i * (r * 2 + gap)
            done = i < self.turns_done
            col = T["GREEN"] if done else T["PANEL"]
            pygame.draw.circle(surface, col, (cx, y), r)
            pygame.draw.circle(surface, T["ACCENT"], (cx, y), r, 2)
        lbl = self._font_panel_l.render(f"{self.turns_done} / {n} Turns", True, T["TEXT"])
        surface.blit(lbl, lbl.get_rect(centerx=self.lock_rect.centerx, bottom=y - r - 4))

    def _draw_gauge(self, surface):
        T = get_theme()
        cx, cy = GAUGE_CENTER
        r = GAUGE_RADIUS

        def ang_to_pt(deg, radius):
            # -45 at left, 0 at top, +45 at right (matches the reference gauge)
            a = math.radians(-90 + deg)
            return (cx + radius * math.cos(a), cy + radius * math.sin(a))

        pygame.draw.arc(surface, T["ACCENT"],
                         pygame.Rect(cx - r, cy - r, r * 2, r * 2),
                         math.radians(-135), math.radians(-45), 4)

        # acceptable tolerance band around the target
        band_pts = [ang_to_pt(d, r) for d in
                    range(int(self.target_angle - self.tolerance), int(self.target_angle + self.tolerance) + 1)]
        if len(band_pts) > 1:
            pygame.draw.lines(surface, T["YELLOW"], False, band_pts, 8)

        # target marker
        tx, ty = ang_to_pt(self.target_angle, r)
        pygame.draw.circle(surface, T["YELLOW"], (int(tx), int(ty)), 8)
        pygame.draw.circle(surface, (20, 20, 20), (int(tx), int(ty)), 8, 2)

        dist = abs(self.current_angle - self.target_angle)
        if dist <= self.tolerance:
            cur_col = T["GREEN"]
        elif dist <= self.tolerance * 2.2:
            cur_col = T["YELLOW"]
        else:
            cur_col = T["ACCENT"]

        # current-angle needle
        nx, ny = ang_to_pt(max(-45, min(45, self.current_angle)), r - 12)
        pygame.draw.line(surface, cur_col, (cx, cy), (int(nx), int(ny)), 5)
        pygame.draw.circle(surface, cur_col, (cx, cy), 7)

        for deg, lbl in ((-45, "-45°"), (0, "0°"), (45, "+45°")):
            lx, ly = ang_to_pt(deg, r + 22)
            s = self._font_gauge.render(lbl, True, T["GRAY"])
            surface.blit(s, s.get_rect(center=(int(lx), int(ly))))

        # Live current-angle readout, directly below the gauge (which sits
        # below the key) -- the -45/0/+45 ticks above are fixed reference
        # points only, this is the actual moving value, large and
        # high-contrast so it's never mistaken for decoration.
        val_s = self._font_panel_n.render(f"{self.current_angle:+.0f}°", True, cur_col)
        chip = pygame.Surface((val_s.get_width() + 24, val_s.get_height() + 14), pygame.SRCALPHA)
        pygame.draw.rect(chip, (15, 20, 36, 200), chip.get_rect(), border_radius=10)
        pygame.draw.rect(chip, cur_col, chip.get_rect(), 2, border_radius=10)
        chip.blit(val_s, (12, 7))
        surface.blit(chip, chip.get_rect(centerx=cx, bottom=cy - r - 50))

    def _draw_hold_indicator(self, surface):
        T = get_theme()
        cx, cy = GAUGE_CENTER[0] + GAUGE_RADIUS + 180, GAUGE_CENTER[1] - 40
        ring_r = 46
        dist = abs(self.current_angle - self.target_angle)
        aligned = dist <= self.tolerance and not self._need_neutral

        pygame.draw.circle(surface, T["PANEL"], (cx, cy), ring_r, 6)
        if aligned:
            prog = min(1.0, self.hold_timer / self.hold_time)
            if prog > 0:
                arc_rect = pygame.Rect(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
                end_angle = -math.pi / 2 + 2 * math.pi * prog
                pygame.draw.arc(surface, T["GREEN"], arc_rect, -math.pi / 2, end_angle, 6)
            label = "Hold Steady"
            timer_s = f"{self.hold_timer:0.1f} / {self.hold_time:0.1f}s"
        elif self._need_neutral:
            label, timer_s = "Return to Neutral", None
        else:
            label, timer_s = "Align to Target", None

        lines = [self._font_panel_l.render(label, True, (255, 255, 255))]
        if timer_s:
            lines.append(self._font_panel_l.render(timer_s, True, (225, 225, 225)))
        chip_w = max(s.get_width() for s in lines) + 24
        chip_h = sum(s.get_height() for s in lines) + 14
        chip = pygame.Surface((chip_w, chip_h), pygame.SRCALPHA)
        pygame.draw.rect(chip, (15, 20, 36, 190), chip.get_rect(), border_radius=10)
        yy = 6
        for s in lines:
            chip.blit(s, s.get_rect(centerx=chip_w // 2, top=yy))
            yy += s.get_height() + 2
        surface.blit(chip, chip.get_rect(centerx=cx, top=cy + ring_r + 10))

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 900, 620
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
                "Turn the key to the target angle and hold steady to complete a turn.",
                "Open every required turn to unlock the lock and score.",
                "Normal lock +1  •  Legendary lock (20% chance) +5",
            ]),
            ("CONTROLS", [
                "Tilt wrist RIGHT to turn the key clockwise.",
                "Tilt wrist LEFT to turn the key counterclockwise.",
                "Return to neutral between turns before the next one can start.",
            ]),
            ("THIS SESSION", [
                f"Hold time: {self.hold_time:.1f} seconds",
                (f"Goal:       Open {self.goal} locks" if self.session_mode == "target" else
                 f"Duration:   {int(self.timed_duration)} seconds"),
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
