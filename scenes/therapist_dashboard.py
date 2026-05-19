# =============================================================================
# scenes/therapist_dashboard.py
# =============================================================================
#
# CHANGES vs previous version:
#   1. Table column widths widened across Patients / Session History / Calibration
#       so longer Patient Names, IDs (10 chars), Severity, and Therapist all fit;
#       row heights and inter-row spacing increased to match the bigger font.
#   2. Register Patient row_gap increased (58→72px) and fh increased (36→40px)
#      to prevent field overlap
#   3. Register Patient dropdowns now draw in a second pass so they always
#      appear on top of all other fields (z-order fix)
#   4. Calibration bypass toggle added to Start Session panel for dev testing
#   5. Patients are now private per therapist — get_all_patients filters by
#      therapist_id so each therapist only sees their own patients plus those
#      explicitly shared with them
#   6. Share Patient modal — therapists can share a patient with another therapist
#      by searching their username; stored in patient_shares junction table
#
# FLOW:
#   Home (4 cards) → Patient List → [select patient] → Game Configuration
#                                 → [game set]       → Start Session
#   Home           → Session History
#   Home           → Analytics
#   Home           → Calibration Records
#
# NAV_IDX mapping (used internally):
#   0 = Patient List          (home card 0)
#   1 = Session History       (home card 1)
#   2 = Analytics             (home card 2)
#   3 = Calibration Records   (home card 3)
#   4 = Game Configuration    (NOT on home — reached via Patient List)
#   5 = Start Session         (NOT on home — reached via Game Config)
#   6 = Register Patient      (NOT on home — reached via Patient List)
# =============================================================================

import pygame
import sys, os, math, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database
from scenes.icon_renderer import draw_icon, ICONS
from scenes.calibration_window import CalibrationWindow

# ─────────────────────────────────────────────────────────────────────
#  NAV / PANEL CONSTANTS
# ─────────────────────────────────────────────────────────────────────

HOME_CARDS = [
    {"label": "Patient List",         "symbol": "👤", "idx": 0},
    {"label": "Session History",      "symbol": "📋", "idx": 1},
    {"label": "Analytics",            "symbol": "📊", "idx": 2},
    {"label": "Calibration Records",  "symbol": "🎯", "idx": 3},
]

HOME_COLORS = [
    (100, 180, 240),
    (240, 170,  90),
    (190, 130, 220),
    (235, 100, 120),
]

PANEL_TITLES = {
    0: "Patient List",
    1: "Session History",
    2: "Analytics",
    3: "Calibration Records",
    4: "Game Configuration",
    5: "Start Rehabilitation Session",
    6: "Register Patient",
}

PANEL_COLORS = {
    0: (100, 180, 240),
    1: (240, 170,  90),
    2: (190, 130, 220),
    3: (235, 100, 120),
    4: ( 80, 195, 195),
    5: ( 60, 140, 220),
    6: (130, 200, 140),
}

SIDEBAR_NAV = [
    {"label": "Patient List",         "symbol": "👤", "idx": 0},
    {"label": "Session History",      "symbol": "📋", "idx": 1},
    {"label": "Analytics",            "symbol": "📊", "idx": 2},
    {"label": "Calibration Records",  "symbol": "🎯", "idx": 3},
]

ROLES = [
    "Physical Therapist",
    "Occupational Therapist",
    "Rehabilitation Specialist",
    "Neurological Rehab Therapist",
    "Other",
]

STROKE_TYPES  = ["Ischemic", "Hemorrhagic", "Unknown / Not Specified"]
SEVERITY_OPTS = ["Mild", "Moderate"]
SEX_OPTS      = ["Male", "Female", "Prefer not to say"]
HAND_OPTS     = ["Left", "Right"]
GAME_DURATION = ["60 seconds", "120 seconds", "180 seconds", "Custom"]

SINGLE_SKILL_GAMES = [
    ("Catch the Falling Object", "Grip Strength"),
    ("Whack-a-Mole Twist",       "Finger Flexion"),
    ("Key & Lock",               "Wrist Rotation"),
]
INTEGRATED_GAMES = [
    ("Dual Skill",  "Dual Skill"),
    ("Multi-skill", "Multi-skill"),
]
ALL_GAMES = SINGLE_SKILL_GAMES + INTEGRATED_GAMES

SKILL_GAMES = {
    "Grip Strength":  ["Basketball"],
    "Finger Flexion": ["Piano Tiles"],
    "Wrist Rotation": ["Apple Catching", "Catch the Falling Object",
                       "Gravity Catch", "Key and Lock", "Steady Aim"],
}

DIFFICULTY_OPTS = ["Easy", "Moderate", "Hard", "Custom"]
SMART_PRESETS   = {
    "Mild":     {"duration": "60 seconds", "speed": "Normal", "sensitivity": "Medium", "difficulty": "Moderate"},
    "Moderate": {"duration": "60 seconds", "speed": "Normal", "sensitivity": "Medium", "difficulty": "Easy"},
}


# ─────────────────────────────────────────────────────────────────────
#  DRAW HELPERS
# ─────────────────────────────────────────────────────────────────────

def _card_bg(surface, rect, alpha=200, radius=14,
             border_col=(200, 218, 240), border_w=1):
    bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    bg.fill((232, 242, 255, alpha))
    surface.blit(bg, rect.topleft)
    hl = pygame.Surface((rect.width, 3), pygame.SRCALPHA)
    hl.fill((255, 255, 255, 190))
    surface.blit(hl, rect.topleft)
    pygame.draw.rect(surface, border_col, rect, border_w, border_radius=radius)


