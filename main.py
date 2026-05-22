# =============================================================================
# main.py
# =============================================================================
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

import pygame
import sys
import os

# --- ENVIRONMENT (must be before pygame.init) ---
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
screen_info = pygame.display.Info()
WIDTH, HEIGHT = screen_info.current_w, screen_info.current_h
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME)
pygame.display.set_caption("RecovR")

# --- CLOSE BUTTON ---
_close_font  = pygame.font.SysFont("segoeuisymbol", int(26 * HEIGHT / 1080))
_close_rect  = pygame.Rect(WIDTH - 56, 0, 56, 46)
_close_hover = False

# --- CONFIRM-EXIT DIALOG ---
_confirm_open    = False                          # True while dialog is visible
_dlg_font_title  = pygame.font.SysFont("segoeui", int(28 * HEIGHT / 1080))
_dlg_font_body   = pygame.font.SysFont("segoeui", int(20 * HEIGHT / 1080))
_dlg_font_btn    = pygame.font.SysFont("segoeui", int(20 * HEIGHT / 1080))

_dlg_w  = int(420 * WIDTH  / 1920)
_dlg_h  = int(200 * HEIGHT / 1080)
_dlg_x  = (WIDTH  - _dlg_w) // 2
_dlg_y  = (HEIGHT - _dlg_h) // 2
_dlg_r  = pygame.Rect(_dlg_x, _dlg_y, _dlg_w, _dlg_h)

_btn_w  = int(140 * WIDTH  / 1920)
_btn_h  = int(44  * HEIGHT / 1080)
_btn_gap = int(20 * WIDTH  / 1920)
_yes_rect = pygame.Rect(
    _dlg_r.centerx - _btn_w - _btn_gap // 2,
    _dlg_r.bottom  - _btn_h - int(24 * HEIGHT / 1080),
    _btn_w, _btn_h,
)
_no_rect = pygame.Rect(
    _dlg_r.centerx + _btn_gap // 2,
    _yes_rect.y,
    _btn_w, _btn_h,
)

_yes_hov = False
_no_hov  = False

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
from scenes.therapist_dashboard import TherapistDashboardScene
from scenes.patient_dashboard   import PatientDashboardScene
from scenes.game_scene          import make_game_scene

# --- IMPORT GAMES ---
from games.steady_aim   import SteadyAimGame
from games.basketball   import BasketballGame
from games.piano_tiles  import PianoTilesGame

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
    # Dim overlay
    dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    dim.fill((10, 14, 22, 180))
    screen.blit(dim, (0, 0))

    # Card background
    pygame.draw.rect(screen, (245, 247, 252), _dlg_r, border_radius=16)
    pygame.draw.rect(screen, (200, 210, 230), _dlg_r, 2, border_radius=16)

    # Title
    title_s = _dlg_font_title.render("Close RecovRWE?", True, (30, 45, 70))
    screen.blit(title_s, title_s.get_rect(center=(_dlg_r.centerx,
                                                   _dlg_r.y + int(52 * HEIGHT / 1080))))

    # Body
    body_s = _dlg_font_body.render("All unsaved changes will be lost.", True, (100, 115, 140))
    screen.blit(body_s, body_s.get_rect(center=(_dlg_r.centerx,
                                                  _dlg_r.y + int(100 * HEIGHT / 1080))))

    # Yes button (red)
    yes_col = (200, 40, 40) if _yes_hov else (160, 30, 30)
    pygame.draw.rect(screen, yes_col, _yes_rect, border_radius=10)
    yes_s = _dlg_font_btn.render("Yes, Close", True, (255, 255, 255))
    screen.blit(yes_s, yes_s.get_rect(center=_yes_rect.center))

    # No button (neutral)
    no_col = (90, 110, 140) if _no_hov else (70, 88, 115)
    pygame.draw.rect(screen, no_col, _no_rect, border_radius=10)
    no_s = _dlg_font_btn.render("Cancel", True, (255, 255, 255))
    screen.blit(no_s, no_s.get_rect(center=_no_rect.center))

# --- STARTING SCENE ---
_current_scene_name = "therapist_welcome"
_game_scene_names   = {"basketball", "steady_aim", "piano_tiles"}
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
        _btn_active = (
            _current_scene_name not in _game_scene_names and
            getattr(current_scene, "_cal_win", None) is None
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

    # Draw close button — hidden during games and calibration
    _in_game        = _current_scene_name in _game_scene_names
    _in_calibration = getattr(current_scene, "_cal_win", None) is not None
    if not _in_game and not _in_calibration:
        _close_hover = _close_rect.collidepoint(mouse_pos)
        _bg = (190, 35, 35) if _close_hover else (110, 25, 25)
        pygame.draw.rect(screen, _bg, _close_rect)
        _xs = _close_font.render("✕", True, (255, 255, 255))
        screen.blit(_xs, _xs.get_rect(center=_close_rect.center))

    # Draw confirm dialog on top of everything
    if _confirm_open:
        _draw_confirm_dialog()

    pygame.display.flip()
