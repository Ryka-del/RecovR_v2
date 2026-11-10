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

Every registered game routes through this wrapper.
"""

import pygame

_MADE: dict = {}          # cache: game_cls -> adapter subclass


def _call_normalize(fn, raw, axis_letter):
    """Call a game's own _normalize*/_normalize_tilt method on its own raw
    reading. Some take (raw, axis) (e.g. SteadyAimGame), most take just
    (raw) -- try the 2-arg form first, fall back to 1-arg, never raise."""
    if fn is None:
        return None
    try:
        return fn(raw, axis_letter)
    except TypeError:
        try:
            return fn(raw)
        except Exception:
            return None
    except Exception:
        return None


def _sensor_telemetry(game):
    """Best-effort raw + calibrated sensor readings for whatever this game's
    OWN update() already computed this frame (games/*.py persists it as
    self._state = input_handler.get_state()). The calibrated value calls the
    game's OWN existing _normalize/_normalize_grip/_normalize_tilt method --
    never a second/duplicate calibration formula -- so it is guaranteed to be
    exactly what gameplay itself is using. A game with no such method (e.g. a
    purely edge-detected finger-press game) simply reports calibrated=None;
    the dashboard decides what, if anything, to show for that.

    Returns {state_key: {"raw": float, "calibrated": float|None}} for every
    key actually present in self._state (grip / tilt_x / tilt_y)."""
    state = getattr(game, "_state", None) or {}
    out = {}
    if "grip" in state:
        raw = state["grip"]
        fn = getattr(game, "_normalize_grip", None) or getattr(game, "_normalize", None)
        out["grip"] = {"raw": raw, "calibrated": _call_normalize(fn, raw, None) if fn else None}
    for key, axis in (("tilt_x", "x"), ("tilt_y", "y")):
        if key in state:
            raw = state[key]
            fn = getattr(game, "_normalize_tilt", None)
            out[key] = {"raw": raw, "calibrated": _call_normalize(fn, raw, axis) if fn else None}
    return out


def _mask_results_buttons(game, surface):
    """Cover the "Play Again" / "Exit" (or, for Steady Aim, "Play Again" /
    "Exit" via _results_back_rect) buttons on the game's own Session-Complete
    screen -- the patient cannot restart or exit; only the therapist controls
    the session.

    Reads the game's OWN stored button Rects (_results_again_rect and
    whichever of _results_exit_rect / _results_back_rect it uses) instead of
    a guessed screen-fraction strip -- those rects are exactly where the game
    just drew the buttons this frame, so this never drifts out of sync when a
    game's results layout changes (a hardcoded strip previously did, landing
    visibly off-target after the Round Complete card redesign).

    The fill colour is SAMPLED from the pixel just above the button strip --
    i.e. the Round Complete card's own stat-row background -- rather than a
    flat constants.get_theme()["PANEL"] guess. PANEL is pure white in Light
    mode, which painted a visibly mismatched white rectangle over the
    card's actual (non-white) art at that point; sampling what the game
    itself just rendered there blends in regardless of theme or which
    game's card is on screen."""
    if not getattr(game, "game_over", False):
        return
    rects = [r for r in (
        getattr(game, "_results_again_rect", None),
        getattr(game, "_results_exit_rect", None),
        getattr(game, "_results_back_rect", None),
    ) if r is not None and r.width > 1 and r.height > 1]

    if not rects:
        return
    strip = rects[0].unionall(rects[1:]).inflate(16, 16)
    try:
        sw, sh = surface.get_size()
        # Sample just OUTSIDE the strip's left/right edges, at its own
        # vertical centre -- the same backdrop band the buttons sit on,
        # clear of both the button artwork itself and any text/confetti
        # directly above/below -- and average the two so one odd pixel
        # (e.g. a stray confetti fleck) can't skew the whole fill.
        sy = max(0, min(sh - 1, strip.centery))
        xs = [x for x in (strip.left - 6, strip.right + 5) if 0 <= x < sw]
        if not xs:
            xs = [max(0, min(sw - 1, strip.centerx))]
        samples = [surface.get_at((x, sy))[:3] for x in xs]
        fill_col = tuple(sum(c) // len(samples) for c in zip(*samples))
    except Exception:
        try:
            from constants import get_theme
            fill_col = get_theme()["PANEL"]
        except Exception:
            fill_col = (30, 35, 50)
    surface.fill(fill_col, strip)


def _hidden_pause_rect(game):
    """The game is about to draw its own top-right Pause button (the
    patient has NO pause control; only the therapist's Session-in-Progress
    panel pauses/resumes) -- return the off-screen Rect it should be drawn
    at instead, so it never appears on the patient display, in ANY game
    state. Returns None only when the game has no _pause_btn_rect at all.

    This used to let the game draw the button on-screen and then paint over
    its footprint with a sampled colour. That cannot reproduce detailed
    background art (e.g. Feed the Cat's sky/trees): a single sampled pixel
    flood-filled across the button's box showed up as a solid mismatched
    rectangle in that corner. Relocating the button before the game ever
    draws it fixes the actual rendering issue instead of covering it up.

    Previously this skipped hiding during _show_instructions/game_over,
    assuming the game's own overlay (instruction panel / results dialog)
    would already cover it -- but those overlays are translucent (e.g.
    _draw_results()'s alpha=185 dim), so the button showed through, dimmed
    but clearly visible, on the Session Complete screen. Hiding it
    unconditionally is always safe: a game that doesn't draw the button in
    some state is unaffected, and one that does (like the results screen)
    now has it correctly relocated off-screen in every state."""
    r = getattr(game, "_pause_btn_rect", None)
    if r is None:
        return None
    return pygame.Rect(-10000, -10000, r.width, r.height)


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
            # The patient side has no in-game Exit control here -- only the
            # therapist's STOP (Session in Progress panel) can end a session
            # mid-play -- so the original game's own
            # _exit_to_game_config() -> _save_session("stopped") path (the
            # single-process app's only route to a "stopped" row) is never
            # reached in the dual-monitor architecture. Without this, a
            # therapist-stopped session was silently never persisted at all.
            # Mirrors the exact game_over/_show_instructions guard every
            # game's own exit path already uses, and calls the SAME
            # self._save_session the "completed" path does -- so therapist
            # attribution (self.account_id, captured once at session start)
            # can never drift between the two outcomes.
            if (not getattr(self, "game_over", False)
                    and not getattr(self, "_show_instructions", False)
                    and not getattr(self, "_stop_saved", False)):
                save = getattr(self, "_save_session", None)
                if callable(save):
                    self._stop_saved = True
                    try:
                        save(status="stopped")
                    except Exception:
                        pass

        # -- draw ---------------------------------------------
        def draw(self, surface):
            real_rect = getattr(self, "_pause_btn_rect", None)
            hidden_rect = _hidden_pause_rect(self)
            if hidden_rect is not None:
                self._pause_btn_rect = hidden_rect
            try:
                if getattr(self, "_external_pause", False):
                    real_paused = getattr(self, "paused", False)
                    self.paused = False
                    try:
                        super().draw(surface)
                    finally:
                        self.paused = real_paused
                else:
                    super().draw(surface)
            finally:
                if hidden_rect is not None:
                    self._pause_btn_rect = real_rect
            _mask_results_buttons(self, surface)

        # -- events -----------------------------------------
        def handle_event(self, event):
            # only the fatigue rest-prompt; the patient never starts/stops/exits
            if getattr(self, "fatigue_paused", False):
                super().handle_event(event)

        # -- telemetry / result -------------------------
        # Every wrapped game uses games/session_mode.py's SessionModeMixin:
        # self.elapsed counts UP (seconds of active, unpaused gameplay) in
        # BOTH modes; self.session_mode is "target" (self.goal is the
        # required reps; ends when self.reps reaches it) or "timed"
        # (self.time_left counts DOWN from the configured duration; ends at
        # zero, self.goal is None).
        def get_telemetry(self):
            return {
                "game": self.GAME_NAME,
                "status": "running",
                "score": getattr(self, "score", 0),
                "reps": getattr(self, "reps", 0),
                "session_mode": getattr(self, "session_mode", "target"),
                "goal": getattr(self, "goal", None),
                "elapsed_sec": round(float(getattr(self, "elapsed", 0.0) or 0.0), 2),
                "remaining_sec": (round(float(self.time_left), 2)
                                  if getattr(self, "time_left", None) is not None else None),
                "difficulty": getattr(self, "difficulty", ""),
                "sensors": _sensor_telemetry(self),
            }

        def get_result(self):
            goal = getattr(self, "goal", None)
            reps = getattr(self, "reps", 0)
            mode = getattr(self, "session_mode", "target")
            completed = (reps >= goal) if (mode == "target" and goal is not None) else \
                        (getattr(self, "time_left", 1) is not None and self.time_left <= 0)
            return {
                "game": self.GAME_NAME,
                "difficulty": getattr(self, "difficulty", ""),
                "session_mode": mode,
                "duration_sec": int(round(float(getattr(self, "elapsed", 0.0) or 0.0))),
                "configured_duration_seconds": getattr(self, "timed_duration", None),
                "score": getattr(self, "game_over_score", getattr(self, "score", 0)),
                "reps": reps,
                "goal": goal,
                "completed": bool(completed),
            }

    RealGameAdapter.__name__ = f"{RealGameAdapter.GAME_NAME}RealAdapter"
    _MADE[game_cls] = RealGameAdapter
    return RealGameAdapter
