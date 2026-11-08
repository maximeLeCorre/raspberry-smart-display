"""Fin de partie, pour la montre : bulletin d'honneurs (honorer alliés et
adversaires) et « Rejouer » (retour au lobby, mêmes joueurs).

Bulletin = `GET /lol-honor-v2/v1/ballot` (lisible pendant PreEndOfGame/EndOfGame) :
`eligibleAllies`/`eligibleOpponents`, `votePool.votes` = votes de la partie
(TOTAL : déjà donnés compris, cf. `honoredPlayers`). Honorer = POST
`honor-player` {gameId, honorType, puuid, summonerId} ; le client lui-même envoie
`HEART` (constaté nov. 2026).
"""

from __future__ import annotations

from lcu import LcuClient

BALLOT_PATH = "/lol-honor-v2/v1/ballot"
HONOR_PATH = "/lol-honor-v2/v1/honor-player"
PLAY_AGAIN_PATH = "/lol-lobby/v2/play-again"
HONOR_TYPE = "HEART"


def _players(ballot: dict, key: str, honored: set[str]) -> list[dict]:
    return [{"puuid": p.get("puuid", ""), "name": p.get("summonerName") or "?",
             "championId": p.get("championId", 0), "championName": p.get("championName", ""),
             "honored": p.get("puuid") in honored}
            for p in ballot.get(key) or [] if not p.get("botPlayer") and p.get("puuid")]


def build_postgame_payload(lcu: LcuClient, phase: str) -> dict:
    """{phase, honor} ; honor None sans bulletin (pas encore prêt, ou partie sans vote)."""
    ballot = lcu.get_json(BALLOT_PATH) or {}
    honor = None
    if ballot.get("gameId"):
        honored = {h.get("recipientPuuid") for h in ballot.get("honoredPlayers") or []}
        votes = (ballot.get("votePool") or {}).get("votes", 0)
        honor = {"gameId": ballot["gameId"], "votesLeft": max(0, votes - len(honored)),
                 "allies": _players(ballot, "eligibleAllies", honored),
                 "opponents": _players(ballot, "eligibleOpponents", honored)}
    return {"phase": phase, "honor": honor}


def honor_player(lcu: LcuClient, puuid: str) -> bool:
    """Honore `puuid` s'il est dans le bulletin courant (ids relus : jamais de périmé)."""
    ballot = lcu.get_json(BALLOT_PATH) or {}
    for p in (ballot.get("eligibleAllies") or []) + (ballot.get("eligibleOpponents") or []):
        if p.get("puuid") == puuid and ballot.get("gameId"):
            return lcu.post(HONOR_PATH, {"gameId": ballot["gameId"], "honorType": HONOR_TYPE,
                                         "puuid": puuid, "summonerId": p.get("summonerId", 0)})
    return False
