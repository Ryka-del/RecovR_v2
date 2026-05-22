# RecovRWE — Complete Software Workflow

## Overview

RecovRWE is a gamified hand rehabilitation system for stroke patients. It is operated by a licensed therapist who manages patients, configures rehabilitation games, runs therapy sessions, and reviews progress data. This document describes every screen, panel, state, and navigation path in the software.

---

## Navigation Map

```
THERAPIST WELCOME
    └──[Start]──► LOGIN
                    ├──[Add Account]──► REGISTRATION ──► LOGIN
                    ├──[Select Account]──► PIN ENTRY
                    │                        └──[Correct PIN]──► SECURITY QUESTIONS SETUP (first login)
                    │                                                └──[Save & Continue]──► THERAPIST DASHBOARD
                    └──[Forgot PIN]──► PIN RESET FLOW ──► LOGIN

THERAPIST DASHBOARD
    ├── Panel 0: Patient List
    │       ├──[Register Patient]──► Panel 6: Register Patient Form
    │       ├──[Select Patient]────► Panel 4: Game Configuration
    │       │                              └──[Next]──► Panel 5: Start Session
    │       │                                                ├──[Calibrate]──► Calibration Window
    │       │                                                └──[Start]──────► GAME SCENE ──► Dashboard
    │       ├──[Edit Patient]──► Edit Patient Modal
    │       └──[Share Patient]──► Share Patient Modal
    ├── Panel 1: Session History
    ├── Panel 2: Analytics
    ├── Panel 3: Calibration Records
    ├──[Edit Profile]──► Edit Profile Modal
    └──[Logout]────────► LOGIN
```

---

## 1. Therapist Welcome Screen

**Purpose:** App entry point.

| Element | Action |
|---------|--------|
| "RecovR" logo + subtitle "Gamified Hand Rehabilitation System" | Display only |
| **Start** button | → Login screen |

A fade-in animation and welcome sound play on load.

---

## 2. Login Screen

### 2A. Account Selection

**Purpose:** Choose which therapist account to log into.

| Element | Description |
|---------|-------------|
| Account circles | One per registered therapist; shows avatar icon and username below |
| Hover effect | Circle lifts and glows |
| **Add Account (+)** button | → Registration screen (max 23 accounts; shows limit modal if full) |
| **← Back** link | → Therapist Welcome |

Click any account circle to open PIN Entry for that account.

---

### 2B. PIN Entry

**Purpose:** Authenticate with a 4-digit PIN.

| Element | Description |
|---------|-------------|
| Account avatar + full name | Shows selected account |
| 4 PIN boxes | Filled with dots as digits are typed |
| Attempt counter | Dots showing remaining attempts (max 5) |
| **Forgot PIN?** link | → PIN Reset Flow |
| Tap outside panel | Cancels and returns to Account Selection |

- Type digits on keyboard (0–9). Auto-submits on 4th digit.
- Wrong PIN: shake animation, error message, attempt counter decrements.
- After **5 failed attempts**: account locks for **1 hour**.

---

### 2C. Lock Screen

**Purpose:** Block access after too many failed attempts.

| Element | Description |
|---------|-------------|
| Red lock icon on avatar | Visual indicator of lock |
| "Account Locked" heading | Red text |
| Countdown timer MM:SS | Real-time countdown to unlock |
| Explanatory text | "After 5 incorrect attempts the account is locked for 1 hour." |
| Tap outside | Returns to Account Selection |

The lock clears automatically when the timer reaches 0:00.

---

### 2D. Forgot PIN — PIN Reset Flow

**Purpose:** Reset a forgotten PIN in three steps.

#### Step 1: Enter New PIN
- Heading: *"Reset Password: Enter New 4-Digit PIN"*
- 4 PIN entry boxes
- Hint: *"Use number keys to assign value"*
- Auto-advances to Step 2 after 4 digits entered.

#### Step 2: Confirm New PIN
- Heading: *"Confirm New 4-Digit PIN Assignment"*
- 4 PIN entry boxes
- If PINs don't match → error, restarts at Step 1.
- If PINs match AND account has security questions → advances to Step 3.
- If PINs match AND no security questions → PIN saved immediately, shows success.

#### Step 3: Security Questions Verification *(only if security questions are set)*
- Heading: *"Verify Your Identity"*
- 3 text input fields, one per security question
- Shows the question text above each field
- **Confirm Reset** button at bottom
- Press **ESC** or tap outside to cancel the entire flow.
- Wrong answers → error, all fields clear, try again.
- Correct answers → PIN saved, shows *"PIN Updated Successfully!"* for 1.5 s → returns to Account Selection.

---

### 2E. Security Questions Setup Overlay

