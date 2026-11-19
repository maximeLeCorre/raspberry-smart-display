"""Dessin commun aux écrans de supervision (code-drawn, mêmes couleurs que l'écran Machine).

Chaque état a sa forme ET son mot (utilisateur daltonien) : rond coché = OK, triangle =
ATTENTION, carré barré = PANNE, rond creux « ? » = INCONNU.
"""

from __future__ import annotations

import time

import pygame

from .monitor import CRIT, OK, UNKNOWN, WARN, WORDS

BG = (10, 14, 26)
WHITE = (238, 240, 245)
SOFT = (201, 210, 228)
GREY = (150, 165, 195)
DIM = (140, 154, 184)            # petits libellés : contraste suffisant sur BG
FAINT = (92, 106, 134)
GOLD = (210, 175, 95)
GREEN = (110, 210, 130)
ORANGE = (230, 170, 70)
RED = (255, 138, 138)            # texte rouge lisible sur fond sombre
RED_LINE = (228, 86, 86)
BLUE = (96, 150, 235)
PANEL = (24, 32, 52)
PANEL_DARK = (20, 27, 46)
BORDER = (42, 54, 84)
TRACK = (30, 40, 62)
CRIT_FILL = (42, 21, 24)
WARN_FILL = (42, 33, 18)

LEVEL_COLOR = {OK: GREEN, WARN: ORANGE, CRIT: RED, UNKNOWN: GREY}

RETOUR_RECT = pygame.Rect(700, 8, 92, 38)


class Fonts:
    def __init__(self):
        self.title = pygame.font.Font(None, 40)
        self.big = pygame.font.Font(None, 34)
        self.label = pygame.font.Font(None, 28)
        self.text = pygame.font.Font(None, 24)
        self.small = pygame.font.Font(None, 21)
        self.tiny = pygame.font.Font(None, 18)


