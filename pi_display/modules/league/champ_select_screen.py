"""Mode sélection de champions : affiche notre équipe (5 joueurs).

Pour chaque joueur : icône du champion, pseudo, position, et nous surligné.
Un clic sur un joueur demande ses détails à l'agent (rang, niveau, maîtrise,
winrate, champions mains) et les affiche dans un panneau à droite.

Données reçues (payload) :
    {"phase": "champselect",
     "players": [{"cellId", "summonerId", "puuid", "championId",
                  "championName", "position", "gameName", "tagLine",
                  "isSelf", "iconB64"}]}

Détails reçus (au clic, message player_info) : voir set_player_info().
"""

from __future__ import annotations

import base64
import io

import pygame

from inputs import ACTION_BACK
from modules.league.names import display_name
from screen import Screen

RETOUR_RECT = pygame.Rect(690, 0, 110, 58)

# Zones alignées sur les cadres du fond (champselect.png).
# Colonne gauche = liste des joueurs (5 lignes) ; panneau droit = détails.
LIST_X = 27
LIST_TOP = 84
ROW_H = 75
ROW_W = 428
ICON = 56
PANEL_X = 468
PANEL_TOP = 72
PANEL_W = 783 - PANEL_X


def _format_points(points) -> str:
    if not points:
        return "0"
    if points >= 1000:
        return f"{points / 1000:.0f}k"
    return str(points)


