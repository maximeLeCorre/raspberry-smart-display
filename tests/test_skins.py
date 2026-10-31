"""Skins joués : relevés en partie (Live Client), rattachés à la partie synchronisée,
restitués par l'historique et le bilan ; skin choisi en sélection (LCU)."""

from __future__ import annotations

from champ_select import _skin_num
from test_app_routing import app, net  # noqa: F401  (fixture)

ME, MATE = "Moi#EUW", "Pote#EUW"


def game(gid, creation, my_champ=21):
    players = [{"riotId": ME, "championId": my_champ, "team": 100, "win": True,
                "isSelf": True, "kda": [1, 2, 3], "metrics": {}},
               {"riotId": MATE, "championId": 103, "team": 100, "win": True,
                "kda": [0, 0, 0], "metrics": {}}]
    return {"gameId": gid, "gameCreation": creation, "gameMode": "KIWI", "queueId": 2400,
            "queue": "ARAM Chaos", "duration": 600, "win": True, "championId": my_champ,
            "championName": "MF", "kda": [1, 2, 3], "cs": 10,
            "detail": {"win": True, "players": players, "me": {"championId": my_champ}}}


def test_skins_de_la_partie_rattaches_a_son_arrivee(app):
    league = app.modules["league"]
    net(app, type="_connected")
    net(app, type="store_matches", games=[game(1, 1000)], done=True)   # partie précédente
    net(app, type="set_screen", screen="lol")
    net(app, type="data", screen="lol", payload={"players": [
        {"riotId": ME, "championId": 21, "skinId": 14, "isSelf": True},
        {"riotId": MATE, "championId": 103, "skinId": 3}]})
    net(app, type="set_screen", screen="postgame")
    net(app, type="store_matches", games=[game(2, 2000)], done=True)   # la partie jouée

    assert league.store.query()[0]["skinId"] == 14                     # historique
    assert league.store.query()[1]["skinId"] == 0                      # ancienne : base
    detail = league.store.detail(2)
    assert [p["skinId"] for p in detail["players"]] == [14, 3]         # bilan
    assert detail["me"]["skinId"] == 14


def test_skins_pas_rattaches_a_une_autre_partie(app):
    league = app.modules["league"]
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    net(app, type="data", screen="lol", payload={"players": [
        {"riotId": ME, "championId": 21, "skinId": 14, "isSelf": True}]})
    # Une partie arrive, mais pas avec mon champion de la partie en cours.
    net(app, type="store_matches", games=[game(7, 3000, my_champ=86)], done=True)
    assert league.store.query()[0]["skinId"] == 0


def test_numero_de_skin_en_selection():
    assert _skin_num(21007, 21) == 7
    assert _skin_num(21014, 21) == 14          # chroma
    assert _skin_num(103002, 21) == 0          # skin d'un autre champion (intention)
    assert _skin_num(None, 21) == 0
