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
"""

import os
import sys
import time
import atexit
import signal
import subprocess
import urllib.request

from recovr.shared import protocol
from recovr import monitors

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


def _spawn(args: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen(args, cwd=_ROOT, env=env)


def _raise_keyboard_interrupt(*_a):
    raise KeyboardInterrupt


def _shutdown(*_a):
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    for name, proc in _PROCS.items():
        if proc.poll() is None:
            print(f"[launch] terminating '{name}' (pid {proc.pid}) ...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    print("[launch] all children stopped.")


def main():
    base_env = os.environ.copy()
    base_env["RECOVR_DUAL_MONITOR"] = "1"

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

    # monitor assignment
    single = os.environ.get("RECOVR_SINGLE_MONITOR") == "1"
    mons = monitors.detect_monitors()
    dual = (not single) and len(mons) >= 2
    if dual:
        print("[launch] monitors: " + ", ".join(
            f"#{m.index} {m.w}x{m.h}@({m.x},{m.y}){'*' if m.primary else ''}" for m in mons))
    else:
        why = "RECOVR_SINGLE_MONITOR=1" if single else f"{len(mons)} monitor(s) detected"
        print(f"[launch] single-monitor mode ({why}) -- no forced window placement")

    # 2. Therapist app (real main.py) on Monitor 2
    ther_env = base_env.copy()
    ther_env["RECOVR_ROLE"] = "therapist"   # main.py: run the scene loop, not the launcher
    if dual:
        t_mon = monitors.therapist_monitor()
        ther_env["RECOVR_THERAPIST_DISPLAY"] = str(t_mon.index)
        print(f"[launch] therapist app (main.py) -> display #{t_mon.index}")
    print("[launch] starting therapist app ...")
    _PROCS["therapist"] = _spawn([sys.executable, "main.py"], ther_env)

    # 3. Patient window on Monitor 1 -- borderless full-screen on that display
    pat_env = base_env.copy()
    pat_env.setdefault("RECOVR_FULLSCREEN", "1")
    if dual:
        p_idx = monitors.patient_display_index()
        pat_env["RECOVR_PATIENT_DISPLAY"] = str(p_idx)
        print(f"[launch] patient window -> display #{p_idx} (full-screen)")
    print("[launch] starting patient window ...")
    _PROCS["patient"] = _spawn([sys.executable, "-m", "recovr.run_patient"], pat_env)

    try:
        while True:
            for name, proc in _PROCS.items():
                if proc.poll() is not None:
                    print(f"[launch] '{name}' exited (code {proc.returncode}) -- shutting down.")
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
    print("[launch] done.")


if __name__ == "__main__":
    main()
