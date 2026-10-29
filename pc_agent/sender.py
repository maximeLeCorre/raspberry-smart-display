"""Client réseau : envoie les messages JSON au Pi via WebSocket.

API synchrone (websockets.sync.client) pour rester dans une boucle simple,
sans asyncio. Gère une (re)connexion paresseuse et un envoi sûr.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable

from websockets.sync.client import connect


class Sender:
    def __init__(self, url: str, auth_token: str = "", ssl_context=None):
        self.url = url
        self.auth_token = auth_token or ""
        self.ssl_context = ssl_context
        self._ws = None
        self._receiver_started = False
        # Les envois viennent de 2 threads (boucle principale + récepteur, qui
        # répond aux requêtes du Pi) : on sérialise pour ne pas entrelacer.
        self._send_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def connect(self) -> None:
        """Ouvre la connexion (lève une exception si le Pi est injoignable).

        Si un jeton est configuré, on envoie immédiatement le handshake d'auth
        (premier message attendu par le Pi). Fait à chaque (re)connexion.

        Keepalive (ping_interval/ping_timeout) : indispensable pour détecter un
        lien mort après une **veille du PC**. Sans lui, les `send()` partent dans
        un socket à moitié ouvert « avec succès » (bufferisés par l'OS) sans lever
        d'exception, et la reconnexion ne se déclenche jamais. Avec, la lib ferme
        la connexion faute de pong (~ping_timeout) → les `send()` suivants lèvent
        → `send_safe` reconnecte (cf. le heartbeat de la boucle de l'agent).
        """
        opts = dict(open_timeout=3, close_timeout=3,
                    ping_interval=20, ping_timeout=20, ssl=self.ssl_context)
        try:
            # websockets ≥ 17.1 : connexion directe (hors `with`) = mode `legacy`.
            self._ws = connect(self.url, legacy=True, **opts)
        except TypeError:
            self._ws = connect(self.url, **opts)
        if self.auth_token:
            self._ws.send(json.dumps({"type": "auth", "token": self.auth_token}))
        print(f"[envoi] Connecté à {self.url}")

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def send(self, obj: dict) -> None:
        """Envoie un objet (sérialisé en JSON)."""
        if self._ws is None:
            raise ConnectionError("non connecté")
        with self._send_lock:
            self._ws.send(json.dumps(obj))

    def send_safe(self, obj: dict) -> bool:
        """Envoie en (re)connectant si besoin. Renvoie True si succès."""
        for attempt in range(2):
            try:
                if not self.connected:
                    self.connect()
                self.send(obj)
                return True
            except Exception as exc:
                # Connexion perdue : on ferme et on retentera au prochain tour.
                self.close()
                if attempt == 0:
                    continue
                print(f"[envoi] Échec d'envoi : {exc}")
        return False

    def start_receiver(self, on_message: Callable[[dict], None]) -> None:
        """Démarre un thread qui écoute les messages venant du Pi (ex. demande
        d'infos joueur) et appelle `on_message` pour chacun."""
        if self._receiver_started:
            return
        self._receiver_started = True

        def loop():
            while True:
                ws = self._ws
                if ws is None:
                    time.sleep(0.2)
                    continue
                try:
                    raw = ws.recv()
                except Exception:
                    time.sleep(0.2)
                    continue
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(data, dict):
                    try:
                        on_message(data)
                    except Exception as exc:
                        print(f"[envoi] Erreur de traitement d'un message reçu : {exc}")

        threading.Thread(target=loop, name="ws-receiver", daemon=True).start()


# Raccourcis de construction des messages du protocole. L'agent ne pousse plus
# que l'écran courant et ses données locales ; tout l'enrichissement (dossiers,
# icônes, splash, historique, bilan) est fait par le Pi lui-même.
def msg_set_screen(screen: str) -> dict:
    return {"type": "set_screen", "screen": screen}


def msg_data(screen: str, payload: dict) -> dict:
    return {"type": "data", "screen": screen, "payload": payload}


# Synchro de l'historique : l'agent envoie les parties (LCU) à stocker sur le Pi,
# par lots (`done` = dernier lot). Sert à la reprise et au push de fin de partie.
def msg_store_matches(games: list, done: bool = True) -> dict:
    return {"type": "store_matches", "games": games, "done": done}


def msg_store_player_games(riot_id: str, games: list, done: bool = True) -> dict:
    """Parties d'un AUTRE joueur (ami comparé) : le Pi n'en garde que les
    participations (stats solo/duo), pas l'historique affiché."""
    return {"type": "store_player_games", "riotId": riot_id, "games": games, "done": done}


def msg_lcu_detail(game_id, payload: dict | None) -> dict:
    """Bilan complet (10 joueurs) d'une partie, récupéré à la demande."""
    return {"type": "lcu_detail", "gameId": game_id, "payload": payload}
