# =============================================================================
# main.py  —  RecovR entry point
# =============================================================================
#
#   python main.py
#       → launches the DUAL-MONITOR production application via
#         recovr.launch_production (the single, existing startup logic):
#           • session broker      — recovr.run_therapist  (headless Flask)
#           • Therapist Interface — this same file, re-run with
#                                   RECOVR_ROLE=therapist  (the scene loop below)
#           • Patient Interface   — recovr.run_patient
#
#   recovr.launch_production spawns the Therapist Interface by re-invoking this
#   file with RECOVR_ROLE=therapist; that path runs the therapist touchscreen
#   UI (scene loop below). No standalone startup happens any more — `python
#   main.py` is now the dual-monitor launcher.
#
# TOUCH vs MOUSE handling:
#   DO NOT set SDL_MOUSE_TOUCH_EVENTS=1.
#   That env-var makes SDL synthesise a MOUSEBUTTONDOWN from every touchscreen
#   tap, but it uses the touch panel's RAW pixel coordinates — which come from
#   the panel's own internal resolution (often different from the display) —
#   so every synthetic mouse click lands in the wrong place.
#
#   Instead we handle two separate event types:
#     • MOUSEBUTTONDOWN  — real physical mouse clicks (mouse device)
#     • FINGERDOWN       — touchscreen taps (0-1 normalised coords → scaled to
#                          logical surface size inside each scene)
#
# =============================================================================

import os
import sys

# --- ENTRY-POINT DISPATCH -----------------------------------------------------
# `python main.py` with no role = the dual-monitor production launcher.
# recovr.launch_production re-invokes this file with RECOVR_ROLE=therapist for
# the Therapist Interface process; that (and a plain `import main`) skips the
# dispatch and falls through to the scene loop below.
_ROLE = os.environ.get("RECOVR_ROLE", "").strip().lower()

if __name__ == "__main__" and _ROLE != "therapist":
    try:
        from recovr.launch_production import main as _launch_production
    except Exception as _exc:
        sys.stderr.write(
            f"[RecovR] cannot start the dual-monitor launcher: {_exc}\n"
            "Run from the repository root with the 'recovr' package present "
            "and Flask installed (pip install flask).\n")
        raise SystemExit(1)
    raise SystemExit(_launch_production())

# ---------------------------------------------------------------------------
#  THERAPIST INTERFACE
#  (started by recovr.launch_production with RECOVR_ROLE=therapist)
# ---------------------------------------------------------------------------

import pygame

# --- ENVIRONMENT (must be before pygame.init) ---
# recovr/launch_production.py hands this process its monitor two ways:
#   RECOVR_THERAPIST_POS  "x,y"  + RECOVR_THERAPIST_SIZE "WxH"  (absolute)
#   RECOVR_THERAPIST_DISPLAY "n"                                (SDL display index)
# The absolute pair wins because on Linux/X11 both panels usually share ONE
# combined X screen, where a display index cannot separate them but an x/y
# offset can. Windows keeps working either way.
_THERAPIST_DISPLAY = os.environ.get("RECOVR_THERAPIST_DISPLAY", "").strip()
_THERAPIST_POS     = os.environ.get("RECOVR_THERAPIST_POS", "").strip()
_THERAPIST_SIZE    = os.environ.get("RECOVR_THERAPIST_SIZE", "").strip()

if _THERAPIST_POS:
    os.environ['SDL_VIDEO_WINDOW_POS'] = _THERAPIST_POS
elif not _THERAPIST_DISPLAY:
    os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"

# --- Windows DPI fix ---
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# --- START PYGAME ---
pygame.init()

# --- CREATE WINDOW ---
screen = None

# 1. Absolute placement (works on a combined X screen -- Raspberry Pi OS / X11).
if _THERAPIST_POS and _THERAPIST_SIZE:
    try:
        WIDTH, HEIGHT = (int(v) for v in _THERAPIST_SIZE.lower().split("x"))
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME)
        print(f"[recovr] therapist window {WIDTH}x{HEIGHT} at ({_THERAPIST_POS})")
    except Exception as _exc:
        print(f"[recovr] RECOVR_THERAPIST_POS/SIZE ignored ({_exc})")
        screen = None

# 2. SDL display index (Windows, or X11 with truly separate screens).
if screen is None and _THERAPIST_DISPLAY:
    try:
        _idx = int(_THERAPIST_DISPLAY)
        _sizes = pygame.display.get_desktop_sizes()
        if 0 <= _idx < len(_sizes):
            WIDTH, HEIGHT = _sizes[_idx]
            screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME, display=_idx)
    except Exception as _exc:
        print(f"[recovr] RECOVR_THERAPIST_DISPLAY ignored ({_exc}); using default display")
        screen = None

