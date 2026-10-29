"""Météo locale (Open-Meteo) : relevé courant (accueil) + historique horaire.

Le Pi interroge lui-même Open-Meteo (gratuit, **sans clé**) : l'accueil affiche
la météo même PC éteint. Même schéma que ``rss_feed`` : un thread de fond
rafraîchit périodiquement ; l'écran lit le dernier relevé (thread-safe).
Tolérant : en cas d'erreur réseau/parse, conserve le dernier relevé connu.

Historique (écran ``weather``) : chaque relevé renvoie aussi la série **horaire**
(hier → demain), upsertée dans ``weather.db`` (SQLite, 1 ligne/heure). Les heures
passées sont donc complètes même si le Pi était éteint, et les heures futures
sont la prévision (écrasée au fil des relevés). Base vide → rattrapage de
``BACKFILL_DAYS`` jours (max Open-Meteo). ⚠️ Jamais déployée (deploy exclut *.db).

Partagé via ``get_weather(app)`` : une seule instance par application.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_URL = "https://api.open-meteo.com/v1/forecast"
_USER_AGENT = "PiDisplay/1.0 (+raspberry-smart-display)"
DB_PATH = Path(__file__).resolve().parents[2] / "weather.db"
BACKFILL_DAYS = 92        # rattrapage si la base est vide (max autorisé par l'API)
REFRESH_PAST_DAYS = 1     # relevés suivants : hier + aujourd'hui suffisent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly (
    ts        INTEGER PRIMARY KEY,   -- début de l'heure (epoch, s)
    temp      REAL,                  -- °C
    code      INTEGER,               -- code WMO
    precip    REAL,                  -- mm sur l'heure
    rain_prob INTEGER,               -- % (prévision)
    is_day    INTEGER
);
"""

# Codes météo WMO -> (catégorie d'icône, libellé français).
# Catégories : clear, partly, cloudy, fog, rain, snow, storm.
_WMO: dict[int, tuple[str, str]] = {
    0: ("clear", "Ensoleillé"),
    1: ("clear", "Plutôt dégagé"),
    2: ("partly", "Éclaircies"),
    3: ("cloudy", "Couvert"),
    45: ("fog", "Brouillard"),
    48: ("fog", "Brouillard givrant"),
    51: ("rain", "Bruine légère"),
    53: ("rain", "Bruine"),
    55: ("rain", "Bruine forte"),
    56: ("rain", "Bruine verglaçante"),
    57: ("rain", "Bruine verglaçante"),
    61: ("rain", "Pluie faible"),
    63: ("rain", "Pluie"),
    65: ("rain", "Pluie forte"),
    66: ("rain", "Pluie verglaçante"),
    67: ("rain", "Pluie verglaçante"),
    71: ("snow", "Neige faible"),
    73: ("snow", "Neige"),
    75: ("snow", "Neige forte"),
    77: ("snow", "Grésil"),
    80: ("rain", "Averses"),
    81: ("rain", "Averses"),
    82: ("rain", "Fortes averses"),
    85: ("snow", "Averses de neige"),
    86: ("snow", "Averses de neige"),
    95: ("storm", "Orage"),
    96: ("storm", "Orage et grêle"),
    99: ("storm", "Orage et grêle"),
}


@dataclass(frozen=True)
class Weather:
    temp: float          # °C actuelle
    kind: str            # catégorie d'icône (cf. _WMO)
    label: str           # libellé français
    is_day: bool
    t_min: float | None  # min/max du jour
    t_max: float | None
    rain_pct: int | None  # probabilité max de pluie du jour (%)


def kind_of(code) -> str:
    """Catégorie d'icône d'un code WMO (« cloudy » si inconnu)."""
    return _WMO.get(int(code), ("cloudy", ""))[0] if code is not None else "cloudy"


def label_of(code) -> str:
    return _WMO.get(int(code), ("", "—"))[1] if code is not None else "—"


@dataclass(frozen=True)
class Hour:
    ts: int
    temp: float | None
    code: int | None
    precip: float | None
    rain_prob: int | None
    is_day: bool


def parse_hourly(data: dict) -> list[tuple]:
    """Série ``hourly`` (timeformat=unixtime) -> lignes (ts, temp, code, precip, prob, jour)."""
    h = data.get("hourly") or {}
    times = h.get("time") or []

    def col(key):
        vals = h.get(key) or []
        return [vals[i] if i < len(vals) else None for i in range(len(times))]

    temps, codes = col("temperature_2m"), col("weather_code")
    precs, probs, days = col("precipitation"), col("precipitation_probability"), col("is_day")
    return [(int(t), temps[i], codes[i], precs[i], probs[i],
             1 if days[i] in (None, 1) else 0)
            for i, t in enumerate(times) if temps[i] is not None]


