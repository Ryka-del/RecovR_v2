"""
Monitor discovery + patient/therapist display assignment.

Best-effort physical-monitor detection so the launcher can place:
  * the patient Pygame window on one display  (via SDL display index)
  * the therapist browser on another          (via window x/y coordinates)

Windows : ctypes EnumDisplayMonitors / GetMonitorInfoW  (authoritative).
Other   : Raspberry Pi / xrandr detection is a TODO -- falls back to pygame
          desktop sizes, then to a single logical 1920x1080 monitor.

Environment overrides (all optional):
    RECOVR_PATIENT_MONITOR   = "x,y,w,h"   force the patient monitor rect
    RECOVR_THERAPIST_MONITOR = "x,y,w,h"   force the therapist monitor rect
    RECOVR_PATIENT_DISPLAY   = "<int>"     force the SDL display index used for
                                           the patient Pygame window
    RECOVR_SINGLE_MONITOR    = "1"         dev/testing: no forced placement,
                                           everything on monitor 0
"""

import os
import sys
from dataclasses import dataclass


@dataclass
class Monitor:
    name: str
    x: int
    y: int
    w: int
    h: int
    primary: bool = False
    index: int = 0

    @property
    def pos(self) -> str:
        return f"{self.x},{self.y}"


_DEFAULT = Monitor("primary", 0, 0, 1920, 1080, primary=True, index=0)


# --------------------------------------------------------------------------
#  Detection
# --------------------------------------------------------------------------

def _detect_windows() -> list[Monitor]:
    """Enumerate physical monitors via the Win32 API (name, rect, primary)."""
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    MONITORINFOF_PRIMARY = 0x1
    user32 = ctypes.windll.user32

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
        ctypes.POINTER(RECT), wintypes.LPARAM)

    found: list[Monitor] = []

    def _cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            found.append(Monitor(
                name=mi.szDevice or f"display{len(found)}",
                x=r.left, y=r.top,
                w=r.right - r.left, h=r.bottom - r.top,
                primary=bool(mi.dwFlags & MONITORINFOF_PRIMARY),
            ))
        return 1

    # keep a ref to the trampoline for the duration of the call
    proc = MONITORENUMPROC(_cb)
    user32.EnumDisplayMonitors(0, 0, proc, 0)
    return found


def _detect_pygame() -> list[Monitor]:
    """Fallback: monitor count + sizes only (SDL gives no x/y offsets)."""
    try:
        import pygame
        if not pygame.display.get_init():
            pygame.display.init()
        sizes = pygame.display.get_desktop_sizes()
    except Exception:
        return []
    mons, ox = [], 0
    for i, (w, h) in enumerate(sizes):
        mons.append(Monitor(f"sdl{i}", ox, 0, w, h, primary=(i == 0)))
        ox += w        # assume side-by-side; offsets are approximate
    return mons


def detect_monitors() -> list[Monitor]:
    """Ordered list of physical monitors: primary first, then by x, then y.

    On Windows the returned index roughly corresponds to the SDL display index
    (primary == 0). It is best-effort; use RECOVR_PATIENT_DISPLAY to pin it.
    """
    if os.environ.get("RECOVR_SINGLE_MONITOR") == "1":
        mons = (_detect_windows() if sys.platform == "win32" else []) or _detect_pygame()
        # prefer the primary; fall back to the first enumerated / the default
        first = next((m for m in mons if m.primary), mons[0] if mons else _DEFAULT)
        first.index = 0
        return [first]

    mons: list[Monitor] = []
    if sys.platform == "win32":
        try:
            mons = _detect_windows()
        except Exception as exc:
            print(f"[recovr.monitors] Windows detection failed ({exc}); trying pygame")
    if not mons:
        # TODO: xrandr parsing for Raspberry Pi OS.
        mons = _detect_pygame()
    if not mons:
        return [_DEFAULT]

    mons.sort(key=lambda m: (not m.primary, m.x, m.y))
    for i, m in enumerate(mons):
        m.index = i
    return mons


# --------------------------------------------------------------------------
#  Overrides
# --------------------------------------------------------------------------

def _parse_rect(env_value: str, name: str) -> Monitor | None:
    try:
        x, y, w, h = (int(p) for p in env_value.split(","))
        return Monitor(name, x, y, w, h)
    except (ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------
#  Assignment helpers
# --------------------------------------------------------------------------

def patient_display_index() -> int:
    """SDL/pygame display index for the patient Pygame window.

    RECOVR_PATIENT_DISPLAY wins when valid; otherwise display 0 (primary), which
    is also the single-monitor fallback.
    """
    mons = detect_monitors()
    raw = os.environ.get("RECOVR_PATIENT_DISPLAY", "").strip()
    if raw:
        try:
            idx = int(raw)
            if 0 <= idx < max(1, len(mons)):
                return idx
        except ValueError:
            pass
    return 0


def _therapist_index(mons: list[Monitor]) -> int:
    p = patient_display_index()
    for i in range(len(mons)):
        if i != p:
            return i
    return 0


def therapist_monitor() -> Monitor:
    """Physical monitor (x/y/w/h) the therapist browser should occupy."""
    override = _parse_rect(os.environ.get("RECOVR_THERAPIST_MONITOR", ""), "therapist")
    if override:
        return override
    mons = detect_monitors()
    if len(mons) < 2:
        return mons[0] if mons else _DEFAULT
    return mons[_therapist_index(mons)]


def patient_monitor() -> Monitor:
    """Physical monitor for the patient window (informational / POS fallback)."""
    override = _parse_rect(os.environ.get("RECOVR_PATIENT_MONITOR", ""), "patient")
    if override:
        return override
    mons = detect_monitors()
    idx = patient_display_index()
    if 0 <= idx < len(mons):
        return mons[idx]
    return mons[0] if mons else _DEFAULT


def get_monitors() -> list[Monitor]:
    return detect_monitors()
