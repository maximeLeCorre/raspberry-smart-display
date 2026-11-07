"""Résumé du lobby (menu League) pour l'accueil de la montre : file, joueurs
présents, invitations en attente, et si on peut lancer la recherche."""

from __future__ import annotations

from lcu import LcuClient

LOBBY_PATH = "/lol-lobby/v2/lobby"
SEARCH_PATH = "/lol-lobby/v2/lobby/matchmaking/search"   # POST = lancer, DELETE = quitter
INVITES_PATH = "/lol-lobby/v2/received-invitations"      # + /{id}/accept | /{id}/decline
SEND_INVITES_PATH = "/lol-lobby/v2/lobby/invitations"    # POST [{"toSummonerId": …}]
FRIENDS_PATH = "/lol-chat/v1/friends"
MAX_FRIENDS = 30
# Disponibilité du chat → libellé écrit (« mobile »/« offline » : non invitables).
AVAILABILITY = {"chat": "en ligne", "away": "absent", "dnd": "occupé"}
_queue_names: dict[int, str] = {}
_names: dict[int, str] = {}           # summonerId → Riot ID (nom), stable


def queue_name(lcu: LcuClient, queue_id: int) -> str:
    """Nom localisé de la file (« ARAM : Chaos »…), mis en cache."""
    if queue_id not in _queue_names:
        info = lcu.get_json(f"/lol-game-queues/v1/queues/{queue_id}") or {}
        name = info.get("description") or info.get("shortName") or ""
        if not name:
            return f"File {queue_id}"     # pas de cache : on réessaiera
        _queue_names[queue_id] = name
    return _queue_names[queue_id]


def _name(lcu: LcuClient, member: dict, id_key: str = "summonerId") -> str:
    """⚠️ Les membres du lobby n'ont plus de nom (gameName/summonerName vides) :
    résolu par summonerId via la LCU (mis en cache)."""
    name = (member.get("gameName") or member.get("summonerName")
            or member.get("toSummonerName") or "")
    if name:
        return name
    sid = member.get(id_key)
    if sid and sid not in _names:
        found = (lcu.summoner_by_id(sid) or {}).get("gameName") or ""
        if not found:
            return "?"                     # pas de cache : on réessaiera
        _names[sid] = found
    return _names.get(sid, "?")


def build_lobby_payload(lcu: LcuClient) -> dict | None:
    """None hors lobby."""
    lobby = lcu.get_json(LOBBY_PATH)
    if not isinstance(lobby, dict) or not lobby.get("gameConfig"):
        return None
    me = (lobby.get("localMember") or {}).get("summonerId")
    taken = ({m.get("summonerId") for m in lobby.get("members") or []}
             | {i.get("toSummonerId") for i in lobby.get("invitations") or []
                if i.get("state") in ("Pending", "Requested", "Accepted")})
    queue_id = int((lobby.get("gameConfig") or {}).get("queueId") or 0)
    return {
        "queueId": queue_id,
        "queueName": queue_name(lcu, queue_id) if queue_id else "",
        "members": [{"name": _name(lcu, m), "isLeader": bool(m.get("isLeader")),
                     "isSelf": m.get("summonerId") == me}
                    for m in lobby.get("members") or []],
        "invites": [{"name": _name(lcu, i, "toSummonerId"), "state": i.get("state", "")}
                    for i in lobby.get("invitations") or []
                    if i.get("state") in ("Pending", "Requested")],
        "isLeader": bool((lobby.get("localMember") or {}).get("isLeader")),
        "canStart": bool(lobby.get("canStartActivity")),
        "friends": invitable_friends(lcu, taken),
    }


def invitable_friends(lcu: LcuClient, taken: set) -> list[dict]:
    """Amis en ligne (sur PC), hors membres et déjà invités."""
    out = []
    for f in lcu.get_json(FRIENDS_PATH) or []:
        status = AVAILABILITY.get((f.get("availability") or "").lower())
        if not status or not f.get("summonerId") or f.get("summonerId") in taken:
            continue
        if ((f.get("lol") or {}).get("gameStatus") or "") == "inGame":
            status = "en partie"
        name = f.get("gameName") or f.get("name") or "?"
        out.append({"name": name, "riotId": f"{name}#{f.get('gameTag') or ''}",
                    "summonerId": f["summonerId"], "status": status})
    out.sort(key=lambda f: (f["status"] != "en ligne", f["name"].lower()))
    return out[:MAX_FRIENDS]


def build_invitation(lcu: LcuClient) -> dict | None:
    """Invitation reçue en attente (la plus récente), sinon None."""
    pending = [i for i in lcu.get_json(INVITES_PATH) or []
               if isinstance(i, dict) and i.get("state") == "Pending" and i.get("invitationId")]
    if not pending:
        return None
    inv = pending[-1]
    queue_id = int((inv.get("gameConfig") or {}).get("queueId") or 0)
    return {"id": str(inv["invitationId"]),
            "from": inv.get("fromSummonerName") or inv.get("fromGameName") or "?",
            "queueName": queue_name(lcu, queue_id) if queue_id else ""}
