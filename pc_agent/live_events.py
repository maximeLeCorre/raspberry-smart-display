"""Événements de la partie en cours (Live Client Data), relevés vite.

`allgamedata` (tout l'état, ~1/s) suffit au tableau du Pi, mais un kill n'y serait
vu qu'au relevé suivant (jusqu'à ~1 s). Ici, un thread ne demande que les
événements NOUVEAUX (`eventdata?eventID=N`, souvent une liste vide) toutes les
~250 ms et, s'il y en a, **réveille** la boucle de l'agent : elle relit l'état
complet et pousse `myKill` aussitôt (même principe que `lcu_events.py`).
Actif SEULEMENT en partie (`set_active`, phase LCU `InProgress`) : sinon le thread
dort. Pendant le chargement, l'API ne répond pas encore : nouvel essai toutes les 2 s.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import requests

EVENT_DATA_URL = "https://127.0.0.1:2999/liveclientdata/eventdata"
POLL_SECONDS = 0.25
RETRY_SECONDS = 2.0     # partie pas encore chargée


def newest_event_id(events: list, last_id: int) -> int:
    """Plus grand EventID au-delà de `last_id` (sinon `last_id`)."""
    ids = [int(e.get("EventID", -1)) for e in events or [] if isinstance(e, dict)]
    return max([last_id, *ids])


class LiveEventWatcher:
    """Thread qui appelle `on_event()` à chaque nouvel événement de la partie."""

    def __init__(self, on_event: Callable[[], None]):
        self.on_event = on_event
        self._thread: threading.Thread | None = None
        self._active = threading.Event()
        # Session à part (une `requests.Session` ne se partage pas entre threads) :
        # la connexion TLS reste ouverte entre deux relevés.
        self._session = requests.Session()
        self._session.verify = False   # certificat auto-signé local (cf. riot_api)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="live-events", daemon=True)
            self._thread.start()

    def set_active(self, active: bool) -> None:
        """En partie (relevés) ou non (le thread dort, aucune requête)."""
        if active:
            self._active.set()
        else:
            self._active.clear()

    def _run(self) -> None:
        last_id = -1    # -1 = rien vu : les EventID repartent de 0 à chaque partie
        while True:
            if not self._active.is_set():
                last_id = -1
                self._active.wait()
            events = self._fetch(last_id + 1)
            if events is None:          # partie en chargement (ou finie)
                time.sleep(RETRY_SECONDS)
                continue
            newest = newest_event_id(events, last_id)
            if newest > last_id:
                last_id = newest
                self.on_event()
            time.sleep(POLL_SECONDS)

    def _fetch(self, from_id: int) -> list | None:
        try:
            response = self._session.get(EVENT_DATA_URL, params={"eventID": from_id}, timeout=1.0)
            if response.status_code != 200:
                return None
            return response.json().get("Events") or []
        except (requests.RequestException, ValueError, AttributeError):
            return None
