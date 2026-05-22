# RecovRWE — Setup & Requirements Guide

## System Requirements

| Requirement | Minimum |
|-------------|---------|
| Operating System | Raspberry Pi OS (Bookworm/Bullseye) **or** Windows 10/11 |
| Python | 3.8 or higher |
| Screen Resolution | 1920 × 1080 recommended (app scales to other resolutions) |
| Bluetooth | Built-in or USB BLE adapter (for wireless controller) |

> **Raspberry Pi 4 is the primary deployment target.** The app also runs on Windows for development; DPI-awareness and window positioning code is Windows-specific.

---

## Python Dependencies

```
pygame>=2.0      # game engine and UI
bleak>=0.21      # BLE communication with the RecovR wireless controller
```

All other dependencies (`sqlite3`, `hashlib`, `datetime`, `asyncio`, `struct`, `threading`) are part of the Python standard library.

All other dependencies (`sqlite3`, `hashlib`, `datetime`, `math`, `sys`, `os`, `random`, `time`, `ctypes`) are part of the Python standard library.

---

## Installation Steps

### 0. Raspberry Pi — Bluetooth & BLE setup *(skip on Windows)*

Enable and start the Bluetooth stack:

```bash
sudo apt-get update
sudo apt-get install -y bluetooth bluez bluez-tools
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
```

Install Python dependencies:

```bash
pip install pygame bleak
```

Grant the Python process permission to use BLE without root (one-time setup):

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))
```

> If `setcap` is unavailable, run the app with `sudo python3 main.py` as an alternative.

Verify BLE is working and the controller is visible:

```bash
# Scan for the controller (power it on first)
python3 -c "
import asyncio
from bleak import BleakScanner
async def scan():
    devices = await BleakScanner.discover(timeout=5)
    for d in devices:
        print(d.name, d.address)
asyncio.run(scan())
"
```

You should see **`RecovR-Controller`** in the list.

---

### 1. Install Python

Download and install Python 3.8+ from [python.org](https://www.python.org/downloads/).

During installation on Windows, check **"Add Python to PATH"**.

Verify your installation:
```
python --version
```

### 2. Install pygame

Open a terminal (Command Prompt or PowerShell) and run:

```
pip install pygame
```

Or if you have multiple Python versions:
```
python -m pip install pygame
```

### 3. Download / Copy the Project

Copy the entire `RecovRWE` folder to your device. The folder structure should look like:

```
RecovRWE/
├── main.py
├── database.py
├── constants.py
├── audio.py
├── requirements.md
├── recovr.db          ← auto-created on first run
├── assets/
│   ├── font/          ← all font files (bundled)
│   └── audio/         ← sound effects and music (bundled)
├── scenes/
├── games/
├── sensors/
└── screens/
```

All fonts and audio files are bundled in the `assets/` folder — **no additional downloads needed**.

---

## Running the App

Open a terminal, navigate to the `RecovRWE` folder, and run:

```
python main.py
```

### Windows shortcut

You can also create a `.bat` file in the project folder:

```bat
@echo off
python main.py
```

Double-click it to launch the app.

---

## Database

- The database file (`recovr.db`) is automatically created in the project folder the first time the app runs.
- **No manual database setup is required.**
- Therapist accounts, patients, calibration records, and session history are all stored in this file.
- To reset all data, delete `recovr.db` and restart the app.

---

## Wireless Controller Hardware

The RecovR controller uses a **Seeed Studio XIAO-ESP32 C3** as the BLE transmitter.

### Components

| Component | Role | Connection |
|-----------|------|-----------|
| FSR402 | Grip strength sensor | MUX channel C5 |
| Flex Sensor 2.2 | Finger flexion sensor | MUX channel C0 |
| Push Button | Action button | MUX channel C10 (pull-down to GND) |
| CD74HC4067 | 16-channel analog MUX | Signal → D0 (GPIO2); S0-S3 → D1-D3, D6 |
| MPU6050 | Wrist tilt (accel X/Y) | I2C: SDA → D4 (GPIO6), SCL → D5 (GPIO7) |

### Pin Wiring (XIAO-ESP32 C3)

| XIAO Pin | GPIO | Connected to |
|----------|------|-------------|
| D0 | GPIO2 | MUX SIG (ADC input) |
| D1 | GPIO3 | MUX S0 |
| D2 | GPIO4 | MUX S1 |
| D3 | GPIO5 | MUX S2 |
| D6 | GPIO21 | MUX S3 |
| D4 | GPIO6 | MPU6050 SDA |
| D5 | GPIO7 | MPU6050 SCL |
| 3V3 | — | VCC for MUX, MPU6050, sensors |
| GND | — | Common ground |

### Flashing the Firmware

1. Install [Arduino IDE](https://www.arduino.cc/en/software) (v2.x recommended).
2. Add the ESP32 board package: Preferences → Additional boards URL →
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. Install these libraries via **Sketch → Include Library → Manage Libraries**:
   - `NimBLE-Arduino` by h2zero
   - `Adafruit MPU6050` by Adafruit
   - `Adafruit Unified Sensor` by Adafruit
4. Open `firmware/controller_esp32c3.ino`, select board **"XIAO_ESP32C3"**, flash.
5. Open Serial Monitor (115200 baud) — you should see sensor readings every 20 ms and
   `[BLE] Advertising as 'RecovR-Controller'`.

### Sensor–Game Mapping

| Sensor | `get_state()` key | Game |
|--------|------------------|------|
| FSR402 | `state["grip"]` | Basketball (squeeze to shoot) |
| Flex Sensor | `state["tilt_y"]` + `state["fingers"]` | Piano Tiles + Calibration |
| MPU6050 accel X | `state["tilt_x"]` | Steady Aim (wrist rotation) |
| Push Button | Synthetic `K_RETURN` event | General action |

The app automatically falls back to keyboard controls when the BLE controller is off or out of range — no configuration needed.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'pygame'` | Run `pip install pygame` |
| `ModuleNotFoundError: No module named 'bleak'` | Run `pip install bleak` |
| Controller not detected (no BLE) | Ensure controller is powered on; run the BLE scan command above to verify it's visible |
| BLE disconnects frequently | Keep controller within 5–10 m of the Raspberry Pi; avoid walls/metal between them |
| `BluetoothPermissionError` on RPi | Run `sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))` |
| App window does not appear / appears on wrong monitor | Ensure `SDL_VIDEO_WINDOW_POS` is not overridden by another app |
| Fonts not loading / text appears as squares | Ensure the `assets/font/` folder is present and contains all `.ttf` files |
| Audio not playing | pygame's mixer requires a working audio device; the app continues without sound if no device is found |
| Touchscreen taps not registering | The app handles touch via SDL `FINGERDOWN` events — ensure your touchscreen driver is recognized by SDL |
