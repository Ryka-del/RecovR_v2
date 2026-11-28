# RecovRWE — Setup & Requirements Guide

## System Requirements

| Requirement | Details |
|-------------|---------|
| Deployment target | Raspberry Pi 4 Model B, Raspberry Pi OS / Debian 13 (Trixie) |
| Development | Windows 10/11 (keyboard test mode, no LED output) |
| Python | 3.10 or newer |
| Displays | Therapist: 800 × 480 touchscreen. Patient: second monitor |
| Bluetooth | Built-in or USB BLE adapter (for the wireless controller) |
| Audio | Raspberry Pi 3.5 mm audio jack |

The app runs as three processes (session broker, therapist screen, patient screen), all started by `python3 main.py`. With only one monitor it still runs, without forced window placement.

---

## Python Dependencies

| Package | Needed for | Debian package |
|---------|------------|----------------|
| `pygame` (or `pygame-ce`) | Interface and games | `python3-pygame` |
| `bleak` 0.21+ | Bluetooth link to the controller | `python3-bleak` |
| `flask` 3.0+ | Local session broker between the two screens | `python3-flask` |
| `gpiozero` + `lgpio` | Optional LED fallback only (see LED Strip) | `python3-gpiozero`, `python3-lgpio` |

Everything else is part of the Python standard library.

`edge-tts` is **development only**. It is used by `generate_calibration_audio.py` to regenerate the English and Filipino calibration narration in `assets/audio/`; the running app never imports it.

**Do not install `pigpio`.** It is no longer used and has no installation candidate on Debian 13.

---

## Installation — Raspberry Pi

### 1. System packages

```bash
sudo apt update
sudo apt install -y bluetooth bluez bluez-tools x11-xserver-utils
sudo apt install -y python3-pygame python3-flask python3-bleak
sudo systemctl enable --now bluetooth
```

`x11-xserver-utils` provides `xrandr`, which is used to detect the two monitors.

Install with `apt`, because the autostart service runs the system Python (`/usr/bin/python3`) and Debian blocks system-wide `pip` installs. If `apt` has no candidate for one package, install just that package for the service user:

```bash
pip install --user --break-system-packages bleak
```

