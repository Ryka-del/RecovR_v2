# Therapist Dashboard Guide

## File Overview
**therapist_dashboard.py** is the main UI scene for the RecovR therapist interface. It handles all therapist-facing screens including patient management, game configuration, session control, and profile editing.

---

## Key Sections

### 1. **Constants & Configuration** (Lines 45-119)
Defines all UI data structures and game parameters:
- **HOME_CARDS**: 4 home screen cards with labels and symbols
- **HOME_COLORS**: Colors for home cards
- **PANEL_TITLES & PANEL_COLORS**: Panel naming and color scheme
- **Game Lists**: SINGLE_SKILL_GAMES, INTEGRATED_GAMES, ALL_GAMES
- **Difficulty & Presets**: Game difficulty options and smart presets by severity
- **Data Options**: STROKE_TYPES, SEVERITY_OPTS, SEX_OPTS, HAND_OPTS, GAME_DURATION, ROLES

### 2. **Helper Functions** (Lines 125-157)
Reusable drawing utilities:
- `_card_bg()`: Draws semi-transparent card background with border
- `_empty_state()`: Renders empty state message (icon + heading + subtext + optional button)
- `_btn()`: Renders button with normal/hover color states

### 3. **TherapistDashboardScene Class** (Lines 163-1850+)
Main application class managing all UI state and logic.

---

## Scene State (active_panel values)

```
-1  = Home screen (4 cards)
 0  = Patient List
 1  = Session History
 2  = Analytics
 3  = Calibration Records
 4  = Game Configuration (reached via Patient List)
 5  = Start Session (reached via Game Configuration)
 6  = Register Patient (reached via Patient List)
```

---

## Constructor (__init__)

**Purpose**: Initialize all UI state, fonts, layout rectangles, and data structures.

**Key Initializations**:
```python
self.WIDTH, self.HEIGHT          # Screen dimensions
self.account                     # Current logged-in therapist
self.fnt                         # Dictionary of 20+ fonts (all scaled by screen height)
self.background_surface          # Pre-rendered gradient background
self.active_panel = -1           # Currently visible panel (-1 = home)
self.modal = None                # Active modal ("edit_profile", "logout_confirm", "delete_confirm", None)
self.selected_patient            # Currently selected patient for game config
self.alpha = 0                   # Fade-in animation value (0-255)
```

**Layout Setup**:
- `_build_nav_rects()`: Calculate positions for 4 sidebar nav items
- `_build_card_rects()`: Calculate 2x2 grid positions for home cards
- `_init_edit_fields()`: Create edit profile modal layout
- `_init_register_state()`: Initialize register patient form state
- `_init_game_config_state()`: Initialize game configuration state

---

## Event Handling

### `handle_event(event)` - Main Event Router
Routes pygame events to appropriate handlers:
- **Touch input** (pygame.FINGERDOWN): Converts normalized coords to pixels
- **Mouse input** (pygame.MOUSEBUTTONDOWN): Calls `_handle_click()`
- **Keyboard input** (pygame.KEYDOWN): Text input or navigation

### `_handle_click(pos)` - Click Dispatcher
Checks UI elements in priority order:
1. **Share modal** (if open) → `_handle_share_key()`
2. **Other modals** → confirmation dialogs
3. **Edit profile modal** → `_handle_edit_click()`
4. **Sidebar** → nav, edit link, logout
5. **Back button**
6. **Home cards** (if active_panel == -1)
7. **Panel-specific content** → dispatches to panel handler

---

## Main Update & Draw Loop

### `update(mouse_pos, dt)`
Called once per frame. Updates hover states for all UI elements:
- Checks which nav items/buttons/cards are under mouse
- Animates fade-in transition (alpha += 4 per frame)

### `draw(surface)`
Main rendering function. Draws in order:
1. Background gradient
2. Sidebar
3. Home screen OR Panel content
4. Modals (if any)
5. Fade transition overlay

---

## State Management

### Modal States
```python
self.modal = None                          # No modal active
self.modal = "edit_profile"                # Edit profile modal open
self.modal = "logout_confirm"              # Confirm logout dialog
self.modal = "delete_confirm"              # Confirm account deletion
```

### Panel Navigation
- `_open_panel(idx)`: Switch to panel idx, load patient data if needed
- `_go_back()`: Navigate back to previous screen
- `action_triggered`: Flag to trigger scene transition (returns "scene_name")

