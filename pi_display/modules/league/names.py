"""Affichage des pseudos : transformation + couleur éventuelle.

Centralise un petit easter egg : le joueur « Matte Mwa » est affiché « BÉBOU »
en rose fluo. Utilisé par les écrans qui montrent des pseudos (sélection, jeu).
"""

from __future__ import annotations

# Rose « bien bien fluo ».
FLUO_PINK = (255, 20, 200)

_EASTER_EGGS = {
    "matte mwa": ("BÉBOU", FLUO_PINK),
}


def display_name(raw: str | None):
    """Renvoie ``(texte, couleur | None)`` pour un pseudo.

    Couleur None = laisser l'appelant choisir sa couleur par défaut.
    """
    name = (raw or "").strip()
    special = _EASTER_EGGS.get(name.casefold())
    if special:
        return special
    return name, None