**Purpose:** Ensure every account has 3 security questions on file.
Shown automatically after a successful login if the account has no security questions yet.

| Element | Description |
|---------|-------------|
| Title | "Set Up Security Questions" |
| Instruction | "Choose 3 different security questions and provide answers." |
| 3 Q&A blocks | Each has a question dropdown + answer text field |
| **Save & Continue** button | Saves questions and proceeds to dashboard |

**Rules:**
- All 3 questions must be selected.
- All 3 answers must be filled in.
- Each question must be different (no duplicates).

**Available Security Questions (choose 3):**
1. What was the name of your first pet?
2. What is your mother's maiden name?
3. What city were you born in?
4. What was the name of your elementary school?
5. What is your oldest sibling's middle name?
6. What was the make of your first car?
7. What is your favorite movie?
8. What was your childhood nickname?

---

## 3. Registration — Create New Account

### Step 1: Account Information

**Layout:** Left column (icon picker) + right column (form fields)

**Icon Picker (left):**
- Large preview circle shows currently selected icon.
- Grid of 10 small icons below — click to select.
- Selected icon shows blue border.

**Form Fields (right):**

| # | Field | Type | Rules |
|---|-------|------|-------|
| 1 | Full Name | Text | Required, max 50 chars |
| 2 | Username | Text | Letters only, no spaces, max 15 chars, must be unique |
| 3 | Role | Dropdown | Physical Therapist / Occupational Therapist / Other |
| 4 | Workplace | Text | Required, max 60 chars |
| 5 | 4-Digit PIN | Masked text | Digits only, exactly 4 digits |
| 6 | Confirm PIN | Masked text | Must match PIN field |

**Navigation:**
- **Register** button → validates all fields → if OK, creates account and advances to Step 2.
- *"Already have an account? Login"* link → Login screen.
- **← Back** link → Login screen.

Error messages appear in red above the Register button.

---

### Step 2: Security Questions Setup

Same as the Security Questions Setup Overlay (§2E).
On completion → redirects to the **Login** screen.

---

## 4. Therapist Dashboard

### Layout

| Zone | Content |
|------|---------|
| Left sidebar (20% width) | Logo · Welcome greeting · Navigation menu · Edit Profile · Logout |
| Right content area (80% width) | Active panel content |

### Sidebar Navigation

| Icon | Label | Panel |
|------|-------|-------|
| 👤 | Patient List | Panel 0 |
| 📋 | Session History | Panel 1 |
| 📊 | Analytics | Panel 2 |
| 🎯 | Calibration Records | Panel 3 |

Clicking a nav item switches the right content area to that panel.

### Home Screen (default)

2 × 2 grid of shortcut cards — equivalent to clicking the sidebar items above.

---

## 5. Panel 0 — Patient List

**Purpose:** View, search, manage, and register patients.

### Patient Search
- Search field at top: filter by name or patient ID (RCVR-XXXX).
- Live filtering — updates instantly as you type.

### Patient Table

| Column | Description |
|--------|-------------|
| Name | Full patient name |
| ID | Auto-generated ID (e.g., RCVR-0001) |
| Age | Patient age |
| Affected Hand | Left / Right |
| Severity | Mild / Moderate |
| Actions | Edit · Share buttons |

- Click a patient row → proceeds to **Panel 4: Game Configuration** with that patient selected.

### Actions
- **Edit (✏)** — opens Edit Patient modal.
- **Share (🔗)** — opens Share Patient modal.
- **Register a New Patient** link at bottom → **Panel 6: Register Patient**.

---

### Edit Patient Modal

Fields:

| Field | Type |
|-------|------|
| Full Name | Text |
| Age | Number |
| Sex | Dropdown (Male / Female / Prefer not to say) |
| Dominant Hand | Dropdown (Left / Right) |
| Affected Hand | Dropdown (Left / Right) |
| Stroke Type | Dropdown (Ischemic / Hemorrhagic / Unknown) |
| Date of Stroke | Text (date) |
| Months Since Stroke | Number |
| Severity | Dropdown (Mild / Moderate) |
| Notes – Stiffness | Text area |
| Notes – Pain | Text area |
| Notes – Therapist | Text area |

Buttons: **Save** · **Cancel** · **Delete Patient** (red, triggers confirmation).

---

### Share Patient Modal

- Search by therapist username (live suggestions appear).
- Click a suggestion → confirm share dialog.
- Already-shared therapists listed with a **Revoke Access** button.

---

## 6. Panel 1 — Session History

**Purpose:** Review all past game sessions.

