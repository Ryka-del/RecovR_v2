"""
Steady Aim — Wrist Rotation (archery) game (1920x1080)

Mechanic:
  - A single archery target hangs from a wooden beam near the top of the
    screen (a fresh one is chosen -- random sprite + random horizontal
    position -- after every shot; never more than one at a time).
  - Wrist tilt (MPU6050, two axes) moves an aiming cursor/crosshair.
    Horizontal = tilt_x, vertical = the MPU6050's own Y axis, read directly
    off the BLE packet (see the _ble import below) since input_handler.py's
    own "tilt_y" field carries the Flex Sensor instead, system-wide.
  - The bow (fixed at a consistent bottom-center origin) and its nocked
    arrow rotate to track the cursor -- the whole assembly always points at
    the same spot the crosshair is projecting onto.
  - Hold the cursor within the target's aim-tolerance zone (difficulty
    dependent) for HOLD_TIME continuous seconds -- a ring around the
    crosshair fills clockwise while holding, and resets instantly to zero
    the moment the cursor leaves the zone. Completing the hold locks the
    current aim and fires automatically.
  - The arrow travels from the bow to the locked point and scores against
    the target's own visible colored rings (yellow/red/blue/black/white =
    7/3/3/1/1, 0 outside) -- this scoring is INDEPENDENT of the difficulty
    aim-tolerance zone used to trigger the hold, so the 7/3/1/0 system
    never changes with difficulty, only how forgiving it is to start a hold.
  - Each fired arrow (any result) consumes one arrow from the
    difficulty-sized basket; the session ends when the goal is reached
    (Target Mode), the timer runs out (Timed Mode), or arrows run out
    (either mode -- recorded as an incomplete attempt, not "completed").
"""

import os
import random
import math
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler
from audio import (play_success, play_completion, start_music, stop_music,
                    pause_music, resume_music, game_bgm_path, play_click)
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.hud import draw_target_pill, TARGET_POS
from games.round_complete import draw_round_complete_overlay

# Real MPU6050 Y-axis tilt (accel_y) -- the firmware already transmits it
# (ble_receiver.py's PACKET_FORMAT) but input_handler.py's own "tilt_y"
# field carries the Flex Sensor instead (every game's calibration shares
# that convention -- see SENSOR_CFG["Finger Flexion"] in
# scenes/calibration_window.py), so it is never exposed through
# get_state(). Reading it directly here, scoped to this file only, gives
# Steady Aim genuine two-axis MPU6050 control without touching that shared
# field or any other game's controls.
try:
    from sensors.ble_receiver import ble_receiver as _ble
except Exception:
    _ble = None

# ── difficulty-scaled parameters ────────────────────────────────────────────
GOALS            = {"Easy": 8,   "Medium": 10, "Hard": 12}   # Target Mode: shots to complete
DURATION         = {"Easy": 90,  "Medium": 75, "Hard": 60}   # Timed Mode: session length in seconds
AIM_TOLERANCE_R  = {"Easy": 120, "Medium": 80, "Hard": 45}   # px radius of the HOLD-trigger zone (not the score rings)
CURSOR_SPD       = {"Easy": 900, "Medium": 1000, "Hard": 1100}
ARROWS_ALLOWANCE = {"Easy": 20,  "Medium": 16,  "Hard": 14}  # arrows in the basket this session
HOLD_TIME_DEFAULT = 3.0   # seconds -- uniform across difficulty per spec, overridable via sa_hold_time

FIRE_DURATION    = 0.35   # seconds the arrow takes to travel to its locked impact point
IMPACT_DURATION  = 1.3    # seconds the arrow stays stuck in the target before the next one --
                           # gives the patient time to reposition/reset before aiming again

# ── target scoring rings, as a fraction of the target FACE's own radius
# (not the full sprite including its rope) -- measured directly off the
# artwork, innermost first. This is completely separate from
# AIM_TOLERANCE_R: difficulty only changes when a hold is allowed to start,
# never what an actual impact is worth.
RING_SCORES = [
    (0.22, 7),   # yellow / bullseye
    (0.39, 3),   # red
    (0.56, 3),   # blue
    (0.68, 1),   # black
    (0.85, 1),   # white
]   # beyond the last radius -> 0 (outside the target)

