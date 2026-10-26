"""Écran « France Info » (module système) : liste d'actualités + détail.

Ouvert depuis l'accueil (onglet « France Info » ou clic sur un des 3 titres).
Deux modes :
  - « list » : liste défilante des titres (flèches ▲/▼ pour parcourir) ;
  - « detail » : titre + date + résumé de l'article sélectionné.

Le bouton RETOUR : en détail → revient à la liste ; en liste → revient à
l'accueil. Le flux RSS est partagé avec l'accueil (voir rss_feed.get_feed).
"""

from __future__ import annotations

import pygame

from inputs import ACTION_BACK
from screen import Screen

from .rss_feed import Article, get_feed

RETOUR_RECT = pygame.Rect(690, 0, 110, 58)

# Liste.
LIST_X = 24
LIST_W = 700
LIST_TOP = 74
ROW_H = 66
VISIBLE = 6
UP_RECT = pygame.Rect(740, 74, 48, 44)
DOWN_RECT = pygame.Rect(740, 400, 48, 44)

# Détail.
DET_X = 28
DET_W = 744

GOLD = (210, 175, 95)
WHITE = (238, 240, 245)
DIM = (150, 165, 195)


def wrap_text(text: str, font: pygame.font.Font, max_w: int, max_lines: int) -> list[str]:
    """Découpe en lignes tenant dans max_w (au plus max_lines, '…' sinon)."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if font.size(trial)[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # Tronque la dernière ligne s'il reste du texte.
    if len(lines) == max_lines and font.size(lines[-1])[0] <= max_w:
        consumed = len(" ".join(lines))
        if consumed < len(text):
            last = lines[-1]
            while last and font.size(last + "…")[0] > max_w:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
    return lines


class NewsScreen(Screen):
    name = "news"
    background_name = None          # dessiné entièrement en code (fond uni)
    bg_color = (10, 14, 26)
    cycle = False                   # accessible seulement via l'accueil

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 42)
        self.font_row = pygame.font.Font(None, 28)
        self.font_meta = pygame.font.Font(None, 20)
        self.font_hint = pygame.font.Font(None, 24)
        self.font_det_title = pygame.font.Font(None, 40)
        self.font_det_body = pygame.font.Font(None, 26)

        self.feed = get_feed(app)
        self.mode = "list"
        self.selected: Article | None = None
        self.offset = 0
        self._rows: list[tuple[pygame.Rect, Article]] = []
        self._last_state = None

    # ----------------------------------------------- appelé depuis l'accueil
    def show_list(self) -> None:
        self.mode = "list"
        self.offset = 0
        self._last_state = None

    def show_detail(self, article: Article) -> None:
        self.mode = "detail"
        self.selected = article
        self._last_state = None

    def enter(self) -> None:
        self._last_state = None     # ne touche pas au mode fixé par show_*

    # --------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            if self.mode == "detail":
                self.show_list()
                return None
            return ACTION_BACK      # liste → retour accueil

        if self.mode == "list":
            articles = self._articles()
            if UP_RECT.collidepoint(pos):
                self.offset = max(0, self.offset - VISIBLE)
                self._last_state = None
            elif DOWN_RECT.collidepoint(pos):
                if self.offset + VISIBLE < len(articles):
                    self.offset += VISIBLE
                    self._last_state = None
            else:
                for rect, art in self._rows:
                    if rect.collidepoint(pos):
                        self.show_detail(art)
                        break
        return None

    # ----------------------------------------------------------------- rendu
    def _articles(self) -> list[Article]:
        return self.feed.articles() if self.feed is not None else []

    def _signature(self):
        if self.mode == "detail":
            s = self.selected
            return ("detail", s.title if s else None)
        arts = self._articles()
        return ("list", self.offset, len(arts),
                tuple(a.title for a in arts[self.offset:self.offset + VISIBLE]))

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        sig = self._signature()
        if sig == self._last_state:
            return []
        self._last_state = sig

        surface.fill(self.bg_color)
        # Barre de titre.
        surface.blit(self.font_title.render("France Info", True, GOLD), (LIST_X, 12))
        pygame.draw.rect(surface, (30, 42, 68), RETOUR_RECT, border_radius=8)
        hint = self.font_hint.render("RETOUR", True, (205, 210, 220))
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))
        pygame.draw.line(surface, (34, 46, 74), (0, 60), (self.width, 60), 1)

        if self.mode == "detail":
            self._draw_detail(surface)
        else:
            self._draw_list(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_list(self, surface: pygame.Surface) -> None:
        self._rows = []
        articles = self._articles()
        if not articles:
            msg = "Chargement des actualités…" if self.feed else "Flux RSS désactivé."
            surface.blit(self.font_row.render(msg, True, DIM), (LIST_X, LIST_TOP + 10))
            return

        window = articles[self.offset:self.offset + VISIBLE]
        for i, art in enumerate(window):
            top = LIST_TOP + i * ROW_H
            row = pygame.Rect(LIST_X, top, LIST_W, ROW_H - 8)
            pygame.draw.rect(surface, (16, 22, 38), row, border_radius=8)
            title = wrap_text(art.title, self.font_row, LIST_W - 24, 1)[0]
            surface.blit(self.font_row.render(title, True, WHITE), (row.x + 12, row.y + 8))
            meta = art.published or ""
            if art.summary:
                snippet = wrap_text(art.summary, self.font_meta, LIST_W - 24, 1)[0]
                meta = f"{meta}   {snippet}" if meta else snippet
                meta = wrap_text(meta, self.font_meta, LIST_W - 24, 1)[0]
            if meta:
                surface.blit(self.font_meta.render(meta, True, DIM), (row.x + 12, row.y + 34))
            self._rows.append((row, art))

        # Flèches de défilement + position.
        self._draw_arrow(surface, UP_RECT, up=True, enabled=self.offset > 0)
        self._draw_arrow(surface, DOWN_RECT, up=False,
                         enabled=self.offset + VISIBLE < len(articles))
        pos = f"{self.offset + 1}–{min(self.offset + VISIBLE, len(articles))} / {len(articles)}"
        surface.blit(self.font_meta.render(pos, True, DIM), (740 - 4, 366))

    def _draw_arrow(self, surface, rect, *, up: bool, enabled: bool) -> None:
        pygame.draw.rect(surface, (30, 42, 68) if enabled else (18, 24, 38),
                         rect, border_radius=8)
        color = GOLD if enabled else (70, 82, 108)
        cx, cy = rect.center
        if up:
            pts = [(cx, cy - 9), (cx - 10, cy + 7), (cx + 10, cy + 7)]
        else:
            pts = [(cx, cy + 9), (cx - 10, cy - 7), (cx + 10, cy - 7)]
        pygame.draw.polygon(surface, color, pts)

    def _draw_detail(self, surface: pygame.Surface) -> None:
        art = self.selected
        if art is None:
            return
        y = 78
        for line in wrap_text(art.title, self.font_det_title, DET_W, 3):
            surface.blit(self.font_det_title.render(line, True, WHITE), (DET_X, y))
            y += 44
        y += 6
        if art.published:
            surface.blit(self.font_meta.render(art.published, True, GOLD), (DET_X, y))
            y += 32
        if art.summary:
            for line in wrap_text(art.summary, self.font_det_body, DET_W, 8):
                surface.blit(self.font_det_body.render(line, True, (205, 212, 228)), (DET_X, y))
                y += 32
        if art.link:
            link = wrap_text(art.link, self.font_meta, DET_W, 1)[0]
            surface.blit(self.font_meta.render(link, True, DIM), (DET_X, self.height - 34))