# 3. Fall back to the whole desktop (original behaviour).
if screen is None:
    screen_info = pygame.display.Info()
    WIDTH, HEIGHT = screen_info.current_w, screen_info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME)
pygame.display.set_caption("RecovR")

# --- 7-inch touch scaling (mirrors scenes/login.py / therapist_dashboard.py) ---
# The confirm-exit dialog below was sized purely from H/1080, giving a 19px
# button height on the 800x480 panel. _fs uses a H/512 reference in touch
# mode so it stays finger-sized; _tt() floors every interactive control at a
# fingertip-sized 50px. Desktop (_touch_ui False) is unaffected -- _fs reduces
# to the original H/1080 reference.
_TOUCH_UI = (HEIGHT <= 820) or (os.environ.get("RECOVR_THERAPIST_TOUCH") == "1")
_DLG_FS   = min(HEIGHT / 512.0, 1.32) if _TOUCH_UI else (HEIGHT / 1080.0)

def _dlg_tt(px):
    v = int(px * _DLG_FS)
    return max(v, 50) if _TOUCH_UI else v

def _dlg_sc(px):
    return max(1, int(px * _DLG_FS))

# --- CLOSE BUTTON ---
# Position is normally read from the current scene's own _close_btn_rect
# (the Therapist Dashboard places it beside its Light/Dark toggle); this
# fixed corner rect is only the fallback for scenes that don't define one
# (Welcome, Login, games).
_close_font       = pygame.font.SysFont("segoeuisymbol", int(26 * HEIGHT / 1080))
_DEFAULT_CLOSE_RECT = pygame.Rect(WIDTH - 56, 0, 56, 46)
_close_rect       = _DEFAULT_CLOSE_RECT
_close_hover      = False


def _draw_close_icon(rect):
    """The close_button.png asset, scaled to fit `rect` without distortion
    (it's a circular icon), falling back to the original vector box+X if
    the asset is missing."""
    size = min(rect.width, rect.height)
    img = _dash_img("close_button.png", size)
    if img is not None:
        screen.blit(img, img.get_rect(center=rect.center))
        if _close_hover:
            pygame.draw.circle(screen, (255, 255, 255), rect.center,
                               size // 2, max(1, int(2 * _DLG_FS)))
    else:
        _bg = (190, 35, 35) if _close_hover else (110, 25, 25)
        pygame.draw.rect(screen, _bg, rect)
        _xs = _close_font.render("✕", True, (255, 255, 255))
        screen.blit(_xs, _xs.get_rect(center=rect.center))

# --- CONFIRM-EXIT DIALOG ---
# Styled through the same shared, theme-aware draw_confirm_dialog every
# other confirmation popup in the therapist interface uses (see
# scenes/therapist_dashboard.py) -- this is the one confirmation dialog
# that lives outside a TherapistDashboardScene instance (it guards the
# window's own close button, which exists across every scene), so it
# passes its own fs/tt/sc/fonts instead of a scene's bound methods.
_confirm_open = False                          # True while dialog is visible
_dlg_font_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "font")

def _dlg_font(name, size):
    try:
        return pygame.font.Font(os.path.join(_dlg_font_dir, name), size)
    except Exception:
        return pygame.font.SysFont("segoeui", size)

_dlg_fonts = {
    "title":       _dlg_font("Poppins-SemiBold.ttf", int(26 * _DLG_FS)),
    "title_small": _dlg_font("Poppins-SemiBold.ttf", int(20 * _DLG_FS)),
    "body":        _dlg_font("Poppins-Regular.ttf",  int(19 * _DLG_FS)),
    "btn":         _dlg_font("Poppins-SemiBold.ttf", int(20 * _DLG_FS)),
}

_yes_rect = pygame.Rect(0, 0, 1, 1)
_no_rect  = pygame.Rect(0, 0, 1, 1)
_yes_hov  = False
_no_hov   = False

# --- COORDINATE NORMALISER ---
_surf_w, _surf_h = screen.get_size()
_scale_x = WIDTH  / _surf_w
_scale_y = HEIGHT / _surf_h

def normalise_pos(raw_pos):
    return (int(raw_pos[0] * _scale_x), int(raw_pos[1] * _scale_y))

