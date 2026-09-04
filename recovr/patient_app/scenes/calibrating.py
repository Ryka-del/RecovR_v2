"""
Calibration screen -- the patient side of the CALIBRATE command.

Prototype: a short progress bar while patient_main self-acks a stub result.
Production dual-monitor: the real CalibrationWindow runs on the therapist
monitor, so this window just shows a "please wait" state (frac=None) until the
therapist finishes.
"""

from recovr.patient_app.scenes.common import PALETTE, fill_bg, draw_lines, draw_progress


class CalibratingScreen:

    def draw(self, surface, frac=None, message=None):
        fill_bg(surface)
        draw_lines(surface, [
            ("Calibrating sensor", 48, PALETTE["text"]),
            (message or "Hold still and follow the on-screen guide", 24, PALETTE["muted"]),
        ], top_frac=0.42)
        if frac is not None:
            draw_progress(surface, frac, y_frac=0.6)
