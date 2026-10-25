"""Point d'entrée de l'agent PC.

Usages :
    python main.py                       # détection réelle (via les Sources)
    python main.py --simulate            # scénario simulé complet (sans jeu)
    python main.py --simulate --scenario champselect|game|queue|postgame

L'agent est **agnostique** : il interroge les Sources des modules activés (le Pi
annonce lesquels à la connexion). Chaque tick, la première Source « active »
gagne et son écran + données sont envoyés ; sinon on affiche l'écran par défaut.
Ajouter un jeu = ajouter une Source (voir `sources/`).
"""

from __future__ import annotations

import argparse
import time
import tomllib
from pathlib import Path

from sender import Sender, msg_data, msg_set_screen
from sources import SOURCES

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"
DEFAULT_SCREEN = "default"


def parse_args():
    p = argparse.ArgumentParser(description="Agent PC (détection -> Pi).")
    p.add_argument("--simulate", action="store_true",
                   help="Scénario simulé, sans lancer de jeu.")
    p.add_argument("--scenario", default="full",
                   choices=["full", "champselect", "game", "queue", "postgame"],
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


def run_real(url: str, config: dict) -> None:
    interval = config["agent"]["update_interval"]
    sender = Sender(url)

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
    url = f"ws://{host}:{port}"

    if args.simulate:
        from simulator import run_simulation
        run_simulation(url, interval=config["agent"]["update_interval"],
                       scenario=args.scenario, duration=args.duration,
                       platform=config["riot"]["platform"],
                       regional=config["riot"]["regional"])
    else:
        run_real(url, config)


if __name__ == "__main__":
    main()
