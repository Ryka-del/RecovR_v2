# RecovR — Final Game Mechanics & Difficulty Configuration Report

This document is the Phase 1/Phase 2 deliverable for the Game Mechanics Verification
and Difficulty Configuration task: a verified, game-by-game breakdown of each game's
final mechanics after implementation, including sensor inputs, scoring, randomization,
Target/Timed Mode behavior, and the final Easy/Medium/Hard difficulty parameters.

All values below reflect the actual code at the time of writing (independently
verified against the game files, not just design intent).

## Shared mechanics (all 10 games)

- **Target Mode** ends when `score >= goal` (changed from `reps >= goal` — necessary
  since several games now award variable points per action, e.g. a rare item worth
  more than a common one, or a penalty for a wrong catch).
- **Timed Mode** ends when the countdown reaches 0; every game checks this *after*
  that frame's own scoring, so a score landing exactly on the final tick is never
  dropped.
- **Difficulty** is chosen once per session, after calibration finishes, from
  whichever Easy/Medium/Hard preset the therapist picks on the Calibration Results
  screen (there is no pre-calibration difficulty picker anymore — see "Game
  Configuration flow" below).
- **Threshold rule**: every "Required Grip Strength" / "Required Finger Flexion" /
  "Required Wrist Rotation" parameter, in every game that has one, uses the same
  Easy = 30% / Medium = 70% / Hard = 90% anchor — expressed as a fraction of *that
  patient's own* calibrated resting→peak (or resting→average) range, never a raw,
  patient-independent number.

## Game Configuration flow change

The old 3-step wizard (Choose Game → Session Mode → **Session Settings**) is now a
2-step wizard (Choose Game → Session Mode). The removed "Session Settings" step's two
responsibilities — difficulty, and the Target-score/Timed-duration goal — are now
decided **after calibration** instead, on the existing Calibration Results screen
(Easy/Medium/Hard preset picker, with an auto-computed recommendation from the
patient's own calibration data) and its Advanced Settings screen (per-game numeric
overrides). This reuses the existing calibration architecture rather than duplicating
it — no new UI was built for this.

---

## 1. Basketball

**Objective & sequence**: How-To-Play card (min. 2.5s) → patient squeezes to raise a
pointer against a drifting green zone on a vertical bar → releasing while the pointer
is inside the zone shoots the ball at a fixed hoop.

**Sensor inputs**: `grip` only. A squeeze is recognized once the calibration-normalized
grip exceeds `self.grip_threshold`.

**Scoring**: +1 per successful release-in-zone. No decrement for a miss.

**Randomization**: none affecting scoring — only the ball's cosmetic rest position
(left/right of hoop) is randomized each round.

**Gameplay parameters**: `ZONE_WIDTH` (green zone width), `self.ramp_up` (pointer rise
rate).

**Target Mode**: ends after the made shot's flight animation finishes, once score ≥
goal.

**Timed Mode**: ends on countdown expiry, checked after scoring.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`bb_goal`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Target Zone Size (`bb_zone_width`) | 25% | 16% | 9% |
| Required Grip Strength (`bb_grip_threshold`) **NEW** | 30% | 70% | 90% |
| Pointer Speed (`bb_pointer_speed`) **NEW** | 0.5/s | 0.8/s | 1.1/s |

**Known issue (flagged, not fixed — out of scope)**: `ZONE_SPEED` (zone drift speed)
is dead code, unconditionally overwritten by the separate Slow/Normal/Fast speed
dropdown.

---

## 2. Lemonade

**Objective & sequence**: squeeze past a threshold, hold for a duration, release to
commit one lemon; every 10th lemon triggers a pitcher-pour animation.

**Sensor inputs**: `grip` only, with a hysteresis band (release threshold = 0.78× the
squeeze threshold).

**Scoring**: +1 per completed lemon. Releasing early discards that attempt with no
penalty.

**Randomization**: none.

**Gameplay parameters**: `HOLD_DURATION` (unchanged — 0.8/1.2/1.6s).

**Target Mode**: ends after the final lemon's pour animation finishes.

**Timed Mode**: ends on countdown expiry.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`lem_target`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Required Grip Strength (`lem_grip_threshold`) | 30% | 70% | 90% |

---

## 3. Tile Rush

**Objective & sequence**: one tile falls per lane at a time (5 lanes); the correct
finger must flex while the tile is within the hit window of the hit line.

**Sensor inputs**: 5 independent finger-flex channels, each calibrated separately.

**Scoring**: +1 per hit tile; a miss resets the on-screen combo counter only (score
unaffected).

**Randomization**: lane choice is uniform random 0–4; one tile is active at a time.

**Gameplay parameters**: `SPAWN_GAP`, `HIT_WINDOW` (both unchanged).

**Target Mode**: ends immediately on the qualifying tap.

**Timed Mode**: ends on countdown expiry, checked after that frame's finger presses.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`pt_goal`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Tile Speed (`pt_tile_speed`) | 260 px/s | 340 px/s | 420 px/s |
| Required Finger Flexion (`pt_flex_threshold`, fallback only) | 30% | 70% | 90% |

**Fixed this phase**: Tile Speed used to be silently overwritten by the generic Speed
dropdown and never actually reached gameplay — it now does.

---

## 4. Whack-a-Mole

**Objective & sequence**: up to N moles active at once (difficulty-dependent), each in
a random hole, must be hit with its assigned finger within the mole's appearance
window.

**Sensor inputs**: 5 independent finger-flex channels.

**Scoring**: tiered — Common 1pt, Rare 3pts, Epic 5pts (previously a flat 1pt for
every mole regardless of its cosmetic sprite).

**Randomization**: mole tier — Common 80%, Rare 15%, Epic 5% (verified by a 300,000-
sample simulation: 80.0% / 15.0% / 5.0%). Hole choice always excludes currently-
occupied holes.

**Target Mode**: ends the instant score ≥ goal.

**Timed Mode**: ends on countdown, deferred if a hit is mid-swing so an earned point
is never lost.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`wm_goal`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Mole Appearance Duration (`wm_mole_duration`) | 3.0s | 2.5s | 2.0s |
| Simultaneous Mole Count (`wm_simultaneous`) **NEW** | 1 | 1 | 2 |
| Required Finger Flexion (`wm_flex_threshold`, fallback only) | 30% | 70% | 90% |

**New this phase**: this game previously had zero Advanced Settings coverage at all,
and every mole scored the same regardless of its sprite — both gaps are closed.

---

## 5. Apple Catching

**Objective & sequence**: objects fall continuously; the basket tracks wrist tilt;
catching is a geometric overlap between the object and the basket's opening.

**Sensor inputs**: `tilt_x` (wrist), now gated by a calibration-relative deadzone
before the basket moves at all (previously the BLE-connected path had no deadzone at
all, while Test Mode used a hardcoded, non-calibrated one — now unified).

**Scoring**: Normal apple +1, Golden +3, Rainbow +5, Insect **−2** (previously +3 — now
correctly a penalty), missed apple 0.

**Randomization**: a flat top-level roll — Insect 15%, Normal 70%, Golden 10%, Rainbow
5% (verified by simulation: 15.1% / 69.9% / 10.0% / 5.0%; previously a nested
15%-then-85%-split roll that did not match these odds).

**Feedback**: the basket visually shakes on an insect **catch** and on any apple-type
**miss** — never on an apple catch or an insect miss (there is no physical vibration
motor in the hardware; this reuses the existing shake effect).

**Target Mode**: ends immediately on the scoring catch.

**Timed Mode**: ends on countdown, checked last.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`ac_goal`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Apple Falling Speed (`ac_apple_speed`) | 260 px/s | 380 px/s | 520 px/s |
| Simultaneous Object Count (`ac_simultaneous`) **NEW** | 1 | 1 | 2 |
| Required Wrist Rotation (`ac_wrist_requirement`) **NEW** | 30% | 70% | 90% |

---

## 6. Key and Lock

**Objective & sequence**: rotate the wrist to a randomly-rolled target angle, hold
within tolerance for the required duration, repeat for the lock's required number of
turns.

**Sensor inputs**: `tilt_x` (wrist), now gated by a new minimum-rotation requirement in
addition to the existing angle-precision tolerance — two separate, composed checks
(rotation amount, then angle accuracy).

**Scoring**: Common lock 3pts, Legendary lock 7pts (previously 1/5).

**Randomization**: lock type — Legendary 15% (previously 20%), Common 85%.

**Turns required**: now **flat by lock type only**, no longer difficulty-scaled —
Common = 2 turns, Legendary = 4 turns, always (previously scaled 1–3 and 3–5 by
difficulty).

**Target Mode**: ends right after an unlock, if score ≥ goal.

**Timed Mode**: ends on countdown, checked after that frame's turn logic.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`kl_goal`) | 80 pts | 120 pts | 160 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Wrist Angle Tolerance (`kl_tolerance`, unchanged) | 15° | 8° | 3° |
| Required Hold Duration (`kl_hold_time`, unchanged) | 2.0s | 2.0s | 2.0s |
| Required Wrist Rotation (`kl_wrist_requirement`) **NEW** | 30% | 70% | 90% |

---

## 7. Steady Aim

**Objective & sequence**: aim a cursor (2-axis wrist tilt) at a randomly-positioned
hanging target, hold inside the aim-tolerance circle to auto-fire.

**Sensor inputs**: both tilt axes, now gated by a new calibration-relative
wrist-rotation requirement before the cursor responds at all (replaces the old flat
0.05 deadzone).

**Scoring**: consolidated from 5 zones to exactly 3 — Innermost 5pts, Middle 3pts,
Outermost 1pt, Miss 0 (boundary radii set at 0.35 / 0.65 / 0.85 of the target face).

**Randomization**: unchanged — target sprite (cosmetic rope length only) and
horizontal spawn position, both uniform random with a no-immediate-repeat rule. No
target-speed/movement mechanic exists or was added, per the explicit constraint to
preserve existing target generation and aiming/bow/arrow mechanics.

**Gameplay parameters**: `AIM_TOLERANCE_R` (the hold-still precision radius) is now a
**frozen flat constant (80px)**, no longer difficulty-scaled — the spec names only one
difficulty parameter for this game.

**Target Mode**: ends right after a scoring impact, if score ≥ goal.

**Timed Mode**: ends on countdown, or earlier if arrows run out (ends as "stopped," an
incomplete session).

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`sa_goal`) | 80 pts | 120 pts | 160 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Cursor Sensitivity / Hold Duration / Arrows Available (unchanged) | 900, 3.0s, 20 | 1000, 3.0s, 16 | 1100, 3.0s, 14 |
| Required Wrist Rotation (`sa_wrist_requirement`) **NEW** | 30% | 70% | 90% |

