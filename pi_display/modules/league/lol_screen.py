"""Écran League « partie en cours » — pensé comme complément à l'écran de jeu.

Le scoreboard brut (KDA/CS/or/killfeed) est déjà sous les yeux du joueur dans
le client ; cet écran privilégie donc ce qu'on n'a PAS facilement en jeu :

  - **Timers d'objectifs** (Dragon/Baron/Héraut) reconstruits depuis les
    événements — uniquement en Faille (`game_mode == "CLASSIC"`).
  - **Dossier adverse au clic** (rang, winrate récent, champions mains) via
    l'API Web — précieux surtout en ARAM, où on ne scoute pas en sélection.

Le mini-scoreboard reste comme contexte, pas comme sujet. L'affichage s'adapte
au mode : pas de bandeau d'objectifs en ARAM, plus de place pour les lignes.

Données reçues (payload), produites par l'agent (Live Client Data API) :
    {"game_time": 930, "game_mode": "CLASSIC",
     "scores": {"order": 12, "chaos": 9},
     "players": [{"name","puuid","champion","championId","position","team",
                  "k","d","a","cs","level","isDead","respawn","isSelf"}, ...],
     "events": ["maxoulefou a tué Greed", ...],   # plus récents d'abord
     "objectives": [{"key","label","at","by","detail"}, ...],  # Faille seule
     "self": {"gold": 8450}}

Dossier reçu au clic (message player_info) : même format qu'en sélection.
"""

from __future__ import annotations

import time

import pygame

from inputs import ACTION_BACK
from modules.league.names import display_name
from modules.league.icons import ChampionIcons
from screen import Screen

# Zones alignées sur les cadres du fond (lol.png) : bandeau haut (0-48),
# colonnes gauche/droite (y 52-354), panneau bas (y 369-466).
RETOUR_RECT = pygame.Rect(742, 4, 54, 30)
COUNTERS_RECT = pygame.Rect(640, 4, 92, 30)    # bascule vers les écarts
ICON = 34
ROWS_TOP = 54
ROWS_BOTTOM = 352
COL_LEFT_X = 13
COL_RIGHT_X = 406
COL_W = 381
PANEL = pygame.Rect(13, 369, 773, 97)   # bas : objectifs/événements OU dossier

BLUE = (90, 150, 230)
RED = (225, 110, 110)
WHITE = (238, 238, 243)
GREY = (150, 168, 198)
GOLD = (210, 175, 95)
GREEN = (120, 210, 140)

MODE_LABELS = {"CLASSIC": "Faille", "ARAM": "ARAM", "URF": "URF"}


def format_game_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _format_points(points) -> str:
    if not points:
        return "0"
    if points >= 1000:
        return f"{points / 1000:.0f}k"
    return str(points)


