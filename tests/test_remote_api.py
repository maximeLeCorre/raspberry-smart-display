"""API télécommande : long polling, jeton, actions vérifiées par le module League."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import app as app_module
from config import load_config
from icon_cache import IconCache
from modules.league import module as league_module
from remote_api import RemoteState
from store import Store

TOKEN = "jeton-test"
READY = {"state": "readycheck", "remaining": 9, "response": "None"}
CHAMPSELECT = {"players": [{"isSelf": True, "championId": 1, "championName": "Annie"}],
               "bench": [{"championId": 22, "championName": "Ashe"}],
               "rerolls": 1, "timer": {"phase": "Sélection", "left": 50}}


@pytest.fixture
def app(tmp_path, free_port, monkeypatch):
    monkeypatch.setattr(league_module, "Store", lambda: Store(tmp_path / "t.db"))
    monkeypatch.setattr(league_module, "IconCache", lambda: IconCache(tmp_path / "i.db"))
    cfg = load_config(app_module.__file__.replace("app.py", "config.toml"))
    cfg.setdefault("server", {})["host"] = ""
    cfg.setdefault("weather", {})["enabled"] = False
    cfg["remote"] = {"enabled": True, "port": 0}
    a = app_module.App(cfg, fullscreen=False, scale=1, monitor=None, debug=False,
                       host="127.0.0.1", port=free_port, remote_token=TOKEN)
    a.modules["league"].sync_lcu = lambda: None
    sent = []
    a.server.send = lambda obj: sent.append(obj) or True   # agent factice
    a.sent = sent
    # Boucle principale réduite au traitement réseau (ce que fait `run`).
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            a._handle_network()
            time.sleep(0.01)
    threading.Thread(target=loop, daemon=True).start()
    yield a
    stop.set()
    a.shutdown()


def call(app, method, path, body=None, token=TOKEN):
    req = urllib.request.Request(f"http://127.0.0.1:{app.remote.port}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def push(app, **msg):
    app.net_queue.put(msg)


def test_state_wait_returns_on_change():
    state = RemoteState()
    state.publish({"screen": "default"})
    threading.Timer(0.1, state.publish, args=({"screen": "queue"},)).start()
    start = time.monotonic()
    version, snap = state.wait(1, timeout=5)
    assert snap == {"screen": "queue"} and version == 2
    assert time.monotonic() - start < 1
    state.publish({"screen": "queue"})        # identique : pas de nouvelle version
    assert state.version == 2


def test_jeton_requis(app):
    assert call(app, "GET", "/state", token="faux")[0] == 401
    assert call(app, "GET", "/state", token="")[0] == 401


def test_long_polling_ready_check_puis_accepter(app):
    push(app, type="_connected")
    time.sleep(0.1)
    status, state = call(app, "GET", "/state?wait=0")
    assert status == 200 and state["agent"] and state["screen"] == "default"

    def later():
        time.sleep(0.2)
        push(app, type="set_screen", screen="queue")
        push(app, type="data", screen="queue", payload=READY)
    threading.Thread(target=later).start()
    start = time.monotonic()
    status, state = call(app, "GET", f"/state?v={state['v']}&wait=5")
    assert time.monotonic() - start < 1.5      # réveillé par le changement, pas le délai
    assert state["screen"] == "queue" and state["queue"]["state"] == "readycheck"

    assert call(app, "POST", "/action", {"action": "accept"}) == (200, {"ok": True})
    assert {"type": "lcu_action", "action": "accept"} in app.sent


def test_actions_refusees_si_etat_perime(app):
    assert call(app, "POST", "/action", {"action": "accept"})[0] == 503   # PC absent
    push(app, type="_connected")
    time.sleep(0.1)
    assert call(app, "POST", "/action", {"action": "accept"})[0] == 409   # pas de ready-check
    assert call(app, "POST", "/action", {"action": "danse"})[0] == 400


def test_banc_aram(app):
    push(app, type="_connected")
    push(app, type="set_screen", screen="champselect")
    push(app, type="data", screen="champselect", payload=CHAMPSELECT)
    time.sleep(0.1)
    state = call(app, "GET", "/state?wait=0")[1]
    assert state["champselect"]["me"]["championName"] == "Annie"
    assert state["champselect"]["bench"] == CHAMPSELECT["bench"]

    assert call(app, "POST", "/action", {"action": "swap", "championId": 99})[0] == 409
    assert call(app, "POST", "/action", {"action": "swap", "championId": 22})[0] == 200
    assert {"type": "lcu_action", "action": "swap", "championId": 22} in app.sent
    assert call(app, "POST", "/action", {"action": "reroll"})[0] == 200


def test_icone_de_champion(app, monkeypatch):
    png = b"\x89PNG-factice"
    monkeypatch.setattr(league_module, "icon_bytes",
                        lambda cid, cache: png if cid == 22 else None)
    url = f"http://127.0.0.1:{app.remote.port}/asset/league/icon/22"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.read() == png and resp.headers["Content-Type"] == "image/png"
        assert "max-age" in resp.headers["Cache-Control"]
    assert call(app, "GET", "/asset/league/icon/99")[0] == 404
    assert call(app, "GET", "/asset/league/icon/abc")[0] == 404
    assert call(app, "GET", "/asset/inconnu/icon/22")[0] == 404
    assert call(app, "GET", "/asset/league/icon/22", token="faux")[0] == 401
