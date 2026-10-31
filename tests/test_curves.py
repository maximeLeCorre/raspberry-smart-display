"""Courbes : relevé en direct, timelines LCU (agent -> store, une à la fois),
navigation tableau <-> courbes <-> bilan, rendu sans erreur."""

from __future__ import annotations

from modules.league.curves_screen import axis_ticks, team_series
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


def test_releve_en_direct_toutes_les_10_s(app):
    league = app.modules["league"]
    league.items._prices = {3153: 3200, 1037: 875}         # table des prix chargée
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    for t in (0, 4, 10, 15, 21):
        net(app, type="data", screen="lol", payload=live(t, kills=t // 10))
    frames = league.live["frames"]
    assert [f["t"] for f in frames] == [0, 10, 21]
    assert frames[-1]["gold"] == [3200, 875] and frames[-1]["kills"] == [2, 0]
    assert [p["team"] for p in league.live["players"]] == [100, 200]
    ally, enemy = team_series(league.live, "gold")
    assert ally[-1] == (21, 3200) and enemy[-1] == (21, 875)


def test_or_inconnu_tant_que_les_prix_ne_sont_pas_charges(app):
    league = app.modules["league"]
    league._items_loading = True                             # pas de réseau en test
    net(app, type="set_screen", screen="lol")
    net(app, type="data", screen="lol", payload=live(0))
    assert league.live["frames"][0]["gold"] == [None, None]
    assert team_series(league.live, "gold") == ([], [])


def test_nouvelle_partie_remet_les_courbes_a_zero(app):
    league = app.modules["league"]
    net(app, type="set_screen", screen="lol")
    net(app, type="data", screen="lol", payload=live(300))
    net(app, type="data", screen="lol", payload=live(5))      # temps qui recule
    assert [f["t"] for f in league.live["frames"]] == [5]


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
    assert league.curves_series("1") == (None, "unavailable")


def test_navigation_tableau_courbes_bilan(app):
    league = app.modules["league"]
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    league.open_curves()
    assert app.current.name == "curves" and app.manual_screen is None
    app.current.draw(app.surface)                            # « quelques secondes… »
    league.close_curves(live=True)
    assert app.current.name == "lol"
    league.store.set_timeline("9", {"players": [{"team": 100, "isSelf": True}, {"team": 200}],
                                    "frames": [{"t": 0, "gold": [500, 500]},
                                               {"t": 60, "gold": [1200, 900]}]})
    league.postgame_game_id = "9"
    league.open_curves_review()
    curves = app.screens["curves"]
    for view in ("teams", "diff", "players"):
        curves.view, curves._last_signature = view, None
        assert app.current.draw(app.surface)                  # rendu sans erreur
    league.close_curves(live=False)
    assert app.current.name == "postgame" and app.manual_screen == "postgame"


def test_graduations_rondes():
    assert axis_ticks(0, 22814) == [0, 5000, 10000, 15000, 20000, 25000]
    assert axis_ticks(-3500, 3500) == [-4000, -2000, 0, 2000, 4000]


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
