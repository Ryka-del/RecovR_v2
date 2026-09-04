"""
Waiting screen -- the patient's resting state between activities.

Reflects (read-only) whatever the therapist has configured so the patient can
see a session is being prepared. It never lets the patient change anything.
"""

from recovr.patient_app.scenes.common import PALETTE, fill_bg, draw_lines


class WaitingScreen:

    def draw(self, surface, snapshot, connected, note=None):
        fill_bg(surface)

        cfg = (snapshot or {}).get("config", {}) if snapshot else {}
        status = (snapshot or {}).get("status", "") if snapshot else ""

        lines = [("Waiting for your therapist", 44, PALETTE["text"])]

        if not connected or snapshot is None:
            lines.append(("connecting to therapist station...", 24, PALETTE["warn"]))
        else:
            patient = cfg.get("patient_name") or "-"
            game = cfg.get("selected_game") or "-"
            diff = cfg.get("difficulty") or "-"
            lines.append(("", 12, PALETTE["muted"]))
            lines.append((f"Patient   {patient}", 26, PALETTE["muted"]))
            lines.append((f"Activity  {game}   ({diff})", 26, PALETTE["muted"]))
            if status:
                lines.append((f"status: {status.lower()}", 22, PALETTE["accent"]))

        if note:
            lines.append(("", 12, PALETTE["muted"]))
            lines.append((note, 24, PALETTE["warn"]))

        draw_lines(surface, lines, top_frac=0.46)