| Column | Description |
|--------|-------------|
| Patient Name | Who played |
| Date & Time | When session occurred |
| Game | Which game was played |
| Duration | Session length |
| Score | Points or accuracy |
| Difficulty | Easy / Medium / Hard |

Sessions are ordered newest first. Click a row to see full details.

---

## 7. Panel 2 — Analytics

**Purpose:** Track patient progress over time.

Displays computed metrics across all sessions:
- Total sessions completed
- Average score per game type
- Per-patient score trend graphs
- Sessions per patient bar chart
- Average session duration

---

## 8. Panel 3 — Calibration Records

**Purpose:** Review sensor calibration history.

| Column | Description |
|--------|-------------|
| Patient | Who was calibrated |
| Game | Which game the calibration was for |
| Sensor | Sensor type used |
| Sensitivity | Low / Medium / High |
| Average | Average sensor reading across 3 trials |
| Threshold | Calculated activation threshold |
| Date | When calibration was performed |

---

## 9. Panel 4 — Game Configuration

**Purpose:** Select a game and configure session parameters for the selected patient.

**Patient name** is shown at the top. Navigate here by clicking a patient in Panel 0.

### Game Selection

| Game | Skill Targeted |
|------|---------------|
| Basketball | Grip Strength |
| Piano Tiles | Finger Flexion |
| Steady Aim | Wrist Rotation |

Click a game card to select it (blue highlight).

### Session Parameters

| Parameter | Options |
|-----------|---------|
| Duration | 60 s · 120 s · 180 s · Custom |
| Difficulty | Easy · Medium · Hard · Custom |
| Speed | Slow · Normal · Fast |
| Sensitivity | Low · Medium · High |
| Resistance | Soft Ball · Medium Ball · Hard Ball |

**Smart Preset** button applies recommended settings based on patient severity:
- Mild → 60 s, Normal, Medium sensitivity, Medium difficulty
- Moderate → 60 s, Normal, Medium sensitivity, Easy difficulty

**Next** button → Panel 5: Start Session.

---

## 10. Panel 5 — Start Rehabilitation Session

**Purpose:** Run calibration and launch the game session.

### Session Summary
Read-only recap of selected patient, game, and parameters.

### Calibration

| Status | Meaning |
|--------|---------|
| 🟡 Not Started | No calibration done yet |
| 🟢 Complete | Sensor calibration accepted |
| 🔴 Mismatch | Calibration was for a different game type |

- **Calibrate** button → opens Calibration Window.
- **Bypass Calibration** toggle → skip calibration (development/testing only).
- If a mismatch is detected when attempting to start, a warning modal appears.

### Start Session
- Blue **Start Session** button (enabled only when calibration is complete or bypassed).
- Click → launches the selected game full-screen.

---

## 11. Calibration Window

**Purpose:** Measure the patient's maximum effort for sensor configuration.

### Phase 1 — Sensitivity Selection

- Choose sensor sensitivity: **Low · Medium · High**
- Description of what calibration does:
  - Runs 3 trials measuring maximum effort
  - Calculates average across all trials
  - Recommends parameters per difficulty
  - Sets a personalized activation threshold
- Click **Begin Calibration →**

### Phase 2 — Countdown (per trial)
- "Trial X of 3 — Get Ready!"
- Countdown: 3… 2… 1…

### Phase 3 — Recording (per trial)
- "Trial X of 3 — Recording"
- Live sensor bar showing real-time input
- Timer counting down the recording window
- 3 trial progress dots at bottom

### Phase 4 — Trial Complete
- Shows trial result value
- Auto-advances to next trial or to Phase 5 after 3 trials.

### Phase 5 — Results

**Left column:** Trial summary
- 3 trial bars with individual values
- Calculated average
- Sensitivity summary

**Right column:** Recommended Presets
| Preset | Threshold | Description |
|--------|-----------|-------------|
| Easy | Lower % | Wider activation window |
| Medium | Mid % | Balanced |
| Hard | Higher % | Requires stronger effort |

- Click a preset card to select it.
- **▼ Advanced Settings** (expandable):
  - Threshold % (30 / 40 / 50 / 60 / 70 / 80 / 90)
  - Speed (Slow / Normal / Fast)
  - Duration (60 s / 120 s / 180 s / Custom)

**Buttons:**
- **↺ Retry** — restart calibration from Phase 1.
- **✓ Accept & Continue** — save results and return to Start Session panel.

---

## 12. Game Scenes

All games are full-screen. A crossfade transition plays when entering and exiting.
Session results (score, duration, difficulty) are saved to the database automatically when the game ends.

---

### Game 1 — Basketball (Grip Strength)

**How to play:**
- A ball and a basket are on screen.
- Squeeze the grip controller to shoot the ball upward.
- A moving zone indicator shows the target strength window.
- If the ball lands in the basket = point scored.

