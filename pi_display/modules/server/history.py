"""Historique de la supervision, gardé sur le Pi (`monitor.db`, SQLite, hors Git/deploy).

- `canary` : frise des 24 h du verdict des trajets témoins Rentrer, en segments
  (début, fin, état) prolongés à chaque relevé ; un trou = Pi éteint ou sonde muette.
- `push_hours` : envois du serveur de push NexusLink par heure. Le serveur ne donne que des
  compteurs depuis son démarrage (`/v1/stats`) : on garde le dernier relevé (`meta`) et on
  ajoute la différence à l'heure courante ; redémarrage (`started` change) = compteurs
  repartis de zéro, la valeur entière compte.
Deux jours gardés. Accès depuis le thread principal seulement (tick du module).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "monitor.db"
KEEP_SECONDS = 2 * 86400
PUSH_FIELDS = ("pushed", "delivered", "refused", "failed", "limited")


class MonitorHistory:
    def __init__(self, path: Path | str = DB_PATH):
        self.db = sqlite3.connect(str(path))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS canary (start REAL NOT NULL, end REAL NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS push_hours (
                hour INTEGER PRIMARY KEY, pushed INTEGER NOT NULL DEFAULT 0,
                delivered INTEGER NOT NULL DEFAULT 0, refused INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0, limited INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
        """)

    # ------------------------------------------------------------- trajets témoins
    def record_canary(self, state: str, now: float, max_gap: float = 180) -> None:
        """Prolonge le dernier segment s'il a le même état et pas de trou, sinon en ouvre un."""
        row = self.db.execute("SELECT rowid, end, state FROM canary ORDER BY start DESC LIMIT 1").fetchone()
        if row and row[2] == state and now - row[1] <= max_gap:
            self.db.execute("UPDATE canary SET end = ? WHERE rowid = ?", (now, row[0]))
        else:
            start = row[1] if row and now - row[1] <= max_gap else now
            self.db.execute("INSERT INTO canary (start, end, state) VALUES (?, ?, ?)", (start, now, state))
        self.db.execute("DELETE FROM canary WHERE end < ?", (now - KEEP_SECONDS,))
        self.db.commit()

    def canary_segments(self, since: float) -> list[tuple[float, float, str]]:
        return [tuple(r) for r in self.db.execute(
            "SELECT max(start, ?), end, state FROM canary WHERE end >= ? ORDER BY start", (since, since))]

    # ------------------------------------------------------------- push NexusLink
    def record_push(self, stats: dict, now: float) -> None:
        cur = {f: int(stats.get(f) or 0) for f in PUSH_FIELDS}
        started = int(stats.get("started") or 0)
        row = self.db.execute("SELECT v FROM meta WHERE k = 'push_last'").fetchone()
        last = json.loads(row[0]) if row else None
        if last is None:
            delta = None                                  # 1er relevé : base, rien à compter
        elif last.get("started") != started:
            delta = cur                                   # redémarré : tout est neuf
        else:
            delta = {f: max(0, cur[f] - int(last.get(f, 0))) for f in PUSH_FIELDS}
        if delta and any(delta.values()):
            hour = int(now // 3600)
            self.db.execute("INSERT OR IGNORE INTO push_hours (hour) VALUES (?)", (hour,))
            self.db.execute(
                "UPDATE push_hours SET " + ", ".join(f"{f} = {f} + ?" for f in PUSH_FIELDS)
                + " WHERE hour = ?", (*[delta[f] for f in PUSH_FIELDS], hour))
        self.db.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('push_last', ?)",
                        (json.dumps({"started": started, **cur}),))
        self.db.execute("DELETE FROM push_hours WHERE hour < ?", (int((now - KEEP_SECONDS) // 3600),))
        self.db.commit()

    def push_hours(self, now: float, hours: int = 24) -> list[dict]:
        """`hours` cases (la plus ancienne d'abord, la dernière = heure en cours)."""
        end = int(now // 3600)
        rows = {r[0]: dict(zip(PUSH_FIELDS, r[1:])) for r in self.db.execute(
            "SELECT hour, " + ", ".join(PUSH_FIELDS) + " FROM push_hours WHERE hour > ?",
            (end - hours,))}
        return [{"hour": h, **rows.get(h, dict.fromkeys(PUSH_FIELDS, 0))}
                for h in range(end - hours + 1, end + 1)]

    def close(self) -> None:
        self.db.close()
