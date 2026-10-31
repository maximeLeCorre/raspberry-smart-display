"""Logique du module League (côté Pi) : API Web Riot + CDN, store des parties,
synchro LCU via l'agent, bilan de fin de partie, bouton « Jouer ».

Sorti de `app.py` (qui reste agnostique du jeu) : l'App appelle les crochets
de `Module` ; les écrans League passent par `app.modules["league"]`.
"""

from __future__ import annotations

import base64
import time

from config import load_riot_key
from icon_cache import IconCache
from modules.base import Module
from modules.league.champ_select_screen import ChampSelectScreen
from modules.league.history_screen import MatchHistoryScreen
from modules.league.lol_screen import LolScreen
from modules.league.postgame_screen import PostGameScreen
from modules.league.queue_screen import QueueScreen
from modules.league.stats_screen import StatsScreen
from riot_web import (PATCH_TTL, Champions, RiotWeb, build_player_info, current_patch,
                      icon_bytes, normalize_riot_id, splash_bytes)
from store import Store


class LeagueModule(Module):
    name = "league"
    screens = [QueueScreen, ChampSelectScreen, LolScreen, PostGameScreen,
               MatchHistoryScreen, StatsScreen]

    def __init__(self, app):
        super().__init__(app)
        # Accès internet « League » (le Pi est autonome : API Web + CDN).
        riot_cfg = app.config.get("riot", {})
        lol_cfg = app.config.get("lol", {})
        self.champions = Champions()
        self.riot = RiotWeb(load_riot_key(), riot_cfg.get("platform", "euw1"),
                            riot_cfg.get("regional", "europe"))
        self.summoner_rid = (lol_cfg.get("summoner") or "").strip()
        # Ami comparé (écran Stats : moi seul / lui seul / ensemble), « Nom#TAG ».
        self.compare_rid = (lol_cfg.get("compare") or "").strip()
        # Bouton « créer un lobby » du défaut : file toujours ARAM Chaos (2400),
        # et ami invité s'il est en ligne (vide = pas d'invitation).
        self.lobby_queue = int(lol_cfg.get("lobby_queue", 2400) or 2400)
        self.lobby_invite = (lol_cfg.get("lobby_invite") or "").strip()
        self.friends = {
            normalize_riot_id(*rid.split("#", 1))
            for rid in lol_cfg.get("friends", [])
            if isinstance(rid, str) and "#" in rid
        }
        # Base locale des parties (historique consultable PC éteint).
        self.store = Store()
        # Icônes sur disque (icons.db) : pas de re-téléchargement au redémarrage.
        self.icon_cache = IconCache()
        # Patch relu chaque heure même si toutes les icônes sont déjà en mémoire
        # (sinon un nouveau patch ne serait vu qu'au redémarrage).
        self._patch_check = time.monotonic()
        # Bilan en mode « dernière partie » (fin de game) vs « revue » (clic).
        self._postgame_latest = False
        # Id de la partie la plus récente AVANT la partie en cours : sert à
        # savoir, en fin de partie, si celle qui vient de finir est bien
        # arrivée dans le store (sinon on afficherait par erreur la précédente).
        self._postgame_baseline = None
        # Écran de retour quand on consulte une partie depuis l'historique
        # (RETOUR du bilan -> historique au lieu du défaut). None = flux normal.
        self.postgame_return: str | None = None
        # Scan périodique de l'historique (LCU) : insensible au délai
        # d'indexation. `_last_sync` = time.monotonic() du dernier scan.
        self._sync_interval = max(0, int(lol_cfg.get("sync_minutes", 3) or 0)) * 60
        self._last_sync = 0.0
        self._repair_champion_names()

    def _current(self) -> str | None:
        cur = self.app.current
        return cur.name if cur is not None else None

    # ------------------------------------------------------------- crochets
    def on_connected(self) -> None:
        self._last_sync = 0.0        # force un scan au prochain tick

    def on_disconnected(self) -> None:
        self.postgame_return = None

    def tick(self) -> None:
        self._maybe_sync()
        if time.monotonic() - self._patch_check >= PATCH_TTL:
            self._patch_check = time.monotonic()
            self.app.async_call(current_patch, lambda _: None)

    def on_agent_screen(self, screen: str, shown: bool) -> None:
        # Un écran poussé par l'agent (vraie partie) sort du mode « revue ».
        self.postgame_return = None
        # Fin de partie : on tente une synchro immédiate (+ re-synchros
        # différées : la LCU met parfois quelques secondes à indexer).
        # Le scan périodique reste le filet. `_postgame_baseline` =
        # dernière partie connue AVANT celle-ci, pour savoir quand la
        # nouvelle est vraiment arrivée. À défaut : « non disponible ».
        if shown and screen == "postgame":
            self._postgame_latest = True
            self._postgame_baseline = self.store.newest_id()
            self._show_postgame({})      # « en attente du bilan… »
            self.sync_lcu()
            self._sync_postgame_later(8)
            self._sync_postgame_later(20)
            self._postgame_unavailable_later(24)

    def on_message(self, msg: dict) -> bool:
        msg_type = msg.get("type")
        screens = self.app.screens

        if msg_type == "store_matches":
            # Lot de parties (résumé + bilan) à stocker localement.
            games = msg.get("games", [])
            if games:
                self.store.upsert_matches(games)
                # Remplissage progressif : on rafraîchit la liste à chaque lot.
                if self._current() == "history":
                    screens["history"].reload()
            if msg.get("done"):
                self._on_sync_done()

        elif msg_type == "store_player_games":
            # Parties de l'ami comparé : participations seulement (pas l'historique).
            games = msg.get("games", [])
            if games:
                self.store.upsert_player_games(games)
            if msg.get("done"):
                self._repair_champion_names()
            if msg.get("done") and self._current() == "stats":
                screens["stats"].reload()

        elif msg_type == "lcu_detail":
            # Bilan complet (10 joueurs) demandé au clic : on le met en cache
            # et on l'affiche si on est bien sur l'écran postgame.
            gid = msg.get("gameId")
            detail = msg.get("payload")
            if gid and detail:
                self.store.set_detail(gid, detail)
            if self._current() == "postgame":
                self._show_postgame(detail or {"status": "unavailable"})

        else:
            return False
        return True

    # --------------------------------------------- enrichissement (local, Pi)
    def request_player_info(self, riot_id, champion_id) -> None:
        """Dossier joueur (rang/winrate/mains) via l'API Web, en tâche de fond."""
        rid, cid = riot_id or "", int(champion_id or 0)

        def deliver(info):
            for screen in self.app.screens.values():
                if hasattr(screen, "set_player_info"):
                    screen.set_player_info(rid, info or {})
        self.app.async_call(lambda: build_player_info(self.riot, self.champions, rid, cid),
                            deliver)

    def request_icon(self, champion_id) -> None:
        """Icône de champion (cache disque, sinon CDN), en tâche de fond."""
        cid = int(champion_id or 0)
        if cid <= 0:
            return

        def fetch():
            raw = icon_bytes(cid, self.icon_cache)
            return base64.b64encode(raw).decode("ascii") if raw else None

        def deliver(b64):
            for screen in self.app.screens.values():
                if hasattr(screen, "set_champion_icon"):
                    screen.set_champion_icon(cid, b64)
        self.app.async_call(fetch, deliver)

    def request_splash(self, champion_id) -> None:
        """Splash art depuis Data Dragon, en tâche de fond."""
        cid = int(champion_id or 0)
        if cid <= 0:
            return

        def fetch():
            raw = splash_bytes(self.champions, cid)
            return base64.b64encode(raw).decode("ascii") if raw else None

        def deliver(b64):
            target = self.app.screens.get("champselect")
            if target is not None and hasattr(target, "set_champion_splash"):
                target.set_champion_splash(cid, b64)
        self.app.async_call(fetch, deliver)

    # ---------------------------------------------------------------- synchro
    def sync_lcu(self) -> None:
        """Demande à l'agent les **nouvelles** parties (les 20 récentes de la LCU,
        jusqu'à la dernière déjà stockée). Sans effet si le PC n'est pas connecté.
        Réarme le minuteur du scan périodique (toute synchro décale le prochain)."""
        if not self.app.agent_connected:
            return
        self._last_sync = time.monotonic()
        self.app.server.send({"type": "request_lcu_sync", "since": self.store.newest_id()})
        if "#" in self.compare_rid:
            # Ses parties récentes ; `known` = ce qu'on a déjà (l'agent les saute).
            self.app.server.send({"type": "request_player_sync", "riotId": self.compare_rid,
                                  "known": self.store.known_games(self.compare_rid)})

    def _maybe_sync(self) -> None:
        """Scan périodique (appelé chaque frame) : relance une synchro tous les
        `sync_minutes`. Filet robuste au délai d'indexation LCU, en complément
        de la synchro immédiate de fin de partie (qui, elle, tombe souvent trop
        tôt mais marche quand la LCU indexe vite)."""
        if self._sync_interval <= 0 or not self.app.agent_connected:
            return
        if time.monotonic() - self._last_sync >= self._sync_interval:
            self.sync_lcu()

    def _sync_postgame_later(self, delay: float) -> None:
        """Re-synchro différée après une fin de partie : la LCU met parfois
        quelques secondes à indexer la partie qui vient de finir."""
        def wait():
            time.sleep(delay)

        def go(_):
            # Seulement si on est toujours sur le bilan de fin (pas parti ailleurs).
            if self._current() == "postgame" and self._postgame_latest:
                self.sync_lcu()
        self.app.async_call(wait, go)

    def _postgame_unavailable_later(self, delay: float) -> None:
        """Après les re-synchros : si la partie qui vient de finir n'est toujours
        pas dans le store (LCU lente à indexer), on affiche « détail non
        disponible » plutôt qu'une attente indéfinie. Le scan périodique continue
        et remplacera ce message par le vrai bilan dès que la partie arrive."""
        def wait():
            time.sleep(delay)

        def go(_):
            if (self._current() == "postgame" and self._postgame_latest
                    and self.store.newest_id() == self._postgame_baseline):
                self._show_postgame({"status": "unavailable"})
        self.app.async_call(wait, go)

    def _repair_champion_names(self) -> None:
        """Noms de champion vides dans le store (agent démarré sans sa table de
        noms) : complétés depuis l'id, en tâche de fond (table CDN au besoin)."""
        def done(changed):
            name = self._current()
            if changed and name in ("history", "stats"):
                self.app.screens[name].reload()
        self.app.async_call(lambda: self.store.fill_champion_names(self.champions.name), done)

    def _on_sync_done(self) -> None:
        """Fin d'une synchro : rafraîchit l'écran courant si besoin."""
        self._repair_champion_names()
        name = self._current()
        if name == "history":
            self.app.screens["history"].reload()
        elif name == "postgame" and self._postgame_latest:
            # On n'affiche le bilan « dernière partie » que si une NOUVELLE
            # partie est arrivée (sinon on montrerait par erreur la précédente).
            newest = self.store.newest_id()
            if newest and newest != self._postgame_baseline:
                self._load_detail(newest)

    # --------------------------------------------------------- actions client
    def lcu_action(self, action: str) -> None:
        """Envoie une commande au client via l'agent (ex. accepter un ready-check)."""
        self.app.server.send({"type": "lcu_action", "action": action})

    def play(self) -> None:
        """Bouton unique : demande à l'agent de lancer le client s'il est fermé,
        créer le lobby ARAM Chaos s'il n'est pas déjà le bon, puis inviter l'ami
        configuré (`lobby_invite`) — chaque étape déjà faite étant sautée côté
        agent. Sans effet si l'agent est déconnecté."""
        if not self.app.agent_connected:
            return
        self.app.server.send({"type": "lcu_action", "action": "play",
                              "queueId": self.lobby_queue, "invite": self.lobby_invite})

    # ------------------------------------------------------------- navigation
    def open_history(self) -> None:
        """Ouvre la liste des parties (verrou manuel). Lit le store local et
        déclenche une synchro si le PC est connecté."""
        hist = self.app.screens.get("history")
        if hist is None:
            return
        self.app.manual_screen = "history"
        self.app.set_screen("history")
        hist.start_fresh()

    def open_stats(self) -> None:
        """Ouvre les stats comparées (verrou manuel ; RETOUR → historique)."""
        stats = self.app.screens.get("stats")
        if stats is None:
            return
        self.app.manual_screen = "stats"
        self.app.set_screen("stats")
        stats.reload()

    def open_postgame_review(self, game_id) -> None:
        """Ouvre le bilan d'une partie choisie en mode « revue » (RETOUR →
        historique). Bilan depuis le store si en cache, sinon demandé à l'agent."""
        if "postgame" not in self.app.screens:
            return
        self._postgame_latest = False
        self.postgame_return = "history"
        self.app.manual_screen = "postgame"
        self.app.set_screen("postgame")
        self._load_detail(game_id)

    # ------------------------------------------------------------------ bilan
    def _mark_friends(self, payload: dict) -> dict:
        """Colore les amis (rose) sur un bilan via le `riotId` de chaque joueur
        (appliqué à la lecture : un ami ajouté plus tard est pris en compte)."""
        for p in (payload or {}).get("players", []):
            rid = p.get("riotId") or ""
            if not p.get("isSelf") and "#" in rid:
                gn, tl = rid.split("#", 1)
                p["isFriend"] = normalize_riot_id(gn, tl) in self.friends
        return payload

    def _show_postgame(self, detail) -> None:
        pg = self.app.screens.get("postgame")
        if pg is not None:
            pg.update_data(self._mark_friends(detail or {}))

    def _load_detail(self, game_id) -> None:
        """Affiche le bilan : depuis le store (consultable PC éteint) si connu,
        sinon le demande à l'agent/LCU, qui le renverra et on le met en cache."""
        detail = self.store.detail(game_id) if game_id else None
        if detail:
            self._show_postgame(detail)
        else:
            self._show_postgame({})      # « en attente du bilan… »
            if self.app.agent_connected and game_id:
                self.app.server.send({"type": "request_lcu_detail", "gameId": game_id})
