"""Timers des objectifs neutres (Dragon, Baron, Héraut) de la Faille.

La Live Client Data API ne fournit AUCUN compte à rebours : on le reconstruit
à partir des événements de prise (`EventName` + `EventTime`) et de constantes
de réapparition. C'est précisément une info qu'on n'a pas « facilement » en
jeu, d'où son intérêt sur l'écran dédié.

⚠️ Les durées/horaires ci-dessous dépendent du patch de League (l'équilibrage
change régulièrement) : à vérifier et ajuster au besoin. Ils ne concernent que
la Faille (`gameMode == "CLASSIC"`) ; l'ARAM n'a pas d'objectifs neutres.
"""

from __future__ import annotations

# Réapparition (secondes) après la prise.
DRAGON_RESPAWN = 300          # 5:00
BARON_RESPAWN = 360           # 6:00
# Première apparition (temps de jeu, secondes).
DRAGON_FIRST = 300            # 5:00
BARON_FIRST = 1200            # 20:00
HERALD_FIRST = 840            # 14:00 (une seule apparition dans le patch actuel)


def _last_kill(events: list, name: str) -> tuple:
    """(EventTime, KillerName, DragonType) du dernier événement `name`, ou None."""
    time_s = killer = detail = None
    for e in events:
        if e.get("EventName") == name:
            time_s = e.get("EventTime")
            killer = e.get("KillerName")
            detail = e.get("DragonType")
    return time_s, killer, detail


def compute_objectives(data: dict) -> list[dict]:
    """Prochaine disponibilité de chaque objectif, en temps de jeu absolu.

    Chaque entrée : {key, label, at, by, detail}
      - at    : temps de jeu (s) de la prochaine apparition, ou None si inconnu
                / déjà consommé pour de bon (Héraut).
      - by    : dernier joueur l'ayant pris (ou None).
      - detail: info complémentaire (type du dernier dragon pris).
    Le Pi en déduit le compte à rebours = at - temps_de_jeu_courant.
    """
    events = data.get("events", {}).get("Events", []) or []

    d_t, d_by, d_type = _last_kill(events, "DragonKill")
    b_t, b_by, _ = _last_kill(events, "BaronKill")
    h_t, h_by, _ = _last_kill(events, "HeraldKill")

    dragon_at = (d_t + DRAGON_RESPAWN) if d_t is not None else DRAGON_FIRST
    baron_at = (b_t + BARON_RESPAWN) if b_t is not None else BARON_FIRST
    # Le Héraut ne réapparaît pas une fois pris (patch actuel).
    herald_at = None if h_t is not None else HERALD_FIRST

    return [
        {"key": "dragon", "label": "Dragon", "at": round(dragon_at),
         "by": d_by, "detail": d_type or None},
        {"key": "baron", "label": "Baron", "at": round(baron_at), "by": b_by},
        {"key": "herald", "label": "Héraut", "at": herald_at, "by": h_by},
    ]
