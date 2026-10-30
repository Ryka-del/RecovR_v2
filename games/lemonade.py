"""
Lemonade -- Grip Strength rehabilitation game (1920x1080)

One completed lemon = one sustained squeeze-and-release repetition:

  1. WAITING   -- hold_lemonade shown; waiting for the calibrated FSR402
                  grip input to reach the difficulty's activation threshold.
  2. SQUEEZING -- squeeze_lemonade shown; juice flows and the pitcher's
                  fill level rises while the grip stays above threshold,
                  gradually filling THIS lemon's own (uncommitted) share,
                  capped once its allocated contribution is reached.
  3. READY     -- the required hold duration has been reached; the fill is
                  frozen (not counted yet) until the patient actually
                  releases. Continuing to squeeze cannot add more juice or
                  count more than one lemon -- it just waits for release.
  4. release   -- counts exactly one repetition, commits this lemon's juice
                  into the pitcher's permanent total, decrements Lemons
                  Left, updates the score, and returns to WAITING.
                  Releasing before READY discards the temporary juice and
                  does NOT count.

Session management, calibration, the shared header, pause/results/fatigue
all reuse the same systems every other RecovR game uses (FatigueMixin,
games/game_header.py, database.Database, sensors.input_handler) -- no
duplicate sensor-processing or session logic.
"""

import os
import math
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import (play_error, play_completion,
                    start_music, stop_music, play_click)
from constants import get_theme, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM

# -- Difficulty configuration (per-difficulty, never a single hardcoded
# clinical value) -- overridable via the existing duration_sec config knob
# exactly like every other game; there is no separate "Advanced Settings"
# override for grip threshold / hold duration anywhere else in RecovR today,
# so those two stay difficulty-driven defaults, same as every other game's
# per-difficulty tables (GOALS/TIME_START/etc. in games/basketball.py). ----
LEMON_TARGET   = {"Easy": 15, "Medium": 30, "Hard": 50}         # repetitions -> pitcher 100% full
GRIP_THRESHOLD = {"Easy": 0.35, "Medium": 0.45, "Hard": 0.55}   # calibrated grip (0-1) to start a squeeze
HOLD_DURATION  = {"Easy": 0.8,  "Medium": 1.2,  "Hard": 1.6}    # seconds the grip must be sustained
TIME_LIMIT     = {"Easy": 90,   "Medium": 120,  "Hard": 150}    # default session length

# Release threshold = activation threshold * this factor -- a small
# hysteresis band so the needle doesn't flicker in/out of "squeezing" right
# at the activation line. RecovR has no separately configured release
# threshold elsewhere, so this reuses the SAME calibrated grip value rather
# than a second sensor-processing path.
RELEASE_FACTOR = 0.78

# A pitcher ALWAYS takes exactly 10 successfully completed lemons to fill,
# regardless of difficulty -- difficulty only changes the grip threshold,
# hold duration, and total repetition target (how many pitchers that target
# works out to, e.g. Medium's 30 lemons = 3 pitchers, is never hardcoded;
# it falls out naturally from counting lemons-per-pitcher as they happen).
PITCHER_LEMONS       = 10
JUICE_PER_LEMON_PCT  = 100.0 / PITCHER_LEMONS

# Pitcher-replacement animation timings (visual recommendations; gameplay
# timing -- the session clock, grip thresholds, hold duration -- is
# untouched by any of these).
POUR_ANIM_DUR    = 1.0   # synced with the ~1s pour_juice sound
FULL_DISPLAY_DUR = 0.5
SLIDE_OUT_DUR    = 0.7
SLIDE_IN_DUR     = 0.7
# Centered on screen, a pitcher's own width never exceeds GAME_W, so sliding
# by a full GAME_W always clears both edges with margin to spare.
PITCHER_SLIDE_DISTANCE = GAME_W

# Lemon segment fill progress indicator -- a brief flash/bounce once all 8
# segments are filled (purely cosmetic, independent of the pitcher's own
# pour/replacement timing above).
INDICATOR_FLASH_DUR = 0.45
INDICATOR_SEGMENTS  = 8

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}

# games/game_header.py's audio.game_music_path() looks for a per-difficulty
# "<Game> <Difficulty>.mp3" file and falls back to the generic sci-fi track
# when none exists -- there's only one flat lemonade.mp3 (no per-difficulty
# variants), so that lookup would never actually find it. Point straight at
# the existing asset instead, via the SAME start_music()/stop_music() the
# rest of RecovR uses, rather than a separate audio system.
_LEMONADE_MUSIC     = os.path.join(_ROOT, "assets", "audio", "lemonade.mp3")
_LEMON_SQUEEZE_SFX  = os.path.join(_ROOT, "assets", "audio", "lemon_squeeze.mp3")
_POUR_JUICE_SFX     = os.path.join(_ROOT, "assets", "audio", "pour_juice.mp3")

_sfx_cache = {}


def _get_sfx(path):
    """Same cached-Sound pattern audio.py's _get_sound() uses for every
    other one-shot effect in RecovR -- Sound.play() runs on the mixer's
    channel pool, entirely separate from pygame.mixer.music (lemonade.mp3),
    so these effects can never interrupt or replace the background music."""
    if path not in _sfx_cache:
        try:
            _sfx_cache[path] = pygame.mixer.Sound(path)
        except Exception:
            _sfx_cache[path] = None
    return _sfx_cache[path]


