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
import pygame
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from sensors.input_handler import input_handler
from audio import (play_success, play_error, play_completion,
                    start_music, stop_music, game_music_path, play_click)
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

JUICE_PER_LEMON = {k: 100.0 / v for k, v in LEMON_TARGET.items()}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_img_cache = {}


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
    """Draw the juice -- clipped to the glass's own interior silhouette,
    rising from the base -- UNDER the glass sprite, so the glass's own
    highlights/outline render on top of the liquid. Returns the glass's
    on-screen rect (used to aim the juice-drip animation)."""
    img = _load_raw_scaled("pitcher_lemonade.png", pitcher_h)
    if img is None:
        return pygame.Rect(cx, bottom_y - pitcher_h, 1, pitcher_h)
    pw, ph = img.get_size()
    px = cx - pw // 2
    py = bottom_y - ph

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

    surface.blit(img, (px, py))
    return pygame.Rect(px, py, pw, ph)


class LemonadeGame(FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "grip"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        self.target          = LEMON_TARGET[self.difficulty]
        self.grip_threshold  = GRIP_THRESHOLD[self.difficulty]
        self.release_threshold = self.grip_threshold * RELEASE_FACTOR
        self.hold_required   = HOLD_DURATION[self.difficulty]
        self.juice_per_lemon = JUICE_PER_LEMON[self.difficulty]

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
        self.pitcher_fill    = 0.0       # committed juice, 0..100
        self.grip_active     = False
        self.calibrated_grip = 0.0

        self.feedback    = None
        self._state      = {"grip": 0.0}
        self._drip_t      = 0.0

    def _normalize_grip(self, raw):
        """SAME calibration formula every grip game uses -- no duplicate
        sensor-processing logic."""
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
                self._show_instructions = False
                self.start_time         = pygame.time.get_ticks()
                start_music(game_music_path("Lemonade", self.difficulty))
            return

        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(game_music_path("Lemonade", self.difficulty))
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
            lambda: setattr(self, "paused", False),
            lambda: (self._reset(), setattr(self, "_show_instructions", False),
                     setattr(self, "paused", False),
                     start_music(game_music_path("Lemonade", self.difficulty))),
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

        raw = self._state.get("grip", 0.0)
        self.calibrated_grip = self._normalize_grip(raw)
        self.grip_active = self.calibrated_grip >= self.grip_threshold

        if self._phase == "waiting":
            if self.grip_active:
                self._phase        = "squeezing"
                self._hold_elapsed = 0.0
                self._temp_fill    = 0.0

        elif self._phase == "squeezing":
            if self.calibrated_grip < self.release_threshold:
                # released before completing the required hold -- discard
                # this lemon's temporary progress; committed juice is
                # untouched.
                self._phase        = "waiting"
                self._hold_elapsed = 0.0
                self._temp_fill    = 0.0
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
                self.completed      += 1
                self.lemons_left     = max(0, self.target - self.completed)
                self.pitcher_fill    = min(100.0, self.pitcher_fill + self.juice_per_lemon)
                self.score           += 1
                self.reps             = self.completed
                self.feedback         = ("LEMON COMPLETE!", (0, 220, 120), 1.0)
                play_success()
                self._phase        = "waiting"
                self._hold_elapsed = 0.0
                self._temp_fill    = 0.0
                if self.completed >= self.target:
                    self._end_game()
                    return

        if self.feedback:
            self.feedback = (self.feedback[0], self.feedback[1], self.feedback[2] - dt)
            if self.feedback[2] <= 0:
                self.feedback = None

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
        surface.blit(lbl1, lbl1.get_rect(centerx=r.centerx, top=r.y + 28))
        surface.blit(lbl2, lbl2.get_rect(centerx=r.centerx, top=r.y + 28 + lbl1.get_height()))
        surface.blit(val, val.get_rect(centerx=r.centerx, bottom=r.bottom - 24))

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

        # -- table / stand -- centered, its VISIBLE bottom (the asset is
        # pre-cropped to its own opaque content by _load_fit, so this rect's
        # bottom already excludes any transparent padding) touches the
        # screen's bottom edge exactly, no gap. The flat tabletop surface
        # itself sits ~60% of the way down the sprite's own visible height
        # (measured directly off the art: coverage jumps from ~8% -- just
        # the two support posts -- to ~80%+ right at that fraction), so
        # everything resting "on the table" is positioned relative to the
        # stand itself rather than a hardcoded screen coordinate.
        stand_img = _load_fit("stand_lemonade.png", int(GAME_W * 0.96), int(GAME_H * 0.62))
        table_surface_y = GAME_H - 260
        if stand_img is not None:
            sr = stand_img.get_rect(midbottom=(GAME_W // 2, GAME_H))
            surface.blit(stand_img, sr)
            table_surface_y = sr.y + int(sr.height * 0.60)

        # -- basket (difficulty-specific) -- left of the pitcher, its own
        # visible bottom resting exactly on the tabletop surface. Each
        # difficulty's art has different internal padding (a different pile
        # of lemons), but _load_fit crops every one of them to its own
        # opaque content first, so anchoring all three the same way here
        # still lines each one's real visible bottom up with the table.
        basket_name = {"Easy": "easy_lemonade.png", "Medium": "medium_lemonade.png",
                       "Hard": "hard_lemonade.png"}.get(self.difficulty, "easy_lemonade.png")
        basket_img = _load_fit(basket_name, 480, 400)
        if basket_img is not None:
            br = basket_img.get_rect(midbottom=(int(GAME_W * 0.205), table_surface_y))
            surface.blit(basket_img, br)

        # -- pitcher (center) -- juice fill drawn underneath its glass; its
        # visible bottom rests exactly on the tabletop surface (no gap, not
        # sunken into it).
        light = (255, 219, 90)
        dark  = (243, 176, 18)
        # Display = committed juice + this lemon's own (still uncommitted)
        # progress, so the level visibly rises while squeezing and drops
        # back to the committed total if released early (discarded).
        display_fill = (self.pitcher_fill + self._temp_fill) / 100.0
        pitcher_rect = _draw_pitcher(
            surface, GAME_W // 2, table_surface_y, 560,
            display_fill, dark, light)

        # -- hand (resting or squeezing) -- right side; its visible bottom
        # (the forearm) touches the screen's bottom edge, as if reaching up
        # from off-screen. Both sprites share this exact same anchor call,
        # so switching between hold/squeeze never shifts the hand.
        hand_name = "squeeze_lemonade.png" if self._phase in ("squeezing", "ready") else "hold_lemonade.png"
        hand_img = _load_fit(hand_name, 560, 620)
        hand_x = int(GAME_W * 0.80)
        if hand_img is not None:
            hr = hand_img.get_rect(midbottom=(hand_x, GAME_H))
            self._draw_juice_drip(surface, (hr.centerx - 60, hr.y + 120), pitcher_rect)
            surface.blit(hand_img, hr)

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
