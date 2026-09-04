"""Dev entry point: run ONLY the Flask therapist server.

    python -m recovr.run_therapist
"""

from recovr.shared import protocol
from recovr.therapist_app import create_app


def main():
    app = create_app()
    # threaded=True, single process -> one authoritative SessionStore in memory.
    app.run(host=protocol.HOST, port=protocol.PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
