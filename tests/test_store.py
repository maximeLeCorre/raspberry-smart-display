"""Base SQLite des parties (historique consultable PC éteint)."""

from __future__ import annotations

from store import Store


def rec(gid, creation, mode="KIWI", win=True, detail=None):
    return {"gameId": gid, "gameCreation": creation, "gameMode": mode,
            "queueId": 2400, "queue": "ARAM Chaos", "duration": 900, "win": win,
            "championId": 1, "championName": "Annie", "kda": [5, 2, 9], "cs": 40,
            "detail": detail}


def test_upsert_ignore_les_doublons(tmp_path):
    st = Store(tmp_path / "m.db")
    assert st.upsert_matches([rec(1, 100), rec(2, 200)]) == 2
    assert st.upsert_matches([rec(2, 200), rec(3, 300)]) == 1
    assert st.total() == 3
    assert st.newest_id() == "3"


def test_query_filtre_et_trie_du_plus_recent(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_matches([rec(1, 100), rec(2, 300, mode="ARAM"), rec(3, 200)])
    rows = st.query("game_mode = ?", ("KIWI",))
    assert [r["gameId"] for r in rows] == ["3", "1"]
    assert rows[0]["kda"] == [5, 2, 9]


def test_detail_stocke_puis_complete(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_matches([rec(1, 100, detail={"players": [1]}), rec(2, 200)])
    assert st.detail(1) == {"players": [1]}
    assert st.detail(2) is None
    st.set_detail(2, {"players": [2]})
    assert st.detail(2) == {"players": [2]}


def test_winrate_par_champion_filtre_mode_file_et_periode(tmp_path):
    st = Store(tmp_path / "m.db")
    games = [rec(1, 1000), rec(2, 2000, win=False), rec(3, 3000),
             {**rec(4, 4000), "championId": 7},
             {**rec(5, 5000, mode="ARAM"), "queueId": 450},
             {**rec(6, 6000, mode="CLASSIC"), "queueId": 420},
             {**rec(7, 7000, mode="CLASSIC", win=False), "queueId": 400}]
    st.upsert_matches(games)
    assert st.champion_records("KIWI") == {1: (2, 3), 7: (1, 1)}
    assert st.champion_records("KIWI", since_ms=2000) == {1: (1, 2), 7: (1, 1)}
    assert st.champion_records("CLASSIC", 420) == {1: (1, 1)}        # classée ≠ normale
    assert st.champion_records()[1] == (4, 6)                         # sans mode : tout
    assert st.champion_stats("KIWI")[0] == (1, "Annie", 2, 3)           # le plus joué d'abord
