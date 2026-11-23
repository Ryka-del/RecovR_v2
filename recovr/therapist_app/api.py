"""
/api/* -- the communication layer's HTTP surface.

This blueprint is deliberately thin: it validates the request, calls one
`SessionStore` method, and returns the resulting snapshot. All the rules live
in `recovr.shared` so they are shared with (and testable without) Flask.
"""

import time

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


@bp.get(protocol.EP_BLE_LEASE)
def ble_lease():
    """Minimal BLE ownership snapshot -- polled at a much higher frequency
    than EP_STATE by each process's own BLEReceiver lease watchdog (see
    sensors/ble_receiver.py) and by launch_production.py's supervisor loop,
    so this is deliberately tiny rather than reusing the full session
    snapshot. pending_seconds is computed here (not left to each caller) so
    everyone reasons about handoff age against the same server clock."""
    snap = _store().snapshot()
    requested_at = snap.get("ble_handoff_requested_at") or 0.0
    pending_seconds = (time.monotonic() - requested_at) if requested_at else 0.0
    return jsonify(
        owner=snap.get("ble_owner", "therapist"),
        target=snap.get("ble_handoff_target", ""),
        generation=snap.get("ble_generation", 0),
        pending_seconds=max(0.0, pending_seconds),
    )


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
    """Patient acknowledges a state/action (e.g. finished calibrating, or
    {"ble_released": true} -- patient confirms ITS OWN BLE receiver is now
    actually disabled + disconnected, completing a pending patient->therapist
    handoff; see SessionStore.confirm_patient_released)."""
    data = request.get_json(silent=True) or {}
    store = _store()
    snap = store.ack(data)
    if data.get("ble_released"):
        snap = store.confirm_patient_released()
    return jsonify(snap)


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
        {"calibration_progress": {..}} -> live sensor/step/attempt detail for the
                                        patient's own Calibration screen (see
                                        SessionState.calibration_progress)
        {"ble_handoff_target": "therapist"|"patient"} -> request a two-phase
                                        BLE ownership handoff toward this
                                        owner (see SessionState.ble_handoff_target)
        {"ble_release_confirmed": true} -> therapist confirms ITS OWN BLE
                                        receiver is now actually disabled +
                                        disconnected, completing a pending
                                        therapist->patient handoff (may come
                                        from the main thread OR the
                                        BLEReceiver's own lease watchdog --
                                        see sensors/ble_receiver.py; either
                                        is fine, the store call is idempotent)

        There is deliberately no "force owner" override here -- a handoff
        that never confirms simply stays pending (see
        scenes/therapist_dashboard.py's handoff-stuck UI handling and
        recovr/launch_production.py's supervisor, the only thing that may
        ever act on a stuck handoff, and only by shutting the whole app
        down after independently confirming a process actually terminated).
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
        snap = store.set_dark_mode(data.get("dark_mode", False))
    if "calibration_progress" in data:
        snap = store.set_calibration_progress(data.get("calibration_progress") or {})
    if "ble_handoff_target" in data:
        snap = store.set_ble_handoff_target(data.get("ble_handoff_target"))
    if "ble_release_confirmed" in data and data.get("ble_release_confirmed"):
        snap = store.confirm_therapist_released()
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
