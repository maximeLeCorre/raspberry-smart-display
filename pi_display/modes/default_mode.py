"""Mode par défaut : horloge, date, et un emplacement météo (placeholder)."""

from __future__ import annotations

import time

import pygame

from modes.base import Mode

# Badge « Rejoindre » (coin bas, centré) affiché quand un mode LoL est dispo.
BADGE_RECT = pygame.Rect(250, 408, 300, 60)
BADGE_LABELS = {
    "lol": "Rejoindre la partie",
    "champselect": "Rejoindre la sélection",
}

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
        self.font_badge = pygame.font.Font(None, 30)
        # Caches pour ne redessiner que lorsque la valeur change.
        self._last_time: str | None = None
        self._last_date: str | None = None
        self._meteo_drawn = False
        self._last_joinable: str | None = None

    def enter(self) -> None:
        # On force le redessin complet des zones dynamiques à la prochaine frame
        # (le fond vient d'être reblité, donc les anciens textes sont effacés).
        self._last_time = None
        self._last_date = None
        self._meteo_drawn = False
        self._last_joinable = None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        dirty: list[pygame.Rect] = []
        now = time.localtime()

        # Placeholder météo : texte statique dessiné une seule fois.
        if not self._meteo_drawn:
            rect = self.draw_centered_line(
                surface, "Météo : — (à venir)", self.font_meteo,
                (120, 140, 170), y=372,
            )
            dirty.append(rect)
            self._meteo_drawn = True

        # Badge « Rejoindre » : apparaît/disparaît selon le mode dispo côté agent.
        joinable = self.app.joinable_mode()
        if joinable != self._last_joinable:
            dirty.append(self._draw_badge(surface, joinable))
            self._last_joinable = joinable

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

    def _draw_badge(self, surface: pygame.Surface, joinable: str | None) -> pygame.Rect:
        """Dessine (ou efface) le badge « Rejoindre ». Renvoie son rect."""
        # On efface d'abord la zone en recopiant le fond.
        self.clear_region(surface, BADGE_RECT)
        if joinable:
            pygame.draw.rect(surface, (34, 48, 78), BADGE_RECT, border_radius=10)
            pygame.draw.rect(surface, (210, 175, 95), BADGE_RECT, width=2, border_radius=10)
            text = "LoL — " + BADGE_LABELS.get(joinable, "Rejoindre")
            label = self.font_badge.render(text, True, (235, 235, 240))
            surface.blit(label, label.get_rect(center=BADGE_RECT.center))
        return BADGE_RECT

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        # Clic sur le badge -> on rejoint le mode proposé par l'agent.
        if self._last_joinable and BADGE_RECT.collidepoint(pos):
            self.app.join_network_mode()
        return None
