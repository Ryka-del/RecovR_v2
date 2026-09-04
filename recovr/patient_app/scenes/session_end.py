"""Session-end summary -- shown when a game finishes on its own."""

from recovr.patient_app.scenes.common import PALETTE, fill_bg, draw_lines


class SessionEndScreen:

    def draw(self, surface, result: dict):
        fill_bg(surface)
        result = result or {}
        score = result.get("score", 0)
        acc = result.get("accuracy")
        acc_txt = f"{acc * 100:.0f}%" if isinstance(acc, (int, float)) else "-"
        draw_lines(surface, [
            ("Session complete", 56, PALETTE["good"]),
            ("", 12, PALETTE["muted"]),
            (f"Score      {score}", 30, PALETTE["text"]),
            (f"Accuracy   {acc_txt}", 30, PALETTE["text"]),
            ("", 12, PALETTE["muted"]),
            ("Waiting for your therapist...", 24, PALETTE["muted"]),
        ], top_frac=0.46)
