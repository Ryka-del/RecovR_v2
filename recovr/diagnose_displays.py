"""Display diagnostics for the RecovR dual-monitor setup.

    python -m recovr.diagnose_displays

Prints what the OS, SDL and RecovR each think the monitors are, then says which
placement strategy will be used and flags the two things that actually break
dual-monitor on a Raspberry Pi (Wayland, and a combined X screen).
"""

import os
import shutil
import subprocess
import sys


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception as exc:
        return f"({cmd[0]} unavailable: {exc})"


def main():
    print("=" * 68)
    print("RecovR display diagnostics")
    print("=" * 68)

    print(f"\nplatform            : {sys.platform}")
    for var in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY",
                "SDL_VIDEODRIVER", "RECOVR_SINGLE_MONITOR",
                "RECOVR_PATIENT_DISPLAY", "RECOVR_THERAPIST_DISPLAY"):
        print(f"{var:<20}: {os.environ.get(var) or '(unset)'}")

    session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

    # ---- 1. what the OS says -------------------------------------------
    if sys.platform.startswith("linux"):
        print("\n--- xrandr --listmonitors ---")
        if shutil.which("xrandr"):
            print(_run(["xrandr", "--listmonitors"]) or "(no output)")
        else:
            print("(xrandr not installed:  sudo apt install x11-xserver-utils)")

    # ---- 2. what SDL says ----------------------------------------------
    print("\n--- SDL / pygame ---")
    try:
        import pygame
        pygame.display.init()
        print(f"video driver        : {pygame.display.get_driver()}")
        print(f"num displays        : {pygame.display.get_num_displays()}")
        print(f"desktop sizes       : {pygame.display.get_desktop_sizes()}")
    except Exception as exc:
        print(f"(pygame display init failed: {exc})")

    # ---- 3. what RecovR resolves ---------------------------------------
    print("\n--- recovr.monitors ---")
    try:
        from recovr import monitors
        mons = monitors.detect_monitors()
        for m in mons:
            star = "*" if m.primary else " "
            print(f"  #{m.index}{star} {m.name:<12} {m.w}x{m.h} at ({m.x},{m.y})")
        p_idx = monitors.patient_display_index()
        t_mon = monitors.therapist_monitor()
        p_mon = monitors.patient_monitor()
        print(f"  patient   -> display #{p_idx}  {p_mon.w}x{p_mon.h}@({p_mon.x},{p_mon.y})")
        print(f"  therapist -> display #{t_mon.index}  {t_mon.w}x{t_mon.h}@({t_mon.x},{t_mon.y})")
        n = len(mons)
    except Exception as exc:
        print(f"(detection failed: {exc})")
        n = 0
        t_mon = p_mon = None

    # ---- 4. verdict -----------------------------------------------------
    print("\n" + "=" * 68)
    print("VERDICT")
    print("=" * 68)

    if wayland:
        print("\n  [X] You are on WAYLAND.")
        print("      SDL2 cannot place a window on a chosen output under Wayland --")
        print("      the compositor decides, so both windows land on one screen.")
        print("      Fix, either one:")
        print("        sudo raspi-config  ->  Advanced Options  ->  Wayland  ->  X11")
        print("        (reboot)")
        print("      or run RecovR with:")
        print("        SDL_VIDEODRIVER=x11 python main.py")
        return 1

    if n < 2:
        print(f"\n  [X] RecovR sees only {n} monitor(s), so it will NOT place windows.")
        print("      Both windows go to the default display -- your symptom.")
        if sys.platform.startswith("linux") and not shutil.which("xrandr"):
            print("      xrandr is missing; install it so RecovR can read the layout:")
            print("        sudo apt install x11-xserver-utils")
        else:
            print("      Check that both panels are active:  xrandr --listmonitors")
            print("      If they are, force the geometry by hand, e.g.:")
            print("        export RECOVR_PATIENT_MONITOR='0,0,1920,1080'")
            print("        export RECOVR_THERAPIST_MONITOR='1920,0,800,480'")
        return 1

    print("\n  [OK] Two monitors resolved with real offsets.")
    print("       The launcher will position each window absolutely:")
    if t_mon and p_mon:
        print(f"         patient    SDL_VIDEO_WINDOW_POS={p_mon.x},{p_mon.y}  size {p_mon.w}x{p_mon.h}")
        print(f"         therapist  SDL_VIDEO_WINDOW_POS={t_mon.x},{t_mon.y}  size {t_mon.w}x{t_mon.h}")
    print("\n       Start with:  python main.py")
    print("       Swap the screens with: RECOVR_PATIENT_DISPLAY=1 python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
