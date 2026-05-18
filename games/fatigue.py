"""
FatigueMixin — mix into any game screen.
Monitors sensor activity. If no meaningful input for FATIGUE_TIMEOUT seconds,
pauses the game and shows a rest prompt.

Also provides shared _draw_pause() and _apply_vol() used by all games.
Games must set self.pause_sel, self.pause_vol, self.vol_active before use.
"""

import pygame
from constants import get_theme, GAME_W, GAME_H

FATIGUE_TIMEOUT = 60.0   # seconds of inactivity before rest prompt
ACTIVITY_THRESH = 0.05   # minimum grip/tilt change to count as "active"


class FatigueMixin:
    def _init_fatigue(self):
        self.fatigue_timer  = 0.0
        self.fatigue_paused = False
        self._last_grip     = 0.0
        self._last_tilt     = 0.0

    def _update_fatigue(self, dt, state):
        if self.fatigue_paused:
            return
        grip_delta = abs(state.get("grip",   0.0) - self._last_grip)
        tilt_delta = abs(state.get("tilt_x", 0.0) - self._last_tilt)
        finger_any = any(state.get("fingers", []))
        if grip_delta > ACTIVITY_THRESH or tilt_delta > ACTIVITY_THRESH or finger_any:
            self.fatigue_timer = 0.0
        else:
            self.fatigue_timer += dt
            if self.fatigue_timer >= FATIGUE_TIMEOUT:
                self.fatigue_paused = True
        self._last_grip = state.get("grip",   0.0)
        self._last_tilt = state.get("tilt_x", 0.0)

    def _resume_fatigue(self):
        self.fatigue_timer  = 0.0
        self.fatigue_paused = False

    def _apply_vol(self):
        try:
            pygame.mixer.music.set_volume(self.pause_vol)
            from db.database import set_volume
            set_volume(self.pause_vol)
        except Exception:
            pass

    def _draw_pause(self, surface):
        T       = get_theme()
        font    = pygame.font.SysFont("monospace", 48, bold=True)
        font_sm = pygame.font.SysFont("monospace", 28)
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        surface.blit(ov, (0, 0))
        panel = pygame.Rect(GAME_W // 2 - 260, GAME_H // 2 - 200, 520, 420)
        pygame.draw.rect(surface, T["PANEL"], panel, border_radius=16)
        pygame.draw.rect(surface, T["ACCENT"], panel, 2, border_radius=16)
        for i, opt in enumerate(["RESUME", "RESTART", "VOLUME", "EXIT"]):
            col = T["ACCENT"] if i == self.pause_sel else T["GRAY"]
            lbl = font.render(opt, True, col)
            surface.blit(lbl, (GAME_W // 2 - lbl.get_width() // 2,
                               GAME_H // 2 - 160 + i * 96))
            if opt == "VOLUME" and (i == self.pause_sel or self.vol_active):
                bw, bh = 360, 12
                bx = GAME_W // 2 - bw // 2
                by = GAME_H // 2 - 160 + i * 96 + 52
                pygame.draw.rect(surface, T["PANEL"], (bx, by, bw, bh), border_radius=6)
                pygame.draw.rect(surface, T["GREEN"],
                                 (bx, by, int(bw * self.pause_vol), bh), border_radius=6)
                pct = font_sm.render(f"{int(self.pause_vol * 100)}%", True, T["GREEN"])
                surface.blit(pct, (bx + bw + 10, by - 4))
                if self.vol_active:
                    hint = font_sm.render("← → adjust  ENTER done", True, T["GRAY"])
                    surface.blit(hint, (GAME_W // 2 - hint.get_width() // 2, by + 20))

    def _draw_fatigue_overlay(self, surface):
        if not self.fatigue_paused:
            return
        T        = get_theme()
        font_big = pygame.font.SysFont("monospace", 64, bold=True)
        font     = pygame.font.SysFont("monospace", 36)
        font_sm  = pygame.font.SysFont("monospace", 28)
        overlay  = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        surface.blit(overlay, (0, 0))
        title = font_big.render("Take a Break!", True, T["YELLOW"])
        surface.blit(title, (GAME_W // 2 - title.get_width() // 2, GAME_H // 2 - 140))
        msg = font.render("No activity detected for 60 seconds.", True, T["TEXT"])
        surface.blit(msg, (GAME_W // 2 - msg.get_width() // 2, GAME_H // 2 - 40))
        sub = font.render("Take a deep breath and rest your hand.", True, T["GRAY"])
        surface.blit(sub, (GAME_W // 2 - sub.get_width() // 2, GAME_H // 2 + 20))
        hint = font_sm.render("Press ENTER or squeeze to continue.", True, T["ACCENT"])
        surface.blit(hint, (GAME_W // 2 - hint.get_width() // 2, GAME_H // 2 + 100))
