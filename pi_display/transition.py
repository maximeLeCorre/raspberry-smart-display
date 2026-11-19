"""Retour automatique : bandeau de préavis + glissement vers l'écran d'arrivée.

- `IdleBanner` : les `[display] idle_warning_seconds` dernières secondes avant le
  retour auto, un bandeau en bas de l'écran (texte + barre qui se vide). Il est
  posé **par-dessus** l'écran courant sans l'abîmer : la zone dessous est gardée
  avant de dessiner, puis remise après la présentation. L'écran continue donc
  ses dirty rects normalement, et le retirer = re-présenter sa zone.
- `slide` : l'écran d'arrivée entre par la gauche en poussant l'ancien
  (~0,4 s, adouci). Seul moment où l'app présente l'écran entier en boucle.
"""

from __future__ import annotations

import math
import time

import pygame

from screen import ASSETS_DIR

FONT_BOLD = ASSETS_DIR / "fonts" / "DejaVuSans-Bold.ttf"
FONT_REGULAR = ASSETS_DIR / "fonts" / "DejaVuSans.ttf"

PANEL = (11, 17, 32, 235)
BORDER = (44, 58, 90)
TRACK = (30, 40, 64)
GOLD = (210, 175, 95)
WHITE = (238, 240, 245)
DIM = (150, 165, 195)

BANNER_H = 62
BAR_H = 6
SLIDE_SECONDS = 0.4
SLIDE_FPS = 40


def _font(path, size):
    return pygame.font.Font(str(path), size) if path.exists() else pygame.font.Font(None, size + 8)


class IdleBanner:
    def __init__(self, width: int, height: int):
        self.rect = pygame.Rect(0, height - BANNER_H, width, BANNER_H)
        self._panel = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        self._panel.fill(PANEL)
        pygame.draw.line(self._panel, BORDER, (0, 0), (width, 0), 2)
        self._font = _font(FONT_BOLD, 20)
        self._font_hint = _font(FONT_REGULAR, 17)
        self._hint = self._font_hint.render("Touchez l'écran pour rester", True, DIM)
        self._under: pygame.Surface | None = None

    def draw(self, surface: pygame.Surface, remaining: float, total: float,
             label: str) -> pygame.Rect:
        """Pose le bandeau (`remaining` s sur `total`) ; `restore` après présentation."""
        self._under = surface.subsurface(self.rect).copy()
        surface.blit(self._panel, self.rect)
        text = self._font.render(f"{label} dans {max(1, math.ceil(remaining))} s", True, WHITE)
        mid = self.rect.y + (BANNER_H - BAR_H) // 2
        surface.blit(text, text.get_rect(midleft=(self.rect.x + 18, mid)))
        surface.blit(self._hint, self._hint.get_rect(midright=(self.rect.right - 18, mid)))
        bar = pygame.Rect(self.rect.x, self.rect.bottom - BAR_H, self.rect.w, BAR_H)
        pygame.draw.rect(surface, TRACK, bar)
        frac = max(0.0, min(1.0, remaining / total)) if total > 0 else 0.0
        pygame.draw.rect(surface, GOLD, (bar.x, bar.y, round(bar.w * frac), bar.h))
        return self.rect

    def restore(self, surface: pygame.Surface) -> None:
        if self._under is not None:
            surface.blit(self._under, self.rect)
            self._under = None


def slide(app, old: pygame.Surface, new: pygame.Surface, seconds: float = SLIDE_SECONDS) -> None:
    """Glisse `new` depuis la gauche en poussant `old` ; finit sur `new` net."""
    surface, w = app.surface, app.width
    full = [pygame.Rect(0, 0, w, app.height)]
    clock = pygame.time.Clock()
    start = time.monotonic()
    while seconds > 0:
        t = (time.monotonic() - start) / seconds
        if t >= 1:
            break
        x = round((1 - (1 - t) ** 3) * w)          # départ vif, arrivée douce
        surface.blit(old, (x, 0))
        surface.blit(new, (x - w, 0))
        pygame.draw.line(surface, GOLD, (x - 1, 0), (x - 1, app.height), 2)
        app.present(full)
        pygame.event.pump()                         # fenêtre réactive (les appuis restent en file)
        clock.tick(SLIDE_FPS)
    surface.blit(new, (0, 0))
    app.present(full)
