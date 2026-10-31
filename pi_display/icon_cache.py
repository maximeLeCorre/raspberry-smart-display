"""Cache disque des icônes de champion (SQLite `icons.db`).

Évite de tout retélécharger à chaque redémarrage du Pi. Une ligne par
champion : l'image brute (taille CDN ; chaque écran la redimensionne) et le
patch Community Dragon du téléchargement. Patch changé -> l'image est reprise
au prochain besoin (mise à jour visuelle) ; hors ligne -> on sert la version
en cache.

Base séparée de `matches.db` : jetable (tout se retélécharge), donc hors de la
sauvegarde SFTP quotidienne. `*.db` : ignoré par Git et par le déploiement.
Thread-safe (un verrou) : appelée depuis les workers de `App.async_call`.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "icons.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS icons (
    champion_id   INTEGER PRIMARY KEY,
    patch         TEXT,
    image         BLOB
);
"""


class IconCache:
    def __init__(self, path: Path = DB_PATH):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def get(self, champion_id: int) -> tuple[bytes, str] | None:
        """(image, patch du téléchargement), ou None si jamais téléchargée."""
        with self._lock:
            row = self._conn.execute(
                "SELECT image, patch FROM icons WHERE champion_id = ?",
                (int(champion_id),)).fetchone()
        return (bytes(row[0]), row[1] or "") if row else None

    def put(self, champion_id: int, patch: str, image: bytes) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO icons VALUES (?, ?, ?)",
                               (int(champion_id), patch or "", sqlite3.Binary(image)))
            self._conn.commit()