def _load_fit(name, w, h):
    """Crop to the asset's own opaque content, then scale to fit within
    w x h preserving aspect ratio (never stretched/distorted)."""
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


def _load_scale_to_height(name, target_h):
    """Crop to the asset's own opaque content (excluding transparent
    padding), then scale it UNIFORMLY -- the same factor for width and
    height, derived purely from its visible height vs target_h -- so its
    width is whatever that proportional scale produces, even if that
    overflows the target area (the caller may let it clip). Unlike
    _load_fit, width is never separately constrained to fit a box."""
    key = ("scaleh", name, target_h)
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
            cw, ch = cropped.get_size()
            scale = target_h / ch
            _img_cache[key] = pygame.transform.smoothscale(
                cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
        except Exception:
            _img_cache[key] = None
    return _img_cache[key]


def _load_cover(name, w, h):
    """A full-bleed background scaled + center-cropped to exactly fill
    w x h (preserves aspect ratio -- no stretching)."""
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


def _load_raw_scaled(name, h):
    """Load the asset at its FULL (uncropped) native canvas, scaled
    uniformly so its height is `h`. Used only for pitcher_lemonade.png, so
    the juice fill (traced from the same uncropped canvas -- see
    _JUICE_PROFILE below) lines up with the glass exactly instead of
    drifting after an independent crop-to-content."""
    key = ("raw", name, h)
    if key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_ROOT, "assets", "images", name)).convert_alpha()
            rw, rh = raw.get_size()
            w = max(1, int(rw * (h / rh)))
            _img_cache[key] = pygame.transform.smoothscale(raw, (w, h))
        except Exception:
            _img_cache[key] = None
    return _img_cache[key]


# Interior-wall profile of pitcher_lemonade.png's glass, traced from
# assets/images/juice_lemonade.png (a guide outline of the glass's inside
# silhouette baked on the SAME 2956x1969 canvas) as
# (y_fraction, left_x_fraction, right_x_fraction) rows from the rim opening
# down to the rounded base. Used to render the rising juice level following
# the glass's own tapered shape instead of a plain rectangle.
_JUICE_PROFILE = [
    (0.1493, 0.2984, 0.6438), (0.1646, 0.2997, 0.6424), (0.1798, 0.3011, 0.6411),
    (0.1950, 0.3024, 0.6394), (0.2103, 0.3038, 0.6380), (0.2255, 0.3051, 0.6367),
    (0.2407, 0.3065, 0.6353), (0.2529, 0.3075, 0.6340), (0.2682, 0.3089, 0.6326),
    (0.2834, 0.3102, 0.6313), (0.2986, 0.3116, 0.6296), (0.3139, 0.3129, 0.6282),
    (0.3291, 0.3139, 0.6269), (0.3443, 0.3153, 0.6255), (0.3596, 0.3166, 0.6238),
    (0.3748, 0.3180, 0.6225), (0.3900, 0.3194, 0.6211), (0.4053, 0.3207, 0.6198),
    (0.4205, 0.3221, 0.6181), (0.4327, 0.3231, 0.6171), (0.4479, 0.3244, 0.6154),
    (0.4632, 0.3258, 0.6140), (0.4784, 0.3271, 0.6127), (0.4937, 0.3285, 0.6113),
    (0.5089, 0.3298, 0.6096), (0.5241, 0.3312, 0.6083), (0.5394, 0.3325, 0.6069),
    (0.5546, 0.3339, 0.6052), (0.5698, 0.3353, 0.6039), (0.5851, 0.3366, 0.6025),
    (0.6003, 0.3376, 0.6012), (0.6125, 0.3390, 0.5998), (0.6277, 0.3403, 0.5984),
    (0.6430, 0.3413, 0.5971), (0.6582, 0.3430, 0.5954), (0.6734, 0.3440, 0.5940),
    (0.6887, 0.3454, 0.5927), (0.7039, 0.3468, 0.5913), (0.7191, 0.3481, 0.5896),
    (0.7344, 0.3495, 0.5883), (0.7496, 0.3508, 0.5869), (0.7649, 0.3522, 0.5853),
    (0.7801, 0.3535, 0.5839), (0.7923, 0.3545, 0.5829), (0.8075, 0.3562, 0.5798),
    (0.8228, 0.3606, 0.5741), (0.8380, 0.3677, 0.5656), (0.8532, 0.3792, 0.5531),
    (0.8685, 0.3982, 0.5332), (0.8837, 0.4489, 0.4834),
]


def _profile_x_at(yf):
    pts = _JUICE_PROFILE
    if yf <= pts[0][0]:
        return pts[0][1], pts[0][2]
    if yf >= pts[-1][0]:
        return pts[-1][1], pts[-1][2]
    for i in range(len(pts) - 1):
        y0, l0, r0 = pts[i]
        y1, l1, r1 = pts[i + 1]
        if y0 <= yf <= y1:
            t = (yf - y0) / max(1e-6, (y1 - y0))
            return l0 + (l1 - l0) * t, r0 + (r1 - r0) * t
    return pts[-1][1], pts[-1][2]


