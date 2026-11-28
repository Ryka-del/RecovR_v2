"""
Trial validation for the FSR402 grip sensor and the flex sensors.

Pure functions (no pygame, no hardware) used by scenes/calibration_window.py.
All values are on the app's normalised 0-1 scale (raw ADC / 4095).

The MPU6050 passes are deliberately not validated here: a tilt reading is not
an effort peak, so these rules do not apply to it.

TUNING -- the limits below are PROVISIONAL. Every pass prints its baseline,
noise and trial values with a "[cal]" prefix (see format_log), so they can be
re-checked against readings from the real glove.
"""

import statistics

PASSED       = "passed"
NO_MOVEMENT  = "no_movement"
INCONSISTENT = "inconsistent"
UNRELIABLE   = "unreliable"

STATUS_LABELS = {
    PASSED:       "Passed",
    NO_MOVEMENT:  "No movement",
    INCONSISTENT: "Inconsistent movement",
    UNRELIABLE:   "Unreliable reading",
}

# A trial counts as movement when it leaves the resting average by more than
# max(MIN_MOVEMENT, NOISE_SIGMAS * resting standard deviation).
MIN_MOVEMENT = 0.01     # the app's previous fixed movement threshold
NOISE_SIGMAS = 4.0      # clearly outside ordinary resting fluctuation

# A resting signal that varies more than this is too unsteady to measure from.
MAX_REST_NOISE = 0.04

# Repeatability: a trial is an outlier when its movement differs from the
# median of the three by more than
# max(REPEAT_MIN_ALLOWANCE, REPEAT_FRACTION * median).
# 0.04 is the widest trial-to-trial range among the steady sessions saved in
# recovr.db (17 Nov 2026, Whack-a-Mole and Basketball), where no trial was
# more than about 6% from its set's median. 25% leaves extra room for
# patients, whose effort varies more.
REPEAT_MIN_ALLOWANCE = 0.04
REPEAT_FRACTION      = 0.25

RAIL_LOW  = 0.005       # ADC pinned at 0    -> open or shorted wiring
RAIL_HIGH = 0.995       # ADC pinned at 4095 -> saturated or shorted wiring

# Consecutive frames (about 0.08 s at 60 fps) whose median must reach a value
# for it to count, so a single spike is never taken as the patient's effort.
SMOOTHING_FRAMES = 5


class TrialTracker:
    """Follows one sensor through one trial and keeps the highest and lowest
    SUSTAINED readings."""

    def __init__(self):
        self._window = []
        self.high = None
        self.low  = None

    def add(self, value):
        self._window.append(value)
        if len(self._window) > SMOOTHING_FRAMES:
            self._window.pop(0)
        if len(self._window) < SMOOTHING_FRAMES:
            return
        v = statistics.median(self._window)
        self.high = v if self.high is None else max(self.high, v)
        self.low  = v if self.low is None else min(self.low, v)

    def peak(self, baseline, bidirectional):
        """The reading that represents this trial's effort. Flex sensors may
        rise or fall when bent, so the side farther from rest wins. The grip
        sensor only rises with force."""
        if self.high is None:
            return baseline
        if bidirectional and baseline - self.low > self.high - baseline:
            return self.low
        return self.high


def rest_stats(samples):
    """(mean, standard deviation) of the resting-baseline samples."""
    if not samples:
        return 0.0, 0.0
    return statistics.fmean(samples), statistics.pstdev(samples)


def movement_threshold(noise):
    return max(MIN_MOVEMENT, NOISE_SIGMAS * noise)


def _trial_list(indexes):
    nums = ", ".join(str(i + 1) for i in indexes)
    return ("trial " if len(indexes) == 1 else "trials ") + nums


def evaluate(trials, baseline, noise, *, bidirectional, live, signal_lost=False):
    """Classifies one sensor's three trials.

    `live` is True when the readings came from the real controller; the
    hardware fault checks are meaningless for keyboard test input.

    Returns {"status", "detail", "baseline_fault"}. `baseline_fault` means the
    resting capture itself is bad, so repeating only the trials cannot help.
    """
    def result(status, detail="", baseline_fault=False):
        return {"status": status, "detail": detail, "baseline_fault": baseline_fault}

    # -- sensor / signal faults first: nothing else can be judged from them --
    if signal_lost:
        # A dropout during the resting capture also spoils the baseline.
        return result(UNRELIABLE, "controller signal dropped", True)
    if live:
        # A grip sensor legitimately rests at 0; a flex divider does not.
        if baseline >= RAIL_HIGH or (bidirectional and baseline <= RAIL_LOW):
            return result(UNRELIABLE, "stuck at its limit while resting", True)
        if bidirectional:
            pinned = [i for i, t in enumerate(trials)
                      if t <= RAIL_LOW or t >= RAIL_HIGH]
            if pinned:
                return result(UNRELIABLE, f"hit its limit in {_trial_list(pinned)}")
    if noise > MAX_REST_NOISE:
        return result(UNRELIABLE, "resting reading was unsteady", True)

    # -- movement ----------------------------------------------------------
    threshold = movement_threshold(noise)
    deltas = [t - baseline for t in trials]
    if not bidirectional:
        deltas = [max(0.0, d) for d in deltas]
    moved = [abs(d) >= threshold for d in deltas]

    if not any(moved):
        return result(NO_MOVEMENT, "no change from rest in any trial")
    if not all(moved):
        still = [i for i, m in enumerate(moved) if not m]
        return result(INCONSISTENT, f"no movement in {_trial_list(still)}")
    if len({d > 0 for d in deltas}) > 1:
        return result(INCONSISTENT, "direction changed between trials")

    # -- repeatability -----------------------------------------------------
    sizes = [abs(d) for d in deltas]
    middle = statistics.median(sizes)
    allowance = max(REPEAT_MIN_ALLOWANCE, REPEAT_FRACTION * middle)
    outliers = [i for i, s in enumerate(sizes) if abs(s - middle) > allowance + 1e-9]
    if outliers:
        return result(INCONSISTENT, f"{_trial_list(outliers)} differed from the others")

    return result(PASSED)


def format_log(name, trials, baseline, noise, outcome):
    values = ", ".join(f"{t:.4f}" for t in trials)
    return (f"[cal] {name}: baseline={baseline:.4f} noise={noise:.4f} "
            f"threshold={movement_threshold(noise):.4f} trials=[{values}] "
            f"-> {outcome['status']} {outcome['detail']}".rstrip())
