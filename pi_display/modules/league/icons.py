"""Cache des icônes de champion d'un écran League, par (championId, n° de skin).

Skin 0 = icône carrée classique ; skin > 0 = tuile du skin joué (cf.
`riot_web.skin_asset_url`). Les images sont demandées au module (`request_icon`,
en tâche de fond) une seule fois par clé, puis livrées via `put` par l'écran
(`set_champion_icon`). En attendant, `get` renvoie None (placeholder à l'écran).
"""

from __future__ import annotations

import base64
import io

import pygame


class ChampionIcons:
    def __init__(self, league, size: int):
        self.league = league
        self.size = size
        self._cache: dict[tuple[int, int], pygame.Surface] = {}
        self._requested: set[tuple[int, int]] = set()

    def get(self, champion_id, skin=0) -> pygame.Surface | None:
        key = (int(champion_id or 0), int(skin or 0))
        if key in self._cache:
            return self._cache[key]
        if key[0] > 0 and key not in self._requested:
            self._requested.add(key)
            self.league.request_icon(*key)
        return None

    def put(self, champion_id: int, skin: int, icon_b64: str | None) -> bool:
        """Mémorise une image reçue ; True si elle est exploitable (redessiner)."""
        if not icon_b64:
            return False
        try:
            raw = base64.b64decode(icon_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert_alpha()
        except Exception:
            return False
        self._cache[(champion_id, skin)] = pygame.transform.smoothscale(
            image, (self.size, self.size))
        return True

    def forget_requests(self) -> None:
        """Nouvelle visite : on pourra redemander les images encore manquantes."""
        self._requested.clear()

    def signature(self) -> tuple:
        return tuple(sorted(self._cache))
