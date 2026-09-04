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
import os
import struct
import subprocess
import sys
import threading
import time

DEVICE_NAME   = "RecovR-Controller"   # primary name set in firmware
# Any BLE device whose name contains one of these strings (case-insensitive)
# will also be accepted — covers typos, spaces vs hyphens, etc.
_NAME_KEYWORDS = ["recovr", "fsr402", "esp32_fsr"]
SERVICE_UUID  = "12345678-1234-1234-1234-123456789abc"
CHAR_UUID     = "12345678-1234-1234-1234-123456789abd"

PACKET_FORMAT = "<HHBhh"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)   # 9 bytes

_SCAN_TIMEOUT    = 5.0
_RECONNECT_DELAY = 2.0
_ERROR_DELAY     = 3.0


class BLEReceiver:

    def __init__(self):
        self._lock      = threading.Lock()
        self._latest    = {
            "grip_raw": 0, "flex_raw": 0,
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
        #                   no_bleak / bluetooth_off / old_firmware / error
        self._stage        = "disabled" if not self._enabled else "scanning"
        self._detail       = ""      # short human-readable reason / device name
        self._dev_name     = ""      # last device we matched
        self._dev_addr     = ""
        self._scan_count   = 0
        self._seen_names   = []      # names from the most recent discover()
        self._last_packet  = 0.0     # time.monotonic() of the last notification

        t = threading.Thread(target=self._thread_main, name="BLEReceiver", daemon=True)
        t.start()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    def set_enabled(self, on: bool) -> None:
        """Enable/disable the scan+connect loop at runtime. Disabling drops any
        active connection within ~0.1 s; enabling resumes scanning within ~0.3 s."""
        self._enabled = bool(on)

    def rescan(self) -> None:
        """Force the loop to drop what it is doing and start a fresh scan.
        Used by the dashboard's controller indicator as a manual retry."""
        self._enabled = False
        self._stage = "scanning"
        self._detail = "restarting"

        def _resume():
            time.sleep(0.6)          # let the loop park + release cleanly
            self._first_run = True   # re-print the visible-device list
            self._enabled = True
        threading.Thread(target=_resume, daemon=True).start()

    def status(self) -> dict:
        """Snapshot of the connection state for the UI.

        stage       -- disabled | scanning | connecting | connected |
                       no_bleak | bluetooth_off | old_firmware | error
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

        while True:
            # ── Park while disabled: no scanning, no connection held ──────────
            if not self._enabled:
                self._connected = False
                if self._stage != "disabled":
                    self._stage, self._detail = "disabled", ""
                    self._scan_count = 0
                await asyncio.sleep(0.3)
                continue

            # First-run (once we are enabled): list every visible device so the
            # user can verify the ESP32 controller is powered on and advertising.
            if self._first_run:
                self._first_run = False
                print("[BLE] Scanning — visible BLE devices:")
                try:
                    devs = await BleakScanner.discover(timeout=4.0)
                    if devs:
                        for d in devs:
                            tag = "  <-- YOUR CONTROLLER" if (
                                d.name and any(kw in d.name.lower() for kw in _NAME_KEYWORDS)
                            ) else ""
                            print(f"[BLE]   {str(d.name):<32s}  {d.address}{tag}")
                    else:
                        print("[BLE]   (none found — is Bluetooth on?)")
                except Exception as exc:
                    print(f"[BLE]   Scan failed: {exc}")

            # ── Scan — compatible with all bleak versions ─────────────────────
            self._scan_count += 1
            self._stage = "scanning"
            self._detail = f"scan #{self._scan_count}"
            print(f"[BLE] Scan #{self._scan_count} — looking for '{DEVICE_NAME}'...")
            device = None
            try:
                devs = await BleakScanner.discover(timeout=8.0)
                named = [(d.name or "(no name)", d.address) for d in devs]
                self._seen_names = [n for n, _ in named]
                print(f"[BLE]   Devices found: {named if named else '(none)'}")

                def _is_controller(name):
                    if not name:
                        return False
                    n = name.lower()
                    return any(kw in n for kw in _NAME_KEYWORDS)

                device = next(
                    (d for d in devs if d.name == DEVICE_NAME), None
                ) or next(
                    (d for d in devs if _is_controller(d.name)), None
                )

            except Exception as exc:
                self._connected = False
                self._stage = self._classify_error(exc)
                self._detail = str(exc)[:60]
                print(f"[BLE] Scan error: {exc}")
                self._print_permission_hint(exc)
                await asyncio.sleep(_ERROR_DELAY)
                continue

            if device is None:
                # Not found this round — retry immediately
                self._detail = f"not advertising (scan #{self._scan_count})"
                continue

            # ── Connect ───────────────────────────────────────────────────────
            self._dev_name = device.name or "(no name)"
            self._dev_addr = device.address
            self._stage    = "connecting"
            self._detail   = self._dev_name
            print(f"[BLE] Found '{device.name}' ({device.address}). Connecting...")
            try:
                async with BleakClient(device, timeout=10.0) as client:
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
                        print("[BLE] The ESP32 is running old firmware — please flash firmware/controller_esp32c3.ino")
                        self._stage  = "old_firmware"
                        self._detail = "flash firmware/controller_esp32c3.ino"
                        # Keep connected flag False; retry after delay
                        await asyncio.sleep(5.0)
                    else:
                        self._connected = True
                        self._stage  = "connected"
                        self._detail = self._dev_name
                        print("[BLE] Controller connected!  Sensor data is live.")
                        await client.start_notify(CHAR_UUID, self._on_notification)
                        # Hold the connection until it drops OR this receiver is
                        # disabled (session handed the controller to the other
                        # process). Leaving the `async with` disconnects cleanly.
                        while client.is_connected and self._enabled:
                            await asyncio.sleep(0.1)

                self._connected = False
                if self._enabled:
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
            if self._enabled:
                self._reset_adapter()
                await asyncio.sleep(_RECONNECT_DELAY)

    # ── Notification handler ──────────────────────────────────────────────────

    def _on_notification(self, sender, data: bytearray):
        if len(data) < PACKET_SIZE:
            return
        self._last_packet = time.monotonic()
        vals = struct.unpack_from(PACKET_FORMAT, data)
        with self._lock:
            self._latest = {
                "grip_raw": vals[0],
                "flex_raw": vals[1],
                "buttons":  vals[2],
                "accel_x":  vals[3],
                "accel_y":  vals[4],
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
