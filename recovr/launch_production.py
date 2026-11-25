"""
RecovR production dual-monitor launcher.

Starts THREE processes:

    1. Session broker   -- python -m recovr.run_therapist   (headless Flask SessionStore; no browser)
    2. Therapist app    -- python main.py                    (the real app) on Monitor 2
    3. Patient window   -- python -m recovr.run_patient      (game host) on Monitor 1

The therapist app is the existing, unchanged main.py / scenes/ UI. With
RECOVR_DUAL_MONITOR=1 its "Start Session" hands the game to the patient window
and keeps the dashboard live with a Pause/Resume/Stop panel.

Run:  python -m recovr.launch_production
Stop: Ctrl+C / SIGTERM / SIGBREAK -- all three children are terminated, nothing orphaned.

Env:
    RECOVR_SINGLE_MONITOR=1   dev: run all three, no forced monitor placement
    RECOVR_PATIENT_DISPLAY / RECOVR_THERAPIST_DISPLAY   pin the SDL display indices

Pi autostart/autoshutdown: see recovr/deploy/ for the systemd unit + the
narrowly-scoped shutdown wrapper/sudoers rule. This script requests an OS
shutdown ONLY when main.py's confirmed "Yes, Close" dialog wrote the
recovr/.clean_exit sentinel (see _maybe_shutdown_pi() below) -- a crash,
Alt+F4, kill, or any other exit never does, so the Pi is never auto-shut-down
except through that one explicit, user-confirmed action.
"""

import json
import os
import sys
import time
import atexit
import signal
import subprocess
import urllib.request

from recovr.shared import protocol
from recovr import monitors
import backup_recovery
import database

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_PROCS: dict[str, subprocess.Popen] = {}
_SHUTTING_DOWN = False


