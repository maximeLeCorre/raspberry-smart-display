"""Point d'entrée de l'agent PC.

Usages :
    python main.py                       # détection réelle (client + jeu)
    python main.py --simulate            # scénario simulé complet (sans le jeu)
    python main.py --simulate --scenario champselect

En mode réel, l'agent s'appuie sur la LCU (API du client) pour connaître la
phase de jeu et piloter le mode affiché sur le Pi :
    menu / lobby / file d'attente  -> mode par défaut
    sélection de champions          -> mode "champselect" (+ données équipe)
    partie en cours                 -> mode "lol" (+ Live Client Data API)

Il écoute aussi les demandes du Pi (clic sur un joueur) pour renvoyer les
détails enrichis via l'API Web Riot.
"""

from __future__ import annotations

import argparse
import os
import time
import tomllib
from pathlib import Path

from dotenv import load_dotenv

from champ_select import build_champ_select_payload, build_player_info, icon_b64
from detector import is_any_process_running
from lcu import LcuClient
from phases import build_queue_payload
from riot_api import get_all_game_data, summarize_full
from riot_web import RiotWeb
from sender import Sender, msg_data, msg_icon, msg_player_info, msg_set_mode

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"
# .env à la racine du dépôt (un niveau au-dessus de pc_agent/).
ENV_PATH = ROOT.parent / ".env"

# Phases LCU qui correspondent au mode par défaut (hors sélection/partie).
DEFAULT_PHASES = {
    None, "None", "Lobby", "Matchmaking", "ReadyCheck", "CheckedIntoTournament",
    "GameStart", "PreEndOfGame", "EndOfGame", "WaitingForStats",
    "TerminatedInError", "Reconnect",
}


def parse_args():
    p = argparse.ArgumentParser(description="Agent PC (détection LoL -> Pi).")
    p.add_argument("--simulate", action="store_true",
                   help="Scénario simulé, sans lancer le jeu.")
    p.add_argument("--scenario", default="full",
                   choices=["full", "champselect", "game", "queue"],
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


def make_riot_web(config: dict, lcu: LcuClient) -> RiotWeb:
    """Construit le client API Web Riot (clé depuis .env, région auto si possible)."""
    load_dotenv(ENV_PATH)
    api_key = os.getenv("RIOT_API_KEY") or None

    platform = config["riot"]["platform"]
    regional = config["riot"]["regional"]
    # Tentative d'auto-détection via la LCU (si le client est ouvert).
    detected_platform, detected_regional = lcu.region_platform()
    if detected_platform and detected_regional:
        platform, regional = detected_platform, detected_regional

    if not api_key:
        print("[agent] RIOT_API_KEY absente de .env : détails joueur limités "
              "(rang/winrate/mains indisponibles).")
    return RiotWeb(api_key, platform, regional)


def make_request_handler(sender: Sender, build_info, lcu: LcuClient):
    """Crée le callback qui répond aux demandes venant du Pi (infos + icônes)."""
    def handle(message: dict):
        msg_type = message.get("type")
        if msg_type == "request_player_info":
            puuid = message.get("puuid", "")
            sender.send_safe(msg_player_info(puuid, build_info(message)))
        elif msg_type == "request_icon":
            champ_id = int(message.get("championId") or 0)
            sender.send_safe(msg_icon(champ_id, icon_b64(lcu, champ_id)))
    return handle


def run_real(url: str, config: dict) -> None:
    interval = config["agent"]["update_interval"]
    use_player_info = config.get("features", {}).get("player_info", True)

    lcu = LcuClient()
    riot = make_riot_web(config, lcu) if use_player_info else None

    sender = Sender(url)

    def build_info(message: dict) -> dict:
        return build_player_info(
            lcu, riot,
            message.get("puuid", ""),
            message.get("summonerId"),
            int(message.get("championId") or 0),
        )

    sender.start_receiver(make_request_handler(sender, build_info, lcu))

    last_mode = None
    print("[agent] Surveillance du client League (LCU)... (Ctrl+C pour quitter)")
    try:
        while True:
            phase = lcu.gameflow_phase()

            if phase in ("Matchmaking", "ReadyCheck"):
                if last_mode != "queue":
                    sender.send_safe(msg_set_mode("queue"))
                    last_mode = "queue"
                sender.send_safe(msg_data("queue", build_queue_payload(lcu, phase)))

            elif phase == "ChampSelect":
                payload = build_champ_select_payload(lcu, riot)
                if payload is not None:
                    if last_mode != "champselect":
                        sender.send_safe(msg_set_mode("champselect"))
                        last_mode = "champselect"
                    sender.send_safe(msg_data("champselect", payload))

            elif phase == "InProgress":
                if last_mode != "lol":
                    sender.send_safe(msg_set_mode("lol"))
                    last_mode = "lol"
                # Données live : disponibles une fois réellement chargé en jeu.
                data = get_all_game_data()
                if data is not None:
                    sender.send_safe(msg_data("lol", summarize_full(data, lcu.champion_id_by_name)))

            else:
                # Menu, lobby, file d'attente, client fermé... -> mode par défaut.
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
        # Import tardif : le simulateur n'a pas besoin des modules LCU/Riot.
        from simulator import run_simulation
        run_simulation(url, interval=config["agent"]["update_interval"],
                       scenario=args.scenario, duration=args.duration,
                       platform=config["riot"]["platform"],
                       regional=config["riot"]["regional"])
    else:
        run_real(url, config)


if __name__ == "__main__":
    main()
