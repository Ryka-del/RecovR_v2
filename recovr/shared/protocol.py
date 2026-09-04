"""
Wire protocol constants shared by the Flask server and the Pygame client.

Pure data -- no imports beyond the standard library, no Flask, no Pygame.
Both sides import this module so endpoint paths and payload key names can never
drift apart.
"""

import os

# --- Server location -------------------------------------------------------
# Overridable via environment so the launcher can move the server if needed.
HOST = os.environ.get("RECOVR_HOST", "127.0.0.1")
PORT = int(os.environ.get("RECOVR_PORT", "5000"))
BASE_URL = f"http://{HOST}:{PORT}"

# --- Endpoint paths ------------------------------------------------------
EP_HEALTH = "/api/health"            # GET  -> {"ok": true}
EP_STATE = "/api/state"              # GET  -> full SessionState snapshot
EP_CONFIG = "/api/session/config"    # POST -> set SessionConfig (therapist)
EP_COMMAND = "/api/command"          # POST -> {"command": "START_GAME"} (therapist)
EP_GAME_DATA = "/api/game-data"      # POST -> live telemetry snapshot (patient)
EP_RESULT = "/api/session/result"    # POST -> final result at game end (patient)
EP_ACK = "/api/ack"                  # POST -> patient acknowledges a state/action
EP_VOLUME = "/api/volume"            # POST -> {"volume": 0.0-1.0} (therapist)
EP_THERAPIST = "/api/therapist"      # POST -> {"present": bool} (therapist logged in / out)

# --- Timing --------------------------------------------------------------
# How often the Pygame client polls the server for state.
POLL_INTERVAL_SEC = 0.15
# How often the Pygame client pushes a telemetry snapshot while a game runs.
TELEMETRY_INTERVAL_SEC = 0.30
# HTTP request timeout for the Pygame client -- kept short so a dead server
# never stalls the game loop for long (the client runs I/O on its own thread
# anyway, but this bounds worst case).
HTTP_TIMEOUT_SEC = 0.6
# How long the launcher waits for the server to answer /api/health.
HEALTH_TIMEOUT_SEC = 10.0
