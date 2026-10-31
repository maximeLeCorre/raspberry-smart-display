"""Routage des messages réseau dans l'App (écrans, verrou manuel, heartbeat)."""

from __future__ import annotations

import pytest

import app as app_module
from modules.league import module as league_module
from config import load_config
from store import Store


@pytest.fixture
def app(tmp_path, free_port, monkeypatch):
    # Base des parties jetable (jamais le matches.db réel) ; synchro neutralisée.
    monkeypatch.setattr(league_module, "Store", lambda: Store(tmp_path / "t.db"))
    cfg = load_config(app_module.__file__.replace("app.py", "config.toml"))
    cfg.setdefault("server", {})["host"] = ""
    cfg.setdefault("weather", {})["enabled"] = False
    a = app_module.App(cfg, fullscreen=False, scale=1, monitor=None, debug=False,
                       host="127.0.0.1", port=free_port)
    a.modules["league"].sync_lcu = lambda: None
    yield a
    a.shutdown()


def net(app, **msg):
    app._on_network(msg)


def test_heartbeat_ne_ferme_pas_un_ecran_ouvert_a_la_main(app):
    net(app, type="_connected")
    app.manual_screen = "server"
    app.set_screen("server")
    for _ in range(3):
        net(app, type="set_screen", screen="default")
    assert app.current.name == "server"


def test_ecran_force_a_la_main_resiste_a_l_agent_puis_fin_d_activite(app):
    net(app, type="_connected")
    app.manual_screen = "server"
    app.set_screen("server")
    net(app, type="set_screen", screen="queue")
    assert app.current.name == "server"          # verrou manuel respecté
    assert app.joinable_screen() == "queue"      # bandeau « Rejoindre »
    net(app, type="set_screen", screen="default")
    assert app.current.name == "default"         # vraie fin d'activité


def test_agent_suit_les_phases_sans_verrou(app):
    net(app, type="_connected")
    net(app, type="set_screen", screen="queue")
    assert app.current.name == "queue"
    net(app, type="set_screen", screen="queue")  # heartbeat : no-op
    net(app, type="set_screen", screen="champselect")
    assert app.current.name == "champselect"


def test_bilan_de_fin_non_reinitialise_par_le_heartbeat(app):
    net(app, type="_connected")
    net(app, type="set_screen", screen="postgame")
    calls = []
    app.modules["league"]._show_postgame = lambda detail: calls.append(detail)
    net(app, type="set_screen", screen="postgame")
    assert calls == []


def test_parties_de_l_ami_stockees_et_stats_rafraichies(app):
    net(app, type="_connected")
    app.modules["league"].open_stats()
    reloads = []
    app.screens["stats"].reload = lambda: reloads.append(1)
    game = {"gameId": 5, "gameMode": "KIWI", "queueId": 2400, "duration": 600,
            "detail": {"players": [{"riotId": "Matte mwa#EUW", "team": 100, "win": True,
                                    "kda": [1, 2, 3], "metrics": {}}]}}
    net(app, type="store_player_games", riotId="Matte mwa#EUW", games=[game], done=False)
    net(app, type="store_player_games", riotId="Matte mwa#EUW", games=[], done=True)
    assert app.modules["league"].store.known_games("Matte mwa#EUW") == ["5"]
    assert app.modules["league"].store.total() == 0 and reloads == [1]


def test_synchro_demande_aussi_les_parties_de_l_ami(app):
    sent = []
    app.server.send = sent.append
    league = app.modules["league"]
    del league.sync_lcu                  # vraie méthode (neutralisée par la fixture)
    app.agent_connected = True
    league.compare_rid = "Matte mwa#EUW"
    league.sync_lcu()
    assert [m["type"] for m in sent] == ["request_lcu_sync", "request_player_sync"]
    assert sent[1]["riotId"] == "Matte mwa#EUW" and sent[1]["known"] == []


def test_deconnexion_revient_au_defaut(app):
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    net(app, type="_disconnected")
    assert app.current.name == "default"
    assert app.agent_connected is False
