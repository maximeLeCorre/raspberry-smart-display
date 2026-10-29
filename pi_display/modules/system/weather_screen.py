"""Écran « Météo » (module système, code-drawn) : courbe de température d'un jour.

Ouvert en touchant la ligne météo de l'accueil. Lit l'historique horaire de
``weather.db`` (cf. weather.py) : marche PC éteint, et même hors ligne pour les
jours déjà stockés.

  - barre du haut : ◀ / jour (menu déroulant) / ▶ + RETOUR ;
  - résumé du jour : min/max, cumul de pluie (+ « maintenant » pour aujourd'hui) ;
  - graphique 0 h → 24 h : icônes toutes les 3 h, courbe de température
    (trait plein = relevé passé, pointillés = prévision), barres de pluie (mm),
    repère « maintenant ».

Le passé et la prévision se distinguent par le **style de trait** et une
légende écrite, pas seulement par la couleur (utilisateur daltonien).
"""

from __future__ import annotations

import math
import time

import pygame

from inputs import ACTION_BACK
from screen import Screen

from .default_screen import JOURS, MOIS, weather_icon
from .weather import get_weather, kind_of, label_of

RETOUR_RECT = pygame.Rect(690, 0, 110, 58)
PREV_RECT = pygame.Rect(170, 8, 48, 44)
DAY_RECT = pygame.Rect(226, 8, 330, 44)
NEXT_RECT = pygame.Rect(564, 8, 48, 44)

SUMMARY_Y = 84
CHART = pygame.Rect(12, 110, 776, 362)
ICON_Y = 134                    # centre de la rangée d'icônes
PLOT = pygame.Rect(58, 158, 690, 250)
RAIN_FRAC = 0.26                # bande du bas réservée à la pluie (part du tracé)
RAIN_SCALE_MM = 2.0             # barre pleine = au moins 2 mm/h

# Menu déroulant des jours.
DROP_ROW_H = 42
DROP_ROWS = 8
DROP = pygame.Rect(DAY_RECT.x, DAY_RECT.bottom + 4, DAY_RECT.w, DROP_ROWS * DROP_ROW_H + 52)

BG = (10, 14, 26)
PANEL = (16, 22, 38)
BTN = (30, 42, 68)
BTN_OFF = (18, 24, 38)
GRID = (34, 46, 74)
GOLD = (210, 175, 95)
WHITE = (238, 240, 245)
DIM = (150, 165, 195)
FAINT = (92, 106, 134)
TEMP = (240, 150, 80)
RAIN = (110, 170, 240)

JOURS_ABBR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS_ABBR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
             "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def day_bounds(day: str) -> tuple[int, int]:
    """« AAAA-MM-JJ » -> (minuit local, minuit suivant) en epoch (gère l'heure d'été)."""
    y, m, d = (int(x) for x in day.split("-"))
    start = int(time.mktime((y, m, d, 0, 0, 0, 0, 0, -1)))
    end = int(time.mktime((y, m, d + 1, 0, 0, 0, 0, 0, -1)))
    return start, end


def day_label(day: str, *, short: bool = False) -> str:
    """« Aujourd'hui », « Hier », « Demain », sinon « jeudi 29 octobre »."""
    now = time.localtime()
    for offset, word in ((0, "Aujourd'hui"), (-1, "Hier"), (1, "Demain")):
        t = time.localtime(time.mktime(
            (now.tm_year, now.tm_mon, now.tm_mday + offset, 12, 0, 0, 0, 0, -1)))
        if day == time.strftime("%Y-%m-%d", t):
            return word
    t = time.localtime(day_bounds(day)[0])
    if short:
        return f"{JOURS_ABBR[t.tm_wday]} {t.tm_mday} {MOIS_ABBR[t.tm_mon - 1]}"
    return f"{JOURS[t.tm_wday]} {t.tm_mday} {MOIS[t.tm_mon - 1]}"


def fmt_deg(v: float) -> str:
    return f"{v:.0f}°"


