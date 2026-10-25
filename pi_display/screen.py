"""Classe de base commune à tous les écrans d'affichage.

Un « écran » (Screen) est une vue affichable (horloge, sélection, partie...).
Les écrans sont regroupés par **module** (un jeu/domaine) dans `modules/`.

Principe de performance (important sur Pi 3) :
  - Chaque écran a un fond pré-rendu (PNG 800x480) chargé UNE SEULE FOIS.
  - On ne redessine pas tout l'écran à chaque frame : seules les zones
    dynamiques sont redessinées (« dirty rects »).
  - Pour effacer une ancienne valeur, on recopie le morceau de fond
    correspondant, puis on dessine la nouvelle valeur par-dessus.
"""

from __future__ import annotations

from pathlib import Path

import pygame

# Dossier des fonds : pi_display/assets/
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


class Screen:
    name = "base"               # identifiant unique de l'écran
    background_name = None      # nom du PNG dans assets/ (ex. "default.png")
    bg_color = (20, 20, 30)     # couleur de repli si le PNG est absent
    cycle = False               # True = inclus dans le cycle du bouton « suivant »

    def __init__(self, app):
        self.app = app
        self.width = app.width
        self.height = app.height
        self.bg = self._load_background()

    # ------------------------------------------------------------------ fond
    def _load_background(self) -> pygame.Surface:
        """Charge le fond une fois. Repli sur une couleur unie si PNG absent."""
        surface = pygame.Surface((self.width, self.height))
        path = ASSETS_DIR / self.background_name if self.background_name else None
        if path and path.exists():
            image = pygame.image.load(str(path)).convert()
            if image.get_size() != (self.width, self.height):
                image = pygame.transform.scale(image, (self.width, self.height))
            surface.blit(image, (0, 0))
        else:
            surface.fill(self.bg_color)
        return surface

    # ---------------------------------------------------------- cycle de vie
    def enter(self) -> None:
        """Appelé à chaque entrée dans l'écran (réinitialiser les caches ici)."""

    def exit(self) -> None:
        """Appelé à la sortie de l'écran."""

    def update_data(self, payload: dict) -> None:
        """Nouvelles données reçues du réseau pour cet écran."""

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        """Touche/clic aux coordonnées internes. Peut renvoyer une action
        (voir inputs.ACTION_*), par ex. pour sortir de l'écran. None = rien."""
        return None

    # ---------------------------------------------------------------- rendu
    def draw_background(self, surface: pygame.Surface) -> None:
        """Dessine le fond complet (appelé une fois à l'entrée de l'écran)."""
        surface.blit(self.bg, (0, 0))

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        """Dessine les zones dynamiques. Renvoie la liste des rects modifiés
        (« dirty rects »). Renvoyer [] si rien n'a changé cette frame."""
        return []

    # ---------------------------------------------------------- utilitaires
    def clear_region(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Efface une zone en y recopiant le fond d'origine."""
        surface.blit(self.bg, rect, rect)

    def draw_centered_line(
        self,
        surface: pygame.Surface,
        text: str,
        font: pygame.font.Font,
        color: tuple[int, int, int],
        y: int,
    ) -> pygame.Rect:
        """Affiche une ligne centrée horizontalement, en effaçant d'abord une
        bande pleine largeur à cette hauteur. Renvoie le rect de la bande."""
        rendered = font.render(text, True, color)
        text_rect = rendered.get_rect(center=(self.width // 2, y))
        band = pygame.Rect(0, text_rect.top - 4, self.width, text_rect.height + 8)
        self.clear_region(surface, band)
        surface.blit(rendered, text_rect)
        return band
