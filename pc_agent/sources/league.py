"""Source League of Legends : détecte la phase de jeu et produit les écrans.

Depuis que le Pi est autonome pour l'enrichissement Web (dossiers joueurs,
icônes, splash, historique, bilan de fin), l'agent ne fournit plus que des
données **locales** : la phase et la session de sélection (LCU) et le scoreboard
d'une partie en cours (Live Client Data API). Il n'a **plus de clé Riot** et ne
répond à aucune requête d'enrichissement (le Pi s'en charge directement).
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

import psutil

from champ_select import build_champ_select_payload
from lcu import LcuClient, find_lcu_credentials
from riot_client import RiotClient
from phases import (build_lcu_detail, build_lcu_timeline, build_queue_payload,
                    find_friend_puuid, iter_lcu_sync, iter_player_sync)
from riot_api import get_all_game_data, summarize_full
from sender import (msg_data, msg_lcu_detail, msg_lcu_timeline, msg_store_matches,
                    msg_store_player_games)
from sources.base import Source

# Actions LCU « simples » (un POST sans corps).
LCU_ACTIONS = {
    "accept": "/lol-matchmaking/v1/ready-check/accept",
    "decline": "/lol-matchmaking/v1/ready-check/decline",
}

# Démarrage à froid du client (Riot Client -> maj -> League -> login -> menu) :
# lent, surtout au 1er lancement de la journée. On attend jusqu'à 5 min.
READY_TIMEOUT = 300.0
# Démarrage de League (patch inclus) après la commande au Riot Client.
LAUNCH_TIMEOUT = 240.0

# Processus League (bootstrapper + client) : présence = League démarre/est ouverte.
LEAGUE_PROCESSES = ("leagueclient.exe", "leagueclientux.exe")


def league_process_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        if (proc.info["name"] or "").lower() in LEAGUE_PROCESSES:
            return True
    return False


def vanguard_stopped() -> bool:
    """Service anti-triche Vanguard (`vgc`) à l'arrêt ? Après un kill forcé de
    League, il peut rester cassé et bloquer le lancement jusqu'au redémarrage."""
    try:
        return psutil.win_service_get("vgc").status() != "running"
    except Exception:
        return False


