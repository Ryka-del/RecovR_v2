# =============================================================================
# sensors/ble_receiver.py
# =============================================================================
# Auto-connecting BLE client for the RecovR wireless controller.
# Runs in a background daemon thread — never blocks pygame.
#
# Fixes stale-connection problem on Raspberry Pi / BlueZ:
#   - Resets the HCI adapter on startup and after every disconnect so that
#     closing and reopening the app always works cleanly.
# =============================================================================

import asyncio
import json
import os
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

DEVICE_NAME   = "RecovR-Controller"   # primary name set in firmware
# Any BLE device whose name contains one of these strings (case-insensitive)
# will also be accepted — covers typos, spaces vs hyphens, etc.
_NAME_KEYWORDS = ["recovr", "fsr402", "esp32_fsr"]
SERVICE_UUID  = "12345678-1234-1234-1234-123456789abc"
CHAR_UUID     = "12345678-1234-1234-1234-123456789abd"

# grip_raw, flex_raw (legacy single-flex), flex_thumb/index/middle/ring/pinky
# (Whack-a-Mole 5-finger glove), buttons, accel_x, accel_y -- must match
# firmware/recovr_controller/recovr_controller.ino's packet layout exactly.
PACKET_FORMAT = "<HHHHHHHBhh"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)   # 19 bytes

# Old firmware's 9-byte packet (grip, flex, buttons, accel_x, accel_y) --
# accepted for backward compatibility, see _on_notification().
_LEGACY_PACKET_FORMAT = "<HHBhh"
_LEGACY_PACKET_SIZE   = struct.calcsize(_LEGACY_PACKET_FORMAT)   # 9 bytes

_SCAN_TIMEOUT    = 5.0
_RECONNECT_DELAY = 2.0
_ERROR_DELAY     = 3.0
# How long a freshly-enabled session keeps retrying a miss before it parks as
# "not_found" -- covers the dual-monitor handoff's own disconnect-then-
# re-advertise chain (the other process's deliberate release, the ESP32's
# ~200ms advertising restart, BlueZ's own connection teardown), which can
# easily eat a single _SCAN_TIMEOUT window on its own, making the very first
# scan of a session come up empty through no fault of the controller actually
# being out of range. Retrying within this budget instead of giving up after
# one miss is what makes "every game start" reconnect reliably instead of
# needing a manual rescan tap almost every time.
_HANDOFF_RETRY_SECONDS = 30.0   # ~4 scan+settle cycles at _SCAN_TIMEOUT+_RECONNECT_DELAY each
# How long client.is_connected must read False CONTINUOUSLY before it's
# treated as a real disconnect -- see the hold loop in _ble_loop(). Real BLE
# stacks (especially BlueZ on the Pi) occasionally report a transient False
# for a single poll (a connection-parameter update, a missed keep-alive,
# brief interference) even though the physical link never actually drops;
# without this grace window that single blip tore the connection down and
# re-scanned from scratch, which is what made the UI flicker between
# Connected/Disconnected on an otherwise stable link. A genuine disconnect
# stays False well past this window, so it's still caught promptly.
_DISCONNECT_GRACE = 1.0

# ── Independent ownership lease (watchdog) ──────────────────────────────────
# In the dual-monitor app, set_enabled() is normally driven by the owning
# process's own main-thread reconcile loop (scenes/therapist_dashboard.py /
# recovr/patient_app/patient_main.py). If THAT thread stalls (frozen pygame
# loop, GC pause, anything short of the whole process dying), this receiver's
# own background thread would otherwise keep doing exactly what it was last
# told -- including staying connected, or even autonomously reconnecting --
# with zero awareness that a handoff moved ownership elsewhere. The lease
# watchdog is a SECOND, independent thread that polls the broker's tiny
# /api/ble/lease endpoint on its own schedule and enforces the SAME
# authorization formula the main thread already uses
# (owner == my role AND target != the other role), so a stuck main thread no
# longer means a stuck physical connection. It is purely additive: the main
# thread's own set_enabled()/confirm calls are unchanged and remain the
# fast, zero-extra-latency path when everything is healthy; the watchdog
# only ever matters when that path didn't run. See set_role() -- a receiver
# with no role set (prototype/standalone/non-dual-monitor use) never
# activates the watchdog at all.
_LEASE_HEARTBEAT_SEC = float(os.environ.get("RECOVR_BLE_LEASE_HEARTBEAT_SEC", "1.0"))
# How long WITHOUT a successful lease poll before the watchdog assumes
# ownership can no longer be verified and fails closed (disables if
# currently enabled). Deliberately several heartbeats' worth of slack so a
# single dropped request / brief broker hiccup never disconnects a
# legitimately-owned, working connection -- only a sustained outage does.
_LEASE_TIMEOUT_SEC = float(os.environ.get("RECOVR_BLE_LEASE_TIMEOUT_SEC", "4.0"))
# Per-request timeout for the watchdog's own HTTP calls -- short and
# distinct from the heartbeat cadence so one slow/hanging request can never
# make the watchdog loop itself stall or overlap a second request; the loop
# is strictly sequential (poll, process, sleep, repeat), so at most one
# lease request is ever in flight.
_LEASE_REQUEST_TIMEOUT_SEC = 0.5


