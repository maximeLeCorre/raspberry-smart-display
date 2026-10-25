"""Chargement de la configuration et détection de l'environnement (PC / Pi)."""

from __future__ import annotations

import tomllib
from pathlib import Path


def is_raspberry_pi() -> bool:
    """Retourne True si le programme tourne sur un Raspberry Pi.

    On lit le modèle exposé par le noyau Linux. Sur un PC Windows ce fichier
    n'existe pas : la fonction renvoie False sans lever d'erreur.
    """
    model = Path("/sys/firmware/devicetree/base/model")
    try:
        return model.exists() and "raspberry pi" in model.read_text(errors="ignore").lower()
    except OSError:
        return False


def load_config(path: str | Path) -> dict:
    """Charge le fichier config.toml et renvoie un dictionnaire."""
    with open(path, "rb") as f:
        return tomllib.load(f)
