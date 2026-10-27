"""Écran par défaut (module système) : horloge, date, 3 dernières actus.

Disposition (cadres dans le fond default.png, cf. tools/gen_default_bg.py) :
  - panneau horloge/date (haut droite) ;
  - panneau actualité : les 3 derniers titres (clic → détail sur l'écran
    France Info) ;
  - onglet « France Info » (haut gauche) : ouvre la liste complète ;
  - bandeau LoL (haut, conditionnel) : « Rejoindre » l'écran proposé par l'agent.

⚠️ Les constantes de géométrie ci-dessous doivent rester alignées avec
tools/gen_default_bg.py (qui dessine les cadres correspondants).
"""

from __future__ import annotations

import time

import pygame

from screen import Screen

from .rss_feed import get_feed

# Axe des panneaux horloge/actu (décalé à droite : illustration à gauche).
CENTER_X = 521
CLOCK_Y = 135
DATE_Y = 212

# Panneau actualité (3 lignes). Doit suivre NEWS_PANEL de gen_default_bg.py.
NEWS_HEADER_POS = (330, 299)
NEWS_ROWS_AREA = pygame.Rect(325, 324, 452, 152)   # zone effaçable des 3 lignes
NEWS_ROW_TOP = (326, 375, 424)
NEWS_ROW_H = 49
NEWS_BULLET_X = 338
NEWS_TITLE_X = 354
NEWS_TITLE_MAX = 774 - NEWS_TITLE_X

# Bouton « Dernières parties » (droite de l'en-tête ACTU ; LoL uniquement).
HISTORY_BTN = pygame.Rect(584, 291, 193, 28)

# Onglet « France Info » (haut gauche) et bandeau LoL (haut, conditionnel).
TAB_RECT = pygame.Rect(18, 12, 186, 40)
BANNER_RECT = pygame.Rect(372, 10, 416, 34)
BANNER_LABELS = {
    "lol": "LoL · partie en cours",
    "champselect": "LoL · sélection en cours",
    "queue": "LoL · file d'attente",
    "postgame": "LoL · voir la dernière performance",
}
# Bouton unique « jouer » : lance le client au besoin, crée le lobby ARAM Chaos
# et invite l'ami configuré (l'agent saute toute étape déjà faite). Pendant le
# flux, l'agent pousse un message d'étape (`playStatus`) affiché à la place du
# libellé — confirmation de la prise en compte + avancement.
PLAY_LABEL = "Jouer une ARAM Chaos"

GOLD = (210, 175, 95)
WHITE = (238, 240, 245)
DIM = (150, 165, 195)

# Noms français pour la date (localtime renvoie des indices)
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def date_francaise(t: time.struct_time) -> str:
    """Ex. 'samedi 25 octobre 2026'."""
    return f"{JOURS[t.tm_wday]} {t.tm_mday} {MOIS[t.tm_mon - 1]} {t.tm_year}"


def fit_text(text: str, font: pygame.font.Font, max_w: int) -> str:
    """Tronque avec '…' pour tenir dans max_w pixels."""
    if font.size(text)[0] <= max_w:
        return text
    ell = "…"
    while text and font.size(text + ell)[0] > max_w:
        text = text[:-1]
    return text.rstrip() + ell


