"""Accès à l'API locale du **Riot Client** (le lanceur commun de Riot).

Distinct de la LCU (`lcu.py`, le client League). Sert à **démarrer League via le
Riot Client déjà ouvert et connecté** (POST `product-launcher`) : c'est fiable,
contrairement à `RiotClientServices --launch-product` qui, sur certaines machines,
ouvre le Riot Client sans enclencher le jeu.

Auth : lockfile du Riot Client (port + mot de passe), comme la LCU. verify=False
(certificat local auto-signé).
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOCKFILE = (Path(os.environ.get("LOCALAPPDATA", ""))
            / "Riot Games" / "Riot Client" / "Config" / "lockfile")


def read_lockfile() -> tuple[int, str] | None:
    """(port, mot de passe) du Riot Client, ou None s'il n'est pas lancé."""
    try:
        parts = LOCKFILE.read_text(encoding="utf-8").strip().split(":")
    except OSError:
        return None
    if len(parts) < 5:
        return None
    try:
        return int(parts[2]), parts[3]
    except ValueError:
        return None


class RiotClient:
    """Client HTTP léger pour l'API locale du Riot Client."""

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False

    def is_running(self) -> bool:
        return read_lockfile() is not None

    def is_logged_in(self) -> bool:
        """Vrai si un compte est authentifié (donc prêt à lancer un jeu)."""
        creds = read_lockfile()
        if not creds:
            return False
        port, pw = creds
        try:
            resp = self.session.get(
                f"https://127.0.0.1:{port}/player-account/aliases/v1/active",
                auth=("riot", pw), timeout=3)
        except requests.RequestException:
            return False
        if resp.status_code != 200:
            return False
        try:
            return bool((resp.json() or {}).get("active"))
        except ValueError:
            return False

    def launch_league(self) -> bool:
        """Demande au Riot Client de lancer League. True si l'ordre est parti
        (l'appel peut ne pas répondre tout de suite : le lancement a lieu quand
        même, d'où le `Timeout` toléré)."""
        creds = read_lockfile()
        if not creds:
            return False
        port, pw = creds
        url = (f"https://127.0.0.1:{port}"
               "/product-launcher/v1/products/league_of_legends/patchlines/live")
        try:
            self.session.post(url, auth=("riot", pw), json={}, timeout=5)
        except requests.Timeout:
            pass
        except requests.RequestException:
            return False
        return True