**Pre-existing limitation (flagged, not fixed)**: both tilt axes share this game's one
wrist calibration pass rather than two independent passes.

---

## 8. Toy Factory

**Objective & sequence**: toys scroll on a conveyor; grip past a threshold grabs one,
moving it to the correct sorting box scores.

**Sensor inputs**: `grip` is the sole real gate for grabbing. Finger Flexion is exposed
as an Advanced Settings slider but is cosmetic/informational only — it does not gate
the grab (a deliberate decision, to avoid destabilizing a working mechanic).

**Scoring**: +1 correct sort, 0 wrong sort. A wrongly-sorted toy returns to its own
conveyor slot for another attempt (confirmed already correct, left untouched).

**Randomization**: toy type is uniform random among all 12 keys, no weighting.

**Gameplay parameters**: Conveyor Speed, Pickup Tolerance, Box-Placement Tolerance (all
unchanged).

**Target Mode / Timed Mode**: unchanged end-condition structure.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`tf_goal`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Conveyor Speed / Pickup Tolerance / Box Tolerance (unchanged) | 90px/s, 110px, 125% | 140px/s, 85px, 100% | 200px/s, 65px, 80% |
| Required Grip Strength (fallback only) | 30% | 70% | 90% |
| Required Wrist Rotation (calibration-relative deadzone) | 30% | 70% | 90% |
| Required Finger Flexion (`tf_flex_threshold`) **NEW, cosmetic/advanced-only** | 30% | 70% | 90% |

