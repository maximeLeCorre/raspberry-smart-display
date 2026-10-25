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

import queue

import pygame

from inputs import ACTION_BACK, ACTION_NEXT, InputManager
from modules import MODULES
from network import NetworkServer

DEFAULT_SCREEN = "default"


class App:
    def __init__(self, config, *, fullscreen, scale, monitor, debug, host, port):
        self.config = config
        self.width = config["display"]["width"]
        self.height = config["display"]["height"]
        self.fps = config["display"]["fps"]
        self.scale = max(1, scale)
        self.fullscreen = fullscreen
        self.debug = debug

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
        self.server = NetworkServer(host, port, self.net_queue)
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

    def request_player_info(self, puuid, summoner_id, champion_id) -> None:
        self.server.send({
            "type": "request_player_info", "puuid": puuid,
            "summonerId": summoner_id, "championId": champion_id,
        })

    def request_icon(self, champion_id) -> None:
        self.server.send({"type": "request_icon", "championId": champion_id})

    def request_splash(self, champion_id) -> None:
        self.server.send({"type": "request_splash", "championId": champion_id})

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
                x, y = event.pos
                pos = (x // self.scale, y // self.scale)
                action = self.current.handle_touch(pos)
                if action:
                    self.last_key = f"tactile {pos} -> {action}"
                    self.do_action(action)

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
            self.server.send({"type": "hello", "modules": self.enabled_modules})

        elif msg_type == "_disconnected":
            self.manual_screen = None
            self.network_screen = DEFAULT_SCREEN
            self.set_screen(DEFAULT_SCREEN)

        elif msg_type == "set_screen":
            screen = msg.get("screen", DEFAULT_SCREEN)
            self.network_screen = screen
            if screen == DEFAULT_SCREEN:
                self.manual_screen = None
            if self.manual_screen is None:
                self.set_screen(screen)

        elif msg_type == "data":
            screen = msg.get("screen")
            payload = msg.get("payload", {})
            if screen in self.screens:
                self.screens[screen].update_data(payload)

        elif msg_type == "player_info":
            target = self.screens.get("champselect")
            if target is not None and hasattr(target, "set_player_info"):
                target.set_player_info(msg.get("puuid", ""), msg.get("info", {}))

        elif msg_type == "icon":
            for screen in self.screens.values():
                if hasattr(screen, "set_champion_icon"):
                    screen.set_champion_icon(msg.get("championId"), msg.get("iconB64"))

        elif msg_type == "splash":
            target = self.screens.get("champselect")
            if target is not None and hasattr(target, "set_champion_splash"):
                target.set_champion_splash(msg.get("championId"), msg.get("splashB64"))

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
