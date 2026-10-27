"""Données produites par l'agent à partir de la **LCU** (client ouvert, sans clé).

- `build_queue_payload` : file d'attente / ready-check.
- `iter_lcu_sync` / `build_lcu_detail` : historique (résumé + bilan) que le Pi
  stocke en local. La LCU est un client RSO : elle a accès aux customs/ARAM chaos
  que l'API Web (`match-v5`) n'indexe pas — mais n'expose que les 20 récentes.
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


def _lcu_detail_from_game(lcu: LcuClient, game: dict) -> dict | None:
    """Bilan (10 joueurs) depuis un objet partie du endpoint **détail** LCU
    (`/games/{id}` ; la liste, elle, ne renvoie qu'1 joueur). `isFriend` : Pi."""
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


def build_lcu_detail(lcu: LcuClient, game_id) -> dict | None:
    """Bilan complet (10 joueurs) d'une partie, via le endpoint détail LCU."""
    if not game_id:
        return None
    game = lcu.get_json(f"/lol-match-history/v1/games/{game_id}")
    if not game:
        return None
    return _lcu_detail_from_game(lcu, game)


def _lcu_full_record(lcu: LcuClient, game_id) -> dict | None:
    """Enregistrement COMPLET (résumé + bilan 10 joueurs) pour le store Pi.

    ⚠️ Le endpoint liste ne donne qu'1 joueur : on récupère le détail par partie
    (`/games/{id}`) pour avoir les 10 joueurs et pouvoir consulter PC éteint.
    """
    game = lcu.get_json(f"/lol-match-history/v1/games/{game_id}")
    if not game:
        return None
    detail = _lcu_detail_from_game(lcu, game)
    if detail is None:
        return None
    me = detail["me"]
    return {
        "gameId": str(game_id),
        "gameCreation": game.get("gameCreation", 0) or 0,
        "gameMode": game.get("gameMode") or "",
        "queueId": game.get("queueId", 0) or 0,
        "queue": _queue_label(game),
        "duration": _dur_seconds(game.get("gameDuration", 0)),
        "win": detail["win"],
        "championId": me["championId"],
        "championName": me["championName"],
        "kda": me["kda"],
        "cs": me["cs"],
        "detail": detail,
    }


def iter_lcu_sync(lcu: LcuClient, since=None, chunk: int = 15):
    """Génère des **lots** d'enregistrements complets (résumé + bilan) pour la
    synchro **progressive** du store.

    ⚠️ La LCU **ne pagine pas** (`begIndex`/`endIndex` ignorés) : elle n'expose
    que les **20 parties les plus récentes**. On lit donc cette page et on
    s'arrête à `since` (dernière partie déjà stockée ⇒ on ne prend que les
    nouvelles). Le reste de l'historique s'accumule au fil des parties jouées."""
    since = str(since) if since else None
    mh = lcu.get_json(
        "/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=19")
    games = (mh or {}).get("games", {}).get("games", [])
    batch = []
    for game in games:
        if since and str(game.get("gameId")) == since:
            break                   # reprise : on a rejoint le store
        rec = _lcu_full_record(lcu, game.get("gameId"))
        if rec:
            batch.append(rec)
            if len(batch) >= chunk:
                yield batch
                batch = []
    if batch:
        yield batch
