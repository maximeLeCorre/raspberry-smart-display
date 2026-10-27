"""Source League of Legends : détecte la phase de jeu et produit les écrans.

Depuis que le Pi est autonome pour l'enrichissement Web (dossiers joueurs,
icônes, splash, historique, bilan de fin), l'agent ne fournit plus que des
données **locales** : la phase et la session de sélection (LCU) et le scoreboard
d'une partie en cours (Live Client Data API). Il n'a **plus de clé Riot** et ne
répond à aucune requête d'enrichissement (le Pi s'en charge directement).
"""

from __future__ import annotations

import threading

from champ_select import build_champ_select_payload
from lcu import LcuClient
from phases import build_lcu_detail, build_queue_payload, iter_lcu_sync
from riot_api import get_all_game_data, summarize_full
from sender import msg_lcu_detail, msg_store_matches
from sources.base import Source

# Actions LCU autorisées (commandes envoyées au client).
LCU_ACTIONS = {
    "accept": "/lol-matchmaking/v1/ready-check/accept",
    "decline": "/lol-matchmaking/v1/ready-check/decline",
}


class LeagueSource(Source):
    name = "league"

    def __init__(self, config: dict):
        super().__init__(config)
        self.lcu = LcuClient()
        self._syncing = False   # une synchro d'historique à la fois

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
        """Requêtes du Pi : synchro de l'historique (LCU) et actions (accepter…)."""
        msg_type = message.get("type")
        if msg_type == "request_lcu_sync":
            # Synchro en arrière-plan : récupère les bilans (1 appel/partie) sans
            # bloquer le récepteur (accepter/clic restent réactifs).
            if not self._syncing:
                threading.Thread(target=self._do_sync, daemon=True,
                                 args=(sender, message.get("since"))).start()
            return True
        if msg_type == "request_lcu_detail":
            gid = message.get("gameId")
            sender.send_safe(msg_lcu_detail(gid, build_lcu_detail(self.lcu, gid)))
            return True
        if msg_type == "lcu_action":
            path = LCU_ACTIONS.get(message.get("action"))
            if path:
                ok = self.lcu.post(path)
                print(f"[league] Action LCU '{message.get('action')}' -> "
                      f"{'OK' if ok else 'échec'}")
            return True
        return False

    def _do_sync(self, sender, since) -> None:
        """Envoie au Pi, par lots, les nouvelles parties (résumé + bilan)."""
        self._syncing = True
        try:
            n = 0
            for batch in iter_lcu_sync(self.lcu, since):
                sender.send_safe(msg_store_matches(batch, False))
                n += len(batch)
            sender.send_safe(msg_store_matches([], True))   # fin de synchro
            print(f"[league] Sync LCU terminée : {n} nouvelle(s) partie(s).")
        finally:
            self._syncing = False