---

## 9. Purrfect Feast

**Objective & sequence**: tilt to the bowl, grip to grab/fill, carry to the cat,
release to feed.

**Sensor inputs**: `grip` is the sole real gate (same decision as Toy Factory —
Finger Flexion is exposed but cosmetic-only).

**Scoring**: +1 per fed cat.

**Randomization**: cat breed is uniform random, with a no-immediate-repeat rule.

**Gameplay parameters**: Wrist Movement Sensitivity, Positioning Tolerance (both
unchanged; a drift between this game's own tolerance numbers and its Advanced Settings
schema preset was found and fixed — both now read 180 / 135 / 95px).

**Target Mode / Timed Mode**: unchanged structure.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`ftc_target_cats`) | 50 pts | 75 pts | 100 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Required Grip Strength (`ftc_grip_threshold`) | 30% | 70% | 90% |
| Required Finger Flexion (`ftc_flex_threshold`) **NEW, cosmetic/advanced-only** | 30% | 70% | 90% |

---

## 10. Garden Wonders

**Objective & sequence**: pick up a seed (flex), plant it, water it the required
number of times (now wrist-gated), full growth scores.

**Sensor inputs**: grip (can/seed pickup), finger flexion (seed pickup/planting,
unchanged), and — new this phase — wrist rotation now gates the watering action
itself (previously watering was grip-gated, which never matched the real-world
"pouring" motion).