# The 6 target sprites share one real-world face size (all 607px wide in
# their own art, the rope above the face being the only thing that differs
# in length) -- TARGET_FACE_DIAM is that shared, on-screen face diameter.
TARGET_ASSETS = [f"target{i}_steady_aim.png" for i in range(1, 7)]
TARGET_FACE_DIAM = 180

BASKET_ASSET = {
    "Easy":   "easy_basket_steady_aim.png",
    "Medium": "medium_basket_steady_aim.png",
    "Hard":   "hard_basket_steady_aim.png",
}
BASKET_BOX = (230, 260)

BEAM_Y      = HEADER_BOTTOM + 70   # leaves room above for the "X/Y shots" progress text
BEAM_X      = GAME_W // 2
BEAM_WIDTH  = int(GAME_W * 0.86)

BOW_ORIGIN    = (GAME_W // 2, GAME_H - 120)   # fixed firing origin -- never translates
# The bow art is already drawn in its correct resting pose -- horizontal,
# curved ends to left/right, grip at the centre -- so it is used as-is (no
# pre-rotation). The arrow art is already drawn vertical, head up / feathers
# down, so it is also used as-is. At aim angle 0 the arrow stands upright
# through the bow's centre, exactly matching the reference pose; both then
# rotate together by the same live aim angle to track the cursor.
BOW_BOX       = (520, 160)
NOCKED_ARROW_BOX = (38, 335)
FLYING_ARROW_BOX = (44, 378)
# Where the nocked arrow crosses the bow's own centre (BOW_ORIGIN), as a
# fraction of the arrow sprite's height measured from its top/head end --
# this is the grip/string "contact point" the two must share while nocked,
# so the arrow sits low through the bow (most of its length below the
# grip) instead of floating entirely above it.
NOCK_CONTACT_FRAC_FROM_TOP = 0.384
MAX_AIM_ANGLE = 38   # degrees -- clamps how far the bow visually tilts off-vertical

# Reachable aiming area for the crosshair (keeps it clear of the header and
# screen edges; also bounds where targets are allowed to spawn).
AIM_X_MIN, AIM_X_MAX = 110, GAME_W - 110
AIM_Y_MIN, AIM_Y_MAX = HEADER_BOTTOM + 40, GAME_H - 40

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


def _fit_scale(name, w, h):
    """The scale factor _load_image_fit(name, w, h) would use, without
    loading/caching the scaled image -- lets another sprite that must share
    this one's real-world size (see _load_image_scaled) reuse that number."""
    try:
        raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
        br = raw.get_bounding_rect(min_alpha=10)
        return min(w / br.width, h / br.height)
    except Exception:
        return 1.0


def _load_image_scaled(name, scale):
    """Crop to the asset's own opaque content, then scale by an EXPLICIT
    factor (not an independent fit-to-box). Used for the 6 target sprites,
    which must all render their shared-size face at the same real-world
    size regardless of each one's own rope length / total image height."""
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


def _rotate_around_point(image, angle, local_point, target_pos):
    """Rotate `image` by `angle` degrees and return (rotated_surface, rect)
    such that `local_point` -- a point given in the image's own unrotated
    pixel coordinates -- lands exactly at `target_pos` in screen space.
    Used to keep the arrow's bow-contact point pinned to BOW_ORIGIN as the
    nocked arrow tilts together with the bow."""
    w, h = image.get_size()
    offset = pygame.math.Vector2(w / 2 - local_point[0], h / 2 - local_point[1])
    rotated_offset = offset.rotate(-angle)
    rotated = pygame.transform.rotate(image, angle)
    rect = rotated.get_rect(center=(target_pos[0] + rotated_offset.x,
                                     target_pos[1] + rotated_offset.y))
    return rotated, rect


class Target:
    """The one currently-hanging archery target. x/face_cy are its face's
    own center in screen coordinates -- the authority for both scoring and
    the aim-tolerance check, independent of which of the 6 sprites (rope
    lengths) was rolled."""
    def __init__(self, img, x):
        self.img = img
        self.x = float(x)
        face_r = TARGET_FACE_DIAM / 2.0
        self.face_r = face_r
        # Every target sprite is cropped+scaled from its own top edge (the
        # rope's attachment knot), so midtop-anchoring at BEAM_Y is correct
        # for all 6 regardless of height; the face center then sits exactly
        # face_r above the image's own bottom edge.
        self.face_cy = BEAM_Y + img.get_height() - face_r


class SteadyAimGame(SessionModeMixin, FatigueMixin, BaseScreen):
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
        cal_params  = self.cal.get("params", {})
        self._session_init(data, GOALS, DURATION, self.difficulty, cal_goal_key="sa_goal")
        self.aim_tolerance_r  = cal_params.get("sa_circle_r", AIM_TOLERANCE_R[self.difficulty])
        self.cursor_spd       = cal_params.get("sa_cursor_spd", CURSOR_SPD[self.difficulty])
        self.hold_time        = cal_params.get("sa_hold_time", HOLD_TIME_DEFAULT)
        self.arrows_allowance = int(cal_params.get("sa_arrows", ARROWS_ALLOWANCE[self.difficulty]))

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_back_rect  = pygame.Rect(0, 0, 1, 1)

        self.vol_active = False
        self.pause_vol  = 0.4
        self._font_hud  = pygame.font.SysFont("monospace", 34, bold=True)
        self._font_target = pygame.font.SysFont("monospace", 54, bold=True)
        self._font_fb   = pygame.font.SysFont("monospace", 52, bold=True)
        self._font_hold = pygame.font.SysFont("monospace", 20, bold=True)
        self._font_counter_lbl = pygame.font.SysFont("monospace", 20, bold=True)
        self._font_counter_num = pygame.font.SysFont("monospace", 30, bold=True)

        self._bg_img   = _load_image_cover("bg_steady_aim.png", GAME_W, GAME_H)
        self._beam_img = _load_image_fit("kahoy_steady_aim.png", BEAM_WIDTH, 999)
        # Bow art is drawn lying horizontal; stand it upright once, cached.
        self._bow_base_img = _load_image_fit("bow_steady_aim.png", *BOW_BOX)
        self._nocked_arrow_img = _load_image_fit("arrow_steady_aim.png", *NOCKED_ARROW_BOX)
        self._flying_arrow_img = _load_image_fit("arrow_steady_aim.png", *FLYING_ARROW_BOX)
        self._basket_img = _load_image_fit(BASKET_ASSET.get(self.difficulty, BASKET_ASSET["Easy"]), *BASKET_BOX)

        # All 6 targets share one real-world face size (see TARGET_ASSETS'
        # comment) -- target1 (shortest rope) sets the reference scale.
        target_scale = _fit_scale(TARGET_ASSETS[0], TARGET_FACE_DIAM, TARGET_FACE_DIAM)
        self._target_imgs = [_load_image_scaled(name, target_scale) for name in TARGET_ASSETS]

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
        self.reps       = 0          # = arrows fired this session (any result)
        self._session_reset()
        self.start_time = pygame.time.get_ticks()

        self.cursor_x = float(GAME_W // 2)
        self.cursor_y = float((AIM_Y_MIN + AIM_Y_MAX) // 2)
        self._tilt_x_smooth = 0.0
        self._tilt_y_smooth = 0.0

        self.arrows_left = self.arrows_allowance

        self.phase      = "aim"   # "aim" | "fire" | "impact"
        self.hold_timer = 0.0

        self.fire_t      = 0.0
        self.fire_from   = BOW_ORIGIN
        self.fire_to     = BOW_ORIGIN
        self.fire_angle  = 0.0

        self.impact_t         = 0.0
        self.last_hit_points  = None
        self.last_hit_pos     = None
        self.target_shake     = 0.0

        self.feedback = None
        self._state   = {"tilt_x": 0.0, "tilt_y": 0.0}

        self._last_target_idx = None
        self._last_target_x   = None
        self._spawn_target()

    def _spawn_target(self):
        idx = random.randrange(len(self._target_imgs))
        if len(self._target_imgs) > 1:
            while idx == self._last_target_idx:
                idx = random.randrange(len(self._target_imgs))
        self._last_target_idx = idx
        img = self._target_imgs[idx]

        face_r = TARGET_FACE_DIAM / 2.0
        x_min = max(int(BEAM_X - BEAM_WIDTH / 2 + face_r), AIM_X_MIN + int(face_r))
        x_max = min(int(BEAM_X + BEAM_WIDTH / 2 - face_r), AIM_X_MAX - int(face_r))
        x = random.randint(x_min, x_max)
        # Avoid an (almost) identical consecutive horizontal position when
        # the range actually offers other options.
        if self._last_target_x is not None and (x_max - x_min) > 80:
            tries = 0
            while abs(x - self._last_target_x) < 60 and tries < 10:
                x = random.randint(x_min, x_max)
                tries += 1
        self._last_target_x = x

        self.target = Target(img, x)
        self.hold_timer = 0.0

    # ── sensor input ─────────────────────────────────────────────────────

    def _vertical_raw(self):
        """Real MPU6050 Y axis on actual hardware; the existing UP/DOWN-
        arrow-driven tilt_y in Test Mode (unaffected -- that path never
        touches the Flex Sensor since there's no physical flex channel to
        read there)."""
        if input_handler.connected:
            if _ble is None:
                return 0.0
            try:
                return max(-1.0, min(1.0, _ble.get_latest()["accel_y"] / 16384.0))
            except Exception:
                return 0.0
        return self._state.get("tilt_y", 0.0)

    def _normalize_tilt(self, raw, axis):
        wmin = self.cal.get("wrist_min", -1.0)
        wmax = self.cal.get("wrist_max",  1.0)
        if wmax == wmin:
            return raw
        return max(-1.0, min(1.0, (raw - wmin) / (wmax - wmin) * 2.0 - 1.0))

    # ── events ───────────────────────────────────────────────────────────

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_bgm_path("Steady Aim"))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    start_music(game_bgm_path("Steady Aim"))
                elif self._results_back_rect.collidepoint(event.pos):
                    play_click()
                    self._exit_to_game_config()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_game_config()
            return

        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"): self._resume_fatigue()
            return
        if self.paused:
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
                lambda: (self._reset(), setattr(self, "paused", False),
                         start_music(game_bgm_path("Steady Aim"))),
                lambda: setattr(self, "vol_active", True),
                self._exit_to_game_config,
            ]
            for i, action in enumerate(opts_actions):
                oy = GAME_H // 2 - 160 + i * 96
                if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                    play_click()
                    action()
                    return
            return
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._pause_btn_rect.collidepoint(event.pos)):
            self.paused = True
            pause_music()
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True
            pause_music()

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

        ty_raw = self._vertical_raw()
        self._state["tilt_y"] = ty_raw   # keep the real value visible to therapist telemetry

        tx = self._normalize_tilt(self._state["tilt_x"], "x")
        ty = self._normalize_tilt(ty_raw, "y")

        # Light smoothing damps minor sensor jitter without adding
        # noticeable delay to deliberate movement.
        smooth_k = min(1.0, dt * 10.0)
        self._tilt_x_smooth += (tx - self._tilt_x_smooth) * smooth_k
        self._tilt_y_smooth += (ty - self._tilt_y_smooth) * smooth_k
        tx, ty = self._tilt_x_smooth, self._tilt_y_smooth

        if self.phase == "aim":
            if abs(tx) > 0.05:
                self.cursor_x += self.cursor_spd * dt * tx
            if abs(ty) > 0.05:
                self.cursor_y += self.cursor_spd * dt * ty
            self.cursor_x = max(AIM_X_MIN, min(AIM_X_MAX, self.cursor_x))
            self.cursor_y = max(AIM_Y_MIN, min(AIM_Y_MAX, self.cursor_y))

            dist   = math.hypot(self.cursor_x - self.target.x, self.cursor_y - self.target.face_cy)
            inside = dist <= self.aim_tolerance_r
            if inside:
                self.hold_timer += dt
                if self.hold_timer >= self.hold_time:
                    self._fire_arrow()
            else:
                self.hold_timer = 0.0   # instant reset on aim-lost, per spec

        elif self.phase == "fire":
            self.fire_t += dt
            if self.fire_t >= FIRE_DURATION:
                self._resolve_impact()

        elif self.phase == "impact":
            self.impact_t -= dt
            if self.target_shake > 0:
                self.target_shake -= dt
            if self.impact_t <= 0:
                self._after_impact()

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0: self.feedback = None

    def _fire_arrow(self):
        """Lock the current aim and hand off to the travel animation --
        called the one frame the hold completes, never again until the
        next target (phase leaves "aim" immediately)."""
        self.arrows_left = max(0, self.arrows_left - 1)
        self.reps += 1   # a shot was taken -- counted regardless of score
        self.phase    = "fire"
        self.fire_t   = 0.0
        self.fire_from = BOW_ORIGIN
        self.fire_to   = (self.cursor_x, self.cursor_y)
        dx = self.fire_to[0] - self.fire_from[0]
        dy = self.fire_to[1] - self.fire_from[1]
        angle = math.degrees(math.atan2(dx, -dy))
        self.fire_angle = max(-MAX_AIM_ANGLE, min(MAX_AIM_ANGLE, angle))
        self.hold_timer = 0.0

    def _resolve_impact(self):
        hx, hy = self.fire_to
        dist = math.hypot(hx - self.target.x, hy - self.target.face_cy)
        points = 0
        for frac, pts in RING_SCORES:
            if dist <= self.target.face_r * frac:
                points = pts
                break
        self.score += points
        self.last_hit_points = points
        self.last_hit_pos    = (hx, hy)
        col = (255, 220, 60) if points >= 7 else (120, 220, 255) if points > 0 else (200, 200, 200)
        self.feedback = (f"+{points}", col, 1.0)
        if points > 0:
            play_success()
        self.target_shake = 0.25
        self.phase    = "impact"
        self.impact_t = IMPACT_DURATION

    def _after_impact(self):
        if self._session_target_reached():
            self._end_game("completed")
            return
        if self.arrows_left <= 0:
            # Ran out of arrows before reaching the goal/duration -- an
            # incomplete attempt, not a false "completed".
            self._end_game("stopped")
            return
        self.phase = "aim"
        self._spawn_target()

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
                game           = "Steady Aim",
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

    def _apply_vol(self):
        try:
            pygame.mixer.music.set_volume(self.pause_vol)
            from db.database import set_volume
            set_volume(self.pause_vol)
        except Exception:
            pass

    def draw(self, surface):
        T = get_theme()
        if self._bg_img is not None:
            surface.blit(self._bg_img, (0, 0))
        else:
            surface.fill(T["BG"])

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        # Beam
        if self._beam_img is not None:
            r = self._beam_img.get_rect(center=(BEAM_X, BEAM_Y))
            surface.blit(self._beam_img, r)

        # Target (with a brief impact shake)
        shake_x = random.randint(-5, 5) if self.target_shake > 0 else 0
        tgt = self.target
        if tgt.img is not None:
            r = tgt.img.get_rect(midtop=(int(tgt.x) + shake_x, BEAM_Y))
            surface.blit(tgt.img, r)

        # Impact mark + points feedback near the target, while shown
        if self.phase == "impact" and self.last_hit_pos is not None:
            hx, hy = self.last_hit_pos
            pygame.draw.circle(surface, (20, 20, 20), (int(hx), int(hy)), 6)
            pygame.draw.circle(surface, (255, 255, 255), (int(hx), int(hy)), 6, 2)

        # Bow + arrow (nocked while aiming, travelling while firing)
        self._draw_bow_and_arrow(surface)

        # Crosshair + hold ring -- only while actively aiming (hidden once
        # locked/firing, since the aim is no longer being adjusted)
        if self.phase == "aim":
            self._draw_cursor(surface)

        # Score flash (brief, subtle, on any impact)
        if self.feedback and self.phase in ("impact",):
            pass  # handled below via feedback text near target

        draw_game_header(surface, "Steady Aim", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        draw_target_pill(surface, self._session_progress_text("shots"),
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

        # Arrow basket + Arrows Left counter (bottom-right)
        self._draw_basket(surface)

        if self.feedback:
            fx, fy = (self.target.x, self.target.face_cy - self.target.face_r - 50)
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, msg.get_rect(center=(int(fx), int(fy))))

        if self.paused: self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_bow_and_arrow(self, surface):
        base = self._bow_base_img
        if self.phase == "fire":
            angle = self.fire_angle
        elif self.phase == "impact":
            angle = self.fire_angle
        else:
            dx = self.cursor_x - BOW_ORIGIN[0]
            dy = self.cursor_y - BOW_ORIGIN[1]
            angle = math.degrees(math.atan2(dx, -dy))
            angle = max(-MAX_AIM_ANGLE, min(MAX_AIM_ANGLE, angle))

        # Bow drawn first -- the arrow lies on top of it so the two read as
        # one connected piece (nocked through the grip and string) rather
        # than the bow occluding the shaft.
        if base is not None:
            bow = pygame.transform.rotate(base, -angle)
            r = bow.get_rect(center=BOW_ORIGIN)
            surface.blit(bow, r)

        if self.phase == "fire":
            frac = min(1.0, self.fire_t / FIRE_DURATION)
            fx = self.fire_from[0] + (self.fire_to[0] - self.fire_from[0]) * frac
            fy = self.fire_from[1] + (self.fire_to[1] - self.fire_from[1]) * frac
            if self._flying_arrow_img is not None:
                # Anchored by its TIP (not centre) so only the point ever
                # reaches the impact location -- the shaft trails behind
                # along the flight path instead of overshooting past it.
                w, h = self._flying_arrow_img.get_size()
                flying, r = _rotate_around_point(self._flying_arrow_img, -self.fire_angle,
                                                  (w / 2, 0), (fx, fy))
                surface.blit(flying, r)
        elif self.phase == "impact" and self.last_hit_pos is not None:
            # Stays stuck in the target (tip pinned at the impact point) for
            # the whole IMPACT_DURATION instead of vanishing immediately --
            # gives the patient a beat to see the result and reposition.
            if self._flying_arrow_img is not None:
                w, h = self._flying_arrow_img.get_size()
                flying, r = _rotate_around_point(self._flying_arrow_img, -self.fire_angle,
                                                  (w / 2, 0), self.last_hit_pos)
                surface.blit(flying, r)
        elif self.phase != "impact" and self._nocked_arrow_img is not None:
            w, h = self._nocked_arrow_img.get_size()
            contact_local = (w / 2, h * NOCK_CONTACT_FRAC_FROM_TOP)
            nocked, r = _rotate_around_point(self._nocked_arrow_img, -angle,
                                              contact_local, BOW_ORIGIN)
            surface.blit(nocked, r)

    def _draw_cursor(self, surface):
        T = get_theme()
        cx, cy = int(self.cursor_x), int(self.cursor_y)
        dist   = math.hypot(self.cursor_x - self.target.x, self.cursor_y - self.target.face_cy)
        inside = dist <= self.aim_tolerance_r
        col    = T["GREEN"] if inside else T["TEXT"]

        # crosshair
        pygame.draw.circle(surface, col, (cx, cy), 10, 2)
        pygame.draw.line(surface, col, (cx - 16, cy), (cx - 6, cy), 2)
        pygame.draw.line(surface, col, (cx + 6, cy), (cx + 16, cy), 2)
        pygame.draw.line(surface, col, (cx, cy - 16), (cx, cy - 6), 2)
        pygame.draw.line(surface, col, (cx, cy + 6), (cx, cy + 16), 2)

        ring_r = 26
        if inside:
            prog = min(1.0, self.hold_timer / self.hold_time)
            pygame.draw.circle(surface, T["PANEL"], (cx, cy), ring_r, 4)
            if prog > 0:
                arc_rect = pygame.Rect(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
                end_angle = -math.pi / 2 + 2 * math.pi * prog
                pygame.draw.arc(surface, T["GREEN"], arc_rect, -math.pi / 2, end_angle, 4)
            label = "Hold Steady"
            timer_s = f"{self.hold_timer:0.1f} / {self.hold_time:0.1f}s"
        else:
            label = "Move Wrist to Aim"
            timer_s = None

        # A small translucent chip behind the label/timer -- the crosshair
        # can sit directly over the target's own colored rings when aimed
        # correctly, so plain text there would be unreadable without it.
        lbl_s = self._font_hold.render(label, True, (255, 255, 255))
        lines = [lbl_s]
        if timer_s:
            lines.append(self._font_hold.render(timer_s, True, (225, 225, 225)))
        chip_w = max(s.get_width() for s in lines) + 24
        chip_h = sum(s.get_height() for s in lines) + 14
        chip_top = cy + ring_r + 6
        chip = pygame.Surface((chip_w, chip_h), pygame.SRCALPHA)
        pygame.draw.rect(chip, (15, 20, 36, 190), chip.get_rect(), border_radius=10)
        yy = 6
        for s in lines:
            chip.blit(s, s.get_rect(centerx=chip_w // 2, top=yy))
            yy += s.get_height() + 2
        surface.blit(chip, chip.get_rect(centerx=cx, top=chip_top))

    def _draw_basket(self, surface):
        T = get_theme()
        if self._basket_img is not None:
            r = self._basket_img.get_rect(bottomright=(GAME_W - 30, GAME_H - 20))
            surface.blit(self._basket_img, r)
            counter_cx = r.centerx
            counter_y  = r.top - 54
        else:
            counter_cx, counter_y = GAME_W - 140, GAME_H - 90

        lbl_s = self._font_counter_lbl.render("Arrows Left", True, T["TEXT"])
        num_s = self._font_counter_num.render(str(max(0, self.arrows_left)), True, T["ACCENT"])
        surface.blit(lbl_s, lbl_s.get_rect(centerx=counter_cx, top=counter_y))
        surface.blit(num_s, num_s.get_rect(centerx=counter_cx, top=counter_y + 22))

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
        card_name = f"steady_aim_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
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
            surface, card_prefix="steady_aim", duration_sec=self.game_over_duration,
            score_text=self._session_count_text(), load_fit=_load_image_fit)

        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        mp = pygame.mouse.get_pos()
        bw, bh = 220, 52
        by = bottom_y + 20

        again_r = pygame.Rect(GAME_W // 2 - bw - 16, by, bw, bh)
        back_r  = pygame.Rect(GAME_W // 2 + 16,       by, bw, bh)
        self._results_again_rect = again_r
        self._results_back_rect  = back_r

        ag_col = (55, 170, 100) if again_r.collidepoint(mp) else (40, 140, 80)
        bk_col = (75, 110, 190) if back_r.collidepoint(mp)  else (55, 85, 160)

        pygame.draw.rect(surface, ag_col, again_r, border_radius=10)
        pygame.draw.rect(surface, bk_col, back_r,  border_radius=10)

        surface.blit(f_btn.render("Play Again", True, T["WHITE"]),
                     f_btn.render("Play Again", True, T["WHITE"]).get_rect(center=again_r.center))
        surface.blit(f_btn.render("Exit", True, T["WHITE"]),
                     f_btn.render("Exit", True, T["WHITE"]).get_rect(center=back_r.center))
