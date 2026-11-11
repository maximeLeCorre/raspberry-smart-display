"""Événements temps réel de la LCU (WebSocket local du client League).

La LCU pousse ses changements sur `wss://127.0.0.1:<port>` (protocole WAMP 1 :
`[5, "<événement>"]` = s'abonner, `[8, "<événement>", {...}]` = un événement).
Même authentification que le REST (Basic riot:<token>, certificat auto-signé).

On ne s'abonne qu'aux événements que le projet affiche (le flux complet
`OnJsonApiEvent` = chat, boutique, patcher… des centaines de messages/min).
L'événement ne sert qu'à **réveiller** la boucle de l'agent : elle relit l'état
en REST comme d'habitude (un seul chemin de code ; si le WebSocket tombe, on
retombe sur le rythme normal `update_interval`, sans rien perdre).
"""

from __future__ import annotations

import base64
import json
import ssl
import threading
import time
from typing import Callable

from websockets.sync.client import connect

from lcu import find_lcu_credentials

EVENTS = (
    "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase",   # changement d'écran
    "OnJsonApiEvent_lol-matchmaking_v1_ready-check",   # ready-check (Accepter)
    "OnJsonApiEvent_lol-matchmaking_v1_search",        # entrée/sortie de file
    "OnJsonApiEvent_lol-lobby_v2_lobby",               # lobby : joueurs, invitations
    "OnJsonApiEvent_lol-lobby_v2_received-invitations",  # on m'invite (notif montre)
    "OnJsonApiEvent_lol-chat_v1_conversations",        # message reçu (notif montre)
    "OnJsonApiEvent_lol-chat_v1_friends",              # ami connecté / sort de partie
    "OnJsonApiEvent_lol-champ-select_v1_session",      # sélection / banc
    # Choix parmi 2-3 champions (ARAM Chaos) : publié juste APRÈS la session.
    "OnJsonApiEvent_lol-lobby-team-builder_champ-select_v1_subset-champion-list",
)
WAMP_SUBSCRIBE = 5
WAMP_EVENT = 8
# Client fermé / connexion perdue : nouvel essai après ce délai.
RETRY_SECONDS = 3.0


def is_event(raw) -> bool:
    """Le message brut est-il un événement WAMP (et non un accusé, vide…) ?"""
    if not raw:
        return False
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(msg, list) and len(msg) >= 3 and msg[0] == WAMP_EVENT


class LcuEventListener:
    """Thread qui écoute la LCU et appelle `on_event()` à chaque changement."""

    def __init__(self, on_event: Callable[[], None]):
        self.on_event = on_event
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="lcu-events", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            creds = find_lcu_credentials()
            if creds is not None:
                try:
                    self._listen(*creds)
                except Exception as exc:
                    print(f"[lcu-events] Connexion perdue ({exc.__class__.__name__}), repli sur le rythme normal.")
            time.sleep(RETRY_SECONDS)

    def _listen(self, port: int, token: str) -> None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False      # certificat auto-signé du client (local)
        ctx.verify_mode = ssl.CERT_NONE
        auth = base64.b64encode(f"riot:{token}".encode()).decode()
        # ping_interval=None : la LCU n'a pas à prouver qu'elle vit (client fermé
        # = socket fermé côté local, détecté immédiatement).
        with connect(f"wss://127.0.0.1:{port}", ssl=ctx, open_timeout=3,
                     additional_headers={"Authorization": f"Basic {auth}"},
                     ping_interval=None, max_size=None) as ws:
            for event in EVENTS:
                ws.send(json.dumps([WAMP_SUBSCRIBE, event]))
            print("[lcu-events] Abonné aux événements du client.")
            self.on_event()  # état possiblement changé pendant la connexion
            for raw in ws:
                if is_event(raw):
                    self.on_event()
