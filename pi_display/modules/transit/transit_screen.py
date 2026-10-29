"""Écran « Trains » (code-drawn) : prochains départs d'une gare, par direction.

Ouvert depuis la tuile Trains de l'accueil. Deux colonnes (vers Paris / sens
opposé) de prochains départs : minutes restantes, heure, destination, mission,
voie et état. En bas, l'info trafic de la ligne (toucher = message suivant).

Les états sont **écrits** (« à l'heure », « retard +3 min », « supprimé »,
« à quai »), la couleur n'est qu'un renfort (utilisateur daltonien).
"""

from __future__ import annotations

import time

import pygame

from inputs import ACTION_BACK
from modules.system.news_screen import wrap_text
from screen import ASSETS_DIR, Screen

from .transit_feed import get_transit

RETOUR_RECT = pygame.Rect(690, 0, 110, 58)
COLS = (pygame.Rect(12, 68, 382, 320), pygame.Rect(406, 68, 382, 320))
HEADER_H = 38
ROW_H = 56
ROWS = 5
MINS_W = 104                    # colonne des minutes restantes (« 38 min »)
INFO = pygame.Rect(12, 396, 776, 76)

NUM_FONT = ASSETS_DIR / "fonts" / "DejaVuSans-Bold.ttf"   # chiffres alignés

BG = (10, 14, 26)
PANEL = (16, 22, 38)
ROW_BG = (22, 30, 50)
BTN = (30, 42, 68)
GRID = (34, 46, 74)
GOLD = (210, 175, 95)
WHITE = (238, 240, 245)
DIM = (150, 165, 195)
FAINT = (92, 106, 134)
GREEN = (110, 210, 130)
ORANGE = (230, 170, 70)
RED = (228, 86, 86)
# Couleurs officielles (fond, texte) des lignes — référentiel des lignes IDFM.
# La lettre est toujours écrite dans la pastille : la couleur n'est qu'un repère.
LINE_COLORS = {"L": ((196, 164, 204), (0, 0, 0)), "U": ((182, 19, 76), (255, 255, 255))}


_ABBREVIATIONS = (("Saint-", "St-"), ("Sainte-", "Ste-"), (" Rive Droite", " RD"),
                  (" Rive Gauche", " RG"))


def short_destination(name: str) -> str:
    """« Paris Saint-Lazare » -> « Paris St-Lazare », « Versailles Rive Droite » ->
    « Versailles RD » (abréviations des panneaux SNCF), pour tenir sur une ligne."""
    for long, short in _ABBREVIATIONS:
        name = name.replace(long, short)
    return name


