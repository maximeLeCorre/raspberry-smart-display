"""Nos kills en partie (vibration de la montre) : dernier kill + multikill."""

from __future__ import annotations

from riot_api import my_last_kill

EVENTS = [
    {"EventID": 1, "EventName": "ChampionKill", "KillerName": "Autre", "EventTime": 50.0},
    {"EventID": 2, "EventName": "ChampionKill", "KillerName": "Moi", "EventTime": 60.0},
    {"EventID": 3, "EventName": "ChampionKill", "KillerName": "Moi#EUW", "EventTime": 64.0},
    {"EventID": 4, "EventName": "Multikill", "KillerName": "Moi", "KillStreak": 2, "EventTime": 64.0},
    {"EventID": 5, "EventName": "ChampionKill", "KillerName": "Autre", "EventTime": 70.0},
]


def test_dernier_kill_et_multikill():
    assert my_last_kill(EVENTS, "Moi") == {"id": 3, "streak": 2}
    assert my_last_kill(EVENTS[:2], "Moi") == {"id": 2, "streak": 1}
    assert my_last_kill(EVENTS[:1], "Moi") is None
    assert my_last_kill(EVENTS, "") is None
