"""Mode League of Legends : scoreboard en direct de la partie en cours.

Données reçues (payload), produites par l'agent depuis la Live Client Data API :
    {"game_time": 930, "scores": {"order": 12, "chaos": 9},
     "players": [{"name","champion","championId","position","team",
                  "k","d","a","cs","level","isDead","respawn","isSelf"}, ...],
     "events": ["maxoulefou a tué Greed", ...],  # plus récents d'abord
     "self": {"gold": 8450}}

Affiche les deux équipes (5 v 5), les timers de mort, et un bandeau des
derniers événements. Icônes de champions réclamées à l'agent à la demande.
"""

from __future__ import annotations

import base64
import io

import pygame

from inputs import ACTION_BACK
from modes.base import Mode

RETOUR_RECT = pygame.Rect(742, 4, 54, 30)
ICON = 36
ROW_H = 66
ROWS_TOP = 62
COL_LEFT = pygame.Rect(6, ROWS_TOP, 388, 5 * ROW_H)
COL_RIGHT = pygame.Rect(406, ROWS_TOP, 388, 5 * ROW_H)
BANNER = pygame.Rect(6, 396, 788, 76)

BLUE = (90, 150, 230)
RED = (225, 110, 110)
WHITE = (238, 238, 243)
GREY = (150, 168, 198)
GOLD = (210, 175, 95)


def format_game_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class LolMode(Mode):
    name = "lol"
    background_name = "lol.png"
    bg_color = (8, 12, 24)

    def __init__(self, app):
        super().__init__(app)
        self.font_time = pygame.font.Font(None, 46)
        self.font_label = pygame.font.Font(None, 28)
        self.font_name = pygame.font.Font(None, 26)
        self.font_stat = pygame.font.Font(None, 24)
        self.font_hint = pygame.font.Font(None, 22)
        self.font_event = pygame.font.Font(None, 26)

        self.data: dict = {}
        self._icon_cache: dict[int, pygame.Surface] = {}
        self._requested: set[int] = set()
        self._last_signature = None

    def enter(self) -> None:
        self._last_signature = None
        self._requested.clear()

    def update_data(self, payload: dict) -> None:
        self.data = payload or {}

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        surface = self._decode_icon(icon_b64)
        if surface is not None:
            self._icon_cache[champion_id] = surface
            self._last_signature = None  # force un redraw

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        return None

    # ----------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = self._signature()
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.blit(self.bg, (0, 0))
        self._draw_header(surface)

        players = self.data.get("players", [])
        order = [p for p in players if p.get("team") == "ORDER"][:5]
        chaos = [p for p in players if p.get("team") == "CHAOS"][:5]
        for i, p in enumerate(order):
            self._draw_row(surface, p, COL_LEFT.x, ROWS_TOP + i * ROW_H)
        for i, p in enumerate(chaos):
            self._draw_row(surface, p, COL_RIGHT.x, ROWS_TOP + i * ROW_H)

        self._draw_banner(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_header(self, surface: pygame.Surface) -> None:
        scores = self.data.get("scores", {})
        time_str = format_game_time(self.data.get("game_time", 0))

        t = self.font_time.render(time_str, True, WHITE)
        surface.blit(t, t.get_rect(center=(self.width // 2, 24)))

        o = self.font_label.render(f"ORDER  {scores.get('order', 0)}", True, BLUE)
        surface.blit(o, o.get_rect(midright=(self.width // 2 - 70, 24)))
        c = self.font_label.render(f"{scores.get('chaos', 0)}  CHAOS", True, RED)
        surface.blit(c, c.get_rect(midleft=(self.width // 2 + 70, 24)))

        hint = self.font_hint.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

    def _draw_row(self, surface: pygame.Surface, player: dict, x: int, y: int) -> None:
        row = pygame.Rect(x, y + 2, 388, ROW_H - 6)
        if player.get("isSelf"):
            pygame.draw.rect(surface, (30, 44, 70), row, border_radius=6)
            pygame.draw.rect(surface, GOLD, row, width=1, border_radius=6)

        icon = self._get_icon(player)
        icon_rect = pygame.Rect(row.x + 5, row.y + (row.h - ICON) // 2, ICON, ICON)
        surface.blit(icon, icon_rect)
        if player.get("isDead"):
            # Voile sombre sur l'icône quand le joueur est mort.
            shade = pygame.Surface((ICON, ICON), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 150))
            surface.blit(shade, icon_rect)

        tx = icon_rect.right + 10
        name = (player.get("name") or "")[:10]
        name_surf = self.font_name.render(name, True, WHITE)
        surface.blit(name_surf, (tx, row.y + 6))
        lvl = self.font_stat.render(f"Niv {player.get('level', 0)}", True, GREY)
        surface.blit(lvl, lvl.get_rect(topright=(row.right - 8, row.y + 7)))

        if player.get("isDead"):
            line2 = self.font_stat.render(f"Mort {player.get('respawn', 0)}s", True, RED)
        else:
            k, d, a = player.get("k", 0), player.get("d", 0), player.get("a", 0)
            line2 = self.font_stat.render(
                f"{k}/{d}/{a}    {player.get('cs', 0)} CS", True, GREY)
        surface.blit(line2, (tx, row.y + 34))

    def _draw_banner(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, (16, 22, 38), BANNER, border_radius=8)
        pygame.draw.rect(surface, GOLD, BANNER, width=1, border_radius=8)
        events = self.data.get("events", [])
        gold = self.data.get("self", {}).get("gold")
        title = self.font_hint.render("ÉVÉNEMENTS", True, GOLD)
        surface.blit(title, (BANNER.x + 12, BANNER.y + 6))
        if gold is not None:
            g = self.font_hint.render(f"Or : {gold}", True, GREY)
            surface.blit(g, g.get_rect(topright=(BANNER.right - 12, BANNER.y + 6)))
        y = BANNER.y + 30
        for ev in events[:2]:
            e = self.font_event.render(ev[:70], True, WHITE)
            surface.blit(e, (BANNER.x + 12, y))
            y += 24
        if not events:
            e = self.font_event.render("—", True, GREY)
            surface.blit(e, (BANNER.x + 12, y))

    # ----------------------------------------------------------- icônes
    def _get_icon(self, player: dict) -> pygame.Surface:
        champ_id = player.get("championId") or 0
        if champ_id in self._icon_cache:
            return self._icon_cache[champ_id]
        if champ_id > 0 and champ_id not in self._requested:
            self._requested.add(champ_id)
            self.app.request_icon(champ_id)
        return self._placeholder_icon(player.get("champion") or "?")

    def _decode_icon(self, icon_b64) -> pygame.Surface | None:
        if not icon_b64:
            return None
        try:
            raw = base64.b64decode(icon_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert_alpha()
            return pygame.transform.smoothscale(image, (ICON, ICON))
        except Exception:
            return None

    def _placeholder_icon(self, champion_name: str) -> pygame.Surface:
        surface = pygame.Surface((ICON, ICON))
        surface.fill((45, 55, 80))
        initials = (champion_name[:2] if champion_name else "?").upper()
        label = self.font_stat.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface

    def _signature(self):
        players = self.data.get("players", [])
        return (
            self.data.get("game_time"),
            tuple((self.data.get("scores") or {}).items()),
            tuple((p.get("championId"), p.get("k"), p.get("d"), p.get("a"),
                   p.get("cs"), p.get("level"), p.get("isDead"), p.get("respawn"))
                  for p in players),
            (self.data.get("events") or [None])[0],
            self.data.get("self", {}).get("gold"),
            # change quand une icône arrive
            tuple(sorted(self._icon_cache.keys())),
        )
