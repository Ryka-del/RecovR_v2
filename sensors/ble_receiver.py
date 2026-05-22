# =============================================================================
# sensors/ble_receiver.py
# =============================================================================
# Auto-connecting BLE client for the RecovR wireless controller.
# Runs in a background daemon thread — never blocks pygame.
#
# On startup it prints ALL visible BLE devices so you can verify the ESP32
# is advertising. Once found, it connects automatically and reconnects
# whenever the controller is powered back on.
# =============================================================================

import asyncio
import struct
import threading
import time

DEVICE_NAME   = "ESP32_FSR"
SERVICE_UUID  = "12345678-1234-1234-1234-123456789abc"
CHAR_UUID     = "12345678-1234-1234-1234-123456789abd"

PACKET_FORMAT = "<HHBhh"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)   # 9 bytes

_SCAN_TIMEOUT    = 5.0
_RECONNECT_DELAY = 1.0
_ERROR_DELAY     = 3.0


class BLEReceiver:

    def __init__(self):
        self._lock      = threading.Lock()
        self._latest    = {
            "grip_raw": 0, "flex_raw": 0,
            "buttons":  0, "accel_x":  0, "accel_y": 0,
        }
        self._connected = False
        self._first_run = True   # flag for the initial device-list scan

        t = threading.Thread(target=self._thread_main, name="BLEReceiver", daemon=True)
        t.start()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    def get_latest(self) -> dict:
        with self._lock:
            return dict(self._latest)

    # ── Thread — restarts the event loop if it ever crashes ──────────────────

    def _thread_main(self):
        while True:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._ble_loop())
            except Exception as exc:
                self._connected = False
                print(f"[BLE] Loop crashed ({type(exc).__name__}: {exc}). Restarting in {_ERROR_DELAY}s...")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
            self._connected = False
            time.sleep(_ERROR_DELAY)

    # ── Main async BLE loop ───────────────────────────────────────────────────

    async def _ble_loop(self):
        # -- import bleak --
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            print("[BLE] ERROR: bleak is not installed.")
            print("[BLE]        Run:  pip install bleak")
            return

        # -- first-run: list every visible BLE device -------------------------
        if self._first_run:
            self._first_run = False
            print("[BLE] Starting initial scan — listing all visible BLE devices...")
            try:
                all_devs = await BleakScanner.discover(timeout=4.0)
                if all_devs:
                    for d in all_devs:
                        tag = "  <-- YOUR CONTROLLER" if (
                            d.name and d.name.lower() == DEVICE_NAME.lower()
                        ) else ""
                        print(f"[BLE]   {str(d.name):<32s}  {d.address}{tag}")
                else:
                    print("[BLE]   (no devices found — is Bluetooth enabled?)")
            except Exception as exc:
                print(f"[BLE]   Scan failed: {exc}")
                self._print_permission_hint(exc)

        # -- main scan/connect loop -------------------------------------------
        print(f"[BLE] Scanning for '{DEVICE_NAME}' — will connect automatically when found...")

        while True:
            device = None
            try:
                # Primary: exact name match
                device = await BleakScanner.find_device_by_name(
                    DEVICE_NAME, timeout=_SCAN_TIMEOUT
                )

                # Fallback: case-insensitive name search
                if device is None:
                    all_devs = await BleakScanner.discover(timeout=3.0)
                    device = next(
                        (d for d in all_devs
                         if d.name and d.name.lower() == DEVICE_NAME.lower()),
                        None
                    )

            except Exception as exc:
                self._connected = False
                print(f"[BLE] Scan error: {type(exc).__name__}: {exc}")
                self._print_permission_hint(exc)
                await asyncio.sleep(_ERROR_DELAY)
                continue

            if device is None:
                # Not found yet — loop immediately, no delay
                continue

            # -- connect --
            print(f"[BLE] Found '{device.name}' ({device.address}). Connecting...")
            try:
                async with BleakClient(device, timeout=10.0) as client:
                    self._connected = True
                    print("[BLE] Controller connected!  Sensor data is now live.")
                    await client.start_notify(CHAR_UUID, self._on_notification)
                    while client.is_connected:
                        await asyncio.sleep(0.1)

                self._connected = False
                print("[BLE] Controller disconnected.  Scanning again...")
                await asyncio.sleep(_RECONNECT_DELAY)

            except Exception as exc:
                self._connected = False
                print(f"[BLE] Connection failed: {type(exc).__name__}: {exc}")
                await asyncio.sleep(_ERROR_DELAY)

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

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _print_permission_hint(exc):
        msg = str(exc).lower()
        if "permission" in msg or "operation not permitted" in msg or "access" in msg:
            print("[BLE] --> Permission error. Fix with ONE of these commands:")
            print("[BLE]     sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))")
            print("[BLE]     OR run the app with:  sudo python3 main.py")
        elif "adapter" in msg or "not found" in msg or "no such" in msg:
            print("[BLE] --> Bluetooth adapter not found. Run:")
            print("[BLE]     sudo systemctl start bluetooth")
            print("[BLE]     sudo hciconfig hci0 up")


# Singleton — starts the background thread immediately on import
ble_receiver = BLEReceiver()
