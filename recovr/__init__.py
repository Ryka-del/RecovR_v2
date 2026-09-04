"""
RecovR dual-monitor architecture package.

This package is the NEW architecture and is intentionally kept separate from the
existing single-process Pygame app (main.py / scenes/ / games/), which still runs
unchanged. Migration happens one game at a time.

Layout
------
    shared/         session state + command vocabulary + wire protocol (no I/O)
    comms/          Pygame-side HTTP client for talking to the Flask server
    therapist_app/  Flask web app -- the therapist control surface
    patient_app/    Pygame app -- the patient-facing screens + games
    launcher.py     starts Flask + Pygame as separate processes

The Flask server process is the single source of truth for session state.
Everyone else (browser, Pygame) reads it over HTTP and reconciles to it.
"""
