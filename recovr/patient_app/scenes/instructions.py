"""
Instructions / get-ready screen -- shown for a few seconds after the therapist
presses Start, before the game takes over. The countdown is driven by
patient_main (it freezes if the therapist pauses during the lead-in).
"""

from recovr.patient_app.scenes.common import PALETTE, fill_bg, draw_lines


class InstructionsScreen:

    def __init__(self):
        self._cfg = {}

    def set_context(self, cfg: dict):
        self._cfg = dict(cfg or {})

    def draw(self, surface, seconds_left: float):
        fill_bg(surface)
        game = self._cfg.get("selected_game") or "Activity"
        diff = self._cfg.get("difficulty") or "Easy"
        draw_lines(surface, [
            (game, 60, PALETTE["text"]),
            (f"Difficulty: {diff}", 28, PALETTE["muted"]),
            ("Press SPACE or tap when the target is GREEN", 24, PALETTE["muted"]),
            ("", 10, PALETTE["muted"]),
            (f"Starting in {max(0, int(seconds_left) + 1)}", 40, PALETTE["accent"]),
        ], top_frac=0.46)