def ellipsize(text: str, font: pygame.font.Font, max_w: int) -> str:
    """Tronque avec « … » pour tenir dans max_w pixels."""
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def minutes_label(dep, now: float) -> str:
    if dep.cancelled:
        return "suppr."
    if dep.at_stop:
        return "à quai"
    mins = int((dep.when - now) // 60)
    return "proche" if mins <= 0 else f"{mins} min"


def next_arrival(departures, destination: str, now: float):
    """Prochain train (non supprimé) vers ``destination`` pas encore arrivé en gare."""
    want = destination.lower()
    for dep in departures:
        when = dep.arrival or dep.when
        if (want in dep.destination.lower() and not dep.cancelled
                and (dep.at_stop or when >= now - 30)):
            return dep
    return None


def arrival_label(dep, now: float) -> str:
    """Temps avant l'entrée en gare : « 5 min », « proche », « à quai »."""
    if dep.at_stop:
        return "à quai"
    mins = int(((dep.arrival or dep.when) - now) // 60)
    return "proche" if mins <= 0 else f"{mins} min"


def status_text(dep) -> tuple[str, tuple]:
    """État écrit + couleur de renfort."""
    if dep.cancelled:
        return "supprimé", RED
    if dep.delay_min > 0:      # l'heure affichée est déjà l'heure réelle
        return f"retard +{dep.delay_min} min", ORANGE
    if dep.status in ("onTime", "early"):
        return "à l'heure", GREEN
    return "", DIM


class TransitScreen(Screen):
    name = "transit"
    background_name = None
    bg_color = BG
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        cfg = app.config.get("transit", {})
        self.station = str(cfg.get("station", "")).strip()
        self.lines = [str(v) for v in (cfg.get("lines") or {}).values()]
        self.directions = list(cfg.get("direction_labels", ["Vers Paris", "Autre sens"]))[:2]
        self.font_title = pygame.font.Font(None, 40)
        self.font = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 22)
        self.font_tiny = pygame.font.Font(None, 19)
        self.font_badge = pygame.font.Font(None, 24)
        big = str(NUM_FONT) if NUM_FONT.exists() else None
        self.font_mins = pygame.font.Font(big, 21 if big else 30)
        self.feed = get_transit(app)
        self.msg_index = 0
        self._sig = None

    def enter(self) -> None:
        self.msg_index = 0
        self._sig = None

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        if INFO.collidepoint(pos):
            self.msg_index += 1
            self._sig = None
        return None

    # ------------------------------------------------------------------ rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        snap = self.feed.snapshot() if self.feed else None
        # Minutes restantes et « il y a X s » : un redessin toutes les 10 s suffit.
        sig = (int(time.time() // 10), self.msg_index,
               (snap["updated"], snap["error"], len(snap["messages"])) if snap else None)
        if sig == self._sig:
            return []
        self._sig = sig
        surface.fill(BG)
        self._draw_top(surface, snap)
        if snap is None:
            self._center(surface, "Trains non configurés",
                         "Ajoute IDFM_API_KEY (clé PRIM gratuite) dans le .env du Pi.")
        elif not snap["updated"]:
            self._center(surface, "Chargement des prochains départs…" if not snap["error"]
                         else f"Indisponible : {snap['error']}", "")
        else:
            now = time.time()
            deps = snap["departures"]
            for col, label, to_paris in ((COLS[0], self.directions[0], True),
                                         (COLS[1], self.directions[-1], False)):
                self._draw_column(surface, col, label,
                                  [d for d in deps if d.to_paris == to_paris][:ROWS], now)
            self._draw_info(surface, snap["messages"])
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _center(self, surface, line1: str, line2: str) -> None:
        a = self.font.render(line1, True, WHITE)
        surface.blit(a, a.get_rect(center=(400, 230)))
        if line2:
            b = self.font_small.render(line2, True, DIM)
            surface.blit(b, b.get_rect(center=(400, 266)))

    def _draw_top(self, surface, snap) -> None:
        title = self.font_title.render("Trains", True, GOLD)
        surface.blit(title, (20, 10))
        x = 20 + title.get_width() + 14
        for name in self.lines:
            x = self._badge(surface, name, pygame.Rect(x, 13, 28, 28), self.font) + 6
        x += 4
        if self.station:
            st = self.font.render(self.station, True, WHITE)
            surface.blit(st, (x, 27 - st.get_height() // 2))
        if snap and snap["updated"]:
            age = int(time.time() - snap["updated"])
            txt = f"mis à jour il y a {age} s" if age < 120 else f"mis à jour il y a {age // 60} min"
            if snap["error"]:
                txt += f" · {snap['error']}"
            s = self.font_tiny.render(txt, True, ORANGE if snap["error"] else FAINT)
            surface.blit(s, (RETOUR_RECT.x - s.get_width() - 14, 21))
        pygame.draw.rect(surface, BTN, RETOUR_RECT, border_radius=8)
        r = self.font_small.render("RETOUR", True, (205, 210, 220))
        surface.blit(r, r.get_rect(center=RETOUR_RECT.center))
        pygame.draw.line(surface, GRID, (0, 60), (self.width, 60), 1)

    def _badge(self, surface, name: str, rect: pygame.Rect, font) -> int:
        """Pastille de ligne (lettre écrite sur la couleur de la ligne) ; renvoie son bord droit."""
        bg, fg = LINE_COLORS.get(name, (BTN, WHITE))
        pygame.draw.rect(surface, bg, rect, border_radius=5)
        t = font.render(name, True, fg)
        surface.blit(t, t.get_rect(center=(rect.centerx, rect.centery + 1)))
        return rect.right

    def _draw_column(self, surface, col, label, deps, now) -> None:
        pygame.draw.rect(surface, PANEL, col, border_radius=10)
        head = self.font.render(label, True, GOLD)
        surface.blit(head, (col.x + 14, col.y + HEADER_H // 2 - head.get_height() // 2 + 2))
        if not deps:
            s = self.font_small.render("Aucun départ annoncé", True, DIM)
            surface.blit(s, (col.x + 14, col.y + HEADER_H + 14))
            return
        for i, dep in enumerate(deps):
            row = pygame.Rect(col.x + 8, col.y + HEADER_H + i * ROW_H, col.w - 16, ROW_H - 6)
            pygame.draw.rect(surface, ROW_BG, row, border_radius=8)
            # Minutes restantes (ou « à quai » / « suppr. »).
            mins = minutes_label(dep, now)
            color = RED if dep.cancelled else (GREEN if dep.at_stop else WHITE)
            m = self.font_mins.render(mins, True, color)
            surface.blit(m, (row.x + 10, row.centery - m.get_height() // 2))
            # Ligne 1 : heure + pastille de ligne + destination (barrées si supprimé).
            x = row.x + MINS_W
            y1 = row.y + 6
            hour = self.font.render(time.strftime("%H:%M", time.localtime(dep.when)), True,
                                    FAINT if dep.cancelled else WHITE)
            surface.blit(hour, (x, y1))
            dx = x + hour.get_width() + 8
            if dep.line:
                dx = self._badge(surface, dep.line, pygame.Rect(dx, y1 - 1, 20, 20),
                                 self.font_small) + 7
            text = ellipsize(short_destination(dep.destination), self.font, row.right - dx - 8)
            l1 = self.font.render(text, True, FAINT if dep.cancelled else WHITE)
            surface.blit(l1, (dx, y1))
            if dep.cancelled:
                mid = y1 + l1.get_height() // 2
                pygame.draw.line(surface, RED, (x, mid), (dx + l1.get_width(), mid), 2)
            # Ligne 2 : mission · voie · état.
            parts = [p for p in (dep.mission, f"voie {dep.platform}" if dep.platform else "")
                     if p]
            text, scol = status_text(dep)
            sep = "  ·  " if parts and text else ""
            meta = self.font_small.render("  ·  ".join(parts) + sep, True, DIM)
            y2 = row.y + 30
            surface.blit(meta, (x, y2))
            if text:
                st = self.font_small.render(text, True, scol)
                surface.blit(st, (x + meta.get_width(), y2))

    def _draw_info(self, surface, messages) -> None:
        pygame.draw.rect(surface, PANEL, INFO, border_radius=10)
        disruptions = [m for m in messages if m.is_disruption]
        shown = disruptions or messages
        x, y = INFO.x + 14, INFO.y + 10
        if not shown:
            t = self.font_small.render("INFO TRAFIC", True, GOLD)
            surface.blit(t, (x, y))
            lines = " et ".join(self.lines)
            s = self.font.render(f"Aucune perturbation signalée (ligne{'s' if len(self.lines) > 1 else ''}"
                                 f" {lines}).", True, GREEN)
            surface.blit(s, (x, y + 26))
            return
        msg = shown[self.msg_index % len(shown)]
        tx = x
        if msg.is_disruption:
            pygame.draw.polygon(surface, ORANGE, [(x, y + 14), (x + 8, y), (x + 16, y + 14)])
            pygame.draw.line(surface, PANEL, (x + 8, y + 5), (x + 8, y + 9), 2)
            tag = self.font_small.render("PERTURBATION", True, ORANGE)
            tx = x + 22
        else:
            tag = self.font_small.render("INFO TRAFIC", True, GOLD)
        surface.blit(tag, (tx, y))
        if msg.line:
            self._badge(surface, msg.line, pygame.Rect(tx + tag.get_width() + 8, y - 3, 20, 20),
                        self.font_small)
        if len(shown) > 1:
            n = self.font_tiny.render(f"{self.msg_index % len(shown) + 1}/{len(shown)}"
                                      "  ·  toucher pour la suite", True, FAINT)
            surface.blit(n, (INFO.right - n.get_width() - 14, y + 2))
        for k, line in enumerate(wrap_text(msg.text, self.font_small, INFO.w - 28, 2)):
            s = self.font_small.render(line, True, WHITE)
            surface.blit(s, (x, y + 24 + k * 20))
