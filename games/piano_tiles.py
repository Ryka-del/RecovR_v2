"""
Piano Tiles — Finger Flexion game (1920x1080)

Five independent keys (Thumb, Index, Middle, Ring, Pinky), one falling tile
at a time. A tap requires the SPECIFIC finger whose key the tile fell in to
cross its activation threshold on a FALSE -> TRUE edge while the tile sits
inside the glowing hit line's window -- holding a finger flexed never
re-fires it, and it must drop back to released before that finger can tap
again. See _try_flex_tap()/update() for the per-finger READY -> FLEX ->
RELEASE -> READY gate.

Input source, today vs. the future (see _read_fingers()):
  - Keyboard Test Mode (no BLE controller connected): keys 1-5 simulate
    Thumb..Pinky independently -- held = flexed, released = relaxed.
  - Real BLE hardware: the physical controller currently has ONE Flex
    Sensor (firmware/controller_esp32c3.ino), not five independent ones.
    Genuine five-finger hardware play is NOT implemented yet -- this file
    deliberately does not fake it by duplicating that single shared
    reading across all five lanes (which would misrepresent which finger
    moved). When real hardware is connected, gameplay is paused and a
    clear in-game notice is shown instead. _read_fingers() is the single
    seam to update once the five-sensor firmware/BLE/input_handler/
    calibration chain lands -- nothing else in this file needs to change.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import random
import math
from screens.base import BaseScreen
from games.fatigue import FatigueMixin
from games.session_mode import SessionModeMixin
from sensors.input_handler import input_handler
from audio import play_success, play_completion, start_music, stop_music, game_music_path, play_click
from constants import get_theme, is_dark_mode, GAME_W, GAME_H
from games.game_header import draw_game_header, HEADER_BOTTOM
from games.round_complete import draw_round_complete_overlay

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


FINGER_NAMES   = ["Thumb", "Index", "Middle", "Ring", "Pinky"]
_FLEX_TEST_KEYS = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5]

# ── difficulty tuning ────────────────────────────────────────────────────
# The primary difficulty axis is the required finger-flexion INTENSITY
# (flex threshold), not reaction speed -- fall speed only varies modestly
# across tiers so the game stays a flexion exercise, not a twitch test.
# The threshold below is shared across all five fingers for now -- true
# per-finger calibration is part of the pending five-sensor architecture
# (not yet built); once that lands, this becomes a per-finger value read
# from calibration instead of one shared constant.
BASE_SPEED     = {"Easy": 260, "Medium": 340, "Hard": 420}   # px/s
FLEX_THRESHOLD = {"Easy": 0.35, "Medium": 0.50, "Hard": 0.65}  # calibrated flex (0-1) to register a tap
HIT_WINDOW     = {"Easy": 130, "Medium": 95,  "Hard": 65}     # px, +/- around the hit line
SPAWN_GAP      = {"Easy": 1.0,  "Medium": 0.7,  "Hard": 0.45}  # pause after a tile resolves before the next spawns
TILE_GOAL      = {"Easy": 20,  "Medium": 30,  "Hard": 40}     # Target Mode: tiles to hit to complete
DURATION       = {"Easy": 60,  "Medium": 60,  "Hard": 60}     # Timed Mode: session length in seconds

HIT_HOLD_DURATION  = 0.18   # white-glow hold at full size, right after a successful tap
HIT_FADE_DURATION  = 0.22   # shrink/fade-out that follows the hold
MISS_FADE_DURATION = 0.18   # tile shrink/fade-out after a miss (no hold, no colour change)

# ── layout ───────────────────────────────────────────────────────────────
# Sized from actually-measured rendered text at the font sizes used below
# (not guessed), so the largest string in each container ("Active Finger:
# Middle", "FLEXION THRESHOLD", "Awaiting Release", ...) fits with real
# padding -- see the panel draw methods for the exact font sizes.
LANE_COUNT     = 5
LEFT_PANEL_W   = 310    # Flexion Threshold + Combo indicators
RIGHT_PANEL_W  = 420    # Flex Sensor monitoring panel
PLAYFIELD_X0   = LEFT_PANEL_W
PLAYFIELD_X1   = GAME_W - RIGHT_PANEL_W
PLAYFIELD_W    = PLAYFIELD_X1 - PLAYFIELD_X0
LANE_W         = PLAYFIELD_W // LANE_COUNT
PLAYFIELD_TOP  = HEADER_BOTTOM + 20

# Bottom-up: a real margin below the screen edge, then the (now larger)
# finger-name row, then the tap zones, then the hit line -- each with
# enough clearance that the bigger fonts below can never run off-screen.
SCREEN_BOTTOM_MARGIN = 16
FINGER_LABEL_H  = 34    # row height reserved for the Thumb/Index/.../Pinky labels
TAP_ZONE_H      = 120
ROW_GAP         = 10
TAP_ZONE_Y      = GAME_H - SCREEN_BOTTOM_MARGIN - FINGER_LABEL_H - ROW_GAP - TAP_ZONE_H
HIT_LINE_GAP    = 36
HIT_LINE_Y      = TAP_ZONE_Y - HIT_LINE_GAP
APPROACH_MARGIN = 150   # px above the hit window where a zone starts showing "approaching"

TILE_W_BOX = LANE_W - 60
TILE_H_BOX = 300

# Game-specific accent colours (independent of light/dark theme, same as
# every other game's hardcoded accent palette).
LANE_BG_COLOR    = (190, 228, 248, 70)
DIVIDER_COLOR    = (20, 150, 170)
HIT_LINE_COLOR   = (255, 205, 40)
CYAN_GLOW        = (70, 225, 255)
MISS_FLASH_COLOR = (150, 158, 172)
ZONE_BASE_COLOR  = (45, 95, 150)
ZONE_APPROACH_COLOR = (70, 140, 200)
WHITE_GLOW_COLOR = (255, 255, 255)


class Tile:
    def __init__(self, lane, speed, img_black, img_white):
        self.lane      = lane
        self.img_black = img_black
        self.img_white = img_white
        self.img_w, self.img_h = img_black.get_size() if img_black is not None else (TILE_W_BOX, TILE_H_BOX)
        self.y     = float(PLAYFIELD_TOP - self.img_h)
        self.speed = speed
        self.hit   = False
        self.miss  = False
        self.resolved = False
        self.hold_t   = 0.0   # successful-tap white-glow hold, before the fade starts
        self.fade_t   = 0.0
        self.fade_dur = 0.0

    @property
    def x(self):
        return PLAYFIELD_X0 + self.lane * LANE_W

    @property
    def center_y(self):
        return self.y + self.img_h / 2

    @property
    def done(self):
        return self.resolved and self.hold_t <= 0 and self.fade_t <= 0

    def resolve(self, hit):
        self.hit      = hit
        self.miss     = not hit
        self.resolved = True
        if hit:
            self.hold_t   = HIT_HOLD_DURATION
            self.fade_dur = HIT_FADE_DURATION
        else:
            self.hold_t   = 0.0
            self.fade_dur = MISS_FADE_DURATION
        self.fade_t = self.fade_dur

    def update(self, dt):
        if self.resolved:
            if self.hold_t > 0:
                self.hold_t -= dt
            else:
                self.fade_t -= dt
        else:
            self.y += self.speed * dt

    def draw(self, surface):
        if self.done:
            return
        img = self.img_white if self.hit else self.img_black
        if img is None:
            return
        cx = int(self.x + LANE_W / 2)
        cy = int(self.y + self.img_h / 2)

        if self.resolved and self.hold_t > 0:
            # Brief full-size white-glow hold right after a successful tap --
            # the tile itself turns white + glows; the tapping zone behind it
            # is untouched (drawn separately, never recoloured by this).
            pad = 26
            glow = pygame.Surface((self.img_w + pad * 2, self.img_h + pad * 2), pygame.SRCALPHA)
            frac = self.hold_t / HIT_HOLD_DURATION
            pygame.draw.rect(glow, WHITE_GLOW_COLOR + (int(120 * frac),), glow.get_rect(), border_radius=36)
            surface.blit(glow, (cx - self.img_w // 2 - pad, cy - self.img_h // 2 - pad))
            rect = img.get_rect(center=(cx, cy))
            surface.blit(img, rect)
        elif self.resolved:
            frac  = max(0.0, self.fade_t / self.fade_dur) if self.fade_dur else 0.0
            scale = 0.5 + 0.5 * frac
            w, h  = self.img_w, self.img_h
            scaled = pygame.transform.smoothscale(
                img, (max(1, int(w * scale)), max(1, int(h * scale))))
            scaled = scaled.copy()
            scaled.set_alpha(int(255 * frac))
            rect = scaled.get_rect(center=(cx, cy))
            surface.blit(scaled, rect)
        else:
            rect = img.get_rect(center=(cx, cy))
            surface.blit(img, rect)


class PianoTilesGame(SessionModeMixin, FatigueMixin, BaseScreen):

    def on_enter(self, data):
        self.account_id = data.get("account_id")
        self.account    = data.get("account")
        self._patient   = data.get("patient")
        self.exercise   = "finger"
        self.difficulty = data.get("difficulty", "Easy")
        self.cal        = data.get("calibration", {})

        # Tile fall speed from Session Details speed setting
        _spd_map   = {"Slow": 260, "Normal": 340, "Fast": 420}
        self.speed = _spd_map.get(data.get("speed", "Normal"), 340)

        # Calibrated flexion threshold (shared across fingers for now --
        # see module docstring) + spawn gap, with Advanced Settings
        # overrides taking priority over the difficulty presets.
        cal_params = (data.get("calibration") or {}).get("params", {})
        cal_diff   = cal_params.get("difficulty", self.difficulty)
        self.flex_threshold = cal_params.get("pt_flex_threshold", FLEX_THRESHOLD.get(cal_diff, 0.5))
        self.spawn_gap      = cal_params.get("pt_spawn_rate",     SPAWN_GAP.get(cal_diff, 0.7))
        self.hit_window     = HIT_WINDOW[self.difficulty]

        self._session_init(data, TILE_GOAL, DURATION, self.difficulty, cal_goal_key="pt_goal")

        self.game_over           = False
        self.game_over_score     = 0
        self.game_over_duration  = 0
        self._results_again_rect = pygame.Rect(0, 0, 1, 1)
        self._results_exit_rect  = pygame.Rect(0, 0, 1, 1)

        self.paused     = False
        self.pause_sel  = 0
        self.vol_active = False
        self.pause_vol  = 0.4
        self._pause_btn_rect = pygame.Rect(GAME_W - 90, HEADER_BOTTOM + 14, 70, 46)

        self._font_panel_h  = pygame.font.SysFont("monospace", 22, bold=True)   # card/panel titles
        self._font_panel_v  = pygame.font.SysFont("monospace", 38, bold=True)   # big values (threshold %, combo, status)
        self._font_panel_s  = pygame.font.SysFont("monospace", 24, bold=True)   # body rows (Active Finger, Flexion, ...)
        self._font_finger   = pygame.font.SysFont("monospace", 24, bold=True)   # Thumb/Index/.../Pinky labels
        self._font_tiles    = pygame.font.SysFont("monospace", 28, bold=True)   # tiles-hit counter

        self._bg_img         = _load_image_cover("bg_piano_tiles.png", GAME_W, GAME_H)
        self._tile_img_black = _load_image_fit("black_tile_piano.png", TILE_W_BOX, TILE_H_BOX)
        self._tile_img_white = _load_image_fit("white_tile_piano.png", TILE_W_BOX, TILE_H_BOX)

        self._init_fatigue()
        self._reset()
        self._show_instructions = True

    # ── state ──────────────────────────────────────────────────────────

    def _reset(self):
        self.game_over   = False
        self.tile        = None
        self.spawn_timer = 0.0
        self.score       = 0
        self.reps        = 0
        self.combo       = 0
        self.combo_flash_t = 0.0
        self.lane_flash  = {}                           # lane -> [color, timer] (miss feedback only)
        self._finger_need_release = [False] * LANE_COUNT  # independent per-finger latch
        self._finger_tap_flash_t  = [0.0] * LANE_COUNT
        self.flex_vals   = [0.0] * LANE_COUNT
        self.five_finger_ready = True
        self._state      = {"grip": 0.0, "tilt_x": 0.0, "tilt_y": 0.0, "fingers": [False] * 5}
        self._session_reset()
        self.start_time  = pygame.time.get_ticks()

    # ── events ─────────────────────────────────────────────────────────

    def handle_event(self, event):
        # How To Play — any key or click dismisses
        if self._show_instructions:
            if (event.type == pygame.KEYDOWN or
                    (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1) or
                    event.type == pygame.FINGERDOWN or
                    input_handler.was_pressed(event, "action")):
                self._show_instructions = False
                self.start_time = pygame.time.get_ticks()
                start_music(game_music_path("Piano Tiles", self.difficulty))
            return

        # Results screen — mouse click on buttons
        if self.game_over:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._results_again_rect.collidepoint(event.pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(game_music_path("Piano Tiles", self.difficulty))
                elif self._results_exit_rect.collidepoint(event.pos):
                    play_click()
                    self._exit_to_game_config()
            elif event.type == pygame.FINGERDOWN:
                pos = (int(event.x * GAME_W), int(event.y * GAME_H))
                if self._results_again_rect.collidepoint(pos):
                    play_click()
                    self._reset()
                    self._show_instructions = False
                    start_music(game_music_path("Piano Tiles", self.difficulty))
                elif self._results_exit_rect.collidepoint(pos):
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

        # Pause button (mouse click)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._pause_btn_rect.collidepoint(event.pos):
                self.paused = True
                return
        if event.type == pygame.FINGERDOWN:
            pos = (int(event.x * GAME_W), int(event.y * GAME_H))
            if self._pause_btn_rect.collidepoint(pos):
                self.paused = True
                return

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
                     start_music(game_music_path("Piano Tiles", self.difficulty))),
            lambda: setattr(self, "vol_active", True),
            self._exit_to_game_config,
        ]
        for i, action in enumerate(opts_actions):
            oy = GAME_H // 2 - 160 + i * 96
            if pygame.Rect(GAME_W // 2 - 200, oy, 400, 80).collidepoint(pos):
                play_click()
                action()
                return

    # ── finger input ───────────────────────────────────────────────────

    def _read_fingers(self):
        """Returns (ready, values). ready=False means no genuine independent
        five-finger input source is currently available -- `values` is then
        just harmless zeros, never a duplicated/shared reading (see module
        docstring: real BLE hardware only has one physical Flex Sensor
        today, so five-finger play isn't faked there)."""
        if input_handler.connected:
            return False, [0.0] * LANE_COUNT
        keys = pygame.key.get_pressed()
        return True, [1.0 if keys[k] else 0.0 for k in _FLEX_TEST_KEYS]

    def _try_flex_tap(self, finger_idx):
        """Called on a FALSE -> TRUE edge for `finger_idx`. Scores the
        active tile only if it exists, hasn't already resolved, sits in
        THIS finger's lane, and is inside the hit window -- flexing any
        other finger, or flexing outside the window, does nothing."""
        self._finger_tap_flash_t[finger_idx] = 0.3
        tile = self.tile
        if tile is not None and not tile.resolved and tile.lane == finger_idx:
            if abs(tile.center_y - HIT_LINE_Y) <= self.hit_window:
                tile.resolve(hit=True)
                self.score += 1
                self.reps  += 1
                self.combo += 1
                self.combo_flash_t = 0.6
                play_success()
                if self._session_target_reached():
                    self._end_game()

    def _active_finger(self):
        """(index, status) for whichever finger the current tile needs, or
        (None, "ready") when no tile is active. status is one of
        'ready' / 'tap' / 'release', for the monitoring panel."""
        if self.tile is None:
            return None, "ready"
        i = self.tile.lane
        if self._finger_tap_flash_t[i] > 0:
            return i, "tap"
        elif self._finger_need_release[i]:
            return i, "release"
        return i, "ready"

    # ── update ─────────────────────────────────────────────────────────

    def update(self, dt):
        if self._show_instructions or self.game_over:
            return

        state = input_handler.get_state()
        self._state = state   # exposed for therapist-side raw sensor monitoring (grip/tilt_x etc.)

        self._update_fatigue(dt, state)
        if self.fatigue_paused or self.paused:
            return

        ready, flex_vals = self._read_fingers()
        self.five_finger_ready = ready
        self.flex_vals = flex_vals
        if not ready:
            return   # real BLE hardware connected -- see draw()'s notice; gameplay fully paused

        for i in range(LANE_COUNT):
            pressed = flex_vals[i] >= self.flex_threshold and not self._finger_need_release[i]
            self._finger_need_release[i] = flex_vals[i] >= self.flex_threshold
            if pressed:
                self._try_flex_tap(i)
            if flex_vals[i] >= self.flex_threshold:
                self.fatigue_timer = 0.0   # counts as activity so Take a Break doesn't trigger mid-game

        if self._session_tick(dt):
            self._end_game()
            return

        if self.tile is None:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                lane = random.randint(0, LANE_COUNT - 1)
                self.tile = Tile(lane, self.speed, self._tile_img_black, self._tile_img_white)
        else:
            self.tile.update(dt)
            if not self.tile.resolved and self.tile.center_y > HIT_LINE_Y + self.hit_window:
                self.tile.resolve(hit=False)
                self.combo = 0
                self.lane_flash[self.tile.lane] = [MISS_FLASH_COLOR, 0.25]
            elif self.tile.done:
                self.tile = None
                self.spawn_timer = self.spawn_gap

        for lane in list(self.lane_flash):
            self.lane_flash[lane][1] -= dt
            if self.lane_flash[lane][1] <= 0:
                del self.lane_flash[lane]

        if self.combo_flash_t > 0:
            self.combo_flash_t -= dt
        for i in range(LANE_COUNT):
            if self._finger_tap_flash_t[i] > 0:
                self._finger_tap_flash_t[i] -= dt

    # ── game end ───────────────────────────────────────────────────────

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
                game           = "Piano Tiles",
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

    # ── draw ───────────────────────────────────────────────────────────

    def draw(self, surface):
        T = get_theme()
        if self._bg_img is not None:
            surface.blit(self._bg_img, (0, 0))
        else:
            surface.fill(T["BG"])

        if self._show_instructions:
            self._draw_instructions(surface)
            return

        self._draw_lanes(surface)
        self._draw_hit_line(surface)
        if self.tile is not None:
            self.tile.draw(surface)
        self._draw_tap_zones(surface)

        draw_game_header(surface, "Piano Tiles", self.difficulty,
                          self._session_header_time(), self.score, GAME_W, GAME_H)

        prog_s = self._font_tiles.render(self._session_progress_text("tiles"), True, T["TEXT"])
        surface.blit(prog_s, (24, HEADER_BOTTOM + 16))

        self._draw_left_panel(surface)
        self._draw_right_panel(surface)

        # Pause button — two solid bars (identical to Basketball / Steady Aim)
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

        if not self.five_finger_ready:
            self._draw_hw_unsupported(surface)

        if self.paused:
            self._draw_pause(surface)
        self._draw_fatigue_overlay(surface)

        if self.game_over:
            self._draw_results(surface)

    def _draw_lanes(self, surface):
        T = get_theme()
        top = PLAYFIELD_TOP
        bottom = TAP_ZONE_Y + TAP_ZONE_H
        lane_surf = pygame.Surface((LANE_W - 2, bottom - top), pygame.SRCALPHA)
        lane_surf.fill(LANE_BG_COLOR)
        for i in range(LANE_COUNT):
            lx = PLAYFIELD_X0 + i * LANE_W
            surface.blit(lane_surf, (lx, top))
        for i in range(LANE_COUNT + 1):
            lx = PLAYFIELD_X0 + i * LANE_W
            pygame.draw.line(surface, DIVIDER_COLOR, (lx, top), (lx, bottom), 2)

        # Finger name under each key, so the 5 lanes read as 5 distinct keys.
        # Row geometry (ROW_GAP below the zones, within FINGER_LABEL_H, with
        # SCREEN_BOTTOM_MARGIN still clear below) is sized precisely for
        # this font so it can never run off the bottom of the screen.
        label_y = bottom + ROW_GAP
        for i in range(LANE_COUNT):
            lx = PLAYFIELD_X0 + i * LANE_W
            s = self._font_finger.render(FINGER_NAMES[i], True, DIVIDER_COLOR)
            surface.blit(s, (lx + LANE_W // 2 - s.get_width() // 2, label_y))

    def _draw_hit_line(self, surface):
        T = get_theme()
        x0, x1 = PLAYFIELD_X0, PLAYFIELD_X1
        y = HIT_LINE_Y
        glow = pygame.Surface((x1 - x0, 14), pygame.SRCALPHA)
        for i, a in enumerate((50, 90, 160)):
            gh = 14 - i * 4
            pygame.draw.rect(glow, HIT_LINE_COLOR + (a,), (0, (14 - gh) // 2, x1 - x0, gh))
        surface.blit(glow, (x0, y - 7))
        pygame.draw.line(surface, HIT_LINE_COLOR, (x0, y), (x1, y), 3)

        # Inside the playfield's left edge (not the left margin -- that's
        # already occupied by the Threshold/Combo cards, which are drawn
        # after this and would otherwise paint over an off-playfield label).
        lbl = self._font_panel_h.render("HIT LINE", True, HIT_LINE_COLOR)
        chip = pygame.Rect(x0 + 8, y - lbl.get_height() // 2 - 5, lbl.get_width() + 10, lbl.get_height() + 10)
        chip_surf = pygame.Surface(chip.size, pygame.SRCALPHA)
        pygame.draw.rect(chip_surf, (15, 20, 36, 170), chip_surf.get_rect(), border_radius=6)
        surface.blit(chip_surf, chip.topleft)
        surface.blit(lbl, (chip.x + 5, chip.y + 5))

    def _draw_tap_zones(self, surface):
        T = get_theme()
        for i in range(LANE_COUNT):
            lx = PLAYFIELD_X0 + i * LANE_W
            rect = pygame.Rect(lx + 10, TAP_ZONE_Y, LANE_W - 20, TAP_ZONE_H)

            # Base state for this zone, derived from the single active tile.
            # A successful tap NEVER recolours this zone -- only the tile
            # itself shows tap feedback (see Tile.draw()'s white-glow hold).
            color = ZONE_BASE_COLOR
            glow  = False
            if self.tile is not None and self.tile.lane == i and not self.tile.resolved:
                dist = abs(self.tile.center_y - HIT_LINE_Y)
                if dist <= self.hit_window:
                    glow = True
                elif self.tile.center_y >= HIT_LINE_Y - self.hit_window - APPROACH_MARGIN:
                    color = ZONE_APPROACH_COLOR

            pygame.draw.rect(surface, color, rect, border_radius=14)
            if glow:
                outer = rect.inflate(10, 10)
                glow_surf = pygame.Surface(outer.size, pygame.SRCALPHA)
                pygame.draw.rect(glow_surf, CYAN_GLOW + (90,), glow_surf.get_rect(), 4, border_radius=18)
                surface.blit(glow_surf, outer.topleft)
                pygame.draw.rect(surface, CYAN_GLOW, rect, 4, border_radius=14)
            else:
                pygame.draw.rect(surface, T["WHITE"], rect, 2, border_radius=14)

            if i in self.lane_flash:   # miss feedback only -- see update()
                flash_col, t = self.lane_flash[i]
                a = max(0, min(255, int(255 * (t / 0.25))))
                ov = pygame.Surface(rect.size, pygame.SRCALPHA)
                pygame.draw.rect(ov, flash_col + (a,), ov.get_rect(), border_radius=14)
                surface.blit(ov, rect.topleft)

    def _draw_left_panel(self, surface):
        T = get_theme()
        x = 20
        y = HEADER_BOTTOM + 70
        w = LEFT_PANEL_W - 40
        card_h = 112
        pad = 16

        # Flexion Threshold indicator
        card1 = pygame.Rect(x, y, w, card_h)
        bg = pygame.Surface(card1.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (235,), bg.get_rect(), border_radius=14)
        surface.blit(bg, card1.topleft)
        pygame.draw.rect(surface, T["ACCENT"], card1, 2, border_radius=14)
        lbl = self._font_panel_h.render("FLEXION THRESHOLD", True, T["GRAY"])
        surface.blit(lbl, (card1.x + pad, card1.y + pad))
        val = self._font_panel_v.render(f"≥ {int(round(self.flex_threshold * 100))}%", True, T["ACCENT"])
        surface.blit(val, (card1.x + pad, card1.y + pad + lbl.get_height() + 8))

        # Combo indicator
        y2 = card1.bottom + 20
        card2 = pygame.Rect(x, y2, w, card_h)
        pulse = self.combo_flash_t > 0
        glow_a = int(160 * max(0.0, self.combo_flash_t / 0.6)) if pulse else 0
        bg2 = pygame.Surface(card2.size, pygame.SRCALPHA)
        pygame.draw.rect(bg2, T["PANEL"] + (235,), bg2.get_rect(), border_radius=14)
        surface.blit(bg2, card2.topleft)
        if glow_a > 0:
            glow_surf = pygame.Surface(card2.inflate(10, 10).size, pygame.SRCALPHA)
            pygame.draw.rect(glow_surf, T["YELLOW"] + (glow_a,), glow_surf.get_rect(), border_radius=18)
            surface.blit(glow_surf, (card2.x - 5, card2.y - 5))
        pygame.draw.rect(surface, T["YELLOW"] if pulse else T["ACCENT"], card2, 2, border_radius=14)
        lbl2 = self._font_panel_h.render("COMBO", True, T["GRAY"])
        surface.blit(lbl2, (card2.x + pad, card2.y + pad))
        val2 = self._font_panel_v.render(f"×{self.combo}", True,
                                          T["YELLOW"] if pulse else T["TEXT"])
        surface.blit(val2, (card2.x + pad, card2.y + pad + lbl2.get_height() + 8))

    def _draw_finger_icon(self, surface, cx, cy, flex_frac, color):
        seg = 20
        base_end = (cx, cy + seg)
        ang = math.radians(75 * max(0.0, min(1.0, flex_frac)))
        tip_end = (base_end[0] + seg * math.sin(ang), base_end[1] + seg * math.cos(ang))
        pygame.draw.line(surface, color, (cx, cy - 4), base_end, 6)
        pygame.draw.line(surface, color, base_end, tip_end, 6)
        pygame.draw.circle(surface, color, (int(cx), int(cy - 4)), 6)
        pygame.draw.circle(surface, color, (int(tip_end[0]), int(tip_end[1])), 5)

    def _draw_right_panel(self, surface):
        T = get_theme()
        pad = 18
        x = PLAYFIELD_X1 + 18
        y = HEADER_BOTTOM + 70
        w = RIGHT_PANEL_W - 38

        active_i, status = self._active_finger()
        finger_name = FINGER_NAMES[active_i] if active_i is not None else "—"
        flex_raw = self.flex_vals[active_i] if active_i is not None else 0.0
        need_release = self._finger_need_release[active_i] if active_i is not None else False

        status_col = {"ready": T["GRAY"], "tap": T["YELLOW"], "release": T["ACCENT"]}[status]
        status_lbl = {"ready": "Ready", "tap": "Tap!", "release": "Release"}[status]
        pct     = int(round(flex_raw * 100))
        thr_pct = int(round(self.flex_threshold * 100))

        # Flow layout: every row's y is the previous row's bottom + a gap,
        # so the panel's own height is derived from its actual content at
        # the real font sizes below, not a guessed constant -- it can never
        # under-size and clip the last row.
        title_s  = self._font_panel_h.render("FLEX SENSOR", True, T["GRAY"])
        status_s = self._font_panel_v.render(status_lbl, True, status_col)
        fin_s    = self._font_panel_s.render(f"Active Finger: {finger_name}", True, T["TEXT"])
        fx_s     = self._font_panel_s.render(f"Flexion: {pct}%", True, T["TEXT"])
        bar_h    = 32
        thr_s    = self._font_panel_s.render(f"Threshold: {thr_pct}%", True, T["GRAY"])
        gate_s   = self._font_panel_s.render(
            "Armed" if not need_release else "Awaiting Release",
            True, T["GREEN"] if not need_release else T["ORANGE"])

        rows_h = (title_s.get_height() + 14 + status_s.get_height() + 18 +
                  fin_s.get_height() + 10 + fx_s.get_height() + 10 + bar_h + 14 +
                  thr_s.get_height() + 10 + gate_s.get_height())
        h = pad * 2 + rows_h
        panel = pygame.Rect(x, y, w, h)

        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (235,), bg.get_rect(), border_radius=16)
        surface.blit(bg, panel.topleft)
        pygame.draw.rect(surface, T["ACCENT"], panel, 2, border_radius=16)

        cy = panel.y + pad
        surface.blit(title_s, (panel.x + pad, cy))
        cy += title_s.get_height() + 14

        icon_cx, icon_cy = panel.x + pad + 16, cy + status_s.get_height() // 2
        self._draw_finger_icon(surface, icon_cx, icon_cy, flex_raw, status_col)
        surface.blit(status_s, (panel.x + pad + 48, cy))
        cy += status_s.get_height() + 18

        surface.blit(fin_s, (panel.x + pad, cy))
        cy += fin_s.get_height() + 10

        surface.blit(fx_s, (panel.x + pad, cy))
        cy += fx_s.get_height() + 10

        bar = pygame.Rect(panel.x + pad, cy, w - pad * 2, bar_h)
        pygame.draw.rect(surface, T["BG"], bar, border_radius=10)
        fill_w = int(bar.width * flex_raw)
        if fill_w > 0:
            fill_col = T["GREEN"] if flex_raw >= self.flex_threshold else T["ACCENT"]
            pygame.draw.rect(surface, fill_col, (bar.x, bar.y, fill_w, bar.height), border_radius=10)
        pygame.draw.rect(surface, T["WHITE"], bar, 2, border_radius=10)
        thr_x = bar.x + int(bar.width * self.flex_threshold)
        pygame.draw.line(surface, T["RED"], (thr_x, bar.y - 6), (thr_x, bar.bottom + 6), 4)
        cy += bar_h + 14

        surface.blit(thr_s, (panel.x + pad, cy))
        cy += thr_s.get_height() + 10

        surface.blit(gate_s, (panel.x + pad, cy))

    def _draw_hw_unsupported(self, surface):
        """Shown instead of normal play when a real BLE controller is
        connected -- see module docstring: genuine five-finger hardware
        support isn't built yet, so gameplay is explicitly paused rather
        than silently using the one shared Flex Sensor for every finger."""
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 190))
        surface.blit(ov, (0, 0))

        pw, ph = 800, 280
        px, py = (GAME_W - pw) // 2, (GAME_H - ph) // 2
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(bg, T["PANEL"] + (250,), (0, 0, pw, ph), border_radius=16)
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, T["RED"], pygame.Rect(px, py, pw, ph), 2, border_radius=16)

        f_t = pygame.font.SysFont("monospace", 28, bold=True)
        f_b = pygame.font.SysFont("monospace", 19)
        title = f_t.render("Five-Finger Hardware Not Yet Available", True, T["RED"])
        surface.blit(title, title.get_rect(centerx=GAME_W // 2, top=py + 26))

        lines = [
            "This controller currently has one Flex Sensor; Piano Tiles",
            "needs five independent sensors (one per finger) to play on",
            "real hardware. That upgrade is in progress.",
            "",
            "Disconnect the controller to use Keyboard Test Mode",
            "(keys 1-5 simulate Thumb - Pinky) in the meantime.",
        ]
        yy = py + 78
        for ln in lines:
            s = f_b.render(ln, True, T["TEXT"])
            surface.blit(s, s.get_rect(centerx=GAME_W // 2, top=yy))
            yy += 26

    # ── How To Play ────────────────────────────────────────────────────

    def _draw_instructions(self, surface):
        T = get_theme()
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surface.blit(ov, (0, 0))

        card_name = f"piano_tiles_how_to_play_{'dark' if is_dark_mode() else 'light'}.png"
        # Same outer card box as _draw_results' Round Complete card -- the
        # two screens read as stages of one interface.
        top_margin, bottom_reserved = int(GAME_H * 0.05), int(GAME_H * 0.17)
        card = _load_image_fit(card_name, int(GAME_W * 0.50), GAME_H - top_margin - bottom_reserved)
        bottom_y = GAME_H // 2
        if card is not None:
            cr = card.get_rect(midtop=(GAME_W // 2, top_margin))
            surface.blit(card, cr)
            bottom_y = cr.bottom

        # No "press any key" prompt -- the patient never starts the game
        # themselves, only the therapist's own START control does.
        f_info = pygame.font.SysFont("monospace", 22, bold=True)
        sess_txt = (f"Goal: Hit {self.goal} tiles" if self.session_mode == "target" else
                    f"Duration: {int(self.timed_duration)}s — hit as many tiles as you can")
        info = f_info.render(
            f"{sess_txt}   ·   Difficulty: {self.difficulty}"
            f"   ·   Flex Threshold: {int(round(self.flex_threshold * 100))}%",
            True, T["WHITE"])
        info_r = info.get_rect(centerx=GAME_W // 2, top=bottom_y + 14)
        surface.blit(info, info_r)

    # ── Session Complete ───────────────────────────────────────────────

    def _draw_results(self, surface):
        T = get_theme()
        _card, bottom_y = draw_round_complete_overlay(
            surface, card_prefix="piano_tiles", duration_sec=self.game_over_duration,
            score_text=self._session_count_text(), load_fit=_load_image_fit)

        f_btn = pygame.font.SysFont("monospace", 32, bold=True)

        mp  = pygame.mouse.get_pos()
        bw, bh = 240, 60
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
