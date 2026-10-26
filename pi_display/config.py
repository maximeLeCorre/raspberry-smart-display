"""Chargement de la configuration et détection de l'environnement (PC / Pi)."""

from __future__ import annotations

import os
import ssl
import tomllib
from pathlib import Path

# Racine du dépôt (un niveau au-dessus de pi_display/).
REPO_ROOT = Path(__file__).resolve().parent.parent
# .env à la racine du dépôt.
ENV_PATH = REPO_ROOT / ".env"


def _resolve(path: str) -> Path:
    """Chemin absolu tel quel, sinon relatif à la racine du dépôt."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def is_raspberry_pi() -> bool:
    """Retourne True si le programme tourne sur un Raspberry Pi.

    On lit le modèle exposé par le noyau Linux. Sur un PC Windows ce fichier
    n'existe pas : la fonction renvoie False sans lever d'erreur.
    """
    model = Path("/sys/firmware/devicetree/base/model")
    try:
        return model.exists() and "raspberry pi" in model.read_text(errors="ignore").lower()
    except OSError:
        return False


def load_config(path: str | Path) -> dict:
    """Charge le fichier config.toml et renvoie un dictionnaire."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_auth_token() -> str:
    """Jeton partagé Pi <-> agent (DISPLAY_AUTH_TOKEN), lu dans .env.

    Vide si non défini (authentification désactivée). Fonctionne sans
    python-dotenv installé : on retombe alors sur les variables d'environnement.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        pass
    return (os.getenv("DISPLAY_AUTH_TOKEN") or "").strip()


def build_server_ssl(config: dict) -> ssl.SSLContext | None:
    """Contexte TLS côté serveur (Pi), ou None si TLS désactivé.

    Lit `[network] tls/cert_file/key_file`. Lève une erreur claire si TLS est
    activé mais que le certificat/la clé sont introuvables (à générer via
    `tools/gen_cert.py`).
    """
    net = config.get("network", {})
    if not net.get("tls", False):
        return None
    cert = _resolve(net.get("cert_file", "certs/pi-display.crt"))
    key = _resolve(net.get("key_file", "certs/pi-display.key"))
    if not cert.exists() or not key.exists():
        raise FileNotFoundError(
            f"TLS activé mais certificat/clé introuvables ({cert}, {key}). "
            f"Générer : python pi_display/tools/gen_cert.py"
        )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
    return ctx
