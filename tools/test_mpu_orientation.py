"""
RecovR MPU6050 Orientation Diagnostic
======================================
Live accel_x / accel_y readout for physically determining which axis
corresponds to which real-world wrist movement on THIS controller's actual
mounting orientation. Written for Part A.4 of the calibration investigation
-- do NOT assume axis meaning from this script's output alone; this just
shows you the numbers so a person can observe them during the physical
test below and report back which axis moved for which motion.

Usage:
    python3 tools/test_mpu_orientation.py

What it does:
    Connects to the controller (same way tools/test_ble.py does, but using
    the CURRENT 19-byte packet format -- test_ble.py's 9-byte format is
    stale) and prints a continuously live-updating line showing:
        - accel_x, accel_y: raw int16 counts (16384 LSB/g at +/-2g)
        - the same values as a fraction of 1g (what input_handler.py's
          tilt_x actually is before clamping)
        - a simple arrow indicating which direction each axis is currently
          leaning (+ / -), so you don't have to do the sign math yourself
          while your hands are busy holding the controller

Physical test procedure (do this with the controller resting flat/neutral
first, note the resting numbers, then):
    1. Tilt the controller LEFT  -- watch which value changes, and whether
       it goes positive or negative.
    2. Tilt the controller RIGHT -- same.
    3. Tilt the controller UP (wrist extension)   -- same.
    4. Tilt the controller DOWN (wrist flexion)    -- same.

Report back, for each of the 4 motions: which axis (X or Y) moved, and in
which direction (+ or -). That's what's needed to finalize the axis-to-
movement mapping in A.4 -- this script does not decide or assume it.

Press Ctrl+C to stop.
"""

import asyncio
import struct
import sys

DEVICE_NAME   = "RecovR-Controller"
_NAME_KEYWORDS = ["recovr", "fsr402", "esp32_fsr"]
CHAR_UUID     = "12345678-1234-1234-1234-123456789abd"
# Must match sensors/ble_receiver.py's PACKET_FORMAT exactly -- grip_raw,
# flex_raw (legacy), 5x finger flex, buttons, accel_x, accel_y (19 bytes).
# tools/test_ble.py still uses the OLD 9-byte format; this one doesn't.
PACKET_FORMAT = "<HHHHHHHBhh"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)

_G_COUNTS = 16384.0   # LSB per g at +/-2g range (see firmware's SCALE constant)


def _arrow(v):
    if v > 300:
        return "+ (positive)"
    if v < -300:
        return "- (negative)"
    return "~0 (near rest)"


def on_data(sender, data: bytearray):
    if len(data) < PACKET_SIZE:
        return
    vals = struct.unpack_from(PACKET_FORMAT, data)
    ax, ay = vals[-2], vals[-1]
    gx, gy = ax / _G_COUNTS, ay / _G_COUNTS
    line = (f"accel_x={ax:6d} ({gx:+.2f}g) {_arrow(ax):16s}  |  "
            f"accel_y={ay:6d} ({gy:+.2f}g) {_arrow(ay):16s}")
    sys.stdout.write("\r" + line + "   ")
    sys.stdout.flush()


async def main():
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print("ERROR: bleak is not installed.  Run:  pip install bleak")
        sys.exit(1)

    print("Scanning for the controller...")

    def _match(d, adv):
        nm = d.name or (getattr(adv, "local_name", None) if adv else None)
        if not nm:
            return False
        nm = nm.lower()
        return nm == DEVICE_NAME.lower() or any(kw in nm for kw in _NAME_KEYWORDS)

    device = await BleakScanner.find_device_by_filter(_match, timeout=8.0)
    if device is None:
        print(f"'{DEVICE_NAME}' not found. Make sure it's powered on and in range.")
        sys.exit(1)

    print(f"Found '{device.name}' ({device.address}). Connecting...")
    async with BleakClient(device, timeout=10.0) as client:
        print("Connected. Hold the controller flat/neutral, note the resting")
        print("numbers below, then do the 4-direction tilt test described in")
        print("this script's own header comment. Press Ctrl+C to stop.\n")
        await client.start_notify(CHAR_UUID, on_data)
        try:
            while True:
                await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\nStopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
