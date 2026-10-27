"""Application d'affichage : fenêtre, boucle de rendu, routage des écrans.

L'app est **agnostique** des jeux : elle charge les écrans fournis par les
**modules** activés (voir `modules/`) et affiche celui que l'agent demande.

À chaque frame :
  1. événements Pygame (fermeture, clavier = boutons simulés, souris = tactile) ;
  2. actions des boutons GPIO (queue) ;
  3. messages réseau (queue) : changement d'écran, données, (dé)connexion ;
  4. l'écran courant redessine ses zones dynamiques (dirty rects) ;
  5. présentation à l'écran.

Rendu et mise à l'échelle :
  - Rendu toujours en 800x480 (résolution interne).
  - scale=1 : dessin direct + `pygame.display.update(dirty)` (optimal Pi).
  - --scale N : surface hors-écran agrandie à la présentation (test PC).
"""

from __future__ import annotations

import base64
import queue
import threading
import time

import pygame

from inputs import ACTION_BACK, ACTION_NEXT, InputManager
from modules import MODULES
from network import NetworkServer
from riot_web import (Champions, RiotWeb, build_player_info, icon_bytes,
                      normalize_riot_id, splash_bytes)
from store import Store

DEFAULT_SCREEN = "default"


class App:
    def __init__(self, config, *, fullscreen, scale, monitor, debug, host, port,
                 auth_token="", ssl_context=None, riot_key=""):
        self.config = config
        self.width = config["display"]["width"]
        self.height = config["display"]["height"]
        self.fps = config["display"]["fps"]
        self.scale = max(1, scale)
        self.fullscreen = fullscreen
        self.debug = debug

        # Accès internet « League » (le Pi est autonome : API Web + CDN).
        riot_cfg = config.get("riot", {})
        lol_cfg = config.get("lol", {})
        self.champions = Champions()
        self.riot = RiotWeb(riot_key, riot_cfg.get("platform", "euw1"),
                            riot_cfg.get("regional", "europe"))
        self.summoner_rid = (lol_cfg.get("summoner") or "").strip()
        # Bouton « créer un lobby » du défaut : file toujours ARAM Chaos (2400),
        # et ami invité s'il est en ligne (vide = pas d'invitation).
        self.lobby_queue = int(lol_cfg.get("lobby_queue", 2400) or 2400)
        self.lobby_invite = (lol_cfg.get("lobby_invite") or "").strip()
        self.friends = {
            normalize_riot_id(*rid.split("#", 1))
            for rid in lol_cfg.get("friends", [])
            if isinstance(rid, str) and "#" in rid
        }
        self._my_puuid_cache = ""
        # Exécution asynchrone des appels réseau (HTTP) hors de la boucle de
        # rendu : un worker produit un résultat, livré au thread principal.
        self._io_results: "queue.Queue[tuple]" = queue.Queue()
        # Base locale des parties (historique consultable PC éteint).
        self.store = Store()
        # Bilan en mode « dernière partie » (fin de game) vs « revue » (clic).
        self._postgame_latest = False
        # Id de la partie la plus récente AVANT la partie en cours : sert à
        # savoir, en fin de partie, si celle qui vient de finir est bien
        # arrivée dans le store (sinon on afficherait par erreur la précédente).
        self._postgame_baseline = None
        # Scan périodique de l'historique (LCU) : insensible au délai
        # d'indexation. `_last_sync` = time.monotonic() du dernier scan.
        self._sync_interval = max(0, int(lol_cfg.get("sync_minutes", 3) or 0)) * 60
        self._last_sync = 0.0

        pygame.init()
        pygame.display.set_caption("Pi Display (simulateur écran 5\")")
        self._init_display(monitor)
        self.clock = pygame.time.Clock()
        self._debug_font = pygame.font.Font(None, 26)
        self.last_key = None

        # Queues alimentées par des threads (réseau) ou callbacks (GPIO).
        self.net_queue: "queue.Queue[dict]" = queue.Queue()
        self.action_queue: "queue.Queue[str]" = queue.Queue()

        # Serveur réseau + entrées physiques.
        self.server = NetworkServer(host, port, self.net_queue,
                                    auth_token=auth_token, ssl_context=ssl_context)
        self.server.start()
        self.inputs = InputManager(config, self.action_queue, debug)

        # Écrans disponibles, construits depuis les modules activés en config.
        self._build_screens(config.get("modules", {}))
        self.current = None

        # Verrou de contrôle manuel : quand l'utilisateur force un écran (bouton),
        # on ignore les « set_screen » réseau jusqu'à (re)connexion de l'agent ou
        # retour explicite au défaut.
        self.manual_screen: str | None = None
        # Dernier écran demandé par l'agent (même ignoré) : sert au badge « Rejoindre ».
        self.network_screen = DEFAULT_SCREEN
        # Agent (PC) connecté ? Utilisé par l'historique (nécessite le PC/LCU).
        self.agent_connected = False
        # Écran de retour quand on consulte une partie depuis l'historique
        # (RETOUR du bilan -> historique au lieu du défaut). None = flux normal.
        self.postgame_return: str | None = None

        self.running = False
        self.set_screen(DEFAULT_SCREEN)

    def _build_screens(self, modules_cfg: dict) -> None:
        self.screens = {}
        self.enabled_modules = []
        for module in MODULES:
            if not (module.always_on or modules_cfg.get(module.name, True)):
                continue
            self.enabled_modules.append(module.name)
            for cls in module.screens:
                self.screens[cls.name] = cls(self)
        # Ordre du bouton « suivant » : les écrans marqués cycle=True.
        self.screen_order = [
            cls.name for module in MODULES for cls in module.screens
            if cls.name in self.screens and cls.cycle
        ]
        print(f"[app] Modules actifs : {self.enabled_modules}")

    # --------------------------------------------------------------- display
    def _init_display(self, monitor) -> None:
        if self.fullscreen:
            flags = pygame.FULLSCREEN
            window_size = (self.width, self.height)
        else:
            flags = 0
            window_size = (self.width * self.scale, self.height * self.scale)

        kwargs = {}
        if monitor is not None:
            kwargs["display"] = monitor

        self.window = pygame.display.set_mode(window_size, flags, **kwargs)
        self.window_size = window_size
        # Interface tactile : pas de curseur souris visible en plein écran (Pi).
        if self.fullscreen:
            pygame.mouse.set_visible(False)
        self.direct = (self.scale == 1)
        self.surface = self.window if self.direct else pygame.Surface((self.width, self.height))

    def present(self, dirty) -> None:
        if self.direct:
            if dirty:
                pygame.display.update(dirty)
        else:
            scaled = pygame.transform.scale(self.surface, self.window_size)
            self.window.blit(scaled, (0, 0))
            pygame.display.flip()

    # ---------------------------------------------------------------- écrans
    def set_screen(self, name: str) -> None:
        if name not in self.screens:
            print(f"[app] Écran inconnu ou module désactivé, ignoré : {name!r}")
            return
        if self.current is not None and self.current.name == name:
            return
        if self.current is not None:
            self.current.exit()
        self.current = self.screens[name]
        self.current.enter()
        self.current.draw_background(self.surface)
        self.current.draw(self.surface)
        self.present([pygame.Rect(0, 0, self.width, self.height)])
        print(f"[app] Écran actif : {name}")

    def _next_screen(self) -> str:
        if not self.screen_order:
            return DEFAULT_SCREEN
        if self.current.name not in self.screen_order:
            return self.screen_order[0]
        idx = self.screen_order.index(self.current.name)
        return self.screen_order[(idx + 1) % len(self.screen_order)]

    # --------------------------------------------------------------- actions
    def do_action(self, action: str) -> None:
        if action == ACTION_BACK:
            self.manual_screen = DEFAULT_SCREEN
            self.set_screen(DEFAULT_SCREEN)
        elif action == ACTION_NEXT:
            target = self._next_screen()
            self.manual_screen = target
            self.set_screen(target)

    # ------------------------------------------------------ exécution async
    def async_call(self, fn, on_result) -> None:
        """Exécute `fn()` (appel réseau bloquant) dans un thread ; le résultat
        est livré à `on_result(res)` dans le thread principal (voir `_drain_io`)."""
        def worker():
            try:
                res = fn()
            except Exception as exc:
                print(f"[app] Appel async en échec : {exc}")
                res = None
            self._io_results.put((on_result, res))
        threading.Thread(target=worker, daemon=True).start()

    def _drain_io(self) -> None:
        while True:
            try:
                on_result, res = self._io_results.get_nowait()
            except queue.Empty:
                break
            try:
                on_result(res)
            except Exception as exc:
                print(f"[app] Livraison async en échec : {exc}")

    def _my_puuid(self) -> str:
        """Notre PUUID externe (résolu une fois). À appeler depuis un worker
        (bloquant réseau au 1er appel)."""
        if self._my_puuid_cache or "#" not in self.summoner_rid:
            return self._my_puuid_cache
        gn, tl = self.summoner_rid.split("#", 1)
        self._my_puuid_cache = self.riot.resolve_puuid(gn.strip(), tl.strip()) or ""
        return self._my_puuid_cache

    # --------------------------------------------- enrichissement (local, Pi)
    def request_player_info(self, riot_id, champion_id) -> None:
        """Dossier joueur (rang/winrate/mains) via l'API Web, en tâche de fond."""
        rid, cid = riot_id or "", int(champion_id or 0)

        def deliver(info):
            for screen in self.screens.values():
                if hasattr(screen, "set_player_info"):
                    screen.set_player_info(rid, info or {})
        self.async_call(lambda: build_player_info(self.riot, self.champions, rid, cid),
                        deliver)

    def request_icon(self, champion_id) -> None:
        """Icône de champion depuis le CDN Community Dragon, en tâche de fond."""
        cid = int(champion_id or 0)
        if cid <= 0:
            return

        def fetch():
            raw = icon_bytes(cid)
            return base64.b64encode(raw).decode("ascii") if raw else None

        def deliver(b64):
            for screen in self.screens.values():
                if hasattr(screen, "set_champion_icon"):
                    screen.set_champion_icon(cid, b64)
        self.async_call(fetch, deliver)

    def request_splash(self, champion_id) -> None:
        """Splash art depuis Data Dragon, en tâche de fond."""
        cid = int(champion_id or 0)
        if cid <= 0:
            return

        def fetch():
            raw = splash_bytes(self.champions, cid)
            return base64.b64encode(raw).decode("ascii") if raw else None

        def deliver(b64):
            target = self.screens.get("champselect")
            if target is not None and hasattr(target, "set_champion_splash"):
                target.set_champion_splash(cid, b64)
        self.async_call(fetch, deliver)

    def sync_lcu(self) -> None:
        """Demande à l'agent les **nouvelles** parties (les 20 récentes de la LCU,
        jusqu'à la dernière déjà stockée). Sans effet si le PC n'est pas connecté.
        Réarme le minuteur du scan périodique (toute synchro décale le prochain)."""
        if not self.agent_connected:
            return
        self._last_sync = time.monotonic()
        self.server.send({"type": "request_lcu_sync", "since": self.store.newest_id()})

    def _maybe_sync(self) -> None:
        """Scan périodique (appelé chaque frame) : relance une synchro tous les
        `sync_minutes`. Filet robuste au délai d'indexation LCU, en complément
        de la synchro immédiate de fin de partie (qui, elle, tombe souvent trop
        tôt mais marche quand la LCU indexe vite)."""
        if self._sync_interval <= 0 or not self.agent_connected:
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
            if (self.current is not None and self.current.name == "postgame"
                    and self._postgame_latest):
                self.sync_lcu()
        self.async_call(wait, go)

    def _postgame_unavailable_later(self, delay: float) -> None:
        """Après les re-synchros : si la partie qui vient de finir n'est toujours
        pas dans le store (LCU lente à indexer), on affiche « détail non
        disponible » plutôt qu'une attente indéfinie. Le scan périodique continue
        et remplacera ce message par le vrai bilan dès que la partie arrive."""
        def wait():
            time.sleep(delay)

        def go(_):
            if (self.current is not None and self.current.name == "postgame"
                    and self._postgame_latest
                    and self.store.newest_id() == self._postgame_baseline):
                self._show_postgame({"status": "unavailable"})
        self.async_call(wait, go)

    def lcu_action(self, action: str) -> None:
        """Envoie une commande au client via l'agent (ex. accepter un ready-check)."""
        self.server.send({"type": "lcu_action", "action": action})

    def play(self) -> None:
        """Bouton unique : demande à l'agent de lancer le client s'il est fermé,
        créer le lobby ARAM Chaos s'il n'est pas déjà le bon, puis inviter l'ami
        configuré (`lobby_invite`) — chaque étape déjà faite étant sautée côté
        agent. Sans effet si l'agent est déconnecté."""
        if not self.agent_connected:
            return
        self.server.send({"type": "lcu_action", "action": "play",
                          "queueId": self.lobby_queue, "invite": self.lobby_invite})

    def _mark_friends(self, payload: dict) -> dict:
        """Colore les amis (rose) sur un bilan via le `riotId` de chaque joueur
        (appliqué à la lecture : un ami ajouté plus tard est pris en compte)."""
        for p in (payload or {}).get("players", []):
            rid = p.get("riotId") or ""
            if not p.get("isSelf") and "#" in rid:
                gn, tl = rid.split("#", 1)
                p["isFriend"] = normalize_riot_id(gn, tl) in self.friends
        return payload

    def open_history(self) -> None:
        """Ouvre la liste des parties (verrou manuel). Lit le store local et
        déclenche une synchro si le PC est connecté."""
        hist = self.screens.get("history")
        if hist is None:
            return
        self.manual_screen = "history"
        self.set_screen("history")
        hist.start_fresh()

    def _show_postgame(self, detail) -> None:
        pg = self.screens.get("postgame")
        if pg is not None:
            pg.update_data(self._mark_friends(detail or {}))

    def open_postgame_review(self, game_id) -> None:
        """Ouvre le bilan d'une partie choisie en mode « revue » (RETOUR →
        historique). Bilan depuis le store si en cache, sinon demandé à l'agent."""
        if "postgame" not in self.screens:
            return
        self._postgame_latest = False
        self.postgame_return = "history"
        self.manual_screen = "postgame"
        self.set_screen("postgame")
        self._load_detail(game_id)

    def _load_detail(self, game_id) -> None:
        """Affiche le bilan : depuis le store (consultable PC éteint) si connu,
        sinon le demande à l'agent/LCU, qui le renverra et on le met en cache."""
        detail = self.store.detail(game_id) if game_id else None
        if detail:
            self._show_postgame(detail)
        else:
            self._show_postgame({})      # « en attente du bilan… »
            if self.agent_connected and game_id:
                self.server.send({"type": "request_lcu_detail", "gameId": game_id})

    def _on_sync_done(self) -> None:
        """Fin d'une synchro : rafraîchit l'écran courant si besoin."""
        name = self.current.name if self.current else None
        if name == "history":
            self.screens["history"].reload()
        elif name == "postgame" and self._postgame_latest:
            # On n'affiche le bilan « dernière partie » que si une NOUVELLE
            # partie est arrivée (sinon on montrerait par erreur la précédente).
            newest = self.store.newest_id()
            if newest and newest != self._postgame_baseline:
                self._load_detail(newest)

    def joinable_screen(self) -> str | None:
        """Écran non-défaut proposé par l'agent, qu'on peut rejoindre depuis le
        défaut (après un retour manuel)."""
        n = self.network_screen
        if n != DEFAULT_SCREEN and n in self.screens:
            return n
        return None

    def join_screen(self) -> None:
        """Rejoint l'écran actuellement demandé par l'agent (clic badge)."""
        target = self.network_screen
        if target in self.screens and target != DEFAULT_SCREEN:
            self.manual_screen = None
            self.set_screen(target)

    # --------------------------------------------------------------- boucles
    def _dispatch_touch(self, pos) -> None:
        """Traite un appui (souris ou tactile) à la position interne `pos`."""
        action = self.current.handle_touch(pos)
        if action:
            self.last_key = f"tactile {pos} -> {action}"
            self.do_action(action)

    def _handle_pygame_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.last_key = "Échap -> retour"
                    self.do_action(ACTION_BACK)
                elif event.key == pygame.K_TAB:
                    self.last_key = "Tab -> écran suivant"
                    self.do_action(ACTION_NEXT)
                elif event.key == pygame.K_F1:
                    self.debug = not self.debug
                    self.last_key = f"F1 -> debug {'on' if self.debug else 'off'}"
                    if not self.debug:
                        self.current.draw_background(self.surface)
                        self.current.enter()
                        self.present([pygame.Rect(0, 0, self.width, self.height)])

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Souris (test PC). event.pos est en pixels fenêtre -> interne.
                x, y = event.pos
                self._dispatch_touch((x // self.scale, y // self.scale))

            elif event.type == pygame.FINGERDOWN:
                # Écran tactile (SDL2/kmsdrm) : event.x/y sont normalisés 0..1
                # de la fenêtre -> on les ramène aux coordonnées internes.
                self._dispatch_touch((int(event.x * self.width),
                                      int(event.y * self.height)))

    def _handle_actions(self) -> None:
        while True:
            try:
                action = self.action_queue.get_nowait()
            except queue.Empty:
                break
            self.do_action(action)

    def _handle_network(self) -> None:
        while True:
            try:
                msg = self.net_queue.get_nowait()
            except queue.Empty:
                break
            self._on_network(msg)

    def _on_network(self, msg: dict) -> None:
        msg_type = msg.get("type")

        if msg_type == "_connected":
            # Nouvelle session : on repasse en auto et on annonce nos modules.
            self.manual_screen = None
            self.agent_connected = True
            self._last_sync = 0.0        # force un scan au prochain _maybe_sync
            self.server.send({"type": "hello", "modules": self.enabled_modules})

        elif msg_type == "_disconnected":
            self.manual_screen = None
            self.agent_connected = False
            self.postgame_return = None
            self.network_screen = DEFAULT_SCREEN
            self.set_screen(DEFAULT_SCREEN)

        elif msg_type == "set_screen":
            screen = msg.get("screen", DEFAULT_SCREEN)
            self.network_screen = screen
            # Un écran poussé par l'agent (vraie partie) sort du mode « revue ».
            self.postgame_return = None
            if screen == DEFAULT_SCREEN:
                self.manual_screen = None
            if self.manual_screen is None:
                self.set_screen(screen)
                # Fin de partie : on tente une synchro immédiate (+ re-synchros
                # différées : la LCU met parfois quelques secondes à indexer).
                # Le scan périodique reste le filet. `_postgame_baseline` =
                # dernière partie connue AVANT celle-ci, pour savoir quand la
                # nouvelle est vraiment arrivée. À défaut : « non disponible ».
                if screen == "postgame":
                    self._postgame_latest = True
                    self._postgame_baseline = self.store.newest_id()
                    self._show_postgame({})      # « en attente du bilan… »
                    self.sync_lcu()
                    self._sync_postgame_later(8)
                    self._sync_postgame_later(20)
                    self._postgame_unavailable_later(24)

        elif msg_type == "data":
            # L'agent ne pousse que les écrans « locaux » (queue/champselect/lol).
            # L'enrichissement (dossiers/icônes/splash) est fait par le Pi ;
            # l'historique/bilan viennent du store (alimenté par la synchro LCU).
            screen = msg.get("screen")
            payload = msg.get("payload", {})
            if screen in self.screens:
                self.screens[screen].update_data(payload)

        elif msg_type == "store_matches":
            # Lot de parties (résumé + bilan) à stocker localement.
            games = msg.get("games", [])
            if games:
                self.store.upsert_matches(games)
                # Remplissage progressif : on rafraîchit la liste à chaque lot.
                if self.current is not None and self.current.name == "history":
                    self.screens["history"].reload()
            if msg.get("done"):
                self._on_sync_done()

        elif msg_type == "lcu_detail":
            # Bilan complet (10 joueurs) demandé au clic : on le met en cache
            # et on l'affiche si on est bien sur l'écran postgame.
            gid = msg.get("gameId")
            detail = msg.get("payload")
            if gid and detail:
                self.store.set_detail(gid, detail)
            if self.current is not None and self.current.name == "postgame":
                self._show_postgame(detail or {"status": "unavailable"})

    def _draw_debug(self, dirty):
        rect = pygame.Rect(0, 0, 360, 58)
        self.current.clear_region(self.surface, rect)
        lines = [
            f"écran={self.current.name}  fps={int(self.clock.get_fps())}  manuel={self.manual_screen}",
            f"dernière entrée: {self.last_key or '-'}",
        ]
        y = 6
        for line in lines:
            surf = self._debug_font.render(line, True, (255, 230, 0))
            self.surface.blit(surf, (8, y))
            y += 26
        return (dirty or []) + [rect]

    def run(self) -> None:
        self.running = True
        try:
            while self.running:
                self._handle_pygame_events()
                self._handle_actions()
                self._handle_network()
                self._maybe_sync()    # scan périodique de l'historique (LCU)
                self._drain_io()      # résultats des appels réseau asynchrones

                dirty = self.current.draw(self.surface)
                if self.debug:
                    dirty = self._draw_debug(dirty)
                self.present(dirty)

                self.clock.tick(self.fps)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.server.stop()
        pygame.quit()
        print("[app] Arrêt.")
