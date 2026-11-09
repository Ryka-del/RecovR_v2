"""
Centralised session state -- the one object Flask and Pygame agree on.

`SessionStore` is the single source of truth. It lives in the Flask server
process; the browser and the Pygame app read it over HTTP and reconcile to it.
Every mutating method is guarded by a lock because Flask serves requests on
multiple threads.

Nothing here imports Flask or Pygame -- it is plain data + a lock, so it is
trivial to unit-test and to reuse from a different transport later.
"""

import time
import uuid
import threading
from dataclasses import dataclass, field, asdict

from recovr.shared import commands as cmd


# ----------------------------------------------------------------------------
#  Data
# ----------------------------------------------------------------------------

@dataclass
class SessionConfig:
    """Everything the therapist chooses before a session starts.

    This is exactly the payload the patient side needs to run a game, so it is
    passed through verbatim inside the state snapshot.
    """
    session_id: str = ""
    patient_id: str = ""
    patient_name: str = ""
    therapist_name: str = ""
    account_id: int | None = None      # therapist DB id (production dual-monitor path)
    selected_game: str = ""            # "" = none chosen yet (patient_main only starts a
                                        # session once this is truthy -- see _begin_session)
    difficulty: str = "Easy"
    session_mode: str = "target"        # "target" (set goal) or "timed" (set duration)
    target_reps: int | None = None      # Target Mode: None = game's own difficulty preset
    duration_sec: int | None = None     # Timed Mode: None = game's own difficulty preset
    speed: str = "Normal"
    dark_mode: bool = False             # mirror of the live theme for the game payload
    calibration: dict = field(default_factory=dict)   # calibration_result passed to the game

    def apply(self, data: dict) -> None:
        """Update fields from a partial dict (unknown keys ignored)."""
        if "patient_id" in data:
            self.patient_id = str(data["patient_id"]).strip() if data["patient_id"] is not None else ""
        if "patient_name" in data:
            self.patient_name = str(data["patient_name"]).strip()
        if "therapist_name" in data:
            self.therapist_name = str(data["therapist_name"]).strip()
        if "account_id" in data:
            try:
                self.account_id = int(data["account_id"]) if data["account_id"] is not None else None
            except (TypeError, ValueError):
                self.account_id = None
        if "selected_game" in data:
            self.selected_game = str(data["selected_game"]).strip()
        if "difficulty" in data:
            self.difficulty = str(data["difficulty"]).strip() or "Easy"
        if "session_mode" in data:
            mode = str(data["session_mode"]).strip() or "target"
            self.session_mode = mode if mode in ("target", "timed") else "target"
        if "target_reps" in data:
            try:
                val = int(data["target_reps"]) if data["target_reps"] is not None else None
                self.target_reps = val if val and val > 0 else None
            except (TypeError, ValueError):
                self.target_reps = None
        if "duration_sec" in data:
            try:
                self.duration_sec = (max(5, min(3600, int(data["duration_sec"])))
                                      if data["duration_sec"] is not None else None)
            except (TypeError, ValueError):
                self.duration_sec = None
        if "speed" in data:
            self.speed = str(data["speed"]).strip() or "Normal"
        if "dark_mode" in data:
            self.dark_mode = bool(data["dark_mode"])
        if "calibration" in data and isinstance(data["calibration"], dict):
            self.calibration = dict(data["calibration"])


@dataclass
class SessionState:
    status: str = cmd.IDLE
    config: SessionConfig = field(default_factory=SessionConfig)

    # Monotonic counters. `command_seq` bumps on every accepted command;
    # `session_seq` bumps on START_SESSION (patient -> How to Play);
    # `game_seq` bumps on START_GAME / RESTART / NEXT (the actual game starts).
    # The patient keys its screen transitions off session_seq and game_seq.
    command_seq: int = 0
    session_seq: int = 0
    game_seq: int = 0

    last_command: str = ""
    pending_action: str = ""     # e.g. "CALIBRATE" -- patient clears it via /api/ack

    telemetry: dict = field(default_factory=dict)   # latest live game-data snapshot
    result: dict = field(default_factory=dict)      # final result of last session
    volume: float = 0.4                              # music volume 0.0-1.0 (therapist-controlled)
    therapist_present: bool = False                  # a therapist is logged in
    session_booting: bool = False                    # therapist left Welcome, not yet logged in
                                                     # (patient -> Waiting Screen; cleared on login)
    selected_patient: dict = field(default_factory=dict)  # the ONE selected session patient
                                                     # {} => none. Patient monitor: {} -> Waiting
                                                     # Screen, set -> Patient Dashboard.
    stop_pending: bool = False                       # red STOP pressed -> game is HELD (paused,
                                                     # state preserved) while the therapist chooses
                                                     # CONTINUE (resume) or BACK (end session).
                                                     # Both monitors show the "Game Stopped" screen.
    dark_mode: bool = False                          # THE single source of truth for the RecovR
                                                     # light/dark theme. Therapist toggles it; the
                                                     # patient applies it live on every screen.
    updated_at: float = field(default_factory=time.time)

    def snapshot(self) -> dict:
        d = asdict(self)
        d["server_time"] = time.time()
        return d


