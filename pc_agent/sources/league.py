"""Source League of Legends : détecte la phase de jeu et produit les écrans.

Depuis que le Pi est autonome pour l'enrichissement Web (dossiers joueurs,
icônes, splash, historique, bilan de fin), l'agent ne fournit plus que des
données **locales** : la phase et la session de sélection (LCU) et le scoreboard
d'une partie en cours (Live Client Data API). Il n'a **plus de clé Riot** et ne
répond à aucune requête d'enrichissement (le Pi s'en charge directement).
"""

from __future__ import annotations

from champ_select import build_champ_select_payload
from lcu import LcuClient
from phases import build_lcu_detail, build_lcu_history, build_queue_payload
from riot_api import get_all_game_data, summarize_full
from sender import msg_lcu_detail, msg_lcu_history
from sources.base import Source


class LeagueSource(Source):
    name = "league"

    def __init__(self, config: dict):
        super().__init__(config)
        self.lcu = LcuClient()

        # (prédicat sur la phase, écran, constructeur du payload)
        self._rules = [
            (lambda p: p in ("Matchmaking", "ReadyCheck"), "queue",
             lambda p: build_queue_payload(self.lcu, p)),
            (lambda p: p == "ChampSelect", "champselect",
             lambda p: build_champ_select_payload(self.lcu)),
            (lambda p: p == "InProgress", "lol",
             lambda p: self._lol_payload()),
            # Fin de partie : on bascule l'écran, mais c'est le Pi qui récupère le
            # bilan (via l'API Web, la dernière partie du compte configuré).
            (lambda p: p in ("WaitingForStats", "PreEndOfGame", "EndOfGame"), "postgame",
             lambda p: None),
        ]

    def _lol_payload(self):
        data = get_all_game_data()
        if not data:
            return None
        # Le Pi enrichit les dossiers au clic via le `riotId` de chaque joueur.
        return summarize_full(data, self.lcu.champion_id_by_name)

    def poll(self):
        phase = self.lcu.gameflow_phase()
        if phase is None:
            return None  # client fermé -> League inactif
        for matches, screen, build in self._rules:
            if matches(phase):
                return (screen, build(phase))
        return None  # menu / lobby -> rien de spécial (défaut géré par l'agent)

    def handle_request(self, message: dict, sender) -> bool:
        """Le Pi réclame l'historique/bilan des parties spéciales (ARAM chaos)
        que seule la LCU expose."""
        msg_type = message.get("type")
        if msg_type == "request_lcu_history":
            games = build_lcu_history(self.lcu, int(message.get("start") or 0),
                                      int(message.get("count") or 10))
            sender.send_safe(msg_lcu_history(games))
            return True
        if msg_type == "request_lcu_detail":
            payload = build_lcu_detail(self.lcu, message.get("gameId"))
            sender.send_safe(msg_lcu_detail(payload))
            return True
        return False
