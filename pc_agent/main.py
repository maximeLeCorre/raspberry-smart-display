"""Point d'entrée de l'agent PC.

Deux usages :
    python main.py --simulate          # envoie de fausses données LoL (test)
    python main.py                     # détection réelle du jeu (League)

En mode réel, l'agent surveille les processus de League. Quand une partie est
en cours, il lit la Live Client Data API locale et envoie un résumé au Pi
(une fois par `update_interval`). Hors partie / jeu fermé, il repasse le Pi
en mode par défaut.
"""

from __future__ import annotations

import argparse
import time
import tomllib
from pathlib import Path

from detector import is_any_process_running
from riot_api import get_all_game_data, summarize
from sender import Sender, msg_data, msg_set_mode
from simulator import run_simulation

CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


def parse_args():
    p = argparse.ArgumentParser(description="Agent PC (détection LoL -> Pi).")
    p.add_argument("--simulate", action="store_true",
                   help="Envoie de fausses données LoL (ne lance pas le jeu).")
    p.add_argument("--duration", type=int, default=None,
                   help="Durée de la simulation en secondes (défaut : illimité).")
    p.add_argument("--host", default=None, help="Surcharge l'hôte du Pi.")
    p.add_argument("--port", type=int, default=None, help="Surcharge le port du Pi.")
    p.add_argument("--config", default=str(CONFIG_PATH), help="Chemin du config.toml.")
    return p.parse_args()


def load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def run_real(url: str, config: dict) -> None:
    """Boucle de détection réelle du jeu."""
    interval = config["agent"]["update_interval"]
    process_names = [config["lol"]["client_process"], config["lol"]["game_process"]]

    sender = Sender(url)
    last_mode = None  # évite d'envoyer set_mode en boucle

    print("[agent] Surveillance de League of Legends... (Ctrl+C pour quitter)")
    try:
        while True:
            lol_running = is_any_process_running(process_names)

            if lol_running:
                data = get_all_game_data()
                if data is not None:
                    # En partie : on envoie le mode (une fois) puis les données.
                    if last_mode != "lol":
                        sender.send_safe(msg_set_mode("lol"))
                        last_mode = "lol"
                    sender.send_safe(msg_data("lol", summarize(data)))
                else:
                    # Client ouvert mais pas en partie -> mode par défaut.
                    if last_mode != "default":
                        sender.send_safe(msg_set_mode("default"))
                        last_mode = "default"
            else:
                # Jeu fermé -> mode par défaut.
                if last_mode != "default":
                    sender.send_safe(msg_set_mode("default"))
                    last_mode = "default"

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[agent] Arrêt demandé.")
    finally:
        sender.send_safe(msg_set_mode("default"))
        sender.close()


def main():
    args = parse_args()
    config = load_config(args.config)

    host = args.host if args.host is not None else config["pi"]["host"]
    port = args.port if args.port is not None else config["pi"]["port"]
    url = f"ws://{host}:{port}"

    if args.simulate:
        run_simulation(url, interval=config["agent"]["update_interval"],
                       duration=args.duration)
    else:
        run_real(url, config)


if __name__ == "__main__":
    main()
