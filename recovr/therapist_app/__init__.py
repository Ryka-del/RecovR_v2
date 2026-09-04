"""
Flask application factory for the therapist control surface.

The app owns exactly one `SessionStore` (`app.config["STORE"]`) -- the single
source of truth for session state. Run it single-process / threaded so that
"in memory" means one authoritative copy:

    create_app().run(host=..., port=..., threaded=True)
"""

from flask import Flask

from recovr.shared.session_state import SessionStore


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = SessionStore()

    from recovr.therapist_app.api import bp as api_bp
    from recovr.therapist_app.views import bp as views_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)
    return app
