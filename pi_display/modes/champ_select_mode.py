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
from modes.base import Mode

RETOUR_RECT = pygame.Rect(690, 0, 110, 58)

# Colonne gauche (liste des joueurs) et panneau droit (détails).
LIST_X = 12
LIST_TOP = 92
ROW_H = 74
ROW_W = 414
ICON = 58
PANEL_X = 440
PANEL_W = 800 - PANEL_X - 12


def _format_points(points) -> str:
    if not points:
        return "0"
    if points >= 1000:
        return f"{points / 1000:.0f}k"
    return str(points)


class ChampSelectMode(Mode):
    name = "champselect"
    background_name = "champselect.png"
    bg_color = (10, 14, 26)

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 48)
        self.font_name = pygame.font.Font(None, 30)
        self.font_small = pygame.font.Font(None, 23)
        self.font_hint = pygame.font.Font(None, 24)
        self.font_panel = pygame.font.Font(None, 26)

        self.players: list[dict] = []
        self.selected_puuid: str | None = None
        self.player_info: dict[str, dict] = {}   # puuid -> détails
        # Icônes reçues (championId -> surface). Persistant entre sessions :
        # une icône ne change jamais, inutile de la redemander.
        self._icon_cache: dict[int, pygame.Surface] = {}
        self._requested: set[int] = set()         # icônes déjà demandées à l'agent
        self._rows: list[tuple[pygame.Rect, dict]] = []  # zones cliquables
        self._dirty = True  # force un premier rendu

    def enter(self) -> None:
        self._dirty = True
        # Nouvelle session : on pourra re-demander les icônes encore manquantes.
        self._requested.clear()

    def update_data(self, payload: dict) -> None:
        players = payload.get("players", [])
        # On ne redessine que si la composition a changé (champions/pseudos).
        if self._players_signature(players) != self._players_signature(self.players):
            self.players = players
            self._dirty = True

    def set_player_info(self, puuid: str, info: dict) -> None:
        self.player_info[puuid] = info
        if puuid == self.selected_puuid:
            self._dirty = True

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        for rect, player in self._rows:
            if rect.collidepoint(pos):
                puuid = player.get("puuid") or ""
                self.selected_puuid = puuid
                self._dirty = True
                # Demande des détails à l'agent (si pas déjà en cache).
                if puuid and puuid not in self.player_info:
                    self.app.request_player_info(
                        puuid, player.get("summonerId"),
                        player.get("championId", 0))
                return None
        return None

    # --------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        if not self._dirty:
            return []
        self._dirty = False

        # Fond complet puis contenu (simple : ce mode change rarement).
        surface.blit(self.bg, (0, 0))

        title = self.font_title.render("SÉLECTION DE CHAMPIONS", True, (210, 175, 95))
        surface.blit(title, title.get_rect(midtop=(self.width // 2, 20)))
        hint = self.font_hint.render("RETOUR", True, (200, 200, 210))
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        self._draw_player_list(surface)
        self._draw_detail_panel(surface)

        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_player_list(self, surface: pygame.Surface) -> None:
        self._rows = []
        for i, player in enumerate(self.players[:5]):
            row = pygame.Rect(LIST_X, LIST_TOP + i * ROW_H, ROW_W, ROW_H - 6)
            selected = (player.get("puuid") or "") == self.selected_puuid
            is_self = player.get("isSelf")

            # Fond de ligne : surligné si sélectionné ou si c'est nous.
            if selected:
                pygame.draw.rect(surface, (40, 60, 95), row, border_radius=6)
            elif is_self:
                pygame.draw.rect(surface, (28, 40, 64), row, border_radius=6)
            pygame.draw.rect(surface, (70, 85, 120), row, width=1, border_radius=6)

            # Icône du champion.
            icon = self._get_icon(player)
            icon_rect = pygame.Rect(row.x + 6, row.y + (row.h - ICON) // 2, ICON, ICON)
            surface.blit(icon, icon_rect)

            tx = icon_rect.right + 12
            name = player.get("championName") or "—"
            pseudo = player.get("gameName") or "(pseudo masqué)"
            if is_self:
                pseudo += "  (moi)"
            position = player.get("position") or ""

            name_surf = self.font_name.render(name, True, (240, 240, 245))
            surface.blit(name_surf, (tx, row.y + 8))
            info_surf = self.font_small.render(f"{pseudo}   {position}", True, (160, 180, 210))
            surface.blit(info_surf, (tx, row.y + 40))

            self._rows.append((row, player))

    def _draw_detail_panel(self, surface: pygame.Surface) -> None:
        panel = pygame.Rect(PANEL_X, LIST_TOP, PANEL_W, self.height - LIST_TOP - 12)
        pygame.draw.rect(surface, (18, 24, 40), panel, border_radius=8)
        pygame.draw.rect(surface, (70, 85, 120), panel, width=1, border_radius=8)

        x = panel.x + 14
        y = panel.y + 14

        if not self.selected_puuid:
            msg = self.font_panel.render("Clique sur un joueur", True, (150, 165, 195))
            surface.blit(msg, (x, y))
            return

        info = self.player_info.get(self.selected_puuid)
        if info is None:
            msg = self.font_panel.render("Chargement…", True, (150, 165, 195))
            surface.blit(msg, (x, y))
            return

        for line, color in self._info_lines(info):
            surf = self.font_panel.render(line, True, color)
            surface.blit(surf, (x, y))
            y += 30

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

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        """Reçoit une icône demandée à l'agent ; la met en cache et redessine."""
        surface = self._decode_icon(icon_b64)
        if surface is not None:
            self._icon_cache[champion_id] = surface
            self._dirty = True

    def _decode_icon(self, icon_b64) -> pygame.Surface | None:
        if not icon_b64:
            return None
        try:
            raw = base64.b64decode(icon_b64)
            image = pygame.image.load(io.BytesIO(raw)).convert_alpha()
            return pygame.transform.smoothscale(image, (ICON, ICON))
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
            (p.get("puuid"), p.get("championId"), p.get("gameName"),
             p.get("position"))
            for p in players
        )
