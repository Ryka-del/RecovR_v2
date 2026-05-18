"""
Shared constants for all games.
"""

GAME_W = 1920
GAME_H = 1080

# Colour palette
WHITE   = (255, 255, 255)
BLACK   = (0,   0,   0)
GRAY    = (120, 130, 150)
PANEL   = (30,  35,  50)
ACCENT  = (80,  160, 230)
ACCENT2 = (50,  120, 190)
TEXT    = (220, 230, 245)
GREEN   = (50,  200, 80)
YELLOW  = (255, 220, 60)
ORANGE  = (255, 140, 30)
RED     = (220, 60,  60)
BLUE    = (60,  120, 220)


def get_theme():
    return {
        "BG":      (12,  14,  22),
        "PANEL":   PANEL,
        "ACCENT":  ACCENT,
        "ACCENT2": ACCENT2,
        "TEXT":    TEXT,
        "GRAY":    GRAY,
        "GREEN":   GREEN,
        "YELLOW":  YELLOW,
        "ORANGE":  ORANGE,
        "RED":     RED,
        "WHITE":   WHITE,
        "BLACK":   BLACK,
    }
