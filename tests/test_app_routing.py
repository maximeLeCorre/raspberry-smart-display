"""Routage des messages réseau dans l'App (écrans, verrou manuel, heartbeat)."""

from __future__ import annotations

import pygame
import pytest

import app as app_module
from modules.league import module as league_module
from config import load_config
from icon_cache import IconCache
from store import Store


@pytest.fixture
def app(tmp_path, free_port, monkeypatch):
    # Base des parties jetable (jamais le matches.db réel) ; synchro neutralisée.
    monkeypatch.setattr(league_module, "Store", lambda: Store(tmp_path / "t.db"))
    monkeypatch.setattr(league_module, "IconCache", lambda: IconCache(tmp_path / "i.db"))
    cfg = load_config(app_module.__file__.replace("app.py", "config.toml"))
    cfg.setdefault("server", {})["host"] = ""
    cfg.setdefault("weather", {})["enabled"] = False
    cfg["remote"] = {"enabled": False}      # pas de port HTTP réel
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
            "detail": {"players": [{"riotId": "Ami#EUW", "team": 100, "win": True,
                                    "kda": [1, 2, 3], "metrics": {}}]}}
    net(app, type="store_player_games", riotId="Ami#EUW", games=[game], done=False)
    net(app, type="store_player_games", riotId="Ami#EUW", games=[], done=True)
    assert app.modules["league"].store.known_games("Ami#EUW") == ["5"]
    assert app.modules["league"].store.total() == 0 and reloads == [1]


def test_synchro_demande_aussi_les_parties_de_l_ami(app):
    sent = []
    app.server.send = sent.append
    league = app.modules["league"]
    del league.sync_lcu                  # vraie méthode (neutralisée par la fixture)
    app.agent_connected = True
    league.compare_rid = "Ami#EUW"
    league.sync_lcu()
    assert [m["type"] for m in sent] == ["request_lcu_sync", "request_player_sync"]
    assert sent[1]["riotId"] == "Ami#EUW" and sent[1]["known"] == []


def test_deconnexion_revient_au_defaut(app):
    net(app, type="_connected")
    net(app, type="set_screen", screen="lol")
    net(app, type="_disconnected")
    assert app.current.name == "default"
    assert app.agent_connected is False


def test_trains_ouverts_par_le_prochain_train_pas_par_une_tuile(app):
    from modules.system.default_screen import TRAIN_BOX

    class Feed:
        def snapshot(self):
            return {"updated": 0, "error": "", "departures": [], "messages": []}

    app.screens["transit"].feed = Feed()
    app.screens["default"].enter()
    assert "trains" not in [tid for tid, _rect in app.screens["default"]._tiles]
    app.current.handle_touch(TRAIN_BOX.center)
    assert app.current.name == "transit" and app.manual_screen == "transit"


def test_ecran_ouvert_a_la_main_revient_a_l_accueil_apres_5_min_sans_appui(app):
    app.manual_screen = "server"
    app.set_screen("server")
    app._idle_return_check()
    assert app.current.name == "server"              # appui récent : on reste
    app._last_input -= 5 * 60 + 1
    app._idle_return_check()
    assert (app.current.name, app.manual_screen) == ("default", None)


def test_retour_auto_rend_la_partie_et_ne_touche_pas_aux_ecrans_de_l_agent(app):
    net(app, type="_connected")
    net(app, type="set_screen", screen="queue")
    app._last_input -= 3600
    app._idle_return_check()
    assert app.current.name == "queue"               # écran mené par l'agent : jamais rabattu
    app.manual_screen = "server"
    app.set_screen("server")
    app._idle_return_check()
    assert app.current.name == "queue"               # écran à la main oublié : retour à la partie


def test_preavis_du_retour_auto_puis_appui_pour_rester(app):
    app.manual_screen = "server"
    app.set_screen("server")
    under = app.surface.subsurface(app._banner.rect).copy()
    app._last_input -= 5 * 60 - 20
    app._idle_return_check()
    assert app._idle_left is None                    # trop tôt pour le préavis
    app._last_input -= 15
    app._idle_return_check()
    assert 0 < app._idle_left <= 10                  # bandeau dans les 10 dernières s
    dirty = app._draw_idle_banner([])
    assert app._banner.rect in dirty
    app._banner.restore(app.surface)                 # l'écran dessous est intact
    assert pygame.image.tobytes(app.surface.subsurface(app._banner.rect).copy(), "RGB") \
        == pygame.image.tobytes(under, "RGB")
    app._dispatch_touch((400, 240))                  # « touchez pour rester »
    assert app.current.name == "server" and app._idle_left is None
    app._idle_return_check()
    assert app._idle_left is None
    assert app._banner.rect in app._draw_idle_banner([])   # zone ré-affichée une fois
    assert app._draw_idle_banner([]) == []


def test_selection_affiche_le_winrate_et_change_de_periode(app):
    league = app.modules["league"]
    league.store.upsert_matches([
        {"gameId": i, "gameCreation": 1000 + i, "gameMode": "KIWI", "queueId": 2400,
         "queue": "ARAM Chaos", "duration": 900, "win": i % 3 != 0, "championId": 3,
         "championName": "Galio", "kda": [1, 1, 1], "cs": 1, "detail": None}
        for i in range(1, 7)])
    net(app, type="_connected")
    net(app, type="data", screen="champselect", payload={
        "players": [{"riotId": "Moi#EUW", "championId": 3, "championName": "Galio", "isSelf": True}],
        "bench": [{"championId": 3, "championName": "Galio"}, {"championId": 77, "championName": "Udyr"}],
        "choices": [], "gameMode": "KIWI", "queueId": 2400, "timer": {}, "bans": {}})
    net(app, type="set_screen", screen="champselect")
    cs = app.current
    assert cs.name == "champselect"
    cs.draw(app.surface)
    assert league.settings.winrate_days == 7               # défaut : 7 jours
    assert cs._records == {}                               # parties de 1970 : hors des 7 jours
    buttons = {days: rect for rect, days in cs._period_rects}
    assert sorted(buttons) == [7, 30, 90]
    cs.handle_touch(buttons[7].center)                     # re-appui sur l'actif
    assert league.settings.winrate_days == 0               # -> depuis toujours
    cs.draw(app.surface)
    assert cs._records == {3: (4, 6)}                      # Galio : 4 V sur 6 en ARAM Chaos
    assert cs._best(cs.bench)["championId"] == 3
    cs.handle_touch(buttons[30].center)
    assert league.settings.winrate_days == 30
    net(app, type="data", screen="champselect", payload={   # draft : ni banc ni choix
        "bench": [], "choices": [], "gameMode": "CLASSIC", "queueId": 420})
    league.settings.set_winrate_days(0)
    cs.draw(app.surface)
    assert cs._top == []                                  # aucune classée stockée
    net(app, type="data", screen="champselect", payload={"gameMode": "KIWI", "queueId": 2400})
    cs.draw(app.surface)
    assert cs._top == [{"championId": 3, "championName": "Galio"}]
