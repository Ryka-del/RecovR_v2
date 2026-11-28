"""
hardware/led_feedback.py -- visual feedback on a 12V LED strip switched by an
IRLZ44N MOSFET (gate on GPIO17 through a 330 ohm series resistor).

Three states (a blink burst interrupts either of the other two, then resumes):
  - idle     : no game running -- slow continuous breathing fade.
  - active   : a game is being played -- steady full brightness.
  - blinking : BLINKS_PER_SEQUENCE flashes on a scoring event.

Owned ONCE per patient process (recovr/patient_app/patient_main.py's
PatientApp). The game loop only calls set_active() and request_blink(), which
just set flags; a small background thread does all timing and is the only code
that writes to the hardware, so a slow game frame never stalls the effect and
the LED never delays the game.

PWM backends, tried in this order:
  1. "kernel"  -- the Linux pwm-gpio driver (dtoverlay=pwm-gpio,gpio=17),
                  controlled through /sys/class/pwm. The kernel times the
                  pulses with high-resolution timers and applies brightness
                  changes only at a cycle boundary, so the fade stays steady
                  while Python is busy. It does not use the Pi's PWM hardware,
                  so the 3.5 mm audio output is unaffected. Needs the one-time
                  setup in recovr/deploy/README.md.
  2. "gpiozero" -- software PWM timed in user space (lgpio). Works without
                  setup, but can flicker during the fade.
  3. none      -- no LED hardware (e.g. a Windows dev machine): every method
                  is a harmless no-op.

Run by hand (with RecovR closed):
    python3 -m hardware.led_feedback status | test | off
"""

import atexit
import glob
import math
import os
import sys
import threading
import time

GPIO_PIN = 17          # BCM numbering

PWM_HZ        = 200    # well above visible flicker; light load for the kernel
MIN_PULSE_NS  = 10_000 # shorter pulses cannot be timed reliably in software
PWM_SYSFS     = "/sys/class/pwm"

# One full dark -> bright -> dark breath.
FADE_PERIOD_SEC = 6.0
# Eyes judge brightness non-linearly; this makes the fade look even instead of
# lingering near full brightness.
FADE_GAMMA = 2.2

BLINK_ON_TIME_SEC   = 0.08
BLINK_OFF_TIME_SEC  = 0.08
BLINKS_PER_SEQUENCE = 3

_FADE_STEP_SEC  = 0.02   # 50 brightness updates per second
_BLINK_STEP_SEC = 0.005


class KernelPwm:
    """GPIO driven by the kernel's pwm-gpio driver, through sysfs."""

    name = "kernel"

    def __init__(self, channel_dir: str, hz: int = PWM_HZ):
        self._dir = channel_dir
        self._period = int(1_000_000_000 / hz)
        # Disabled first: the kernel then accepts any period/duty combination
        # left behind by an earlier run.
        self._write("enable", 0)
        self._write("duty_cycle", 0)
        self._write("period", self._period)
        self._write("enable", 1)

    @staticmethod
    def find_channel(pin: int = GPIO_PIN, root: str = PWM_SYSFS):
        """The sysfs directory of the pwm-gpio channel on `pin`, exporting it
        if permitted; None if the overlay is not loaded for that pin."""
        for chip in sorted(glob.glob(os.path.join(root, "pwmchip*"))):
            node = os.path.join(chip, "device", "of_node")
            try:
                with open(os.path.join(node, "compatible"), "rb") as f:
                    if b"pwm-gpio" not in f.read().split(b"\0"):
                        continue
                # gpios = <controller pin flags>, big-endian 32-bit cells
                with open(os.path.join(node, "gpios"), "rb") as f:
                    if int.from_bytes(f.read()[4:8], "big") != pin:
                        continue
            except OSError:
                continue
            channel = os.path.join(chip, "pwm0")
            if not os.path.isdir(channel):
                try:
                    with open(os.path.join(chip, "export"), "w") as f:
                        f.write("0")
                except OSError:
                    pass
            return channel if os.path.isdir(channel) else None
        return None

    def _write(self, attr: str, value: int):
        with open(os.path.join(self._dir, attr), "w") as f:
            f.write(str(value))

    def duty_ns(self, level: float) -> int:
        duty = int(round(max(0.0, min(1.0, level)) * self._period))
        if duty < MIN_PULSE_NS:
            return 0
        if self._period - duty < MIN_PULSE_NS:
            return self._period
        return duty

    def set(self, level: float):
        self._write("duty_cycle", self.duty_ns(level))

    def close(self):
        """Drive the pin low and leave it there."""
        self._write("duty_cycle", 0)
        time.sleep(2 * self._period / 1e9)   # the change lands at a cycle edge
        self._write("enable", 0)             # the driver holds the pin low


class GpiozeroPwm:
    """Fallback: gpiozero's own (user-space) software PWM."""

    name = "gpiozero"

    def __init__(self, pin: int = GPIO_PIN):
        from gpiozero import PWMLED
        self._led = PWMLED(pin, initial_value=0.0, frequency=PWM_HZ)

    def set(self, level: float):
        self._led.value = max(0.0, min(1.0, level))

    def close(self):
        self._led.off()
        self._led.close()


def open_backend(pin: int = GPIO_PIN):
    """The best available backend, or None. Says which one on stdout."""
    channel = KernelPwm.find_channel(pin)
    if channel is not None:
        try:
            backend = KernelPwm(channel)
            print(f"[led] kernel PWM on GPIO{pin} at {PWM_HZ} Hz")
            return backend
        except OSError as exc:
            print(f"[led] WARNING: kernel PWM found but not usable ({exc}). "
                  "Check: systemctl status recovr-led")
    try:
        backend = GpiozeroPwm(pin)
        print(f"[led] WARNING: using gpiozero software PWM on GPIO{pin}; the "
              "fade may flicker. See recovr/deploy/README.md (LED strip).")
        return backend
    except Exception as exc:
        if sys.platform.startswith("linux"):
            print(f"[led] WARNING: LED disabled, no usable GPIO backend ({exc})")
        return None


