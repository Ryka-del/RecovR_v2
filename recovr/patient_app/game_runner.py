"""
GameRunner -- hosts one `BaseScreen` game inside the patient loop and lets an
EXTERNAL controller (the therapist, over the comms layer) start / pause / resume
/ stop it without the game needing to know anything about Flask or HTTP.

It mirrors `scenes/game_scene.py` from the existing app: the game draws onto a
fixed GAME_W x GAME_H surface which is then scaled to the real display.

Host responsibilities kept OUT of the individual games so every game reuses them:
  * pump the sensor bridge (`sensors.input_handler.update(dt)`) once per frame
  * translate therapist commands into the game's own lifecycle
    (via optional `begin()` / `external_pause()` / `external_resume()` /
     `external_stop()` hooks -- a game without them still works)
  * normalise "the game finished" (ScreenManager.go_to OR a `game_over` flag)
  * decide telemetry cadence

Real games plug in via `_GAME_REGISTRY` -- one line per game, resolved lazily so
that importing sensor/BLE code only happens when a sensor game is actually
launched.
"""

import importlib
from dataclasses import dataclass

import pygame

from constants import GAME_W, GAME_H
from recovr.shared import protocol
from recovr.patient_app.scenes.countdown import CountdownScreen, TOTAL_SEC as COUNTDOWN_TOTAL_SEC


# ---------------------------------------------------------------------------
#  Registry
# ---------------------------------------------------------------------------

@dataclass
class GameSpec:
    cls: type
    uses_sensors: bool = False


# therapist-facing name -> (game module, GameClass name). Every registered
# game is wrapped by the generic real-game adapter. No games/*.py file is
# modified by the wrapping itself.
_REAL_GAMES = {
    "Basketball":               ("games.basketball",    "BasketballGame"),
    "Piano Tiles":              ("games.piano_tiles",   "PianoTilesGame"),
    "Apple Catching":           ("games.catchingapple", "AppleCatchingGame"),
    "Key and Lock":             ("games.key_lock",      "KeyLockGame"),
    "Steady Aim":               ("games.steady_aim",    "SteadyAimGame"),
    "Catch 'n Grab":             ("games.catch_object",  "CatchObjectGame"),
    "Lemonade":                 ("games.lemonade",      "LemonadeGame"),
    "Feed the Cat":             ("games.feed_the_cat",  "FeedTheCatGame"),
    "Plant the Garden":         ("games.plant_the_garden", "PlantTheGardenGame"),
}


class GameNotAvailable(Exception):
    """Raised when the therapist selects a game name we don't recognise."""


def resolve_game(name: str) -> GameSpec:
    """Resolve a configured game name to a GameSpec.

    Modules are imported here and nowhere earlier, so sensor/BLE code only loads
    once a game is actually selected. Raises GameNotAvailable for unknown names.
    """
    key = (name or "").strip()

    if key in _REAL_GAMES:
        mod_path, cls_name = _REAL_GAMES[key]
        from recovr.patient_app.games.generic_adapter import make_real_adapter
        game_cls = getattr(importlib.import_module(mod_path), cls_name)
        return GameSpec(make_real_adapter(game_cls), uses_sensors=True)

    raise GameNotAvailable(key or "(no game selected)")


# ---------------------------------------------------------------------------
#  Runner
# ---------------------------------------------------------------------------

