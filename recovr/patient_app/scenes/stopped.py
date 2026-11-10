"""
"Game Stopped" notice -- shown on the patient monitor when the therapist presses
the red STOP. The game is HELD (paused, not destroyed) while the therapist
decides whether to resume it or end the session -- that hold/decide logic is
unchanged here; this screen only shows the patient a calm, reassuring notice
instead of narrating the therapist's still-open CONTINUE/BACK choice (it
never promises an automatic resume -- CONTINUE is the therapist's decision,
not something that happens on its own).
Theme-aware background (follows constants.get_theme()), same shared card
language as Take a Break / Game Paused (see ui_cards.py).
"""

from recovr.patient_app.scenes.common import fill_bg
from ui_cards import draw_state_card, STOP_ACCENT


class StoppedScreen:

    def draw(self, surface):
        fill_bg(surface)
        draw_state_card(
            surface,
            title="Game Stopped",
            subtitle="Please wait for your therapist's instructions.",
            accent=STOP_ACCENT,
            kind="stop",
            dim=False,
        )
