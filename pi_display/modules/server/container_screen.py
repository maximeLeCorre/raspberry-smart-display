"""Écran d'un conteneur Rentrer (ouvert en touchant sa carte sur l'écran Rentrer).

État (écrit + forme), redémarrages, démarré depuis ; deux courbes séparées, chacune avec
son échelle et ses valeurs écrites : CPU (% d'un cœur, comme `docker stats`) et RAM.
Points lus dans `monitor.db` (`history.py`, ~1 par minute, 2 jours gardés) ; fenêtre 1 h,
6 h ou 24 h. Un trou dans la courbe = conteneur arrêté ou Pi sans relevé.
"""

from __future__ import annotations

import time

import pygame

from screen import Screen

from . import widgets as w
from .monitor import CRIT, DOCKER_WORDS, OK, WARN

RANGES = ((3600, "1 h"), (6 * 3600, "6 h"), (86400, "24 h"))
RANGE_RECTS = [pygame.Rect(470 + i * 74, 56, 66, 34) for i in range(len(RANGES))]
CPU_RECT = pygame.Rect(24, 104, 752, 176)
RAM_RECT = pygame.Rect(24, 292, 752, 176)
CPU_COL = (240, 165, 30)       # mêmes couleurs que l'écran Machine
RAM_COL = (110, 195, 245)


def nice_top(value: float, unit: float = 1.0) -> float:
    """Plus petite graduation 1/2/5 × 10^k (× `unit`) au-dessus de `value` (+10 % de marge)."""
    target = max(value * 1.1, 0.1 * unit)
    step = 0.1 * unit
    while True:
        for m in (1, 2, 5):
            if m * step >= target:
                return m * step
        step *= 10


def series_segments(points: list[tuple[float, float]], max_gap: float) -> list[list[tuple[float, float]]]:
    """Coupe la série là où deux points sont trop espacés (conteneur arrêté, Pi muet)."""
    out, cur, prev = [], [], None
    for t, v in points:
        if prev is not None and t - prev > max_gap and cur:
            out.append(cur)
            cur = []
        cur.append((t, v))
        prev = t
    if cur:
        out.append(cur)
    return out


