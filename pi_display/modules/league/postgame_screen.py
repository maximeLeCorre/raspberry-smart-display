"""Écran de fin de partie : comparatif des 10 joueurs en barres horizontales.

Dessiné **entièrement en code** (pas de PNG de cadres) car tout est dynamique.

Onglets en haut = une métrique chacun (Dégâts, Subis, Or, CS, Vision, Soins) ;
clic sur un onglet = change le graphe. Chaque barre = un joueur, triées par
valeur décroissante, avec son icône de champion et sa valeur.

Code couleur : TOI = rouge, tes amis (premade) = rose, les autres = bleu.
Un bandeau en bas rappelle tes stats en petit, quel que soit l'onglet.

Données reçues (payload), tout via la LCU (aucune clé API Web) :
    {"win": true, "queue": "Classé Solo/Duo", "duration": 1830,
     "me": {"championId": 103, "championName": "Ahri", "kda": [12,4,9],
            "cs": 210, "gold": 14200, "damage": 32500, "level": 16},
     "players": [
        {"name": "maxoulefou", "championId": 103, "championName": "Ahri",
         "team": 100, "isSelf": true, "isFriend": false, "kda": [12,4,9],
         "metrics": {"dmg": 32500, "taken": 18900, "gold": 14200,
                     "cs": 210, "vision": 22, "heal": 5400}},
        ... (jusqu'à 10 joueurs)
     ]}
"""

from __future__ import annotations


import pygame

from inputs import ACTION_BACK
from modules.league.icons import ChampionIcons
from screen import Screen

# Métriques -> (clé dans payload.metrics, libellé de l'onglet). Doit rester
# aligné avec POSTGAME_METRICS côté agent (pc_agent/phases.py).
METRICS = [
    ("dmg", "Dégâts"),
    ("taken", "Subis"),
    ("gold", "Or"),
    ("cs", "CS"),
    ("vision", "Vision"),
    ("heal", "Soins"),
]

# Barre d'onglets (haut) + boutons COURBES et RETOUR à droite.
TAB_TOP, TAB_H = 8, 38
TAB_LEFT, TAB_RIGHT, TAB_GAP = 8, 590, 6
CURVES_RECT = pygame.Rect(600, 8, 92, 38)
RETOUR_RECT = pygame.Rect(700, 8, 92, 38)

TITLE_Y = 64

# Zone des 10 barres.
ROW_TOP, ROW_H = 86, 33
ICON = 26
NAME_X = 46
BAR_X = 158
BAR_MAX_W = 548          # largeur max d'une barre (valeur = max de la métrique)
VALUE_RIGHT = 788        # valeurs alignées à droite

# Bandeau perso (bas).
STRIP_TOP = 432

GREEN = (110, 210, 130)
# Couleurs des barres : toi=jaune, amis=rose, alliés=bleu, ennemis=rouge.
YELLOW = (240, 210, 70)    # toi
PINK = (240, 130, 190)     # amis (premade, ex. Matte Mwa)
BLUE = (92, 150, 235)      # alliés (ton équipe)
RED = (228, 86, 86)        # ennemis (équipe adverse)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
GOLD = (210, 175, 95)
BG = (10, 14, 26)
PANEL = (24, 32, 52)
TRACK = (30, 40, 62)      # fond de barre (piste)