class WeatherScreen(Screen):
    name = "weather"
    background_name = None
    bg_color = BG
    cycle = False                   # accessible via l'accueil (clic sur la météo)

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 40)
        self.font_day = pygame.font.Font(None, 32)
        self.font = pygame.font.Font(None, 26)
        self.font_small = pygame.font.Font(None, 22)
        self.font_tiny = pygame.font.Font(None, 19)
        self.weather = get_weather(app)
        self.store = self.weather.store if self.weather else None
        self.city = str(app.config.get("weather", {}).get("city", "")).strip()
        self.days: list[tuple[str, float, float]] = []
        self.day: str | None = None
        self.drop_open = False
        self.drop_offset = 0
        self._drop_rows: list[tuple[pygame.Rect, str]] = []
        self._sig = None

    # ---------------------------------------------------------------- données
    def _reload_days(self) -> None:
        self.days = self.store.days() if self.store else []

    def _index(self) -> int:
        keys = [d[0] for d in self.days]
        return keys.index(self.day) if self.day in keys else -1

    def enter(self) -> None:
        self._reload_days()
        today = time.strftime("%Y-%m-%d")
        keys = [d[0] for d in self.days]
        self.day = today if today in keys else (keys[-1] if keys else None)
        self.drop_open = False
        self._sig = None

    # ---------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            if self.drop_open:
                self.drop_open = False
                self._sig = None
                return None
            return ACTION_BACK
        if self.drop_open:
            self._touch_dropdown(pos)
            return None
        i = self._index()
        if PREV_RECT.collidepoint(pos) and i > 0:
            self.day = self.days[i - 1][0]
        elif NEXT_RECT.collidepoint(pos) and 0 <= i < len(self.days) - 1:
            self.day = self.days[i + 1][0]
        elif DAY_RECT.collidepoint(pos) and self.days:
            self.drop_open = True
            # Page qui contient le jour affiché (liste du plus récent au plus ancien).
            rev = len(self.days) - 1 - max(i, 0)
            self.drop_offset = rev - rev % DROP_ROWS
        self._sig = None
        return None

    def _touch_dropdown(self, pos) -> None:
        self._sig = None
        if not DROP.collidepoint(pos):
            self.drop_open = False          # clic à côté = fermer
            return
        for rect, day in self._drop_rows:
            if rect.collidepoint(pos):
                self.day = day
                self.drop_open = False
                return
        up, down = self._drop_arrows()
        if up.collidepoint(pos) and self.drop_offset > 0:
            self.drop_offset -= DROP_ROWS
        elif down.collidepoint(pos) and self.drop_offset + DROP_ROWS < len(self.days):
            self.drop_offset += DROP_ROWS

    # ------------------------------------------------------------------ rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        version = self.store.version if self.store else 0
        # Le repère « maintenant » avance : redessin toutes les 5 min suffit.
        sig = (self.day, self.drop_open, self.drop_offset, version,
               int(time.time() // 300))
        if sig == self._sig:
            return []
        if self._sig is not None and self._sig[3] != version:
            self._reload_days()
        self._sig = sig

        surface.fill(BG)
        self._draw_top(surface)
        if self.day is None:
            msg = ("Météo désactivée." if self.weather is None
                   else "Collecte en cours… (premier relevé)")
            surf = self.font.render(msg, True, DIM)
            surface.blit(surf, surf.get_rect(center=(400, 260)))
        else:
            hours = self.store.hours(*day_bounds(self.day))
            self._draw_summary(surface, hours)
            self._draw_chart(surface, hours)
        if self.drop_open:
            self._draw_dropdown(surface)
        return [pygame.Rect(0, 0, self.width, self.height)]

    def _button(self, surface, rect, enabled: bool) -> None:
        pygame.draw.rect(surface, BTN if enabled else BTN_OFF, rect, border_radius=8)

    def _draw_top(self, surface) -> None:
        surface.blit(self.font_title.render("Météo", True, GOLD), (20, 10))
        if self.city:
            surface.blit(self.font_small.render(self.city, True, DIM), (20, 38))
        i = self._index()
        for rect, enabled, left in ((PREV_RECT, i > 0, True),
                                    (NEXT_RECT, 0 <= i < len(self.days) - 1, False)):
            self._button(surface, rect, enabled)
            cx, cy = rect.center
            pts = ([(cx - 8, cy), (cx + 6, cy - 10), (cx + 6, cy + 10)] if left
                   else [(cx + 8, cy), (cx - 6, cy - 10), (cx - 6, cy + 10)])
            pygame.draw.polygon(surface, GOLD if enabled else FAINT, pts)
        # Sélecteur de jour (menu déroulant) : libellé + chevron.
        self._button(surface, DAY_RECT, bool(self.days))
        pygame.draw.rect(surface, GOLD if self.drop_open else GRID, DAY_RECT, 2, border_radius=8)
        label = day_label(self.day) if self.day else "—"
        t = self.font_day.render(label, True, WHITE)
        surface.blit(t, t.get_rect(center=(DAY_RECT.centerx - 12, DAY_RECT.centery)))
        cx, cy = DAY_RECT.right - 22, DAY_RECT.centery
        pts = ([(cx - 7, cy + 4), (cx, cy - 4), (cx + 7, cy + 4)] if self.drop_open
               else [(cx - 7, cy - 4), (cx, cy + 4), (cx + 7, cy - 4)])
        pygame.draw.lines(surface, GOLD, False, pts, 3)
        # RETOUR (même style que France Info).
        pygame.draw.rect(surface, BTN, RETOUR_RECT, border_radius=8)
        r = self.font_small.render("RETOUR", True, (205, 210, 220))
        surface.blit(r, r.get_rect(center=RETOUR_RECT.center))
        pygame.draw.line(surface, GRID, (0, 60), (self.width, 60), 1)

    def _draw_summary(self, surface, hours) -> None:
        temps = [h.temp for h in hours if h.temp is not None]
        if not temps:
            return
        parts = [(f"min {fmt_deg(min(temps))}  ·  max {fmt_deg(max(temps))}", WHITE)]
        rain = sum(h.precip or 0 for h in hours)
        parts.append((f"  ·  pluie {rain:.1f} mm".replace(".", ",") if rain >= 0.1
                      else "  ·  pas de pluie", RAIN if rain >= 0.1 else DIM))
        if self.day == time.strftime("%Y-%m-%d") and self.weather:
            w = self.weather.current()
            if w is not None:
                parts.append((f"  ·  maintenant {fmt_deg(w.temp)}, {w.label.lower()}", DIM))
        x = 20
        for text, color in parts:
            s = self.font.render(text, True, color)
            surface.blit(s, (x, SUMMARY_Y - s.get_height() // 2))
            x += s.get_width()

    def _draw_chart(self, surface, hours) -> None:
        pygame.draw.rect(surface, PANEL, CHART, border_radius=10)
        start, end = day_bounds(self.day)
        span = end - start

        def px(ts: float) -> float:
            return PLOT.x + (ts - start) / span * PLOT.w

        pts = [h for h in hours if h.temp is not None]
        if not pts:
            return
        lo, hi = min(h.temp for h in pts), max(h.temp for h in pts)
        step = 2 if hi - lo <= 12 else 5
        y_lo = math.floor((lo - 1) / step) * step
        y_hi = math.ceil((hi + 1) / step) * step
        # Température en haut, pluie dans sa propre bande en bas (pas de chevauchement).
        rain_h = round(PLOT.h * RAIN_FRAC)
        temp_area = pygame.Rect(PLOT.x, PLOT.y, PLOT.w, PLOT.h - rain_h - 10)

        def py(v: float) -> float:
            return temp_area.bottom - (v - y_lo) / (y_hi - y_lo) * temp_area.h

        # Grille horizontale (°C) + verticale (toutes les 3 h).
        v = y_lo
        while v <= y_hi:
            y = round(py(v))
            pygame.draw.line(surface, GRID, (PLOT.x, y), (PLOT.right, y))
            lab = self.font_tiny.render(fmt_deg(v), True, DIM)
            surface.blit(lab, (PLOT.x - lab.get_width() - 8, y - lab.get_height() // 2))
            v += step
        for h in range(0, 25, 3):
            x = round(PLOT.x + h / 24 * PLOT.w)
            pygame.draw.line(surface, GRID, (x, PLOT.y), (x, PLOT.bottom))
            lab = self.font_tiny.render(f"{h} h", True, DIM)
            surface.blit(lab, (x - lab.get_width() // 2, PLOT.bottom + 6))

        # Barres de pluie (mm/h) en bas du tracé, avec la valeur si notable.
        bar_w = max(4, PLOT.w / 24 - 6)
        for h in hours:
            if not h.precip or h.precip < 0.1:
                continue
            frac = min(1.0, h.precip / max(RAIN_SCALE_MM, 0.1))
            bh = max(3, round(frac * (rain_h - 16)))
            x = px(h.ts + 1800) - bar_w / 2
            pygame.draw.rect(surface, RAIN, (round(x), PLOT.bottom - bh, round(bar_w), bh),
                             border_radius=2)
            if h.precip >= 0.5:
                lab = self.font_tiny.render(f"{h.precip:.1f}".replace(".", ","), True, RAIN)
                surface.blit(lab, (round(x + bar_w / 2 - lab.get_width() / 2),
                                   PLOT.bottom - bh - lab.get_height()))

        # Icônes du temps toutes les 3 h (heure centrale de chaque tranche).
        by_hour = {time.localtime(h.ts).tm_hour: h for h in hours}
        for hh in range(1, 24, 3):
            h = by_hour.get(hh)
            if h is None:
                continue
            icon = weather_icon(kind_of(h.code), h.is_day, 26)
            surface.blit(icon, (round(px(h.ts + 1800)) - 13, ICON_Y - 13))

        # Courbe : passé en trait plein (+ aire), futur en pointillés.
        now = time.time()
        coords = [(px(h.ts + 1800), py(h.temp), h.ts + 1800 <= now) for h in pts]
        past = [(x, y) for x, y, p in coords if p]
        future = [(x, y) for x, y, p in coords if not p]
        if past and future:
            future.insert(0, past[-1])      # raccord sans trou
        if len(past) >= 2:
            overlay = pygame.Surface(PLOT.size, pygame.SRCALPHA)
            poly = [(x - PLOT.x, y - PLOT.y) for x, y in past]
            poly += [(poly[-1][0], temp_area.h), (poly[0][0], temp_area.h)]
            pygame.draw.polygon(overlay, (*TEMP, 50), poly)
            surface.blit(overlay, PLOT.topleft)
            pygame.draw.lines(surface, TEMP, False, past, 3)
        if len(future) >= 2:
            self._dashed(surface, TEMP, future, 2)

        # Repère « maintenant » (jour courant seulement).
        if start <= now < end:
            x = round(px(now))
            for y in range(PLOT.y, PLOT.bottom, 8):
                pygame.draw.line(surface, WHITE, (x, y), (x, min(y + 4, PLOT.bottom)))
            lab = self.font_tiny.render("maintenant", True, WHITE)
            lx = min(max(x - lab.get_width() // 2, PLOT.x), PLOT.right - lab.get_width())
            surface.blit(lab, (lx, PLOT.y - lab.get_height() - 1))

        # Min / max annotés sur la courbe.
        hmax = max(pts, key=lambda h: h.temp)
        hmin = min(pts, key=lambda h: h.temp)
        for h, above in ((hmax, True), (hmin, False)):
            x, y = px(h.ts + 1800), py(h.temp)
            pygame.draw.circle(surface, WHITE, (round(x), round(y)), 4)
            lab = self.font_small.render(fmt_deg(h.temp), True, WHITE)
            ly = y - lab.get_height() - 6 if above else y + 6
            lx = min(max(x - lab.get_width() / 2, PLOT.x), PLOT.right - lab.get_width())
            surface.blit(lab, (round(lx), round(ly)))

        # Légende écrite (styles, pas seulement couleurs).
        lx, ly = CHART.x + 14, CHART.bottom - 22
        pygame.draw.line(surface, TEMP, (lx, ly + 7), (lx + 24, ly + 7), 3)
        lx = self._legend(surface, lx + 30, ly, "relevé")
        self._dashed(surface, TEMP, [(lx + 18, ly + 7), (lx + 42, ly + 7)], 2)
        lx = self._legend(surface, lx + 48, ly, "prévision")
        pygame.draw.rect(surface, RAIN, (lx + 18, ly + 1, 10, 12), border_radius=2)
        lx = self._legend(surface, lx + 34, ly, "pluie (mm/h)")
        conditions = label_of(max((h.code for h in hours if h.code is not None), default=None))
        cond = self.font_tiny.render(f"temps le plus marqué : {conditions.lower()}", True, DIM)
        surface.blit(cond, (CHART.right - cond.get_width() - 14, ly))

    def _legend(self, surface, x, y, text) -> int:
        s = self.font_tiny.render(text, True, DIM)
        surface.blit(s, (x, y))
        return x + s.get_width()

    @staticmethod
    def _dashed(surface, color, points, width, dash=8, gap=6) -> None:
        """Polyligne en pointillés (longueur de tiret constante le long du tracé)."""
        on, left = True, dash
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            seg = math.hypot(x1 - x0, y1 - y0)
            pos = 0.0
            while pos < seg:
                step = min(left, seg - pos)
                if on:
                    a, b = pos / seg, (pos + step) / seg
                    pygame.draw.line(surface, color,
                                     (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                                     (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), width)
                pos += step
                left -= step
                if left <= 0:
                    on = not on
                    left = dash if on else gap

    # --------------------------------------------------------- menu déroulant
    def _drop_arrows(self) -> tuple[pygame.Rect, pygame.Rect]:
        y = DROP.bottom - 46
        half = (DROP.w - 24) // 2
        return (pygame.Rect(DROP.x + 8, y, half, 38),
                pygame.Rect(DROP.x + 16 + half, y, half, 38))

    def _draw_dropdown(self, surface) -> None:
        # Voile sur le graphique pour détacher le menu.
        veil = pygame.Surface((self.width, self.height - 61), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 120))
        surface.blit(veil, (0, 61))
        pygame.draw.rect(surface, PANEL, DROP, border_radius=10)
        pygame.draw.rect(surface, GOLD, DROP, 2, border_radius=10)
        newest_first = list(reversed(self.days))
        window = newest_first[self.drop_offset:self.drop_offset + DROP_ROWS]
        self._drop_rows = []
        for k, (day, t_min, t_max) in enumerate(window):
            row = pygame.Rect(DROP.x + 8, DROP.y + 6 + k * DROP_ROW_H, DROP.w - 16,
                              DROP_ROW_H - 4)
            selected = day == self.day
            pygame.draw.rect(surface, BTN if selected else BTN_OFF, row, border_radius=6)
            if selected:
                pygame.draw.rect(surface, GOLD, row, 2, border_radius=6)
            name = self.font.render(day_label(day, short=True), True,
                                    GOLD if selected else WHITE)
            surface.blit(name, (row.x + 12, row.centery - name.get_height() // 2))
            rng = self.font_small.render(f"{fmt_deg(t_min)} / {fmt_deg(t_max)}", True, DIM)
            surface.blit(rng, (row.right - rng.get_width() - 12,
                               row.centery - rng.get_height() // 2))
            self._drop_rows.append((row, day))
        up, down = self._drop_arrows()
        for rect, label, enabled in (
                (up, "plus récents", self.drop_offset > 0),
                (down, "plus anciens", self.drop_offset + DROP_ROWS < len(self.days))):
            self._button(surface, rect, enabled)
            s = self.font_small.render(label, True, GOLD if enabled else FAINT)
            surface.blit(s, s.get_rect(center=rect.center))