class ContainerScreen(Screen):
    name = "server_container"
    background_name = None
    bg_color = w.BG
    cycle = False

    def __init__(self, app):
        super().__init__(app)
        self.fonts = w.Fonts()
        self.module = app.modules.get("server")
        self.range_idx = 0
        self._key = None
        self._drawn_at = 0.0

    def enter(self) -> None:
        self._key = None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        if self._key is not None and time.monotonic() - self._drawn_at < 1.0:
            return []
        self._drawn_at = time.monotonic()
        mod = self.module
        svc = mod.selected_container
        span = RANGES[self.range_idx][0]
        now = time.time()
        series = mod.history.container_series(svc, now - span) if mod.history else []
        rep = (mod.link.report() if mod.link else {}) or {}
        ctr = ((rep.get("data") or {}).get("containers") or {}).get(svc)
        key = (svc, self.range_idx, len(series), series[-1] if series else None, repr(ctr), int(now // 60))
        if key == self._key:
            return []
        self._key = key
        surface.blit(self.bg, (0, 0))
        w.header(surface, self.fonts, f"RENTRER · {svc}")
        self._status(surface, ctr, now)
        self._ranges(surface)
        gap = 3 * (getattr(mod.link, "report_seconds", 60) or 60)
        self._chart(surface, CPU_RECT, "CPU", CPU_COL, [(t, c) for t, c, _ in series if c is not None],
                    now, span, gap, w.cpu_text, 1.0)
        self._chart(surface, RAM_RECT, "RAM", RAM_COL, [(t, m) for t, _, m in series if m is not None],
                    now, span, gap, w.size_text, 1024 ** 2)
        return [surface.get_rect()]

    def _status(self, surface, ctr, now) -> None:
        f = self.fonts
        y = 73
        if ctr is None:
            w.state_word(surface, f.text, CRIT, (24, y), 18, "absent du relevé")
            return
        running = ctr.get("state") == "running"
        level = (WARN if ctr.get("health") == "unhealthy" else OK) if running else CRIT
        word = DOCKER_WORDS.get(ctr.get("state"), ctr.get("state") or "?")
        if ctr.get("health") == "unhealthy":
            word += " · malade"
        elif ctr.get("health") == "healthy":
            word += " · sain"
        r = w.state_word(surface, f.text, level, (24, y), 18, word)
        since = w.duration(now - ctr["started"]) if ctr.get("started") else "—"
        restarts = ctr.get("restarts", 0)
        w.blit(surface, f.small, f"· {restarts} redém. · depuis {since}", w.GREY, (r.right + 10, y),
               max_w=RANGE_RECTS[0].x - r.right - 24, anchor="midleft")

    def _ranges(self, surface) -> None:
        for i, (rect, (_, label)) in enumerate(zip(RANGE_RECTS, RANGES)):
            if i == self.range_idx:      # choisi = plein (repérable sans la couleur)
                pygame.draw.rect(surface, w.GOLD, rect, border_radius=8)
                w.blit(surface, self.fonts.small, label, w.BG, rect.center, anchor="center")
            else:
                pygame.draw.rect(surface, w.BORDER, rect, width=2, border_radius=8)
                w.blit(surface, self.fonts.small, label, w.SOFT, rect.center, anchor="center")

    def _chart(self, surface, rect, name, color, points, now, span, max_gap, fmt, unit) -> None:
        f = self.fonts
        w.panel(surface, rect)
        plot = pygame.Rect(rect.x + 70, rect.y + 36, rect.w - 90, rect.h - 62)
        last = points[-1][1] if points else None
        pygame.draw.circle(surface, color, (rect.x + 18, rect.y + 18), 5)
        r = w.blit(surface, f.text, f"{name} {fmt(last)}", w.WHITE, (rect.x + 30, rect.y + 18), anchor="midleft")
        if points:
            vals = [v for _, v in points]
            w.blit(surface, f.small, f"moy. {fmt(sum(vals) / len(vals))} · max {fmt(max(vals))}", w.GREY,
                   (rect.right - 14, rect.y + 18), anchor="midright", max_w=rect.right - r.right - 30)
        top = nice_top(max((v for _, v in points), default=0), unit)
        for frac in (0, 0.5, 1):
            y = plot.bottom - round(plot.h * frac)
            pygame.draw.line(surface, w.TRACK, (plot.x, y), (plot.right, y))
            w.blit(surface, f.tiny, fmt(top * frac) if frac else "0", w.DIM, (plot.x - 8, y), anchor="midright")
        start = now - span
        for i in range(5):                # repères horaires
            t = start + i * span / 4
            x = plot.x + round(i * plot.w / 4)
            anchor = "midtop" if 0 < i < 4 else ("topleft" if i == 0 else "topright")
            w.blit(surface, f.tiny, "maint." if i == 4 else w.hhmm(t), w.DIM, (x, plot.bottom + 5), anchor=anchor)
        if len(points) < 2:
            w.blit(surface, f.small, "collecte en cours (1 point par minute)…", w.DIM, plot.center, anchor="center")
            return

        def xy(t, v):
            return (plot.x + (t - start) / span * plot.w,
                    plot.bottom - max(0.0, min(1.0, v / top)) * plot.h)

        segments = [[xy(t, v) for t, v in seg] for seg in series_segments(points, max_gap)]
        overlay = pygame.Surface(plot.size, pygame.SRCALPHA)
        for pts in segments:
            if len(pts) >= 2:
                local = [(x - plot.x, y - plot.y) for x, y in pts]
                pygame.draw.polygon(overlay, (*color, 55), local + [(local[-1][0], plot.h), (local[0][0], plot.h)])
        surface.blit(overlay, plot.topleft)
        for pts in segments:
            if len(pts) >= 2:
                pygame.draw.lines(surface, color, False, pts, 3)
            else:
                pygame.draw.circle(surface, color, (round(pts[0][0]), round(pts[0][1])), 3)

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if w.RETOUR_RECT.collidepoint(pos):
            self.app.manual_screen = "server_rentrer"
            self.app.set_screen("server_rentrer")
            return None
        for i, rect in enumerate(RANGE_RECTS):
            if rect.collidepoint(pos) and i != self.range_idx:
                self.range_idx = i
                self._key = None
        return None
