# =============================================================================
# scenes/therapist_welcome.py
# =============================================================================

import pygame
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audio import play_welcome, play_click

# Dual-monitor mode only: clicking START here must also flip the shared session
# so the patient window leaves its Welcome splash for the Waiting Screen. Inert
# (and this import is skipped) when RECOVR_DUAL_MONITOR is unset.
_DUAL_MONITOR = os.environ.get("RECOVR_DUAL_MONITOR") == "1"


class TherapistWelcomeScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        # --- BACKGROUND ---
        self.background_surface = self._create_gradient(width, height)

        # ------------------------------------------------------------------
        # LAYOUT -- tuned for the 7-inch 800x480 therapist LCD.
        #
        # Everything below is a fraction of the real viewport, and the two text
        # elements are FITTED to those boxes rather than scaled from a 1080p
        # mock-up, so 800x480 is the design target instead of a shrunken desktop
        # layout. Vertical budget at 800x480:
        #     top 35 | title 192 | 14 | subtitle 34 | 62 | button 103 | 41 = 480
        # ------------------------------------------------------------------
        TOP_FRAC     = 0.072   # margin above the title
        TITLE_H_FRAC = 0.40    # title box height
        TITLE_W_FRAC = 0.86    # title may not exceed this share of the width
        GAP_TS_FRAC  = 0.030   # title -> subtitle (kept tight: one branding block)
        SUB_H_FRAC   = 0.070   # subtitle box height
        SUB_W_FRAC   = 0.90
        BTN_H_FRAC   = 0.215   # big finger target
        BTN_W_FRAC   = 0.42
        BOT_FRAC     = 0.085   # margin below the button (clear of the bezel)

        _fd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "font")
        def _F(n): return os.path.join(_fd, n)

        # Title: largest arialblack that fits the title box in BOTH axes.
        self.font_title = self._fit_font(
            lambda px: pygame.font.SysFont("arialblack", px), "RecovR",
            int(width * TITLE_W_FRAC), int(height * TITLE_H_FRAC))
        # Subtitle: fitted the same way so it never overruns a narrow screen.
        sub_text = "Gamified Hand Rehabilitation System"
        self.font_subtitle = self._fit_font(
            lambda px: pygame.font.Font(_F("Sora-Light.ttf"), px), sub_text,
            int(width * SUB_W_FRAC), int(height * SUB_H_FRAC))

        title_h = self.font_title.size("RecovR")[1]
        sub_h   = self.font_subtitle.size(sub_text)[1]

        # Title sits high; subtitle hangs directly under it as one branding block.
        self.title_y     = int(height * TOP_FRAC)
        self.row_spacing = int(height * GAP_TS_FRAC)
        self.sub_y       = self.title_y + title_h + self.row_spacing
        # Outline thickness scales with the title so it never looks pasted on.
        self._outline    = max(2, int(title_h * 0.035))

        # Button is anchored to the BOTTOM of the viewport, not stacked under
        # the text -- that is what removes the dead space at the foot of the page.
        btn_h    = int(height * BTN_H_FRAC)
        btn_w    = int(width  * BTN_W_FRAC)
        button_y = height - int(height * BOT_FRAC) - btn_h

        self.font_button = self._fit_font(
            lambda px: pygame.font.Font(_F("Lexend-SemiBold.ttf"), px), "Start",
            int(btn_w * 0.55), int(btn_h * 0.42))

        # --- BUTTON ---
        self.start_button = self._DeepStartButton(
            width // 2, button_y, btn_w, btn_h, width, height, self.font_button
        )

        # --- FADE-IN ---
        self.alpha          = 0
        self.fade_surface   = pygame.Surface((width, height))
        self.fade_surface.fill((255, 255, 255))
        self._welcome_played = False

        # --- LAUNCH GUARD ---
        self.launch_triggered = False

    # ------------------------------------------------------------------
    # SCENE INTERFACE
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if not self.launch_triggered:
            if self.start_button.handle_click(event):
                play_click()
                self.launch_triggered = True
                if _DUAL_MONITOR:
                    # Synchronized state change: patient Welcome -> Waiting Screen
                    # while this app goes Welcome -> Login. No timers.
                    try:
                        from recovr.therapist_link import therapist_link
                        therapist_link.start()
                        therapist_link.set_booting(True)
                    except Exception as exc:      # pragma: no cover - defensive
                        print(f"[recovr] welcome->waiting sync skipped ({exc})")
                return "login"
        return None

    def update(self, mouse_pos, dt):
        self.start_button.update(mouse_pos)
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    def draw(self, surface):
        if not self._welcome_played:
            play_welcome()
            self._welcome_played = True
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

    @staticmethod
    def _fit_font(make_font, text, max_w, max_h, lo=8, hi=400):
        """Largest font from `make_font(px)` whose `text` fits max_w x max_h.
        Fitting (rather than scaling a 1080p constant) is what lets the same
        code look right on the 800x480 panel and on a desktop window."""
        best = make_font(lo)
        while lo <= hi:
            mid = (lo + hi) // 2
            f = make_font(mid)
            w, h = f.size(text)
            if w <= max_w and h <= max_h:
                best, lo = f, mid + 1
            else:
                hi = mid - 1
        return best

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

        tw1, _    = self.font_title.size(part1)
        tw2, _    = self.font_title.size(part2)
        tsub_w, _ = self.font_subtitle.size(sub_text)

        start_x = (self.WIDTH // 2) - ((tw1 + tw2) // 2)
        part2_x = start_x + tw1

        o = self._outline
        def draw_outlined(font, text, x, y, color):
            for dx in (-o, 0, o):
                for dy in (-o, 0, o):
                    if dx or dy:
                        surface.blit(font.render(text, True, COLOR_OUTLINE), (x+dx, y+dy))
            surface.blit(font.render(text, True, color), (x, y))

        draw_outlined(self.font_title, part1, start_x, self.title_y, COLOR_WHITE)
        draw_outlined(self.font_title, part2, part2_x, self.title_y, COLOR_RED)

        sub_x = (self.WIDTH // 2) - (tsub_w // 2)
        surface.blit(self.font_subtitle.render(sub_text, True, COLOR_SUB),
                     (sub_x, self.sub_y))

    # ------------------------------------------------------------------
    # INNER CLASS: 3D Start Button
    # ------------------------------------------------------------------

    class _DeepStartButton:

        def __init__(self, center_x, top_y, btn_w, btn_h, WIDTH, HEIGHT, font_button):
            self.SCREEN_W     = WIDTH
            self.SCREEN_H     = HEIGHT
            self.width        = btn_w
            self.height       = btn_h
            self.shadow_depth = max(3, int(btn_h * 0.10))

            self.rect     = pygame.Rect(
                center_x - (self.width // 2), top_y, self.width, self.height
            )
            # Hit area = the whole visible button (body + its drop shadow) plus a
            # small margin. Deliberately modest so a tap near the screen edge or
            # under the subtitle cannot trigger Start by accident.
            self.hit_rect = pygame.Rect(
                self.rect.x, self.rect.y,
                self.width, self.height + self.shadow_depth
            ).inflate(int(WIDTH * 0.02), int(HEIGHT * 0.02))

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
                # FINGERDOWN carries normalised 0-1 coords -- convert and hit-test.
                # (Previously this returned True for a tap ANYWHERE on the panel,
                #  so the capacitive screen started a session on any stray touch.)
                pos = (int(event.x * self.SCREEN_W), int(event.y * self.SCREEN_H))
                if self.hit_rect.collidepoint(pos):
                    print("Start button touched!")
                    return True
            return False