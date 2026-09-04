"""
Session command vocabulary and the status-transition rules.

The therapist sends *commands*; the server turns each into a *status* change.
The patient (Pygame) never receives commands directly -- it polls the current
status and reconciles its screens to it. That makes every command idempotent and
impossible to "miss" over a lossy poll.
"""

# --- Commands (therapist -> server) -------------------------------------
START_SESSION = "START_SESSION"   # therapist "Start Session": patient -> How to Play (game NOT running)
START_GAME = "START_GAME"         # therapist "Start" on Session in Progress: the game actually starts
PAUSE_GAME = "PAUSE_GAME"
RESUME_GAME = "RESUME_GAME"
STOP_GAME = "STOP_GAME"
NEXT_GAME = "NEXT_GAME"
RESTART_GAME = "RESTART_GAME"     # re-run the SAME game from the start (current config)
CALIBRATE = "CALIBRATE"

ALL_COMMANDS = (
    START_SESSION, START_GAME, PAUSE_GAME, RESUME_GAME, STOP_GAME,
    NEXT_GAME, RESTART_GAME, CALIBRATE,
)

# --- Session status (server -> everyone) -------------------------------
IDLE = "IDLE"                # server up, nothing configured yet
READY = "READY"             # config set, waiting for START
RUNNING = "RUNNING"         # a game is active on the patient screen
PAUSED = "PAUSED"           # game held by the therapist
STOPPED = "STOPPED"         # game ended early by the therapist
COMPLETE = "COMPLETE"       # game finished on its own (result posted)
CALIBRATING = "CALIBRATING"  # patient is running a calibration routine

ALL_STATUSES = (
    IDLE, READY, RUNNING, PAUSED, STOPPED, COMPLETE, CALIBRATING,
)

# Which statuses a command is allowed to fire from. Anything else -> 409.
_ALLOWED_FROM = {
    START_SESSION: {IDLE, READY, STOPPED, COMPLETE},
    START_GAME:    {READY, STOPPED, COMPLETE},
    PAUSE_GAME:    {RUNNING},
    RESUME_GAME:   {PAUSED},
    STOP_GAME:     {READY, RUNNING, PAUSED},   # READY: emergency-stop during How-to-Play
    NEXT_GAME:     {RUNNING, PAUSED, STOPPED, COMPLETE},
    RESTART_GAME:  {RUNNING, PAUSED, STOPPED, COMPLETE},
    CALIBRATE:     {IDLE, READY, STOPPED, COMPLETE},
}

# Resulting status for each command.
_RESULT_STATUS = {
    START_SESSION: READY,
    START_GAME:    RUNNING,
    PAUSE_GAME:    PAUSED,
    RESUME_GAME:   RUNNING,
    STOP_GAME:     STOPPED,
    NEXT_GAME:     RUNNING,
    RESTART_GAME:  RUNNING,
    CALIBRATE:     CALIBRATING,
}

# Commands that (re)start a fresh activity -- the patient uses a bump in
# game_seq as its "start now / restart now" trigger.
_STARTS_FRESH_ACTIVITY = {START_GAME, NEXT_GAME, RESTART_GAME}

# START_SESSION bumps its own counter (session_seq): patient -> How to Play.
_STARTS_SESSION = {START_SESSION}


def is_command(value: str) -> bool:
    return value in ALL_COMMANDS


def can_apply(command: str, current_status: str) -> bool:
    return current_status in _ALLOWED_FROM.get(command, set())


def result_status(command: str) -> str:
    return _RESULT_STATUS[command]


def starts_fresh_activity(command: str) -> bool:
    return command in _STARTS_FRESH_ACTIVITY


def starts_session(command: str) -> bool:
    return command in _STARTS_SESSION
