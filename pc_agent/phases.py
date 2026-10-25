"""Construction des données pour les phases « file d'attente » et « après-partie ».

Ces infos viennent de la LCU (pas de clé Riot nécessaire).
"""

from __future__ import annotations

from lcu import LcuClient

# Durée totale (secondes) d'un ready-check pour estimer le temps restant.
READY_CHECK_TOTAL = 12

# Quelques files courantes -> libellé lisible.
QUEUE_NAMES = {
    420: "Classé Solo/Duo", 440: "Classé Flex", 400: "Normale Draft",
    430: "Normale Aveugle", 450: "ARAM", 490: "Normale (Swiftplay)",
    700: "Clash", 830: "Co-op vs IA", 1700: "Arena", 1900: "URF",
}


def build_queue_payload(lcu: LcuClient, phase: str) -> dict:
    """Résumé de la file d'attente ou du ready-check (mode 'queue')."""
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


def build_postgame_payload(lcu: LcuClient) -> dict | None:
    """Résumé de la dernière partie jouée (mode 'postgame'), via l'historique LCU."""
    mh = lcu.get_json(
        "/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=0")
    games = (mh or {}).get("games", {}).get("games", [])
    if not games:
        return None
    game = games[0]

    # On retrouve notre participant via le PUUID.
    my_puuid = (lcu.current_summoner() or {}).get("puuid")
    my_pid = None
    for ident in game.get("participantIdentities", []):
        if ident.get("player", {}).get("puuid") == my_puuid:
            my_pid = ident.get("participantId")
            break
    parts = game.get("participants", [])
    mine = next((p for p in parts if p.get("participantId") == my_pid),
                parts[0] if parts else {})
    stats = mine.get("stats", {})

    champ_id = mine.get("championId", 0) or 0
    cs = (stats.get("totalMinionsKilled", 0) or 0) + (stats.get("neutralMinionsKilled", 0) or 0)
    queue_id = game.get("queueId", 0)
    return {
        "win": bool(stats.get("win")),
        "championId": champ_id,
        "championName": lcu.champion_name(champ_id),
        "kda": [stats.get("kills", 0), stats.get("deaths", 0), stats.get("assists", 0)],
        "cs": cs,
        "gold": stats.get("goldEarned", 0),
        "damage": stats.get("totalDamageDealtToChampions", 0),
        "level": stats.get("champLevel", 0),
        "duration": game.get("gameDuration", 0),
        "queue": QUEUE_NAMES.get(queue_id, "Partie"),
    }
