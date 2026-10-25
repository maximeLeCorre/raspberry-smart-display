"""Mode League of Legends : affiche un résumé de la partie en cours.

Les données viennent du PC (agent) via le réseau, au format :
    {"game_time": 930, "kda": [4, 2, 7], "gold": 8450, "cs": 142,
     "level": 11, "score": {"order": 12, "chaos": 9}}

Un appui dans le coin haut-droit (zone « RETOUR ») fait sortir du mode.
"""

from __future__ import annotations

import pygame

from inputs import ACTION_BACK
from modes.base import Mode

# Zone tactile de sortie (coin haut-droit), en coordonnées internes 800x480.
RETOUR_RECT = pygame.Rect(690, 0, 110, 70)


def format_game_time(seconds: int) -> str:
    """Secondes -> 'mm:ss'."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class LolMode(Mode):
    name = "lol"
    background_name = "lol.png"
    bg_color = (8, 12, 24)

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 56)
        self.font_value = pygame.font.Font(None, 52)
        self.font_label = pygame.font.Font(None, 28)
        self.font_hint = pygame.font.Font(None, 26)
        self.data: dict = {}
        # Empreinte des dernières données affichées (évite de redessiner si rien
        # n'a changé entre deux frames).
        self._last_signature = None

    def enter(self) -> None:
        self._last_signature = None

    def update_data(self, payload: dict) -> None:
        self.data = payload or {}

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        return None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = self._signature()
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        # On efface puis redessine tout le panneau de contenu (sous le titre).
        content = pygame.Rect(0, 90, self.width, self.height - 90)
        self.clear_region(surface, content)

        # Titre + indice de sortie (zone tactile).
        title = self.font_title.render("LEAGUE OF LEGENDS", True, (210, 170, 90))
        surface.blit(title, title.get_rect(midtop=(self.width // 2, 24)))
        hint = self.font_hint.render("RETOUR", True, (200, 200, 210))
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        d = self.data
        game_time = format_game_time(d.get("game_time", 0))
        kills, deaths, assists = (d.get("kda") or [0, 0, 0])[:3]
        gold = int(d.get("gold", 0))
        cs = d.get("cs", 0)
        level = d.get("level", 0)
        score = d.get("score") or {}
        order = score.get("order", 0)
        chaos = score.get("chaos", 0)

        # Grille simple : (label, valeur) en deux colonnes.
        cells = [
            ("Temps", game_time),
            ("Niveau", str(level)),
            ("KDA", f"{kills} / {deaths} / {assists}"),
            ("Or", f"{gold}"),
            ("CS", str(cs)),
            ("Score (B/R)", f"{order} - {chaos}"),
        ]
        col_x = [self.width // 4, 3 * self.width // 4]
        row_y = [170, 280, 390]
        for i, (label, value) in enumerate(cells):
            cx = col_x[i % 2]
            cy = row_y[i // 2]
            lbl = self.font_label.render(label, True, (140, 160, 190))
            surface.blit(lbl, lbl.get_rect(center=(cx, cy - 26)))
            val = self.font_value.render(value, True, (240, 240, 245))
            surface.blit(val, val.get_rect(center=(cx, cy + 12)))

        # On redessine aussi le titre (il est au-dessus de `content`, donc pas
        # effacé) : on renvoie tout l'écran comme zone modifiée pour simplifier.
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _signature(self):
        """Empreinte hashable des champs affichés."""
        d = self.data
        return (
            d.get("game_time"),
            tuple(d.get("kda") or []),
            d.get("gold"),
            d.get("cs"),
            d.get("level"),
            tuple((d.get("score") or {}).items()),
        )
