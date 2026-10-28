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

Authentification (optionnelle) : si un jeton est configuré (DISPLAY_AUTH_TOKEN
dans .env), le premier message du client DOIT être {"type":"auth","token":...}
avec le bon jeton, sinon la connexion est refusée et fermée (sans jamais devenir
le client courant). Jeton vide = authentification désactivée (on accepte tout le
réseau local, comportement historique pour les tests). Cela protège aussi d'un
client fantôme : tant qu'il n'est pas authentifié, il n'écrase pas le vrai agent.
"""

from __future__ import annotations

import hmac
import json
import queue
import threading

from websockets.sync.server import serve


class NetworkServer:
    """Serveur WebSocket léger tournant dans un thread démon."""

    # Délai max accordé au client pour envoyer son message d'auth (secondes).
    AUTH_TIMEOUT = 5.0

    def __init__(self, host: str, port: int, event_queue: "queue.Queue[dict]",
                 auth_token: str = "", ssl_context=None):
        self.host = host
        self.port = port
        self.event_queue = event_queue
        self.auth_token = auth_token or ""
        self.ssl_context = ssl_context
        self._server = None
        self._thread: threading.Thread | None = None
        # Client connecté courant + verrou (pour envoyer depuis le thread Pygame).
        self._client = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Démarre le serveur en arrière-plan (non bloquant)."""
        self._server = serve(self._handler, self.host, self.port, ssl=self.ssl_context)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="websocket-server", daemon=True
        )
        self._thread.start()
        scheme = "wss" if self.ssl_context else "ws"
        etat_auth = "jeton requis" if self.auth_token else "ouverte (aucun jeton)"
        print(f"[reseau] Serveur WebSocket en écoute sur {scheme}://{self.host}:{self.port} "
              f"(TLS : {'oui' if self.ssl_context else 'non'}, authentification : {etat_auth})")

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

    def _authenticate(self, websocket) -> bool:
        """Vérifie le handshake d'auth. Renvoie True si l'accès est accordé.

        Sans jeton configuré : toujours True (accès ouvert). Sinon, on attend le
        premier message et on exige {"type":"auth","token":<jeton exact>}. La
        connexion est fermée sans devenir le client courant en cas d'échec.
        """
        if not self.auth_token:
            return True
        try:
            first = websocket.recv(timeout=self.AUTH_TIMEOUT)
            data = json.loads(first)
            ok = (isinstance(data, dict) and data.get("type") == "auth"
                  and isinstance(data.get("token"), str)
                  and hmac.compare_digest(data["token"].encode(), self.auth_token.encode()))
        except Exception:
            ok = False
        if not ok:
            try:
                websocket.send(json.dumps({"type": "auth_result", "ok": False}))
            except Exception:
                pass
            print("[reseau] Connexion refusée (authentification invalide)")
        return ok

    def _handler(self, websocket) -> None:
        """Appelé pour chaque client connecté (dans un thread dédié)."""
        if not self._authenticate(websocket):
            return  # socket fermée en sortant ; pas de _connected émis
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
            # Après une veille du PC, l'agent se reconnecte AVANT que l'ancien
            # lien (à moitié ouvert) ne tombe par timeout de ping : seul le
            # client COURANT qui part signifie « agent déconnecté ».
            with self._lock:
                current = self._client is websocket
                if current:
                    self._client = None
            if current:
                self.event_queue.put({"type": "_disconnected"})
                print("[reseau] Client déconnecté")
            else:
                print("[reseau] Ancienne connexion fermée (remplacée)")
