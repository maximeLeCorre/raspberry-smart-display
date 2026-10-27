"""Construction des données pour la phase « file d'attente » (LCU, sans clé).

Le bilan de fin de partie et l'historique sont désormais calculés **par le Pi**
(via l'API Web Riot) ; l'agent ne s'en occupe plus.
"""

from __future__ import annotations

from lcu import LcuClient

# Durée totale (secondes) d'un ready-check pour estimer le temps restant.
READY_CHECK_TOTAL = 12


def build_queue_payload(lcu: LcuClient, phase: str) -> dict:
    """Résumé de la file d'attente ou du ready-check (écran 'queue')."""
    if phase == "ReadyCheck":
        rc = lcu.get_json("/lol-matchmaking/v1/ready-check") or {}
        elapsed = round(rc.get("timer", 0) or 0)
        return {
            "state": "readycheck",
            "remaining": max(0, READY_CHECK_TOTAL - elapsed),
            "response": rc.get("playerResponse", "None"),
        }

    search = lcu.get_json("/lol-matchmaking/v1/search") or {}
    return {
        "state": "searching",
        "timeInQueue": round(search.get("timeInQueue", 0) or 0),
        "estimated": round(search.get("estimatedQueueTime", 0) or 0),
    }