# ----------------------------------------------------------------------------
#  Store
# ----------------------------------------------------------------------------

class SessionStore:
    """Thread-safe holder for the one `SessionState`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = SessionState()

    # -- reads ------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return self._state.snapshot()

    # -- config (therapist) --------------------------------------------
    def set_config(self, data: dict) -> dict:
        with self._lock:
            self._state.config.apply(data)
            if "dark_mode" in data:                      # keep the SoT consistent
                self._state.dark_mode = bool(data["dark_mode"])
            if not self._state.config.session_id:
                self._state.config.session_id = uuid.uuid4().hex[:12]
            # Configuring while idle/stopped/complete makes us READY to start.
            if self._state.status in (cmd.IDLE, cmd.STOPPED, cmd.COMPLETE):
                self._state.status = cmd.READY
            self._touch()
            return self._state.snapshot()

    # -- commands (therapist) ----------------------------------------
    def apply_command(self, command: str) -> tuple[bool, str, dict]:
        with self._lock:
            if not cmd.is_command(command):
                return False, f"unknown command: {command!r}", self._state.snapshot()

            status = self._state.status
            if not cmd.can_apply(command, status):
                return (
                    False,
                    f"{command} not allowed from status {status}",
                    self._state.snapshot(),
                )

            self._state.status = cmd.result_status(command)
            self._state.last_command = command
            self._state.command_seq += 1

            if cmd.starts_session(command):
                self._state.session_seq += 1
                self._state.telemetry = {}
                self._state.result = {}

            if cmd.starts_fresh_activity(command):
                self._state.game_seq += 1
                self._state.telemetry = {}
                self._state.result = {}

            if command == cmd.STOP_GAME:
                # A real STOP_GAME terminates the session; the decision state is over.
                self._state.stop_pending = False

            if command == cmd.CALIBRATE:
                self._state.pending_action = cmd.CALIBRATE

            self._touch()
            return True, "ok", self._state.snapshot()

    # -- telemetry (patient) -----------------------------------------
    def update_telemetry(self, data: dict) -> dict:
        with self._lock:
            self._state.telemetry = dict(data or {})
            self._touch()
            return self._state.snapshot()

    # -- therapist presence (login / logout) ------------------------
    def set_therapist_present(self, value) -> dict:
        with self._lock:
            self._state.therapist_present = bool(value)
            if self._state.therapist_present:
                # A successful login ends the "booting" (welcome -> login) phase.
                self._state.session_booting = False
            self._touch()
            return self._state.snapshot()

    # -- session boot phase (therapist left Welcome, before login) --
    def set_session_booting(self, value) -> dict:
        with self._lock:
            self._state.session_booting = bool(value)
            self._touch()
            return self._state.snapshot()

    # -- selected session patient (single source of truth) ---------
    def set_selected_patient(self, data) -> dict:
        with self._lock:
            if isinstance(data, dict) and data.get("id") is not None:
                hist = []
                for h in (data.get("history") or [])[:30]:
                    if isinstance(h, dict):
                        # Full per-session detail (not just game/date/score) so
                        # the Patient Dashboard's Latest Session card can show
                        # the real game-specific result (completed_reps),
                        # duration, and goal/session_mode -- these are genuine
                        # DB columns (see database.py's sessions table), not
                        # invented fields. goal/completed_reps stay None when
                        # absent (pre-goal-tracking rows, or Timed Mode) rather
                        # than being coerced to 0, so the Dashboard can tell
                        # "no goal was set" apart from "goal of zero".
                        hist.append({
                            "game":                        str(h.get("game", "")),
                            "played_at":                   str(h.get("played_at", "")),
                            "difficulty":                  str(h.get("difficulty", "")),
                            "score":                       h.get("score", ""),
                            "status":                      str(h.get("status", "completed")),
                            "goal":                        h.get("goal"),
                            "completed_reps":               h.get("completed_reps"),
                            "duration_sec":                 h.get("duration_sec", 0) or 0,
                            "session_mode":                 str(h.get("session_mode", "target")),
                            "configured_duration_seconds":  h.get("configured_duration_seconds"),
                        })
                stats_in = data.get("stats")
                stats = None
                if isinstance(stats_in, dict):
                    stats = {
                        "total_sessions":  int(stats_in.get("total_sessions", 0) or 0),
                        "games_played":    int(stats_in.get("games_played", 0) or 0),
                        "goals_assigned":  int(stats_in.get("goals_assigned", 0) or 0),
                        "goals_completed": int(stats_in.get("goals_completed", 0) or 0),
                    }
                self._state.selected_patient = {
                    "id":        data.get("id"),
                    "full_name": str(data.get("full_name", "")),
                    "sex":       str(data.get("sex", "")),   # Dashboard's male/female illustration
                    "history":   hist,     # recent sessions for the Patient Dashboard
                    "stats":     stats,    # aggregate counts, or None if unavailable --
                                            # see database.py's get_patient_progress_summary()
                }
            else:
                self._state.selected_patient = {}
            self._touch()
            return self._state.snapshot()

    # -- red STOP pressed -> game held, awaiting CONTINUE / BACK --
    def set_stop_pending(self, value) -> dict:
        with self._lock:
            self._state.stop_pending = bool(value)
            self._touch()
            return self._state.snapshot()

    # -- light/dark theme (single source of truth) ---------------
    def set_dark_mode(self, value) -> dict:
        with self._lock:
            self._state.dark_mode = bool(value)
            self._state.config.dark_mode = bool(value)   # mirror for the game-launch payload
            self._touch()
            return self._state.snapshot()

    # -- volume (therapist) -------------------------------------------
    def set_volume(self, value) -> dict:
        with self._lock:
            try:
                self._state.volume = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                pass
            self._touch()
            return self._state.snapshot()

    # -- final result (patient) ------------------------------------
    def set_result(self, data: dict) -> dict:
        with self._lock:
            self._state.result = dict(data or {})
            # A game only finishes on its own from RUNNING/PAUSED.
            if self._state.status in (cmd.RUNNING, cmd.PAUSED):
                self._state.status = cmd.COMPLETE
            self._touch()
            return self._state.snapshot()

    # -- acknowledgements (patient) --------------------------------
    def ack(self, data: dict) -> dict:
        """Patient confirms it has handled something.

        Supported keys:
            pending_action: "CALIBRATE" -> clears pending_action and, if a
                            config exists, returns to READY (else IDLE).
            calibration:    optional dict stored alongside the result.
        """
        with self._lock:
            if data.get("pending_action") == cmd.CALIBRATE and \
                    self._state.pending_action == cmd.CALIBRATE:
                self._state.pending_action = ""
                if "calibration" in data:
                    self._state.result = {"calibration": data["calibration"]}
                if self._state.status == cmd.CALIBRATING:
                    self._state.status = (
                        cmd.READY if self._state.config.session_id else cmd.IDLE
                    )
            self._touch()
            return self._state.snapshot()

    # -- reset --------------------------------------------------------
    def reset(self) -> dict:
        """Clear config / telemetry / result back to IDLE, but KEEP the
        monotonic counters. game_seq/command_seq must only ever increase so the
        patient reliably detects the next START as a fresh activity -- zeroing
        them is what caused 'second game does not appear'.
        """
        with self._lock:
            dark = self._state.dark_mode
            self._state = SessionState(
                game_seq=self._state.game_seq,
                session_seq=self._state.session_seq,
                command_seq=self._state.command_seq,
                volume=self._state.volume,
                therapist_present=self._state.therapist_present,
                session_booting=self._state.session_booting,
                selected_patient=self._state.selected_patient,
                dark_mode=dark,
            )
            self._state.config.dark_mode = dark          # carry the theme onto the fresh config
            return self._state.snapshot()

    # -- internal ---------------------------------------------------
    def _touch(self):
        self._state.updated_at = time.time()
