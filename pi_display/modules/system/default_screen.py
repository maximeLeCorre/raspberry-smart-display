"""Écran par défaut (module système) : horloge, une actu, dock de tuiles.

Disposition (cadres dans le fond default.png, cf. tools/gen_default_bg.py) :
  - panneau horloge/date (haut droite) + ligne d'état du PC ;
  - bandeau d'actualité : UN titre qui tourne (clic → détail France Info) ;
  - dock (bas) : grosses tuiles tactiles « vivantes », selon les modules actifs :
      Jouer (LoL : « Jouer une ARAM Chaos », devient « Rejoindre » quand une
      activité est en cours, ou affiche l'étape du flux « jouer »),
      Historique (nombre de parties), Serveur (état du service + CPU),
      Actus (liste France Info).

⚠️ Les constantes de géométrie ci-dessous doivent rester alignées avec
tools/gen_default_bg.py (qui dessine les cadres correspondants).
"""

from __future__ import annotations

import time

import pygame

from screen import Screen

from .rss_feed import get_feed

# Panneau horloge (axe central) — CLOCK_PANEL de gen_default_bg.py.
CENTER_X = 516
CLOCK_Y = 112
DATE_Y = 192
STATUS_Y = 248

# Bandeau d'actualité — NEWS_STRIP de gen_default_bg.py.
NEWS_STRIP = pygame.Rect(240, 292, 552, 58)
NEWS_INNER = NEWS_STRIP.inflate(-28, -8)
NEWS_ROTATE_SECONDS = 8      # un titre toutes les N s
NEWS_ROTATE_COUNT = 5        # parmi les N plus récents

# Dock des tuiles — DOCK de gen_default_bg.py.
DOCK = pygame.Rect(240, 360, 552, 112)
TILE_GAP = 8
TILE_PAD = 8                 # marge intérieure du dock
PRIMARY_WEIGHT = 1.3         # la tuile Jouer est plus large

# Libellés de la tuile Jouer quand l'agent propose un écran à rejoindre.
JOIN_LABELS = {
    "lol": "Partie en cours",
    "champselect": "Sélection en cours",
    "queue": "File d'attente",
    "postgame": "Dernière performance",
}

