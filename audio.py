import os
import pygame

_DIR   = os.path.dirname(os.path.abspath(__file__))
_MUSIC = os.path.join(_DIR, "assets", "audio",
    "denis-pavlov-music-futuristic-technology-science-sci-fi-high-tech-game-music-368220.mp3")
_SFX_SUCCESS    = os.path.join(_DIR, "assets", "audio", "catch_sound_effect.wav")
_SFX_ERROR      = os.path.join(_DIR, "assets", "audio", "blast_sound.wav")
_SFX_COMPLETE   = os.path.join(_DIR, "assets", "audio",
                                "mixkit-completion-of-a-level-2063.wav")
_SFX_CONFIRM    = os.path.join(_DIR, "assets", "audio",
                                "mixkit-quick-win-video-game-notification-269.wav")
_SFX_START_SES  = os.path.join(_DIR, "assets", "audio",
                                "mixkit-sci-fi-interface-robot-click-901.wav")
_SFX_WELCOME = os.path.join(_DIR, "assets", "audio",
                             "mixkit-game-user-interface-tone-2570.wav")
_SFX_CLICK      = os.path.join(_DIR, "assets", "audio",
                                "mixkit-modern-technology-select-3124.wav")
_AUDIO_DIR = os.path.join(_DIR, "assets", "audio")

def game_music_path(game: str, difficulty: str) -> str:
    """Return the path for a game+difficulty track, falling back to default."""
    filename = f"{game} {difficulty}.mp3"
    path = os.path.join(_AUDIO_DIR, filename)
    return path if os.path.exists(path) else _MUSIC

_sounds: dict = {}


def _get_sound(path):
    if path not in _sounds:
        try:
            _sounds[path] = pygame.mixer.Sound(path)
        except Exception:
            _sounds[path] = None
    return _sounds[path]


def start_music(path=None):
    """Play looping background music. Pass a file path to use a specific track."""
    track = path if path else _MUSIC
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.stop()
        pygame.mixer.music.load(track)
        pygame.mixer.music.set_volume(0.4)
        pygame.mixer.music.play(-1)
    except Exception:
        pass


def stop_music():
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass


def play_success():
    snd = _get_sound(_SFX_SUCCESS)
    if snd:
        try:
            snd.play()
        except Exception:
            pass


def play_completion():
    snd = _get_sound(_SFX_COMPLETE)
    if snd:
        try:
            snd.play()
        except Exception:
            pass


def _play(path):
    """Internal helper — initialise mixer if needed, then play a one-shot sfx."""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception:
        return
    snd = _get_sound(path)
    if snd:
        try:
            snd.play()
        except Exception:
            pass


def play_confirm_alert():
    """Confirmation / delete prompt appears."""
    _play(_SFX_CONFIRM)


def play_start_session():
    """Start Session button clicked."""
    _play(_SFX_START_SES)


def play_welcome():
    """Welcome / splash screen shown."""
    _play(_SFX_WELCOME)


def play_click():
    """Generic UI button click."""
    _play(_SFX_CLICK)


def play_error():
    snd = _get_sound(_SFX_ERROR)
    if snd:
        try:
            snd.play()
        except Exception:
            pass
