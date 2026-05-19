import os
import pygame

_DIR   = os.path.dirname(os.path.abspath(__file__))
_MUSIC = os.path.join(_DIR, "assets", "audio",
    "denis-pavlov-music-futuristic-technology-science-sci-fi-high-tech-game-music-368220.mp3")
_SFX_SUCCESS = os.path.join(_DIR, "assets", "audio", "catch_sound_effect.wav")
_SFX_ERROR   = os.path.join(_DIR, "assets", "audio", "blast_sound.wav")

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


def play_error():
    snd = _get_sound(_SFX_ERROR)
    if snd:
        try:
            snd.play()
        except Exception:
            pass
