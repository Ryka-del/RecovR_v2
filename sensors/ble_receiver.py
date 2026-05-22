# =============================================================================
# sensors/ble_receiver.py
# =============================================================================
# Async BLE client that runs in a background daemon thread so it never
# blocks pygame's main loop.
#
# The ESP32 C3 controller advertises as "RecovR-Controller" and sends
# 9-byte little-endian packets via BLE GATT notifications:
#
#   Offset  Type    Field       Description
#   0-1     uint16  grip_raw    FSR402 ADC  0-4095
#   2-3     uint16  flex_raw    Flex sensor 0-4095
#   4       uint8   buttons     bit 0 = push button (C10)
#   5-6     int16   accel_x     MPU6050 accel X  (16384 LSB/g at ±2 g)
#   7-8     int16   accel_y     MPU6050 accel Y
#
# Usage:
#   from sensors.ble_receiver import ble_receiver
#   if ble_receiver.connected:
#       data = ble_receiver.get_latest()
#       # data keys: grip_raw, flex_raw, buttons, accel_x, accel_y
# =============================================================================

import asyncio
import struct
import threading
import logging

logger = logging.getLogger(__name__)

SERVICE_UUID = "12345678-1234-1234-1234-123456789abc"
CHAR_UUID    = "12345678-1234-1234-1234-123456789abd"
DEVICE_NAME  = "RecovR-Controller"

PACKET_FORMAT = "<HHBhh"                         # little-endian
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)   # 9 bytes

_RECONNECT_DELAY = 2.0   # seconds between reconnect attempts
_SCAN_TIMEOUT    = 8.0   # seconds to scan before retrying


class BLEReceiver:
    """Thread-safe BLE receiver for the RecovR controller."""

    def __init__(self):
        self._lock    = threading.Lock()
        self._latest  = {
            "grip_raw": 0,
            "flex_raw": 0,
            "buttons":  0,
            "accel_x":  0,
            "accel_y":  0,
        }
        self._connected = False

        # Daemon thread — dies automatically when the main process exits
        self._thread = threading.Thread(target=self._run, name="BLEReceiver", daemon=True)
        self._thread.start()

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    def get_latest(self) -> dict:
        """Return a copy of the most recently received sensor packet."""
        with self._lock:
            return dict(self._latest)

    # ── Background thread entry ───────────────────────────────────────────────

    def _run(self):
        """Entry point for the background thread; runs the asyncio event loop."""
        try:
            asyncio.run(self._ble_loop())
        except Exception as exc:
            logger.warning("BLE receiver thread exited: %s", exc)

    # ── Async BLE loop ────────────────────────────────────────────────────────

    async def _ble_loop(self):
        """Continuously scan → connect → subscribe → reconnect on disconnect."""
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            logger.warning(
                "bleak not installed — BLE controller unavailable. "
                "Run: pip install bleak"
            )
            return

        while True:
            try:
                logger.info("Scanning for '%s' ...", DEVICE_NAME)
                device = await BleakScanner.find_device_by_name(
                    DEVICE_NAME, timeout=_SCAN_TIMEOUT
                )
                if device is None:
                    logger.debug("'%s' not found, retrying in %.1f s", DEVICE_NAME, _RECONNECT_DELAY)
                    await asyncio.sleep(_RECONNECT_DELAY)
                    continue

                logger.info("Found '%s' (%s), connecting ...", DEVICE_NAME, device.address)
                async with BleakClient(device, timeout=10.0) as client:
                    self._connected = True
                    logger.info("Connected to %s", device.address)

                    await client.start_notify(CHAR_UUID, self._on_notification)

                    # Stay alive until disconnected
                    while client.is_connected:
                        await asyncio.sleep(0.05)

                self._connected = False
                logger.info("Disconnected from controller, reconnecting ...")
                await asyncio.sleep(_RECONNECT_DELAY)

            except Exception as exc:
                self._connected = False
                logger.warning("BLE error: %s — retrying in %.1f s", exc, _RECONNECT_DELAY)
                await asyncio.sleep(_RECONNECT_DELAY)

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


# Module-level singleton — imported by input_handler.py
ble_receiver = BLEReceiver()
