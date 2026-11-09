"""
SessionModeMixin — the one piece of session-mode logic every RecovR game
shares, so it is implemented once instead of once per game.

Two modes, selected by the therapist in Game Configuration:
  "target" — the patient works toward a set number of successful reps; the
             elapsed timer counts UP and is purely a performance measure.
  "timed"  — the patient works for a configured duration; the countdown
             counts DOWN and ends the session at 00:00.

A game using this mixin still owns everything that makes it that game: what
counts as a successful rep, sensor thresholds, mechanics, animations. This
mixin only owns:
  - which mode is active and its target/duration value
  - advancing elapsed/remaining time each frame (paused time excluded, since
    callers only ever call _session_tick() from their own already-existing
    "not paused/not fatigued" branch)
  - the single question "has Target Mode's goal been reached?" (Timed Mode
    always answers False here -- it ends on the timer instead, via
    _session_tick()'s return value)
  - formatting the header's time value and the "X/Y" vs "X" progress text
  - the result fields every save_session() call needs

Usage (see games/feed_the_cat.py or any converted game for the full pattern):

    class MyGame(SessionModeMixin, FatigueMixin, BaseScreen):
        def on_enter(self, data):
            ...
            self._session_init(data, GOAL, DURATION, self.difficulty,
                                cal_goal_key="xyz_goal")
            ...
        def _reset(self):
            self._session_reset()
            ...
        def update(self, dt):
            ...
            if self._session_tick(dt):
                self._end_game(); return
            ...
        def _on_success(self):
            self.score += 1
            self.reps  += 1
            if self._session_target_reached():
                self._end_game()
"""


class SessionModeMixin:

    def _session_init(self, data, target_presets, duration_presets, difficulty,
                       cal_goal_key=None):
        """target_presets / duration_presets: the game's own per-difficulty
        {"Easy": .., "Medium": .., "Hard": ..} dicts. cal_goal_key: the
        Advanced Settings GAME_PARAM_SCHEMA key (e.g. "bb_goal") that can
        override the Target Mode preset, exactly like before -- Timed Mode's
        duration is never Advanced-Settings-overridable, matching how
        duration worked before goal-based sessions existed."""
        mode = data.get("session_mode") or "target"
        self.session_mode = mode if mode in ("target", "timed") else "target"

        # Invalid/zero/negative/non-numeric values from the therapist's own
        # input (or a malformed config payload) always fall back to the
        # game's own difficulty preset -- never a zero/negative goal or
        # duration, which would otherwise end the session on its very first
        # frame.
        def _positive_int(value):
            try:
                n = int(value)
            except (TypeError, ValueError):
                return None
            return n if n > 0 else None

        cal_params = (data.get("calibration") or {}).get("params", {})
        if self.session_mode == "target":
            target = _positive_int(data.get("target_reps"))
            cal_goal = _positive_int(cal_params.get(cal_goal_key)) if cal_goal_key else None
            self.goal = target or cal_goal or int(target_presets[difficulty])
            self.timed_duration = None
        else:
            dur = _positive_int(data.get("duration_sec"))
            self.timed_duration = dur or int(duration_presets[difficulty])
            self.goal = None

    def _session_reset(self):
        """Call from the game's own _reset()."""
        self.elapsed   = 0.0
        self.time_left = float(self.timed_duration) if self.session_mode == "timed" else None

    def _session_tick(self, dt):
        """Call once per frame, only from the branch that already skips
        paused/fatigued frames (so paused time is automatically excluded,
        no extra bookkeeping needed). Returns True the one frame Timed
        Mode's countdown reaches zero -- the caller ends the session then,
        exactly like it already does for a reached Target."""
        self.elapsed += dt
        if self.session_mode == "timed":
            self.time_left = max(0.0, self.time_left - dt)
            return self.time_left <= 0
        return False

    def _session_target_reached(self):
        """Target Mode only -- True the instant self.reps reaches self.goal.
        Timed Mode always returns False (it ends via _session_tick() instead)."""
        return self.session_mode == "target" and self.reps >= self.goal

    def _session_header_time(self):
        """The value to feed games/game_header.py's draw_game_header (it
        just formats whatever float it's given as MM:SS) -- elapsed for
        Target Mode, the remaining countdown for Timed Mode."""
        return self.time_left if self.session_mode == "timed" else self.elapsed

    def _session_count_text(self):
        """"12/20" in Target Mode, "12" in Timed Mode -- for a label the
        caller already provides (results screens, counter boxes)."""
        return f"{self.reps}/{self.goal}" if self.session_mode == "target" else f"{self.reps}"

    def _session_progress_text(self, noun):
        """"12/20 shots" in Target Mode, "12 shots" in Timed Mode."""
        return f"{self._session_count_text()} {noun}"

    def _session_result_fields(self):
        """Merge into every save_session() call (see games/*.py _save_session())."""
        return {
            "session_mode":                self.session_mode,
            "goal":                        self.goal,
            "completed_reps":              self.reps,
            "duration_sec":                int(round(self.elapsed)),
            "configured_duration_seconds": self.timed_duration,
        }
