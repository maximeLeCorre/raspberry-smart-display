"""Serveur réseau du Pi : reçoit les messages JSON envoyés par le PC.

Protocole : WebSocket (lib `websockets`, API synchrone `websockets.sync`).
On utilise l'API synchrone pour ne pas avoir à gérer un event loop asyncio :
chaque connexion est traitée dans son propre thread. Les messages reçus sont
déposés dans une queue thread-safe que la boucle Pygame vient vider à chaque
frame, sans jamais être bloquée par le réseau.

Messages attendus (PC -> Pi), un objet JSON par message :
    {"type": "set_screen", "screen": "lol"}
    {"type": "data", "screen": "lol", "payload": {...}}
    {"type": "set_screen", "screen": "default"}

Deux événements internes sont aussi déposés dans la queue pour que l'appli
réagisse aux (dé)connexions :
    {"type": "_connected"}
    {"type": "_disconnected"}   -> l'appli revient à l'écran par défaut
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
        # Client connecté courant + verrou (pour envoyer depuis le thread Pygame).
        self._client = None
        self._lock = threading.Lock()

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

    def send(self, obj: dict) -> bool:
        """Envoie un message au client connecté (ex. demande d'infos joueur).

        Appelable depuis le thread Pygame. Renvoie False si pas de client.
        """
        with self._lock:
            client = self._client
        if client is None:
            return False
        try:
            client.send(json.dumps(obj))
            return True
        except Exception:
            return False

    def _handler(self, websocket) -> None:
        """Appelé pour chaque client connecté (dans un thread dédié)."""
        with self._lock:
            self._client = websocket
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
            with self._lock:
                if self._client is websocket:
                    self._client = None
            self.event_queue.put({"type": "_disconnected"})
            print("[reseau] Client déconnecté")
