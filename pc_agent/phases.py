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
            "win": bool(st.get("win")),
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


def build_lcu_timeline(lcu: LcuClient, game_id) -> dict | None:
    """Timeline d'une partie terminée (LCU, 1 point par minute ; marche aussi en
    ARAM Chaos/custom, absentes de `match-v5`). Même format que le relevé en
    direct du Pi : `players` (ordre participantId) + `frames`
    [{t (s), gold, cs, level, kills}] aux listes alignées sur `players`.
    Or = total gagné **exact** ; kills = cumul des CHAMPION_KILL jusqu'à `t`."""
    if not game_id:
        return None
    game = lcu.get_json(f"/lol-match-history/v1/games/{game_id}")
    timeline = lcu.get_json(f"/lol-match-history/v1/game-timelines/{game_id}", timeout=8)
    if not game or not timeline or not timeline.get("frames"):
        return None
    my_pid, _ident = _lcu_my_pid(lcu, game)
    ident_by_pid = {i.get("participantId"): (i.get("player", {}) or {})
                    for i in game.get("participantIdentities", [])}
    parts = sorted(game.get("participants", []), key=lambda p: p.get("participantId", 0))
    pids = [p.get("participantId") for p in parts]
    players = []
    for p in parts:
        player = ident_by_pid.get(p.get("participantId"), {})
        name = player.get("gameName") or player.get("summonerName") or ""
        tag = player.get("tagLine") or ""
        cid = p.get("championId", 0) or 0
        players.append({"name": name, "riotId": f"{name}#{tag}" if (name and tag) else "",
                        "championId": cid, "champion": lcu.champion_name(cid),
                        "team": p.get("teamId", 0) or 0,
                        "isSelf": p.get("participantId") == my_pid})

    index = {pid: i for i, pid in enumerate(pids)}
    kill_events = sorted((e.get("timestamp") or 0, index[e.get("killerId")])
                         for fr in timeline["frames"] for e in fr.get("events") or []
                         if e.get("type") == "CHAMPION_KILL" and e.get("killerId") in index)
    kills, k = [0] * len(pids), 0
    frames = []
    for fr in timeline["frames"]:
        ts = fr.get("timestamp") or 0
        while k < len(kill_events) and kill_events[k][0] <= ts:
            kills[kill_events[k][1]] += 1
            k += 1
        pf = [(fr.get("participantFrames") or {}).get(str(pid)) or {} for pid in pids]
        frames.append({
            "t": round(ts / 1000),
            "gold": [f.get("totalGold", 0) or 0 for f in pf],
            "cs": [(f.get("minionsKilled", 0) or 0) + (f.get("jungleMinionsKilled", 0) or 0)
                   for f in pf],
            "level": [f.get("level", 0) or 0 for f in pf],
            "kills": list(kills),
        })
    return {"players": players, "frames": frames, "estimated": False}


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


# ------------------------------------------- historique d'un AUTRE joueur (ami)
def find_friend_puuid(lcu: LcuClient, riot_id: str) -> str | None:
    """PUUID (LCU) d'un ami par Riot ID « Nom#TAG » (insensible à la casse).
    Passe par la liste d'amis : la LCU ne cherche plus de joueur par nom."""
    want = (riot_id or "").strip().lower()
    for f in (lcu.get_json("/lol-chat/v1/friends") or []):
        rid = f"{(f.get('gameName') or '').lower()}#{(f.get('gameTag') or '').lower()}"
        if rid == want and f.get("puuid"):
            return f["puuid"]
    return None


def iter_player_sync(lcu: LcuClient, puuid: str, known=(), chunk: int = 15):
    """Lots de parties d'un autre joueur (ses 20 récentes, comme pour nous) au
    format des enregistrements du store (résumé de partie + bilan 10 joueurs).

    On SAUTE les parties déjà connues du Pi (`known`) au lieu de s'arrêter à la
    première : une partie en duo arrivée par NOTRE synchro peut être plus
    récente que des parties solo de l'ami encore jamais lues."""
    known = {str(k) for k in known or ()}
    mh = lcu.get_json(
        f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=19")
    batch = []
    for game in (mh or {}).get("games", {}).get("games", []):
        gid = str(game.get("gameId"))
        if gid in known:
            continue
        rec = _lcu_full_record(lcu, gid)
        if rec:
            batch.append(rec)
            if len(batch) >= chunk:
                yield batch
                batch = []
    if batch:
        yield batch