def _draw_pitcher(surface, cx, bottom_y, pitcher_h, fill_frac, color_dark, color_light):
    """Draw the glass, then the juice -- clipped to the glass's own interior
    silhouette, rising from the base -- fully opaque ON TOP of it.
    pitcher_lemonade.png's body is a near-opaque (~91% alpha) pale overlay
    baked in for its own glossy-glass look; drawing the liquid underneath it
    (as an earlier version of this did) left any fill colour almost
    completely washed out to a pale cream regardless of how saturated it
    was -- math some colour simply cannot survive a 91%-opacity near-white
    layer on top. Painting the liquid afterward keeps it clearly, brightly
    visible while the glass's handle and outer rim contour (both outside
    the interior silhouette the liquid is clipped to) still read normally.
    Returns the glass's on-screen rect (used to aim the juice-drip
    animation)."""
    img = _load_raw_scaled("pitcher_lemonade.png", pitcher_h)
    if img is None:
        return pygame.Rect(cx, bottom_y - pitcher_h, 1, pitcher_h)
    pw, ph = img.get_size()
    px = cx - pw // 2
    py = bottom_y - ph

    surface.blit(img, (px, py))

    fill_frac = max(0.0, min(1.0, fill_frac))
    if fill_frac > 0.001:
        y_bottom   = _JUICE_PROFILE[-1][0]
        y_top_full = _JUICE_PROFILE[0][0]
        y0 = y_bottom - fill_frac * (y_bottom - y_top_full)
        lx0, rx0 = _profile_x_at(y0)
        rows = [p for p in _JUICE_PROFILE if p[0] > y0]
        left_pts  = [(lx0, y0)] + [(l, y) for y, l, r in rows]
        right_pts = [(r, y) for y, l, r in reversed(rows)] + [(rx0, y0)]
        poly = [(x * pw, y * ph) for x, y in (left_pts + right_pts)]
        if len(poly) >= 3:
            liquid = pygame.Surface((pw, ph), pygame.SRCALPHA)
            pygame.draw.polygon(liquid, color_dark, poly)
            near_surface = rows[:5]
            surf_pts = ([(lx0, y0)] + [(l, y) for y, l, r in near_surface]
                        + [(r, y) for y, l, r in reversed(near_surface)] + [(rx0, y0)])
            if len(surf_pts) >= 3:
                pygame.draw.polygon(liquid, color_light,
                                    [(x * pw, y * ph) for x, y in surf_pts])
            surface.blit(liquid, (px, py))

    return pygame.Rect(px, py, pw, ph)