class LolScreen(Screen):
    name = "lol"
    background_name = "lol.png"
    bg_color = (8, 12, 24)
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        self.league = app.modules["league"]
        self.font_time = pygame.font.Font(None, 44)
        self.font_label = pygame.font.Font(None, 26)
        self.font_name = pygame.font.Font(None, 25)
        self.font_stat = pygame.font.Font(None, 23)
        self.font_hint = pygame.font.Font(None, 21)
        self.font_obj = pygame.font.Font(None, 30)

        self.data: dict = {}
        self._recv_at: float | None = None       # horloge locale à la réception
        self.icons = ChampionIcons(self.league, ICON)
        self.selected_puuid: str | None = None
        self.player_info: dict[str, dict] = {}    # puuid -> dossier
        self._requested_info: set[str] = set()
        self._rows: list[tuple[pygame.Rect, dict]] = []
        self._last_signature = None

    def enter(self) -> None:
        self._last_signature = None
        self.icons.forget_requests()
        self.selected_puuid = None

    def update_data(self, payload: dict) -> None:
        self.data = payload or {}
        self._recv_at = time.monotonic()
        self.league.note_live(self.data)

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        if self.icons.put(champion_id, icon_b64):
            self._last_signature = None

    def set_player_info(self, puuid: str, info: dict) -> None:
        self.player_info[puuid] = info
        if puuid == self.selected_puuid:
            self._last_signature = None

    # --------------------------------------------------------- horloge fluide
    def _elapsed(self) -> float:
        """Temps de jeu extrapolé : l'agent n'envoie que ~1 fois/s, on comble
        avec l'horloge locale pour un décompte qui ne saccade pas."""
        base = self.data.get("game_time", 0) or 0
        if self._recv_at is None:
            return base
        return base + (time.monotonic() - self._recv_at)

    # ------------------------------------------------------------------ clics
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        if COUNTERS_RECT.collidepoint(pos):
            self.league.open_counters()
            return None
        for rect, player in self._rows:
            if rect.collidepoint(pos):
                rid = player.get("riotId") or ""      # clé = Riot ID 'Nom#TAG'
                if rid and rid == self.selected_puuid:
                    self.selected_puuid = None      # re-clic = refermer le dossier
                else:
                    self.selected_puuid = rid or None
                    if rid and rid not in self.player_info \
                            and rid not in self._requested_info:
                        self._requested_info.add(rid)
                        self.league.request_player_info(rid, player.get("championId", 0))
                self._last_signature = None
                return None
        return None

    # ----------------------------------------------------------------- rendu
    def _is_rift(self) -> bool:
        return (self.data.get("game_mode") or "CLASSIC") == "CLASSIC"

    def _objectives(self) -> list[dict]:
        return self.data.get("objectives", []) if self._is_rift() else []

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        signature = self._signature()
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.blit(self.bg, (0, 0))
        self._draw_header(surface)

        # Les colonnes (cadres fournis par le fond) accueillent les 5 joueurs.
        row_h = (ROWS_BOTTOM - ROWS_TOP) // 5
        self._rows = []
        players = self.data.get("players", [])
        order = [p for p in players if p.get("team") == "ORDER"][:5]
        chaos = [p for p in players if p.get("team") == "CHAOS"][:5]
        for i, p in enumerate(order):
            self._draw_row(surface, p, COL_LEFT_X, ROWS_TOP + i * row_h, row_h)
        for i, p in enumerate(chaos):
            self._draw_row(surface, p, COL_RIGHT_X, ROWS_TOP + i * row_h, row_h)

        self._draw_panel(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_header(self, surface: pygame.Surface) -> None:
        scores = self.data.get("scores", {})
        time_str = format_game_time(self._elapsed())

        t = self.font_time.render(time_str, True, WHITE)
        surface.blit(t, t.get_rect(center=(self.width // 2, 22)))

        o = self.font_label.render(f"ORDER  {scores.get('order', 0)}", True, BLUE)
        surface.blit(o, o.get_rect(midright=(self.width // 2 - 64, 22)))
        c = self.font_label.render(f"{scores.get('chaos', 0)}  CHAOS", True, RED)
        surface.blit(c, c.get_rect(midleft=(self.width // 2 + 64, 22)))

        mode = MODE_LABELS.get(self.data.get("game_mode", ""), self.data.get("game_mode", ""))
        if mode:
            m = self.font_hint.render(mode, True, GREY)
            surface.blit(m, (10, 8))

        hint = self.font_hint.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))
        pygame.draw.rect(surface, (30, 44, 70), COUNTERS_RECT, border_radius=6)
        pygame.draw.rect(surface, (70, 90, 130), COUNTERS_RECT, width=1, border_radius=6)
        btn = self.font_hint.render("ÉCARTS", True, WHITE)
        surface.blit(btn, btn.get_rect(center=COUNTERS_RECT.center))

    def _draw_objectives(self, surface, objectives, strip) -> None:
        """Rangée compacte de timers d'objectifs dans `strip` (Faille seule).
        Le fond ne réserve pas de bande dédiée : on les loge dans le panneau bas."""
        elapsed = self._elapsed()
        n = len(objectives)
        gap = 8
        pill_w = (strip.w - gap * (n - 1)) // n
        for i, obj in enumerate(objectives):
            pill = pygame.Rect(strip.x + i * (pill_w + gap), strip.y, pill_w, strip.h)
            pygame.draw.rect(surface, (22, 28, 46), pill, border_radius=6)
            pygame.draw.rect(surface, (60, 74, 110), pill, width=1, border_radius=6)

            label = obj.get("label", "")
            detail = obj.get("detail")
            text = label + (f" · {detail}" if detail else "")
            lbl = self.font_hint.render(text[:20], True, GREY)
            surface.blit(lbl, (pill.x + 8, pill.y + 4))

            at = obj.get("at")
            if at is None:
                value, color = ("pris" if obj.get("by") else "—"), GREY
            else:
                rem = at - elapsed
                if rem <= 0:
                    value, color = "PRÊT", GREEN
                else:
                    value = format_game_time(rem)
                    color = GOLD if rem <= 30 else WHITE
            val = self.font_name.render(value, True, color)
            surface.blit(val, val.get_rect(bottomright=(pill.right - 8, pill.bottom - 4)))

    def _draw_row(self, surface, player, x, y, row_h) -> None:
        row = pygame.Rect(x, y + 2, COL_W, row_h - 4)
        self._rows.append((row, player))

        selected = (player.get("riotId") or "") and \
            (player.get("riotId") == self.selected_puuid)
        if selected:
            pygame.draw.rect(surface, (40, 60, 95), row, border_radius=6)
            pygame.draw.rect(surface, BLUE, row, width=1, border_radius=6)
        elif player.get("isSelf"):
            pygame.draw.rect(surface, (30, 44, 70), row, border_radius=6)
            pygame.draw.rect(surface, GOLD, row, width=1, border_radius=6)

        icon = self._get_icon(player)
        icon_rect = pygame.Rect(row.x + 5, row.y + (row.h - ICON) // 2, ICON, ICON)
        surface.blit(icon, icon_rect)
        if player.get("isDead"):
            shade = pygame.Surface((ICON, ICON), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 150))
            surface.blit(shade, icon_rect)

        tx = icon_rect.right + 10
        text, color = display_name(player.get("name"))
        surface.blit(self.font_name.render(text[:11], True, color or WHITE), (tx, row.y + 5))
        lvl = self.font_stat.render(f"Niv {player.get('level', 0)}", True, GREY)
        surface.blit(lvl, lvl.get_rect(topright=(row.right - 8, row.y + 6)))

        if player.get("isDead"):
            line2 = self.font_stat.render(f"Mort {player.get('respawn', 0)}s", True, RED)
        else:
            k, d, a = player.get("k", 0), player.get("d", 0), player.get("a", 0)
            line2 = self.font_stat.render(
                f"{k}/{d}/{a}    {player.get('cs', 0)} CS", True, GREY)
        surface.blit(line2, (tx, row.y + row.h - 24))

    def _draw_panel(self, surface: pygame.Surface) -> None:
        # Cadre fourni par le fond : on n'écrit que le contenu.
        if self.selected_puuid:
            self._draw_dossier(surface)
        else:
            self._draw_events(surface)

    def _draw_events(self, surface: pygame.Surface) -> None:
        # En Faille : rangée de timers d'objectifs en haut du panneau, puis
        # le dernier événement + l'or. En ARAM : événements seuls (plus de place).
        objectives = self._objectives()
        top = PANEL.y + 6
        if objectives:
            self._draw_objectives(surface, objectives,
                                  pygame.Rect(PANEL.x + 8, top, PANEL.w - 16, 28))
            top += 34

        events = self.data.get("events", [])
        gold = self.data.get("self", {}).get("gold")
        if gold is not None:
            g = self.font_hint.render(f"Or : {gold}", True, GREY)
            surface.blit(g, g.get_rect(topright=(PANEL.right - 12, top)))
        n_events = 1 if objectives else 2
        y = top
        for ev in events[:n_events]:
            surface.blit(self.font_stat.render(ev[:60], True, WHITE), (PANEL.x + 12, y))
            y += 23
        if not events:
            surface.blit(self.font_stat.render("—", True, GREY), (PANEL.x + 12, y))
        hint = self.font_hint.render("Touchez un joueur pour son profil", True, GREY)
        surface.blit(hint, hint.get_rect(bottomright=(PANEL.right - 12, PANEL.bottom - 5)))

    def _draw_dossier(self, surface: pygame.Surface) -> None:
        info = self.player_info.get(self.selected_puuid)
        x = PANEL.x + 14
        if info is None:
            surface.blit(self.font_stat.render("Chargement du profil…", True, GREY),
                         (x, PANEL.y + 8))
            return
        y = PANEL.y + 5
        for text, color in self._dossier_lines(info)[:5]:
            surface.blit(self.font_hint.render(text[:84], True, color), (x, y))
            y += 19

    def _dossier_lines(self, info: dict) -> list[tuple[str, tuple]]:
        lines: list[tuple[str, tuple]] = []
        head = info.get("championName") or ""
        if info.get("summonerLevel") is not None:
            head = f"{head}   Niveau {info['summonerLevel']}".strip()
        if head:
            lines.append((head, GOLD))

        if info.get("error"):
            lines.append((str(info["error"]), GREY))
            return lines

        for label, r in (info.get("ranks") or {}).items():
            tier = (r.get("tier") or "").title()
            txt = f"{label}: {tier} {r.get('rank') or ''} {r.get('lp')} LP"
            if r.get("wins") is not None and r.get("losses") is not None:
                txt += f" ({r['wins']}V/{r['losses']}D)"
            lines.append((txt, WHITE))

        recent = info.get("recent")
        if recent:
            lines.append((f"Récent: {recent.get('wins')}V/{recent.get('losses')}D "
                          f"({recent.get('winrate')}%)", WHITE))

        mains = info.get("mains")
        if mains:
            txt = "Mains: " + ", ".join(
                f"{m.get('championName')} ({_format_points(m.get('points'))})"
                for m in mains[:3])
            lines.append((txt, GREY))

        if len(lines) <= 1:
            lines.append(("Pas de données classées.", GREY))
        return lines

    # ----------------------------------------------------------- icônes
    def _get_icon(self, player: dict) -> pygame.Surface:
        return (self.icons.get(player.get("championId"))
                or self._placeholder_icon(player.get("champion") or "?"))

    def _placeholder_icon(self, champion_name: str) -> pygame.Surface:
        surface = pygame.Surface((ICON, ICON))
        surface.fill((45, 55, 80))
        initials = (champion_name[:2] if champion_name else "?").upper()
        label = self.font_stat.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface

    def _signature(self):
        players = self.data.get("players", [])
        sel = self.selected_puuid
        return (
            int(self._elapsed()),                 # horloge/timers : tic chaque seconde
            self.data.get("game_mode"),
            tuple((self.data.get("scores") or {}).items()),
            tuple((p.get("championId"), p.get("k"), p.get("d"), p.get("a"),
                   p.get("cs"), p.get("level"), p.get("isDead"), p.get("respawn"))
                  for p in players),
            (self.data.get("events") or [None])[0],
            self.data.get("self", {}).get("gold"),
            tuple((o.get("key"), o.get("at"), o.get("detail"))
                  for o in self._objectives()),
            sel, bool(self.player_info.get(sel)) if sel else None,
            self.icons.signature(),
        )
