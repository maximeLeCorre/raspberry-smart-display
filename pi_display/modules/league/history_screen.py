"""Liste des dernières parties (ouverte depuis l'accueil).

En haut : des **filtres par type de partie** (Tout / Classé / Normal / ARAM) à
gauche du bouton RETOUR. En bas : des **flèches de pagination** (◀ plus récentes
/ ▶ plus anciennes) pour remonter dans le temps. La plus récente est en haut.

Les données sont récupérées **par le Pi** via l'API Web Riot (`match-v5`), page
par page, avec le filtre courant — voir `App.request_match_history`. Un clic sur
une partie ouvre son bilan (`App.open_postgame_review`).

Données reçues (payload) : {"games": [ {gameId, championId, championName, win,
kda, cs, queue, duration, when}, ... ]} (la page courante, déjà triée récent→ancien).
"""

from __future__ import annotations

import base64
import io

import pygame

from inputs import ACTION_BACK
from screen import Screen

# Filtres : (libellé, paramètres API, source). source "web" = API Riot (le Pi),
# "lcu" = l'agent/client PC (parties spéciales que l'API Web n'indexe pas).
FILTERS = [
    ("Tout", {}, "web"),
    ("Classé", {"match_type": "ranked"}, "web"),
    # ⚠️ Riot range l'ARAM dans `type=normal` : on l'exclut pour « Normale ».
    ("Normale", {"match_type": "normal", "exclude_queue": 450}, "web"),
    ("ARAM", {"queue": 450}, "web"),
    ("ARAM Chaos", {}, "lcu"),
]
PER_PAGE = 10

RETOUR_RECT = pygame.Rect(700, 8, 92, 38)
BTN_TOP, BTN_H = 8, 38

ROW_TOP, ROW_H = 58, 36
ICON = 30

# Pagination (bas).
PREV_RECT = pygame.Rect(300, 430, 52, 36)
NEXT_RECT = pygame.Rect(448, 430, 52, 36)

