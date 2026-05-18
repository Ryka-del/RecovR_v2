"""
BaseScreen and ScreenManager — base classes for all game screens.
"""


class ScreenManager:
    """Holds a pending scene transition requested by a game."""

    def __init__(self):
        self._next = None
        self._data = {}

    def go_to(self, screen_name, **data):
        self._next = screen_name
        self._data = data

    def get_next(self):
        """Return (scene_name, data) and clear the pending transition."""
        n, d = self._next, self._data
        self._next = None
        self._data = {}
        return n, d


class BaseScreen:
    """Base class every game screen inherits from."""

    def __init__(self):
        self.manager = ScreenManager()

    def on_enter(self, data): pass
    def handle_event(self, event): pass
    def update(self, dt): pass
    def draw(self, surface): pass
