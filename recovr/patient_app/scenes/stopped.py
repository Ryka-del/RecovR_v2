"""
"Game Stopped" notice -- shown on the patient monitor when the therapist presses
the red STOP. The game is HELD (paused, not destroyed) while the therapist
decides whether to resume it or end the session. Theme-aware (follows
constants.get_theme()), in the same minimal style as the other patient screens.
"""

from recovr.patient_app.scenes.common import PALETTE, fill_bg, draw_lines


class StoppedScreen:

    def draw(self, surface):
        fill_bg(surface)
        draw_lines(surface, [
            ("GAME STOPPED", 60, PALETTE["bad"]),
            ("", 14, PALETTE["muted"]),
            ("The game has been paused by the therapist.", 30, PALETTE["text"]),
            ("Please wait -- your game may resume shortly.", 28, PALETTE["muted"]),
        ], top_frac=0.46)