class DefaultScreen(Screen):
    name = "default"
    background_name = "default.png"
    bg_color = (15, 23, 42)
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        self.font_time = pygame.font.Font(None, 124)
        self.font_date = pygame.font.Font(None, 44)
        self.font_header = pygame.font.Font(None, 22)
        self.font_title = pygame.font.Font(None, 26)
        self.font_meta = pygame.font.Font(None, 20)
        self.font_tab = pygame.font.Font(None, 26)
        self.font_banner = pygame.font.Font(None, 22)

        self.feed = get_feed(app)
        self._last_time: str | None = None
        self._last_date: str | None = None
        self._banner_key: tuple | None = None   # état actuellement dessiné
        self._banner_mode: str | None = None    # "join" / "play" / None (pour le clic)
        self._play_status = ""                   # message d'étape du flux « jouer »
        self._chrome_drawn = False
        self._news_key: tuple[str, ...] | None = None
        self._news_rows: list[tuple[pygame.Rect, object]] = []

    def _line(self, surface, text, font, color, y):
        """Ligne centrée sur CENTER_X, après effacement d'une bande pleine
        largeur (restaure le fond, illustration comprise)."""
        rendered = font.render(text, True, color)
        rect = rendered.get_rect(center=(CENTER_X, y))
        band = pygame.Rect(0, rect.top - 4, self.width, rect.height + 8)
        self.clear_region(surface, band)
        surface.blit(rendered, rect)
        return band

    def enter(self) -> None:
        self._last_time = None
        self._last_date = None
        self._banner_key = None
        self._chrome_drawn = False
        self._news_key = None
        self._news_rows = []
        self._play_status = ""

    def update_data(self, payload: dict) -> None:
        """L'agent pousse un message d'étape du flux « jouer » (vide = terminé)."""
        if "playStatus" in payload:
            self._play_status = str(payload.get("playStatus") or "")

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        dirty: list[pygame.Rect] = []
        now = time.localtime()

        # Éléments statiques (onglet + en-tête actu) : une fois par entrée.
        if not self._chrome_drawn:
            dirty.extend(self._draw_chrome(surface))
            self._chrome_drawn = True

        # 3 dernières actus : redessinées quand le flux change.
        if self.feed is not None:
            articles = self.feed.articles()[:3]
            key = tuple(a.title for a in articles)
            if key != self._news_key:
                self._news_key = key
                dirty.append(self._draw_news(surface, articles))

        # Bandeau LoL (conditionnel) : « Rejoindre » un écran proposé par l'agent,
        # sinon le bouton unique « Jouer une ARAM Chaos » si l'agent est connecté.
        joinable = self.app.joinable_screen()
        key = (joinable, self.app.agent_connected, self._play_status)
        if key != self._banner_key:
            dirty.append(self._draw_banner(surface, joinable))
            self._banner_key = key

        # Horloge et date.
        time_str = time.strftime("%H:%M:%S", now)
        if time_str != self._last_time:
            dirty.append(self._line(surface, time_str, self.font_time, WHITE, y=CLOCK_Y))
            self._last_time = time_str

        date_str = date_francaise(now)
        if date_str != self._last_date:
            dirty.append(self._line(surface, date_str, self.font_date, (150, 170, 205), y=DATE_Y))
            self._last_date = date_str

        return dirty

    # ---------------------------------------------------------------- chrome
    def _draw_chrome(self, surface: pygame.Surface) -> list[pygame.Rect]:
        tab = self.font_tab.render("France Info", True, GOLD)
        surface.blit(tab, tab.get_rect(center=TAB_RECT.center))
        header = self.font_header.render("ACTUALITÉS", True, GOLD)
        surface.blit(header, NEWS_HEADER_POS)
        dirty = [TAB_RECT, pygame.Rect(*NEWS_HEADER_POS, 200, 22)]
        # Bouton « Dernières parties » : seulement si le module League est actif.
        if "history" in self.app.screens:
            pygame.draw.rect(surface, GOLD, HISTORY_BTN, width=1, border_radius=7)
            label = self.font_banner.render("Dernières parties  »", True, GOLD)
            surface.blit(label, label.get_rect(center=HISTORY_BTN.center))
            dirty.append(HISTORY_BTN)
        return dirty

    def _draw_news(self, surface: pygame.Surface, articles: list) -> pygame.Rect:
        self.clear_region(surface, NEWS_ROWS_AREA)   # restaure fond + séparateurs
        self._news_rows = []

        if self.feed is None:
            return NEWS_ROWS_AREA
        if not articles:
            msg = self.font_title.render("Chargement des actualités…", True, DIM)
            surface.blit(msg, (NEWS_TITLE_X, NEWS_ROW_TOP[0] + 12))
            return NEWS_ROWS_AREA

        for i, top in enumerate(NEWS_ROW_TOP):
            if i >= len(articles):
                break
            art = articles[i]
            pygame.draw.circle(surface, GOLD, (NEWS_BULLET_X, top + 16), 3)
            title = fit_text(art.title, self.font_title, NEWS_TITLE_MAX)
            surface.blit(self.font_title.render(title, True, WHITE), (NEWS_TITLE_X, top + 5))
            if art.published:
                surface.blit(self.font_meta.render(art.published, True, DIM),
                             (NEWS_TITLE_X, top + 29))
            self._news_rows.append(
                (pygame.Rect(NEWS_ROWS_AREA.x, top, NEWS_ROWS_AREA.w, NEWS_ROW_H), art))
        return NEWS_ROWS_AREA

    def _draw_banner(self, surface: pygame.Surface, joinable: str | None) -> pygame.Rect:
        self.clear_region(surface, BANNER_RECT)
        # Priorité à « Rejoindre » (partie/sélection/file en cours) ; à défaut,
        # « Créer un lobby » si le client LoL est simplement ouvert au menu.
        border = GOLD
        if joinable:
            self._banner_mode = "join"
            label = BANNER_LABELS.get(joinable, "LoL") + "   »"
        elif self._play_status:
            # Flux « jouer » en cours : on affiche l'étape (bordure verte), clic
            # neutralisé (voir handle_touch).
            self._banner_mode = "play"
            label = self._play_status
            border = (120, 200, 120)
        elif self.app.agent_connected:
            self._banner_mode = "play"
            label = PLAY_LABEL + "   »"
        else:
            self._banner_mode = None
            return BANNER_RECT
        pygame.draw.rect(surface, (34, 48, 78), BANNER_RECT, border_radius=9)
        pygame.draw.rect(surface, border, BANNER_RECT, width=2, border_radius=9)
        label = fit_text(label, self.font_banner, BANNER_RECT.w - 24)
        surf = self.font_banner.render(label, True, (235, 235, 240))
        surface.blit(surf, surf.get_rect(center=BANNER_RECT.center))
        return BANNER_RECT

    # ---------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if TAB_RECT.collidepoint(pos):
            self._open_news(None)
            return None
        if "history" in self.app.screens and HISTORY_BTN.collidepoint(pos):
            self.app.open_history()
            return None
        for rect, art in self._news_rows:
            if rect.collidepoint(pos):
                self._open_news(art)
                return None
        if BANNER_RECT.collidepoint(pos):
            if self._banner_mode == "join":
                self.app.join_screen()
            elif self._banner_mode == "play" and not self._play_status:
                self.app.play()   # ignoré si un flux est déjà en cours
        return None

    def _open_news(self, article) -> None:
        news = self.app.screens.get("news")
        if news is None:
            return
        if article is None:
            news.show_list()
        else:
            news.show_detail(article)
        # Navigation manuelle : on verrouille pour que l'agent ne reprenne pas
        # la main pendant la lecture (le bouton RETOUR ramène au défaut).
        self.app.manual_screen = "news"
        self.app.set_screen("news")
