"""Affichage des pseudos : transformation + couleur éventuelle.

Surnoms (`[lol] nicknames`, config.local.toml hors Git) : un pseudo affiché sous un
autre nom, en rose fluo. Utilisé par les écrans qui montrent des pseudos
(sélection, jeu).
"""

from __future__ import annotations

# Rose « bien bien fluo ».
FLUO_PINK = (255, 20, 200)

_EASTER_EGGS: dict[str, tuple[str, tuple]] = {}


def set_nicknames(nicknames: dict | None) -> None:
    """{pseudo: surnom} (insensible à la casse), depuis la config."""
    _EASTER_EGGS.clear()
    for raw, nick in (nicknames or {}).items():
        _EASTER_EGGS[str(raw).strip().casefold()] = (str(nick), FLUO_PINK)


def display_name(raw: str | None):
    """Renvoie ``(texte, couleur | None)`` pour un pseudo.

    Couleur None = laisser l'appelant choisir sa couleur par défaut.
    """
    name = (raw or "").strip()
    special = _EASTER_EGGS.get(name.casefold())
    if special:
        return special
    return name, None
