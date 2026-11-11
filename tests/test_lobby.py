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

    def summoner_by_id(self, sid):
        return {"gameName": {1: "Moi", 2: "Ami"}.get(sid, "")}

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
    assert payload["lobby"]["penaltyEnds"] == 0 and not payload["reconnect"]
    assert [f["name"] for f in payload["friendList"]] == ["Ami", "Bob", "Joue", "Tel", "Zoé"]
    src.lcu.phase = "None"                                  # retour au menu
    _, payload = src.poll()
    assert {k: payload[k] for k in ("client", "lobby", "invitation", "chat")} == {
        "client": True, "lobby": None, "invitation": None, "chat": None}
    src.lcu.phase = "Reconnect"                             # jeu planté en partie
    assert src.poll()[1]["reconnect"]
    src.lcu.phase = None                                    # client fermé : effacé une fois
    assert src.poll() == ("default", {"client": False, "lobby": None, "invitation": None,
                                      "chat": None, "friendList": None, "rewards": None,
                                      "reconnect": False})
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


def test_dernier_message_prive_recu():
    import chat

    class ChatLcu:
        def get_json(self, path, **_kw):
            if path == chat.ME_PATH:
                return {"id": "moi@pvp"}
            return [
                {"type": "chat", "gameName": "Ami", "unreadMessageCount": 1, "id": "ami@pvp",
                 "lastMessage": {"id": "m2", "fromId": "ami@pvp", "body": "on joue ?",
                                 "timestamp": "2026-11-07T12:00:05.000Z"}},
                {"type": "chat", "gameName": "Vieux", "unreadMessageCount": 1,       # avant le démarrage
                 "lastMessage": {"id": "m0", "fromId": "x@pvp", "body": "...",
                                 "timestamp": "2026-11-01T12:00:00.000Z"}},
                {"type": "chat", "gameName": "Moi", "unreadMessageCount": 1,         # notre message
                 "lastMessage": {"id": "m3", "fromId": "moi@pvp", "body": "ok",
                                 "timestamp": "2026-11-07T12:00:09.000Z"}},
                {"type": "customGame", "name": "Lobby", "unreadMessageCount": 3,     # salon de lobby
                 "lastMessage": {"id": "m4", "fromId": "y@pvp", "body": "gg",
                                 "timestamp": "2026-11-07T12:00:10.000Z"}},
            ]

    since = chat._timestamp("2026-11-07T11:00:00Z")
    msg = chat.build_last_message(ChatLcu(), since)
    assert (msg["id"], msg["from"], msg["body"], msg["conv"]) == ("m2", "Ami", "on joue ?", "ami@pvp")


def test_reponse_a_un_message_depuis_la_montre():
    import chat
    src = LeagueSource({})
    src.lcu = FakeLcu()
    src.handle_request({"type": "lcu_action", "action": "chat_reply",
                        "conversationId": "ami@pvp.net", "body": "J'arrive !"}, None)
    src.handle_request({"type": "lcu_action", "action": "chat_reply",
                        "conversationId": "", "body": "x"}, None)        # ignorée
    assert src.lcu.posted == [chat.reply_path("ami@pvp.net")]
    assert chat.reply_path("ami@pvp.net") == "/lol-chat/v1/conversations/ami%40pvp.net/messages"


def test_quitter_le_lobby_et_fermer_le_client():
    src = LeagueSource({})
    src.lcu = FakeLcu()
    src.handle_request({"type": "lcu_action", "action": "leave_lobby"}, None)
    src.handle_request({"type": "lcu_action", "action": "quit_client"}, None)
    assert src.lcu.deleted == [lobby.LOBBY_PATH]
    assert src.lcu.posted == ["/process-control/v1/process/quit"]


def test_noms_des_membres_resolus_par_summoner_id():
    lcu = FakeLcu()
    bare = {**LOBBY, "members": [{"summonerId": 2, "isLeader": False}]}   # sans gameName (réel)
    lcu.get_json = lambda path, **_kw: bare if path == lobby.LOBBY_PATH else None
    assert [m["name"] for m in lobby.build_lobby_payload(lcu)["members"]] == ["Ami"]
