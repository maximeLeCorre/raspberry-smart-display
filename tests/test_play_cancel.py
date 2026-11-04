"""Bouton « Jouer » : un ré-appui pendant l'enchaînement l'arrête."""

from __future__ import annotations

import threading
import time

from sources import league
from sources.league import LeagueSource


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_safe(self, obj):
        self.sent.append(obj)
        return True


def test_reappui_annule_le_lancement_en_boucle(monkeypatch):
    src = LeagueSource({})
    monkeypatch.setattr(src.lcu, "gameflow_phase", lambda: None)   # client fermé

    def launch_forever():                    # mise à jour impossible : ne finit jamais
        while True:
            src._pause(0.05)
    monkeypatch.setattr(src, "_launch_client", launch_forever)
    monkeypatch.setattr(league.time, "sleep", lambda s: None)       # message final
    sender = FakeSender()

    src.handle_request({"type": "lcu_action", "action": "play"}, sender)
    time.sleep(0.2)
    assert src._playing
    src.handle_request({"type": "lcu_action", "action": "play_cancel"}, sender)
    deadline = time.monotonic() + 2
    while src._playing and time.monotonic() < deadline:
        time.sleep(0.02)

    assert not src._playing
    statuses = [m["payload"] for m in sender.sent if m.get("type") == "data"]
    assert {"playStatus": "Lancement annulé", "playBusy": False} in statuses
    assert statuses[-1]["playStatus"] == ""          # bandeau effacé ensuite
    assert all(s["playBusy"] for s in statuses[:2])  # étapes en cours = annulables


def test_annuler_sans_enchainement_ne_fait_rien():
    src = LeagueSource({})
    assert src.handle_request({"type": "lcu_action", "action": "play_cancel"}, FakeSender())
    assert not src._cancel.is_set()
