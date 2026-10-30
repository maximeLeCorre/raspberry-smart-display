"""Sauvegarde quotidienne des bases du Pi sur le serveur (faux lien SSH)."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime

from modules.server.backup import ServerBackup


class FakeLink:
    """Imite ServerLink : `_exec` journalise, `upload` copie dans un dossier."""

    def __init__(self, remote_dir, online=True, upload_error=""):
        self.remote_dir = remote_dir
        self.online = online
        self.upload_error = upload_error
        self.cmds = []

    def _exec(self, cmd, timeout=10.0):
        self.cmds.append(cmd)
        return (0, "", "") if self.online else None

    def upload(self, local, remote, timeout=60.0):
        if self.upload_error:
            return self.upload_error
        shutil.copy(local, self.remote_dir / remote.rsplit("/", 1)[-1])
        return ""


def make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    return conn


def test_envoie_une_copie_coherente_et_fait_la_rotation(tmp_path):
    (tmp_path / "remote").mkdir()
    matches = tmp_path / "matches.db"
    conn = make_db(matches, 3)           # base ouverte, comme sur le Pi
    link = FakeLink(tmp_path / "remote")
    backup = ServerBackup(link, {"dir": "bk", "keep_days": 5},
                          [matches, tmp_path / "weather.db"])   # météo absente : ignorée

    assert backup.run("2026-10-30")
    copy = tmp_path / "remote" / "matches-2026-10-30.db"
    assert sqlite3.connect(str(copy)).execute("SELECT COUNT(*) FROM t").fetchone() == (3,)
    assert not (tmp_path / "remote" / "weather-2026-10-30.db").exists()
    assert link.cmds[0] == "mkdir -p bk"
    assert "head -n -5" in link.cmds[-1] and "matches weather" in link.cmds[-1]
    st = backup.status()
    assert st["ok"] and st["last"] == "2026-10-30"
    conn.close()


def test_une_seule_fois_par_jour_apres_l_heure(tmp_path):
    backup = ServerBackup(FakeLink(tmp_path), {"hour": 4}, [])
    assert not backup.due(datetime(2026, 10, 30, 3, 59))
    assert backup.due(datetime(2026, 10, 30, 4, 0))
    backup.run("2026-10-30")
    assert not backup.due(datetime(2026, 10, 30, 22, 0))
    assert backup.due(datetime(2026, 10, 31, 4, 0))


def test_echec_garde_la_tentative_pour_plus_tard(tmp_path):
    matches = tmp_path / "matches.db"
    make_db(matches, 1).close()
    for link in (FakeLink(tmp_path, online=False), FakeLink(tmp_path, upload_error="refusé")):
        backup = ServerBackup(link, {"hour": 0}, [matches])
        assert not backup.run("2026-10-30")
        assert backup.status()["ok"] is False
        assert backup.due(datetime(2026, 10, 30, 12, 0))      # retentée au contrôle suivant
