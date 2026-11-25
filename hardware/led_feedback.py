"""
hardware/led_feedback.py -- visual feedback on a 12V LED strip switched via
a GPIO-driven MOSFET (gate on GPIO17 through a 330ohm series resistor).

Three states, in priority order (a blink burst always interrupts whichever
of the other two was running, then resumes it):
  - idle     : no game session running -- slow continuous breathing fade.
  - active   : a game session is actively being played -- steady full brightness.
  - blinking : a transient burst of BLINKS_PER_SEQUENCE on/off flashes on a
               scoring event, then resumes idle/active exactly where it left off.

Owned ONCE per patient PROCESS (see recovr/patient_app/patient_main.py's
PatientApp.__init__), not per game session -- the idle fade has to keep
running even when no GameRunner exists at all (patient on the Waiting
Screen / Dashboard between sessions), so this can't be scoped to a single
GameRunner's lifetime the way the old score-blink-only version was.
GameRunner still triggers request_blink() on a score increase and tells
set_active() when a session starts/stops, but no longer constructs or
owns the LedFeedback instance itself.

Ticked once per frame from the patient process's own main loop (see
PatientApp.run()), never a background thread, never a sleep call -- GPIO17
therefore only ever has one thread touching it, by construction, exactly
like the version this replaces.

Hardware degrades gracefully: if gpiozero (or its pin-factory backend)
isn't available -- this dev machine, a Pi without the library installed, a
permissions issue -- every method below becomes a harmless no-op instead of
raising into the game loop, the same established pattern as
sensors/ble_receiver.py's "bleak not installed" handling and audio.py's
blanket try/except around every sound call.

Requires `gpiozero` on the Raspberry Pi target (not installed by this
change -- see the deployment notes wherever this project's setup steps are
tracked). Uses PWMLED (not the plain digital LED class) so the idle fade
can vary brightness smoothly -- same GPIO17 pin, gpiozero software-PWMs it
at its own default frequency, which is a normal, supported way to dim an
LED through a MOSFET gate.

PWM BACKEND -- IMPORTANT for a flicker-free fade: by default gpiozero times
its software PWM from *inside this same Python process*, sharing the CPU
(and the GIL) with the patient app's own pygame main loop (per-frame game
logic, BLE polling, rendering). Under that load the PWM pulse timing gets
starved and jittery, which shows up as visible flicker riding on top of the
fade -- not a bug in the brightness curve itself (that part was verified
smooth, step-by-step, in isolation). The fix is to hand PWM generation to
`pigpiod`, a separate always-running system daemon immune to this
process's load, instead of timing it in-process -- see the pin-factory
setup below. Requires, once, on the Pi:
    sudo apt install pigpio python3-pigpio
    sudo systemctl enable pigpiod --now
Falls back to gpiozero's own default (in-process, potentially jittery under
load) factory if pigpiod isn't installed/running -- including on this
Windows dev machine, where there's no GPIO at all.
"""

import atexit
import math

GPIO_PIN = 17          # BCM numbering -- confirmed unused elsewhere in this codebase

try:
    from gpiozero import Device
    from gpiozero.pins.pigpio import PiGPIOFactory
    Device.pin_factory = PiGPIOFactory()
except Exception:
    pass  # pigpiod not installed/running (or not on a Pi at all) -- gpiozero
          # falls back to its own default pin factory further down

# Idle "breathing" fade -- one full dim(0) -> bright(1) -> dim(0) cycle.
# Slow and continuous, not a attention-grabbing animation (this plays
# whenever the device is simply powered on with no game running, which can
# be most of the time).
FADE_PERIOD_SEC = 6.0

# Scoring-event blink burst -- snappier than the idle fade so it reads as a
# distinct, immediate "you scored" cue rather than a continuation of the
# slow breathing. Tune these two if the real hardware still looks too slow;
# they're independent of FADE_PERIOD_SEC above.
BLINK_ON_TIME_SEC  = 0.08
BLINK_OFF_TIME_SEC = 0.08
BLINKS_PER_SEQUENCE = 3

try:
    from gpiozero import PWMLED as _LED
except Exception:
    _LED = None


class LedFeedback:
    """One instance per patient process -- see the module docstring for why
    this changed from one-per-session. request_blink() and set_active() are
    the only things calling code needs; both are safe to call as often as
    they like."""

    def __init__(self, pin: int = GPIO_PIN):
        self._led = None
        if _LED is not None:
            try:
                self._led = _LED(pin)
                self._led.value = 0.0
            except Exception:
                self._led = None   # hardware unavailable -- stay a no-op

        # Base state -- which of "idle" (slow fade) or "active" (steady
        # full brightness) applies whenever no blink burst is in progress.
        self._active = False
        self._fade_t = 0.0

        # Blink-burst state machine -- "idle" / "on" / "off_gap". "idle"
        # here means "no burst running", distinct from the base idle/active
        # state above (a burst can interrupt either one).
        self._blink_state = "idle"
        self._blink_phase_t = 0.0
        self._blinks_left = 0
        # A single boolean, not a counter -- deliberately collapses any
        # number of requests that arrive while a burst is already running
        # into exactly ONE follow-up burst, never more than one pending at
        # a time regardless of how many scoring events happened meanwhile.
        self._blink_pending = False

        atexit.register(self.cleanup)

    # -- public -----------------------------------------------------------

    def set_active(self, active: bool):
        """Call whenever a game session starts or stops being actively
        played (see patient_main.py's _set_mode) -- True for "steady on",
        False for "idle fade". Safe to call every frame with the same
        value; only takes effect as a base-state change, never interrupts
        an in-progress blink burst."""
        self._active = bool(active)

    def request_blink(self):
        """Call once per successful scoring event (score increased). Safe
        to call repeatedly in a burst -- see the pending-collapse note
        above."""
        if self._blink_state == "idle":
            self._start_blink_sequence()
        else:
            self._blink_pending = True

    def tick(self, dt: float):
        """Call once per frame, every frame, for the entire lifetime of the
        patient process -- NOT only while a game is running (the idle fade
        needs to keep animating between sessions too)."""
        if self._blink_state != "idle":
            self._tick_blink(dt)
        else:
            self._tick_base(dt)

    def cleanup(self):
        """Force the LED off and release the GPIO resource. Registered with
        atexit at construction; also called explicitly on a trapped
        SIGTERM/SIGINT -- see recovr/patient_app/patient_main.py. Safe to
        call more than once."""
        self._active = False
        self._blink_state = "idle"
        self._blink_pending = False
        self._set(0.0)
        if self._led is not None:
            try:
                self._led.close()
            except Exception:
                pass
            self._led = None

    # -- internal -----------------------------------------------------------

    def _tick_base(self, dt: float):
        if self._active:
            self._set(1.0)
            # Reset so a later return to idle always restarts the fade from
            # a consistent, predictable point (dimmest) rather than
            # whatever phase it happened to be at when the session began.
            self._fade_t = 0.0
        else:
            self._fade_t += dt
            phase = (self._fade_t % FADE_PERIOD_SEC) / FADE_PERIOD_SEC
            # Smooth 0 -> 1 -> 0 easing (cosine, not linear) -- no visible
            # "corner" at the brightest/dimmest points.
            level = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
            self._set(level)

    def _tick_blink(self, dt: float):
        self._blink_phase_t += dt
        if self._blink_state == "on" and self._blink_phase_t >= BLINK_ON_TIME_SEC:
            self._set(0.0)
            self._blink_state = "off_gap"
            self._blink_phase_t = 0.0
        elif self._blink_state == "off_gap" and self._blink_phase_t >= BLINK_OFF_TIME_SEC:
            self._blinks_left -= 1
            if self._blinks_left > 0:
                self._set(1.0)
                self._blink_state = "on"
                self._blink_phase_t = 0.0
            else:
                self._blink_state = "idle"
                if self._blink_pending:
                    self._blink_pending = False
                    self._start_blink_sequence()
                # else: the NEXT tick() call falls through to _tick_base()
                # above, resuming idle-fade/active-steady exactly where
                # that state's own math says it should be.

    def _start_blink_sequence(self):
        self._blinks_left = BLINKS_PER_SEQUENCE
        self._blink_phase_t = 0.0
        self._blink_state = "on"
        self._set(1.0)

    def _set(self, level: float):
        if self._led is None:
            return
        try:
            self._led.value = level
        except Exception:
            pass
