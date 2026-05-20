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
# NOTE: SDL_MOUSE_TOUCH_EVENTS intentionally NOT set.
#       Touchscreen is handled via FINGERDOWN with normalised 0-1 coords.

# --- Windows DPI fix ---
# Tells Windows this process handles its own DPI scaling so that
# event.pos coords are in logical pixels, not physical pixels.
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

# --- COORDINATE NORMALISER ---
# Compares the actual surface pixel size to the logical (WIDTH, HEIGHT).
# If DPI scaling still caused a mismatch, this corrects every event.pos.
# Injected into builtins so any scene can call normalise_pos() without
# importing main.py (which would create a circular dependency).
_surf_w, _surf_h = screen.get_size()
_scale_x = WIDTH  / _surf_w
_scale_y = HEIGHT / _surf_h

def normalise_pos(raw_pos):
    """Convert event.pos (may be physical px) → logical surface px."""
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
    # Games
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

# --- STARTING SCENE ---
current_scene = TherapistWelcomeScene(screen, WIDTH, HEIGHT)

# --- MAIN LOOP ---
clock = pygame.time.Clock()

while True:
    dt = clock.tick(60)

    # Normalise mouse position for update() (hover detection)
    mouse_pos = normalise_pos(pygame.mouse.get_pos())

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit(); sys.exit()

        next_scene_name = current_scene.handle_event(event)

        if next_scene_name and next_scene_name in SCENES:
            incoming_scene = SCENES[next_scene_name](screen, WIDTH, HEIGHT)
            _game_scenes = {"basketball", "steady_aim", "piano_tiles"}
            _fade_steps  = 70 if next_scene_name in _game_scenes else 25
            crossfade(screen, current_scene, incoming_scene, clock, steps=_fade_steps)
            current_scene = incoming_scene

    current_scene.update(mouse_pos, dt)

    # Handle transitions triggered by update() (e.g. game-over)
    pending = getattr(current_scene, "_pending_scene", None)
    if pending and pending in SCENES:
        current_scene._pending_scene = None
        incoming_scene = SCENES[pending](screen, WIDTH, HEIGHT)
        crossfade(screen, current_scene, incoming_scene, clock)
        current_scene = incoming_scene

    current_scene.draw(screen)
    pygame.display.flip() 