class LemonadeGame(FatigueMixin, BaseScreen):

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
        cal_params           = self.cal.get("params", {})
        self.target          = cal_params.get("lem_target", LEMON_TARGET[self.difficulty])
        self.grip_threshold  = cal_params.get("lem_grip_threshold", GRIP_THRESHOLD[self.difficulty])
        self.release_threshold = self.grip_threshold * RELEASE_FACTOR
        self.hold_required   = cal_params.get("lem_hold_duration", HOLD_DURATION[self.difficulty])
        self.juice_per_lemon = JUICE_PER_LEMON_PCT   # always 10% -- see PITCHER_LEMONS

        dur = data.get("duration_sec")
        self.duration = int(dur) if dur else TIME_LIMIT[self.difficulty]

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

        self._font_sm  = pygame.font.SysFont("monospace", 26)
        self._font_fb  = pygame.font.SysFont("monospace", 46, bold=True)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    def _reset(self):
        self.game_over  = False
        self.score       = 0
        self.reps         = 0     # == completed lemons
        self.time_left    = float(self.duration)
        self.start_time   = pygame.time.get_ticks()

        # -- state machine ------------------------------------------------
        self._phase       = "waiting"   # "waiting" | "squeezing" | "ready"
        self._hold_elapsed = 0.0
        self._temp_fill    = 0.0        # this lemon's OWN uncommitted juice (0..juice_per_lemon)

        self.completed      = 0
        self.lemons_left    = self.target
        self.pitcher_fill    = 0.0       # current pitcher's committed juice, 0..100
        self.grip_active     = False
        self.calibrated_grip = 0.0

        self.feedback    = None
        self._state      = {"grip": 0.0}
        self._drip_t      = 0.0

        # -- lemon segment fill progress indicator -----------------------
        # Purely a visualisation of the SAME _phase/_hold_elapsed state the
        # squeeze mechanic already tracks -- no separate progress source.
        self._indicator_flash_t = 0.0   # brief flash/bounce right after a completed lemon

        # -- pitcher pour / replacement animation ---------------------
        self.pitcher_lemon_count = 0          # lemons completed in the CURRENT pitcher (0-10)
        self.pitcher_index       = 0          # which pitcher we're on (0-based), informational
        self._pitcher_state        = "idle"   # idle|pouring|full_display|sliding_out|sliding_in
        self._pitcher_anim_t       = 0.0
        self._pitcher_will_replace = False
        self._pitcher_pending_end  = False
        self._pitcher_x_offset     = 0.0
        # True right after a pitcher-replacement animation starts -- a grip
        # already held through it must NOT auto-count as a new squeeze once
        # gameplay resumes; the patient must release first.
        self._require_fresh_release = False

        self._squeeze_channel = None
        self._pour_channel    = None

    def _normalize_grip(self, raw):
        """SAME calibration formula every grip game uses -- no duplicate
        sensor-processing logic."""
        rest = self.cal.get("grip_rest", 0.0)
        mx   = self.cal.get("grip_max",  1.0)
        if mx <= rest:
            return raw
        return max(0.0, min(1.0, (raw - rest) / (mx - rest)))

    @staticmethod
    def _pause_music():
        """Pause lemonade.mp3 in place (not stop_music()'s full stop) so
        RESUME can continue from the same position -- scoped to this game's
        own pause flow only, not a change to the shared audio module."""
        try:
            pygame.mixer.music.pause()
        except Exception:
            pass

    @staticmethod
    def _resume_music():
        try:
            pygame.mixer.music.unpause()
        except Exception:
            pass

    def _start_squeeze_sound(self):
        """Triggered once on the resting-to-squeezing transition only (see
        _update_squeeze_state) -- never retriggered while the same squeeze
        continues, so a squeeze/hold longer than the clip just lets it play
        through once rather than restarting it every frame."""
        snd = _get_sfx(_LEMON_SQUEEZE_SFX)
        if snd is None:
            return
        try:
            if self._squeeze_channel is not None:
                self._squeeze_channel.stop()
            self._squeeze_channel = snd.play()
        except Exception:
            self._squeeze_channel = None

    def _stop_squeeze_sound(self):
        """The sound corresponds to the actual squeezing action, so it ends
        when squeezing ends (release, whether that completes a rep or
        discards an incomplete one) rather than always playing out in full."""
        try:
            if self._squeeze_channel is not None:
                self._squeeze_channel.stop()
        except Exception:
            pass
        self._squeeze_channel = None

    def _play_pour_sound(self):
        """~1 second of pour_juice.mp3 via Sound.play(maxtime=...) -- the
        built-in pygame mechanism for this, so the original file is never
        trimmed/modified. Stopping any previous instance first guarantees no
        overlap even if this were ever called in quick succession."""
        snd = _get_sfx(_POUR_JUICE_SFX)
        if snd is None:
            return
        try:
            if self._pour_channel is not None:
                self._pour_channel.stop()
            self._pour_channel = snd.play(maxtime=int(POUR_ANIM_DUR * 1000))
        except Exception:
            self._pour_channel = None

    def _pause_sfx(self):
        for ch in (self._squeeze_channel, self._pour_channel):
            try:
                if ch is not None:
                    ch.pause()
            except Exception:
                pass

    def _resume_sfx(self):
        for ch in (self._squeeze_channel, self._pour_channel):
            try:
                if ch is not None:
                    ch.unpause()
            except Exception:
                pass

    @staticmethod
    def _ease(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)   # smoothstep -- natural ease in/out

    # ------------------------------------------------------------------ #

    def handle_event(self, event):
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time         = pygame.time.get_ticks()
                start_music(_LEMONADE_MUSIC)
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(_LEMONADE_MUSIC)
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
            self._pause_music()
            self._pause_sfx()

    def _pause_handle(self, event):
        pos = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
        elif event.type == pygame.FINGERDOWN:
            pos = (int(event.x * GAME_W), int(event.y * GAME_H))
        if pos is None:
            return
        if self.vol_active:
            _bx = GAME_W // 2 - (10 * 30 + 9 * 6) // 2
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
            lambda: (setattr(self, "paused", False), self._resume_music(), self._resume_sfx()),
            lambda: (self._reset(), setattr(self, "_show_instructions", False),
                     setattr(self, "paused", False),
                     start_music(_LEMONADE_MUSIC)),
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

        self._drip_t += dt

        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0.0
            self._end_game()
            return

        # Sensor readings keep updating every frame regardless of what
        # follows, so the therapist monitoring interface always reflects
        # the real, live grip state -- including during a pour/replacement
        # animation.
        raw = self._state.get("grip", 0.0)
        self.calibrated_grip = self._normalize_grip(raw)
        self.grip_active = self.calibrated_grip >= self.grip_threshold

        # While a pitcher pour/replacement animation is in progress, the
        # squeeze state machine is frozen entirely (no new reps, no score,
        # no Lemons Left change) -- it resumes once the animation reaches
        # "idle" again.
        if self._pitcher_state != "idle":
            self._update_pitcher_animation(dt)
        else:
            self._update_squeeze_state(dt)

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

        if self._indicator_flash_t > 0:
            self._indicator_flash_t = max(0.0, self._indicator_flash_t - dt)

    def _update_squeeze_state(self, dt):
        if self._phase == "waiting":
            if self._require_fresh_release:
                # A grip held through a pitcher-replacement animation must
                # not auto-count as a new squeeze -- require it to actually
                # drop below threshold at least once first.
                if not self.grip_active:
                    self._require_fresh_release = False
                return
            if self.grip_active:
                self._phase        = "squeezing"
                self._hold_elapsed = 0.0
                self._temp_fill    = 0.0
                self._start_squeeze_sound()

        elif self._phase == "squeezing":
            if self.calibrated_grip < self.release_threshold:
                # released before completing the required hold -- discard
                # this lemon's temporary progress; committed juice is
                # untouched.
                self._phase        = "waiting"
                self._hold_elapsed = 0.0
                self._temp_fill    = 0.0
                self._stop_squeeze_sound()
            else:
                self._hold_elapsed += dt
                progress = min(1.0, self._hold_elapsed / self.hold_required)
                self._temp_fill = progress * self.juice_per_lemon   # capped automatically
                if self._hold_elapsed >= self.hold_required:
                    self._phase = "ready"

        elif self._phase == "ready":
            # Hold requirement already met -- a continued squeeze adds
            # nothing further; only an actual release commits the lemon.
            if self.calibrated_grip < self.release_threshold:
                self._stop_squeeze_sound()
                self._commit_lemon()

    def _commit_lemon(self):
        """One successful squeeze-and-release: update score/counters, and
        commit the juice INSTANTLY. The rising fill the patient already saw
        during the squeeze/hold (the live _temp_fill preview) IS the fill
        animation -- release just locks that same value in, so there is no
        second visual "pour" of the same 10%. The ~1s "pouring" pitcher-state
        that follows is now a pure timer kept in sync with the pour_juice
        sound (and, for a pitcher's 10th lemon, the lead-in to the
        replacement sequence) -- it no longer changes the fill level."""
        self.completed  += 1
        self.lemons_left = max(0, self.target - self.completed)
        self.score       += 1
        self.reps          = self.completed
        self.feedback      = ("LEMON COMPLETE!", (0, 220, 120), 1.0)
        self._indicator_flash_t = INDICATOR_FLASH_DUR

        self.pitcher_lemon_count += 1
        self.pitcher_fill = min(100.0, self.pitcher_fill + self.juice_per_lemon)
        self._temp_fill   = 0.0

        # The session's own final lemon never triggers a replacement, even
        # if it also happens to be this pitcher's 10th (no "next" pitcher is
        # needed -- the completed/partial pitcher is simply left on screen).
        self._pitcher_pending_end  = self.completed >= self.target
        self._pitcher_will_replace = (self.pitcher_lemon_count >= PITCHER_LEMONS
                                       and not self._pitcher_pending_end)
        if self._pitcher_will_replace:
            self._require_fresh_release = True

        self._play_pour_sound()

        self._phase          = "waiting"
        self._hold_elapsed   = 0.0
        self._pitcher_state  = "pouring"
        self._pitcher_anim_t = 0.0

    def _update_pitcher_animation(self, dt):
        self._pitcher_anim_t += dt

        if self._pitcher_state == "pouring":
            # Fill level was already committed instantly in _commit_lemon();
            # this is just a ~1s timer synced to the pour_juice sound.
            if self._pitcher_anim_t >= POUR_ANIM_DUR:
                if self._pitcher_pending_end:
                    self._pitcher_state = "idle"
                    self._end_game()
                    return
                if self._pitcher_will_replace:
                    self._pitcher_state  = "full_display"
                    self._pitcher_anim_t = 0.0
                else:
                    self._pitcher_state = "idle"

        elif self._pitcher_state == "full_display":
            if self._pitcher_anim_t >= FULL_DISPLAY_DUR:
                self._pitcher_state  = "sliding_out"
                self._pitcher_anim_t = 0.0

        elif self._pitcher_state == "sliding_out":
            t = min(1.0, self._pitcher_anim_t / SLIDE_OUT_DUR)
            self._pitcher_x_offset = PITCHER_SLIDE_DISTANCE * self._ease(t)
            if self._pitcher_anim_t >= SLIDE_OUT_DUR:
                # the full pitcher has exited -- the new one starts empty
                self.pitcher_fill        = 0.0
                self.pitcher_lemon_count = 0
                self.pitcher_index      += 1
                self._pitcher_state      = "sliding_in"
                self._pitcher_anim_t     = 0.0

        elif self._pitcher_state == "sliding_in":
            t = min(1.0, self._pitcher_anim_t / SLIDE_IN_DUR)
            self._pitcher_x_offset = PITCHER_SLIDE_DISTANCE * (1.0 - self._ease(t))
            if self._pitcher_anim_t >= SLIDE_IN_DUR:
                self._pitcher_x_offset = 0.0
                self._pitcher_state    = "idle"

    # ------------------------------------------------------------------ #

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        pw, ph = 900, 600
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
                "Squeeze the lemon firmly and HOLD it -- the hand changes",
                "to show you're squeezing hard enough.",
                "Keep squeezing until the hold is complete, then RELEASE",
                "to pour that lemon's juice into the pitcher.",
            ]),
            ("CONTROLS", [
                "Squeeze and hold - fills this lemon's juice.",
                "Release after the hold completes - counts the lemon.",
            ]),
            ("THIS SESSION", [
                f"Lemons needed: {self.target}",
                f"Duration:      {self.duration} seconds",
                f"Difficulty:    {self.difficulty}",
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
                game         = "Lemonade",
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

        mw, mh = 640, 420
        mx, my = (GAME_W - mw) // 2, (GAME_H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (245,), (0, 0, mw, mh), border_radius=16)
        surface.blit(bg, mr.topleft)
        pygame.draw.rect(surface, T["ACCENT"], mr, 2, border_radius=16)

        f_big = pygame.font.SysFont("monospace", 46, bold=True)
        f_mid = pygame.font.SysFont("monospace", 30, bold=True)
        f_sm  = pygame.font.SysFont("monospace", 22)
        f_btn = pygame.font.SysFont("monospace", 28, bold=True)

        title = f_big.render("Session Complete!", True, T["YELLOW"])
        surface.blit(title, title.get_rect(center=(mr.centerx, my + 56)))

        lemons_s = f_mid.render(f"Lemons completed: {self.completed}/{self.target}", True, T["TEXT"])
        surface.blit(lemons_s, lemons_s.get_rect(midleft=(mx + 70, my + 130)))

        sc_s = f_mid.render(f"Score: {self.game_over_score}", True, T["TEXT"])
        surface.blit(sc_s, sc_s.get_rect(midleft=(mx + 70, my + 172)))

        mins, secs = divmod(self.game_over_duration, 60)
        dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        du_s = f_mid.render(f"Duration: {dur_str}", True, T["TEXT"])
        surface.blit(du_s, du_s.get_rect(midleft=(mx + 70, my + 214)))

        dif_s = f_sm.render(f"Difficulty: {self.difficulty}", True, T["GRAY"])
        surface.blit(dif_s, dif_s.get_rect(midleft=(mx + 70, my + 256)))

        mp = pygame.mouse.get_pos()
        bw, bh = 220, 52
        again_r = pygame.Rect(mx + 60,          my + mh - 80, bw, bh)
        exit_r  = pygame.Rect(mx + mw - 60 - bw, my + mh - 80, bw, bh)
        self._results_again_rect = again_r
        self._results_exit_rect  = exit_r

        ag_col = (55, 170, 100) if again_r.collidepoint(mp) else (40, 140, 80)
        ex_col = (75, 110, 190) if exit_r.collidepoint(mp)  else (55, 85, 160)
        pygame.draw.rect(surface, ag_col, again_r, border_radius=10)
        pygame.draw.rect(surface, ex_col, exit_r,  border_radius=10)

        ag_lbl = f_btn.render("Play Again", True, T["WHITE"])
        ex_lbl = f_btn.render("Exit",       True, T["WHITE"])
        surface.blit(ag_lbl, ag_lbl.get_rect(center=again_r.center))
        surface.blit(ex_lbl, ex_lbl.get_rect(center=exit_r.center))

    # ------------------------------------------------------------------ #

    def _draw_lemons_left(self, surface):
        box_w, box_h = 230, 220
        bx, by = 56, HEADER_BOTTOM + 36
        img = _load_fit("left_lemons_bg.png", box_w, box_h)
        r = pygame.Rect(bx, by, box_w, box_h)
        if img is not None:
            r = img.get_rect(topleft=(bx, by))
            surface.blit(img, r)
        else:
            pygame.draw.rect(surface, (90, 195, 60), r, border_radius=20)

        f_lbl = pygame.font.SysFont("arial", 30, bold=True)
        f_val = pygame.font.SysFont("arial", 56, bold=True)
        lbl1 = f_lbl.render("Lemons", True, (255, 255, 255))
        lbl2 = f_lbl.render("left", True, (255, 255, 255))
        val  = f_val.render(f"{self.lemons_left:02d}", True, (255, 255, 255))

        # Center the WHOLE label+number group as one block within the box's
        # actual content rect, rather than anchoring the label from the top
        # and the number from the bottom independently (which left uneven,
        # resolution/font-size-dependent padding instead of true centering).
        # Each line is still individually horizontally centered -- correct
        # for stacked text of differing widths -- and recentres automatically
        # as the digit count changes (e.g. "00" vs a two-digit value).
        line_gap  = 4
        group_gap = 10
        group_h = (lbl1.get_height() + line_gap + lbl2.get_height()
                   + group_gap + val.get_height())
        gy = r.centery - group_h // 2
        surface.blit(lbl1, lbl1.get_rect(centerx=r.centerx, top=gy))
        gy += lbl1.get_height() + line_gap
        surface.blit(lbl2, lbl2.get_rect(centerx=r.centerx, top=gy))
        gy += lbl2.get_height() + group_gap
        surface.blit(val, val.get_rect(centerx=r.centerx, top=gy))

    def _draw_juice_drip(self, surface, hand_pos, pitcher_rect):
        """A few small animated drops arcing from the squeezed lemon toward
        the pitcher's rim while juice is actively being earned -- purely a
        visual cue alongside the rising fill level, not gameplay state."""
        if self._phase not in ("squeezing", "ready"):
            return
        target = (pitcher_rect.centerx, pitcher_rect.top + int(pitcher_rect.height * 0.12))
        n = 3
        for i in range(n):
            t = ((self._drip_t * 1.4) + i / n) % 1.0
            x = hand_pos[0] + (target[0] - hand_pos[0]) * t
            # a gentle arc rather than a straight line
            arc = -90 * (4 * t * (1 - t))
            y = hand_pos[1] + (target[1] - hand_pos[1]) * t + arc
            alpha = int(255 * (1.0 - 0.3 * t))
            r = max(2, int(7 - 3 * t))
            drop = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(drop, (255, 221, 51, alpha), (r, r), r)
            surface.blit(drop, (x - r, y - r))

    def _draw_progress_indicator(self, surface, cx, cy, radius):
        """Lemon-slice progress ring: 8 wedge segments that fill clockwise
        purely as a visualisation of the SAME _phase/_hold_elapsed the
        squeeze mechanic already tracks -- how long the grip has been
        continuously held, never how hard. No separate progress source,
        no gameplay effect of its own."""
        phase = self._phase
        active = phase in ("squeezing", "ready")
        if phase == "squeezing":
            progress = min(1.0, self._hold_elapsed / max(1e-6, self.hold_required))
        elif phase == "ready":
            progress = 1.0
        else:
            progress = 0.0

        flash = self._indicator_flash_t
        flash_frac = (flash / INDICATOR_FLASH_DUR) if INDICATOR_FLASH_DUR > 0 else 0.0
        bounce = 1.0 + 0.14 * math.sin(flash_frac * math.pi) if flash > 0 else 1.0
        r = max(10, int(radius * bounce))

        # a gentle glow while actively squeezing (or during the completion
        # flash) -- a few soft, low-alpha rings, nothing distracting
        if active or flash > 0:
            for i, a in enumerate((36, 22, 10)):
                gr = r + 8 + i * 9
                glow = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow, (255, 221, 60, a), (gr, gr), gr)
                surface.blit(glow, (cx - gr, cy - gr))

        DARK_SEG   = (118, 106, 56)     # desaturated/idle wedge colour
        BRIGHT_SEG = (255, 221, 51)     # juicy lemon-yellow, fully filled
        FLASH_SEG  = (255, 250, 214)    # brief bright-white flash on completion

        n = INDICATOR_SEGMENTS
        seg_span = 360.0 / n
        for i in range(n):
            seg_prog = max(0.0, min(1.0, progress * n - i))
            col = tuple(int(DARK_SEG[k] + (BRIGHT_SEG[k] - DARK_SEG[k]) * seg_prog) for k in range(3))
            if flash > 0:
                col = tuple(int(col[k] + (FLASH_SEG[k] - col[k]) * flash_frac) for k in range(3))
            a0 = math.radians(-90 + i * seg_span)
            a1 = math.radians(-90 + (i + 1) * seg_span)
            pts = [(cx, cy)]
            steps = 6
            for s in range(steps + 1):
                a = a0 + (a1 - a0) * (s / steps)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            pygame.draw.polygon(surface, col, pts)

        # thin cream separators between wedges, like a real sliced lemon
        for i in range(n):
            a = math.radians(-90 + i * seg_span)
            x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a)
            pygame.draw.line(surface, (255, 252, 235), (cx, cy), (x2, y2), 2)

        pygame.draw.circle(surface, (190, 196, 90), (cx, cy), r, 4)       # rind ring
        pygame.draw.circle(surface, (250, 250, 240), (cx, cy), max(3, int(r * 0.08)))  # core

        if flash > 0 or phase == "ready":
            label, col = "COMPLETE!", (120, 255, 160)
        elif phase == "squeezing":
            label, col = "KEEP SQUEEZING!", (255, 221, 60)
        else:
            label, col = "SQUEEZE", (235, 240, 248)
        lbl_s = self._font_sm.render(label, True, col)
        lbl_r = lbl_s.get_rect(centerx=cx, bottom=cy - r - 14)
        # a dark backing pill, same legibility trick the bottom hint bar
        # uses, so the label reads clearly against the bright sky behind it
        bar = pygame.Surface((lbl_r.width + 24, lbl_r.height + 10), pygame.SRCALPHA)
        pygame.draw.rect(bar, (10, 20, 15, 150), bar.get_rect(), border_radius=8)
        surface.blit(bar, (lbl_r.x - 12, lbl_r.y - 5))
        surface.blit(lbl_s, lbl_r)

    def draw(self, surface):
        T = get_theme()
        bg_img = _load_cover("bg_lemonade.png", GAME_W, GAME_H)
        if bg_img is not None:
            surface.blit(bg_img, (0, 0))
        else:
            surface.fill(T["BG"])

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        # -- table / stand -- centered, scaled UNIFORMLY (one factor for
        # both axes, never stretched) so its own VISIBLE height exactly
        # fills the screen: top = 0, bottom = GAME_H. Left/right may extend
        # past the screen edges and clip -- that's expected at this scale.
        #
        # The tabletop is drawn in perspective as a slab: pixel-coverage
        # first goes from ~8% (just the two support posts) to ~80%+ at
        # y_frac=~0.595 -- but that's the slab's BACK edge (farthest from
        # the camera), not where an object actually rests. The lit top face
        # continues at a flat, uniform colour all the way to y_frac=~0.757,
        # where it darkens into the slab's front bevel -- THAT edge (the
        # near side, closest to the camera) is the real resting surface;
        # anchoring to the back edge instead was leaving every item resting
        # on the table visibly "floating" above its actual visible bulk,
        # even though it technically touched the top-most tan pixel. Both
        # fractions were measured directly off the art and are scale-
        # independent, so this keeps working at any render size.
        stand_img = _load_scale_to_height("stand_lemonade.png", GAME_H)
        table_surface_y = GAME_H - 260
        if stand_img is not None:
            sr = stand_img.get_rect(midbottom=(GAME_W // 2, GAME_H))
            surface.blit(stand_img, sr)
            table_surface_y = sr.y + int(sr.height * 0.757)

        # -- basket (difficulty-specific) -- left of the pitcher, nudged a
        # little above the tabletop line (rather than sitting at the exact
        # same height as the pitcher's own bottom) so the two don't read as
        # mechanically level, while its own visible bottom still lands on
        # the tabletop with no gap. Each difficulty's art has different
        # internal padding (a different pile of lemons), but _load_fit crops
        # every one of them to its own opaque content first, so anchoring
        # all three the same way here still lines each one's real visible
        # bottom up with the table.
        basket_lift = int(GAME_H * 0.013)
        basket_name = {"Easy": "easy_lemonade.png", "Medium": "medium_lemonade.png",
                       "Hard": "hard_lemonade.png"}.get(self.difficulty, "easy_lemonade.png")
        basket_img = _load_fit(basket_name, 480, 400)
        if basket_img is not None:
            br = basket_img.get_rect(midbottom=(int(GAME_W * 0.205), table_surface_y - basket_lift))
            surface.blit(basket_img, br)

        # -- pitcher (center) -- juice drawn on top of its glass so the
        # fill stays clearly visible (see _draw_pitcher); resting
        # position/size are unchanged (visible bottom on the
        # tabletop surface) -- only sliding_out/sliding_in offset it
        # horizontally for the pitcher-replacement animation. A softer,
        # less saturated lemon-yellow at lower alpha so the glass's own
        # highlights underneath clearly show through -- reading as real
        # liquid inside the glass rather than a painted-on shape.
        light = (255, 240, 170, 150)
        dark  = (255, 221, 100, 150)
        pitcher_cx = GAME_W // 2 + int(self._pitcher_x_offset)
        if self._pitcher_state == "sliding_out":
            # the OLD, just-filled pitcher riding off to the right -- its
            # fill isn't reset to 0 until sliding_out finishes, so
            # self.pitcher_fill still holds the old pitcher's final value
            # here.
            pitcher_fill_display = self.pitcher_fill / 100.0
        elif self._pitcher_state == "sliding_in":
            # the NEW, empty pitcher arriving from the right
            pitcher_fill_display = 0.0
        else:
            # idle/pouring/full_display: committed juice + this lemon's own
            # (still uncommitted) hold-preview, so the level visibly rises
            # while squeezing and drops back if released early (discarded).
            pitcher_fill_display = (self.pitcher_fill + self._temp_fill) / 100.0
        pitcher_rect = _draw_pitcher(
            surface, pitcher_cx, table_surface_y, 560,
            pitcher_fill_display, dark, light)

        # -- hand (resting or squeezing) -- right side; the forearm is
        # pushed PAST the screen's bottom edge (FPS-style) so it's actually
        # clipped by the screen boundary instead of just touching it --
        # the hand/lemon stay fully visible since they sit in the sprite's
        # upper portion. Both sprites share this exact same anchor call
        # (same x, same extra drop), so switching hold/squeeze never shifts
        # the hand or the lemon's apparent position.
        hand_name = "squeeze_lemonade.png" if self._phase in ("squeezing", "ready") else "hold_lemonade.png"
        hand_img = _load_fit(hand_name, 560, 620)
        hand_x = int(GAME_W * 0.80)
        hand_bottom_y = GAME_H + int(GAME_H * 0.12)
        if hand_img is not None:
            hr = hand_img.get_rect(midbottom=(hand_x, hand_bottom_y))
            self._draw_juice_drip(surface, (hr.centerx - 60, hr.y + 120), pitcher_rect)
            surface.blit(hand_img, hr)

        # -- lemon segment progress indicator -- right side, directly above
        # the hand (same x as the hand's own anchor), clear of the header
        # above and the hand below regardless of hold/squeeze sprite.
        self._draw_progress_indicator(surface, hand_x, int(GAME_H * 0.335), 80)

        self._draw_lemons_left(surface)

        # -- shared header --
        draw_game_header(surface, "Lemonade", self.difficulty,
                          self.time_left, self.score, GAME_W, GAME_H)

        if self.feedback:
            msg = self._font_fb.render(self.feedback[0], True, self.feedback[1])
            surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, int(GAME_H * 0.30)))

        hint = ("Squeeze and HOLD the lemon, then release to add it to the pitcher"
                if self._phase != "ready" else
                "Hold complete -- RELEASE to pour this lemon into the pitcher!")
        hint_col = (255, 230, 120) if self._phase == "ready" else (235, 240, 248)
        hint_s = self._font_sm.render(hint, True, hint_col)
        hint_r = hint_s.get_rect(midleft=(80, GAME_H - 34))
        bar = pygame.Surface((hint_r.width + 28, hint_r.height + 14), pygame.SRCALPHA)
        pygame.draw.rect(bar, (10, 20, 15, 150), bar.get_rect(), border_radius=10)
        surface.blit(bar, (hint_r.x - 14, hint_r.y - 7))
        surface.blit(hint_s, hint_r)

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)
