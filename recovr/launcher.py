"""
RecovR launcher -- starts the two halves of the system as SEPARATE processes:

    1. Flask therapist server   (python -m recovr.run_therapist)
    2. Patient Pygame app       (python -m recovr.run_patient)

then opens the therapist control page in a browser.

Separate processes (not threads) so a crash on one side cannot take down the
other, and so each is placed on its own physical monitor:

    patient Pygame window -> monitor via SDL display index (RECOVR_PATIENT_DISPLAY)
    therapist browser     -> monitor via window x/y coordinates

Run:
    python -m recovr.launcher

Stop: Ctrl+C (or send SIGTERM / SIGBREAK) -- both child processes are always
terminated via the shutdown handler, so nothing is left orphaned. (The browser
is user-managed and is never killed by the launcher.)
"""

import os
import sys
import time
import atexit
import shutil
import signal
import subprocess
import webbrowser
import urllib.request

from recovr.shared import protocol
from recovr import monitors

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Chromium-family browsers honour --window-position / --start-fullscreen.
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Child processes, tracked module-level so signal/atexit handlers can reach them.
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


def _spawn(module: str, env: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", module], cwd=_ROOT, env=env)


def _find_chromium() -> str | None:
    for name in ("chrome", "msedge", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    for path in _CHROME_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def _open_therapist_browser(mon) -> None:
    """Open the control page on the therapist monitor.

    Chromium-family browser: positioned + fullscreen on that monitor.
    Otherwise: default browser + a note telling the operator to move it.
    The browser is NOT tracked in _PROCS -- it is the therapist's to manage.
    """
    url = protocol.BASE_URL
    browser = _find_chromium()
    if browser:
        # A dedicated user-data-dir guarantees a fresh instance that actually
        # honours --window-position / --start-fullscreen (an already-running
        # Chrome/Edge ignores them). Overridable via RECOVR_BROWSER_PROFILE.
        profile = os.environ.get(
            "RECOVR_BROWSER_PROFILE",
            os.path.join(os.path.expandvars(r"%LOCALAPPDATA%"), "RecovR", "therapist-browser"),
        )
        args = [
            browser, "--new-window",
            f"--user-data-dir={profile}",
            f"--window-position={mon.x},{mon.y}",
            "--window-size=1280,900",
            "--start-fullscreen",
            url,
        ]
        try:
            # Detached: an independent window the therapist manages, exactly like
            # the default-browser path. The launcher never tracks or closes it.
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            subprocess.Popen(args, cwd=_ROOT, creationflags=flags,
                             close_fds=True, start_new_session=(os.name != "nt"))
            print(f"[launcher] therapist browser -> monitor #{mon.index} "
                  f"@({mon.x},{mon.y}) [{os.path.basename(browser)}]")
            return
        except Exception as exc:
            print(f"[launcher] chromium launch failed ({exc}); using default browser")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("[launcher] Therapist browser opened using the default browser. "
          "Move it to monitor 2 if necessary.")


def _raise_keyboard_interrupt(*_a):
    raise KeyboardInterrupt


def _shutdown(*_a):
    """Terminate every child process. Idempotent; safe from a signal handler."""
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    for name, proc in _PROCS.items():
        if proc.poll() is None:
            print(f"[launcher] terminating '{name}' (pid {proc.pid}) ...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    print("[launcher] all children stopped.")


def main():
    base_env = os.environ.copy()

    atexit.register(_shutdown)
    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _raise_keyboard_interrupt)
            except (ValueError, OSError):
                pass  # not all signals are settable on every platform

    # 1. Therapist server
    print(f"[launcher] starting Flask server on {protocol.BASE_URL} ...")
    _PROCS["server"] = _spawn("recovr.run_therapist", base_env)

    if not _wait_for_health(protocol.HEALTH_TIMEOUT_SEC):
        print("[launcher] server did not become healthy in time -- aborting.")
        _shutdown()
        sys.exit(1)
    print("[launcher] server is up.")

    # --- monitor assignment ---------------------------------------------
    single = os.environ.get("RECOVR_SINGLE_MONITOR") == "1"
    mons = monitors.detect_monitors()
    dual = (not single) and len(mons) >= 2
    if dual:
        print("[launcher] monitors: " + ", ".join(
            f"#{m.index} {m.w}x{m.h}@({m.x},{m.y}){'*' if m.primary else ''}" for m in mons))
    else:
        why = "RECOVR_SINGLE_MONITOR=1" if single else f"{len(mons)} monitor(s) detected"
        print(f"[launcher] single-monitor mode ({why}) -- no forced window placement")

    # 2. Patient app
    patient_env = base_env.copy()
    if dual:
        p_idx = monitors.patient_display_index()
        patient_env["RECOVR_PATIENT_DISPLAY"] = str(p_idx)
        patient_env.setdefault("RECOVR_PATIENT_SIZE", "1280x720")
        print(f"[launcher] patient Pygame window -> display #{p_idx}")
    else:
        # unchanged development defaults
        patient_env.setdefault("RECOVR_PATIENT_POS", "60,60")
        patient_env.setdefault("RECOVR_PATIENT_SIZE", "1280x720")
    print("[launcher] starting patient app ...")
    _PROCS["patient"] = _spawn("recovr.run_patient", patient_env)

    # 3. Therapist browser
    if dual:
        _open_therapist_browser(monitors.therapist_monitor())
    else:
        print("[launcher] opening therapist control page (default browser) ...")
        try:
            webbrowser.open(protocol.BASE_URL)
        except Exception:
            print(f"[launcher] open a browser at {protocol.BASE_URL}")

    try:
        while True:
            for name, proc in _PROCS.items():
                if proc.poll() is not None:
                    print(f"[launcher] '{name}' exited (code {proc.returncode}) -- shutting down.")
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
    print("[launcher] done.")


if __name__ == "__main__":
    main()