class GameRunner:

    def __init__(self, spec: GameSpec, config: dict, *, sensor_update=None):
        self.spec = spec
        self.surface = pygame.Surface((GAME_W, GAME_H))
        self.game = spec.cls()
        self.game.on_enter(dict(config))

        self.paused = False
        self.stopped = False
        self.finished = False
        self._started = False

        self.counting_down = False     # pre-gameplay "Get Ready / 3-2-1 / START!"
        self._countdown_t = 0.0
        self._countdown_screen = CountdownScreen()

        self._tele_accum = 0.0

        # --- sensor bridge pump -------------------------------------------
        # Lives in the runner (not the game) so every game reuses it.
        # `sensor_update` is an injection seam for tests; production resolves the
        # existing sensors.input_handler singleton. `sensor_frames` is a public
        # counter so a test can prove the pump is actually running each frame.
        self.sensor_frames = 0
        self._sensor_update = None
        if spec.uses_sensors:
            if sensor_update is not None:
                self._sensor_update = sensor_update
            else:
                try:
                    from sensors.input_handler import input_handler
                    self._sensor_update = input_handler.update
                except Exception:
                    self._sensor_update = None

    # -- external control (therapist authority) ----------------------
    def start(self):
        """Unpause the game. Production keeps the game's own How-to-Play screen
        up (begin() is a no-op there); prototype dismisses it (3-2-1 owns it)."""
        self._started = True
        self.set_paused(False)
        begin = getattr(self.game, "begin", None)
        if callable(begin):
            begin()

    def force_begin(self):
        """Dismiss the game's own instruction screen NOW (no patient input).
        Called by the patient loop after the How-to-Play display time so the
        game starts on its own -- the therapist's START is the only trigger."""
        self.counting_down = False
        self._started = True
        self.set_paused(False)
        fn = getattr(self.game, "force_begin", None)
        if callable(fn):
            fn()

    def begin_countdown(self):
        """Therapist-triggered START (dual-monitor production): show the
        "Get Ready! / 3 / 2 / 1 / START!" sequence while the underlying game
        stays completely frozen (update() below skips sensor pump, game
        update, AND the telemetry accumulator while counting_down -- not just
        drawing a countdown on top of a timer that's already running), then
        call force_begin() automatically once it's done. One shared
        implementation for every wrapped game (see games/*.py + the generic
        adapter) instead of each game drawing its own countdown."""
        self.counting_down = True
        self._countdown_t = 0.0

    def set_paused(self, value: bool):
        self.paused = bool(value)
        hook = getattr(self.game,
                       "external_pause" if self.paused else "external_resume", None)
        if callable(hook):
            hook()

    def stop(self):
        self.stopped = True
        # A countdown that gets cancelled must never reach force_begin() on a
        # later update() -- clearing it here (not just leaving self.stopped
        # to short-circuit update()) is what guarantees that.
        self.counting_down = False
        hook = getattr(self.game, "external_stop", None)
        if callable(hook):
            hook()

    # -- per-frame ---------------------------------------------------
    def handle_event(self, event):
        if self.counting_down or self.paused or self.stopped or self.finished:
            return
        self.game.handle_event(event)

    def update(self, dt: float):
        if self.counting_down:
            self._countdown_t += dt
            if self._countdown_t >= COUNTDOWN_TOTAL_SEC:
                self.counting_down = False
                self.force_begin()
            return
        if self.stopped or self.finished or self.paused:
            return

        # Advance the sensor bridge before the game reads it (same order the
        # legacy scenes/game_scene.py used).
        if self._sensor_update is not None:
            self._sensor_update(dt)
            self.sensor_frames += 1

        self.game.update(dt)

        # A game signals completion either by asking its ScreenManager to move
        # on (older games) or by raising an internal `game_over` flag without
        # navigating (every current goal-based game).
        if getattr(self.game, "game_over", False):
            self.finished = True
        next_scene, _ = self.game.manager.get_next()
        if next_scene is not None:
            self.finished = True

        self._tele_accum += dt

    def due_telemetry(self) -> dict | None:
        """Return a telemetry snapshot when one is due, else None."""
        if self._tele_accum < protocol.TELEMETRY_INTERVAL_SEC:
            return None
        self._tele_accum = 0.0
        return self._extract_telemetry()

    def result(self) -> dict:
        game = self.game
        if hasattr(game, "get_result"):
            try:
                return game.get_result()
            except Exception:
                pass
        return {"score": getattr(game, "score", None)}

    def draw(self, target: pygame.Surface):
        self.surface.fill((0, 0, 0))
        self.game.draw(self.surface)

        tw, th = target.get_size()
        if (tw, th) == (GAME_W, GAME_H):
            target.blit(self.surface, (0, 0))
        else:
            # scale to FIT the patient screen while preserving the 16:9 game
            # aspect ratio; centre with black bars if the monitor differs.
            scale = min(tw / GAME_W, th / GAME_H)
            sw, sh = max(1, int(GAME_W * scale)), max(1, int(GAME_H * scale))
            scaled = pygame.transform.smoothscale(self.surface, (sw, sh))
            if (sw, sh) != (tw, th):
                target.fill((0, 0, 0))
            target.blit(scaled, ((tw - sw) // 2, (th - sh) // 2))

        if self.counting_down:
            self._countdown_screen.draw(target, self._countdown_t)
        elif self.paused:
            self._draw_pause_overlay(target)

    # -- internals -------------------------------------------------
    def _extract_telemetry(self) -> dict:
        game = self.game
        if hasattr(game, "get_telemetry"):
            try:
                return game.get_telemetry()
            except Exception:
                pass
        # Best-effort fallback for a game that doesn't expose telemetry yet.
        snap = {}
        for attr, key in (("score", "score"), ("reps", "reps"),
                          ("time_left", "remaining_sec")):
            if hasattr(game, attr):
                snap[key] = getattr(game, attr)
        return snap

    def _draw_pause_overlay(self, target: pygame.Surface):
        from ui_cards import draw_state_card, PAUSE_ACCENT
        draw_state_card(
            target,
            title="Game Paused",
            subtitle="Your therapist has paused the game. Please wait.",
            accent=PAUSE_ACCENT,
            kind="pause",
            dim=True,
        )
