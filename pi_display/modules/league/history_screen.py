"""Liste des dernières parties (ouverte depuis l'accueil).

Un clic sur une partie ouvre son bilan détaillé (écran `postgame`) en mode
« revue » via `App.open_postgame_review`.

Dessiné **entièrement en code** (pas de PNG). Les données viennent de l'agent
(LCU) sur demande : `App.request_match_history()` → message `match_history`.

Données reçues (payload) :
    {"games": [
        {"gameId": 123, "championId": 103, "championName": "Ahri",
         "win": true, "kda": [12, 4, 9], "cs": 210,
         "queue": "Classé Solo/Duo", "duration": 1830, "when": "25/10 14:30"},
        ... (jusqu'à ~10)
    ]}
"""

from __future__ import annotations

import base64
import io

import pygame

from inputs import ACTION_BACK
from screen import Screen

RETOUR_RECT = pygame.Rect(700, 8, 92, 38)
TITLE_POS = (16, 12)

ROW_TOP, ROW_H = 60, 37
ICON = 32

GREEN = (110, 210, 130)
RED = (228, 86, 86)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
GOLD = (210, 175, 95)
BG = (10, 14, 26)
PANEL = (24, 32, 52)


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
        self.font_title = pygame.font.Font(None, 40)
        self.font_row = pygame.font.Font(None, 28)
        self.font_meta = pygame.font.Font(None, 24)
        self.font_hint = pygame.font.Font(None, 22)
        self.font_badge = pygame.font.Font(None, 24)

        self.games: list = []
        self._icon_cache: dict[int, pygame.Surface] = {}
        self._requested: set[int] = set()
        self._rows: list[tuple[pygame.Rect, object]] = []    # (rect, gameId)
        self._last_signature = None

    def enter(self) -> None:
        self._last_signature = None
        self._requested.clear()

    def update_data(self, payload: dict) -> None:
        self.games = (payload or {}).get("games", []) or []
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
        for rect, game_id in self._rows:
            if rect.collidepoint(pos):
                self.app.open_postgame_review(game_id)
                return None
        return None

    # ---------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = (
            tuple((g.get("gameId"), g.get("championId"), g.get("win"))
                  for g in self.games),
            self.app.agent_connected,
            tuple(sorted(self._icon_cache.keys())),
        )
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.fill(BG)
        surface.blit(self.font_title.render("Dernières parties", True, WHITE), TITLE_POS)
        pygame.draw.rect(surface, PANEL, RETOUR_RECT, border_radius=8)
        hint = self.font_hint.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        self._rows = []
        if not self.games:
            if not self.app.agent_connected:
                msg = "PC non connecté — lance l'agent (pc_agent/main.py)."
            else:
                msg = "Aucune partie trouvée (clé API Riot + Riot ID, ou client League ouvert)."
            surf = self.font_row.render(msg, True, GREY)
            surface.blit(surf, surf.get_rect(center=(self.width // 2, self.height // 2)))
            return [pygame.Rect(0, 0, self.width, self.height)]

        max_rows = (self.height - ROW_TOP) // ROW_H
        for i, g in enumerate(self.games[:max_rows]):
            self._draw_row(surface, i, g)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_row(self, surface: pygame.Surface, i: int, g: dict) -> None:
        top = ROW_TOP + i * ROW_H
        cy = top + ROW_H // 2
        row_rect = pygame.Rect(8, top + 2, self.width - 16, ROW_H - 4)
        self._rows.append((row_rect, g.get("gameId")))

        if i > 0:
            pygame.draw.line(surface, (34, 44, 70), (12, top), (self.width - 12, top), 1)

        # Icône + nom du champion.
        surface.blit(self._get_icon(g.get("championId") or 0, g.get("championName") or "?"),
                     (12, cy - ICON // 2))
        name = _fit(g.get("championName") or "?", self.font_row, 150)
        surface.blit(self.font_row.render(name, True, WHITE),
                     (54, cy - self.font_row.get_height() // 2))

        # Chip résultat V / D.
        win = g.get("win")
        chip = pygame.Rect(214, cy - 13, 30, 26)
        pygame.draw.rect(surface, (30, 60, 40) if win else (62, 30, 34), chip, border_radius=6)
        badge = self.font_badge.render("V" if win else "D", True, GREEN if win else RED)
        surface.blit(badge, badge.get_rect(center=chip.center))

        # KDA.
        k, d, a = (g.get("kda") or [0, 0, 0])[:3]
        surface.blit(self.font_meta.render(f"{k} / {d} / {a}", True, GOLD),
                     (262, cy - self.font_meta.get_height() // 2))

        # File + durée.
        info = f"{g.get('queue', '')}  •  {_mmss(g.get('duration', 0))}"
        surface.blit(self.font_meta.render(_fit(info, self.font_meta, 320), True, GREY),
                     (388, cy - self.font_meta.get_height() // 2))

        # Date, alignée à droite.
        when = self.font_meta.render(g.get("when", ""), True, GREY)
        surface.blit(when, (self.width - 14 - when.get_width(),
                            cy - when.get_height() // 2))

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
