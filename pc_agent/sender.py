"""Client réseau : envoie les messages JSON au Pi via WebSocket.

API synchrone (websockets.sync.client) pour rester dans une boucle simple,
sans asyncio. Gère une (re)connexion paresseuse et un envoi sûr.
"""

from __future__ import annotations

import json

from websockets.sync.client import connect


class Sender:
    def __init__(self, url: str):
        self.url = url
        self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def connect(self) -> None:
        """Ouvre la connexion (lève une exception si le Pi est injoignable)."""
        self._ws = connect(self.url, open_timeout=3)
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


# Raccourcis de construction des messages du protocole.
def msg_set_mode(mode: str) -> dict:
    return {"type": "set_mode", "mode": mode}


def msg_data(mode: str, payload: dict) -> dict:
    return {"type": "data", "mode": mode, "payload": payload}