**Scoring**: tiered by rarity — Common 3pts, Rare 5pts, Epic 7pts (previously a flat
1pt for every plant).

**Randomization**: rarity is now rolled **at planting time** (previously at
full-growth time) — Common 70%, Rare 20%, Epic 10%, unchanged odds.

**Watering count**: tiered by that same rarity roll — Common 2 waterings, Rare 3, Epic
5 (previously a flat 2 for every plant regardless of type).

**Target Mode**: ends right after a plant finishes growing, if score ≥ goal.

**Timed Mode**: ends on countdown, correctly deferred around the cycle-pause screen.

**Difficulty parameters (final)**:

| Param | Easy | Medium | Hard |
|---|---|---|---|
| Target Score (`ptg_goal`) | 80 pts | 120 pts | 160 pts |
| Timed Duration | 5 min | 7 min | 10 min |
| Wrist Movement Sensitivity / Positioning Tolerance / Watering Hold Duration (unchanged) | 5%, 130px, 0.8s | 8%, 100px, 1.2s | 12%, 70px, 1.6s |
| Required Grip Strength (`ptg_grip_threshold`, pickup only now) | 30% | 70% | 90% |
| Required Finger Flexion (`ptg_flex_threshold`) | 30% | 70% | 90% |
| Required Wrist Rotation (`ptg_wrist_requirement`) **NEW, gates watering** | 30% | 70% | 90% |

---

## Files changed in this phase

- `games/session_mode.py` — Target Mode now checks `score >= goal`.
- `scenes/calibration_window.py` — full `GAME_PARAM_SCHEMA` rewrite (all 10 games),
  `_recommend_difficulty` rebanded to the 50%/80% cutoffs, `DIFFICULTY_PRESETS`
  rebanded to 30/70/90.
- `scenes/therapist_dashboard.py` — Session Settings step removed; difficulty now
  synced from the calibration Results screen; related dead code removed.
- All 10 `games/*.py` files — per-game changes itemized above.

## Verification performed

- `python -m py_compile` across all 10 game files and the 3 shared files — passes.
- Independent probability simulations (300,000 samples each) for Whack-a-Mole's
  80/15/5 tier split and Apple Catching's 15/70/10/5 spawn split — both within 0.1
  percentage points of spec.
- Manual code review of the Garden Wonders per-plot rarity/watering-count state
  machine and the Apple Catching/Whack-a-Mole multi-entity refactors.
- Confirmed Affected-Hand Adaptation (`hand_flipped`) is untouched in all 6 games that
  implement it.
