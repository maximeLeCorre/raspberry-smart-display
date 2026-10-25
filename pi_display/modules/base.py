"""Descripteur de module d'affichage.

Un module regroupe plusieurs écrans (Screen) d'un même jeu/domaine.
Exemple : le module « league » fournit les écrans file d'attente, sélection,
partie et après-partie.
"""

from __future__ import annotations


class Module:
    name = "base"          # identifiant du module (clé de config)
    always_on = False      # True = toujours actif, non désactivable (ex. système)
    screens: list = []     # classes Screen fournies par ce module
