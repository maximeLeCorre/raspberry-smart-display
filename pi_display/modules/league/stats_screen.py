"""Stats comparées (code-drawn) : toi seul / l'ami seul / vous deux ensemble.

Lu depuis le **store local** (table `participations`, voir `store.compare`) →
consultable PC éteint. Les parties de l'ami arrivent par la synchro (l'agent lit
ses 20 dernières via la LCU, `[lol] compare`) et s'accumulent au fil du temps.

« Seul » = parties sans l'autre dans SON équipe ; « Ensemble » = même équipe
(victoire commune, chacun garde ses propres stats : affichées « toi / lui »).
Mise en valeur sans couleur seule (l'utilisateur est daltonien) : la meilleure
valeur solo est en blanc, l'autre en gris (contraste de luminosité).

En haut : filtres de mode (ARAM Chaos par défaut), bouton **Période** (fenêtre
de dates, voir `period.py`) et RETOUR (→ historique). La période ouvre un
sélecteur plein écran : préréglages (7/30/90 j, toutes dates) + début/fin
réglables au jour ou au mois ; les stats sont relues à chaque changement
(aperçu du nombre de parties). Elle reste choisie tant que l'appli tourne.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pygame

from screen import Screen

from . import period
from .history_screen import FILTERS

STAT_FILTERS = FILTERS + [("Tout", "", ())]

RETOUR_RECT = pygame.Rect(700, 8, 92, 38)
BTN_TOP, BTN_H = 8, 38

LABEL_X = 20
COL_X = (300, 470, 660)          # centres : toi seul, ami seul, ensemble
HEAD_Y = 66
ROW_TOP, ROW_H = 100, 33
TOP_Y = 352                      # bloc « champions les plus joués »

# Sélecteur de période (plein écran).
PRESET_Y, PRESET_H = 64, 56
DATE_ROWS = (("Du", 156), ("Au", 250))          # (libellé, haut de la ligne)
DATE_ROW_H = 66
STEPS = (("-1 mois", "m", -1, 100, 112), ("-1 j", "d", -1, 222, 90),
         ("+1 j", "d", 1, 530, 90), ("+1 mois", "m", 1, 630, 112))  # (texte, unité, sens, x, w)
DATE_BOX = (322, 198)                            # (x, w) de la date affichée
SUMMARY_Y = 352

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
        self._period_rect = pygame.Rect(x + 6, BTN_TOP, RETOUR_RECT.x - x - 14, BTN_H)

        # Période (dates incluses ; None = toutes) et sélecteur ouvert ?
        self.start: date | None = None
        self.end: date | None = None
        self._picking = False
        gap = 10
        w = (self.width - 32 - gap * (len(period.PRESETS) - 1)) // len(period.PRESETS)
        self._preset_rects = [pygame.Rect(16 + i * (w + gap), PRESET_Y, w, PRESET_H)
                              for i in range(len(period.PRESETS))]

    @property
    def friend_name(self) -> str:
        return self.app.compare_rid.split("#", 1)[0] or "Ami"

    def reload(self) -> None:
        """Relit le store (ouverture, changement de filtre, fin de synchro)."""
        _label, mode_where, mode_params = STAT_FILTERS[self.filter_idx]
        per_where, per_params = period.where(self.start, self.end)
        where = " AND ".join(f"({w})" for w in (mode_where, per_where) if w)
        params = (*mode_params, *per_params)
        me, other = self.app.summoner_rid, self.app.compare_rid
        self.data = (self.app.store.compare(me, other, where, params)
                     if "#" in me and "#" in other else None)
        self._dirty = True

    def enter(self) -> None:
        self._picking = False
        self._dirty = True

    # --------------------------------------------------------------- période
    @staticmethod
    def _today() -> date:
        return date.today()

    def _set_period(self, start, end) -> None:
        self.start, self.end = start, end
        self.reload()

    def _step(self, which: str, unit: str, sign: int) -> None:
        """Décale le début ou la fin d'un jour / d'un mois (début ≤ fin ≤ aujourd'hui)."""
        today = self._today()
        start, end = self.start, self.end
        if start is None or end is None:      # « toutes dates » → bornes réelles
            oldest = self.app.store.oldest_creation()
            start = datetime.fromtimestamp(oldest / 1000).date() if oldest else today
            end = today
        cur = start if which == "Du" else end
        new = (period.add_months(cur, sign) if unit == "m"
               else cur + timedelta(days=sign))
        if which == "Du":
            start = min(new, end)
        else:
            end = max(start, min(new, today))
        self._set_period(start, end)

    def _step_enabled(self, which: str, sign: int) -> bool:
        if self.start is None or self.end is None:
            return not (which == "Au" and sign > 0)
        if which == "Du":
            return sign < 0 or self.start < self.end
        return (self.end < self._today()) if sign > 0 else self.end > self.start

    def _touch_picker(self, pos) -> None:
        if RETOUR_RECT.collidepoint(pos):          # OK : retour aux stats
            self._picking = False
            self._dirty = True
            return
        for rect, (_label, days) in zip(self._preset_rects, period.PRESETS):
            if rect.collidepoint(pos):
                self._set_period(*period.preset(days, self._today()))
                return
        for which, top in DATE_ROWS:
            for _text, unit, sign, x, w in STEPS:
                if (pygame.Rect(x, top, w, DATE_ROW_H).collidepoint(pos)
                        and self._step_enabled(which, sign)):
                    self._step(which, unit, sign)
                    return

    # --------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if self._picking:
            self._touch_picker(pos)
            return None
        if self._period_rect.collidepoint(pos):
            self._picking = True
            self._dirty = True
            return None
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
        if self._picking:
            self._draw_picker(surface)
            return [surface.get_rect()]
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
        # Période : encadrée en or (et texte blanc) dès qu'elle restreint les dates.
        rect = self._period_rect
        restricted = self.start is not None
        pygame.draw.rect(surface, PANEL, rect, border_radius=8)
        pygame.draw.rect(surface, GOLD if restricted else LINE, rect, width=2, border_radius=8)
        text = period.short_label(self.start, self.end, self._today())
        surf = self.font_btn.render(_fit(text, self.font_btn, rect.w - 12), True,
                                    WHITE if restricted else GREY)
        surface.blit(surf, surf.get_rect(center=rect.center))

    # ------------------------------------------------------- sélecteur période
    def _button(self, surface, rect, text, *, active=False, enabled=True) -> None:
        pygame.draw.rect(surface, PANEL if enabled else PANEL_OFF, rect, border_radius=8)
        if active:
            pygame.draw.rect(surface, GOLD, rect, width=2, border_radius=8)
        color = WHITE if active else (GREY if enabled else DIM)
        surf = self.font_btn.render(text, True, color)
        surface.blit(surf, surf.get_rect(center=rect.center))

    def _draw_picker(self, surface) -> None:
        today = self._today()
        title = self.font_head.render("PÉRIODE DES STATS", True, GOLD)
        surface.blit(title, (LABEL_X, 18))
        self._button(surface, RETOUR_RECT, "OK", active=True)

        for rect, (label, days) in zip(self._preset_rects, period.PRESETS):
            active = (self.start, self.end) == period.preset(days, today)
            self._button(surface, rect, label, active=active)

        oldest = self.app.store.oldest_creation()
        shown = {"Du": self.start or (datetime.fromtimestamp(oldest / 1000).date()
                                      if oldest else None),
                 "Au": self.end or today}
        for which, top in DATE_ROWS:
            lab = self.font_head.render(which, True, GREY)
            surface.blit(lab, lab.get_rect(midleft=(LABEL_X + 6, top + DATE_ROW_H // 2)))
            for text, _unit, sign, x, w in STEPS:
                self._button(surface, pygame.Rect(x, top, w, DATE_ROW_H), text,
                             enabled=self._step_enabled(which, sign))
            box = pygame.Rect(DATE_BOX[0], top, DATE_BOX[1], DATE_ROW_H)
            pygame.draw.rect(surface, (14, 19, 34), box, border_radius=8)
            pygame.draw.rect(surface, LINE, box, width=2, border_radius=8)
            d = shown[which]
            surf = self.font_val.render(d.strftime("%d/%m/%Y") if d else "—", True, WHITE)
            surface.blit(surf, surf.get_rect(center=box.center))

        # Résumé : bornes en toutes lettres + nombre de parties (filtre de mode inclus).
        if self.start is None:
            line1 = "Toutes les parties stockées"
        else:
            n = (self.end - self.start).days + 1
            line1 = (f"Du {period.long_date(self.start)} au {period.long_date(self.end)}"
                     f"  ·  {n} jour{'s' if n > 1 else ''}")
        surf = self.font_label.render(line1, True, WHITE)
        surface.blit(surf, surf.get_rect(center=(self.width // 2, SUMMARY_Y)))
        if self.data is not None:
            games = self.data["me_solo"]["games"] + self.data["duo_me"]["games"]
            line2 = (f"{games} partie{'s' if games > 1 else ''}"
                     f" ({STAT_FILTERS[self.filter_idx][0]})")
            surf = self.font_label.render(line2, True, GREY)
            surface.blit(surf, surf.get_rect(center=(self.width // 2, SUMMARY_Y + 34)))
        hint = self.font_sub.render(
            "La période s'applique à toutes les colonnes (toi, ami, ensemble).", True, DIM)
        surface.blit(hint, hint.get_rect(center=(self.width // 2, self.height - 24)))

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
