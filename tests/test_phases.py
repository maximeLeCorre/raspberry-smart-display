"""Données produites par l'agent depuis la LCU (file, historique)."""

from __future__ import annotations

from phases import build_lcu_detail, build_queue_payload, iter_lcu_sync

ME = "puuid-moi"


def game(gid, creation=0):
    parts, idents = [], []
    for pid in range(1, 11):
        parts.append({"participantId": pid, "championId": pid, "teamId": 100 if pid <= 5 else 200,
                      "stats": {"kills": pid, "deaths": 1, "assists": 2, "win": pid <= 5,
                                "totalMinionsKilled": 10, "neutralMinionsKilled": 2}})
        idents.append({"participantId": pid, "player": {
            "puuid": ME if pid == 3 else f"p{pid}", "gameName": f"J{pid}", "tagLine": "EUW"}})
    return {"gameId": gid, "gameCreation": creation, "gameMode": "KIWI", "queueId": 2400,
            "gameDuration": 1200, "participants": parts, "participantIdentities": idents}


class FakeLcu:
    def __init__(self, ids):
        self.games = {g: game(g, 1000 - g) for g in ids}
        self.order = ids

    def current_summoner(self):
        return {"puuid": ME}

    def champion_name(self, cid):
        return f"Champ{cid}"

    def get_json(self, path, **_kw):
        if path.startswith("/lol-match-history/v1/products"):
            return {"games": {"games": [{"gameId": g} for g in self.order]}}
        if path.startswith("/lol-match-history/v1/games/"):
            return self.games.get(int(path.rsplit("/", 1)[1]))
        if path == "/lol-matchmaking/v1/ready-check":
            return {"timer": 4.6, "playerResponse": "None"}
        if path == "/lol-matchmaking/v1/search":
            return {"timeInQueue": 61.2, "estimatedQueueTime": 90}
        return None


def test_synchro_s_arrete_a_la_derniere_partie_stockee():
    lcu = FakeLcu([9, 8, 7, 6, 5])
    batches = list(iter_lcu_sync(lcu, since=7, chunk=15))
    assert [r["gameId"] for b in batches for r in b] == ["9", "8"]


def test_synchro_par_lots():
    lcu = FakeLcu(list(range(20, 0, -1)))
    sizes = [len(b) for b in iter_lcu_sync(lcu, since=None, chunk=15)]
    assert sizes == [15, 5]


def test_bilan_identifie_le_joueur_et_les_equipes():
    d = build_lcu_detail(FakeLcu([1]), 1)
    me = [p for p in d["players"] if p["isSelf"]]
    assert len(d["players"]) == 10 and len(me) == 1
    assert me[0]["riotId"] == "J3#EUW" and me[0]["metrics"]["cs"] == 12
    assert d["win"] is True and d["duration"] == 1200


def test_bilan_partie_vide_ou_inconnue():
    assert build_lcu_detail(FakeLcu([]), 42) is None


def test_payload_file_et_ready_check():
    lcu = FakeLcu([])
    assert build_queue_payload(lcu, "ReadyCheck") == {
        "state": "readycheck", "remaining": 7, "response": "None"}
    assert build_queue_payload(lcu, "Matchmaking") == {
        "state": "searching", "timeInQueue": 61, "estimated": 90}
