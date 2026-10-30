"""
Basketball — Grip Strength game (1920x1080)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import play_success, play_error, play_completion, start_music, stop_music, game_music_path, play_click
from constants import get_theme, GAME_W, GAME_H
from games.game_header import draw_game_header

GOALS      = {"Easy": 10, "Medium": 15, "Hard": 20}
ZONE_WIDTH = {"Easy": 0.25, "Medium": 0.16, "Hard": 0.09}
ZONE_SPEED = {"Easy": 0.0,  "Medium": 0.18, "Hard": 0.28}
TIME_START = {"Easy": 40,   "Medium": 35,   "Hard": 30}

RAMP_UP = 0.6   # grip rises at 0.6 units/sec while squeezing

BAR_W, BAR_H = 60, 500
BAR_X = GAME_W - 140
BAR_Y = (GAME_H - BAR_H) // 2

HOOP_W  = 190
HOOP_RX = HOOP_W // 2   # 95 — x-radius of rim ellipse
HOOP_RY = 10             # y-radius (perspective flattening)

# The court's visual ground level in bg_basketball.png (where the painted
# court surface begins, just past the fence) -- the stand's base is grounded
# here instead of an arbitrary screen-bottom offset.
STAND_GROUND_Y = 820

# The ball is largest while held (close to the patient) and shrinks smoothly
# while in flight toward the distant hoop, reaching BALL_R_HOOP once it
# arrives -- a simple perspective cue, not a new physics system.
BALL_R_HELD = 160
BALL_R_HOOP = 34

# Higher than real-world gravity so the shot arc covers its fixed rise/fall
# distance noticeably faster, without changing the arc's shape. Raised again
# so the natural slow-down near the apex (where vertical speed briefly
# approaches zero, same as any real projectile) passes quickly instead of
# reading as the animation stalling.
GRAVITY = 8000.0

_RIM_COL   = (220,  85,  20)
_RIM_DARK  = (140,  50,  10)
_BOARD_COL = (245, 245, 252)
_BOARD_EDG = ( 70,  75,  95)
_NET_COL   = (210, 205, 190)
_BRKT_COL  = (110, 115, 130)
_BALL_COL  = (210,  95,  20)
_BALL_SEAM = ( 20,  10,   5)
_BALL_HI   = (240, 135,  55)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}


def _load_image(name, size):
    """A square asset scaled uniformly to `size` (a (w, h) tuple) and cached.
    Returns None if the file is missing so callers can fall back to the
    original vector drawing instead of crashing."""
    key = (name, size)
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            _img_cache[key] = pygame.transform.smoothscale(raw, size)
        except Exception:
            _img_cache[key] = None
    return _img_cache[key]


def _load_image_fit(name, w, h):
    """Like _load_image(), but for an asset with extra transparent padding
    baked into its square canvas (e.g. a wide backboard graphic) -- crops to
    the actual opaque content, then scales to fit within w x h preserving
    its own aspect ratio instead of squashing it to a w x h square."""
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
    """A full-bleed background scaled + center-cropped to exactly fill w x h
    (preserves aspect ratio -- no stretching). Crops to the asset's own
    opaque content first, in case it sits on a larger, mostly-transparent
    export canvas, so that padding doesn't get covered in as if it were
    real content. Returns None if missing."""
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


# ring_back_basketball.png / ring_front_basketball.png are two independent
# renders of the same hoop (far side vs near side), each with its own
# transparent padding -- they are NOT cropped to a shared rectangle (that
# forced misalignment since their padding differs). Each is cropped to its
# own opaque content, then scaled so its rim comes out at the same width
# (tied to HOOP_W, the physics rim width used for scoring) as the other.
def _ring_img(name):
    return _load_image_fit(name, HOOP_W, HOOP_W * 2)


# The front ring's own rim band sits lower within its cropped content than
# the back ring's does, so it needs an extra downward nudge (beyond the
# shared base anchor below) for the two rim curves to read as one circle.
_RING_FRONT_EXTRA_Y = 10


def _ring_pos(hcx, hcy, img, extra_y=0):
    """Both ring halves start from this exact same base placement, anchored
    on the hoop's own (hcx, hcy) physics reference point, so they can only
    diverge by the explicit extra_y nudge below -- never by independent
    guesswork."""
    return img.get_rect(midtop=(hcx, hcy + int(img.get_height() * 0.03) + extra_y))


def _draw_hand(surface, bx, by):
    """The hand cradling the ball at its resting position -- shown only
    while the ball is not in flight. Anchored to the ball's own live
    position (which is randomized each round), not a fixed spot."""
    img = _load_image_fit("hand_basketball.png", 460, 640)
    if img is None:
        return
    # The palm/fingers sit near the upper-right of this asset's own crop,
    # roughly where the ball should nestle -- anchor that point to the
    # ball's center rather than the image's own top-left corner. A larger
    # anchor_x pulls the hand further left relative to the (fixed) ball
    # position, so the ball reads as sitting further right under the
    # fingers instead of centered in the palm.
    anchor_x = int(img.get_width() * 1.05)
    anchor_y = int(img.get_height() * 0.24)
    surface.blit(img, (bx - anchor_x, by - anchor_y))


def _ball_r_bucket(r):
    """Snap a ball radius to the same coarse step _draw_basketball uses, so
    the image cache only ever holds a small, reusable set of sizes."""
    return max(1, int(round(r / 8.0)) * 8)


def _prewarm_ball_cache():
    """Load and scale every ball-image bucket the shot animation can land
    on, once, up front -- so the first shot of a session doesn't stutter
    while _draw_basketball's cache would otherwise fill in frame by frame."""
    buckets = {_ball_r_bucket(r) for r in range(int(BALL_R_HOOP), int(BALL_R_HELD) + 1)}
    for r in buckets:
        _load_image("basketball_ball.png", (r * 2, r * 2))


