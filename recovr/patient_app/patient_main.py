"""
Patient-side Pygame application.

It holds NO session authority. Every frame it reads the latest server snapshot
(via PatientCommsClient) and *reconciles* its local screen to `status`:

    IDLE / READY      -> Waiting
    RUNNING (new)     -> Instructions countdown -> game
    RUNNING (resumed) -> unpause the game
    PAUSED            -> pause the game
    STOPPED           -> abandon the game -> Waiting
    COMPLETE          -> Session-end summary
    CALIBRATING       -> Calibrating screen -> post /api/ack

Reconciliation keys off two counters from the server:
    game_seq     bumps when a fresh activity should (re)start
    command_seq  bumps on every therapist command (used only for logging here)

Dev keys:  ESC or window close quits.
Env:  RECOVR_PATIENT_POS="x,y"  RECOVR_PATIENT_SIZE="WxH"  RECOVR_FULLSCREEN=1
"""

import os
import sys

# make the project root importable (screens/, constants, ...) even if launched oddly
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pygame

from recovr.shared import commands as cmd
from recovr.comms.client import PatientCommsClient
from recovr.patient_app.game_runner import GameRunner, GameNotAvailable, resolve_game
from recovr.patient_app.scenes.common import draw_banner
from recovr.patient_app.scenes.welcome import WelcomeScreen
from recovr.patient_app.scenes.waiting import WaitingScreen
from recovr.patient_app.scenes.instructions import InstructionsScreen
from recovr.patient_app.scenes.session_end import SessionEndScreen
from recovr.patient_app.scenes.calibrating import CalibratingScreen
from recovr.patient_app.scenes.stopped import StoppedScreen
from recovr.patient_app.scenes.patient_dashboard import PatientDashboardScreen
from recovr.patient_app.scenes.waiting_screen import WaitingScreen as WaitingScreenV2

# Production dual-monitor mode: the therapist half is the real main.py app on the
# other monitor, so this window skips the prototype's own instruction/countdown
# and calibration-stub, lets the real game show its own "How to Play" screen, and
# forwards real patient/therapist ids so the game persists results as it always has.
DUAL = os.environ.get("RECOVR_DUAL_MONITOR") == "1"

# local screen modes
WELCOME = "WELCOME"              # app start / logged out (patient welcome splash)
DASHBOARD = "DASHBOARD"         # production: therapist logged in, no active game -- resting state (temp UI)
WAITING = "WAITING"            # prototype resting screen
WAITING_SCREEN = "WAITING_SCREEN"   # production: waiting for the therapist -- pre-login OR
                                   # logged in but NO patient selected (instruction carousel)
HOWTOPLAY = "HOWTOPLAY"          # production: game created, showing its own How-to-Play, NOT started
INSTRUCTIONS = "INSTRUCTIONS"    # prototype only: recovr's own 3-2-1
PLAYING = "PLAYING"
ENDED = "ENDED"                  # prototype only: recovr's own session-end screen
STOPPED_NOTICE = "STOPPED_NOTICE"
CALIBRATING = "CALIBRATING"

WELCOME_SECONDS = 2.0           # prototype only -- production stays on Welcome until START SESSION
INSTRUCTIONS_SECONDS = 3.0
CALIBRATION_SECONDS = 3.0


def _window_size():
    if os.environ.get("RECOVR_FULLSCREEN") == "1":
        return (0, 0), pygame.FULLSCREEN
    raw = os.environ.get("RECOVR_PATIENT_SIZE", "1280x720")
    try:
        w, h = (int(x) for x in raw.lower().split("x"))
    except ValueError:
        w, h = 1280, 720
    return (w, h), 0


