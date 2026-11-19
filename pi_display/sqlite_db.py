"""Ouverture commune des bases SQLite du Pi (toutes sur la carte SD).

Mode **WAL** + `synchronous=NORMAL` : une écriture = un ajout au journal (pas de
réécriture du fichier + journal de rollback à chaque commit), donc bien moins
d'écritures sur la SD pour `monitor.db` (~1/min, jour et nuit) et les autres ;
les lectures (écran) ne bloquent plus les écritures (threads de fond).
NORMAL en WAL reste cohérent après une coupure de courant (au pire, les
derniers commits sont perdus, jamais la base corrompue).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def open_db(path: Path | str, **kwargs) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), **kwargs)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
