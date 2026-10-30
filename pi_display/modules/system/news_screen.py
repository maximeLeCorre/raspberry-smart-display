"""Écran « France Info » (module système) : liste d'actualités + article.

Ouvert depuis l'accueil (tuile Actus ou clic sur le titre du bandeau).
Deux modes :
  - « list » : liste défilante des titres (flèches ▲/▼ pour parcourir) ;
  - « detail » : l'article **complet**, découpé en pages (flèches ▲/▼ +
    « page 2 / 9 »). Le flux RSS n'ayant qu'un résumé, le Pi télécharge la page
    de l'article en tâche de fond (`article_text.fetch_article`, mis en cache) ;
    en attendant ou en cas d'échec, on affiche le résumé du flux.

Texte en DejaVu Sans **régulière** (plus lisible qu'en gras pour un long texte).
Le bouton RETOUR : en détail → revient à la liste ; en liste → revient à
l'accueil. Le flux RSS est partagé avec l'accueil (voir rss_feed.get_feed).
"""

from __future__ import annotations

import pygame

from inputs import ACTION_BACK
from screen import ASSETS_DIR, Screen

from .article_text import fetch_article
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

# Article : zone de texte à gauche, colonne de défilement à droite.
TEXT_RECT = pygame.Rect(24, 70, 676, 406)
PAGE_UP = pygame.Rect(712, 70, 80, 160)
PAGE_DOWN = pygame.Rect(712, 312, 80, 160)
PAGE_LABEL_Y = 271                # centre de « 2 / 9 » entre les flèches
PARA_GAP = 10                     # espace entre paragraphes
BULLET_INDENT = 22
CACHE_SIZE = 20                   # articles complets gardés en mémoire

FONT_REGULAR = ASSETS_DIR / "fonts" / "DejaVuSans.ttf"
FONT_BOLD = ASSETS_DIR / "fonts" / "DejaVuSans-Bold.ttf"

GOLD = (210, 175, 95)
WHITE = (238, 240, 245)
BODY = (214, 220, 232)
DIM = (150, 165, 195)
BTN = (30, 42, 68)
BTN_OFF = (18, 24, 38)


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


