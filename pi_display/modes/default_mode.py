"""Mode par défaut : horloge, date, et un emplacement météo (placeholder)."""

from __future__ import annotations

import time

import pygame

from modes.base import Mode

# Noms français pour la date (localtime renvoie des indices)
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def date_francaise(t: time.struct_time) -> str:
    """Ex. 'samedi 25 octobre 2026'."""
    return f"{JOURS[t.tm_wday]} {t.tm_mday} {MOIS[t.tm_mon - 1]} {t.tm_year}"


class DefaultMode(Mode):
    name = "default"
    background_name = "default.png"
    bg_color = (15, 23, 42)

    def __init__(self, app):
        super().__init__(app)
        self.font_time = pygame.font.Font(None, 150)
        self.font_date = pygame.font.Font(None, 48)
        self.font_meteo = pygame.font.Font(None, 30)
        # Caches pour ne redessiner que lorsque la valeur change.
        self._last_time: str | None = None
        self._last_date: str | None = None
        self._meteo_drawn = False

    def enter(self) -> None:
        # On force le redessin complet des zones dynamiques à la prochaine frame
        # (le fond vient d'être reblité, donc les anciens textes sont effacés).
        self._last_time = None
        self._last_date = None
        self._meteo_drawn = False

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        dirty: list[pygame.Rect] = []
        now = time.localtime()

        # Placeholder météo : texte statique dessiné une seule fois.
        if not self._meteo_drawn:
            rect = self.draw_centered_line(
                surface, "Météo : — (à venir)", self.font_meteo,
                (120, 140, 170), y=430,
            )
            dirty.append(rect)
            self._meteo_drawn = True

        # Heure : mise à jour à la seconde.
        time_str = time.strftime("%H:%M:%S", now)
        if time_str != self._last_time:
            rect = self.draw_centered_line(
                surface, time_str, self.font_time, (240, 240, 245), y=200,
            )
            dirty.append(rect)
            self._last_time = time_str

        # Date : change rarement, mais même mécanisme.
        date_str = date_francaise(now)
        if date_str != self._last_date:
            rect = self.draw_centered_line(
                surface, date_str, self.font_date, (150, 170, 205), y=310,
            )
            dirty.append(rect)
            self._last_date = date_str

        return dirty
