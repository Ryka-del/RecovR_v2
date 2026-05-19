import os
import pygame

_DIR   = os.path.dirname(os.path.abspath(__file__))
_MUSIC = os.path.join(_DIR, "assets", "audio",
    "denis-pavlov-music-futuristic-technology-science-sci-fi-high-tech-game-music-368220.mp3")
_SFX_SUCCESS = os.path.join(_DIR, "assets", "audio", "catch_sound_effect.wav")
_SFX_ERROR   = os.path.join(_DIR, "assets", "audio", "blast_sound.wav")

_sounds: dict = {}


def _get_sound(path):
    if path not in _sounds:
        try:
            _sounds[path] = pygame.mixer.Sound(path)
        except Exception:
            _sounds[path] = None
    return _sounds[path]


def start_music():
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        if not pygame.mixer.music.get_busy():
            pygame.mixer.music.load(_MUSIC)
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
