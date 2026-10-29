"""Écran par défaut (module système) : horloge, météo, une actu, dock de tuiles.

Disposition (cadres dans le fond default.png, cf. tools/gen_default_bg.py) :
  - pastille d'état du PC (haut gauche, sur l'illustration) ;
  - panneau horloge/date (haut droite) + météo locale (+ alerte si le Pi
    dépasse un seuil CPU/RAM/disque/température) ;
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

from screen import ASSETS_DIR, Screen

from modules.transit.transit_screen import (LINE_COLORS, arrival_label, minutes_label,
                                            next_arrival)

from .news_screen import wrap_text
from .rss_feed import get_feed
from .pi_health import get_pi_health
from .weather import get_weather

# Panneau horloge (axe central) — CLOCK_PANEL de gen_default_bg.py.
CENTER_X = 516
# Avec le module Trains, l'horloge se décale à gauche pour laisser à sa droite le
# prochain train pour Paris (« rentre en gare dans 5 min ») ; le groupe reste centré.
CLOCK_X_WITH_TRAIN = 448
TRAIN_BOX = pygame.Rect(604, 50, 168, 96)
CLOCK_Y = 96
DATE_Y = 170
WEATHER_Y = 214
WEATHER_BAND = pygame.Rect(256, WEATHER_Y - 18, 520, 36)   # zone cliquable → écran Météo
STATUS_Y = 256               # ligne d'alerte santé du Pi (vide si tout va bien)
# Pastille « PC connecté » : en haut à gauche, sur l'illustration (hors panneaux).
PC_STATUS_ZONE = pygame.Rect(6, 6, 200, 36)
WEATHER_ICON = 30            # côté de l'icône météo (px)

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
TILE_WEIGHTS = {"play": PRIMARY_WEIGHT, "trains": 1.2}   # Trains : « Versailles 12 min »
TILE_SUB_LINES = 3           # lignes max du sous-titre d'une tuile

# Libellés de la tuile Jouer quand l'agent propose un écran à rejoindre.
JOIN_LABELS = {
    "lol": "Partie en cours",
    "champselect": "Sélection en cours",
    "queue": "File d'attente",
    "postgame": "Dernière performance",
}

PANEL_FILL = (11, 17, 32)    # = FILL de gen_default_bg.py
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
SUN = (245, 196, 80)
CLOUD = (196, 206, 224)
RAIN = (110, 170, 240)

# Police de la date : la police par défaut de pygame (freesansbold) dessine le
# « 9 » et le « 7 » 1 px plus bas que les autres chiffres ; DejaVu est alignée.
DATE_FONT = ASSETS_DIR / "fonts" / "DejaVuSans-Bold.ttf"

# Libellés des alertes de santé du Pi (cf. pi_health.py).
PI_ALERT_FMT = {"cpu": "CPU {} %", "ram": "RAM {} %", "disk": "Disque {} %",
                "temp": "{} °C"}

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


def weather_icon(kind: str, is_day: bool, size: int) -> pygame.Surface:
    """Petite icône météo dessinée au code (les polices n'ont pas d'emoji).
    Le libellé écrit à côté porte l'info : l'icône n'est qu'un repère."""
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    u = size / 30  # dessin pensé sur une grille 30×30

    def p(x, y):
        return round(x * u), round(y * u)

    def r(v):
        return max(1, round(v * u))

    def sun(cx, cy, rad):
        for i in range(8):
            v = pygame.math.Vector2(1, 0).rotate(i * 45)
            a, b = v * (rad + 2), v * (rad + 5)
            pygame.draw.line(s, SUN, p(cx + a.x, cy + a.y), p(cx + b.x, cy + b.y), r(2))
        pygame.draw.circle(s, SUN, p(cx, cy), r(rad))

    def moon(cx, cy, rad):
        pygame.draw.circle(s, CLOUD, p(cx, cy), r(rad))
        pygame.draw.circle(s, (0, 0, 0, 0), p(cx + rad * 0.55, cy - rad * 0.35), r(rad * 0.8))

    def cloud(dy=0.0, color=CLOUD):
        pygame.draw.circle(s, color, p(11, 15 + dy), r(6))
        pygame.draw.circle(s, color, p(18, 12 + dy), r(8))
        pygame.draw.circle(s, color, p(24, 17 + dy), r(5))
        pygame.draw.rect(s, color, (*p(6, 16 + dy), r(19), r(6)), border_radius=r(3))

    if kind == "clear":
        (sun if is_day else moon)(15, 15, 7 if is_day else 9)
    elif kind == "partly":
        (sun if is_day else moon)(10, 10, 5 if is_day else 6)
        cloud(dy=4)
    elif kind == "fog":
        for y in (9, 15, 21):
            pygame.draw.line(s, CLOUD, p(4, y), p(26, y), r(3))
    elif kind in ("rain", "snow", "storm"):
        cloud(dy=-4)
        if kind == "rain":
            for x in (10, 16, 22):
                pygame.draw.line(s, RAIN, p(x, 21), p(x - 2, 28), r(2))
        elif kind == "snow":
            for x in (10, 16, 22):
                pygame.draw.circle(s, WHITE, p(x, 24), r(2))
        else:
            pygame.draw.polygon(s, SUN, [p(17, 18), p(12, 25), p(16, 25), p(13, 30),
                                         p(20, 22), p(16, 22), p(19, 18)])
    else:  # cloudy
        cloud()
    return s


class DefaultScreen(Screen):
    name = "default"
    background_name = "default.png"
    bg_color = (15, 23, 42)
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        self.font_time = pygame.font.Font(None, 150)
        self.font_date = (pygame.font.Font(str(DATE_FONT), 28) if DATE_FONT.exists()
                          else pygame.font.Font(None, 42))
        self.font_status = pygame.font.Font(None, 24)
        self.font_weather_temp = pygame.font.Font(None, 38)
        self.font_weather = pygame.font.Font(None, 28)
        self.font_news_tag = pygame.font.Font(None, 20)
        self.font_news = pygame.font.Font(None, 26)
        self.font_tile = pygame.font.Font(None, 30)
        self.font_tile_sub = pygame.font.Font(None, 22)

        self.feed = get_feed(app)
        self.weather = get_weather(app)
        self.health = get_pi_health(app)
        # Prochain train pour Paris à côté de l'horloge (module Trains actif + clé).
        tcfg = app.config.get("transit", {})
        self._train_dest = str(tcfg.get("home_destination", "saint-lazare"))
        self._train_label = str(tcfg.get("home_label", "St-Lazare"))
        self._train_line = str(tcfg.get("home_line", "L"))
        self._train_feed = None       # résolu à l'entrée (écran transit construit après)
        self.font_train = (pygame.font.Font(str(DATE_FONT), 30) if DATE_FONT.exists()
                           else pygame.font.Font(None, 44))
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
        self._alert_key = None
        self._train_key = None
        self._weather_key = ()           # () = jamais dessiné (None = pas de relevé)
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
        # Trains (s'il est actif) prend la place d'Actus : la liste des actus
        # reste accessible via le bandeau France Info (détail → RETOUR → liste).
        if "transit" in screens:
            ids.append("trains")
        elif "news" in screens:
            ids.append("news")
        if not ids:
            return []
        weights = [TILE_WEIGHTS.get(t, 1.0) for t in ids]
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
        self._train_feed = getattr(self.app.screens.get("transit"), "feed", None)
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
            if self._train_feed is not None:
                dirty.append(self._line(surface, time_str, self.font_time, WHITE, CLOCK_Y,
                                        cx=CLOCK_X_WITH_TRAIN, right=TRAIN_BOX.x - 6))
            else:
                dirty.append(self._line(surface, time_str, self.font_time, WHITE, CLOCK_Y))
            self._last_time = time_str
        if self._train_feed is not None:
            train = self._train_state()
            if train != self._train_key:
                dirty.append(self._draw_train(surface, train))
                self._train_key = train

        date_str = date_francaise(now)
        if date_str != self._last_date:
            dirty.append(self._line(surface, date_str, self.font_date, DIM, DATE_Y))
            self._last_date = date_str

        if self.weather is not None:
            w = self.weather.current()
            if w != self._weather_key:
                dirty.append(self._draw_weather(surface, w))
                self._weather_key = w

        connected = self.app.agent_connected
        alerts = tuple((k, round(v)) for k, v in self.health.alerts()) if self.health else ()
        if connected != self._status_key:
            dirty.append(self._draw_pc_status(surface, connected))
            self._status_key = connected
        if alerts != self._alert_key:
            dirty.append(self._draw_alert(surface, alerts))
            self._alert_key = alerts

        dirty.extend(self._draw_news_if_changed(surface))

        for tid, rect in self._tiles:
            state = self._tile_state(tid)
            if state != self._tile_keys.get(tid):
                self._draw_tile(surface, rect, *state)
                self._tile_keys[tid] = state
                dirty.append(rect)
        return dirty

    def _line(self, surface, text, font, color, y, *, cx=CENTER_X, right=776) -> pygame.Rect:
        """Ligne centrée sur ``cx`` dans le panneau horloge (efface sa bande, jusqu'à
        ``right`` : le bloc train à droite de l'horloge n'est pas effacé)."""
        rendered = font.render(text, True, color)
        rect = rendered.get_rect(center=(cx, y))
        band = pygame.Rect(256, rect.top - 4, right - 256, rect.height + 8)
        self.clear_region(surface, band)
        surface.blit(rendered, rect)
        return band

    # --------------------------------------------------- prochain train (horloge)
    def _train_state(self) -> tuple:
        """(temps, détail, couleur du détail) du prochain train pour Paris."""
        snap = self._train_feed.snapshot()
        if not snap["updated"]:
            return ("—", "indisponible" if snap["error"] else "chargement…", FAINT)
        now = time.time()
        dep = next_arrival(snap["departures"], self._train_dest, now)
        if dep is None:
            return ("—", "pas de train", FAINT)
        if dep.delay_min > 0:
            return (arrival_label(dep, now), f"retard +{dep.delay_min} min", ORANGE)
        hour = time.strftime("%H:%M", time.localtime(dep.arrival or dep.when))
        return (arrival_label(dep, now), f"arrivée {hour}", DIM)

    def _draw_train(self, surface, state) -> pygame.Rect:
        """Bloc à droite de l'horloge : ligne + destination, temps avant l'entrée en
        gare, puis heure d'arrivée (ou retard, écrit)."""
        mins, detail, detail_col = state
        box = TRAIN_BOX
        self.clear_region(surface, box)
        pygame.draw.line(surface, BORDER, (box.x, box.y + 8), (box.x, box.bottom - 8), 2)
        x = box.x + 14
        bg, fg = LINE_COLORS.get(self._train_line, (BORDER, WHITE))
        badge = pygame.Rect(x, box.y + 6, 20, 20)
        pygame.draw.rect(surface, bg, badge, border_radius=4)
        letter = self.font_tile_sub.render(self._train_line, True, fg)
        surface.blit(letter, letter.get_rect(center=(badge.centerx, badge.centery + 1)))
        dest = self.font_tile_sub.render(self._train_label, True, DIM)
        surface.blit(dest, (badge.right + 7, badge.centery - dest.get_height() // 2 + 1))
        color = GREEN if mins == "à quai" else (FAINT if mins == "—" else WHITE)
        big = self.font_train.render(mins, True, color)
        surface.blit(big, (x, box.y + 32))
        small = self.font_tile_sub.render(detail, True, detail_col)
        surface.blit(small, (x, box.y + 72))
        return box

    def _draw_pc_status(self, surface, connected: bool) -> pygame.Rect:
        """Pastille d'état discrète, en haut à gauche (sur le ciel, au-dessus du
        chat) : le PC (agent) est-il joignable ?"""
        text, color = ("PC connecté", GREEN) if connected else ("PC hors ligne", FAINT)
        surf = self.font_status.render(text, True, color)
        self.clear_region(surface, PC_STATUS_ZONE)
        pill = pygame.Rect(PC_STATUS_ZONE.x + 4, PC_STATUS_ZONE.y + 4,
                           surf.get_width() + 34, 28)
        pygame.draw.rect(surface, PANEL_FILL, pill, border_radius=14)
        pygame.draw.rect(surface, BORDER, pill, width=2, border_radius=14)
        pygame.draw.circle(surface, color, (pill.x + 14, pill.centery), 5)
        surface.blit(surf, (pill.x + 25, pill.centery - surf.get_height() // 2))
        return PC_STATUS_ZONE

    def _draw_alert(self, surface, alerts) -> pygame.Rect:
        """Ligne d'alerte du panneau horloge, seulement si le Pi dépasse un seuil :
        « ⚠ Pi : CPU 95 % · 78 °C » (écrite, pas que colorée)."""
        band = pygame.Rect(256, STATUS_Y - 12, 520, 24)
        self.clear_region(surface, band)
        if not alerts:
            return band
        words = "  ·  ".join(PI_ALERT_FMT[k].format(v) for k, v in alerts)
        alert = self.font_status.render(f"Pi : {words}", True, ORANGE)
        ax = CENTER_X - (alert.get_width() + 18) // 2
        pygame.draw.polygon(surface, ORANGE, [(ax, STATUS_Y + 6), (ax + 7, STATUS_Y - 7),
                                              (ax + 14, STATUS_Y + 6)])
        pygame.draw.line(surface, PANEL_FILL, (ax + 7, STATUS_Y - 2), (ax + 7, STATUS_Y + 1), 2)
        pygame.draw.circle(surface, PANEL_FILL, (ax + 7, STATUS_Y + 4), 1)
        surface.blit(alert, (ax + 18, STATUS_Y - alert.get_height() // 2))
        return band

    def _draw_weather(self, surface, w) -> pygame.Rect:
        """Ligne météo : icône + température + libellé · min/max (· pluie)."""
        band = WEATHER_BAND
        self.clear_region(surface, band)
        city = str(self.app.config.get("weather", {}).get("city", "")).strip()
        if w is None:
            surf = self.font_weather.render(f"Météo {city}…" if city else "Météo…", True, FAINT)
            surface.blit(surf, surf.get_rect(center=(CENTER_X, WEATHER_Y)))
            return band
        # Segments (texte, police, couleur) ; les optionnels sautent si trop large.
        temp = (f"{w.temp:.0f}°", self.font_weather_temp, WHITE)
        label = (f"  {w.label}", self.font_weather, DIM)
        extras = []
        if w.t_min is not None and w.t_max is not None:
            extras.append((f"  ·  {w.t_min:.0f}° / {w.t_max:.0f}°", self.font_weather, DIM))
        if w.rain_pct is not None and w.rain_pct >= 20:
            extras.append((f"  ·  pluie {w.rain_pct} %", self.font_weather, RAIN))
        lead = [(f"{city}  ", self.font_weather, FAINT)] if city else []
        gap = 10

        def width(parts):
            return WEATHER_ICON + gap + sum(f.size(t)[0] for t, f, _ in parts)

        parts = lead + [temp, label] + extras
        while width(parts) > band.w - 8 and (extras or lead):
            if lead:
                lead, parts = [], parts[1:]      # la ville part en premier
            else:
                extras.pop()
                parts = [temp, label] + extras
        x = CENTER_X - width(parts) // 2
        surface.blit(weather_icon(w.kind, w.is_day, WEATHER_ICON),
                     (x, WEATHER_Y - WEATHER_ICON // 2))
        x += WEATHER_ICON + gap
        for text, font, color in parts:
            surf = font.render(text, True, color)
            surface.blit(surf, (x, WEATHER_Y - surf.get_height() // 2))
            x += surf.get_width()
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
        if tid == "trains":
            return self._trains_tile_state()
        if tid == "news":
            n = len(self.feed.articles()) if self.feed else 0
            return ("Actus", f"{n} articles" if n else "France Info", DIM, False, True)
        return ("", "", DIM, False, False)

    def _trains_tile_state(self) -> tuple:
        """Prochain départ dans chaque sens (« Paris 4 min ») + perturbation écrite."""
        scr = self.app.screens.get("transit")
        feed = getattr(scr, "feed", None)
        if feed is None:
            return ("Trains", "non configuré", FAINT, False, True)
        snap = feed.snapshot()
        if not snap["updated"]:
            return ("Trains", "indisponible" if snap["error"] else "chargement…",
                    RED if snap["error"] else FAINT, False, True)
        labels = list(self.app.config.get("transit", {}).get(
            "tile_labels", ["Paris", "Autre sens"]))
        now = time.time()
        lines = []
        for label, to_paris in ((labels[0], True), (labels[-1], False)):
            dep = next((d for d in snap["departures"]
                        if d.to_paris == to_paris and not d.cancelled), None)
            lines.append(f"{label} {minutes_label(dep, now)}" if dep else f"{label} —")
        if any(m.is_disruption for m in snap["messages"]):
            return ("Trains", "\n".join(lines + ["perturbation"]), ORANGE, False, True)
        return ("Trains", "\n".join(lines), DIM, False, True)

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
        # Sous-titre renvoyé à la ligne (étapes du bouton Jouer, ex. « Connexion au
        # client… (1-2 min) ») plutôt que tronqué ; « \n » force une coupure.
        lines: list[str] = []
        for part in sub.split("\n"):
            if len(lines) < TILE_SUB_LINES:
                lines +=wrap_text(part, self.font_tile_sub, max_w, TILE_SUB_LINES - len(lines))
        subs = [self.font_tile_sub.render(fit_text(line, self.font_tile_sub, max_w),
                                          True, sub_color) for line in lines]
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
        if self.weather is not None and WEATHER_BAND.collidepoint(pos):
            self.app.manual_screen = "weather"
            self.app.set_screen("weather")
            return None
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
        elif tid == "trains":
            self.app.manual_screen = "transit"
            self.app.set_screen("transit")
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
