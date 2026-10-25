"""Classe de base d'une Source : la moitié « agent » d'un module.

Une Source sait détecter si son jeu/domaine est actif et produire l'écran +
les données à afficher. Elle répond aussi aux requêtes du Pi (infos, images).

Pour ajouter un jeu : créer une Source dans `sources/<nom>.py` et l'enregistrer
dans `sources/__init__.py`.
"""

from __future__ import annotations


class Source:
    name = "base"   # doit correspondre au nom du module côté Pi

    def __init__(self, config: dict):
        self.config = config

    def poll(self) -> tuple[str, dict | None] | None:
        """Renvoie (nom_écran, payload) à afficher, ou None si inactif.

        payload peut être None (basculer sur l'écran sans données ce tick).
        """
        return None

    def handle_request(self, message: dict, sender) -> bool:
        """Traite une requête du Pi (infos joueur, icône, splash...).
        Renvoie True si le message a été pris en charge."""
        return False