| Difficulty | Zone Width | Zone Speed | Goal |
|------------|-----------|-----------|------|
| Easy | 25% of bar | Stationary | 10 baskets |
| Medium | 16% of bar | Slow movement | 15 baskets |
| Hard | 9% of bar | Fast movement | 20 baskets |

**Metrics saved:** Successful shots · Total attempts · Accuracy %

---

### Game 2 — Piano Tiles (Finger Flexion)

**How to play:**
- 5 vertical lanes (one per finger: A S D F G keys).
- Colored tiles fall from the top.
- Press the corresponding key when a tile reaches the hit zone at the bottom.
- Tiles that pass the zone count as a miss.

| Difficulty | Fall Speed | Spawn Rate |
|------------|-----------|-----------|
| Easy | 280 px/s | 1 tile/s |
| Medium | 420 px/s | 1.4 tiles/s |
| Hard | 580 px/s | 2.2 tiles/s |

**Metrics saved:** Tiles hit · Tiles missed · Accuracy % · Combo streak

---

### Game 3 — Steady Aim (Wrist Rotation)

**How to play:**
- Circles appear at random positions on screen.
- Move the cursor (via wrist rotation) into the circle.
- Hold the cursor inside the circle for the required duration to score.

| Difficulty | Circle Radius | Hold Time | Goal |
|------------|--------------|-----------|------|
| Easy | 120 px | 1.5 s | 8 circles |
| Medium | 80 px | 2.0 s | 10 circles |
| Hard | 45 px | 2.5 s | 12 circles |

**Metrics saved:** Circles completed · Attempts · Average hold time · Accuracy %

---

## 13. Modals & Overlays

### Edit Profile Modal
- Triggered by: **Edit Profile** link in sidebar.
- Same fields as registration + optional new PIN.
- **Delete Account** button (red) → confirmation dialog → if confirmed, account deleted and app returns to Therapist Welcome.

### Logout Confirmation Modal
- Triggered by: **Logout** button in sidebar.
- *"Are you sure you want to log out?"*
- **Yes, log out** → Login screen.
- **Cancel** → stays on dashboard.

### Account Limit Modal
- Triggered by: Clicking **Add Account** when 23 accounts already exist.
- Shows limit message with an OK button to dismiss.

### Register Patient Success Modal
- Triggered by: Successfully submitting the Register Patient form.
- Shows patient name and auto-generated RCVR-XXXX ID.
- **OK** button → navigates to Patient List where the new patient is visible.

### Calibration Mismatch Modal
- Triggered by: Starting a session when calibration was done for a different game type.
- *"Game type changed. Recalibrate for accuracy?"*
- **Calibrate Now** → opens Calibration Window.
- **Cancel** → stays on Start Session panel.

---

## 14. Panel 6 — Register Patient Form

**Purpose:** Add a new patient to the system.

| Field | Type | Notes |
|-------|------|-------|
| Full Name | Text | Required |
| Age | Number | Required |
| Sex | Dropdown | Male / Female / Prefer not to say |
| Dominant Hand | Dropdown | Left / Right |
| Affected Hand | Dropdown | Left / Right — Required |
| Stroke Type | Dropdown | Ischemic / Hemorrhagic / Unknown |
| Date of Stroke | Text | |
| Months Since Stroke | Number | |
| Severity | Dropdown | Mild / Moderate — Required |
| Notes – Stiffness | Text | |
| Notes – Pain | Text | |
| Notes – Therapist | Text | |

**Submit:** Validates required fields → inserts patient into database → shows success modal → returns to Patient List.

---

## 15. Close Button (✕)

A dark-red **✕** button is always visible in the **top-right corner** of the screen (except during active game sessions and while the Calibration Window is open). Click it at any time to close the application.

---

## 16. Data Stored per Session

Every completed game session automatically saves:

| Field | Source |
|-------|--------|
| Patient | Selected patient |
| Therapist | Logged-in account |
| Game | Selected game |
| Score | Game result |
| Duration | Session length in seconds |
| Difficulty | Selected difficulty |
| Timestamp | Date and time of play |

Calibration records are stored separately and include all 3 trial values, the average, threshold %, and the recommended preset that was accepted.

---

## 17. Audio Cues

| Event | Sound |
|-------|-------|
| Welcome screen loads | Startup tone |
| Any button / link click | UI click |
| Confirmation modal opens | Alert chime |
| Game session starts | Sci-fi start sound |
| Correct game action | Success catch sound |
| Missed game action | Blast/error sound |
| Session completes | Level complete fanfare |
| During gameplay | Looping sci-fi background music |