def _draw_basketball(surface, cx, cy, r):
    # r is a continuously-interpolated float while the ball is in flight
    # (see BALL_R_HELD/BALL_R_HOOP) -- snapping it to coarse steps keeps the
    # image cache (and the underlying disk load + rescale it guards) to a
    # small, reusable set of sizes instead of reloading the asset from disk
    # on almost every single frame of the shot animation, which was the
    # real source of the stutter/lag during shots.
    r = _ball_r_bucket(r)
    img = _load_image("basketball_ball.png", (r * 2, r * 2))
    if img is not None:
        surface.blit(img, img.get_rect(center=(cx, cy)))
        return
    pygame.draw.circle(surface, _BALL_COL, (cx, cy), r)
    pygame.draw.line(surface, _BALL_SEAM, (cx - r + 4, cy), (cx + r - 4, cy), 2)
    pts = []
    for i in range(21):
        t  = i / 20
        sy = int(cy - r + 2 * r * t)
        sx = int(cx - r * 0.44 * math.sin(t * math.pi))
        pts.append((sx, sy))
    if len(pts) > 1:
        pygame.draw.lines(surface, _BALL_SEAM, False, pts, 2)
    pts_r = [(2 * cx - x, y) for x, y in pts]
    if len(pts_r) > 1:
        pygame.draw.lines(surface, _BALL_SEAM, False, pts_r, 2)
    pygame.draw.circle(surface, _BALL_SEAM, (cx, cy), r, 2)
    pygame.draw.circle(surface, _BALL_HI, (cx - r // 3, cy - r // 3), max(1, r // 5))


def _draw_hoop_back(surface, hx, hy):
    """Stand, backboard, bracket, and the BACK (far) half of the ring/net."""
    hcx = hx + HOOP_RX
    hcy = hy

    # Backboard size is tied to HOOP_W (the rim's own physics width) so the
    # two stay proportionate to each other however either is resized.
    bw, bh = int(HOOP_W * 1.9), int(HOOP_W * 1.9) // 2
    by = hcy - bh - HOOP_RY + 45   # lowered further, closer to/overlapping the rim

    # Stand — a pole running from behind the LOWER part of the backboard
    # down to the court's visual ground level, drawn first (furthest back).
    # Starting it partway down the board shortens the span it needs to
    # cover, and it's then squeezed noticeably narrower than its own native
    # width so it reads as a slim, unobtrusive support -- while its height
    # is left alone so its bottom still lands exactly on the ground and its
    # top stays hidden behind the board.
    stand_top = by + int(bh * 0.3)
    stand_bot = STAND_GROUND_Y
    stand_img = _load_image_fit("ring_stand_basketball.png", bw * 2, stand_bot - stand_top)
    if stand_img is not None:
        narrow_w = max(1, int(stand_img.get_width() * 0.45))
        stand_img = pygame.transform.smoothscale(stand_img, (narrow_w, stand_img.get_height()))
        surface.blit(stand_img, stand_img.get_rect(midtop=(hcx, stand_top)))

    # Backboard — centered ABOVE the rim
    bx = hcx - bw // 2
    board_img = _load_image_fit("basketball_board.png", bw, bh)
    if board_img is not None:
        surface.blit(board_img, board_img.get_rect(center=(hcx, by + bh // 2)))
    else:
        pygame.draw.rect(surface, _BOARD_COL, (bx, by, bw, bh), border_radius=4)
        pygame.draw.rect(surface, _BOARD_EDG, (bx, by, bw, bh), 3, border_radius=4)
        sq_m = 14
        sq_by = by + bh // 2
        sq_bh = bh // 2 - sq_m
        pygame.draw.rect(surface, _BOARD_EDG, (bx + sq_m, sq_by, bw - sq_m * 2, sq_bh), 2)

    # Vertical bracket connecting backboard bottom to rim top
    brkt_top = by + bh
    brkt_bot = hcy - HOOP_RY
    pygame.draw.rect(surface, _BRKT_COL,
                     (hcx - 5, brkt_top, 10, max(2, brkt_bot - brkt_top + 2)),
                     border_radius=2)

    # Ring — back half (far side of rim + net). Paired with the identically
    # placed front half drawn after the ball, so the ball appears to pass
    # through the hoop opening.
    ring_back = _ring_img("ring_back_basketball.png")
    if ring_back is not None:
        surface.blit(ring_back, _ring_pos(hcx, hcy, ring_back))
    else:
        # Fallback vector net + far rim arc if the asset is ever missing.
        net_h   = 55
        base_rx = HOOP_RX // 2
        top_y   = hcy + HOOP_RY
        bot_y   = hcy + net_h
        for i in range(9):
            t     = i / 8
            top_x = int(hcx - HOOP_RX + t * HOOP_RX * 2)
            bot_x = int(hcx - base_rx  + t * base_rx  * 2)
            pygame.draw.line(surface, _NET_COL, (top_x, top_y), (bot_x, bot_y), 1)
        for j in range(1, 5):
            p     = j / 4
            y_l   = int(top_y + p * (bot_y - top_y))
            left  = int(hcx - HOOP_RX + p * (HOOP_RX - base_rx))
            right = int(hcx + HOOP_RX - p * (HOOP_RX - base_rx))
            pygame.draw.line(surface, _NET_COL, (left, y_l), (right, y_l), 1)
        rim_rect = pygame.Rect(hcx - HOOP_RX, hcy - HOOP_RY, HOOP_RX * 2, HOOP_RY * 2)
        pygame.draw.arc(surface, _RIM_DARK, rim_rect, 0, math.pi, 6)


def _draw_hoop_front(surface, hx, hy):
    """Ring — front half (near side of rim + net), drawn over the ball for depth."""
    hcx = hx + HOOP_RX
    hcy = hy
    ring_front = _ring_img("ring_front_basketball.png")
    if ring_front is not None:
        surface.blit(ring_front, _ring_pos(hcx, hcy, ring_front, _RING_FRONT_EXTRA_Y))
    else:
        rim_rect = pygame.Rect(hcx - HOOP_RX, hcy - HOOP_RY, HOOP_RX * 2, HOOP_RY * 2)
        pygame.draw.arc(surface, _RIM_COL, rim_rect, math.pi, 2 * math.pi, 6)


# Grip bar track: vivid red at the top fading to a light pink at the bottom,
# a bright green target-zone band, and a black capsule-shaped needle.
_BAR_RED_TOP    = (235, 40, 35)
_BAR_RED_BOTTOM = (247, 175, 180)


def _draw_vertical_gradient_rect(surface, rect, top_col, bot_col, radius):
    """A top-to-bottom gradient filling a rounded rect (pygame has no
    built-in gradient fill, so this blends a per-row gradient onto a
    rounded-rect alpha mask)."""
    w, h = rect.width, rect.height
    grad = pygame.Surface((w, h), pygame.SRCALPHA)
    for yy in range(h):
        t = yy / max(1, h - 1)
        col = (int(top_col[0] + (bot_col[0] - top_col[0]) * t),
               int(top_col[1] + (bot_col[1] - top_col[1]) * t),
               int(top_col[2] + (bot_col[2] - top_col[2]) * t), 255)
        pygame.draw.line(grad, col, (0, yy), (w, yy))
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(grad, rect.topleft)


class BasketballGame(FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "grip"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        # Advanced Settings overrides (set by the therapist on the
        # calibration Advanced Settings screen) take priority; absent an
        # override, fall back to the normal per-difficulty preset.
        cal_params  = self.cal.get("params", {})
        self.goal   = cal_params.get("bb_goal", GOALS[self.difficulty])
        self.zone_w = cal_params.get("bb_zone_width", ZONE_WIDTH[self.difficulty])
        _spd_map    = {"Slow": 0.07, "Normal": 0.18, "Fast": 0.32}
        self.zone_speed = _spd_map.get(data.get("speed", "Normal"), 0.18)

        dur = data.get("duration_sec")
        self.time_start = int(dur) if dur else TIME_START[self.difficulty]

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        try:
            from db.database import get_volume
            self.pause_vol = get_volume()
        except Exception:
            self.pause_vol = 0.4

        self._font_hud = pygame.font.SysFont("monospace", 36, bold=True)
        self._font_sm  = pygame.font.SysFont("monospace", 26)
        self._font_fb  = pygame.font.SysFont("monospace", 52, bold=True)

        _prewarm_ball_cache()
        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    def _reset(self):
        self.game_over           = False
        self._grip_ignore_timer  = 0.0
        self.score          = 0
        self.reps           = 0
        self.time_left      = float(self.time_start)
        self.start_time     = pygame.time.get_ticks()
        self._pre_complete   = False
        self._pre_complete_t = 0.0

        self.zone_pos = random.uniform(0.15, 0.50)
        self.zone_dir = 1

        self._grip      = 0.0
        self._squeezing = False
        self._cooldown  = 0.0

        # Hoop is fixed at screen center -- the backboard's own position is
        # derived from this same hoop_y (see _draw_hoop_back), so moving it
        # moves the ring and board down together as one unit.
        self.hoop_x = GAME_W // 2 - HOOP_RX
        self.hoop_y = 340

        # Ball rest position changes each round
        self.ball_x      = float(self._rand_ball_x())
        self.ball_y      = float(GAME_H - 160)
        self.ball_vx     = 0.0
        self.ball_vy     = 0.0
        self.ball_r      = BALL_R_HELD
        self.ball_active = False
        self._above_ring = False
        self._hoop_center_x  = self.hoop_x + HOOP_RX
        self._shot_elapsed = 0.0
        self._shot_duration = 1.0
        self._next_ball_x = None

        self.feedback    = None
        self.score_flash = 0.0
        self._state      = {"grip": 0.0}

    def _normalize(self, raw):
        rest = self.cal.get("grip_rest", 0.0)
        mx   = self.cal.get("grip_max",  1.0)
        if mx <= rest:
            return raw
        return max(0.0, min(1.0, (raw - rest) / (mx - rest)))

    # ------------------------------------------------------------------ #

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions    = False
                self.start_time            = pygame.time.get_ticks()
                self._grip                 = 0.0
                self._squeezing            = False
                self._grip_ignore_timer    = 0.8
                start_music(game_music_path("Basketball", self.difficulty))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(game_music_path("Basketball", self.difficulty))
                elif self._results_exit_rect.collidepoint(event.pos):
                    play_click()
                    self._exit_to_game_config()
            return

        if self.fatigue_paused:
            if input_handler.was_pressed(event, "action"):
                self._resume_fatigue()
            return
        if self.paused:
            self._pause_handle(event)
            return
        if input_handler.was_pressed(event, "back"):
            self.paused = True

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
            lambda: setattr(self, "paused", False),
            lambda: (self._reset(), setattr(self, "_show_instructions", False),
                     setattr(self, "paused", False),
                     start_music(game_music_path("Basketball", self.difficulty))),
            lambda: setattr(self, "vol_active", True),
            self._exit_to_game_config,
        ]
        for i, action in enumerate(opts_actions):
            oy = GAME_H // 2 - 160 + i * 96
            if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                play_click()
                action()
                return

    # ------------------------------------------------------------------ #

    def update(self, dt):
        if self._show_instructions or self.game_over:
            return

        self._state = input_handler.get_state()
        self._update_fatigue(dt, self._state)
        if self.fatigue_paused or self.paused:
            return

        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0.0
            if not self._pre_complete:
                self._pre_complete   = True
                self._pre_complete_t = 0.8
                pygame.mixer.music.fadeout(800)
            else:
                self._pre_complete_t -= dt
                if self._pre_complete_t <= 0:
                    self._end_game()
            return

        raw = self._normalize(self._state["grip"])

        # Grace period after instructions dismissed — ignore grip so the dismiss-squeeze doesn't charge bar
        if self._grip_ignore_timer > 0:
            self._grip_ignore_timer -= dt
            raw = 0.0
            self._grip      = 0.0
            self._squeezing = False

        # Evaluate zone from CURRENT grip before updating it
        needle_now = 1.0 - self._grip
        half       = self.zone_w / 2
        in_zone    = (self.zone_pos - half) <= needle_now <= (self.zone_pos + half)

        was_squeezing   = self._squeezing
        self._squeezing = raw > 0.1

        # Release detection -- scoring is decided HERE, by the grip-release
        # condition alone. A correct release always scores; the shot that
        # follows is just the visual result of that point, not a separate
        # check the ball has to pass.
        if not self.ball_active and self._cooldown <= 0:
            if was_squeezing and not self._squeezing:
                if in_zone:
                    self.score       += 1
                    self.reps        += 1
                    self.score_flash  = 0.6
                    self.feedback     = ("PERFECT!", (0, 255, 160), 1.5)
                    play_success()
                    self._shoot()
                else:
                    self.feedback = ("MISSED — release in the GREEN zone!", (255, 60, 80), 1.5)
                    play_error()
                self._cooldown = 0.6
                self._grip = 0.0   # reset needle immediately after shot or miss

        if self._cooldown > 0:
            self._cooldown -= dt

        # Zone movement — moves only while relaxed
        if self.zone_speed > 0 and raw <= 0.1:
            self.zone_pos += self.zone_dir * self.zone_speed * dt
            if self.zone_pos > 0.55: self.zone_dir = -1
            if self.zone_pos < 0.10: self.zone_dir =  1

        # Needle: rises while squeezing, drops to 0 instantly on release
        if raw > 0.1:
            self._grip = min(1.0, self._grip + RAMP_UP * dt)
        else:
            self._grip = 0.0

        # Ball physics
        if self.ball_active:
            self.ball_vy += GRAVITY * dt
            if not self._above_ring:
                self.ball_x += self.ball_vx * dt
            self.ball_y += self.ball_vy * dt

            # Once the ball's vertical velocity turns from rising to falling
            # it has passed its apex and is directly above the hoop (all
            # sideways travel happened during the rise, above) -- from here
            # it drops straight down the hoop's own center line, so it
            # visibly passes through the middle of both the front and back
            # rings instead of continuing to drift sideways while falling.
            # (Checked via velocity sign rather than the analytic apex_y
            # position, since discrete timestep integration may not land
            # exactly on that position.)
            if not self._above_ring and self.ball_vy >= 0:
                self._above_ring = True
                self.ball_x  = self._hoop_center_x
                self.ball_vx = 0.0

            # Perspective cue: the ball shrinks smoothly from its held size
            # down to its hoop-opening size as the shot progresses, in sync
            # with the flight rather than snapping instantly.
            self._shot_elapsed += dt
            progress = min(1.0, self._shot_elapsed / self._shot_duration)
            self.ball_r = BALL_R_HELD + (BALL_R_HOOP - BALL_R_HELD) * progress

            # Scoring already happened at release, above -- this is purely
            # the visual shot animation now. It ends once the ball has had
            # time to reach the rim (per the trajectory computed in
            # _shoot()) AND has fallen all the way down to the court, so it's
            # seen passing through the net and landing on the ground rather
            # than disappearing shortly after entering the hoop, or if it
            # ever goes out of bounds as a safety fallback.
            reached_hoop = self._shot_elapsed >= self._shot_duration
            landed = reached_hoop and self.ball_y >= STAND_GROUND_Y
            out_of_bounds = (self.ball_y > GAME_H + 80 or
                              self.ball_x < -80 or self.ball_x > GAME_W + 80)
            if landed or out_of_bounds:
                self.ball_active = False
                self._advance_hoop()


        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None
        if self.score_flash > 0:
            self.score_flash -= dt

    def _rand_ball_x(self):
        """Return a random ball rest x that avoids the hoop centre."""
        if random.random() < 0.5:
            return float(random.randint(150, GAME_W // 2 - 220))   # left side
        return float(random.randint(GAME_W // 2 + 220, GAME_W - 150))  # right side

    def _advance_hoop(self):
        self.ball_r = BALL_R_HELD
        if self._next_ball_x is not None:
            self.ball_x      = self._next_ball_x
            self.ball_y      = float(GAME_H - 160)
            self._next_ball_x = None

    def _shoot(self):
        bx0 = self.ball_x
        by0 = float(GAME_H - 160)
        hcx = float(self.hoop_x + HOOP_RX)
        hcy = float(self.hoop_y)

        # Apex is set well above the rim opening so the ball visibly clears
        # it by a clear margin before descending. All of the sideways travel
        # happens during the rise (below) -- by the apex the ball is already
        # centered over the hoop, so the whole descent afterward is a
        # straight vertical drop through the middle of the front and back
        # rings, instead of still drifting sideways while falling through.
        apex_y = hcy - 300.0
        rise   = by0 - apex_y
        fall   = hcy - apex_y
        t_rise = math.sqrt(2 * rise / GRAVITY)
        t_fall = math.sqrt(2 * fall / GRAVITY)
        t_total = t_rise + t_fall

        self.ball_x      = bx0
        self.ball_y      = by0
        self.ball_vx     = (hcx - bx0) / t_rise
        self.ball_vy     = -GRAVITY * t_rise
        self.ball_r      = BALL_R_HELD
        self.ball_active = True
        self._above_ring     = False
        self._hoop_center_x  = hcx
        self._shot_elapsed  = 0.0
        self._shot_duration = t_total

        self._next_ball_x = self._rand_ball_x()
        self.zone_pos     = random.uniform(0.15, 0.50)

    # ------------------------------------------------------------------ #

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 860, 560
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (252,), (0, 0, pw, ph), border_radius=16)
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, T["ACCENT"], pygame.Rect(px, py, pw, ph), 2, border_radius=16)

        f_title = pygame.font.SysFont("monospace", 36, bold=True)
        f_head  = pygame.font.SysFont("monospace", 22, bold=True)
        f_body  = pygame.font.SysFont("monospace", 19)
        f_hint  = pygame.font.SysFont("monospace", 21, bold=True)

        diff_col = {"Easy": T["GREEN"], "Medium": T["YELLOW"], "Hard": T["RED"]}[self.difficulty]
        title = f_title.render("How to Play", True, diff_col)
        surface.blit(title, title.get_rect(centerx=GAME_W // 2, top=py + 26))
        pygame.draw.line(surface, T["ACCENT"], (px + 40, py + 78), (px + pw - 40, py + 78), 1)

        y = py + 96
        for header, lines in [
            ("OBJECTIVE", [
                "Squeeze your hand to raise the needle on the grip bar.",
                "When the needle enters the GREEN zone, RELEASE to shoot!",
                "The ball must pass through the hoop to score a basket.",
            ]),
            ("CONTROLS", [
                "Squeeze - pushes the needle up.",
                "Release - stops the needle.",
            ]),
            ("THIS SESSION", [
                f"Duration:   {self.time_start} seconds",
                f"Difficulty: {self.difficulty}",
            ]),
        ]:
            surface.blit(f_head.render(header, True, T["ACCENT"]), (px + 48, y))
            y += 30
            for line in lines:
                surface.blit(f_body.render(line, True, T["TEXT"]), (px + 64, y))
                y += 26
            y += 14

        blink_col = T["YELLOW"] if (pygame.time.get_ticks() // 600) % 2 == 0 else T["GRAY"]
        hint = f_hint.render("Press any key or click to begin", True, blink_col)
        surface.blit(hint, hint.get_rect(centerx=GAME_W // 2, bottom=py + ph - 20))

    def _exit_to_game_config(self):
        import builtins
        stop_music()
        builtins.pending_panel   = 4
        builtins.pending_patient = self._patient
        builtins.pending_account = self.account
        self.manager.go_to("therapist_dashboard")

    def _end_game(self):
        if self.game_over:
            return
        stop_music()
        play_completion()
        self.game_over_duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.game_over_score    = self.score
        try:
            from database import Database
            db = Database()
            patient_id = self._patient.get("id") if self._patient else None
            db.save_session(
                patient_id   = patient_id,
                therapist_id = self.account_id,
                game         = "Basketball",
                score        = self.score,
                duration_sec = self.game_over_duration,
                difficulty   = self.difficulty,
            )
        except Exception:
            pass
        self.game_over = True

    def _draw_results(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        surface.blit(ov, (0, 0))

        mw, mh = 640, 400
        mx, my = (GAME_W - mw) // 2, (GAME_H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (245,), (0, 0, mw, mh), border_radius=16)
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, T["ACCENT"], mr, 2, border_radius=16)

        f_big = pygame.font.SysFont("monospace", 48, bold=True)
        f_mid = pygame.font.SysFont("monospace", 32, bold=True)
        f_sm  = pygame.font.SysFont("monospace", 24)
        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        title = f_big.render("Session Complete!", True, T["YELLOW"])
        surface.blit(title, title.get_rect(center=(mr.centerx, my + 60)))

        sc_s = f_mid.render(f"Score:    {self.game_over_score}", True, T["TEXT"])
        surface.blit(sc_s, sc_s.get_rect(midleft=(mx + 80, my + 140)))

        mins, secs = divmod(self.game_over_duration, 60)
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, T["TEXT"])
        surface.blit(du_s, du_s.get_rect(midleft=(mx + 80, my + 190)))

        dif_s = f_sm.render(f"Difficulty: {self.difficulty}", True, T["GRAY"])
        surface.blit(dif_s, dif_s.get_rect(midleft=(mx + 80, my + 238)))

        mp  = pygame.mouse.get_pos()
        bw, bh = 220, 52

        again_r = pygame.Rect(mx + 60,           my + mh - 80, bw, bh)
        exit_r  = pygame.Rect(mx + mw - 60 - bw, my + mh - 80, bw, bh)
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

    # ------------------------------------------------------------------ #

    def draw(self, surface):
        T = get_theme()
        bg_img = _load_image_cover("bg_basketball.png", GAME_W, GAME_H)
        if bg_img is not None:
            surface.blit(bg_img, (0, 0))
        else:
            surface.fill(T["BG"])
            for y in range(0, GAME_H, 60):
                pygame.draw.line(surface, T["PANEL"], (0, y), (GAME_W, y), 1)

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        font_sm  = self._font_sm

        # Z-ordered drawing: back of hoop → ball → hand (while resting, so the
        # fingers appear to hold the ball) → front of hoop
        _draw_hoop_back(surface, self.hoop_x, self.hoop_y)
        _draw_basketball(surface, int(self.ball_x), int(self.ball_y), self.ball_r)
        if not self.ball_active:
            _draw_hand(surface, self.ball_x, self.ball_y)
        _draw_hoop_front(surface, self.hoop_x, self.hoop_y)

        # Grip bar
        needle  = 1.0 - self._grip
        half    = self.zone_w / 2

        _draw_vertical_gradient_rect(surface, pygame.Rect(BAR_X, BAR_Y, BAR_W, BAR_H),
                                     _BAR_RED_TOP, _BAR_RED_BOTTOM, 8)
        gz_y = BAR_Y + int((self.zone_pos - half) * BAR_H)
        gz_h = max(6, int(self.zone_w * BAR_H))
        pygame.draw.rect(surface, T["GREEN"], (BAR_X, gz_y, BAR_W, gz_h), border_radius=4)
        needle_y = BAR_Y + int(needle * BAR_H)
        pygame.draw.rect(surface, T["BLACK"],
                         (BAR_X - 20, needle_y - 8, BAR_W + 40, 16), border_radius=8)
        pygame.draw.rect(surface, T["BLACK"], (BAR_X, BAR_Y, BAR_W, BAR_H), 2, border_radius=8)
        surface.blit(font_sm.render("GRIP", True, T["GRAY"]),
                     (BAR_X - 8, BAR_Y - 34))
        surface.blit(font_sm.render(f"{int(self._grip * 100)}%", True, T["ACCENT"]),
                     (BAR_X - 8, BAR_Y + BAR_H + 8))

        # Score flash
        if self.score_flash > 0:
            alpha = int(80 * min(1.0, self.score_flash / 0.3))
            fl = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
            fl.fill((0, 255, 160, alpha))
            surface.blit(fl, (0, 0))

        # HUD
        draw_game_header(surface, "Basketball", self.difficulty,
                          self.time_left, self.score, GAME_W, GAME_H)

        # Feedback
        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, GAME_H // 2 - 60))

        # Hint
        if self.difficulty == "Easy":
            hint = "Squeeze into the GREEN zone, then RELEASE to shoot"
        else:
            hint = "Zone moves while relaxed -- squeeze to freeze, release in GREEN to shoot"
        surface.blit(font_sm.render(hint, True, T["GRAY"]), (80, GAME_H - 44))

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)