### 2. Bluetooth permission

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))
```

Power on the controller, then check that it is visible:

```bash
python3 tools/test_ble.py
```

You should see **`RecovR-Controller`** in the device list. (This tool's live readout expects older firmware; use it only to confirm the controller is found.)

### 3. Copy the project

Copy the whole project folder to the Pi:

```
<project folder>/
├── main.py            ← start here
├── database.py, backup_recovery.py, constants.py, audio.py, i18n.py, ui_cards.py
├── assets/            ← fonts, images and audio (bundled)
├── scenes/            ← therapist interface and calibration
├── games/
├── screens/
├── sensors/           ← Bluetooth and sensor input
├── hardware/          ← LED strip control
├── recovr/            ← patient screen, session broker, launcher
│   └── deploy/        ← autostart, shutdown and LED setup files
├── firmware/          ← controller sketches
├── tools/             ← diagnostics
└── recovr.db          ← created on first run
```

### 4. LED strip, autostart and shutdown

Follow [recovr/deploy/README.md](recovr/deploy/README.md). Before installing `recovr.service`, set `User=` and `WorkingDirectory=` to your account and project folder (the file's defaults are `pi` and `/home/pi/RecovRWE`).

The same guide covers setting the time zone. The Pi 4 has no battery-backed clock.

---

## Installation — Windows (development)

Install Python 3.10+ from [python.org](https://www.python.org/downloads/) and check **"Add Python to PATH"**. Then, in the project folder:

```
pip install pygame-ce bleak flask
python main.py
```

---

## Running the App

```bash
python3 main.py
```

On Windows use `python main.py`. Close it with the therapist screen's close button, or `Ctrl+C` in the terminal. On a Pi with autostart installed:

```bash
sudo systemctl start recovr
sudo systemctl stop recovr
journalctl -u recovr -f      # live log
```

Confirming **Close** on the therapist screen also shuts down the Pi if the shutdown files from the deploy guide are installed.

To check monitor detection:

```bash
python3 tools/diagnose_displays.py
```

---

## Database

- `recovr.db` is created automatically in the project folder on first run. No manual setup is needed.
- It stores therapist accounts, patients, calibration records and session history.
- Automatic backups are kept in `backups/`. If the database fails its integrity check at startup, the latest valid backup is restored.
- Both are excluded from Git, so each device keeps its own data.
- To reset all data, close the app, then delete `recovr.db` and the `backups/` folder.

---

## LED Strip

| Part | Details |
|------|---------|
| Strip | 12 V, powered from its own 12 V supply |
| Switch | IRLZ44N MOSFET |
| Control pin | Raspberry Pi **GPIO17** (BCM numbering), through a 330 Ω gate resistor |
| Ground | The Pi and the 12 V supply must share ground |
| Driver | Linux kernel `pwm-gpio` (`dtoverlay=pwm-gpio,gpio=17`) |

| App state | LED behaviour |
|-----------|---------------|
| No game running | Slow breathing fade |
| Game running | Steady light |
| Patient scores | Three flashes |
| App closed | Off |

Test it with RecovR stopped:

```bash
python3 -m hardware.led_feedback status   # expected: backend: kernel
python3 -m hardware.led_feedback test
python3 -m hardware.led_feedback off
```

The IRLZ44N is usually specified for a gate drive of 4 V or more and the Pi supplies 3.3 V, so check that it stays cool with your strip.

---

## Wireless Controller Hardware

The controller uses a **Seeed Studio XIAO ESP32-C3** and sends readings over Bluetooth every 20 ms.

### Components

| Component | Role | Connection |
|-----------|------|------------|
| FSR402 | Grip strength | MUX channel C4 |
| 5 flex sensors | Thumb, Index, Middle, Ring, Pinky bending | MUX channels C5–C9 (left-hand glove) |
| CD74HC4067 | 16-channel analog multiplexer | SIG → D0; S0–S3 → D1, D2, D3, D6; EN → GND |
| MPU6050 | Wrist tilt (acceleration X and Y) | I²C: SDA → D4, SCL → D5 |

No push button is wired.

For a **right-hand glove**, set `GLOVE_RIGHT_HAND` to `1` in the firmware before flashing. Thumb to Pinky then read from C9 down to C5.

### Pin Wiring (XIAO ESP32-C3)

| XIAO Pin | GPIO | Connected to |
|----------|------|--------------|
| D0 | GPIO2 | MUX SIG (ADC input) |
| D1 | GPIO3 | MUX S0 |
| D2 | GPIO4 | MUX S1 |
| D3 | GPIO5 | MUX S2 |
| D6 | GPIO21 | MUX S3 |
| D4 | GPIO6 | MPU6050 SDA |
| D5 | GPIO7 | MPU6050 SCL |
| 3V3 | — | MUX, MPU6050 and sensor power |
| GND | — | Common ground |

### Flashing the Firmware

1. Install [Arduino IDE](https://www.arduino.cc/en/software) 2.x.
2. Add the ESP32 board package (Preferences → Additional boards manager URLs):
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. Install these libraries through the Library Manager:
   - `Adafruit MPU6050`
   - `Adafruit Unified Sensor`

   Bluetooth support is included in the ESP32 board package.
4. Open `firmware/recovr_controller/recovr_controller.ino`, select the board **XIAO_ESP32C3**, and upload.
5. Open the Serial Monitor at 115200 baud. You should see `[BLE] Advertising as 'RecovR-Controller'`, followed by sensor readings.

### Sensors Used by Each Game

| Game | Grip | Flex (5) | Wrist X | Wrist Y |
|------|:----:|:--------:|:-------:|:-------:|
| Basketball | ✓ | | | |
| Lemonade | ✓ | | | |
| Tile Rush | | ✓ | | |
| Whack-a-Mole | | ✓ | | |
| Apple Catching | | | ✓ | |
| Key and Lock | | | ✓ | |
| Steady Aim | | | ✓ | ✓ |
| Toy Factory | ✓ | | ✓ | ✓ |
| Purrfect Feast | ✓ | | ✓ | |
| Garden Wonders | ✓ | ✓ | ✓ | ✓ |

The app falls back to keyboard controls when the controller is off or out of range.

### Calibration Checks

Grip and flex calibrations are checked after three trials and reported as **Passed**, **No movement**, **Inconsistent movement** or **Unreliable reading**. A failed check repeats once automatically, then offers **Retry Again** or **Continue Anyway**. Wrist (MPU6050) calibration is not checked.

The limits are provisional and are set in `scenes/calibration_validation.py`. To collect readings for tuning:

```bash
journalctl -u recovr -f | grep "\[cal\]"
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `No module named 'pygame'`, `'bleak'` or `'flask'` | Install it as described under Installation |
| `Package 'pigpio' has no installation candidate` | Expected on Debian 13; `pigpio` is not needed |
| Controller not detected | Check it is powered on, then run `python3 tools/test_ble.py` |
| Bluetooth permission error | Repeat the `setcap` command above |
| Controller disconnects often | Keep it within 5–10 m of the Pi, without metal or walls in between |
| LED status is not `backend: kernel` | Check `systemctl status recovr-led` and the `config.txt` overlay |
| LED fade flickers | Confirm the log shows `[led] kernel PWM`, not a `[led] WARNING` |
| LED stays on after a forced kill | `python3 -m hardware.led_feedback off` |
| Window on the wrong monitor | Run `python3 tools/diagnose_displays.py` |
| Autostart cannot open the display | See "If the windows don't appear" in the deploy guide |
| Text appears as squares | Check that `assets/font/` is complete |
| No sound | Check the Pi's audio output is set to the 3.5 mm jack |
| Touchscreen taps do not register | Check that the operating system detects the touchscreen |
