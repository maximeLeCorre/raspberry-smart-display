"""Écran League « Courbes » : évolution de l'or, des CS, du niveau et des kills.

Deux sources, même format (`{"players": [...], "frames": [{t, gold, cs, level,
kills}], "estimated": bool}`, listes alignées sur `players`) :
  - **en direct** (bouton COURBES de l'écran de partie) : relevé du module toutes
    les 10 s de jeu ; or ESTIMÉ (valeur des objets, l'or des autres est invisible) ;
  - **partie terminée** (bouton COURBES du bilan) : timeline LCU stockée,
    1 point/minute, or total exact.

Vue « Équipes » : ton équipe (bleu ciel, trait PLEIN) contre les adversaires
(orange, TIRETS), étiquette écrite au bout de chaque courbe. Vue « Écart » :
différence ton équipe − adversaires autour de zéro (zones légendées « devant »).
Vue « Joueurs » : 10 courbes, toi en jaune épais, nom du champion au bout.
Jamais d'information portée par la seule couleur (utilisateur daltonien).
"""

from __future__ import annotations

import math

import pygame

from screen import Screen

BG = (10, 14, 26)
PANEL = (24, 32, 52)
GRID = (38, 48, 72)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
FAINT = (105, 118, 145)
GOLD = (210, 175, 95)
# Okabe-Ito : distinguables par les daltoniens (et doublés par le style de trait).
ALLY = (86, 180, 233)       # bleu ciel, trait plein
ENEMY = (230, 159, 0)       # orange, tirets
ME = (240, 228, 66)         # jaune, trait épais

METRICS = [("gold", "Or"), ("cs", "CS"), ("level", "Niveau"), ("kills", "Kills")]
VIEWS = [("teams", "Équipes"), ("diff", "Écart"), ("players", "Joueurs")]

BACK_RECT = pygame.Rect(700, 8, 92, 38)
TAB_Y, TAB_H, TAB_W, TAB_GAP = 54, 34, 86, 6
VIEW_X, VIEW_W = 476, 100
CHART = pygame.Rect(58, 104, 590, 316)
LABEL_X = CHART.right + 10
FOOTER_Y = 440

STATUS_TEXT = {
    "loading": "Chargement des courbes…",
    "offline": "Courbes disponibles quand le PC est allumé.",
    "unavailable": "Courbes non disponibles pour cette partie.",
    "waiting": "Les courbes apparaissent après quelques secondes de jeu…",
}


def _short(v: float) -> str:
    """12 500 -> « 12.5k » ; petits nombres tels quels."""
    if abs(v) >= 1000:
        return f"{v / 1000:.1f}k".replace(".0k", "k")
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}"


def axis_ticks(lo: float, hi: float) -> list[float]:
    """Graduations « rondes » (pas de 1, 2, 2.5 ou 5 × 10^n, 4 à 6 intervalles)
    couvrant [lo, hi] au plus près."""
    raw = max(hi - lo, 1e-9) / 5
    exp = 10 ** math.floor(math.log10(raw))
    step = next(m * exp for m in (1, 2, 2.5, 5, 10) if m * exp >= raw)
    first, last = math.floor(lo / step), math.ceil(hi / step)
    return [k * step for k in range(first, max(last, first + 1) + 1)]


