"""Données produites par l'agent à partir de la **LCU** (client ouvert, sans clé).

- `build_queue_payload` : file d'attente / ready-check.
- `build_lcu_history` / `build_lcu_detail` : historique et bilan des parties
  **spéciales/customs** (ARAM chaos…) que l'API Web Riot (`match-v5`) n'indexe
  pas. La LCU, elle, est un client RSO : elle y a accès (uniquement pour soi).
  Le Pi réclame ces données à l'agent ; les parties standard restent côté Pi.
"""

from __future__ import annotations

import time

from lcu import LcuClient

# Durée totale (secondes) d'un ready-check pour estimer le temps restant.
READY_CHECK_TOTAL = 12

QUEUE_NAMES = {
    420: "Classé Solo/Duo", 440: "Classé Flex", 400: "Normale Draft",
    430: "Normale Aveugle", 450: "ARAM", 490: "Normale (Swiftplay)",
    700: "Clash", 830: "Co-op vs IA", 1700: "Arène", 1900: "URF",
}

# gameMode -> libellé lisible (les modes spéciaux ont un nom de code interne).
GAME_MODE_LABELS = {
    "KIWI": "ARAM Chaos", "ARAM": "ARAM", "CLASSIC": "Normale",
    "URF": "URF", "CHERRY": "Arène", "NEXUSBLITZ": "Nexus Blitz",
    "ULTBOOK": "Grimoire ultime", "ONEFORALL": "Un pour tous",
}

# Modes « ARAM Chaos » (customs/spéciaux absents de l'API Web) servis via la LCU.
CHAOS_MODES = {"KIWI"}


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


# --------------------------------------------------- historique LCU (customs)
def _cs(stats: dict) -> int:
    return (stats.get("totalMinionsKilled", 0) or 0) + (stats.get("neutralMinionsKilled", 0) or 0)


def _dur_seconds(value) -> int:
    """gameDuration en secondes (ou millisecondes selon la version)."""
    d = value or 0
    return d // 1000 if d > 10000 else d


def _when(ms) -> str:
    try:
        return time.strftime("%d/%m %H:%M", time.localtime((ms or 0) / 1000))
    except (TypeError, ValueError, OSError):
        return ""


def _queue_label(game: dict) -> str:
    qid = game.get("queueId", 0) or 0
    if qid in QUEUE_NAMES:
        return QUEUE_NAMES[qid]
    mode = game.get("gameMode") or ""
    return GAME_MODE_LABELS.get(mode, mode or "Partie")


def _lcu_my_pid(lcu: LcuClient, game: dict):
    my_puuid = (lcu.current_summoner() or {}).get("puuid")
    for ident in game.get("participantIdentities", []):
        if ident.get("player", {}).get("puuid") == my_puuid:
            return ident.get("participantId"), ident
    return None, None


def build_lcu_history(lcu: LcuClient, start: int = 0, count: int = 10) -> list[dict]:
    """Liste des parties **ARAM Chaos** vues par le client (mode(s) `CHAOS_MODES`,
    ex. `KIWI`) : ces modes spéciaux sont absents de l'API Web. Paginé via
    begIndex/endIndex.
    """
    end = max(start, start + count - 1)
    mh = lcu.get_json(
        f"/lol-match-history/v1/products/lol/current-summoner/matches?begIndex={start}&endIndex={end}")
    games = (mh or {}).get("games", {}).get("games", [])
    out = []
    modes = {}
    for game in games:
        mode = game.get("gameMode") or "?"
        modes[mode] = modes.get(mode, 0) + 1
        if mode not in CHAOS_MODES:
            continue
        my_pid, _ident = _lcu_my_pid(lcu, game)
        parts = game.get("participants", [])
        mine = next((p for p in parts if p.get("participantId") == my_pid),
                    parts[0] if parts else None)
        if mine is None:
            continue
        st = mine.get("stats", {})
        cid = mine.get("championId", 0) or 0
        out.append({
            "gameId": game.get("gameId"),
            "championId": cid,
            "championName": lcu.champion_name(cid),
            "win": bool(st.get("win")),
            "kda": [st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)],
            "cs": _cs(st),
            "queue": _queue_label(game),
            "duration": _dur_seconds(game.get("gameDuration", 0)),
            "when": _when(game.get("gameCreation", 0)),
        })
    print(f"[league] LCU historique ARAM : {len(out)} partie(s) "
          f"(modes vus sur la page : {modes})")
    return out


def build_lcu_detail(lcu: LcuClient, game_id) -> dict | None:
    """Bilan détaillé (10 joueurs) d'une partie LCU choisie. Le Pi colore
    ensuite les amis via le `riotId` de chaque joueur."""
    if not game_id:
        return None
    game = lcu.get_json(f"/lol-match-history/v1/games/{game_id}")
    if not game:
        return None

    my_pid, _ident = _lcu_my_pid(lcu, game)
    ident_by_pid = {i.get("participantId"): (i.get("player", {}) or {})
                    for i in game.get("participantIdentities", [])}
    parts = game.get("participants", [])
    if not parts:
        return None

    players, mine = [], None
    for p in parts:
        pid = p.get("participantId")
        player = ident_by_pid.get(pid, {})
        st = p.get("stats", {})
        name = player.get("gameName") or player.get("summonerName") or ""
        tag = player.get("tagLine") or ""
        cid = p.get("championId", 0) or 0
        players.append({
            "name": name,
            "riotId": f"{name}#{tag}" if (name and tag) else "",
            "championId": cid,
            "championName": lcu.champion_name(cid),
            "team": p.get("teamId", 0) or 0,
            "isSelf": pid == my_pid,
            "isFriend": False,     # marqué côté Pi (il a la liste d'amis)
            "kda": [st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)],
            "metrics": {
                "dmg": st.get("totalDamageDealtToChampions", 0) or 0,
                "taken": st.get("totalDamageTaken", 0) or 0,
                "gold": st.get("goldEarned", 0) or 0,
                "cs": _cs(st),
                "vision": st.get("visionScore", 0) or 0,
                "heal": st.get("totalHeal", 0) or 0,
            },
        })
        if pid == my_pid:
            mine = p

    mine = mine or parts[0]
    ms = mine.get("stats", {})
    my_champ = mine.get("championId", 0) or 0
    return {
        "win": bool(ms.get("win")),
        "queue": _queue_label(game),
        "duration": _dur_seconds(game.get("gameDuration", 0)),
        "me": {
            "championId": my_champ,
            "championName": lcu.champion_name(my_champ),
            "kda": [ms.get("kills", 0), ms.get("deaths", 0), ms.get("assists", 0)],
            "cs": _cs(ms),
            "gold": ms.get("goldEarned", 0) or 0,
            "damage": ms.get("totalDamageDealtToChampions", 0) or 0,
            "level": ms.get("champLevel", 0) or 0,
        },
        "players": players,
    }
