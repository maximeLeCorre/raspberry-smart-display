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

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def connect(self) -> None:
        """Ouvre la connexion (lève une exception si le Pi est injoignable).

        Si un jeton est configuré, on envoie immédiatement le handshake d'auth
        (premier message attendu par le Pi). Fait à chaque (re)connexion.
        """
        self._ws = connect(self.url, open_timeout=3, ssl=self.ssl_context)
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


# Raccourcis de construction des messages du protocole.
def msg_set_screen(screen: str) -> dict:
    return {"type": "set_screen", "screen": screen}


def msg_data(screen: str, payload: dict) -> dict:
    return {"type": "data", "screen": screen, "payload": payload}


def msg_player_info(puuid: str, info: dict) -> dict:
    return {"type": "player_info", "puuid": puuid, "info": info}


def msg_icon(champion_id, icon_b64) -> dict:
    return {"type": "icon", "championId": champion_id, "iconB64": icon_b64}


def msg_splash(champion_id, splash_b64) -> dict:
    return {"type": "splash", "championId": champion_id, "splashB64": splash_b64}