def _mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _dashed(surface, color, points, width, dash=9, gap=6) -> None:
    """Polyligne en tirets (le style distingue l'adversaire sans la couleur)."""
    on, left = True, float(dash)
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        pos = 0.0
        while pos < seg:
            step = min(left, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                pygame.draw.line(surface, color, (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a),
                                 (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b), width)
            pos += step
            left -= step
            if left <= 0:
                on = not on
                left = float(dash if on else gap)


def team_series(series: dict, metric: str) -> tuple[list, list]:
    """Points (t, valeur) de ton équipe et des adversaires. Or/CS/kills : somme ;
    niveau : moyenne. Un point dont une valeur manque (or pas encore estimable)
    est omis."""
    players = series.get("players") or []
    mine = next((p.get("team") for p in players if p.get("isSelf")), None) or 100
    ally_idx = [i for i, p in enumerate(players) if p.get("team") == mine]
    enemy_idx = [i for i, p in enumerate(players) if p.get("team") != mine]
    out = ([], [])
    for frame in series.get("frames") or []:
        values = frame.get(metric) or []
        for idx, pts in ((ally_idx, out[0]), (enemy_idx, out[1])):
            vals = [values[i] if i < len(values) else None for i in idx]
            if not vals or any(v is None for v in vals):
                continue
            total = sum(vals)
            pts.append((frame.get("t", 0), total / len(vals) if metric == "level" else total))
    return out


def player_series(series: dict, metric: str, index: int) -> list:
    pts = []
    for frame in series.get("frames") or []:
        values = frame.get(metric) or []
        if index < len(values) and values[index] is not None:
            pts.append((frame.get("t", 0), values[index]))
    return pts


class CurvesScreen(Screen):
    name = "curves"
    background_name = None          # dessiné en code
    bg_color = BG

    def __init__(self, app):
        super().__init__(app)
        self.league = app.modules["league"]
        self.font_title = pygame.font.Font(None, 30)
        self.font_btn = pygame.font.Font(None, 26)
        self.font_axis = pygame.font.Font(None, 20)
        self.font_label = pygame.font.Font(None, 22)
        self.font_note = pygame.font.Font(None, 22)
        self.metric = "gold"
        self.view = "diff"          # en or, les totaux d'équipe se superposent
        self.live = True
        self.game_id = None
        self._series: dict | None = None
        self._status = "waiting"
        self._tab_rects = [(key, pygame.Rect(8 + i * (TAB_W + TAB_GAP), TAB_Y, TAB_W, TAB_H))
                           for i, (key, _label) in enumerate(METRICS)]
        self._view_rects = [(key, pygame.Rect(VIEW_X + i * (VIEW_W + TAB_GAP), TAB_Y,
                                              VIEW_W, TAB_H))
                            for i, (key, _label) in enumerate(VIEWS)]
        self._last_signature = None

    # ------------------------------------------------------------- sources
    def show_live(self) -> None:
        self.live, self.game_id = True, None

    def show_game(self, game_id) -> None:
        self.live, self.game_id = False, game_id
        self.refresh()

    def refresh(self) -> None:
        """Recharge la série d'une partie terminée (timeline arrivée…)."""
        if not self.live:
            self._series, self._status = self.league.curves_series(self.game_id)
        self._last_signature = None

    def _current(self) -> tuple[dict | None, str]:
        if self.live:
            series = self.league.live
            return series, ("ok" if len(series.get("frames") or []) >= 2 else "waiting")
        return self._series, self._status

    def enter(self) -> None:
        self._last_signature = None

    # -------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if BACK_RECT.collidepoint(pos):
            self.league.close_curves(self.live)
            return None
        for key, rect in self._tab_rects:
            if rect.collidepoint(pos):
                self.metric = key
        for key, rect in self._view_rects:
            if rect.collidepoint(pos):
                self.view = key
        return None

    # ----------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        series, status = self._current()
        frames = (series or {}).get("frames") or []
        signature = (self.live, self.game_id, self.metric, self.view, status, id(series),
                     len(frames), frames[-1].get("t") if frames else None)
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.fill(BG)
        self._draw_header(surface, series)
        if status != "ok" or not series:
            msg = self.font_title.render(STATUS_TEXT.get(status, "—"), True, GREY)
            surface.blit(msg, msg.get_rect(center=CHART.center))
            return [pygame.Rect(0, 0, self.width, self.height)]

        if self.view == "teams":
            lines = self._team_lines(series)
        elif self.view == "diff":
            lines = self._diff_lines(series)
        else:
            lines = self._player_lines(series)
        self._draw_chart(surface, series, lines)
        self._draw_footer(surface, series)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_header(self, surface, series) -> None:
        frames = (series or {}).get("frames") or []
        if self.live:
            title = "Courbes · en direct" + (f" · {_mmss(frames[-1]['t'])}" if frames else "")
        else:
            title = "Courbes de la partie"
        surface.blit(self.font_title.render(title, True, WHITE), (12, 18))

        pygame.draw.rect(surface, PANEL, BACK_RECT, border_radius=8)
        back = self.font_btn.render("TABLEAU" if self.live else "RETOUR", True, GREY)
        surface.blit(back, back.get_rect(center=BACK_RECT.center))

        for rects, current, labels in ((self._tab_rects, self.metric, dict(METRICS)),
                                       (self._view_rects, self.view, dict(VIEWS))):
            for key, rect in rects:
                active = key == current
                pygame.draw.rect(surface, (44, 58, 92) if active else PANEL, rect,
                                 border_radius=8)
                if active:      # actif : cadre doré + texte blanc (pas que la teinte)
                    pygame.draw.rect(surface, GOLD, rect, width=2, border_radius=8)
                txt = self.font_btn.render(labels[key], True, WHITE if active else GREY)
                surface.blit(txt, txt.get_rect(center=rect.center))

    # ----------------------------------------------------------- courbes
    def _team_lines(self, series) -> list[dict]:
        ally, enemy = team_series(series, self.metric)
        return [
            {"pts": enemy, "color": ENEMY, "width": 3, "dashed": True, "label": "Adversaires"},
            {"pts": ally, "color": ALLY, "width": 3, "dashed": False, "label": "Ton équipe"},
        ]

    def _diff_lines(self, series) -> list[dict]:
        ally, enemy = team_series(series, self.metric)
        diff = [(t, a - e) for (t, a), (_t, e) in zip(ally, enemy)]
        return [{"pts": diff, "color": WHITE, "width": 2, "dashed": False, "label": "Écart"}]

    def _player_lines(self, series) -> list[dict]:
        players = series.get("players") or []
        mine = next((p.get("team") for p in players if p.get("isSelf")), None) or 100
        lines = []
        for i, p in enumerate(players):
            me = bool(p.get("isSelf"))
            ally = p.get("team") == mine
            lines.append({
                "pts": player_series(series, self.metric, i),
                "color": ME if me else (ALLY if ally else ENEMY),
                "width": 3 if me else 1,
                "dashed": not ally,
                "label": "Toi" if me else (p.get("champion") or p.get("name") or "?"),
                "order": 2 if me else (1 if ally else 0),
            })
        return sorted(lines, key=lambda line: line["order"])     # toi par-dessus

    def _draw_chart(self, surface, series, lines) -> None:
        frames = series.get("frames") or []
        t_max = max(60, frames[-1].get("t", 0) if frames else 60)
        values = [v for line in lines for _, v in line["pts"]] or [0]
        if self.view == "diff":                   # symétrique autour de zéro
            span = max(abs(v) for v in values) or 1
            ticks = axis_ticks(-span, span)
        else:
            ticks = axis_ticks(0, max(values) or 1)
        v_min, v_max = ticks[0], ticks[-1]

        def xy(t, v):
            return (CHART.x + CHART.w * t / t_max,
                    CHART.bottom - CHART.h * (v - v_min) / (v_max - v_min))

        # Grille horizontale + graduations.
        for v in ticks:
            y = xy(0, v)[1]
            pygame.draw.line(surface, WHITE if (v == 0 and self.view == "diff") else GRID,
                             (CHART.x, y), (CHART.right, y), 1)
            lab = self.font_axis.render(("+" if v > 0 and self.view == "diff" else "")
                                        + _short(v), True, FAINT)
            surface.blit(lab, lab.get_rect(midright=(CHART.x - 6, y)))
        if self.view == "diff":
            self._draw_diff_zones(surface, [xy(t, v) for t, v in lines[0]["pts"]], xy(0, 0)[1])
        # Minutes en abscisse (au plus ~6 repères).
        minutes = t_max / 60
        step = next((s for s in (1, 2, 5, 10, 15) if minutes / s <= 6), 20)
        m = 0
        while m * 60 <= t_max:
            x = CHART.x + CHART.w * m * 60 / t_max
            pygame.draw.line(surface, GRID, (x, CHART.bottom), (x, CHART.bottom + 4), 1)
            lab = self.font_axis.render(f"{m}'", True, FAINT)
            surface.blit(lab, lab.get_rect(midtop=(x, CHART.bottom + 6)))
            m += step

        ends = []
        for line in lines:
            pts = [xy(t, v) for t, v in line["pts"]]
            if len(pts) >= 2:
                if line["dashed"]:
                    _dashed(surface, line["color"], pts, line["width"])
                elif line["width"] > 1:
                    pygame.draw.lines(surface, line["color"], False, pts, line["width"])
                else:
                    pygame.draw.aalines(surface, line["color"], False, pts)
            if pts:
                ends.append((pts[-1][1], line))
        self._draw_end_labels(surface, ends)

    def _draw_diff_zones(self, surface, pts, zero_y) -> None:
        """Aire entre la courbe d'écart et zéro : bleu ciel au-dessus (ton équipe
        devant), orange en dessous ; chaque zone est aussi légendée par écrit."""
        if len(pts) >= 2:
            poly = [(pts[0][0], zero_y)] + pts + [(pts[-1][0], zero_y)]
            layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            for color, clip in ((ALLY, pygame.Rect(CHART.x, CHART.y, CHART.w, zero_y - CHART.y)),
                                (ENEMY, pygame.Rect(CHART.x, zero_y, CHART.w,
                                                    CHART.bottom - zero_y))):
                layer.set_clip(clip)
                pygame.draw.polygon(layer, (*color, 70), poly)
            layer.set_clip(None)
            surface.blit(layer, (0, 0))
        # Triangles dessinés (la police par défaut n'a pas ▲/▼).
        x, top, bottom = CHART.x + 8, CHART.y + 6, CHART.bottom - 20
        pygame.draw.polygon(surface, ALLY, [(x, top + 12), (x + 12, top + 12), (x + 6, top + 2)])
        pygame.draw.polygon(surface, ENEMY, [(x, bottom + 2), (x + 12, bottom + 2),
                                             (x + 6, bottom + 12)])
        surface.blit(self.font_label.render("ton équipe devant", True, ALLY), (x + 18, top))
        surface.blit(self.font_label.render("adversaires devant", True, ENEMY), (x + 18, bottom))

    def _draw_end_labels(self, surface, ends) -> None:
        """Étiquette écrite au bout de chaque courbe, écartées pour ne pas se
        chevaucher (repère non coloré : nom + valeur)."""
        gap = 15 if self.view == "players" else 42
        ends.sort(key=lambda e: e[0])
        placed: list[float] = []
        for y, _line in ends:
            y = max(CHART.y + 6, y if not placed else max(y, placed[-1] + gap))
            placed.append(y)
        overflow = placed[-1] - (CHART.bottom - 6) if placed else 0
        if overflow > 0:          # trop bas : on remonte le tout
            placed = [max(CHART.y + 6, y - overflow) for y in placed]
        for (_y, line), y in zip(ends, placed):
            value = _short(line["pts"][-1][1]) if line["pts"] else "—"
            if self.view == "diff" and line["pts"]:
                last = line["pts"][-1][1]
                value = ("+" if last > 0 else "") + value
            if self.view in ("teams", "diff"):
                name = self.font_label.render(line["label"], True, line["color"])
                val = self.font_title.render(value, True, WHITE)
                surface.blit(name, (LABEL_X, y - 16))
                surface.blit(val, (LABEL_X, y + 2))
            else:
                text = f"{line['label'][:11]} {value}"
                lab = self.font_axis.render(text, True, line["color"])
                surface.blit(lab, lab.get_rect(midleft=(LABEL_X, y)))

    def _draw_footer(self, surface, series) -> None:
        notes = []
        if self.view in ("teams", "diff"):
            ally, enemy = team_series(series, self.metric)
            if ally and enemy:
                diff = ally[-1][1] - enemy[-1][1]
                who = "pour ton équipe" if diff >= 0 else "pour les adversaires"
                notes.append(f"Écart : {_short(abs(diff))} {who} ({_mmss(ally[-1][0])})")
        else:
            notes.append("Trait plein : ton équipe · tirets : adversaires")
        if self.metric == "gold":
            notes.append("or estimé (valeur des objets)" if series.get("estimated")
                         else "or total gagné")
        if self.metric == "level" and self.view == "teams":
            notes.append("niveau moyen")
        txt = self.font_note.render("  ·  ".join(notes), True, GREY)
        surface.blit(txt, (12, FOOTER_Y + 10))
