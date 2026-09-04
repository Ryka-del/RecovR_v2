"""
GravityCatchAdapter -- connects the existing games/gravity_catch.py to the
recovr patient architecture.

GLUE ONLY. Every bit of gameplay -- falling objects, the basket, scoring,
difficulty tables, the timer, sensor handling, graphics -- is inherited
UNCHANGED from GravityCatchGame. This file only translates between the game's
internals and the GameRunner host contract:

  begin()                     start gameplay immediately; recovr owns the 3-2-1,
                              so the game's own "press any key" gate is bypassed
  external_pause/resume/stop  therapist-controlled; drives the game's REAL
                              self.paused flag (timer + mechanics actually stop)
  _end_game()                 keep the game's end-of-session finalisation but
                              DROP its direct Database().save_session() call --
                              recovr persists via POST /api/session/result
  draw()                      while externally paused, show the frozen playfield
                              WITHOUT the game's own pause menu (the patient must
                              not be able to restart/exit/change volume)
  handle_event()              forward events to the game only to clear its
                              fatigue rest-prompt; withhold everything else
  get_telemetry()/get_result() expose the game's real values in the shape the
                              recovr comms layer expects
"""

import pygame

from games.gravity_catch import GravityCatchGame
from sensors.input_handler import input_handler
from audio import stop_music, play_completion, start_music
from recovr.patient_app.games.generic_adapter import (
    _mask_begin_prompt, _mask_results_buttons, _mask_pause_button)


class GravityCatchAdapter(GravityCatchGame):

    GAME_NAME = "Gravity Catch"

    # -- construction --------------------------------------------------
    def on_enter(self, data):
        super().on_enter(data)          # real game setup (difficulty, duration, _reset, ...)
        self._external_pause = False
        self._began = False
        # production dual-monitor: the game keeps its own "How to Play" screen and
        # persists its own result, exactly like the standalone main.py app.
        self._real_app = bool(data.get("real_app"))
        self._has_db_ctx = bool(data.get("account_id") or data.get("patient"))

    # -- lifecycle (called by GameRunner) --------------------------
    def begin(self):
        """Prototype: dismiss the game's instruction screen (recovr's 3-2-1 owns
        the lead-in). Production: no-op -- the game keeps showing its own
        "How to Play"; patient_main calls force_begin() after the display time."""
        if self._began:
            return
        self._began = True
        if not self._real_app:
            self._dismiss_instructions()

    def force_begin(self):
        """Dismiss the game's own instruction screen NOW, with no patient input --
        the therapist's START is the trigger, the patient does not touch anything."""
        self._began = True
        self._dismiss_instructions()

    def _dismiss_instructions(self):
        if not getattr(self, "_show_instructions", False):
            return
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
        try:
            super().handle_event(ev)     # game clears _show_instructions, sets start_time, start_music()
        except Exception:
            pass
        if getattr(self, "_show_instructions", False):
            self._show_instructions = False
            self.start_time = pygame.time.get_ticks()
            try:
                start_music()
            except Exception:
                pass

    def external_pause(self):
        self._external_pause = True
        self.paused = True             # the game's REAL pause flag -> update() early-returns

    def external_resume(self):
        self._external_pause = False
        self.paused = False

    def external_stop(self):
        # Match the game's own exit cleanup (stop_music) without navigating,
        # writing builtins.pending_*, or touching the database.
        try:
            stop_music()
        except Exception:
            pass

    # -- natural completion --------------------------------------
    def _end_game(self):
        """Timer-expiry finalisation.

        Production (real ids present): run the game's OWN _end_game() unchanged --
        it writes the session to the database exactly as the standalone app does.
        Prototype: the trimmed version (no DB write); recovr persists via
        POST /api/session/result instead.
        """
        if self.game_over:
            return
        if self._real_app and self._has_db_ctx:
            super()._end_game()
            return
        try:
            stop_music()
            play_completion()
        except Exception:
            pass
        self.game_over_duration = (pygame.time.get_ticks() - self.start_time) // 1000
        self.game_over_score = self.score
        self.game_over = True

    # -- draw --------------------------------------------------
    def draw(self, surface):
        if self._external_pause:
            # Render the frozen playfield but suppress the game's own pause menu
            # (FatigueMixin._draw_pause). GameRunner draws the therapist-pause
            # overlay on top.
            real_paused = self.paused
            self.paused = False
            try:
                super().draw(surface)
            finally:
                self.paused = real_paused
        else:
            super().draw(surface)
        _mask_begin_prompt(self, surface)
        _mask_results_buttons(self, surface)
        _mask_pause_button(self, surface)

    # -- events ---------------------------------------------
    def handle_event(self, event):
        # recovr / the therapist own session control. The game only gets events
        # to clear its own fatigue rest-prompt; everything else (pause button,
        # ESC, pause menu, results buttons, and the "press any key" gate) is
        # withheld -- the patient never starts / stops / exits the session.
        if getattr(self, "fatigue_paused", False):
            super().handle_event(event)

    # -- telemetry / result -------------------------------
    def get_telemetry(self):
        state = getattr(self, "_state", {}) or {}
        elapsed = max(0.0, float(self.duration) - float(self.time_left))
        return {
            "game": self.GAME_NAME,
            "status": "running",
            "score": self.score,
            "reps": self.reps,                       # == score for this game
            "elapsed_sec": round(elapsed, 2),
            "remaining_sec": round(max(0.0, float(self.time_left)), 2),
            "duration_sec": int(self.duration),
            "difficulty": self.difficulty,
            "catcher_x": round(float(self.catcher_x), 1),
            "tilt_x": round(float(state.get("tilt_x", 0.0)), 3),
            "sensor_connected": bool(input_handler.connected),
            "falling_objects": len(self.objects),
            # NOT AVAILABLE from the unmodified game: misses, accuracy, reaction_time_ms
        }

    def get_result(self):
        # elapsed = duration - time_left is driven by accumulated dt (== real
        # seconds at 60 fps) and stays consistent with telemetry's elapsed_sec;
        # the game's own game_over_duration uses wall-clock get_ticks().
        elapsed = max(0.0, float(self.duration) - float(self.time_left))
        return {
            "game": self.GAME_NAME,
            "difficulty": self.difficulty,
            "duration_sec": int(round(elapsed)),
            "score": self.game_over_score if self.game_over else self.score,
            "reps": self.reps,
        }
