"""Mode après-partie : bilan de la dernière partie.

Données reçues (payload) :
    {"win": true, "championId": 222, "championName": "Jinx",
     "kda": [9, 15, 34], "cs": 58, "gold": 17936, "damage": 41476,
     "level": 18, "duration": 1202, "queue": "Classé Solo/Duo"}
"""

from __future__ import annotations

import base64
import io

import pygame

from inputs import ACTION_BACK
from modes.base import Mode

RETOUR_RECT = pygame.Rect(700, 8, 92, 40)
ICON = 72

GREEN = (110, 210, 130)
RED = (225, 95, 95)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
GOLD = (210, 175, 95)


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class PostGameMode(Mode):
    name = "postgame"
    background_name = "lol.png"
    bg_color = (8, 12, 24)

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 90)
        self.font_champ = pygame.font.Font(None, 40)
        self.font_kda = pygame.font.Font(None, 72)
        self.font_label = pygame.font.Font(None, 26)
        self.font_value = pygame.font.Font(None, 46)
        self.font_hint = pygame.font.Font(None, 22)
        self.font_sub = pygame.font.Font(None, 28)

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
            self._last_signature = None

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        return None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = (tuple(sorted((k, str(v)) for k, v in self.data.items()
                                  if k != "championName")),
                     tuple(self._icon_cache.keys()))
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.blit(self.bg, (0, 0))
        hint = self.font_hint.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        if not self.data:
            msg = self.font_champ.render("En attente du bilan…", True, GREY)
            surface.blit(msg, msg.get_rect(center=(self.width // 2, self.height // 2)))
            return [pygame.Rect(0, 0, self.width, self.height)]

        win = self.data.get("win")
        title = self.font_title.render("VICTOIRE" if win else "DÉFAITE", True,
                                       GREEN if win else RED)
        surface.blit(title, title.get_rect(center=(self.width // 2, 66)))

        # Champion : icône + nom + file + durée.
        icon = self._get_icon()
        icon_rect = pygame.Rect(self.width // 2 - 175, 120, ICON, ICON)
        surface.blit(icon, icon_rect)
        champ = self.font_champ.render(self.data.get("championName") or "", True, WHITE)
        surface.blit(champ, (icon_rect.right + 16, 128))
        sub = self.font_sub.render(
            f"{self.data.get('queue', '')}  •  {_mmss(self.data.get('duration', 0))}  "
            f"•  Niv {self.data.get('level', 0)}", True, GREY)
        surface.blit(sub, (icon_rect.right + 16, 168))

        # KDA au centre.
        k, d, a = (self.data.get("kda") or [0, 0, 0])[:3]
        kda = self.font_kda.render(f"{k} / {d} / {a}", True, GOLD)
        surface.blit(kda, kda.get_rect(center=(self.width // 2, 255)))
        lbl = self.font_label.render("KDA", True, GREY)
        surface.blit(lbl, lbl.get_rect(center=(self.width // 2, 300)))

        # Trois stats en bas.
        cells = [
            ("CS", str(self.data.get("cs", 0))),
            ("Or", f"{self.data.get('gold', 0)}"),
            ("Dégâts", f"{self.data.get('damage', 0)}"),
        ]
        for i, (label, value) in enumerate(cells):
            cx = self.width * (i + 1) // 4
            v = self.font_value.render(value, True, WHITE)
            surface.blit(v, v.get_rect(center=(cx, 380)))
            l = self.font_label.render(label, True, GREY)
            surface.blit(l, l.get_rect(center=(cx, 420)))

        return [pygame.Rect(0, 0, self.width, self.height)]

    # ----------------------------------------------------------- icône
    def _get_icon(self) -> pygame.Surface:
        champ_id = self.data.get("championId") or 0
        if champ_id in self._icon_cache:
            return self._icon_cache[champ_id]
        if champ_id > 0 and champ_id not in self._requested:
            self._requested.add(champ_id)
            self.app.request_icon(champ_id)
        return self._placeholder(self.data.get("championName") or "?")

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
        label = self.font_champ.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface
