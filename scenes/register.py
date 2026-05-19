# =============================================================================
# scenes/register.py
# =============================================================================
# Register / Create Account screen.
# Layout:
#   Centered workspace block encompassing both the left icon selector
#   and right form inputs cleanly without overlaps.
# =============================================================================

import pygame
import math
import sys
import os

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


class RegisterScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height
        self.db     = Database()

        # --- FONTS ---
        self.font_title    = pygame.font.SysFont("georgia",  int(34 * (height / 1080)), bold=True)
        self.font_label    = pygame.font.SysFont("georgia",  int(18 * (height / 1080)))
        self.font_input    = pygame.font.SysFont("arial",    int(19 * (height / 1080)))
        self.font_caption  = pygame.font.SysFont("georgia",  int(16 * (height / 1080)), italic=True)
        self.font_btn      = pygame.font.SysFont("arial",    int(19 * (height / 1080)), bold=True)
        self.font_back     = pygame.font.SysFont("georgia",  int(17 * (height / 1080)), italic=True)
        self.font_login_ln = pygame.font.SysFont("georgia",  int(16 * (height / 1080)))
        self.font_error    = pygame.font.SysFont("georgia",  int(15 * (height / 1080)), italic=True)
        self.font_dropdown = pygame.font.SysFont("arial",    int(17 * (height / 1080)))

        # --- BACKGROUND ---
        self.background_surface = self._create_gradient(width, height)

        # ----------------------------------------------------------------
        # CENTRALIZED GLOBAL COORDINATE CALCULATIONS
        # ----------------------------------------------------------------
        # Define block widths and gutters to treat left and right columns as a unit
        icon_area_w = int(width * 0.26)
        form_w      = int(width * 0.42)
        inner_gutter = int(width * 0.06)
        
        total_content_w = icon_area_w + inner_gutter + form_w
        start_x = (width - total_content_w) // 2

        # Left column visual center anchor
        left_zone_cx = start_x + (icon_area_w // 2)
        # Right column horizontal starting point
        fx = start_x + icon_area_w + inner_gutter
        fw = form_w

        # Squeezed gap layout vertically to fit 6 full fields elegantly
        field_h   = int(38 * (height / 1080))
        field_gap = field_h + int(32 * (height / 1080))  
        
        # Pushed down from 0.17 to 0.23 to noticeably drop the layout lower
        form_top  = int(height * 0.23) 

        # ----------------------------------------------------------------
        # LEFT COLUMN — icon picker
        # ----------------------------------------------------------------
        # Big preview circle sits near the top of the workspace row
        big_r      = int(82 * (height / 1080))
        big_cy     = form_top + int(60 * (height / 1080))  
        self.big_r  = big_r
        self.big_cx = left_zone_cx
        self.big_cy = big_cy

        # Small icon grid: 4 columns × 3 rows
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

        # ----------------------------------------------------------------
        # RIGHT COLUMN — form setup
        # ----------------------------------------------------------------
        self.fields = [
            {
                "key": "full_name",  "label": "Full Name",
                "value": "", "placeholder": "e.g. Maria Santos",
                "is_pin": False, "max_len": 50,
                "rect": pygame.Rect(fx, form_top + 0 * field_gap, fw, field_h),
            },
            {
                "key": "username",   "label": "Username",
                "value": "", "placeholder": "Letters only, max 15 characters",
                "is_pin": False, "max_len": 15,
                "rect": pygame.Rect(fx, form_top + 1 * field_gap, fw, field_h),
            },
            {
                "key": "role",       "label": "Role",
                "value": "", "placeholder": "Select your role",
                "is_pin": False, "max_len": 0,
                "rect": pygame.Rect(fx, form_top + 2 * field_gap, fw, field_h),
            },
            {
                "key": "workplace",  "label": "Workplace",
                "value": "", "placeholder": "e.g. PGH Rehabilitation Unit",
                "is_pin": False, "max_len": 60,
                "rect": pygame.Rect(fx, form_top + 3 * field_gap, fw, field_h),
            },
            {
                "key": "pin",        "label": "4-Digit PIN",
                "value": "", "placeholder": "Digits only",
                "is_pin": True,  "max_len": 4,
                "rect": pygame.Rect(fx, form_top + 4 * field_gap, fw, field_h),
            },
            {
                "key": "confirm_pin", "label": "Confirm PIN",
                "value": "", "placeholder": "Re-enter your 4-digit PIN",
                "is_pin": True,  "max_len": 4,
                "rect": pygame.Rect(fx, form_top + 5 * field_gap, fw, field_h),
            },
        ]

        # Title alignment variable (Brought down proportionally with the workspace)
        self.title_left_x = fx

        # Role dropdown setup linked directly to field layout index [2]
        role_rect  = self.fields[2]["rect"]
        opt_h      = int(38 * (height / 1080))
        self.role_opts = [
            {
                "label": r,
                "rect": pygame.Rect(fx, role_rect.bottom + i * opt_h, fw, opt_h),
            }
            for i, r in enumerate(ROLES)
        ]
        self.role_open = False

        # ----------------------------------------------------------------
        # BUTTONS / LINKS (Sitting compactly beneath fields)
        # ----------------------------------------------------------------
        last_field_rect = self.fields[-1]["rect"]
        btn_y  = last_field_rect.bottom + int(45 * (height / 1080))
        btn_h  = int(50 * (height / 1080))
        btn_w  = int(fw * 0.50)
        
        self.register_btn_rect = pygame.Rect(fx, btn_y, btn_w, btn_h)

        self.login_link_rect = pygame.Rect(
            fx, btn_y + btn_h + int(12 * (height / 1080)),
            fw, int(28 * (height / 1080))
        )

        # ----------------------------------------------------------------
        # STATE
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

    # ------------------------------------------------------------------
    # SCENE INTERFACE
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if self.launch_triggered:
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos

            if self.role_open:
                for opt in self.role_opts:
                    if opt["rect"].collidepoint(pos):
                        self.fields[2]["value"] = opt["label"]
                        self.role_open          = False
                        return None
                self.role_open = False

            for (cx, cy, idx) in self.sm_circles:
                if math.hypot(pos[0] - cx, pos[1] - cy) <= self.sm_r:
                    self.selected_icon = idx
                    return None

            clicked_field = False
            for i, f in enumerate(self.fields):
                if f["rect"].collidepoint(pos):
                    if f["key"] == "role":
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
                return self._attempt_create()

            if self.login_link_rect.collidepoint(pos):
                self.launch_triggered = True
                return "login"

            if self._back_rect().collidepoint(pos):
                self.launch_triggered = True
                return "login"

        if event.type == pygame.FINGERDOWN:
            touch = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            if self._back_rect().collidepoint(touch):
                self.launch_triggered = True
                return "login"

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.launch_triggered = True
                return "login"
            if self.active_field >= 0:
                self._handle_key(event)

        return None

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
            self.launch_triggered = True
            return "login"
        self.error_msg = "Could not create account. Try a different username."
        return None

    def update(self, mouse_pos, dt):
        self.back_hovered     = self._back_rect().collidepoint(mouse_pos)
        self.register_hovered = self.register_btn_rect.collidepoint(mouse_pos)
        self.login_ln_hovered = self.login_link_rect.collidepoint(mouse_pos)
        self.icon_hovered = 0
        for (cx, cy, idx) in self.sm_circles:
            if math.hypot(mouse_pos[0] - cx, mouse_pos[1] - cy) <= self.sm_r + int(8 * (self.HEIGHT / 1080)):
                self.icon_hovered = idx
                break
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    def draw(self, surface):
        surface.blit(self.background_surface, (0, 0))
        self._draw_title(surface)
        self._draw_icon_picker(surface)
        self._draw_form(surface)
        self._draw_back_link(surface)
        if self.alpha < 255:
            self.fade_surface.set_alpha(255 - self.alpha)
            surface.blit(self.fade_surface, (0, 0))

    # ------------------------------------------------------------------
    # DRAW HELPERS
    # ------------------------------------------------------------------

    def _draw_title(self, surface):
        ts = self.font_title.render("Create New Account", True, (40, 55, 80))
        surface.blit(ts, ts.get_rect(
            midleft=(self.title_left_x, int(self.HEIGHT * 0.15)) # Lowered safely above the new form_top position
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
                chev = self.font_dropdown.render("▼", True, (90, 110, 140))
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

    def _draw_back_link(self, surface):
        col  = (80, 105, 140) if self.back_hovered else (160, 175, 195)
        surf = self.font_back.render("← Back", True, col)
        rect = surf.get_rect(
            bottomleft=(int(30 * self.WIDTH / 1920),
                        self.HEIGHT - int(24 * self.HEIGHT / 1080))
        )
        surface.blit(surf, rect)

    def _back_rect(self):
        return pygame.Rect(
            0, self.HEIGHT - int(55 * self.HEIGHT / 1080),
            int(130 * self.WIDTH / 1920), int(44 * self.HEIGHT / 1080)
        )

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