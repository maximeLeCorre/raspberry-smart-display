"""Mode file d'attente / ready-check.

Données reçues (payload) :
    {"state": "searching", "timeInQueue": 42, "estimated": 90}
    {"state": "readycheck", "remaining": 8, "response": "None"|"Accepted"}
"""

from __future__ import annotations

import pygame

from inputs import ACTION_BACK
from modes.base import Mode

RETOUR_RECT = pygame.Rect(700, 8, 92, 40)


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class QueueMode(Mode):
    name = "queue"
    background_name = "champselect.png"
    bg_color = (12, 16, 30)

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 54)
        self.font_big = pygame.font.Font(None, 150)
        self.font_sub = pygame.font.Font(None, 36)
        self.font_hint = pygame.font.Font(None, 24)
        self.data: dict = {}
        self._last_signature = None

    def enter(self) -> None:
        self._last_signature = None

    def update_data(self, payload: dict) -> None:
        self.data = payload or {}

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        return None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = (self.data.get("state"), self.data.get("timeInQueue"),
                     self.data.get("remaining"), self.data.get("response"))
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.blit(self.bg, (0, 0))
        hint = self.font_hint.render("RETOUR", True, (200, 200, 210))
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        if self.data.get("state") == "readycheck":
            self._draw_ready(surface)
        else:
            self._draw_searching(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_searching(self, surface: pygame.Surface) -> None:
        t = self.data.get("timeInQueue", 0)
        dots = "." * (1 + (t % 3))
        title = self.font_title.render(f"Recherche de partie{dots}", True, (210, 175, 95))
        surface.blit(title, title.get_rect(center=(self.width // 2, 120)))

        timer = self.font_big.render(_mmss(t), True, (240, 240, 245))
        surface.blit(timer, timer.get_rect(center=(self.width // 2, 250)))

        est = self.data.get("estimated", 0)
        if est:
            sub = self.font_sub.render(f"Temps estimé : ~{_mmss(est)}", True, (150, 170, 205))
            surface.blit(sub, sub.get_rect(center=(self.width // 2, 360)))

    def _draw_ready(self, surface: pygame.Surface) -> None:
        accepted = self.data.get("response") == "Accepted"
        color = (120, 220, 130) if accepted else (235, 200, 90)
        title = self.font_title.render("PARTIE TROUVÉE !", True, color)
        surface.blit(title, title.get_rect(center=(self.width // 2, 120)))

        remaining = self.data.get("remaining", 0)
        big = self.font_big.render(str(remaining), True, color)
        surface.blit(big, big.get_rect(center=(self.width // 2, 250)))

        msg = "Accepté ✓" if accepted else "Accepte dans le client"
        sub = self.font_sub.render(msg, True, (200, 215, 230))
        surface.blit(sub, sub.get_rect(center=(self.width // 2, 360)))