class LeagueSource(Source):
    name = "league"

    def __init__(self, config: dict):
        super().__init__(config)
        self.lcu = LcuClient()
        self.riot = RiotClient()    # API du Riot Client (lancement de League)
        self._syncing = False       # une synchro d'historique à la fois
        self._player_syncing = False  # idem pour l'historique de l'ami comparé
        self._playing = False       # un enchaînement « jouer » à la fois
        lol_cfg = config.get("lol", {})
        self._launch_exe = (lol_cfg.get("launch_exe") or "").strip()
        self._launch_args = list(lol_cfg.get("launch_args", []))

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
        if msg_type == "request_player_sync":
            if not self._player_syncing:
                threading.Thread(target=self._do_player_sync, daemon=True,
                                 args=(sender, message.get("riotId"),
                                       message.get("known") or [])).start()
            return True
        if msg_type == "request_lcu_detail":
            gid = message.get("gameId")
            sender.send_safe(msg_lcu_detail(gid, build_lcu_detail(self.lcu, gid)))
            return True
        if msg_type == "request_lcu_timeline":
            gid = message.get("gameId")
            sender.send_safe(msg_lcu_timeline(gid, build_lcu_timeline(self.lcu, gid)))
            return True
        if msg_type == "lcu_action":
            action = message.get("action")
            if action == "play":
                # Enchaînement potentiellement long (démarrage du client) : en
                # thread, pour ne pas bloquer le récepteur.
                if not self._playing:
                    threading.Thread(target=self._play, daemon=True,
                                     args=(sender, message.get("queueId"),
                                           message.get("invite"))).start()
                return True
            path = LCU_ACTIONS.get(action)
            if path:
                ok = self.lcu.post(path)
                print(f"[league] Action LCU '{action}' -> {'OK' if ok else 'échec'}")
            return True
        return False

    # -------------------------------------------------------------- jouer (1 clic)
    def _play(self, sender, queue_id, invite) -> None:
        """Bouton unique : lance le client s'il est fermé, crée le lobby `queue_id`
        s'il n'est pas déjà le bon, puis invite l'ami `invite` s'il n'est pas déjà
        présent/invité. Chaque étape déjà faite est sautée (idempotent). Pousse un
        message d'étape au Pi (`playStatus`) : confirmation + avancement."""
        self._playing = True

        def status(text: str) -> None:
            print(f"[league] {text}")
            sender.send_safe(msg_data("default", {"playStatus": text}))

        status("Instruction reçue…")
        final = "Lobby ARAM Chaos prêt"
        try:
            if self.lcu.gameflow_phase() is None:          # client fermé -> lancer
                status("Lancement de League…")
                if not self._launch_client():
                    final = ("Vanguard arrêté - redémarre le PC" if vanguard_stopped()
                             else "Lancement impossible (voir config)")
                    return
                status("Connexion au client… (1-2 min)")
                if not self._wait_ready(READY_TIMEOUT):
                    final = "Client non prêt (abandon)"
                    return
            status("Création du lobby ARAM Chaos…")
            if not self._ensure_lobby(queue_id):
                final = "Échec de création du lobby"
                return
            name = (invite or "").strip()
            if name:
                status(f"Invitation de {name}…")
                final = self._invite_if_needed(name)
        finally:
            status(final)
            time.sleep(4)          # laisse le message final lisible sur le Pi
            sender.send_safe(msg_data("default", {"playStatus": ""}))
            self._playing = False

    def _ensure_lobby(self, queue_id) -> bool:
        """Crée le lobby si ce n'est pas déjà le bon. Plusieurs essais : juste
        après la connexion, le client peut encore refuser (en cours de
        stabilisation). True dès que le lobby `queue_id` est en place."""
        for attempt in range(6):
            if self._current_queue() == queue_id:
                if attempt == 0:
                    print(f"[league] Lobby queueId={queue_id} déjà ouvert : rien à créer.")
                return True
            if self.lcu.post("/lol-lobby/v2/lobby", {"queueId": queue_id}):
                print(f"[league] Lobby ARAM Chaos (queueId={queue_id}) créé.")
                return True
            time.sleep(3)
        print(f"[league] Lobby ARAM Chaos (queueId={queue_id}) -> échec (plusieurs essais).")
        return False

    def _launch_client(self) -> bool:
        """Démarre League. Si le Riot Client est fermé, l'ouvre d'abord (il
        s'auto-connecte si « rester connecté »). Puis (re)commande le lancement de
        League jusqu'à ce que le jeu démarre vraiment : juste après l'ouverture du
        Riot Client, le 1er ordre est souvent ignoré (pas encore prêt)."""
        # « Réellement connecté » (appel API), pas juste le lockfile : il peut
        # rester sur le disque après fermeture (port mort).
        if not self.riot.is_logged_in():
            if not self._spawn_riot_client():
                return False
            if not self._wait_riot_logged_in(180):
                print("[league] Riot Client non connecté (connexion manuelle ?).")
        # Succès = la LCU de League répond (pas juste un process présent : un
        # zombie laissé par un plantage Vanguard existe SANS LCU et piégeait la
        # détection). On ne re-commande que si RIEN ne démarre (sinon on laisse
        # League patcher/charger).
        posted = 0
        deadline = time.monotonic() + LAUNCH_TIMEOUT
        while time.monotonic() < deadline:
            if find_lcu_credentials() is not None:
                return True
            if not league_process_running() and posted < 6:
                if self.riot.launch_league():
                    posted += 1
                    print(f"[league] Lancement de League demandé (essai {posted}).")
                else:
                    print("[league] Le Riot Client n'a pas accepté le lancement.")
            time.sleep(4)
        print("[league] League ne démarre pas (process zombie ou Vanguard ?).")
        return False

    def _spawn_riot_client(self) -> bool:
        """Ouvre le Riot Client (exécutable configuré)."""
        if not self._launch_exe or not os.path.exists(self._launch_exe):
            print(f"[league] Lancement impossible : exécutable introuvable "
                  f"({self._launch_exe or 'non configuré'}).")
            return False
        try:
            subprocess.Popen([self._launch_exe, *self._launch_args],
                             cwd=os.path.dirname(self._launch_exe))
            print("[league] Riot Client lancé, attente de la connexion…")
            return True
        except OSError as exc:
            print(f"[league] Échec du lancement du Riot Client : {exc}")
            return False

    def _wait_riot_logged_in(self, timeout: float) -> bool:
        """Attend que le Riot Client soit lancé ET un compte authentifié."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.riot.is_logged_in():
                return True
            time.sleep(2)
        return False

    def _wait_ready(self, timeout: float) -> bool:
        """Attend que la LCU réponde et que le compte soit connecté (menu)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            summ = self.lcu.current_summoner()
            if summ and summ.get("summonerId"):
                return True
            time.sleep(2)
        return False

    def _current_queue(self):
        """queueId du lobby courant, ou None s'il n'y a pas de lobby."""
        lobby = self.lcu.get_json("/lol-lobby/v2/lobby") or {}
        return (lobby.get("gameConfig") or {}).get("queueId")

    def _invite_if_needed(self, name: str) -> str:
        """Invite l'ami s'il faut. Renvoie le message d'état final (affiché sur le Pi)."""
        summoner_id = self._online_friend_id(name)
        if summoner_id is None:
            print(f"[league] Invitation : « {name} » introuvable ou hors ligne.")
            return f"Lobby prêt - {name} hors ligne"
        if self._in_lobby(summoner_id):
            print(f"[league] « {name} » est déjà dans le lobby / invité.")
            return f"Lobby prêt - {name} déjà présent"
        ok = self.lcu.post("/lol-lobby/v2/lobby/invitations",
                           [{"toSummonerId": summoner_id}])
        print(f"[league] Invitation de « {name} » -> {'OK' if ok else 'échec'}")
        return f"{name} invité !" if ok else "Lobby prêt - invitation échouée"

    def _in_lobby(self, summoner_id) -> bool:
        """L'ami est-il déjà membre du lobby ou déjà invité (en attente/accepté) ?"""
        lobby = self.lcu.get_json("/lol-lobby/v2/lobby") or {}
        if any(m.get("summonerId") == summoner_id
               for m in (lobby.get("members") or [])):
            return True
        return any(i.get("toSummonerId") == summoner_id
                   and i.get("state") in ("Pending", "Requested", "Accepted")
                   for i in (lobby.get("invitations") or []))

    def _online_friend_id(self, name: str):
        """summonerId d'un ami EN LIGNE, par Riot ID « Nom#TAG » ou juste « Nom »
        (insensible à la casse). None si absent, non-ami, ou hors ligne."""
        want = name.lower()
        for f in (self.lcu.get_json("/lol-chat/v1/friends") or []):
            gn = (f.get("gameName") or "").lower()
            rid = f"{gn}#{(f.get('gameTag') or '').lower()}"
            if want in (gn, rid):
                if (f.get("availability") or "").lower() == "offline":
                    return None
                return f.get("summonerId")
        return None

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

    def _do_player_sync(self, sender, riot_id, known) -> None:
        """Envoie au Pi les parties récentes d'un ami (stats comparées)."""
        self._player_syncing = True
        try:
            puuid = find_friend_puuid(self.lcu, riot_id or "")
            n = 0
            if puuid:
                for batch in iter_player_sync(self.lcu, puuid, known):
                    sender.send_safe(msg_store_player_games(riot_id, batch, False))
                    n += len(batch)
            else:
                print(f"[league] « {riot_id} » introuvable dans la liste d'amis.")
            sender.send_safe(msg_store_player_games(riot_id, [], True))
            print(f"[league] Sync de {riot_id} : {n} nouvelle(s) partie(s).")
        finally:
            self._player_syncing = False
