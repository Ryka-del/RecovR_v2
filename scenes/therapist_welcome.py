# =============================================================================
# scenes/therapist_welcome.py
# =============================================================================

import pygame
import os


class TherapistWelcomeScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        # --- FONTS ---
        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(n): return os.path.join(_fd, n)
        title_size       = int(240 * (height / 1080))
        subtitle_size    = int(43  * (height / 1080))
        button_font_size = int(34  * (height / 1080))

        self.font_title    = pygame.font.SysFont("arialblack", title_size)
        self.font_subtitle = pygame.font.Font(_F("Sora-Light.ttf"),          subtitle_size)
        self.font_button   = pygame.font.Font(_F("Lexend-SemiBold.ttf"),     button_font_size)

        # --- SPACING ---
        self.row_spacing = int(45 * (height / 1080))

        # --- BACKGROUND ---
        self.background_surface = self._create_gradient(width, height)

        # --- LAYOUT ---
        # Measure each element's height so we can stack them and center the whole group.
        _, self.h1  = self.font_title.size("Recov")       # title height
        _, sub_h    = self.font_subtitle.size("x")         # subtitle height
        btn_h       = int(80 * (height / 1080))            # button height
        gap_sub_btn = int(60 * (height / 1080))            # gap between subtitle and button

        # Total height of the whole block: title + gap + subtitle + gap + button
        total_h = self.h1 + self.row_spacing + sub_h + gap_sub_btn + btn_h

        # Anchor point: vertically center the entire block
        self.start_layout_y = (height // 2) - (total_h // 2)

        # Button sits directly below the title + subtitle block
        button_y = self.start_layout_y + self.h1 + self.row_spacing + sub_h + gap_sub_btn

        # --- BUTTON ---
        self.start_button = self._DeepStartButton(
            width // 2, button_y, width, height, self.font_button
        )

        # --- FADE-IN ---
        self.alpha        = 0
        self.fade_surface = pygame.Surface((width, height))
        self.fade_surface.fill((255, 255, 255))

        # --- LAUNCH GUARD ---
        self.launch_triggered = False

    # ------------------------------------------------------------------
    # SCENE INTERFACE
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if not self.launch_triggered:
            if self.start_button.handle_click(event):
                self.launch_triggered = True
                return "login"
        return None

    def update(self, mouse_pos, dt):
        self.start_button.update(mouse_pos)
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    def draw(self, surface):
        # 1. Background
        surface.blit(self.background_surface, (0, 0))

        # 2. Title + subtitle
        self._render_centered_ui(surface)

        # 3. Button
        self.start_button.draw(surface)

        # 4. Fade-in overlay
        if self.alpha < 255:
            self.fade_surface.set_alpha(255 - self.alpha)
            surface.blit(self.fade_surface, (0, 0))

    # ------------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------------

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

    def _render_centered_ui(self, surface):
        part1    = "Recov"
        part2    = "R"
        sub_text = "Gamified Hand Rehabilitation System"

        COLOR_WHITE   = (255, 255, 255)
        COLOR_RED     = (220, 40,  40)
        COLOR_OUTLINE = (0,   0,   0)
        COLOR_SUB     = (70,  80,  95)

        tw1, h1   = self.font_title.size(part1)
        tw2, _    = self.font_title.size(part2)
        tsub_w, _ = self.font_subtitle.size(sub_text)

        start_x = (self.WIDTH // 2) - ((tw1 + tw2) // 2)
        part2_x = start_x + tw1

        def draw_outlined(font, text, x, y, color):
            for dx in [-5, 0, 5]:
                for dy in [-5, 0, 5]:
                    if dx or dy:
                        surface.blit(font.render(text, True, COLOR_OUTLINE), (x+dx, y+dy))
            surface.blit(font.render(text, True, color), (x, y))

        draw_outlined(self.font_title, part1, start_x, self.start_layout_y, COLOR_WHITE)
        draw_outlined(self.font_title, part2, part2_x, self.start_layout_y, COLOR_RED)

        sub_y = self.start_layout_y + h1 + self.row_spacing
        sub_x = (self.WIDTH // 2) - (tsub_w // 2)
        surface.blit(self.font_subtitle.render(sub_text, True, COLOR_SUB), (sub_x, sub_y))

    # ------------------------------------------------------------------
    # INNER CLASS: 3D Start Button
    # ------------------------------------------------------------------

    class _DeepStartButton:

        def __init__(self, center_x, top_y, WIDTH, HEIGHT, font_button):
            self.width        = int(280 * (WIDTH  / 1920))
            self.height       = int(80  * (HEIGHT / 1080))
            self.shadow_depth = int(8   * (HEIGHT / 1080))

            self.rect     = pygame.Rect(
                center_x - (self.width // 2), top_y, self.width, self.height
            )
            self.hit_rect = self.rect.inflate(30, 30)

            self.color_normal        = (40,  160, 220)
            self.color_normal_shadow = (25,  110, 160)
            self.color_hover         = (30,  140, 195)
            self.color_hover_shadow  = (15,  90,  135)
            self.color_text          = (255, 255, 255)

            self.text_surf  = font_button.render("Start", True, self.color_text)
            self.is_hovered = False

        def update(self, mouse_pos):
            self.is_hovered = self.hit_rect.collidepoint(mouse_pos)

        def draw(self, surface):
            main_col   = self.color_hover        if self.is_hovered else self.color_normal
            shadow_col = self.color_hover_shadow if self.is_hovered else self.color_normal_shadow
            offset     = self.shadow_depth // 2  if self.is_hovered else 0

            shadow_rect = pygame.Rect(
                self.rect.x, self.rect.y + self.shadow_depth,
                self.width, self.height
            )
            pygame.draw.rect(surface, shadow_col, shadow_rect, border_radius=14)

            body_rect = pygame.Rect(
                self.rect.x, self.rect.y + offset,
                self.width, self.height
            )
            pygame.draw.rect(surface, main_col, body_rect, border_radius=14)

            surface.blit(self.text_surf, self.text_surf.get_rect(center=body_rect.center))

        def handle_click(self, event):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.hit_rect.collidepoint(event.pos):
                    print("Start button clicked!")
                    return True
            if event.type == pygame.FINGERDOWN:
                print("Start button touched!")
                return True
            return False