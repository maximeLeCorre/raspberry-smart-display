"""Mode sélection de champions : affiche notre équipe (5 joueurs).

Pour chaque joueur : icône du champion, pseudo, position, et nous surligné.
Un clic sur un joueur demande ses détails à l'agent (rang, niveau, maîtrise,
winrate, champions mains) et les affiche dans un panneau à droite (re-clic =
retour au panneau par défaut).

Panneau par défaut : **ton winrate** avec chaque champion que tu peux prendre
(le tien, le choix de départ ARAM Chaos, le banc ; sans banc ni choix, en
draft : tes champions les plus joués dans cette file), dans le mode de la partie,
lu dans le store (`LeagueModule.champion_records`). Boutons de période
`[lol] winrate_periods` (7/30/90 j, 7 par défaut) ; re-appui sur l'actif =
depuis toujours (réglage gardé dans watch.db).
Écrit, jamais la couleur seule : « 64 % » + « 7V 4D » / « 11 p. », « jamais joué ».

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
from modules.league.icons import ChampionIcons
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
WR_ICON = 44
WR_CELL_H = 82
WR_PER_ROW = 5

GOLD = (210, 175, 95)
WHITE = (235, 235, 240)
GREY = (160, 180, 210)
FAINT = (120, 140, 170)
GOOD = (110, 210, 130)
BAD = (235, 120, 120)

QUEUE_NAMES = {400: "Normale (draft)", 420: "Classée solo/duo", 440: "Classée flexible",
               430: "Normale (aveugle)", 490: "Partie rapide"}
MODE_NAMES = {"KIWI": "ARAM Chaos", "ARAM": "ARAM", "CLASSIC": "Faille", "CHERRY": "Arène"}


def period_label(days: int) -> str:
    return "depuis toujours" if not days else f"{days} derniers jours"


def record_text(rec) -> tuple[str, str]:
    """(« 64 % », « 7V 4D ») ; (« — », « jamais joué ») sans partie."""
    wins, games = rec or (0, 0)
    if not games:
        return "—", "jamais joué"
    return f"{round(100 * wins / games)} %", f"{wins}V {games - wins}D"


def rate_color(rec):
    wins, games = rec or (0, 0)
    if not games:
        return FAINT
    rate = 100 * wins / games
    return GOOD if rate >= 55 else BAD if rate < 45 else GOLD


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
        self.league = app.modules["league"]
        self.font_title = pygame.font.Font(None, 48)
        self.font_name = pygame.font.Font(None, 30)
        self.font_small = pygame.font.Font(None, 23)
        self.font_hint = pygame.font.Font(None, 24)
        self.font_panel = pygame.font.Font(None, 26)
        self.font_tiny = pygame.font.Font(None, 19)

        self.players: list[dict] = []
        self.timer: dict = {}
        self.bans: dict = {}
        self.selected_puuid: str | None = None
        self.player_info: dict[str, dict] = {}   # puuid -> détails
        # Icônes et splash arts par championId. Persistants entre sessions :
        # une image ne change jamais, inutile de la redemander.
        self.icons = ChampionIcons(self.league, ICON)
        self._splash_cache: dict[int, pygame.Surface] = {}
        self._splash_requested: set[int] = set()
        self._rows: list[tuple[pygame.Rect, dict]] = []  # zones cliquables
        self._last_state = None
        self.queue_id = 0
        self.game_mode = ""
        self.bench: list[dict] = []
        self.choices: list[dict] = []
        self._period_rects: list[tuple[pygame.Rect, int]] = []
        self._records: dict[int, tuple[int, int]] = {}
        self._top: list[dict] = []           # tes plus joués (draft : pas de banc)
        self._records_key = None

    def enter(self) -> None:
        self._last_state = None
        # Nouvelle session : on pourra re-demander les icônes encore manquantes.
        self.icons.forget_requests()
        self._splash_requested.clear()

    def update_data(self, payload: dict) -> None:
        self.players = payload.get("players", self.players)
        self.timer = payload.get("timer", self.timer)
        self.bans = payload.get("bans", self.bans)
        self.bench = payload.get("bench", self.bench)
        self.choices = payload.get("choices", self.choices)
        self.queue_id = payload.get("queueId", self.queue_id) or 0
        self.game_mode = payload.get("gameMode", self.game_mode) or ""

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
        for rect, days in self._period_rects:
            if rect.collidepoint(pos):
                self.league.toggle_winrate_period(days)
                self._last_state = None
                return None
        for rect, player in self._rows:
            if rect.collidepoint(pos):
                rid = player.get("riotId") or ""
                champ_id = player.get("championId", 0)
                if rid and rid == self.selected_puuid:     # re-clic : retour au winrate
                    self.selected_puuid = None
                    self._last_state = None
                    return None
                self.selected_puuid = rid     # clé = Riot ID 'Nom#TAG'
                self._last_state = None
                # Détails joueur (si pas déjà en cache). Le Pi résout/enrichit.
                if rid and rid not in self.player_info:
                    self.league.request_player_info(rid, champ_id)
                # Splash art du champion (si pas déjà reçu).
                if champ_id and champ_id not in self._splash_cache \
                        and champ_id not in self._splash_requested:
                    self._splash_requested.add(champ_id)
                    self.league.request_splash(champ_id)
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
            self.icons.signature(),
            tuple(sorted(self._splash_cache.keys())),
            tuple(c.get("championId") for c in self.bench),
            tuple(c.get("championId") for c in self.choices),
            self._refresh_records(),
        )

    def _refresh_records(self):
        """Relit tes winrates si le mode, la période ou le store ont changé."""
        key = (self.game_mode, self.queue_id, self.league.settings.winrate_days,
               self.league.store.total())
        if key != self._records_key:
            self._records_key = key
            try:
                stats = self.league.champion_stats(self.game_mode, self.queue_id)
            except Exception as exc:
                print(f"[champselect] winrate illisible : {exc}")
                stats = []
            self._records = {cid: (w, n) for cid, _name, w, n in stats}
            self._top = [{"championId": cid, "championName": name} for cid, name, _w, _n in stats]
        return key

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
        self._period_rects = []

        if not self.selected_puuid:
            self._draw_winrate(surface, panel)
            return

        # Splash art en bannière (haut du portrait), si reçu.
        content_top = panel.y + 14
        splash = self._splash_cache.get(self._selected_champion_id())
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

    def _draw_winrate(self, surface: pygame.Surface, panel: pygame.Rect) -> None:
        x, w = panel.x + 14, panel.w - 28
        y = panel.y + 12
        # Faille : filtrée par file -> on la nomme (classée ≠ normale).
        mode = ((QUEUE_NAMES.get(self.queue_id) if self.game_mode == "CLASSIC" else None)
                or MODE_NAMES.get(self.game_mode, self.game_mode or "toutes files"))
        surface.blit(self.font_panel.render(f"Ton winrate · {mode}", True, GOLD), (x, y))
        y += 28
        # Boutons de période : actif = plein (texte sombre), les autres = contour ;
        # la période en cours est aussi écrite dessous (pas que la couleur).
        current = self.league.settings.winrate_days
        periods = self.league.winrate_periods
        gap = 8
        bw = (w - gap * (len(periods) - 1)) // len(periods)
        for i, days in enumerate(periods):
            rect = pygame.Rect(x + i * (bw + gap), y, bw, 44)
            on = days == current
            pygame.draw.rect(surface, GOLD if on else (28, 40, 64), rect, border_radius=6)
            pygame.draw.rect(surface, GOLD if on else (90, 110, 150), rect,
                             width=2 if on else 1, border_radius=6)
            t = self.font_name.render(f"{days} j", True, (20, 24, 36) if on else WHITE)
            surface.blit(t, t.get_rect(center=rect.center))
            self._period_rects.append((rect, days))
        y += 48
        hint = (f"sur les {period_label(current)}" if current
                else "depuis toujours · touche une durée pour filtrer")
        surface.blit(self.font_tiny.render(hint, True, GREY), (x, y))
        y += 22

        if self.choices:
            surface.blit(self.font_small.render("Choix de départ", True, GREY), (x, y))
            y = self._draw_champ_cells(surface, x, y + 20, w, self.choices[:WR_PER_ROW], None)
        else:
            me = next((p for p in self.players if p.get("isSelf")), None) or {}
            cid = me.get("championId") or 0
            if cid:
                rec = self._records.get(cid)
                rate, detail = record_text(rec)
                self._blit_champ(surface, me, pygame.Rect(x, y, 40, 40))
                surface.blit(self.font_name.render(me.get("championName") or "", True, WHITE),
                             (x + 50, y + 1))
                surface.blit(self.font_small.render(f"{rate} · {detail}", True, rate_color(rec)),
                             (x + 50, y + 24))
                y += 50

        if self.bench:
            best = self._best(self.bench)
            surface.blit(self.font_small.render("Banc · % de victoires", True, GREY), (x, y))
            rows = 1 if self.choices else 2           # avec le choix de départ : 1 rangée
            y = self._draw_champ_cells(surface, x, y + 20, w, self.bench[:rows * WR_PER_ROW], best)
            if best is not None and y + 18 < panel.bottom:
                wins, games = self._records[best["championId"]]
                txt = (f"Meilleur : {best.get('championName') or '?'}, "
                       f"{round(100 * wins / games)} % sur {games} p.")
                surface.blit(self.font_small.render(txt, True, GOLD), (x, y))
                y += 24

        elif not self.choices:
            # Draft (ni banc ni choix) : tes plus joués dans cette file, pour choisir.
            bans = bool(self.bans.get("myTeam") or self.bans.get("theirTeam"))
            top = self._top[:(1 if bans else 2) * WR_PER_ROW]
            if top:
                surface.blit(self.font_small.render("Tes plus joués · % de victoires", True, GREY),
                             (x, y))
                y = self._draw_champ_cells(surface, x, y + 20, w, top, self._best(top))
            else:
                surface.blit(self.font_small.render("Aucune partie dans cette file sur la période",
                                                    True, FAINT), (x, y))
                y += 24

        if (self.bans.get("myTeam") or self.bans.get("theirTeam")) and y + 98 < panel.bottom:
            self._draw_bans(surface, panel, y)
        elif y + 30 < panel.bottom:
            surface.blit(self.font_small.render("Clique un joueur pour ses infos", True,
                                                (130, 150, 185)), (x, panel.bottom - 30))

    def _blit_champ(self, surface, champ: dict, rect: pygame.Rect) -> None:
        """Icône du champion ; en attendant l'image, ses initiales écrites."""
        cid = champ.get("championId") or 0
        if self.icons.get(cid) is not None:
            surface.blit(self._small_icon(cid, rect.w), rect)
            return
        pygame.draw.rect(surface, (45, 55, 80), rect)
        ini = self.font_small.render((champ.get("championName") or "?")[:2].upper(),
                                     True, (210, 220, 235))
        surface.blit(ini, ini.get_rect(center=rect.center))

    def _best(self, champs: list[dict]) -> dict | None:
        """Champion au meilleur winrate (au moins 3 parties, sinon on ne conclut pas)."""
        scored = []
        for c in champs:
            wins, games = self._records.get(c.get("championId") or 0, (0, 0))
            if games >= 3:
                scored.append((wins / games, games, c))
        return max(scored, key=lambda s: (s[0], s[1]))[2] if scored else None

    def _draw_champ_cells(self, surface, x, y, w, champs, best) -> int:
        """Grille d'icônes + winrate écrit ; renvoie le y sous la grille."""
        cell_w = w // WR_PER_ROW
        for i, champ in enumerate(champs):
            cid = champ.get("championId") or 0
            cx = x + (i % WR_PER_ROW) * cell_w + cell_w // 2
            cy = y + (i // WR_PER_ROW) * WR_CELL_H
            icon_rect = pygame.Rect(cx - WR_ICON // 2, cy, WR_ICON, WR_ICON)
            self._blit_champ(surface, champ, icon_rect)
            if best is not None and champ is best:
                pygame.draw.rect(surface, GOLD, icon_rect.inflate(6, 6), width=3)
            rec = self._records.get(cid)
            rate, _ = record_text(rec)
            games = (rec or (0, 0))[1]
            r = self.font_small.render(rate, True, rate_color(rec))
            surface.blit(r, r.get_rect(midtop=(cx, cy + WR_ICON + 3)))
            g = self.font_tiny.render(f"{games} p." if games else "jamais", True, FAINT)
            surface.blit(g, g.get_rect(midtop=(cx, cy + WR_ICON + 20)))
        rows = (len(champs) + WR_PER_ROW - 1) // WR_PER_ROW
        return y + rows * WR_CELL_H

    def _draw_bans(self, surface: pygame.Surface, panel: pygame.Rect, top: int) -> None:
        """Bans des deux équipes, sous le winrate (draft)."""
        x, y = panel.x + 14, top + 4
        surface.blit(self.font_small.render("Bans", True, GOLD), (x, y))
        y += 22
        for label, ids in (("Alliés", self.bans.get("myTeam", [])),
                           ("Ennemis", self.bans.get("theirTeam", []))):
            surface.blit(self.font_small.render(label, True, (160, 180, 210)), (x, y + 4))
            bx = x + 96
            for cid in ids[:5]:
                surface.blit(self._small_icon(cid, 30), (bx, y))
                bx += 36
            if not ids:
                surface.blit(self.font_small.render("—", True, (120, 140, 170)), (x + 96, y + 4))
            y += 36

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
        # En attendant l'image, un placeholder.
        return (self.icons.get(player.get("championId"))
                or self._placeholder_icon(player.get("championName") or "?"))

    def _small_icon(self, champ_id, size: int) -> pygame.Surface:
        """Petite icône (pour les bans) depuis le cache, redimensionnée."""
        icon = self.icons.get(champ_id)
        if icon is not None:
            return pygame.transform.smoothscale(icon, (size, size))
        placeholder = pygame.Surface((size, size))
        placeholder.fill((45, 55, 80))
        return placeholder

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        """Reçoit une image demandée ; la met en cache et redessine."""
        if self.icons.put(champion_id, icon_b64):
            self._last_state = None

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