class WeatherStore:
    """Historique horaire en SQLite (écrit par le thread météo, lu par l'écran)."""

    def __init__(self, path: Path | str = DB_PATH):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self.version = 0      # incrémenté à chaque écriture (l'écran redessine)

    def is_empty(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM hourly LIMIT 1").fetchone() is None

    def upsert(self, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO hourly VALUES (?,?,?,?,?,?)", rows)
            self._db.commit()
            self.version += 1

    def hours(self, start: int, end: int) -> list[Hour]:
        """Heures dans [start, end[ (epoch), par ordre chronologique."""
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, temp, code, precip, rain_prob, is_day FROM hourly "
                "WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)).fetchall()
        return [Hour(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in rows]

    def days(self) -> list[tuple[str, float, float]]:
        """[(« AAAA-MM-JJ » local, min, max)] du plus ancien au plus récent."""
        with self._lock:
            return self._db.execute(
                "SELECT date(ts, 'unixepoch', 'localtime') AS d, MIN(temp), MAX(temp) "
                "FROM hourly GROUP BY d ORDER BY d").fetchall()


def parse_weather(data: dict) -> Weather:
    """Réponse JSON Open-Meteo -> Weather (lève si ``current`` est absent)."""
    cur = data["current"]
    kind, label = _WMO.get(int(cur["weather_code"]), ("cloudy", "—"))
    daily = data.get("daily") or {}

    # Avec past_days, « daily » commence dans le passé : on prend le jour de
    # « current » (dernière date <= maintenant ; 1re entrée si dates absentes).
    idx = 0
    now = cur.get("time")
    for i, t in enumerate(daily.get("time") or []):
        if isinstance(t, (int, float)) and isinstance(now, (int, float)) and t <= now:
            idx = i

    def first(key):
        vals = daily.get(key) or []
        return vals[idx] if idx < len(vals) and vals[idx] is not None else None

    rain = first("precipitation_probability_max")
    return Weather(
        temp=float(cur["temperature_2m"]),
        kind=kind,
        label=label,
        is_day=bool(cur.get("is_day", 1)),
        t_min=first("temperature_2m_min"),
        t_max=first("temperature_2m_max"),
        rain_pct=int(rain) if rain is not None else None,
    )


class WeatherFeed:
    """Relève la météo d'un point (lat/lon) en arrière-plan."""

    def __init__(self, latitude: float, longitude: float, *,
                 refresh_interval: float = 900.0, timeout: float = 20.0,
                 store: WeatherStore | None = None):
        self.params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "hourly": "temperature_2m,weather_code,precipitation,"
                      "precipitation_probability,is_day",
            "timezone": "auto",
            "timeformat": "unixtime",
            "forecast_days": 2,
        }
        self.store = store
        self.refresh_interval = max(300.0, refresh_interval)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._current: Weather | None = None
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def current(self) -> Weather | None:
        with self._lock:
            return self._current

    # ----------------------------------------------------------------- interne
    def _loop(self) -> None:
        while True:
            w = self._fetch()
            if w is not None:  # garde l'ancien relevé si le fetch échoue
                with self._lock:
                    self._current = w
            # Réessai rapide tant qu'on n'a rien (ex. Wi-Fi pas encore prêt au boot).
            time.sleep(self.refresh_interval if self._current else 60)

    def _fetch(self) -> Weather | None:
        try:
            params = dict(self.params)
            if self.store is not None:
                params["past_days"] = (BACKFILL_DAYS if self.store.is_empty()
                                       else REFRESH_PAST_DAYS)
            url = f"{_URL}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
            if self.store is not None:
                self.store.upsert(parse_hourly(data))
            return parse_weather(data)
        except Exception as exc:  # réseau, parse, etc. : on ne casse jamais l'UI
            print(f"[météo] échec du relevé : {exc}")
            return None


def get_weather(app):
    """Instance unique de la météo pour l'app (config ``[weather]``).

    Renvoie None si désactivée (``enabled = false``) ou sans coordonnées.
    """
    if not hasattr(app, "_weather_feed"):
        cfg = app.config.get("weather", {})
        feed = None
        if cfg.get("enabled", True) and "latitude" in cfg and "longitude" in cfg:
            feed = WeatherFeed(
                float(cfg["latitude"]), float(cfg["longitude"]),
                refresh_interval=float(cfg.get("refresh_minutes", 15)) * 60,
                store=WeatherStore(),
            )
            feed.start()
        app._weather_feed = feed
    return app._weather_feed
