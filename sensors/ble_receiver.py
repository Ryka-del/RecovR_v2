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
import struct
import subprocess
import sys
import threading
import time

DEVICE_NAME   = "FSR402"
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

        t = threading.Thread(target=self._thread_main, name="BLEReceiver", daemon=True)
        t.start()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

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
            return

        # First-run: list every visible device so user can verify ESP32 is on
        if self._first_run:
            self._first_run = False
            print("[BLE] Scanning — visible BLE devices:")
            try:
                devs = await BleakScanner.discover(timeout=4.0)
                if devs:
                    for d in devs:
                        tag = "  <-- YOUR CONTROLLER" if (
                            d.name and d.name.lower() == DEVICE_NAME.lower()
                        ) else ""
                        print(f"[BLE]   {str(d.name):<32s}  {d.address}{tag}")
                else:
                    print("[BLE]   (none found — is Bluetooth on?)")
            except Exception as exc:
                print(f"[BLE]   Scan failed: {exc}")

        scan_count = 0
        while True:
            # ── Scan — compatible with all bleak versions ─────────────────────
            scan_count += 1
            print(f"[BLE] Scan #{scan_count} — looking for '{DEVICE_NAME}'...")
            device = None
            try:
                devs = await BleakScanner.discover(timeout=8.0)
                named = [(d.name or "(no name)", d.address) for d in devs]
                print(f"[BLE]   Devices found: {named if named else '(none)'}")

                device = next(
                    (d for d in devs if d.name == DEVICE_NAME), None
                )
                if device is None:
                    device = next(
                        (d for d in devs
                         if d.name and d.name.lower() == DEVICE_NAME.lower()),
                        None
                    )

            except Exception as exc:
                self._connected = False
                print(f"[BLE] Scan error: {exc}")
                self._print_permission_hint(exc)
                await asyncio.sleep(_ERROR_DELAY)
                continue

            if device is None:
                # Not found this round — retry immediately
                continue

            # ── Connect ───────────────────────────────────────────────────────
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
                        # Keep connected flag False; retry after delay
                        await asyncio.sleep(5.0)
                    else:
                        self._connected = True
                        print("[BLE] Controller connected!  Sensor data is live.")
                        await client.start_notify(CHAR_UUID, self._on_notification)
                        while client.is_connected:
                            await asyncio.sleep(0.1)

                self._connected = False
                print("[BLE] Controller disconnected. Scanning again...")

            except Exception as exc:
                self._connected = False
                print(f"[BLE] Connection error: {type(exc).__name__}: {exc}")

            # Reset adapter so BlueZ doesn't cache the old connection
            self._reset_adapter()
            await asyncio.sleep(_RECONNECT_DELAY)

    # ── Notification handler ──────────────────────────────────────────────────

    def _on_notification(self, sender, data: bytearray):
        if len(data) < PACKET_SIZE:
            return
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
    def _print_permission_hint(exc):
        msg = str(exc).lower()
        if "permission" in msg or "not permitted" in msg:
            print("[BLE] --> Fix: sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))")
        elif "adapter" in msg or "not found" in msg:
            print("[BLE] --> Fix: sudo systemctl start bluetooth && sudo hciconfig hci0 up")


# Singleton — starts background thread on import
ble_receiver = BLEReceiver()
