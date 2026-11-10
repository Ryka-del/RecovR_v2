"""
Pre-gameplay countdown -- "Get Ready!" + 3 / 2 / 1 + a brief "START!" --
drawn by GameRunner (see game_runner.py's `counting_down` state) between the
game's own frozen How-to-Play frame and the moment gameplay actually begins.

Purely presentational: GameRunner is the one that keeps the wrapped game's
update() (timer / score / sensor processing) from running until this
screen's time is up (see GameRunner.update()'s `counting_down` branch), so
this module never needs to know anything about timing correctness -- it only
turns an elapsed-seconds float into a frame.
"""

import pygame

from ui_cards import font as _font

STEP_SEC  = 1.0     # each of "3", "2", "1"
FLASH_SEC = 0.55    # brief "START!" transition
TOTAL_SEC = STEP_SEC * 3 + FLASH_SEC

_READY_COLOR  = (255, 255, 255)
_NUMBER_COLOR = (90, 175, 240)     # blue
_START_COLOR  = (55, 201, 122)     # green -- "go"
_POP_IN_SEC   = 0.16
_POP_OUT_SEC  = 0.16


class CountdownScreen:

    def draw(self, surface: pygame.Surface, elapsed: float):
        W, H = surface.get_size()

        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((6, 10, 18, 170))
        surface.blit(ov, (0, 0))

        if elapsed < STEP_SEC * 3:
            step_i = min(2, int(elapsed // STEP_SEC))   # 0, 1, 2
            local = elapsed - step_i * STEP_SEC
            number = str(3 - step_i)
            self._draw_ready(surface, W, H)
            self._draw_pop_text(surface, W, H, number, local, STEP_SEC,
                                int(H * 0.30), _NUMBER_COLOR, "Poppins-ExtraBold.ttf")
        else:
            local = elapsed - STEP_SEC * 3
            self._draw_pop_text(surface, W, H, "START!", local, FLASH_SEC,
                                int(H * 0.13), _START_COLOR, "Poppins-ExtraBold.ttf")

    def _draw_ready(self, surface, W, H):
        f = _font("Poppins-SemiBold.ttf", H * 0.065)
        s = f.render("Get Ready!", True, _READY_COLOR)
        surface.blit(s, s.get_rect(center=(W // 2, int(H * 0.30))))

    def _draw_pop_text(self, surface, W, H, text, local, hold_sec, size_px, color, font_name):
        """A single word/number that scales+fades in, holds, then
        scales+fades out -- smooth, no flashing, same curve every step so
        the rhythm stays consistent across 3 / 2 / 1 / START!."""
        if local < _POP_IN_SEC:
            p = max(0.0, local / _POP_IN_SEC)
            scale, alpha = 0.72 + 0.28 * p, p
        elif local > hold_sec - _POP_OUT_SEC:
            p = max(0.0, (hold_sec - local) / _POP_OUT_SEC)
            scale, alpha = 1.0, p
        else:
            scale, alpha = 1.0, 1.0

        f = _font(font_name, size_px)
        s = f.render(text, True, color)
        if scale != 1.0:
            w = max(1, int(s.get_width() * scale))
            h = max(1, int(s.get_height() * scale))
            s = pygame.transform.smoothscale(s, (w, h))
        s.set_alpha(max(0, min(255, int(alpha * 255))))
        cy = int(H * 0.58) if text != "START!" else int(H * 0.5)
        surface.blit(s, s.get_rect(center=(W // 2, cy)))
