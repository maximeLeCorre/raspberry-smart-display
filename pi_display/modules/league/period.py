"""Fenêtre de dates des stats (écran Stats) : bornes, clause SQL, libellés.

Une période = (début, fin) en `date` locales, **incluses** ; (None, None) =
toutes les dates. Le store filtre sur `game_creation` (epoch en ms, LCU).
Sans pygame : testable seul.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

# Préréglages du sélecteur : (libellé, nb de jours jusqu'à aujourd'hui inclus ; None = tout).
PRESETS = [("7 derniers jours", 7), ("30 derniers jours", 30),
           ("90 derniers jours", 90), ("Toutes dates", None)]

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def preset(days: int | None, today: date) -> tuple[date | None, date | None]:
    if days is None:
        return None, None
    return today - timedelta(days=days - 1), today


def add_months(d: date, n: int) -> date:
    """d décalée de n mois (jour ramené à la fin du mois si besoin : 31/03 - 1 → 28/02)."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def day_ms(d: date) -> int:
    """Minuit local du jour `d`, en ms (unité de `game_creation`)."""
    return int(datetime.combine(d, time.min).timestamp() * 1000)


def where(start: date | None, end: date | None) -> tuple[str, tuple]:
    """Clause SQL [début 0 h ; lendemain de la fin 0 h[ ; borne None = ouverte."""
    parts, params = [], []
    if start is not None:
        parts.append("game_creation >= ?")
        params.append(day_ms(start))
    if end is not None:
        parts.append("game_creation < ?")
        params.append(day_ms(end + timedelta(days=1)))
    return " AND ".join(parts), tuple(params)


def short_label(start: date | None, end: date | None, today: date) -> str:
    """Libellé court (bouton de l'écran Stats)."""
    if start is None or end is None:
        return "Toutes dates"
    if end == today:
        n = (end - start).days + 1
        return "Aujourd'hui" if n == 1 else f"{n} derniers jours"
    fmt = "%d/%m" if start.year == end.year == today.year else "%d/%m/%y"
    return f"{start.strftime(fmt)} – {end.strftime(fmt)}"


def long_date(d: date) -> str:
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"
