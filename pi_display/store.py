"""Stockage local des parties sur le Pi (SQLite).

But : garder l'historique **consultable PC éteint**. Toutes les parties viennent
de la LCU (via l'agent) et sont stockées ici ; l'écran historique lit cette base
(local, instantané, hors-ligne). Le détail complet (10 joueurs) est conservé en
JSON pour afficher le bilan sans re-fetch.

Thread-safe (un verrou) car les écritures arrivent depuis la boucle réseau et les
lectures depuis la boucle de rendu.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "matches.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    game_id       TEXT PRIMARY KEY,
    game_creation INTEGER,
    game_mode     TEXT,
    queue_id      INTEGER,
    queue_label   TEXT,
    duration      INTEGER,
    win           INTEGER,
    champion_id   INTEGER,
    champion_name TEXT,
    kills         INTEGER,
    deaths        INTEGER,
    assists       INTEGER,
    cs            INTEGER,
    detail_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_creation ON matches(game_creation DESC);
CREATE INDEX IF NOT EXISTS idx_mode ON matches(game_mode);
CREATE INDEX IF NOT EXISTS idx_queue ON matches(queue_id);
"""


def _when(ms) -> str:
    try:
        return time.strftime("%d/%m %H:%M", time.localtime((ms or 0) / 1000))
    except (TypeError, ValueError, OSError):
        return ""


class Store:
    def __init__(self, path: Path = DB_PATH):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------ écriture
    def upsert_matches(self, records: list[dict]) -> int:
        """Insère des parties (ignore les doublons par game_id). Renvoie le
        nombre de nouvelles lignes."""
        new = 0
        with self._lock:
            for r in records:
                kda = r.get("kda") or [0, 0, 0]
                detail = r.get("detail")
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(r.get("gameId")), r.get("gameCreation", 0) or 0,
                     r.get("gameMode", "") or "", r.get("queueId", 0) or 0,
                     r.get("queue", "") or "", r.get("duration", 0) or 0,
                     1 if r.get("win") else 0, r.get("championId", 0) or 0,
                     r.get("championName", "") or "",
                     kda[0], kda[1], kda[2], r.get("cs", 0) or 0,
                     json.dumps(detail, ensure_ascii=False) if detail else ""))
                new += cur.rowcount
            self._conn.commit()
        return new

    def set_detail(self, game_id, detail: dict) -> None:
        """Mémorise le bilan complet d'une partie (récupéré à la demande)."""
        with self._lock:
            self._conn.execute("UPDATE matches SET detail_json = ? WHERE game_id = ?",
                               (json.dumps(detail or {}, ensure_ascii=False), str(game_id)))
            self._conn.commit()

    # ------------------------------------------------------------ lecture
    def newest_id(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT game_id FROM matches ORDER BY game_creation DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def total(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]

    def query(self, where_sql: str = "", params: tuple = (),
              limit: int = 10, offset: int = 0) -> list[dict]:
        """Lignes de liste (résumé) pour l'écran, triées récent→ancien."""
        sql = ("SELECT game_id, champion_id, champion_name, win, kills, deaths, "
               "assists, cs, queue_label, duration, game_creation FROM matches")
        if where_sql:
            sql += " WHERE " + where_sql
        sql += " ORDER BY game_creation DESC LIMIT ? OFFSET ?"
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit, offset)).fetchall()
        return [{
            "gameId": r[0], "championId": r[1], "championName": r[2],
            "win": bool(r[3]), "kda": [r[4], r[5], r[6]], "cs": r[7],
            "queue": r[8], "duration": r[9], "when": _when(r[10]),
        } for r in rows]

    def detail(self, game_id) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT detail_json FROM matches WHERE game_id = ?",
                (str(game_id),)).fetchone()
        if not row or not row[0]:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None
