# Raspberry Pi autostart / autoshutdown

Three files, installed once per Pi:

| File | Installs to | Purpose |
|---|---|---|
| `recovr.service` | `/etc/systemd/system/recovr.service` | Autostarts the app on boot, waits for the graphical session, bounded crash-restart |
| `recovr-shutdown` | `/usr/local/bin/recovr-shutdown` | The ONE command the app may ever run as root — `exec systemctl poweroff`, nothing else |
| `recovr-shutdown.sudoers` | `/etc/sudoers.d/recovr-shutdown` | Grants the service user NOPASSWD access to exactly that one command |

**Safety invariant: the Pi only ever auto-shuts-down after a successful,
explicit, user-confirmed exit** — the therapist UI's "Close RecovR? → Yes,
Close" dialog (`main.py`'s `_confirmed_exit()`). A crash, Alt+F4, `kill`,
a failed save, a failed cleanup, or a startup failure never triggers it —
see `recovr/launch_production.py`'s `_maybe_shutdown_pi()` for exactly how
that's enforced (it only checks for the sentinel *after* already cleanly
tearing down all 3 processes, and the sentinel is written in exactly one
place in the whole codebase).

## Install steps

1. **Edit the placeholders first** — `recovr.service`'s `User=`/
   `WorkingDirectory=` and `recovr-shutdown.sudoers`' username must match your
   actual Pi account and where you copied the `RecovRWE` folder (see
   `requirements.md`'s "Download / Copy the Project" step). The defaults
   assume user `pi`, folder `/home/pi/RecovRWE`.

2. **Install the shutdown wrapper** (root-owned, not writable by the service
   user):
   ```bash
   sudo install -m 0755 -o root -g root recovr-shutdown /usr/local/bin/recovr-shutdown
   ```

3. **Install the sudoers rule**:
   ```bash
   sudo visudo -c -f recovr-shutdown.sudoers   # validate syntax first
   sudo install -m 0440 recovr-shutdown.sudoers /etc/sudoers.d/recovr-shutdown
   ```

4. **Install and enable the systemd unit**:
   ```bash
   sudo install -m 0644 recovr.service /etc/systemd/system/recovr.service
   sudo systemctl daemon-reload
   sudo systemctl enable recovr.service
   sudo systemctl start recovr.service    # or just reboot
   ```

## If the windows don't appear (X11 permission)

A system-level systemd service launching a GUI app sometimes can't open the
display even with `Environment=DISPLAY=:0` set, because it isn't running in
the desktop user's actual login session and lacks that session's X11 auth
cookie. This is environment-dependent (differs by Raspberry Pi OS version/
desktop) and **cannot be verified from a Windows dev machine** — only on the
real Pi. If `journalctl -u recovr.service` shows a "cannot open display" /
"Authorization required" error:

1. Try adding `Environment=XAUTHORITY=/home/pi/.Xauthority` (adjust the user)
   to `recovr.service`'s `[Service]` section, then `daemon-reload` + restart.
2. If that still fails, run it as a **user** systemd service instead (under
   `~/.config/systemd/user/`, enabled with `systemctl --user enable` plus
   `loginctl enable-linger pi`) — a user service naturally inherits the
   desktop session's display/auth instead of needing it passed in by hand.

## Checking it

```bash
systemctl status recovr.service      # is it running? how many times has it restarted?
journalctl -u recovr.service -f      # live log (same [launch] prints as running it by hand)
```

To stop autostarting without uninstalling anything: `sudo systemctl disable recovr.service`.

## What this deliberately does NOT do

- Does not run the app as root, and does not grant it any sudo access beyond
  the single `recovr-shutdown` command above.
- Does not restart forever on a persistent crash (`StartLimitBurst=3` within
  `StartLimitIntervalSec=60` — after that, systemd gives up and the unit
  just stays stopped until someone looks at it).
- Does not touch calibration code, assets, or the database schema.

## LED strip (GPIO17, Debian 13 / Trixie)

The 12V strip's MOSFET stays on **GPIO17**. Brightness comes from the Linux
kernel's `pwm-gpio` driver, which needs no extra packages and does not use the
Pi's PWM hardware, so 3.5 mm audio is unaffected. `pigpio` is not used.

Install once, from this `recovr/deploy` folder:

1. Check that this kernel provides the driver (both should print information):
   ```bash
   modinfo pwm-gpio
   dtoverlay -h pwm-gpio
   ```
2. Add the overlay, then reboot:
   ```bash
   echo -e "\n[all]\ndtoverlay=pwm-gpio,gpio=17" | sudo tee -a /boot/firmware/config.txt
   ```
3. Install the boot-time permission setup (the service user must be in the
   `gpio` group):
   ```bash
   sudo install -m 0755 -o root -g root recovr-led-setup /usr/local/bin/recovr-led-setup
   sudo install -m 0644 recovr-led.service /etc/systemd/system/recovr-led.service
   # If recovr.service is already installed and edited, don't overwrite it:
   # run "sudo systemctl edit --full recovr" and copy in the new
   # After=, Wants= and ExecStopPost= lines. Otherwise edit User= and
   # WorkingDirectory= in the file first, then:
   sudo install -m 0644 recovr.service /etc/systemd/system/recovr.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now recovr-led.service
   sudo reboot
   ```

Test it, from the project folder with RecovR stopped
(`sudo systemctl stop recovr`):

```bash
python3 -m hardware.led_feedback status   # should report: backend: kernel
python3 -m hardware.led_feedback test     # fade, steady light, flashes, off
python3 -m hardware.led_feedback off
```

If the overlay or setup is missing, the app falls back to `gpiozero` software
PWM (Raspberry Pi OS packages `python3-gpiozero` and `python3-lgpio`), which can
flicker; the console shows a `[led] WARNING` line. With the overlay loaded, GPIO17 belongs to
the kernel driver and that fallback cannot take it, so a failed
`recovr-led.service` leaves the strip dark.

## Date/time accuracy (occasional wrong date/time reported in the field)

**Investigated, not fixed in code — this is an OS/hardware issue, not an
application bug.** A full search of this codebase found zero lines that set,
adjust, or override the system clock: every `datetime.now()` call anywhere
in `database.py`, `scenes/login.py`, `scenes/therapist_dashboard.py`, and
`recovr/patient_app/scenes/patient_dashboard.py` only *reads* the OS clock
(PIN-lockout timers, "now" displays) — none of them ever write to it.
`database.py`'s own stored timestamps (`played_at`, `calibrated_at`, etc.)
come from SQLite's `CURRENT_TIMESTAMP` (always UTC) and are converted to the
OS's configured local timezone only for display (`_utc_to_local()`,
`database.py`); that conversion is correct by construction regardless of
what the OS's timezone is actually set to — which is exactly why a
misconfigured OS timezone would make every displayed timestamp look "wrong"
even though nothing in the app is broken. Nothing in this repo's deploy
scripts (`recovr.service`, `recovr-shutdown`, this README) or
`requirements.md` sets up NTP, a timezone, or an RTC either — that step has
apparently never been done on this project's Pi image.

