"""
Shared drag-to-scroll / mouse-wheel handling for the therapist interface.

Follows the same rules as the Login page's profile grid
(scenes/login.py::_profile_scroll_handle_event):

  * Both mouse and finger events drive a drag, since a touchscreen may be
    reported as either one (or both) depending on the driver.
  * A press inside the scrollable area is only a PENDING tap. It becomes a
    scroll once it moves past a threshold; otherwise it fires on release.
  * The release position counts too: some touch drivers report only the down
    and up events of a swipe, with no motion events in between.
"""

import builtins

import pygame

# A touch reported as both a mouse and a finger event arrives as two presses
# within this window; they are one gesture, not two.
_DUPLICATE_PRESS_MS = 250


def _event_pos(event, size):
    """(source, phase, (x, y)) for a pointer event, else None."""
    t = event.type
    if t in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        if event.button != 1:
            return None
        phase = "down" if t == pygame.MOUSEBUTTONDOWN else "up"
    elif t == pygame.MOUSEMOTION:
        phase = "move"
    elif t in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
        phase = ("down" if t == pygame.FINGERDOWN else
                 "up" if t == pygame.FINGERUP else "move")
        return "finger", phase, (int(event.x * size[0]), int(event.y * size[1]))
    else:
        return None
    norm = getattr(builtins, "normalise_pos", lambda p: p)
    return "mouse", phase, norm(event.pos)


class DragScroller:
    """Tracks one gesture at a time. The caller owns the scroll offset."""

    def __init__(self):
        self.cancel()

    def cancel(self):
        self._key          = None
        self._source       = None
        self._start_pos    = (0, 0)
        self._start_scroll = 0
        self._start_ms     = 0
        self._dragging     = False

    def handle(self, event, *, key, viewport, scroll, max_scroll, size,
               wheel_step, threshold, wheel_anywhere=True,
               capture_unscrollable=False):
        """Returns (consumed, new_scroll, tap_pos).

        `key` identifies the scroll area, so a gesture never carries over to a
        different one. `tap_pos` is set when a press was released without
        turning into a scroll; the caller then treats it as a normal tap.
        With nothing to scroll, events pass through untouched unless
        `capture_unscrollable` is set.
        """
        if self._key is not None and self._key != key:
            self.cancel()

        def clamp(v):
            return max(0, min(max_scroll, v))

        if event.type == pygame.MOUSEWHEEL:
            if max_scroll <= 0:
                return False, scroll, None
            if not wheel_anywhere:
                norm = getattr(builtins, "normalise_pos", lambda p: p)
                if not viewport.collidepoint(norm(pygame.mouse.get_pos())):
                    return False, scroll, None
            return True, clamp(scroll - event.y * wheel_step), None

        info = _event_pos(event, size)
        if info is None:
            return False, scroll, None
        source, phase, pos = info

        if phase == "down":
            if (self._key is not None and source != self._source
                    and pygame.time.get_ticks() - self._start_ms < _DUPLICATE_PRESS_MS):
                # Same physical touch reported twice. Finger coordinates are
                # the more reliable pair on a touchscreen, so they take over.
                if source == "finger":
                    self._source, self._start_pos = source, pos
                return True, scroll, None
            self.cancel()
            if not viewport.collidepoint(pos):
                return False, scroll, None
            if max_scroll <= 0 and not capture_unscrollable:
                return False, scroll, None
            self._key          = key
            self._source       = source
            self._start_pos    = pos
            self._start_scroll = scroll
            self._start_ms     = pygame.time.get_ticks()
            return True, scroll, None

        if self._key is None:
            return False, scroll, None
        if source != self._source:
            return True, scroll, None

        dy = pos[1] - self._start_pos[1]
        if abs(dy) > threshold or abs(pos[0] - self._start_pos[0]) > threshold:
            self._dragging = True
        new_scroll = clamp(self._start_scroll - dy) if self._dragging else scroll

        if phase == "move":
            return True, new_scroll, None

        tap_pos = None if self._dragging else self._start_pos
        self.cancel()
        return True, new_scroll, tap_pos
