"""
TherapistLink -- the therapist side (production main.py / scenes/therapist_dashboard.py)
client for the shared session broker.

Mirrors recovr.comms.client.PatientCommsClient: a single daemon thread does all
HTTP (polls /api/state, drains an outbox of POSTs); the Pygame loop only touches
cheap in-memory fields. Never blocks, never raises into the scene loop.

Used ONLY when RECOVR_DUAL_MONITOR=1. A module-level singleton `therapist_link`
is provided so the dashboard scene (which is recreated on every return-from-game)
always talks to the same client / poll thread.
"""

import json
import time
import queue
import threading
import urllib.request

from recovr.shared import protocol
from recovr.shared import commands as cmd


class TherapistLink:

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or protocol.BASE_URL).rstrip("/")
        self._snapshot: dict | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._outbox: "queue.Queue[tuple[str, dict]]" = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="TherapistLink", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    # -- reads (scene loop) -----------------------------------------
    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def get_state(self) -> dict | None:
        with self._lock:
            return self._snapshot

    # -- writes (scene loop, non-blocking) ------------------------
    def configure(self, cfg: dict):
        self._enqueue(protocol.EP_CONFIG, cfg)

    def command(self, name: str):
        self._enqueue(protocol.EP_COMMAND, {"command": name})

    def set_volume(self, value: float):
        self._enqueue(protocol.EP_VOLUME, {"volume": value})

    def set_present(self, present: bool):
        self._enqueue(protocol.EP_THERAPIST, {"present": bool(present)})

    def set_booting(self, booting: bool):
        """Therapist has left the Welcome page but has not logged in yet
        (patient shows the Waiting Screen). Cleared automatically on login."""
        self._enqueue(protocol.EP_THERAPIST, {"booting": bool(booting)})

    def set_selected_patient(self, patient: dict | None):
        """Mirror the therapist's ONE selected session patient into shared state.
        `patient` = {"id":.., "full_name":..} or None to clear. Patient monitor:
        none -> Waiting Screen, set -> Patient Dashboard."""
        self._enqueue(protocol.EP_THERAPIST, {"selected_patient": patient or {}})

    def set_stop_pending(self, value: bool):
        """Red STOP pressed: the game is HELD (paused, state kept) and both
        monitors show the 'Game Stopped' screen until CONTINUE / BACK. Cleared
        when the therapist makes that choice."""
        self._enqueue(protocol.EP_THERAPIST, {"stop_pending": bool(value)})

    def set_dark_mode(self, value: bool):
        """Push the light/dark theme choice -- the patient applies it live on
        whatever screen it is currently showing."""
        self._enqueue(protocol.EP_THERAPIST, {"dark_mode": bool(value)})

    def reset(self):
        self._enqueue("/api/reset", {})

    def calibrate_begin(self, game_type: str):
        """Tell the patient window a (therapist-driven) calibration has started."""
        self._enqueue(protocol.EP_CONFIG, {"selected_game": game_type or "Gravity Catch"})
        self._enqueue(protocol.EP_COMMAND, {"command": cmd.CALIBRATE})

    def calibrate_end(self):
        """Clear the calibration state once the therapist's CalibrationWindow closes."""
        self._enqueue(protocol.EP_ACK, {"pending_action": cmd.CALIBRATE})

    def _enqueue(self, path: str, data: dict):
        try:
            self._outbox.put_nowait((path, data))
        except queue.Full:
            pass

    # -- worker thread --------------------------------------------
    def _run(self):
        next_poll = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_poll:
                self._poll_state()
                next_poll = now + protocol.POLL_INTERVAL_SEC
            drained = 0
            while drained < 16:
                try:
                    path, data = self._outbox.get_nowait()
                except queue.Empty:
                    break
                self._post(path, data)
                drained += 1
            time.sleep(0.02)

    def _poll_state(self):
        try:
            req = urllib.request.Request(self.base_url + protocol.EP_STATE, method="GET")
            with urllib.request.urlopen(req, timeout=protocol.HTTP_TIMEOUT_SEC) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            with self._lock:
                self._connected = False
            return
        with self._lock:
            self._snapshot = payload
            self._connected = True

    def _post(self, path: str, data: dict):
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=protocol.HTTP_TIMEOUT_SEC):
                with self._lock:
                    self._connected = True
        except Exception:
            with self._lock:
                self._connected = False


# module-level singleton (shared across dashboard recreations)
therapist_link = TherapistLink()
