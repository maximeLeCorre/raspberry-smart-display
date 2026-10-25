"""Détection des processus League of Legends via psutil."""

from __future__ import annotations

import psutil


def is_any_process_running(names: list[str]) -> bool:
    """True si au moins un processus dont le nom figure dans `names` tourne.

    La comparaison est insensible à la casse.
    """
    wanted = {n.lower() for n in names}
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name in wanted:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False
