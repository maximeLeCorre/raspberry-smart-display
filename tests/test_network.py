"""Serveur WebSocket du Pi : authentification et reconnexion de l'agent."""

from __future__ import annotations

import json
import queue
import time

import pytest
from websockets.sync.client import connect

from network import NetworkServer


def _drain(q, wait: float = 0.3) -> list[str]:
    time.sleep(wait)
    out = []
    while not q.empty():
        out.append(q.get()["type"])
    return out


@pytest.fixture
def server(free_port):
    servers = []

    def make(token: str = ""):
        q = queue.Queue()
        s = NetworkServer("127.0.0.1", free_port, q, auth_token=token)
        s.start()
        time.sleep(0.2)
        servers.append(s)
        return s, q, f"ws://127.0.0.1:{free_port}"
    yield make
    for s in servers:
        s.stop()


def test_reconnexion_apres_veille_garde_l_agent_connecte(server):
    """L'ancien lien (à moitié ouvert après une veille) tombe APRÈS la
    reconnexion : il ne doit pas déclarer l'agent déconnecté."""
    s, q, url = server()
    old = connect(url, legacy=True)
    new = connect(url, legacy=True)
    old.close()
    assert _drain(q) == ["_connected", "_connected"]
    assert s.send({"type": "ping"})          # le nouveau client reste joignable
    new.close()
    assert _drain(q) == ["_disconnected"]


def test_jeton_invalide_refuse(server):
    s, q, url = server(token="secret")
    ws = connect(url, legacy=True)
    ws.send(json.dumps({"type": "auth", "token": "faux"}))
    assert json.loads(ws.recv(timeout=2)) == {"type": "auth_result", "ok": False}
    ws.close()
    assert _drain(q) == []


def test_jeton_valide_accepte(server):
    s, q, url = server(token="secret")
    ws = connect(url, legacy=True)
    ws.send(json.dumps({"type": "auth", "token": "secret"}))
    ws.send(json.dumps({"type": "set_screen", "screen": "lol"}))
    assert _drain(q) == ["_connected", "set_screen"]
    ws.close()
