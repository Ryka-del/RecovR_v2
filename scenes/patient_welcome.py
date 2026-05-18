# =============================================================================
# scenes/patient_welcome.py
# =============================================================================

import pygame


class PatientWelcomeScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        # --- FONTS ---
        title_size    = int(240 * (height / 1080))
        subtitle_size = int(45  * (height / 1080))

        self.font_title    = pygame.font.SysFont("arialblack", title_size)
        self.font_subtitle = pygame.font.SysFont("georgia", subtitle_size, bold=False, italic=False)
        self.row_spacing   = int(50 * (height / 1080))

        # --- BACKGROUND ---
        self.background_surface = self._create_gradient(width, height)

        # --- FADE-IN ---
        self.alpha        = 0
        self.fade_surface = pygame.Surface((width, height))
        self.fade_surface.fill((255, 255, 255))

    # ------------------------------------------------------------------
    # SCENE INTERFACE
    # ------------------------------------------------------------------

    def handle_event(self, event):
        # No buttons yet — returns None so we stay on this screen.
        # When you add a Start button later, return "patient_dashboard" here.
        return None

    def update(self, mouse_pos, dt):
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    def draw(self, surface):
        # 1. Background
        surface.blit(self.background_surface, (0, 0))

        # 2. Title + subtitle
        self._render_centered_ui(surface)

        # 3. Fade-in overlay
        if self.alpha < 255:
            self.fade_surface.set_alpha(255 - self.alpha)
            surface.blit(self.fade_surface, (0, 0))

    # ------------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------------

    def _render_centered_ui(self, surface):
        part1    = "Recov"
        part2    = "R"
        sub_text = "Ready to start your therapy journey?"

        COLOR_WHITE   = (255, 255, 255)
        COLOR_RED     = (220, 40,  40)
        COLOR_OUTLINE = (0,   0,   0)
        COLOR_SUB     = (70,  80,  95)

        tw1, h1   = self.font_title.size(part1)
        tw2, _    = self.font_title.size(part2)
        tsub_w, sub_h = self.font_subtitle.size(sub_text)

        recovr_width = tw1 + tw2
        total_h      = h1 + self.row_spacing + sub_h
        top_y        = (self.HEIGHT // 2) - (total_h // 2)

        start_x = (self.WIDTH // 2) - (recovr_width // 2)
        part2_x = start_x + tw1

        def draw_outlined(font, text, x, y, color):
            for dx in [-5, 0, 5]:
                for dy in [-5, 0, 5]:
                    if dx or dy:
                        surface.blit(font.render(text, True, COLOR_OUTLINE), (x+dx, y+dy))
            surface.blit(font.render(text, True, color), (x, y))

        draw_outlined(self.font_title, part1, start_x, top_y, COLOR_WHITE)
        draw_outlined(self.font_title, part2, part2_x, top_y, COLOR_RED)

        sub_y = top_y + h1 + self.row_spacing
        sub_x = (self.WIDTH // 2) - (tsub_w // 2)
        surface.blit(self.font_subtitle.render(sub_text, True, COLOR_SUB), (sub_x, sub_y))

    def _create_gradient(self, width, height):
        scale  = 4
        surf_w = width  // scale
        surf_h = height // scale

        surface       = pygame.Surface((surf_w, surf_h), depth=32).convert()
        white         = (255, 255, 255)
        pastel_blue   = (185, 215, 255)
        pastel_purple = (225, 185, 255)
        w_factor      = surf_w * 0.75

        for y in range(surf_h):
            for x in range(surf_w):
                wb = max(0, 1.0 - (x + y) / w_factor)
                wp = max(0, 1.0 - ((surf_w - x) + (surf_h - y)) / w_factor)
                tc = wb + wp
                if tc > 1.0:
                    wb /= tc; wp /= tc; ww = 0.0
                else:
                    ww = 1.0 - tc

                r = min(255, max(0, int(pastel_blue[0]*wb + pastel_purple[0]*wp + white[0]*ww)))
                g = min(255, max(0, int(pastel_blue[1]*wb + pastel_purple[1]*wp + white[1]*ww)))
                b = min(255, max(0, int(pastel_blue[2]*wb + pastel_purple[2]*wp + white[2]*ww)))
                surface.set_at((x, y), surface.map_rgb((r, g, b)))

        return pygame.transform.smoothscale(surface, (width, height))