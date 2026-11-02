"""Événements LCU : abonnements envoyés et réveil sur les seuls événements."""

from __future__ import annotations

import json

import lcu_events
from lcu_events import EVENTS, LcuEventListener, is_event


def test_is_event_only_wamp_events():
    assert is_event(json.dumps([8, "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase",
                                {"data": "ReadyCheck"}]))
    assert not is_event("")                                  # accusé vide
    assert not is_event(json.dumps([0, "session", 1, "x"]))  # bienvenue WAMP
    assert not is_event("pas du json")


class FakeWs:
    def __init__(self, incoming):
        self.incoming = incoming
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send(self, raw):
        self.sent.append(json.loads(raw))

    def __iter__(self):
        return iter(self.incoming)


def test_listen_subscribes_and_wakes(monkeypatch):
    event = json.dumps([8, EVENTS[0], {"data": "ChampSelect"}])
    ws = FakeWs(["", event, json.dumps([0, "session"]), event])
    seen = {}

    def fake_connect(url, **kwargs):
        seen["url"], seen["headers"] = url, kwargs["additional_headers"]
        return ws

    monkeypatch.setattr(lcu_events, "connect", fake_connect)
    wakes = []
    LcuEventListener(lambda: wakes.append(1))._listen(51234, "tok")

    assert seen["url"] == "wss://127.0.0.1:51234"
    assert seen["headers"]["Authorization"].startswith("Basic ")
    assert ws.sent == [[5, e] for e in EVENTS]
    assert len(wakes) == 3   # 1 à la connexion + 2 vrais événements
