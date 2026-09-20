# =============================================================================
# scenes/register.py
# =============================================================================
# Register / Create Account screen.
#
# Desktop layout (unchanged): centered workspace block with a left icon
# selector and right form inputs.
#
# Touch layout (7-inch 800x480 LCD): the same left-icon / right-form concept,
# rescaled with the same _touch_ui/_fs/_tt/_sc system used on the Login page
# (scenes/login.py) and the therapist dashboard. The 6-field form does not
# fit at touch-target sizes in 480px of height, so the field column scrolls
# (wheel + finger drag + on-screen arrows) while the icon column and the
# Register button stay fixed -- the same pattern already used for the
# Register Patient panel in scenes/therapist_dashboard.py.
# =============================================================================

import pygame
import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audio import play_click

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Database
from scenes.icon_renderer import draw_icon, ICONS

# Roles relevant to hand rehabilitation for stroke patients
ROLES = [
    "Physical Therapist",
    "Occupational Therapist",
    "Other",
]

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What was the name of your elementary school?",
    "What is your oldest sibling's middle name?",
    "What was the make of your first car?",
    "What is your favorite movie?",
    "What was your childhood nickname?",
]


class RegisterScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height
        self.db     = Database()

        # ── Touch scaling (mirrors scenes/login.py / therapist_dashboard.py) ──
        # A plain H/1080 reference gives ~8-15px text and ~16px fields on the
        # 800x480 panel. _fs uses a H/512 reference in touch mode so text and
        # tap targets stay legible; _tt() floors every INTERACTIVE control at
        # a fingertip-sized 50px; _sc() scales non-interactive spacing with no
        # floor. Desktop (_touch_ui False) keeps the original H/1080 reference
        # and _tt/_sc reduce to plain scaling, so desktop is unchanged.
        H = height
        self._touch_ui = (H <= 820) or (os.environ.get("RECOVR_THERAPIST_TOUCH") == "1")
        self._fs = min(H / 512.0, 1.32) if self._touch_ui else (H / 1080.0)

        # --- FONTS ---
        _fd = os.path.join(_ROOT, "assets", "font")
        def _F(n): return os.path.join(_fd, n)
        _s = self._fs
        self.font_title    = pygame.font.Font(_F("FjallaOne-Regular.ttf"),  int(34 * _s))
        self.font_label    = pygame.font.Font(_F("Lexend-Regular.ttf"),     int(19 * _s))
        self.font_input    = pygame.font.Font(_F("Lexend-Regular.ttf"),     int(20 * _s))
        self.font_caption  = pygame.font.Font(_F("Sora-ExtraLight.ttf"),    int(17 * _s))
        self.font_btn      = pygame.font.Font(_F("Lexend-SemiBold.ttf"),    int(20 * _s))
        self.font_back     = pygame.font.Font(_F("Lexend-SemiBold.ttf") if self._touch_ui
                                              else _F("Lexend-Light.ttf"),  int(22 * _s if self._touch_ui else 17 * _s))
        self.font_login_ln = pygame.font.Font(_F("Lexend-Light.ttf"),       int(17 * _s))
        self.font_error    = pygame.font.Font(_F("Lexend-Light.ttf"),       int(16 * _s))
        self.font_dropdown = pygame.font.Font(_F("Lexend-Regular.ttf"),     int(18 * _s))
        # A plain text font has no glyph for ▲/▼ (renders as an empty box --
        # the same bug class as the old "<- Back" arrow); use a symbol font,
        # matching scenes/therapist_dashboard.py's nav_sym/sym26.
        self.font_sym      = pygame.font.SysFont("segoeuisymbol",           int(22 * _s))

        # --- BACKGROUND ---
        self.background_surface = self._create_gradient(width, height)

        # ----------------------------------------------------------------
        # STATE (shared between touch and desktop) -- defined before layout
        # so touch layout helpers can reference them safely.
        # ----------------------------------------------------------------
        self.selected_icon    = 0
        self.icon_hovered     = 0
        self.active_field     = -1
        self.error_msg        = ""
        self.back_hovered     = False
        self.register_hovered = False
        self.login_ln_hovered = False
        self.launch_triggered = False

        self.alpha        = 0
        self.fade_surface = pygame.Surface((width, height))
        self.fade_surface.fill((255, 255, 255))

        self.reg_step          = 1          # 1 = account form, 2 = security questions
        self.sq_therapist_id   = None
        self.sq_error_msg      = ""
        self.sq_complete_hov   = False
        self.sq_active_slot    = None

        # Touch-only scroll state (the field column / security-question
        # column scroll while the icon picker / title / footer stay fixed).
        self._form_scroll      = 0
        self._form_scroll_max  = 0
        self._form_drag_y      = None
        self._form_up_rect     = pygame.Rect(0, 0, 1, 1)
        self._form_down_rect   = pygame.Rect(0, 0, 1, 1)
        self._sq_scroll        = 0
        self._sq_scroll_max    = 0
        self._sq_drag_y        = None
        self._sq_up_rect       = pygame.Rect(0, 0, 1, 1)
        self._sq_down_rect     = pygame.Rect(0, 0, 1, 1)

        if self._touch_ui:
            self._init_touch_layout()
        else:
            self._init_desktop_layout()

    # ------------------------------------------------------------------
    # TOUCH-TARGET / SPACING HELPERS
    # ------------------------------------------------------------------

    def _tt(self, px):
        """Touch-target size for an INTERACTIVE control -- a 1080-referenced
        px, floored at ~50px on the 7-inch panel so a fingertip clears it."""
        v = int(px * self._fs)
        if self._touch_ui:
            v = max(v, 50)
        return v

    def _sc(self, px):
        """Plain scaled size for NON-interactive spacing -- no tap-target floor."""
        return max(1, int(px * self._fs))

    # ------------------------------------------------------------------
    # DESKTOP LAYOUT (unchanged from before this pass)
    # ------------------------------------------------------------------

    def _init_desktop_layout(self):
        width, height = self.WIDTH, self.HEIGHT

        icon_area_w = int(width * 0.26)
        form_w      = int(width * 0.42)
        inner_gutter = int(width * 0.06)

        total_content_w = icon_area_w + inner_gutter + form_w
        start_x = (width - total_content_w) // 2

        left_zone_cx = start_x + (icon_area_w // 2)
        fx = start_x + icon_area_w + inner_gutter
        fw = form_w

        field_h   = int(38 * (height / 1080))
        field_gap = field_h + int(32 * (height / 1080))
        form_top  = int(height * 0.23)

        big_r      = int(82 * (height / 1080))
        big_cy     = form_top + int(60 * (height / 1080))
        self.big_r  = big_r
        self.big_cx = left_zone_cx
        self.big_cy = big_cy

        sm_r      = int(38 * (height / 1080))
        sm_cols   = 4
        sm_gap_x  = int(84 * (width  / 1920))
        sm_gap_y  = int(84 * (height / 1080))
        grid_w    = (sm_cols - 1) * sm_gap_x
        sm_start_x = left_zone_cx - grid_w // 2
        sm_start_y = big_cy + big_r + int(52 * (height / 1080))

        self.sm_r       = sm_r
        self.sm_circles = []
        for idx in range(1, 11):
            col = (idx - 1) % sm_cols
            row = (idx - 1) // sm_cols
            cx  = sm_start_x + col * sm_gap_x
            cy  = sm_start_y + row * sm_gap_y
            self.sm_circles.append((cx, cy, idx))

        self.fields = [
            {"key": "full_name",  "label": "Full Name",
             "value": "", "placeholder": "e.g. Maria Santos",
             "is_pin": False, "max_len": 50,
             "rect": pygame.Rect(fx, form_top + 0 * field_gap, fw, field_h)},
            {"key": "username",   "label": "Username",
             "value": "", "placeholder": "Letters only, max 15 characters",
             "is_pin": False, "max_len": 15,
             "rect": pygame.Rect(fx, form_top + 1 * field_gap, fw, field_h)},
            {"key": "role",       "label": "Role",
             "value": "", "placeholder": "Select your role",
             "is_pin": False, "max_len": 0,
             "rect": pygame.Rect(fx, form_top + 2 * field_gap, fw, field_h)},
            {"key": "workplace",  "label": "Workplace",
             "value": "", "placeholder": "e.g. PGH Rehabilitation Unit",
             "is_pin": False, "max_len": 60,
             "rect": pygame.Rect(fx, form_top + 3 * field_gap, fw, field_h)},
            {"key": "pin",        "label": "4-Digit PIN",
             "value": "", "placeholder": "Digits only",
             "is_pin": True,  "max_len": 4,
             "rect": pygame.Rect(fx, form_top + 4 * field_gap, fw, field_h)},
            {"key": "confirm_pin", "label": "Confirm PIN",
             "value": "", "placeholder": "Re-enter your 4-digit PIN",
             "is_pin": True,  "max_len": 4,
             "rect": pygame.Rect(fx, form_top + 5 * field_gap, fw, field_h)},
        ]

        self.title_left_x = fx

        role_rect  = self.fields[2]["rect"]
        opt_h      = int(38 * (height / 1080))
        self.role_opts = [
            {"label": r, "rect": pygame.Rect(fx, role_rect.bottom + i * opt_h, fw, opt_h)}
            for i, r in enumerate(ROLES)
        ]
        self.role_open = False

        last_field_rect = self.fields[-1]["rect"]
        btn_y  = last_field_rect.bottom + int(45 * (height / 1080))
        btn_h  = int(50 * (height / 1080))
        btn_w  = int(fw * 0.50)

        self.register_btn_rect = pygame.Rect(fx, btn_y, btn_w, btn_h)
        self.login_link_rect = pygame.Rect(
            fx, btn_y + btn_h + int(12 * (height / 1080)),
            fw, int(28 * (height / 1080))
        )

        sq_cw   = int(width  * 0.55)
        sq_cx   = (width - sq_cw) // 2
        sq_top  = int(height * 0.22)
        sq_fh   = field_h
        sq_gap  = int(48  * (height / 1080))
        sq_step = int(200 * (height / 1080))

        self.sq_fields = []
        for i in range(3):
            base_y = sq_top + i * sq_step
            q_rect = pygame.Rect(sq_cx, base_y, sq_cw, sq_fh)
            a_rect = pygame.Rect(sq_cx, base_y + sq_fh + sq_gap, sq_cw, sq_fh)
            opt_h  = sq_fh
            q_opts = [
                pygame.Rect(sq_cx, q_rect.bottom + j * opt_h, sq_cw, opt_h)
                for j in range(len(SECURITY_QUESTIONS))
            ]
            self.sq_fields.append({
                "q_value": "", "q_open": False, "q_rect": q_rect,
                "a_value": "", "a_rect": a_rect, "q_opts": q_opts,
            })

        last_a = self.sq_fields[2]["a_rect"]
        self.sq_complete_rect = pygame.Rect(
            sq_cx, last_a.bottom + int(50 * (height / 1080)),
            int(sq_cw * 0.45), int(50 * (height / 1080)),
        )

    # ------------------------------------------------------------------
    # TOUCH LAYOUT (800x480 7-inch LCD)
    # ------------------------------------------------------------------

    def _init_touch_layout(self):
        W, H = self.WIDTH, self.HEIGHT
        pad = self._sc(16)

        # Reserve a full-width band at the bottom for the Back button so it
        # can never overlap the icon column or the form footer.
        self._back_band_h = self._tt(48) + self._sc(20)

        self._title_top = self._sc(10)
        title_h = self.font_title.get_height()
        self.content_top = self._title_top + title_h + self._sc(10)
        self.content_bottom = H - self._back_band_h

        # ── Left column: icon picker (fixed, not scrolled) ──
        self.icon_col_w = int(W * 0.34)
        icon_cx = pad + self.icon_col_w // 2
        avail_h = self.content_bottom - self.content_top - self._sc(10)

        self.big_r = max(self._sc(30), min(self._sc(52), int(avail_h * 0.20)))
        big_cy = self.content_top + self._sc(10) + self.big_r
        self.big_cx = icon_cx
        self.big_cy = big_cy

        # 3 columns x 4 rows fits all 10 icons in the narrow left column
        # without needing to scroll (unlike the smaller Edit Profile popup).
        cols = 3
        rows_n = 4
        grid_top = big_cy + self.big_r + self._sc(18)
        grid_h = self.content_bottom - grid_top - self._sc(6)
        col_w = self.icon_col_w - 2 * pad
        gap = self._sc(10)
        r_w = (col_w - (cols - 1) * gap) // (2 * cols)
        r_h = (grid_h - (rows_n - 1) * gap) // (2 * rows_n)
        self.sm_r = max(self._sc(18), min(r_w, r_h, self._sc(34)))
        step = self.sm_r * 2 + gap

        self.sm_circles = []
        for idx in range(1, 11):
            col = (idx - 1) % cols
            row = (idx - 1) // cols
            cx = icon_cx + (col - (cols - 1) / 2) * step
            cy = grid_top + self.sm_r + row * step
            self.sm_circles.append((int(cx), int(cy), idx))

        # ── Right column: scrollable form ──
        self.form_x = pad + self.icon_col_w + self._sc(12)
        self.form_w = W - pad - self.form_x
        self.title_left_x = self.form_x   # kept for _draw_title compatibility

        field_specs = [
            ("full_name",  "Full Name",    "e.g. Maria Santos",                 False, 50),
            ("username",   "Username",     "Letters only, max 15",              False, 15),
            ("role",       "Role",         "Select your role",                  False, 0),
            ("workplace",  "Workplace",    "e.g. PGH Rehabilitation Unit",      False, 60),
            ("pin",        "4-Digit PIN",  "Digits only",                       True,  4),
            ("confirm_pin","Confirm PIN",  "Re-enter your 4-digit PIN",         True,  4),
        ]
        self.fields = [
            {"key": k, "label": lbl, "value": "", "placeholder": ph,
             "is_pin": is_pin, "max_len": ml, "rect": pygame.Rect(0, 0, 1, 1)}
            for k, lbl, ph, is_pin, ml in field_specs
        ]
        self.role_open = False
        self.role_opts = []   # populated each draw (position depends on scroll)

        # Fixed footer inside the form column: error/success line, Register
        # button, Login link -- always visible, never scrolled away.
        btn_h = self._tt(48)
        link_h = self.font_login_ln.get_height() + self._sc(8)
        self.footer_h = btn_h + self._sc(8) + link_h + self._sc(6)
        self.register_btn_rect = pygame.Rect(
            self.form_x, self.content_bottom - self.footer_h, self.form_w, btn_h)
        self.login_link_rect = pygame.Rect(
            self.form_x, self.register_btn_rect.bottom + self._sc(8),
            self.form_w, link_h)

        # ── Step 2 (security questions): same idea, single scrollable column ──
        self._sq_x = int(W * 0.14)
        self._sq_w = W - 2 * self._sq_x
        sq_btn_h = self._tt(48)
        self._sq_footer_h = sq_btn_h + self._sc(10)
        self.sq_complete_rect = pygame.Rect(
            (W - self._sc(260)) // 2, self.content_bottom - sq_btn_h,
            self._sc(260), sq_btn_h)
        self.sq_fields = [
            {"q_value": "", "q_open": False, "q_rect": pygame.Rect(0, 0, 1, 1),
             "a_value": "", "a_rect": pygame.Rect(0, 0, 1, 1), "q_opts": []}
            for _ in range(3)
        ]

    # ------------------------------------------------------------------
    # SCENE INTERFACE
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if self.launch_triggered:
            return None

        if self.reg_step == 2:
            return self._sq_handle_event(event)

        # ── Touch: scroll the field column (wheel + finger drag) ──
        if self._touch_ui:
            if event.type == pygame.MOUSEWHEEL:
                self._form_scroll = max(0, min(
                    self._form_scroll - event.y * int(60 * self._fs), self._form_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN and self.content_top <= event.y * self.HEIGHT:
                self._form_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._form_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._form_scroll = max(0, min(
                    self._form_scroll + (self._form_drag_y - cy), self._form_scroll_max))
                self._form_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._form_drag_y = None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if self._touch_ui and self._handle_touch_scroll_click(pos):
                return None

            if self.role_open:
                for opt in self.role_opts:
                    if opt["rect"].collidepoint(pos):
                        play_click()
                        self.fields[2]["value"] = opt["label"]
                        self.role_open          = False
                        return None
                self.role_open = False

            for (cx, cy, idx) in self.sm_circles:
                if math.hypot(pos[0] - cx, pos[1] - cy) <= self.sm_r:
                    play_click()
                    self.selected_icon = idx
                    return None

            clicked_field = False
            for i, f in enumerate(self.fields):
                if f["rect"].collidepoint(pos):
                    if f["key"] == "role":
                        play_click()
                        self.role_open    = not self.role_open
                        self.active_field = -1
                    else:
                        self.active_field = i
                        self.role_open    = False
                    clicked_field = True
                    break
            if not clicked_field:
                self.active_field = -1

            if self.register_btn_rect.collidepoint(pos):
                play_click()
                return self._attempt_create()

            if self.login_link_rect.collidepoint(pos):
                play_click()
                self.launch_triggered = True
                return "login"

            if self._back_rect().collidepoint(pos):
                play_click()
                self.launch_triggered = True
                return "login"

        if event.type == pygame.FINGERDOWN:
            touch = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            if self._touch_ui and self._handle_touch_scroll_click(touch):
                return None
            if self._back_rect().collidepoint(touch):
                play_click()
                self.launch_triggered = True
                return "login"

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.launch_triggered = True
                return "login"
            if self.active_field >= 0:
                self._handle_key(event)

        return None

    def _handle_touch_scroll_click(self, pos):
        """Up/down scroll-arrow taps. Returns True if the tap was consumed."""
        if self._form_up_rect.collidepoint(pos):
            play_click()
            self._form_scroll = max(0, self._form_scroll - int(160 * self._fs))
            return True
        if self._form_down_rect.collidepoint(pos):
            play_click()
            self._form_scroll = min(self._form_scroll_max,
                                    self._form_scroll + int(160 * self._fs))
            return True
        return False

    def _handle_key(self, event):
        f = self.fields[self.active_field]
        if event.key == pygame.K_BACKSPACE:
            f["value"]     = f["value"][:-1]
            self.error_msg = ""
        elif event.key == pygame.K_TAB:
            nxt = self.active_field + 1
            if nxt == 2:     # Skip dropdown interactive index choice typing
                nxt = 3
            self.active_field = nxt % len(self.fields)
        elif event.key == pygame.K_RETURN:
            self._attempt_create()
        elif event.unicode:
            self._type_char(f, event.unicode)
            self.error_msg = ""

    def _type_char(self, field, char):
        key = field["key"]
        if field["is_pin"]:
            if char.isdigit() and len(field["value"]) < 4:
                field["value"] += char
        elif key == "username":
            if char.isalpha() and len(field["value"]) < 15:
                field["value"] += char
        else:
            if field["max_len"] <= 0 or len(field["value"]) < field["max_len"]:
                field["value"] += char

    def _attempt_create(self):
        fn        = self.fields[0]["value"].strip()
        un        = self.fields[1]["value"].strip()
        role      = self.fields[2]["value"].strip()
        workplace = self.fields[3]["value"].strip()
        pin       = self.fields[4]["value"].strip()
        conf_pin  = self.fields[5]["value"].strip()
        idx       = self.selected_icon

        if not fn:                                             self.error_msg = "Full Name is required.";             return None
        if not un:                                             self.error_msg = "Username is required.";              return None
        if not un.isalpha():                                   self.error_msg = "Username: letters only, no spaces."; return None
        if not role:                                           self.error_msg = "Please select a Role.";             return None
        if not workplace:                                      self.error_msg = "Workplace is required.";            return None
        if len(pin) != 4 or not pin.isdigit():                 self.error_msg = "PIN must be exactly 4 digits.";    return None
        if len(conf_pin) != 4 or not conf_pin.isdigit():       self.error_msg = "Confirm PIN must be 4 digits.";     return None
        if pin != conf_pin:                                    self.error_msg = "PINs do not match. Please verify."; return None
        if idx == 0:                                           self.error_msg = "Please choose a profile icon.";    return None

        if self.db.username_exists(un):
            self.error_msg = "Username already taken. Choose another."; return None

        ok = self.db.create_therapist(fn, un, pin, role, workplace, idx)
        if ok:
            therapist = self.db.get_therapist_by_username(un)
            if therapist:
                self.sq_therapist_id = therapist["id"]
            self.reg_step  = 2
            self.error_msg = ""
            return None
        self.error_msg = "Could not create account. Try a different username."
        return None

    def update(self, mouse_pos, dt):
        if self.reg_step == 2:
            self.sq_complete_hov = self.sq_complete_rect.collidepoint(mouse_pos)
            if self.alpha < 255:
                self.alpha = min(255, self.alpha + 4)
            return
        self.back_hovered     = self._back_rect().collidepoint(mouse_pos)
        self.register_hovered = self.register_btn_rect.collidepoint(mouse_pos)
        self.login_ln_hovered = self.login_link_rect.collidepoint(mouse_pos)
        hover_slop = int(8 * (self.HEIGHT / 1080)) if not self._touch_ui else 0
        self.icon_hovered = 0
        for (cx, cy, idx) in self.sm_circles:
            if math.hypot(mouse_pos[0] - cx, mouse_pos[1] - cy) <= self.sm_r + hover_slop:
                self.icon_hovered = idx
                break
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    def draw(self, surface):
        surface.blit(self.background_surface, (0, 0))
        if self.reg_step == 2:
            if self._touch_ui:
                self._draw_step2_touch(surface)
            else:
                self._draw_step2(surface)
        elif self._touch_ui:
            self._draw_title(surface)
            self._draw_icon_picker(surface)
            self._draw_form_touch(surface)
            self._draw_back_link(surface)
        else:
            self._draw_title(surface)
            self._draw_icon_picker(surface)
            self._draw_form(surface)
            self._draw_back_link(surface)
        if self.alpha < 255:
            self.fade_surface.set_alpha(255 - self.alpha)
            surface.blit(self.fade_surface, (0, 0))

    # ------------------------------------------------------------------
    # DRAW HELPERS (shared)
    # ------------------------------------------------------------------

    def _draw_title(self, surface):
        if self._touch_ui:
            ts = self.font_title.render("Create Account", True, (40, 55, 80))
            surface.blit(ts, (self._sc(16), self._title_top))
        else:
            ts = self.font_title.render("Create New Account", True, (40, 55, 80))
            surface.blit(ts, ts.get_rect(
                midleft=(self.title_left_x, int(self.HEIGHT * 0.15))
            ))

    def _draw_icon_picker(self, surface):
        H = self.HEIGHT

        if self.selected_icon == 0:
            bg_color, _, _ = ICONS[0]
            shadow_col = tuple(max(0, c - 45) for c in bg_color)
            shadow_off = max(3, self.big_r // 18)
            pygame.draw.circle(surface, shadow_col, (self.big_cx, self.big_cy + shadow_off), self.big_r)
            pygame.draw.circle(surface, bg_color, (self.big_cx, self.big_cy), self.big_r)
            hint = self.font_caption.render("choose icon", True, (70, 95, 125))
            surface.blit(hint, hint.get_rect(center=(self.big_cx, self.big_cy)))
        else:
            draw_icon(surface, self.selected_icon, self.big_cx, self.big_cy,
                      self.big_r, shadow=True)

        for (cx, cy, idx) in self.sm_circles:
            selected = (self.selected_icon == idx)
            hovered  = (self.icon_hovered == idx)
            radius   = self.sm_r + (int(6 * (H / 1080)) if hovered else 0)
            border_color = (40, 160, 220) if selected else ((120, 180, 230) if hovered else None)
            border_width = 4 if selected else (3 if hovered else 0)
            draw_icon(surface, idx, cx, cy, radius,
                      shadow=True,
                      border_color=border_color,
                      border_width=border_width)
            if hovered and not selected:
                glow = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
                pygame.draw.circle(glow, (40, 160, 220, 35), (radius + 4, radius + 4), radius + 4)
                surface.blit(glow, (cx - radius - 4, cy - radius - 4))

    # ------------------------------------------------------------------
    # DESKTOP FORM (unchanged)
    # ------------------------------------------------------------------

    def _draw_form(self, surface):
        W, H = self.WIDTH, self.HEIGHT

        for i, field in enumerate(self.fields):
            active = (i == self.active_field)
            rect   = field["rect"]

            lbl_y = rect.y - int(24 * H / 1080)
            ls    = self.font_label.render(field["label"], True, (55, 72, 95))
            surface.blit(ls, (rect.x, lbl_y))

            pygame.draw.rect(surface, (255, 255, 255), rect, border_radius=10)
            border_col = (40, 160, 220) if active else (195, 210, 228)
            border_w   = 3 if active else 2
            pygame.draw.rect(surface, border_col, rect, border_w, border_radius=10)

            if field["key"] == "role":
                val  = field["value"] or field["placeholder"]
                col  = (40, 50, 65) if field["value"] else (170, 183, 200)
                ts   = self.font_dropdown.render(val, True, col)
                surface.blit(ts, ts.get_rect(
                    midleft=(rect.x + int(14 * W / 1920), rect.centery)
                ))
                chev = self.font_sym.render("▼", True, (90, 110, 140))
                surface.blit(chev, chev.get_rect(
                    midright=(rect.right - int(14 * W / 1920), rect.centery)
                ))
            else:
                val = field["value"]
                if not val:
                    ts = self.font_input.render(field["placeholder"], True, (175, 188, 205))
                else:
                    disp = "•" * len(val) if field["is_pin"] else val
                    ts   = self.font_input.render(disp, True, (30, 45, 65))
                surface.blit(ts, ts.get_rect(
                    midleft=(rect.x + int(14 * W / 1920), rect.centery)
                ))
                if active and val:
                    cur_x = rect.x + int(14 * W / 1920) + ts.get_width() + 2
                    pygame.draw.line(
                        surface, (40, 160, 220),
                        (cur_x, rect.centery - int(10 * H / 1080)),
                        (cur_x, rect.centery + int(10 * H / 1080)), 2
                    )

        if self.role_open:
            rf    = self.fields[2]["rect"]
            opt_h = self.role_opts[0]["rect"].height
            ph    = len(ROLES) * opt_h + 6
            pr    = pygame.Rect(rf.x, rf.bottom - 1, rf.width, ph)
            pygame.draw.rect(surface, (248, 251, 255), pr, border_radius=10)
            pygame.draw.rect(surface, (40, 160, 220),  pr, 2, border_radius=10)
            for j, opt in enumerate(self.role_opts):
                if j % 2 == 0:
                    shade = pygame.Surface((pr.width - 4, opt_h), pygame.SRCALPHA)
                    shade.fill((40, 160, 220, 18))
                    surface.blit(shade, (pr.x + 2, opt["rect"].y))
                ts = self.font_dropdown.render(opt["label"], True, (40, 50, 65))
                surface.blit(ts, ts.get_rect(
                    midleft=(opt["rect"].x + int(14 * W / 1920), opt["rect"].centery)
                ))

        if self.error_msg:
            es = self.font_error.render(self.error_msg, True, (210, 50, 50))
            surface.blit(es, es.get_rect(
                midleft=(self.register_btn_rect.x,
                         self.register_btn_rect.y - int(20 * H / 1080))
            ))

        bc = (25, 130, 185) if self.register_hovered else (40, 160, 220)
        pygame.draw.rect(surface, bc, self.register_btn_rect, border_radius=12)
        cs = self.font_btn.render("Register", True, (255, 255, 255))
        surface.blit(cs, cs.get_rect(center=self.register_btn_rect.center))

        parts = [
            ("Already have an account? ", (110, 125, 150)),
            ("Login", (40, 150, 215) if self.login_ln_hovered else (60, 130, 200)),
        ]
        x_cursor = self.login_link_rect.x
        link_y   = self.login_link_rect.centery
        for text, col in parts:
            ts = self.font_login_ln.render(text, True, col)
            surface.blit(ts, ts.get_rect(midleft=(x_cursor, link_y)))
            x_cursor += ts.get_width()

    # ------------------------------------------------------------------
    # TOUCH FORM (scrollable field column + fixed footer)
    # ------------------------------------------------------------------

    def _draw_form_touch(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        x0 = self.form_x
        fw = self.form_w
        fh = self._tt(46)
        lbl_h = self.font_label.get_height()
        row_h = lbl_h + self._sc(4) + fh + self._sc(16)

        top = self.content_top
        bottom = self.register_btn_rect.top - self._sc(10)
        view_h = bottom - top
        total = len(self.fields) * row_h + self._sc(8)
        self._form_scroll_max = max(0, total - view_h)
        self._form_scroll = max(0, min(self._form_scroll, self._form_scroll_max))
        arrow_w = self._tt(40) if self._form_scroll_max > 0 else 0
        field_w = fw - (arrow_w + self._sc(8) if arrow_w else 0)

        open_overlay = None

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(x0, top, fw, view_h))
        y = top - self._form_scroll
        self.role_opts = []
        for i, field in enumerate(self.fields):
            fr = pygame.Rect(x0, y + lbl_h + self._sc(4), field_w, fh)
            visible = fr.bottom >= top and fr.top <= bottom
            field["rect"] = fr if visible else pygame.Rect(-9, -9, 1, 1)
            if visible:
                active = (self.active_field == i)
                surface.blit(self.font_label.render(field["label"], True, (55, 72, 95)), (x0, y))
                pygame.draw.rect(surface, (255, 255, 255), fr, border_radius=10)
                border_col = (40, 160, 220) if active else (195, 210, 228)
                pygame.draw.rect(surface, border_col, fr, 3 if active else 2, border_radius=10)

                if field["key"] == "role":
                    val = field["value"] or field["placeholder"]
                    col = (40, 50, 65) if field["value"] else (170, 183, 200)
                    ts = self.font_dropdown.render(val, True, col)
                    surface.blit(ts, ts.get_rect(midleft=(fr.x + self._sc(14), fr.centery)))
                    chev = self.font_sym.render("▼", True, (90, 110, 140))
                    surface.blit(chev, chev.get_rect(midright=(fr.right - self._sc(14), fr.centery)))
                    if self.role_open:
                        open_overlay = fr
                else:
                    val = field["value"]
                    if not val:
                        ts = self.font_input.render(field["placeholder"], True, (175, 188, 205))
                    else:
                        disp = "•" * len(val) if field["is_pin"] else val
                        ts = self.font_input.render(disp, True, (30, 45, 65))
                    surface.blit(ts, ts.get_rect(midleft=(fr.x + self._sc(14), fr.centery)))
                    if active and val:
                        cur_x = fr.x + self._sc(14) + ts.get_width() + 2
                        pygame.draw.line(surface, (40, 160, 220),
                                         (cur_x, fr.centery - self._sc(10)),
                                         (cur_x, fr.centery + self._sc(10)), 2)
            y += row_h
        surface.set_clip(prev_clip)

        if self._form_scroll_max > 0:
            ax = x0 + fw - arrow_w
            ah = view_h // 2 - self._sc(4)
            self._form_up_rect = pygame.Rect(ax, top, arrow_w, ah)
            self._form_down_rect = pygame.Rect(ax, top + ah + self._sc(8), arrow_w, ah)
            for r, tri, on in ((self._form_up_rect, "▲", self._form_scroll > 0),
                              (self._form_down_rect, "▼",
                               self._form_scroll < self._form_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244),
                                 r, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r, 1, border_radius=8)
                g = self.font_sym.render(tri, True,
                                         (45, 90, 150) if on else (188, 196, 206))
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._form_up_rect = self._form_down_rect = pygame.Rect(0, 0, 1, 1)

        # Open Role dropdown, drawn on top and unclipped.
        if open_overlay is not None:
            opts = ROLES
            opt_h = self._tt(42)
            lst_h = len(opts) * opt_h + 4
            base_y = (open_overlay.top - lst_h
                     if open_overlay.bottom + lst_h > self.content_bottom
                     else open_overlay.bottom)
            dp = pygame.Rect(open_overlay.x, base_y, open_overlay.width, lst_h)
            pygame.draw.rect(surface, (248, 251, 255), dp, border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220), dp, 2, border_radius=9)
            mp = pygame.mouse.get_pos()
            self.role_opts = []
            for j, opt in enumerate(opts):
                orr = pygame.Rect(open_overlay.x, base_y + j * opt_h, open_overlay.width, opt_h)
                if orr.collidepoint(mp):
                    pygame.draw.rect(surface, (220, 236, 255), orr, border_radius=6)
                ts = self.font_dropdown.render(opt, True, (40, 50, 65))
                surface.blit(ts, ts.get_rect(midleft=(orr.x + self._sc(14), orr.centery)))
                self.role_opts.append({"label": opt, "rect": orr})

        # ── Fixed footer: error message + Register button + Login link ──
        if self.error_msg:
            es = self.font_error.render(self.error_msg, True, (210, 50, 50))
            avail = fw
            if es.get_width() > avail:
                txt = self.error_msg
                while txt and self.font_error.size(txt + "…")[0] > avail:
                    txt = txt[:-1]
                es = self.font_error.render(txt + "…", True, (210, 50, 50))
            surface.blit(es, (x0, self.register_btn_rect.y - es.get_height() - self._sc(4)))

        bc = (25, 130, 185) if self.register_hovered else (40, 160, 220)
        pygame.draw.rect(surface, bc, self.register_btn_rect, border_radius=12)
        cs = self.font_btn.render("Register", True, (255, 255, 255))
        surface.blit(cs, cs.get_rect(center=self.register_btn_rect.center))

        parts = [
            ("Already have an account? ", (110, 125, 150)),
            ("Login", (40, 150, 215) if self.login_ln_hovered else (60, 130, 200)),
        ]
        x_cursor = self.login_link_rect.x
        link_y   = self.login_link_rect.centery
        for text, col in parts:
            ts = self.font_login_ln.render(text, True, col)
            surface.blit(ts, ts.get_rect(midleft=(x_cursor, link_y)))
            x_cursor += ts.get_width()

    # ------------------------------------------------------------------
    # STEP 2 — SECURITY QUESTIONS
    # ------------------------------------------------------------------

    def _sq_handle_event(self, event):
        """Route events when reg_step == 2."""
        if self._touch_ui:
            if event.type == pygame.MOUSEWHEEL:
                self._sq_scroll = max(0, min(
                    self._sq_scroll - event.y * int(60 * self._fs), self._sq_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._sq_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._sq_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._sq_scroll = max(0, min(
                    self._sq_scroll + (self._sq_drag_y - cy), self._sq_scroll_max))
                self._sq_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._sq_drag_y = None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._sq_handle_click(event.pos)
        if event.type == pygame.FINGERDOWN:
            touch = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            return self._sq_handle_click(touch)
        if event.type == pygame.KEYDOWN:
            self._sq_handle_key(event)
        return None

    def _sq_handle_click(self, pos):
        if self._touch_ui:
            if self._sq_up_rect.collidepoint(pos):
                play_click()
                self._sq_scroll = max(0, self._sq_scroll - int(160 * self._fs))
                return None
            if self._sq_down_rect.collidepoint(pos):
                play_click()
                self._sq_scroll = min(self._sq_scroll_max, self._sq_scroll + int(160 * self._fs))
                return None

        # Close any open dropdown if click is outside it
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
            sf["a_value"]     = sf["a_value"][:-1]
            self.sq_error_msg = ""
        elif event.key == pygame.K_TAB:
            self.sq_active_slot = (self.sq_active_slot + 1) % 3
        elif event.key == pygame.K_RETURN:
            self.sq_active_slot = None
        elif event.unicode:
            sf["a_value"]     += event.unicode
            self.sq_error_msg  = ""

    def _sq_submit(self):
        chosen_questions = [sf["q_value"] for sf in self.sq_fields]
        answers          = [sf["a_value"].strip() for sf in self.sq_fields]

        for i in range(3):
            if not chosen_questions[i]:
                self.sq_error_msg = f"Please select Question {i + 1}."
                return None
            if not answers[i]:
                self.sq_error_msg = f"Please enter an answer for Question {i + 1}."
                return None

        if len(set(chosen_questions)) < 3:
            self.sq_error_msg = "Each security question must be different."
            return None

        if self.sq_therapist_id:
            self.db.set_security_questions(
                self.sq_therapist_id,
                chosen_questions[0], answers[0],
                chosen_questions[1], answers[1],
                chosen_questions[2], answers[2],
            )

        self.launch_triggered = True
        return "login"

    def _draw_step2(self, surface):
        W, H = self.WIDTH, self.HEIGHT

        ts = self.font_title.render("Set Up Security Questions", True, (40, 55, 80))
        surface.blit(ts, ts.get_rect(center=(W // 2, int(H * 0.11))))

        sub = self.font_caption.render(
            "These help verify your identity. Choose 3 different questions.",
            True, (100, 120, 150)
        )
        surface.blit(sub, sub.get_rect(center=(W // 2, int(H * 0.16))))

        open_slot = next((i for i, sf in enumerate(self.sq_fields) if sf["q_open"]), None)

        for i, sf in enumerate(self.sq_fields):
            q_rect = sf["q_rect"]
            a_rect = sf["a_rect"]
            a_active = (self.sq_active_slot == i)

            lbl = self.font_label.render(f"Question {i + 1}", True, (55, 72, 95))
            surface.blit(lbl, (q_rect.x, q_rect.y - int(24 * H / 1080)))

            if not sf["q_open"]:
                self._sq_draw_dropdown(surface, sf, q_rect, W)

            a_lbl = self.font_label.render("Answer", True, (55, 72, 95))
            surface.blit(a_lbl, (a_rect.x, a_rect.y - int(22 * H / 1080)))
            pygame.draw.rect(surface, (255, 255, 255), a_rect, border_radius=10)
            border_col = (40, 160, 220) if a_active else (195, 210, 228)
            pygame.draw.rect(surface, border_col, a_rect, 3 if a_active else 2, border_radius=10)
            if sf["a_value"]:
                vs = self.font_input.render(sf["a_value"], True, (30, 45, 65))
                surface.blit(vs, vs.get_rect(midleft=(a_rect.x + int(14 * W / 1920), a_rect.centery)))
                if a_active:
                    cur_x = a_rect.x + int(14 * W / 1920) + vs.get_width() + 2
                    pygame.draw.line(
                        surface, (40, 160, 220),
                        (cur_x, a_rect.centery - int(10 * H / 1080)),
                        (cur_x, a_rect.centery + int(10 * H / 1080)), 2
                    )
            else:
                ph = self.font_input.render("Type your answer here", True, (175, 188, 205))
                surface.blit(ph, ph.get_rect(midleft=(a_rect.x + int(14 * W / 1920), a_rect.centery)))

        if self.sq_error_msg:
            es = self.font_error.render(self.sq_error_msg, True, (210, 50, 50))
            surface.blit(es, es.get_rect(
                midleft=(self.sq_complete_rect.x,
                         self.sq_complete_rect.y - int(20 * H / 1080))
            ))

        bc = (25, 130, 185) if self.sq_complete_hov else (40, 160, 220)
        pygame.draw.rect(surface, bc, self.sq_complete_rect, border_radius=12)
        cs = self.font_btn.render("Complete Setup", True, (255, 255, 255))
        surface.blit(cs, cs.get_rect(center=self.sq_complete_rect.center))

        if open_slot is not None:
            sf = self.sq_fields[open_slot]
            self._sq_draw_dropdown(surface, sf, sf["q_rect"], W)
            self._sq_draw_options(surface, sf, W)

    def _draw_step2_touch(self, surface):
        """Same 3 Q&A slots, but scrollable -- 3 dropdown+answer pairs at
        touch-target sizes do not fit in 480px, so this column scrolls while
        the title and the Complete Setup button stay fixed."""
        W, H = self.WIDTH, self.HEIGHT
        x0, w = self._sq_x, self._sq_w

        ts = self.font_title.render("Security Questions", True, (40, 55, 80))
        surface.blit(ts, (self._sc(16), self._title_top))
        sub = self.font_caption.render(
            "These help verify your identity. Choose 3 different questions.",
            True, (100, 120, 150))
        surface.blit(sub, (self._sc(16), self._title_top + ts.get_height() + self._sc(2)))

        top = self._title_top + ts.get_height() + sub.get_height() + self._sc(14)
        bottom = self.sq_complete_rect.top - self._sc(10)
        view_h = bottom - top

        fh = self._tt(46)
        lbl_h = self.font_label.get_height()
        slot_h = (lbl_h + self._sc(2) + fh) * 2 + self._sc(10) + self._sc(18)
        total = slot_h * 3
        self._sq_scroll_max = max(0, total - view_h)
        self._sq_scroll = max(0, min(self._sq_scroll, self._sq_scroll_max))
        arrow_w = self._tt(40) if self._sq_scroll_max > 0 else 0
        col_w = w - (arrow_w + self._sc(8) if arrow_w else 0)

        open_overlay = None
        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(x0, top, w, view_h))
        y = top - self._sq_scroll
        for i, sf in enumerate(self.sq_fields):
            q_rect = pygame.Rect(x0, y + lbl_h + self._sc(2), col_w, fh)
            a_rect = pygame.Rect(x0, q_rect.bottom + lbl_h + self._sc(12), col_w, fh)
            slot_visible = a_rect.bottom >= top and q_rect.top <= bottom
            sf["q_rect"] = q_rect if slot_visible else pygame.Rect(-9, -9, 1, 1)
            sf["a_rect"] = a_rect if slot_visible else pygame.Rect(-9, -9, 1, 1)
            if slot_visible:
                lbl = self.font_label.render(f"Question {i + 1}", True, (55, 72, 95))
                surface.blit(lbl, (x0, y))
                self._sq_draw_dropdown(surface, sf, q_rect, W)
                if sf["q_open"]:
                    open_overlay = (sf, q_rect)

                a_lbl = self.font_label.render("Answer", True, (55, 72, 95))
                surface.blit(a_lbl, (x0, q_rect.bottom + self._sc(2)))
                a_active = (self.sq_active_slot == i)
                pygame.draw.rect(surface, (255, 255, 255), a_rect, border_radius=10)
                border_col = (40, 160, 220) if a_active else (195, 210, 228)
                pygame.draw.rect(surface, border_col, a_rect, 3 if a_active else 2, border_radius=10)
                if sf["a_value"]:
                    vs = self.font_input.render(sf["a_value"], True, (30, 45, 65))
                    surface.blit(vs, vs.get_rect(midleft=(a_rect.x + self._sc(14), a_rect.centery)))
                    if a_active:
                        cur_x = a_rect.x + self._sc(14) + vs.get_width() + 2
                        pygame.draw.line(surface, (40, 160, 220),
                                         (cur_x, a_rect.centery - self._sc(10)),
                                         (cur_x, a_rect.centery + self._sc(10)), 2)
                else:
                    ph = self.font_input.render("Type your answer here", True, (175, 188, 205))
                    surface.blit(ph, ph.get_rect(midleft=(a_rect.x + self._sc(14), a_rect.centery)))
            y += slot_h
        surface.set_clip(prev_clip)

        if self._sq_scroll_max > 0:
            ax = x0 + w - arrow_w
            ah = view_h // 2 - self._sc(4)
            self._sq_up_rect = pygame.Rect(ax, top, arrow_w, ah)
            self._sq_down_rect = pygame.Rect(ax, top + ah + self._sc(8), arrow_w, ah)
            for r, tri, on in ((self._sq_up_rect, "▲", self._sq_scroll > 0),
                              (self._sq_down_rect, "▼", self._sq_scroll < self._sq_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244),
                                 r, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r, 1, border_radius=8)
                g = self.font_sym.render(tri, True,
                                         (45, 90, 150) if on else (188, 196, 206))
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._sq_up_rect = self._sq_down_rect = pygame.Rect(0, 0, 1, 1)

        if open_overlay is not None:
            sf, q_rect = open_overlay
            self._sq_draw_options(surface, sf, W, base_rect=q_rect)

        if self.sq_error_msg:
            es = self.font_error.render(self.sq_error_msg, True, (210, 50, 50))
            surface.blit(es, (x0, self.sq_complete_rect.y - es.get_height() - self._sc(4)))

        bc = (25, 130, 185) if self.sq_complete_hov else (40, 160, 220)
        pygame.draw.rect(surface, bc, self.sq_complete_rect, border_radius=12)
        cs = self.font_btn.render("Complete Setup", True, (255, 255, 255))
        surface.blit(cs, cs.get_rect(center=self.sq_complete_rect.center))

    def _sq_draw_dropdown(self, surface, sf, q_rect, W):
        pygame.draw.rect(surface, (255, 255, 255), q_rect, border_radius=10)
        border_col = (40, 160, 220) if sf["q_open"] else (195, 210, 228)
        pygame.draw.rect(surface, border_col, q_rect, 3 if sf["q_open"] else 2, border_radius=10)
        val = sf["q_value"] or "Select a security question…"
        col = (40, 50, 65) if sf["q_value"] else (170, 183, 200)
        ts  = self.font_dropdown.render(val, True, col)
        clip_w = q_rect.width - int(40 * W / 1920 if not self._touch_ui else self._sc(40))
        if ts.get_width() > clip_w:
            ts = ts.subsurface(pygame.Rect(0, 0, max(1, clip_w), ts.get_height()))
        surface.blit(ts, ts.get_rect(midleft=(q_rect.x + (int(14*W/1920) if not self._touch_ui else self._sc(14)), q_rect.centery)))
        chev = self.font_sym.render("▼" if not sf["q_open"] else "▲", True, (90, 110, 140))
        surface.blit(chev, chev.get_rect(midright=(q_rect.right - (int(14*W/1920) if not self._touch_ui else self._sc(14)), q_rect.centery)))

    def _sq_draw_options(self, surface, sf, W, base_rect=None):
        q_rect = base_rect if base_rect is not None else sf["q_rect"]
        opt_h  = self._tt(40) if self._touch_ui else q_rect.height
        ph     = len(SECURITY_QUESTIONS) * opt_h + 6
        if self._touch_ui and q_rect.bottom + ph > self.content_bottom:
            pr = pygame.Rect(q_rect.x, q_rect.top - ph, q_rect.width, ph)
        else:
            pr = pygame.Rect(q_rect.x, q_rect.bottom - 1, q_rect.width, ph)
        pygame.draw.rect(surface, (248, 251, 255), pr, border_radius=10)
        pygame.draw.rect(surface, (40, 160, 220), pr, 2, border_radius=10)
        sf["q_opts"] = []
        pad = int(14 * W / 1920) if not self._touch_ui else self._sc(14)
        for j in range(len(SECURITY_QUESTIONS)):
            opt_r = pygame.Rect(pr.x, pr.y + 3 + j * opt_h, pr.width, opt_h)
            if j % 2 == 0:
                shade = pygame.Surface((pr.width - 4, opt_h), pygame.SRCALPHA)
                shade.fill((40, 160, 220, 18))
                surface.blit(shade, (pr.x + 2, opt_r.y))
            ts = self.font_dropdown.render(SECURITY_QUESTIONS[j], True, (40, 50, 65))
            clip_w = pr.width - int(28 * W / 1920 if not self._touch_ui else self._sc(28))
            if ts.get_width() > clip_w:
                ts = ts.subsurface(pygame.Rect(0, 0, max(1, clip_w), ts.get_height()))
            surface.blit(ts, ts.get_rect(midleft=(opt_r.x + pad, opt_r.centery)))
            sf["q_opts"].append(opt_r)

    # ------------------------------------------------------------------
    # BACK BUTTON
    # ------------------------------------------------------------------

    def _draw_back_link(self, surface):
        """Text-only Back button (same fix as the Login page): the old label
        was the literal string "<- Back" using U+2190, a glyph Lexend-Light
        has no shape for -- it rendered as an empty box next to the word.
        No icon at all now; a real bordered pill matching the dashboard's
        Back control, with the hit rect equal to what's drawn."""
        r = self._back_rect()
        hov = self.back_hovered
        pygame.draw.rect(surface, (255, 255, 255) if not hov else (236, 243, 252),
                         r, border_radius=10)
        pygame.draw.rect(surface, (95, 130, 175) if hov else (150, 175, 210),
                         r, 2, border_radius=10)
        col = (45, 80, 130) if hov else (70, 95, 130)
        s = self.font_back.render("Back", True, col)
        surface.blit(s, s.get_rect(center=r.center))

    def _back_rect(self):
        """Hit area == the drawn pill (previously started at x=0 while the
        text was drawn at x=30, so the tappable area didn't match what was
        visible)."""
        bw = max(self._tt(120), self.font_back.size("Back")[0] + self._sc(40))
        bh = self._tt(48)
        m  = self._sc(16)
        return pygame.Rect(m, self.HEIGHT - bh - m, bw, bh)

    def _create_gradient(self, width, height):
        scale = 4; sw = width // scale; sh = height // scale
        s = pygame.Surface((sw, sh), depth=32).convert()
        w = (255,255,255); pb = (185,215,255); pp = (225,185,255); wf = sw * 0.75
        for y in range(sh):
            for x in range(sw):
                wb = max(0, 1.0 - (x + y) / wf)
                wp = max(0, 1.0 - ((sw - x) + (sh - y)) / wf)
                tc = wb + wp
                if tc > 1.0: wb /= tc; wp /= tc; ww = 0.0
                else:         ww = 1.0 - tc
                r = min(255, max(0, int(pb[0]*wb + pp[0]*wp + w[0]*ww)))
                g = min(255, max(0, int(pb[1]*wb + pp[1]*wp + w[1]*ww)))
                b = min(255, max(0, int(pb[2]*wb + pp[2]*wp + w[2]*ww)))
                s.set_at((x, y), s.map_rgb((r, g, b)))
        return pygame.transform.smoothscale(s, (width, height))
