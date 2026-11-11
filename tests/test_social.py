"""Amis connectés, récompenses à récupérer, message à un ami (agent, social.py)."""

from __future__ import annotations

import social

FRIENDS = [
    {"gameName": "Zoé", "gameTag": "EUW", "summonerId": 5, "pid": "zoe@pvp", "availability": "away",
     "lol": {"gameStatus": "outOfGame"}},
    {"gameName": "Ami", "gameTag": "EUW", "summonerId": 2, "pid": "ami@pvp", "availability": "dnd",
     "lol": {"gameStatus": "inGame", "gameMode": "KIWI", "timeStamp": "1794355985091"}},
    {"gameName": "Parti", "gameTag": "EUW", "summonerId": 3, "pid": "p@pvp", "availability": "offline"},
]
GRANT = {"info": {"id": "g1", "status": "PENDING_SELECTION", "rewardGroupId": "rg"},
         "rewardGroup": {"id": "rg", "selectionStrategyConfig": {"maxSelectionsAllowed": 1},
                         "rewards": [{"id": "r1", "localizations": {"title": "750 essences bleues",
                                                                    "details": "Pour des champions"}}]}}
DONE = {"info": {"id": "g2", "status": "FULFILLED"}, "rewardGroup": {"rewards": [{"id": "x"}]}}


class FakeLcu:
    def __init__(self):
        self.posted = []
        self.refuse_first_message = False

    def get_json(self, path, **_kw):
        return {
            social.FRIENDS_PATH: FRIENDS,
            social.GRANTS_PATH: [GRANT, DONE],
            social.EVENTS_PATH: [{"eventId": "e1", "eventInfo": {"eventName": "Passe Worlds"}},
                                 {"eventId": "e2"}],
            f"{social.EVENTS_PATH}/e1/reward-track/unclaimed-rewards": {"rewardsCount": 2},
            f"{social.EVENTS_PATH}/e2/reward-track/unclaimed-rewards": {"rewardsCount": 0},
            social.SEARCH_STATE_PATH: {"errors": [{"penaltyTimeRemaining": 270}]},
        }.get(path)

    def post(self, path, payload=None, **_kw):
        self.posted.append((path, payload))
        if self.refuse_first_message and path.endswith("/messages"):
            self.refuse_first_message = False
            return False
        return True


def test_tous_les_amis_avec_leur_etat():
    friends = social.build_friends(FakeLcu())
    assert [(f["name"], f["availability"]) for f in friends] == [
        ("Ami", "dnd"), ("Parti", "offline"), ("Zoé", "away")]   # hors ligne inclus, trié
    ami = friends[0]
    assert ami["riotId"] == "Ami#EUW" and ami["pid"] == "ami@pvp"
    assert ami["gameStatus"] == "inGame" and ami["gameMode"] == "KIWI" and ami["since"] == 1794355985


def test_recompenses_a_recuperer():
    rewards = social.build_rewards(FakeLcu())
    assert rewards["grants"] == [{"grantId": "g1", "rewardGroupId": "rg", "max": 1, "options": [
        {"id": "r1", "title": "750 essences bleues", "details": "Pour des champions"}]}]
    assert rewards["events"] == [{"eventId": "e1", "count": 2, "name": "Passe Worlds"}]


def test_message_cree_la_conversation_si_besoin():
    lcu = FakeLcu()
    lcu.refuse_first_message = True
    assert social.send_message(lcu, "ami@pvp", "On joue ?")
    assert [p for p, _ in lcu.posted] == ["/lol-chat/v1/conversations/ami%40pvp/messages",
                                          "/lol-chat/v1/conversations",
                                          "/lol-chat/v1/conversations/ami%40pvp/messages"]


def test_penalite_et_echeance_stable():
    assert social.queue_penalty(FakeLcu()) == 270
    deadline = social.StableDeadline()
    first = deadline.update(270, now=1000)
    assert first == 1270
    assert deadline.update(269, now=1001.4) == first          # même échéance : pas de changement
    assert deadline.update(100, now=1001) == 1101             # vraie nouvelle pénalité
    assert deadline.update(0) == 0