def fit(text: str, font, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def blit(surface, font, text, color, pos, max_w: int = 0, anchor: str = "topleft") -> pygame.Rect:
    surf = font.render(fit(text, font, max_w) if max_w else text, True, color)
    rect = surf.get_rect(**{anchor: pos})
    surface.blit(surf, rect)
    return rect


def state_icon(surface, level: str, center: tuple[int, int], size: int = 22) -> None:
    color = LEVEL_COLOR[level]
    x, y = center
    r = size // 2
    w = max(2, size // 9)
    if level == OK:
        pygame.draw.circle(surface, color, center, r, w)
        pygame.draw.lines(surface, color, False,
                          [(x - r * 0.45, y + r * 0.05), (x - r * 0.1, y + r * 0.4), (x + r * 0.5, y - r * 0.3)], w)
    elif level == WARN:
        pts = [(x, y - r), (x + r, y + r * 0.85), (x - r, y + r * 0.85)]
        pygame.draw.polygon(surface, color, pts, w)
        pygame.draw.line(surface, color, (x, y - r * 0.3), (x, y + r * 0.3), w)
        pygame.draw.circle(surface, color, (x, round(y + r * 0.6)), max(1, w // 2 + 1))
    elif level == CRIT:
        box = pygame.Rect(0, 0, size - 2, size - 2)
        box.center = center
        pygame.draw.rect(surface, color, box, w, border_radius=3)
        d = r * 0.4
        pygame.draw.line(surface, color, (x - d, y - d), (x + d, y + d), w)
        pygame.draw.line(surface, color, (x + d, y - d), (x - d, y + d), w)
    else:
        for i in range(0, 360, 45):            # cercle en pointillés
            v = pygame.math.Vector2(r, 0).rotate(i)
            pygame.draw.circle(surface, color, (round(x + v.x), round(y + v.y)), max(1, w // 2 + 1))
        f = pygame.font.Font(None, size)
        q = f.render("?", True, color)
        surface.blit(q, q.get_rect(center=(x, y + 1)))


def mark(surface, level: str, center: tuple[int, int], color) -> None:
    """Petit signe dans une étiquette pleine : × (panne) ou ! (attention)."""
    x, y = center
    if level == CRIT:
        pygame.draw.line(surface, color, (x - 4, y - 4), (x + 4, y + 4), 2)
        pygame.draw.line(surface, color, (x + 4, y - 4), (x - 4, y + 4), 2)
    else:
        pygame.draw.line(surface, color, (x, y - 5), (x, y + 2), 2)
        pygame.draw.circle(surface, color, (x, y + 5), 1)


def arrow(surface, color, center: tuple[int, int], left: bool = False) -> None:
    """Flèche pleine ◀/▶ (la police par défaut n'a pas ces glyphes)."""
    x, y = center
    d = -5 if left else 5
    pygame.draw.polygon(surface, color, [(x - d, y - 6), (x + d, y), (x - d, y + 6)])


def state_word(surface, font, level: str, pos: tuple[int, int], size: int = 22, word: str = "") -> pygame.Rect:
    """Icône + mot d'état (« PANNE »), à gauche en `pos` (centre vertical)."""
    state_icon(surface, level, (pos[0] + size // 2, pos[1]), size)
    return blit(surface, font, word or WORDS[level], LEVEL_COLOR[level], (pos[0] + size + 8, pos[1]),
                anchor="midleft")


def header(surface, fonts: Fonts, title: str) -> None:
    blit(surface, fonts.title, title, WHITE, (24, 14), max_w=440)
    pygame.draw.rect(surface, GOLD, RETOUR_RECT, width=2, border_radius=8)
    blit(surface, fonts.small, "RETOUR", GOLD, RETOUR_RECT.center, anchor="center")


def panel(surface, rect, level: str | None = None, fill=PANEL) -> None:
    """Cadre ; bordure (épaisse en panne) selon l'état s'il est donné."""
    if level == CRIT:
        pygame.draw.rect(surface, CRIT_FILL, rect, border_radius=12)
        pygame.draw.rect(surface, RED_LINE, rect, width=3, border_radius=12)
    elif level == WARN:
        pygame.draw.rect(surface, fill, rect, border_radius=12)
        pygame.draw.rect(surface, ORANGE, rect, width=2, border_radius=12)
    else:
        pygame.draw.rect(surface, fill, rect, border_radius=12)
        pygame.draw.rect(surface, BORDER, rect, width=2, border_radius=12)


def kv(surface, fonts: Fonts, rect: pygame.Rect, y: int, key: str, value: str, color=WHITE) -> None:
    """Ligne « libellé ........ valeur » dans un panneau."""
    blit(surface, fonts.small, key, GREY, (rect.x + 12, y))
    blit(surface, fonts.small, value, color, (rect.right - 12, y), anchor="topright",
         max_w=rect.w - 24 - fonts.small.size(key)[0] - 10)


def bar(surface, rect: pygame.Rect, frac: float, color) -> None:
    pygame.draw.rect(surface, TRACK, rect, border_radius=rect.h // 2)
    frac = max(0.0, min(1.0, frac))
    if frac > 0:
        pygame.draw.rect(surface, color, (rect.x, rect.y, max(rect.h, int(rect.w * frac)), rect.h),
                         border_radius=rect.h // 2)


def nice_step(value: float, max_ticks: int = 4, min_step: float = 1.0) -> float:
    """Pas 1/2/5 × 10^k (≥ `min_step`) pour couvrir `value` en `max_ticks` graduations au plus."""
    step = min_step
    while True:
        for m in (1, 2, 5):
            if value <= m * step * max_ticks:
                return m * step
        step *= 10


def y_axis(surface, font, plot: pygame.Rect, top: float, step: float, fmt, color=DIM) -> None:
    """Échelle verticale : ligne de grille + valeur écrite à gauche à chaque pas, de 0 à `top`."""
    n = max(1, round(top / step))
    for i in range(n + 1):
        y = plot.bottom - round(plot.h * i / n)
        pygame.draw.line(surface, TRACK, (plot.x, y), (plot.right, y))
        blit(surface, font, fmt(i * step), color, (plot.x - 6, y), anchor="midright")


def hatch(surface, rect: pygame.Rect, color, bg) -> None:
    """Hachures (période dégradée/panne : repérable sans la couleur)."""
    pygame.draw.rect(surface, bg, rect)
    clip = surface.get_clip()
    surface.set_clip(rect)
    for x in range(rect.x - rect.h, rect.right, 6):
        pygame.draw.line(surface, color, (x, rect.bottom), (x + rect.h, rect.y), 2)
    surface.set_clip(clip)


def ago(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return "—"
    s = (now or time.time()) - ts
    if s < 90:
        return "à l'instant"
    if s < 3600:
        return f"il y a {int(s // 60)} min"
    if s < 2 * 86400:
        return f"il y a {int(s // 3600)} h"
    return f"il y a {int(s // 86400)} j"


def hhmm(ts: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "—"


def duration(seconds: float | None) -> str:
    if not seconds or seconds < 0:
        return "—"
    s = int(seconds)
    if s < 3600:
        return f"{s // 60} min"
    if s < 2 * 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} j"


def size_text(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} Go".replace(".", ",")
    return f"{n / 1024 ** 2:.0f} Mo"


def cpu_text(pct: float | None) -> str:
    """CPU de `docker stats` (% d'un cœur) : décimales sous 10 %, un conteneur au repos est à 0,0x %."""
    if pct is None:
        return "—"
    return f"{pct:.2f} %".replace(".", ",") if pct < 10 else f"{pct:.0f} %"
