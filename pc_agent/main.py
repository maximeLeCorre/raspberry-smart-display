"""Point d'entrée de l'agent PC.

Usages :
    python main.py                       # détection réelle (via les Sources)
    python main.py --simulate            # scénario simulé complet (sans jeu)
    python main.py --simulate --scenario champselect|game|aram|queue|postgame

L'agent est **agnostique** : il interroge les Sources des modules activés (le Pi
annonce lesquels à la connexion). Chaque tick, la première Source « active »
gagne et son écran + données sont envoyés ; sinon on affiche l'écran par défaut.
Ajouter un jeu = ajouter une Source (voir `sources/`).
"""

from __future__ import annotations

import argparse
import os
import ssl
import time
import tomllib
from pathlib import Path

from dotenv import load_dotenv

from sender import Sender, msg_data, msg_set_screen
from sources import SOURCES

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"
REPO_ROOT = ROOT.parent          # racine du dépôt
ENV_PATH = REPO_ROOT / ".env"    # .env à la racine du dépôt
DEFAULT_SCREEN = "default"


def load_auth_token() -> str:
    """Jeton partagé Pi <-> agent (DISPLAY_AUTH_TOKEN), lu dans .env.

    Vide = authentification désactivée (doit correspondre au réglage du Pi).
    """
    load_dotenv(ENV_PATH)
    return (os.getenv("DISPLAY_AUTH_TOKEN") or "").strip()


def build_client_ssl(config: dict) -> ssl.SSLContext | None:
    """Contexte TLS côté agent, ou None si TLS désactivé (`[pi] tls`).

    Épingle le certificat auto-signé du Pi (`cert_file`) : on vérifie que le
    serveur présente CE certificat précis, mais on ne vérifie pas le nom d'hôte
    (le certificat reste valable même si l'IP du Pi change).
    """
    pi = config["pi"]
    if not pi.get("tls", False):
        return None
    cert = Path(pi.get("cert_file", "certs/pi-display.crt"))
    if not cert.is_absolute():
        cert = REPO_ROOT / cert
    if not cert.exists():
        raise FileNotFoundError(
            f"TLS activé mais certificat du Pi introuvable ({cert}). "
            f"Copier le .crt généré sur le Pi (tools/gen_cert.py)."
        )
    ctx = ssl.create_default_context(cafile=str(cert))
    ctx.check_hostname = False   # certificat épinglé : on vérifie le cert, pas le nom
    return ctx


def parse_args():
    p = argparse.ArgumentParser(description="Agent PC (détection -> Pi).")
    p.add_argument("--simulate", action="store_true",
                   help="Scénario simulé, sans lancer de jeu.")
    p.add_argument("--scenario", default="full",
                   choices=["full", "champselect", "game", "aram", "queue", "postgame"],
                   help="Scénario de simulation (défaut : full).")
    p.add_argument("--duration", type=int, default=None,
                   help="Durée d'une étape de simulation en secondes.")
    p.add_argument("--host", default=None, help="Surcharge l'hôte du Pi.")
    p.add_argument("--port", type=int, default=None, help="Surcharge le port du Pi.")
    p.add_argument("--config", default=str(CONFIG_PATH), help="Chemin du config.toml.")
    return p.parse_args()


def load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def run_real(url: str, config: dict, auth_token: str = "", ssl_context=None) -> None:
    interval = config["agent"]["update_interval"]
    sender = Sender(url, auth_token=auth_token, ssl_context=ssl_context)

    # Toutes les Sources connues sont instanciées ; `enabled` filtre lesquelles
    # sont réellement interrogées (selon ce que le Pi annonce via 'hello').
    sources = {name: cls(config) for name, cls in SOURCES.items()}
    state = {"enabled": None}  # None = tout activé tant que le Pi n'a rien dit

    def is_enabled(name: str) -> bool:
        return state["enabled"] is None or name in state["enabled"]

    def handle(message: dict):
        if message.get("type") == "hello":
            state["enabled"] = set(message.get("modules", []))
            print(f"[agent] Modules actifs (annoncés par le Pi) : {sorted(state['enabled'])}")
            return
        for name, src in sources.items():
            if is_enabled(name) and src.handle_request(message, sender):
                return

    sender.start_receiver(handle)

    last_screen = None
    print("[agent] Surveillance des modules... (Ctrl+C pour quitter)")
    try:
        while True:
            result = None
            for name, src in sources.items():
                if not is_enabled(name):
                    continue
                result = src.poll()
                if result is not None:
                    break

            if result is not None:
                screen, payload = result
                if last_screen != screen:
                    sender.send_safe(msg_set_screen(screen))
                    last_screen = screen
                if payload is not None:
                    sender.send_safe(msg_data(screen, payload))
            else:
                if last_screen != DEFAULT_SCREEN:
                    sender.send_safe(msg_set_screen(DEFAULT_SCREEN))
                    last_screen = DEFAULT_SCREEN

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[agent] Arrêt demandé.")
    finally:
        sender.send_safe(msg_set_screen(DEFAULT_SCREEN))
        sender.close()


def main():
    args = parse_args()
    config = load_config(args.config)

    host = args.host if args.host is not None else config["pi"]["host"]
    port = args.port if args.port is not None else config["pi"]["port"]
    ssl_context = build_client_ssl(config)
    scheme = "wss" if ssl_context else "ws"
    url = f"{scheme}://{host}:{port}"
    auth_token = load_auth_token()

    if args.simulate:
        from simulator import run_simulation
        run_simulation(url, interval=config["agent"]["update_interval"],
                       scenario=args.scenario, duration=args.duration,
                       platform=config["riot"]["platform"],
                       regional=config["riot"]["regional"],
                       auth_token=auth_token, ssl_context=ssl_context)
    else:
        run_real(url, config, auth_token, ssl_context)


if __name__ == "__main__":
    main()
