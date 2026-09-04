"""Patient welcome splash -- shown briefly on start-up."""

from recovr.patient_app.scenes.common import PALETTE, fill_bg, draw_lines


class WelcomeScreen:

    def draw(self, surface):
        fill_bg(surface)
        draw_lines(surface, [
            ("RecovR", 96, PALETTE["text"]),
            ("Gamified Hand Rehabilitation", 30, PALETTE["muted"]),
        ], top_frac=0.5)
