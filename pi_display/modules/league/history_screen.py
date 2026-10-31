"""Liste des parties, lue depuis le **store local** du Pi (SQLite).

Toutes les parties viennent de la LCU (via l'agent) et sont stockées sur le Pi ;
cet écran lit la base → **consultable PC éteint**, instantané. À l'ouverture, si
le PC est connecté, on déclenche une **synchro** (reprise : récupère ce qui
manque depuis la dernière partie stockée). Filtres par type (requêtes SQL),
pagination locale, le plus récent en haut.

En haut : filtres, bouton STATS (comparaison avec l'ami, `[lol] compare`) et
RETOUR (« ARAM Chaos » par défaut). En bas : flèches ◀/▶.
"""

from __future__ import annotations


import pygame

from inputs import ACTION_BACK
from modules.league.icons import ChampionIcons
from screen import Screen

# Filtres : (libellé, clause WHERE SQL sur le store, params).
FILTERS = [
    ("ARAM Chaos", "game_mode = ?", ("KIWI",)),
    ("Classé", "queue_id IN (420, 440)", ()),
    ("Normale", "queue_id IN (400, 430, 490)", ()),
    ("ARAM", "queue_id = ?", (450,)),
]
PER_PAGE = 10

RETOUR_RECT = pygame.Rect(700, 8, 92, 38)
STATS_RECT = pygame.Rect(598, 8, 94, 38)
BTN_TOP, BTN_H = 8, 38

ROW_TOP, ROW_H = 58, 36
ICON = 30

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
        self.league = app.modules["league"]
        self.font_btn = pygame.font.Font(None, 26)
        self.font_row = pygame.font.Font(None, 28)
        self.font_meta = pygame.font.Font(None, 24)
        self.font_hint = pygame.font.Font(None, 22)
        self.font_badge = pygame.font.Font(None, 24)

        self.games: list = []
        self.filter_idx = 0
        self.page = 0
        self.syncing = False
        self.has_more = False
        self.icons = ChampionIcons(self.league, ICON)
        self._rows: list[tuple[pygame.Rect, object]] = []
        self._last_signature = None

        self._filter_rects: list[pygame.Rect] = []
        x = 8
        for label, _w, _p in FILTERS:
            w = self.font_btn.size(label)[0] + 22
            self._filter_rects.append(pygame.Rect(x, BTN_TOP, w, BTN_H))
            x += w + 6

    # --------------------------------------------------------------- données
    def start_fresh(self) -> None:
        """Ouverture : filtre par défaut, page 0, lecture store + synchro."""
        self.filter_idx = 0
        self.page = 0
        self.syncing = self.app.agent_connected
        self._reload_page()
        self.league.sync_lcu()          # reprise (sans effet si PC déconnecté)

    def reload(self) -> None:
        """Re-lecture du store (après une synchro)."""
        self.syncing = False
        self._reload_page()

    def _reload_page(self) -> None:
        where, params = FILTERS[self.filter_idx][1], FILTERS[self.filter_idx][2]
        rows = self.league.store.query(where, params, PER_PAGE + 1, self.page * PER_PAGE)
        self.has_more = len(rows) > PER_PAGE
        self.games = rows[:PER_PAGE]
        self._last_signature = None

    def enter(self) -> None:
        self._last_signature = None
        self.icons.forget_requests()

    def set_champion_icon(self, champion_id: int, skin: int, icon_b64: str | None) -> None:
        if self.icons.put(champion_id, skin, icon_b64):
            self._last_signature = None

    # --------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        if STATS_RECT.collidepoint(pos) and "stats" in self.app.screens:
            self.league.open_stats()
            return None
        for i, rect in enumerate(self._filter_rects):
            if rect.collidepoint(pos):
                if i != self.filter_idx:
                    self.filter_idx = i
                    self.page = 0
                    self._reload_page()
                return None
        if PREV_RECT.collidepoint(pos) and self.page > 0:
            self.page -= 1
            self._reload_page()
            return None
        if NEXT_RECT.collidepoint(pos) and self.has_more:
            self.page += 1
            self._reload_page()
            return None
        for rect, game_id in self._rows:
            if rect.collidepoint(pos):
                self.league.open_postgame_review(game_id)
                return None
        return None

    # ---------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = (
            self.filter_idx, self.page, self.syncing, self.has_more,
            tuple((g.get("gameId"), g.get("championId"), g.get("win")) for g in self.games),
            self.icons.signature(),
        )
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.fill(BG)
        self._draw_filters(surface)
        pygame.draw.rect(surface, PANEL, RETOUR_RECT, border_radius=8)
        hint = self.font_hint.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))
        if "stats" in self.app.screens:
            pygame.draw.rect(surface, PANEL, STATS_RECT, border_radius=8)
            pygame.draw.rect(surface, GOLD, STATS_RECT, width=1, border_radius=8)
            label = self.font_hint.render("STATS", True, GOLD)
            surface.blit(label, label.get_rect(center=STATS_RECT.center))

        self._rows = []
        if not self.games:
            if self.syncing:
                msg = "Synchronisation…"
            elif self.league.store.total() == 0:
                msg = "Aucune partie stockée — connecte le PC pour synchroniser."
            elif self.page > 0:
                msg = "Fin de l'historique."
            else:
                msg = "Aucune partie pour ce filtre."
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

        surface.blit(self._get_icon(g.get("championId") or 0, g.get("championName") or "?",
                                    g.get("skinId") or 0),
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
        prev_on = self.page > 0
        next_on = self.has_more
        for rect, left, on in ((PREV_RECT, True, prev_on), (NEXT_RECT, False, next_on)):
            pygame.draw.rect(surface, PANEL if on else PANEL_OFF, rect, border_radius=8)
            cx, cy = rect.center
            color = WHITE if on else DIM
            pts = ([(cx + 7, cy - 9), (cx + 7, cy + 9), (cx - 8, cy)] if left
                   else [(cx - 7, cy - 9), (cx - 7, cy + 9), (cx + 8, cy)])
            pygame.draw.polygon(surface, color, pts)
        page_txt = self.font_meta.render(f"Page {self.page + 1}", True, GREY)
        surface.blit(page_txt, page_txt.get_rect(center=(self.width // 2, PREV_RECT.centery)))

    # ----------------------------------------------------------- icônes
    def _get_icon(self, champ_id: int, name: str, skin: int = 0) -> pygame.Surface:
        return self.icons.get(champ_id, skin) or self._placeholder(name)

    def _placeholder(self, name: str) -> pygame.Surface:
        surface = pygame.Surface((ICON, ICON))
        surface.fill((45, 55, 80))
        initials = (name[:2] if name else "?").upper()
        label = self.font_meta.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface
