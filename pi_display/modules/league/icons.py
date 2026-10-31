"""Cache des icônes de champion d'un écran League (championId -> surface).

Icône = carré classique, comme en jeu (cf. `riot_web.icon_bytes`). Demandée au
module (`request_icon`, en tâche de fond) une seule fois par champion, puis
livrée par l'écran via `put` (`set_champion_icon`). En attendant, `get` renvoie
None (placeholder à l'écran).
"""

from __future__ import annotations

import base64
import io

import pygame


class ChampionIcons:
    def __init__(self, league, size: int):
        self.league = league
        self.size = size
        self._cache: dict[int, pygame.Surface] = {}
        self._requested: set[int] = set()

    def get(self, champion_id) -> pygame.Surface | None:
        cid = int(champion_id or 0)
        if cid in self._cache:
            return self._cache[cid]
        if cid > 0 and cid not in self._requested:
            self._requested.add(cid)
            self.league.request_icon(cid)
        return None

    def put(self, champion_id: int, icon_b64: str | None) -> bool:
        """Mémorise une image reçue ; True si elle est exploitable (redessiner)."""
        if not icon_b64:
            return False
        try:
            raw = base64.b64decode(icon_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert_alpha()
        except Exception:
            return False
        self._cache[champion_id] = pygame.transform.smoothscale(image, (self.size, self.size))
        return True

    def forget_requests(self) -> None:
        """Nouvelle visite : on pourra redemander les images encore manquantes."""
        self._requested.clear()

    def signature(self) -> tuple:
        return tuple(sorted(self._cache))
