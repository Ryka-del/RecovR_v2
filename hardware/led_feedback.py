"""
hardware/led_feedback.py -- non-blocking "patient scored" visual feedback on
a 12V LED strip switched via a GPIO-driven MOSFET.

Ticked once per frame from the SAME thread that runs the game loop
(recovr/patient_app/game_runner.py's GameRunner), never a background
thread, never a sleep call. GPIO17 therefore only ever has one thread
touching it, by construction -- that's what makes exclusive ownership a
non-issue here rather than something needing a lock.

Hardware degrades gracefully: if gpiozero (or its pin-factory backend)
isn't available -- this dev machine, a Pi without the library installed, a
permissions issue -- every method below becomes a harmless no-op instead of
raising into the game loop, the same established pattern as
sensors/ble_receiver.py's "bleak not installed" handling and audio.py's
blanket try/except around every sound call.

Requires `gpiozero` on the Raspberry Pi target (not installed by this
change -- see the deployment notes wherever this project's setup steps are
tracked).
"""

import atexit

GPIO_PIN = 17          # BCM numbering -- confirmed unused elsewhere in this codebase
ON_TIME_SEC  = 0.10
OFF_TIME_SEC = 0.10
BLINKS_PER_SEQUENCE = 3

try:
    from gpiozero import LED as _LED
except Exception:
    _LED = None


class LedFeedback:
    """One instance per patient-process session -- see
    recovr/patient_app/game_runner.py's GameRunner.__init__. request_blink()
    is the only thing calling code needs; it is safe to call on every
    scoring event, as often as it likes -- see the coalescing design below."""

    def __init__(self, pin: int = GPIO_PIN):
        self._led = None
        if _LED is not None:
            try:
                self._led = _LED(pin)
                self._led.off()
            except Exception:
                self._led = None   # hardware unavailable -- stay a no-op

        # State machine -- "idle" / "on" / "off_gap". Only ever advanced by
        # tick(), only ever started by request_blink().
        self._state = "idle"
        self._phase_t = 0.0
        self._blinks_left = 0
        # A single boolean, not a counter -- deliberately collapses any
        # number of requests that arrive while a sequence is already
        # running into exactly ONE follow-up sequence, never more than
        # one pending at a time regardless of how many scoring events
        # happened in the meantime.
        self._pending = False

        atexit.register(self.cleanup)

    # -- public -----------------------------------------------------------

    def request_blink(self):
        """Call once per successful scoring event (score increased). Safe
        to call repeatedly in a burst -- see the module docstring."""
        if self._state == "idle":
            self._start_sequence()
        else:
            self._pending = True

    def tick(self, dt: float):
        """Call once per frame, every frame, regardless of whether a
        sequence is currently active -- a cheap no-op while idle."""
        if self._state == "idle":
            return
        self._phase_t += dt
        if self._state == "on" and self._phase_t >= ON_TIME_SEC:
            self._set(False)
            self._state = "off_gap"
            self._phase_t = 0.0
        elif self._state == "off_gap" and self._phase_t >= OFF_TIME_SEC:
            self._blinks_left -= 1
            if self._blinks_left > 0:
                self._set(True)
                self._state = "on"
                self._phase_t = 0.0
            else:
                self._state = "idle"
                if self._pending:
                    self._pending = False
                    self._start_sequence()

    def cleanup(self):
        """Force the LED off and release the GPIO resource. Registered with
        atexit at construction; also called explicitly on a trapped
        SIGTERM/SIGINT -- see recovr/patient_app/patient_main.py. Safe to
        call more than once."""
        self._state = "idle"
        self._pending = False
        self._set(False)
        if self._led is not None:
            try:
                self._led.close()
            except Exception:
                pass
            self._led = None

    # -- internal -----------------------------------------------------------

    def _start_sequence(self):
        self._blinks_left = BLINKS_PER_SEQUENCE
        self._phase_t = 0.0
        self._state = "on"
        self._set(True)

    def _set(self, on: bool):
        if self._led is None:
            return
        try:
            self._led.on() if on else self._led.off()
        except Exception:
            pass