import builtins
builtins.normalise_pos  = normalise_pos
builtins.LOGICAL_WIDTH  = WIDTH
builtins.LOGICAL_HEIGHT = HEIGHT

# --- IMPORT SCENES ---
from scenes.therapist_welcome   import TherapistWelcomeScene
from scenes.patient_welcome     import PatientWelcomeScene
from scenes.login               import LoginScene
from scenes.register            import RegisterScene
from scenes.therapist_dashboard import TherapistDashboardScene, _img as _dash_img, draw_confirm_dialog
from scenes.patient_dashboard   import PatientDashboardScene
from scenes.game_scene          import make_game_scene

# --- IMPORT GAMES ---
from games.steady_aim     import SteadyAimGame
from games.basketball     import BasketballGame
from games.piano_tiles    import PianoTilesGame
from games.catchingapple  import AppleCatchingGame
from games.catch_object   import CatchObjectGame
from games.key_lock       import KeyLockGame
from games.lemonade       import LemonadeGame
from games.feed_the_cat   import FeedTheCatGame
from games.plant_the_garden import PlantTheGardenGame

SCENES = {
    "therapist_welcome"  : TherapistWelcomeScene,
    "patient_welcome"    : PatientWelcomeScene,
    "login"              : LoginScene,
    "register"           : RegisterScene,
    "therapist_dashboard": TherapistDashboardScene,
    "patient_dashboard"  : PatientDashboardScene,
    "steady_aim"         : make_game_scene(SteadyAimGame),
    "basketball"         : make_game_scene(BasketballGame),
    "piano_tiles"        : make_game_scene(PianoTilesGame),
    "catchingapple"      : make_game_scene(AppleCatchingGame),
    "catch_object"       : make_game_scene(CatchObjectGame),
    "key_lock"           : make_game_scene(KeyLockGame),
    "lemonade"           : make_game_scene(LemonadeGame),
    "feed_the_cat"       : make_game_scene(FeedTheCatGame),
    "plant_the_garden"   : make_game_scene(PlantTheGardenGame),
}

# --- CROSSFADE ---
def crossfade(screen, outgoing_scene, incoming_scene, clock, steps=25):
    old_frame = pygame.Surface((WIDTH, HEIGHT))
    outgoing_scene.draw(old_frame)
    new_frame = pygame.Surface((WIDTH, HEIGHT))
    incoming_scene.draw(new_frame)
    for i in range(steps + 1):
        alpha = int((i / steps) * 255)
        screen.blit(old_frame, (0, 0))
        new_frame.set_alpha(alpha)
        screen.blit(new_frame, (0, 0))
        pygame.display.flip()
        clock.tick(60)
    new_frame.set_alpha(255)

# --- DRAW CONFIRM DIALOG ---
def _draw_confirm_dialog():
    global _yes_rect, _no_rect
    _yes_rect, _no_rect = draw_confirm_dialog(
        screen, WIDTH, HEIGHT, tt=_dlg_tt, sc=_dlg_sc, fonts=_dlg_fonts,
        icon="close", accent=(205, 45, 45),
        title="Close RecovR?", body="All unsaved changes will be lost.",
        confirm_label="Yes, Close", cancel_label="Cancel",
        confirm_hov=_yes_hov, cancel_hov=_no_hov)

# --- STARTING SCENE ---
_current_scene_name = "therapist_welcome"
_game_scene_names   = {"basketball", "steady_aim", "piano_tiles",
                        "catchingapple", "catch_object", "key_lock",
                        "feed_the_cat", "plant_the_garden"}
current_scene = TherapistWelcomeScene(screen, WIDTH, HEIGHT)

# --- MAIN LOOP ---
clock = pygame.time.Clock()