def _create_display(size, flags):
    """set_mode, optionally targeting a specific physical display.

    RECOVR_PATIENT_DISPLAY (int) selects the SDL display index so the patient
    window opens on a chosen monitor -- no hard-coded coordinates. Missing /
    invalid / out-of-range / headless falls back to the current behaviour
    (default display). All other window behaviour -- RECOVR_PATIENT_SIZE,
    RECOVR_FULLSCREEN, RECOVR_PATIENT_POS, and the render scaling -- is unchanged.
    """
    raw = os.environ.get("RECOVR_PATIENT_DISPLAY", "").strip()
    if raw:
        try:
            idx = int(raw)
            n = pygame.display.get_num_displays()
            if 0 <= idx < n:
                return pygame.display.set_mode(size, flags, display=idx)
            print(f"[recovr] RECOVR_PATIENT_DISPLAY={idx} out of range (0..{n - 1}); "
                  "using default display")
        except (ValueError, pygame.error) as exc:
            print(f"[recovr] RECOVR_PATIENT_DISPLAY ignored ({exc}); using default display")
    return pygame.display.set_mode(size, flags)


def _make_welcome(screen):
    """Dual-monitor: the production RecovR welcome splash (scenes/patient_welcome.py).
    Prototype / fallback: the minimal built-in welcome. Both expose draw(surface)."""
    if DUAL:
        try:
            from scenes.patient_welcome import PatientWelcomeScene
            w, h = screen.get_size()
            return PatientWelcomeScene(screen, w, h)
        except Exception as exc:
            print(f"[recovr] PatientWelcomeScene unavailable ({exc}); using minimal welcome")
    return WelcomeScreen()