def _wait_for_health(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    url = protocol.BASE_URL + protocol.EP_HEALTH
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


# How long a BLE ownership handoff may sit unconfirmed before this supervisor
# treats it as unsafe to leave running and shuts the whole app down for a
# clean restart. Deliberately longer than both the per-receiver lease
# watchdog's own _LEASE_TIMEOUT_SEC (sensors/ble_receiver.py, default 4s) and
# the therapist UI's own "handoff stuck" warning threshold
# (scenes/therapist_dashboard.py's _BLE_HANDOFF_TIMEOUT_MS, default 5s) --
# giving the normal, much faster paths every reasonable chance to resolve it
# on their own first. This is a LAST RESORT, not a normal operating path:
# the supervisor never selectively kills one child and grants the survivor
# ownership (that would require a way to PROVE the killed process's BLE
# connection was actually released before resuming, which is exactly the
# guarantee a bare timeout can't provide) -- it only ever shuts everything
# down, via the existing _shutdown() path, which already waits for every
# child to actually exit (OS-level process teardown is what genuinely
# guarantees any BLE handle it held is released). See
# recovr/shared/session_state.py's ble_generation docstring for why there is
# no "force" method any more.
_BLE_SUPERVISOR_SHUTDOWN_SEC = float(os.environ.get("RECOVR_BLE_SUPERVISOR_SHUTDOWN_SEC", "10.0"))


def _ble_handoff_stuck_too_long() -> bool:
    try:
        url = protocol.BASE_URL + protocol.EP_BLE_LEASE
        with urllib.request.urlopen(url, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # Broker unreachable -- can't determine handoff age from here either;
        # the existing proc.poll() check already catches a broker that
        # actually crashed, so this isn't this function's job to escalate.
        return False
    target = str(data.get("target", ""))
    pending = float(data.get("pending_seconds", 0.0) or 0.0)
    return bool(target) and pending > _BLE_SUPERVISOR_SHUTDOWN_SEC


def _spawn(args: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen(args, cwd=_ROOT, env=env)


def _raise_keyboard_interrupt(*_a):
    raise KeyboardInterrupt


def _shutdown(*_a):
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    all_confirmed_exited = True
    for name, proc in _PROCS.items():
        if proc.poll() is None:
            print(f"[launch] terminating '{name}' (pid {proc.pid}) ...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                # Graceful termination didn't finish in time -- escalate,
                # and verify the escalation itself actually worked instead
                # of assuming kill() alone is enough (SIGKILL is sent
                # immediately but the OS reaping it is a separate, still-
                # unconfirmed step without this wait).
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    print(f"[launch] WARNING: could not confirm '{name}' "
                          f"(pid {proc.pid}) actually exited.")
                    all_confirmed_exited = False
    if all_confirmed_exited:
        print("[launch] all children stopped.")
    else:
        print("[launch] shutdown finished, but not every child was confirmed "
              "exited -- see the WARNING(s) above.")


# The one and only place that may ever power off the Pi. This sentinel is
# written by main.py's _confirmed_exit() -- ONLY on the confirmed "Yes,
# Close" dialog action -- and nowhere else: not a crash, not a kill, not
# Alt+F4, not a failed save/cleanup, not a startup failure. Checked here,
# AFTER _shutdown() has already cleanly torn down all 3 children, so a
# shutdown request (if any) is the very last thing this process does.
_CLEAN_EXIT_SENTINEL = os.path.join(_ROOT, "recovr", ".clean_exit")
_SHUTDOWN_CMD = "/usr/local/bin/recovr-shutdown"   # see recovr/deploy/


def _maybe_shutdown_pi():
    if not os.path.exists(_CLEAN_EXIT_SENTINEL):
        return
    try:
        os.remove(_CLEAN_EXIT_SENTINEL)   # consume once -- never re-trigger on the next boot
    except OSError:
        pass
    print("[launch] confirmed clean exit -- requesting Pi shutdown.")
    try:
        subprocess.run(["sudo", _SHUTDOWN_CMD], check=False, timeout=10)
    except Exception as exc:
        print(f"[launch] shutdown request failed ({exc}); Pi stays running.")


# Right at boot, X11 can report graphical.target reached before both physical
# monitors have actually finished EDID/hotplug negotiation -- a single,
# immediate detect_monitors() call can then see only 1 screen and silently
# fall back to single-monitor placement for the whole session. Retrying for a
# few seconds (instead of a fixed startup sleep before this script even
# starts) means a boot where both monitors are already ready proceeds
# immediately, and only a genuinely slow boot waits the longer tail --
# either way it's the actual minimum needed, not a padded guess.
_MONITOR_RETRY_ATTEMPTS = 8
_MONITOR_RETRY_DELAY_SEC = 1.0


def _detect_monitors_with_retry():
    for attempt in range(1, _MONITOR_RETRY_ATTEMPTS + 1):
        mons = monitors.detect_monitors()
        if len(mons) >= 2:
            if attempt > 1:
                print(f"[launch] both monitors detected on attempt {attempt}.")
            return mons
        if attempt < _MONITOR_RETRY_ATTEMPTS:
            time.sleep(_MONITOR_RETRY_DELAY_SEC)
    print(f"[launch] only {len(mons)} monitor(s) detected after "
          f"{_MONITOR_RETRY_ATTEMPTS} attempts -- proceeding anyway.")
    return mons


def main():
    base_env = os.environ.copy()
    base_env["RECOVR_DUAL_MONITOR"] = "1"
    # The therapist and patient processes each hold a BLEReceiver, but only one
    # may own the controller at a time, tracked by the broker's ble_owner field
    # (default "therapist" -- see recovr/shared/session_state.py). The patient
    # must stay parked until the therapist explicitly hands it over (Start
    # Session), so it starts BLE-disabled; the therapist searches for the
    # controller immediately on launch, so this is overridden back off for it
    # alone below (RECOVR_BLE_START_DISABLED=0).
    base_env["RECOVR_BLE_START_DISABLED"] = "1"

    atexit.register(_shutdown)
    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _raise_keyboard_interrupt)
            except (ValueError, OSError):
                pass

    # 1. Session broker (headless)
    print(f"[launch] starting session broker on {protocol.BASE_URL} ...")
    broker_env = base_env.copy()
    _PROCS["broker"] = _spawn([sys.executable, "-m", "recovr.run_therapist"], broker_env)
    if not _wait_for_health(protocol.HEALTH_TIMEOUT_SEC):
        print("[launch] broker did not become healthy -- aborting.")
        _shutdown()
        sys.exit(1)
    print("[launch] broker is up.")

    # Database integrity check + crash/power-loss recovery -- run exactly
    # ONCE, here, before either the therapist or patient process opens the
    # database for real use. This is the only point in the whole startup
    # sequence with that guarantee: the broker above never touches SQLite
    # (its SessionStore is pure in-memory), so doing it here instead of in
    # either UI process means there is no race between two processes each
    # trying to recover the same file at once.
    result = backup_recovery.check_and_recover_startup()
    if result == "corrupt_no_backup":
        print("[launch] WARNING: recovr.db failed its integrity check and no "
              "valid backup was found. The corrupt file was left in place "
              "(not deleted) for manual inspection -- see "
              f"{backup_recovery.BACKUP_DIR}\\backup_log.txt. Proceeding "
              "anyway; expect database errors until this is resolved.")
    elif result == "recovered":
        print("[launch] recovr.db failed its integrity check -- restored "
              "from the most recent valid backup. Any changes made after "
              "that backup are lost; see backup_log.txt for details.")
    try:
        _recovered = database.Database()
        n = _recovered.recover_interrupted_checkpoints()
        _recovered.close()
        if n:
            print(f"[launch] recovered {n} session(s) left unfinished by a "
                  "previous crash/power loss -- recorded as 'interrupted'.")
    except Exception as e:
        print(f"[launch] WARNING: could not check for interrupted sessions: {e}")

    # monitor assignment
    single = os.environ.get("RECOVR_SINGLE_MONITOR") == "1"
    mons = _detect_monitors_with_retry() if not single else monitors.detect_monitors()
    # Explicit geometry always wins: if the user has pinned both rects by hand,
    # honour them even when auto-detection could only find one screen.
    forced = bool(os.environ.get("RECOVR_PATIENT_MONITOR")
                  and os.environ.get("RECOVR_THERAPIST_MONITOR"))
    dual = (not single) and (len(mons) >= 2 or forced)
    if dual:
        if forced and len(mons) < 2:
            print("[launch] using RECOVR_PATIENT_MONITOR / RECOVR_THERAPIST_MONITOR overrides")
        else:
            print("[launch] monitors: " + ", ".join(
                f"#{m.index} {m.w}x{m.h}@({m.x},{m.y}){'*' if m.primary else ''}" for m in mons))
    else:
        why = "RECOVR_SINGLE_MONITOR=1" if single else f"{len(mons)} monitor(s) detected"
        print(f"[launch] single-monitor mode ({why}) -- no forced window placement")
        if not single:
            print("[launch] run 'python tools/diagnose_displays.py' to see why")

    # 2. Therapist app (real main.py) on Monitor 2
    ther_env = base_env.copy()
    ther_env["RECOVR_ROLE"] = "therapist"   # main.py: run the scene loop, not the launcher
    # Therapist owns the controller by default (ble_owner starts "therapist") --
    # search for it immediately on launch, not just once a patient is selected.
    ther_env["RECOVR_BLE_START_DISABLED"] = "0"
    if dual:
        t_mon = monitors.therapist_monitor()
        ther_env["RECOVR_THERAPIST_DISPLAY"] = str(t_mon.index)
        # Absolute geometry as well as the display index: on Linux/X11 both
        # panels usually live in ONE combined X screen, where a display index
        # cannot separate them but an x/y offset can.
        ther_env["RECOVR_THERAPIST_POS"]  = f"{t_mon.x},{t_mon.y}"
        ther_env["RECOVR_THERAPIST_SIZE"] = f"{t_mon.w}x{t_mon.h}"
        print(f"[launch] therapist app (main.py) -> display #{t_mon.index} "
              f"{t_mon.w}x{t_mon.h}@({t_mon.x},{t_mon.y})")
    print("[launch] starting therapist app ...")
    _PROCS["therapist"] = _spawn([sys.executable, "main.py"], ther_env)

    # 3. Patient window on Monitor 1 -- borderless full-screen on that display
    pat_env = base_env.copy()
    pat_env.setdefault("RECOVR_FULLSCREEN", "1")
    if dual:
        p_idx = monitors.patient_display_index()
        p_mon = monitors.patient_monitor()
        pat_env["RECOVR_PATIENT_DISPLAY"] = str(p_idx)
        pat_env["RECOVR_PATIENT_POS"]  = f"{p_mon.x},{p_mon.y}"
        pat_env["RECOVR_PATIENT_SIZE"] = f"{p_mon.w}x{p_mon.h}"
        print(f"[launch] patient window -> display #{p_idx} "
              f"{p_mon.w}x{p_mon.h}@({p_mon.x},{p_mon.y})")
    print("[launch] starting patient window ...")
    _PROCS["patient"] = _spawn([sys.executable, "-m", "recovr.run_patient"], pat_env)

    try:
        while True:
            for name, proc in _PROCS.items():
                if proc.poll() is not None:
                    print(f"[launch] '{name}' exited (code {proc.returncode}) -- shutting down.")
                    raise KeyboardInterrupt
            if _ble_handoff_stuck_too_long():
                print(f"[launch] BLE ownership handoff unconfirmed past "
                      f"{_BLE_SUPERVISOR_SHUTDOWN_SEC:.0f}s -- shutting down for safety "
                      "rather than risk two processes holding the controller at once. "
                      "Restart once the unresponsive process/controller issue is resolved.")
                raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
        _maybe_shutdown_pi()
    print("[launch] done.")


if __name__ == "__main__":
    main()