class BLEReceiver:

    def __init__(self):
        self._lock      = threading.Lock()
        self._latest    = {
            "grip_raw": 0, "flex_raw": 0,
            "flex_thumb_raw": 0, "flex_index_raw": 0, "flex_middle_raw": 0,
            "flex_ring_raw": 0, "flex_pinky_raw": 0,
            "buttons":  0, "accel_x":  0, "accel_y": 0,
        }
        self._connected = False
        self._first_run = True

        # Gate for the scan/connect loop. When False the loop parks and any live
        # connection is dropped, freeing the controller for another process.
        # In the dual-monitor app the therapist and patient processes each own a
        # BLEReceiver but only one holds the controller at a time; they start
        # disabled (RECOVR_BLE_START_DISABLED=1, set by recovr.launch_production)
        # and call set_enabled() as the session moves between them. Unset env =>
        # enabled, so the standalone app / tests are unaffected.
        self._enabled = os.environ.get("RECOVR_BLE_START_DISABLED") != "1"

        # ── Observable status, for the UI connection monitor ──────────────────
        # _stage is one of: disabled / scanning / connecting / connected /
        #                   not_found / no_bleak / bluetooth_off /
        #                   old_firmware / error
        self._stage        = "disabled" if not self._enabled else "scanning"
        self._detail       = ""      # short human-readable reason / device name
        self._dev_name     = ""      # last device we matched
        self._dev_addr     = ""
        self._scan_count   = 0
        self._seen_names   = []      # names from the most recent discover()
        self._last_packet  = 0.0     # time.monotonic() of the last notification

        # ── Independent ownership lease (see the module-level comment above
        # _LEASE_HEARTBEAT_SEC) ─────────────────────────────────────────────
        self._role = None                 # "therapist" / "patient" / None (inert)
        self._last_known_generation = -1  # -1 so the very first lease response is
                                           # always accepted regardless of its value
        self._confirmed_generation = -1   # highest generation this receiver has
                                           # already posted a release confirmation
                                           # for -- avoids re-posting every watchdog
                                           # cycle while a confirmed handoff is still
                                           # being reflected back by the broker

        t = threading.Thread(target=self._thread_main, name="BLEReceiver", daemon=True)
        t.start()
        w = threading.Thread(target=self._lease_watchdog, name="BLEReceiverLease", daemon=True)
        w.start()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    def set_enabled(self, on: bool) -> None:
        """Enable/disable the scan+connect loop at runtime. Disabling drops any
        active connection within ~0.1 s; enabling resumes scanning within ~0.3 s.
        Thread-safe -- called from both the owning process's own main-thread
        reconcile loop AND this receiver's own lease watchdog thread; either
        can disable at any time, and a redundant call from the other is a
        harmless no-op (the actual scan/connect/disconnect logic lives in a
        single coroutine in _ble_loop(), which only ever reads this flag)."""
        with self._lock:
            self._enabled = bool(on)

    def _is_enabled(self) -> bool:
        """Lock-protected read of self._enabled, used throughout _ble_loop()
        instead of the bare attribute -- not because a bool read/write can
        tear under the GIL, but so this stays correct even if _enabled ever
        grows into a compound/multi-field check, and so it's unambiguous
        this is read consistently with how set_enabled()/the watchdog write
        it."""
        with self._lock:
            return self._enabled

    def set_role(self, role: str) -> None:
        """Identify which process this receiver belongs to ("therapist" or
        "patient"), enabling the independent lease watchdog (see the
        module-level comment above _LEASE_HEARTBEAT_SEC). Call once, early
        in startup. A receiver with no role set (the default) never polls
        the broker and behaves exactly as before this feature existed --
        this is what keeps the prototype/non-dual-monitor and standalone
        paths, which never call this, completely unaffected."""
        with self._lock:
            self._role = str(role or "").strip().lower() or None

    def rescan(self) -> None:
        """Force the loop to drop what it is doing and start a fresh scan.
        Used by the dashboard's controller indicator as a manual retry."""
        with self._lock:
            self._enabled = False
        self._stage = "scanning"
        self._detail = "restarting"

        def _resume():
            time.sleep(0.6)          # let the loop park + release cleanly
            self._first_run = True   # re-print the visible-device list
            with self._lock:
                self._enabled = True
        threading.Thread(target=_resume, daemon=True).start()

    def status(self) -> dict:
        """Snapshot of the connection state for the UI.

        stage       -- disabled | scanning | connecting | connected |
                       not_found | no_bleak | bluetooth_off | old_firmware | error
        detail      -- short reason / device name (may be "")
        connected   -- True only when sensor data is live
        scans       -- how many scan rounds since the receiver was enabled
        seen        -- device names from the last scan (helps spot the ESP32)
        data_age    -- seconds since the last sensor packet (None if never)
        """
        age = None
        if self._last_packet:
            age = max(0.0, time.monotonic() - self._last_packet)
        return {
            "stage":     self._stage,
            "detail":    self._detail,
            "connected": self._connected,
            "device":    self._dev_name,
            "address":   self._dev_addr,
            "scans":     self._scan_count,
            "seen":      list(self._seen_names),
            "data_age":  age,
        }

    def get_latest(self) -> dict:
        with self._lock:
            return dict(self._latest)

    # ── Independent ownership lease watchdog ──────────────────────────────────
    # Runs in its own thread, entirely independent of the owning process's
    # main pygame loop and of the _ble_loop asyncio thread -- so it keeps
    # enforcing ownership even if the main loop freezes (the scenario this
    # exists for) or, to the extent it can, even if _ble_loop itself is
    # wedged (it can still independently flip self._enabled; whether
    # _ble_loop notices promptly depends on that loop recovering). It is a
    # plain synchronous loop (poll, process, sleep, repeat) -- never more
    # than one lease request in flight, bounded per-request timeout, no
    # thread spawned per poll.
    def _lease_watchdog(self):
        last_good_poll = None   # time.monotonic() of the last successful poll
        while True:
            with self._lock:
                role = self._role
            if role is None:
                # No role assigned (prototype/standalone/non-dual-monitor
                # use, or not yet configured) -- stay fully inert.
                time.sleep(_LEASE_HEARTBEAT_SEC)
                continue

            other_role = "patient" if role == "therapist" else "therapist"
            response = self._poll_lease()

            if response is None:
                # Broker unreachable this cycle. Tolerate up to
                # _LEASE_TIMEOUT_SEC of consecutive failures (a single
                # dropped request / brief outage must not disconnect a
                # legitimately-owned, working connection) -- only a
                # sustained outage means ownership genuinely can't be
                # verified, at which point fail closed.
                if last_good_poll is not None and (time.monotonic() - last_good_poll) > _LEASE_TIMEOUT_SEC:
                    if self._is_enabled():
                        print("[BLE] Lease watchdog: broker unreachable past the lease "
                              "window -- ownership can't be verified, disabling.")
                        self.set_enabled(False)
                elif last_good_poll is None:
                    # Never successfully polled yet -- same reasoning, can't
                    # assume authorization without ever having confirmed it.
                    pass
                time.sleep(_LEASE_HEARTBEAT_SEC)
                continue

            owner, target, generation = response

            with self._lock:
                if generation < self._last_known_generation:
                    # Stale/out-of-order response (e.g. a slow request that
                    # completed after a faster, later one already landed) --
                    # discard the WHOLE response, change nothing. Using >=
                    # (not >) for acceptance is what lets a receiver re-
                    # authorize itself after a mere connectivity outage,
                    # where the generation legitimately hasn't moved at all.
                    stale = True
                else:
                    stale = False
                    self._last_known_generation = generation
            if stale:
                time.sleep(_LEASE_HEARTBEAT_SEC)
                continue

            last_good_poll = time.monotonic()
            authorized = (owner == role) and (target != other_role)

            if not authorized:
                if self._is_enabled():
                    self.set_enabled(False)
            elif not self._is_enabled():
                # Mirrors the main thread's own "owner == role and target !=
                # other" formula -- this only ever runs once ownership has
                # ALREADY been safely, confirmedly transferred by whichever
                # side (main thread or watchdog, either direction) got there
                # first; it is never itself a path that grants ownership
                # without confirmation.
                self.set_enabled(True)

            # We are the still-current, mid-handoff OUTGOING owner: confirm
            # release as soon as our OWN receiver verifiably shows actually
            # disconnected (not merely told to disable) -- independent of
            # whatever the main thread is or isn't doing. Idempotent with
            # the main thread's own confirm call (the broker-side guard
            # only applies the first one to arrive); _confirmed_generation
            # just avoids re-posting every watchdog cycle once done.
            if owner == role and target == other_role:
                with self._lock:
                    already_confirmed = self._confirmed_generation >= generation
                if not already_confirmed:
                    st = self.status()
                    if st["stage"] == "disabled" and not st["connected"]:
                        if self._post_release_confirm(role):
                            with self._lock:
                                self._confirmed_generation = generation

            time.sleep(_LEASE_HEARTBEAT_SEC)

    def _poll_lease(self):
        """GET /api/ble/lease -> (owner, target, generation), or None on any
        failure (timeout, connection error, malformed response). Lazily
        imports recovr.shared.protocol so this module has zero hard
        dependency on the recovr package at import time -- a receiver that
        never gets a role assigned (and thus never reaches this method)
        never needs it at all."""
        try:
            from recovr.shared import protocol
        except Exception:
            return None
        try:
            req = urllib.request.Request(protocol.BASE_URL + protocol.EP_BLE_LEASE, method="GET")
            with urllib.request.urlopen(req, timeout=_LEASE_REQUEST_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return (
                str(data.get("owner", "therapist")),
                str(data.get("target", "")),
                int(data.get("generation", 0)),
            )
        except Exception:
            return None

    def _post_release_confirm(self, role: str) -> bool:
        """POST this process's own release confirmation -- the same call
        the main thread makes (TherapistLink.confirm_ble_released() /
        PatientCommsClient.post_ack({"ble_released": True})), issued
        directly here so it has no dependency on those subsystems' own
        health. Returns True on a successful request (not necessarily that
        the store accepted it -- the store-side owner/target guard makes a
        rejected/stale confirm a harmless no-op either way)."""
        try:
            from recovr.shared import protocol
        except Exception:
            return False
        path, body = (
            (protocol.EP_THERAPIST, {"ble_release_confirmed": True}) if role == "therapist"
            else (protocol.EP_ACK, {"ble_released": True})
        )
        try:
            req = urllib.request.Request(
                protocol.BASE_URL + path, data=json.dumps(body).encode("utf-8"),
                method="POST", headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=_LEASE_REQUEST_TIMEOUT_SEC):
                pass
            return True
        except Exception:
            return False

    # ── Thread — resets adapter then runs the async loop ─────────────────────

    def _thread_main(self):
        while True:
            # Reset the Bluetooth adapter before every loop iteration.
            # This clears stale connections left over from a previous session.
            self._reset_adapter()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._ble_loop())
            except Exception as exc:
                self._connected = False
                self._stage  = self._classify_error(exc)
                self._detail = f"{type(exc).__name__}: {exc}"[:60]
                print(f"[BLE] Loop error ({type(exc).__name__}: {exc}). Restarting...")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

            self._connected = False
            time.sleep(_ERROR_DELAY)

    # ── Adapter reset (Linux / Raspberry Pi only) ─────────────────────────────

    @staticmethod
    def _reset_adapter():
        if sys.platform != "linux":
            return
        try:
            subprocess.run(
                ["hciconfig", "hci0", "reset"],
                capture_output=True, timeout=5
            )
            time.sleep(1.0)   # let the adapter come back up
        except Exception:
            pass   # hciconfig not available — skip silently

    # ── Main async BLE loop ───────────────────────────────────────────────────

    async def _ble_loop(self):
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            print("[BLE] ERROR: bleak not installed.  Run:  pip install bleak")
            self._stage, self._detail = "no_bleak", "pip install bleak"
            return

        # Two different retry policies per "enabled session" (a patient
        # being selected, or an explicit manual rescan -- both go through
        # set_enabled/rescan()):
        #   - Never connected yet this session: retry misses for
        #     _HANDOFF_RETRY_SECONDS, then give up (`gave_up`) and park
        #     until the therapist taps the monitor for a manual rescan --
        #     avoids scanning forever for a controller that may genuinely
        #     not be there (dead battery, powered off).
        #   - Connected at least once this session (`ever_connected`): it's
        #     known to be around, so a later miss keeps retrying (still
        #     paced) indefinitely instead of giving up -- a mid-session
        #     drop reconnects on its own, no manual tap needed.
        # Both are reset on the NEXT disabled->enabled transition.
        was_enabled = False
        gave_up = False
        enabled_since = 0.0
        # Once this enabled session has connected successfully at least
        # once, the controller is known to be around -- a later miss is far
        # more likely a brief handoff/range blip than "it was never here,"
        # so give-up-after-a-budget no longer applies and it keeps retrying
        # (still paced) until reconnected or disabled. Reset alongside
        # gave_up/enabled_since on every fresh enable.
        ever_connected = False

        while True:
            # ── Park while disabled: no scanning, no connection held ──────────
            if not self._is_enabled():
                was_enabled = False
                gave_up = False
                self._connected = False
                if self._stage != "disabled":
                    self._stage, self._detail = "disabled", ""
                    self._scan_count = 0
                await asyncio.sleep(0.3)
                continue

            if not was_enabled:
                gave_up = False   # fresh enable -- allow new scan attempts
                enabled_since = time.monotonic()
                ever_connected = False
            was_enabled = True

            # ── Already searched once this session and found nothing: park
            # without re-scanning until re-enabled (new patient selected) or
            # the therapist taps the monitor for a manual rescan. ──────────
            if gave_up:
                if self._stage != "not_found":
                    self._stage  = "not_found"
                    self._detail = "tap to search again"
                await asyncio.sleep(0.3)
                continue

            # ── Scan ─────────────────────────────────────────────────────────
            # find_device_by_filter returns the INSTANT the controller
            # advertises, instead of always burning the whole timeout like
            # discover(). That matters for the dual-monitor handoff: the game
            # must have the controller before the therapist's START unlocks.
            self._scan_count += 1
            self._stage = "scanning"
            self._detail = f"scan #{self._scan_count}"
            # Printed on the first attempt and then only every 5th after that
            # (~35s instead of ~7s) -- still a visible heartbeat while no
            # controller is in range, without flooding the terminal for
            # every single retry of an indefinite "while True" loop.
            if self._scan_count == 1 or self._scan_count % 5 == 0:
                print(f"[BLE] Scan #{self._scan_count} — looking for '{DEVICE_NAME}'...")
            device = None
            seen = {}

            def _adv_name(d, adv):
                """Name from the advert OR the scan response (the ESP32 puts the
                full name in the scan response, so d.name can lag)."""
                return d.name or (getattr(adv, "local_name", None) if adv else None)

            def _match(d, adv):
                nm = _adv_name(d, adv)
                seen[d.address] = nm or "(no name)"
                if nm == DEVICE_NAME:
                    return True
                return any(kw in nm.lower() for kw in _NAME_KEYWORDS) if nm else False

            try:
                device = await BleakScanner.find_device_by_filter(
                    _match, timeout=_SCAN_TIMEOUT)
            except Exception as exc:
                self._connected = False
                self._stage = self._classify_error(exc)
                self._detail = str(exc)[:60]
                print(f"[BLE] Scan error: {exc}")
                self._print_permission_hint(exc)
                await asyncio.sleep(_ERROR_DELAY)
                continue
            finally:
                self._seen_names = list(seen.values())

            if device is None:
                if ever_connected:
                    # Known to be around (we've already connected to it this
                    # session) -- keep retrying indefinitely instead of
                    # giving up, so a mid-session drop reconnects on its own.
                    self._detail = f"not advertising, reconnecting (scan #{self._scan_count})"
                else:
                    retry_budget_left = _HANDOFF_RETRY_SECONDS - (time.monotonic() - enabled_since)
                    if retry_budget_left <= 0:
                        gave_up = True   # retry budget spent -- stop auto-rescanning
                        self._detail = f"not advertising (scan #{self._scan_count})"
                    else:
                        self._detail = f"not advertising, retrying (scan #{self._scan_count})"
                # Nothing matched -- print what IS visible, so the user can tell
                # "Bluetooth sees nothing" from "the ESP32 is advertising nameless".
                if self._first_run:
                    self._first_run = False
                    if seen:
                        print("[BLE]   Visible BLE devices:")
                        for addr, nm in seen.items():
                            print(f"[BLE]     {nm:<32s}  {addr}")
                        print("[BLE]   None matched. If your controller is listed as "
                              "'(no name)', re-flash firmware/recovr_controller/recovr_controller.ino "
                              "(it needs setScanResponse(true)).")
                    else:
                        print("[BLE]   (no BLE devices at all — is Bluetooth on?)")
                if not gave_up:
                    # Reset the adapter before retrying, same as every other
                    # retry path in this loop (e.g. after a dropped
                    # connection) -- repeated BlueZ StartDiscovery/
                    # StopDiscovery cycles with no hard reset in between can
                    # leave the adapter's discovery state degraded on real
                    # Raspberry Pi hardware (missing advertisements it would
                    # otherwise see, or producing an unstable connection even
                    # once one is found), which a scan-miss retry loop could
                    # run into many times in a row without ever hitting the
                    # connect-failure branch that already resets. Also gives
                    # BlueZ a moment to settle -- restarting scans back-to-
                    # back with no gap at all is unreliable on its own.
                    self._reset_adapter()
                    await asyncio.sleep(_RECONNECT_DELAY)
                continue

            # A scan can take up to _SCAN_TIMEOUT seconds -- ownership may
            # have been revoked (set_enabled(False), from the main thread OR
            # this receiver's own lease watchdog) while it was in flight.
            # Re-check before spending more time on a connect attempt nobody
            # authorized any more.
            if not self._is_enabled():
                continue

            # ── Connect ───────────────────────────────────────────────────────
            self._dev_name = device.name or "(no name)"
            self._dev_addr = device.address
            self._stage    = "connecting"
            self._detail   = self._dev_name
            print(f"[BLE] Found '{device.name}' ({device.address}). Connecting...")
            try:
                async with BleakClient(device, timeout=10.0) as client:
                    # connect() itself can take up to 10s -- ownership may
                    # have been revoked while it was in flight. Check BEFORE
                    # touching characteristics/notify or ever reporting
                    # "connected", so a stale attempt disconnects
                    # immediately (the `async with` exit below) without
                    # ever having been usable or visible as live.
                    if not self._is_enabled():
                        print("[BLE] Ownership revoked while connecting -- disconnecting without using it.")
                    else:
                        print("[BLE] Connected. Reading characteristics...")
                        for svc in client.services:
                            for ch in svc.characteristics:
                                match = " <-- TARGET" if ch.uuid == CHAR_UUID else ""
                                print(f"[BLE]   {ch.uuid}{match}")

                        if not any(
                            ch.uuid == CHAR_UUID
                            for svc in client.services
                            for ch in svc.characteristics
                        ):
                            print(f"[BLE] WARNING: CHAR_UUID {CHAR_UUID} not found.")
                            print("[BLE] The ESP32 is running old firmware — please flash firmware/recovr_controller/recovr_controller.ino")
                            self._stage  = "old_firmware"
                            self._detail = "flash firmware/recovr_controller/recovr_controller.ino"
                            # Keep connected flag False; retry after delay
                            await asyncio.sleep(5.0)
                        else:
                            self._connected = True
                            ever_connected = True
                            self._stage  = "connected"
                            self._detail = self._dev_name
                            print("[BLE] Controller connected!  Sensor data is live.")
                            await client.start_notify(CHAR_UUID, self._on_notification)
                            # Hold the connection until it drops OR this receiver is
                            # disabled (session handed the controller to the other
                            # process, or this receiver's own lease watchdog revoked
                            # it). Leaving the `async with` disconnects cleanly.
                            # client.is_connected going False is given a short grace
                            # window (_DISCONNECT_GRACE) to recover on its own before
                            # this is treated as a real disconnect -- see that
                            # constant's comment. self._connected/_stage are left
                            # untouched during the grace window, so the UI never
                            # flickers for a blip that resolves on its own.
                            disconnect_since = None
                            while self._is_enabled():
                                if client.is_connected:
                                    disconnect_since = None
                                else:
                                    if disconnect_since is None:
                                        disconnect_since = time.monotonic()
                                    elif time.monotonic() - disconnect_since >= _DISCONNECT_GRACE:
                                        break
                                await asyncio.sleep(0.1)

                self._connected = False
                if self._is_enabled():
                    self._stage, self._detail = "scanning", "link dropped"
                    print("[BLE] Controller disconnected. Scanning again...")
                else:
                    print("[BLE] Controller released (receiver disabled).")

            except Exception as exc:
                self._connected = False
                self._stage  = self._classify_error(exc)
                self._detail = f"{type(exc).__name__}: {exc}"[:60]
                print(f"[BLE] Connection error: {type(exc).__name__}: {exc}")

            # Reset the adapter so BlueZ doesn't cache the old connection — but
            # not on a deliberate release, so we don't disturb the other process.
            if self._is_enabled():
                self._reset_adapter()
                await asyncio.sleep(_RECONNECT_DELAY)

    # ── Notification handler ──────────────────────────────────────────────────

    def _on_notification(self, sender, data: bytearray):
        # Backward compatible with a controller still running the OLD 9-byte
        # firmware (grip, flex, buttons, accel_x, accel_y) -- the 5 new
        # per-finger fields just fall back to duplicating the single legacy
        # flex reading (today's behavior) instead of the whole packet being
        # silently dropped and every sensor-based game freezing until the
        # ESP32 is reflashed with the updated firmware.
        if len(data) >= PACKET_SIZE:
            self._last_packet = time.monotonic()
            vals = struct.unpack_from(PACKET_FORMAT, data)
            with self._lock:
                self._latest = {
                    "grip_raw":        vals[0],
                    "flex_raw":        vals[1],
                    "flex_thumb_raw":  vals[2],
                    "flex_index_raw":  vals[3],
                    "flex_middle_raw": vals[4],
                    "flex_ring_raw":   vals[5],
                    "flex_pinky_raw":  vals[6],
                    "buttons":         vals[7],
                    "accel_x":         vals[8],
                    "accel_y":         vals[9],
                }
            return
        if len(data) >= _LEGACY_PACKET_SIZE:
            self._last_packet = time.monotonic()
            grip_raw, flex_raw, buttons, accel_x, accel_y = \
                struct.unpack_from(_LEGACY_PACKET_FORMAT, data)
            with self._lock:
                self._latest = {
                    "grip_raw": grip_raw, "flex_raw": flex_raw,
                    "flex_thumb_raw": flex_raw, "flex_index_raw": flex_raw,
                    "flex_middle_raw": flex_raw, "flex_ring_raw": flex_raw,
                    "flex_pinky_raw": flex_raw,
                    "buttons": buttons, "accel_x": accel_x, "accel_y": accel_y,
                }

    @staticmethod
    def _classify_error(exc) -> str:
        """Map a bleak/OS exception onto a UI stage so the dashboard can show a
        useful reason instead of a bare 'disconnected'."""
        msg = str(exc).lower()
        if ("powered off" in msg or "not powered on" in msg or "turn on bluetooth" in msg
                or "bluetooth radio" in msg):
            return "bluetooth_off"
        if "adapter" in msg or "no such device" in msg or "not found" in msg:
            return "bluetooth_off"
        if "permission" in msg or "not permitted" in msg or "access denied" in msg:
            return "no_permission"
        return "error"

    @staticmethod
    def _print_permission_hint(exc):
        msg = str(exc).lower()
        if "permission" in msg or "not permitted" in msg:
            print("[BLE] --> Fix: sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))")
        elif "adapter" in msg or "not found" in msg:
            print("[BLE] --> Fix: sudo systemctl start bluetooth && sudo hciconfig hci0 up")


# Singleton — starts background thread on import
ble_receiver = BLEReceiver()
