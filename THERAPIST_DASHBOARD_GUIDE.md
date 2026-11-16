# Therapist Dashboard Guide

`scenes/therapist_dashboard.py` is the main UI scene for the RecovR therapist
interface (~9,000 lines, one `TherapistDashboardScene` class). It owns all
therapist-facing screens: patient management, game configuration, session
control, and account/profile editing.

This guide intentionally references **function/constant names, not line
numbers** — the file is large and actively changing; names stay valid across
edits, line numbers don't.

## Module-level constants (top of file)

- `HOME_CARDS` / `HOME_COLORS` — the 4 home-screen cards
- `PANEL_TITLES` / `PANEL_COLORS` — panel naming/color per `active_panel` value
- `SINGLE_SKILL_GAMES` / `INTEGRATED_GAMES` / `ALL_GAMES` — the game catalog
- `CATEGORY_SENSOR_LABEL` — per-category sensor-name labels shown in Game Config
- `ROLES`, `STROKE_TYPES`, `SEX_OPTS`, `HAND_OPTS` — dropdown option lists
- `_CAL_SENSOR_KEY` — maps every calibration `game_type` down to 3 buckets
  (`grip`/`flex`/`wrist`), reused by both calibration-mismatch checks and the
  patient dashboard's Rehabilitation Progress card

## Panels (`active_panel` values, see `PANEL_TITLES`)

```
-1  Home (4 cards)
 0  Patient List
 1  Session History
 2  Analytics
 3  Calibration Records
 4  Game Configuration     (Step 1: category/game, Step 2: Target/Timed mode)
 5  Start Session           (readiness checklist + Calibrate/Start CTA)
 6  Register Patient
 7  Session in Progress     (owns all input while active)
 8  Patient                 (a selected patient's own Info/Metrics/Calibration/History page)
```

Each panel has its own `_draw_<panel>(surface, pa)` method and its own click
handler reached through `_handle_click()`'s priority dispatch (see below).
Difficulty/Advanced Settings are **not** a Game Configuration step any more —
they're chosen post-calibration, in `scenes/calibration_window.py`'s own
Results/Advanced screens.

## Event handling

`handle_event(event)` routes touch (`FINGERDOWN`), mouse
(`MOUSEBUTTONDOWN` → `_handle_click()`), and keyboard input. `_handle_click(pos)`
checks UI elements in priority order: open modals (share / edit-profile /
confirm dialogs) → sidebar/back/logout → home cards → the active panel's own
handler.

## Draw loop

`draw(surface)`: background → sidebar → home or active panel → any open
modal → fade-in overlay. `update(mouse_pos, dt)` refreshes hover state every
frame and advances the fade-in alpha.

## Register Patient (panel 6)

State lives in `self.rp` (built by `_init_register_state()`); required fields
are defined once in `_RP_REQUIRED` (used by both the validation in
`_rp_submit()` and the red-asterisk labels in `_draw_register_patient()` /
`_draw_register_patient_touch()`). There are two draw paths — desktop
(`_draw_register_patient`) and the 7-inch touch panel's scrollable column
(`_draw_register_patient_touch`) — kept in sync by hand, not shared code.

## Game Configuration (panel 4)

State lives in `self.gc` (built by `_init_game_config_state()`): selected
game, session mode (`target`/`timed`), speed. Two steps, tracked by
`self._gc_step` (`"game"` / `"mode"`), each with its own draw method
(`_draw_gc_step_game`, `_draw_gc_step_mode`). Tile sizing in Step 1 is
computed from however many tiles the active tab (`self._gc_active_tab`,
`"single"`/`"integrated"`) actually has — not a fixed divisor — so Integrated
Games' longer combined sensor labels get proportionally wider tiles.

## Edit Profile modal

State: `self.edit_fields`, `self.edit_role_open`, `self.edit_selected_icon`,
`self.edit_error`. Built by `_init_edit_fields()`, handled by
`_handle_edit_click()`, drawn by `_draw_edit_modal()`. The Role dropdown's
open-list is drawn **after** the Save/Cancel/Delete buttons (not before) so
it always renders on top of them; each role label wraps to the field's width
via the shared `_wrap()` helper.

## Share Patient modal

State: `self._share_modal_open`, `self._share_input`, `self._share_results`,
etc. Handled by `_open_share_modal()` / `_do_share_search()` /
`_do_share_confirm()`, drawn by `_draw_share_modal()`.

## Breadcrumb (top nav)

`_breadcrumb(idx)` returns the `(label, target)` list for the current panel;
`_draw_top_right_bar`'s crumb-rendering loop colors whichever crumb has
`target is None` (the current page) blue, everything else gray — no
underline. See the loop right after `crumbs = self._breadcrumb(idx)`.

## Database calls used throughout

```python
self.db.get_all_patients(therapist_id=...)
self.db.get_calibrations(therapist_id, patient_id=...)
self.db.create_patient(rp, therapist_id)
self.db.update_therapist(...)
self.db.share_patient(...) / unshare_patient(...)
self.db.delete_therapist(...)
self.db.get_therapist_by_username(...)
self.db.get_shared_therapists(...)
```

## Tips

1. Fonts/positions scale via `self._sc(px)` (non-interactive) and
   `self._tt(px)` (interactive, floored to a touch-friendly size on the
   7-inch panel) — not raw `H/1080` arithmetic in new code.
2. `self._touch_ui` branches desktop vs. the 800×480 LCD layout; many panels
   have a `_draw_x` (desktop) and `_draw_x_touch` (touch) pair.
3. Panels reload their own data lazily when opened (`_open_panel`), not
   cached across switches.
4. When adding a UI fix, grep for the function name mentioned above rather
   than trusting any line number — including the ones in this guide.
