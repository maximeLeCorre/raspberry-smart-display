"""Application d'affichage : fenêtre/écran, boucle de rendu, routage des modes.

La boucle tourne à FPS bas (config). À chaque frame :
  1. on traite les événements Pygame (fermeture, clavier = boutons simulés,
     souris = tactile simulé) ;
  2. on traite les actions des boutons GPIO (queue) ;
  3. on traite les messages réseau (queue) : changement de mode, données,
     (dé)connexion de l'agent ;
  4. le mode courant redessine ses zones dynamiques (dirty rects) ;
  5. on présente à l'écran.

Rendu et mise à l'échelle :
  - Le rendu se fait toujours en 800x480 (résolution interne).
  - Sans mise à l'échelle (scale=1), on dessine directement sur la surface
    d'affichage et on utilise `pygame.display.update(dirty)` : optimal sur Pi.
  - Avec --scale N (test PC), on dessine sur une surface hors-écran puis on
    l'agrandit vers la fenêtre : pratique pour voir, moins optimisé.
"""

from __future__ import annotations

import queue

import pygame

from inputs import ACTION_BACK, ACTION_NEXT, InputManager
from modes.champ_select_mode import ChampSelectMode
from modes.default_mode import DefaultMode
from modes.lol_mode import LolMode
from modes.queue_mode import QueueMode
from network import NetworkServer


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

        # Modes disponibles. Les modes transitoires (queue...) sont pilotés par
        # l'agent uniquement : ils ne sont pas dans mode_order (cycle « suivant »).
        self.modes = {
            DefaultMode.name: DefaultMode(self),
            ChampSelectMode.name: ChampSelectMode(self),
            LolMode.name: LolMode(self),
            QueueMode.name: QueueMode(self),
        }
        self.mode_order = [DefaultMode.name, ChampSelectMode.name, LolMode.name]
        self.current = None

        # Verrou de contrôle manuel : quand l'utilisateur force un mode (bouton),
        # on ignore les « set_mode » venant du réseau jusqu'à ce que l'agent se
        # (re)connecte ou signale explicitement le mode par défaut.
        self.manual_mode: str | None = None
        # Dernier mode demandé par l'agent (même si on l'ignore à cause du verrou
        # manuel). Sert à proposer un badge « Rejoindre » sur l'écran par défaut.
        self.network_mode = DefaultMode.name

        self.running = False
        self.set_mode(DefaultMode.name)

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

        # Dessin direct (dirty rects) si pas de mise à l'échelle, sinon surface
        # hors-écran agrandie à la présentation.
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

    # ---------------------------------------------------------------- modes
    def set_mode(self, name: str) -> None:
        if name not in self.modes:
            print(f"[app] Mode inconnu ignoré : {name!r}")
            return
        if self.current is not None and self.current.name == name:
            return
        if self.current is not None:
            self.current.exit()
        self.current = self.modes[name]
        self.current.enter()
        # Fond complet + premier rendu dynamique, puis on présente tout l'écran.
        self.current.draw_background(self.surface)
        self.current.draw(self.surface)
        self.present([pygame.Rect(0, 0, self.width, self.height)])
        print(f"[app] Mode actif : {name}")

    def _next_mode(self) -> str:
        # Si le mode courant n'est pas dans le cycle (mode transitoire), on
        # repart du premier.
        if self.current.name not in self.mode_order:
            return self.mode_order[0]
        idx = self.mode_order.index(self.current.name)
        return self.mode_order[(idx + 1) % len(self.mode_order)]

    # --------------------------------------------------------------- actions
    def do_action(self, action: str) -> None:
        if action == ACTION_BACK:
            # Retour forcé au mode par défaut, même si le jeu tourne.
            self.manual_mode = DefaultMode.name
            self.set_mode(DefaultMode.name)
        elif action == ACTION_NEXT:
            target = self._next_mode()
            self.manual_mode = target
            self.set_mode(target)

    def request_player_info(self, puuid, summoner_id, champion_id) -> None:
        """Demande à l'agent les détails d'un joueur (clic en sélection)."""
        self.server.send({
            "type": "request_player_info",
            "puuid": puuid,
            "summonerId": summoner_id,
            "championId": champion_id,
        })

    def request_icon(self, champion_id) -> None:
        """Demande à l'agent l'icône d'un champion (envoyée une seule fois)."""
        self.server.send({"type": "request_icon", "championId": champion_id})

    def joinable_mode(self) -> str | None:
        """Mode LoL (sélection/partie) proposé par l'agent et qu'on peut
        rejoindre depuis l'écran par défaut (après un retour manuel)."""
        if self.network_mode in (LolMode.name, ChampSelectMode.name):
            return self.network_mode
        return None

    def join_network_mode(self) -> None:
        """Rejoint le mode actuellement demandé par l'agent (clic sur le badge),
        en relâchant le verrou manuel."""
        target = self.network_mode
        if target in self.modes and target != DefaultMode.name:
            self.manual_mode = None
            self.set_mode(target)

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
                    self.last_key = "Tab -> mode suivant"
                    self.do_action(ACTION_NEXT)
                elif event.key == pygame.K_F1:
                    self.debug = not self.debug
                    self.last_key = f"F1 -> debug {'on' if self.debug else 'off'}"
                    # Si on désactive le debug, on efface l'overlay en reblittant
                    # le fond du mode courant sur sa zone.
                    if not self.debug:
                        self.current.draw_background(self.surface)
                        self.current.enter()
                        self.present([pygame.Rect(0, 0, self.width, self.height)])

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # La souris simule le tactile. On ramène aux coords internes.
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
            # Nouvelle session agent : on repasse en contrôle automatique.
            self.manual_mode = None

        elif msg_type == "_disconnected":
            # Agent parti (jeu fermé, PC éteint) : retour au mode par défaut.
            self.manual_mode = None
            self.network_mode = DefaultMode.name
            self.set_mode(DefaultMode.name)

        elif msg_type == "set_mode":
            mode = msg.get("mode", DefaultMode.name)
            # On mémorise ce que l'agent veut afficher (pour le badge « Rejoindre »).
            self.network_mode = mode
            if mode == DefaultMode.name:
                # L'agent signale la fin de partie : on redonne la main à l'auto.
                self.manual_mode = None
            if self.manual_mode is None:
                self.set_mode(mode)

        elif msg_type == "data":
            mode = msg.get("mode")
            payload = msg.get("payload", {})
            if mode in self.modes:
                self.modes[mode].update_data(payload)

        elif msg_type == "player_info":
            # Réponse à une demande de détails joueur (mode sélection).
            champ_select = self.modes.get(ChampSelectMode.name)
            if champ_select is not None:
                champ_select.set_player_info(msg.get("puuid", ""), msg.get("info", {}))

        elif msg_type == "icon":
            # Réponse à une demande d'icône : on la transmet aux modes qui en
            # affichent (sélection et partie). Chacun garde son propre cache.
            for mode in self.modes.values():
                if hasattr(mode, "set_champion_icon"):
                    mode.set_champion_icon(msg.get("championId"), msg.get("iconB64"))

    def _draw_debug(self, dirty):
        rect = pygame.Rect(0, 0, 340, 58)
        # Efface via le fond du mode courant, puis écrit les infos de debug.
        self.current.clear_region(self.surface, rect)
        lines = [
            f"mode={self.current.name}  fps={int(self.clock.get_fps())}  manual={self.manual_mode}",
            f"derniere entree: {self.last_key or '-'}",
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
