"""
HTML views for the therapist. For the prototype there is a single control page;
real dashboard panels (patient list, history, analytics) get ported here later,
one at a time, from scenes/therapist_dashboard.py.
"""

from flask import Blueprint, render_template

from recovr.shared import protocol

bp = Blueprint("views", __name__)

# The seven RecovR games. Only "Gravity Catch" is integrated so far; selecting
# any other one leaves the patient app on its Waiting screen with a notice until
# that game is wired into recovr/patient_app/game_runner.py.
KNOWN_GAMES = [
    "Gravity Catch",
    "Basketball", "Piano Tiles", "Steady Aim", "Apple Catching",
    "Key and Lock", "Catch the Falling Object",
]
DIFFICULTIES = ["Easy", "Medium", "Hard"]


@bp.get("/")
def control():
    return render_template(
        "control.html",
        games=KNOWN_GAMES,
        difficulties=DIFFICULTIES,
        poll_ms=int(protocol.POLL_INTERVAL_SEC * 1000),
    )
