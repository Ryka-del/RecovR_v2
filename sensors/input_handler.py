"""
InputHandler — keyboard stub for sensor input.

Grip simulation:
  Hold SPACE  → grip ramps up from 0 → 1 over ~0.8 s
  Release     → grip drops back to 0 over ~0.5 s
  Release while grip is in the green zone → shoot (detected in game handle_event)

Menu controls:
  ENTER / SPACE → "action"
  ESCAPE        → "back"
  UP / DOWN     → menu navigation
"""

import pygame


class InputHandler:

    RAMP_UP   = 1.25   # full grip in ~0.8 s
    RAMP_DOWN = 2.0    # drops to 0 in ~0.5 s

    _KEY_MAP = {
        "action": (pygame.K_SPACE, pygame.K_RETURN),
        "back":   (pygame.K_ESCAPE,),
        "up":     (pygame.K_UP,),
        "down":   (pygame.K_DOWN,),
        "left":   (pygame.K_LEFT,),
        "right":  (pygame.K_RIGHT,),
    }

    def __init__(self):
        self._grip = 0.0

    def update(self, dt):
        """Call once per frame (dt in seconds) to advance the grip ramp."""
        keys = pygame.key.get_pressed()
        if keys[pygame.K_SPACE]:
            self._grip = min(1.0, self._grip + self.RAMP_UP * dt)
        else:
            self._grip = 0.0

    def was_pressed(self, event, action):
        """True if the action key was just pressed (KEYDOWN)."""
        if event.type != pygame.KEYDOWN:
            return False
        return event.key in self._KEY_MAP.get(action, ())

    def was_released(self, event, action):
        """True if the action key was just released (KEYUP)."""
        if event.type != pygame.KEYUP:
            return False
        return event.key in self._KEY_MAP.get(action, ())

    def get_state(self):
        """Return current sensor state dict.
        Tilt is driven by arrow keys for keyboard testing:
          LEFT / RIGHT → tilt_x  -1.0 / +1.0
          UP   / DOWN  → tilt_y  -1.0 / +1.0
        """
        keys   = pygame.key.get_pressed()
        tilt_x = (-1.0 if keys[pygame.K_LEFT]  else 0.0) + (1.0 if keys[pygame.K_RIGHT] else 0.0)
        tilt_y = (-1.0 if keys[pygame.K_UP]    else 0.0) + (1.0 if keys[pygame.K_DOWN]  else 0.0)
        return {
            "grip":    self._grip,
            "tilt_x":  max(-1.0, min(1.0, tilt_x)),
            "tilt_y":  max(-1.0, min(1.0, tilt_y)),
            "fingers": [False] * 5,
        }


input_handler = InputHandler()
