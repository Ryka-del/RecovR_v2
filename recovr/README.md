# RecovR — Dual-Monitor Architecture

This package makes the existing therapist UI (`../main.py` / `scenes/`,
otherwise unchanged) and the patient Pygame app run as **separate processes on
two monitors**, synchronized through a small Flask broker that owns the one
source of truth for session state.

```
┌── THERAPIST (Monitor 2) ──┐      ┌── SESSION BROKER ────────────┐      ┌── PATIENT (Monitor 1) ────┐
│ python main.py             │      │ python -m recovr.run_therapist│      │ python -m recovr.run_patient│
│ (real main.py / scenes/ UI,│ HTTP │ headless Flask app, owns the  │ HTTP │ Pygame app: welcome /      │
│  RECOVR_DUAL_MONITOR=1)    │◄────►│ one SessionStore (source of   │◄────►│ waiting / How-to-Play /    │
│ Start Session hands the    │      │ truth). Everyone else polls   │      │ live game / session-end    │
│ game to the patient window │      │ GET /api/state + reconciles.  │      │                            │
└─────────────────────────────┘      └───────────────────────────────┘      └────────────────────────────┘
```

Real RecovR games are integrated one at a time via the generic adapter in
`patient_app/games/generic_adapter.py`.

## Install

```
pip install -r recovr/requirements.txt      # just Flask (plus existing pygame)
```

## Run everything

From the project root:

```
python -m recovr.launch_production
```

Starts all three processes above, waits for the broker's `/api/health`, then
places the therapist/patient windows on their detected (or env-overridden)
monitors. `Ctrl+C` (or `SIGTERM`/`SIGBREAK`) stops all three children —
nothing is left orphaned. See `launch_production.py`'s own docstring for the
exact env vars (`RECOVR_SINGLE_MONITOR`, `RECOVR_PATIENT_DISPLAY`,
`RECOVR_THERAPIST_DISPLAY`, etc.).

If the display/monitor detection looks wrong, run
`python tools/diagnose_displays.py` first.

## Run the halves separately (development)

```
python -m recovr.run_therapist     # Flask broker on http://127.0.0.1:5000
python main.py                     # therapist UI (set RECOVR_DUAL_MONITOR=1 / RECOVR_ROLE=therapist to match the launcher)
python -m recovr.run_patient       # patient Pygame window
```

`python main.py` on its own (no `RECOVR_DUAL_MONITOR`) still runs as the
original single-process app with its own built-in patient scenes — that path
is untouched by any of this.

## Telemetry

Real values only, per game; the generic adapter forwards whatever each game's
`get_telemetry()` exposes.

## Environment overrides

| Variable | Effect |
|---|---|
| `RECOVR_SINGLE_MONITOR=1` | dev: run all three, no forced monitor placement |
| `RECOVR_PATIENT_DISPLAY` / `RECOVR_THERAPIST_DISPLAY` | pin the SDL display indices |
| `RECOVR_PATIENT_MONITOR` / `RECOVR_THERAPIST_MONITOR` | `"x,y,w,h"` — explicit monitor geometry, wins even over auto-detection |
| `RECOVR_BLE_START_DISABLED=1` | start both processes with BLE parked (set automatically by the launcher) |

## Layout

| Path | Role |
|---|---|
| `shared/protocol.py` | endpoint paths + timing constants (no I/O) |
| `shared/commands.py` | command vocabulary + status-transition rules |
| `shared/session_state.py` | `SessionConfig`, `SessionState`, thread-safe `SessionStore` |
| `comms/client.py` | `PatientCommsClient` — background-thread HTTP client for Pygame |
| `therapist_app/` | Flask app factory (`create_app()`) + `api.py` (`/api/*`) — the broker's HTTP surface |
| `launch_production.py` | starts all 3 processes + places them on their monitors; signal-handled shutdown; requests a Pi shutdown ONLY after a confirmed clean exit (see `deploy/README.md`) |
| `deploy/` | Raspberry Pi autostart (systemd unit) + the narrowly-scoped autoshutdown wrapper/sudoers rule |
| `monitors.py` | monitor detection (native OS APIs, SDL fallback) + env overrides |
| `patient_app/patient_main.py` | Pygame loop + reconcile-to-status state machine |
| `patient_app/game_runner.py` | hosts a `BaseScreen` game; sensor pump; external start/pause/resume/stop; telemetry cadence; game registry |
| `patient_app/games/generic_adapter.py` | glue-only adapter factory: `make_real_adapter()` wraps any registered game — no game mechanics |
| `patient_app/scenes/` | welcome / waiting / instructions / session_end / calibrating / patient_dashboard |

## Integrating the next game

1. Add one line to `_REAL_GAMES` in `patient_app/game_runner.py`:
   `"Basketball": ("games.basketball", "BasketballGame")`
2. The generic adapter (`patient_app/games/generic_adapter.py`) wraps it automatically with
   the shared glue hooks (`begin`, `external_pause/resume/stop`, `_end_game` without the DB
   write, `get_telemetry`, `get_result`, and `handle_event` filtering).
3. Do **not** edit the game's own file under `games/`.
