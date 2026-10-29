"""Stats comparées (code-drawn) : toi seul / l'ami seul / vous deux ensemble.

Lu depuis le **store local** (table `participations`, voir `store.compare`) →
consultable PC éteint. Les parties de l'ami arrivent par la synchro (l'agent lit
ses 20 dernières via la LCU, `[lol] compare`) et s'accumulent au fil du temps.

« Seul » = parties sans l'autre dans SON équipe ; « Ensemble » = même équipe
(victoire commune, chacun garde ses propres stats : affichées « toi / lui »).
Mise en valeur sans couleur seule (l'utilisateur est daltonien) : la meilleure
valeur solo est en blanc, l'autre en gris (contraste de luminosité).

En haut : filtres de mode (ARAM Chaos par défaut) et RETOUR (→ historique).
"""

from __future__ import annotations

import pygame

from screen import Screen

from .history_screen import FILTERS

STAT_FILTERS = FILTERS + [("Tout", "", ())]

RETOUR_RECT = pygame.Rect(700, 8, 92, 38)
BTN_TOP, BTN_H = 8, 38

LABEL_X = 20
COL_X = (300, 470, 660)          # centres : toi seul, ami seul, ensemble
HEAD_Y = 66
ROW_TOP, ROW_H = 100, 33
TOP_Y = 352                      # bloc « champions les plus joués »

BG = (10, 14, 26)
PANEL = (24, 32, 52)
PANEL_OFF = (18, 24, 40)
LINE = (34, 44, 70)
WHITE = (238, 238, 243)
GREY = (155, 172, 200)
DIM = (90, 104, 132)
GOLD = (210, 175, 95)

# (libellé, extracteur de valeur, format, plus grand = mieux ?)
ROWS = [
    ("Parties", lambda a: a["games"], "{}", None),
    ("Winrate", lambda a: a["winrate"], "{} %", True),
    ("K / D / A", lambda a: a["kda"], None, None),
    ("Ratio KDA", lambda a: a["kda_ratio"], "{:.2f}", True),
    ("Dégâts / min", lambda a: a["dmg_min"], "{:,}", True),
    ("Or / min", lambda a: a["gold_min"], "{:,}", True),
    ("CS / min", lambda a: a["cs_min"], "{:.1f}", True),
]


def _fmt(value, fmt) -> str:
    if value is None:
        return "—"
    if fmt is None:                      # K / D / A
        return " / ".join(str(round(x)) for x in value)
    return fmt.format(value).replace(",", " ")


