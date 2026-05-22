# =============================================================================
# sensors/ble_receiver.py
# =============================================================================
# Auto-connecting BLE client for the RecovR wireless controller.
#
# Runs in a background daemon thread so it never blocks pygame.
# Continuously scans for "RecovR-Controller". As soon as the ESP32 powers on
# and starts advertising, this receiver connects automatically within ~5 s.
# If the controller disconnects (powered off / out of range), it keeps scanning
# and reconnects automatically when the device is available again.
#
# BLE Packet (9 bytes, little-endian):
#   [0-1] uint16  grip_raw    FSR402 ADC  0-4095
#   [2-3] uint16  flex_raw    Flex sensor 0-4095
#   [4]   uint8   buttons     bit0 = push button
#   [5-6] int16   accel_x     MPU6050 accel X  (16384 LSB/g)
#   [7-8] int16   accel_y     MPU6050 accel Y
#
# Usage:
#   from sensors.ble_receiver import ble_receiver
#   ble_receiver.connected      -> bool
#   ble_receiver.get_latest()   -> dict of raw sensor values
# =============================================================================

import asyncio
import struct
import threading
import time

DEVICE_NAME   = "RecovR-Controller"
SERVICE_UUID  = "12345678-1234-1234-1234-123456789abc"
CHAR_UUID     = "12345678-1234-1234-1234-123456789abd"

PACKET_FORMAT = "<HHBhh"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)   # 9 bytes

_SCAN_TIMEOUT    = 5.0    # seconds per scan attempt
_RECONNECT_DELAY = 1.0    # seconds to wait after a clean disconnect
_ERROR_DELAY     = 3.0    # seconds to wait after an unexpected error


class BLEReceiver:

    def __init__(self):
        self._lock      = threading.Lock()
        self._latest    = {
            "grip_raw": 0,
            "flex_raw": 0,
            "buttons":  0,
            "accel_x":  0,
            "accel_y":  0,
        }
        self._connected = False

        # Daemon thread — exits automatically when the main process quits
        t = threading.Thread(target=self._thread_main, name="BLEReceiver", daemon=True)
        t.start()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    def get_latest(self) -> dict:
        with self._lock:
            return dict(self._latest)

    # ── Thread entry — restarts the event loop if it ever crashes ─────────────

    def _thread_main(self):
        while True:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._ble_loop())
            except Exception as exc:
                print(f"[BLE] Event loop crashed: {exc}. Restarting in {_ERROR_DELAY}s...")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
            self._connected = False
            time.sleep(_ERROR_DELAY)

    # ── Main async loop — scan → connect → notify → repeat ───────────────────

    async def _ble_loop(self):
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            print("[BLE] 'bleak' is not installed.")
            print("[BLE] Run:  pip install bleak")
            print("[BLE] BLE controller will be unavailable until bleak is installed.")
            return   # thread_main will restart this after _ERROR_DELAY

        print(f"[BLE] Auto-scan started. Waiting for '{DEVICE_NAME}' to power on...")

        while True:
            # ── Scan ─────────────────────────────────────────────────────────
            device = None
            try:
                device = await BleakScanner.find_device_by_name(
                    DEVICE_NAME, timeout=_SCAN_TIMEOUT
                )
            except Exception as exc:
                print(f"[BLE] Scan error: {exc}. Retrying...")
                await asyncio.sleep(_ERROR_DELAY)
                continue

            if device is None:
                # Not found this round — loop back and scan again immediately
                continue

            # ── Connect ───────────────────────────────────────────────────────
            print(f"[BLE] Found '{DEVICE_NAME}' ({device.address}). Connecting...")
            try:
                async with BleakClient(device, timeout=10.0) as client:
                    self._connected = True
                    print("[BLE] Controller connected! Sensor data is live.")

                    await client.start_notify(CHAR_UUID, self._on_notification)

                    # Hold the connection open until the device disconnects
                    while client.is_connected:
                        await asyncio.sleep(0.1)

                # Clean disconnect (powered off / out of range)
                self._connected = False
                print(f"[BLE] Controller disconnected. Scanning again...")
                await asyncio.sleep(_RECONNECT_DELAY)

            except Exception as exc:
                self._connected = False
                print(f"[BLE] Connection error: {exc}. Retrying in {_ERROR_DELAY}s...")
                await asyncio.sleep(_ERROR_DELAY)

    # ── Notification handler ──────────────────────────────────────────────────

    def _on_notification(self, sender, data: bytearray):
        if len(data) < PACKET_SIZE:
            return
        grip_raw, flex_raw, buttons, accel_x, accel_y = struct.unpack_from(
            PACKET_FORMAT, data
        )
        with self._lock:
            self._latest = {
                "grip_raw": grip_raw,
                "flex_raw": flex_raw,
                "buttons":  buttons,
                "accel_x":  accel_x,
                "accel_y":  accel_y,
            }


# Singleton — created once when this module is first imported
ble_receiver = BLEReceiver()
