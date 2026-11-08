"""Fin de partie (montre) : bulletin d'honneurs, honorer, rejouer."""
import endgame
from sources.league import LeagueSource

BALLOT = {
    "gameId": 42,
    "votePool": {"votes": 3},
    "honoredPlayers": [{"honorType": "HEART", "recipientPuuid": "a1"}],
    "eligibleAllies": [
        {"puuid": "a1", "summonerId": 1, "summonerName": "Ami", "championId": 103, "championName": "Ahri"},
        {"puuid": "a2", "summonerId": 2, "summonerName": "Bob", "championId": 110, "championName": "Varus"},
        {"puuid": "b0", "summonerId": 0, "summonerName": "Bot", "championId": 1, "botPlayer": True},
    ],
    "eligibleOpponents": [
        {"puuid": "o1", "summonerId": 9, "summonerName": "Zed", "championId": 238, "championName": "Zed"},
    ],
}


class Lcu:
    def __init__(self, ballot=BALLOT):
        self.ballot, self.posted = ballot, []

    def get_json(self, path, **_kw):
        return self.ballot if path == endgame.BALLOT_PATH else None

    def post(self, path, payload=None):
        self.posted.append((path, payload))
        return True


def test_bulletin_d_honneurs():
    payload = endgame.build_postgame_payload(Lcu(), "EndOfGame")
    honor = payload["honor"]
    assert honor["votesLeft"] == 2                       # 3 votes, 1 déjà donné
    assert [(p["name"], p["honored"]) for p in honor["allies"]] == [("Ami", True), ("Bob", False)]
    assert [p["name"] for p in honor["opponents"]] == ["Zed"]
    assert endgame.build_postgame_payload(Lcu({}), "WaitingForStats")["honor"] is None


def test_honorer_et_rejouer():
    src = LeagueSource({})
    src.lcu = Lcu()
    src.handle_request({"type": "lcu_action", "action": "honor", "puuid": "o1"}, None)
    src.handle_request({"type": "lcu_action", "action": "honor", "puuid": "inconnu"}, None)
    src.handle_request({"type": "lcu_action", "action": "play_again"}, None)
    assert src.lcu.posted == [
        (endgame.HONOR_PATH, {"gameId": 42, "honorType": "HEART", "puuid": "o1", "summonerId": 9}),
        (endgame.PLAY_AGAIN_PATH, None)]
