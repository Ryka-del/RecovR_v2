"""
/api/* -- the communication layer's HTTP surface.

This blueprint is deliberately thin: it validates the request, calls one
`SessionStore` method, and returns the resulting snapshot. All the rules live
in `recovr.shared` so they are shared with (and testable without) Flask.
"""

from flask import Blueprint, current_app, jsonify, request

from recovr.shared import protocol
from recovr.shared import commands as cmd

bp = Blueprint("api", __name__)


def _store():
    return current_app.config["STORE"]


@bp.get(protocol.EP_HEALTH)
def health():
    return jsonify(ok=True)


@bp.get(protocol.EP_STATE)
def get_state():
    """Full session snapshot. Polled by both the browser and the Pygame client."""
    return jsonify(_store().snapshot())


@bp.post(protocol.EP_CONFIG)
def set_config():
    """Therapist sets/updates the session configuration."""
    data = request.get_json(silent=True) or {}
    return jsonify(_store().set_config(data))


@bp.post(protocol.EP_COMMAND)
def command():
    """Therapist issues a session command (START/PAUSE/RESUME/STOP/NEXT/CALIBRATE)."""
    data = request.get_json(silent=True) or {}
    name = str(data.get("command", "")).strip().upper()
    ok, msg, snap = _store().apply_command(name)
    status_code = 200 if ok else 409
    return jsonify(ok=ok, message=msg, state=snap), status_code


@bp.post(protocol.EP_GAME_DATA)
def game_data():
    """Patient pushes a live telemetry snapshot while a game runs."""
    data = request.get_json(silent=True) or {}
    return jsonify(_store().update_telemetry(data))


@bp.post(protocol.EP_RESULT)
def session_result():
    """Patient posts the final result when a game finishes on its own."""
    data = request.get_json(silent=True) or {}
    return jsonify(_store().set_result(data))


@bp.post(protocol.EP_ACK)
def ack():
    """Patient acknowledges a state/action (e.g. finished calibrating)."""
    data = request.get_json(silent=True) or {}
    return jsonify(_store().ack(data))


@bp.post(protocol.EP_VOLUME)
def volume():
    """Therapist sets the music volume (0.0-1.0); the patient applies it."""
    data = request.get_json(silent=True) or {}
    return jsonify(_store().set_volume(data.get("volume", 0.4)))


@bp.post(protocol.EP_THERAPIST)
def therapist_present():
    """Therapist session-shell state (any subset of keys; last write wins):
        {"booting": true}            -> left the Welcome page (patient -> Waiting Screen)
        {"present": true|false}      -> logged in / out
        {"selected_patient": {..}|null} -> the ONE selected session patient
                                        (patient monitor: none -> Waiting Screen,
                                         set -> Patient Dashboard)
        {"stop_pending": true|false}  -> red STOP pressed (game held) / decision made
        {"dark_mode": true|false}    -> light/dark theme (patient applies it live)
    """
    data = request.get_json(silent=True) or {}
    store = _store()
    snap = store.snapshot()
    if "booting" in data:
        snap = store.set_session_booting(data.get("booting", False))
    if "selected_patient" in data:
        snap = store.set_selected_patient(data.get("selected_patient") or {})
    if "stop_pending" in data:
        snap = store.set_stop_pending(data.get("stop_pending", False))
    if "dark_mode" in data:
        snap = store.set_dark_mode(data.get("dark_mode", True))
    if "present" in data:
        snap = store.set_therapist_present(data.get("present", False))
    return jsonify(snap)


# Small convenience for the browser UI / manual testing.
@bp.post("/api/reset")
def reset():
    return jsonify(_store().reset())


@bp.get("/api/meta")
def meta():
    """Static reference data for the control page (command + status names)."""
    return jsonify(commands=list(cmd.ALL_COMMANDS), statuses=list(cmd.ALL_STATUSES))
