"""Écran League « Écarts » : compteurs ton équipe / adversaires et leur différence.

Pour l'or, les kills, les CS et le niveau moyen : valeur de ton équipe, valeur
adverse et **écart** écrit en grand (signe + « devant »/« derrière »), avec sa
variation sur la dernière minute (tendance).

Sources, même format (`{"players", "frames": [{t, gold, cs, level, kills}],
"current", "estimated"}`, listes alignées sur `players`) :
  - **en direct** (bouton ÉCARTS de l'écran de partie) : valeurs du dernier
    message de l'agent (`current`, ~1/s), tendance tirée du relevé /10 s ; or
    ESTIMÉ (valeur des objets : l'or des autres joueurs est invisible) ;
  - **partie terminée** (bouton ÉCARTS du bilan) : timeline LCU stockée (or
    total exact), valeurs de fin de partie, tendance sur sa dernière minute.

Couleurs (bleu ciel / rouge, comme le bilan) toujours doublées par le texte :
signe + « devant »/« derrière » (utilisateur daltonien).
"""

from __future__ import annotations

import pygame

from screen import Screen

BG = (10, 14, 26)
PANEL = (24, 32, 52)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
ALLY = (86, 180, 233)       # bleu ciel : ton équipe, écart positif
ENEMY = (235, 80, 80)       # rouge : adversaires, écart négatif

METRICS = [("gold", "Or"), ("kills", "Kills"), ("cs", "CS"), ("level", "Niveau moyen")]
TREND_WINDOW = 60           # s : tendance = évolution de l'écart sur la dernière minute

BACK_RECT = pygame.Rect(700, 8, 92, 38)
ALLY_X, DIFF_X, ENEMY_X = 170, 400, 630
HEAD_Y = 66
ROW_TOP, ROW_H, ROW_GAP = 86, 84, 6

STATUS_TEXT = {
    "loading": "Chargement des données de la partie…",
    "offline": "Données disponibles quand le PC est allumé.",
    "unavailable": "Données non disponibles pour cette partie.",
    "waiting": "Les compteurs apparaissent dès les premières données de la partie…",
}


def team_totals(series: dict, frame: dict | None, metric: str) -> tuple:
    """(ton équipe, adversaires) pour une frame : somme (niveau : moyenne) ;
    None si une valeur manque (or pas encore estimable)."""
    players = series.get("players") or []
    if not frame or not players:
        return None, None
    mine = next((p.get("team") for p in players if p.get("isSelf")), None) or 100
    values = frame.get(metric) or []
    out = []
    for ally in (True, False):
        vals = [values[i] if i < len(values) else None
                for i, p in enumerate(players) if (p.get("team") == mine) == ally]
        if not vals or any(v is None for v in vals):
            out.append(None)
        else:
            out.append(sum(vals) / len(vals) if metric == "level" else sum(vals))
    return out[0], out[1]


def current_frame(series: dict) -> dict | None:
    return series.get("current") or ((series.get("frames") or [None])[-1])


def trend(series: dict, metric: str) -> float | None:
    """Variation de l'écart sur la dernière minute (None : pas assez de recul)."""
    cur = current_frame(series)
    if not cur:
        return None
    past = None
    for frame in series.get("frames") or []:
        if frame.get("t", 0) <= cur.get("t", 0) - TREND_WINDOW:
            past = frame
    if past is None:
        return None
    a, e = team_totals(series, cur, metric)
    pa, pe = team_totals(series, past, metric)
    if None in (a, e, pa, pe):
        return None
    return (a - e) - (pa - pe)


