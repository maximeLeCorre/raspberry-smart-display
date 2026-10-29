"""Accueil : parse de la météo Open-Meteo et seuils d'alerte de santé du Pi."""

from __future__ import annotations

from modules.system.pi_health import PiHealth
from modules.system.weather import parse_weather


def test_parse_weather_open_meteo():
    w = parse_weather({
        "current": {"temperature_2m": 9.4, "weather_code": 61, "is_day": 0},
        "daily": {"temperature_2m_min": [5.7], "temperature_2m_max": [14.3],
                  "precipitation_probability_max": [40]},
    })
    assert (w.temp, w.kind, w.label, w.is_day) == (9.4, "rain", "Pluie faible", False)
    assert (w.t_min, w.t_max, w.rain_pct) == (5.7, 14.3, 40)


def test_parse_weather_sans_journalier_ni_code_connu():
    w = parse_weather({"current": {"temperature_2m": 1, "weather_code": 42}})
    assert w.kind == "cloudy" and w.t_min is None and w.rain_pct is None


def _health():
    return PiHealth(thresholds={"cpu": 90, "ram": 90, "disk": 90, "temp": 75},
                    cpu_sustain=3)


def test_alertes_au_dessus_des_seuils_seulement():
    h = _health()
    h.update({"cpu": 10, "ram": 95, "disk": 50, "temp": None})
    assert h.alerts() == [("ram", 95)]


def test_pic_cpu_isole_ne_declenche_pas_d_alerte():
    h = _health()
    for _ in range(2):
        h.update({"cpu": 99, "ram": 10, "disk": 10, "temp": 40})
    assert h.alerts() == []
    h.update({"cpu": 99, "ram": 10, "disk": 10, "temp": 40})
    assert h.alerts() == [("cpu", 99)]
    h.update({"cpu": 20, "ram": 10, "disk": 10, "temp": 40})
    assert h.alerts() == []


# ------------------------------------------------------------- historique météo
from modules.system.weather import WeatherStore, parse_hourly  # noqa: E402
from modules.system.weather_screen import day_bounds  # noqa: E402


def test_daily_du_jour_meme_avec_past_days():
    """Avec past_days, daily[0] est un jour passé : il faut celui de « current »."""
    w = parse_weather({
        "current": {"time": 1_000_500, "temperature_2m": 9, "weather_code": 0},
        "daily": {"time": [900_000, 1_000_000, 1_090_000],
                  "temperature_2m_min": [1, 5, 7], "temperature_2m_max": [2, 14, 9]},
    })
    assert (w.t_min, w.t_max) == (5, 14)


def test_parse_hourly_ignore_les_heures_sans_temperature():
    rows = parse_hourly({"hourly": {
        "time": [3600, 7200], "temperature_2m": [4.5, None], "weather_code": [61, 0],
        "precipitation": [0.8, 0], "precipitation_probability": [70, 0], "is_day": [0, 1]}})
    assert rows == [(3600, 4.5, 61, 0.8, 70, 0)]


def test_store_upsert_remplace_la_prevision_et_regroupe_par_jour(tmp_path):
    store = WeatherStore(tmp_path / "w.db")
    assert store.is_empty()
    start, end = day_bounds("2026-10-24")
    store.upsert([(start + 3600 * h, 10.0 + h, 3, 0.0, 0, 1) for h in range(3)])
    v = store.version
    store.upsert([(start + 3600, 2.0, 61, 1.5, 90, 1)])      # nouvelle valeur, même heure
    assert store.version == v + 1
    hours = store.hours(start, end)
    assert [h.temp for h in hours] == [10.0, 2.0, 12.0] and hours[1].precip == 1.5
    assert store.days() == [("2026-10-24", 2.0, 12.0)]


def test_day_bounds_couvre_une_journee_locale():
    start, end = day_bounds("2026-10-25")          # passage à l'heure d'hiver (Paris)
    assert 23 * 3600 <= end - start <= 25 * 3600
    assert day_bounds("2026-10-26")[0] == end