def _fit(text: str, font: pygame.font.Font, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


class StatsScreen(Screen):
    name = "stats"
    background_name = None
    bg_color = BG

    def __init__(self, app):
        super().__init__(app)
        self.font_btn = pygame.font.Font(None, 26)
        self.font_head = pygame.font.Font(None, 28)
        self.font_sub = pygame.font.Font(None, 20)
        self.font_label = pygame.font.Font(None, 26)
        self.font_val = pygame.font.Font(None, 28)
        self.font_top = pygame.font.Font(None, 22)

        self.filter_idx = 0
        self.data: dict | None = None
        self._dirty = True
        self._filter_rects: list[pygame.Rect] = []
        x = 8
        for label, _w, _p in STAT_FILTERS:
            w = self.font_btn.size(label)[0] + 22
            self._filter_rects.append(pygame.Rect(x, BTN_TOP, w, BTN_H))
            x += w + 6

    @property
    def friend_name(self) -> str:
        return self.app.compare_rid.split("#", 1)[0] or "Ami"

    def reload(self) -> None:
        """Relit le store (ouverture, changement de filtre, fin de synchro)."""
        _label, where, params = STAT_FILTERS[self.filter_idx]
        me, other = self.app.summoner_rid, self.app.compare_rid
        self.data = (self.app.store.compare(me, other, where, params)
                     if "#" in me and "#" in other else None)
        self._dirty = True

    def enter(self) -> None:
        self._dirty = True

    # --------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            self.app.open_history()
            return None
        for i, rect in enumerate(self._filter_rects):
            if rect.collidepoint(pos):
                if i != self.filter_idx:
                    self.filter_idx = i
                    self.reload()
                return None
        return None

    # ---------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        if not self._dirty:
            return []
        self._dirty = False
        surface.fill(BG)
        self._draw_filters(surface)
        pygame.draw.rect(surface, PANEL, RETOUR_RECT, border_radius=8)
        hint = self.font_sub.render("RETOUR", True, GREY)
        surface.blit(hint, hint.get_rect(center=RETOUR_RECT.center))

        if self.data is None:
            msg = self.font_head.render(
                "Renseigne [lol] summoner et compare (Nom#TAG) dans config.toml.", True, GREY)
            surface.blit(msg, msg.get_rect(center=(self.width // 2, self.height // 2)))
            return [surface.get_rect()]

        self._draw_headers(surface)
        self._draw_rows(surface)
        self._draw_tops(surface)
        return [surface.get_rect()]

    def _draw_filters(self, surface) -> None:
        for i, rect in enumerate(self._filter_rects):
            active = i == self.filter_idx
            pygame.draw.rect(surface, PANEL if active else PANEL_OFF, rect, border_radius=8)
            if active:
                pygame.draw.rect(surface, GOLD, rect, width=2, border_radius=8)
            surf = self.font_btn.render(STAT_FILTERS[i][0], True, WHITE if active else GREY)
            surface.blit(surf, surf.get_rect(center=rect.center))

    def _draw_headers(self, surface) -> None:
        heads = (("Toi", "seul"), (self.friend_name, "seul"),
                 ("Ensemble", f"toi / {self.friend_name}"))
        for cx, (title, sub) in zip(COL_X, heads):
            t = self.font_head.render(_fit(title, self.font_head, 160), True, GOLD)
            surface.blit(t, t.get_rect(midbottom=(cx, HEAD_Y + 6)))
            s = self.font_sub.render(sub, True, DIM)
            surface.blit(s, s.get_rect(midtop=(cx, HEAD_Y + 8)))
        pygame.draw.line(surface, LINE, (12, ROW_TOP - 4), (self.width - 12, ROW_TOP - 4))

    def _draw_rows(self, surface) -> None:
        d = self.data
        for i, (label, get, fmt, higher) in enumerate(ROWS):
            cy = ROW_TOP + i * ROW_H + ROW_H // 2
            if i % 2 == 0:
                pygame.draw.rect(surface, (14, 19, 34),
                                 (12, cy - ROW_H // 2, self.width - 24, ROW_H))
            lab = self.font_label.render(label, True, GREY)
            surface.blit(lab, (LABEL_X, cy - lab.get_height() // 2))

            me, other = d["me_solo"], d["other_solo"]
            v_me, v_ot = (get(me) if me["games"] else None), (get(other) if other["games"] else None)
            # Meilleure valeur solo en blanc, l'autre en gris (luminosité, pas teinte).
            best = None
            if higher is not None and v_me is not None and v_ot is not None and v_me != v_ot:
                best = 0 if (v_me > v_ot) == higher else 1
            for col, value in enumerate((v_me, v_ot)):
                color = WHITE if best in (None, col) else GREY
                self._cell(surface, COL_X[col], cy, _fmt(value, fmt), color)

            duo_me, duo_ot = d["duo_me"], d["duo_other"]
            if not duo_me["games"]:
                text = "—"
            elif label in ("Parties", "Winrate"):   # communs au duo
                text = _fmt(get(duo_me), fmt)
            else:
                text = f"{_fmt(get(duo_me), fmt)}   |   {_fmt(get(duo_ot), fmt)}"
            self._cell(surface, COL_X[2], cy, text, WHITE)

    def _cell(self, surface, cx, cy, text, color) -> None:
        font = self.font_val if self.font_val.size(text)[0] <= 250 else self.font_top
        surf = font.render(text, True, color)
        surface.blit(surf, surf.get_rect(center=(cx, cy)))

    def _draw_tops(self, surface) -> None:
        top = self.data["top"]
        pygame.draw.line(surface, LINE, (12, TOP_Y - 8), (self.width - 12, TOP_Y - 8))
        title = self.font_sub.render("PLUS JOUÉS", True, GOLD)
        surface.blit(title, (LABEL_X, TOP_Y))
        hint = self.font_sub.render("(parties · winrate)", True, DIM)
        surface.blit(hint, (LABEL_X, TOP_Y + 20))

        def line(c):
            return f"{c['championName'] or '?'}  {c['games']} · {c['winrate']} %"

        columns = (
            [line(c) for c in top["me_solo"]],
            [line(c) for c in top["other_solo"]],
            [f"toi : {c['championName']} ({c['games']})" for c in top["duo_me"][:2]]
            + [f"{self.friend_name} : {c['championName']} ({c['games']})"
               for c in top["duo_other"][:2]],
        )
        for cx, lines in zip(COL_X, columns):
            if not lines:
                lines = ["—"]
            for j, text in enumerate(lines[:4]):
                surf = self.font_top.render(_fit(text, self.font_top, 176), True, GREY)
                surface.blit(surf, surf.get_rect(midtop=(cx, TOP_Y + j * 26)))
        if not self.data["other_solo"]["games"]:
            note = (f"Aucune partie solo de {self.friend_name} ici : ses 20 dernières "
                    "sont lues à chaque synchro (PC allumé).")
            surf = self.font_sub.render(note, True, DIM)
            surface.blit(surf, surf.get_rect(bottomright=(self.width - 14, self.height - 6)))
