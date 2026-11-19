"""Sauvegarde quotidienne des bases du Pi sur le serveur (faux lien SSH)."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime

from modules.server import backup as backup_mod
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


# ------------------------------------------------------------ restauration
class RestoreLink(FakeLink):
    """Serveur = dossier local : `ls` le liste, `download` y copie."""

    def _exec(self, cmd, timeout=10.0):
        self.cmds.append(cmd)
        if not self.online:
            return None
        return (0, "\n".join(sorted(p.name for p in self.remote_dir.iterdir())), "")

    def download(self, remote, local, timeout=60.0):
        src = self.remote_dir / remote.rsplit("/", 1)[-1]
        if not src.exists():
            return "No such file"
        shutil.copy(src, local)
        return ""


def count(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


def test_restaure_la_plus_recente_et_garde_l_ancienne(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    make_db(remote / "matches-2026-11-17.db", 5).close()
    make_db(remote / "matches-2026-11-18.db", 7).close()
    make_db(remote / "watch-2026-11-18.db", 2).close()
    (remote / "notes.txt").write_text("x")             # ignoré
    local = tmp_path / "pi"
    local.mkdir()
    make_db(local / "matches.db", 1).close()
    (local / "matches.db-wal").write_bytes(b"vieux journal")
    files = [local / "matches.db", local / "weather.db", local / "watch.db"]

    assert backup_mod.available(RestoreLink(remote), "bk") == {
        "matches": ["2026-11-17", "2026-11-18"], "watch": ["2026-11-18"]}
    ok, lines = backup_mod.restore(RestoreLink(remote), "bk", files)
    assert ok
    assert count(local / "matches.db") == 7 and count(local / "watch.db") == 2
    assert count(local / "matches.db.avant-restauration") == 1
    assert not (local / "matches.db-wal").exists()     # pas rejoué sur la nouvelle base
    assert not (local / "weather.db").exists()
    assert "weather.db : aucune copie" in lines

    ok, _ = backup_mod.restore(RestoreLink(remote), "bk", files, day="2026-11-17")
    assert ok and count(local / "matches.db") == 5


def test_restauration_refuse_une_copie_abimee(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "matches-2026-11-18.db").write_bytes(b"pas une base SQLite" * 100)
    local = tmp_path / "pi"
    local.mkdir()
    make_db(local / "matches.db", 3).close()
    ok, lines = backup_mod.restore(RestoreLink(remote), "bk", [local / "matches.db"])
    assert not ok and "ÉCHEC" in lines[0]
    assert count(local / "matches.db") == 3            # base en place intacte
    assert not (local / "matches.db.restore").exists()
    assert backup_mod.restore(RestoreLink(remote, online=False), "bk", [])[0] is False


def test_bases_du_pi_en_wal_et_toutes_sauvegardees(tmp_path):
    from sqlite_db import open_db
    conn = open_db(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
    assert [f.name for f in backup_mod.default_files()] == [
        "matches.db", "weather.db", "watch.db", "push.db"]