def paginate(heights: list[tuple[int, int]], view_h: int) -> list[int]:
    """Indices de début de page pour des lignes (écart avant, hauteur) ; l'écart
    d'une ligne qui commence une page est ignoré. Toujours au moins une page."""
    pages, used = [0], 0
    for i, (gap, h) in enumerate(heights):
        need = h if used == 0 else gap + h
        if used and used + need > view_h:
            pages.append(i)
            used = h
        else:
            used += need
    return pages


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
        self.font_page = pygame.font.Font(None, 26)
        # Article : (police, couleur, interligne) par type de bloc.
        bold, regular = str(FONT_BOLD), str(FONT_REGULAR)
        self.styles = {
            "title": (pygame.font.Font(bold, 25), WHITE, 33),
            "chapo": (pygame.font.Font(bold, 19), WHITE, 28),
            "h": (pygame.font.Font(bold, 20), GOLD, 29),
            "p": (pygame.font.Font(regular, 20), BODY, 29),
            "li": (pygame.font.Font(regular, 20), BODY, 29),
            "quote": (pygame.font.Font(regular, 20), DIM, 29),
            "meta": (pygame.font.Font(regular, 16), GOLD, 26),
            "status": (pygame.font.Font(regular, 17), DIM, 26),
        }

        self.feed = get_feed(app)
        self.mode = "list"
        self.selected: Article | None = None
        self.offset = 0
        self._rows: list[tuple[pygame.Rect, Article]] = []
        self._last_state = None
        # Articles complets : lien -> blocs, ou None si indisponible.
        self._full: dict[str, list | None] = {}
        self._loading: set[str] = set()
        self._lines: list[tuple] = []     # mise en page de l'article affiché
        self._pages: list[int] = [0]
        self.page = 0

    # ----------------------------------------------- appelé depuis l'accueil
    def show_list(self) -> None:
        self.mode = "list"
        self.offset = 0
        self._last_state = None

    def show_detail(self, article: Article) -> None:
        self.mode = "detail"
        self.selected = article
        self.page = 0
        self._last_state = None
        link = article.link
        # Pas encore chargé, ou échec précédent (réseau) : on (re)tente.
        if link and self._full.get(link) is None and link not in self._loading:
            self._loading.add(link)
            self.app.async_call(lambda: fetch_article(link),
                                lambda blocks: self._on_article(link, blocks))
        self._layout()

    def _on_article(self, link: str, blocks) -> None:
        self._loading.discard(link)
        self._full[link] = blocks or None
        while len(self._full) > CACHE_SIZE:
            self._full.pop(next(iter(self._full)))
        if self.mode == "detail" and self.selected and self.selected.link == link:
            self._layout()            # on reste en page 1 : rien n'a encore été lu au-delà
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

        if self.mode == "detail":
            if PAGE_UP.collidepoint(pos) and self.page > 0:
                self.page -= 1
            elif PAGE_DOWN.collidepoint(pos) and self.page < len(self._pages) - 1:
                self.page += 1
            return None

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

    # ------------------------------------------------------ mise en page article
    def _status(self) -> str:
        """État du texte complet : loading / full / summary (indisponible)."""
        link = self.selected.link if self.selected else ""
        if link in self._loading:
            return "loading"
        return "full" if self._full.get(link) else "summary"

    def _blocks(self) -> list[tuple[str, str]]:
        art = self.selected
        blocks: list[tuple[str, str]] = [("title", art.title)]
        if art.published:
            blocks.append(("meta", art.published))
        full = self._full.get(art.link)
        if full:
            if full[0][0] != "chapo" and art.summary:
                blocks.append(("chapo", art.summary))
            blocks.extend(full)
        else:
            if art.summary:
                blocks.append(("chapo", art.summary))
            blocks.append(("status", "Chargement de l'article complet…"
                           if self._status() == "loading"
                           else "Article complet indisponible : résumé du flux seulement."))
        return blocks

    def _layout(self) -> None:
        """Lignes (type, texte, retrait, écart avant, hauteur) puis pages."""
        lines = []
        for kind, text in self._blocks():
            font, _color, lh = self.styles[kind]
            indent = BULLET_INDENT if kind in ("li", "quote") else 0
            gap = PARA_GAP if kind != "meta" else 2
            if kind == "h":
                gap += 8
            wrapped = wrap_text(text, font, TEXT_RECT.w - indent, 10 ** 6)
            for j, line in enumerate(wrapped):
                lines.append((kind, line, indent, gap if j == 0 else 0, lh, j == 0))
        self._lines = lines
        self._pages = paginate([(l[3], l[4]) for l in lines], TEXT_RECT.h)
        self.page = min(self.page, len(self._pages) - 1)

    # ----------------------------------------------------------------- rendu
    def _articles(self) -> list[Article]:
        return self.feed.articles() if self.feed is not None else []

    def _signature(self):
        if self.mode == "detail":
            s = self.selected
            return ("detail", s.title if s else None, self.page, len(self._pages),
                    self._status() if s else None)
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
        pygame.draw.rect(surface, BTN, RETOUR_RECT, border_radius=8)
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

    def _draw_arrow(self, surface, rect, *, up: bool, enabled: bool, size: int = 10) -> None:
        pygame.draw.rect(surface, BTN if enabled else BTN_OFF, rect, border_radius=8)
        color = GOLD if enabled else (70, 82, 108)
        cx, cy = rect.center
        s, t = size, size * 8 // 10
        if up:
            pts = [(cx, cy - t), (cx - s, cy + t), (cx + s, cy + t)]
        else:
            pts = [(cx, cy + t), (cx - s, cy - t), (cx + s, cy - t)]
        pygame.draw.polygon(surface, color, pts)

    def _draw_detail(self, surface: pygame.Surface) -> None:
        if self.selected is None:
            return
        start = self._pages[self.page]
        end = self._pages[self.page + 1] if self.page + 1 < len(self._pages) else len(self._lines)
        y = TEXT_RECT.y
        for i in range(start, end):
            kind, text, indent, gap, lh, first = self._lines[i]
            if i != start:
                y += gap
            font, color, _ = self.styles[kind]
            x = TEXT_RECT.x + indent
            surf = font.render(text, True, color)
            # Centre vertical du texte dans son interligne.
            ty = y + (lh - surf.get_height()) // 2
            surface.blit(surf, (x, ty))
            if first and kind == "li":
                pygame.draw.circle(surface, GOLD, (TEXT_RECT.x + 7, y + lh // 2), 4)
            if kind == "quote":
                pygame.draw.line(surface, GOLD, (TEXT_RECT.x + 6, y + 3),
                                 (TEXT_RECT.x + 6, y + lh - 3), 3)
            y += lh

        # Colonne de défilement : flèches pleine hauteur + « page x / n ».
        n = len(self._pages)
        self._draw_arrow(surface, PAGE_UP, up=True, enabled=self.page > 0, size=18)
        self._draw_arrow(surface, PAGE_DOWN, up=False, enabled=self.page < n - 1, size=18)
        label = self.font_page.render(f"{self.page + 1} / {n}", True, WHITE if n > 1 else DIM)
        surface.blit(label, label.get_rect(center=(PAGE_UP.centerx, PAGE_LABEL_Y - 10)))
        sub = self.font_meta.render("fin" if self.page == n - 1 else "page", True, DIM)
        surface.blit(sub, sub.get_rect(center=(PAGE_UP.centerx, PAGE_LABEL_Y + 14)))
