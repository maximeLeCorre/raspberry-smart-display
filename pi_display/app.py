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
from riot_web import (Champions, RiotWeb, build_match_detail, build_match_history,
                      build_player_info, icon_bytes, normalize_riot_id, splash_bytes)

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
        self.friends = {
            normalize_riot_id(*rid.split("#", 1))
            for rid in lol_cfg.get("friends", [])
            if isinstance(rid, str) and "#" in rid
        }
        self._my_puuid_cache = ""
        # Exécution asynchrone des appels réseau (HTTP) hors de la boucle de
        # rendu : un worker produit un résultat, livré au thread principal.
        self._io_results: "queue.Queue[tuple]" = queue.Queue()

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

    def request_match_history(self, count: int = 10) -> None:
        """Historique des dernières parties (API Web), en tâche de fond."""
        def deliver(games):
            hist = self.screens.get("history")
            if hist is not None:
                hist.update_data({"games": games or []})
        self.async_call(
            lambda: build_match_history(self.riot, self._my_puuid(), count), deliver)

    def open_history(self) -> None:
        """Ouvre la liste des dernières parties (verrou manuel) et la charge."""
        if "history" not in self.screens:
            return
        self.manual_screen = "history"
        self.set_screen("history")
        self.request_match_history()

    def _load_postgame(self, game_id, retries: int = 0) -> None:
        """Charge le bilan d'une partie (donnée ou la dernière si None) et le
        pousse à l'écran `postgame`. `retries` : réessais (délai d'indexation
        de l'API après une partie qui vient de finir)."""
        my = self._my_puuid
        riot, champs, friends = self.riot, self.champions, self.friends

        def fetch():
            payload = None
            for _ in range(retries + 1):
                payload = build_match_detail(riot, my(), game_id, friends)
                if payload and payload.get("players"):
                    return payload
                if retries:
                    time.sleep(3)
            return payload

        def deliver(payload):
            pg = self.screens.get("postgame")
            if pg is not None:
                pg.update_data(payload or {})
        self.async_call(fetch, deliver)

    def open_postgame_review(self, game_id) -> None:
        """Ouvre le bilan d'une partie choisie dans l'historique, en mode
        « revue » : RETOUR y ramène à l'historique, et l'écran reste verrouillé
        tant que l'agent ne pousse pas une vraie partie."""
        if "postgame" not in self.screens:
            return
        self.screens["postgame"].update_data({})      # vide -> « en attente »
        self.postgame_return = "history"
        self.manual_screen = "postgame"
        self.set_screen("postgame")
        self._load_postgame(game_id)

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
                # Bilan de fin de partie : le Pi récupère LUI-MÊME la dernière
                # partie via l'API Web (réessais le temps de l'indexation).
                if screen == "postgame":
                    self._load_postgame(None, retries=4)

        elif msg_type == "data":
            # L'agent ne pousse que les écrans « locaux » (queue/champselect/lol).
            # L'enrichissement (dossiers/icônes/splash/historique/bilan) est fait
            # par le Pi lui-même (voir request_* / _load_postgame).
            screen = msg.get("screen")
            payload = msg.get("payload", {})
            if screen in self.screens:
                self.screens[screen].update_data(payload)

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
