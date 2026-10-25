"""Serveur réseau du Pi : reçoit les messages JSON envoyés par le PC.

Protocole : WebSocket (lib `websockets`, API synchrone `websockets.sync`).
On utilise l'API synchrone pour ne pas avoir à gérer un event loop asyncio :
chaque connexion est traitée dans son propre thread. Les messages reçus sont
déposés dans une queue thread-safe que la boucle Pygame vient vider à chaque
frame, sans jamais être bloquée par le réseau.

Messages attendus (PC -> Pi), un objet JSON par message :
    {"type": "set_mode", "mode": "lol"}
    {"type": "data", "mode": "lol", "payload": {...}}
    {"type": "set_mode", "mode": "default"}

Deux événements internes sont aussi déposés dans la queue pour que l'appli
réagisse aux (dé)connexions :
    {"type": "_connected"}
    {"type": "_disconnected"}   -> l'appli revient au mode par défaut
"""

from __future__ import annotations

import json
import queue
import threading

from websockets.sync.server import serve


class NetworkServer:
    """Serveur WebSocket léger tournant dans un thread démon."""

    def __init__(self, host: str, port: int, event_queue: "queue.Queue[dict]"):
        self.host = host
        self.port = port
        self.event_queue = event_queue
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Démarre le serveur en arrière-plan (non bloquant)."""
        self._server = serve(self._handler, self.host, self.port)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="websocket-server", daemon=True
        )
        self._thread.start()
        print(f"[reseau] Serveur WebSocket en écoute sur ws://{self.host}:{self.port}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()

    def _handler(self, websocket) -> None:
        """Appelé pour chaque client connecté (dans un thread dédié)."""
        self.event_queue.put({"type": "_connected"})
        print("[reseau] Client connecté")
        try:
            for message in websocket:
                try:
                    data = json.loads(message)
                except (json.JSONDecodeError, TypeError):
                    continue  # on ignore les messages malformés
                if isinstance(data, dict):
                    self.event_queue.put(data)
        except Exception:
            # Déconnexion brutale, erreur de socket : on sort proprement.
            pass
        finally:
            self.event_queue.put({"type": "_disconnected"})
            print("[reseau] Client déconnecté")
