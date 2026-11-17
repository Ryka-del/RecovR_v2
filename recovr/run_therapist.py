"""Dev entry point: run ONLY the Flask therapist server.

    python -m recovr.run_therapist
"""

import logging

from recovr.shared import protocol
from recovr.therapist_app import create_app


def main():
    # Werkzeug's own dev-server banner ("WARNING: This is a development
    # server...") and its per-request access log (one line per poll from the
    # therapist/patient processes, several times a second) both go through
    # this same logger at INFO level -- this is a purely local, loopback-only
    # broker talked to only by the other 2 trusted local processes, not a
    # public-facing deployment, so neither line is useful signal here.
    # Raising the threshold to WARNING leaves genuine errors/warnings
    # visible; it does not disable logging.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app = create_app()
    # Calling werkzeug's own run_simple() directly instead of app.run() --
    # functionally identical (app.run() is a thin wrapper around exactly
    # this), but app.run() also unconditionally prints " * Serving Flask
    # app ..." / " * Debug mode: off" via a separate code path that isn't
    # covered by the logger-level change above. threaded=True, single
    # process -> one authoritative SessionStore in memory.
    from werkzeug.serving import run_simple
    run_simple(protocol.HOST, protocol.PORT, app, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