GREEN = (110, 210, 130)
RED = (228, 86, 86)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
DIM = (90, 104, 132)
GOLD = (210, 175, 95)
BG = (10, 14, 26)
PANEL = (24, 32, 52)
PANEL_OFF = (18, 24, 40)


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fit(text: str, font: pygame.font.Font, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


class MatchHistoryScreen(Screen):
    name = "history"
    background_name = None
    bg_color = BG

    def __init__(self, app):
        super().__init__(app)
        self.font_btn = pygame.font.Font(None, 26)
        self.font_row = pygame.font.Font(None, 28)
        self.font_meta = pygame.font.Font(None, 24)
        self.font_hint = pygame.font.Font(None, 22)
        self.font_badge = pygame.font.Font(None, 24)

        self.games: list = []
        self.filter_idx = 0
        self.page = 0
        self.loading = False
        self.has_more = False
        self._icon_cache: dict[int, pygame.Surface] = {}
        self._requested: set[int] = set()
        self._rows: list[tuple[pygame.Rect, object]] = []
        self._last_signature = None

        # Rects des boutons de filtre (gauche → droite), calculés une fois.
        self._filter_rects: list[pygame.Rect] = []
        x = 8
        for label, _params, _src in FILTERS:
            w = self.font_btn.size(label)[0] + 22
            self._filter_rects.append(pygame.Rect(x, BTN_TOP, w, BTN_H))
            x += w + 6

    # --------------------------------------------------------------- données
    def start_fresh(self) -> None:
        """Ouverture depuis l'accueil : filtre « Tout », page 0, chargement."""
        self.filter_idx = 0
        self.page = 0
        self.games = []
        self._request()

    def _request(self) -> None:
        self.loading = True
        self._last_signature = None
        _label, params, source = FILTERS[self.filter_idx]
        if source == "lcu":
            # Parties spéciales : via l'agent/client PC (la LCU seule les a).
            if not self.app.agent_connected:
                self.loading = False
                self.games = []
                return
            self.app.request_lcu_history(start=self.page * PER_PAGE, count=PER_PAGE)
        else:
            self.app.request_match_history(start=self.page * PER_PAGE,
                                           count=PER_PAGE, **params)

    def enter(self) -> None:
        # On garde games/filtre/page (retour depuis un bilan) ; juste re-render.
        self._last_signature = None
        self._requested.clear()

    def update_data(self, payload: dict) -> None:
        self.games = (payload or {}).get("games", []) or []
        self.loading = False
        self.has_more = len(self.games) >= PER_PAGE
        self._last_signature = None

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        surface = self._decode_icon(icon_b64)
        if surface is not None:
            self._icon_cache[champion_id] = surface
            self._last_signature = None

    # --------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        for i, rect in enumerate(self._filter_rects):
            if rect.collidepoint(pos):
                if i != self.filter_idx:
                    self.filter_idx = i
                    self.page = 0
                    self._request()
                return None
        if PREV_RECT.collidepoint(pos) and self.page > 0 and not self.loading:
            self.page -= 1
            self._request()
            return None
        if NEXT_RECT.collidepoint(pos) and self.has_more and not self.loading:
            self.page += 1
            self._request()
            return None
        for rect, game_id in self._rows:
            if rect.collidepoint(pos):
                self.app.open_postgame_review(game_id)
                return None
        return None

    # ---------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = (
            self.filter_idx, self.page, self.loading, self.has_more,
            self.app.agent_connected,
            tuple((g.get("gameId"), g.get("championId"), g.get("win")) for g in self.games),
            tuple(sorted(self._icon_cache.keys())),
        )
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.fill(BG)
        self._draw_filters(surface)
        pygame.draw.rect(surface, PANEL, RETOUR_RECT, border_radius=8)
        hint = self.font_hint.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        self._rows = []
        source = FILTERS[self.filter_idx][2]
        if self.loading and not self.games:
            self._center_msg(surface, "Chargement…")
        elif not self.games:
            if source == "lcu" and not self.app.agent_connected:
                msg = "Ouvre le client League sur le PC pour les ARAM Chaos."
            elif self.page > 0:
                msg = "Fin de l'historique."
            elif source == "lcu":
                msg = "Aucune ARAM spéciale trouvée (client ouvert ?)."
            else:
                msg = "Aucune partie (vérifie le Riot ID / la clé API)."
            self._center_msg(surface, msg)
        else:
            for i, g in enumerate(self.games[:PER_PAGE]):
                self._draw_row(surface, i, g)

        self._draw_pagination(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_filters(self, surface: pygame.Surface) -> None:
        for i, rect in enumerate(self._filter_rects):
            active = i == self.filter_idx
            pygame.draw.rect(surface, PANEL if active else PANEL_OFF, rect, border_radius=8)
            if active:
                pygame.draw.rect(surface, GOLD, rect, width=2, border_radius=8)
            surf = self.font_btn.render(FILTERS[i][0], True, WHITE if active else GREY)
            surface.blit(surf, surf.get_rect(center=rect.center))

    def _center_msg(self, surface: pygame.Surface, msg: str) -> None:
        surf = self.font_row.render(msg, True, GREY)
        surface.blit(surf, surf.get_rect(center=(self.width // 2, (ROW_TOP + 418) // 2)))

    def _draw_row(self, surface: pygame.Surface, i: int, g: dict) -> None:
        top = ROW_TOP + i * ROW_H
        cy = top + ROW_H // 2
        self._rows.append((pygame.Rect(8, top + 2, self.width - 16, ROW_H - 4), g.get("gameId")))
        if i > 0:
            pygame.draw.line(surface, (34, 44, 70), (12, top), (self.width - 12, top), 1)

        surface.blit(self._get_icon(g.get("championId") or 0, g.get("championName") or "?"),
                     (12, cy - ICON // 2))
        name = _fit(g.get("championName") or "?", self.font_row, 150)
        surface.blit(self.font_row.render(name, True, WHITE),
                     (52, cy - self.font_row.get_height() // 2))

        win = g.get("win")
        chip = pygame.Rect(214, cy - 13, 30, 26)
        pygame.draw.rect(surface, (30, 60, 40) if win else (62, 30, 34), chip, border_radius=6)
        badge = self.font_badge.render("V" if win else "D", True, GREEN if win else RED)
        surface.blit(badge, badge.get_rect(center=chip.center))

        k, d, a = (g.get("kda") or [0, 0, 0])[:3]
        surface.blit(self.font_meta.render(f"{k} / {d} / {a}", True, GOLD),
                     (262, cy - self.font_meta.get_height() // 2))

        info = f"{g.get('queue', '')}  •  {_mmss(g.get('duration', 0))}"
        surface.blit(self.font_meta.render(_fit(info, self.font_meta, 320), True, GREY),
                     (388, cy - self.font_meta.get_height() // 2))

        when = self.font_meta.render(g.get("when", ""), True, GREY)
        surface.blit(when, (self.width - 14 - when.get_width(), cy - when.get_height() // 2))

    def _draw_pagination(self, surface: pygame.Surface) -> None:
        prev_on = self.page > 0 and not self.loading
        next_on = self.has_more and not self.loading
        for rect, left, on in ((PREV_RECT, True, prev_on), (NEXT_RECT, False, next_on)):
            pygame.draw.rect(surface, PANEL if on else PANEL_OFF, rect, border_radius=8)
            # Triangle dessiné (la police par défaut n'a pas les glyphes ◀/▶).
            cx, cy = rect.center
            color = WHITE if on else DIM
            if left:
                pts = [(cx + 7, cy - 9), (cx + 7, cy + 9), (cx - 8, cy)]
            else:
                pts = [(cx - 7, cy - 9), (cx - 7, cy + 9), (cx + 8, cy)]
            pygame.draw.polygon(surface, color, pts)
        page_txt = self.font_meta.render(f"Page {self.page + 1}", True, GREY)
        surface.blit(page_txt, page_txt.get_rect(center=(self.width // 2, PREV_RECT.centery)))

    # ----------------------------------------------------------- icônes
    def _get_icon(self, champ_id: int, name: str) -> pygame.Surface:
        if champ_id in self._icon_cache:
            return self._icon_cache[champ_id]
        if champ_id > 0 and champ_id not in self._requested:
            self._requested.add(champ_id)
            self.app.request_icon(champ_id)
        return self._placeholder(name)

    def _decode_icon(self, icon_b64) -> pygame.Surface | None:
        if not icon_b64:
            return None
        try:
            raw = base64.b64decode(icon_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert_alpha()
            return pygame.transform.smoothscale(image, (ICON, ICON))
        except Exception:
            return None

    def _placeholder(self, name: str) -> pygame.Surface:
        surface = pygame.Surface((ICON, ICON))
        surface.fill((45, 55, 80))
        initials = (name[:2] if name else "?").upper()
        label = self.font_meta.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface
