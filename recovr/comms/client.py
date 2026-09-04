"""
PatientCommsClient -- the Pygame side of the communication layer.

Design goals: never block the 60 FPS game loop, never raise into it.

A single daemon thread does all HTTP:
  * every POLL_INTERVAL_SEC it GETs /api/state and stores the snapshot
  * between polls it drains an outbox queue of POSTs (telemetry / result / ack)

The game loop only ever touches in-memory fields (`get_snapshot()`, `connected`)
and appends to the outbox (`post_telemetry()` etc.) -- all lock-guarded and cheap.

Uses urllib from the standard library: no `requests` dependency.
"""

import json
import time
import queue
import threading
import urllib.request
import urllib.error

from recovr.shared import protocol


class PatientCommsClient:

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or protocol.BASE_URL).rstrip("/")

        self._snapshot: dict | None = None
        self._connected = False
        self._lock = threading.Lock()

        self._outbox: "queue.Queue[tuple[str, dict]]" = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="PatientComms", daemon=True
        )

    # -- lifecycle ------------------------------------------------------
    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -- reads (game loop) -------------------------------------------
    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def get_snapshot(self) -> dict | None:
        """Latest /api/state payload, or None if we have not reached the server."""
        with self._lock:
            return self._snapshot

    # -- writes (game loop, non-blocking) -------------------------
    def post_telemetry(self, data: dict):
        self._enqueue(protocol.EP_GAME_DATA, data)

    def post_result(self, data: dict):
        self._enqueue(protocol.EP_RESULT, data)

    def post_ack(self, data: dict):
        self._enqueue(protocol.EP_ACK, data)

    def _enqueue(self, path: str, data: dict):
        try:
            self._outbox.put_nowait((path, data))
        except queue.Full:
            # Telemetry is fire-and-forget; dropping a stale frame is fine.
            pass

    # -- worker thread --------------------------------------------
    def _run(self):
        next_poll = 0.0
        while not self._stop.is_set():
            now = time.monotonic()

            if now >= next_poll:
                self._poll_state()
                next_poll = now + protocol.POLL_INTERVAL_SEC

            # Drain whatever is waiting, but do not spin forever.
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
            payload = self._get(protocol.EP_STATE)
        except Exception:
            with self._lock:
                self._connected = False
            return
        with self._lock:
            self._snapshot = payload
            self._connected = True

    # -- raw HTTP -------------------------------------------------
    def _get(self, path: str) -> dict:
        req = urllib.request.Request(self.base_url + path, method="GET")
        with urllib.request.urlopen(req, timeout=protocol.HTTP_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, data: dict) -> dict | None:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=protocol.HTTP_TIMEOUT_SEC) as resp:
                with self._lock:
                    self._connected = True
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            with self._lock:
                self._connected = False
            return None
