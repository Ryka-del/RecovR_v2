"""
make_real_adapter(game_cls) -- wrap ANY existing games/*.py BaseScreen game so
the patient window (GameRunner) can host it, WITHOUT changing the game.

GLUE ONLY. All mechanics / graphics / scoring / difficulty / timer / sensor
handling come straight from the original game class. The wrapper only adds the
hooks GameRunner looks for:

  begin()                     no-op -- the real game shows its OWN "How to Play"
                              screen and the patient dismisses it (production).
  external_pause/resume/stop  therapist control -> the game's real self.paused
                              flag (mechanics + timer actually stop).
  draw()                      hide the game's own pause menu while the therapist
                              has it externally paused.
  handle_event()              forward only what the game needs pre-gameplay
                              (its instruction screen) and its fatigue prompt --
                              the patient cannot open the pause menu / exit.
  get_telemetry()/get_result()  best-effort, from whatever attributes the game
                              exposes (score / reps / time_left / difficulty).

Gravity Catch keeps its own dedicated adapter (it also supports the prototype
path); every other game routes through this wrapper.
"""

import pygame

_MADE: dict = {}          # cache: game_cls -> adapter subclass


def _mask_begin_prompt(game, surface):
    """Cover the game's own "Press any key or click to begin" line while its
    How-to-Play screen is up -- the patient never starts the game, the therapist's
    START does. The prompt sits at the bottom of a centred instruction panel;
    this paints that strip with the current theme's panel colour.
    """
    if not getattr(game, "_show_instructions", False):
        return
    try:
        from constants import get_theme
        panel = get_theme()["PANEL"]
    except Exception:
        panel = (30, 35, 50)
    w, h = surface.get_size()
    # the "press any key" hint sits ~0.70-0.76 h, centred, near the bottom of the
    # instruction panel; cover just that band with the panel colour.
    strip = pygame.Rect(int(w * 0.31), int(h * 0.695), int(w * 0.38), int(h * 0.055))
    surface.fill(panel, strip)


def _mask_results_buttons(game, surface):
    """Cover the "Play Again" / "Exit" buttons on the game's own Session-Complete
    screen -- the patient cannot restart or exit; only the therapist controls the
    session. The buttons sit near the bottom of a centred ~640x400 results modal.
    """
    if not getattr(game, "game_over", False):
        return
    try:
        from constants import get_theme
        panel = get_theme()["PANEL"]
    except Exception:
        panel = (30, 35, 50)
    w, h = surface.get_size()
    strip = pygame.Rect(int(w * 0.345), int(h * 0.60), int(w * 0.31), int(h * 0.075))
    surface.fill(panel, strip)


def _mask_pause_button(game, surface):
    """Cover the game's own top-right Pause button during play -- the patient has
    NO pause control; only the therapist (Session in Progress) pauses/resumes.
    Every game places it at Rect(GAME_W-90, 13, 70, 46). The fill colour is
    sampled from the top edge just above the button so it blends whether the game
    draws a solid HUD bar there (basketball, piano tiles, ...) or shows the bare
    playfield (gravity catch). (games/*.py are left untouched.)
    """
    if getattr(game, "_show_instructions", False) or getattr(game, "game_over", False):
        return
    r = getattr(game, "_pause_btn_rect", None)
    if r is None:
        return
    w, h = surface.get_size()
    sx, sy = w / 1920.0, h / 1080.0
    pad = int(14 * sx)
    cx = min(w - 1, max(0, int((r.x + r.width // 2) * sx)))
    try:
        fill = surface.get_at((cx, 1))[:3]                 # top edge above the button
    except Exception:
        try:
            from constants import get_theme
            fill = get_theme()["PANEL"]
        except Exception:
            fill = (30, 35, 50)
    strip = pygame.Rect(int(r.x * sx) - pad, 0,
                        int(r.width * sx) + 2 * pad, int((r.y + r.height) * sy) + int(12 * sy))
    surface.fill(fill, strip)


def make_real_adapter(game_cls):
    if game_cls in _MADE:
        return _MADE[game_cls]

    class RealGameAdapter(game_cls):

        GAME_NAME = getattr(game_cls, "__name__", "game")

        # -- construction -------------------------------------------
        def on_enter(self, data):
            super().on_enter(data)
            self._external_pause = False
            self._real_app = bool(data.get("real_app"))

        # -- lifecycle hooks --------------------------------------
        def begin(self):
            # production: the game keeps its own How-to-Play screen; the patient
            # loop calls force_begin() after the display time (no patient input).
            pass

        def force_begin(self):
            if not getattr(self, "_show_instructions", False):
                return
            try:
                super().handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
            except Exception:
                pass
            if getattr(self, "_show_instructions", False):
                self._show_instructions = False
                if hasattr(self, "start_time"):
                    self.start_time = pygame.time.get_ticks()
                try:
                    from audio import start_music
                    start_music()
                except Exception:
                    pass

        def external_pause(self):
            self._external_pause = True
            self.paused = True

        def external_resume(self):
            self._external_pause = False
            self.paused = False

        def external_stop(self):
            try:
                from audio import stop_music
                stop_music()
            except Exception:
                pass

        # -- draw ---------------------------------------------
        def draw(self, surface):
            if getattr(self, "_external_pause", False):
                real_paused = getattr(self, "paused", False)
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

        # -- events -----------------------------------------
        def handle_event(self, event):
            # only the fatigue rest-prompt; the patient never starts/stops/exits
            if getattr(self, "fatigue_paused", False):
                super().handle_event(event)

        # -- telemetry / result -------------------------
        def _elapsed_remaining(self):
            dur = float(getattr(self, "duration", 0) or 0)
            tl  = float(getattr(self, "time_left", dur) or 0)
            return max(0.0, dur - tl), max(0.0, tl), dur

        def get_telemetry(self):
            elapsed, remaining, dur = self._elapsed_remaining()
            return {
                "game": self.GAME_NAME,
                "status": "running",
                "score": getattr(self, "score", 0),
                "reps": getattr(self, "reps", 0),
                "elapsed_sec": round(elapsed, 2),
                "remaining_sec": round(remaining, 2),
                "duration_sec": int(dur),
                "difficulty": getattr(self, "difficulty", ""),
            }

        def get_result(self):
            elapsed, _remaining, _dur = self._elapsed_remaining()
            return {
                "game": self.GAME_NAME,
                "difficulty": getattr(self, "difficulty", ""),
                "duration_sec": int(round(elapsed)),
                "score": getattr(self, "game_over_score", getattr(self, "score", 0)),
                "reps": getattr(self, "reps", 0),
            }

    RealGameAdapter.__name__ = f"{RealGameAdapter.GAME_NAME}RealAdapter"
    _MADE[game_cls] = RealGameAdapter
    return RealGameAdapter