class LedFeedback:
    """One instance per patient process. request_blink() and set_active() are
    safe to call from the game loop as often as needed."""

    def __init__(self, pin: int = GPIO_PIN, *, backend=None, start_thread=True):
        self._backend = backend if backend is not None else open_backend(pin)
        self._lock = threading.RLock()
        self._level = None

        # Base state: "idle" fade or "active" steady, whenever not blinking.
        self._active = False
        self._fade_t = 0.0

        # Blink burst: "idle" (none running) / "on" / "off_gap".
        self._blink_state = "idle"
        self._blink_phase_t = 0.0
        self._blinks_left = 0
        # A flag, not a counter: any number of scores during a burst collapse
        # into exactly one follow-up burst.
        self._blink_pending = False

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        if self._backend is not None and start_thread:
            self._thread = threading.Thread(target=self._run, name="LedFeedback",
                                            daemon=True)
            self._thread.start()

        atexit.register(self.cleanup)

    # -- public -----------------------------------------------------------

    @property
    def backend_name(self) -> str:
        return self._backend.name if self._backend is not None else "none"

    def set_active(self, active: bool):
        """True while a game is being played (steady light), else idle fade.
        Never interrupts a blink burst."""
        with self._lock:
            self._active = bool(active)
        self._wake.set()

    def request_blink(self):
        """Call once per scoring event (score increased)."""
        with self._lock:
            if self._blink_state == "idle":
                self._start_blink_sequence()
            else:
                self._blink_pending = True
        self._wake.set()

    def tick(self, dt: float):
        """Advances the effect by dt seconds. Called by the background thread
        (tests call it directly with start_thread=False)."""
        with self._lock:
            if self._blink_state != "idle":
                self._tick_blink(dt)
            else:
                self._tick_base(dt)

    def cleanup(self):
        """Stop the thread, turn the LED off and release it. Idempotent."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        with self._lock:
            backend, self._backend = self._backend, None
            self._active = False
            self._blink_state = "idle"
            self._blink_pending = False
        if backend is not None:
            try:
                backend.close()
            except Exception as exc:
                print(f"[led] WARNING: could not switch the LED off: {exc}")

    # -- internal -----------------------------------------------------------

    def _run(self):
        last = time.monotonic()
        while not self._stop.is_set():
            self._wake.wait(_BLINK_STEP_SEC if self._blink_state != "idle"
                            else _FADE_STEP_SEC)
            self._wake.clear()
            if self._stop.is_set():
                break
            now = time.monotonic()
            self.tick(now - last)
            last = now

    def _tick_base(self, dt: float):
        if self._active:
            self._set(1.0)
            self._fade_t = 0.0   # the next idle fade starts from dark
        else:
            self._fade_t += dt
            phase = (self._fade_t % FADE_PERIOD_SEC) / FADE_PERIOD_SEC
            # Cosine easing: no visible corner at the brightest/dimmest points.
            wave = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
            self._set(wave ** FADE_GAMMA)

    def _tick_blink(self, dt: float):
        self._blink_phase_t += dt
        if self._blink_state == "on":
            self._set(1.0)
            if self._blink_phase_t >= BLINK_ON_TIME_SEC:
                self._set(0.0)
                self._blink_state = "off_gap"
                self._blink_phase_t = 0.0
        elif self._blink_phase_t >= BLINK_OFF_TIME_SEC:
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
                # else the next tick resumes the fade / steady light

    def _start_blink_sequence(self):
        # The first flash is written by the next tick, which the wake event
        # triggers at once, so all hardware writes stay on one thread.
        self._blinks_left = BLINKS_PER_SEQUENCE
        self._blink_phase_t = 0.0
        self._blink_state = "on"
        if self._thread is None:
            self._set(1.0)

    def _set(self, level: float):
        if self._backend is None or level == self._level:
            return
        try:
            self._backend.set(level)
            self._level = level
        except Exception as exc:
            if self._level != "failed":
                print(f"[led] WARNING: LED write failed: {exc}")
                self._level = "failed"


def force_off(pin: int = GPIO_PIN):
    """Switch the strip off from outside the patient process -- used after it
    has exited (cleanly or not). The kernel PWM keeps its last brightness when
    a process is killed, so this must be run explicitly. Never raises."""
    try:
        channel = KernelPwm.find_channel(pin)
        if channel is not None:
            KernelPwm(channel).close()
            return
        GpiozeroPwm(pin).close()
    except Exception as exc:
        if sys.platform.startswith("linux"):
            print(f"[led] could not force the LED off: {exc}")


def _main(argv) -> int:
    command = argv[0] if argv else "status"
    if command == "off":
        force_off()
        return 0
    if command not in ("status", "test"):
        print("usage: python3 -m hardware.led_feedback status | test | off")
        return 2
    led = LedFeedback()
    print(f"[led] backend: {led.backend_name}")
    if command == "test" and led.backend_name != "none":
        try:
            print("1/4  idle fade (12 s)");           time.sleep(12)
            print("2/4  steady game light (5 s)");    led.set_active(True); time.sleep(5)
            print("3/4  three scoring flashes, 3 times")
            for _ in range(3):
                led.request_blink();                  time.sleep(2)
            print("4/4  back to idle fade (6 s)");    led.set_active(False); time.sleep(6)
        except KeyboardInterrupt:
            print("interrupted")
    ok = led.backend_name == "kernel"
    led.cleanup()
    print("[led] off")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