---

## Register Patient Panel (Panel 6)

**State Dict** (`self.rp`):
```python
self.rp = {
    "full_name": "",              # Patient name
    "age": "",                    # Patient age
    "sex": "",                    # Biological sex (dropdown)
    "dominant_hand": "",          # Dominant hand (dropdown)
    "affected_hand": "",          # Hand affected by stroke (dropdown)
    "stroke_type": "",            # Stroke type (dropdown)
    "date_of_stroke": "",         # Date of stroke
    "months_stroke": "",          # Months since stroke
    "severity": "",               # Hemiplegia severity (dropdown)
    "notes_stiffness": "",        # Clinical notes
    "notes_pain": "",             # Pain notes
    "notes_therapist": "",        # General notes
    
    # UI State
    "active_key": None,           # Currently focused text field
    "error": "",                  # Error message
    "success": "",                # Success message
    "sex_open": False,            # Dropdown open states
    "dominant_open": False,
    "affected_open": False,
    "stroke_open": False,
    "severity_open": False,
}
```

**Key Methods**:
- `_init_register_state()`: Reset form to empty
- `_rp_handle_click(pos)`: Handle form interactions
- `_rp_keydown(event)`: Handle text input
- `_rp_submit()`: Validate and save patient to DB
- `_draw_register_patient(surface, pa)`: Render panel

---

## Game Configuration Panel (Panel 4)

**State Dict** (`self.gc`):
```python
self.gc = {
    "selected_game": None,                # (game_name, game_type) tuple
    "duration": "6 minutes",              # Session duration
    "difficulty": "Moderate",             # Difficulty level
    "speed": "Normal",                    # Game speed
    "sensitivity": "Medium",              # Input sensitivity
    "resistance": "Medium Ball",          # Ball resistance
    "preset_applied": False,              # Is preset active?
}
self._gc_open_param = None                # Which parameter dropdown is open
```

**Key Methods**:
- `_init_game_config_state()`: Reset to defaults
- `_gc_handle_click(pos)`: Handle game/preset/parameter selection
- `_draw_game_config(surface, pa)`: Render panel with adjustable element sizing

**Adjustable Sizing Values** (see comments in code for manual adjustment):
- Game tile height: `int(72*H/1080)` ← increase if titles overlap
- Parameter box height: `int(46*H/1080)` ← increase if text overlaps
- Adaptive difficulty box height: `int(60*H/1080)` ← increase if overlapping
- Spacing values: increase `int(...*H/1080)` values to add more space

---

## Patient List Panel (Panel 0)

**Key Methods**:
- `_draw_patient_list(surface, pa)`: Renders table of patients
- Clicking patient → selects them → opens Game Configuration
- "Register" link → opens Register Patient panel (Panel 6)
- "Share" icon → opens share modal

---

## Edit Profile Modal

**State**:
```python
self.edit_fields              # List of dicts with field data
self.edit_selected_icon       # Currently selected profile icon (1-10)
self.edit_active_field        # Index of currently focused field (-1 = none)
self.edit_role_open           # Is role dropdown open?
self.edit_error               # Validation error message
self.edit_modal_rect          # Modal position/size
```

**Key Methods**:
- `_init_edit_fields()`: Build modal layout
- `_handle_edit_click(pos)`: Handle field/button clicks
- `_handle_edit_key(event)`: Handle text input
- `_draw_edit_modal(surface)`: Render modal
- `_attempt_save()`: Validate and save therapist profile

---

## Share Patient Modal

**State**:
```python
self._share_modal_open        # Is modal visible?
self.share_modal_patient      # Patient being shared
self._share_input             # Username being typed
self._share_error             # Error message
self._share_success           # Success message
self._share_results           # Therapists matching search
self._unshare_rects           # Rects for revoke-access buttons
```

**Key Methods**:
- `_open_share_modal(patient)`: Open modal for patient
- `_do_share_search()`: Search for therapist by username
- `_do_share_confirm()`: Grant access to selected therapist
- `_draw_share_modal(surface)`: Render modal
- Share data stored in DB patient_shares table

---

## Font Dictionary

All fonts are scaled by height: `pygame.font.SysFont("name", int(SIZE*(H/1080)))`