def fmt(metric: str, value: float, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ("-" if value < 0 else "")
    v = abs(value)
    if metric == "level":
        text = f"{v:.1f}"
    elif v >= 1000:
        text = f"{v / 1000:.1f}k"
    else:
        text = f"{v:.0f}"
    return sign + text


def _mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class CountersScreen(Screen):
    name = "counters"
    background_name = None          # dessiné en code
    bg_color = BG

    def __init__(self, app):
        super().__init__(app)
        self.league = app.modules["league"]
        self.font_title = pygame.font.Font(None, 30)
        self.font_btn = pygame.font.Font(None, 26)
        self.font_head = pygame.font.Font(None, 26)
        self.font_label = pygame.font.Font(None, 24)
        self.font_value = pygame.font.Font(None, 46)
        self.font_diff = pygame.font.Font(None, 50)
        self.font_sub = pygame.font.Font(None, 22)
        self.live = True
        self.game_id = None
        self._series: dict | None = None
        self._status = "waiting"
        self._last_signature = None

    # ------------------------------------------------------------- sources
    def show_live(self) -> None:
        self.live, self.game_id = True, None

    def show_game(self, game_id) -> None:
        self.live, self.game_id = False, game_id
        self.refresh()

    def refresh(self) -> None:
        """Recharge les données d'une partie terminée (timeline arrivée…)."""
        if not self.live:
            self._series, self._status = self.league.game_series(self.game_id)
        self._last_signature = None

    def _source(self) -> tuple[dict | None, str]:
        if self.live:
            series = self.league.live
            return series, ("ok" if current_frame(series) else "waiting")
        return self._series, self._status

    def enter(self) -> None:
        self._last_signature = None

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if BACK_RECT.collidepoint(pos):
            self.league.close_counters(self.live)
        return None

    # ----------------------------------------------------------------- rendu
    def _rows(self, series: dict) -> list[tuple]:
        cur = current_frame(series)
        rows = []
        for key, label in METRICS:
            ally, enemy = team_totals(series, cur, key)
            diff = None if ally is None or enemy is None else ally - enemy
            rows.append((key, label, ally, enemy, diff, trend(series, key)))
        return rows

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        series, status = self._source()
        rows = self._rows(series) if (status == "ok" and series) else []
        cur = current_frame(series) if series else None
        signature = (self.live, self.game_id, status, tuple(rows),
                     cur.get("t") if cur else None)
        if signature == self._last_signature:
            return []
        self._last_signature = signature

        surface.fill(BG)
        self._draw_header(surface, cur)
        if not rows:
            msg = self.font_label.render(STATUS_TEXT.get(status, "—"), True, GREY)
            surface.blit(msg, msg.get_rect(center=(self.width // 2, self.height // 2)))
            return [pygame.Rect(0, 0, self.width, self.height)]

        for x, text, color in ((ALLY_X, "Ton équipe", ALLY), (DIFF_X, "Écart", GREY),
                               (ENEMY_X, "Adversaires", ENEMY)):
            head = self.font_head.render(text, True, color)
            surface.blit(head, head.get_rect(center=(x, HEAD_Y)))
        for i, row in enumerate(rows):
            self._draw_row(surface, ROW_TOP + i * (ROW_H + ROW_GAP), *row)
        self._draw_footer(surface, series)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _draw_header(self, surface, cur) -> None:
        if self.live:
            title = "Écarts · en direct" + (f" · {_mmss(cur['t'])}" if cur else "")
        else:
            title = "Écarts de la partie" + (f" · fin ({_mmss(cur['t'])})" if cur else "")
        surface.blit(self.font_title.render(title, True, WHITE), (12, 18))
        pygame.draw.rect(surface, PANEL, BACK_RECT, border_radius=8)
        back = self.font_btn.render("TABLEAU" if self.live else "RETOUR", True, GREY)
        surface.blit(back, back.get_rect(center=BACK_RECT.center))

    def _draw_row(self, surface, y, key, label, ally, enemy, diff, trend_value) -> None:
        box = pygame.Rect(8, y, self.width - 16, ROW_H)
        pygame.draw.rect(surface, PANEL, box, border_radius=10)
        surface.blit(self.font_label.render(label, True, GREY), (box.x + 12, box.y + 8))

        mid = box.centery + 6
        for x, value in ((ALLY_X, ally), (ENEMY_X, enemy)):
            txt = self.font_value.render("…" if value is None else fmt(key, value), True, WHITE)
            surface.blit(txt, txt.get_rect(center=(x, mid)))

        if diff is None:
            word, color, big = "en attente", GREY, "…"
        elif abs(diff) < (0.05 if key == "level" else 0.5):
            word, color, big = "égalité", WHITE, "="
        else:
            ahead = diff > 0
            word = "devant" if ahead else "derrière"
            color = ALLY if ahead else ENEMY
            big = fmt(key, diff, signed=True)
        val = self.font_diff.render(big, True, color)
        surface.blit(val, val.get_rect(center=(DIFF_X, box.y + 30)))
        sub = word
        if trend_value is not None and diff is not None:
            sub += ("  ·  stable sur 1 min" if abs(trend_value) < (0.05 if key == "level" else 0.5)
                    else f"  ·  {fmt(key, trend_value, signed=True)} en 1 min")
        sub_s = self.font_sub.render(sub, True, GREY)
        surface.blit(sub_s, sub_s.get_rect(center=(DIFF_X, box.bottom - 16)))

    def _draw_footer(self, surface, series) -> None:
        note = ("Or estimé : valeur des objets achetés (l'or en poche des autres est invisible)"
                if series.get("estimated") else "Or : total gagné (exact)")
        txt = self.font_sub.render(note, True, GREY)
        surface.blit(txt, (12, self.height - 26))
