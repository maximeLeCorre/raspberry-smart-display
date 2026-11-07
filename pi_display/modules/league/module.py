"""Logique du module League (côté Pi) : API Web Riot + CDN, store des parties,
synchro LCU via l'agent, bilan de fin de partie, bouton « Jouer », écarts.

Écarts (écran `counters`) : en direct, valeurs du dernier message + relevé en
mémoire toutes les `LIVE_STEP` s de jeu pour la tendance (or ESTIMÉ = valeur des
objets : le Live Client ne donne pas l'or des autres) ; après la partie, la
timeline LCU (1 point/min, or total exact) est demandée à l'agent et stockée
(`timelines`). Le relevé direct n'est jamais stocké.

Sorti de `app.py` (qui reste agnostique du jeu) : l'App appelle les crochets
de `Module` ; les écrans League passent par `app.modules["league"]`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import time
from pathlib import Path

import pygame

from config import load_riot_key
from icon_cache import IconCache
from modules.base import Module
from modules.league.champ_select_screen import ChampSelectScreen
from modules.league.counters_screen import CountersScreen
from modules.league.history_screen import MatchHistoryScreen
from modules.league.lol_screen import LolScreen
from modules.league.postgame_screen import PostGameScreen
from modules.league.queue_screen import QueueScreen
from modules.league.stats_screen import StatsScreen
from riot_web import (PATCH_TTL, Champions, ItemPrices, RiotWeb, build_player_info,
                      current_patch, icon_bytes, normalize_riot_id, splash_bytes)
from store import Store

LIVE_STEP = 10                         # s de jeu entre deux points en direct
TEAM_IDS = {"ORDER": 100, "CHAOS": 200}
TIMELINE_BACKFILL = 20                 # parties récentes dont on veut la timeline


def _new_series() -> dict:
    return {"players": [], "frames": [], "estimated": True}


def _live_key(player: dict) -> str:
    return player.get("riotId") or player.get("name") or ""


class LeagueModule(Module):
    name = "league"
    screens = [QueueScreen, ChampSelectScreen, LolScreen, CountersScreen, PostGameScreen,
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
        self._remote_icons: dict[int, bytes] = {}   # icônes réduites pour la montre
        self._remote_icons_lock = threading.Lock()
        self._ready_pushed = False      # notification du ready-check courant déjà envoyée
        self._choice_pushed = False     # idem pour le choix de départ
        self._invite_pushed = ""        # id de la dernière invitation notifiée
        self._lobby_members: set | None = None   # autres membres du lobby (None : pas de lobby)
        self._chat_pushed = ""          # id du dernier message notifié
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
        # Écarts en direct (mémoire) + prix des objets pour estimer l'or.
        self.items = ItemPrices()
        self._items_loading = False
        self.live = _new_series()
        # Partie affichée par le bilan (écarts « de cette partie »).
        self.postgame_game_id = None
        # Timelines demandées à l'agent UNE à la fois (sans bloquer son récepteur).
        self._timeline_queue: list[str] = []
        self._timeline_pending: str | None = None
        self._timeline_failed: set[str] = set()   # indisponibles (pas de re-demande)
        self._repair_champion_names()

    def _current(self) -> str | None:
        cur = self.app.current
        return cur.name if cur is not None else None

    # ------------------------------------------------------------- crochets
    def on_connected(self) -> None:
        self._last_sync = 0.0        # force un scan au prochain tick

    def on_disconnected(self) -> None:
        self.postgame_return = None
        self._timeline_queue, self._timeline_pending = [], None

    def tick(self) -> None:
        self._maybe_sync()
        self._maybe_push_ready_check()
        if time.monotonic() - self._patch_check >= PATCH_TTL:
            self._patch_check = time.monotonic()
            self.app.async_call(current_patch, lambda _: None)

    def _maybe_push_ready_check(self) -> None:
        """Partie trouvée → notification sur la montre (une par ready-check),
        avec Accepter/Refuser ; périmée au bout de la fenêtre du ready-check.
        Idem au choix de départ de la sélection (ouvre l'app dessus), à une
        invitation, à l'arrivée d'un joueur dans notre lobby et à un message privé."""
        queue = ((self.app.agent_data.get("queue") or {})
                 if self.app.network_screen == "queue" else {})
        ready = queue.get("state") == "readycheck" and queue.get("response") == "None"
        if ready and not self._ready_pushed:
            remaining = int(queue.get("remaining") or 10)
            self.app.push.notify(
                {"alert": {"title": "Partie trouvée !", "body": f"{remaining} s pour accepter"},
                 "sound": "default", "category": "READY_CHECK"},
                collapse_id="readycheck", ttl=max(3, remaining))
        self._ready_pushed = ready

        # Choix de départ (2-3 champions, ~15 s) : la montre ouvre l'app dessus.
        cs = ((self.app.agent_data.get("champselect") or {})
              if self.app.network_screen == "champselect" else {})
        choices = [c.get("championName") or "?" for c in cs.get("choices") or []]
        if choices and not self._choice_pushed:
            left = int((cs.get("timer") or {}).get("left") or 15)
            self.app.push.notify(
                {"alert": {"title": "Choisis ton champion", "body": " ou ".join(choices)},
                 "sound": "default", "category": "CHAMP_CHOICE"},
                collapse_id="champchoice", ttl=max(3, left))
        self._choice_pushed = bool(choices)

        # Invitation dans un lobby (client ouvert) : Accepter ouvre l'app.
        inv = (self.app.agent_data.get("default") or {}).get("invitation") or {}
        if inv.get("id") and inv["id"] != self._invite_pushed:
            self.app.push.notify(
                {"alert": {"title": f"Invitation de {inv.get('from') or '?'}",
                           "body": inv.get("queueName") or "Rejoindre son lobby ?"},
                 "sound": "default", "category": "LOBBY_INVITE"},
                collapse_id="invite", ttl=120, extra={"invitationId": inv["id"]})
        self._invite_pushed = inv.get("id") or ""

        # Quelqu'un rejoint NOTRE lobby (pas à sa création ni quand on en rejoint un).
        lobby = (self.app.agent_data.get("default") or {}).get("lobby")
        members = ({m.get("name") for m in lobby.get("members") or [] if not m.get("isSelf")}
                   if lobby and self.app.network_screen == "default" else None)
        if members is not None and self._lobby_members is not None:
            for name in sorted(members - self._lobby_members):
                self.app.push.notify(
                    {"alert": {"title": f"{name} a rejoint ton lobby",
                               "body": lobby.get("queueName") or ""},
                     "sound": "default", "category": "LOBBY_JOIN"},
                    collapse_id="lobbyjoin", ttl=300)
        self._lobby_members = members

        # Message privé reçu (menu ou lobby : l'agent ne lit le chat qu'à l'accueil).
        msg = (self.app.agent_data.get("default") or {}).get("chat") or {}
        if msg.get("id") and msg["id"] != self._chat_pushed:
            self.app.push.notify(
                {"alert": {"title": f"Message de {msg.get('from') or '?'}",
                           "body": msg.get("body") or ""},
                 "sound": "default", "category": "CHAT_MESSAGE"},
                collapse_id=f"chat-{msg.get('from') or ''}"[:64], ttl=600,
                extra={"conversationId": msg.get("conv") or "", "from": msg.get("from") or ""})
        self._chat_pushed = msg.get("id") or self._chat_pushed

    def on_agent_screen(self, screen: str, shown: bool) -> None:
        # Un écran poussé par l'agent (vraie partie) sort du mode « revue ».
        self.postgame_return = None
        if screen == "lol":                   # nouvelle partie : écarts à zéro
            self.live = _new_series()
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

    def route_screen(self, screen: str) -> str:
        # En partie, les écarts d'abord (le tableau reste à un clic : TABLEAU).
        if screen == "lol" and "counters" in self.app.screens:
            self.app.screens["counters"].show_live()
            return "counters"
        return screen

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

        elif msg_type == "lcu_timeline":
            gid = str(msg.get("gameId") or "")
            if msg.get("payload"):
                self.store.set_timeline(gid, msg["payload"])
            elif gid:
                self._timeline_failed.add(gid)
            if self._timeline_pending == gid:
                self._timeline_pending = None
            counters = screens.get("counters")
            if counters is not None and self._current() == "counters":
                counters.refresh()
            self._next_timeline()

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

    # ------------------------------------------------- écarts (live + timeline)
    def note_live(self, payload: dict) -> None:
        """Partie en cours (agent, ~1/s) : `current` = valeurs du message (compteurs),
        et un point gardé toutes les `LIVE_STEP` s de jeu (tendance sur 1 min).
        Or = valeur totale des objets (estimée) ; CS, niveau, kills exacts."""
        players = (payload or {}).get("players") or []
        if not players:
            return
        t = int(payload.get("game_time") or 0)
        frames = self.live["frames"]
        if frames and t < frames[-1]["t"]:     # autre partie (Pi redémarré en jeu…)
            self.live = _new_series()
            frames = self.live["frames"]
        if not self.live["players"]:
            self.live["players"] = [{
                "name": p.get("name", ""), "riotId": p.get("riotId", ""),
                "championId": p.get("championId", 0), "champion": p.get("champion", ""),
                "team": TEAM_IDS.get(p.get("team"), 0), "isSelf": bool(p.get("isSelf")),
            } for p in players]
        if not self.items.ready():
            self._load_items()
        by_key = {_live_key(p): p for p in players}
        cols = [by_key.get(_live_key(p)) or {} for p in self.live["players"]]
        frame = {
            "t": t,
            "gold": [self.items.value(p.get("items")) if p else None for p in cols],
            "cs": [p.get("cs", 0) for p in cols],
            "level": [p.get("level", 0) for p in cols],
            "kills": [p.get("k", 0) for p in cols],
        }
        self.live["current"] = frame
        if not frames or t - frames[-1]["t"] >= LIVE_STEP:
            frames.append(frame)

    def _load_items(self) -> None:
        if self._items_loading:
            return
        self._items_loading = True

        def done(_):
            self._items_loading = False
        self.app.async_call(self.items.load, done)

    def game_series(self, game_id) -> tuple[dict | None, str]:
        """Données d'une partie terminée : (série, état). Timeline stockée si
        connue ; sinon, juste après la partie, le relevé en direct (estimé)."""
        timeline = self.store.timeline(game_id) if game_id else None
        if timeline:
            return timeline, "ok"
        if self._postgame_latest and self.live.get("current"):
            return self.live, "ok"
        if game_id and str(game_id) in self._timeline_failed:
            return None, "unavailable"
        if game_id and self.app.agent_connected:
            return None, "loading"
        return None, "offline"

    def _queue_timelines(self, game_ids) -> None:
        """Demande à l'agent les timelines manquantes de ces parties (une à la fois)."""
        missing = [g for g in self.store.without_timeline(game_ids)
                   if g not in self._timeline_failed and g not in self._timeline_queue
                   and g != self._timeline_pending]
        self._timeline_queue.extend(missing)
        self._next_timeline()

    def _next_timeline(self) -> None:
        if self._timeline_pending or not self._timeline_queue or not self.app.agent_connected:
            return
        self._timeline_pending = self._timeline_queue.pop(0)
        self.app.server.send({"type": "request_lcu_timeline", "gameId": self._timeline_pending})

    def open_counters(self) -> None:
        """Depuis l'écran de partie : écarts en direct (sans verrou : l'agent
        reprend la main en fin de partie, comme pour le tableau)."""
        counters = self.app.screens.get("counters")
        if counters is None:
            return
        counters.show_live()
        self.app.set_screen("counters")

    def open_counters_review(self) -> None:
        """Depuis le bilan : écarts de cette partie (RETOUR -> bilan)."""
        counters = self.app.screens.get("counters")
        if counters is None:
            return
        gid = self.postgame_game_id
        key = str(gid or "")
        if (key and not self.store.timeline(key) and key not in self._timeline_queue
                and key != self._timeline_pending and key not in self._timeline_failed):
            self._timeline_queue.insert(0, key)       # priorité : on la regarde
            self._next_timeline()
        counters.show_game(gid)
        self.app.manual_screen = "counters"
        self.app.set_screen("counters")

    def close_counters(self, live: bool) -> None:
        """RETOUR/TABLEAU des écarts : partie en cours -> écran voulu par
        l'agent ; revue -> bilan."""
        if live:
            target = self.app.network_screen
            self.app.set_screen(target if target in self.app.screens else "default")
        else:
            self.app.manual_screen = "postgame"
            self.app.set_screen("postgame")

    def _on_sync_done(self) -> None:
        """Fin d'une synchro : rafraîchit l'écran courant si besoin, et demande
        les timelines des parties récentes qui ne les ont pas encore."""
        self._repair_champion_names()
        self._queue_timelines([g["gameId"] for g in self.store.query(limit=TIMELINE_BACKFILL)])
        name = self._current()
        if name == "history":
            self.app.screens["history"].reload()
        elif name == "postgame" and self._postgame_latest:
            # On n'affiche le bilan « dernière partie » que si une NOUVELLE
            # partie est arrivée (sinon on montrerait par erreur la précédente).
            newest = self.store.newest_id()
            if newest and newest != self._postgame_baseline:
                self._load_detail(newest)

    # ------------------------------------------------- télécommande (montre)
    def remote_view(self) -> dict:
        """Ready-check et sélection (banc ARAM) pour l'API télécommande. En partie,
        seulement notre dernier kill : le tableau changerait chaque seconde pour rien."""
        screen, data = self.app.network_screen, self.app.agent_data
        if screen == "queue":
            return {"queue": data.get("queue") or {}}
        if screen == "champselect":
            cs = data.get("champselect") or {}
            me = next((p for p in cs.get("players", []) if p.get("isSelf")), {})
            return {"champselect": {
                "me": {"championId": me.get("championId", 0),
                       "championName": me.get("championName", "")},
                "bench": cs.get("bench", []),
                "choices": cs.get("choices", []),
                "rerolls": cs.get("rerolls", 0),
                "timer": cs.get("timer", {}),
            }}
        if screen == "lol":       # en partie : seulement notre dernier kill (vibration)
            return {"game": {"kill": (data.get("lol") or {}).get("myKill")}}
        if screen == "default":   # accueil : bouton Jouer + lobby (joueurs, Lancer)
            home = data.get("default") or {}
            return {"home": {"client": bool(home.get("client")),
                             "lobby": self._lobby_with_default_friend(home.get("lobby")),
                             "invitation": home.get("invitation"),
                             "playStatus": home.get("playStatus") or "",
                             "playBusy": bool(home.get("playBusy")),
                             "playInvite": self.lobby_invite}}
        return {}

    def _lobby_with_default_friend(self, lobby: dict | None) -> dict | None:
        """Ami par défaut (`[lol] lobby_invite`, comme le bouton Jouer) marqué et en tête."""
        if not lobby:
            return lobby
        want = self.lobby_invite.lower()
        friends = [{**f, "isDefault": bool(want) and want in (f.get("name", "").lower(),
                                                             f.get("riotId", "").lower())}
                   for f in lobby.get("friends") or []]
        friends.sort(key=lambda f: not f["isDefault"])     # tri stable : reste dans l'ordre
        return {**lobby, "friends": friends}

    def remote_asset(self, name: str) -> tuple[bytes, str] | None:
        """`sounds` (liste + empreintes) et `sound/<kill1…5>` : sons des kills de la
        montre (`sounds/`, gitignoré : extraits sans licence, hors dépôt public).
        `icon/<championId>` : icône carrée (cache disque `icons.db`, sinon CDN),
        **réduite** pour la montre (~4 Ko au lieu de ~30 : le lien montre ↔ iPhone
        en Bluetooth est lent). Le verrou sérialise aussi pygame (thread HTTP)."""
        kind, _, ident = name.partition("/")
        if kind == "sounds":
            return json.dumps(_kill_sounds()).encode(), "application/json"
        if kind == "sound":       # nom exact de la liste : pas de chemin arbitraire
            sound = _kill_sounds().get(ident)
            if sound is None:
                return None
            path = SOUNDS_DIR / f"{ident}.{sound['ext']}"
            return path.read_bytes(), AUDIO_TYPES[path.suffix]
        if kind != "icon" or not ident.isdigit():
            return None
        cid = int(ident)
        small = self._remote_icons.get(cid)
        if small is None:
            raw = icon_bytes(cid, self.icon_cache)   # hors verrou : téléchargements en parallèle
            if not raw:
                return None
            with self._remote_icons_lock:
                small = self._remote_icons[cid] = _shrink_icon(raw)
        return small, "image/jpeg"

    def on_remote_action(self, body: dict) -> tuple[int, dict] | None:
        """Actions à distance, **vérifiées sur l'état courant** : une liste vue
        sur la montre peut être périmée (champion pris entre-temps) → 409."""
        action = body.get("action")
        screen, data = self.app.network_screen, self.app.agent_data
        if action in ("accept", "decline"):
            queue = data.get("queue") or {}
            if screen != "queue" or queue.get("state") != "readycheck":
                return 409, {"ok": False, "error": "aucun ready-check en cours"}
            self.lcu_action(action)
            return 200, {"ok": True}
        if action in ("play", "play_cancel"):        # = bouton Jouer de l'accueil du Pi
            if action == "play":
                self.play()
            else:
                self.play_cancel()
            return 200, {"ok": True}
        if action in ("invite_accept", "invite_decline"):
            inv = (data.get("default") or {}).get("invitation") or {}
            if not inv or str(body.get("invitationId") or "") != inv.get("id"):
                return 409, {"ok": False, "error": "invitation expirée"}
            self.app.server.send({"type": "lcu_action", "action": action,
                                  "invitationId": inv["id"]})
            return 200, {"ok": True}
        if action == "invite":
            lobby = (data.get("default") or {}).get("lobby") if screen == "default" else None
            sid = body.get("summonerId")
            if not lobby or sid not in {f.get("summonerId") for f in lobby.get("friends") or []}:
                return 409, {"ok": False, "error": "ami non invitable"}
            self.app.server.send({"type": "lcu_action", "action": "invite", "summonerId": sid})
            return 200, {"ok": True}
        if action == "start_queue":
            lobby = (data.get("default") or {}).get("lobby") if screen == "default" else None
            if not lobby:
                return 409, {"ok": False, "error": "pas de lobby"}
            if not lobby.get("isLeader"):
                return 409, {"ok": False, "error": "seul le chef lance"}
            self.lcu_action("start_queue")
            return 200, {"ok": True}
        if action in ("leave_lobby", "quit_client"):
            home = (data.get("default") or {}) if screen == "default" else {}
            if action == "leave_lobby" and not home.get("lobby"):
                return 409, {"ok": False, "error": "pas de lobby"}
            if action == "quit_client" and not home.get("client"):
                # Hors accueil (sélection, partie) : jamais de fermeture à distance.
                return 409, {"ok": False, "error": "client fermé ou en partie"}
            self.lcu_action(action)
            return 200, {"ok": True}
        if action == "chat_reply":      # réponse à un message privé (notif / app montre)
            conv, text = body.get("conversationId"), body.get("body")
            if not (isinstance(conv, str) and conv and len(conv) <= 200
                    and isinstance(text, str) and 0 < len(text.strip()) <= MAX_REPLY):
                return 400, {"ok": False, "error": "réponse invalide"}
            if screen == "default" and not (data.get("default") or {}).get("client"):
                return 409, {"ok": False, "error": "client fermé"}
            self.app.server.send({"type": "lcu_action", "action": "chat_reply",
                                  "conversationId": conv, "body": text.strip()})
            return 200, {"ok": True}
        if action == "cancel_queue":
            if screen != "queue" or (data.get("queue") or {}).get("state") == "readycheck":
                return 409, {"ok": False, "error": "pas en file"}
            self.lcu_action("cancel_queue")
            return 200, {"ok": True}
        if action in ("swap", "reroll", "pick"):
            if screen != "champselect":
                return 409, {"ok": False, "error": "pas en sélection"}
            cs = data.get("champselect") or {}
            if action == "reroll":
                if not cs.get("rerolls"):
                    return 409, {"ok": False, "error": "plus de relance"}
                self.lcu_action("reroll")
                return 200, {"ok": True}
            try:
                cid = int(body.get("championId") or 0)
            except (TypeError, ValueError):
                cid = 0
            if action == "pick":   # choix de départ (2-3 champions)
                if cid not in {c.get("championId") for c in cs.get("choices", [])}:
                    return 409, {"ok": False, "error": "choix terminé"}
                self.app.server.send({"type": "lcu_action", "action": "pick", "championId": cid})
                return 200, {"ok": True}
            if cid not in {c.get("championId") for c in cs.get("bench", [])}:
                return 409, {"ok": False, "error": "champion plus sur le banc"}
            self.app.server.send({"type": "lcu_action", "action": "swap", "championId": cid})
            return 200, {"ok": True}
        return None

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

    def play_cancel(self) -> None:
        """Ré-appui sur « Jouer » pendant l'enchaînement : l'agent arrête ses
        demandes (lancement en boucle, attente du client…)."""
        self.app.server.send({"type": "lcu_action", "action": "play_cancel"})

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
        self.postgame_game_id = game_id
        detail = self.store.detail(game_id) if game_id else None
        if detail:
            self._show_postgame(detail)
        else:
            self._show_postgame({})      # « en attente du bilan… »
            if self.app.agent_connected and game_id:
                self.app.server.send({"type": "request_lcu_detail", "gameId": game_id})


REMOTE_ICON_SIZE = 96    # px : 48 pt × 2 (écran Retina de la montre)


def _shrink_icon(raw: bytes) -> bytes:
    """PNG du CDN → JPEG 96 px (pas besoin d'écran pygame : pur calcul)."""
    surface = pygame.image.load(io.BytesIO(raw), "icon.png")
    small = pygame.transform.smoothscale(surface, (REMOTE_ICON_SIZE, REMOTE_ICON_SIZE))
    out = io.BytesIO()
    pygame.image.save(small, out, "icon.jpg")
    return out.getvalue()


SOUNDS_DIR = Path(__file__).resolve().parents[2] / "sounds"
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".caf": "audio/x-caf"}
MAX_REPLY = 200        # réponse à un message privé depuis la montre (caractères)


def _kill_sounds() -> dict[str, dict]:
    """{"kill1": {"ext": "mp3", "hash": …}, …} : la montre ne retélécharge qu'un son
    dont l'empreinte a changé. Relu à chaque appel (5 petits fichiers, rare)."""
    out = {}
    for path in sorted(SOUNDS_DIR.glob("kill[1-5].*")):
        if path.suffix.lower() in AUDIO_TYPES:
            out[path.stem] = {"ext": path.suffix[1:].lower(),
                              "hash": hashlib.sha1(path.read_bytes()).hexdigest()}
    return out
