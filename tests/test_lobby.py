"""Lobby (accueil de la montre) : résumé agent, effacement, actions Pi."""

from __future__ import annotations

import lobby
from sources.league import LeagueSource

LOBBY = {
    "gameConfig": {"queueId": 2400},
    "localMember": {"summonerId": 1, "isLeader": True},
    "members": [{"summonerId": 1, "gameName": "Moi", "isLeader": True},
                {"summonerId": 2, "gameName": "Ami", "isLeader": False}],
    "invitations": [{"toSummonerName": "Autre", "state": "Pending"},
                    {"toSummonerName": "Parti", "state": "Declined"}],
    "canStartActivity": True,
}


class FakeLcu:
    def __init__(self, phase="Lobby"):
        self.phase = phase
        self.posted, self.deleted = [], []
        self.invites = []
        self.friends = [
            {"gameName": "Ami", "gameTag": "EUW", "summonerId": 2, "availability": "chat"},   # membre
            {"gameName": "Zoé", "gameTag": "EUW", "summonerId": 5, "availability": "away"},
            {"gameName": "Bob", "gameTag": "EUW", "summonerId": 6, "availability": "chat"},
            {"gameName": "Tel", "gameTag": "EUW", "summonerId": 7, "availability": "mobile"},
            {"gameName": "Joue", "gameTag": "EUW", "summonerId": 8, "availability": "dnd",
             "lol": {"gameStatus": "inGame"}},
        ]

    def gameflow_phase(self):
        return self.phase

    def get_json(self, path, **_kw):
        if path == lobby.LOBBY_PATH:
            return LOBBY if self.phase == "Lobby" else None
        if path == lobby.FRIENDS_PATH:
            return self.friends
        if path == lobby.INVITES_PATH:
            return self.invites
        if path.startswith("/lol-game-queues/v1/queues/"):
            return {"description": "ARAM : Chaos"}
        return None

    def post(self, path, payload=None):
        self.posted.append(path)
        return True

    def delete(self, path):
        self.deleted.append(path)
        return True


def test_resume_du_lobby():
    payload = lobby.build_lobby_payload(FakeLcu())
    assert payload["queueName"] == "ARAM : Chaos"
    assert [(m["name"], m["isLeader"], m["isSelf"]) for m in payload["members"]] == [
        ("Moi", True, True), ("Ami", False, False)]
    assert payload["invites"] == [{"name": "Autre", "state": "Pending"}]   # refus masqués
    assert payload["isLeader"] and payload["canStart"]
    # En ligne d'abord ; membres, mobiles et hors ligne exclus ; statut écrit.
    assert [(f["name"], f["status"]) for f in payload["friends"]] == [
        ("Bob", "en ligne"), ("Joue", "en partie"), ("Zoé", "absent")]


def test_poll_lobby_puis_client_ferme():
    src = LeagueSource({})
    src.lcu = FakeLcu("Lobby")
    screen, payload = src.poll()
    assert screen == "default" and payload["lobby"]["members"]
    src.lcu.phase = "None"                                  # retour au menu
    assert src.poll() == ("default", {"lobby": None, "invitation": None})
    src.lcu.phase = "Lobby"
    src.poll()
    src.lcu.phase = None                                    # client fermé : effacé une fois
    assert src.poll() == ("default", {"lobby": None, "invitation": None})
    assert src.poll() is None


def test_lancer_et_quitter_la_file():
    src = LeagueSource({})
    src.lcu = FakeLcu()
    src.handle_request({"type": "lcu_action", "action": "start_queue"}, None)
    src.handle_request({"type": "lcu_action", "action": "cancel_queue"}, None)
    assert src.lcu.posted == [lobby.SEARCH_PATH] and src.lcu.deleted == [lobby.SEARCH_PATH]


def test_invitation_recue_et_acceptee():
    src = LeagueSource({})
    src.lcu = FakeLcu("None")
    src.lcu.invites = [{"invitationId": "abc", "state": "Pending", "fromSummonerName": "Ami",
                        "gameConfig": {"queueId": 2400}},
                       {"invitationId": "old", "state": "Declined"}]
    _, payload = src.poll()
    assert payload["invitation"] == {"id": "abc", "from": "Ami", "queueName": "ARAM : Chaos"}
    src.handle_request({"type": "lcu_action", "action": "invite_accept", "invitationId": "abc"}, None)
    assert src.lcu.posted == [f"{lobby.INVITES_PATH}/abc/accept"]


def test_inviter_un_ami():
    src = LeagueSource({})
    src.lcu = FakeLcu()
    src.handle_request({"type": "lcu_action", "action": "invite", "summonerId": 6}, None)
    assert src.lcu.posted == [lobby.SEND_INVITES_PATH]
