# =============================================================================
# scenes/patient_dashboard.py
# =============================================================================
# PLACEHOLDER — Fill this in when you're ready to build the patient dashboard.
#
# WHEN YOU'RE READY TO BUILD THIS SCREEN:
#   - Design the patient's game selection screen here.
#   - Show grip strength, finger flexion, wrist rotation game options.
#   - For a Logout button, return "patient_welcome" from handle_event().
# =============================================================================

import pygame


class PatientDashboardScene:

    def __init__(self, screen, width, height):
        self.screen = screen
        self.WIDTH  = width
        self.HEIGHT = height

        self.font_title = pygame.font.SysFont("arialblack", int(60 * (height / 1080)))
        self.font_sub   = pygame.font.SysFont("georgia",    int(32 * (height / 1080)))

        # --- FADE-IN ---
        self.alpha        = 0
        self.fade_surface = pygame.Surface((width, height))
        self.fade_surface.fill((255, 255, 255))

    def handle_event(self, event):
        """
        PLACEHOLDER: press Backspace to go back to patient welcome screen.
        Replace this with your real game selection interactions later.
        """
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                return "patient_welcome"
        return None

    def update(self, mouse_pos, dt):
        if self.alpha < 255:
            self.alpha = min(255, self.alpha + 4)

    def draw(self, surface):
        surface.fill((245, 255, 245))

        title = self.font_title.render("Patient Dashboard", True, (30, 140, 80))
        hint  = self.font_sub.render(
            "Backspace → Back to Patient Welcome",
            True, (60, 120, 70)
        )
        surface.blit(title, title.get_rect(center=(self.WIDTH//2, self.HEIGHT//2 - 40)))
        surface.blit(hint,  hint.get_rect(center=(self.WIDTH//2,  self.HEIGHT//2 + 40)))

        if self.alpha < 255:
            self.fade_surface.set_alpha(255 - self.alpha)
            surface.blit(self.fade_surface, (0, 0))