BG_TILE = (22, 30, 50)
BG_PRIMARY = (40, 34, 20)
BORDER = (44, 58, 90)
GOLD = (210, 175, 95)
GREEN = (110, 210, 130)
ORANGE = (230, 170, 70)
RED = (228, 86, 86)
WHITE = (238, 240, 245)
DIM = (150, 165, 195)
FAINT = (92, 106, 134)

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
        self.font_time = pygame.font.Font(None, 150)
        self.font_date = pygame.font.Font(None, 42)
        self.font_status = pygame.font.Font(None, 24)
        self.font_news_tag = pygame.font.Font(None, 20)
        self.font_news = pygame.font.Font(None, 26)
        self.font_tile = pygame.font.Font(None, 30)
        self.font_tile_sub = pygame.font.Font(None, 22)

        self.feed = get_feed(app)
        self._play_status = ""          # message d'étape du flux « jouer »
        # Tuiles calculées à l'entrée : les écrans des autres modules ne sont
        # pas encore tous construits quand celui-ci l'est.
        self._tiles: list[tuple[str, pygame.Rect]] = []
        self._news_article = None       # article affiché dans le bandeau
        self._history_count = 0
        self._history_ts = 0.0
        self._reset_keys()

    def _reset_keys(self) -> None:
        self._last_time: str | None = None
        self._last_date: str | None = None
        self._status_key = None
        self._news_key = None
        self._tile_keys: dict[str, tuple] = {}

    def _layout_tiles(self) -> list[tuple[str, pygame.Rect]]:
        """Tuiles présentes selon les modules actifs, réparties sur le dock."""
        screens = self.app.screens
        ids = []
        if "history" in screens:          # module League
            ids += ["play", "history"]
        if "server" in screens:
            ids.append("server")
        if "news" in screens:
            ids.append("news")
        if not ids:
            return []
        weights = [PRIMARY_WEIGHT if t == "play" else 1.0 for t in ids]
        inner = DOCK.inflate(-2 * TILE_PAD, -2 * TILE_PAD)
        unit = (inner.w - TILE_GAP * (len(ids) - 1)) / sum(weights)
        tiles, x = [], float(inner.x)
        for tid, w in zip(ids, weights):
            width = unit * w
            tiles.append((tid, pygame.Rect(round(x), inner.y, round(width), inner.h)))
            x += width + TILE_GAP
        return tiles

    def enter(self) -> None:
        self._tiles = self._layout_tiles()
        self._reset_keys()
        self._play_status = ""
        self._history_ts = 0.0

    def update_data(self, payload: dict) -> None:
        """L'agent pousse un message d'étape du flux « jouer » (vide = terminé)."""
        if "playStatus" in payload:
            self._play_status = str(payload.get("playStatus") or "")

    # ------------------------------------------------------------------ rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        dirty: list[pygame.Rect] = []
        now = time.localtime()

        time_str = time.strftime("%H:%M", now)
        if time_str != self._last_time:
            dirty.append(self._line(surface, time_str, self.font_time, WHITE, CLOCK_Y))
            self._last_time = time_str

        date_str = date_francaise(now)
        if date_str != self._last_date:
            dirty.append(self._line(surface, date_str, self.font_date, DIM, DATE_Y))
            self._last_date = date_str

        connected = self.app.agent_connected
        if connected != self._status_key:
            dirty.append(self._draw_status(surface, connected))
            self._status_key = connected

        dirty.extend(self._draw_news_if_changed(surface))

        for tid, rect in self._tiles:
            state = self._tile_state(tid)
            if state != self._tile_keys.get(tid):
                self._draw_tile(surface, rect, *state)
                self._tile_keys[tid] = state
                dirty.append(rect)
        return dirty

    def _line(self, surface, text, font, color, y) -> pygame.Rect:
        """Ligne centrée dans le panneau horloge (efface sa bande de panneau)."""
        rendered = font.render(text, True, color)
        rect = rendered.get_rect(center=(CENTER_X, y))
        band = pygame.Rect(256, rect.top - 4, 520, rect.height + 8)
        self.clear_region(surface, band)
        surface.blit(rendered, rect)
        return band

    def _draw_status(self, surface, connected: bool) -> pygame.Rect:
        """Ligne d'état discrète : le PC (agent) est-il joignable ?"""
        text, color = ("PC connecté", GREEN) if connected else ("PC hors ligne", FAINT)
        surf = self.font_status.render(text, True, color)
        w = surf.get_width() + 18
        x = CENTER_X - w // 2
        band = pygame.Rect(256, STATUS_Y - 12, 520, 24)
        self.clear_region(surface, band)
        pygame.draw.circle(surface, color, (x + 5, STATUS_Y), 5)
        surface.blit(surf, (x + 18, STATUS_Y - surf.get_height() // 2))
        return band

    def _draw_news_if_changed(self, surface) -> list[pygame.Rect]:
        if self.feed is None:
            return []
        articles = self.feed.articles()[:NEWS_ROTATE_COUNT]
        art = (articles[int(time.time() // NEWS_ROTATE_SECONDS) % len(articles)]
               if articles else None)
        key = (art.title, art.published) if art else None
        if key == self._news_key and self._news_key is not None:
            return []
        self._news_key = key
        self._news_article = art
        self.clear_region(surface, NEWS_INNER)
        tag = self.font_news_tag.render("FRANCE INFO", True, GOLD)
        surface.blit(tag, (NEWS_INNER.x, NEWS_INNER.centery - tag.get_height() // 2))
        x = NEWS_INNER.x + tag.get_width() + 14
        if art is None:
            text, color = "Chargement des actualités…", FAINT
        else:
            text, color = art.title, WHITE
        meta = f"  {art.published}" if art and art.published else ""
        meta_w = self.font_news_tag.size(meta)[0] if meta else 0
        title = fit_text(text, self.font_news, NEWS_INNER.right - x - meta_w)
        t = self.font_news.render(title, True, color)
        surface.blit(t, (x, NEWS_INNER.centery - t.get_height() // 2))
        if meta:
            m = self.font_news_tag.render(meta, True, FAINT)
            surface.blit(m, (x + t.get_width(), NEWS_INNER.centery - m.get_height() // 2 + 1))
        return [NEWS_INNER]

    # ------------------------------------------------------------------ tuiles
    def _tile_state(self, tid: str) -> tuple:
        """(titre, sous-titre, couleur du sous-titre, primaire, actif).
        Le sous-titre peut tenir sur deux lignes (séparées par « \\n »)."""
        if tid == "play":
            joinable = self.app.joinable_screen()
            if joinable:
                return ("Rejoindre", JOIN_LABELS.get(joinable, "LoL"), GREEN, True, True)
            if self._play_status:
                return ("En cours…", self._play_status, GREEN, True, False)
            if self.app.agent_connected:
                return ("Jouer", "ARAM Chaos", GOLD, True, True)
            return ("Jouer", "PC hors ligne", FAINT, True, False)
        if tid == "history":
            if time.monotonic() - self._history_ts > 5:
                self._history_count = self.app.store.total()
                self._history_ts = time.monotonic()
            n = self._history_count
            return ("Historique", f"{n} partie{'s' if n > 1 else ''}", DIM, False, True)
        if tid == "server":
            return self._server_tile_state()
        if tid == "news":
            n = len(self.feed.articles()) if self.feed else 0
            return ("Actus", f"{n} articles" if n else "France Info", DIM, False, True)
        return ("", "", DIM, False, False)

    def _server_tile_state(self) -> tuple:
        srv = self.app.screens.get("server")
        link = getattr(srv, "link", None)
        service = getattr(srv, "service", None)
        if link is None:
            return ("Serveur", "non configuré", FAINT, False, True)
        snap = link.snapshot()
        if not snap.get("online"):
            return ("Serveur", "hors ligne", RED, False, True)
        if service:
            status = snap.get("services", {}).get(service["unit"], "")
            color = GREEN if status == "active" else (RED if status in ("inactive", "failed")
                                                      else ORANGE)
            word = {"active": "actif", "inactive": "arrêté", "failed": "en échec"}.get(
                status, status or "…")
            # Libellé et état sur deux lignes : l'état est écrit, pas seulement coloré.
            return ("Serveur", f"{service['label']}\n{word}", color, False, True)
        cpu = snap.get("cpu_pct")
        return ("Serveur", f"CPU {cpu:.0f} %" if cpu is not None else "en ligne",
                GREEN, False, True)

    def _draw_tile(self, surface, rect, title, sub, sub_color, primary, enabled) -> None:
        self.clear_region(surface, rect)
        fill = BG_PRIMARY if primary and enabled else BG_TILE
        border = GOLD if primary and enabled else BORDER
        pygame.draw.rect(surface, fill, rect, border_radius=14)
        pygame.draw.rect(surface, border, rect, width=2, border_radius=14)
        title_col = WHITE if enabled else FAINT
        max_w = rect.w - 12
        t = self.font_tile.render(fit_text(title, self.font_tile, max_w), True, title_col)
        subs = [self.font_tile_sub.render(fit_text(line, self.font_tile_sub, max_w),
                                          True, sub_color) for line in sub.split("\n")]
        gap = 8 if len(subs) == 1 else 5
        height = t.get_height() + gap + sum(x.get_height() for x in subs)
        y = rect.centery - height // 2
        surface.blit(t, t.get_rect(midtop=(rect.centerx, y)))
        y += t.get_height() + gap
        for line in subs:
            surface.blit(line, line.get_rect(midtop=(rect.centerx, y)))
            y += line.get_height()

    # ---------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if NEWS_STRIP.collidepoint(pos):
            self._open_news(self._news_article)
            return None
        for tid, rect in self._tiles:
            if rect.collidepoint(pos):
                self._activate(tid)
                return None
        return None

    def _activate(self, tid: str) -> None:
        if tid == "play":
            if self.app.joinable_screen():
                self.app.join_screen()
            elif not self._play_status:
                self.app.play()       # ignoré si l'agent est déconnecté
        elif tid == "history":
            self.app.open_history()
        elif tid == "server":
            self.app.manual_screen = "server"
            self.app.set_screen("server")
        elif tid == "news":
            self._open_news(None)

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
