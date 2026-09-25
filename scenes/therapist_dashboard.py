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
from audio import play_confirm_alert, play_start_session, play_click
from sensors.input_handler import input_handler
try:
    from sensors.ble_receiver import ble_receiver as _ble_receiver
except Exception:
    _ble_receiver = None

# ── Dual-monitor mode (opt-in via recovr/launch_production.py) ────────────
# When RECOVR_DUAL_MONITOR=1, "Start Session" hands the game to the patient
# window (a separate process on the other monitor) instead of switching this
# window to the game scene, and this dashboard stays live showing a small
# session-monitoring panel with Pause/Resume/Stop. Everything below is inert
# and this file behaves exactly as before when the flag is unset.
_DUAL_MONITOR = os.environ.get("RECOVR_DUAL_MONITOR") == "1"
if _DUAL_MONITOR:
    try:
        from recovr.therapist_link import therapist_link
        from recovr.shared import commands as _rc_cmd
    except Exception as _exc:               # pragma: no cover - defensive
        print(f"[recovr] dual-monitor link unavailable ({_exc}); staying single-window")
        _DUAL_MONITOR = False

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
    7: "Session in Progress",
    8: "Patient",
}

PANEL_COLORS = {
    0: (100, 180, 240),
    1: (240, 170,  90),
    2: (190, 130, 220),
    3: (235, 100, 120),
    4: ( 80, 195, 195),
    5: ( 60, 140, 220),
    6: (130, 200, 140),
    7: ( 60, 140, 220),
    8: (150, 130, 220),
}

# Sidebar navigation is now EMPTY. The Patient List is the Therapist Dashboard
# itself (panel 0, shown on load); Session History / Analytics / Calibration
# Records moved into the Patient Preview panel. Panels 0-3 draw methods are
# unchanged and still reachable code. Navigation back to the Patient List is via
# the standard Back buttons on each sub-panel.
SIDEBAR_NAV = []

ROLES = [
    "Physical Therapist",
    "Occupational Therapist",
    "Rehabilitation Specialist",
    "Neurological Rehab Therapist",
    "Other",
]

STROKE_TYPES  = ["Ischemic", "Hemorrhagic", "Unknown / Not Specified"]
SEX_OPTS      = ["Male", "Female"]
HAND_OPTS     = ["Left", "Right"]
GAME_DURATION = ["60 seconds", "120 seconds", "180 seconds"]   # no custom/specific-time entry

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
    "Wrist Rotation": ["Apple Catching", "Gravity Catch",
                       "Key and Lock", "Steady Aim"],
    "Dual Skill":     ["Catch the Falling Object"],
}

DIFFICULTY_OPTS = ["Easy", "Medium", "Hard", "Custom"]
SMART_PRESETS   = {
    "Mild":     {"duration": "60 seconds", "speed": "Normal", "sensitivity": "Medium", "difficulty": "Medium"},
    "Moderate": {"duration": "60 seconds", "speed": "Normal", "sensitivity": "Medium", "difficulty": "Easy"},
}


# ─────────────────────────────────────────────────────────────────────
#  DRAW HELPERS
# ─────────────────────────────────────────────────────────────────────

def _card_bg(surface, rect, alpha=200, radius=14,
             border_col=(200, 218, 240), border_w=1):
    bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(bg, (232, 242, 255, alpha),
                     (0, 0, rect.width, rect.height), border_radius=radius)
    surface.blit(bg, rect.topleft)
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


_IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "images")
_img_cache: dict = {}


def _img(name, size=None):
    """A square illustration from assets/images/, uniformly scaled to
    `size x size` and cached. Returns None (silently) if the file is
    missing, so a missing asset degrades gracefully instead of crashing."""
    key = (name, size)
    im = _img_cache.get(key)
    if im is None and key not in _img_cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            im = pygame.transform.smoothscale(raw, (size, size)) if size else raw
        except Exception:
            im = None
        _img_cache[key] = im
    return im


_img_bbox_cache: dict = {}
_img_fit_cache: dict = {}


