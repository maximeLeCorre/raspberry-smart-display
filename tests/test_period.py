"""Période des stats : bornes de dates, filtre SQL, sélecteur de l'écran Stats."""

from __future__ import annotations

from datetime import date

from modules.league import period
from store import Store
from test_app_routing import app  # noqa: F401  (fixture)
from test_compare import ME, MATE, player, rec

TODAY = date(2026, 10, 30)


def test_prereglages_et_libelles():
    assert period.preset(7, TODAY) == (date(2026, 10, 24), TODAY)
    assert period.preset(None, TODAY) == (None, None)
    assert period.short_label(date(2026, 10, 24), TODAY, TODAY) == "7 derniers jours"
    assert period.short_label(TODAY, TODAY, TODAY) == "Aujourd'hui"
    assert period.short_label(date(2026, 9, 1), date(2026, 9, 30), TODAY) == "01/09 – 30/09"
    assert period.short_label(None, None, TODAY) == "Toutes dates"


def test_mois_ramene_en_fin_de_mois():
    assert period.add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert period.add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)


def test_fin_incluse_dans_le_filtre_sql(tmp_path):
    st = Store(tmp_path / "m.db")
    day = period.day_ms
    games = [rec(1, [player(ME, 100, True, self_=True)], creation=day(date(2026, 10, 9)) + 1),
             rec(2, [player(ME, 100, True, self_=True)], creation=day(date(2026, 10, 10))),
             rec(3, [player(ME, 100, True, self_=True)], creation=day(date(2026, 10, 11)) - 1),
             rec(4, [player(ME, 100, True, self_=True)], creation=day(date(2026, 10, 11)))]
    st.upsert_matches(games)
    where, params = period.where(date(2026, 10, 10), date(2026, 10, 10))
    assert st.compare(ME, MATE, where, params)["me_solo"]["games"] == 2      # 2 et 3
    assert st.compare(ME, MATE, *period.where(None, None))["me_solo"]["games"] == 4
    assert st.oldest_creation() == day(date(2026, 10, 9)) + 1


def test_selecteur_de_l_ecran_stats(app):
    stats = app.screens["stats"]
    app.compare_rid, app.summoner_rid = MATE, ME
    stats._today = lambda: TODAY
    app.open_stats()
    stats.handle_touch(stats._period_rect.center)
    assert stats._picking
    stats.handle_touch(stats._preset_rects[0].center)              # 7 derniers jours
    assert (stats.start, stats.end) == (date(2026, 10, 24), TODAY)
    assert not stats._step_enabled("Au", 1)                        # pas après aujourd'hui
    stats._step("Du", "d", 10)                                     # début ramené à la fin
    assert stats.start == TODAY
    stats._step("Au", "m", -1)                                     # fin jamais avant le début
    assert stats.end == TODAY
    stats.handle_touch((740, 27))                                  # OK
    assert not stats._picking