def _mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fmt(n) -> str:
    """Nombre lisible : séparateur de milliers par espace fine (>= 1000)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n:,}".replace(",", " ") if n >= 1000 else str(n)


def _fit(text: str, font: pygame.font.Font, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


class PostGameScreen(Screen):
    name = "postgame"
    background_name = None          # dessiné en code
    bg_color = BG

    def __init__(self, app):
        super().__init__(app)
        self.league = app.modules["league"]
        self.font_title = pygame.font.Font(None, 40)
        self.font_tab = pygame.font.Font(None, 26)
        self.font_row = pygame.font.Font(None, 26)
        self.font_val = pygame.font.Font(None, 26)
        self.font_hint = pygame.font.Font(None, 22)
        self.font_strip = pygame.font.Font(None, 28)

        self.data: dict = {}
        self.active = METRICS[0][0]           # onglet-métrique sélectionné
        self.icons = ChampionIcons(self.league, ICON)
        self._last_signature = None

        # Rects des onglets (fixes) : (clé_métrique, rect).
        self._tab_rects: list[tuple[str, pygame.Rect]] = []
        slot = (TAB_RIGHT - TAB_LEFT) / len(METRICS)
        for i, (key, _label) in enumerate(METRICS):
            rect = pygame.Rect(int(TAB_LEFT + i * slot + TAB_GAP / 2), TAB_TOP,
                               int(slot - TAB_GAP), TAB_H)
            self._tab_rects.append((key, rect))

    # --------------------------------------------------------------- réseau
    def enter(self) -> None:
        self._last_signature = None
        self.icons.forget_requests()

    def update_data(self, payload: dict) -> None:
        self.data = payload or {}

    def set_champion_icon(self, champion_id: int, icon_b64: str | None) -> None:
        if self.icons.put(champion_id, icon_b64):
            self._last_signature = None

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            # En mode « revue » (ouvert depuis l'historique), RETOUR y revient.
            ret = self.league.postgame_return
            if ret and ret in self.app.screens:
                self.league.postgame_return = None
                self.app.manual_screen = ret
                self.app.set_screen(ret)
                return None
            return ACTION_BACK
        if CURVES_RECT.collidepoint(pos) and self.data.get("players"):
            self.league.open_curves_review()
            return None
        for key, rect in self._tab_rects:
            if rect.collidepoint(pos):
                self.active = key
                return None
        return None

    # ---------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        players = self.data.get("players") or []
        signature = (
            self.active,
            self.data.get("win"),
            self.data.get("status"),
            str(self.data.get("me")),
            tuple((p.get("championId"), p.get("isSelf"), p.get("isFriend"),
                   (p.get("metrics") or {}).get(self.active, 0)) for p in players),
            self.icons.signature(),
        )
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.fill(BG)
        self._draw_tabs(surface)
        hint = self.font_hint.render("RETOUR", True, GREY)
        pygame.draw.rect(surface, PANEL, RETOUR_RECT, border_radius=8)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))
        if self.data.get("players"):
            pygame.draw.rect(surface, PANEL, CURVES_RECT, border_radius=8)
            pygame.draw.rect(surface, GOLD, CURVES_RECT, width=1, border_radius=8)
            btn = self.font_hint.render("COURBES", True, WHITE)
            surface.blit(btn, btn.get_rect(center=CURVES_RECT.center))

        if not players:
            text = ("Détail non disponible"
                    if self.data.get("status") == "unavailable"
                    else "En attente du bilan…")
            msg = self.font_title.render(text, True, GREY)
            surface.blit(msg, msg.get_rect(center=(self.width // 2, self.height // 2)))
            return [pygame.Rect(0, 0, self.width, self.height)]

        self._draw_title(surface)
        self._draw_bars(surface, players)
        self._draw_strip(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_tabs(self, surface: pygame.Surface) -> None:
        for key, rect in self._tab_rects:
            label = dict(METRICS)[key]
            active = key == self.active
            pygame.draw.rect(surface, PANEL if active else (18, 24, 40),
                             rect, border_radius=8)
            if active:
                pygame.draw.rect(surface, GOLD, rect, width=2, border_radius=8)
            surf = self.font_tab.render(label, True, WHITE if active else GREY)
            surface.blit(surf, surf.get_rect(center=rect.center))

    def _draw_title(self, surface: pygame.Surface) -> None:
        win = self.data.get("win")
        parts = [
            ("VICTOIRE" if win else "DÉFAITE", GREEN if win else RED),
            (f"  {self.data.get('queue', '')}  •  {_mmss(self.data.get('duration', 0))}", GREY),
        ]
        widths = [self.font_title.render(t, True, c).get_width() for t, c in parts]
        x = (self.width - sum(widths)) // 2
        for (t, c), w in zip(parts, widths):
            surf = self.font_title.render(t, True, c)
            surface.blit(surf, (x, TITLE_Y - surf.get_height() // 2))
            x += w

    def _draw_bars(self, surface: pygame.Surface, players: list) -> None:
        rows = sorted(players, key=lambda p: (p.get("metrics") or {}).get(self.active, 0),
                      reverse=True)
        max_val = max((p.get("metrics") or {}).get(self.active, 0) for p in rows) or 1
        # Mon équipe (pour distinguer alliés/ennemis).
        my_team = next((p.get("team") for p in players if p.get("isSelf")), None)

        for i, p in enumerate(rows):
            top = ROW_TOP + i * ROW_H
            cy = top + ROW_H // 2
            if p.get("isSelf"):
                color = YELLOW
            elif p.get("isFriend"):
                color = PINK
            elif my_team is not None and p.get("team") == my_team:
                color = BLUE        # allié (ton équipe)
            else:
                color = RED         # ennemi (équipe adverse)

            # Icône + nom du champion.
            surface.blit(self._get_icon(p.get("championId") or 0,
                                        p.get("championName") or "?"),
                         (12, cy - ICON // 2))
            name = _fit(p.get("championName") or p.get("name") or "?",
                        self.font_row, BAR_X - NAME_X - 6)
            name_surf = self.font_row.render(name, True, WHITE)
            surface.blit(name_surf, (NAME_X, cy - name_surf.get_height() // 2))

            # Piste + barre proportionnelle.
            value = (p.get("metrics") or {}).get(self.active, 0)
            bar_w = max(3, int(BAR_MAX_W * value / max_val))
            track = pygame.Rect(BAR_X, cy - 9, BAR_MAX_W, 18)
            pygame.draw.rect(surface, TRACK, track, border_radius=6)
            pygame.draw.rect(surface, color, pygame.Rect(BAR_X, cy - 9, bar_w, 18),
                             border_radius=6)

            # Valeur, alignée à droite.
            val_surf = self.font_val.render(_fmt(value), True, WHITE)
            surface.blit(val_surf, (VALUE_RIGHT - val_surf.get_width(),
                                    cy - val_surf.get_height() // 2))

    def _draw_strip(self, surface: pygame.Surface) -> None:
        me = self.data.get("me") or {}
        pygame.draw.line(surface, (40, 52, 80), (8, STRIP_TOP - 6),
                         (self.width - 8, STRIP_TOP - 6), 1)
        cy = STRIP_TOP + 20
        surface.blit(self._get_icon(me.get("championId") or 0,
                                    me.get("championName") or "?"),
                     (12, cy - ICON // 2))
        k, d, a = (me.get("kda") or [0, 0, 0])[:3]
        name_surf = self.font_strip.render(me.get("championName") or "", True, YELLOW)
        surface.blit(name_surf, (46, cy - name_surf.get_height() // 2))
        detail = (f"{k} / {d} / {a}   •   CS {me.get('cs', 0)}   •   "
                  f"Or {_fmt(me.get('gold', 0))}   •   Dég {_fmt(me.get('damage', 0))}"
                  f"   •   Niv {me.get('level', 0)}")
        det_surf = self.font_strip.render(detail, True, GREY)
        surface.blit(det_surf, (46 + name_surf.get_width() + 18,
                                cy - det_surf.get_height() // 2))

    # ----------------------------------------------------------- icônes
    def _get_icon(self, champ_id: int, name: str) -> pygame.Surface:
        return self.icons.get(champ_id) or self._placeholder(name)

    def _placeholder(self, name: str) -> pygame.Surface:
        surface = pygame.Surface((ICON, ICON))
        surface.fill((45, 55, 80))
        initials = (name[:2] if name else "?").upper()
        label = self.font_row.render(initials, True, (210, 220, 235))
        surface.blit(label, label.get_rect(center=(ICON // 2, ICON // 2)))
        return surface
