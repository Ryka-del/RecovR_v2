"""
GameScene — adapts any BaseScreen game to the scene interface used by main.py.

Usage in main.py:
    from scenes.game_scene import make_game_scene
    from games.space_hoops import SpaceHoopsGame

    SCENES["space_hoops"] = make_game_scene(SpaceHoopsGame)

Before switching to a game scene, store session data in builtins:
    builtins.pending_game_data = { "account_id": ..., "difficulty": ..., ... }
"""

import pygame
import builtins
from constants import GAME_W, GAME_H


class GameScene:

    def __init__(self, screen, width, height, game_class, game_data):
        self.screen  = screen
        self.WIDTH   = width
        self.HEIGHT  = height

        # Render target: games are designed for GAME_W × GAME_H
        self.game_surface = pygame.Surface((GAME_W, GAME_H))

        self.game = game_class()
        self.game.on_enter(game_data)

        # Pending scene transition set by update() when the game ends
        self._pending_scene = None

    # ------------------------------------------------------------------ #
    #  Scene interface                                                     #
    # ------------------------------------------------------------------ #

    def handle_event(self, event):
        # If update() already flagged a transition, honour it
        if self._pending_scene:
            s = self._pending_scene
            self._pending_scene = None
            return s

        self.game.handle_event(event)

        next_s, _ = self.game.manager.get_next()
        if next_s:
            return "therapist_dashboard"
        return None

    def update(self, mouse_pos, dt):
        from sensors.input_handler import input_handler
        input_handler.update(dt / 1000.0)   # advance grip ramp before game logic
        self.game.update(dt / 1000.0)

        next_s, _ = self.game.manager.get_next()
        if next_s and not self._pending_scene:
            self._pending_scene = "therapist_dashboard"

    def draw(self, surface):
        self.game_surface.fill((0, 0, 0))   # clear each frame before the game draws
        self.game.draw(self.game_surface)
        # Scale game surface to actual screen size if needed
        if (self.WIDTH, self.HEIGHT) == (GAME_W, GAME_H):
            surface.blit(self.game_surface, (0, 0))
        else:
            scaled = pygame.transform.scale(self.game_surface, (self.WIDTH, self.HEIGHT))
            surface.blit(scaled, (0, 0))


def make_game_scene(game_class):
    """Factory that captures game_class and reads pending_game_data from builtins."""
    def factory(screen, width, height):
        data = getattr(builtins, "pending_game_data", {})
        builtins.pending_game_data = {}
        from constants import set_dark_mode
        set_dark_mode(data.get("dark_mode", True))
        return GameScene(screen, width, height, game_class, data)
    return factory