while True:
    dt = clock.tick(60)

    mouse_pos = normalise_pos(pygame.mouse.get_pos())

    # Update hover states for confirm dialog
    _yes_hov = _yes_rect.collidepoint(mouse_pos)
    _no_hov  = _no_rect.collidepoint(mouse_pos)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit(); sys.exit()

        # --- Handle confirm dialog (blocks all input below when open) ---
        if _confirm_open:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                _confirm_open = False

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = normalise_pos(event.pos)
                if _yes_rect.collidepoint(pos):
                    pygame.quit(); sys.exit()
                if _no_rect.collidepoint(pos):
                    _confirm_open = False

            if event.type == pygame.FINGERDOWN:
                fp = (int(event.x * WIDTH), int(event.y * HEIGHT))
                if _yes_rect.collidepoint(fp):
                    pygame.quit(); sys.exit()
                if _no_rect.collidepoint(fp):
                    _confirm_open = False

            continue   # don't pass events to the scene while dialog is open

        # --- Close button (opens the confirm dialog) ---
        # Also blocked for the whole lifetime of a Patient Sharing/Transferring
        # popup (search -> SHARE|TRANSFER choice -> confirm, including the
        # mandatory transfer countdown -- all covered by _share_modal_open)
        # and its Transfer Success acknowledgment (a separate self.modal
        # state that fires once _share_modal_open has already gone False --
        # see TherapistDashboardScene._do_share_or_transfer_confirm). Those
        # modals already swallow every click/touch themselves while open
        # (TherapistDashboardScene.handle_event checks them first), so this
        # only needed to stop the APPLICATION's own Close button, which lives
        # outside the scene entirely.
        _share_blocking = (
            bool(getattr(current_scene, "_share_modal_open", False)) or
            getattr(current_scene, "modal", None) == "transfer_success" or
            bool(getattr(current_scene, "_gc_skill_modal_open", False))
        )
        _btn_active = (
            _current_scene_name not in _game_scene_names and
            getattr(current_scene, "_cal_win", None) is None and
            not _share_blocking
        )
        if _btn_active:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if _close_rect.collidepoint(normalise_pos(event.pos)):
                    _confirm_open = True
                    continue
            if event.type == pygame.FINGERDOWN:
                _fp = (int(event.x * WIDTH), int(event.y * HEIGHT))
                if _close_rect.collidepoint(_fp):
                    _confirm_open = True
                    continue

        # --- Pass event to the current scene ---
        next_scene_name = current_scene.handle_event(event)

        if next_scene_name and next_scene_name in SCENES:
            incoming_scene = SCENES[next_scene_name](screen, WIDTH, HEIGHT)
            _fade_steps = 70 if next_scene_name in _game_scene_names else 25
            crossfade(screen, current_scene, incoming_scene, clock, steps=_fade_steps)
            current_scene       = incoming_scene
            _current_scene_name = next_scene_name

    if not _confirm_open:
        current_scene.update(mouse_pos, dt)

    # Handle transitions triggered by update()
    pending = getattr(current_scene, "_pending_scene", None)
    if pending and pending in SCENES:
        current_scene._pending_scene = None
        incoming_scene = SCENES[pending](screen, WIDTH, HEIGHT)
        crossfade(screen, current_scene, incoming_scene, clock)
        current_scene       = incoming_scene
        _current_scene_name = pending

    current_scene.draw(screen)

    # Position for THIS frame's visuals + next frame's hit-testing: read the
    # scene's own close-button slot (currently only the Therapist Dashboard
    # publishes one, beside its Light/Dark toggle) if it published one this
    # draw, else fall back to the fixed corner rect and the original look
    # (Welcome/Login/Register/games: reverted back to the plain red box + X
    # for now, at the original fixed position -- only the Therapist
    # Dashboard uses the close_button.png asset and the repositioned slot).
    _scene_close_rect = getattr(current_scene, "_close_btn_rect", None)
    if _scene_close_rect is not None and _scene_close_rect.width > 1:
        _close_rect      = _scene_close_rect
        _use_close_asset = True
    else:
        _close_rect      = _DEFAULT_CLOSE_RECT
        _use_close_asset = False

    # Draw close button — hidden during games, calibration, and a Patient
    # Sharing/Transferring popup (see _share_blocking above; recomputed here
    # since this runs after the scene's own draw() may have changed state).
    _in_game        = _current_scene_name in _game_scene_names
    _in_calibration = getattr(current_scene, "_cal_win", None) is not None
    _in_share_modal = (
        bool(getattr(current_scene, "_share_modal_open", False)) or
        getattr(current_scene, "modal", None) == "transfer_success" or
        bool(getattr(current_scene, "_gc_skill_modal_open", False))
    )
    if not _in_game and not _in_calibration and not _in_share_modal:
        _close_hover = _close_rect.collidepoint(mouse_pos)
        if _use_close_asset:
            _draw_close_icon(_close_rect)
        else:
            _bg = (190, 35, 35) if _close_hover else (110, 25, 25)
            pygame.draw.rect(screen, _bg, _close_rect)
            _xs = _close_font.render("✕", True, (255, 255, 255))
            screen.blit(_xs, _xs.get_rect(center=_close_rect.center))

    # Draw confirm dialog on top of everything
    if _confirm_open:
        _draw_confirm_dialog()

    pygame.display.flip()
