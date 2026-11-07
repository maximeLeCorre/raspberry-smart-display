"""Choix de départ (ARAM Chaos : 2-3 champions) : payload agent + verrouillage."""

from __future__ import annotations

import champ_select
from sources.league import LeagueSource

SESSION = {
    "localPlayerCellId": 3,
    "myTeam": [{"cellId": 3, "championId": 0}],
    "actions": [[{"id": 7, "actorCellId": 2, "type": "pick", "isInProgress": True, "completed": False},
                 {"id": 8, "actorCellId": 3, "type": "pick", "isInProgress": True, "completed": False}]],
    "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 15000},
}


class FakeLcu:
    def __init__(self, session):
        self.session, self.patched = session, []

    def champ_select_session(self):
        return self.session

    def get_json(self, path, **_kw):
        return [233, 893] if path == champ_select.SUBSET_PATH else None

    def champion_name(self, cid):
        return {233: "Briar", 893: "Aurora"}.get(cid, "")

    def summoner_by_id(self, _sid):
        return {}

    def patch(self, path, payload=None):
        self.patched.append((path, payload))
        return True


def test_choix_proposes_tant_que_le_pick_est_en_cours():
    payload = champ_select.build_champ_select_payload(FakeLcu(SESSION))
    assert [c["championName"] for c in payload["choices"]] == ["Briar", "Aurora"]

    locked = {**SESSION, "actions": [[{**SESSION["actions"][0][1], "completed": True,
                                       "isInProgress": False, "championId": 893}]]}
    assert champ_select.build_champ_select_payload(FakeLcu(locked))["choices"] == []


def test_pick_verrouille_notre_action():
    src = LeagueSource({})
    src.lcu = FakeLcu(SESSION)
    assert src.handle_request({"type": "lcu_action", "action": "pick", "championId": 893}, None)
    assert src.lcu.patched == [("/lol-champ-select/v1/session/actions/8",
                                {"championId": 893, "completed": True})]


class BenchLcu:
    """Banc : le 1er échange est ignoré par le client (2xx sans effet), le 2e passe."""

    def __init__(self):
        self.posts, self.mine = 0, 22

    def post(self, path, payload=None):
        self.posts += 1
        if self.posts >= 2:
            self.mine = 121
        return True

    def champ_select_session(self):
        bench = [] if self.mine == 121 else [{"championId": 121}]
        return {"localPlayerCellId": 0, "myTeam": [{"cellId": 0, "championId": self.mine}],
                "benchChampions": bench}


def test_echange_du_banc_verifie_et_reessaye():
    src = LeagueSource({})
    src.lcu = BenchLcu()
    src._swap(121)
    assert src.lcu.posts == 2 and src.lcu.mine == 121
