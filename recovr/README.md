# RecovR — Dual-Monitor Architecture

This package is the **therapist (Flask) + patient (Pygame) + communication layer**
architecture. It runs *alongside* the existing app in `../main.py`, which is untouched.

The first real RecovR game — **Gravity Catch** — is integrated. The other six
games (`Basketball`, `Piano Tiles`, `Steady Aim`, `Apple Catching`, `Key and Lock`,
`Catch the Falling Object`) are added one at a time; until then, selecting one
leaves the patient app on its Waiting screen with a notice.

```
┌── THERAPIST ─────────────┐        ┌── COMMUNICATION LAYER ──────┐        ┌── PATIENT ───────────────┐
│ Flask web control page   │        │ Flask process owns the one  │        │ Pygame app               │
│  - session config        │  HTTP  │ SessionStore (source of     │  HTTP  │  - welcome / waiting     │
│  - START/PAUSE/RESUME/    │ ─────► │ truth). Everyone else polls  │ ◄───── │  - instructions + 3-2-1  │
│    STOP/NEXT/CALIBRATE    │        │ GET /api/state and reconciles│        │  - Gravity Catch (real)  │
│  - live telemetry view   │        │ to it. Commands => status.   │        │  - session-end summary   │
└──────────────────────────┘        └─────────────────────────────┘        └──────────────────────────┘
```

## Install

```
pip install -r recovr/requirements.txt      # just Flask (plus existing pygame)
```

## Run everything (launcher)

From the project root:

```
python -m recovr.launcher
```

Starts the Flask server, waits for `/api/health`, starts the patient Pygame
window, opens the therapist control page. `Ctrl+C` (or SIGTERM / SIGBREAK) stops
both children — nothing is left orphaned.

## Run the halves separately (development)

```
python -m recovr.run_therapist     # Flask on http://127.0.0.1:5000
python -m recovr.run_patient       # Pygame patient window
```

## Try the flow

1. Open <http://127.0.0.1:5000>.
2. **Session configuration** → `Gravity Catch` / `Easy` / `60` → **Apply configuration**. The patient Waiting screen shows the details.
3. Click **Start** → patient shows a 3-2-1 lead-in, then the **real Gravity Catch** game.
4. Move the basket with the wrist sensor (or ←/→ when the patient window has focus). Live score / remaining / catcher position / tilt appear on the control page.
5. **Pause** → the game's real timer and mechanics stop (not just an overlay). **Resume** continues. **Stop** ends it cleanly and returns the patient to Waiting.
6. Let the duration run out → patient shows *Session complete*, control page status → `COMPLETE`, and the result is posted to `/api/session/result` (no DB write from the game).

## Telemetry (Gravity Catch)

Real values only: `score`, `reps`, `elapsed_sec`, `remaining_sec`, `duration_sec`,
`difficulty`, `catcher_x`, `tilt_x`, `sensor_connected`, `falling_objects`.
**Not available from the unmodified game:** `misses`, `accuracy`, `reaction_time_ms`
(the control page shows `—` for those).

## Environment overrides

| Variable | Effect |
|---|---|
| `RECOVR_HOST`, `RECOVR_PORT` | server bind / client target (default `127.0.0.1:5000`) |
| `RECOVR_PATIENT_POS="x,y"` | patient window position |
| `RECOVR_PATIENT_SIZE="WxH"` | patient window size (default `1280x720`) |
| `RECOVR_FULLSCREEN=1` | patient window fullscreen |
| `RECOVR_PATIENT_MONITOR="x,y,w,h"` | launcher places the patient window here |

## Layout

| Path | Role |
|---|---|
| `shared/protocol.py` | endpoint paths + timing constants (no I/O) |
| `shared/commands.py` | command vocabulary + status-transition rules |
| `shared/session_state.py` | `SessionConfig`, `SessionState`, thread-safe `SessionStore` |
| `comms/client.py` | `PatientCommsClient` — background-thread HTTP client for Pygame |
| `therapist_app/` | Flask app: `api.py` (/api/*), `views.py` + templates/static (control page) |
| `patient_app/patient_main.py` | Pygame loop + reconcile-to-status state machine |
| `patient_app/game_runner.py` | hosts a `BaseScreen` game; sensor pump; external start/pause/resume/stop; telemetry cadence; game registry |
| `patient_app/games/gravity_catch_adapter.py` | glue-only adapter: `GravityCatchAdapter(GravityCatchGame)` — no game mechanics |
| `patient_app/scenes/` | welcome / waiting / instructions / session_end / calibrating |
| `launcher.py` | starts both processes + browser; signal-handled shutdown |
| `monitors.py` | monitor map (stub + env overrides) |

## Integrating the next game

1. Add one line to `_GAME_REGISTRY` in `patient_app/game_runner.py`:
   `"Basketball": ("recovr.patient_app.games.basketball_adapter", "BasketballAdapter", True)`
2. Create `patient_app/games/basketball_adapter.py` subclassing the real game with the
   same glue hooks Gravity Catch uses (`begin`, `external_pause/resume/stop`, `_end_game`
   without the DB write, `get_telemetry`, `get_result`, and `handle_event` filtering).
3. Do **not** edit `games/basketball.py`.

## Later (not yet)

- Persist `SessionStore.result` from the Flask side with real patient/therapist IDs.
- Port `scenes/therapist_dashboard.py` panels to Flask/HTML.
- Retire `main.py` + the Pygame therapist scenes.
- Real sensors / calibration / analytics.
