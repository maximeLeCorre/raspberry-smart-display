"""Réveil rapide de l'agent sur les événements de la partie (live_events.py)."""

from __future__ import annotations

from live_events import newest_event_id


def test_plus_grand_id_nouveau():
    events = [{"EventID": 4}, {"EventID": 6}, {"EventID": 5}]
    assert newest_event_id(events, 3) == 6
    assert newest_event_id(events, 6) == 6      # déjà vus : pas de réveil
    assert newest_event_id([], 2) == 2
    assert newest_event_id(None, -1) == -1
