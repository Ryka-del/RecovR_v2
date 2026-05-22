"""
RecovR BLE Controller — Connection Test
========================================
Run this script on the Raspberry Pi to check whether it can see and
connect to the RecovR-Controller (ESP32 C3).

Usage:
    python3 sensors/test_ble.py

What it does:
    1. Lists every BLE device your Raspberry Pi can currently see
    2. Tries to connect to RecovR-Controller
    3. Prints live sensor values for 10 seconds if connection succeeds

If this works but the main app still shows "Not Connected", re-run main.py.
If this fails, follow the printed instructions to fix the issue.
"""

import asyncio
import struct
import sys

DEVICE_NAME   = "ESP32_FSR"
CHAR_UUID     = "12345678-1234-1234-1234-123456789abd"
PACKET_FORMAT = "<HHBhh"
PACKET_SIZE   = struct.calcsize(PACKET_FORMAT)


def on_data(sender, data: bytearray):
    if len(data) < PACKET_SIZE:
        return
    grip, flex, btn, ax, ay = struct.unpack_from(PACKET_FORMAT, data)
    print(f"  grip={grip:4d}  flex={flex:4d}  btn={btn}  ax={ax:6d}  ay={ay:6d}")


async def main():
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print("ERROR: bleak is not installed.")
        print("Run:   pip install bleak")
        sys.exit(1)

    # Step 1 — list all visible devices
    print("=" * 60)
    print("Step 1: Scanning for all visible BLE devices (5 s)...")
    print("=" * 60)
    devices = await BleakScanner.discover(timeout=5.0)

    if not devices:
        print("No BLE devices found at all.")
        print()
        print("Possible fixes:")
        print("  sudo systemctl start bluetooth")
        print("  sudo hciconfig hci0 up")
        print("  sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))")
        sys.exit(1)

    controller = None
    for d in devices:
        marker = "  <-- CONTROLLER FOUND" if (
            d.name and d.name.lower() == DEVICE_NAME.lower()
        ) else ""
        print(f"  {str(d.name):<35s}  {d.address}{marker}")
        if d.name and d.name.lower() == DEVICE_NAME.lower():
            controller = d

    print()

    if controller is None:
        print(f"'{DEVICE_NAME}' was NOT found in the scan.")
        print()
        print("Possible causes:")
        print("  - ESP32 is not powered on")
        print("  - ESP32 is out of Bluetooth range (try moving closer)")
        print("  - Firmware not flashed — flash firmware/controller_esp32c3.ino first")
        print("  - Device name mismatch — check Serial Monitor shows '[BLE] Advertising as RecovR-Controller'")
        sys.exit(1)

    # Step 2 — connect and stream data
    print("=" * 60)
    print(f"Step 2: Connecting to '{controller.name}' ({controller.address})...")
    print("=" * 60)

    try:
        async with BleakClient(controller, timeout=10.0) as client:
            print(f"Connected: {client.is_connected}")
            print()
            print("Streaming sensor data for 10 seconds...")
            print("  (squeeze FSR, bend flex sensor, tilt MPU6050 to see values change)")
            print()
            await client.start_notify(CHAR_UUID, on_data)
            await asyncio.sleep(10.0)
            print()
            print("Test complete — connection is working!")

    except Exception as exc:
        print(f"Connection failed: {type(exc).__name__}: {exc}")
        print()
        if "permission" in str(exc).lower() or "not permitted" in str(exc).lower():
            print("Fix: run this command then try again:")
            print("  sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))")


asyncio.run(main())