```python
"logo"          → Large title (RecovR)
"nav"           → Sidebar nav text
"nav_sym"       → Sidebar emoji symbols
"panel_title"   → Panel section title
"body"          → Main text
"small"         → Details/captions
"input"         → Input field text
"btn"           → Button text
"modal_head"    → Modal dialog title
"modal_inp"     → Modal input fields
"section"       → Section headers (Session Parameters, etc)
...and more
```

---

## Database Integration

**Key Database Calls**:
```python
self.db.get_all_patients(therapist_id=...)         # Get my patients
self.db.get_all_therapists()                       # Get all therapists
self.db.create_patient(rp, therapist_id)           # Register new patient
self.db.update_therapist(...)                      # Update profile
self.db.share_patient(patient_id, therapist_id)    # Share patient access
self.db.unshare_patient(patient_id, therapist_id)  # Revoke access
self.db.delete_therapist(therapist_id)             # Delete account
self.db.get_therapist_by_username(username)        # Search for therapist
self.db.get_shared_therapists(patient_id)          # Get therapists with access
```

---

## Common Tasks & Where to Modify

### Change Home Card Title/Symbol
**Lines 48-53**: Modify `HOME_CARDS` list

### Change Panel Colors
**Lines 72-80**: Modify `PANEL_COLORS` dict

### Add New Game
**Lines 103-111**: Add to `SINGLE_SKILL_GAMES` or `INTEGRATED_GAMES`

### Adjust UI Sizing (Game Config Box Sizes)
**Lines 1642-1677**: Look for `ADJUST` comments showing which values to modify

### Change Register Patient Fields
**Lines 290-300**: Modify `_init_register_state()` dict keys

### Change Game Configuration Defaults
**Lines 304-310**: Modify `_init_game_config_state()` values

---

## Flow Diagrams

### Navigation Flow
```
Home (-1)
  ├─ Patient List Card → Patient List (0)
  │   ├─ Click Patient → Game Configuration (4)
  │   │   └─ Proceed → Start Session (5)
  │   └─ Register Link → Register Patient (6)
  ├─ Session History Card → Session History (1)
  ├─ Analytics Card → Analytics (2)
  └─ Calibration Card → Calibration Records (3)
```

### Modal Flow
```
Any Screen
  ├─ Edit Link → Edit Profile Modal
  │   ├─ Save → Updates DB
  │   ├─ Delete → Delete Confirm Modal
  │   └─ Cancel → Close
  ├─ Logout → Logout Confirm Modal
  │   ├─ Yes → Logout (return to welcome)
  │   └─ No → Close
  └─ Share Icon (Patient List) → Share Modal
      ├─ Search → Find therapist
      ├─ Confirm → Grant access
      └─ Close → Cancel
```

### Data Flow
```
Therapist Account Loaded (DB)
  ↓
Initialize Dashboard (set up fonts, rects, state)
  ↓
Event Loop (mouse/keyboard/touch)
  ↓
Update Hover States
  ↓
Draw Everything
  ↓
Check if Scene Transition Needed
```

---

## Tips for Modifying

1. **All font sizes scale with height**: Use `int(SIZE*(H/1080))` pattern
2. **All positions scale with width**: Use `int(SIZE*(W/1920))` pattern
3. **Hover states are updated every frame**: Check these to highlight buttons
4. **Events are handled in priority order**: Share modal > modals > sidebar > panels
5. **Panels are stateless**: Load data in `_open_panel()`, don't cache between switches
6. **Modal state drives rendering**: Check `self.modal` in draw functions
7. **Colors are RGB tuples**: (R, G, B) values 0-255

---

## File Size & Performance Notes

- **Total Lines**: ~1850
- **Main Class Methods**: 50+
- **Panel Drawers**: 7 (one per panel)
- **State Dicts**: 3 major (rp, gc, account)
- **Font Dictionary**: 20+ entries
- **Database Queries**: Per-panel data loading (lazy load on panel open)

---

## Common Debugging

### Elements Not Visible?
1. Check `active_panel` value
2. Check modal state (might be hiding content)
3. Check alpha value (fade-in animation)
4. Verify rect coordinates with print statements

### Clicks Not Working?
1. Check rect.collidepoint(pos) logic
2. Verify priority order in `_handle_click()`
3. Check modal state (modals capture all clicks)
4. Ensure rect is being calculated in update() or draw()

### Text Overlapping?
1. Adjust box heights in ADJUST comment sections
2. Increase spacing values (int(...*H/1080))
3. Check font sizes
4. Verify padding/margin inside boxes

---

