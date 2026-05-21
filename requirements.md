# RecovRWE — Setup & Requirements Guide

## System Requirements

| Requirement | Minimum |
|-------------|---------|
| Operating System | Windows 10 / 11 (primary platform) |
| Python | 3.8 or higher |
| Screen Resolution | 1920 × 1080 recommended (app scales to other resolutions) |

> **Note:** The app runs on macOS and Linux but is optimized for Windows. DPI-awareness and window positioning code is Windows-specific; on other platforms the window may not anchor to position (0, 0) correctly.

---

## Python Dependencies

The only external library required is **pygame**:

```
pygame>=2.0
```

All other dependencies (`sqlite3`, `hashlib`, `datetime`, `math`, `sys`, `os`, `random`, `time`, `ctypes`) are part of the Python standard library.

---

## Installation Steps

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

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'pygame'` | Run `pip install pygame` |
| App window does not appear / appears on wrong monitor | Ensure `SDL_VIDEO_WINDOW_POS` is not overridden by another app; try running as Administrator |
| Fonts not loading / text appears as squares | Ensure the `assets/font/` folder is present and contains all `.ttf` files |
| Audio not playing | pygame's mixer requires a working audio device; the app continues without sound if no device is found |
| Touchscreen taps not registering | The app handles touch via SDL `FINGERDOWN` events — ensure your touchscreen driver is recognized by SDL |
