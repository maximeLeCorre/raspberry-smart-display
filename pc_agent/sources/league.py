"""Source League of Legends : détecte la phase de jeu et produit les écrans.

S'appuie sur la LCU (phase, sélection, après-partie), la Live Client Data API
(partie en cours) et l'API Web Riot (détails joueur enrichis).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from champ_select import (build_champ_select_payload, build_player_info,
                          icon_b64, splash_b64)
from lcu import LcuClient
from phases import build_postgame_payload, build_queue_payload
from riot_api import get_all_game_data, summarize_full
from riot_web import RiotWeb
from sender import msg_icon, msg_player_info, msg_splash
from sources.base import Source

# .env à la racine du dépôt (deux niveaux au-dessus de pc_agent/sources/).
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class LeagueSource(Source):
    name = "league"

    def __init__(self, config: dict):
        super().__init__(config)
        self.lcu = LcuClient()
        use_player_info = config.get("features", {}).get("player_info", True)
        self.riot = self._make_riot(config) if use_player_info else None

        # (prédicat sur la phase, écran, constructeur du payload)
        self._rules = [
            (lambda p: p in ("Matchmaking", "ReadyCheck"), "queue",
             lambda p: build_queue_payload(self.lcu, p)),
            (lambda p: p == "ChampSelect", "champselect",
             lambda p: build_champ_select_payload(self.lcu, self.riot)),
            (lambda p: p == "InProgress", "lol",
             lambda p: self._lol_payload()),
            (lambda p: p in ("WaitingForStats", "PreEndOfGame", "EndOfGame"), "postgame",
             lambda p: build_postgame_payload(self.lcu)),
        ]

    def _make_riot(self, config: dict) -> RiotWeb:
        load_dotenv(ENV_PATH)
        api_key = os.getenv("RIOT_API_KEY") or None
        platform = config["riot"]["platform"]
        regional = config["riot"]["regional"]
        detected_platform, detected_regional = self.lcu.region_platform()
        if detected_platform and detected_regional:
            platform, regional = detected_platform, detected_regional
        if not api_key:
            print("[league] RIOT_API_KEY absente de .env : détails joueur limités.")
        return RiotWeb(api_key, platform, regional)

    def _lol_payload(self):
        data = get_all_game_data()
        return summarize_full(data, self.lcu.champion_id_by_name) if data else None

    def poll(self):
        phase = self.lcu.gameflow_phase()
        if phase is None:
            return None  # client fermé -> League inactif
        for matches, screen, build in self._rules:
            if matches(phase):
                return (screen, build(phase))
        return None  # menu / lobby -> rien de spécial (défaut géré par l'agent)

    def handle_request(self, message: dict, sender) -> bool:
        msg_type = message.get("type")
        if msg_type == "request_player_info":
            puuid = message.get("puuid", "")
            info = build_player_info(self.lcu, self.riot, puuid,
                                     message.get("summonerId"),
                                     int(message.get("championId") or 0))
            sender.send_safe(msg_player_info(puuid, info))
            return True
        if msg_type == "request_icon":
            cid = int(message.get("championId") or 0)
            sender.send_safe(msg_icon(cid, icon_b64(self.lcu, cid)))
            return True
        if msg_type == "request_splash":
            cid = int(message.get("championId") or 0)
            sender.send_safe(msg_splash(cid, splash_b64(self.lcu, cid)))
            return True
        return False