def _img_fit(name, w, h):
    """Like _img(), but for assets that bake extra transparent padding into
    a square canvas (e.g. a wide pill-shaped button centered in a 3375x3375
    file) -- crops to the actual opaque content once, then scales it to fit
    within w x h preserving its own aspect ratio (never stretched into an
    oval/squished pill), centered by the caller via get_rect(center=...)."""
    key = (name, w, h)
    if key in _img_fit_cache:
        return _img_fit_cache[key]
    cropped = _img_bbox_cache.get(name)
    if cropped is None and name not in _img_bbox_cache:
        try:
            raw = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
            cropped = raw.subsurface(raw.get_bounding_rect(min_alpha=10)).copy()
        except Exception:
            cropped = None
        _img_bbox_cache[name] = cropped
    if cropped is None:
        _img_fit_cache[key] = None
        return None
    cw, ch = cropped.get_size()
    scale = min(w / cw, h / ch)
    result = pygame.transform.smoothscale(cropped, (max(1, int(cw * scale)), max(1, int(ch * scale))))
    _img_fit_cache[key] = result
    return result


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

        # ── Touch / small-display mode ───────────────────────────────
        # The therapist dashboard also runs on a ~7-inch LCD touchscreen. On a
        # short display we scale UI up (larger fonts) and enforce minimum tap
        # target sizes, and the Patient List becomes scrollable. Desktop /
        # large-monitor layout is unchanged.
        H = height
        self._touch_ui = (H <= 820) or (os.environ.get("RECOVR_THERAPIST_TOUCH") == "1")
        # font scale factor: normal = H/1080; on the 7-inch panel we scale text
        # up relative to the screen so it reads from a distance and every tap
        # target clears ~48px.
        #   reference is H/512 -> 800x480 panel gives _fs = 0.9375 (27px body
        #   -> 25px). A plain H/1080 would give 0.44 here, i.e. 12px body text
        #   on a physically SMALLER screen. The 1.32 cap only bites above
        #   H=676, which no therapist panel reaches.
        _fs = min(H / 512.0, 1.32) if self._touch_ui else (H / 1080.0)
        self._fs = _fs
        # Narrow panel (the 800px-wide LCD): abbreviate labels that would
        # otherwise overrun a row. Checked wherever a row must fit several
        # controls side by side.
        self._narrow = width <= 900

        # ── Font dictionary (all fonts scaled by _fs) ──
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(name): return os.path.join(_fd, name)
        self.fnt = {
            "logo":        pygame.font.SysFont("arialblack",                 int((36 if self._touch_ui else 51)*_fs)),
            "nav":         pygame.font.Font(_F("Lexend-Medium.ttf"),         int(27*_fs)),
            "nav_sym":     pygame.font.SysFont("segoeuisymbol",              int(35*_fs)),
            "welcome":     pygame.font.Font(_F("Sora-Light.ttf"),            int(33*_fs)),
            "dash_title":  pygame.font.Font(_F("GravitasOne-Regular.ttf"),   int(60*_fs)),
            "panel_title": pygame.font.Font(_F("FjallaOne-Regular.ttf"),     int(36*_fs)),
            "body":        pygame.font.Font(_F("Lexend-Regular.ttf"),        int(27*_fs)),
            "body_b":      pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(27*_fs)),
            "small":       pygame.font.Font(_F("Lexend-Light.ttf"),          int(25*_fs)),
            "small_i":     pygame.font.Font(_F("Sora-ExtraLight.ttf"),       int(25*_fs)),
            "label":       pygame.font.Font(_F("Lexend-Regular.ttf"),        int(25*_fs)),
            "input":       pygame.font.Font(_F("Lexend-Regular.ttf"),        int(25*_fs)),
            "btn":         pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(27*_fs)),
            "btn_lg":      pygame.font.Font(_F("Lexend-Bold.ttf"),           int(30*_fs)),
            "profile_nm":  pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(24*_fs)),
            "profile":     pygame.font.Font(_F("Lexend-Light.ttf"),          int(22*_fs)),
            "card_lbl":    pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(25*_fs)),
            "card_sym":    pygame.font.SysFont("segoeuisymbol",              int(51*_fs)),
            "modal_head":  pygame.font.Font(_F("FjallaOne-Regular.ttf"),     int(42*_fs)),
            "modal_lbl":   pygame.font.Font(_F("Lexend-Medium.ttf"),         int(27*_fs)),
            "modal_inp":   pygame.font.Font(_F("Lexend-Regular.ttf"),        int(27*_fs)),
            "modal_err":   pygame.font.Font(_F("Lexend-Light.ttf"),          int(23*_fs)),
            "empty_head":  pygame.font.Font(_F("Sora-SemiBold.ttf"),         int(33*_fs)),
            "section":     pygame.font.Font(_F("Lexend-SemiBold.ttf"),       int(24*_fs)),
            "tag":         pygame.font.Font(_F("Lexend-Medium.ttf"),         int(22*_fs)),
            "time":        pygame.font.Font(_F("ZenDots-Regular.ttf"),       int(19*_fs)),
            "header_date": pygame.font.Font(_F("Lexend-Light.ttf"),          int(16*_fs)),
            "breadcrumb":  pygame.font.Font(_F("Lexend-Light.ttf"),          int(24*_fs)),
            "sym26":       pygame.font.SysFont("segoeuisymbol",              int(26*_fs)),
            "sym29":       pygame.font.SysFont("segoeuisymbol",              int(29*_fs)),
        }

        # Patient List scroll offset (touch: list scrolls instead of shrinking).
        self._pl_scroll     = 0
        self._pl_scroll_max  = 0
        self._pl_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._pl_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._pl_drag_y     = None

        # Session History (panel 1) scroll -- was a silent truncation before.
        self._sh_scroll     = 0
        self._sh_scroll_max = 0
        self._sh_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._sh_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._sh_drag_y     = None

        # Analytics (panel 2) scroll -- one section per game, was truncated.
        self._an_scroll     = 0
        self._an_scroll_max = 0
        self._an_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._an_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._an_drag_y     = None

        # Calibration Records (panel 3) scroll -- was truncated via max_rows.
        self._cr_scroll     = 0
        self._cr_scroll_max = 0
        self._cr_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._cr_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._cr_drag_y     = None

        # Create gradient background surface for visual depth
        self.background_surface = self._gradient(width, height)
        # Sidebar width: 20% desktop; narrower on the 7-inch panel (the nav list
        # was removed, so it only carries the profile + logout now).
        self.sidebar_w = int(width * (0.23 if self._touch_ui else 0.20))

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
        self._crumb_rects      = []                       # [(Rect, target)] clickable breadcrumbs

        # ── Modal state ──
        self.modal           = None            # Current modal: "edit_profile", "logout_confirm", "delete_confirm", "register_success", None
        self.confirm_yes_hov = False           # Is "Yes" button hovered in confirmation modal?
        self.confirm_no_hov  = False           # Is "No" button hovered in confirmation modal?
        self._rp_success_msg = ""              # Text shown in register success popup
        self._rp_ok_rect     = pygame.Rect(0, 0, 1, 1)
        self._rp_ok_hov      = False

        # ── Patient selection state ──
        self.selected_patient = None           # Patient chosen (via SELECT + confirm) for this session
        self.patients         = []             # List of patients belonging to/shared with this therapist

        # ── Patient page (panel 8) state ──
        # preview_patient is the patient whose page is open -- opening it must NOT
        # select them. Its tabs reuse the per-patient Analytics / Calibration /
        # Session History panels via _view_patient(); Info shows every DB field.
        self.preview_patient          = None
        self._pv_tab                  = "info"     # info | analytics | calibration | history
        self._pv_tab_rects            = {}
        self._pv_select_rect          = pygame.Rect(0, 0, 1, 1)
        self._pv_edit_rect            = pygame.Rect(0, 0, 1, 1)   # legacy, now unused
        self._pv_sec_edit_rects       = {}     # {section_key: Rect} per-group Edit buttons
        self._pv_info_scroll          = 0
        self._pv_info_scroll_max      = 0
        self._pv_info_up_rect         = pygame.Rect(0, 0, 1, 1)
        self._pv_info_down_rect       = pygame.Rect(0, 0, 1, 1)
        self._rp_scroll               = 0          # Register Patient (touch) form scroll offset
        self._rp_scroll_max           = 0
        self._rp_drag_y               = None
        self._rp_up_rect              = pygame.Rect(0, 0, 1, 1)
        self._rp_down_rect            = pygame.Rect(0, 0, 1, 1)
        self._pending_select_patient  = None       # patient awaiting the SELECT confirm dialog
        self._pending_deselect_patient = None      # patient awaiting the DESELECT confirm dialog

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
        self._ep_section      = None   # which Info group the edit modal is scoped to
        self._db_blocked_ok_rect = pygame.Rect(0, 0, 1, 1)   # "delete_blocked" dismiss

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
        self._share_confirm_therapist = None       # therapist chosen from suggestions, pending confirm/choice
        # Stage machine for the modal: "pick" (typing/suggestions) ->
        # "choice" (SHARE or TRANSFER?) -> "confirm" (final Yes/Cancel, worded
        # for whichever action was chosen). Ownership does NOT change on Share;
        # it DOES change on Transfer -- see _do_share_or_transfer().
        self._share_stage            = "pick"
        self._share_pending_action   = None        # "share" | "transfer", set entering "confirm"
        self._share_choice_share_rect    = pygame.Rect(0, 0, 1, 1)
        self._share_choice_transfer_rect = pygame.Rect(0, 0, 1, 1)
        self._share_choice_share_hov     = False
        self._share_choice_transfer_hov  = False
        self._share_yes_rect         = pygame.Rect(0, 0, 1, 1)
        self._share_no_rect          = pygame.Rect(0, 0, 1, 1)
        self._share_yes_hov          = False
        self._share_no_hov           = False
        self._unshare_rects          = []

        # ── Edit profile modal state ──
        # Dedicated icon-picker popup (opened from the big preview / "Change
        # Icon" prompt inside Edit Profile) -- large, scrollable grid of all
        # 10 icons instead of the old cramped always-visible rail.
        self.edit_icon_picker_open = False
        self._eip_scroll     = 0
        self._eip_scroll_max = 0
        self._eip_drag_y     = None
        self._eip_up_rect    = pygame.Rect(0, 0, 1, 1)
        self._eip_down_rect  = pygame.Rect(0, 0, 1, 1)
        self._eip_done_rect  = pygame.Rect(0, 0, 1, 1)
        self._eip_circles    = []       # [(cx, cy, idx)] -- recomputed each draw (scroll-dependent)
        self._eip_r          = 0        # current icon radius in the popup (recomputed each draw)
        self.edit_change_icon_rect = pygame.Rect(0, 0, 1, 1)
        self._init_edit_fields()

        # ── Build layout rectangles ──
        self._build_nav_rects()                # Calculate positions for sidebar nav items
        self._build_card_rects()               # Calculate positions for 4 home cards

        # ── Page transition animation ──
        self.alpha        = 0                  # Current alpha for fade-in effect (0-255)
        self.fade_surface = pygame.Surface((width, height))  # White surface for fade transition
        self.fade_surface.fill((255, 255, 255))
        self.action_triggered = False          # Flag to trigger next scene transition

        # ── Dual-monitor "Session in Progress" (panel 7) state ──
        self._sm_state    = {}                 # latest broker snapshot
        self._sm_result   = None               # captured result on COMPLETE
        self._sm_btn_rects = {}                # {key: (Rect, enabled)} for the controls
        self._sm_started_ms = 0                # pygame ticks when "Start Session" was pressed
        self._sm_start_lock_ms = 5000          # START held for this long -> BLE handoff window
        self._ble_want    = None               # last enable/disable pushed to the BLE receiver
        self._sm_hover    = None
        self._sm_volume   = None               # music volume (lazy-init from broker state)
        self._sm_stop_rect = pygame.Rect(0, 0, 1, 1)   # emergency STOP (lower-right)
        self._sm_stopped_notice = False        # "Game Stopped" screen shown on panel 7
        self._sm_notice_continue_rect = pygame.Rect(0, 0, 1, 1)
        self._sm_notice_back_rect     = pygame.Rect(0, 0, 1, 1)
        # Light/dark theme -- one shared state (constants.get_theme()). Toggled
        # from the sidebar control; synchronised to the patient monitor.
        try:
            from constants import is_dark_mode as _is_dark
            self._applied_theme_dark = bool(_is_dark())
        except Exception:
            self._applied_theme_dark = True
        self._theme_btn_rect = pygame.Rect(0, 0, 1, 1)
        # Close (X) button -- main.py reads this each frame instead of a
        # fixed screen-corner rect, so it can sit beside the Light/Dark
        # toggle in the header row. Falls back to its own fixed corner rect
        # on scenes that never populate this (login, welcome, games).
        self._close_btn_rect = pygame.Rect(0, 0, 1, 1)
        self._ctrl_btn_rect  = pygame.Rect(0, 0, 1, 1)   # ESP32 status block (tap = rescan)
        self._ctrl_hov       = False
        self._theme_hov      = False
        if _DUAL_MONITOR:
            therapist_link.start()
            therapist_link.set_present(True)     # a therapist is logged in
            therapist_link.set_dark_mode(self._applied_theme_dark)   # start in sync

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

        if _DUAL_MONITOR:
            # Push the current selection to shared state so the patient monitor
            # shows its Dashboard only when a patient is actually selected
            # (fresh login -> none -> patient stays on the Waiting Screen).
            self._push_selected_patient()

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
            "sex",              # Patient's sex (Male/Female) -- required
            "dominant_hand",    # Dominant hand (Left/Right)
            "affected_hand",    # Hand affected by stroke (Left/Right)
            "stroke_type",      # Type of stroke (Ischemic/Hemorrhagic/Unknown)
            "date_of_stroke",   # Date stroke occurred
            "months_stroke",    # Months since stroke
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
            "difficulty": "Medium",         # Difficulty level (Easy/Medium/Hard/Custom)
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
        # Top edge: below the header band (breadcrumb + Back live here).
        # On touch, the breadcrumb floats ABOVE this by (hdr_h + gap), so it
        # must clear the top-right clock/theme bar too, not just this rect.
        if self._touch_ui:
            bar_bottom = self._bar_top() + self._bar_height()
            hdr_h = max(int(50*(self.HEIGHT/1080)), self._tt(46))
            my = bar_bottom + self._sc(8) + hdr_h + int(10*self.HEIGHT/1080)
        else:
            my = int(self.HEIGHT * 0.15)
        # Width: full screen - sidebar - margins
        mw = self.WIDTH - mx - int(24*(self.WIDTH/1920))
        # Height: screen - top - bottom margins
        mh = self.HEIGHT - my - int(16*(self.HEIGHT/1080))
        return pygame.Rect(mx, my, mw, mh)

    def _bar_top(self):
        """Y where the top-right clock/theme/close bar (and, on touch,
        Patient List's own header row) starts. The close (X) button used to
        float above this row at a fixed screen position, so this returned
        room to clear it; now main.py reads the close button's rect FROM
        this bar (see _draw_top_right_bar), so it's just a plain top margin.
        Single source of truth so the bar, Patient List's header and
        _panel_area()'s margin can't drift apart from one another."""
        return self._sc(12)

    def _bar_height(self):
        """Tallest control _draw_top_right_bar draws -- the calendar/time
        pill, the Light/Dark toggle and the close button all share this same
        container height. _panel_area() uses this -- instead of a guess --
        to keep every other panel's header clear of this bar."""
        return self._sc(40)

    def _tt(self, px):
        """Touch-target size for an INTERACTIVE control: a 1080-referenced px,
        never below ~50px on the 7-inch panel so a fingertip clears it."""
        v = int(px * self._fs)
        if self._touch_ui:
            v = max(v, 50)
        return v

    def _sc(self, px):
        """Plain scaled size for a NON-interactive element (dot, row height,
        spacing) -- no tap-target floor."""
        return max(1, int(px * self._fs))

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE MODAL — Manages therapist profile editing interface
    # ──────────────────────────────────────────────────────────────────

    def _init_edit_fields(self):
        """Therapist profile editor. Sized from _fs/_tt so the controls stay
        finger-sized on the 800x480 panel.

        NOTE: there is deliberately no "New PIN" field. Changing a PIN goes
        through the forgot-PIN flow on the Login page and nowhere else."""
        W, H  = self.WIDTH, self.HEIGHT
        pad   = self._sc(18)
        fh    = self._tt(46)
        lbl_h = self.fnt["small"].get_height()
        # 2x2 field grid (not a single stacked column): 4 fields each floored at
        # a 50px touch target do not fit above the button row when stacked on a
        # 480px-tall screen even after the modal cap below. A 2-column grid
        # needs half the rows and fits with headroom to spare.
        row_h  = lbl_h + self._sc(4) + fh
        colgap = self._sc(14)
        rowgap = self._sc(14)
        btn_h = self._tt(46)
        icon_col_w = self._sc(170)   # wide enough for the big preview + "Change Icon"

        modal_w = min(int(W * 0.88), self._sc(720))
        modal_h = min(int(H * 0.94),
                      self.fnt["panel_title"].get_height() + self._sc(14)
                      + 2 * row_h + rowgap + btn_h + pad * 3)
        modal_x = (W - modal_w) // 2
        modal_y = (H - modal_h) // 2

        fx0 = modal_x + pad + icon_col_w
        fw  = (modal_w - pad * 2 - icon_col_w - colgap) // 2
        fy0 = modal_y + self.fnt["panel_title"].get_height() + self._sc(20) + lbl_h + self._sc(4)

        self.edit_modal_rect = pygame.Rect(modal_x, modal_y, modal_w, modal_h)
        _specs = [
            ("full_name", "Full Name",  self.account.get("full_name",""),  50, "Full name"),
            ("username",  "Username",   self.account.get("username",""),   15, "Letters only, max 15"),
            ("role",      "Role",       self.account.get("role",""),        0, "Select role"),
            ("workplace", "Workplace",  self.account.get("workplace", self.account.get("clinic","")),
                                                                            60, "Workplace name"),
        ]
        self.edit_fields = []
        for i, (key, label, value, max_len, placeholder) in enumerate(_specs):
            col, row = i % 2, i // 2
            fx = fx0 + col * (fw + colgap)
            fy = fy0 + row * (row_h + rowgap)
            self.edit_fields.append({
                "key": key, "label": label, "value": value,
                "is_pin": False, "max_len": max_len, "placeholder": placeholder,
                "rect": pygame.Rect(fx, fy, fw, fh),
            })

        btn_y = modal_y + modal_h - btn_h - pad          # computed early for the icon budget below

        # Icon column: just the big preview + a "Change Icon" prompt. Picking
        # an icon now opens a dedicated, larger, SCROLLABLE picker popup
        # (_draw_icon_picker_popup) instead of cramming all 10 choices into
        # this narrow rail at a shrunk size -- see _open_icon_picker().
        icon_cx  = modal_x + pad + icon_col_w // 2
        avail_h  = btn_y - fy0 - self._sc(6)
        self.edit_big_r      = max(self._sc(30), min(int(avail_h * 0.34), self._sc(56)))
        self.edit_big_center = (icon_cx, fy0 + self.edit_big_r)
        chg_h = self._tt(40)
        chg_y = min(self.edit_big_center[1] + self.edit_big_r + self._sc(10),
                    btn_y - chg_h)
        chg_margin = self._sc(6)
        self.edit_change_icon_rect = pygame.Rect(
            modal_x + pad - chg_margin, chg_y, icon_col_w - 2 * pad + 2 * chg_margin, chg_h)
        # Kept for backward compatibility with any external reference; the
        # inline small-icon rail itself is gone (replaced by the picker popup).
        self.edit_small_r       = 0
        self.edit_small_circles = []

        self.edit_selected_icon = self.account.get("icon_index", 1)
        self.edit_active_field  = -1
        self.edit_error         = ""
        self.edit_role_open     = False

        role_rect = self.edit_fields[2]["rect"]
        opt_h     = self._tt(42)
        self.edit_role_options = [
            {"label": r,
             "rect": pygame.Rect(role_rect.x, role_rect.bottom+i*opt_h, fw, opt_h)}
            for i, r in enumerate(ROLES)
        ]

        btn_y = modal_y + modal_h - btn_h - pad
        bw2   = self._sc(120)
        dw2   = self.fnt["small"].size("Delete Account")[0] + self._sc(24)
        self.edit_save_rect   = pygame.Rect(modal_x+modal_w-pad-bw2,              btn_y, bw2, btn_h)
        self.edit_cancel_rect = pygame.Rect(self.edit_save_rect.x-self._sc(10)-bw2, btn_y, bw2, btn_h)
        self.edit_delete_rect = pygame.Rect(modal_x+pad,                          btn_y, dw2, btn_h)
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

        # ── "Session in Progress" screen (panel 7) owns all input ────
        if self.active_panel == 7:
            if event.type == pygame.FINGERDOWN:
                self._sm_handle_click((int(event.x * self.WIDTH), int(event.y * self.HEIGHT)))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                import builtins as _bi2
                _norm = getattr(_bi2, 'normalise_pos', lambda p: p)
                self._sm_handle_click(_norm(event.pos))
            return None

        # ── Calibration window intercepts all events when active ──────
        if self._cal_win is not None:
            self._cal_win.handle_event(event)
            return None

        # ── Patient List scrolling (wheel + touch drag) ──────────────
        if self.active_panel == 0:
            if event.type == pygame.MOUSEWHEEL:
                step = int(60 * self._fs)
                self._pl_scroll = max(0, min(self._pl_scroll - event.y * step,
                                             self._pl_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._pl_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._pl_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._pl_scroll = max(0, min(self._pl_scroll + (self._pl_drag_y - cy),
                                             self._pl_scroll_max))
                self._pl_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._pl_drag_y = None

        # ── Session History scrolling (wheel + touch drag) ───────────
        if self.active_panel == 1:
            if event.type == pygame.MOUSEWHEEL:
                self._sh_scroll = max(0, min(self._sh_scroll - event.y * int(60 * self._fs),
                                             self._sh_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._sh_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._sh_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._sh_scroll = max(0, min(self._sh_scroll + (self._sh_drag_y - cy),
                                             self._sh_scroll_max))
                self._sh_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._sh_drag_y = None

        # ── Analytics scrolling (wheel + touch drag) ─────────────────
        if self.active_panel == 2:
            if event.type == pygame.MOUSEWHEEL:
                self._an_scroll = max(0, min(self._an_scroll - event.y * int(60 * self._fs),
                                             self._an_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._an_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._an_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._an_scroll = max(0, min(self._an_scroll + (self._an_drag_y - cy),
                                             self._an_scroll_max))
                self._an_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._an_drag_y = None

        # ── Calibration Records scrolling (wheel + touch drag) ───────
        if self.active_panel == 3:
            if event.type == pygame.MOUSEWHEEL:
                self._cr_scroll = max(0, min(self._cr_scroll - event.y * int(60 * self._fs),
                                             self._cr_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._cr_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._cr_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._cr_scroll = max(0, min(self._cr_scroll + (self._cr_drag_y - cy),
                                             self._cr_scroll_max))
                self._cr_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._cr_drag_y = None

        # ── Patient page Info tab: scroll the field list ────────────
        if self.active_panel == 8 and self._pv_tab == "info":
            if event.type == pygame.MOUSEWHEEL:
                self._pv_info_scroll = max(0, min(
                    self._pv_info_scroll - event.y * int(60 * self._fs),
                    self._pv_info_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._pv_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and getattr(self, "_pv_drag_y", None) is not None:
                cy = event.y * self.HEIGHT
                self._pv_info_scroll = max(0, min(
                    self._pv_info_scroll + (self._pv_drag_y - cy), self._pv_info_scroll_max))
                self._pv_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._pv_drag_y = None

        # ── Register Patient (touch): scroll the form ───────────────
        if self.active_panel == 6 and self._touch_ui:
            if event.type == pygame.MOUSEWHEEL:
                self._rp_scroll = max(0, min(
                    self._rp_scroll - event.y * int(60 * self._fs),
                    self._rp_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._rp_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._rp_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._rp_scroll = max(0, min(
                    self._rp_scroll + (self._rp_drag_y - cy), self._rp_scroll_max))
                self._rp_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._rp_drag_y = None

        # ── Edit Profile: icon-picker popup scroll (wheel + finger drag) ──
        if self.modal == "edit_profile" and self.edit_icon_picker_open:
            if event.type == pygame.MOUSEWHEEL:
                self._eip_scroll = max(0, min(
                    self._eip_scroll - event.y * int(60 * self._fs), self._eip_scroll_max))
                return None
            if event.type == pygame.FINGERDOWN:
                self._eip_drag_y = event.y * self.HEIGHT
            elif event.type == pygame.FINGERMOTION and self._eip_drag_y is not None:
                cy = event.y * self.HEIGHT
                self._eip_scroll = max(0, min(
                    self._eip_scroll + (self._eip_drag_y - cy), self._eip_scroll_max))
                self._eip_drag_y = cy
                return None
            elif event.type == pygame.FINGERUP:
                self._eip_drag_y = None

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
                if self.edit_icon_picker_open:
                    if event.key == pygame.K_ESCAPE:
                        self.edit_icon_picker_open = False
                    return None
                return self._handle_edit_key(event)
            # Patient search field
            if self.active_panel == 0 and self._pt_search_active:
                if event.key == pygame.K_BACKSPACE:
                    self._pt_search_text = self._pt_search_text[:-1]
                elif event.unicode and len(self._pt_search_text) < 40:
                    self._pt_search_text += event.unicode
                return None
            # Game config custom duration input
            if self.active_panel == 4 and self._gc_custom_dur_active:
                if event.key == pygame.K_BACKSPACE:
                    self._gc_custom_dur = self._gc_custom_dur[:-1]
                elif event.key == pygame.K_RETURN:
                    self._gc_custom_dur_active = False
                elif event.unicode.isdigit() and len(self._gc_custom_dur) < 4:
                    self._gc_custom_dur += event.unicode
                return None
            # Session Details custom duration input (panel 5)
            if self.active_panel == 5 and self._ss_custom_dur_active:
                if event.key == pygame.K_BACKSPACE:
                    self._gc_custom_dur = self._gc_custom_dur[:-1]
                elif event.key == pygame.K_RETURN:
                    self._ss_custom_dur_active = False
                elif event.unicode.isdigit() and len(self._gc_custom_dur) < 4:
                    self._gc_custom_dur += event.unicode
                return None
            # Register patient panel handles text input
            if self.active_panel == 6 and self.rp.get("active_key"):
                self._rp_keydown(event)
                return None
            # (no ESC navigation — use mouse/touch only)

        return None

    def _handle_click(self, pos):
        """
        Process mouse/touch clicks. Routes clicks to appropriate handlers
        based on which UI element was clicked. Checked in priority order:
        share modal > other modals > sidebar > panels
        """
        # ── Edit patient modal ────────────────────────────────────────
        if self._ep_modal_open:
            # Delete-confirm overlay sits on top — it must be handled first
            if self.modal == "delete_patient_confirm":
                yr, nr = self._confirm_rects()
                if yr.collidepoint(pos):
                    play_click()
                    self._ep_delete()
                    self._ep_modal_open = False
                    self.modal = None
                elif nr.collidepoint(pos):
                    play_click()
                    self.modal = None
                return None
            self._ep_handle_click(pos); return None

        # ── Share modal (checked before everything else - highest priority) ──
        if self._share_modal_open:
            if self._share_close_rect.collidepoint(pos):
                play_click()
                self._share_modal_open = False; return None

            # Final confirmation (worded for whichever action was chosen)
            if self._share_stage == "confirm":
                if self._share_yes_rect.collidepoint(pos):
                    play_click()
                    self._do_share_or_transfer_confirm(); return None
                if self._share_no_rect.collidepoint(pos):
                    play_click()
                    self._share_stage = "choice"       # back one step, not all the way out
                    return None
                return None

            # SHARE | TRANSFER choice
            if self._share_stage == "choice":
                if self._share_choice_share_rect.collidepoint(pos):
                    play_click()
                    self._share_pending_action = "share"
                    self._share_stage = "confirm"
                    return None
                if self._share_choice_transfer_rect.collidepoint(pos):
                    play_click()
                    self._share_pending_action = "transfer"
                    self._share_stage = "confirm"
                    return None
                if self._share_no_rect.collidepoint(pos):   # "Cancel" back to the picker
                    play_click()
                    self._share_stage             = "pick"
                    self._share_confirm_therapist = None
                    return None
                return None

            # Live suggestion item clicks -> SHARE|TRANSFER choice (not straight to confirm)
            for (sr, therapist) in self._share_sugg_rects:
                if sr.collidepoint(pos):
                    play_click()
                    self._share_confirm_therapist = therapist
                    self._share_stage             = "choice"
                    return None

            # Unshare/Revoke buttons
            for (ur, tid) in self._unshare_rects:
                if ur.collidepoint(pos):
                    play_click()
                    self.db.unshare_patient(self.share_modal_patient["id"], tid)
                    self._share_success = "Access revoked."
                    self._share_error   = ""
                    return None

            return None  # absorb all other clicks

        # ── Calibration mismatch modal ────────────────────────────────
        if self.modal == "calibration_mismatch":
            if self._mismatch_cal_rect.collidepoint(pos):
                play_click()
                self.modal = None
                game_type  = (self.gc.get("selected_game") or (None, None))[1] or "Grip Strength"
                self._cal_win = CalibrationWindow(self.WIDTH, self.HEIGHT, game_type, dark_mode=self._applied_theme_dark)
                if _DUAL_MONITOR:
                    therapist_link.calibrate_begin(game_type)
                self._sync_dur_to_cal()
                return None
            if self._mismatch_cancel_rect.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        # ── Other modals ──────────────────────────────────────────────
        if self.modal == "delete_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                play_click()
                # _ep_delete() itself decides what closes: on success it clears
                # _ep_modal_open; on an ownership-check failure it leaves the
                # edit modal open (behind this confirm dialog) so the error is
                # visible, and here we only need to dismiss the confirm dialog.
                self._ep_delete()
                self.modal = None
            if nr.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        if self.modal == "delete_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                play_click()
                if self.db.delete_therapist(self.account["id"]):
                    self.action_triggered = True
                    return "therapist_welcome"
                # Still owns patients -- refuse and explain instead of deleting.
                self.modal = "delete_blocked"
            if nr.collidepoint(pos):
                play_click()
                self.modal = "edit_profile"
            return None

        if self.modal == "delete_blocked":
            # Single dismiss button: back to Edit Profile so the therapist can
            # go transfer their patients (Phase 4: Share icon -> TRANSFER).
            if self._db_blocked_ok_rect.collidepoint(pos):
                play_click()
                self.modal = "edit_profile"
            return None

        if self.modal == "register_success":
            if self._rp_ok_rect.collidepoint(pos):
                play_click()
                self.modal = None
                self._open_panel(0)
            return None

        if self.modal == "logout_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):
                play_click()
                if _DUAL_MONITOR:
                    therapist_link.set_present(False)   # logged out ...
                    therapist_link.set_booting(True)    # ... back on the Login page -> patient Waiting Screen
                self.action_triggered = True
                return "login"
            if nr.collidepoint(pos):
                play_click()
                self.modal = None
            return None

        if self.modal == "select_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):                    # CONFIRM
                play_click()
                self._confirm_select_patient()
            elif nr.collidepoint(pos):                  # CANCEL
                play_click()
                self._pending_select_patient = None
                self.modal = None
            return None

        if self.modal == "deselect_patient_confirm":
            yr, nr = self._confirm_rects()
            if yr.collidepoint(pos):                    # CONFIRM -> clear the selection
                play_click()
                self._pending_deselect_patient = None
                self.modal = None
                self._set_selected_patient(None)
            elif nr.collidepoint(pos):                  # CANCEL -> keep it selected
                play_click()
                self._pending_deselect_patient = None
                self.modal = None
            return None

        if self.modal == "edit_profile":
            if self.edit_icon_picker_open:
                return self._handle_icon_picker_click(pos)
            return self._handle_edit_click(pos)

        # ── Sidebar ──────────────────────────────────────────────────
        if self._edit_link_rect.collidepoint(pos):
            play_click()
            self._init_edit_fields(); self.modal = "edit_profile"; return None

        if self._logout_rect().collidepoint(pos):
            play_confirm_alert()
            self.modal = "logout_confirm"; return None

        if self._theme_btn_rect.collidepoint(pos):
            play_click()
            self._apply_theme(not self._applied_theme_dark)   # -> therapist + patient
            return None

        # Controller monitor: tap to force a fresh BLE scan (manual retry).
        if self._ctrl_btn_rect.collidepoint(pos):
            play_click()
            if _ble_receiver is not None and (not _DUAL_MONITOR or self.selected_patient):
                try:
                    _ble_receiver.rescan()
                    self._ble_want = True        # keep the reconcile in step
                except Exception:
                    pass
            return None

        for i, r in enumerate(self.nav_rects):
            if r.collidepoint(pos):
                play_click()
                self._open_panel(SIDEBAR_NAV[i]["idx"]); return None

        # ── Back button ───────────────────────────────────────────────
        if self.active_panel != -1 and self._back_btn_rect.collidepoint(pos):
            play_click(); self._go_back(); return None

        # ── Clickable breadcrumbs ─────────────────────────────────────
        for hit, target in self._crumb_rects:
            if hit.collidepoint(pos):
                play_click()
                self._nav_breadcrumb(target)
                return None

        # ── Home cards ────────────────────────────────────────────────
        if self.active_panel == -1:
            for i, cr in enumerate(self.card_rects):
                if cr.collidepoint(pos):
                    play_click()
                    self._open_panel(HOME_CARDS[i]["idx"])
                    return None

        # ── Panel 0: Patient List ─────────────────────────────────────
        if self.active_panel == 0:
            if self._pl_up_rect.collidepoint(pos):
                play_click(); self._pl_scroll_by(-1); return None
            if self._pl_down_rect.collidepoint(pos):
                play_click(); self._pl_scroll_by(1); return None
            if self._pt_search_rect.collidepoint(pos):
                self._pt_search_active = True; return None
            else:
                self._pt_search_active = False
            if self._register_link_rect.collidepoint(pos):
                play_click(); self._open_panel(6); return None
            for row in self._patient_rows:
                btn_rect = row[0]
                patient  = row[1]
                action   = row[2] if len(row) > 2 else "name"
                if btn_rect.collidepoint(pos):
                    play_click()
                    if action == "share":
                        self._open_share_modal(patient)     # only right-side action left
                    else:   # "name" -- the row opens the patient's own page.
                        # Does NOT select the patient; selection happens there.
                        self.preview_patient = patient
                        self._pv_tab = "info"
                        self._pv_info_scroll = 0
                        self._open_panel(8)
                    return None

        # ── Panel 1: Session History ────────────────────────────────
        if self.active_panel == 1:
            if self._sh_up_rect.collidepoint(pos):
                play_click(); self._sh_scroll = max(0, self._sh_scroll - int(160*self._fs)); return None
            if self._sh_down_rect.collidepoint(pos):
                play_click()
                self._sh_scroll = min(self._sh_scroll_max, self._sh_scroll + int(160*self._fs))
                return None

        # ── Panel 2: Analytics ───────────────────────────────────────
        if self.active_panel == 2:
            if self._an_up_rect.collidepoint(pos):
                play_click(); self._an_scroll = max(0, self._an_scroll - int(160*self._fs)); return None
            if self._an_down_rect.collidepoint(pos):
                play_click()
                self._an_scroll = min(self._an_scroll_max, self._an_scroll + int(160*self._fs))
                return None

        # ── Panel 3: Calibration Records ─────────────────────────────
        if self.active_panel == 3:
            if self._cr_up_rect.collidepoint(pos):
                play_click(); self._cr_scroll = max(0, self._cr_scroll - int(160*self._fs)); return None
            if self._cr_down_rect.collidepoint(pos):
                play_click()
                self._cr_scroll = min(self._cr_scroll_max, self._cr_scroll + int(160*self._fs))
                return None

        # ── Panel 8: the patient's own page (info + records + selection) ──
        if self.active_panel == 8:
            if self._pv_info_up_rect.collidepoint(pos):
                play_click(); self._pv_info_scroll = max(0, self._pv_info_scroll - int(160*self._fs)); return None
            if self._pv_info_down_rect.collidepoint(pos):
                play_click()
                self._pv_info_scroll = min(self._pv_info_scroll_max, self._pv_info_scroll + int(160*self._fs))
                return None
            for key, r in self._pv_tab_rects.items():
                if r.collidepoint(pos):
                    play_click()
                    self._pv_tab = key
                    self._pv_info_scroll = 0
                    return None
            # Per-section Edit buttons on the Info tab (owner only).
            # "Record" deliberately has none -- it is always read-only.
            for sec, r in self._pv_sec_edit_rects.items():
                if r.collidepoint(pos) and self.preview_patient:
                    play_click()
                    self._open_ep_modal(self.preview_patient, section=sec)
                    return None
            if self._pv_select_rect.collidepoint(pos) and self.preview_patient:
                play_confirm_alert()
                if self._is_selected(self.preview_patient):
                    # DESELECT PATIENT -- confirm first, then clear (stay here).
                    self._pending_deselect_patient = self.preview_patient
                    self.modal = "deselect_patient_confirm"
                else:
                    # SELECT PATIENT -- confirm, then continue to Game Config.
                    self._pending_select_patient = self.preview_patient
                    self.modal = "select_patient_confirm"
                return None

        # ── Panel 6: Register Patient ─────────────────────────────────
        if self.active_panel == 6:
            if self._touch_ui:
                if self._rp_up_rect.collidepoint(pos):
                    play_click()
                    self._rp_scroll = max(0, self._rp_scroll - int(160 * self._fs))
                    return None
                if self._rp_down_rect.collidepoint(pos):
                    play_click()
                    self._rp_scroll = min(self._rp_scroll_max,
                                          self._rp_scroll + int(160 * self._fs))
                    return None
            self._rp_handle_click(pos)

        # ── Panel 4: Game Configuration ───────────────────────────────
        if self.active_panel == 4:
            self._gc_handle_click(pos)
            if self._gc_next_rect.collidepoint(pos):
                play_click()
                self._open_panel(5); return None

        # ── Panel 5: Start Session ────────────────────────────────────
        if self.active_panel == 5:
            # ── Session Details dropdown intercept (highest priority) ──
            if self._ss_open_param:
                open_key, open_opts = self._ss_open_param
                pr = self._ss_param_rects.get(open_key)
                if pr:
                    opt_h = self._tt(44) if self._touch_ui else int(36 * self.HEIGHT / 1080)
                    for j, opt_val in enumerate(open_opts):
                        or_ = pygame.Rect(pr.x, pr.bottom + j * opt_h, pr.width, opt_h)
                        if or_.collidepoint(pos):
                            play_click()
                            self.gc[open_key] = opt_val
                            self._ss_custom_dur_active = False
                            self._ss_open_param = None
                            return None
                self._ss_open_param = None
                return None   # consume click; dropdown closes

            if self._bypass_btn_rect.collidepoint(pos):
                play_click()
                self.calibration_bypassed = not self.calibration_bypassed
                return None
            if self._calibrate_btn_rect.collidepoint(pos):
                play_click()
                game_type = (self.gc.get("selected_game") or (None, None))[1] or "Grip Strength"
                self._cal_win = CalibrationWindow(self.WIDTH, self.HEIGHT, game_type, dark_mode=self._applied_theme_dark)
                if _DUAL_MONITOR:
                    therapist_link.calibrate_begin(game_type)
                self._sync_dur_to_cal()
                return None

            # ── Duration / Speed dropdown toggle ──────────────────────
            DUR_OPTS = ["60 seconds", "120 seconds", "180 seconds"]
            SPD_OPTS = ["Slow", "Normal", "Fast"]
            for pk, opts in [("duration", DUR_OPTS), ("speed", SPD_OPTS)]:
                pr = self._ss_param_rects.get(pk)
                if pr and pr.collidepoint(pos):
                    play_click()
                    self._ss_open_param = (pk, opts)
                    return None

            if self._start_btn_rect.collidepoint(pos) and self._session_ready():
                if self._calibration_mismatched():
                    self.modal = "calibration_mismatch"
                    return None
                play_start_session()
                return self._launch_game()

        return None

    def _go_back(self):
        if self.active_panel == 6:   self._open_panel(0)
        elif self.active_panel == 4: self._open_panel(0)
        elif self.active_panel == 5: self._open_panel(4)
        elif self.active_panel == 8: self._open_panel(0)     # patient page -> Patient List
        elif self.active_panel == 7:
            # Session in Progress -> Game Configuration. Terminate any active
            # game/session first so no stale patient-side state is left behind.
            self._sm_back()

    def _nav_breadcrumb(self, target):
        """Handle a click on a clickable breadcrumb item."""
        kind, val = target
        if kind == "panel":
            self._open_panel(val)
        elif kind == "patient" and val:
            self.preview_patient = val
            self._pv_tab = "info"
            self._pv_info_scroll = 0
            self._open_panel(8)

    def _view_patient(self):
        """Which patient the per-patient record panels (Analytics / Calibration /
        Session History) should display: the Preview target while reviewing on
        panel 8, otherwise the selected session patient."""
        if self.active_panel == 8:
            return self.preview_patient
        return self.selected_patient

    def _apply_theme(self, dark: bool, persist: bool = True):
        """One source of truth for the RecovR light/dark theme. Applies it on
        this side (constants.get_theme() drives the games / calibration window)
        AND pushes it to the patient monitor immediately -- no reload, no new
        session, works on whatever patient screen is showing.

        The theme belongs to the SELECTED PATIENT: whenever one is selected the
        new value is written to their row, so re-selecting them later restores
        it. `persist=False` is used when we are *restoring* a stored value and
        must not write it straight back."""
        if dark == self._applied_theme_dark:
            return
        self._applied_theme_dark = dark
        try:
            from constants import set_dark_mode
            set_dark_mode(dark)
        except Exception:
            pass
        if _DUAL_MONITOR:
            therapist_link.set_dark_mode(dark)
        if persist and self.selected_patient:
            pid = self.selected_patient.get("id")
            try:
                if pid is not None and hasattr(self.db, "set_patient_theme"):
                    self.db.set_patient_theme(pid, dark)
                    # keep the in-memory rows in step so a re-select reads it back
                    self.selected_patient["theme_dark"] = 1 if dark else 0
                    for p in (self.patients or []):
                        if p.get("id") == pid:
                            p["theme_dark"] = 1 if dark else 0
                    if self.preview_patient and self.preview_patient.get("id") == pid:
                        self.preview_patient["theme_dark"] = 1 if dark else 0
            except Exception:
                pass

    def _restore_patient_theme(self, patient):
        """Apply a patient's stored theme when they become the selected patient.
        Patients registered before the column existed default to Light."""
        dark = bool((patient or {}).get("theme_dark", 0))
        self._apply_theme(dark, persist=False)

    # ── selected-patient: ONE source of truth (self.selected_patient),
    #    mirrored into the shared session so every view + the patient monitor
    #    agree. Route ALL selection changes through _set_selected_patient(). ──
    def _is_selected(self, patient):
        return bool(patient and self.selected_patient
                    and self.selected_patient.get("id") == patient.get("id"))

    def _push_selected_patient(self):
        if not _DUAL_MONITOR:
            return
        p = self.selected_patient
        if not p:
            therapist_link.set_selected_patient(None)
            return
        # Attach the patient's recent session history so the Patient Dashboard
        # can show it (the patient process has no DB access of its own).
        hist = []
        try:
            if hasattr(self.db, "get_sessions"):
                for s in self.db.get_sessions(self.account["id"], patient_id=p["id"])[:20]:
                    hist.append({
                        "game":       s.get("game", ""),
                        "played_at":  str(s.get("played_at", ""))[:10],
                        "difficulty": s.get("difficulty", ""),
                        "score":      s.get("score", ""),
                    })
        except Exception:
            pass
        therapist_link.set_selected_patient(
            {"id": p.get("id"), "full_name": p.get("full_name", ""),
             "sex": p.get("sex", ""), "history": hist})

    def _set_selected_patient(self, patient):
        """Set (patient dict) or clear (None) the selected session patient and
        mirror it to shared state. The patient monitor shows its Dashboard only
        while this is set, and returns to the Waiting Screen when it is cleared.

        Selecting also restores that patient's saved theme; deselecting returns
        the interface to the Light default."""
        self.selected_patient = patient or None
        self._push_selected_patient()
        if patient:
            self._restore_patient_theme(patient)
        else:
            self._apply_theme(False, persist=False)   # no patient -> Light

    def _pl_scroll_by(self, direction):
        """Scroll the Patient List (touchscreen ▲/▼ buttons and mouse wheel).
        `direction` is -1 (up) or +1 (down); each press moves ~3 rows."""
        step = int(120 * self._fs) * 3 * (1 if direction > 0 else -1)
        self._pl_scroll = max(0, min(self._pl_scroll + step, self._pl_scroll_max))

    def _confirm_select_patient(self):
        """The single place a patient actually becomes the session patient:
        reached only after the SELECT -> confirmation dialog is confirmed.
        Sets the patient and continues to Game Configuration."""
        patient = self._pending_select_patient
        self._pending_select_patient = None
        self.modal = None
        if not patient:
            return
        self._set_selected_patient(patient)
        self._init_game_config_state()
        self.calibration_done   = False
        self.calibration_result = None
        self._cal_win           = None
        self._open_panel(4)

    def _open_panel(self, idx):
        self.active_panel      = idx
        self._ss_open_param    = None   # close any open session-detail dropdown
        self._ss_custom_dur_active = False
        if idx == 6:
            self._rp_scroll  = 0
            self._rp_drag_y  = None
        if idx == 0:
            self._pt_search_active = False
            self._pt_search_text   = ""
            self._pl_scroll        = 0
            self._pl_drag_y        = None
            try:
                self.patients = (
                    self.db.get_all_patients(therapist_id=self.account["id"])
                    if hasattr(self.db, 'get_all_patients') else []
                )
            except Exception:
                self.patients = []

    def _sync_dur_to_cal(self):
        """Push Session Details duration → newly opened CalibrationWindow Advanced Settings."""
        if self._cal_win is None:
            return
        sd = self.gc.get("duration", "120 seconds")
        if sd == "Custom":
            self._cal_win.adv_duration   = "Custom"
            self._cal_win.adv_custom_dur = self._gc_custom_dur or ""
        else:
            try:
                self._cal_win.adv_duration = f"{int(sd.split()[0])} s"
            except (ValueError, IndexError):
                pass

    def _sync_dur_from_cal(self, cal_win):
        """Pull CalibrationWindow Advanced Settings duration → Session Details."""
        cal_d = cal_win.adv_duration
        if cal_d == "Custom":
            # specific-time entry was removed from Game Config -- keep the preset
            pass
        else:
            try:
                self.gc["duration"] = f"{int(cal_d.split()[0])} seconds"
            except (ValueError, IndexError):
                pass

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
        "Piano Tiles": "piano_tiles",
        "Apple Catching": "catchingapple",
        "Catch the Falling Object": "catch_object",
        "Gravity Catch": "gravity_catch",
        "Key and Lock": "key_lock",
    }

    def _launch_game(self):
        import builtins
        game_name = (self.gc.get("selected_game") or (None,))[0]
        scene_key = self._GAME_SCENE_MAP.get(game_name)
        if not scene_key and not _DUAL_MONITOR:
            return None  # game not yet implemented (single-window path)
        dur_str = self.gc.get("duration", "60 seconds")
        try:
            dur_sec = int(str(dur_str).split()[0])   # "120 seconds" -> 120
        except (ValueError, IndexError):
            dur_sec = 60
        raw_diff  = self.gc.get("difficulty", "Easy")
        game_diff = raw_diff

        # ── Dual-monitor "START SESSION": send the config, fire START_SESSION   ──
        # ── (patient Welcome/Waiting -> How to Play; game NOT running), and     ──
        # ── navigate to the "Session in Progress" screen (panel 7). The actual  ──
        # ── game starts later, when the therapist clicks START there.           ──
        if _DUAL_MONITOR:
            # Same payload the standalone app puts in builtins.pending_game_data,
            # so the real game on the patient monitor behaves identically.
            therapist_link.configure({
                "selected_game":  game_name,
                "difficulty":     game_diff,
                "duration_sec":   dur_sec,
                "speed":          self.gc.get("speed", "Normal"),
                "calibration":    self.calibration_result or {},
                # the SELECTED PATIENT's theme -- not the calibration snapshot, which
                # would clobber it at session start (set_config mirrors this
                # onto the live shared dark_mode).
                "dark_mode":      self._applied_theme_dark,
                "patient_id":     (self.selected_patient or {}).get("id"),
                "patient_name":   (self.selected_patient or {}).get("full_name", ""),
                "therapist_name": self.account.get("full_name", ""),
                "account_id":     self.account.get("id"),
            })
            therapist_link.command(_rc_cmd.START_SESSION)
            self._sm_result = None
            self._sm_volume = None
            self._sm_stopped_notice = False
            self._sm_started_ms = pygame.time.get_ticks()   # START locked for the BLE handoff window
            self._open_panel(7)
            return None                      # do NOT switch this window to a game scene

        builtins.pending_game_data = {
            "account_id":   self.account.get("id"),
            "account":      self.account,
            "patient":      self.selected_patient,
            "difficulty":   game_diff,
            "duration_sec": dur_sec,
            "speed":        self.gc.get("speed", "Normal"),
            "calibration":  self.calibration_result or {},
            "dark_mode":    self._applied_theme_dark,
        }
        # Re-set pending_account so the dashboard gets the right therapist when recreated
        builtins.pending_account = self.account
        self.action_triggered = True
        return scene_key

    # ══════════════════════════════════════════════════════════════════
    #  PANEL 7 — "SESSION IN PROGRESS"  (dual-monitor; RECOVR_DUAL_MONITOR=1)
    #
    #  A real dashboard screen (not a pop-up). ONE state-driven control button
    #  START → PAUSE → RESUME → PAUSE ... → RESTART, plus Volume; the standard
    #  dashboard Back button in the header leaves the screen (no separate Exit),
    #  plus a separate red emergency STOP at the lower-right of the interface.
    #  (START SESSION already sent the config + START_SESSION; the patient is now
    #  on How to Play. This button's START sends START_GAME -> the game runs.)
    # ══════════════════════════════════════════════════════════════════

    _SM_VOL_STEPS = [0.0, 0.25, 0.5, 0.75, 1.0]

    def _sm_update(self, mouse_pos):
        st = therapist_link.get_state() or {}
        self._sm_state = st
        status = st.get("status", "")
        if status == _rc_cmd.COMPLETE and self._sm_result is None:
            self._sm_result = dict(st.get("result") or {}) or {"score": "-"}
        if status in (_rc_cmd.RUNNING, _rc_cmd.PAUSED):
            self._sm_result = None
        if self._sm_volume is None:
            try:
                self._sm_volume = float(st.get("volume", 0.4))
            except (TypeError, ValueError):
                self._sm_volume = 0.4
        self._sm_hover = None
        for key, (r, enabled) in self._sm_btn_rects.items():
            if enabled and r.collidepoint(mouse_pos):
                self._sm_hover = key
        if self._sm_stop_rect.collidepoint(mouse_pos):
            self._sm_hover = "stop"
        if self._sm_notice_continue_rect.collidepoint(mouse_pos):
            self._sm_hover = "notice_continue"
        if self._sm_notice_back_rect.collidepoint(mouse_pos):
            self._sm_hover = "notice_back"

    def _sm_primary(self, status):
        """(icon, label, command) for the single state-driven control button."""
        if status == _rc_cmd.RUNNING:
            return ("pause",  "PAUSE",   _rc_cmd.PAUSE_GAME)
        if status == _rc_cmd.PAUSED:
            return ("start",  "RESUME",  _rc_cmd.RESUME_GAME)
        if status == _rc_cmd.COMPLETE:
            return ("restart", "RESTART", _rc_cmd.RESTART_GAME)
        return ("start", "START", _rc_cmd.START_GAME)   # READY / connecting

    def _sm_leave(self):
        """Clear the session and return to Game Configuration."""
        therapist_link.reset()
        self._sm_result = None
        self._sm_volume = None
        self._sm_stopped_notice = False
        self._open_panel(4)                 # -> Game Configuration (NOT Patient List)

    def _sm_back(self):
        """The standard dashboard Back button on panel 7: stop any active game
        and navigate to Game Configuration -- no stale session left behind."""
        st = self._sm_state or {}
        if st.get("status") in (_rc_cmd.RUNNING, _rc_cmd.PAUSED):
            therapist_link.command(_rc_cmd.STOP_GAME)
        self._sm_leave()

    def _sm_emergency_stop(self):
        """Red STOP: HOLD the game (pause it -- state preserved) and open the
        'Game Stopped' decision screen on BOTH monitors. The game is NOT
        terminated yet; the therapist still chooses CONTINUE or BACK."""
        st = self._sm_state or {}
        if st.get("status") == _rc_cmd.RUNNING:
            therapist_link.command(_rc_cmd.PAUSE_GAME)   # freeze; keep the instance
        therapist_link.set_stop_pending(True)            # -> decision state, both monitors
        self._sm_stopped_notice = True

    def _sm_continue(self):
        """CONTINUE: resume the SAME game and stay on Session in Progress.
        No teardown, no navigation."""
        self._sm_stopped_notice = False
        therapist_link.set_stop_pending(False)
        if (self._sm_state or {}).get("status") == _rc_cmd.PAUSED:
            therapist_link.command(_rc_cmd.RESUME_GAME)  # patient resumes the same game

    def _sm_end_session(self):
        """BACK: end the current game/session -- terminate + clean up, then
        therapist -> Game Configuration (patient -> Patient Dashboard / Waiting)."""
        self._sm_stopped_notice = False
        therapist_link.set_stop_pending(False)
        if (self._sm_state or {}).get("status") in (
                _rc_cmd.RUNNING, _rc_cmd.PAUSED, _rc_cmd.READY):
            therapist_link.command(_rc_cmd.STOP_GAME)
        self._sm_leave()                                 # reset() + _open_panel(4)

    def _sm_handle_click(self, pos):
        # "Game Stopped" decision screen -> CONTINUE (resume) | BACK (end session).
        if self._sm_stopped_notice:
            if self._sm_notice_continue_rect.collidepoint(pos):
                play_click(); self._sm_continue()
            elif self._sm_notice_back_rect.collidepoint(pos):
                play_click(); self._sm_end_session()
            return
        # the standard dashboard Back button (drawn by _draw_panel_shell)
        if self._back_btn_rect.collidepoint(pos):
            play_click()
            self._go_back()
            return
        # emergency STOP: separate red button
        if self._sm_stop_rect.collidepoint(pos):
            play_click()
            self._sm_emergency_stop()
            return
        for key, (r, enabled) in list(self._sm_btn_rects.items()):
            if not r.collidepoint(pos) or not enabled:
                continue
            play_click()
            if key == "primary":
                _icon, _lbl, command = self._sm_primary((self._sm_state or {}).get("status", ""))
                therapist_link.command(command)
                if command == _rc_cmd.RESTART_GAME:
                    self._sm_result = None
            elif key == "volume":
                cur = self._sm_volume if self._sm_volume is not None else 0.4
                idx = min(range(len(self._SM_VOL_STEPS)),
                          key=lambda i: abs(self._SM_VOL_STEPS[i] - cur))
                self._sm_volume = self._SM_VOL_STEPS[(idx + 1) % len(self._SM_VOL_STEPS)]
                therapist_link.set_volume(self._sm_volume)
            return

    # -- draw one vector control glyph inside a button ---------------
    def _sm_icon(self, surface, kind, cx, cy, s, col):
        w = max(3, int(s * 0.30))
        if kind == "pause":
            bw = max(3, int(s * 0.34)); bh = int(s * 1.4); g = int(s * 0.34)
            pygame.draw.rect(surface, col, (cx - g - bw, cy - bh // 2, bw, bh), border_radius=3)
            pygame.draw.rect(surface, col, (cx + g,      cy - bh // 2, bw, bh), border_radius=3)
        elif kind == "start":                       # play triangle (START / RESUME)
            pygame.draw.polygon(surface, col, [
                (cx - int(s * 0.55), cy - int(s * 0.75)),
                (cx - int(s * 0.55), cy + int(s * 0.75)),
                (cx + int(s * 0.80), cy)])
        elif kind == "restart":
            import math as _m
            rr = pygame.Rect(cx - s, cy - s, 2 * s, 2 * s)
            pygame.draw.arc(surface, col, rr, _m.radians(70), _m.radians(360), w)
            ax, ay = cx + int(s * 0.34), cy - int(s * 0.94)
            pygame.draw.polygon(surface, col, [
                (ax, ay - int(s * 0.10)),
                (ax + int(s * 0.55), ay + int(s * 0.05)),
                (ax + int(s * 0.02), ay + int(s * 0.55))])
        elif kind == "volume":
            pygame.draw.polygon(surface, col, [
                (cx - int(s * 0.95), cy - int(s * 0.30)),
                (cx - int(s * 0.45), cy - int(s * 0.30)),
                (cx + int(s * 0.05), cy - int(s * 0.80)),
                (cx + int(s * 0.05), cy + int(s * 0.80)),
                (cx - int(s * 0.45), cy + int(s * 0.30)),
                (cx - int(s * 0.95), cy + int(s * 0.30))])
            vol = self._sm_volume if self._sm_volume is not None else 0.4
            arcs = int(round(vol * 3))
            if arcs == 0:
                mx = cx + int(s * 0.35)
                pygame.draw.line(surface, col, (mx, cy - int(s * 0.4)),
                                 (mx + int(s * 0.55), cy + int(s * 0.4)), w)
                pygame.draw.line(surface, col, (mx, cy + int(s * 0.4)),
                                 (mx + int(s * 0.55), cy - int(s * 0.4)), w)
            else:
                import math as _m
                for i in range(arcs):
                    rad = int(s * (0.45 + 0.42 * i))
                    ar = pygame.Rect(cx + int(s * 0.1) - rad, cy - rad, 2 * rad, 2 * rad)
                    pygame.draw.arc(surface, col, ar, _m.radians(-45), _m.radians(45), w)
        elif kind == "exit":
            x0, x1 = cx - int(s * 0.85), cx + int(s * 0.05)
            y0, y1 = cy - int(s * 0.85), cy + int(s * 0.85)
            pygame.draw.lines(surface, col, False,
                              [(x1, y0), (x0, y0), (x0, y1), (x1, y1)], w)
            pygame.draw.line(surface, col, (cx - int(s * 0.25), cy),
                             (cx + int(s * 0.85), cy), w)
            pygame.draw.polygon(surface, col, [
                (cx + int(s * 0.55), cy - int(s * 0.42)),
                (cx + int(s * 1.02), cy),
                (cx + int(s * 0.55), cy + int(s * 0.42))])
        elif kind == "stop":                        # filled square (emergency stop)
            pygame.draw.rect(surface, col, (cx - int(s * 0.7), cy - int(s * 0.7),
                                            int(s * 1.4), int(s * 1.4)), border_radius=4)

    def _sm_draw(self, surface, pa):
        """Panel-7 drawer: (surface, panel-area rect). Also draws the separate
        emergency STOP button at the lower-right of the whole interface."""
        F = self.fnt
        W, H = self.WIDTH, self.HEIGHT
        st  = self._sm_state or {}
        status = st.get("status", "connecting")
        tel = st.get("telemetry") or {}
        cfg = st.get("config") or {}

        _card_bg(surface, pa, alpha=235, radius=16)
        pad = int(44 * (W / 1920))
        x0  = pa.x + pad
        y   = pa.y + pad

        surface.blit(F["panel_title"].render(cfg.get("selected_game") or "Session",
                                             True, (28, 42, 64)), (x0, y))
        y += max(int(76 * (H / 1080)), self._sc(60))

        # Simplified therapist read-out: only Game Name (already the title
        # above), Patient, Difficulty and a real-time Score -- Status/Elapsed/
        # Remaining/Duration removed. Score comes from the SAME telemetry the
        # old "Score" row already used (no second scoring system); once the
        # session completes it falls back to the final recorded score so the
        # number doesn't disappear the moment the game ends.
        score_val = tel.get("score")
        if score_val in (None, ""):
            score_val = (self._sm_result or {}).get("score", "-")
        rows = [
            ("Patient",    cfg.get("patient_name") or "-"),
            ("Difficulty", cfg.get("difficulty") or "-"),
            ("Score",      score_val),
        ]
        val_dx = max(int(260 * W / 1920), self._sc(150)) if self._touch_ui \
            else int(260 * W / 1920)
        row_dy = max(int(42 * (H / 1080)), self._sc(40))
        for k, v in rows:
            surface.blit(F["body"].render(k, True, (120, 135, 160)), (x0, y))
            surface.blit(F["body_b"].render(str(v), True, (38, 52, 78)), (x0 + val_dx, y))
            y += row_dy

        # ── control row: [ primary(START/PAUSE/RESUME/RESTART) ] [ VOLUME ] ──
        # (EXIT removed -- use the standard dashboard Back button in the header)
        bs  = max(int(108 * (H / 1080)), self._tt(104))
        gap = int(34 * (W / 1920))
        p_icon, p_label, _p_cmd = self._sm_primary(status)
        # The initial START is held for a few seconds after "Start Session" so the
        # BLE controller can move from this process to the patient process before
        # the game runs. RESUME / RESTART / PAUSE are never locked.
        lock_ms_left = self._sm_start_lock_ms - (pygame.time.get_ticks() - self._sm_started_ms)
        primary_locked = (
            _p_cmd == _rc_cmd.START_GAME
            and status in (_rc_cmd.READY, _rc_cmd.IDLE, "connecting")
            and lock_ms_left > 0
        )
        if primary_locked:
            p_label = f"START  {lock_ms_left // 1000 + 1}"
        specs = [
            ("primary", p_icon,  p_label,  not primary_locked),
            ("volume",  "volume", "VOLUME", True),
        ]
        total = bs * len(specs) + gap * (len(specs) - 1)
        bx = pa.x + (pa.width - total) // 2
        brow_y = pa.y + pa.height - bs - int(64 * (H / 1080))
        cap_font = F.get("small") or F["body"]
        self._sm_btn_rects = {}
        for key, icon, label, enabled in specs:
            r = pygame.Rect(bx, brow_y, bs, bs)
            self._sm_btn_rects[key] = (r, bool(enabled))
            hovered = self._sm_hover == key and enabled
            if key == "primary":
                if not enabled:
                    fill = (176, 190, 205)          # locked during the BLE handoff window
                else:
                    fill = (86, 162, 232) if hovered else (70, 150, 225)
                pygame.draw.rect(surface, fill, r, border_radius=18)
                ic = cap = (255, 255, 255)
            else:
                if hovered:
                    fill, brd, ic, cap = (223, 235, 249), (90, 140, 210), (30, 48, 78), (55, 72, 100)
                else:
                    fill, brd, ic, cap = (236, 242, 250), (95, 145, 212), (36, 54, 86), (60, 76, 104)
                pygame.draw.rect(surface, fill, r, border_radius=18)
                pygame.draw.rect(surface, brd, r, 2, border_radius=18)
            self._sm_icon(surface, icon, r.centerx, r.centery - int(bs * 0.13), int(bs * 0.22), ic)
            cs = cap_font.render(label, True, cap)
            surface.blit(cs, cs.get_rect(center=(r.centerx, r.bottom - int(bs * 0.20))))
            bx += bs + gap

        # ── emergency STOP: red, separate, lower-right of the interface ──
        sw, sh = max(int(210 * W / 1920), self._tt(210)), max(int(78 * H / 1080), self._tt(70))
        self._sm_stop_rect = pygame.Rect(W - sw - int(30 * W / 1920),
                                         H - sh - int(30 * H / 1080), sw, sh)
        shov = self._sm_hover == "stop"
        pygame.draw.rect(surface, (232, 66, 60) if shov else (214, 48, 44),
                         self._sm_stop_rect, border_radius=14)
        pygame.draw.rect(surface, (150, 22, 20), self._sm_stop_rect, 2, border_radius=14)
        gy = self._sm_stop_rect.centery
        self._sm_icon(surface, "stop", self._sm_stop_rect.left + sh // 2, gy,
                      int(sh * 0.22), (255, 255, 255))
        ss = F["btn"].render("STOP", True, (255, 255, 255))
        surface.blit(ss, ss.get_rect(midleft=(self._sm_stop_rect.left + sh, gy)))

        # ── "Game Stopped" screen (both monitors show this) ──
        if self._sm_stopped_notice:
            self._sm_draw_stopped_notice(surface)
        else:
            self._sm_notice_continue_rect = pygame.Rect(0, 0, 1, 1)
            self._sm_notice_back_rect     = pygame.Rect(0, 0, 1, 1)

    def _sm_draw_stopped_notice(self, surface):
        """The 'Game Stopped' decision screen: CONTINUE resumes the same game;
        BACK ends the session -> Game Configuration / Patient Dashboard."""
        F = self.fnt
        W, H = self.WIDTH, self.HEIGHT
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((12, 18, 28, 190))
        surface.blit(ov, (0, 0))
        mw = min(W - int(40*W/1920), max(int(W * 0.46), self._tt(660)))
        mh = max(int(H * 0.42), self._tt(320))
        mx, my = (W - mw) // 2, (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)
        pygame.draw.rect(surface, (250, 250, 252), mr, border_radius=18)
        pygame.draw.rect(surface, (214, 48, 44), mr, 3, border_radius=18)
        t = F["modal_head"].render("GAME STOPPED", True, (200, 40, 40))
        surface.blit(t, t.get_rect(centerx=mr.centerx, top=my + int(34 * H / 1080)))
        for i, line in enumerate((
                "CONTINUE  —  resume the current game.",
                "BACK  —  end the session and return to Game Configuration.")):
            s = F["small"].render(line, True, (60, 74, 96))
            surface.blit(s, s.get_rect(centerx=mr.centerx,
                                       top=my + int((100 + i*38) * H / 1080)))

        bw, bh = max(int(230 * W / 1920), self._tt(220)), self._tt(58)
        g = int(28 * W / 1920)
        by = my + mh - bh - int(34 * H / 1080)
        self._sm_notice_continue_rect = pygame.Rect(mr.centerx - bw - g // 2, by, bw, bh)
        self._sm_notice_back_rect     = pygame.Rect(mr.centerx + g // 2,     by, bw, bh)
        chov = self._sm_hover == "notice_continue"
        bhov = self._sm_hover == "notice_back"
        pygame.draw.rect(surface, (90, 165, 235) if chov else (74, 150, 225),
                         self._sm_notice_continue_rect, border_radius=12)
        pygame.draw.rect(surface, (205, 214, 226) if bhov else (188, 200, 214),
                         self._sm_notice_back_rect, border_radius=12)
        cb = F["btn"].render("CONTINUE", True, (255, 255, 255))
        bb = F["btn"].render("BACK", True, (45, 60, 84))
        surface.blit(cb, cb.get_rect(center=self._sm_notice_continue_rect.center))
        surface.blit(bb, bb.get_rect(center=self._sm_notice_back_rect.center))


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
        self._share_stage             = "pick"
        self._share_pending_action    = None

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PATIENT MODAL — helpers
    # ──────────────────────────────────────────────────────────────────

    def _open_ep_modal(self, patient, section=None):
        """Open the edit-patient modal. `section` limits it to one Info group
        ("info" / "stroke" / "notes"); None edits every field (legacy path).

        Refuses outright for a non-owner -- a shared patient is read-only."""
        if not self._is_owner(patient):
            return
        self._ep_patient     = patient
        self._ep_section     = section
        self._ep_modal_open  = True
        self._ep_confirm_del = False
        self._ep_error       = ""
        self._ep_success     = ""
        self._ep_active_key  = None
        self._ep_drop_open   = {k: False for k in
                                ["sex","dominant_hand","affected_hand","stroke_type"]}
        self._ep_drop_rects  = {}
        self._ep = {k: str(patient.get(k, "") or "")
                    for k in ["full_name","age","sex","dominant_hand","affected_hand",
                               "stroke_type","date_of_stroke","months_stroke",
                               "notes_stiffness","notes_pain","notes_therapist"]}

    def _ep_fields(self):
        """(key, label, kind, opts) for the fields this modal is editing."""
        SPEC = {
            "full_name":       ("Full Name",            "text", None),
            "age":             ("Age",                  "text", None),
            "sex":             ("Sex",                  "drop", SEX_OPTS),
            "stroke_type":     ("Stroke Type",          "drop", STROKE_TYPES),
            "date_of_stroke":  ("Stroke Onset Date",    "text", None),
            "months_stroke":   ("Months Since Stroke",  "text", None),
            "dominant_hand":   ("Dominant Hand",        "drop", HAND_OPTS),
            "affected_hand":   ("Affected Hand",        "drop", HAND_OPTS),
            "notes_stiffness": ("Muscle Stiffness",     "text", None),
            "notes_pain":      ("Pain Level",           "text", None),
            "notes_therapist": ("Therapist Comments",   "text", None),
        }
        # A single "edit everything at once" view is no longer part of this
        # UI (it's 3 section-scoped edits now) and its 11 fields do not fit
        # the 800x480 modal budget. An invalid/missing section defaults to
        # "info" -- the smallest, always-present section -- rather than
        # silently falling back to the old all-fields layout.
        sec = getattr(self, "_ep_section", None)
        if sec not in self._PV_SECTIONS:
            sec = "info"
        keys = self._PV_SECTIONS[sec][1]
        return [(k,) + SPEC[k] for k in keys if k in SPEC]

    def _ep_title(self):
        sec = getattr(self, "_ep_section", None)
        if sec and sec in self._PV_SECTIONS:
            return f"Edit {self._PV_SECTIONS[sec][0]}"
        return "Edit Patient"

    def _ep_handle_click(self, pos):
        W, H = self.WIDTH, self.HEIGHT
        if self._ep_cancel_rect.collidepoint(pos):
            play_click()
            self._ep_modal_open = False; return
        if self._ep_save_rect.collidepoint(pos):
            play_click()
            self._ep_submit(); return
        if self._ep_delete_rect.collidepoint(pos):
            play_confirm_alert()
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
                            play_click()
                            self._ep[key] = opt_val
                            self._ep_drop_open[key] = False
                            return
                self._ep_drop_open[key] = False
                return

        # Dropdown toggle
        drop_fields = {
            "sex": SEX_OPTS, "dominant_hand": HAND_OPTS,
            "affected_hand": HAND_OPTS, "stroke_type": STROKE_TYPES,
        }
        for key, opts in drop_fields.items():
            info = self._ep_drop_rects.get(key)
            if info and info[0].collidepoint(pos):
                play_click()
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
        # The edit modal only ever opens for the owner (_open_ep_modal refuses
        # otherwise), but the write is ownership-checked here too -- a shared
        # (non-owner) therapist must never be able to edit patient info, even
        # if that UI gate were ever bypassed.
        ok = self.db.update_patient(self._ep_patient["id"], ep,
                                    acting_therapist_id=self.account["id"])
        if not ok:
            self._ep_error = "You no longer own this patient."
            return
        # Refresh patient name if selected
        if self.selected_patient and self.selected_patient["id"] == self._ep_patient["id"]:
            self.selected_patient["full_name"] = ep["full_name"].strip()
            self._push_selected_patient()
        self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                         if hasattr(self.db, "get_all_patients") else [])
        self._ep_success = "Patient updated successfully."
        self._ep_error   = ""

    def _ep_delete(self):
        pid = self._ep_patient["id"]
        ok = self.db.delete_patient(pid, acting_therapist_id=self.account["id"])
        if not ok:
            self._ep_error = "You no longer own this patient."
            self.modal = None
            return
        if self.selected_patient and self.selected_patient.get("id") == pid:
            self._set_selected_patient(None)
        self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                         if hasattr(self.db, "get_all_patients") else [])
        self._ep_modal_open = False

    def _draw_edit_patient_modal(self, surface):
        """Section-scoped patient editor, sized from _fs/_tt so the controls stay
        finger-sized on the 800x480 panel (the old layout computed everything
        from H/1080 and produced 18px boxes here)."""
        W, H = self.WIDTH, self.HEIGHT
        fields  = self._ep_fields()
        two_col = len(fields) > 3
        pad     = self._sc(18)
        fh      = self._tt(46)
        lbl_h   = self.fnt["small"].get_height()
        row_h   = lbl_h + self._sc(4) + fh + self._sc(14)
        rows    = (len(fields) + 1) // 2 if two_col else len(fields)
        btn_h   = self._tt(46)

        head_h  = self.fnt["panel_title"].get_height() + self._sc(14)
        mw = min(int(W * 0.86), self._sc(700))
        mh = min(int(H * 0.92),
                 head_h + rows * row_h + btn_h + pad * 3 + self.fnt["modal_err"].get_height())
        mx = (W - mw) // 2;  my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (228, 238, 252, 252), (0, 0, mw, mh), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), mr, 1, border_radius=16)

        # Title -- names the section being edited
        surface.blit(self.fnt["panel_title"].render(self._ep_title(), True, (38, 52, 78)),
                     (mr.x + pad, mr.y + self._sc(10)))
        hl_y = mr.y + head_h
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + pad, hl_y), (mr.right - pad, hl_y), 1)

        colgap = self._sc(14)
        fw  = (mw - 2 * pad - colgap) // 2 if two_col else (mw - 2 * pad)
        fy0 = hl_y + self._sc(12)
        self._ep_drop_rects = {}

        def _draw_ep_field(key, lbl, kind, opts, idx):
            col = idx % 2 if two_col else 0
            row = idx // 2 if two_col else idx
            fx  = mr.x + pad + col * (fw + colgap)
            fy  = fy0 + row * row_h + lbl_h + self._sc(4)
            fr  = pygame.Rect(fx, fy, fw, fh)
            self._ep_drop_rects[key] = (fr, [], opts or [])

            active = (self._ep_active_key == key)
            surface.blit(self.fnt["small"].render(lbl, True, (70, 88, 112)),
                         (fx, fy - lbl_h - self._sc(4)))
            pygame.draw.rect(surface, (250, 252, 255), fr, border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220) if active else (180, 205, 232),
                             fr, 2 if active else 1, border_radius=9)

            val = self._ep.get(key, "")
            if kind == "drop":
                disp = val or "Select"
                ts = self.fnt["input"].render(disp, True,
                                              (40, 50, 65) if val else (170, 185, 205))
                surface.blit(ts, ts.get_rect(midleft=(fr.x + self._sc(12), fr.centery)))
                chev = self.fnt["sym26"].render("▼", True, (90, 110, 140))
                surface.blit(chev, chev.get_rect(midright=(fr.right - self._sc(12), fr.centery)))
            else:
                ph = "Optional" if key.startswith("notes_") else ""
                ts = (self.fnt["input"].render(val, True, (40, 50, 65)) if val
                      else self.fnt["input"].render(ph, True, (185, 198, 215)))
                surface.blit(ts, ts.get_rect(midleft=(fr.x + self._sc(12), fr.centery)))
                if active and val:
                    cx2 = fr.x + self._sc(12) + ts.get_width() + 2
                    pygame.draw.line(surface, (40, 160, 220),
                                     (cx2, fr.centery - self._sc(10)),
                                     (cx2, fr.centery + self._sc(10)), 2)

        for i, (key, lbl, kind, opts) in enumerate(fields):
            _draw_ep_field(key, lbl, kind, opts, i)

        # Buttons -- Delete lives on the Patient Information section only.
        btn_y = mr.bottom - btn_h - pad
        bw    = self._sc(120)
        self._ep_save_rect   = pygame.Rect(mr.right - pad - bw, btn_y, bw, btn_h)
        self._ep_cancel_rect = pygame.Rect(self._ep_save_rect.x - self._sc(10) - bw,
                                           btn_y, bw, btn_h)
        if getattr(self, "_ep_section", None) in (None, "info"):
            dw = self.fnt["small"].size("Delete Patient")[0] + self._sc(24)
            self._ep_delete_rect = pygame.Rect(mr.x + pad, btn_y, dw, btn_h)
        else:
            self._ep_delete_rect = pygame.Rect(0, 0, 1, 1)

        msg = self._ep_error or self._ep_success
        if msg:
            mc = (210, 50, 50) if self._ep_error else (50, 175, 75)
            surface.blit(self.fnt["modal_err"].render(msg, True, mc),
                         (mr.x + pad, btn_y - self.fnt["modal_err"].get_height() - self._sc(4)))

        btns = [(self._ep_save_rect,   (40,160,220), (25,125,180), self._ep_save_hov,   "Save",   self.fnt["btn"]),
                (self._ep_cancel_rect, (160,175,195),(130,145,165),self._ep_cancel_hov, "Cancel", self.fnt["btn"])]
        if self._ep_delete_rect.width > 1:
            btns.append((self._ep_delete_rect, (200,50,50), (165,28,28),
                         self._ep_delete_hov, "Delete Patient", self.fnt["small"]))
        for rect, cn, ch, hov, lbl, fnt in btns:
            pygame.draw.rect(surface, ch if hov else cn, rect, border_radius=10)
            s = fnt.render(lbl, True, (255, 255, 255))
            surface.blit(s, s.get_rect(center=rect.center))

        # Open dropdown last so it paints over the fields; flips upward when it
        # would fall off the bottom of the modal.
        for key, (fr, _r, opts) in list(self._ep_drop_rects.items()):
            if not self._ep_drop_open.get(key) or not opts:
                continue
            opt_h = self._tt(42)
            lst_h = len(opts) * opt_h + 4
            base  = fr.top - lst_h if fr.bottom + lst_h > mr.bottom else fr.bottom
            pygame.draw.rect(surface, (244, 250, 255),
                             pygame.Rect(fr.x, base, fr.width, lst_h), border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220),
                             pygame.Rect(fr.x, base, fr.width, lst_h), 2, border_radius=9)
            opt_rects, mp = [], pygame.mouse.get_pos()
            for j, ov in enumerate(opts):
                orr = pygame.Rect(fr.x, base + j * opt_h, fr.width, opt_h)
                if orr.collidepoint(mp):
                    pygame.draw.rect(surface, (214, 234, 255), orr, border_radius=7)
                ts2 = self.fnt["input"].render(ov, True, (40, 50, 65))
                surface.blit(ts2, ts2.get_rect(midleft=(orr.x + self._sc(12), orr.centery)))
                opt_rects.append(orr)
            self._ep_drop_rects[key] = (fr, opt_rects, opts)

    def _handle_share_key(self, event):
        if event.key == pygame.K_ESCAPE:
            if self._share_stage == "confirm":
                self._share_stage = "choice"           # back one step
            elif self._share_stage == "choice":
                self._share_stage             = "pick"
                self._share_confirm_therapist = None
            else:
                self._share_modal_open = False
            return None
        if self._share_stage != "pick":
            return None  # swallow all other keys once past the picker
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

    def _do_share_or_transfer_confirm(self):
        """Final Yes on the confirm screen. SHARE and TRANSFER are genuinely
        different operations at the data layer, not two flavours of the same
        call: share_patient() only ever inserts a patient_shares row (the
        owner is unchanged); transfer_patient() reassigns patients.therapist_id
        itself, so the target becomes the new owner and this therapist loses
        owner permissions on this patient."""
        target = self._share_confirm_therapist
        patient = self.share_modal_patient
        if not target or not patient:
            self._share_error = "No therapist selected."; return

        if self._share_pending_action == "transfer":
            ok = self.db.transfer_patient(patient["id"], target["id"],
                                          acting_therapist_id=self.account["id"])
            if ok:
                self._share_success = (f"{patient['full_name']} transferred to "
                                       f"{target['full_name']}. You are no longer the owner.")
                patient["therapist_id"] = target["id"]      # keep the in-memory row in step
                if self.selected_patient and self.selected_patient.get("id") == patient["id"]:
                    self._set_selected_patient(None)          # no longer ours to run sessions with
                self.patients = (self.db.get_all_patients(therapist_id=self.account["id"])
                                 if hasattr(self.db, "get_all_patients") else self.patients)
            else:
                self._share_error = "Transfer failed. Try again."
        else:
            ok = self.db.share_patient(patient["id"], target["id"], self.account["id"])
            if ok:
                self._share_success = f"Shared with {target['full_name']}."
            else:
                self._share_error = "Share failed. Try again."

        self._share_stage             = "pick"
        self._share_pending_action    = None
        self._share_confirm_therapist = None
        self._share_suggestions       = []
        self._share_input             = ""
        if ok:
            self._share_error = ""

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

        # Tapping the big preview (or the "Change Icon" prompt beneath it)
        # opens the dedicated picker popup instead of an inline rail.
        bcx, bcy = self.edit_big_center
        if math.hypot(pos[0]-bcx, pos[1]-bcy) <= self.edit_big_r + self._sc(10):
            play_click()
            self._open_icon_picker(); return None
        if self.edit_change_icon_rect.collidepoint(pos):
            play_click()
            self._open_icon_picker(); return None

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

        if self.edit_save_rect.collidepoint(pos):
            play_click()
            return self._attempt_save()
        if self.edit_cancel_rect.collidepoint(pos):
            play_click()
            self.modal = None
        if self.edit_delete_rect.collidepoint(pos):
            play_confirm_alert(); self.modal = "delete_confirm"
        return None

    # ──────────────────────────────────────────────────────────────────
    #  EDIT PROFILE — ICON PICKER POPUP
    #  A dedicated, larger, scrollable grid of all 10 icons, opened from the
    #  big preview / "Change Icon" prompt in the main Edit Profile modal.
    #  Tapping an icon sets edit_selected_icon immediately (same underlying
    #  state and _attempt_save() persistence as before -- only HOW the icon
    #  is chosen changed, not what happens with the choice).
    # ──────────────────────────────────────────────────────────────────

    def _open_icon_picker(self):
        self.edit_icon_picker_open = True
        self._eip_scroll = 0
        self._eip_drag_y = None

    def _handle_icon_picker_click(self, pos):
        if self._eip_up_rect.collidepoint(pos):
            play_click()
            self._eip_scroll = max(0, self._eip_scroll - int(160 * self._fs))
            return None
        if self._eip_down_rect.collidepoint(pos):
            play_click()
            self._eip_scroll = min(self._eip_scroll_max, self._eip_scroll + int(160 * self._fs))
            return None
        if self._eip_done_rect.collidepoint(pos):
            play_click()
            self.edit_icon_picker_open = False
            return None
        for (cx, cy, idx) in self._eip_circles:
            if math.hypot(pos[0] - cx, pos[1] - cy) <= self._eip_r:
                play_click()
                self.edit_selected_icon = idx
                return None
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
        idx=self.edit_selected_icon
        if not fn:   self.edit_error="Full Name required.";      return None
        if not un:   self.edit_error="Username required.";       return None
        if not un.isalpha(): self.edit_error="Username: letters only."; return None
        if not role: self.edit_error="Please select a role.";    return None
        if not wp:   self.edit_error="Workplace required.";      return None
        if idx==0:   self.edit_error="Please choose an icon.";   return None
        if un!=self.account["username"] and self.db.username_exists(un):
            self.edit_error="Username already taken."; return None
        # new_pin is intentionally never passed here -- the PIN is only
        # changeable through the forgot-PIN flow on the Login page.
        ok=self.db.update_therapist(self.account["id"],fn,un,role,wp,idx,
                                    new_pin=None)
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
            play_click()
            self._rp_submit(); return

        for key in ["sex_open","dominant_open","affected_open","stroke_open"]:
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
                            play_click()
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
        ]
        for (field_key, open_key, opts) in drop_map:
            info = self._rp_drop_rects.get(field_key)
            if info:
                field_rect = info[0]
                if field_rect.collidepoint(pos):
                    play_click()
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

    # Registration must ask for every field the Patient Info page shows.
    # Patient Information + Stroke & Therapy are required; Clinical Notes are
    # optional (notes_* are deliberately absent from this list).
    _RP_REQUIRED = [
        ("full_name",      "Full Name"),
        ("age",            "Age"),
        ("sex",            "Sex"),
        ("stroke_type",    "Stroke Type"),
        ("date_of_stroke", "Stroke Onset Date"),
        ("months_stroke",  "Months Since Stroke"),
        ("dominant_hand",  "Dominant Hand"),
        ("affected_hand",  "Affected Hand"),
    ]

    def _rp_submit(self):
        rp = self.rp
        for key, label in self._RP_REQUIRED:
            if not str(rp.get(key, "")).strip():
                rp["error"] = f"{label} is required."
                return
        if not rp["age"].strip().isdigit():
            rp["error"] = "Age must be a number."; return
        if not rp["months_stroke"].strip().isdigit():
            rp["error"] = "Months Since Stroke must be a number."; return
        name = rp["full_name"].strip()
        try:
            pid = self.db.create_patient(rp, self.account["id"]) if hasattr(self.db, 'create_patient') else None
            if pid is None:
                rp["error"] = "Registration failed. Please try again."
                return
            self.patients = (
                self.db.get_all_patients(therapist_id=self.account["id"])
                if hasattr(self.db, 'get_all_patients') else []
            )
        except Exception:
            rp["error"] = "An error occurred. Please try again."
            return
        self._init_register_state()
        self._rp_success_msg = f"Patient '{name}' registered successfully.\nID: {pid}"
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
            if key in ("age", "months_stroke") and (
                    not event.unicode.isdigit() or len(rp[key]) >= 3):
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
                play_click()
                self._gc_skill_modal_open = False
                return
            for (gr, game_name) in self._gc_skill_modal_rects:
                if gr.collidepoint(pos):
                    play_click()
                    gc["selected_game"] = (game_name, self._gc_skill_modal_type)
                    gc["preset_applied"] = False
                    self._gc_skill_modal_open = False
                    return
            self._gc_skill_modal_open = False
            return

        for (tr, game_tuple) in self._game_tiles:
            if tr.collidepoint(pos):
                play_click()
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
        # ── "Session in Progress" screen (panel 7) ──
        if self.active_panel == 7:
            self._sm_update(mouse_pos)

        # ── BLE controller ownership (dual-monitor) ──
        # The therapist process holds the controller while a patient is selected
        # and we are NOT on "Session in Progress" (select -> Game Config ->
        # calibration all read the live sensor here). Entering panel 7 releases
        # it so the patient process can take it for the game; leaving panel 7
        # with a patient still selected reclaims it. Deselect always releases.
        if _DUAL_MONITOR and _ble_receiver is not None:
            want_ble = bool(self.selected_patient) and self.active_panel != 7
            if want_ble != self._ble_want:
                self._ble_want = want_ble
                try:
                    _ble_receiver.set_enabled(want_ble)
                except Exception:
                    pass

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
        self._theme_hov        = self._theme_btn_rect.collidepoint(mouse_pos)
        self._ctrl_hov         = self._ctrl_btn_rect.collidepoint(mouse_pos)

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
            # Light/dark toggle inside the calibration window -> sync BOTH
            # interfaces immediately (no reload / new session / navigation).
            self._apply_theme(bool(self._cal_win.dark_mode))
            if self._cal_win.done:
                self.calibration_done   = True
                self.calibration_result = self._cal_win.calibration_result
                self._sync_dur_from_cal(self._cal_win)
                self._cal_win           = None
                if _DUAL_MONITOR:
                    therapist_link.calibrate_end()
                pt_id = (self.selected_patient or {}).get("id")
                if pt_id and hasattr(self.db, "save_calibration"):
                    game_name = (self.gc.get("selected_game") or (None,))[0] or ""
                    self.db.save_calibration(
                        pt_id, self.account["id"],
                        self.calibration_result,
                        game_name=game_name,
                    )
            elif self._cal_win.cancelled:
                self._cal_win = None
                if _DUAL_MONITOR:
                    therapist_link.calibrate_end()

        # ── Share modal hover states ──
        self._share_search_hov  = self._share_search_rect.collidepoint(mouse_pos)
        self._share_confirm_hov = self._share_confirm_rect.collidepoint(mouse_pos)
        self._share_close_hov   = self._share_close_rect.collidepoint(mouse_pos)
        self._share_yes_hov     = self._share_yes_rect.collidepoint(mouse_pos)
        self._share_no_hov      = self._share_no_rect.collidepoint(mouse_pos)
        self._share_choice_share_hov    = self._share_choice_share_rect.collidepoint(mouse_pos)
        self._share_choice_transfer_hov = self._share_choice_transfer_rect.collidepoint(mouse_pos)

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
        if self.modal in ("logout_confirm","delete_confirm","delete_patient_confirm",
                          "select_patient_confirm","deselect_patient_confirm"):
            yr, nr = self._confirm_rects()
            self.confirm_yes_hov = yr.collidepoint(mouse_pos)
            self.confirm_no_hov  = nr.collidepoint(mouse_pos)

        # ── Calibration mismatch modal hover ──
        if self.modal == "calibration_mismatch":
            self._mismatch_cal_hov    = self._mismatch_cal_rect.collidepoint(mouse_pos)
            self._mismatch_cancel_hov = self._mismatch_cancel_rect.collidepoint(mouse_pos)

        # ── Home card hover ──
        for i, cr in enumerate(self.card_rects):
            self.card_hovered[i] = (self.active_panel == -1 and cr.collidepoint(mouse_pos))

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
            7: self._sm_draw,               # dual-monitor "Session in Progress"
            8: self._draw_patient_preview,  # review a patient (does NOT select them)
        }
        if self.active_panel in panel_drawers:
            # Panel 0 (Patient List) is the dashboard home now -- no Back button,
            # no breadcrumb shell; it draws its own header and gets the full
            # height (reclaim the header band the other panels reserve).
            pa = self._panel_area()
            if self.active_panel != 0:
                self._draw_panel_shell(surface, self.active_panel)
            else:
                # Touch: the card itself still starts right under the close
                # (X) button -- only its header CONTENT is padded down away
                # from that top edge (see _draw_patient_list's head_y), to
                # match the top-right bar without shrinking the card itself.
                top = (46 + self._sc(10)) if self._touch_ui else int(self.HEIGHT * 0.06)
                pa = pygame.Rect(pa.x, top, pa.width,
                                 self.HEIGHT - top - int(self.HEIGHT * 0.025))
            panel_drawers[self.active_panel](surface, pa)

        # Clock/date + theme toggle float above the panel's own content
        # (painted after it, not inside _draw_sidebar) so no panel's
        # background card can ever wash them out. Always present now --
        # _panel_area()/panel 0's own header both clear this bar's height.
        self._draw_top_right_bar(surface)

        if self.modal == "edit_profile":
            self._draw_overlay(surface); self._draw_edit_modal(surface)
            if self.edit_icon_picker_open:
                self._draw_overlay(surface); self._draw_icon_picker_popup(surface)
        elif self.modal in ("logout_confirm","delete_confirm"):
            self._draw_overlay(surface); self._draw_confirm_modal(surface)
        elif self.modal == "select_patient_confirm":
            self._draw_overlay(surface); self._draw_select_confirm_modal(surface)
        elif self.modal == "deselect_patient_confirm":
            self._draw_overlay(surface); self._draw_deselect_confirm_modal(surface)
        elif self.modal == "register_success":
            self._draw_overlay(surface); self._draw_register_success_modal(surface)
        elif self.modal == "calibration_mismatch":
            self._draw_overlay(surface); self._draw_calibration_mismatch_modal(surface)
        elif self.modal == "delete_blocked":
            self._draw_overlay(surface); self._draw_delete_blocked_modal(surface)

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

        # (Session in Progress = panel 7, drawn via panel_drawers above)

        if self.alpha < 255:
            self.fade_surface.set_alpha(255-self.alpha)
            surface.blit(self.fade_surface, (0,0))

    # ──────────────────────────────────────────────────────────────────
    #  SIDEBAR
    # ──────────────────────────────────────────────────────────────────

    def _draw_sidebar(self, surface):
        W, H, sw = self.WIDTH, self.HEIGHT, self.sidebar_w
        # Solid (opaque) panel -- was a translucent wash over the gradient.
        sb = pygame.Surface((sw, H), pygame.SRCALPHA)
        sb.fill((230, 240, 252, 255)); surface.blit(sb, (0,0))
        hl = pygame.Surface((sw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200)); surface.blit(hl, (0, 0))
        pygame.draw.line(surface, (200, 216, 236), (sw,0), (sw,H), 1)

        # Logo centred in the rail -- the clock/date used to sit beside/under
        # it (now moved to the top-right, alongside the theme toggle), which
        # left the wordmark looking off-balance pinned to the left edge.
        ly = int(H*0.05)
        s1 = self.fnt["logo"].render("Recov", True, (45,60,80))
        s2 = self.fnt["logo"].render("R",     True, (215,40,40))
        logo_w = s1.get_width() + s2.get_width()
        lx = (sw - logo_w) // 2
        surface.blit(s1, s1.get_rect(midleft=(lx, ly)))
        surface.blit(s2, s2.get_rect(midleft=(lx+s1.get_width(), ly)))

        # "Hand Rehabilitation System" removed from under the wordmark -- the
        # logo now flows straight into the profile card below it.
        stack_y = ly + s1.get_height() // 2

        if self._touch_ui:
            # Flow from the measured bottom of the clock/date block. The old
            # fixed 0.205*H put the card at y=98 while the date ran to y=105,
            # so the two overlapped on the 480px-tall panel.
            pc_y = stack_y + self._sc(10)
            pc_h = self._tt(76)
        else:
            pc_y = int(H*0.11); pc_h = int(H*0.13)
        pc_r = pygame.Rect(int(sw*0.05), pc_y, int(sw*0.90), pc_h)
        # Solid white card with a soft shadow (was a translucent blue box).
        pc_shadow = pc_r.move(0, max(2, int(3 * self._fs)))
        pygame.draw.rect(surface, (200, 214, 234), pc_shadow, border_radius=14)
        pygame.draw.rect(surface, (255, 255, 255), pc_r, border_radius=14)
        pygame.draw.rect(surface, (222, 232, 246), pc_r, 1, border_radius=14)
        f_nm  = self.fnt["profile_nm"]
        f_sub = self.fnt["profile"]

        def _fit(txt, fnt, avail):
            if fnt.size(txt)[0] <= avail:
                return txt
            while txt and fnt.size(txt + "…")[0] > avail:
                txt = txt[:-1]
            return txt + "…"

        if self._touch_ui:
            # 184px-wide rail: two rows -- [icon] name, then the Edit Profile
            # link on its own full-width line. The Role is dropped here; it is
            # still editable (and visible) in the Edit Profile modal.
            pad_c = self._sc(8)
            ir = self._sc(15)
            ix = pc_r.x + pad_c + ir
            iy = pc_r.y + pad_c + ir
            draw_icon(surface, self.account.get("icon_index", 1), ix, iy, ir, shadow=True)
            tx = ix + ir + self._sc(8)
            surface.blit(
                f_nm.render(_fit(self.account["full_name"], f_nm,
                                 pc_r.right - tx - pad_c), True, (40, 55, 75)),
                (tx, iy - f_nm.get_height() // 2))
            ec = (50, 120, 200) if self.edit_link_hovered else (75, 140, 210)
            es = f_sub.render("Edit Profile", True, ec)
            ep = (pc_r.x + pad_c, pc_r.bottom - pad_c - es.get_height())
            surface.blit(es, ep)
            self._edit_link_rect = pygame.Rect(
                pc_r.x, ep[1] - self._sc(6),
                pc_r.width, es.get_height() + self._sc(12))
        else:
            ir = int(44*(H/1080))
            ix = pc_r.x + int(sw*0.11) + ir
            iy = pc_r.centery
            draw_icon(surface, self.account.get("icon_index",1), ix, iy, ir, shadow=False)
            tx  = ix + ir + int(12*(W/1920))
            avail = pc_r.right - tx - int(8*W/1920)
            line_h = f_nm.get_height()
            surface.blit(f_nm.render(_fit(self.account["full_name"], f_nm, avail), True, (40,55,75)),
                         (tx, iy - line_h - int(2*H/1080)))
            surface.blit(f_sub.render(_fit(self.account.get("role",""), f_sub, avail), True, (100,115,140)),
                         (tx, iy + int(3*H/1080)))
            ec  = (50,120,200) if self.edit_link_hovered else (75,140,210)
            es  = f_sub.render("Edit Profile", True, ec)
            ep  = (tx, iy + int(3*H/1080) + f_sub.get_height() + int(4*H/1080))
            surface.blit(es, ep)
            self._edit_link_rect = pygame.Rect(ep[0]-int(8*W/1920), ep[1]-int(8*H/1080),
                                               es.get_width()+int(16*W/1920),
                                               es.get_height()+int(16*H/1080))

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

        # ── Controller status, then Active Patient directly below it --
        #    the connection status is the more time-sensitive of the two, so
        #    it reads first, with the patient identity underneath it. ──
        stack_y = pc_r.bottom + (self._sc(10) if self._touch_ui else int(20*H/1080))
        stack_y = self._draw_controller_monitor(surface, sw, stack_y)

        if self.selected_patient:
            bpad = self._sc(8) if self._touch_ui else int(12*W/1920)
            label_max_w = int(sw * 0.90) - bpad * 2
            f_bl = self.fnt["tag"] if self._touch_ui else self.fnt["small"]
            # "PATIENT" (not "ACTIVE PATIENT") -- the longer label didn't fit
            # this rail's width even at the smallest label font and always
            # truncated to "ACTIVE PATI...", which reads as a mistake rather
            # than an intentional shortening on a label that never changes.
            # _fit() is kept as a safety net for narrower rails still.
            f_bl_txt = _fit("PATIENT", f_bl, label_max_w)
            pn = (self.fnt["body_b"] if self._touch_ui else self.fnt["label"])
            pname = self.selected_patient.get("full_name", "—")
            _wrapped = self._wrap(pname, pn, label_max_w)
            name_lines = _wrapped[:2]
            if len(_wrapped) > 2:                    # 3rd+ line -- ellipsize the 2nd
                name_lines[1] = _fit(name_lines[1] + "…", pn, label_max_w)

            badge_y = stack_y + (self._sc(8) if self._touch_ui else int(12*H/1080))
            line_h = pn.get_height()
            name_block_h = line_h * len(name_lines)
            bh = (self._sc(6) + f_bl.get_height() + self._sc(4) + name_block_h + self._sc(8))
            bh = max(bh, self._tt(60) if self._touch_ui else int(60*H/1080))
            badge_r = pygame.Rect(int(sw*0.05), badge_y, int(sw*0.90), bh)
            pygame.draw.rect(surface, (232,245,255), badge_r, border_radius=10)
            pygame.draw.rect(surface, (140,195,240), badge_r, 1, border_radius=10)
            surface.blit(f_bl.render(f_bl_txt, True, (90,120,160)),
                         (badge_r.x+bpad, badge_r.y+self._sc(6)))
            ny = badge_r.bottom - self._sc(8) - name_block_h
            for ln in name_lines:
                surface.blit(pn.render(ln, True, (40,80,140)), (badge_r.x+bpad, ny))
                ny += line_h
            stack_y = badge_r.bottom

        lr = self._logout_rect()
        # The old sidebar-bottom theme button is gone -- the icon-based
        # toggle in _draw_top_right_bar (called from draw(), on every panel)
        # is now the only theme control.

        logout_img = _img_fit("logout_button.png", lr.width, lr.height)
        if logout_img is not None:
            surface.blit(logout_img, logout_img.get_rect(center=lr.center))
            if self.logout_hovered:
                hi = pygame.Surface(lr.size, pygame.SRCALPHA)
                pygame.draw.rect(hi, (255, 255, 255, 40), hi.get_rect(), border_radius=10)
                surface.blit(hi, lr.topleft)
        else:
            lc = (165,25,25) if self.logout_hovered else (205,45,45)
            pygame.draw.rect(surface, lc, lr, border_radius=10)
            ls = self.fnt["btn"].render("Logout", True, (255,255,255))
            surface.blit(ls, ls.get_rect(center=lr.center))

    def _draw_top_right_bar(self, surface):
        """Calendar/time pill + the Light/Dark theme toggle + the close (X)
        button's reserved slot, top-right of the whole window -- moved out
        of the sidebar so the wordmark could be centred. All three share one
        container height (_bar_height()) and sit in one row, left to right:
        [date/time pill] [Light/Dark toggle] [close button].

        The close (X) button itself is drawn by main.py (always on top, so
        it still works over modals/overlays) -- this method only reserves
        and publishes self._close_btn_rect, which main.py reads each frame
        instead of using a fixed screen-corner position. That rect is
        published unconditionally (not patient-dependent), since the close
        button must always be reachable.

        The theme toggle keeps its exact original behaviour: it belongs to
        the selected patient, so with nobody selected it is not drawn and
        self._theme_btn_rect collapses to (0,0,1,1) so a stray tap can't
        fire it -- only WHERE/HOW it is drawn changed, not the logic.
        """
        top    = self._bar_top()
        # Right edge = the panel card's own right edge (not the raw screen
        # edge), inset enough to stay clear of its rounded corner -- this is
        # what keeps the row from visually spilling past the card.
        card_right = self._panel_area().right
        pad_r  = self._sc(20)
        gap    = self._sc(10)
        row_h  = self._bar_height()      # shared container height for all three controls

        # ── Close (X) button slot -- always reserved, rightmost ──────────
        close_r = pygame.Rect(card_right - pad_r - row_h, top, row_h, row_h)
        self._close_btn_rect = close_r

        # ── Light | Dark toggle -- icons only now, sized to just fit the
        #    two knob positions ("shorten the toggle to fit just the
        #    circles" instead of the old label-driven width) ──────────────
        track_h = row_h
        if self.selected_patient:
            dark = self._applied_theme_dark
            tog_w = track_h * 2
            tr = pygame.Rect(close_r.left - gap - tog_w, top, tog_w, track_h)
            self._theme_btn_rect = tr

            track_col = (34, 46, 66) if dark else (210, 222, 240)
            pygame.draw.rect(surface, track_col, tr, border_radius=track_h // 2)
            pygame.draw.rect(surface, (255, 255, 255) if not self._theme_hov else (235, 240, 248),
                             tr, max(1, int(2 * self._fs)), border_radius=track_h // 2)
            knob_d  = track_h - self._sc(6)
            knob_cx = (tr.right - track_h // 2) if dark else (tr.left + track_h // 2)
            knob_img = _img("dark_mode.png" if dark else "light_mode.png", knob_d)
            if knob_img is not None:
                surface.blit(knob_img, knob_img.get_rect(center=(knob_cx, tr.centery)))
            else:
                pygame.draw.circle(surface, (255, 255, 255), (knob_cx, tr.centery), knob_d // 2)
                pygame.draw.circle(surface, (190, 200, 215), (knob_cx, tr.centery), knob_d // 2, 1)
            anchor_left = tr.left
        else:
            self._theme_btn_rect = pygame.Rect(0, 0, 1, 1)
            anchor_left = close_r.left

        # Date/time pill -- calendar icon + two stacked lines, sized with its
        # OWN small fonts (not fonts sized for other controls) so both lines
        # sit fully inside the pill instead of touching its top/bottom edge.
        pill_h = row_h
        now = datetime.datetime.now()
        f_time = pygame.font.SysFont("segoeui,arial", int(16 * self._fs), bold=True)
        f_date = pygame.font.SysFont("segoeui,arial", int(12 * self._fs))
        t_surf = f_time.render(now.strftime("%I:%M %p"), True, (55, 74, 104))
        d_surf = f_date.render(now.strftime("%b %d, %Y"), True, (110, 128, 150))
        cal_sz = int(pill_h * 0.55)
        gap_in = self._sc(8)
        text_w = max(t_surf.get_width(), d_surf.get_width())
        pill_w = self._sc(12) + cal_sz + gap_in + text_w + self._sc(14)
        pill_r = pygame.Rect(0, top, pill_w, pill_h)
        pill_r.right = anchor_left - gap

        pygame.draw.rect(surface, (255, 255, 255), pill_r, border_radius=pill_h // 2)
        pygame.draw.rect(surface, (222, 232, 246), pill_r, 1, border_radius=pill_h // 2)
        cal_img = _img("calendar.png", cal_sz)
        cx = pill_r.x + self._sc(12)
        if cal_img is not None:
            surface.blit(cal_img, cal_img.get_rect(midleft=(cx, pill_r.centery)))
            cx += cal_sz + gap_in
        line_gap = self._sc(2)
        block_h = t_surf.get_height() + line_gap + d_surf.get_height()
        ty = pill_r.centery - block_h // 2
        surface.blit(t_surf, (cx, ty))
        surface.blit(d_surf, (cx, ty + t_surf.get_height() + line_gap))

    # ──────────────────────────────────────────────────────────────────
    #  ESP32 CONTROLLER CONNECTION MONITOR
    # ──────────────────────────────────────────────────────────────────

    #   stage -> (label, dot colour, text colour)
    _CTRL_LOOK = {
        "connected":     ("Controller connected", (40, 190, 90),  (28, 130, 66)),
        "stalled":       ("Signal stalled",       (230, 165, 30), (166, 112, 12)),
        "connecting":    ("Connecting…",     (230, 165, 30), (166, 112, 12)),
        "scanning":      ("Searching…",      (230, 165, 30), (166, 112, 12)),
        "handed_off":    ("On patient screen",    (60, 140, 225), (40, 100, 175)),
        "idle":          ("Controller idle",      (172, 184, 198), (118, 132, 150)),
        "disabled":      ("Controller off",       (172, 184, 198), (118, 132, 150)),
        "old_firmware":  ("Old firmware",         (215, 60, 55),  (170, 40, 36)),
        "bluetooth_off": ("Bluetooth is off",     (215, 60, 55),  (170, 40, 36)),
        "no_bleak":      ("bleak not installed",  (215, 60, 55),  (170, 40, 36)),
        "no_permission": ("No BLE permission",    (215, 60, 55),  (170, 40, 36)),
        "error":         ("Controller error",     (215, 60, 55),  (170, 40, 36)),
    }

    def _controller_status(self):
        """(stage, label, detail, dot_col, txt_col) for the controller monitor.

        Handoff-aware: with RECOVR_DUAL_MONITOR the therapist process gives the
        controller up on purpose (no patient selected, or the patient process is
        running the game), so 'not connected' there is normal, not a fault."""
        st = {}
        if _ble_receiver is not None:
            try:
                st = _ble_receiver.status()
            except Exception:
                st = {}

        # Keep every detail line short -- the sidebar rail is ~200 px wide.
        if _DUAL_MONITOR and self.active_panel == 7:
            stage, detail = "handed_off", "used by the game"
        elif _DUAL_MONITOR and not self.selected_patient:
            stage, detail = "idle", "select a patient"
        else:
            stage  = st.get("stage", "error")
            detail = st.get("detail", "")
            if stage == "connected":
                age = st.get("data_age")
                if age is not None and age > 2.0:
                    stage, detail = "stalled", f"no data {age:.0f}s"
                else:
                    detail = st.get("device") or "sensor live"
            elif stage == "scanning":
                n = len(st.get("seen") or [])
                s = st.get("scans", 0)
                detail = f"scan {s} · {n} nearby" if n else f"scan {s} · none nearby"
            elif stage == "connecting":
                detail = st.get("device") or "pairing"
            elif stage == "bluetooth_off":
                detail = "turn Bluetooth on"
            elif stage == "no_permission":
                detail = "see console hint"
            elif stage == "no_bleak":
                detail = "pip install bleak"
            elif stage == "old_firmware":
                detail = "re-flash the ESP32"

        label, dot, txt = self._CTRL_LOOK.get(stage, self._CTRL_LOOK["error"])
        return stage, label, detail, dot, txt

    def _draw_controller_monitor(self, surface, sw, top_y):
        """Compact always-visible ESP32 status block, now positioned right
        under the profile card (top-anchored -- grows downward from `top_y`)
        so it reads ABOVE Active Patient. Tapping it forces a fresh BLE scan.
        Returns the y just below the block for whatever comes next."""
        W, H = self.WIDTH, self.HEIGHT
        stage, label, detail, dot_col, txt_col = self._controller_status()

        bh = self._tt(62) if self._touch_ui else max(int(58 * H / 1080), 44)
        r  = pygame.Rect(int(sw * 0.05), top_y, int(sw * 0.90), bh)
        self._ctrl_btn_rect = r

        bg = (247, 250, 254) if not self._ctrl_hov else (236, 243, 252)
        pygame.draw.rect(surface, bg, r, border_radius=10)
        pygame.draw.rect(surface, (196, 212, 232), r, 1, border_radius=10)

        # status dot -- pulses while it is actively trying to connect
        dr = max(4, int(6 * self._fs))
        cx = r.x + int(12 * W / 1920) + dr
        cy = r.y + int(14 * H / 1080) + dr
        if stage in ("scanning", "connecting"):
            t = (pygame.time.get_ticks() % 1200) / 1200.0
            pulse = 1.0 + 0.45 * abs(1.0 - 2.0 * t)
            pygame.draw.circle(surface, (245, 226, 190), (cx, cy), int(dr * pulse * 1.7))
        pygame.draw.circle(surface, dot_col, (cx, cy), dr)

        # Label -- ellipsize (never overflow the card) rather than shrink,
        # since the dot + right padding already fix its available width.
        label_x = cx + dr + int(9 * W / 1920)
        avail_lab = r.right - int(10 * W / 1920) - label_x
        f_lab = self.fnt["small"]
        lab_txt = label
        if f_lab.size(lab_txt)[0] > avail_lab:
            while lab_txt and f_lab.size(lab_txt + "…")[0] > avail_lab:
                lab_txt = lab_txt[:-1]
            lab_txt += "…"
        ls = f_lab.render(lab_txt, True, txt_col)
        surface.blit(ls, (label_x, r.y + int(7 * H / 1080)))

        if detail:
            ds = self.fnt["small_i"].render(detail, True, (128, 142, 162))
            avail = r.width - int(18 * W / 1920)
            if ds.get_width() > avail:                     # ellipsize
                txt = detail
                while txt and self.fnt["small_i"].size(txt + "…")[0] > avail:
                    txt = txt[:-1]
                ds = self.fnt["small_i"].render(txt + "…", True, (128, 142, 162))
            surface.blit(ds, (r.x + int(12 * W / 1920),
                              r.bottom - ds.get_height() - int(6 * H / 1080)))
        return r.bottom

    def _share_icon(self, surface, cx, cy, s, col):
        """A right-pointing arrow whose shaft arches gently upward -- 'send this
        patient onward to another therapist'. Icon-only, vector-drawn to match
        the rest of the RecovR glyphs."""
        lw = max(2, int(s * 0.16))
        # shaft: quadratic Bezier from the left, bowed upward, meeting the tip
        tip = (cx + s * 0.92, cy - s * 0.16)          # tip -- a hair above centre
        p0  = (cx - s * 0.98, cy + s * 0.10)
        p1  = (cx - s * 0.05, cy - s * 0.88)          # control -> the upward arch
        p2  = (tip[0] - s * 0.28, tip[1] + s * 0.04)
        pts = []
        for i in range(15):
            t = i / 14.0
            u = 1.0 - t
            pts.append((int(u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0]),
                        int(u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1])))
        pts.append((int(tip[0]), int(tip[1])))
        pygame.draw.lines(surface, col, False, pts, lw)
        # arrowhead -- points to the RIGHT (wings back toward upper-left / lower-left)
        hl, hw = s * 0.58, s * 0.52
        pygame.draw.line(surface, col, (int(tip[0]), int(tip[1])),
                         (int(tip[0] - hl), int(tip[1] - hw)), lw)
        pygame.draw.line(surface, col, (int(tip[0]), int(tip[1])),
                         (int(tip[0] - hl), int(tip[1] + hw)), lw)

    def _sun_moon_icon(self, surface, cx, cy, s, dark, col):
        """Small ☀ (light selected) / ☾ (dark selected) glyph."""
        if dark:
            pygame.draw.circle(surface, col, (cx, cy), s, 2)
            pygame.draw.circle(surface, (236, 242, 250), (cx + int(s * 0.55), cy - int(s * 0.35)),
                               int(s * 0.85))
        else:
            pygame.draw.circle(surface, col, (cx, cy), int(s * 0.6), 2)
            for k in range(8):
                import math
                a = k * math.pi / 4
                x1 = cx + int(math.cos(a) * s * 0.85); y1 = cy + int(math.sin(a) * s * 0.85)
                x2 = cx + int(math.cos(a) * s * 1.15); y2 = cy + int(math.sin(a) * s * 1.15)
                pygame.draw.line(surface, col, (x1, y1), (x2, y2), 2)

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

        hdr_h = max(int(50*(H/1080)), self._tt(46))
        hdr = pygame.Rect(pa.x, pa.y-hdr_h-int(10*(H/1080)), pa.width, hdr_h)

        if idx in (4, 5, 6, 7, 8):
            back_w = max(int(140*(W/1920)), self._tt(128))
            back_r = pygame.Rect(hdr.x, hdr.y, back_w, hdr.height)
            glass_back = pygame.Surface((back_r.width, back_r.height), pygame.SRCALPHA)
            glass_back.fill((225, 238, 255, 180)); surface.blit(glass_back, back_r.topleft)
            pygame.draw.rect(surface, (150,180,215), back_r, 2, border_radius=8)
            bs = self.fnt["btn"].render("Back", True, (60,100,165))
            surface.blit(bs, bs.get_rect(center=back_r.center))
            self._back_btn_rect = back_r
            crumb_x = back_r.right + int(20*(W/1920))
        else:
            self._back_btn_rect = pygame.Rect(0, 0, 1, 1)
            crumb_x = hdr.x + int(12*(W/1920))

        crumbs = self._breadcrumb(idx)          # list of (label, target|None)
        self._crumb_rects = []
        # on the 7-inch panel the chain must not clip -> smaller crumb font,
        # tight separators, big (full-height) hit rects still.
        cf   = self.fnt["breadcrumb"] if self._touch_ui else self.fnt["breadcrumb"]
        sep_f = self.fnt["breadcrumb"]
        sep_txt = " › " if self._touch_ui else "  ›  "
        cx   = crumb_x
        last = len(crumbs) - 1
        for j, (label, target) in enumerate(crumbs):
            clickable = target is not None          # any crumb with a target navigates
            if clickable:
                col = (55, 110, 185)
            else:
                col = (26, 40, 60) if j == last else (135, 150, 175)
            cs = cf.render(label, True, col)
            tx = cx
            ty = hdr.centery - cs.get_height() // 2
            surface.blit(cs, (tx, ty))
            if clickable:
                pygame.draw.line(surface, col, (tx, ty + cs.get_height() + 1),
                                 (tx + cs.get_width(), ty + cs.get_height() + 1), 2)
                hit = pygame.Rect(tx - int(8*W/1920), hdr.y,
                                  cs.get_width() + int(16*W/1920), hdr.height)
                self._crumb_rects.append((hit, target))
            cx += cs.get_width()
            if j < last:
                sp = sep_f.render(sep_txt, True, (180, 195, 215))
                surface.blit(sp, (cx, hdr.centery - sp.get_height() // 2))
                cx += sp.get_width()

    # Breadcrumb items as (label, target). target: None = current page (not
    # clickable); ("panel", n) = open panel n; ("patient", pt) = open that
    # patient's page (panel 8). There is NO "Preview" level any more.
    def _breadcrumb(self, idx):
        LIST = ("panel", 0)
        # Abbreviate only when the header is genuinely narrow (the 7-inch panel).
        # A 1280-wide touch laptop keeps the full labels.
        t = self.WIDTH <= 1080
        L_LIST = "List" if t else "Patient List"
        L_GC   = "Game Config" if t else "Game Configuration"
        L_SS   = "Start" if t else "Start Session"
        L_SIP  = "Session" if t else "Session in Progress"
        if idx == 6:
            return [(L_LIST, LIST), ("Register" if t else "Register Patient", None)]
        if idx == 8:
            name = (self.preview_patient or {}).get("full_name", "Patient")
            crumbs = [(L_LIST, LIST), (self._crumb_name(name), None)]
            # Game Configuration stays reachable as long as a patient is selected
            # -- from Info / Analytics / Calibration / Session History alike.
            if self.selected_patient:
                crumbs.append((L_GC, ("panel", 4)))
            return crumbs
        sel = self.selected_patient or {}
        pt_crumb = (self._crumb_name(sel.get("full_name", "Patient")),
                    ("patient", sel) if sel else None)
        if idx == 4:
            return [(L_LIST, LIST), pt_crumb, (L_GC, None)]
        if idx == 5:
            return [(L_LIST, LIST), pt_crumb, (L_GC, ("panel", 4)), (L_SS, None)]
        if idx == 7:
            # Active session: breadcrumb is display-only. Leaving a running
            # session goes through the panel-7 Back / STOP flow so nothing is
            # left stale.
            return [(L_LIST, None), (self._crumb_name(sel.get("full_name", "Patient")), None),
                    (L_GC, None), (L_SIP, None)]
        return [(PANEL_TITLES.get(idx, ""), None)]

    def _crumb_name(self, name):
        name = (name or "Patient").strip() or "Patient"
        limit = 13 if self.WIDTH <= 1080 else 22
        return name if len(name) <= limit else name[:limit - 1] + "…"

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 0: PATIENT LIST
    # ──────────────────────────────────────────────────────────────────

    def _draw_patient_list(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        self._patient_rows = []
        self._back_btn_rect = pygame.Rect(0, 0, 1, 1)   # panel 0 has no Back
        self._crumb_rects   = []                        # ... and no breadcrumb

        touch   = self._touch_ui
        pad     = int(16*W/1920)
        # panel-0 title (this panel is the dashboard home -- no breadcrumb shell)
        title = self.fnt["panel_title"].render("Patient List", True, (30, 44, 66))
        # Compact on touch -- the row-list viewport is tight on the 7-inch
        # panel, so this subtitle must not eat into scrollable list height.
        sub_font = (pygame.font.SysFont("segoeui,arial", int(16 * self._fs))
                   if touch else self.fnt["small"])
        subtitle = sub_font.render("Manage and view your patients.", True, (128, 145, 168))

        # Aligned with the top-right clock/theme bar's own row (not just a
        # tiny offset off the card's top edge) so the title doesn't hug the
        # box and both rows read as one aligned header line.
        head_y  = self._bar_top() if touch else (pa.y + int(10*H/1080))
        head_h  = title.get_height() + subtitle.get_height()
        ic_size = int(head_h * 0.92)
        ic_img  = _img("patient.png", ic_size)
        text_x  = pa.x + pad
        if ic_img is not None:
            surface.blit(ic_img, (pa.x + pad, head_y + (head_h - ic_size) // 2))
            text_x = pa.x + pad + ic_size + self._sc(10)
        surface.blit(title, (text_x, head_y))
        sub_y = head_y + title.get_height() + (0 if touch else self._sc(2))
        surface.blit(subtitle, (text_x, sub_y))
        top_y = sub_y + subtitle.get_height() + (self._sc(1) if touch else int(10*H/1080))

        sb_h    = self._tt(60)
        hint_w  = int((pa.width * 0.44) if not touch else (pa.width * 0.50))
        hint_r  = pygame.Rect(pa.x+pad, top_y, hint_w, sb_h)
        self._pt_search_rect = hint_r
        s_active = self._pt_search_active
        pygame.draw.rect(surface, (248,251,255), hint_r, border_radius=int(sb_h*0.4))
        s_border = (40,160,220) if s_active else (195,210,228)
        pygame.draw.rect(surface, s_border, hint_r, 2 if s_active else 1, border_radius=int(sb_h*0.4))
        # a small drawn magnifying-glass (no font-glyph dependency)
        gr = max(3, self._sc(6))
        gcx, gcy = hint_r.x + int(16*W/1920) + gr, hint_r.centery - int(gr*0.3)
        pygame.draw.circle(surface, (150, 168, 190), (gcx, gcy), gr, max(1, self._sc(2)))
        pygame.draw.line(surface, (150, 168, 190),
                         (gcx + int(gr*0.7), gcy + int(gr*0.7)),
                         (gcx + int(gr*1.6), gcy + int(gr*1.6)), max(1, self._sc(2)))
        text_x = gcx + int(gr*1.6) + int(10*W/1920)
        _ty = hint_r.y + (sb_h - self.fnt["input"].get_height()) // 2
        s_text = self._pt_search_text
        if s_text:
            s_surf = self.fnt["input"].render(s_text, True, (40, 55, 75))
            surface.blit(s_surf, (text_x, _ty))
            if s_active:
                cx_s = text_x + s_surf.get_width() + 2
                pygame.draw.line(surface, (40,160,220),
                                 (cx_s, hint_r.y+int(10*H/1080)),
                                 (cx_s, hint_r.bottom-int(10*H/1080)), 2)
        else:
            ph_txt = "Search patient" if not s_active else ""
            surface.blit(self.fnt["input"].render(ph_txt, True, (170,185,205)),
                         (text_x, _ty))

        reg_w = self.fnt["btn"].size("+ Register Patient")[0] + int(36*W/1920)
        reg_r = pygame.Rect(pa.right-pad-reg_w, hint_r.y, reg_w, sb_h)
        _btn(surface, reg_r, "+ Register Patient", self.fnt["btn"],
             (20,150,165), (15,125,140), self.register_link_hov, radius=int(sb_h*0.4))
        self._register_link_rect = reg_r

        hdr_y  = hint_r.bottom + int(20*H/1080)
        # Columns: just Name on the 7-inch panel -- Therapist/ownership moved
        # to Patient -> Info -> Record (everything else already lived on the
        # patient's own page); the full set (desktop only) still shows it.
        if touch:
            cols   = ["Patient Name"]
            col_xs = [pa.x+pad]
        else:
            cols   = ["Patient Name", "Patient ID", "Therapist", ""]
            # Patient ID pushed further right of Patient Name -- more room
            # before a longer name could run into it.
            col_xs = [pa.x+int(16*W/1920),  pa.x+int(480*W/1920),
                      pa.x+int(940*W/1920), pa.x+int(1160*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c,True,(85,105,135)), (cx, hdr_y))
        pygame.draw.line(surface, (200,212,228),
                         (pa.x+pad, hdr_y+self.fnt["section"].get_height()+int(6*H/1080)),
                         (pa.right-pad, hdr_y+self.fnt["section"].get_height()+int(6*H/1080)), 1)

        q = self._pt_search_text.strip().lower()
        visible_patients = [p for p in self.patients
                            if not q or q in p.get("full_name","").lower()
                            or q in p.get("patient_id_str","").lower()]

        if not self.patients or not visible_patients:
            self._pl_scroll_max = 0
            self._pl_up_rect = self._pl_down_rect = pygame.Rect(0, 0, 1, 1)
            icon, head, sub = (("👤", "No patients registered yet",
                                'Tap "+ Register Patient" above to add your first patient.')
                               if not self.patients else
                               ("🔍", f'No results for "{self._pt_search_text}"',
                                "Try a different name or patient ID."))
            _empty_state(surface,
                         pygame.Rect(pa.x, hdr_y+int(30*H/1080), pa.width,
                                     pa.bottom-hdr_y-int(60*H/1080)),
                         icon, head, sub, self.fnt["empty_head"], self.fnt["small_i"])
            return

        # ── scrollable row area ─────────────────────────────────────
        list_top    = hdr_y + self.fnt["section"].get_height() + int(14*H/1080)
        list_bottom = pa.bottom - int(10*H/1080)
        view_h      = list_bottom - list_top
        row_h       = self._tt(84) if touch else int(72*H/1080)
        content_h   = len(visible_patients) * row_h
        self._pl_scroll_max = max(0, content_h - view_h)
        self._pl_scroll     = max(0, min(self._pl_scroll, self._pl_scroll_max))
        scrollable          = self._pl_scroll_max > 0

        arrow_w = self._tt(50) if scrollable else 0
        # keep a clear gap between the Share icons and the scroll arrows.
        # (_sc, not _tt -- this is spacing, not a tap target: _tt would floor to 50 px
        #  and squeeze the Therapist column out of the row.)
        arrow_gap = self._sc(16) if (scrollable and touch) else 0
        btn_x_r = pa.right - pad - arrow_w - arrow_gap   # right edge available to Share icon
        bgap    = self._tt(18) if touch else int(10*W/1920)
        f_name  = self.fnt["body_b"] if touch else self.fnt["body"]
        f_ther  = self.fnt["body"]   if touch else self.fnt["tag"]

        mp = pygame.mouse.get_pos()
        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, list_top, pa.width-2, view_h))
        for k, pt in enumerate(visible_patients):
            ry = list_top + k*row_h - self._pl_scroll
            if ry + row_h <= list_top or ry >= list_bottom:
                continue

            is_owner = (pt.get("therapist_id") == self.account["id"])
            if is_owner:
                ther_label, ther_col = self.account.get("full_name", "You"), (46, 150, 95)
            else:
                _o = self.db.get_therapist_by_id(pt.get("therapist_id"))
                ther_label = _o["full_name"] if _o else "Unknown"
                ther_col = (55, 120, 215)

            # zebra fill + a clean full-width divider under each row
            if k % 2 == 1:
                bg = pygame.Surface((pa.width - 2*pad, row_h), pygame.SRCALPHA)
                bg.fill((236, 243, 255, 150)); surface.blit(bg, (pa.x + pad, ry))
            pygame.draw.line(surface, (208, 218, 234),
                             (pa.x + pad, ry + row_h), (pa.right - pad, ry + row_h), 1)

            # Share button -- the ONLY right-side action. Large touch target,
            # clearly separated from the name.
            ic = self._tt(52)
            shr_r = pygame.Rect(btn_x_r - ic, ry + (row_h - ic)//2, ic, ic)
            right_x = shr_r.x - bgap

            # Patient name -- the primary tap target (opens the patient's
            # page; does NOT select). The "SELECTED" pill is gone -- the
            # currently-selected patient's name turns blue instead (readable
            # in both themes; ownership/sharing no longer tints it at all).
            name_val = pt.get("full_name", "—")
            name_r = pygame.Rect(pa.x + pad, ry, right_x - (pa.x + pad), row_h)
            # Clamp the hit area to the visible list band: a row scrolled
            # half-off must not be tappable in the space below the list.
            hit_r = name_r.clip(pygame.Rect(pa.x, list_top, pa.width,
                                            list_bottom - list_top))
            # Only register a scrolled-partial row as tappable once a real
            # touch-sized sliver of it is showing -- a few stray pixels
            # peeking past the edge must not become an undersized tap target.
            if hit_r.height >= self._tt(44):
                self._patient_rows.append((hit_r, pt, "name"))
            n_col = (35, 110, 220) if self._is_selected(pt) else (34, 46, 66)
            if name_r.collidepoint(mp):
                n_col = tuple(min(255, c + 25) for c in n_col)
            if touch:
                # a small colourful avatar circle ahead of the name on the
                # 7-inch panel -- purely decorative (reuses the existing
                # profile-icon palette), no new per-patient data or interaction
                av_r = min(int(row_h * 0.30), self._sc(26))
                draw_icon(surface, (pt.get("id", 0) % 10) + 1,
                         pa.x + pad + av_r, ry + row_h // 2, av_r, shadow=False)
                name_x = pa.x + pad + av_r * 2 + self._sc(10)
                # Ellipsize before the Share button -- the Therapist column
                # is gone, so the name now has the full row width to itself.
                max_name_w = right_x - self._sc(10) - name_x
                fit_name = name_val
                if f_name.size(fit_name)[0] > max_name_w:
                    while fit_name and f_name.size(fit_name + "…")[0] > max_name_w:
                        fit_name = fit_name[:-1]
                    fit_name = (fit_name + "…") if fit_name else "…"
            else:
                name_x, fit_name = col_xs[0], name_val
            ns = f_name.render(fit_name, True, n_col)
            surface.blit(ns, (name_x, ry + (row_h - ns.get_height())//2))

            # Patient ID / Therapist columns -- desktop only now.
            if not touch:
                tya = ry + (row_h - self.fnt["body"].get_height())//2
                pid_val = pt.get("patient_id_str", "—")
                if col_xs[1] + self.fnt["body"].size(str(pid_val))[0] < right_x:
                    surface.blit(self.fnt["body"].render(pid_val, True, (40,55,75)), (col_xs[1], tya))
                if col_xs[2] + self.fnt["tag"].size(ther_label)[0] < right_x:
                    surface.blit(self.fnt["tag"].render(ther_label, True, ther_col), (col_xs[2], tya))

            enabled = is_owner
            hov = shr_r.collidepoint(mp) and enabled
            share_img = _img("share_button.png", ic)
            if share_img is not None:
                if not enabled:
                    share_img = share_img.copy()
                    share_img.set_alpha(100)
                surface.blit(share_img, shr_r.topleft)
                if hov:
                    pygame.draw.circle(surface, (255, 255, 255), shr_r.center,
                                       ic // 2, max(1, self._sc(2)))
            else:
                # fallback if the asset is ever missing -- the original
                # vector-drawn button, unchanged
                if not enabled:
                    shr_col = (170, 174, 184)
                elif hov:
                    shr_col = (110, 168, 235)
                else:
                    shr_col = (90, 150, 220)
                pygame.draw.rect(surface, shr_col, shr_r, border_radius=12)
                self._share_icon(surface, shr_r.centerx, shr_r.centery,
                                 int(ic * 0.32), (255, 255, 255))
            if enabled:
                self._patient_rows.append((shr_r, pt, "share"))
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when the list overflows) ────────────
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - pad - arrow_w
            self._pl_up_rect   = pygame.Rect(ax, list_top, arrow_w, ah)
            self._pl_down_rect = pygame.Rect(ax, list_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._pl_up_rect, "▲", self._pl_scroll > 0),
                               (self._pl_down_rect, "▼", self._pl_scroll < self._pl_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
            # thumb
            tb_x = ax + arrow_w + int(4*W/1920)
            track_h = view_h
            th = max(int(28*H/1080), int(track_h * view_h / max(content_h, 1)))
            ty0 = list_top + int((track_h - th) * (self._pl_scroll / self._pl_scroll_max))
            pygame.draw.rect(surface, (150,175,210),
                             pygame.Rect(tb_x, ty0, int(6*W/1920), th), border_radius=3)
        else:
            self._pl_up_rect = self._pl_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  SHARE PATIENT MODAL
    # ──────────────────────────────────────────────────────────────────

    def _draw_share_modal(self, surface):
        # Sized from _fs/_tt and laid out by flowing from the top, instead of the
        # old fixed H/1080 offsets which produced 12-18px controls at 800x480.
        W, H = self.WIDTH, self.HEIGHT
        pad   = self._sc(18)
        fh    = self._tt(46)
        btn_h = self._tt(46)
        lbl_h = self.fnt["small"].get_height()

        mw = min(int(W * 0.86), self._sc(640))

        # ── Height adapts to whatever this stage actually needs to show --
        # a bare username picker with no suggestions yet needs far less
        # room than the SHARE/TRANSFER confirmation text, so a single fixed
        # near-fullscreen height left a large empty gap under the Close
        # button most of the time. This mirrors the real draw pass below
        # closely enough to size correctly without duplicating its blits.
        pt_name = (self.share_modal_patient or {}).get("full_name", "Patient")
        pt_id   = (self.share_modal_patient or {}).get("patient_id_str", "")
        hs_w    = self.fnt["panel_title"].size("Share Patient")[0]
        sub_w   = self.fnt["small"].size(f"{pt_name} · {pt_id}")[0]
        title_h = self.fnt["panel_title"].get_height()
        same_line = (pad + hs_w + self._sc(10) + sub_w) <= (mw - pad)
        header_h = (title_h + self._sc(6)) if same_line else \
                   (title_h + self._sc(2) + self.fnt["small"].get_height() + self._sc(6))
        header_h += 1 + self._sc(10)                       # divider + gap

        core_h = lbl_h + self._sc(4) + fh + self._sc(10)   # "Share with:" + input

        if self._share_stage == "choice" and self._share_confirm_therapist:
            body_h = (3 * self.fnt["body_b"].get_linesize() + self._sc(6)
                      + btn_h + self._sc(8) + self._tt(40) + self._sc(8))
        elif self._share_stage == "confirm" and self._share_confirm_therapist:
            t = self._share_confirm_therapist
            if self._share_pending_action == "transfer":
                prompt = f"Transfer {pt_name} to {t['full_name']}?"
                detail = (f"{t['full_name']} will become the owner of this patient. "
                          "They will be able to manage and edit the patient's "
                          "information and handle future sharing or transfer of the patient.")
            else:
                prompt = f"Share {pt_name} with {t['full_name']}?"
                detail = ("They will be able to access the patient's information and "
                          "assist with therapy sessions according to their shared-patient "
                          "permissions. They will not become the owner and cannot edit "
                          "the patient's information.")
            n_prompt = len(self._wrap(prompt, self.fnt["body_b"], mw - pad * 2))
            n_detail = len(self._wrap(detail, self.fnt["small"], mw - pad * 2))
            body_h = (n_prompt * self.fnt["body_b"].get_linesize() + self._sc(4)
                      + n_detail * self.fnt["small"].get_linesize() + self._sc(8)
                      + btn_h + self._sc(10))
        elif self._share_suggestions:
            n = min(len(self._share_suggestions), 5)
            body_h = n * (self._tt(44) + self._sc(4)) + self._sc(6)
        else:
            body_h = self.fnt["small_i"].get_height() + self._sc(8)

        try:
            shared_n = (len(self.db.get_shared_therapists(self.share_modal_patient["id"]))
                        if self.share_modal_patient else 0)
        except Exception:
            shared_n = 0
        shared_n = min(shared_n, 4)   # a longer list still degrades gracefully below
        shared_h = (lbl_h + self._sc(4) + shared_n * (self._tt(40) + self._sc(4))
                    if shared_n else lbl_h)

        mh = min(int(H * 0.94),
                 pad + header_h + core_h + body_h + shared_h + self._sc(10) + btn_h + pad)
        mh = max(mh, self._tt(300))
        mx = (W - mw) // 2
        my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (228, 238, 252, 252), (0, 0, mw, mh), border_radius=14)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), mr, 1, border_radius=14)

        pt_name = (self.share_modal_patient or {}).get("full_name", "Patient")
        pt_id   = (self.share_modal_patient or {}).get("patient_id_str", "")

        # Title line: heading + patient on the same row to save vertical space.
        y = mr.y + self._sc(10)
        hs = self.fnt["panel_title"].render("Share Patient", True, (38, 52, 78))
        surface.blit(hs, (mr.x + pad, y))
        sub = self.fnt["small"].render(f"{pt_name} · {pt_id}", True, (100, 120, 155))
        if mr.x + pad + hs.get_width() + self._sc(10) + sub.get_width() <= mr.right - pad:
            surface.blit(sub, (mr.x + pad + hs.get_width() + self._sc(10),
                               y + hs.get_height() - sub.get_height() - self._sc(2)))
            y += hs.get_height() + self._sc(6)
        else:
            y += hs.get_height() + self._sc(2)
            surface.blit(sub, (mr.x + pad, y)); y += sub.get_height() + self._sc(6)
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + pad, y), (mr.right - pad, y), 1)
        y += self._sc(10)

        # "Share with:" label + input field
        surface.blit(self.fnt["small"].render("Share with:", True, (80, 95, 115)),
                     (mr.x + pad, y))
        y += lbl_h + self._sc(4)
        sf_r = pygame.Rect(mr.x + pad, y, mw - pad * 2, fh)
        past_picker = self._share_stage != "pick"
        bc = (185, 205, 228) if past_picker else (40, 160, 220)
        pygame.draw.rect(surface, (248, 252, 255), sf_r, border_radius=10)
        pygame.draw.rect(surface, bc, sf_r, 2, border_radius=10)
        disp = self._share_input
        ts_inp = (self.fnt["input"].render(disp, True, (40, 50, 65)) if disp
                  else self.fnt["input"].render("Enter username", True, (175, 188, 205)))
        surface.blit(ts_inp, ts_inp.get_rect(midleft=(sf_r.x + self._sc(12), sf_r.centery)))
        if disp and not past_picker:
            curs_x = sf_r.x + self._sc(12) + ts_inp.get_width() + 2
            pygame.draw.line(surface, (40, 160, 220),
                             (curs_x, sf_r.centery - self._sc(10)),
                             (curs_x, sf_r.centery + self._sc(10)), 2)
        self._share_field_rect = sf_r

        content_y = sf_r.bottom + self._sc(10)
        close_top = mr.bottom - btn_h - pad          # everything must stay above this

        # ── SHARE | TRANSFER choice ────────────────────────────────────
        if self._share_stage == "choice" and self._share_confirm_therapist:
            t = self._share_confirm_therapist
            for ln in (f"Patient: {pt_name}", f"Therapist: {t['full_name']}",
                      "What would you like to do?"):
                ls = self.fnt["body_b"].render(ln, True, (35, 50, 75))
                surface.blit(ls, (mr.x + pad, content_y))
                content_y += self.fnt["body_b"].get_linesize()
            content_y += self._sc(6)
            bw2 = (mw - pad * 2 - self._sc(12)) // 2
            self._share_choice_share_rect    = pygame.Rect(mr.x + pad, content_y, bw2, btn_h)
            self._share_choice_transfer_rect = pygame.Rect(
                mr.x + pad + bw2 + self._sc(12), content_y, bw2, btn_h)
            _btn(surface, self._share_choice_share_rect, "SHARE", self.fnt["btn"],
                 (40,160,90),(28,130,70), self._share_choice_share_hov, radius=10)
            _btn(surface, self._share_choice_transfer_rect, "TRANSFER", self.fnt["btn"],
                 (215,140,30),(180,112,15), self._share_choice_transfer_hov, radius=10)
            content_y += btn_h + self._sc(8)
            bw3 = self.fnt["small"].size("Cancel")[0] + self._sc(24)
            self._share_no_rect = pygame.Rect(mr.x + pad, content_y, bw3, self._tt(40))
            _btn(surface, self._share_no_rect, "Cancel", self.fnt["small"],
                 (160,175,195),(130,148,168), self._share_no_hov, radius=8)
            content_y += self._share_no_rect.height + self._sc(8)

        # ── Final confirmation (worded for the chosen action) ──────────
        elif self._share_stage == "confirm" and self._share_confirm_therapist:
            t = self._share_confirm_therapist
            if self._share_pending_action == "transfer":
                prompt = f"Transfer {pt_name} to {t['full_name']}?"
                detail = (f"{t['full_name']} will become the owner of this patient. "
                         "They will be able to manage and edit the patient's "
                         "information and handle future sharing or transfer of the patient.")
                yes_lbl, yes_col, yes_hi = "Yes, Transfer", (215,140,30), (180,112,15)
            else:
                prompt = f"Share {pt_name} with {t['full_name']}?"
                detail = ("They will be able to access the patient's information and "
                         "assist with therapy sessions according to their shared-patient "
                         "permissions. They will not become the owner and cannot edit "
                         "the patient's information.")
                yes_lbl, yes_col, yes_hi = "Yes, Share", (40,160,90), (28,130,70)
            for ln in self._wrap(prompt, self.fnt["body_b"], mw - pad * 2):
                surface.blit(self.fnt["body_b"].render(ln, True, (35, 50, 75)),
                             (mr.x + pad, content_y))
                content_y += self.fnt["body_b"].get_linesize()
            content_y += self._sc(4)
            for ln in self._wrap(detail, self.fnt["small"], mw - pad * 2):
                surface.blit(self.fnt["small"].render(ln, True, (95, 108, 128)),
                             (mr.x + pad, content_y))
                content_y += self.fnt["small"].get_linesize()
            content_y += self._sc(8)
            bw2 = (mw - pad * 2 - self._sc(12)) // 2
            self._share_yes_rect = pygame.Rect(mr.x + pad, content_y, bw2, btn_h)
            self._share_no_rect  = pygame.Rect(mr.x + pad + bw2 + self._sc(12),
                                               content_y, bw2, btn_h)
            _btn(surface, self._share_yes_rect, yes_lbl, self.fnt["btn"],
                 yes_col, yes_hi, self._share_yes_hov, radius=10)
            _btn(surface, self._share_no_rect, "Cancel", self.fnt["btn"],
                 (160,175,195),(130,148,168), self._share_no_hov, radius=10)
            content_y += btn_h + self._sc(10)

        # ── Live suggestions ─────────────────────────────────────────
        elif self._share_suggestions:
            self._share_sugg_rects = []
            opt_h = self._tt(44)
            for i, t in enumerate(self._share_suggestions):
                sr = pygame.Rect(sf_r.x, content_y + i * (opt_h + self._sc(4)),
                                 sf_r.width, opt_h)
                if sr.bottom > close_top:
                    break
                if sr.collidepoint(pygame.mouse.get_pos()):
                    pygame.draw.rect(surface, (206, 228, 255), sr, border_radius=8)
                pygame.draw.rect(surface, (190, 212, 238), sr, 1, border_radius=8)
                row_lbl = f"@{t['username']}  ·  {t['full_name']}"
                rs = self.fnt["body"].render(row_lbl, True, (40, 75, 140))
                surface.blit(rs, rs.get_rect(midleft=(sr.x + self._sc(12), sr.centery)))
                self._share_sugg_rects.append((sr, t))
            content_y += len(self._share_sugg_rects) * (opt_h + self._sc(4)) + self._sc(6)

        # ── Error / success / hint ───────────────────────────────────
        else:
            if self._share_error:
                msg, mc = self._share_error, (210, 50, 50)
            elif self._share_success:
                msg, mc = self._share_success, (50, 175, 75)
            elif not disp:
                msg, mc = "Type a username to see suggestions.", (155, 168, 188)
            else:
                msg, mc = "", None
            if msg:
                surface.blit(self.fnt["small_i"].render(msg, True, mc),
                             (mr.x + pad, content_y))
                content_y += self.fnt["small_i"].get_height() + self._sc(8)

        # ── Currently shared-with (flows under the content, never fixed) ──
        self._unshare_rects = []
        shared = []
        if self.share_modal_patient:
            try:
                shared = self.db.get_shared_therapists(self.share_modal_patient["id"])
            except Exception:
                shared = []

        row_h = self._tt(40)
        if shared:
            if content_y + lbl_h + row_h <= close_top:
                surface.blit(self.fnt["small"].render(
                    "Currently shared with:", True, (85, 105, 135)), (mr.x + pad, content_y))
                content_y += lbl_h + self._sc(4)
                rev_w = self.fnt["tag"].size("Revoke")[0] + self._sc(20)
                for t in shared:
                    if content_y + row_h > close_top:
                        break
                    ts_l = self.fnt["small"].render(
                        f"{t['full_name']} (@{t['username']})", True, (50, 65, 90))
                    surface.blit(ts_l, (mr.x + pad, content_y + (row_h - ts_l.get_height()) // 2))
                    rev_r = pygame.Rect(mr.right - pad - rev_w, content_y, rev_w, row_h)
                    pygame.draw.rect(surface, (210, 60, 60), rev_r, border_radius=8)
                    rev_s = self.fnt["tag"].render("Revoke", True, (255, 255, 255))
                    surface.blit(rev_s, rev_s.get_rect(center=rev_r.center))
                    self._unshare_rects.append((rev_r, t["id"]))
                    content_y += row_h + self._sc(4)
        elif content_y + lbl_h <= close_top:
            surface.blit(self.fnt["small_i"].render(
                "Not shared with anyone yet.", True, (155, 168, 188)), (mr.x + pad, content_y))

        # ── Close button ─────────────────────────────────────────────
        bw_c = self._sc(140)
        clos_r = pygame.Rect(mr.centerx - bw_c // 2, close_top, bw_c, btn_h)
        _btn(surface, clos_r, "Close", self.fnt["btn"],
             (160,175,195),(130,148,168), self._share_close_hov, radius=10)
        self._share_close_rect   = clos_r
        self._share_search_rect  = pygame.Rect(0, 0, 1, 1)
        self._share_confirm_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 6: REGISTER PATIENT
    # ──────────────────────────────────────────────────────────────────

    def _draw_register_patient(self, surface, pa):
        if self._touch_ui:
            self._draw_register_patient_touch(surface, pa)
            return
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
        _register_field("date_of_stroke","Stroke Onset Date",           col1_x, 2, "MM-DD-YY")
        _register_field("months_stroke", "Months Since Stroke",         col1_x, 3, "e.g. 6")
        _register_field("sex",           "Sex",                         col1_x, 4, is_drop=True, opts=SEX_OPTS)
        _register_field("dominant_hand", "Dominant Hand",               col1_x, 5, is_drop=True, opts=HAND_OPTS)
        _register_field("affected_hand", "Affected Hand (Stroke Side)", col1_x, 6, is_drop=True, opts=HAND_OPTS)
        _register_field("stroke_type",   "Stroke Type",                 col2_x, 0, is_drop=True, opts=STROKE_TYPES)

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

    def _draw_register_patient_touch(self, surface, pa):
        """Single-column, finger-scrollable registration form for the 1024x600
        panel. Reuses self._rp_drop_rects / self._rp_btn_rect so the existing
        _rp_handle_click / _rp_submit logic works unchanged -- only the layout
        and the vertical scroll are new."""
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=224)
        rp = self.rp
        self._rp_drop_rects = {}

        pad = self._sc(16)
        x0  = pa.x + pad
        fw  = pa.width - 2 * pad
        fh  = self._tt(50)
        lbl_h = self.fnt["small"].get_height()
        row_h = lbl_h + int(4 * H / 1080) + fh + self._sc(16)

        FIELDS = [
            ("full_name",      "Full Name *",                   "text", None),
            ("age",            "Age *",                         "text", None),
            ("sex",            "Sex *",                         "drop", SEX_OPTS),
            ("dominant_hand",  "Dominant Hand *",               "drop", HAND_OPTS),
            ("affected_hand",  "Affected Hand (Stroke Side) *", "drop", HAND_OPTS),
            ("stroke_type",    "Stroke Type",                   "drop", STROKE_TYPES),
            ("date_of_stroke", "Stroke Onset Date *",           "text", None),
            ("months_stroke",  "Months Since Stroke *",         "text", None),
            ("notes_stiffness","Muscle Stiffness Notes",        "text", None),
            ("notes_pain",     "Pain Level Notes",              "text", None),
            ("notes_therapist","Therapist Comments",            "text", None),
        ]
        PLACEHOLD = {"full_name": "Enter full name", "age": "Enter age",
                     "date_of_stroke": "MM-DD-YY", "months_stroke": "e.g. 6"}
        open_flag_map = {"sex": "sex_open", "dominant_hand": "dominant_open",
                         "affected_hand": "affected_open", "stroke_type": "stroke_open",
                         }

        # fixed footer: message line + Register button (always on screen)
        btn_h = self._tt(56)
        rb = pygame.Rect(x0, pa.bottom - pad - btn_h, fw, btn_h)
        footer_top = rb.top - int(8 * H / 1080)
        if rp["error"]:
            msg, mcol = rp["error"], (205, 55, 55)
        elif rp["success"]:
            msg, mcol = rp["success"], (40, 165, 80)
        else:
            msg, mcol = "", None

        top    = pa.y + int(12 * H / 1080)
        bottom = footer_top - int(6 * H / 1080)
        if msg:
            bottom -= self.fnt["small"].get_height() + int(4 * H / 1080)
        view_h = bottom - top
        total  = len(FIELDS) * row_h + self._sc(10)
        self._rp_scroll_max = max(0, total - view_h)
        self._rp_scroll = max(0, min(self._rp_scroll, self._rp_scroll_max))
        arrow_w = self._tt(46) if self._rp_scroll_max > 0 else 0
        field_w = fw - (arrow_w + int(8 * W / 1920) if arrow_w else 0)

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x + 1, top, pa.width - 2, view_h))
        y = top - self._rp_scroll
        open_overlay = None
        for key, label, kind, opts in FIELDS:
            fr = pygame.Rect(x0, y + lbl_h + int(4 * H / 1080), field_w, fh)
            visible = fr.bottom >= top and fr.top <= bottom
            self._rp_drop_rects[key] = ((fr if visible else pygame.Rect(-9, -9, 1, 1)),
                                        [], opts or [])
            if visible:
                active = (rp["active_key"] == key)
                surface.blit(self.fnt["small"].render(label, True, (78, 95, 118)), (x0, y))
                pygame.draw.rect(surface, (255, 255, 255), fr, border_radius=9)
                pygame.draw.rect(surface, (40, 160, 220) if active else (188, 205, 226),
                                 fr, 2 if active else 1, border_radius=9)
                val = rp.get(key, "")
                if kind == "drop":
                    disp = val or "Select"
                    tc   = (40, 52, 68) if val else (170, 185, 202)
                    ds   = self.fnt["input"].render(disp, True, tc)
                    surface.blit(ds, ds.get_rect(midleft=(fr.x + int(12 * W / 1920),
                                                          fr.centery)))
                    chev = self.fnt["sym26"].render("▼", True, (95, 115, 145))
                    surface.blit(chev, chev.get_rect(
                        midright=(fr.right - int(12 * W / 1920), fr.centery)))
                    if rp.get(open_flag_map[key]):
                        open_overlay = (fr, opts, key)
                else:
                    ph = PLACEHOLD.get(key, "Optional")
                    vs = (self.fnt["input"].render(val, True, (40, 52, 68)) if val
                          else self.fnt["input"].render(ph, True, (183, 197, 214)))
                    surface.blit(vs, vs.get_rect(midleft=(fr.x + int(12 * W / 1920),
                                                          fr.centery)))
            y += row_h
        surface.set_clip(prev_clip)

        if self._rp_scroll_max > 0:
            ax = pa.right - int(8 * W / 1920) - arrow_w
            ah = view_h // 2 - int(4 * H / 1080)
            self._rp_up_rect   = pygame.Rect(ax, top, arrow_w, ah)
            self._rp_down_rect = pygame.Rect(ax, top + ah + int(8 * H / 1080), arrow_w, ah)
            for r, tri, on in ((self._rp_up_rect, "▲", self._rp_scroll > 0),
                               (self._rp_down_rect, "▼",
                                self._rp_scroll < self._rp_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244),
                                 r, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r, 1, border_radius=8)
                g = self.fnt["nav_sym"].render(tri, True,
                                               (45, 90, 150) if on else (188, 196, 206))
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._rp_up_rect = self._rp_down_rect = pygame.Rect(0, 0, 1, 1)

        if open_overlay:
            fr, opts, fkey = open_overlay
            opt_h = self._tt(46)
            lst_h = len(opts) * opt_h + 4
            # Flip the list upward whenever it would otherwise spill past the
            # fixed footer (message + Register button) -- comparing against
            # pa.bottom (the whole card) instead of footer_top let the open
            # list sit on top of the Register button when a field sat low in
            # the scroll view, e.g. Sex right above the footer.
            base_y = fr.top - lst_h if fr.bottom + lst_h > footer_top else fr.bottom
            dp = pygame.Rect(fr.x, base_y, fr.width, lst_h)
            pygame.draw.rect(surface, (248, 251, 255), dp, border_radius=9)
            pygame.draw.rect(surface, (40, 160, 220), dp, 2, border_radius=9)
            opt_rs, mp = [], pygame.mouse.get_pos()
            for j, ov in enumerate(opts):
                orr = pygame.Rect(fr.x, base_y + j * opt_h, fr.width, opt_h)
                if orr.collidepoint(mp):
                    pygame.draw.rect(surface, (220, 236, 255), orr, border_radius=6)
                os_ = self.fnt["input"].render(ov, True, (40, 52, 68))
                surface.blit(os_, os_.get_rect(midleft=(orr.x + int(12 * W / 1920),
                                                        orr.centery)))
                opt_rs.append(orr)
            self._rp_drop_rects[fkey] = (fr, opt_rs, opts)

        if msg:
            surface.blit(self.fnt["small"].render(msg, True, mcol),
                         (x0, footer_top - self.fnt["small"].get_height()
                          - int(2 * H / 1080)))
        _btn(surface, rb, "Register Patient", self.fnt["btn"],
             (40, 160, 220), (25, 130, 190), self.rp_btn_hov, radius=12)
        self._rp_btn_rect = rb


    # ──────────────────────────────────────────────────────────────────
    #  PANEL 8: THE PATIENT'S OWN PAGE  (breadcrumb: Patient List > <Name>)
    #
    #  Reached by clicking a patient row in the Patient List (that click does
    #  NOT select the patient). Hosts the per-patient records (Info / Analytics
    #  / Calibration Records / Session History) AND the only SELECT PATIENT /
    #  DESELECT PATIENT control -- both go through a confirmation dialog.
    # ──────────────────────────────────────────────────────────────────

    _PV_TABS = [("info", "Info"), ("analytics", "Analytics"),
                ("calibration", "Calibration Records"), ("history", "Session History")]
    _PV_TABS_SHORT = [("info", "Info"), ("analytics", "Analytics"),
                      ("calibration", "Calibration"), ("history", "History")]

    def _draw_patient_preview(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        pt = self.preview_patient or {}
        is_sel = self._is_selected(self.preview_patient)

        # ── header row: tab strip (left) + Select/Deselect button (right) ──
        # No Edit button here any more -- editing moved to a per-section Edit
        # button on each Info group (Patient Information / Stroke & Therapy /
        # Clinical Notes). Record stays read-only.
        self._pv_edit_rect = pygame.Rect(0, 0, 1, 1)

        strip_h = max(int(46 * H / 1080), self._tt(46))
        if self._narrow:
            # 800px panel: the full labels do not fit beside four tabs.
            sel_txt   = "DESELECT" if is_sel else "SELECT"
            sel_gauge = "DESELECT"
        else:
            sel_txt   = "DESELECT PATIENT" if is_sel else "SELECT PATIENT"
            sel_gauge = "DESELECT PATIENT"
        sel_w = self.fnt["label"].size(sel_gauge)[0] + self._sc(40)
        self._pv_tab_rects = {}
        tabs = self._PV_TABS_SHORT if self._touch_ui else self._PV_TABS
        tab_pad = self._sc(34)
        gap     = self._sc(8)
        # Shrink the padding (never the font) if the row would overrun.
        row_w = sum(self.fnt["label"].size(l)[0] for _, l in tabs) \
            + tab_pad * len(tabs) + gap * (len(tabs) - 1) + gap + sel_w
        if row_w > pa.width:
            tab_pad = max(self._sc(10),
                          tab_pad - (row_w - pa.width) // len(tabs) - 1)
        tx = pa.x
        for key, label in tabs:
            tw = self.fnt["label"].size(label)[0] + tab_pad
            r  = pygame.Rect(tx, pa.y, tw, strip_h)
            active = (self._pv_tab == key)
            # Active page = dark fill + white text, so the current page is
            # unmistakable at a glance on the small panel.
            pygame.draw.rect(surface, (34, 46, 66) if active else (232, 242, 255),
                             r, border_radius=10)
            pygame.draw.rect(surface, (34, 46, 66) if active else (150, 175, 210),
                             r, 1, border_radius=10)
            col = (255, 255, 255) if active else (70, 95, 130)
            ls = self.fnt["label"].render(label, True, col)
            surface.blit(ls, ls.get_rect(center=r.center))
            self._pv_tab_rects[key] = r
            tx += tw + gap

        sel_r = pygame.Rect(pa.right - sel_w, pa.y, sel_w, strip_h)
        pygame.draw.rect(surface, (190, 60, 55) if is_sel else (55, 150, 95),
                         sel_r, border_radius=10)
        ss = self.fnt["label"].render(sel_txt, True, (255, 255, 255))
        surface.blit(ss, ss.get_rect(center=sel_r.center))
        self._pv_select_rect = sel_r

        # ── content area below the strip ──
        sub = pygame.Rect(pa.x, pa.y + strip_h + int(14 * H / 1080),
                          pa.width, pa.height - strip_h - int(14 * H / 1080))
        if self._pv_tab == "analytics":
            self._draw_analytics(surface, sub)
        elif self._pv_tab == "calibration":
            self._draw_calibration(surface, sub)
        elif self._pv_tab == "history":
            self._draw_session_history(surface, sub)
        else:
            self._pv_draw_info(surface, sub, pt)

    def _is_owner(self, pt):
        """True when the logged-in therapist OWNS this patient (not merely
        shared with them). Only the owner may edit, share or transfer."""
        if not pt:
            return False
        return pt.get("therapist_id") == self.account.get("id")

    # Section key -> the patient fields it owns. Drives both the Info groups and
    # the per-section edit modal, so the two can never drift apart.
    # "record" is absent on purpose: it is derived data and never editable.
    _PV_SECTIONS = {
        "info":   ("Patient Information", ["full_name", "age", "sex"]),
        "stroke": ("Stroke & Therapy",
                   ["stroke_type", "date_of_stroke", "months_stroke",
                    "dominant_hand", "affected_hand"]),
        "notes":  ("Clinical Notes",
                   ["notes_stiffness", "notes_pain", "notes_therapist"]),
    }

    def _pv_info_fields(self, pt):
        """Every stored patient field, grouped. Sourced from the `patients` table
        (database.py) -- nothing invented.

        Each group carries its section key so the renderer can attach the right
        Edit button; `None` means the group is read-only (Record)."""
        def g(k):
            v = pt.get(k)
            return "—" if v is None or str(v).strip() == "" else str(v)
        owner = "—"
        try:
            o = self.db.get_therapist_by_id(pt.get("therapist_id"))
            if o:
                owner = o.get("full_name", "—")
        except Exception:
            pass
        return [
            ("Patient Information", "info", [
                ("Patient ID",   g("patient_id_str")),   # generated, not editable
                ("Full Name",    g("full_name")),
                ("Age",          g("age")),
                ("Sex",          g("sex")),
            ]),
            ("Stroke & Therapy", "stroke", [
                ("Stroke Type",         g("stroke_type")),
                ("Stroke Onset Date",   g("date_of_stroke")),
                ("Months Since Stroke", g("months_stroke")),
                ("Dominant Hand",       g("dominant_hand")),
                ("Affected Hand",       g("affected_hand")),
            ]),
            ("Clinical Notes", "notes", [
                ("Stiffness",       g("notes_stiffness")),
                ("Pain",            g("notes_pain")),
                ("Therapist Notes", g("notes_therapist")),
            ]),
            ("Record", None, [            # read-only: no Edit button, ever
                ("Registered By", owner),
                ("Registered On", str(pt.get("created_at", "—"))[:16] or "—"),
            ]),
        ]

    def _wrap(self, text, font, max_w):
        words, lines, cur = str(text).split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if font.size(t)[0] <= max_w or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _pv_draw_info(self, surface, pa, pt):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        x0    = pa.x + int(30 * W / 1920)
        val_x = x0 + max(int(300 * W / 1920), self._tt(250))
        # Field rows are plain text, not tap targets -- _tt()'s 50px touch
        # floor doesn't belong here; _sc() gives a compact row without it.
        lh    = max(int(34 * H / 1080), self._sc(32))
        val_w = pa.right - int(30 * W / 1920) - val_x

        # Only the OWNER may edit. A shared patient is read-only here, so the
        # per-section Edit buttons are simply not drawn for a non-owner.
        can_edit = self._is_owner(pt)
        edit_w   = edit_h = self._tt(34)

        # measure -> total content height
        groups = self._pv_info_fields(pt)
        blocks = []   # (kind, *payload)
        for title, sec, fields in groups:
            blocks.append(("hdr", title, sec))
            for lbl, val in fields:
                wl = self._wrap(val, self.fnt["body"], val_w)
                blocks.append(("row", lbl, wl))
        def block_h(b):
            if b[0] == "hdr":
                # header rows carry an Edit button, so they need its height
                return max(lh, edit_h) + self._sc(6)
            return lh * len(b[2]) + self._sc(3)
        total = sum(block_h(b) for b in blocks) + self._sc(10)

        top    = pa.y + int(16 * H / 1080)
        bottom = pa.bottom - self._sc(14)
        view_h = bottom - top
        self._pv_info_scroll_max = max(0, total - view_h)
        self._pv_info_scroll = max(0, min(self._pv_info_scroll, self._pv_info_scroll_max))
        arrow_w = self._tt(44) if self._pv_info_scroll_max > 0 else 0

        self._pv_sec_edit_rects = {}
        right_edge = pa.right - int(30 * W / 1920) - (arrow_w + self._sc(8) if arrow_w else 0)

        prev = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x + 1, top, pa.width - 2, view_h))
        y = top - self._pv_info_scroll
        for b in blocks:
            if y + block_h(b) >= top and y <= bottom:
                if b[0] == "hdr":
                    hdr_s = self.fnt["body_b"].render(b[1], True, (46, 110, 180))
                    surface.blit(hdr_s, (x0, y))
                    sec = b[2]
                    if sec and can_edit:
                        # Immediately beside the subtitle, not pushed to the
                        # far right of the card -- clearly "this button
                        # belongs to this section", per row.
                        er = pygame.Rect(x0 + hdr_s.get_width() + self._sc(14),
                                         y + (hdr_s.get_height() - edit_h) // 2,
                                         edit_w, edit_h)
                        if er.right > right_edge:      # never spill past the arrows
                            er.right = right_edge
                        edit_img = _img("edit_button.png", min(er.width, er.height))
                        if edit_img is not None:
                            surface.blit(edit_img, edit_img.get_rect(center=er.center))
                        else:
                            pygame.draw.rect(surface, (236, 242, 250), er, border_radius=9)
                            pygame.draw.rect(surface, (95, 130, 175), er, 2, border_radius=9)
                            es = self.fnt["small"].render("Edit", True, (60, 95, 150))
                            surface.blit(es, es.get_rect(center=er.center))
                        # only clickable while actually on screen
                        if er.top >= top and er.bottom <= bottom:
                            self._pv_sec_edit_rects[sec] = er
                    hl_y = y + max(lh, edit_h) - int(4 * H / 1080)
                    pygame.draw.line(surface, (200, 214, 232),
                                     (x0, hl_y), (pa.right - int(30 * W / 1920), hl_y), 1)
                else:
                    surface.blit(self.fnt["small"].render(b[1], True, (120, 135, 160)), (x0, y))
                    yy = y
                    for ln in b[2]:
                        surface.blit(self.fnt["body"].render(ln, True, (40, 55, 75)), (val_x, yy))
                        yy += lh
            y += block_h(b)
        surface.set_clip(prev)

        if self._pv_info_scroll_max > 0:
            ax = pa.right - int(8 * W / 1920) - arrow_w
            ah = view_h // 2 - int(4 * H / 1080)
            self._pv_info_up_rect   = pygame.Rect(ax, top, arrow_w, ah)
            self._pv_info_down_rect = pygame.Rect(ax, top + ah + int(8 * H / 1080), arrow_w, ah)
            for r, tri, on in ((self._pv_info_up_rect, "▲", self._pv_info_scroll > 0),
                               (self._pv_info_down_rect, "▼", self._pv_info_scroll < self._pv_info_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244), r, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r, 1, border_radius=8)
                g = self.fnt["nav_sym"].render(tri, True, (45, 90, 150) if on else (185, 193, 203))
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._pv_info_up_rect = self._pv_info_down_rect = pygame.Rect(0, 0, 1, 1)
        # The bottom instructional hint ("Selected -- use DESELECT PATIENT
        # above.") was removed -- selection state is already shown via the
        # SELECT/DESELECT button itself and the sidebar's Active Patient card.

    def _draw_choice_modal(self, surface, title, body, confirm_col, confirm_hi):
        """Shared CANCEL | CONFIRM dialog (used for SELECT and DESELECT).
        Sized from its own title/body/button content instead of a fixed
        floor that was wide enough to leave large empty margins around a
        two-line message, and stacked top-down by actual font line height
        instead of two fixed offsets that put the title's descender under
        the body text's ascender."""
        W, H = self.WIDTH, self.HEIGHT
        pad = self._sc(28)
        gap = self._sc(14)
        max_content_w = int(W * 0.8) - pad * 2

        # A long patient name must WRAP, never overflow the box -- a font
        # downgrade alone isn't enough once the name itself is long.
        title_font = self.fnt["modal_head"]
        if title_font.size(title)[0] > max_content_w:
            title_font = self.fnt["modal_lbl"]
        title_lines = self._wrap(title, title_font, max_content_w)
        title_surfs = [title_font.render(ln, True, (38, 52, 78)) for ln in title_lines]
        title_line_h = title_font.get_linesize()

        yr, nr = self._confirm_rects()
        btn_row_w  = max(yr.right, nr.right) - min(yr.left, nr.left)
        body_lines = self._wrap(body, self.fnt["modal_lbl"], max_content_w)
        body_surfs = [self.fnt["modal_lbl"].render(ln, True, (98, 114, 140)) for ln in body_lines]
        line_h     = self.fnt["modal_lbl"].get_linesize()

        content_w = max([btn_row_w] + [s.get_width() for s in title_surfs]
                        + [s.get_width() for s in body_surfs])
        mw = min(max(content_w + pad * 2, self._sc(360)), int(W * 0.86))

        stack_h = len(title_lines) * title_line_h + gap + len(body_lines) * line_h
        mh = max(int(H * 0.24), self._tt(300))
        my = (H - mh) // 2
        avail = (yr.top - self._sc(10)) - (my + pad)
        if stack_h > avail:
            mh += 2 * (stack_h - avail)   # grow symmetrically: pulls 'my' up to fit
        mx, my = (W - mw) // 2, (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)
        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (250, 252, 255, 255), (0, 0, mw, mh), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (195, 210, 228), mr, 2, border_radius=16)

        ty = my + pad
        for s in title_surfs:
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += title_line_h
        ty += gap
        for s in body_surfs:
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += line_h

        yc = confirm_hi if self.confirm_yes_hov else confirm_col
        nc = (148, 162, 180) if self.confirm_no_hov else (175, 190, 210)
        pygame.draw.rect(surface, yc, yr, border_radius=10)
        pygame.draw.rect(surface, nc, nr, border_radius=10)
        surface.blit(self.fnt["btn"].render("Confirm", True, (255, 255, 255)),
                     self.fnt["btn"].render("Confirm", True, (255, 255, 255)).get_rect(center=yr.center))
        surface.blit(self.fnt["btn"].render("Cancel", True, (255, 255, 255)),
                     self.fnt["btn"].render("Cancel", True, (255, 255, 255)).get_rect(center=nr.center))

    def _draw_select_confirm_modal(self, surface):
        name = (self._pending_select_patient or {}).get("full_name", "this patient")
        self._draw_choice_modal(
            surface, f"Select {name} for this session?",
            "You will continue to Game Configuration.",
            (45, 150, 95), (30, 120, 75))

    def _draw_deselect_confirm_modal(self, surface):
        name = (self._pending_deselect_patient or {}).get("full_name", "this patient")
        self._draw_choice_modal(
            surface, f"Deselect {name}?",
            "The patient monitor returns to the Waiting Screen.",
            (200, 70, 60), (175, 45, 40))

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 1: SESSION HISTORY
    # ──────────────────────────────────────────────────────────────────

    def _draw_session_history(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        table_y = pa.y + int(28*H/1080)
        cols   = ["Date", "Game", "Score", "Duration", "Difficulty", "Therapist"]
        col_xs = [pa.x+int(16*W/1920),  pa.x+int(230*W/1920), pa.x+int(620*W/1920),
                  pa.x+int(780*W/1920), pa.x+int(950*W/1920),  pa.x+int(1140*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c, True, (85,105,135)), (cx, table_y))
        pygame.draw.line(surface, (210,218,230),
                         (pa.x+int(16*W/1920), table_y+int(36*H/1080)),
                         (pa.right-int(16*W/1920), table_y+int(36*H/1080)), 1)

        pt = self._view_patient()
        if not pt:
            _empty_state(surface,
                         pygame.Rect(pa.x, table_y+int(48*H/1080), pa.width,
                                     pa.bottom-table_y-int(48*H/1080)),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view their session history.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._sh_up_rect = self._sh_down_rect = pygame.Rect(0, 0, 1, 1)
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
            self._sh_up_rect = self._sh_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        row_h       = int(52*H/1080)
        view_top    = table_y + int(44*H/1080)
        view_bottom = pa.bottom - int(10*H/1080)
        view_h      = view_bottom - view_top
        content_h   = len(sessions) * row_h
        self._sh_scroll_max = max(0, content_h - view_h)
        self._sh_scroll     = max(0, min(self._sh_scroll, self._sh_scroll_max))
        scrollable  = self._sh_scroll_max > 0
        arrow_w     = self._tt(44) if scrollable else 0
        content_right = pa.right - int(8*W/1920) - (arrow_w + self._sc(8) if scrollable else 0)

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, view_top, content_right - pa.x - 1, view_h))
        for k, s in enumerate(sessions):
            ry = view_top + k * row_h - self._sh_scroll
            if ry + row_h <= view_top or ry >= view_bottom:
                continue
            row_r = pygame.Rect(pa.x+int(10*W/1920), ry, pa.width-int(20*W/1920), row_h - 4)
            if k % 2 == 0:
                bg = pygame.Surface((row_r.width, row_r.height), pygame.SRCALPHA)
                bg.fill((240,246,255,180)); surface.blit(bg, row_r.topleft)
            pygame.draw.rect(surface, (215,225,240), row_r, 1, border_radius=8)

            date_str = str(s.get("played_at",""))[:16]
            mins, secs = divmod(int(s.get("duration_sec", 0)), 60)
            if mins and secs:
                dur_str = f"{mins}min {secs}s"
            elif mins:
                dur_str = f"{mins}min"
            else:
                dur_str = f"{secs}s"
            vals = [date_str,
                    s.get("game","—"),
                    str(s.get("score","—")),
                    dur_str,
                    s.get("difficulty","—"),
                    s.get("therapist_name","—")]
            for cx, v in zip(col_xs, vals):
                surface.blit(self.fnt["small"].render(v, True, (40,55,75)),
                             (cx, ry + int(14*H/1080)))
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when the history overflows) ──────────
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - int(8*W/1920) - arrow_w
            self._sh_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._sh_down_rect = pygame.Rect(ax, view_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._sh_up_rect, "▲", self._sh_scroll > 0),
                               (self._sh_down_rect, "▼", self._sh_scroll < self._sh_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._sh_up_rect = self._sh_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 2: ANALYTICS
    # ──────────────────────────────────────────────────────────────────

    def _draw_analytics(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        lx = pa.x + int(16*W/1920)
        ly = pa.y + int(20*H/1080)

        pt = self._view_patient()
        if not pt:
            _empty_state(surface, pygame.Rect(pa.x, ly, pa.width, pa.bottom-ly),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view their analytics.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._an_up_rect = self._an_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        sessions = (self.db.get_sessions(self.account["id"], patient_id=pt["id"])
                    if hasattr(self.db, "get_sessions") else [])

        if not sessions:
            _empty_state(surface, pygame.Rect(pa.x, ly, pa.width, pa.bottom-ly),
                         "📊", "No analytics data yet",
                         f"No sessions recorded for {pt.get('full_name', 'this patient')} yet.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._an_up_rect = self._an_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        # Group sessions by game name
        from collections import defaultdict
        by_game = defaultdict(list)
        for s in sessions:
            by_game[s.get("game", "Unknown")].append(s)
        games_list = list(by_game.items())

        GAME_COLORS = [
            (60, 140, 210), (55, 185, 100), (210, 120, 40),
            (160, 60, 200), (200, 60, 80),  (40, 180, 190),
        ]

        section_gap = int(18*H/1080)
        lbl_h       = int(20*H/1080)
        # Fixed per-section advance (heading + stat boxes + chart + gap) --
        # every section takes the same vertical space, so this also doubles
        # as the exact scroll-content-height unit.
        adv_h = int(36*H/1080) + int(92*H/1080) + int(60*H/1080) + lbl_h + section_gap

        view_top    = ly
        view_bottom = pa.bottom - int(10*H/1080)
        view_h      = view_bottom - view_top
        content_h   = len(games_list) * adv_h
        self._an_scroll_max = max(0, content_h - view_h)
        self._an_scroll     = max(0, min(self._an_scroll, self._an_scroll_max))
        scrollable  = self._an_scroll_max > 0
        arrow_w     = self._tt(44) if scrollable else 0
        content_right = pa.right - int(16*W/1920) - (arrow_w + self._sc(8) if scrollable else 0)

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, view_top, content_right - pa.x - 1, view_h))
        cy = view_top - self._an_scroll
        for g_idx, (game_name, g_sessions) in enumerate(games_list):
            if cy + adv_h >= view_top and cy <= view_bottom:
                bar_col  = GAME_COLORS[g_idx % len(GAME_COLORS)]
                g_total  = len(g_sessions)
                g_durs   = [s.get("duration_sec", 0) for s in g_sessions]
                # rate = score / duration (pts/s); guard against zero duration
                g_rates  = [s.get("score", 0) / max(s.get("duration_sec", 1), 1)
                            for s in g_sessions]
                g_best   = max(g_rates)
                g_avg    = sum(g_rates) / g_total
                g_tmin, g_tsec = divmod(sum(g_durs), 60)

                # Section heading
                surface.blit(self.fnt["section"].render(game_name, True, bar_col),
                             (lx, cy))
                pygame.draw.line(surface, bar_col,
                                 (lx, cy + int(28*H/1080)),
                                 (content_right, cy + int(28*H/1080)), 1)
                stat_y = cy + int(36*H/1080)

                # Stat boxes
                stat_items = [
                    ("Sessions",    str(g_total)),
                    ("Best (pts/s)", f"{g_best:.3f}"),
                    ("Avg (pts/s)",  f"{g_avg:.3f}"),
                    ("Play Time",   f"{g_tmin}m {g_tsec}s" if g_tmin else f"{g_tsec}s"),
                ]
                sw = int((content_right - lx - int(48*W/1920)) // 4)
                for si, (lbl, val) in enumerate(stat_items):
                    sx = lx + si * (sw + int(16*W/1920))
                    box = pygame.Rect(sx, stat_y, sw, int(70*H/1080))
                    _card_bg(surface, box, alpha=235,
                             border_col=(*bar_col, 255), border_w=1)
                    surface.blit(self.fnt["tag"].render(lbl, True, (100,120,150)),
                                 (sx + int(8*W/1920), stat_y + int(8*H/1080)))
                    surface.blit(self.fnt["body_b"].render(val, True, bar_col),
                                 (sx + int(8*W/1920), stat_y + int(34*H/1080)))
                chart_y = stat_y + int(92*H/1080)

                # Mini bar chart — last 8 sessions, bars = score/duration (pts/s)
                recent       = g_sessions[:8][::-1]
                recent_rates = g_rates[-len(recent):][::-1] if len(g_sessions) >= len(recent) else g_rates[::-1]
                if recent:
                    max_r     = max(recent_rates) or 1
                    bar_w     = int((content_right - lx - int(48*W/1920)) // len(recent))
                    bar_h_max = int(60*H/1080)
                    for i, (s, rate) in enumerate(zip(recent, recent_rates)):
                        bh = max(4, int(bar_h_max * rate / max_r))
                        bx = lx + i * (bar_w + 4)
                        br = pygame.Rect(bx, chart_y + bar_h_max - bh, bar_w - 4, bh)
                        pygame.draw.rect(surface, bar_col, br, border_radius=4)
                        sc_s = self.fnt["time"].render(f"{rate:.2f}",
                                                       True, (80, 100, 130))
                        surface.blit(sc_s, sc_s.get_rect(
                            midtop=(br.centerx, chart_y + bar_h_max + int(4*H/1080))))
            cy += adv_h
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when analytics overflow the viewport) ─
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - int(8*W/1920) - arrow_w
            self._an_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._an_down_rect = pygame.Rect(ax, view_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._an_up_rect, "▲", self._an_scroll > 0),
                               (self._an_down_rect, "▼", self._an_scroll < self._an_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._an_up_rect = self._an_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 3: CALIBRATION RECORDS
    # ──────────────────────────────────────────────────────────────────

    def _draw_calibration(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        _card_bg(surface, pa, alpha=220)
        table_y = pa.y + int(28*H/1080)

        pt = self._view_patient()
        if not pt:
            _empty_state(surface,
                         pygame.Rect(pa.x, table_y+int(48*H/1080), pa.width,
                                     pa.bottom-table_y-int(48*H/1080)),
                         "👤", "No patient selected",
                         "Select a patient from the Patient List to view calibration records.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._cr_up_rect = self._cr_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        records = (self.db.get_calibrations(self.account["id"],
                                             patient_id=pt["id"])
                   if hasattr(self.db, "get_calibrations") else [])

        cols   = ["Game", "Sensor", "Avg", "Threshold", "Sensitivity", "Date", "Therapist"]
        col_xs = [pa.x+int(16*W/1920),  pa.x+int(230*W/1920), pa.x+int(430*W/1920),
                  pa.x+int(570*W/1920), pa.x+int(720*W/1920),  pa.x+int(880*W/1920),
                  pa.x+int(1040*W/1920)]
        for cx, c in zip(col_xs, cols):
            surface.blit(self.fnt["section"].render(c, True, (85,105,135)), (cx, table_y))
        pygame.draw.line(surface, (210,218,230),
                         (pa.x+int(16*W/1920), table_y+int(32*H/1080)),
                         (pa.right-int(16*W/1920), table_y+int(32*H/1080)), 1)

        if not records:
            _empty_state(surface,
                         pygame.Rect(pa.x, table_y+int(48*H/1080), pa.width,
                                     pa.bottom-table_y-int(48*H/1080)),
                         "🎯", "No calibration records yet",
                         f"No calibration data found for {pt.get('full_name', 'this patient')}.",
                         self.fnt["empty_head"], self.fnt["small_i"])
            self._cr_up_rect = self._cr_down_rect = pygame.Rect(0, 0, 1, 1)
            return

        row_h       = int(38*H/1080)
        view_top    = table_y + int(44*H/1080)
        view_bottom = pa.bottom - int(10*H/1080)
        view_h      = view_bottom - view_top
        content_h   = len(records) * row_h
        self._cr_scroll_max = max(0, content_h - view_h)
        self._cr_scroll     = max(0, min(self._cr_scroll, self._cr_scroll_max))
        scrollable  = self._cr_scroll_max > 0
        arrow_w     = self._tt(44) if scrollable else 0
        content_right = pa.right - int(8*W/1920) - (arrow_w + self._sc(8) if scrollable else 0)

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pa.x+1, view_top, content_right - pa.x - 1, view_h))
        for j, rec in enumerate(records):
            ry = view_top + j * row_h - self._cr_scroll
            if ry + row_h <= view_top or ry >= view_bottom:
                continue
            if j % 2 == 0:
                row_r = pygame.Rect(pa.x+int(8*W/1920), ry, pa.width-int(16*W/1920), row_h)
                bg = pygame.Surface((row_r.width, row_r.height), pygame.SRCALPHA)
                pygame.draw.rect(bg, (240,246,255,160),
                                 (0,0,row_r.width,row_r.height), border_radius=6)
                surface.blit(bg, row_r.topleft)

            date_str = str(rec.get("calibrated_at", ""))[:10]
            game_disp = rec.get("game_name") or rec.get("game_type", "—")
            vals = [
                game_disp,
                rec.get("sensor", "—"),
                f"{rec.get('average', 0):.3f}",
                f"{rec.get('threshold', 0):.3f}",
                rec.get("sensitivity", "—"),
                date_str,
                rec.get("therapist_name", "—"),
            ]
            for cx, v in zip(col_xs, vals):
                surface.blit(self.fnt["body"].render(v, True, (40,55,75)), (cx, ry+int(9*H/1080)))
        surface.set_clip(prev_clip)

        # ── scroll arrows (only when records overflow the viewport) ──
        if scrollable:
            ah = view_h // 2 - int(4*H/1080)
            ax = pa.right - int(8*W/1920) - arrow_w
            self._cr_up_rect   = pygame.Rect(ax, view_top, arrow_w, ah)
            self._cr_down_rect = pygame.Rect(ax, view_top + ah + int(8*H/1080), arrow_w, ah)
            for r, tri, on in ((self._cr_up_rect, "▲", self._cr_scroll > 0),
                               (self._cr_down_rect, "▼", self._cr_scroll < self._cr_scroll_max)):
                pygame.draw.rect(surface, (226,238,250) if on else (238,240,244), r, border_radius=8)
                pygame.draw.rect(surface, (150,175,210), r, 1, border_radius=8)
                gc = (45,90,150) if on else (185,193,203)
                g = self.fnt["nav_sym"].render(tri, True, gc)
                surface.blit(g, g.get_rect(center=r.center))
        else:
            self._cr_up_rect = self._cr_down_rect = pygame.Rect(0, 0, 1, 1)

    # ──────────────────────────────────────────────────────────────────
    #  PANEL 4: GAME CONFIGURATION
    # ──────────────────────────────────────────────────────────────────

    def _draw_game_config(self, surface, pa):
        W, H = self.WIDTH, self.HEIGHT
        gc   = self.gc
        touch = self._touch_ui
        _card_bg(surface, pa, alpha=220)
        self._game_tiles = []
        pad = int(16*W/1920)

        # ── Banner: who we're configuring for + controller status ─────
        pt    = self.selected_patient or {}
        pt_nm = pt.get("full_name","—")
        # Same source of truth as the sidebar monitor, so the two never disagree.
        _stage, _lab, _det, dot_col, txt_col = self._controller_status()
        if touch:
            ble_text = {"connected": "Controller ready",
                        "scanning":  "Searching…",
                        "connecting": "Connecting…"}.get(_stage, _lab)
        else:
            ble_text = _lab if _stage != "connected" else "Controller Connected"

        ban_h = self._tt(72) if touch else int(50*H/1080)
        ban_r = pygame.Rect(pa.x+pad, pa.y+int(12*H/1080), pa.width-2*pad, ban_h)
        pygame.draw.rect(surface,(232,244,255),ban_r,border_radius=10)
        pygame.draw.rect(surface,(160,205,245),ban_r,1,border_radius=10)
        f_ban = self.fnt["body"] if touch else self.fnt["small"]
        if touch:
            surface.blit(f_ban.render(f"Configuring for:  {pt_nm}", True,(50,100,160)),
                         (ban_r.x+int(14*W/1920), ban_r.y+int(8*H/1080)))
            l2 = self.fnt["small"].render(f"Patient ID: {pt.get('patient_id_str','—')}",
                                         True,(80,110,150))
            surface.blit(l2, (ban_r.x+int(14*W/1920), ban_r.bottom - l2.get_height() - int(8*H/1080)))
            bs = self.fnt["small"].render(ble_text, True, txt_col)
            dr = int(7*H/1080)
            bx = ban_r.right - bs.get_width() - int(20*W/1920)
            pygame.draw.circle(surface, dot_col, (bx-dr-int(6*W/1920), ban_r.bottom-l2.get_height()//2-int(8*H/1080)), dr)
            surface.blit(bs, (bx, ban_r.bottom - bs.get_height() - int(8*H/1080)))
        else:
            surface.blit(f_ban.render(f"Configuring session for:  {pt_nm}",
                         True,(50,100,160)),(ban_r.x+int(12*W/1920),ban_r.y+int(15*H/1080)))
            bs = self.fnt["small"].render(ble_text, True, txt_col)
            dr = int(7*H/1080)
            dx = ban_r.right - bs.get_width() - dr*2 - int(24*W/1920)
            pygame.draw.circle(surface, dot_col, (dx, ban_r.centery), dr)
            surface.blit(bs, (dx + dr + int(8*W/1920), ban_r.centery - bs.get_height()//2))

        # ── Game tiles ───────────────────────────────────────────────
        tg = int(14*W/1920)
        if touch:
            tw = (pa.width - 2*pad - 2*tg) // 3
            th = self._tt(74)
        else:
            tw = int(460*W/1920); th = int(120*H/1080)

        game_y = ban_r.bottom + int((22 if touch else 24)*H/1080)
        surface.blit((self.fnt["body_b"] if touch else self.fnt["small"]).render(
            "Single Skill Games", True, (75,95,125)), (pa.x + pad, game_y))
        ty = game_y + (self.fnt["body_b"] if touch else self.fnt["small"]).get_height() + int(10*H/1080)

        ss_total_w = len(SINGLE_SKILL_GAMES) * tw + (len(SINGLE_SKILL_GAMES) - 1) * tg
        ss_start_x = pa.x + (pa.width - ss_total_w) // 2
        for i, (gname, gtype) in enumerate(SINGLE_SKILL_GAMES):
            tx  = ss_start_x + i * (tw + tg)
            tr  = pygame.Rect(tx, ty, tw, th)
            sel = gc["selected_game"] and gc["selected_game"][1] == gtype
            bc  = PANEL_COLORS.get(i, (180,200,220)) if sel else (210,220,235)
            _card_bg(surface, tr, alpha=245 if sel else 200, border_col=bc, border_w=2 if sel else 1)
            _fg = self.fnt["label"] if touch else self.fnt["body_b"]
            if sel and gc["selected_game"]:
                lbl_s = _fg.render(gtype, True, bc)
                surface.blit(lbl_s, lbl_s.get_rect(midleft=(tr.x + int(14*W/1920), tr.centery - _fg.get_height()//2)))
                sub = self.fnt["small"].render(gc["selected_game"][0], True, bc)
                surface.blit(sub, sub.get_rect(midleft=(tr.x + int(14*W/1920), tr.centery + _fg.get_height()//2)))
            else:
                lbl_s = _fg.render(gtype, True, (55,72,95))
                surface.blit(lbl_s, lbl_s.get_rect(midleft=(tr.x + int(14*W/1920), tr.centery)))
            self._game_tiles.append((tr, (gname, gtype)))

        ig_label_y = ty + th + int((24 if touch else 50)*H/1080)
        surface.blit((self.fnt["body_b"] if touch else self.fnt["small"]).render(
            "Integrated Games", True, (75,95,125)), (pa.x + pad, ig_label_y))
        gy2 = ig_label_y + (self.fnt["body_b"] if touch else self.fnt["small"]).get_height() + int(10*H/1080)

        ig_total_w = len(INTEGRATED_GAMES) * tw + (len(INTEGRATED_GAMES) - 1) * tg
        ig_start_x = pa.x + (pa.width - ig_total_w) // 2
        for i, (gname, gtype) in enumerate(INTEGRATED_GAMES):
            tx  = ig_start_x + i * (tw + tg)
            tr  = pygame.Rect(tx, gy2, tw, th)
            sel = gc["selected_game"] and gc["selected_game"][1] == gtype
            bc  = PANEL_COLORS.get(i + 3, (180,200,220)) if sel else (210,220,235)
            _card_bg(surface, tr, alpha=245 if sel else 200, border_col=bc, border_w=2 if sel else 1)
            _fg = self.fnt["label"] if touch else self.fnt["body_b"]
            if sel and gc["selected_game"]:
                lbl_s = _fg.render(gtype, True, bc)
                surface.blit(lbl_s, lbl_s.get_rect(midleft=(tr.x + int(14*W/1920), tr.centery - _fg.get_height()//2)))
                sub = self.fnt["small"].render(gc["selected_game"][0], True, bc)
                surface.blit(sub, sub.get_rect(midleft=(tr.x + int(14*W/1920), tr.centery + _fg.get_height()//2)))
            else:
                lbl_s = _fg.render(gname, True, (55,72,95))
                surface.blit(lbl_s, lbl_s.get_rect(center=tr.center))
            self._game_tiles.append((tr, (gname, gtype)))

        # ── Proceed to Start Calibration button ───────────────────────
        game_chosen = gc["selected_game"] is not None
        if touch:
            bw = self.fnt["btn"].size("Start Calibration")[0] + self._tt(40)
            next_r = pygame.Rect(pa.right - pad - bw, pa.bottom - self._tt(60) - int(8*H/1080),
                                 bw, self._tt(58))
        else:
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

        cal_done     = self.calibration_done or self.calibration_bypassed
        cal_mismatch = self._calibration_mismatched()

        if self._touch_ui:
            self._draw_start_session_touch(surface, pa, gc, pt, cal_done, cal_mismatch)
            return

        cx0 = pa.x + int(20*W/1920)
        cy0 = pa.y + int(20*H/1080)

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
        _game_type = (gc.get("selected_game") or (None, ""))[1] or ""
        ss_params = [
            ("duration", "Duration", gc["duration"],
             ["60 seconds", "120 seconds", "180 seconds"]),
        ]
        if _game_type != "Wrist Rotation":
            ss_params.append(
                ("speed", "Speed", gc["speed"], ["Slow", "Normal", "Fast"])
            )
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
                          "Wrist Rotation": "Motion Sensor",
                          "Dual Skill": "Force + Motion Sensors"}
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
                "Dual Skill": "Force + Motion Sensors",
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

    # ── PANEL 5 (7-inch): single-column, touch-first layout ──────────
    def _draw_start_session_touch(self, surface, pa, gc, pt, cal_done, cal_mismatch):
        W, H = self.WIDTH, self.HEIGHT
        pad = int(16*W/1920)
        x0  = pa.x + pad
        y   = pa.y + int(10*H/1080)

        gname = gc["selected_game"][0] if gc["selected_game"] else "—"
        gtype = (gc.get("selected_game") or (None, ""))[1] or ""

        # ── readiness checklist (compact) ──
        steps = [
            ("Patient selected",   True),
            ("Game configured",    gc["selected_game"] is not None),
            ("Calibration " + ("mismatch" if cal_mismatch else "complete"),
             cal_done and not cal_mismatch),
            ("Ready to start",     self._session_ready() and not cal_mismatch),
        ]
        rh  = self._sc(42)
        dot = self._sc(7)
        for lbl, ok in steps:
            col = (55,175,75) if ok else ((220,140,30) if ("mismatch" in lbl) else (196,206,220))
            pygame.draw.circle(surface, col, (x0 + dot, y + rh//2), dot)
            tcl = (40,55,75) if ok else ((170,105,15) if "mismatch" in lbl else (130,145,165))
            s = self.fnt["body"].render(lbl, True, tcl)
            surface.blit(s, (x0 + self._sc(28), y + (rh - s.get_height())//2))
            y += rh
        y += int(10*H/1080)

        # ── session details card ──
        sd = pygame.Rect(x0, y, pa.width - 2*pad, self._tt(210))
        _card_bg(surface, sd, alpha=235, border_col=(185,210,240), border_w=1)
        sy = sd.y + int(10*H/1080)
        surface.blit(self.fnt["body_b"].render("Session Details", True, (75,95,125)),
                     (sd.x + int(12*W/1920), sy))
        sy += self.fnt["body_b"].get_height() + int(6*H/1080)
        for line in (f"Patient:  {pt.get('full_name','—')}", f"Game:  {gname}"):
            surface.blit(self.fnt["body"].render(line, True, (50,65,90)),
                         (sd.x + int(12*W/1920), sy))
            sy += self.fnt["body"].get_height() + int(6*H/1080)

        # duration / speed dropdown fields (large)
        params = [("duration", "Duration", gc["duration"])]
        if gtype != "Wrist Rotation":
            params.append(("speed", "Speed", gc["speed"]))
        self._ss_param_rects = {}
        fw = (sd.width - int(36*W/1920)) // 2
        fx = sd.x + int(12*W/1920)
        fy = sd.bottom - self._tt(52) - int(12*H/1080)
        for pk, plbl, pval in params:
            surface.blit(self.fnt["small"].render(plbl, True, (88,108,138)),
                         (fx, fy - self.fnt["small"].get_height() - int(2*H/1080)))
            pr = pygame.Rect(fx, fy, fw, self._tt(52))
            active = self._ss_open_param and self._ss_open_param[0] == pk
            pygame.draw.rect(surface, (255,255,255), pr, border_radius=10)
            pygame.draw.rect(surface, (40,160,220) if active else (185,205,228),
                             pr, 2 if active else 1, border_radius=10)
            surface.blit(self.fnt["input"].render(pval, True, (40,55,80)),
                         self.fnt["input"].render(pval, True, (40,55,80)).get_rect(
                             midleft=(pr.x + int(10*W/1920), pr.centery)))
            surface.blit(self.fnt["sym26"].render("▼", True, (90,110,140)),
                         self.fnt["sym26"].render("▼", True, (90,110,140)).get_rect(
                             midright=(pr.right - int(10*W/1920), pr.centery)))
            self._ss_param_rects[pk] = pr
            fx += fw + int(12*W/1920)
        y = sd.bottom + int(14*H/1080)

        # ── calibration status + button ──
        if cal_mismatch:
            cs_txt, cs_col, cal_lbl = "Sensor mismatch — recalibrate", (170,110,10), "Calibrate"
        elif self.calibration_done and not self.calibration_bypassed:
            cs_txt, cs_col, cal_lbl = "Calibration complete", (30,140,60), "Re-Calibrate"
        elif cal_done:
            cs_txt, cs_col, cal_lbl = "Calibration bypassed (DEV)", (30,140,60), None
        else:
            cs_txt, cs_col, cal_lbl = "Calibration required", (160,110,20), "Calibrate"
        surface.blit(self.fnt["body_b"].render(cs_txt, True, cs_col), (x0, y + int(6*H/1080)))
        if cal_lbl:
            cw = self.fnt["btn"].size(cal_lbl)[0] + self._tt(36)
            cal_r = pygame.Rect(pa.right - pad - cw, y, cw, self._tt(52))
            _btn(surface, cal_r, cal_lbl, self.fnt["btn"], (225,165,30), (195,135,15),
                 self._calibrate_hov, radius=10)
            self._calibrate_btn_rect = cal_r
        else:
            self._calibrate_btn_rect = pygame.Rect(0,0,1,1)

        # ── bottom action row: Bypass (small) + Start Session (big) ──
        bb_lbl = "Disable Bypass" if cal_done else "Bypass Calibration"
        bb_w = self.fnt["small"].size(bb_lbl)[0] + self._tt(28)
        byp_r = pygame.Rect(x0, pa.bottom - self._tt(50) - int(6*H/1080), bb_w, self._tt(46))
        _btn(surface, byp_r, bb_lbl, self.fnt["small"],
             (160,60,60) if cal_done else (110,110,128),
             (130,35,35) if cal_done else (85,85,105), self._bypass_hov, radius=8)
        self._bypass_btn_rect = byp_r

        ready = self._session_ready()
        sw2 = self.fnt["btn"].size("Start Session")[0] + self._tt(52)
        st_r = pygame.Rect(pa.right - pad - sw2, pa.bottom - self._tt(60) - int(4*H/1080),
                           sw2, self._tt(58))
        _btn(surface, st_r, "Start Session", self.fnt["btn"],
             (40,160,80) if ready else (175,188,202),
             (28,130,62) if ready else (155,168,182), self.start_hov and ready, radius=14)
        self._start_btn_rect = st_r if ready else pygame.Rect(0,0,1,1)
        self._ss_custom_dur_rect = pygame.Rect(0,0,1,1)

        # ── open dropdown list (on top) ──
        if self._ss_open_param:
            open_key, open_opts = self._ss_open_param
            pr = self._ss_param_rects.get(open_key)
            if pr:
                opt_h = self._tt(44)
                dp = pygame.Rect(pr.x, pr.bottom, pr.width, len(open_opts)*opt_h + 4)
                pygame.draw.rect(surface, (248,251,255), dp, border_radius=8)
                pygame.draw.rect(surface, (40,160,220), dp, 2, border_radius=8)
                for j, ov in enumerate(open_opts):
                    orr = pygame.Rect(pr.x, pr.bottom + j*opt_h, pr.width, opt_h)
                    if orr.collidepoint(pygame.mouse.get_pos()):
                        pygame.draw.rect(surface, (223,238,255), orr, border_radius=6)
                    surface.blit(self.fnt["input"].render(ov, True, (40,50,65)),
                                 self.fnt["input"].render(ov, True, (40,50,65)).get_rect(
                                     midleft=(orr.x + int(10*W/1920), orr.centery)))

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
        pygame.draw.rect(ms, (228, 238, 252, 252), (0, 0, mr.width, mr.height), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface,(175,205,235),mr,1,border_radius=16)
        hs = self.fnt["panel_title"].render("Edit Profile",True,(38,52,78))
        surface.blit(hs,(mr.x+self._sc(18), mr.y+self._sc(10)))

        bcx,bcy = self.edit_big_center
        draw_icon(surface,self.edit_selected_icon,bcx,bcy,self.edit_big_r,shadow=True,
                  border_color=(40,160,220), border_width=3)
        # "Change Icon" -- opens the dedicated picker popup (large, scrollable)
        cr = self.edit_change_icon_rect
        pygame.draw.rect(surface, (236, 242, 250), cr, border_radius=9)
        pygame.draw.rect(surface, (95, 130, 175), cr, 2, border_radius=9)
        chg_lbl = "Change Icon"
        cs = self.fnt["tag"].render(chg_lbl, True, (60, 95, 150))
        if cs.get_width() > cr.width - self._sc(8):
            cs = self.fnt["tag"].render("Change", True, (60, 95, 150))
        surface.blit(cs, cs.get_rect(center=cr.center))

        for i,field in enumerate(self.edit_fields):
            active=(i==self.edit_active_field)
            rect=field["rect"]
            surface.blit(self.fnt["small"].render(field["label"],True,(80,95,115)),
                         (rect.x, rect.y-self.fnt["small"].get_height()-self._sc(4)))
            bc=(40,160,220) if active else (185,205,228)
            pygame.draw.rect(surface,(255,255,255),rect,border_radius=9)
            pygame.draw.rect(surface,bc,rect,3 if active else 1,border_radius=9)
            if field["key"]=="role":
                val=field["value"] or field["placeholder"]
                ts=self.fnt["input"].render(val,True,(40,50,65) if field["value"] else (175,188,205))
                surface.blit(ts,ts.get_rect(midleft=(rect.x+self._sc(12),rect.centery)))
                chev=self.fnt["sym26"].render("▼",True,(95,115,145))
                surface.blit(chev,chev.get_rect(midright=(rect.right-self._sc(12),rect.centery)))
            else:
                val=field["value"]
                ts=(self.fnt["input"].render("•"*len(val) if field["is_pin"] else val,
                    True,(40,50,65)) if val else
                    self.fnt["input"].render(field["placeholder"],True,(175,188,205)))
                surface.blit(ts,ts.get_rect(midleft=(rect.x+self._sc(12),rect.centery)))
                if active and val:
                    cx2=rect.x+self._sc(12)+ts.get_width()+2
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
                ts=self.fnt["input"].render(opt["label"],True,(40,50,65))
                surface.blit(ts,ts.get_rect(midleft=(opt["rect"].x+self._sc(12),opt["rect"].centery)))

        if self.edit_error:
            es=self.fnt["modal_err"].render(self.edit_error,True,(210,50,50))
            surface.blit(es,(mr.x+self._sc(18),
                             self.edit_save_rect.y-es.get_height()-self._sc(6)))

        for rect,cn,ch,hov,lbl,fnt in [
            (self.edit_save_rect,  (40,160,220),(25,125,180),self.edit_save_hov,  "Save",           self.fnt["btn"]),
            (self.edit_cancel_rect,(175,190,210),(148,162,180),self.edit_cancel_hov,"Cancel",        self.fnt["btn"]),
            (self.edit_delete_rect,(200,50,50),(165,28,28),self.edit_delete_hov,"Delete Account",    self.fnt["small"]),
        ]:
            pygame.draw.rect(surface,ch if hov else cn,rect,border_radius=10)
            s=fnt.render(lbl,True,(255,255,255))
            surface.blit(s,s.get_rect(center=rect.center))

    def _draw_icon_picker_popup(self, surface):
        """Dedicated icon-selection popup: bigger than the old inline rail,
        icons sized generously from the popup's own width (not shrunk to
        force all 10 to fit at once), and scrollable when they don't."""
        W, H = self.WIDTH, self.HEIGHT
        pad = self._sc(20)
        pw = min(int(W * 0.92), self._sc(560))
        ph = min(int(H * 0.94), self._sc(440))
        px = (W - pw) // 2
        py = (H - ph) // 2
        pr = pygame.Rect(px, py, pw, ph)

        ms = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(ms, (250, 252, 255, 255), (0, 0, pw, ph), border_radius=18)
        surface.blit(ms, pr.topleft)
        pygame.draw.rect(surface, (175, 205, 235), pr, 2, border_radius=18)

        title = self.fnt["panel_title"].render("Choose Profile Icon", True, (38, 52, 78))
        surface.blit(title, (pr.x + pad, pr.y + self._sc(12)))
        hl_y = pr.y + self._sc(12) + title.get_height() + self._sc(8)
        pygame.draw.line(surface, (200, 218, 240), (pr.x + pad, hl_y), (pr.right - pad, hl_y), 1)

        btn_h = self._tt(48)
        top = hl_y + self._sc(14)
        bottom = pr.bottom - pad - btn_h - self._sc(10)
        view_h = bottom - top

        # Icons sized from the popup's own width -- comfortably large and
        # spaced, but pulled in a bit from the earlier oversized cap -- with
        # however many rows that takes, scrolling if they don't all fit
        # rather than shrinking them back down to the old cramped size.
        cols = 3
        gap = self._sc(18)
        avail_w = pw - 2 * pad
        r = max(self._sc(24), min(self._sc(46), (avail_w - (cols - 1) * gap) // (2 * cols)))
        self._eip_r = r
        step = 2 * r + gap
        rows_n = (10 + cols - 1) // cols
        total_h = rows_n * step - gap
        self._eip_scroll_max = max(0, total_h - view_h)
        self._eip_scroll = max(0, min(self._eip_scroll, self._eip_scroll_max))
        arrow_w = self._tt(40) if self._eip_scroll_max > 0 else 0
        grid_w = cols * step - gap
        grid_cx = pr.x + pad + (avail_w - (arrow_w + self._sc(8) if arrow_w else 0)) // 2

        prev_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(pr.x, top, pw, view_h))
        self._eip_circles = []
        y0 = top - self._eip_scroll
        for i in range(10):
            idx = i + 1
            col, row = i % cols, i // cols
            cx = grid_cx + (col - (cols - 1) / 2) * step
            cy = y0 + r + row * step
            if cy + r < top or cy - r > bottom:
                continue
            self._eip_circles.append((int(cx), int(cy), idx))
            sel = (self.edit_selected_icon == idx)
            draw_icon(surface, idx, int(cx), int(cy), r, shadow=True,
                     border_color=(40, 160, 220) if sel else None,
                     border_width=max(3, self._sc(4)) if sel else 0)
        surface.set_clip(prev_clip)

        if self._eip_scroll_max > 0:
            ax = pr.right - pad - arrow_w
            ah = view_h // 2 - self._sc(4)
            self._eip_up_rect = pygame.Rect(ax, top, arrow_w, ah)
            self._eip_down_rect = pygame.Rect(ax, top + ah + self._sc(8), arrow_w, ah)
            for r2, tri, on in ((self._eip_up_rect, "▲", self._eip_scroll > 0),
                               (self._eip_down_rect, "▼",
                                self._eip_scroll < self._eip_scroll_max)):
                pygame.draw.rect(surface, (226, 238, 250) if on else (238, 240, 244),
                                 r2, border_radius=8)
                pygame.draw.rect(surface, (150, 175, 210), r2, 1, border_radius=8)
                g = self.fnt["sym26"].render(tri, True,
                                             (45, 90, 150) if on else (188, 196, 206))
                surface.blit(g, g.get_rect(center=r2.center))
        else:
            self._eip_up_rect = self._eip_down_rect = pygame.Rect(0, 0, 1, 1)

        done_w = self._sc(160)
        self._eip_done_rect = pygame.Rect(pr.centerx - done_w // 2,
                                          pr.bottom - pad - btn_h, done_w, btn_h)
        hov = self._eip_done_rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, (25, 130, 185) if hov else (40, 160, 220),
                         self._eip_done_rect, border_radius=10)
        ds = self.fnt["btn"].render("Done", True, (255, 255, 255))
        surface.blit(ds, ds.get_rect(center=self._eip_done_rect.center))

    def _draw_skill_game_modal(self, surface):
        # Sized from _sc/_tt so rows and the Close button stay finger-sized on
        # the 800x480 panel -- the old H/1080-only math produced ~21px rows
        # and a ~16px-tall Close button here.
        W, H = self.WIDTH, self.HEIGHT
        skill = self._gc_skill_modal_type or ""
        games = SKILL_GAMES.get(skill, [])

        pad      = self._sc(22)
        item_gap = self._sc(8)
        item_h   = self._tt(52)
        btn_h    = self._tt(44)
        header_h = self.fnt["modal_lbl"].get_height() + self._sc(20)
        footer_h = self._sc(16) + btn_h + self._sc(16)

        ts = self.fnt["modal_lbl"].render(f"Select a Game  —  {skill}", True, (38, 52, 78))
        row_w_needed = max((self.fnt["body_b"].size(g)[0] for g in games), default=0) + self._sc(32)
        mw = min(max(ts.get_width() + pad * 2, row_w_needed + pad * 2, self._sc(360)), int(W * 0.9))
        mh = min(header_h + len(games) * (item_h + item_gap) + footer_h, int(H * 0.92))
        mx = (W - mw) // 2
        my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (245, 249, 255, 255), (0, 0, mw, mh), border_radius=14)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (100, 160, 220), mr, 2, border_radius=14)

        # Title
        surface.blit(ts, ts.get_rect(midleft=(mr.x + pad, mr.y + header_h // 2)))
        pygame.draw.line(surface, (200, 218, 240),
                         (mr.x + pad, mr.y + header_h),
                         (mr.right - pad, mr.y + header_h), 1)

        # Game option rows
        self._gc_skill_modal_rects = []
        mp = pygame.mouse.get_pos()
        for j, game_name in enumerate(games):
            gr = pygame.Rect(mr.x + pad,
                             mr.y + header_h + j * (item_h + item_gap),
                             mw - pad * 2, item_h)
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
            surface.blit(gs, gs.get_rect(midleft=(gr.x + self._sc(16), gr.centery)))
            self._gc_skill_modal_rects.append((gr, game_name))

        # Close / Cancel button
        close_r = pygame.Rect(mr.centerx - self._sc(70), mr.bottom - self._sc(16) - btn_h,
                              self._sc(140), btn_h)
        self._gc_skill_modal_close = close_r
        close_hov = close_r.collidepoint(mp)
        close_col = (145, 158, 178) if not close_hov else (118, 130, 150)
        pygame.draw.rect(surface, close_col, close_r, border_radius=10)
        cls = self.fnt["btn"].render("Cancel", True, (255, 255, 255))
        surface.blit(cls, cls.get_rect(center=close_r.center))

    def _draw_register_success_modal(self, surface):
        # Sized from its own content -- the old fixed 0.40W x 0.30H box spaced
        # the message lines 32*H/1080 (14px at 800x480) apart while the font
        # itself renders at 32px tall, so the two lines visibly overlapped.
        W, H = self.WIDTH, self.HEIGHT
        pad   = self._sc(20)
        ck_r  = self._sc(24)
        max_w = int(W * 0.7)

        ts     = self.fnt["modal_lbl"].render("Registration Successful", True, (30, 120, 65))
        # Wrap each line to the width cap FIRST -- a long patient name must
        # wrap instead of forcing the modal wider than the cap (which would
        # just clip it against the box edges instead).
        lines = []
        for raw in self._rp_success_msg.split("\n"):
            lines.extend(self._wrap(raw, self.fnt["body"], max_w - pad * 2))
        line_h    = self.fnt["body"].get_linesize()
        msg_surfs = [self.fnt["body"].render(ln, True, (45, 65, 85)) for ln in lines]
        btn_h     = self._tt(44)

        content_w = max([ts.get_width()] + [s.get_width() for s in msg_surfs])
        mw = min(max(content_w + pad * 2, self._sc(320)), max_w)
        mh = (pad + ck_r * 2 + self._sc(10) + ts.get_height() + self._sc(12)
              + len(lines) * line_h + self._sc(18) + btn_h + pad)
        mx = (W - mw) // 2;  my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (245, 252, 248, 255), (0, 0, mw, mh), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (80, 190, 120), mr, 2, border_radius=16)

        # Checkmark circle
        ck_cy = my + pad + ck_r
        pygame.draw.circle(surface, (60, 185, 100), (mr.centerx, ck_cy), ck_r)
        ck = self.fnt["sym29"].render("✓", True, (255, 255, 255))
        surface.blit(ck, ck.get_rect(center=(mr.centerx, ck_cy)))

        # Title
        ty = ck_cy + ck_r + self._sc(10)
        surface.blit(ts, ts.get_rect(midtop=(mr.centerx, ty)))
        ty += ts.get_height() + self._sc(12)

        # Message lines (split on \n) -- spaced by the font's own line height
        for s in msg_surfs:
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += line_h

        # OK button
        bw = self.fnt["btn"].size("OK")[0] + self._sc(60)
        ok_r = pygame.Rect(mr.centerx - bw // 2, mr.bottom - pad - btn_h, bw, btn_h)
        self._rp_ok_rect = ok_r
        ok_col = (40, 160, 90) if not self._rp_ok_hov else (28, 130, 68)
        pygame.draw.rect(surface, ok_col, ok_r, border_radius=10)
        oks = self.fnt["btn"].render("OK", True, (255, 255, 255))
        surface.blit(oks, oks.get_rect(center=ok_r.center))

    def _draw_calibration_mismatch_modal(self, surface):
        # Sized from its own content -- the old fixed 0.46W x 0.38H box spaced
        # 7 lines 28*H/1080 (12px at 800x480) apart while modal_lbl renders at
        # 32px tall, so nearly every line visibly overlapped the next.
        W, H  = self.WIDTH, self.HEIGHT
        pad   = self._sc(20)
        ic_r  = self._sc(24)

        ts = self.fnt["modal_head"].render("Sensor Mismatch", True, (160, 100, 10))

        res       = self.calibration_result or {}
        cal_type  = res.get("game_type", "—")
        cal_sens  = res.get("sensor",    "—")
        need_type = (self.gc.get("selected_game") or (None, "—"))[1] or "—"
        SENSOR_FOR = {"Grip Strength":  "Force Sensor",
                      "Finger Flexion": "Flex Sensors",
                      "Wrist Rotation": "Motion Sensor",
                      "Dual Skill":     "Force + Motion Sensors"}
        need_sens  = SENSOR_FOR.get(need_type, "—")

        body_lines = [
            "The sensor calibration on file does not match the",
            "selected exercise type. Please recalibrate.",
            "",
            f"Calibrated for:  {cal_type}  ({cal_sens})",
            f"Required for:  {need_type}  ({need_sens})",
        ]
        line_h = self.fnt["modal_lbl"].get_linesize()
        body_surfs = []
        for line in body_lines:
            col = (90, 65, 20) if line.startswith(("Calibrated", "Required")) else (75, 85, 105)
            body_surfs.append(self.fnt["modal_lbl"].render(line or " ", True, col))

        btn_h = self._tt(46)
        bw    = max(self.fnt["btn"].size("Calibrate Now")[0],
                    self.fnt["btn"].size("Cancel")[0]) + self._sc(36)
        gap   = self._sc(16)

        content_w = max([ts.get_width()] + [s.get_width() for s in body_surfs] + [2 * bw + gap])
        mw = min(max(content_w + pad * 2, self._sc(360)), int(W * 0.86))
        mh = (pad + ic_r * 2 + self._sc(8) + ts.get_height() + self._sc(14)
              + len(body_lines) * line_h + self._sc(18) + btn_h + pad)
        mx = (W - mw) // 2
        my = (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        # background
        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        ms.fill((255, 248, 235, 255))
        surface.blit(ms, mr.topleft)
        hl = pygame.Surface((mw, 3), pygame.SRCALPHA)
        hl.fill((255, 255, 255, 200))
        surface.blit(hl, mr.topleft)
        pygame.draw.rect(surface, (220, 145, 30), mr, 2, border_radius=16)

        # warning icon circle
        ic_cy = my + pad + ic_r
        pygame.draw.circle(surface, (240, 165, 30), (mr.centerx, ic_cy), ic_r)
        ws = self.fnt["body_b"].render("!", True, (255, 255, 255))
        surface.blit(ws, ws.get_rect(center=(mr.centerx, ic_cy)))

        # title
        ty = ic_cy + ic_r + self._sc(8)
        surface.blit(ts, ts.get_rect(midtop=(mr.centerx, ty)))
        ty += ts.get_height() + self._sc(14)

        # body lines -- spaced by the font's own line height
        for s in body_surfs:
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += line_h

        # buttons
        by2 = mr.bottom - pad - btn_h
        cal_r = pygame.Rect(mr.centerx - bw - gap // 2, by2, bw, btn_h)
        can_r = pygame.Rect(mr.centerx + gap // 2,      by2, bw, btn_h)

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
        # Sized from its own title/body/button content -- see _draw_choice_modal
        # for why (the old fixed-offset layout overlapped title and body text).
        W,H=self.WIDTH,self.HEIGHT
        pad = self._sc(28)
        gap = self._sc(14)
        is_logout = (self.modal == "logout_confirm")
        is_del_pt  = (self.modal == "delete_patient_confirm")
        pt_name    = (self._ep_patient or {}).get("full_name", "this patient") if is_del_pt else ""
        title = ("Log out of RecovR?"         if is_logout else
                 f"Delete {pt_name}?"         if is_del_pt else
                 "Delete your account?")
        body  = ("You will be returned to the login screen." if is_logout
                 else "This action cannot be undone.")
        yes_l = "Logout" if is_logout else "Delete"

        max_content_w = int(W * 0.8) - pad * 2
        title_font = self.fnt["modal_head"]
        if title_font.size(title)[0] > max_content_w:
            title_font = self.fnt["modal_lbl"]
        title_lines  = self._wrap(title, title_font, max_content_w)
        title_surfs  = [title_font.render(ln, True, (38, 52, 78)) for ln in title_lines]
        title_line_h = title_font.get_linesize()

        yr, nr = self._confirm_rects()
        btn_row_w  = max(yr.right, nr.right) - min(yr.left, nr.left)
        body_lines = self._wrap(body, self.fnt["modal_lbl"], max_content_w)
        body_surfs = [self.fnt["modal_lbl"].render(ln, True, (98, 114, 140)) for ln in body_lines]
        line_h     = self.fnt["modal_lbl"].get_linesize()

        content_w = max([btn_row_w] + [s.get_width() for s in title_surfs]
                        + [s.get_width() for s in body_surfs])
        mw = min(max(content_w + pad * 2, self._sc(360)), int(W * 0.86))

        stack_h = len(title_lines) * title_line_h + gap + len(body_lines) * line_h
        mh = max(int(H*0.26), self._tt(320))
        my = (H - mh) // 2
        avail = (yr.top - self._sc(10)) - (my + pad)
        if stack_h > avail:
            mh += 2 * (stack_h - avail)
        mx, my = (W - mw) // 2, (H - mh) // 2
        mr=pygame.Rect(mx,my,mw,mh)
        ms=pygame.Surface((mw,mh),pygame.SRCALPHA)
        pygame.draw.rect(ms,(250,252,255,255),(0,0,mw,mh),border_radius=16)
        surface.blit(ms,mr.topleft)
        pygame.draw.rect(surface,(195,210,228),mr,2,border_radius=16)

        ty = my + pad
        for s in title_surfs:
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += title_line_h
        ty += gap
        for s in body_surfs:
            surface.blit(s, s.get_rect(midtop=(mr.centerx, ty)))
            ty += line_h
        yc=(175,25,25) if self.confirm_yes_hov else (205,45,45)
        nc=(148,162,180) if self.confirm_no_hov else (175,190,210)
        pygame.draw.rect(surface,yc,yr,border_radius=10)
        pygame.draw.rect(surface,nc,nr,border_radius=10)
        ys=self.fnt["btn"].render(yes_l,True,(255,255,255))
        ns=self.fnt["btn"].render("Cancel",True,(255,255,255))
        surface.blit(ys,ys.get_rect(center=yr.center))
        surface.blit(ns,ns.get_rect(center=nr.center))

    def _draw_delete_blocked_modal(self, surface):
        """Shown instead of deleting the account when the therapist still
        CURRENTLY owns patients (database.delete_therapist refused). A single
        dismiss button -- this is information, not a yes/no choice."""
        W, H = self.WIDTH, self.HEIGHT
        pad = self._sc(20)
        mw = max(int(W * 0.7), self._tt(560))
        title = "Patients not yet transferred"
        msg = ("There are patient accounts that have not been transferred yet. "
               "Please transfer all patients currently under your ownership "
               "before deleting your account.")
        lines = self._wrap(msg, self.fnt["modal_lbl"], mw - pad * 2)
        line_h = self.fnt["modal_lbl"].get_linesize()
        btn_h = self._tt(46)
        mh = self.fnt["modal_head"].get_height() + self._sc(16) + \
            len(lines) * line_h + self._sc(20) + btn_h + pad * 2
        mx, my = (W - mw) // 2, (H - mh) // 2
        mr = pygame.Rect(mx, my, mw, mh)

        ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
        pygame.draw.rect(ms, (250, 252, 255, 255), (0, 0, mw, mh), border_radius=16)
        surface.blit(ms, mr.topleft)
        pygame.draw.rect(surface, (225, 165, 60), mr, 2, border_radius=16)

        y = mr.y + pad
        ts = self.fnt["modal_head"].render(title, True, (170, 110, 15))
        surface.blit(ts, (mr.x + pad, y)); y += ts.get_height() + self._sc(16)
        for ln in lines:
            ls = self.fnt["modal_lbl"].render(ln, True, (70, 80, 95))
            surface.blit(ls, (mr.x + pad, y)); y += line_h

        bw = self._sc(150)
        ok_r = pygame.Rect(mr.right - pad - bw, mr.bottom - pad - btn_h, bw, btn_h)
        self._db_blocked_ok_rect = ok_r
        hov = ok_r.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, (60, 140, 220) if not hov else (45, 120, 195),
                         ok_r, border_radius=10)
        ok_s = self.fnt["btn"].render("Got it", True, (255, 255, 255))
        surface.blit(ok_s, ok_s.get_rect(center=ok_r.center))

    # ──────────────────────────────────────────────────────────────────
    #  UTILITIES
    # ──────────────────────────────────────────────────────────────────

    def _confirm_rects(self):
        W,H=self.WIDTH,self.HEIGHT
        bw=max(int(115*W/1920), self._tt(150)); bh=self._tt(46); gap=int(16*W/1920)
        cy=H//2+int(30*H/1080)
        return (pygame.Rect(W//2-bw-gap//2,cy,bw,bh),
                pygame.Rect(W//2+gap//2,cy,bw,bh))

    def _logout_rect(self):
        lw=int(self.WIDTH*(0.13 if self._touch_ui else 0.11))
        lh=max(int(self.HEIGHT*0.046), self._tt(44))
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