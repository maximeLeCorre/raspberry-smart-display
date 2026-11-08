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


def _merge(base: dict, extra: dict) -> dict:
    """Fusion récursive : les tables de `extra` complètent celles de `base`."""
    out = dict(base)
    for key, value in extra.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load_config(path: str | Path, local: bool = False) -> dict:
    """Charge config.toml. `local` : fusionne aussi `config.local.toml` (même dossier,
    hors Git, copié sur le Pi par deploy) = réglages PERSONNELS (ville, gare, pseudos…)
    qui n'ont rien à faire dans le dépôt public."""
    with open(path, "rb") as f:
        config = tomllib.load(f)
    extra = Path(path).with_name("config.local.toml")
    if local and extra.exists():
        with open(extra, "rb") as f:
            config = _merge(config, tomllib.load(f))
    return config


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


def load_riot_key() -> str:
    """Clé de l'API Web Riot (RIOT_API_KEY), lue dans le .env du Pi.

    Le Pi est désormais autonome pour l'enrichissement Web (rangs, winrate,
    historique) : la clé vit ici, pas sur l'agent. Vide si non définie.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        pass
    return (os.getenv("RIOT_API_KEY") or "").strip()


def load_server_host() -> str:
    """Hôte SSH de l'écran « Serveur » (SERVER_HOST), lu dans le .env du Pi.

    Garde l'IP du serveur hors de Git ; prioritaire sur ``[server] host``.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        pass
    return (os.getenv("SERVER_HOST") or "").strip()


def load_idfm_key() -> str:
    """Clé de l'API PRIM d'Île-de-France Mobilités (IDFM_API_KEY), .env du Pi.

    Écran « Trains » ; vide = module non configuré.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        pass
    return (os.getenv("IDFM_API_KEY") or "").strip()


def load_remote_token() -> str:
    """Jeton de l'API télécommande (REMOTE_API_TOKEN), .env du Pi. Distinct du
    jeton de l'agent : la montre ne peut pas se faire passer pour l'agent."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        pass
    return (os.getenv("REMOTE_API_TOKEN") or "").strip()


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