class PatientApp:

    def __init__(self):
        pos = os.environ.get("RECOVR_PATIENT_POS")
        if pos:
            os.environ.setdefault("SDL_VIDEO_WINDOW_POS", pos)

        pygame.init()
        size, flags = _window_size()
        self.screen = _create_display(size, flags)
        pygame.display.set_caption("RecovR - Patient")
        self.clock = pygame.time.Clock()

        self.comms = PatientCommsClient()
        self.comms.start()

        # screens
        self.s_welcome = _make_welcome(self.screen)
        self.s_waiting = WaitingScreen()
        self.s_instructions = InstructionsScreen()
        self.s_end = SessionEndScreen()
        self.s_calibrating = CalibratingScreen()
        self.s_stopped = StoppedScreen()
        self.s_patient_dash = PatientDashboardScreen()   # temp; after therapist login
        self.s_waiting_v2 = WaitingScreenV2()            # temp; after START SESSION

        # local state
        self.mode = WELCOME
        self.mode_t = 0.0
        self.runner: GameRunner | None = None
        self.session_id = ""
        self.applied_session_seq = 0   # START SESSION cursor (-> How to Play)
        self.applied_game_seq = 0      # START GAME / restart cursor (-> game runs)
        self.instr_elapsed = 0.0       # prototype 3-2-1 countdown
        self._howto_elapsed = 0.0
        self._result_posted = False    # session result POSTed once per game
        self._cal_acked = False
        self._unavailable_game = None   # set when the therapist picks an unknown game
        self._applied_dark = True       # last theme applied from the therapist (DUAL)
        self._applied_volume = None     # last music volume applied from the therapist (DUAL)

    # ------------------------------------------------------------------ #
    #  Main loop
    # ------------------------------------------------------------------ #

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            self.mode_t += dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif self.mode == PLAYING and self.runner is not None:
                    self.runner.handle_event(event)

            snap = self.comms.get_snapshot()
            self._reconcile(snap)
            self._update(dt, snap)
            self._draw(snap)
            pygame.display.flip()

        self.comms.stop()
        pygame.quit()

    # ------------------------------------------------------------------ #
    #  Reconcile local screen to server status
    # ------------------------------------------------------------------ #

    @staticmethod
    def _has_patient(snap) -> bool:
        return bool((snap or {}).get("selected_patient"))

    def _resting_mode(self, snap):
        """Production resting screen: Patient Dashboard when a patient is selected,
        otherwise the Waiting Screen. Prototype: its own Waiting screen."""
        if not DUAL:
            return WAITING
        return DASHBOARD if self._has_patient(snap) else WAITING_SCREEN

    def _idle(self, snap):
        """Return to the resting screen and re-sync both counters so the NEXT
        therapist START SESSION / START GAME is reliably detected."""
        self._teardown_runner()
        s = snap or {}
        self.applied_session_seq = s.get("session_seq", self.applied_session_seq)
        self.applied_game_seq = s.get("game_seq", self.applied_game_seq)
        self._set_mode(self._resting_mode(s))

    def _reconcile(self, snap):
        if snap is None:
            # No server contact yet. Prototype auto-advances Welcome->Waiting;
            # production stays on Welcome until START SESSION arrives.
            if not DUAL and self.mode == WELCOME and self.mode_t >= WELCOME_SECONDS:
                self._set_mode(WAITING)
            return

        if DUAL:
            self._reconcile_dual(snap)
        else:
            self._reconcile_prototype(snap)

    # -- production ----------------------------------------------------
    #
    #  Patient dual-monitor state machine, driven ENTIRELY by broker state
    #  (no timers). The resting screen is chosen by whether a patient is
    #  selected -- Patient Dashboard when one is, the Waiting Screen when not:
    #     present False, booting False  -> WELCOME          (app start / logged out)
    #     present False, booting True   -> WAITING_SCREEN   (on the Login page)
    #     present True, no patient       -> WAITING_SCREEN   (logged in, nobody selected)
    #     present True, patient selected -> DASHBOARD         (resting state)
    #     session_seq bump              -> HOWTOPLAY         (START SESSION: build game)
    #     game_seq bump + RUNNING       -> PLAYING           (START on Session in Progress)
    #     PAUSED / RUNNING              -> pause / resume the game
    #     COMPLETE                      -> stay in PLAYING (game's own Session Complete)
    #     stop_pending                  -> STOPPED_NOTICE, runner KEPT (paused, held)
    #        then CONTINUE (RUNNING/PAUSED) -> back to PLAYING, SAME game resumes
    #             BACK     (STOPPED/IDLE)   -> teardown -> resting screen
    #     IDLE (from an active mode)    -> resting screen     (therapist Back)
    #
    _SESSION_MODES = (HOWTOPLAY, PLAYING, STOPPED_NOTICE, ENDED, CALIBRATING)
    _RESTING_MODES = (WELCOME, WAITING_SCREEN, DASHBOARD)

    def _reconcile_dual(self, snap):
        status = snap.get("status", cmd.IDLE)
        config = snap.get("config", {})
        session_seq = snap.get("session_seq", 0)
        game_seq = snap.get("game_seq", 0)
        pending = snap.get("pending_action", "")
        therapist_present = bool(snap.get("therapist_present", False))
        booting = bool(snap.get("session_booting", False))

        # 0a. No therapist logged in. Welcome normally; Waiting Screen once the
        #     therapist has left their Welcome page (booting) but not logged in.
        if not therapist_present:
            target = WAITING_SCREEN if booting else WELCOME
            if self.mode != target:
                self._teardown_runner()
                self._set_mode(target)
            return

        # 0b. Logged in and on a resting screen -> keep it in sync with the
        #     selected-patient state (Dashboard iff a patient is selected). This
        #     flips live when the therapist selects / deselects.
        if self.mode in self._RESTING_MODES:
            want = self._resting_mode(snap)
            if self.mode != want:
                self._set_mode(want)

        # 1. Red STOP -> decision state. HOLD the game (pause it, keep the runner
        #    alive) and show the "Game Stopped" screen. Nothing is destroyed here
        #    -- the therapist may still choose CONTINUE.
        if snap.get("stop_pending"):
            if self.mode in (HOWTOPLAY, PLAYING, STOPPED_NOTICE):
                if self.runner is not None:
                    self.runner.set_paused(True)
                if self.mode != STOPPED_NOTICE:
                    self._set_mode(STOPPED_NOTICE)
            return

        # 1b. Decision made while the "Game Stopped" screen is up.
        if self.mode == STOPPED_NOTICE:
            if self.runner is not None and status in (cmd.RUNNING, cmd.PAUSED):
                # CONTINUE -> the SAME game resumes (state preserved).
                self.runner.set_paused(status == cmd.PAUSED)
                self._set_mode(PLAYING)
            elif self.runner is not None and status == cmd.READY:
                # CONTINUE during How-to-Play -> back to the game's own screen.
                self._set_mode(HOWTOPLAY)
            else:
                # BACK (STOPPED / IDLE) -> session ended, clean up.
                self._teardown_runner()
                self._set_mode(self._resting_mode(snap))
            return

        # 1c. A bare STOP_GAME with no pending decision (e.g. header Back path)
        #     -> end the session.
        if status == cmd.STOPPED and self.mode in (HOWTOPLAY, PLAYING):
            self._teardown_runner()
            self._set_mode(self._resting_mode(snap))
            return

        # 2. Calibration (therapist-driven; patient just waits).
        if pending == cmd.CALIBRATE or status == cmd.CALIBRATING:
            if self.mode != CALIBRATING:
                self._teardown_runner()
                self._set_mode(CALIBRATING)
            return

        # 3. START SESSION -> build the game and show its OWN How-to-Play / first
        #    frame, frozen. The game does NOT run until the therapist presses
        #    START on the Session in Progress screen (no waiting screen here,
        #    no timer, no patient input).
        if session_seq != self.applied_session_seq and config.get("selected_game"):
            self.applied_session_seq = session_seq
            self.applied_game_seq = game_seq          # game hasn't started yet
            self._begin_session(config)
            self._set_mode(HOWTOPLAY if self.runner is not None else DASHBOARD)
            return

        # 4. START GAME / RESTART -> the actual game starts NOW (no touch, no timer).
        if status == cmd.RUNNING and game_seq != self.applied_game_seq:
            self.applied_game_seq = game_seq
            if self.runner is None or self.runner.finished:
                self._begin_session(config)           # restart / late-join -> fresh instance
            if self.runner is not None:
                self._set_mode(PLAYING)
                self.runner.force_begin()
            else:
                self._set_mode(self._resting_mode(snap))
            return

        # 5. pause / resume the running game
        if status == cmd.PAUSED:
            if self.mode == PLAYING and self.runner is not None:
                self.runner.set_paused(True)
            return
        if status == cmd.RUNNING and self.mode == PLAYING and self.runner is not None:
            self.runner.set_paused(False)
            return

        # 6. COMPLETE -> stay in PLAYING; the game keeps drawing its OWN original
        #    "Session Complete" screen until the therapist goes Back.
        if status == cmd.COMPLETE:
            return

        # 7. IDLE from an active session mode -> resting Waiting Screen.
        if status == cmd.IDLE and self.mode in self._SESSION_MODES:
            self._idle(snap)

    # -- prototype ----------------------------------------------------
    def _reconcile_prototype(self, snap):
        status = snap.get("status", cmd.IDLE)
        config = snap.get("config", {})
        game_seq = snap.get("game_seq", 0)
        pending = snap.get("pending_action", "")

        if self.mode == WELCOME and self.mode_t >= WELCOME_SECONDS:
            self._set_mode(WAITING)

        if pending == cmd.CALIBRATE or status == cmd.CALIBRATING:
            if self.mode != CALIBRATING:
                self._teardown_runner()
                self._cal_acked = False
                self._set_mode(CALIBRATING)
            return

        if status == cmd.RUNNING:
            if game_seq != self.applied_game_seq:
                self.applied_game_seq = game_seq
                self._begin_session(config)
                self._set_mode(INSTRUCTIONS if self.runner is not None else WAITING)
            elif self.mode == PLAYING and self.runner is not None:
                self.runner.set_paused(False)
        elif status == cmd.PAUSED:
            if self.mode == PLAYING and self.runner is not None:
                self.runner.set_paused(True)
        elif status == cmd.STOPPED:
            self._unavailable_game = None
            if self.mode in (PLAYING, INSTRUCTIONS, ENDED):
                self._idle(snap)
        elif status == cmd.COMPLETE:
            if self.mode in (PLAYING, INSTRUCTIONS):
                self._set_mode(ENDED)
        elif status in (cmd.IDLE, cmd.READY):
            self._unavailable_game = None
            if self.mode in (PLAYING, INSTRUCTIONS, ENDED, CALIBRATING):
                self._idle(snap)

    # ------------------------------------------------------------------ #
    #  Per-frame update for the active mode
    # ------------------------------------------------------------------ #

    def _update(self, dt, snap):
        status = (snap or {}).get("status", cmd.IDLE)

        # Production: keep the patient side in sync with the therapist's live
        # controls -- theme (light/dark) and music volume -- every frame, on
        # whatever screen is currently showing.
        if DUAL and snap is not None:
            cfg = snap.get("config", {})
            # top-level dark_mode is the source of truth; config.dark_mode is a
            # mirror kept for the game-launch payload.
            want_dark = bool(snap.get("dark_mode", cfg.get("dark_mode", True)))
            if want_dark != self._applied_dark:
                self._applied_dark = want_dark
                try:
                    from constants import set_dark_mode
                    set_dark_mode(want_dark)
                except Exception:
                    pass
            vol = snap.get("volume")
            if vol is not None and vol != self._applied_volume:
                self._applied_volume = vol
                try:
                    pygame.mixer.music.set_volume(float(vol))
                except Exception:
                    pass

        if self.mode == INSTRUCTIONS:
            # countdown only advances while the therapist is actually running
            if status == cmd.RUNNING:
                self.instr_elapsed += dt
            if self.instr_elapsed >= INSTRUCTIONS_SECONDS:
                self._set_mode(PLAYING)
                if self.runner is not None:
                    # tell the game to begin NOW (starts its timer/music at the
                    # right instant, and dismisses any in-game instruction gate)
                    self.runner.start()

        elif self.mode == PLAYING and self.runner is not None:
            self.runner.update(dt)

            tele = self.runner.due_telemetry()
            if tele is not None:
                tele["session_id"] = self.session_id
                self.comms.post_telemetry(tele)

            if self.runner.finished and not self._result_posted:
                self._result_posted = True
                result = self.runner.result()
                result["session_id"] = self.session_id
                self.comms.post_result(result)     # server -> COMPLETE
                if not DUAL:
                    self._set_mode(ENDED)
                # DUAL: stay in PLAYING so the game keeps drawing its OWN
                # original "Session Complete" screen until the therapist exits.

        elif self.mode == CALIBRATING:
            # Production: the real CalibrationWindow runs on the therapist monitor;
            # this window just shows a "please wait" state until the therapist
            # finishes and the broker leaves CALIBRATING. Only the prototype
            # self-acks with a stub result.
            if not DUAL and not self._cal_acked and self.mode_t >= CALIBRATION_SECONDS:
                self._cal_acked = True
                cfg = (snap or {}).get("config", {})
                self.comms.post_ack({
                    "pending_action": cmd.CALIBRATE,
                    "calibration": {
                        "game_type": cfg.get("selected_game", ""),
                        "avg": 0.62,
                        "threshold": 0.40,
                        "note": "stub calibration from patient app",
                    },
                })

    # ------------------------------------------------------------------ #
    #  Draw
    # ------------------------------------------------------------------ #

    def _draw(self, snap):
        if self.mode == WELCOME:
            # PatientWelcomeScene wants an update(mouse_pos, dt_ms) tick for its fade-in
            upd = getattr(self.s_welcome, "update", None)
            if DUAL and callable(upd):
                try:
                    upd((0, 0), self.clock.get_time())
                except Exception:
                    pass
            self.s_welcome.draw(self.screen)
        elif self.mode == DASHBOARD:
            self.s_patient_dash.draw(self.screen, snap)
        elif self.mode == WAITING_SCREEN:
            self.s_waiting_v2.draw(self.screen, snap)
        elif self.mode == WAITING:
            note = None
            if self._unavailable_game:
                note = f"\"{self._unavailable_game}\" is not available yet"
            self.s_waiting.draw(self.screen, snap, self.comms.connected, note=note)
        elif self.mode == INSTRUCTIONS:
            self.s_instructions.draw(self.screen, INSTRUCTIONS_SECONDS - self.instr_elapsed)
        elif self.mode == HOWTOPLAY and self.runner is not None:
            # the game's OWN "How to Play" screen (frozen; not started yet)
            self.runner.draw(self.screen)
        elif self.mode == PLAYING and self.runner is not None:
            self.runner.draw(self.screen)
        elif self.mode == STOPPED_NOTICE:
            self.s_stopped.draw(self.screen)
        elif self.mode == ENDED:
            self.s_end.draw(self.screen, self.runner.result() if self.runner else {})
        elif self.mode == CALIBRATING:
            if DUAL:
                self.s_calibrating.draw(self.screen, frac=None,
                                        message="Follow the guidance on the therapist station.")
            else:
                self.s_calibrating.draw(self.screen, min(1.0, self.mode_t / CALIBRATION_SECONDS))
        else:
            self.s_waiting.draw(self.screen, snap, self.comms.connected)

        if not self.comms.connected:
            draw_banner(self.screen, "Reconnecting to therapist station...")

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _set_mode(self, mode):
        self.mode = mode
        self.mode_t = 0.0
        if mode == INSTRUCTIONS:
            self.instr_elapsed = 0.0
        # BLE controller ownership: the patient process holds the controller only
        # for How-to-Play (connecting during the therapist's ~5 s START lock) and
        # the running game. Every other mode releases it so the therapist process
        # can own it (patient selection / Game Config / calibration).
        self._reconcile_ble(mode in (HOWTOPLAY, PLAYING))

    def _reconcile_ble(self, want: bool):
        if getattr(self, "_ble_want", None) == want:
            return
        self._ble_want = want
        try:
            from sensors.ble_receiver import ble_receiver
            ble_receiver.set_enabled(want)
        except Exception:
            pass

    def _begin_session(self, config: dict):
        self._teardown_runner()
        self._result_posted = False
        self._howto_elapsed = 0.0
        self.session_id = config.get("session_id", "")
        name = config.get("selected_game")
        try:
            spec = resolve_game(name)
        except GameNotAvailable as exc:
            print(f"[recovr] cannot start session: game not available ({exc})")
            self.runner = None
            self._unavailable_game = name or "?"
            return
        self._unavailable_game = None
        runner_cfg = {
            "session_id": self.session_id,
            "patient_name": config.get("patient_name", ""),
            "difficulty": config.get("difficulty", "Easy"),
            "duration_sec": config.get("duration_sec", 60),
        }
        if DUAL:
            # apply the therapist's light/dark choice to constants BEFORE the
            # game is constructed -- exactly what scenes/game_scene.py does.
            try:
                from constants import set_dark_mode
                set_dark_mode(bool(config.get("dark_mode", True)))
            except Exception:
                pass
            # give the real game the same context the standalone main.py app
            # passes it (so difficulty / calibration / persistence all work).
            pid = config.get("patient_id") or None
            runner_cfg.update({
                "real_app": True,
                "account_id": config.get("account_id"),
                "patient": {"id": pid} if pid else None,
                "account": None,
                "speed": config.get("speed", "Normal"),
                "calibration": config.get("calibration") or {},
                "dark_mode": bool(config.get("dark_mode", True)),
            })
        self.runner = GameRunner(spec, runner_cfg)
        # Not paused: the game is frozen simply because runner.update() is not
        # called while on the How-to-Play / Instructions screen. (Pausing here
        # would make GameRunner draw its "held by therapist" overlay over it.)
        self.s_instructions.set_context(config)

    def _teardown_runner(self):
        """Fully drop the current game so the NEXT one starts from a clean slate
        (fresh adapter + fresh game instance; no stale state / music / flags)."""
        if self.runner is not None:
            try:
                self.runner.stop()          # -> game.external_stop() -> stop_music()
            except Exception:
                pass
        self.runner = None
        self._result_posted = False
        self._howto_elapsed = 0.0
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass


def main():
    PatientApp().run()


if __name__ == "__main__":
    main()
