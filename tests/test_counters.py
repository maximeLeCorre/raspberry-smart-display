"""Écarts : compteurs en direct, tendance sur 1 min, timelines LCU (agent ->
store, une à la fois), navigation tableau <-> écarts <-> bilan, rendu."""

from __future__ import annotations

from modules.league.counters_screen import fmt, team_totals, trend
from phases import build_lcu_timeline
from test_app_routing import app, net  # noqa: F401  (fixture)
from test_phases import FakeLcu


def live(t, kills=0, items=(3153,)):
    players = [{"name": "Moi", "riotId": "Moi#EUW", "champion": "Ahri", "championId": 103,
                "team": "ORDER", "isSelf": True, "k": kills, "cs": t // 10, "level": 3,
                "items": list(items)},
               {"name": "Lui", "riotId": "Lui#EUW", "champion": "Garen", "championId": 86,
                "team": "CHAOS", "k": 0, "cs": 1, "level": 2, "items": [1037]}]
    return {"game_time": t, "game_mode": "KIWI", "players": players, "scores": {}}


def test_compteurs_a_chaque_message_releve_toutes_les_10_s(app):
    league = app.modules["league"]
    league.items._prices = {3153: 3200, 1037: 875}         # table des prix chargée
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    for t in (0, 4, 10, 15, 21):
        net(app, type="data", screen="lol", payload=live(t, kills=t // 10))
    assert [f["t"] for f in league.live["frames"]] == [0, 10, 21]
    cur = league.live["current"]
    assert cur["t"] == 21 and cur["gold"] == [3200, 875] and cur["kills"] == [2, 0]
    assert team_totals(league.live, cur, "gold") == (3200, 875)
    assert [p["team"] for p in league.live["players"]] == [100, 200]


def test_or_inconnu_tant_que_les_prix_ne_sont_pas_charges(app):
    league = app.modules["league"]
    league._items_loading = True                             # pas de réseau en test
    net(app, type="set_screen", screen="lol")
    net(app, type="data", screen="lol", payload=live(0))
    assert team_totals(league.live, league.live["current"], "gold") == (None, None)


def test_nouvelle_partie_remet_les_ecarts_a_zero(app):
    league = app.modules["league"]
    net(app, type="set_screen", screen="lol")
    net(app, type="data", screen="lol", payload=live(300))
    net(app, type="data", screen="lol", payload=live(5))      # temps qui recule
    assert [f["t"] for f in league.live["frames"]] == [5]


def test_tendance_sur_la_derniere_minute():
    series = {"players": [{"team": 100, "isSelf": True}, {"team": 200}],
              "frames": [{"t": 0, "gold": [500, 500]}, {"t": 60, "gold": [1500, 1000]},
                         {"t": 120, "gold": [2500, 1600]}]}
    assert team_totals(series, series["frames"][-1], "gold") == (2500, 1600)
    assert trend(series, "gold") == 400                    # écart 500 -> 900
    assert trend({"players": series["players"], "frames": series["frames"][:1]}, "gold") is None
    assert fmt("gold", 900, signed=True) == "+900" and fmt("gold", -3500, signed=True) == "-3.5k"
    assert fmt("level", 0.4, signed=True) == "+0.4"


def test_timelines_demandees_une_a_la_fois_puis_stockees(app):
    league = app.modules["league"]
    sent = []
    app.server.send = sent.append
    net(app, type="_connected")
    games = [{"gameId": g, "gameCreation": g, "gameMode": "KIWI", "queueId": 2400,
              "duration": 600, "win": True, "championId": 1, "kda": [0, 0, 0], "cs": 0,
              "detail": {"players": []}} for g in (1, 2)]
    net(app, type="store_matches", games=games, done=True)
    asked = [m["gameId"] for m in sent if m["type"] == "request_lcu_timeline"]
    assert asked == ["2"]                                    # la plus récente d'abord
    net(app, type="lcu_timeline", gameId="2", payload={"players": [], "frames": [{"t": 0}]})
    net(app, type="lcu_timeline", gameId="1", payload=None)  # indisponible
    asked = [m["gameId"] for m in sent if m["type"] == "request_lcu_timeline"]
    assert asked == ["2", "1"]
    assert league.store.timeline("2") and league.store.without_timeline(["1", "2"]) == ["1"]
    assert league.game_series("1") == (None, "unavailable")


def test_navigation_tableau_ecarts_bilan(app):
    league = app.modules["league"]
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    league.open_counters()
    assert app.current.name == "counters" and app.manual_screen is None
    app.current._last_signature = None                       # set_screen l'a déjà dessiné
    assert app.current.draw(app.surface)                     # « dès les premières… »
    league.close_counters(live=True)
    assert app.current.name == "lol"
    league.store.set_timeline("9", {"players": [{"team": 100, "isSelf": True}, {"team": 200}],
                                    "frames": [{"t": 0, "gold": [500, 500], "kills": [0, 0],
                                                "cs": [0, 0], "level": [1, 1]},
                                               {"t": 60, "gold": [1200, 900], "kills": [1, 0],
                                                "cs": [5, 4], "level": [3, 3]}]})
    league.postgame_game_id = "9"
    league.open_counters_review()
    app.current._last_signature = None
    assert app.current.draw(app.surface)                     # rendu sans erreur
    league.close_counters(live=False)
    assert app.current.name == "postgame" and app.manual_screen == "postgame"


class TimelineLcu(FakeLcu):
    def get_json(self, path, **_kw):
        if "game-timelines" in path:
            pf = {str(pid): {"totalGold": 500 * pid, "minionsKilled": pid,
                             "jungleMinionsKilled": 1, "level": 2} for pid in range(1, 11)}
            return {"frames": [
                {"timestamp": 0, "participantFrames": pf, "events": []},
                {"timestamp": 60000, "participantFrames": pf, "events": [
                    {"type": "CHAMPION_KILL", "killerId": 3, "timestamp": 59000},
                    {"type": "CHAMPION_KILL", "killerId": 3, "timestamp": 61000}]},
                {"timestamp": 70000, "participantFrames": pf, "events": []}]}
        return super().get_json(path)


def test_timeline_lcu_format_commun():
    tl = build_lcu_timeline(TimelineLcu([7]), 7)
    assert [f["t"] for f in tl["frames"]] == [0, 60, 70]
    assert tl["frames"][1]["kills"][2] == 1 and tl["frames"][2]["kills"][2] == 2
    assert tl["frames"][0]["gold"][2] == 1500 and tl["frames"][0]["cs"][2] == 4
    me = [p for p in tl["players"] if p["isSelf"]]
    assert me[0]["riotId"] == "J3#EUW" and tl["estimated"] is False
    assert build_lcu_timeline(TimelineLcu([]), 42) is None


def test_ecarts_par_defaut_en_partie(app):
    league = app.modules["league"]
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    assert app.current.name == "counters" and app.screens["counters"].live
    league.close_counters(live=True)                         # bouton TABLEAU
    assert app.current.name == "lol"
    net(app, type="set_screen", screen="lol")                # heartbeat : reste au tableau
    assert app.current.name == "lol"
    app.manual_screen = "server"
    app.set_screen("server")
    app.join_screen()                                        # « Rejoindre » depuis l'accueil
    assert app.current.name == "counters"