def _empty_state(surface, rect, icon_text, heading, subtext,
                 fnt_head, fnt_sub, action_label=None, fnt_btn=None):
    cx = rect.centerx
    cy = rect.centery - int(rect.height * 0.05)
    r  = int(min(rect.width, rect.height) * 0.09)
    pygame.draw.circle(surface, (228, 238, 252), (cx, cy - r // 2), r)
    ic = fnt_head.render(icon_text, True, (158, 183, 218))
    surface.blit(ic, ic.get_rect(center=(cx, cy - r // 2)))
    hs = fnt_head.render(heading, True, (108, 128, 158))
    surface.blit(hs, hs.get_rect(center=(cx, cy + int(r * 0.85))))
    ss = fnt_sub.render(subtext, True, (153, 170, 193))
    surface.blit(ss, ss.get_rect(center=(cx, cy + int(r * 0.85) + hs.get_height() + 6)))
    if action_label and fnt_btn:
        ar = pygame.Rect(0, 0, int(rect.width * 0.40), int(rect.height * 0.075))
        ar.center = (cx, cy + int(r * 0.85) + hs.get_height() + ss.get_height() + 26)
        pygame.draw.rect(surface, (198, 213, 233), ar, 1, border_radius=20)
        als = fnt_btn.render(action_label, True, (98, 133, 188))
        surface.blit(als, als.get_rect(center=ar.center))


def _btn(surface, rect, label, font, col_normal, col_hover, hovered, radius=10):
    pygame.draw.rect(surface, col_hover if hovered else col_normal, rect, border_radius=radius)
    s = font.render(label, True, (255, 255, 255))
    surface.blit(s, s.get_rect(center=rect.center))


# ─────────────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────────────

class TherapistDashboardScene:

    def __init__(self, screen, width, height, account=None):
        """
        Initialize the Therapist Dashboard Scene.

        Args:
            screen: pygame surface to draw on
            width: screen width in pixels
            height: screen height in pixels
            account: therapist account dict (optional, will load from DB if not provided)
        """
        # Store screen and display dimensions
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        # Initialize database connection for patient/therapist data
        self.db     = Database()

        # ── Account loading priority ──────────────────────────────────
        # Priority: 1) passed account param, 2) pending_account global, 3) last DB therapist, 4) default
        import builtins as _bi
        if account:
            self.account = account
        elif hasattr(_bi, 'pending_account') and _bi.pending_account:
            self.account = _bi.pending_account
            _bi.pending_account = None
        else:
            all_acc = self.db.get_all_therapists()
            self.account = all_acc[-1] if all_acc else {
                "id": 0, "full_name": "Therapist", "username": "user",
                "role": "Physical Therapist", "workplace": "RecovR Clinic",
                "icon_index": 1
            }

        # ── Font dictionary (all fonts scaled relative to screen height) ──
        H = height
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(name): return os.path.join(_fd, name)
        self.fnt = {
            "logo":        pygame.font.SysFont("arialblack",                 int(51*(H/1080))),
            "nav":         pygame.font.Font(_F("Lexend-Medium.ttf"),         int(27*(H/1080))),
            "nav_sym":     pygame.font.SysFont("segoeuisymbol",              int(35*(H/1080))),
            "welcome":     pygame.font.Font(_F("Sora-Light.ttf"),            int(33*(H/1080))),
            "dash_title":  pygame.font.Font(_F("GravitasOne-Regular.ttf"),   int(60*(H/1080))),
            "panel_title": pygame.font.Font(_F("FjallaOne-Regular.ttf"),     int(36*(H/1080))),
            "body":        pygame.font.Font(_F("Lexend-Regular.ttf"),        int(27*(H/1080))),
            "body_b":      pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(27*(H/1080))),
            "small":       pygame.font.Font(_F("Lexend-Light.ttf"),          int(25*(H/1080))),
            "small_i":     pygame.font.Font(_F("Sora-ExtraLight.ttf"),       int(25*(H/1080))),
            "label":       pygame.font.Font(_F("Lexend-Regular.ttf"),        int(25*(H/1080))),
            "input":       pygame.font.Font(_F("Lexend-Regular.ttf"),        int(25*(H/1080))),
            "btn":         pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(27*(H/1080))),
            "btn_lg":      pygame.font.Font(_F("Lexend-Bold.ttf"),           int(30*(H/1080))),
            "profile_nm":  pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(24*(H/1080))),
            "profile":     pygame.font.Font(_F("Lexend-Light.ttf"),          int(22*(H/1080))),
            "card_lbl":    pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(25*(H/1080))),
            "card_sym":    pygame.font.SysFont("segoeuisymbol",              int(51*(H/1080))),
            "modal_head":  pygame.font.Font(_F("FjallaOne-Regular.ttf"),     int(42*(H/1080))),
            "modal_lbl":   pygame.font.Font(_F("Lexend-Medium.ttf"),         int(27*(H/1080))),
            "modal_inp":   pygame.font.Font(_F("Lexend-Regular.ttf"),        int(27*(H/1080))),
            "modal_err":   pygame.font.Font(_F("Lexend-Light.ttf"),          int(23*(H/1080))),
            "empty_head":  pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(33*(H/1080))),
            "section":     pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(24*(H/1080))),
            "tag":         pygame.font.Font(_F("Lexend-Medium.ttf"),         int(22*(H/1080))),
            "time":        pygame.font.Font(_F("ZenDots-Regular.ttf"),       int(19*(H/1080))),
            "header_date": pygame.font.Font(_F("Lexend-Light.ttf"),          int(16*(H/1080))),
            "breadcrumb":  pygame.font.Font(_F("Lexend-Light.ttf"),          int(24*(H/1080))),
            "sym26":       pygame.font.SysFont("segoeuisymbol",              int(26*(H/1080))),
            "sym29":       pygame.font.SysFont("segoeuisymbol",              int(29*(H/1080))),
        }

        # Create gradient background surface for visual depth
        self.background_surface = self._gradient(width, height)
        # Sidebar width is 20% of screen width
        self.sidebar_w = int(width * 0.20)

        # ── Panel state tracking ──
        # active_panel: -1 = home, 0-6 = specific panels (see NAV_IDX mapping at top)
        self.active_panel = -1
        # nav_hovered: which sidebar nav item is currently hovered (-1 = none)
        self.nav_hovered  = -1
        # nav_rects: list of pygame.Rect objects for sidebar navigation buttons
        self.nav_rects    = []
        # card_hovered: list of 4 booleans tracking hover state of home cards
        self.card_hovered = [False] * 4

        # ── Header/profile area interaction ──
        self.edit_link_hovered = False         # Is "Edit Profile" link hovered?
        self.logout_hovered    = False         # Is logout button hovered?
        self._edit_link_rect   = pygame.Rect(0, 0, 1, 1)  # Clickable rect for edit link
        self._back_btn_rect    = pygame.Rect(0, 0, 1, 1)  # Clickable rect for back button

        # ── Modal state ──
        self.modal           = None            # Current modal: "edit_profile", "logout_confirm", "delete_confirm", "register_success", None
        self.confirm_yes_hov = False           # Is "Yes" button hovered in confirmation modal?
        self.confirm_no_hov  = False           # Is "No" button hovered in confirmation modal?
        self._rp_success_msg = ""              # Text shown in register success popup
        self._rp_ok_rect     = pygame.Rect(0, 0, 1, 1)
        self._rp_ok_hov      = False

        # ── Patient selection state ──
        self.selected_patient = None           # Currently selected patient dict
        self.patients         = []             # List of patients belonging to/shared with this therapist

        # ── Patient search state ──
        self._pt_search_text   = ""            # Current search text in patient list
        self._pt_search_active = False         # Whether search field has keyboard focus
        self._pt_search_rect   = pygame.Rect(0, 0, 1, 1)

        # Initialize state for Register Patient and Game Config panels
        self._init_register_state()
        self._init_game_config_state()

        # ── Calibration bypass for dev testing ────────────────────────
        # Allows therapists to bypass sensor calibration during development
        self.calibration_bypassed = False
        self._bypass_btn_rect     = pygame.Rect(0, 0, 1, 1)
        self._bypass_hov          = False

        # ── Real calibration state ─────────────────────────────────────
        self.calibration_done     = False       # True after CalibrationWindow accepted
        self.calibration_result   = None        # dict from CalibrationWindow
        self._cal_win             = None        # active CalibrationWindow instance (or None)
        self._calibrate_btn_rect  = pygame.Rect(0, 0, 1, 1)
        self._calibrate_hov       = False

        # ── Calibration mismatch modal ─────────────────────────────────
        self._mismatch_cal_rect    = pygame.Rect(0, 0, 1, 1)
        self._mismatch_cancel_rect = pygame.Rect(0, 0, 1, 1)
        self._mismatch_cal_hov     = False
        self._mismatch_cancel_hov  = False

        # ── Session Details dropdowns (panel 5) ────────────────────────
        self._ss_open_param        = None   # ("duration"|"speed", opts) or None
        self._ss_param_rects       = {}     # {"duration": Rect, "speed": Rect}
        self._ss_custom_dur_active = False
        self._ss_custom_dur_rect   = pygame.Rect(0, 0, 1, 1)

        # ── Interactive UI element rects ──
        # These store clickable areas for various buttons/interactive elements
        self._rp_btn_rect        = pygame.Rect(0, 0, 1, 1)  # Register patient submit button
        self._gc_next_rect       = pygame.Rect(0, 0, 1, 1)  # "Proceed to Start Session" button
        self._start_btn_rect     = pygame.Rect(0, 0, 1, 1)  # "Start Session" button
        self._register_link_rect = pygame.Rect(0, 0, 1, 1)  # Register patient link in patient list
        self._game_tiles         = []                        # List of (rect, game_tuple) for clickable game cards
        self._preset_btn_rect    = pygame.Rect(0, 0, 1, 1)  # Smart Preset button rect
        self._param_rects        = {}                        # Dict of parameter name -> rect for game config dropdowns

        # ── Hover state tracking for buttons ──
        self.rp_btn_hov        = False         # Is register patient button hovered?
        self.gc_next_hov       = False         # Is game config "next" button hovered?
        self.start_hov         = False         # Is start session button hovered?
        self.register_link_hov = False         # Is register patient link hovered?
        self.preset_hov        = False         # Is smart preset button hovered?

        # ── Edit patient modal state ──────────────────────────────────
        self._ep_modal_open   = False
        self._ep_patient      = None
        self._ep              = {}
        self._ep_active_key   = None
        self._ep_error        = ""
        self._ep_success      = ""
        self._ep_drop_open    = {}
        self._ep_drop_rects   = {}
        self._ep_confirm_del  = False
        self._ep_save_rect    = pygame.Rect(0, 0, 1, 1)
        self._ep_cancel_rect  = pygame.Rect(0, 0, 1, 1)
        self._ep_delete_rect  = pygame.Rect(0, 0, 1, 1)
        self._ep_save_hov     = False
        self._ep_cancel_hov   = False
        self._ep_delete_hov   = False

        # ── Share patient modal state ─────────────────────────────────
        # Allows therapists to share a patient with other therapists
        self.share_modal_patient  = None       # Patient dict being shared (None if modal closed)
        self._share_modal_open    = False      # Is share modal currently visible?
        self._share_input         = ""         # Username text being typed in search field
        self._share_error         = ""         # Error message to display
        self._share_success       = ""         # Success message to display
        self._share_results       = []         # List of therapist dicts matching search
        self._share_field_rect       = pygame.Rect(0, 0, 1, 1)
        self._share_search_rect      = pygame.Rect(0, 0, 1, 1)
        self._share_confirm_rect     = pygame.Rect(0, 0, 1, 1)
        self._share_close_rect       = pygame.Rect(0, 0, 1, 1)
        self._share_search_hov       = False
        self._share_confirm_hov      = False
        self._share_close_hov        = False
        self._share_suggestions      = []          # live-search results (list of therapist dicts)
        self._share_sugg_rects       = []          # list of (rect, therapist) for click handling
        self._share_confirm_therapist = None       # therapist chosen from suggestions, pending confirm
        self._share_confirm_mode     = False       # whether confirm prompt is visible
        self._share_yes_rect         = pygame.Rect(0, 0, 1, 1)
        self._share_no_rect          = pygame.Rect(0, 0, 1, 1)
        self._share_yes_hov          = False
        self._share_no_hov           = False
        self._unshare_rects          = []

        # ── Edit profile modal state ──
        self._init_edit_fields()

        # ── Build layout rectangles ──
        self._build_nav_rects()                # Calculate positions for sidebar nav items
        self._build_card_rects()               # Calculate positions for 4 home cards

        # ── Page transition animation ──
        self.alpha        = 0                  # Current alpha for fade-in effect (0-255)
        self.fade_surface = pygame.Surface((width, height))  # White surface for fade transition
        self.fade_surface.fill((255, 255, 255))
        self.action_triggered = False          # Flag to trigger next scene transition

        # Restore state from a returning game session if set
        _panel   = getattr(_bi, 'pending_panel',   None)
        _patient = getattr(_bi, 'pending_patient', None)
        if _panel is not None:
            _bi.pending_panel = None
            if _patient is not None:
                self.selected_patient = _patient
                _bi.pending_patient = None
            self._open_panel(_panel)
        else:
            self._open_panel(0)

    # ──────────────────────────────────────────────────────────────────
    #  STATE INITS
    # ──────────────────────────────────────────────────────────────────

    def _init_register_state(self):
        """
        Initialize state dict for Register Patient panel.
        Tracks patient information form data and UI state.
        """
        # Initialize all patient fields as empty strings
        self.rp = {k: "" for k in [
            "full_name",        # Patient's full name
            "age",              # Patient's age (numeric)
            "sex",              # Patient's biological sex (Male/Female/Prefer not to say)
            "dominant_hand",    # Dominant hand (Left/Right)
            "affected_hand",    # Hand affected by stroke (Left/Right)
            "stroke_type",      # Type of stroke (Ischemic/Hemorrhagic/Unknown)
            "date_of_stroke",   # Date stroke occurred
            "months_stroke",    # Months since stroke
            "severity",         # Severity of hemiplegia (Mild/Moderate)
            "notes_stiffness",  # Notes about stiffness
            "notes_pain",       # Notes about pain
            "notes_therapist",  # General therapist notes
        ]}
        # Add UI state flags to the dict
        self.rp.update({
            "active_key": None,     # Currently focused text input field name
            "error": "",            # Error message to display
            "success": "",          # Success message to display
            "sex_open": False,      # Is sex dropdown menu open?
            "dominant_open": False, # Is dominant hand dropdown open?
            "affected_open": False, # Is affected hand dropdown open?
            "stroke_open": False,   # Is stroke type dropdown open?
            "severity_open": False, # Is severity dropdown open?
        })
        # Dict to store the click-sensitive rectangles for all dropdown buttons
        self._rp_drop_rects = {}

    def _init_game_config_state(self):
        """
        Initialize state dict for Game Configuration panel.
        Tracks selected game and session parameters.
        """
        self.gc = {
            "selected_game": None,          # Tuple of (game_name, game_type) or None if not selected
            "duration": "60 seconds",       # Session duration (60/120/180 seconds or Custom)
            "difficulty": "Moderate",       # Difficulty level (Easy/Moderate/Hard/Custom)
            "speed": "Normal",              # Game speed (Slow/Normal/Fast)
            "sensitivity": "Medium",        # Input sensitivity (Low/Medium/High)
            "resistance": "Medium Ball",    # Ball resistance for games (Soft/Medium/Hard)
            "preset_applied": False,        # Has smart preset been applied?
        }
        # Track which parameter dropdown is currently open (None if all closed)
        # Format: (param_name, options_list) or None
        self._gc_open_param = None
        self._gc_custom_dur = ""            # Custom duration text when "Custom" is selected
        self._gc_custom_dur_active = False  # Whether the custom duration input has focus
        self._gc_custom_dur_rect = pygame.Rect(0, 0, 1, 1)
        self._gc_skill_modal_open = False   # Is game-picker modal open?
        self._gc_skill_modal_type = None    # Skill type whose games are being shown
        self._gc_skill_modal_rects = []     # List of (rect, game_name) for click handling
        self._gc_skill_modal_close = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  LAYOUT
    # ──────────────────────────────────────────────────────────────────

    def _build_nav_rects(self):
        """
        Calculate clickable rectangles for sidebar navigation items.
        Called once during __init__ to set up static nav button positions.
        """
        # Position nav items starting at 40% down the sidebar
        nav_top = int(self.HEIGHT * 0.40)
        # Each nav button height (scales with screen height)
        nav_h   = int(60 * (self.HEIGHT / 1080))
        # Vertical gap between nav buttons
        gap     = int(8  * (self.HEIGHT / 1080))
        # Build list of rectangles: one for each sidebar nav item
        # x=0 (left edge), y=nav_top + row*spacing, width=full sidebar width, height=nav_h
        self.nav_rects = [
            pygame.Rect(0, nav_top + i*(nav_h+gap), self.sidebar_w, nav_h)
            for i in range(len(SIDEBAR_NAV))
        ]

    def _build_card_rects(self):
        """
        Calculate positions for 4 home screen cards in 2x2 grid.
        Called once during __init__ to set up static card positions.
        """
        # Left margin (sidebar width + padding)
        mx     = self.sidebar_w + int(24*(self.WIDTH/1920))
        # Top margin (below logo/header area)
        my     = int(self.HEIGHT * 0.22)
        # Available width for cards (screen - margins)
        mw     = self.WIDTH - mx - int(24*(self.WIDTH/1920))
        # Available height for cards (screen - margins)
        mh     = self.HEIGHT - my - int(20*(self.HEIGHT/1080))
        # Horizontal gap between card columns
        gap    = int(20*(self.WIDTH/1920))
        # Calculate individual card width (half available width minus gap)
        card_w = (mw - gap) // 2
        # Calculate individual card height (half available height minus gap)
        card_h = (mh - gap) // 2
        # Build 2x2 grid of rectangles:
        # [0] Top-left    [1] Top-right
        # [2] Bottom-left [3] Bottom-right
        self.card_rects = [
            pygame.Rect(mx,            my,            card_w, card_h),  # Top-left
            pygame.Rect(mx+card_w+gap, my,            card_w, card_h),  # Top-right
            pygame.Rect(mx,            my+card_h+gap, card_w, card_h),  # Bottom-left
            pygame.Rect(mx+card_w+gap, my+card_h+gap, card_w, card_h),  # Bottom-right
        ]

    def _panel_area(self):
        """
        Get the main content area rectangle for panels (excluding sidebar and header).
        Returns a pygame.Rect defining the clickable/drawable panel area.
        """
        # Left edge: sidebar + padding
        mx = self.sidebar_w + int(24*(self.WIDTH/1920))
        # Top edge: below top navigation bar (15% down)
        my = int(self.HEIGHT * 0.15)
        # Width: full screen - sidebar - margins
        mw = self.WIDTH - mx - int(24*(self.WIDTH/1920))
        # Height: screen - top - bottom margins
        mh = self.HEIGHT - my - int(16*(self.HEIGHT/1080))
        return pygame.Rect(mx, my, mw, mh)

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE MODAL — Manages therapist profile editing interface
    # ──────────────────────────────────────────────────────────────────

    def _init_edit_fields(self):
        W, H    = self.WIDTH, self.HEIGHT
        modal_w = int(W * 0.52)
        modal_h = int(H * 0.82)
        modal_x = (W - modal_w) // 2
        modal_y = (H - modal_h) // 2

        fw  = int(modal_w * 0.52)
        fx  = modal_x + int(modal_w * 0.42)
        fh  = int(42*(H/1080))
        fsp = int(84*(H/1080))
        fy0 = modal_y + int(115*(H/1080))

        self.edit_modal_rect = pygame.Rect(modal_x, modal_y, modal_w, modal_h)
        self.edit_fields = [
            {"key":"full_name","label":"Full Name",
             "value":self.account.get("full_name",""),
             "is_pin":False,"max_len":50,"placeholder":"Full name",
             "rect":pygame.Rect(fx, fy0+0*fsp, fw, fh)},
            {"key":"username","label":"Username",
             "value":self.account.get("username",""),
             "is_pin":False,"max_len":15,"placeholder":"Letters only, max 15",
             "rect":pygame.Rect(fx, fy0+1*fsp, fw, fh)},
            {"key":"role","label":"Role",
             "value":self.account.get("role",""),
             "is_pin":False,"max_len":0,"placeholder":"Select role",
             "rect":pygame.Rect(fx, fy0+2*fsp, fw, fh)},
            {"key":"workplace","label":"Workplace",
             "value":self.account.get("workplace", self.account.get("clinic","")),
             "is_pin":False,"max_len":60,"placeholder":"Workplace name",
             "rect":pygame.Rect(fx, fy0+3*fsp, fw, fh)},
            {"key":"new_pin","label":"New PIN (optional)",
             "value":"","is_pin":True,"max_len":4,
             "placeholder":"Leave blank to keep current",
             "rect":pygame.Rect(fx, fy0+4*fsp, fw, fh)},
        ]

        icon_cx  = modal_x + int(modal_w*0.18)
        icon_cy0 = modal_y + int(215*(H/1080))
        sm_r     = int(22*(H/1080))
        self.edit_small_r       = sm_r
        self.edit_small_circles = []
        for i in range(10):
            col = i % 2; row = i // 2
            cx  = icon_cx + col*int(54*(W/1920)) - int(27*(W/1920))
            cy  = icon_cy0 + row*int(52*(H/1080))
            self.edit_small_circles.append((cx, cy, i+1))

        self.edit_big_r         = int(46*(H/1080))
        self.edit_big_center    = (icon_cx, modal_y + int(140*(H/1080)))
        self.edit_selected_icon = self.account.get("icon_index", 1)
        self.edit_active_field  = -1
        self.edit_error         = ""
        self.edit_role_open     = False

        role_rect = self.edit_fields[2]["rect"]
        opt_h     = int(38*(H/1080))
        self.edit_role_options = [
            {"label": r,
             "rect": pygame.Rect(role_rect.x, role_rect.bottom+i*opt_h, fw, opt_h)}
            for i, r in enumerate(ROLES)
        ]

        btn_y = modal_y + modal_h - int(58*(H/1080))
        bh2   = int(42*(H/1080)); bw2 = int(120*(W/1920)); dw2 = int(200*(W/1920))
        cx2   = modal_x + modal_w//2
        self.edit_save_rect   = pygame.Rect(cx2-bw2-int(8*W/1920), btn_y, bw2, bh2)
        self.edit_cancel_rect = pygame.Rect(cx2+int(8*W/1920),      btn_y, bw2, bh2)
        self.edit_delete_rect = pygame.Rect(modal_x+int(14*W/1920), btn_y, dw2, bh2)
        self.edit_save_hov = self.edit_cancel_hov = self.edit_delete_hov = False

    # ──────────────────────────────────────────────────────────────────
    #  EVENT HANDLING
    # ──────────────────────────────────────────────────────────────────

    def handle_event(self, event):
        """
        Main event dispatcher. Routes pygame events to appropriate handlers.
        Supports mouse clicks, touch/finger input, and keyboard input.
        """
        # If a scene transition is in progress, ignore all events
        if self.action_triggered:
            return None

        # ── Calibration window intercepts all events when active ──────
        if self._cal_win is not None:
            self._cal_win.handle_event(event)
            return None

        # ── Touch screen input (mobile/tablet) ──
        if event.type == pygame.FINGERDOWN:
            # FINGERDOWN uses normalized coordinates (0.0-1.0), convert to pixels
            pos = (int(event.x * self.WIDTH), int(event.y * self.HEIGHT))
            return self._handle_click(pos)

        # ── Mouse click input (desktop) ──
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:  # 1 = left mouse button
            import builtins
            # Apply position normalization function if it exists (for coordinate mapping)
            norm = getattr(builtins, 'normalise_pos', lambda p: p)
            pos  = norm(event.pos)
            return self._handle_click(pos)

        # ── Keyboard input ──
        if event.type == pygame.KEYDOWN:
            # Share modal captures all keys first (highest priority)
            if self._share_modal_open:
                return self._handle_share_key(event)
            # Edit patient modal
            if self._ep_modal_open:
                self._ep_keydown(event); return None
            # Edit profile modal handles text input
            if self.modal == "edit_profile":
                return self._handle_edit_key(event)
            # Patient search field
            if self.active_panel == 0 and self._pt_search_active:
                if event.key == pygame.K_ESCAPE:
                    self._pt_search_active = False
                elif event.key == pygame.K_BACKSPACE:
                    self._pt_search_text = self._pt_search_text[:-1]
                elif event.unicode and len(self._pt_search_text) < 40:
                    self._pt_search_text += event.unicode
                return None
            # Game config custom duration input
            if self.active_panel == 4 and self._gc_custom_dur_active:
                if event.key == pygame.K_BACKSPACE:
                    self._gc_custom_dur = self._gc_custom_dur[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self._gc_custom_dur_active = False
                elif event.unicode.isdigit() and len(self._gc_custom_dur) < 4:
                    self._gc_custom_dur += event.unicode
                return None
            # Session Details custom duration input (panel 5)
            if self.active_panel == 5 and self._ss_custom_dur_active:
                if event.key == pygame.K_BACKSPACE:
                    self._gc_custom_dur = self._gc_custom_dur[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self._ss_custom_dur_active = False
                elif event.unicode.isdigit() and len(self._gc_custom_dur) < 4:
                    self._gc_custom_dur += event.unicode
                return None
            # Register patient panel handles text input
            if self.active_panel == 6 and self.rp.get("active_key"):
                self._rp_keydown(event)
                return None
            # ESC key closes modals or goes back
            if event.key == pygame.K_ESCAPE:
                if self.active_panel == 4 and self._gc_skill_modal_open:
                    self._gc_skill_modal_open = False
                    return None
                if self.modal in ("edit_profile","logout_confirm","register_success"):
                    self.modal = None
                elif self.modal == "delete_confirm":
                    self.modal = "edit_profile"
                elif self.modal == "delete_patient_confirm":
                    self.modal = None
                elif self.active_panel != -1:
                    # Going back from a panel returns to previous screen
                    self._go_back()

        return None

    def _handle_click(self, pos):
        """
        Process mouse/touch clicks. Routes clicks to appropriate handlers
        based on which UI element was clicked. Checked in priority order:
        share modal > other modals > sidebar > panels
        """
        # ── Edit patient modal ────────────────────────────────────────
        if self._ep_modal_open:
            self._ep_handle_click(pos); return None

        # ── Share modal (checked before everything else - highest priority) ──
        if self._share_modal_open:
            if self._share_close_rect.collidepoint(pos):
                self._share_modal_open = False; return None

            # Confirmation prompt yes/no
            if self._share_confirm_mode:
                if self._share_yes_rect.collidepoint(pos):
                    self._do_share_confirm(); return None
                if self._share_no_rect.collidepoint(pos):
                    self._share_confirm_mode      = False
                    self._share_confirm_therapist = None
                    return None
                return None

            # Live suggestion item clicks → enter confirm mode
            for (sr, therapist) in self._share_sugg_rects:
                if sr.collidepoint(pos):
                    self._share_confirm_therapist = therapist
                    self._share_confirm_mode      = True
                    return None

            # Unshare/Revoke buttons
            for (ur, tid) in self._unshare_rects:
                if ur.collidepoint(pos):
                    self.db.unshare_patient(self.share_modal_patient["id"], tid)
                    self._share_success = "Access revoked."
                    self._share_error   = ""
                    return None

            return None  # absorb all other clicks

        # ── Calibration mismatch modal ────────────────────────────────
        if self.modal == "calibration_mismatch":
            if self._mismatch_cal_rect.collidepoint(pos):
                self.modal = None
                game_type  = (self.gc.get("selected_game") or (None, None))[1] or "Grip Strength"
                self._cal_win = CalibrationWindow(self.WIDTH, self.HEIGHT, game_type)
                return None
            if self._mismatch_cancel_rect.collidepoint(pos):
                self.modal = None
            return None

        # ── Other modals ──────────────────────────────────────────────
        if self.modal == "delete_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                self._ep_delete()
                self._ep_modal_open = False
                self.modal = None
            if nr.collidepoint(pos):
                self.modal = None
            return None

        if self.modal == "delete_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                self.db.delete_therapist(self.account["id"])
                self.action_triggered = True
                return "therapist_welcome"
            if nr.collidepoint(pos): self.modal = "edit_profile"
            return None

        if self.modal == "register_success":
            if self._rp_ok_rect.collidepoint(pos):
                self.modal = None
            return None

        if self.modal == "logout_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                self.action_triggered = True
                return "login"
            if nr.collidepoint(pos): self.modal = None
            return None

        if self.modal == "edit_profile":
            return self._handle_edit_click(pos)

        # ── Sidebar ──────────────────────────────────────────────────
        if self._edit_link_rect.collidepoint(pos):
            self._init_edit_fields(); self.modal = "edit_profile"; return None

        if self._logout_rect().collidepoint(pos):
            self.modal = "logout_confirm"; return None

        for i, r in enumerate(self.nav_rects):
            if r.collidepoint(pos):
                self._open_panel(SIDEBAR_NAV[i]["idx"]); return None

        # ── Back button ───────────────────────────────────────────────
        if self.active_panel != -1 and self._back_btn_rect.collidepoint(pos):
            self._go_back(); return None

        # ── Panel 0: Patient List ─────────────────────────────────────
        if self.active_panel == 0:
            if self._pt_search_rect.collidepoint(pos):
                self._pt_search_active = True; return None
            else:
                self._pt_search_active = False
            if self._register_link_rect.collidepoint(pos):
                self._open_panel(6); return None
            for row in self._patient_rows:
                btn_rect = row[0]
                patient  = row[1]
                action   = row[2] if len(row) > 2 else "select"
                if btn_rect.collidepoint(pos):
                    if action == "share":
                        self._open_share_modal(patient)
                    elif action == "edit":
                        self._open_ep_modal(patient)
                    elif action == "name":
                        self.selected_patient = patient
                        self._init_game_config_state()
                        self.calibration_done   = False
                        self.calibration_result = None
                        self._cal_win           = None
                        self._open_panel(4)
                    elif action == "select":
                        if (self.selected_patient is not None and
                                self.selected_patient.get("id") == patient.get("id")):
                            self.selected_patient = None
                        else:
                            self.selected_patient = patient
                    return None

        # ── Panel 6: Register Patient ─────────────────────────────────
        if self.active_panel == 6:
            self._rp_handle_click(pos)

        # ── Panel 4: Game Configuration ───────────────────────────────
        if self.active_panel == 4:
            self._gc_handle_click(pos)
            if self._gc_next_rect.collidepoint(pos):
                self._open_panel(5); return None

        # ── Panel 5: Start Session ────────────────────────────────────
        if self.active_panel == 5:
            # ── Session Details dropdown intercept (highest priority) ──
            if self._ss_open_param:
                open_key, open_opts = self._ss_open_param
                pr = self._ss_param_rects.get(open_key)
                if pr:
                    opt_h = int(36 * self.HEIGHT / 1080)
                    for j, opt_val in enumerate(open_opts):
                        or_ = pygame.Rect(pr.x, pr.bottom + j * opt_h, pr.width, opt_h)
                        if or_.collidepoint(pos):
                            self.gc[open_key] = opt_val
                            if opt_val == "Custom":
                                self._gc_custom_dur     = ""
                                self._ss_custom_dur_active = True
                            else:
                                self._ss_custom_dur_active = False
                            self._ss_open_param = None
                            return None
                self._ss_open_param = None
                return None   # consume click; dropdown closes

            if self._bypass_btn_rect.collidepoint(pos):
                self.calibration_bypassed = not self.calibration_bypassed
                return None
            if self._calibrate_btn_rect.collidepoint(pos):
                game_type = (self.gc.get("selected_game") or (None, None))[1] or "Grip Strength"
                self._cal_win = CalibrationWindow(self.WIDTH, self.HEIGHT, game_type)
                return None

            # ── Custom duration field ──────────────────────────────────
            if self.gc.get("duration") == "Custom":
                if self._ss_custom_dur_rect.collidepoint(pos):
                    self._ss_custom_dur_active = True
                    return None
                else:
                    self._ss_custom_dur_active = False

            # ── Duration / Speed dropdown toggle ──────────────────────
            DUR_OPTS = ["60 seconds", "120 seconds", "180 seconds", "Custom"]
            SPD_OPTS = ["Slow", "Normal", "Fast"]
            for pk, opts in [("duration", DUR_OPTS), ("speed", SPD_OPTS)]:
                pr = self._ss_param_rects.get(pk)
                if pr and pr.collidepoint(pos):
                    self._ss_open_param = (pk, opts)
                    return None

            if self._start_btn_rect.collidepoint(pos) and self._session_ready():
                if self._calibration_mismatched():
                    self.modal = "calibration_mismatch"
                    return None
                return self._launch_game()

        return None

    def _go_back(self):
        if self.active_panel == 6:   self.active_panel = 0
        elif self.active_panel == 4: self.active_panel = 0
        elif self.active_panel == 5: self.active_panel = 4

    def _open_panel(self, idx):
        self.active_panel      = idx
        self._ss_open_param    = None   # close any open session-detail dropdown
        self._ss_custom_dur_active = False
        if idx == 0:
            self._pt_search_active = False
            self._pt_search_text   = ""
            # Only load patients belonging to or shared with this therapist
            self.patients = (
                self.db.get_all_patients(therapist_id=self.account["id"])
                if hasattr(self.db, 'get_all_patients') else []
            )

    def _session_ready(self):
        return (self.selected_patient is not None and
                self.gc["selected_game"] is not None and
                (self.calibration_done or self.calibration_bypassed))

    def _calibration_mismatched(self):
        """True when calibration_done but the calibrated sensor type doesn't match
        the currently selected game's exercise type."""
        if not self.calibration_done or self.calibration_bypassed:
            return False
        cal_type  = (self.calibration_result or {}).get("game_type", "")
        game_type = (self.gc.get("selected_game") or (None, ""))[1] or ""
        return bool(cal_type) and cal_type != game_type

    # Maps the specific game name chosen in Game Config to a scene key in main.py
    _GAME_SCENE_MAP = {
        "Basketball": "basketball",
        "Steady Aim": "steady_aim",
    }

    def _launch_game(self):
        import builtins
        game_name = (self.gc.get("selected_game") or (None,))[0]
        scene_key = self._GAME_SCENE_MAP.get(game_name)
        if not scene_key:
            return None  # game not yet implemented
        dur_str = self.gc.get("duration", "60 seconds")
        if dur_str == "Custom":
            try:
                dur_sec = int(self._gc_custom_dur) if self._gc_custom_dur else 60
            except ValueError:
                dur_sec = 60
        else:
            try:
                dur_sec = int(dur_str.split()[0])
            except (ValueError, IndexError):
                dur_sec = 60
        _diff_remap = {"Moderate": "Medium"}  # dashboard uses "Moderate", games use "Medium"
        raw_diff = self.gc.get("difficulty", "Easy")
        game_diff = _diff_remap.get(raw_diff, raw_diff)
        builtins.pending_game_data = {
            "account_id":   self.account.get("id"),
            "account":      self.account,
            "patient":      self.selected_patient,
            "difficulty":   game_diff,
            "duration_sec": dur_sec,
            "calibration":  {},
        }
        self.action_triggered = True
        return scene_key

    # ──────────────────────────────────────────────────────────────────
    #  SHARE MODAL HELPERS
    # ──────────────────────────────────────────────────────────────────

    def _open_share_modal(self, patient):
        self.share_modal_patient      = patient
        self._share_modal_open        = True
        self._share_input             = ""
        self._share_error             = ""
        self._share_success           = ""
        self._share_results           = []
        self._unshare_rects           = []
        self._share_suggestions       = []
        self._share_sugg_rects        = []
        self._share_confirm_therapist = None
        self._share_confirm_mode      = False

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PATIENT MODAL — helpers
    # ──────────────────────────────────────────────────────────────────

    def _open_ep_modal(self, patient):
        self._ep_patient     = patient
        self._ep_modal_open  = True
        self._ep_confirm_del = False
        self._ep_error       = ""
        self._ep_success     = ""
        self._ep_active_key  = None
        self._ep_drop_open   = {k: False for k in
                                ["sex","dominant_hand","affected_hand","stroke_type","severity"]}
        self._ep_drop_rects  = {}
        self._ep = {k: str(patient.get(k, "") or "")
                    for k in ["full_name","age","sex","dominant_hand","affected_hand",
                               "stroke_type","date_of_stroke","months_stroke","severity",
                               "notes_stiffness","notes_pain","notes_therapist"]}

    def _ep_handle_click(self, pos):
        W, H = self.WIDTH, self.HEIGHT
        if self._ep_cancel_rect.collidepoint(pos):
            self._ep_modal_open = False; return
        if self._ep_save_rect.collidepoint(pos):
            self._ep_submit(); return
        if self._ep_delete_rect.collidepoint(pos):
            self.modal = "delete_patient_confirm"
            return

        # Dropdown option selection
        for key, is_open in list(self._ep_drop_open.items()):
            if is_open:
                info = self._ep_drop_rects.get(key)
                if info:
                    _, opt_rects, opts = info
                    for or_, opt_val in zip(opt_rects, opts):
                        if or_.collidepoint(pos):
                            self._ep[key] = opt_val
                            self._ep_drop_open[key] = False
                            return
                self._ep_drop_open[key] = False
                return

        # Dropdown toggle
        drop_fields = {
            "sex": SEX_OPTS, "dominant_hand": HAND_OPTS,
            "affected_hand": HAND_OPTS, "stroke_type": STROKE_TYPES, "severity": SEVERITY_OPTS,
        }
        for key, opts in drop_fields.items():
            info = self._ep_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                for k in self._ep_drop_open: self._ep_drop_open[k] = False
                self._ep_drop_open[key] = True
                return

        # Text field focus
        for key in ["full_name","age","date_of_stroke","months_stroke",
                     "notes_stiffness","notes_pain","notes_therapist"]:
            info = self._ep_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                self._ep_active_key = key; return
        self._ep_active_key = None

    def _ep_keydown(self, event):
        if event.key == pygame.K_ESCAPE:
            if self._ep_active_key:
                self._ep_active_key = None
            else:
                self._ep_modal_open = False
            return
        if event.key == pygame.K_RETURN:
            self._ep_active_key = None; return
        key = self._ep_active_key
        if not key: return
        if event.key == pygame.K_BACKSPACE:
            self._ep[key] = self._ep[key][:-1]; self._ep_error = ""
        elif event.unicode:
            if key == "age" and (not event.unicode.isdigit() or len(self._ep[key]) >= 3):
                return
            self._ep[key] += event.unicode; self._ep_error = ""

    def _ep_submit(self):
        ep = self._ep
        if not ep["full_name"].strip():
            self._ep_error = "Full Name is required."; return
        if ep["age"] and not ep["age"].isdigit():
            self._ep_error = "Age must be a number."; return
        self.db.update_patient(self._ep_patient["id"], ep)
        # Refresh patient name if selected
        if self.selected_patient and self.selected_patient["id"] == self._ep_patient["id"]:
            self.selected_patient["full_name"] = ep["full_name"].strip()
        self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                         if hasattr(self.db, "get_all_patients") else [])
        self._ep_success = "Patient updated successfully."
        self._ep_error   = ""

    def _ep_delete(self):
        pid = self._ep_patient["id"]
        self.db.delete_patient(pid)
        if self.selected_patient and self.selected_patient.get("id") == pid:
            self.selected_patient = None
        self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                         if hasattr(self.db, "get_all_patients") else [])
        self._ep_modal_open = False

    def _draw_edit_patient_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mw = int(W * 0.64); mh = int(H * 0.86)
        mx = (W - mw) // 2;  my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        # Glass background
        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((228, 238, 252, 252)); surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 210)); surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), mr, 1, border_radius=16)

        # Title
        pt = self._ep_patient or {}
        surface.blit(self.fnt["modal_head"].render("Edit Patient", True, (38, 52, 78)),
                     (mr.x + int(22*W/1920), mr.y + int(28*H/1080)))
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + int(16*W/1920), mr.y + int(75*H/1080)),
                         (mr.right - int(16*W/1920), mr.y + int(75*H/1080)), 1)

        # Field layout
        fw   = mw // 2 - int(mw * 0.08)
        fh   = int(42*(H/1080))
        loff = int(34*(H/1080))
        gap  = int(82*(H/1080))
        fy0  = my + int(130*(H/1080))
        lx   = mx + int(mw * 0.04)
        rx   = mx + mw // 2 + int(mw * 0.04)

        left_fields = [
            ("full_name",     "Full Name",                   "Enter Full Name",   False, []),
            ("age",           "Age",                         "Enter Age",         False, []),
            ("date_of_stroke","Date of Stroke",              "MM-DD-YY",          False, []),
            ("months_stroke", "Stroke Onset Date",           "MM-DD-YY",          False, []),
            ("sex",           "Sex",                         "",                  True,  SEX_OPTS),
            ("dominant_hand", "Dominant Hand",               "",                  True,  HAND_OPTS),
            ("affected_hand", "Affected Hand (Stroke Side)", "",                  True,  HAND_OPTS),
        ]
        right_fields = [
            ("stroke_type",    "Stroke Type",           "", True,  STROKE_TYPES),
            ("severity",       "Severity",              "", True,  SEVERITY_OPTS),
            ("notes_stiffness","Muscle Stiffness Notes","Optional", False, []),
            ("notes_pain",     "Pain Level Notes",      "Optional", False, []),
            ("notes_therapist","Therapist Comments",    "Optional", False, []),
        ]

        def _draw_ep_field(key, lbl, placeholder, is_drop, opts, col_x, row_i):
            fy = fy0 + row_i * gap
            fr = pygame.Rect(col_x, fy, fw, fh)
            self._ep_drop_rects[key] = (fr, [], opts)

            active = (self._ep_active_key == key)
            surface.blit(self.fnt["label"].render(lbl, True, (70, 88, 112)),
                         (fr.x, fr.y - loff))

            glass_f = pygame.Surface((fw, fh), pygame.SRCALPHA)
            glass_f.fill((240, 248, 255, 200)); surface.blit(glass_f, fr.topleft)
            bc = (40, 160, 220) if active else (180, 205, 232)
            pygame.draw.rect(surface, bc, fr, 2 if active else 1, border_radius=8)

            val = self._ep.get(key, "")
            if is_drop:
                disp = val or "Select"
                tc   = (40, 50, 65) if val else (170, 185, 205)
                ts   = self.fnt["input"].render(disp, True, tc)
                surface.blit(ts, ts.get_rect(midleft=(fr.x + int(10*W/1920), fr.centery)))
                chev = self.fnt["sym26"].render("▼", True, (90, 110, 140))
                surface.blit(chev, chev.get_rect(midright=(fr.right - int(10*W/1920), fr.centery)))
            else:
                ts = (self.fnt["input"].render(val, True, (40, 50, 65)) if val
                      else self.fnt["input"].render(placeholder, True, (185, 198, 215)))
                surface.blit(ts, ts.get_rect(midleft=(fr.x + int(10*W/1920), fr.centery)))
                if active and val:
                    cx2 = fr.x + int(10*W/1920) + ts.get_width() + 2
                    pygame.draw.line(surface, (40, 160, 220),
                                     (cx2, fr.centery - int(9*H/1080)),
                                     (cx2, fr.centery + int(9*H/1080)), 2)

        # Pass 1: draw all field boxes + labels
        for i, (key, lbl, ph, isd, opts) in enumerate(left_fields):
            _draw_ep_field(key, lbl, ph, isd, opts, lx, i)
        for i, (key, lbl, ph, isd, opts) in enumerate(right_fields):
            _draw_ep_field(key, lbl, ph, isd, opts, rx, i)

        # Pass 2: open dropdowns on top
        drop_opts = {
            "sex": SEX_OPTS, "dominant_hand": HAND_OPTS, "affected_hand": HAND_OPTS,
            "stroke_type": STROKE_TYPES, "severity": SEVERITY_OPTS,
        }
        for key, opts in drop_opts.items():
            if self._ep_drop_open.get(key):
                fr = self._ep_drop_rects[key][0]
                opt_h  = int(38*H/1080)
                dp_bg  = pygame.Rect(fr.x, fr.bottom - 1, fw, len(opts)*opt_h + 4)
                glass_dp = pygame.Surface((dp_bg.width, dp_bg.height), pygame.SRCALPHA)
                glass_dp.fill((230, 242, 255, 230)); surface.blit(glass_dp, dp_bg.topleft)
                pygame.draw.rect(surface, (40, 160, 220), dp_bg, 2, border_radius=8)
                opt_rects = []
                for j, ov in enumerate(opts):
                    or_ = pygame.Rect(fr.x, fr.bottom + j*opt_h, fw, opt_h)
                    mp  = pygame.mouse.get_pos()
                    if or_.collidepoint(mp):
                        hl2 = pygame.Surface((fw, opt_h), pygame.SRCALPHA)
                        hl2.fill((190, 225, 255, 180)); surface.blit(hl2, or_.topleft)
                    ts2 = self.fnt["input"].render(ov, True, (40, 50, 65))
                    surface.blit(ts2, ts2.get_rect(midleft=(or_.x + int(10*W/1920), or_.centery)))
                    opt_rects.append(or_)
                self._ep_drop_rects[key] = (fr, opt_rects, opts)

        # Messages
        msg_y = mr.bottom - int(82*H/1080)
        if self._ep_error:
            surface.blit(self.fnt["modal_err"].render(self._ep_error, True, (210, 50, 50)),
                         (mr.centerx - int(160*W/1920), msg_y))
        if self._ep_success:
            surface.blit(self.fnt["modal_err"].render(self._ep_success, True, (50, 175, 75)),
                         (mr.centerx - int(160*W/1920), msg_y))

        # Buttons
        btn_y = mr.bottom - int(56*H/1080)
        bh    = int(42*(H/1080)); bw = int(120*(W/1920))
        cx2   = mr.centerx

        self._ep_save_rect   = pygame.Rect(cx2 - bw - int(8*W/1920), btn_y, bw, bh)
        self._ep_cancel_rect = pygame.Rect(cx2 + int(8*W/1920),       btn_y, bw, bh)
        dw = int(160*(W/1920))
        self._ep_delete_rect = pygame.Rect(mr.x + int(16*W/1920),     btn_y, dw, bh)

        del_col = (200, 50, 50)
        del_hov = (165, 28, 28)
        del_lbl = "Delete Patient"

        for rect, cn, ch, hov, lbl, fnt in [
            (self._ep_save_rect,   (40,160,220),(25,125,180), self._ep_save_hov,   "Save",   self.fnt["btn"]),
            (self._ep_cancel_rect, (160,175,195),(130,145,165),self._ep_cancel_hov,"Cancel", self.fnt["btn"]),
            (self._ep_delete_rect, del_col, del_hov,           self._ep_delete_hov, del_lbl, self.fnt["profile"]),
        ]:
            glass_btn = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(glass_btn, (*( ch if hov else cn), 230),
                             (0, 0, rect.width, rect.height), border_radius=10)
            surface.blit(glass_btn, rect.topleft)
            hl_btn = pygame.Surface((rect.width, 2), pygame.SRCALPHA)
            hl_btn.fill((255, 255, 255, 120)); surface.blit(hl_btn, rect.topleft)
            pygame.draw.rect(surface, ch if hov else cn, rect, 1, border_radius=10)
            s = fnt.render(lbl, True, (255, 255, 255))
            surface.blit(s, s.get_rect(center=rect.center))

    def _handle_share_key(self, event):
        if event.key == pygame.K_ESCAPE:
            if self._share_confirm_mode:
                self._share_confirm_mode      = False
                self._share_confirm_therapist = None
            else:
                self._share_modal_open = False
            return None
        if self._share_confirm_mode:
            return None  # swallow all other keys during confirm
        if event.key == pygame.K_BACKSPACE:
            self._share_input   = self._share_input[:-1]
            self._share_error   = ""
            self._share_success = ""
            self._live_share_search()
        elif event.unicode and len(self._share_input) < 20:
            if event.unicode.isalpha() or event.unicode.isdigit() or event.unicode == "_":
                self._share_input  += event.unicode
                self._share_error  = ""
                self._share_success = ""
                self._live_share_search()
        return None

    def _live_share_search(self):
        prefix = self._share_input.strip()
        if not prefix:
            self._share_suggestions = []; return
        results = self.db.search_therapists_by_prefix(prefix, self.account["id"])
        if self.share_modal_patient:
            already = {t["id"] for t in
                       self.db.get_shared_therapists(self.share_modal_patient["id"])}
            results = [t for t in results if t["id"] not in already]
        self._share_suggestions = results[:3]

    def _do_share_search(self):
        self._share_error   = ""
        self._share_success = ""
        self._share_results = []
        uname = self._share_input.strip()
        if not uname:
            self._share_error = "Enter a username to search."; return
        if uname == self.account["username"]:
            self._share_error = "That's your own account."; return
        t = self.db.get_therapist_by_username(uname)
        if not t:
            self._share_error = f"No therapist found: '{uname}'."; return
        if self.share_modal_patient:
            already = self.db.get_shared_therapists(self.share_modal_patient["id"])
            if any(a["id"] == t["id"] for a in already):
                self._share_error = f"Already shared with {t['full_name']}."; return
        self._share_results = [t]

    def _do_share_confirm(self):
        target = self._share_confirm_therapist
        if not target or not self.share_modal_patient:
            self._share_error = "No therapist selected."; return
        ok = self.db.share_patient(
            self.share_modal_patient["id"],
            target["id"],
            self.account["id"]
        )
        if ok:
            self._share_success           = f"Shared with {target['full_name']}."
            self._share_confirm_mode      = False
            self._share_confirm_therapist = None
            self._share_suggestions       = []
            self._share_input             = ""
            self._share_error             = ""
        else:
            self._share_error        = "Share failed. Try again."
            self._share_confirm_mode = False

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE EVENTS
    # ──────────────────────────────────────────────────────────────────

    def _handle_edit_click(self, pos):
        if self.edit_role_open:
            for opt in self.edit_role_options:
                if opt["rect"].collidepoint(pos):
                    self.edit_fields[2]["value"] = opt["label"]
                    self.edit_role_open = False; return None
            self.edit_role_open = False; return None

        for (cx, cy, idx) in self.edit_small_circles:
            if math.hypot(pos[0]-cx, pos[1]-cy) <= self.edit_small_r+8:
                self.edit_selected_icon = idx; return None

        clicked = False
        for i, field in enumerate(self.edit_fields):
            if field["rect"].inflate(8,8).collidepoint(pos):
                if field["key"] == "role":
                    self.edit_role_open    = not self.edit_role_open
                    self.edit_active_field = -1
                else:
                    self.edit_active_field = i
                    self.edit_role_open    = False
                clicked = True; break
        if not clicked:
            self.edit_active_field = -1; self.edit_role_open = False

        if self.edit_save_rect.collidepoint(pos):   return self._attempt_save()
        if self.edit_cancel_rect.collidepoint(pos): self.modal = None
        if self.edit_delete_rect.collidepoint(pos): self.modal = "delete_confirm"
        return None

    def _handle_edit_key(self, event):
        if event.key == pygame.K_ESCAPE: self.modal = None; return None
        if self.edit_active_field < 0:   return None
        f = self.edit_fields[self.edit_active_field]
        if event.key == pygame.K_BACKSPACE:
            f["value"] = f["value"][:-1]; self.edit_error = ""
        elif event.key == pygame.K_TAB:
            nxt = (self.edit_active_field+1) % len(self.edit_fields)
            self.edit_active_field = 3 if nxt==2 else nxt
        elif event.key == pygame.K_RETURN:
            return self._attempt_save()
        elif event.unicode:
            self._edit_type(f, event.unicode); self.edit_error = ""
        return None

    def _edit_type(self, field, char):
        if field["is_pin"]:
            if char.isdigit() and len(field["value"]) < 4: field["value"] += char
        elif field["key"] == "username":
            if char.isalpha() and len(field["value"]) < 15: field["value"] += char
        else:
            if field["max_len"] <= 0 or len(field["value"]) < field["max_len"]:
                field["value"] += char

    def _attempt_save(self):
        fn=self.edit_fields[0]["value"].strip(); un=self.edit_fields[1]["value"].strip()
        role=self.edit_fields[2]["value"].strip(); wp=self.edit_fields[3]["value"].strip()
        pin=self.edit_fields[4]["value"].strip(); idx=self.edit_selected_icon
        if not fn:   self.edit_error="Full Name required.";      return None
        if not un:   self.edit_error="Username required.";       return None
        if not un.isalpha(): self.edit_error="Username: letters only."; return None
        if not role: self.edit_error="Please select a role.";    return None
        if not wp:   self.edit_error="Workplace required.";      return None
        if pin and (len(pin)!=4 or not pin.isdigit()):
            self.edit_error="New PIN must be 4 digits."; return None
        if idx==0:   self.edit_error="Please choose an icon.";   return None
        if un!=self.account["username"] and self.db.username_exists(un):
            self.edit_error="Username already taken."; return None
        ok=self.db.update_therapist(self.account["id"],fn,un,role,wp,idx,
                                    new_pin=pin if pin else None)
        if ok:
            self.account=self.db.get_therapist_by_id(self.account["id"]); self.modal=None
        else:
            self.edit_error="Save failed."
        return None

    # ──────────────────────────────────────────────────────────────────
    #  REGISTER PATIENT EVENTS
    # ──────────────────────────────────────────────────────────────────

    def _rp_handle_click(self, pos):
        rp = self.rp

        if self._rp_btn_rect.collidepoint(pos):
            self._rp_submit(); return

        for key in ["sex_open","dominant_open","affected_open","stroke_open","severity_open"]:
            if rp[key]:
                field_key = key.replace("_open","")
                if field_key == "dominant": field_key = "dominant_hand"
                if field_key == "affected": field_key = "affected_hand"
                if field_key == "stroke":   field_key = "stroke_type"
                info = self._rp_drop_rects.get(field_key)
                if info:
                    _, opt_rects, opts = info
                    for j, (or_, opt_val) in enumerate(zip(opt_rects, opts)):
                        if or_.collidepoint(pos):
                            rp[field_key] = opt_val
                            rp[key] = False
                            return
                rp[key] = False
                return

        drop_map = [
            ("sex",           "sex_open",      SEX_OPTS),
            ("dominant_hand", "dominant_open", HAND_OPTS),
            ("affected_hand", "affected_open", HAND_OPTS),
            ("stroke_type",   "stroke_open",   STROKE_TYPES),
            ("severity",      "severity_open", SEVERITY_OPTS),
        ]
        for (field_key, open_key, opts) in drop_map:
            info = self._rp_drop_rects.get(field_key)
            if info:
                field_rect = info[0]
                if field_rect.collidepoint(pos):
                    for _, ok2, _ in drop_map:
                        rp[ok2] = False
                    rp[open_key] = not rp[open_key]
                    return

        text_keys = ["full_name","age","date_of_stroke","months_stroke",
                     "notes_stiffness","notes_pain","notes_therapist"]
        for key in text_keys:
            info = self._rp_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                rp["active_key"] = key
                return
        rp["active_key"] = None

    def _rp_submit(self):
        rp = self.rp
        if not rp["full_name"].strip():   rp["error"]="Full Name required.";       return
        if not rp["age"].strip() or not rp["age"].isdigit():
                                           rp["error"]="Valid age required.";        return
        if not rp["sex"]:                 rp["error"]="Sex required.";              return
        if not rp["dominant_hand"]:       rp["error"]="Dominant Hand required.";    return
        if not rp["affected_hand"]:       rp["error"]="Affected Hand required.";    return
        if not rp["severity"]:            rp["error"]="Severity required.";         return
        name = rp["full_name"].strip()
        pid  = self.db.create_patient(rp, self.account["id"]) if hasattr(self.db, 'create_patient') else None
        self.patients = (
            self.db.get_all_patients(therapist_id=self.account["id"])
            if hasattr(self.db, 'get_all_patients') else []
        )
        self._init_register_state()
        self._rp_success_msg = f"Patient '{name}' registered successfully." + (f"\nID: {pid}" if pid else "")
        self.modal = "register_success"

    def _rp_keydown(self, event):
        rp  = self.rp
        key = rp["active_key"]
        if not key: return
        if event.key == pygame.K_BACKSPACE:
            rp[key] = rp[key][:-1]; rp["error"] = ""
        elif event.key == pygame.K_RETURN:
            rp["active_key"] = None
        elif event.key == pygame.K_ESCAPE:
            rp["active_key"] = None
        elif event.unicode:
            if key == "age" and (not event.unicode.isdigit() or len(rp[key]) >= 3):
                return
            rp[key] += event.unicode; rp["error"] = ""

    # ──────────────────────────────────────────────────────────────────
    #  GAME CONFIG EVENTS
    # ──────────────────────────────────────────────────────────────────

    def _gc_handle_click(self, pos):
        gc = self.gc

        # ── Skill game picker modal ───────────────────────────────────
        if self._gc_skill_modal_open:
            if self._gc_skill_modal_close.collidepoint(pos):
                self._gc_skill_modal_open = False
                return
            for (gr, game_name) in self._gc_skill_modal_rects:
                if gr.collidepoint(pos):
                    gc["selected_game"] = (game_name, self._gc_skill_modal_type)
                    gc["preset_applied"] = False
                    self._gc_skill_modal_open = False
                    return
            self._gc_skill_modal_open = False
            return

        for (tr, game_tuple) in self._game_tiles:
            if tr.collidepoint(pos):
                skill_type = game_tuple[1]
                if skill_type in SKILL_GAMES:
                    self._gc_skill_modal_type = skill_type
                    self._gc_skill_modal_open = True
                    self._gc_skill_modal_rects = []
                else:
                    gc["selected_game"] = game_tuple
                return

    # ──────────────────────────────────────────────────────────────────
    #  UPDATE
    # ──────────────────────────────────────────────────────────────────

    def update(self, mouse_pos, dt):
        """
        Update hover states for all interactive UI elements.
        Called once per frame to check which buttons/elements are under the mouse.
        Also handles fade-in animation on scene load.

        Args:
            mouse_pos: (x, y) tuple of current mouse position in pixels
            dt: delta time since last frame (in seconds)
        """
        # ── Sidebar navigation hover ──
        # Reset to -1, then check each nav item for collision with mouse
        self.nav_hovered = -1
        for i, r in enumerate(self.nav_rects):
            if r.collidepoint(mouse_pos):
                self.nav_hovered = i  # Store which nav item is hovered
                break

        # ── Header/profile area hover ──
        self.edit_link_hovered = self._edit_link_rect.collidepoint(mouse_pos)
        self.logout_hovered    = self._logout_rect().collidepoint(mouse_pos)

        # ── Panel interactive elements hover ──
        self.rp_btn_hov        = self._rp_btn_rect.collidepoint(mouse_pos)         # Register Patient submit
        self.gc_next_hov       = self._gc_next_rect.collidepoint(mouse_pos)        # Game Config "next" button
        self.start_hov         = self._start_btn_rect.collidepoint(mouse_pos)      # Start Session button
        self.register_link_hov = self._register_link_rect.collidepoint(mouse_pos)  # Patient list "register" link
        self.preset_hov        = self._preset_btn_rect.collidepoint(mouse_pos)     # Smart Preset button
        self._bypass_hov      = self._bypass_btn_rect.collidepoint(mouse_pos)      # Calibration bypass toggle
        self._calibrate_hov   = self._calibrate_btn_rect.collidepoint(mouse_pos)  # Real Calibrate button

        # ── Calibration window update (delegates sensor + phase logic) ──
        if self._cal_win is not None:
            self._cal_win.update(dt)
            if self._cal_win.done:
                self.calibration_done   = True
                self.calibration_result = self._cal_win.calibration_result
                self._cal_win           = None
            elif self._cal_win.cancelled:
                self._cal_win = None

        # ── Share modal hover states ──
        self._share_search_hov  = self._share_search_rect.collidepoint(mouse_pos)
        self._share_confirm_hov = self._share_confirm_rect.collidepoint(mouse_pos)
        self._share_close_hov   = self._share_close_rect.collidepoint(mouse_pos)
        self._share_yes_hov     = self._share_yes_rect.collidepoint(mouse_pos)
        self._share_no_hov      = self._share_no_rect.collidepoint(mouse_pos)

        # ── Edit patient modal hover ──
        if self._ep_modal_open:
            self._ep_save_hov   = self._ep_save_rect.collidepoint(mouse_pos)
            self._ep_cancel_hov = self._ep_cancel_rect.collidepoint(mouse_pos)
            self._ep_delete_hov = self._ep_delete_rect.collidepoint(mouse_pos)

        # ── Edit profile modal hover ──
        if self.modal == "edit_profile":
            self.edit_save_hov   = self.edit_save_rect.collidepoint(mouse_pos)
            self.edit_cancel_hov = self.edit_cancel_rect.collidepoint(mouse_pos)
            self.edit_delete_hov = self.edit_delete_rect.collidepoint(mouse_pos)

        # ── Register success popup hover ──
        if self.modal == "register_success":
            self._rp_ok_hov = self._rp_ok_rect.collidepoint(mouse_pos)

        # ── Confirmation modal hover ──
        if self.modal in ("logout_confirm","delete_confirm","delete_patient_confirm"):
            yr, nr = self._confirm_rects()
            self.confirm_yes_hov = yr.collidepoint(mouse_pos)
            self.confirm_no_hov  = nr.collidepoint(mouse_pos)

        # ── Calibration mismatch modal hover ──
        if self.modal == "calibration_mismatch":
            self._mismatch_cal_hov    = self._mismatch_cal_rect.collidepoint(mouse_pos)
            self._mismatch_cancel_hov = self._mismatch_cancel_rect.collidepoint(mouse_pos)

        # ── Page transition fade-in animation ──
        # Fade in over several frames (alpha goes from 0→255, +4 per frame = ~64 frames at 60FPS = 1 second)
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    # ──────────────────────────────────────────────────────────────────
    #  DRAW — TOP LEVEL — Main rendering function called each frame
    # ──────────────────────────────────────────────────────────────────

    def draw(self, surface):
        """
        Main draw function. Renders entire UI each frame in the following order:
        1. Background gradient
        2. Sidebar (navigation, profile)
        3. Home screen (if active_panel == -1) OR Panel content + shell
        4. Modals (if any)
        5. Fade transition animation

        Args:
            surface: pygame.Surface to draw on (usually the main screen)
        """
        # ── Background layer ──
        # Draw pre-rendered gradient background for visual depth
        surface.blit(self.background_surface, (0, 0))

        # ── Sidebar (always visible) ──
        # Contains profile info, edit link, logout, and navigation menu
        self._draw_sidebar(surface)

        # ── Main content area ──
        # Dispatch to the active panel (Patient List shown by default on load)
        panel_drawers = {
            0: self._draw_patient_list,
            1: self._draw_session_history,
            2: self._draw_analytics,
            3: self._draw_calibration,
            4: self._draw_game_config,
            5: self._draw_start_session,
            6: self._draw_register_patient,
        }
        if self.active_panel in panel_drawers:
            self._draw_panel_shell(surface, self.active_panel)
            panel_drawers[self.active_panel](surface, self._panel_area())

        if self.modal == "edit_profile":
            self._draw_overlay(surface); self._draw_edit_modal(surface)
        elif self.modal in ("logout_confirm","delete_confirm"):
            self._draw_overlay(surface); self._draw_confirm_modal(surface)
        elif self.modal == "register_success":
            self._draw_overlay(surface); self._draw_register_success_modal(surface)
        elif self.modal == "calibration_mismatch":
            self._draw_overlay(surface); self._draw_calibration_mismatch_modal(surface)

        # Edit patient modal
        if self._ep_modal_open:
            self._draw_overlay(surface)
            self._draw_edit_patient_modal(surface)
            if self.modal == "delete_patient_confirm":
                self._draw_overlay(surface)
                self._draw_confirm_modal(surface)

        # Skill game picker modal (game config panel)
        if self.active_panel == 4 and self._gc_skill_modal_open:
            self._draw_overlay(surface)
            self._draw_skill_game_modal(surface)

        # Share modal drawn on top of everything
        if self._share_modal_open:
            self._draw_overlay(surface)
            self._draw_share_modal(surface)

        # Calibration window (full-screen, drawn last so it covers everything)
        if self._cal_win is not None:
            self._cal_win.draw(surface)

        if self.alpha < 255:
            self.fade_surface.set_alpha(255-self.alpha)
            surface.blit(self.fade_surface, (0,0))

    # ──────────────────────────────────────────────────────────────────
    #  SIDEBAR
    # ──────────────────────────────────────────────────────────────────

    def _draw_sidebar(self, surface):
        W, H, sw = self.WIDTH, self.HEIGHT, self.sidebar_w
        sb = pygame.Surface((sw, H), pygame.SRCALPHA)
        sb.fill((212, 230, 255, 158)); surface.blit(sb, (0,0))
        hl = pygame.Surface((sw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200)); surface.blit(hl, (0, 0))
        pygame.draw.line(surface, (185, 210, 240), (sw,0), (sw,H), 1)

        ly = int(H*0.05)
        s1 = self.fnt["logo"].render("Recov", True, (45,60,80))
        s2 = self.fnt["logo"].render("R",     True, (215,40,40))
        lx = int(sw*0.10)
        surface.blit(s1, s1.get_rect(midleft=(lx, ly)))
        surface.blit(s2, s2.get_rect(midleft=(lx+s1.get_width(), ly)))

        now = datetime.datetime.now()
        ts  = self.fnt["time"].render(now.strftime("%I:%M %p"), True, (60,80,110))
        ds  = self.fnt["header_date"].render(now.strftime("%b %d, %Y"), True, (110,128,150))
        surface.blit(ts, ts.get_rect(midright=(sw-int(10*W/1920), ly-int(6*H/1080))))
        surface.blit(ds, ds.get_rect(midright=(sw-int(10*W/1920), ly+int(14*H/1080))))

        pc_y = int(H*0.11); pc_h = int(H*0.18)
        pc_r = pygame.Rect(int(sw*0.05), pc_y, int(sw*0.90), pc_h)
        glass_pc = pygame.Surface((pc_r.width, pc_r.height), pygame.SRCALPHA)
        glass_pc.fill((195, 220, 255, 130)); surface.blit(glass_pc, pc_r.topleft)
        hl_pc = pygame.Surface((pc_r.width, 3), pygame.SRCALPHA)
        hl_pc.fill((255, 255, 255, 210)); surface.blit(hl_pc, pc_r.topleft)
        pygame.draw.rect(surface, (175, 208, 240), pc_r, 1, border_radius=12)
        ir = int(34*(H/1080)); ix = pc_r.x+int(sw*0.10); iy = pc_r.centery
        draw_icon(surface, self.account.get("icon_index",1), ix, iy, ir, shadow=False)
        tx = ix+ir+int(16*(W/1920))
        surface.blit(self.fnt["profile_nm"].render(self.account["full_name"],True,(40,55,75)),
                     (tx, iy-int(40*(H/1080))))
        surface.blit(self.fnt["profile"].render(self.account["role"],True,(100,115,140)),
                     (tx, iy-int(10*(H/1080))))
        ec  = (50,120,200) if self.edit_link_hovered else (75,140,210)
        es  = self.fnt["profile"].render("Edit Profile", True, ec)
        ep  = (tx, iy+int(22*(H/1080)))
        surface.blit(es, ep)
        self._edit_link_rect = pygame.Rect(ep[0], ep[1], es.get_width(), es.get_height())

        for i, item in enumerate(SIDEBAR_NAV):
            r       = self.nav_rects[i]
            col     = PANEL_COLORS[item["idx"]]
            hovered = (self.nav_hovered == i)
            active  = (self.active_panel == item["idx"])
            if active:
                bg = pygame.Surface((sw, r.height), pygame.SRCALPHA)
                bg.fill((*col, 55)); surface.blit(bg, r.topleft)
                hl_nav = pygame.Surface((sw, 2), pygame.SRCALPHA)
                hl_nav.fill((255, 255, 255, 160)); surface.blit(hl_nav, r.topleft)
                pygame.draw.rect(surface, col, pygame.Rect(0,r.y,int(4*W/1920),r.height))
            elif hovered:
                bg = pygame.Surface((sw, r.height), pygame.SRCALPHA)
                bg.fill((255, 255, 255, 40)); surface.blit(bg, r.topleft)
                hl_nav = pygame.Surface((sw, 2), pygame.SRCALPHA)
                hl_nav.fill((255, 255, 255, 100)); surface.blit(hl_nav, r.topleft)
            px  = int(sw*0.10)
            sym = self.fnt["nav_sym"].render(item["symbol"],True,col if active else (120,140,165))
            lbl = self.fnt["nav"].render(item["label"],True,col if active else (60,78,100))
            surface.blit(sym, sym.get_rect(midleft=(px, r.centery)))
            surface.blit(lbl, lbl.get_rect(midleft=(px + sym.get_width() + int(10*W/1920), r.centery)))

        if self.selected_patient:
            badge_y = self.nav_rects[-1].bottom + int(18*H/1080)
            badge_r = pygame.Rect(int(sw*0.05), badge_y, int(sw*0.90), int(74*H/1080))
            pygame.draw.rect(surface, (232,245,255), badge_r, border_radius=10)
            pygame.draw.rect(surface, (140,195,240), badge_r, 1, border_radius=10)
            surface.blit(self.fnt["small"].render("Active Patient:", True, (90,120,160)),
                         (badge_r.x+int(10*W/1920), badge_r.y+int(8*H/1080)))
            pname = self.selected_patient.get("full_name","—")
            surface.blit(self.fnt["label"].render(pname, True, (40,80,140)),
                         (badge_r.x+int(10*W/1920), badge_r.y+int(40*H/1080)))

        lr = self._logout_rect()
        lc = (165,25,25) if self.logout_hovered else (205,45,45)
        pygame.draw.rect(surface, lc, lr, border_radius=10)
        ls = self.fnt["btn"].render("Logout", True, (255,255,255))
        surface.blit(ls, ls.get_rect(center=lr.center))

    # ──────────────────────────────────────────────────────────────────
    #  HOME
    # ──────────────────────────────────────────────────────────────────

    def _draw_home(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mx   = self.sidebar_w + int(24*(W/1920))
        wc_y = int(H*0.05)
        wname = self.account["full_name"].split()[0]
        surface.blit(self.fnt["welcome"].render(f"Welcome back, {wname} 👋",True,(75,135,200)),(mx,wc_y))
        surface.blit(self.fnt["dash_title"].render("Dashboard",True,(28,42,62)),(mx,wc_y+int(48*(H/1080))))
        for i, card in enumerate(HOME_CARDS):
            self._draw_home_card(surface, self.card_rects[i], card, HOME_COLORS[i],
                                 self.card_hovered[i])

    def _draw_home_card(self, surface, rect, card, color, hovered):
        H, W = self.HEIGHT, self.WIDTH
        lift = int(5*(H/1080)) if hovered else 0
        dr   = pygame.Rect(rect.x, rect.y-lift, rect.width, rect.height)
        sh   = pygame.Surface((dr.width,dr.height), pygame.SRCALPHA)
        sh.fill((0,0,0,22 if hovered else 10)); surface.blit(sh, (dr.x+3,dr.y+6))
        _card_bg(surface, dr, alpha=228,
                 border_col=color if hovered else (215,222,232),
                 border_w=2 if hovered else 1)
        pygame.draw.rect(surface, color,
                         pygame.Rect(dr.x, dr.y+int(14*H/1080), int(4*W/1920),
                                     dr.height-int(28*H/1080)), border_radius=3)
        sym = self.fnt["card_sym"].render(card["symbol"], True, color)
        surface.blit(sym, sym.get_rect(center=(dr.centerx, dr.centery-int(20*H/1080))))
        words = card["label"].split()
        mid   = max(1, len(words)//2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words)>2 else [card["label"],""]
        lh    = self.fnt["card_lbl"].get_linesize()
        ly    = dr.centery + int(14*H/1080)
        for ln in lines:
            if ln:
                s = self.fnt["card_lbl"].render(ln, True, (42,58,80))
                surface.blit(s, s.get_rect(center=(dr.centerx, ly))); ly += lh

    # ──────────────────────────────────────────────────────────────────
    #  PANEL SHELL
    # ──────────────────────────────────────────────────────────────────

    def _draw_panel_shell(self, surface, idx):
        pa   = self._panel_area()
        W, H = self.WIDTH, self.HEIGHT

        hdr = pygame.Rect(pa.x, pa.y-int(60*(H/1080)), pa.width, int(50*(H/1080)))

        if idx in (4, 5, 6):
            back_r = pygame.Rect(hdr.x, hdr.y, int(140*(W/1920)), hdr.height)
            glass_back = pygame.Surface((back_r.width, back_r.height), pygame.SRCALPHA)
            glass_back.fill((225, 238, 255, 180)); surface.blit(glass_back, back_r.topleft)
            pygame.draw.rect(surface, (195,210,228), back_r, 1, border_radius=8)
            bs = self.fnt["label"].render("Back", True, (75,110,170))
            surface.blit(bs, bs.get_rect(center=back_r.center))
            self._back_btn_rect = back_r
            crumb_x = hdr.x + int(160*(W/1920))
        else:
            self._back_btn_rect = pygame.Rect(0, 0, 1, 1)
            crumb_x = hdr.x + int(12*(W/1920))

        crumbs = self._breadcrumb(idx)
        cx     = crumb_x
        for j, crumb in enumerate(crumbs):
            col = (30,44,65) if j==len(crumbs)-1 else (130,150,180)
            cs  = self.fnt["breadcrumb"].render(crumb, True, col)
            surface.blit(cs, (cx, hdr.centery - cs.get_height()//2))
            cx += cs.get_width()
            if j < len(crumbs)-1:
                sep = self.fnt["breadcrumb"].render("  ›  ", True, (180,195,215))
                surface.blit(sep, (cx, hdr.centery - sep.get_height()//2))
                cx += sep.get_width()

    def _breadcrumb(self, idx):
        if idx == 6: return ["Patient List", "Register Patient"]
        if idx == 4:
            pt = (self.selected_patient or {}).get("full_name","Patient")
            return ["Patient List", pt, "Game Configuration"]
        if idx == 5:
            pt = (self.selected_patient or {}).get("full_name","Patient")
            return ["Patient List", pt, "Game Configuration", "Start Session"]
        return [PANEL_TITLES.get(idx,"")]

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 0: PATIENT LIST
    # ──────────────────────────────────────────────────────────────────

    def _draw_patient_list(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        self._patient_rows = []

        hint_r = pygame.Rect(pa.x+int(16*W/1920), pa.y+int(16*H/1080),
                             int(460*W/1920), int(56*H/1080))
        self._pt_search_rect = hint_r
        s_active = self._pt_search_active
        pygame.draw.rect(surface, (248,251,255), hint_r, border_radius=8)
        s_border = (40,160,220) if s_active else (195,210,228)
        pygame.draw.rect(surface, s_border, hint_r, 2 if s_active else 1, border_radius=8)
        s_text = self._pt_search_text
        if s_text:
            s_surf = self.fnt["input"].render(s_text, True, (40, 55, 75))
            surface.blit(s_surf, (hint_r.x+int(14*W/1920), hint_r.y+int(14*H/1080)))
            if s_active:
                cx_s = hint_r.x + int(14*W/1920) + s_surf.get_width() + 2
                pygame.draw.line(surface, (40,160,220),
                                 (cx_s, hint_r.y+int(12*H/1080)),
                                 (cx_s, hint_r.y+int(44*H/1080)), 2)
        else:
            ph_txt = "Search patient" if not s_active else ""
            surface.blit(self.fnt["input"].render(ph_txt, True, (170,185,205)),
                         (hint_r.x+int(14*W/1920), hint_r.y+int(14*H/1080)))

        reg_r = pygame.Rect(pa.right-int(280*W/1920), pa.y+int(14*H/1080),
                            int(264*W/1920), int(58*H/1080))
        _btn(surface, reg_r, "+ Register Patient", self.fnt["btn"],
             (40,160,100), (28,135,80), self.register_link_hov, radius=10)
        self._register_link_rect = reg_r

        hdr_y  = pa.y + int(96*H/1080)
        # Column headers — added "Therapist" column
        # Widened so long names fit; Patient ID (10 chars) + Age (>=5 chars) reserved.
        cols   = ["Patient Name", "Patient ID", "Age", "Severity", "Therapist", ""]
        col_xs = [pa.x+int(16*W/1920),  pa.x+int(360*W/1920), pa.x+int(560*W/1920),
                  pa.x+int(680*W/1920), pa.x+int(940*W/1920), pa.x+int(1160*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c,True,(85,105,135)), (cx, hdr_y))
        pygame.draw.line(surface, (210,218,230),
                         (pa.x+int(16*W/1920), hdr_y+int(36*H/1080)),
                         (pa.right-int(16*W/1920), hdr_y+int(36*H/1080)), 1)

        q = self._pt_search_text.strip().lower()
        visible_patients = [p for p in self.patients
                            if not q or q in p.get("full_name","").lower()
                            or q in p.get("patient_id_str","").lower()]

        if not self.patients:
            _empty_state(
                surface,
                pygame.Rect(pa.x, hdr_y+int(30*H/1080), pa.width,
                            pa.bottom-hdr_y-int(60*H/1080)),
                "👤", "No patients registered yet",
                'Tap "+ Register Patient" above to add your first patient.',
                self.fnt["empty_head"], self.fnt["small_i"],
            )
        elif not visible_patients:
            _empty_state(
                surface,
                pygame.Rect(pa.x, hdr_y+int(30*H/1080), pa.width,
                            pa.bottom-hdr_y-int(60*H/1080)),
                "🔍", f'No results for "{self._pt_search_text}"',
                "Try a different name or patient ID.",
                self.fnt["empty_head"], self.fnt["small_i"],
            )
        else:
            row_h = int(72*H/1080)
            for k, pt in enumerate(visible_patients):
                ry    = hdr_y + int(44*H/1080) + k*row_h
                row_r = pygame.Rect(pa.x+int(10*W/1920), ry,
                                    pa.width-int(20*W/1920), row_h-6)
                if k%2==0:
                    bg = pygame.Surface((row_r.width,row_r.height), pygame.SRCALPHA)
                    bg.fill((240,246,255,180)); surface.blit(bg, row_r.topleft)
                pygame.draw.rect(surface, (215,225,240), row_r, 1, border_radius=10)

                # Determine ownership and resolve therapist name
                is_owner = (pt.get("therapist_id") == self.account["id"])
                if is_owner:
                    owner_label = self.account.get("full_name", "You")
                    owner_col   = (40, 140, 80)
                else:
                    _owner_rec = self.db.get_therapist_by_id(pt.get("therapist_id"))
                    owner_label = _owner_rec["full_name"] if _owner_rec else "Unknown"
                    owner_col   = (50, 100, 200)

                mp = pygame.mouse.get_pos()

                # Patient name — hoverable, clickable to open Game Config
                name_val = pt.get("full_name", "—")
                name_r = pygame.Rect(col_xs[0], ry + int(14*H/1080),
                                     int(330*W/1920), int(44*H/1080))
                name_hov = name_r.collidepoint(mp)
                name_col = (40, 155, 220) if name_hov else (40, 55, 75)
                name_surf = self.fnt["body"].render(name_val, True, name_col)
                surface.blit(name_surf, (col_xs[0], ry + int(20*H/1080)))
                self._patient_rows.append((name_r, pt, "name"))

                # Remaining columns (skip index 0 — already drawn above)
                rest_vals = [pt.get("patient_id_str","—"),
                             str(pt.get("age","—")), pt.get("severity","—")]
                for cx, v in zip(col_xs[1:], rest_vals):
                    surface.blit(self.fnt["body"].render(v, True, (40,55,75)),
                                 (cx, ry+int(20*H/1080)))

                # Owner badge
                own_s = self.fnt["tag"].render(owner_label, True, owner_col)
                surface.blit(own_s, (col_xs[4], ry+int(22*H/1080)))

                # Select / Deselect button — indicator only, no navigation
                bh_row = int(34*H/1080); by_row = ry + int(19*H/1080)
                sel_r = pygame.Rect(pa.right-int(112*W/1920), by_row,
                                    int(100*W/1920), bh_row)
                is_selected = (self.selected_patient is not None and
                               self.selected_patient.get("id") == pt.get("id"))
                sel_col = (190, 45, 45) if is_selected else (55, 140, 210)
                sel_txt = "Deselect" if is_selected else "Select"
                pygame.draw.rect(surface, sel_col, sel_r, border_radius=10)
                sel_lbl = self.fnt["tag"].render(sel_txt, True, (255,255,255))
                surface.blit(sel_lbl, sel_lbl.get_rect(center=sel_r.center))
                self._patient_rows.append((sel_r, pt, "select"))

                # Share button — active (blue) for owner, dark/disabled for others
                shr_r = pygame.Rect(pa.right-int(218*W/1920), by_row,
                                    int(90*W/1920), bh_row)
                if is_owner:
                    pygame.draw.rect(surface, (100,155,220), shr_r, border_radius=10)
                    shr_lbl = self.fnt["tag"].render("Share", True, (255,255,255))
                    surface.blit(shr_lbl, shr_lbl.get_rect(center=shr_r.center))
                    self._patient_rows.append((shr_r, pt, "share"))
                else:
                    pygame.draw.rect(surface, (130,135,145), shr_r, border_radius=10)
                    shr_lbl = self.fnt["tag"].render("Share", True, (190,192,198))
                    surface.blit(shr_lbl, shr_lbl.get_rect(center=shr_r.center))

                # Edit button — available to owner and shared therapists
                edt_r = pygame.Rect(pa.right-int(324*W/1920), by_row,
                                    int(90*W/1920), bh_row)
                pygame.draw.rect(surface, (65,155,80), edt_r, border_radius=10)
                edt_lbl = self.fnt["tag"].render("Edit", True, (255,255,255))
                surface.blit(edt_lbl, edt_lbl.get_rect(center=edt_r.center))
                self._patient_rows.append((edt_r, pt, "edit"))

    # ──────────────────────────────────────────────────────────────────
    #  SHARE PATIENT MODAL
    # ──────────────────────────────────────────────────────────────────

    def _draw_share_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mw   = int(W * 0.42)
        mh   = int(H * 0.62)
        mx   = (W - mw) // 2
        my   = (H - mh) // 2
        mr   = pygame.Rect(mx, my, mw, mh)

        # Glass background
        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((228, 238, 252, 252)); surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 210)); surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), mr, 1, border_radius=14)

        pt_name = (self.share_modal_patient or {}).get("full_name", "Patient")
        pt_id   = (self.share_modal_patient or {}).get("patient_id_str", "")

        # Title + patient subtitle
        surface.blit(self.fnt["modal_head"].render("Share Patient", True, (38, 52, 78)),
                     (mr.x + int(18*W/1920), mr.y + int(24*H/1080)))
        surface.blit(self.fnt["small"].render(
            f"{pt_name}  ·  {pt_id}", True, (100, 120, 155)),
            (mr.x + int(18*W/1920), mr.y + int(82*H/1080)))
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + int(16*W/1920), mr.y + int(118*H/1080)),
                         (mr.right - int(16*W/1920), mr.y + int(118*H/1080)), 1)

        # "Share with:" label + input field
        lbl_y = mr.y + int(134*H/1080)
        sf_y  = mr.y + int(164*H/1080)
        sf_r  = pygame.Rect(mr.x + int(18*W/1920), sf_y, mw - int(36*W/1920), int(42*H/1080))
        surface.blit(self.fnt["label"].render("Share with:", True, (80, 95, 115)),
                     (sf_r.x, lbl_y))

        bc = (185, 205, 228) if self._share_confirm_mode else (40, 160, 220)
        pygame.draw.rect(surface, (248, 252, 255), sf_r, border_radius=10)
        pygame.draw.rect(surface, bc, sf_r, 2, border_radius=10)
        disp = self._share_input
        ts_inp = (self.fnt["modal_inp"].render(disp, True, (40, 50, 65))
                  if disp else
                  self.fnt["modal_inp"].render("Enter username", True, (175, 188, 205)))
        surface.blit(ts_inp, ts_inp.get_rect(midleft=(sf_r.x + int(10*W/1920), sf_r.centery)))
        if disp and not self._share_confirm_mode:
            curs_x = sf_r.x + int(10*W/1920) + ts_inp.get_width() + 2
            pygame.draw.line(surface, (40, 160, 220),
                             (curs_x, sf_r.centery - int(9*H/1080)),
                             (curs_x, sf_r.centery + int(9*H/1080)), 2)
        self._share_field_rect = sf_r

        content_y = sf_r.bottom + int(10*H/1080)

        # ── Confirmation prompt ──────────────────────────────────────
        if self._share_confirm_mode and self._share_confirm_therapist:
            t = self._share_confirm_therapist
            conf_lbl = f"Share {pt_name} with {t['full_name']}?"
            surface.blit(self.fnt["body_b"].render(conf_lbl, True, (35, 50, 75)),
                         (mr.x + int(18*W/1920), content_y))
            bw2 = int(128*W/1920); bh2 = int(40*H/1080)
            self._share_yes_rect = pygame.Rect(
                mr.x + int(18*W/1920), content_y + int(38*H/1080), bw2, bh2)
            self._share_no_rect  = pygame.Rect(
                mr.x + int(18*W/1920) + bw2 + int(12*W/1920),
                content_y + int(38*H/1080), bw2, bh2)
            _btn(surface, self._share_yes_rect, "Yes, Share", self.fnt["btn"],
                 (40,160,90),(28,130,70), self._share_yes_hov, radius=10)
            _btn(surface, self._share_no_rect, "Cancel", self.fnt["btn"],
                 (160,175,195),(130,148,168), self._share_no_hov, radius=10)

        # ── Live suggestions ─────────────────────────────────────────
        elif self._share_suggestions:
            self._share_sugg_rects = []
            opt_h  = int(40*H/1080)
            sug_fw = mw - int(36*W/1920)
            for i, t in enumerate(self._share_suggestions):
                sr = pygame.Rect(sf_r.x, content_y + i * opt_h, sug_fw, opt_h)
                mp = pygame.mouse.get_pos()
                if sr.collidepoint(mp):
                    hbg = pygame.Surface((sug_fw, opt_h), pygame.SRCALPHA)
                    hbg.fill((195, 222, 255, 200)); surface.blit(hbg, sr.topleft)
                pygame.draw.rect(surface, (190, 212, 238), sr, 1, border_radius=8)
                row_lbl = f"@{t['username']}  ·  {t['full_name']}"
                surface.blit(self.fnt["body"].render(row_lbl, True, (40, 75, 140)),
                             row_lbl.__class__.join if False else
                             sr.move(int(10*W/1920), (opt_h - self.fnt["body"].get_linesize())//2).topleft)
                self._share_sugg_rects.append((sr, t))

        # ── Error / success / hint ───────────────────────────────────
        elif self._share_error:
            surface.blit(self.fnt["modal_err"].render(self._share_error, True, (210, 50, 50)),
                         (mr.x + int(18*W/1920), content_y))
        elif self._share_success:
            surface.blit(self.fnt["modal_err"].render(self._share_success, True, (50, 175, 75)),
                         (mr.x + int(18*W/1920), content_y))
        elif not disp:
            surface.blit(self.fnt["small_i"].render(
                "Type a username to see suggestions.", True, (155, 168, 188)),
                (mr.x + int(18*W/1920), content_y))

        # ── Currently shared-with section (fixed position) ───────────
        self._unshare_rects = []
        shared_y = mr.y + int(375*H/1080)
        shared   = []
        if self.share_modal_patient:
            shared = self.db.get_shared_therapists(self.share_modal_patient["id"])

        if shared:
            surface.blit(self.fnt["section"].render(
                "Currently shared with:", True, (85, 105, 135)),
                (mr.x + int(18*W/1920), shared_y))
            for i, t in enumerate(shared[:4]):
                row_y = shared_y + int(30*H/1080) + i * int(34*H/1080)
                t_lbl = f"• {t['full_name']}  (@{t['username']})"
                surface.blit(self.fnt["body"].render(t_lbl, True, (50, 65, 90)),
                             (mr.x + int(28*W/1920), row_y))
                rev_r = pygame.Rect(mr.right - int(92*W/1920), row_y - int(2*H/1080),
                                    int(76*W/1920), int(28*H/1080))
                pygame.draw.rect(surface, (210, 60, 60), rev_r, border_radius=8)
                rev_s = self.fnt["tag"].render("Revoke", True, (255, 255, 255))
                surface.blit(rev_s, rev_s.get_rect(center=rev_r.center))
                self._unshare_rects.append((rev_r, t["id"]))
        else:
            surface.blit(self.fnt["small_i"].render(
                "This patient hasn't been shared with anyone yet.",
                True, (155, 168, 188)),
                (mr.x + int(18*W/1920), shared_y))

        # ── Close button ─────────────────────────────────────────────
        bw_c = int(120*W/1920); bh_c = int(42*H/1080)
        clos_r = pygame.Rect(mr.centerx - bw_c // 2, mr.bottom - int(58*H/1080), bw_c, bh_c)
        _btn(surface, clos_r, "Close", self.fnt["btn"],
             (160,175,195),(130,148,168), self._share_close_hov, radius=10)
        self._share_close_rect   = clos_r
        self._share_search_rect  = pygame.Rect(0, 0, 1, 1)
        self._share_confirm_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 6: REGISTER PATIENT
    # ──────────────────────────────────────────────────────────────────

    def _draw_register_patient(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        rp = self.rp
        self._rp_drop_rects = {}

        col1_x = pa.x + int(20*W/1920)
        col2_x = pa.centerx + int(10*W/1920)
        fw      = pa.width//2 - int(36*W/1920)
        fh      = int(40*H/1080)
        lbl_off = int(34*H/1080)
        row_gap = int(80*H/1080)
        top_y   = pa.y + int(34*H/1080)

        field_defs = []

        def _register_field(key, lbl, col_x, row_i, placeholder="", is_drop=False, opts=None):
            fy = top_y + row_i * row_gap
            fr = pygame.Rect(col_x, fy, fw, fh)
            field_defs.append((key, lbl, fr, placeholder, is_drop, opts or []))
            self._rp_drop_rects[key] = (fr, [], opts or [])

        _register_field("full_name",     "Full Name",                   col1_x, 0, "Enter Full Name")
        _register_field("age",           "Age",                         col1_x, 1, "Enter Age")
        _register_field("date_of_stroke","Date of Stroke",              col1_x, 2, "MM-DD-YY")
        _register_field("months_stroke", "Stroke Onset Date",           col1_x, 3, "MM-DD-YY")
        _register_field("sex",           "Sex",                         col1_x, 4, is_drop=True, opts=SEX_OPTS)
        _register_field("dominant_hand", "Dominant Hand",               col1_x, 5, is_drop=True, opts=HAND_OPTS)
        _register_field("affected_hand", "Affected Hand (Stroke Side)", col1_x, 6, is_drop=True, opts=HAND_OPTS)
        _register_field("stroke_type",   "Stroke Type",                 col2_x, 0, is_drop=True, opts=STROKE_TYPES)
        _register_field("severity",      "Severity",                    col2_x, 1, is_drop=True, opts=SEVERITY_OPTS)

        notes_y = top_y + 2*row_gap + int(8*H/1080)
        note_fields_def = [
            ("Muscle Stiffness Notes", "notes_stiffness"),
            ("Pain Level Notes",       "notes_pain"),
            ("Therapist Comments",     "notes_therapist"),
        ]
        for i, (nl, nk) in enumerate(note_fields_def):
            ny  = notes_y + int(64*H/1080) + i*row_gap
            fr2 = pygame.Rect(col2_x, ny, fw, fh)
            field_defs.append((nk, nl, fr2, "Optional", False, []))
            self._rp_drop_rects[nk] = (fr2, [], [])

        # ── PASS 1: labels + field boxes ─────────────────────────────
        surface.blit(self.fnt["section"].render("Clinical Notes", True, (85,105,135)),
                     (col2_x, notes_y))

        for (key, lbl, fr, placeholder, is_drop, opts) in field_defs:
            active = (rp["active_key"] == key)
            surface.blit(self.fnt["label"].render(lbl, True, (80,95,115)),
                         (fr.x, fr.y - lbl_off))
            pygame.draw.rect(surface, (255,255,255), fr, border_radius=8)
            pygame.draw.rect(surface,
                             (40,160,220) if active else (190,205,225),
                             fr, 2 if active else 1, border_radius=8)
            val = rp.get(key, "")
            if is_drop:
                disp = val or "Select"
                tc   = (40,50,65) if val else (175,188,205)
                ts   = self.fnt["input"].render(disp, True, tc)
                surface.blit(ts, ts.get_rect(midleft=(fr.x+int(10*W/1920), fr.centery)))
                chev = self.fnt["sym26"].render("▼", True, (90,110,140))
                surface.blit(chev, chev.get_rect(midright=(fr.right-int(10*W/1920), fr.centery)))
            else:
                ts = (self.fnt["input"].render(val, True, (40,50,65)) if val
                      else self.fnt["input"].render(placeholder, True, (185,198,215)))
                surface.blit(ts, ts.get_rect(midleft=(fr.x+int(10*W/1920), fr.centery)))

        # ── PASS 2: open dropdowns drawn on top of everything ─────────
        open_key_map = {
            "sex":           "sex_open",
            "dominant_hand": "dominant_open",
            "affected_hand": "affected_open",
            "stroke_type":   "stroke_open",
            "severity":      "severity_open",
        }
        for (key, lbl, fr, placeholder, is_drop, opts) in field_defs:
            if not is_drop or not opts:
                continue
            open_flag = open_key_map.get(key)
            if open_flag and rp.get(open_flag):
                opt_h  = int(38*H/1080)
                opt_rs = []
                dp_bg  = pygame.Rect(fr.x, fr.bottom - 1, fw, len(opts)*opt_h + 4)
                pygame.draw.rect(surface, (248,251,255), dp_bg, border_radius=8)
                pygame.draw.rect(surface, (40,160,220),  dp_bg, 2, border_radius=8)
                for j, ov in enumerate(opts):
                    or_ = pygame.Rect(fr.x, fr.bottom + j*opt_h, fw, opt_h)
                    mp  = pygame.mouse.get_pos()
                    if or_.collidepoint(mp):
                        pygame.draw.rect(surface, (220,236,255), or_, border_radius=6)
                    ts2 = self.fnt["input"].render(ov, True, (40,50,65))
                    surface.blit(ts2, ts2.get_rect(midleft=(or_.x+int(10*W/1920), or_.centery)))
                    opt_rs.append(or_)
                self._rp_drop_rects[key] = (fr, opt_rs, opts)

        # ── Messages + submit button ──────────────────────────────────
        msg_y = pa.bottom - int(90*H/1080)
        if rp["error"]:
            surface.blit(self.fnt["modal_err"].render(rp["error"], True, (210,50,50)),
                         (pa.centerx - int(140*W/1920), msg_y))
        if rp["success"]:
            surface.blit(self.fnt["modal_err"].render(rp["success"], True, (50,175,75)),
                         (pa.centerx - int(140*W/1920), msg_y))

        rb = pygame.Rect(pa.centerx - int(130*W/1920), pa.bottom - int(62*H/1080),
                         int(260*W/1920), int(46*H/1080))
        _btn(surface, rb, "Register Patient", self.fnt["btn"],
             (40,160,220), (25,130,190), self.rp_btn_hov, radius=12)
        self._rp_btn_rect = rb

        auto_s = self.fnt["small_i"].render(
            "A unique Patient ID will be auto-generated upon registration.",
            True, (140,155,175))
        surface.blit(auto_s, auto_s.get_rect(center=(pa.centerx, rb.y - int(18*H/1080))))

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 1: SESSION HISTORY
    # ──────────────────────────────────────────────────────────────────

    def _draw_session_history(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        table_y = pa.y + int(28*H/1080)
        cols   = ["Date", "Patient", "Game", "Score", "Duration", "Difficulty"]
        col_xs = [pa.x+int(16*W/1920), pa.x+int(230*W/1920), pa.x+int(510*W/1920),
                  pa.x+int(720*W/1920), pa.x+int(860*W/1920), pa.x+int(1020*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c, True, (85,105,135)), (cx, table_y))
        pygame.draw.line(surface, (210,218,230),
                         (pa.x+int(16*W/1920), table_y+int(36*H/1080)),
                         (pa.right-int(16*W/1920), table_y+int(36*H/1080)), 1)

        pt = self.selected_patient
        if not pt:
            _empty_state(surface,
                         pygame.Rect(pa.x, table_y+int(48*H/1080), pa.width,
                                     pa.bottom-table_y-int(48*H/1080)),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view their session history.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            return

        sessions = (self.db.get_sessions(self.account["id"], patient_id=pt["id"])
                    if hasattr(self.db, "get_sessions") else [])
        if not sessions:
            _empty_state(surface,
                         pygame.Rect(pa.x, table_y+int(48*H/1080), pa.width,
                                     pa.bottom-table_y-int(48*H/1080)),
                         "📋", "No sessions recorded yet",
                         f"No sessions found for {pt.get('full_name', 'this patient')}.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            return

        row_h = int(52*H/1080)
        for k, s in enumerate(sessions):
            ry = table_y + int(44*H/1080) + k * row_h
            if ry + row_h > pa.bottom - int(10*H/1080):
                break
            row_r = pygame.Rect(pa.x+int(10*W/1920), ry, pa.width-int(20*W/1920), row_h - 4)
            if k % 2 == 0:
                bg = pygame.Surface((row_r.width, row_r.height), pygame.SRCALPHA)
                bg.fill((240,246,255,180)); surface.blit(bg, row_r.topleft)
            pygame.draw.rect(surface, (215,225,240), row_r, 1, border_radius=8)

            date_str = str(s.get("played_at",""))[:16]
            mins, secs = divmod(int(s.get("duration_sec", 0)), 60)
            dur_str = f"{mins}:{secs:02d}" if mins else f"{secs}s"
            vals = [date_str,
                    s.get("patient_name","—"),
                    s.get("game","—"),
                    str(s.get("score","—")),
                    dur_str,
                    s.get("difficulty","—")]
            for cx, v in zip(col_xs, vals):
                surface.blit(self.fnt["small"].render(v, True, (40,55,75)),
                             (cx, ry + int(14*H/1080)))

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 2: ANALYTICS
    # ──────────────────────────────────────────────────────────────────

    def _draw_analytics(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        lx = pa.x + int(16*W/1920)
        ly = pa.y + int(28*H/1080)

        pt = self.selected_patient
        if not pt:
            _empty_state(surface, pygame.Rect(pa.x, ly, pa.width, pa.bottom-ly),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view their analytics.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            return

        sessions = (self.db.get_sessions(self.account["id"], patient_id=pt["id"])
                    if hasattr(self.db, "get_sessions") else [])

        if not sessions:
            _empty_state(surface, pygame.Rect(pa.x, ly, pa.width, pa.bottom-ly),
                         "📊", "No analytics data yet",
                         f"No sessions recorded for {pt.get('full_name', 'this patient')} yet.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            return

        total   = len(sessions)
        scores  = [s.get("score", 0) for s in sessions]
        durs    = [s.get("duration_sec", 0) for s in sessions]
        best    = max(scores)
        avg     = sum(scores) / total
        tot_dur = sum(durs)
        tot_min, tot_sec = divmod(tot_dur, 60)

        stats = [
            ("Total Sessions",   str(total)),
            ("Best Score",       str(best)),
            ("Average Score",    f"{avg:.1f}"),
            ("Total Play Time",  f"{tot_min}m {tot_sec}s"),
        ]
        sw = int((pa.width - int(64*W/1920)) // 4)
        for i, (label, val) in enumerate(stats):
            sx = lx + i * (sw + int(16*W/1920))
            box = pygame.Rect(sx, ly, sw, int(90*H/1080))
            _card_bg(surface, box, alpha=235, border_col=(185,210,240), border_w=1)
            surface.blit(self.fnt["section"].render(label, True, (85,105,135)),
                         (sx + int(10*W/1920), ly + int(10*H/1080)))
            surface.blit(self.fnt["panel_title"].render(val, True, (40,100,210)),
                         (sx + int(10*W/1920), ly + int(40*H/1080)))

        # Recent sessions bar chart (score per session, last 10)
        chart_y = ly + int(120*H/1080)
        surface.blit(self.fnt["section"].render("Score per Session (recent)", True, (85,105,135)),
                     (lx, chart_y))
        chart_y += int(32*H/1080)
        recent = sessions[:10][::-1]
        if recent:
            max_s  = max(s.get("score", 1) for s in recent) or 1
            bar_w  = int((pa.width - int(64*W/1920)) // len(recent))
            bar_h_max = int(180*H/1080)
            for i, s in enumerate(recent):
                bh = max(4, int(bar_h_max * s.get("score", 0) / max_s))
                bx = lx + i * (bar_w + 4)
                br = pygame.Rect(bx, chart_y + bar_h_max - bh, bar_w - 4, bh)
                pygame.draw.rect(surface, (60, 140, 210), br, border_radius=4)
                sc_s = self.fnt["time"].render(str(s.get("score",0)), True, (60,80,120))
                surface.blit(sc_s, sc_s.get_rect(center=(br.centerx, br.y - int(14*H/1080))))

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 3: CALIBRATION RECORDS
    # ──────────────────────────────────────────────────────────────────

    def _draw_calibration(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        table_y = pa.y+int(28*H/1080)
        cols    = ["Data Type","Force Sensor","Flex Sensor","Motion Sensor","Timestamp","Therapist"]
        # Widened column positions to fit larger font
        col_xs  = [pa.x+int(16*W/1920),  pa.x+int(230*W/1920), pa.x+int(450*W/1920),
                   pa.x+int(670*W/1920), pa.x+int(900*W/1920), pa.x+int(1120*W/1920)]
        for cx,c in zip(col_xs,cols):
            surface.blit(self.fnt["section"].render(c,True,(85,105,135)),(cx,table_y))
        pygame.draw.line(surface,(210,218,230),
                         (pa.x+int(16*W/1920),table_y+int(36*H/1080)),
                         (pa.right-int(16*W/1920),table_y+int(36*H/1080)),1)
        info_r = pygame.Rect(pa.x+int(16*W/1920),table_y+int(50*H/1080),
                             pa.width-int(32*W/1920),int(64*H/1080))
        pygame.draw.rect(surface,(235,245,255),info_r,border_radius=8)
        pygame.draw.rect(surface,(180,210,240),info_r,1,border_radius=8)
        surface.blit(self.fnt["sym26"].render(
            "ℹ  Calibration values (Raw, Average Max, Resting, Threshold) are recorded "
            "per patient at the start of each session.",
            True,(65,105,165)),(info_r.x+int(14*W/1920),info_r.y+int(18*H/1080)))
        _empty_state(surface,
                     pygame.Rect(pa.x,table_y+int(130*H/1080),pa.width,
                                 pa.bottom-table_y-int(130*H/1080)),
                     "🎯","No calibration records yet",
                     "Calibration data will appear here after the first session calibration.",
                     self.fnt["empty_head"],self.fnt["small_i"])

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 4: GAME CONFIGURATION
    # ──────────────────────────────────────────────────────────────────

    def _draw_game_config(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        gc   = self.gc
        _card_bg(surface, pa, alpha=220)
        self._game_tiles = []

        # ── Banner ────────────────────────────────────────────────────
        pt    = self.selected_patient or {}
        pt_nm = pt.get("full_name","—")
        sev   = pt.get("severity","—")
        ban_r = pygame.Rect(pa.x+int(16*W/1920), pa.y+int(12*H/1080),
                            pa.width-int(32*W/1920), int(50*H/1080))
        pygame.draw.rect(surface,(232,244,255),ban_r,border_radius=8)
        pygame.draw.rect(surface,(160,205,245),ban_r,1,border_radius=8)
        surface.blit(self.fnt["small"].render(
            f"Configuring session for:  {pt_nm}  ·  {sev}",
            True,(50,100,160)),(ban_r.x+int(12*W/1920),ban_r.y+int(15*H/1080)))

        # ── Game tiles — word-wrap helper ─────────────────────────────
        def _tile_name(surf, font, text, color, max_w, x, y, lh):
            words = text.split()
            lines, cur = [], []
            for w in words:
                test = " ".join(cur + [w])
                if font.size(test)[0] <= max_w:
                    cur.append(w)
                else:
                    if cur: lines.append(" ".join(cur))
                    cur = [w]
            if cur: lines.append(" ".join(cur))
            for k, line in enumerate(lines):
                surf.blit(font.render(line, True, color), (x, y + k * lh))
            return len(lines)

        tw = int(460*W/1920); th = int(120*H/1080); tg = int(16*W/1920)

        game_y = pa.y + int(78*H/1080)
        surface.blit(self.fnt["small"].render("Single Skill Games", True, (75,95,125)),
                     (pa.x + int(16*W/1920), game_y))
        ty = game_y + int(32*H/1080)

        ss_total_w = len(SINGLE_SKILL_GAMES) * tw + (len(SINGLE_SKILL_GAMES) - 1) * tg
        ss_start_x = pa.x + (pa.width - ss_total_w) // 2
        for i, (gname, gtype) in enumerate(SINGLE_SKILL_GAMES):
            tx  = ss_start_x + i * (tw + tg)
            tr  = pygame.Rect(tx, ty, tw, th)
            sel = gc["selected_game"] and gc["selected_game"][1] == gtype
            bc  = PANEL_COLORS.get(i, (180,200,220)) if sel else (210,220,235)
            _card_bg(surface, tr, alpha=245 if sel else 200, border_col=bc, border_w=2 if sel else 1)
            if sel and gc["selected_game"]:
                lbl_s = self.fnt["body_b"].render(gtype, True, bc)
                surface.blit(lbl_s, lbl_s.get_rect(midleft=(tr.x + int(14*W/1920), tr.y + int(36*H/1080))))
                sub = self.fnt["small"].render(gc["selected_game"][0], True, bc)
                surface.blit(sub, sub.get_rect(midleft=(tr.x + int(14*W/1920), tr.y + int(82*H/1080))))
            else:
                lbl_s = self.fnt["body_b"].render(gtype, True, (55,72,95))
                surface.blit(lbl_s, lbl_s.get_rect(midleft=(tr.x + int(14*W/1920), tr.centery)))
            self._game_tiles.append((tr, (gname, gtype)))

        ig_label_y = ty + th + int(50*H/1080)
        surface.blit(self.fnt["small"].render("Integrated Games", True, (75,95,125)),
                     (pa.x + int(16*W/1920), ig_label_y))
        gy2 = ig_label_y + int(32*H/1080)

        ig_total_w = len(INTEGRATED_GAMES) * tw + (len(INTEGRATED_GAMES) - 1) * tg
        ig_start_x = pa.x + (pa.width - ig_total_w) // 2
        for i, (gname, gtype) in enumerate(INTEGRATED_GAMES):
            tx  = ig_start_x + i * (tw + tg)
            tr  = pygame.Rect(tx, gy2, tw, th)
            sel = gc["selected_game"] and gc["selected_game"][0] == gname
            bc  = PANEL_COLORS.get(i + 3, (180,200,220)) if sel else (210,220,235)
            _card_bg(surface, tr, alpha=245 if sel else 200, border_col=bc, border_w=2 if sel else 1)
            lbl_s = self.fnt["body_b"].render(gname, True, bc if sel else (55,72,95))
            surface.blit(lbl_s, lbl_s.get_rect(center=(tr.centerx, tr.centery)))
            self._game_tiles.append((tr, (gname, gtype)))

        # ── Proceed to Start Calibration button ───────────────────────
        game_chosen = gc["selected_game"] is not None
        next_r = pygame.Rect(pa.right-int(260*W/1920), pa.bottom-int(60*H/1080),
                             int(244*W/1920), int(46*H/1080))
        nc = (40,160,80)  if game_chosen else (175,188,202)
        nh = (28,130,62)  if game_chosen else (155,168,182)
        _btn(surface,next_r,"Start Calibration",self.fnt["btn"],
             nc,nh,self.gc_next_hov and game_chosen,radius=12)
        self._gc_next_rect = next_r if game_chosen else pygame.Rect(0,0,1,1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 5: START SESSION
    # ──────────────────────────────────────────────────────────────────

    def _draw_start_session(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        gc = self.gc
        pt = self.selected_patient or {}

        cx0 = pa.x + int(20*W/1920)
        cy0 = pa.y + int(20*H/1080)

        cal_done     = self.calibration_done or self.calibration_bypassed
        cal_mismatch = self._calibration_mismatched()

        steps = [
            ("Patient selected",             True,                             False),
            ("Game configured",              gc["selected_game"] is not None,  False),
            ("Calibration complete",         cal_done,                         cal_mismatch),
            ("Session parameters confirmed", gc["selected_game"] is not None,  False),
            ("Ready to start",               self._session_ready(),            cal_mismatch),
        ]
        surface.blit(self.fnt["section"].render("Session Readiness Checklist", True, (75,95,125)),
                     (cx0, cy0))
        for i, (lbl, done, warn) in enumerate(steps):
            sy  = cy0 + int(30*H/1080) + i*int(36*H/1080)
            col = ((220,140,30) if warn else
                   (55,175,75)  if done else
                   (195,205,220))
            pygame.draw.circle(surface, col,
                               (cx0+int(10*W/1920), sy+int(10*H/1080)),
                               int(9*H/1080))
            txt_col = ((170,105,15) if warn else
                       (40,55,75)   if done else
                       (130,145,165))
            surface.blit(self.fnt["body"].render(lbl, True, txt_col),
                         (cx0+int(28*W/1920), sy))

        custom_active = gc.get("duration") == "Custom"
        custom_extra  = int(44*H/1080) if custom_active else 0
        sum_r = pygame.Rect(pa.x+int(80*W/1920), cy0+int(225*H/1080),
                            int(480*W/1920), int(288*H/1080) + custom_extra)
        _card_bg(surface, sum_r, alpha=235, border_col=(185,210,240), border_w=1)
        surface.blit(self.fnt["section"].render("Session Details", True, (75,95,125)),
                     (sum_r.x+int(12*W/1920), sum_r.y+int(12*H/1080)))
        gname = gc["selected_game"][0] if gc["selected_game"] else "—"

        # ── Static rows: Patient and Game ─────────────────────────────
        for k, line in enumerate([
            f"Patient  : {pt.get('full_name','—')}",
            f"Game     : {gname}",
        ]):
            surface.blit(self.fnt["body"].render(line, True, (50,65,90)),
                         (sum_r.x+int(12*W/1920), sum_r.y+int(46*H/1080)+k*int(34*H/1080)))

        # ── Interactive dropdown rows: Duration and Speed ─────────────
        ss_params = [
            ("duration", "Duration", gc["duration"],
             ["60 seconds", "120 seconds", "180 seconds", "Custom"]),
            ("speed",    "Speed",    gc["speed"],    ["Slow", "Normal", "Fast"]),
        ]
        dd_w  = sum_r.width - int(24*W/1920)
        dd_h  = int(36*H/1080)
        dd_x  = sum_r.x + int(12*W/1920)
        dd_y0 = sum_r.y + int(158*H/1080)
        self._ss_param_rects = {}
        for i, (pk, plbl, pval, _) in enumerate(ss_params):
            extra   = custom_extra if i > 0 else 0
            field_y = dd_y0 + i * int(84*H/1080) + extra
            lbl_s   = self.fnt["small"].render(plbl, True, (88,108,138))
            surface.blit(lbl_s, (dd_x, field_y - int(34*H/1080)))
            pr = pygame.Rect(dd_x, field_y, dd_w, dd_h)
            active = (self._ss_open_param is not None and
                      self._ss_open_param[0] == pk)
            pygame.draw.rect(surface, (255,255,255), pr, border_radius=8)
            pygame.draw.rect(surface,
                             (40,160,220) if active else (185,205,228),
                             pr, 2 if active else 1, border_radius=8)
            val_display = pval
            txt_s  = self.fnt["input"].render(val_display, True, (40,55,80))
            chev_s = self.fnt["sym26"].render("▼", True, (90,110,140))
            surface.blit(txt_s,  txt_s.get_rect(midleft=(pr.x + int(8*W/1920), pr.centery)))
            surface.blit(chev_s, chev_s.get_rect(midright=(pr.right - int(8*W/1920), pr.centery)))
            self._ss_param_rects[pk] = pr

        cal_r = pygame.Rect(pa.x+int(610*W/1920), cy0+int(225*H/1080),
                            pa.width-int(630*W/1920), int(220*H/1080))
        if cal_mismatch:
            # ── Sensor mismatch warning ───────────────────────────────
            res = self.calibration_result or {}
            cal_type  = res.get("game_type", "—")
            cal_sens  = res.get("sensor",    "—")
            need_type = (gc.get("selected_game") or (None, "—"))[1] or "—"
            SENSOR_FOR = {"Grip Strength": "Force Sensor",
                          "Finger Flexion": "Flex Sensors",
                          "Wrist Rotation": "Motion Sensor"}
            need_sens = SENSOR_FOR.get(need_type, "—")
            pygame.draw.rect(surface, (255,243,215), cal_r, border_radius=14)
            pygame.draw.rect(surface, (220,145,30),  cal_r, 2, border_radius=14)
            surface.blit(self.fnt["sym26"].render("⚠  Sensor Mismatch",
                         True, (175,110,10)),
                         (cal_r.x+int(12*W/1920), cal_r.y+int(12*H/1080)))
            mismatch_lines = [
                f"Calibrated for : {cal_type}  ({cal_sens})",
                f"Required for   : {need_type}  ({need_sens})",
                "Please recalibrate for the correct sensor.",
            ]
            for j, ln in enumerate(mismatch_lines):
                surface.blit(self.fnt["small"].render(ln, True, (140,90,15)),
                             (cal_r.x+int(12*W/1920),
                              cal_r.y+int(50*H/1080)+j*int(26*H/1080)))
            recal_r = pygame.Rect(cal_r.x+int(12*W/1920), cal_r.bottom-int(50*H/1080),
                                  int(190*W/1920), int(36*H/1080))
            rc_col = (180,110,10) if self._calibrate_hov else (220,145,30)
            pygame.draw.rect(surface, rc_col, recal_r, border_radius=8)
            surface.blit(self.fnt["small"].render("Calibrate Now", True, (255,255,255)),
                         self.fnt["small"].render("Calibrate Now", True,
                         (255,255,255)).get_rect(center=recal_r.center))
            self._calibrate_btn_rect = recal_r
        elif self.calibration_done and not self.calibration_bypassed:
            # ── Real calibration complete ─────────────────────────────
            res = self.calibration_result or {}
            pygame.draw.rect(surface, (215,248,225), cal_r, border_radius=14)
            pygame.draw.rect(surface, (55,185,85),   cal_r, 1, border_radius=14)
            surface.blit(self.fnt["sym26"].render("✓  Calibration Complete",
                         True, (30,140,60)),
                         (cal_r.x+int(12*W/1920), cal_r.y+int(12*H/1080)))
            details = [
                f"Sensor      : {res.get('sensor', '—')}",
                f"Average     : {res.get('average', 0):.3f}",
                f"Threshold   : {res.get('threshold', 0):.3f}",
                f"Sensitivity : {res.get('sensitivity', '—')}",
            ]
            for j, ln in enumerate(details):
                surface.blit(self.fnt["small"].render(ln, True, (40,120,60)),
                             (cal_r.x+int(12*W/1920),
                              cal_r.y+int(50*H/1080)+j*int(26*H/1080)))
            recal_r = pygame.Rect(cal_r.x+int(12*W/1920), cal_r.bottom-int(46*H/1080),
                                  int(172*W/1920), int(32*H/1080))
            rc_col = (40,150,70) if self._calibrate_hov else (55,185,85)
            pygame.draw.rect(surface, rc_col, recal_r, border_radius=8)
            surface.blit(self.fnt["small"].render("Re-Calibrate", True, (255,255,255)),
                         self.fnt["small"].render("Re-Calibrate", True,
                         (255,255,255)).get_rect(center=recal_r.center))
            self._calibrate_btn_rect = recal_r
        elif cal_done:
            # ── Bypassed (DEV) ────────────────────────────────────────
            pygame.draw.rect(surface, (220,248,228), cal_r, border_radius=14)
            pygame.draw.rect(surface, (60,190,90),   cal_r, 1, border_radius=14)
            surface.blit(self.fnt["section"].render("Calibration Bypassed (DEV)",
                         True, (30,140,60)),
                         (cal_r.x+int(12*W/1920), cal_r.y+int(12*H/1080)))
            surface.blit(self.fnt["small_i"].render(
                         "Session will run without sensor calibration.",
                         True, (50,120,70)),
                         (cal_r.x+int(12*W/1920), cal_r.y+int(46*H/1080)))
            self._calibrate_btn_rect = pygame.Rect(0, 0, 1, 1)
        else:
            # ── Calibration Required ──────────────────────────────────
            pygame.draw.rect(surface, (255,248,220), cal_r, border_radius=14)
            pygame.draw.rect(surface, (240,190,60),  cal_r, 1, border_radius=14)
            surface.blit(self.fnt["section"].render("Calibration Required",
                         True, (160,110,20)),
                         (cal_r.x+int(12*W/1920), cal_r.y+int(12*H/1080)))
            game_type = (gc.get("selected_game") or (None, "—"))[1] or "—"
            sensor_map = {
                "Grip Strength": "Force Sensor",
                "Finger Flexion": "Flex Sensors",
                "Wrist Rotation": "Motion Sensor",
            }
            sensor_name = sensor_map.get(game_type, "Sensor")
            for j, ln in enumerate([
                    f"Game type: {game_type}",
                    f"Requires: {sensor_name}",
                    "Calibrate before starting the session."]):
                surface.blit(self.fnt["small"].render(ln, True, (130,95,30)),
                             (cal_r.x+int(12*W/1920),
                              cal_r.y+int(50*H/1080)+j*int(30*H/1080)))
            gc_btn = pygame.Rect(cal_r.x+int(12*W/1920), cal_r.bottom-int(50*H/1080),
                                 int(180*W/1920), int(36*H/1080))
            btn_col = (195,135,15) if self._calibrate_hov else (225,165,30)
            pygame.draw.rect(surface, btn_col, gc_btn, border_radius=8)
            surface.blit(self.fnt["small"].render("Calibrate", True, (255,255,255)),
                         self.fnt["small"].render("Calibrate", True,
                         (255,255,255)).get_rect(center=gc_btn.center))
            self._calibrate_btn_rect = gc_btn

        # ── Adaptive Difficulty info box (above DEV bypass) ──────────
        adp_h = int(74*H/1080)
        adp_y = pa.bottom - int(170*H/1080)
        adp_r = pygame.Rect(pa.x+int(16*W/1920), adp_y,
                            pa.width-int(32*W/1920), adp_h)
        pygame.draw.rect(surface, (235,245,255), adp_r, border_radius=8)
        pygame.draw.rect(surface, (150,195,240), adp_r, 1, border_radius=8)
        surface.blit(self.fnt["small"].render(
            "Adaptive Difficulty: After calibration, the system normalises patient max effort to 100%.",
            True, (65,105,165)),
            (adp_r.x+int(10*W/1920), adp_r.y+int(10*H/1080)))
        surface.blit(self.fnt["small"].render(
            "Therapist adjusts speed/difficulty as a % of that calibrated maximum.",
            True, (65,105,165)),
            (adp_r.x+int(10*W/1920), adp_r.y+int(42*H/1080)))

        # ── DEV bypass toggle ─────────────────────────────────────────
        byp_r    = pygame.Rect(pa.x+int(16*W/1920), pa.bottom-int(82*H/1080),
                               int(260*W/1920), int(36*H/1080))
        byp_col  = (160, 60,  60) if cal_done else (100, 100, 120)
        byp_hcol = (130, 35,  35) if cal_done else ( 70,  70,  95)
        byp_lbl  = "Disable Bypass" if cal_done else "Bypass Calibration"
        _btn(surface, byp_r, byp_lbl, self.fnt["tag"],
             byp_col, byp_hcol, self._bypass_hov, radius=8)
        self._bypass_btn_rect = byp_r

        ready = self._session_ready()
        btn_r = pygame.Rect(pa.centerx-int(140*W/1920), pa.bottom-int(56*H/1080),
                            int(280*W/1920), int(48*H/1080))
        bc = (40,160,80)  if ready else (175,188,202)
        bh = (28,130,62)  if ready else (155,168,182)
        _btn(surface, btn_r, "Start Session", self.fnt["btn"],
             bc, bh, self.start_hov and ready, radius=14)
        self._start_btn_rect = btn_r if ready else pygame.Rect(0, 0, 1, 1)

        # ── Custom duration text input (drawn AFTER other content) ────
        if gc.get("duration") == "Custom":
            dur_pr = self._ss_param_rects.get("duration")
            if dur_pr:
                cust_r  = pygame.Rect(dur_pr.x, dur_pr.bottom + int(6*H/1080),
                                      dur_pr.width, int(34*H/1080))
                act_c   = self._ss_custom_dur_active
                pygame.draw.rect(surface, (255,255,255), cust_r, border_radius=6)
                pygame.draw.rect(surface,
                                 (40,160,220) if act_c else (185,205,228),
                                 cust_r, 2 if act_c else 1, border_radius=6)
                dv = self._gc_custom_dur
                fi_s = (self.fnt["input"].render(dv + " sec", True, (40,50,65))
                        if dv else
                        self.fnt["input"].render("Enter seconds…", True, (185,198,215)))
                surface.blit(fi_s, fi_s.get_rect(
                    midleft=(cust_r.x+int(8*W/1920), cust_r.centery)))
                self._ss_custom_dur_rect = cust_r

        # ── Open dropdown list (drawn LAST — renders on top of everything) ──
        if self._ss_open_param:
            open_key, open_opts = self._ss_open_param
            pr = self._ss_param_rects.get(open_key)
            if pr:
                opt_h = int(36*H/1080)
                dp_r  = pygame.Rect(pr.x, pr.bottom, pr.width,
                                    len(open_opts) * opt_h + 4)
                pygame.draw.rect(surface, (248,251,255), dp_r, border_radius=8)
                pygame.draw.rect(surface, (40,160,220),  dp_r, 2, border_radius=8)
                for j, ov in enumerate(open_opts):
                    or_   = pygame.Rect(pr.x, pr.bottom + j * opt_h, pr.width, opt_h)
                    ts3   = self.fnt["input"].render(ov, True, (40,50,65))
                    surface.blit(ts3, ts3.get_rect(
                        midleft=(or_.x+int(8*W/1920), or_.centery)))

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE MODAL
    # ──────────────────────────────────────────────────────────────────

    def _draw_overlay(self, surface):
        ov = pygame.Surface((self.WIDTH,self.HEIGHT), pygame.SRCALPHA)
        ov.fill((12,18,32,172)); surface.blit(ov,(0,0))

    def _draw_edit_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mr   = self.edit_modal_rect
        ms   = pygame.Surface((mr.width,mr.height), pygame.SRCALPHA)
        ms.fill((228, 238, 252, 252)); surface.blit(ms, mr.topleft)
        hl_m = pygame.Surface((mr.width, 3), pygame.SRCALPHA)
        hl_m.fill((255, 255, 255, 210)); surface.blit(hl_m, mr.topleft)
        pygame.draw.rect(surface,(175,205,235),mr,1,border_radius=16)
        hs = self.fnt["modal_head"].render("Edit Profile",True,(38,52,78))
        surface.blit(hs,hs.get_rect(midleft=(mr.x+int(18*W/1920),mr.y+int(35*H/1080))))

        bcx,bcy = self.edit_big_center
        draw_icon(surface,self.edit_selected_icon,bcx,bcy,self.edit_big_r,shadow=True)
        for (scx,scy,idx) in self.edit_small_circles:
            sel=(self.edit_selected_icon==idx)
            draw_icon(surface,idx,scx,scy,self.edit_small_r,shadow=True,
                      border_color=(40,160,220) if sel else None,
                      border_width=3 if sel else 0)

        for i,field in enumerate(self.edit_fields):
            active=(i==self.edit_active_field)
            rect=field["rect"]
            surface.blit(self.fnt["modal_lbl"].render(field["label"],True,(80,95,115)),
                         (rect.x,rect.y-int(36*H/1080)))
            bc=(40,160,220) if active else (185,205,228)
            pygame.draw.rect(surface,(255,255,255),rect,border_radius=9)
            pygame.draw.rect(surface,bc,rect,3 if active else 1,border_radius=9)
            if field["key"]=="role":
                val=field["value"] or field["placeholder"]
                ts=self.fnt["modal_inp"].render(val,True,(40,50,65) if field["value"] else (175,188,205))
                surface.blit(ts,ts.get_rect(midleft=(rect.x+int(10*W/1920),rect.centery)))
                chev=self.fnt["sym26"].render("▼",True,(95,115,145))
                surface.blit(chev,chev.get_rect(midright=(rect.right-int(12*W/1920),rect.centery)))
            else:
                val=field["value"]
                ts=(self.fnt["modal_inp"].render("•"*len(val) if field["is_pin"] else val,
                    True,(40,50,65)) if val else
                    self.fnt["modal_inp"].render(field["placeholder"],True,(175,188,205)))
                surface.blit(ts,ts.get_rect(midleft=(rect.x+int(10*W/1920),rect.centery)))
                if active and val:
                    cx2=rect.x+int(10*W/1920)+ts.get_width()+2
                    pygame.draw.line(surface,(40,160,220),
                                     (cx2,rect.centery-int(9*H/1080)),
                                     (cx2,rect.centery+int(9*H/1080)),2)

        if self.edit_role_open:
            rf=self.edit_fields[2]["rect"]
            oh=self.edit_role_options[0]["rect"].height
            pr=pygame.Rect(rf.x,rf.bottom-1,rf.width,len(ROLES)*oh+4)
            pygame.draw.rect(surface,(248,251,255),pr,border_radius=9)
            pygame.draw.rect(surface,(40,160,220),pr,2,border_radius=9)
            for opt in self.edit_role_options:
                ts=self.fnt["modal_inp"].render(opt["label"],True,(40,50,65))
                surface.blit(ts,ts.get_rect(midleft=(opt["rect"].x+int(10*W/1920),opt["rect"].centery)))

        if self.edit_error:
            es=self.fnt["modal_err"].render(self.edit_error,True,(210,50,50))
            surface.blit(es,es.get_rect(center=(mr.centerx,self.edit_save_rect.y-int(14*H/1080))))

        for rect,cn,ch,hov,lbl,fnt in [
            (self.edit_save_rect,  (40,160,220),(25,125,180),self.edit_save_hov,  "Save",           self.fnt["btn"]),
            (self.edit_cancel_rect,(175,190,210),(148,162,180),self.edit_cancel_hov,"Cancel",        self.fnt["btn"]),
            (self.edit_delete_rect,(200,50,50),(165,28,28),self.edit_delete_hov,"Delete Account",    self.fnt["profile"]),
        ]:
            pygame.draw.rect(surface,ch if hov else cn,rect,border_radius=10)
            s=fnt.render(lbl,True,(255,255,255))
            surface.blit(s,s.get_rect(center=rect.center))

    def _draw_skill_game_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        skill = self._gc_skill_modal_type or ""
        games = SKILL_GAMES.get(skill, [])

        item_h  = int(56*H/1080)
        pad     = int(24*W/1920)
        mw      = int(W * 0.38)
        header_h = int(70*H/1080)
        close_h  = int(54*H/1080)
        mh      = header_h + len(games) * item_h + pad + close_h
        mx      = (W - mw) // 2
        my      = (H - mh) // 2
        mr      = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((245, 249, 255, 255))
        surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200))
        surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (100, 160, 220), mr, 2, border_radius=14)

        # Title
        ts = self.fnt["modal_lbl"].render(f"Select a Game  —  {skill}", True, (38, 52, 78))
        surface.blit(ts, ts.get_rect(midleft=(mr.x + pad, mr.y + header_h // 2)))
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + pad, mr.y + header_h),
                         (mr.right - pad, mr.y + header_h), 1)

        # Game option rows
        self._gc_skill_modal_rects = []
        mp = pygame.mouse.get_pos()
        for j, game_name in enumerate(games):
            gr = pygame.Rect(mr.x + pad,
                             mr.y + header_h + j * item_h + int(8*H/1080),
                             mw - pad * 2, item_h - int(8*H/1080))
            is_cur = (self.gc.get("selected_game") or (None,))[0] == game_name
            hov    = gr.collidepoint(mp)
            if is_cur:
                pygame.draw.rect(surface, (210, 235, 255), gr, border_radius=10)
                pygame.draw.rect(surface, (60, 140, 220), gr, 2, border_radius=10)
            elif hov:
                pygame.draw.rect(surface, (228, 242, 255), gr, border_radius=10)
            else:
                pygame.draw.rect(surface, (238, 244, 252), gr, border_radius=10)
                pygame.draw.rect(surface, (200, 215, 235), gr, 1, border_radius=10)
            g_col = (35, 110, 200) if is_cur else (40, 55, 80)
            gs    = self.fnt["body_b"].render(game_name, True, g_col)
            surface.blit(gs, gs.get_rect(midleft=(gr.x + int(16*W/1920), gr.centery)))
            self._gc_skill_modal_rects.append((gr, game_name))

        # Close / Cancel button
        close_r = pygame.Rect(mr.centerx - int(70*W/1920),
                              mr.bottom - close_h + int(8*H/1080),
                              int(140*W/1920), int(38*H/1080))
        self._gc_skill_modal_close = close_r
        close_hov = close_r.collidepoint(mp)
        close_col = (145, 158, 178) if not close_hov else (118, 130, 150)
        pygame.draw.rect(surface, close_col, close_r, border_radius=10)
        cls = self.fnt["btn"].render("Cancel", True, (255, 255, 255))
        surface.blit(cls, cls.get_rect(center=close_r.center))

    def _draw_register_success_modal(self, surface):
        W, H = self.WIDTH, self.HEIGHT
        mw = int(W * 0.40); mh = int(H * 0.30)
        mx = (W - mw) // 2;  my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((245, 252, 248, 255))
        surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200))
        surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (80, 190, 120), mr, 2, border_radius=16)

        # Checkmark circle
        pygame.draw.circle(surface, (60, 185, 100), (mr.centerx, my + int(52*H/1080)), int(22*H/1080))
        ck = self.fnt["sym29"].render("✓", True, (255, 255, 255))
        surface.blit(ck, ck.get_rect(center=(mr.centerx, my + int(52*H/1080))))

        # Title
        ts = self.fnt["modal_lbl"].render("Registration Successful", True, (30, 120, 65))
        surface.blit(ts, ts.get_rect(center=(mr.centerx, my + int(95*H/1080))))

        # Message lines (split on \n)
        lines = self._rp_success_msg.split("\n")
        for i, line in enumerate(lines):
            ls = self.fnt["body"].render(line, True, (45, 65, 85))
            surface.blit(ls, ls.get_rect(center=(mr.centerx, my + int(130*H/1080) + i * int(32*H/1080))))

        # OK button
        bw = int(120*W/1920); bh = int(40*H/1080)
        ok_r = pygame.Rect(mr.centerx - bw // 2, mr.bottom - int(58*H/1080), bw, bh)
        self._rp_ok_rect = ok_r
        ok_col = (40, 160, 90) if not self._rp_ok_hov else (28, 130, 68)
        pygame.draw.rect(surface, ok_col, ok_r, border_radius=10)
        oks = self.fnt["btn"].render("OK", True, (255, 255, 255))
        surface.blit(oks, oks.get_rect(center=ok_r.center))

    def _draw_calibration_mismatch_modal(self, surface):
        W, H  = self.WIDTH, self.HEIGHT
        mw    = int(W * 0.46)
        mh    = int(H * 0.38)
        mx    = (W - mw) // 2
        my    = (H - mh) // 2
        mr    = pygame.Rect(mx, my, mw, mh)

        # background
        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((255, 248, 235, 255))
        surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200))
        surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (220, 145, 30), mr, 2, border_radius=16)

        # warning icon circle
        ic_cx = mr.centerx
        ic_cy = my + int(44 * H / 1080)
        pygame.draw.circle(surface, (240, 165, 30), (ic_cx, ic_cy), int(22 * H / 1080))
        ws = self.fnt["body_b"].render("!", True, (255, 255, 255))
        surface.blit(ws, ws.get_rect(center=(ic_cx, ic_cy)))

        # title
        ts = self.fnt["modal_head"].render("Sensor Mismatch", True, (160, 100, 10))
        surface.blit(ts, ts.get_rect(center=(mr.centerx, my + int(86 * H / 1080))))

        # retrieve types
        res       = self.calibration_result or {}
        cal_type  = res.get("game_type", "—")
        cal_sens  = res.get("sensor",    "—")
        need_type = (self.gc.get("selected_game") or (None, "—"))[1] or "—"
        SENSOR_FOR = {"Grip Strength":  "Force Sensor",
                      "Finger Flexion": "Flex Sensors",
                      "Wrist Rotation": "Motion Sensor"}
        need_sens  = SENSOR_FOR.get(need_type, "—")

        # body lines
        body_lines = [
            "The sensor calibration on file does not match the",
            "selected exercise type. Please recalibrate.",
            "",
            f"Calibrated for :  {cal_type}",
            f"                         ({cal_sens})",
            f"Required for   :  {need_type}",
            f"                         ({need_sens})",
        ]
        for k, line in enumerate(body_lines):
            col = (90, 65, 20) if line.startswith("Calibrated") or line.startswith("Required") else (75, 85, 105)
            ls  = self.fnt["modal_lbl"].render(line, True, col)
            surface.blit(ls, ls.get_rect(
                center=(mr.centerx, my + int(130 * H / 1080) + k * int(28 * H / 1080))))

        # buttons
        bw   = int(178 * W / 1920)
        bh   = int(44  * H / 1080)
        gap  = int(16  * W / 1920)
        by2  = mr.bottom - int(60 * H / 1080)

        cal_r = pygame.Rect(mr.centerx - bw - gap // 2, by2, bw, bh)
        can_r = pygame.Rect(mr.centerx + gap // 2,       by2, bw, bh)

        cal_col = (180, 110, 10) if self._mismatch_cal_hov    else (220, 145, 30)
        can_col = (148, 162, 180) if self._mismatch_cancel_hov else (175, 190, 210)

        pygame.draw.rect(surface, cal_col, cal_r, border_radius=10)
        pygame.draw.rect(surface, can_col, can_r, border_radius=10)

        surface.blit(self.fnt["btn"].render("Calibrate Now", True, (255, 255, 255)),
                     self.fnt["btn"].render("Calibrate Now", True, (255, 255, 255))
                     .get_rect(center=cal_r.center))
        surface.blit(self.fnt["btn"].render("Cancel",        True, (255, 255, 255)),
                     self.fnt["btn"].render("Cancel",        True, (255, 255, 255))
                     .get_rect(center=can_r.center))

        self._mismatch_cal_rect    = cal_r
        self._mismatch_cancel_rect = can_r

    def _draw_confirm_modal(self, surface):
        W,H=self.WIDTH,self.HEIGHT
        mw,mh=int(W*0.36),int(H*0.28); mx,my=(W-mw)//2,(H-mh)//2
        mr=pygame.Rect(mx,my,mw,mh)
        ms=pygame.Surface((mw,mh),pygame.SRCALPHA); ms.fill((250,252,255,255))
        surface.blit(ms,mr.topleft)
        pygame.draw.rect(surface,(195,210,228),mr,1,border_radius=14)
        is_logout  = (self.modal == "logout_confirm")
        is_del_pt  = (self.modal == "delete_patient_confirm")
        pt_name    = (self._ep_patient or {}).get("full_name", "this patient") if is_del_pt else ""
        title = ("Log out of RecovR?"         if is_logout else
                 f"Delete {pt_name}?"         if is_del_pt else
                 "Delete your account?")
        body  = ("You will be returned to the login screen." if is_logout
                 else "This action cannot be undone.")
        yes_l = "Logout" if is_logout else "Delete"
        ts=self.fnt["modal_head"].render(title,True,(38,52,78))
        bs=self.fnt["modal_lbl"].render(body,True,(98,114,140))
        surface.blit(ts,ts.get_rect(center=(mr.centerx,my+int(52*H/1080))))
        surface.blit(bs,bs.get_rect(center=(mr.centerx,my+int(90*H/1080))))
        yr,nr=self._confirm_rects()
        yc=(175,25,25) if self.confirm_yes_hov else (205,45,45)
        nc=(148,162,180) if self.confirm_no_hov else (175,190,210)
        pygame.draw.rect(surface,yc,yr,border_radius=10)
        pygame.draw.rect(surface,nc,nr,border_radius=10)
        ys=self.fnt["btn"].render(yes_l,True,(255,255,255))
        ns=self.fnt["btn"].render("Cancel",True,(255,255,255))
        surface.blit(ys,ys.get_rect(center=yr.center))
        surface.blit(ns,ns.get_rect(center=nr.center))

    # ──────────────────────────────────────────────────────────────────
    #  UTILITIES
    # ──────────────────────────────────────────────────────────────────

    def _confirm_rects(self):
        W,H=self.WIDTH,self.HEIGHT
        bw=int(115*W/1920); bh=int(42*H/1080); gap=int(12*W/1920)
        cy=H//2+int(30*H/1080)
        return (pygame.Rect(W//2-bw-gap//2,cy,bw,bh),
                pygame.Rect(W//2+gap//2,cy,bw,bh))

    def _logout_rect(self):
        lw=int(self.WIDTH*0.11); lh=int(self.HEIGHT*0.046)
        lx=(self.sidebar_w-lw)//2; ly=self.HEIGHT-lh-int(20*self.HEIGHT/1080)
        return pygame.Rect(lx,ly,lw,lh)

    def _gradient(self, width, height):
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