**This could not be verified against the actual deployed Raspberry Pi from
this Windows development machine** — the two checks below need to be run
directly on the Pi.

1. **Check the configured timezone and NTP state:**
   ```bash
   timedatectl status
   ```
   If "Time zone" is not `Asia/Manila`, every timestamp this app displays
   will be off by the UTC+8 offset — this alone would look exactly like
   "the date/time is wrong," even though storage is correct UTC. Fix with:
   ```bash
   sudo timedatectl set-timezone Asia/Manila
   sudo timedatectl set-ntp true
   ```

2. **Check whether a hardware RTC is present and recognized:**
   ```bash
   timedatectl status | grep "RTC time"
   ls /dev/rtc*
   ```
   The **Raspberry Pi 4 Model B has no onboard battery-backed RTC** — this
   is a hardware characteristic of the board itself, not a configuration
   that can be turned on. Without external RTC hardware added, the Pi can
   only know the correct time by: (a) syncing over NTP when it has
   internet access, or (b) `fake-hwclock` (enabled by default on Raspberry
   Pi OS), which saves the clock to disk on shutdown and restores it on
   the next boot — this is an **approximation that only prevents the clock
   from resetting to an absurd default**, not genuine timekeeping across a
   power-off period: if the Pi is unplugged for 3 days with no network,
   it will boot up still believing no time passed, until NTP can correct
   it.
   - If `/dev/rtc0` (or similar) already exists, an RTC module (or an SoC
     with one built in) is present and the OS is already using it —
     nothing further to investigate.
   - If it does **not** exist, genuine offline timekeeping across a full
     power loss requires adding an external I2C RTC module (e.g. a ~$3-5
     DS3231 board) and enabling it via `/boot/config.txt`
     (`dtoverlay=i2c-rtc,ds3231`) plus removing `fake-hwclock` per the
     module's own setup instructions. **This is a hardware addition, not a
     software fix** — do not expect accurate time across days of power loss
     without it.

Everything else asked for in this item is already satisfied by the existing
design once the two checks above are corrected: no application code
overrides the OS clock, and all stored timestamps are internally consistent
(always UTC in the database, converted once for display).
