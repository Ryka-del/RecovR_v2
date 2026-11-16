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
