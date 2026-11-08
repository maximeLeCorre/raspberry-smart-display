"""Module « trains » : prochains départs d'une gare + info trafic (API PRIM d'IDFM).
Le Pi interroge l'API lui-même (marche PC éteint). Activable en config
([modules] transit), paramétré par [transit] ; clé IDFM_API_KEY dans le .env.
Pi-only : pas de moitié `sources/` côté agent.
"""

import json
import sqlite3
import threading
from pathlib import Path

from modules.base import Module
from modules.transit.transit_screen import TransitScreen, short_destination

MAX_REMOTE = 16      # départs envoyés à la montre (complication : ~1 h d'avance)
# Domicile saisi sur la montre (trajet retour) : *.db = hors Git et hors déploiement.
SETTINGS_DB = Path(__file__).resolve().parents[2] / "settings.db"


class TransitModule(Module):
    name = "transit"
    screens = [TransitScreen]

    def __init__(self, app):
        super().__init__(app)
        self._lock = threading.Lock()
        self._db = None

    def _store(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(str(SETTINGS_DB), check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        return self._db

    def home(self) -> dict | None:
        with self._lock:
            row = self._store().execute("SELECT value FROM settings WHERE key='home'").fetchone()
        return json.loads(row[0]) if row else None

    def remote_setting(self, name: str, body: dict) -> bool:
        """`home` {lat, lon, label} : domicile saisi (adresse) sur la montre."""
        if name != "home":
            return False
        try:
            lat, lon = float(body["lat"]), float(body["lon"])
        except (KeyError, TypeError, ValueError):
            return False
        label = body.get("label")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not isinstance(label, str) or len(label) > 200:
            return False
        value = json.dumps({"lat": lat, "lon": lon, "label": label}, ensure_ascii=False)
        with self._lock:
            db = self._store()
            db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('home', ?)", (value,))
            db.commit()
        return True

    def remote_asset(self, name: str) -> tuple[bytes, str] | None:
        """`next` : prochains départs pour la complication de la montre (JSON), + `trip`
        (clé IDFM et domicile) que la montre garde pour le trajet retour hors Wi-Fi.
        Thread HTTP : seulement le `snapshot()` verrouillé du flux (créé avec l'écran)."""
        feed = getattr(self.app, "_transit_feed", None)
        if name != "next" or feed is None:
            return None
        snap = feed.snapshot()
        cfg = self.app.config.get("transit", {})
        home = str(cfg.get("home_destination", "")).lower()     # comme l'accueil du Pi
        board = {
            "station": str(cfg.get("station", "")),
            "homeLabel": str(cfg.get("home_label", "")),
            "updated": snap["updated"],
            "departures": [{"line": d.line, "destination": short_destination(d.destination),
                            "time": d.when, "arrival": d.arrival, "delay": d.delay_min,
                            "cancelled": d.cancelled, "platform": d.platform, "toParis": d.to_paris,
                            "home": bool(home) and home in d.destination.lower()}
                           for d in snap["departures"][:MAX_REMOTE]],
            "trip": {"key": feed.api_key, "home": self.home()},
        }
        return json.dumps(board, ensure_ascii=False).encode(), "application/json"