class ChampSelectScreen(Screen):
    name = "champselect"
    background_name = "champselect.png"
    bg_color = (10, 14, 26)
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 48)
        self.font_name = pygame.font.Font(None, 30)
        self.font_small = pygame.font.Font(None, 23)
        self.font_hint = pygame.font.Font(None, 24)
        self.font_panel = pygame.font.Font(None, 26)

        self.players: list[dict] = []
        self.timer: dict = {}
        self.bans: dict = {}
        self.selected_puuid: str | None = None
        self.player_info: dict[str, dict] = {}   # puuid -> détails
        # Icônes reçues (championId -> surface). Persistant entre sessions :
        # une icône ne change jamais, inutile de la redemander.
        self._icon_cache: dict[int, pygame.Surface] = {}
        self._requested: set[int] = set()         # icônes déjà demandées à l'agent
        self._splash_cache: dict[int, pygame.Surface] = {}  # splash arts reçus
        self._splash_requested: set[int] = set()
        self._rows: list[tuple[pygame.Rect, dict]] = []  # zones cliquables
        self._last_state = None

    def enter(self) -> None:
        self._last_state = None
        # Nouvelle session : on pourra re-demander les icônes encore manquantes.
        self._requested.clear()
        self._splash_requested.clear()

    def update_data(self, payload: dict) -> None:
        self.players = payload.get("players", self.players)
        self.timer = payload.get("timer", self.timer)
        self.bans = payload.get("bans", self.bans)

    def set_player_info(self, puuid: str, info: dict) -> None:
        self.player_info[puuid] = info
        if puuid == self.selected_puuid:
            self._last_state = None

    def set_champion_splash(self, champion_id: int, splash_b64: str | None) -> None:
        surface = self._decode_splash(splash_b64)
        if surface is not None:
            self._splash_cache[champion_id] = surface
            self._last_state = None

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        for rect, player in self._rows:
            if rect.collidepoint(pos):
                rid = player.get("riotId") or ""
                champ_id = player.get("championId", 0)
                self.selected_puuid = rid     # clé = Riot ID 'Nom#TAG'
                self._last_state = None
                # Détails joueur (si pas déjà en cache). Le Pi résout/enrichit.
                if rid and rid not in self.player_info:
                    self.app.request_player_info(rid, champ_id)
                # Splash art du champion (si pas déjà reçu).
                if champ_id and champ_id not in self._splash_cache \
                        and champ_id not in self._splash_requested:
                    self._splash_requested.add(champ_id)
                    self.app.request_splash(champ_id)
                return None
        return None

    # --------------------------------------------------------------- rendu
    def _signature(self):
        sel = self.selected_puuid
        return (
            self._players_signature(self.players),
            self.timer.get("left"), self.timer.get("phase"),
            tuple(self.bans.get("myTeam", [])), tuple(self.bans.get("theirTeam", [])),
            sel, bool(self.player_info.get(sel)) if sel else None,
            tuple(sorted(self._icon_cache.keys())),
            tuple(sorted(self._splash_cache.keys())),
        )

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = self._signature()
        if signature == self._last_state:
            return []
        self._last_state = signature

        surface.blit(self.bg, (0, 0))

        # Titre dans le bandeau haut (y 12-60) ; timer de phase à gauche.
        title = self.font_title.render("SÉLECTION DE CHAMPIONS", True, (210, 175, 95))
        surface.blit(title, title.get_rect(center=(self.width // 2, 32)))
        phase, left = self.timer.get("phase"), self.timer.get("left")
        if phase and left is not None:
            t = self.font_small.render(f"{phase} — {left}s", True, (160, 180, 210))
            surface.blit(t, (18, 24))
        hint = self.font_hint.render("RETOUR", True, (200, 200, 210))
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        self._draw_player_list(surface)
        self._draw_detail_panel(surface)

        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_player_list(self, surface: pygame.Surface) -> None:
        self._rows = []
        for i, player in enumerate(self.players[:5]):
            row = pygame.Rect(LIST_X, LIST_TOP + i * ROW_H, ROW_W, ROW_H - 6)
            selected = (player.get("riotId") or "") == self.selected_puuid
            is_self = player.get("isSelf")

            # Le cadre de ligne est fourni par le fond : on ne dessine qu'un
            # léger surlignage si la ligne est sélectionnée ou que c'est nous.
            if selected:
                pygame.draw.rect(surface, (40, 60, 95), row, border_radius=6)
                pygame.draw.rect(surface, (120, 150, 210), row, width=2, border_radius=6)
            elif is_self:
                pygame.draw.rect(surface, (28, 40, 64), row, border_radius=6)

            # Icône du champion.
            icon = self._get_icon(player)
            icon_rect = pygame.Rect(row.x + 6, row.y + (row.h - ICON) // 2, ICON, ICON)
            surface.blit(icon, icon_rect)

            tx = icon_rect.right + 12
            name = player.get("championName") or "—"
            pseudo, pseudo_color = display_name(player.get("gameName"))
            if not pseudo:
                pseudo = "(pseudo masqué)"
            if is_self:
                pseudo += "  (moi)"
            position = player.get("position") or ""

            name_surf = self.font_name.render(name, True, (240, 240, 245))
            surface.blit(name_surf, (tx, row.y + 8))
            # Pseudo (couleur spéciale éventuelle) puis position en couleur normale.
            pseudo_surf = self.font_small.render(pseudo, True, pseudo_color or (160, 180, 210))
            surface.blit(pseudo_surf, (tx, row.y + 40))
            if position:
                pos_surf = self.font_small.render(f"   {position}", True, (160, 180, 210))
                surface.blit(pos_surf, (tx + pseudo_surf.get_width(), row.y + 40))

            self._rows.append((row, player))

    def _draw_detail_panel(self, surface: pygame.Surface) -> None:
        # Le cadre du panneau est dans le fond : on n'écrit que le contenu.
        panel = pygame.Rect(PANEL_X, PANEL_TOP, PANEL_W, self.height - PANEL_TOP - 13)

        x = panel.x + 14

        if not self.selected_puuid:
            self._draw_bans(surface, panel)
            return

        # Splash art en bannière (haut du portrait), si reçu.
        content_top = panel.y + 14
        champ_id = self._selected_champion_id()
        splash = self._splash_cache.get(champ_id)
        if splash is not None:
            banner_h = 150
            prev = surface.get_clip()
            surface.set_clip(pygame.Rect(panel.x + 1, panel.y + 1, panel.w - 2, banner_h))
            surface.blit(splash, (panel.x, panel.y - 8))
            surface.set_clip(prev)
            shade = pygame.Surface((panel.w, 44), pygame.SRCALPHA)
            shade.fill((18, 24, 40, 190))
            surface.blit(shade, (panel.x, panel.y + banner_h - 44))
            content_top = panel.y + banner_h + 6

        info = self.player_info.get(self.selected_puuid)
        y = content_top
        if info is None:
            surface.blit(self.font_panel.render("Chargement…", True, (150, 165, 195)), (x, y))
            return
        for line, color in self._info_lines(info):
            surface.blit(self.font_panel.render(line, True, color), (x, y))
            y += 29

    def _draw_bans(self, surface: pygame.Surface, panel: pygame.Rect) -> None:
        x = panel.x + 14
        y = panel.y + 14
        surface.blit(self.font_panel.render("Bans", True, (210, 175, 95)), (x, y))
        y += 42
        for label, ids in (("Alliés", self.bans.get("myTeam", [])),
                           ("Ennemis", self.bans.get("theirTeam", []))):
            surface.blit(self.font_small.render(label, True, (160, 180, 210)), (x, y + 4))
            bx = x + 96
            for cid in ids[:5]:
                surface.blit(self._small_icon(cid, 30), (bx, y))
                bx += 36
            if not ids:
                surface.blit(self.font_small.render("—", True, (120, 140, 170)), (x + 96, y + 4))
            y += 50
        surface.blit(self.font_small.render("Clique un joueur pour ses infos", True,
                                            (130, 150, 185)), (x, panel.bottom - 34))

    def _selected_champion_id(self) -> int:
        for p in self.players:
            if (p.get("riotId") or "") == self.selected_puuid:
                return p.get("championId", 0) or 0
        return 0

    def _info_lines(self, info: dict) -> list[tuple[str, tuple[int, int, int]]]:
        white = (235, 235, 240)
        grey = (160, 180, 210)
        lines: list[tuple[str, tuple[int, int, int]]] = []

        champ = info.get("championName")
        if champ:
            lines.append((champ, (210, 175, 95)))

        if info.get("error"):
            lines.append((str(info["error"]), grey))
            return lines

        if info.get("summonerLevel") is not None:
            lines.append((f"Niveau {info['summonerLevel']}", white))

        for label, r in (info.get("ranks") or {}).items():
            tier = (r.get("tier") or "").title()
            rank = r.get("rank") or ""
            lp = r.get("lp")
            wins, losses = r.get("wins"), r.get("losses")
            txt = f"{label}: {tier} {rank} {lp} LP"
            if wins is not None and losses is not None:
                txt += f" ({wins}V/{losses}D)"
            lines.append((txt, white))

        mastery = info.get("championMastery")
        if mastery:
            lines.append((f"Maîtrise: Nv{mastery.get('level')} "
                          f"({_format_points(mastery.get('points'))})", white))

        recent = info.get("recent")
        if recent:
            lines.append((f"Récent: {recent.get('wins')}V/{recent.get('losses')}D "
                          f"({recent.get('winrate')}%)", white))

        mains = info.get("mains")
        if mains:
            txt = "Mains: " + ", ".join(
                f"{m.get('championName')} ({_format_points(m.get('points'))})"
                for m in mains[:3])
            lines.append((txt, grey))

        return lines

    # ----------------------------------------------------------- icônes
    def _get_icon(self, player: dict) -> pygame.Surface:
        champ_id = player.get("championId") or 0
        if champ_id in self._icon_cache:
            return self._icon_cache[champ_id]

        # Icône pas encore reçue : on la demande à l'agent (une seule fois) et
        # on affiche un placeholder en attendant qu'elle arrive.
        if champ_id > 0 and champ_id not in self._requested:
            self._requested.add(champ_id)
            self.app.request_icon(champ_id)
        return self._placeholder_icon(player.get("championName") or "?")

    def _small_icon(self, champ_id, size: int) -> pygame.Surface:
        """Petite icône (pour les bans) depuis le cache, redimensionnée."""
        champ_id = champ_id or 0
        if champ_id in self._icon_cache:
            return pygame.transform.smoothscale(self._icon_cache[champ_id], (size, size))
        if champ_id > 0 and champ_id not in self._requested:
            self._requested.add(champ_id)
            self.app.request_icon(champ_id)
        placeholder = pygame.Surface((size, size))
        placeholder.fill((45, 55, 80))
        return placeholder

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        """Reçoit une icône demandée à l'agent ; la met en cache et redessine."""
        surface = self._decode_icon(icon_b64)
        if surface is not None:
            self._icon_cache[champion_id] = surface
            self._last_state = None

    def _decode_icon(self, icon_b64) -> pygame.Surface | None:
        if not icon_b64:
            return None
        try:
            raw = base64.b64decode(icon_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert_alpha()
            return pygame.transform.smoothscale(image, (ICON, ICON))
        except Exception:
            return None

    def _decode_splash(self, splash_b64) -> pygame.Surface | None:
        if not splash_b64:
            return None
        try:
            raw = base64.b64decode(splash_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert()
            w, h = image.get_size()
            return pygame.transform.smoothscale(image, (PANEL_W, int(PANEL_W * h / w)))
        except Exception:
            return None

    def _placeholder_icon(self, champion_name: str) -> pygame.Surface:
        surface = pygame.Surface((ICON, ICON))
        surface.fill((45, 55, 80))
        pygame.draw.rect(surface, (90, 105, 140), surface.get_rect(), width=1)
        initials = (champion_name[:2] if champion_name else "?").upper()
        label = self.font_name.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface

    @staticmethod
    def _players_signature(players: list[dict]):
        return tuple(
            (p.get("riotId"), p.get("championId"), p.get("gameName"),
             p.get("position"))
            for p in players
        )
