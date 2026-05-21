# =============================================================================
# scenes/login.py
# =============================================================================
# Fixes:
#   1. Correct account is passed to the dashboard via builtins.pending_account
#   2. PIN lockout: 5 wrong attempts → locked for 1 hour, live countdown shown
#   3. Forgot PIN: Interactive 4-digit reset workflow with strict validation match
#
# Touch / mouse:
#   MOUSEBUTTONDOWN → normalise_pos(event.pos)   (physical mouse)
#   FINGERDOWN      → (event.x * W, event.y * H)  (touchscreen, 0-1 normalised)
# =============================================================================

import pygame
import math
import sys, os
import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audio import play_click

MAX_ACCOUNTS = 23
GRID_COLS    = 8

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database, MAX_PIN_ATTEMPTS, LOCK_DURATION_HOURS
from scenes.icon_renderer import draw_icon, get_icon_color
from scenes.register import SECURITY_QUESTIONS

import builtins
if not hasattr(builtins, 'normalise_pos'):
    builtins.normalise_pos = lambda p: p


class LoginScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        self.db       = Database()
        self.accounts = self.db.get_all_therapists()

        # --- FONTS ---
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(n): return os.path.join(_fd, n)
        H = height
        self.font_heading   = pygame.font.Font(_F("FjallaOne-Regular.ttf"),  int(44 * (H / 1080)))
        self.font_username  = pygame.font.Font(_F("Lexend-Regular.ttf"),     int(18 * (H / 1080)))
        self.font_add_lbl   = pygame.font.Font(_F("Lexend-Light.ttf"),       int(18 * (H / 1080)))
        self.font_plus      = pygame.font.Font(_F("GravitasOne-Regular.ttf"),int(50 * (H / 1080)))
        self.font_pin_lbl   = pygame.font.Font(_F("Lexend-Medium.ttf"),      int(22 * (H / 1080)))
        self.font_name_big  = pygame.font.Font(_F("Lexend-SemiBold.ttf"),    int(26 * (H / 1080)))
        self.font_error     = pygame.font.Font(_F("Lexend-Light.ttf"),       int(17 * (H / 1080)))
        self.font_back      = pygame.font.Font(_F("Lexend-Light.ttf"),       int(18 * (H / 1080)))
        self.font_lock      = pygame.font.Font(_F("Lexend-SemiBold.ttf"),    int(20 * (H / 1080)))
        self.font_lock_sub  = pygame.font.Font(_F("Lexend-Light.ttf"),       int(15 * (H / 1080)))
        self.font_forgot    = pygame.font.Font(_F("Lexend-Light.ttf"),       int(15 * (H / 1080)))
        self.font_attempts  = pygame.font.Font(_F("Lexend-Light.ttf"),       int(14 * (H / 1080)))
        self.font_sq_title  = pygame.font.Font(_F("FjallaOne-Regular.ttf"), int(30 * (H / 1080)))
        self.font_sq_lbl    = pygame.font.Font(_F("Lexend-Regular.ttf"),    int(16 * (H / 1080)))
        self.font_sq_inp    = pygame.font.Font(_F("Lexend-Regular.ttf"),    int(17 * (H / 1080)))
        self.font_sq_btn    = pygame.font.Font(_F("Lexend-SemiBold.ttf"),   int(17 * (H / 1080)))

        # --- BACKGROUND ---
        self.background_surface = self._create_gradient(width, height)

        # --- LAYOUT ---
        self.circle_r   = int(72 * (height / 1080))
        self.add_radius = int(72 * (height / 1080))
        self._compute_layout()

        n = len(self.accounts) + 1
        self.circle_hover = [False] * n
        self.circle_lift  = [0.0]  * n

        # --- STATE ---
        self.selected         = None   # account dict currently being PIN-entered
        self.dim_alpha        = 0
        self.dimming          = False
        self.undimming        = False
        self.pin_entered      = ""
        self.pin_error        = ""
        self.pin_shake        = 0
        self.pin_shake_x      = 0
        self.back_hovered     = False
        self.forgot_hovered   = False
        self.launch_triggered = False

        # Lock state for currently selected account
        self.lock_attempts    = 0       # failed attempts so far
        self.locked_until     = None    # datetime when lock expires (or None)
        
        # --- FORGOT PIN RESET WORKFLOW STATE MACHINE ---
        self.show_forgot      = False   # flag showing reset workflow is running
        self.forgot_state     = "new_pin" # "new_pin" | "confirm_pin" | "security_qs"
        self.forgot_new_pin   = ""
        self.forgot_conf_pin  = ""
        self.forgot_error     = ""
        self.forgot_success_msg = ""
        self.forgot_success_timer = 0.0

        # Security questions sub-step within forgot PIN flow
        self.forgot_sq_questions  = []          # [q1, q2, q3] loaded when entering the step
        self.forgot_sq_answers    = ["", "", ""]
        self.forgot_sq_active     = 0           # which answer field has focus (0-2)
        self.forgot_sq_error      = ""
        self._sq_forgot_a_rects   = [pygame.Rect(0, 0, 1, 1)] * 3
        self._sq_forgot_btn_rect  = pygame.Rect(0, 0, 1, 1)
        self._sq_forgot_btn_hov   = False

        self._limit_modal  = False
        self._limit_ok_rect = pygame.Rect(0, 0, 1, 1)
        self._limit_ok_hov  = False

        # --- SECURITY QUESTIONS SETUP (for accounts that haven't set them yet) ---
        self.setup_sq        = False
        self.sq_account      = None
        self.sq_active_slot  = None   # index 0-2 of the answer field with focus
        self.sq_error_msg    = ""
        self.sq_complete_hov = False

        sq_cw   = int(width  * 0.55)
        sq_cx   = (width - sq_cw) // 2
        sq_top  = int(height * 0.22)
        sq_fh   = int(38 * (height / 1080))
        sq_gap  = int(48 * (height / 1080))    # gap between question dropdown and answer input
        sq_step = int(200 * (height / 1080))   # spacing between each Q&A block

        self.sq_fields = []
        for i in range(3):
            base_y = sq_top + i * sq_step
            q_rect = pygame.Rect(sq_cx, base_y, sq_cw, sq_fh)
            a_rect = pygame.Rect(sq_cx, base_y + sq_fh + sq_gap, sq_cw, sq_fh)
            q_opts = [
                pygame.Rect(sq_cx, q_rect.bottom + j * sq_fh, sq_cw, sq_fh)
                for j in range(len(SECURITY_QUESTIONS))
            ]
            self.sq_fields.append({
                "q_value": "",
                "q_open":  False,
                "q_rect":  q_rect,
                "a_value": "",
                "a_rect":  a_rect,
                "q_opts":  q_opts,
            })

        last_a = self.sq_fields[2]["a_rect"]
        self.sq_complete_rect = pygame.Rect(
            sq_cx,
            last_a.bottom + int(50 * (height / 1080)),
            int(sq_cw * 0.45),
            int(50 * (height / 1080)),
        )

        self.dim_surface  = pygame.Surface((width, height))
        self.dim_surface.fill((10, 14, 22))

        self.alpha = 0
        self.fade_surface = pygame.Surface((width, height))
        self.fade_surface.fill((255, 255, 255))

    def _compute_layout(self):
        r         = self.circle_r
        diam      = 2 * r
        h_spacing = int(56 * (self.WIDTH  / 1920))
        v_step    = int(210 * (self.HEIGHT / 1080))

        n_total = len(self.accounts) + 1  # accounts + add button

        self.account_circles = []
        self.account_rects   = []

        if n_total <= GRID_COLS:
            # ── Single centered row ──────────────────────────────────
            row_w    = n_total * diam + (n_total - 1) * h_spacing
            row_left = (self.WIDTH - row_w) // 2
            cy       = int(self.HEIGHT * 0.52)

            for i in range(len(self.accounts)):
                cx = row_left + i * (diam + h_spacing) + r
                self.account_circles.append((cx, cy))
                self.account_rects.append(pygame.Rect(cx - r, cy - r, diam, diam))

            add_idx = len(self.accounts)
            cx_add  = row_left + add_idx * (diam + h_spacing) + r
            self.add_center = (cx_add, cy)
            self.add_rect   = pygame.Rect(cx_add - r, cy - r, diam, diam)

        else:
            # ── 8-column grid ────────────────────────────────────────
            total_grid_w = GRID_COLS * diam + (GRID_COLS - 1) * h_spacing
            row_left     = (self.WIDTH - total_grid_w) // 2
            cy_row0      = int(self.HEIGHT * 0.39)

            for i in range(len(self.accounts)):
                col = i % GRID_COLS
                row = i // GRID_COLS
                cx  = row_left + col * (diam + h_spacing) + r
                cy  = cy_row0  + row * v_step
                self.account_circles.append((cx, cy))
                self.account_rects.append(pygame.Rect(cx - r, cy - r, diam, diam))

            add_idx = len(self.accounts)
            add_col = add_idx % GRID_COLS
            add_row = add_idx // GRID_COLS
            cx_add  = row_left + add_col * (diam + h_spacing) + r
            cy_add  = cy_row0  + add_row * v_step
            self.add_center = (cx_add, cy_add)
            self.add_rect   = pygame.Rect(cx_add - r, cy_add - r, diam, diam)

    # ------------------------------------------------------------------
    # HIT-TEST (shared by mouse and touch)
    # ------------------------------------------------------------------

    def _hit_test(self, pos):
        # Forgot PIN interactive workflow tap-outside validation logic
        if self.show_forgot:
            if self.forgot_success_msg:
                return None
            # Security questions step: handle answer field + button clicks
            if self.forgot_state == "security_qs":
                return self._sq_forgot_click(pos)
            cx, cy = self.WIDTH // 2, int(self.HEIGHT * 0.38)
            if math.hypot(pos[0] - cx, pos[1] - cy) > self.circle_r * 3.5:
                self._cancel_forgot_workflow()
            return None

        # PIN mode
        if self.selected is not None:
            # Forgot PIN link click detection
            if self._forgot_rect().collidepoint(pos):
                self._start_forgot_workflow()
                return None
            # Tap outside cancels selection
            cx, cy = self.WIDTH // 2, int(self.HEIGHT * 0.38)
            if math.hypot(pos[0] - cx, pos[1] - cy) > self.circle_r * 3.5:
                self._cancel_selection()
            return None

        # Account circles
        for i, rect in enumerate(self.account_rects):
            if rect.collidepoint(pos):
                play_click()
                self._select_account(i)
                return None

        # Limit modal dismiss
        if self._limit_modal:
            if self._limit_ok_rect.collidepoint(pos):
                play_click()
                self._limit_modal = False
            return None

        # Add button
        if self.add_rect.collidepoint(pos):
            play_click()
            if len(self.accounts) >= MAX_ACCOUNTS:
                self._limit_modal = True
                return None
            self.launch_triggered = True
            return "register"

        # Back
        if self._back_rect().collidepoint(pos):
            play_click()
            self.launch_triggered = True
            return "therapist_welcome"

        return None

    # ------------------------------------------------------------------
    # SCENE INTERFACE
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if self.launch_triggered:
            return None

        if self.setup_sq:
            return self._sq_handle_event(event)

        # Keyboard (PIN entry routing)
        if event.type == pygame.KEYDOWN:
            return self._handle_key(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = builtins.normalise_pos(event.pos)
            return self._hit_test(pos)

        if event.type == pygame.FINGERDOWN:
            pos = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            return self._hit_test(pos)

        return None

    def _handle_key(self, event):
        if event.key == pygame.K_ESCAPE:
            if self._limit_modal:
                self._limit_modal = False
                return None
            if self.show_forgot:
                if not self.forgot_success_msg:
                    self._cancel_forgot_workflow()
            elif self.selected is not None:
                self._cancel_selection()
            return None

        # Route keys to the automated self-service PIN reset wizard machine if active
        if self.show_forgot:
            if self.forgot_success_msg:
                return None  # freeze interaction on validation splash delay
            return self._handle_forgot_key(event)

        if self.selected is None:
            return None

        # Locked — ignore key input
        if self.locked_until is not None:
            if datetime.datetime.now() >= self.locked_until:
                self.locked_until  = None
                self.lock_attempts = 0
            return None

        if event.key == pygame.K_BACKSPACE:
            self.pin_entered = self.pin_entered[:-1]
            self.pin_error   = ""
            return None

        if event.unicode.isdigit() and len(self.pin_entered) < 4:
            self.pin_entered += event.unicode
            self.pin_error    = ""
            if len(self.pin_entered) == 4:
                return self._verify_pin()

        return None

    def _handle_forgot_key(self, event):
        """Processes key signatures running inside the custom reset overlay loop."""
        if self.forgot_state == "security_qs":
            self._sq_forgot_key(event)
            return None

        if event.key == pygame.K_BACKSPACE:
            if self.forgot_state == "new_pin":
                self.forgot_new_pin = self.forgot_new_pin[:-1]
            else:
                self.forgot_conf_pin = self.forgot_conf_pin[:-1]
            self.forgot_error = ""
            return None

        if event.unicode.isdigit():
            if self.forgot_state == "new_pin" and len(self.forgot_new_pin) < 4:
                self.forgot_new_pin += event.unicode
                self.forgot_error = ""
                if len(self.forgot_new_pin) == 4:
                    self.forgot_state = "confirm_pin"
            elif self.forgot_state == "confirm_pin" and len(self.forgot_conf_pin) < 4:
                self.forgot_conf_pin += event.unicode
                self.forgot_error = ""
                if len(self.forgot_conf_pin) == 4:
                    self._process_pin_reset_commit()
        return None

    def _sq_forgot_click(self, pos):
        """Handle mouse/touch clicks during the security-questions step of PIN reset."""
        for i, a_rect in enumerate(self._sq_forgot_a_rects):
            if a_rect.collidepoint(pos):
                play_click()
                self.forgot_sq_active = i
                return None
        if self._sq_forgot_btn_rect.collidepoint(pos):
            play_click()
            self._verify_sq_and_commit()
        return None

    def _sq_forgot_key(self, event):
        """Handle keyboard input for the security-questions step of PIN reset."""
        idx = self.forgot_sq_active
        if event.key == pygame.K_BACKSPACE:
            self.forgot_sq_answers[idx] = self.forgot_sq_answers[idx][:-1]
            self.forgot_sq_error = ""
        elif event.key == pygame.K_TAB:
            self.forgot_sq_active = (idx + 1) % 3
        elif event.key == pygame.K_RETURN:
            if idx < 2:
                self.forgot_sq_active = idx + 1
            else:
                self._verify_sq_and_commit()
        elif event.key == pygame.K_ESCAPE:
            self._cancel_forgot_workflow()
        elif event.unicode:
            self.forgot_sq_answers[idx] += event.unicode
            self.forgot_sq_error = ""

    # ------------------------------------------------------------------
    # ACCOUNT SELECTION & PIN
    # ------------------------------------------------------------------

    def _select_account(self, index):
        acc = self.accounts[index]
        self.selected    = acc
        self.dimming     = True
        self.undimming   = False
        self.pin_entered = ""
        self.pin_error   = ""
        self.show_forgot = False

        # Load lock state from DB for this account
        locked, locked_until = self.db.is_locked(acc["id"])
        if locked:
            self.locked_until  = locked_until
            self.lock_attempts = MAX_PIN_ATTEMPTS
        else:
            attempts, _ = self.db.get_lock_info(acc["id"])
            self.lock_attempts = attempts
            self.locked_until  = None

    def _verify_pin(self):
        acc = self.selected

        # Re-check lock in case time passed
        locked, locked_until = self.db.is_locked(acc["id"])
        if locked:
            self.locked_until = locked_until
            self.pin_entered  = ""
            return None

        if self.db.verify_pin(acc["username"], self.pin_entered):
            self.db.record_successful_login(acc["id"])
            if not self.db.has_security_questions(acc["id"]):
                # Prompt existing account to set security questions before dashboard
                self.pin_entered = ""
                self.setup_sq    = True
                self.sq_account  = acc
                return None
            builtins.pending_account = acc
            self.launch_triggered = True
            return "therapist_dashboard"

        # FAILURE
        new_attempts, lock_until = self.db.record_failed_attempt(acc["id"])
        self.lock_attempts = new_attempts
        self.pin_entered   = ""
        self.pin_shake     = 14

        if lock_until:
            self.locked_until = lock_until
            self.pin_error    = ""   # lock screen replaces error text
        else:
            remaining = MAX_PIN_ATTEMPTS - new_attempts
            self.pin_error = (
                f"Incorrect PIN. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
            )

        return None

    def _cancel_selection(self):
        self.undimming   = True
        self.dimming     = False
        self.show_forgot = False

    # ------------------------------------------------------------------
    # RESET FLOW LOGIC MACHINE ENGINE
    # ------------------------------------------------------------------

    def _start_forgot_workflow(self):
        self.show_forgot          = True
        self.forgot_state         = "new_pin"
        self.forgot_new_pin       = ""
        self.forgot_conf_pin      = ""
        self.forgot_error         = ""
        self.forgot_success_msg   = ""
        self.forgot_success_timer = 0.0
        self.forgot_sq_questions  = []
        self.forgot_sq_answers    = ["", "", ""]
        self.forgot_sq_active     = 0
        self.forgot_sq_error      = ""

    def _cancel_forgot_workflow(self):
        self.show_forgot = False
        self.pin_entered = ""
        self.pin_error   = ""

    def _process_pin_reset_commit(self):
        """After both PIN entries match, check security questions (if set) before committing."""
        if self.forgot_new_pin != self.forgot_conf_pin:
            self.forgot_error    = "PINs do not match! Restarting verification..."
            self.forgot_state    = "new_pin"
            self.forgot_new_pin  = ""
            self.forgot_conf_pin = ""
            self.pin_shake       = 14
            return

        # If the account has security questions, require them before the PIN is saved
        acc     = self.selected
        sq_data = self.db.get_security_questions(acc["id"])
        if sq_data:
            self.forgot_sq_questions = [sq_data["q1"], sq_data["q2"], sq_data["q3"]]
            self.forgot_sq_answers   = ["", "", ""]
            self.forgot_sq_active    = 0
            self.forgot_sq_error     = ""
            self.forgot_state        = "security_qs"
            return

        self._do_pin_reset()

    def _do_pin_reset(self):
        """Commit the new PIN to the database and show the success message."""
        try:
            username = self.selected["username"]
            acc      = self.selected
            self.db.update_therapist(
                acc["id"],
                acc["full_name"],
                acc["username"],
                acc["role"],
                acc["workplace"],
                acc["icon_index"],
                new_pin=self.forgot_new_pin,
            )
            self.forgot_success_msg   = "PIN Updated Successfully!"
            self.forgot_success_timer = 1.5
            self.db.record_successful_login(acc["id"])
            self.lock_attempts = 0
            self.locked_until  = None
            self.accounts = self.db.get_all_therapists()
            for item in self.accounts:
                if item["username"] == username:
                    self.selected = item
                    break
        except Exception:
            self.forgot_error    = "Could not update PIN. Please try again."
            self.forgot_state    = "new_pin"
            self.forgot_new_pin  = ""
            self.forgot_conf_pin = ""

    def _verify_sq_and_commit(self):
        """Verify the three security answers and, if correct, commit the PIN reset."""
        acc = self.selected
        ok  = self.db.verify_security_answers(
            acc["id"],
            self.forgot_sq_answers[0],
            self.forgot_sq_answers[1],
            self.forgot_sq_answers[2],
        )
        if ok:
            self._do_pin_reset()
        else:
            self.forgot_sq_error   = "One or more answers are incorrect. Please try again."
            self.forgot_sq_answers = ["", "", ""]
            self.forgot_sq_active  = 0
            self.pin_shake         = 14

    # ------------------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------------------

    def update(self, mouse_pos, dt):
        if self.setup_sq:
            self.sq_complete_hov = self.sq_complete_rect.collidepoint(mouse_pos)
            if self.alpha < 255:
                self.alpha = min(255, self.alpha + 4)
            return
        self._limit_ok_hov  = self._limit_ok_rect.collidepoint(mouse_pos)
        self.back_hovered   = self._back_rect().collidepoint(mouse_pos)
        self.forgot_hovered = self._forgot_rect().collidepoint(mouse_pos)

        # Handle structural success timer decay on updates
        if self.show_forgot and self.forgot_success_msg:
            self.forgot_success_timer -= dt
            if self.forgot_success_timer <= 0:
                self._cancel_forgot_workflow()

        max_lift   = int(10 * self.HEIGHT / 1080)
        lift_speed = max(1, int(max_lift * 0.4))

        for i, rect in enumerate(self.account_rects):
            lifted = rect.move(0, -int(self.circle_lift[i]))
            over   = lifted.collidepoint(mouse_pos)
            self.circle_hover[i] = over
            self.circle_lift[i]  = (min(max_lift, self.circle_lift[i] + lift_speed) if over
                                    else max(0, self.circle_lift[i] - lift_speed))

        idx_add    = len(self.accounts)
        lifted_add = self.add_rect.move(0, -int(self.circle_lift[idx_add]))
        over_add   = lifted_add.collidepoint(mouse_pos)
        self.circle_hover[idx_add] = over_add
        self.circle_lift[idx_add]  = (min(max_lift, self.circle_lift[idx_add] + lift_speed) if over_add
                                      else max(0, self.circle_lift[idx_add] - lift_speed))

        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

        if self.dimming:
            self.dim_alpha = min(220, self.dim_alpha + 14)
            if self.dim_alpha >= 220:
                self.dimming = False
        if self.undimming:
            self.dim_alpha = max(0, self.dim_alpha - 14)
            if self.dim_alpha == 0:
                self.undimming = False
                self.selected  = None

        if self.pin_shake > 0:
            self.pin_shake   -= 1
            self.pin_shake_x = 7 * (1 if self.pin_shake % 4 < 2 else -1)
        else:
            self.pin_shake_x = 0

        # Auto-clear expired lock
        if self.locked_until and datetime.datetime.now() >= self.locked_until:
            self.locked_until  = None
            self.lock_attempts = 0
            self.pin_error     = ""

    # ------------------------------------------------------------------
    # DRAW
    # ------------------------------------------------------------------

    def draw(self, surface):
        surface.blit(self.background_surface, (0, 0))
        self._draw_heading(surface)
        self._draw_circles(surface)

        if self.setup_sq:
            self._draw_sq_overlay(surface)
        else:
            if self.dim_alpha > 0:
                self.dim_surface.set_alpha(self.dim_alpha)
                surface.blit(self.dim_surface, (0, 0))

            if self.selected is not None and self.dim_alpha > 0:
                if self.show_forgot:
                    self._draw_forgot_panel(surface)
                elif self.locked_until is not None:
                    self._draw_lock_screen(surface)
                else:
                    self._draw_pin_panel(surface)

            self._draw_back_link(surface)

            if self._limit_modal:
                self._draw_limit_modal(surface)

        if self.alpha < 255:
            self.fade_surface.set_alpha(255 - self.alpha)
            surface.blit(self.fade_surface, (0, 0))

    # ------------------------------------------------------------------
    # DRAW HELPERS
    # ------------------------------------------------------------------

    def _draw_heading(self, surface):
        text = "Please choose an account"
        surf = self.font_heading.render(text, True, (55, 70, 90))
        rect = surf.get_rect(center=(self.WIDTH // 2, int(self.HEIGHT * 0.13)))
        surface.blit(surf, rect)
        lw = int(self.WIDTH * 0.22)
        ly = rect.bottom + int(12 * (self.HEIGHT / 1080))
        lx = self.WIDTH // 2 - lw // 2
        pygame.draw.line(surface, (185, 200, 220), (lx, ly), (lx + lw, ly), 2)

    def _draw_circles(self, surface):
        r       = self.circle_r
        lbl_gap = int(18 * self.HEIGHT / 1080)
        lbl_col = (60, 75, 95)

        for i, account in enumerate(self.accounts):
            cx, cy_base = self.account_circles[i]
            lift        = int(self.circle_lift[i])
            cy          = cy_base - lift
            hovered     = self.circle_hover[i]

            if hovered:
                icon_col = get_icon_color(account.get("icon_index", 1))
                glow_col = tuple(min(255, c + 55) for c in icon_col)
                pygame.draw.circle(surface, glow_col, (cx, cy), r + 8)

            draw_icon(surface, account.get("icon_index", 1), cx, cy, r, shadow=True)

            name_surf = self.font_username.render(account["username"], True, lbl_col)
            surface.blit(name_surf, name_surf.get_rect(
                center=(cx, cy_base + r + lbl_gap)
            ))

        # Add button
        cx, cy_base = self.add_center
        idx_add     = len(self.accounts)
        lift        = int(self.circle_lift[idx_add])
        cy          = cy_base - lift
        hovered     = self.circle_hover[idx_add]
        at_limit    = len(self.accounts) >= MAX_ACCOUNTS

        if at_limit:
            outline_col = (180, 185, 195)
            fill_col    = (220, 222, 228)
        else:
            outline_col = (40, 160, 220)  if hovered else (160, 180, 210)
            fill_col    = (225, 238, 252) if hovered else (245, 248, 255)
            if hovered:
                pygame.draw.circle(surface, (185, 218, 248), (cx, cy), self.add_radius + 8)

        pygame.draw.circle(surface, fill_col,    (cx, cy), self.add_radius)
        pygame.draw.circle(surface, outline_col, (cx, cy), self.add_radius, 2)

        plus = self.font_plus.render("+", True, outline_col)
        surface.blit(plus, plus.get_rect(center=(cx, cy - int(3 * self.HEIGHT / 1080))))

        lbl = self.font_add_lbl.render("Add Account", True, lbl_col if not at_limit else (160, 168, 180))
        surface.blit(lbl, lbl.get_rect(
            center=(cx, cy_base + self.add_radius + lbl_gap)
        ))

    def _draw_pin_panel(self, surface):
        alpha_factor = self.dim_alpha / 220.0

        acc = self.selected
        cx  = self.WIDTH  // 2
        cy  = int(self.HEIGHT * 0.36)
        r   = int(82 * self.HEIGHT / 1080)

        panel = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)

        draw_icon(panel, acc.get("icon_index", 1), cx, cy, r,
                  shadow=True, border_color=(255, 255, 255), border_width=3)

        ns = self.font_name_big.render(acc["full_name"], True, (230, 235, 248))
        panel.blit(ns, ns.get_rect(center=(cx, cy + r + int(22 * self.HEIGHT/1080))))

        ps = self.font_pin_lbl.render("Enter PIN", True, (180, 195, 220))
        panel.blit(ps, ps.get_rect(center=(cx, cy + r + int(58 * self.HEIGHT/1080))))

        # Render explicit raw standard pin entry fields safely
        self._draw_pin_boxes(panel, cx, cy + r + int(94 * self.HEIGHT/1080), len(self.pin_entered))

        # Attempt counter dots
        dot_y = cy + r + int(158 * self.HEIGHT/1080)
        if self.lock_attempts > 0:
            dot_r  = int(5 * self.HEIGHT / 1080)
            dot_gap = int(14 * self.WIDTH / 1920)
            total_dot_w = MAX_PIN_ATTEMPTS * 2 * dot_r + (MAX_PIN_ATTEMPTS - 1) * dot_gap
            dot_x = cx - total_dot_w // 2 + dot_r
            for j in range(MAX_PIN_ATTEMPTS):
                col = (230, 80, 80) if j < self.lock_attempts else (100, 120, 160)
                pygame.draw.circle(panel, col, (dot_x + j * (2 * dot_r + dot_gap), dot_y), dot_r)
            att_s = self.font_attempts.render(
                f"{self.lock_attempts}/{MAX_PIN_ATTEMPTS} attempts used",
                True, (200, 110, 110) if self.lock_attempts >= 3 else (160, 178, 205)
            )
            panel.blit(att_s, att_s.get_rect(center=(cx, dot_y + int(18 * self.HEIGHT/1080))))

        # Error text
        if self.pin_error:
            es = self.font_error.render(self.pin_error, True, (255, 120, 120))
            panel.blit(es, es.get_rect(center=(cx, dot_y + int(40 * self.HEIGHT/1080))))

        # "Forgot PIN?" link
        fc  = (140, 180, 230) if self.forgot_hovered else (120, 148, 195)
        fts = self.font_forgot.render("Forgot PIN?", True, fc)
        fty = dot_y + int(66 * self.HEIGHT/1080)
        panel.blit(fts, fts.get_rect(center=(cx, fty)))

        # Cancel hint
        hs = self.font_error.render("Tap outside to cancel", True, (130, 148, 175))
        panel.blit(hs, hs.get_rect(center=(cx, fty + int(24 * self.HEIGHT/1080))))

        panel.set_alpha(int(255 * alpha_factor))
        surface.blit(panel, (0, 0))

    def _draw_pin_boxes(self, surface, cx, top_y, current_length):
        box = int(54 * self.HEIGHT / 1080)
        gap = int(16 * self.WIDTH  / 1920)
        tw  = 4 * box + 3 * gap
        sx  = cx - tw // 2 + self.pin_shake_x
        for i in range(4):
            bx   = sx + i * (box + gap)
            rect = pygame.Rect(bx, top_y, box, box)
            box_s = pygame.Surface((box, box), pygame.SRCALPHA)
            box_s.fill((255, 255, 255, 35))
            surface.blit(box_s, rect.topleft)
            pygame.draw.rect(surface, (200, 215, 235), rect, 2, border_radius=10)
            if i < current_length:
                dr = int(12 * self.HEIGHT / 1080)
                pygame.draw.circle(surface, (80, 145, 230), rect.center, dr)

    def _draw_lock_screen(self, surface):
        """Shown when account is locked after too many wrong PINs."""
        alpha_factor = self.dim_alpha / 220.0
        panel = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)

        acc = self.selected
        cx  = self.WIDTH  // 2
        cy  = int(self.HEIGHT * 0.36)
        r   = int(82 * self.HEIGHT / 1080)

        draw_icon(panel, acc.get("icon_index", 1), cx, cy, r,
                  shadow=True, border_color=(220, 60, 60), border_width=3)

        lock_r = int(24 * self.HEIGHT / 1080)
        pygame.draw.circle(panel, (210, 45, 45), (cx + r - lock_r//2, cy - r + lock_r//2), lock_r)
        ls = self.font_pin_lbl.render("🔒", True, (255, 255, 255))
        panel.blit(ls, ls.get_rect(center=(cx + r - lock_r//2, cy - r + lock_r//2)))

        ns = self.font_name_big.render(acc["full_name"], True, (230, 235, 248))
        panel.blit(ns, ns.get_rect(center=(cx, cy + r + int(22 * self.HEIGHT/1080))))

        heading = self.font_lock.render("Account Locked", True, (230, 90, 90))
        panel.blit(heading, heading.get_rect(center=(cx, cy + r + int(62 * self.HEIGHT/1080))))

        now       = datetime.datetime.now()
        remaining = self.locked_until - now if self.locked_until > now else datetime.timedelta(0)
        total_sec = int(remaining.total_seconds())
        mins      = total_sec // 60
        secs      = total_sec % 60
        countdown_text = f"Try again in  {mins:02d}:{secs:02d}"
        ct = self.font_lock.render(countdown_text, True, (200, 160, 100))
        panel.blit(ct, ct.get_rect(center=(cx, cy + r + int(100 * self.HEIGHT/1080))))

        sub = self.font_lock_sub.render(
            f"After {MAX_PIN_ATTEMPTS} incorrect attempts the account is locked for {LOCK_DURATION_HOURS} hour.",
            True, (160, 175, 200)
        )
        panel.blit(sub, sub.get_rect(center=(cx, cy + r + int(132 * self.HEIGHT/1080))))

        hint = self.font_lock_sub.render("Tap outside to go back.", True, (130, 148, 175))
        panel.blit(hint, hint.get_rect(center=(cx, cy + r + int(160 * self.HEIGHT/1080))))

        panel.set_alpha(int(255 * alpha_factor))
        surface.blit(panel, (0, 0))

    def _draw_forgot_panel(self, surface):
        """Renders interactive wizard panel requesting input validation metrics."""
        alpha_factor = self.dim_alpha / 220.0
        panel = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)

        acc = self.selected
        cx  = self.WIDTH  // 2
        cy  = int(self.HEIGHT * 0.36)
        r   = int(82 * self.HEIGHT / 1080)

        draw_icon(panel, acc.get("icon_index", 1), cx, cy, r,
                  shadow=True, border_color=(120, 160, 230), border_width=3)

        ns = self.font_name_big.render(acc["full_name"], True, (230, 235, 248))
        panel.blit(ns, ns.get_rect(center=(cx, cy + r + int(22 * self.HEIGHT/1080))))

        if self.forgot_success_msg:
            heading = self.font_lock.render(self.forgot_success_msg, True, (100, 240, 140))
            panel.blit(heading, heading.get_rect(center=(cx, cy + r + int(70 * self.HEIGHT/1080))))
            sub_lbl = self.font_lock_sub.render("Returning to account verification...", True, (160, 180, 200))
            panel.blit(sub_lbl, sub_lbl.get_rect(center=(cx, cy + r + int(115 * self.HEIGHT/1080))))

        elif self.forgot_state == "security_qs":
            panel.set_alpha(int(255 * alpha_factor))
            surface.blit(panel, (0, 0))
            # Draw SQ step directly on surface so rects stay in screen coords
            self._draw_sq_forgot_step(surface, cx, cy, r)
            return

        else:
            if self.forgot_state == "new_pin":
                heading_txt = "Reset Password: Enter New 4-Digit PIN"
                current_len = len(self.forgot_new_pin)
            else:
                heading_txt = "Confirm New 4-Digit PIN Assignment"
                current_len = len(self.forgot_conf_pin)

            heading = self.font_lock.render(heading_txt, True, (200, 220, 255))
            panel.blit(heading, heading.get_rect(center=(cx, cy + r + int(62 * self.HEIGHT/1080))))
            self._draw_pin_boxes(panel, cx, cy + r + int(94 * self.HEIGHT/1080), current_len)

            label_y = cy + r + int(168 * self.HEIGHT/1080)
            if self.forgot_error:
                es = self.font_error.render(self.forgot_error, True, (255, 120, 120))
                panel.blit(es, es.get_rect(center=(cx, label_y)))
            else:
                hint_lbl = ("Use number keys to assign value" if self.forgot_state == "new_pin"
                            else "Please match the original values explicitly")
                ts = self.font_lock_sub.render(hint_lbl, True, (140, 155, 185))
                panel.blit(ts, ts.get_rect(center=(cx, label_y)))
            hint = self.font_lock_sub.render("Tap outside or press ESC to abort reset.", True, (120, 138, 165))
            panel.blit(hint, hint.get_rect(center=(cx, label_y + int(36 * self.HEIGHT/1080))))

        panel.set_alpha(int(255 * alpha_factor))
        surface.blit(panel, (0, 0))

    def _draw_sq_forgot_step(self, surface, cx, cy, r):
        """Draw the security-questions verification step of the forgot-PIN flow."""
        W, H = self.WIDTH, self.HEIGHT
        inp_w  = int(W * 0.52)
        inp_x  = cx - inp_w // 2
        inp_h  = int(36 * H / 1080)
        gap    = int(12 * H / 1080)
        q_gap  = int(44 * H / 1080)   # space between end of one A-field and start of next Q-label
        start_y = cy + r + int(70 * H / 1080)

        heading = self.font_sq_title.render("Verify Your Identity", True, (200, 220, 255))
        surface.blit(heading, heading.get_rect(center=(cx, start_y)))

        sub = self.font_lock_sub.render(
            "Answer your security questions to confirm the PIN reset.",
            True, (150, 168, 200)
        )
        surface.blit(sub, sub.get_rect(center=(cx, start_y + int(32 * H / 1080))))

        cur_y = start_y + int(70 * H / 1080)
        new_a_rects = []
        for i, question in enumerate(self.forgot_sq_questions):
            # Question text (truncated if too long)
            q_surf = self.font_sq_lbl.render(question, True, (180, 198, 225))
            clip_w = inp_w
            if q_surf.get_width() > clip_w:
                q_surf = q_surf.subsurface(pygame.Rect(0, 0, clip_w, q_surf.get_height()))
            surface.blit(q_surf, (inp_x, cur_y))
            cur_y += q_surf.get_height() + gap

            # Answer input field
            a_rect = pygame.Rect(inp_x, cur_y, inp_w, inp_h)
            new_a_rects.append(a_rect)
            a_act  = (self.forgot_sq_active == i)
            pygame.draw.rect(surface, (240, 244, 252), a_rect, border_radius=8)
            bc = (80, 160, 230) if a_act else (100, 120, 160)
            pygame.draw.rect(surface, bc, a_rect, 2 if a_act else 1, border_radius=8)

            ans = self.forgot_sq_answers[i]
            if ans:
                vs = self.font_sq_inp.render(ans, True, (30, 45, 70))
                surface.blit(vs, vs.get_rect(midleft=(a_rect.x + int(10 * W / 1920), a_rect.centery)))
                if a_act:
                    cxr = a_rect.x + int(10 * W / 1920) + vs.get_width() + 2
                    pygame.draw.line(surface, (80, 160, 230),
                                     (cxr, a_rect.centery - int(9 * H / 1080)),
                                     (cxr, a_rect.centery + int(9 * H / 1080)), 2)
            else:
                ph = self.font_sq_inp.render("Your answer…", True, (150, 165, 200))
                surface.blit(ph, ph.get_rect(midleft=(a_rect.x + int(10 * W / 1920), a_rect.centery)))

            cur_y += inp_h + q_gap

        self._sq_forgot_a_rects = new_a_rects

        # Error
        if self.forgot_sq_error:
            es = self.font_error.render(self.forgot_sq_error, True, (255, 110, 110))
            surface.blit(es, es.get_rect(center=(cx, cur_y)))
            cur_y += int(26 * H / 1080)
        else:
            cur_y += int(10 * H / 1080)

        # Confirm Reset button
        bw = int(inp_w * 0.46)
        bh = int(46 * H / 1080)
        btn_r = pygame.Rect(cx - bw // 2, cur_y, bw, bh)
        self._sq_forgot_btn_rect = btn_r
        self._sq_forgot_btn_hov  = btn_r.collidepoint(pygame.mouse.get_pos())
        bc = (28, 115, 175) if self._sq_forgot_btn_hov else (40, 150, 220)
        pygame.draw.rect(surface, bc, btn_r, border_radius=12)
        cs = self.font_sq_btn.render("Confirm Reset", True, (255, 255, 255))
        surface.blit(cs, cs.get_rect(center=btn_r.center))

        esc_hint = self.font_lock_sub.render("Press ESC to cancel.", True, (120, 138, 165))
        surface.blit(esc_hint, esc_hint.get_rect(center=(cx, btn_r.bottom + int(20 * H / 1080))))

    # ------------------------------------------------------------------
    # SECURITY QUESTIONS SETUP OVERLAY
    # ------------------------------------------------------------------

    def _sq_handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = builtins.normalise_pos(event.pos)
            return self._sq_handle_click(pos)
        if event.type == pygame.FINGERDOWN:
            pos = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            return self._sq_handle_click(pos)
        if event.type == pygame.KEYDOWN:
            self._sq_handle_key(event)
        return None

    def _sq_handle_click(self, pos):
        # Close any open dropdown if click lands outside it
        for i, sf in enumerate(self.sq_fields):
            if sf["q_open"]:
                for j, opt_r in enumerate(sf["q_opts"]):
                    if opt_r.collidepoint(pos):
                        play_click()
                        sf["q_value"] = SECURITY_QUESTIONS[j]
                        sf["q_open"]  = False
                        self.sq_error_msg = ""
                        return None
                sf["q_open"] = False
                return None

        for i, sf in enumerate(self.sq_fields):
            if sf["q_rect"].collidepoint(pos):
                play_click()
                for other in self.sq_fields:
                    other["q_open"] = False
                sf["q_open"] = True
                self.sq_active_slot = None
                return None
            if sf["a_rect"].collidepoint(pos):
                play_click()
                self.sq_active_slot = i
                return None

        if self.sq_complete_rect.collidepoint(pos):
            play_click()
            return self._sq_submit()

        self.sq_active_slot = None
        return None

    def _sq_handle_key(self, event):
        if self.sq_active_slot is None:
            return
        sf = self.sq_fields[self.sq_active_slot]
        if event.key == pygame.K_BACKSPACE:
            sf["a_value"]    = sf["a_value"][:-1]
            self.sq_error_msg = ""
        elif event.key == pygame.K_TAB:
            self.sq_active_slot = (self.sq_active_slot + 1) % 3
        elif event.key == pygame.K_RETURN:
            self.sq_active_slot = None
        elif event.unicode:
            sf["a_value"]    += event.unicode
            self.sq_error_msg = ""

    def _sq_submit(self):
        chosen = [sf["q_value"] for sf in self.sq_fields]
        answers = [sf["a_value"].strip() for sf in self.sq_fields]

        for i in range(3):
            if not chosen[i]:
                self.sq_error_msg = f"Please select Question {i + 1}."
                return None
            if not answers[i]:
                self.sq_error_msg = f"Please enter an answer for Question {i + 1}."
                return None

        if len(set(chosen)) < 3:
            self.sq_error_msg = "Each security question must be different."
            return None

        if self.sq_account:
            self.db.set_security_questions(
                self.sq_account["id"],
                chosen[0], answers[0],
                chosen[1], answers[1],
                chosen[2], answers[2],
            )

        builtins.pending_account = self.sq_account
        self.launch_triggered = True
        return "therapist_dashboard"

    def _draw_sq_overlay(self, surface):
        W, H = self.WIDTH, self.HEIGHT

        # Dim the background
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((10, 14, 22, 200))
        surface.blit(ov, (0, 0))

        # Title
        ts = self.font_sq_title.render("Set Up Security Questions", True, (230, 238, 255))
        surface.blit(ts, ts.get_rect(center=(W // 2, int(H * 0.10))))

        sub = self.font_lock_sub.render(
            "Choose 3 different security questions and provide answers.",
            True, (160, 175, 200)
        )
        surface.blit(sub, sub.get_rect(center=(W // 2, int(H * 0.15))))

        # Determine open dropdown (drawn last so it overlaps)
        open_slot = next((i for i, sf in enumerate(self.sq_fields) if sf["q_open"]), None)

        for i, sf in enumerate(self.sq_fields):
            q_rect  = sf["q_rect"]
            a_rect  = sf["a_rect"]
            a_act   = (self.sq_active_slot == i)

            # Slot label
            lbl = self.font_sq_lbl.render(f"Question {i + 1}", True, (190, 205, 230))
            surface.blit(lbl, (q_rect.x, q_rect.y - int(22 * H / 1080)))

            # Dropdown button (skip if this slot is open — drawn after loop)
            if not sf["q_open"]:
                self._sq_draw_q_btn(surface, sf, q_rect, W)

            # Answer label + input
            a_lbl = self.font_sq_lbl.render("Answer", True, (190, 205, 230))
            surface.blit(a_lbl, (a_rect.x, a_rect.y - int(20 * H / 1080)))
            pygame.draw.rect(surface, (240, 244, 252), a_rect, border_radius=8)
            bc = (80, 160, 230) if a_act else (100, 120, 160)
            pygame.draw.rect(surface, bc, a_rect, 2 if a_act else 1, border_radius=8)
            if sf["a_value"]:
                vs = self.font_sq_inp.render(sf["a_value"], True, (30, 45, 70))
                surface.blit(vs, vs.get_rect(midleft=(a_rect.x + int(12 * W / 1920), a_rect.centery)))
                if a_act:
                    cx2 = a_rect.x + int(12 * W / 1920) + vs.get_width() + 2
                    pygame.draw.line(surface, (80, 160, 230),
                                     (cx2, a_rect.centery - int(9 * H / 1080)),
                                     (cx2, a_rect.centery + int(9 * H / 1080)), 2)
            else:
                ph = self.font_sq_inp.render("Type your answer", True, (150, 165, 195))
                surface.blit(ph, ph.get_rect(midleft=(a_rect.x + int(12 * W / 1920), a_rect.centery)))

        # Error + button drawn BEFORE open dropdown so dropdown renders on top
        if self.sq_error_msg:
            es = self.font_error.render(self.sq_error_msg, True, (255, 100, 100))
            surface.blit(es, es.get_rect(
                midleft=(self.sq_complete_rect.x,
                         self.sq_complete_rect.y - int(20 * H / 1080))
            ))

        bc = (28, 115, 175) if self.sq_complete_hov else (40, 150, 220)
        pygame.draw.rect(surface, bc, self.sq_complete_rect, border_radius=12)
        cs = self.font_sq_btn.render("Save & Continue", True, (255, 255, 255))
        surface.blit(cs, cs.get_rect(center=self.sq_complete_rect.center))

        # Draw open dropdown last so it overlays everything below it
        if open_slot is not None:
            sf = self.sq_fields[open_slot]
            self._sq_draw_q_btn(surface, sf, sf["q_rect"], W)
            self._sq_draw_q_opts(surface, sf, W)

    def _sq_draw_q_btn(self, surface, sf, q_rect, W):
        pygame.draw.rect(surface, (240, 244, 252), q_rect, border_radius=8)
        bc = (80, 160, 230) if sf["q_open"] else (100, 120, 160)
        pygame.draw.rect(surface, bc, q_rect, 2 if sf["q_open"] else 1, border_radius=8)
        val = sf["q_value"] or "Select a security question…"
        col = (30, 45, 70) if sf["q_value"] else (140, 158, 190)
        ts  = self.font_sq_inp.render(val, True, col)
        clip_w = q_rect.width - int(38 * W / 1920)
        if ts.get_width() > clip_w:
            ts = ts.subsurface(pygame.Rect(0, 0, clip_w, ts.get_height()))
        surface.blit(ts, ts.get_rect(midleft=(q_rect.x + int(12 * W / 1920), q_rect.centery)))
        chev = self.font_sq_inp.render("▼" if not sf["q_open"] else "▲", True, (100, 120, 160))
        surface.blit(chev, chev.get_rect(midright=(q_rect.right - int(12 * W / 1920), q_rect.centery)))

    def _sq_draw_q_opts(self, surface, sf, W):
        q_rect = sf["q_rect"]
        opt_h  = sf["q_opts"][0].height
        ph     = len(SECURITY_QUESTIONS) * opt_h + 6
        pr     = pygame.Rect(q_rect.x, q_rect.bottom - 1, q_rect.width, ph)
        pygame.draw.rect(surface, (240, 246, 255), pr, border_radius=8)
        pygame.draw.rect(surface, (80, 160, 230), pr, 2, border_radius=8)
        for j, opt_r in enumerate(sf["q_opts"]):
            if j % 2 == 0:
                sh = pygame.Surface((pr.width - 4, opt_h), pygame.SRCALPHA)
                sh.fill((80, 160, 230, 20))
                surface.blit(sh, (pr.x + 2, opt_r.y))
            ts = self.font_sq_inp.render(SECURITY_QUESTIONS[j], True, (30, 45, 70))
            clip_w = pr.width - int(24 * W / 1920)
            if ts.get_width() > clip_w:
                ts = ts.subsurface(pygame.Rect(0, 0, clip_w, ts.get_height()))
            surface.blit(ts, ts.get_rect(midleft=(opt_r.x + int(12 * W / 1920), opt_r.centery)))

    def _draw_limit_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        # Semi-transparent overlay
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((10, 14, 22, 172))
        surface.blit(ov, (0, 0))

        mw = int(W * 0.38); mh = int(H * 0.28)
        mx = (W - mw) // 2;  my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((250, 248, 245, 255))
        surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200))
        surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (210, 90, 60), mr, 2, border_radius=14)

        # Warning icon circle
        pygame.draw.circle(surface, (230, 80, 50),
                           (mr.centerx, my + int(52*H/1080)), int(20*H/1080))
        icon_s = self.font_pin_lbl.render("!", True, (255, 255, 255))
        surface.blit(icon_s, icon_s.get_rect(center=(mr.centerx, my + int(52*H/1080))))

        # Title
        title_s = self.font_name_big.render("Account Limit Reached", True, (175, 40, 20))
        surface.blit(title_s, title_s.get_rect(center=(mr.centerx, my + int(95*H/1080))))

        # Body
        body_s = self.font_add_lbl.render(
            "Remove an account to add a new one.", True, (60, 70, 90))
        surface.blit(body_s, body_s.get_rect(center=(mr.centerx, my + int(128*H/1080))))

        # OK button
        bw = int(110*W/1920); bh = int(38*H/1080)
        ok_r = pygame.Rect(mr.centerx - bw // 2, mr.bottom - int(58*H/1080), bw, bh)
        self._limit_ok_rect = ok_r
        ok_col = (190, 55, 30) if self._limit_ok_hov else (215, 75, 45)
        pygame.draw.rect(surface, ok_col, ok_r, border_radius=10)
        ok_s = self.font_pin_lbl.render("OK", True, (255, 255, 255))
        surface.blit(ok_s, ok_s.get_rect(center=ok_r.center))

    def _draw_back_link(self, surface):
        col  = (80, 105, 140) if self.back_hovered else (160, 175, 195)
        surf = self.font_back.render("← Back", True, col)
        rect = surf.get_rect(
            bottomleft=(int(30 * self.WIDTH/1920),
                        self.HEIGHT - int(24 * self.HEIGHT/1080))
        )
        surface.blit(surf, rect)

    # ------------------------------------------------------------------
    # RECTS
    # ------------------------------------------------------------------

    def _back_rect(self):
        return pygame.Rect(
            0, self.HEIGHT - int(55 * self.HEIGHT/1080),
            int(130 * self.WIDTH/1920), int(44 * self.HEIGHT/1080)
        )

    def _forgot_rect(self):
        """Clickable area for the 'Forgot PIN?' link in the PIN panel."""
        cy = int(self.HEIGHT * 0.36)
        r  = int(82 * self.HEIGHT / 1080)
        dot_y = cy + r + int(158 * self.HEIGHT/1080)
        fty   = dot_y + int(66 * self.HEIGHT/1080)
        tw    = int(120 * self.WIDTH / 1920)
        th    = int(28 * self.HEIGHT / 1080)
        return pygame.Rect(self.WIDTH//2 - tw//2, fty - th//2, tw, th)

    # ------------------------------------------------------------------
    # GRADIENT
    # ------------------------------------------------------------------

    def _create_gradient(self, width, height):
        scale=4; sw=width//scale; sh=height//scale
        s=pygame.Surface((sw,sh),depth=32).convert()
        w=(255,255,255); pb=(185,215,255); pp=(225,185,255); wf=sw*0.75
        for y in range(sh):
            for x in range(sw):
                wb=max(0,1.0-(x+y)/wf); wp=max(0,1.0-((sw-x)+(sh-y))/wf)
                tc=wb+wp
                if tc>1.0: wb/=tc;wp/=tc;ww=0.0
                else: ww=1.0-tc
                r=min(255,max(0,int(pb[0]*wb+pp[0]*wp+w[0]*ww)))
                g=min(255,max(0,int(pb[1]*wb+pp[1]*wp+w[1]*ww)))
                b=min(255,max(0,int(pb[2]*wb+pp[2]*wp+w[2]*ww)))
                s.set_at((x,y),s.map_rgb((r,g,b)))
        return pygame.transform.smoothscale(s,(width,height))