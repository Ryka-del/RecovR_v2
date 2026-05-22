"""
InputHandler — dual-mode sensor bridge.

BLE mode (when RecovR-Controller is connected via Bluetooth):
  FSR402      → state["grip"]        0.0–1.0
  Flex Sensor → state["tilt_y"]      0.0–1.0  (also used by calibration window)
  Flex Sensor → state["fingers"]     edge-detected, all 5 lanes fire together
  MPU6050 X   → state["tilt_x"]     −1.0–1.0  (wrist left/right rotation)
  Push Button → synthetic pygame KEYDOWN K_RETURN (rising edge only)

Keyboard fallback (when BLE is disconnected or bleak not installed):
  SPACE       → grip ramps up; release drops to 0
  LEFT/RIGHT  → tilt_x  −1.0 / +1.0
  UP/DOWN     → tilt_y  −1.0 / +1.0
  A/S/D/F/G   → finger lanes handled by individual games (events, not get_state)

All game files and the calibration window use this module via the singleton
`input_handler` — the interface is unchanged so no game code needs editing.
"""

import pygame

# ── BLE receiver (optional) ──────────────────────────────────────────────────
try:
    from sensors.ble_receiver import ble_receiver as _ble
except Exception:
    _ble = None


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class InputHandler:

    RAMP_UP      = 1.25    # grip ramp-up rate in keyboard mode (full in ~0.8 s)
    FLEX_THRESH  = 0.30    # flex normalised value above which a finger press fires

    _KEY_MAP = {
        "action": (pygame.K_SPACE, pygame.K_RETURN),
        "back":   (pygame.K_ESCAPE,),
        "up":     (pygame.K_UP,),
        "down":   (pygame.K_DOWN,),
        "left":   (pygame.K_LEFT,),
        "right":  (pygame.K_RIGHT,),
    }

    def __init__(self):
        # Sensor state (shared between update() and get_state())
        self._grip    = 0.0
        self._tilt_x  = 0.0
        self._tilt_y  = 0.0
        self._fingers      = [False] * 5   # current frame finger state
        self._prev_fingers = [False] * 5   # previous frame (for edge detection)

        # Button edge detection
        self._prev_button = False

    # ── Public: called once per frame by game_scene.py ───────────────────────

    def update(self, dt):
        """Advance sensor state. dt is in seconds."""
        if _ble is not None and _ble.connected:
            self._update_ble()
        else:
            self._update_keyboard(dt)

    # ── Public: polled by games and calibration_window ───────────────────────

    def get_state(self):
        """Return current sensor readings as a normalised dict.

        Keys:
            grip    float 0–1      (squeeze strength)
            tilt_x  float −1–1     (wrist left/right, or left/right arrows)
            tilt_y  float −1–1     (flex bend, or up/down arrows)
            fingers list[bool]×5   (True on rising edge of flex press, all lanes)
        """
        return {
            "grip":    self._grip,
            "tilt_x":  self._tilt_x,
            "tilt_y":  self._tilt_y,
            "fingers": list(self._fingers),
        }

    # ── Public: event-based action detection (unchanged API) ─────────────────

    def was_pressed(self, event, action):
        """True if the action key was just pressed (KEYDOWN).
        The push button also triggers 'action' via a synthetic KEYDOWN K_RETURN
        injected in update(), so this method handles both without changes.
        """
        if event.type != pygame.KEYDOWN:
            return False
        return event.key in self._KEY_MAP.get(action, ())

    def was_released(self, event, action):
        """True if the action key was just released (KEYUP)."""
        if event.type != pygame.KEYUP:
            return False
        return event.key in self._KEY_MAP.get(action, ())

    # ── Public: connection status ─────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """True when the BLE controller is connected."""
        return _ble is not None and _ble.connected

    # ── BLE update ───────────────────────────────────────────────────────────

    def _update_ble(self):
        raw = _ble.get_latest()

        # FSR402 (C5) → grip  0.0–1.0
        self._grip = raw["grip_raw"] / 4095.0

        # MPU6050 accel X → tilt_x  ±1.0  (±2 g range = ±16384 LSB)
        self._tilt_x = _clamp(raw["accel_x"] / 16384.0, -1.0, 1.0)

        # Flex Sensor (C0) → tilt_y  0.0–1.0
        # tilt_y is also what the calibration window reads for Finger Flexion
        flex = raw["flex_raw"] / 4095.0
        self._tilt_y = flex

        # Flex → fingers: edge-detected rising edge fires all 5 lanes at once
        self._prev_fingers = list(self._fingers)
        was_bent = any(self._prev_fingers)
        is_bent  = flex > self.FLEX_THRESH
        # True only on the frame the sensor crosses the threshold (rising edge)
        self._fingers = [is_bent and not was_bent] * 5

        # Push button (C10, pull-down) → synthetic pygame KEYDOWN on rising edge
        btn_now = bool(raw["buttons"] & 0x01)
        if btn_now and not self._prev_button:
            try:
                pygame.event.post(pygame.event.Event(
                    pygame.KEYDOWN,
                    key=pygame.K_RETURN,
                    unicode="\r",
                    mod=0,
                    scancode=0,
                ))
            except Exception:
                pass  # pygame may not be fully initialised during startup
        self._prev_button = btn_now

    # ── Keyboard fallback update ──────────────────────────────────────────────

    def _update_keyboard(self, dt):
        keys = pygame.key.get_pressed()

        # SPACE held → ramp grip up; release → drop to 0 instantly
        if keys[pygame.K_SPACE]:
            self._grip = min(1.0, self._grip + self.RAMP_UP * dt)
        else:
            self._grip = 0.0

        # Arrow keys → tilt (computed live but stored so get_state is consistent)
        self._tilt_x = (
            (-1.0 if keys[pygame.K_LEFT]  else 0.0) +
            ( 1.0 if keys[pygame.K_RIGHT] else 0.0)
        )
        self._tilt_y = (
            (-1.0 if keys[pygame.K_UP]   else 0.0) +
            ( 1.0 if keys[pygame.K_DOWN] else 0.0)
        )

        # Fingers remain all-False in keyboard mode; piano tiles uses KEYDOWN events
        self._prev_fingers = list(self._fingers)
        self._fingers      = [False] * 5


# Module-level singleton used by all game files and calibration_window
input_handler = InputHandler()
