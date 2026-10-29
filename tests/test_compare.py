"""Stats comparées : participations, solo vs duo, synchro de l'ami."""

from __future__ import annotations

import json

from phases import iter_player_sync
from store import Store
from test_phases import FakeLcu

ME, MATE = "Moi#EUW", "Matte mwa#EUW"


def player(rid, team, win, k=5, self_=False, champ=1):
    return {"riotId": rid, "team": team, "win": win, "isSelf": self_, "championId": champ,
            "championName": f"C{champ}", "kda": [k, 2, 3],
            "metrics": {"dmg": 6000, "gold": 3000, "cs": 30}}


def rec(gid, players, my_win=True, creation=0):
    return {"gameId": gid, "gameCreation": creation, "gameMode": "KIWI", "queueId": 2400,
            "queue": "ARAM Chaos", "duration": 600, "win": my_win, "championId": 1,
            "championName": "C1", "kda": [5, 2, 3], "cs": 30,
            "detail": {"win": my_win, "players": players}}


def test_solo_duo_et_adversaires(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_matches([
        rec(1, [player(ME, 100, True, self_=True), player(MATE, 100, True)]),       # duo, V
        rec(2, [player(ME, 100, False, self_=True), player(MATE, 100, False)], False),  # duo, D
        rec(3, [player(ME, 100, True, self_=True), player("x#y", 200, False)]),     # moi seul
        rec(4, [player(ME, 100, True, self_=True), player(MATE, 200, False)]),      # face à face
    ])
    st.upsert_player_games([rec(5, [player(MATE, 200, True, champ=7), player("z#w", 100, False)])])
    c = st.compare(ME, MATE)
    assert (c["duo_me"]["games"], c["duo_me"]["winrate"]) == (2, 50)
    assert c["duo_other"]["games"] == 2
    assert (c["me_solo"]["games"], c["me_solo"]["winrate"]) == (2, 100)   # 3 et 4
    assert (c["other_solo"]["games"], c["other_solo"]["wins"]) == (2, 1)  # 4 (D) et 5 (V)
    assert c["me_solo"]["dmg_min"] == 600 and c["me_solo"]["kda_ratio"] == 4.0
    assert c["top"]["other_solo"][0]["championName"] in ("C1", "C7")


def test_parties_de_l_ami_hors_historique_affiche(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_player_games([rec(9, [player(MATE, 100, True)])])
    assert st.total() == 0                       # l'historique reste le mien
    assert st.known_games(MATE) == ["9"]


def test_retro_remplissage_des_anciens_bilans(tmp_path):
    """Bilans d'avant la mise à jour (sans `win` par joueur) : déduit de l'équipe."""
    path = tmp_path / "m.db"
    st = Store(path)
    old = rec(1, [player(ME, 100, True, self_=True), player(MATE, 100, True),
                  player("e#1", 200, False)], my_win=False)
    for p in old["detail"]["players"]:
        del p["win"]
    st.upsert_matches([old])
    st._conn.execute("DELETE FROM participations")
    st._conn.commit()
    st2 = Store(path)                            # réouverture → rétro-remplissage
    wins = dict(st2._conn.execute("SELECT riot_key, win FROM participations").fetchall())
    assert wins == {"moi#euw": 0, "matte mwa#euw": 0, "e#1": 1}


def test_synchro_ami_saute_les_parties_connues():
    lcu = FakeLcu([9, 8, 7, 6])
    lcu.get_json_orig = lcu.get_json

    def get_json(path):
        if "/products/lol/" in path and "current-summoner" not in path:
            path = "/lol-match-history/v1/products/lol/current-summoner/matches"
        return lcu.get_json_orig(path)
    lcu.get_json = get_json
    ids = [r["gameId"] for b in iter_player_sync(lcu, "puuid-ami", known=["8"]) for r in b]
    assert ids == ["9", "7", "6"]                # pas d'arrêt à la 1re connue
    assert all("win" in p for p in json.loads(json.dumps(
        next(iter_player_sync(lcu, "p"))[0]["detail"]))["players"])
