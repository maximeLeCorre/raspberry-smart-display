"""Sauvegarde quotidienne des bases du Pi sur le serveur (SFTP).

Les bases SQLite du Pi ne sont **que** sur sa carte SD : `matches.db`
(historique LoL, la LCU ne rend que les 20 dernières parties → irrécupérable),
`weather.db` (série météo au-delà des ~50 j qu'Open-Meteo sait rattraper),
`watch.db` (réglages faits depuis la montre) et `push.db` (jetons APNs : sans
eux, plus de notif tant que la montre ne s'est pas réenregistrée).
`monitor.db` / `icons.db` ne sont pas gardées : elles se reconstruisent seules.
Une fois par jour (à partir de `[server.backup] hour`), on en prend une copie
**cohérente** (API backup de SQLite, sûre pendant les écritures) qu'on envoie
par le lien SSH de l'écran Serveur, puis on ne garde que `keep_days` copies.

Côté serveur : `<dir>/matches-AAAA-MM-JJ.db`, `<dir>/weather-AAAA-MM-JJ.db`
(`dir` relatif au home de l'utilisateur SSH). Un redémarrage du Pi après
l'heure prévue renvoie la copie du jour (écrasée, sans conséquence).
Un échec est retenté au contrôle suivant (`CHECK_SECONDS`).

Restauration (Pi neuf, SD morte) : `restore()`, lancée par
`deploy/deploy_pi.py --restore [AAAA-MM-JJ]` (service arrêté pendant la copie).
"""

from __future__ import annotations

import os
import re
import shlex
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path


def default_files() -> list[Path]:
    """Bases sauvegardées (chemins réels du Pi), `matches` en tête (sa date sert
    de « dernière sauvegarde » à l'écran)."""
    from store import DB_PATH as MATCHES_DB
    from modules.system.weather import DB_PATH as WEATHER_DB
    from watch_settings import DB_PATH as WATCH_DB
    from push_apns import DB_PATH as PUSH_DB
    return [Path(MATCHES_DB), Path(WEATHER_DB), Path(WATCH_DB), Path(PUSH_DB)]


def snapshot_db(src: Path, dst: Path) -> None:
    """Copie cohérente d'une base SQLite, même si elle est en cours d'écriture."""
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dst))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


class ServerBackup:
    """Thread de fond : une sauvegarde par jour, statut lisible par l'écran."""

    CHECK_SECONDS = 600          # contrôle (et nouvel essai après échec) toutes les 10 min

    def __init__(self, link, cfg: dict, files: list[Path]):
        self.link = link
        self.dir = str(cfg.get("dir", "pi-display-backups")).strip().rstrip("/") \
            or "pi-display-backups"
        self.hour = min(23, max(0, int(cfg.get("hour", 4) or 0)))
        self.keep_days = max(1, int(cfg.get("keep_days", 14) or 14))
        self.files = [Path(f) for f in files]
        self._lock = threading.Lock()
        self._done_date = ""     # jour (AAAA-MM-JJ) de la dernière réussite
        # last = date de la dernière copie connue (locale ou vue sur le serveur).
        self._status: dict = {"last": "", "ts": 0.0, "ok": None, "error": ""}
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def due(self, now: datetime) -> bool:
        return now.hour >= self.hour and self._done_date != now.date().isoformat()

    # ---------------------------------------------------------------- boucle
    def _loop(self) -> None:
        self.probe()
        while True:
            now = datetime.now()
            if self.due(now):
                self.run(now.date().isoformat())
            time.sleep(self.CHECK_SECONDS)

    def probe(self) -> None:
        """Au démarrage : date de la plus récente copie déjà sur le serveur."""
        res = self.link._exec(
            f"ls -1 {shlex.quote(self.dir)}/matches-*.db 2>/dev/null | sort | tail -1")
        if res is None:
            return
        name = res[1].strip().rsplit("/", 1)[-1]
        if name.startswith("matches-") and name.endswith(".db"):
            with self._lock:
                self._status["last"] = name[len("matches-"):-len(".db")]

    def run(self, day: str) -> bool:
        """Envoie la copie du jour `day` de chaque base présente + rotation."""
        error = ""
        sent = 0
        try:
            res = self.link._exec(f"mkdir -p {shlex.quote(self.dir)}")
            if res is None or res[0] != 0:
                raise RuntimeError("serveur injoignable" if res is None
                                   else f"mkdir : {res[2].strip()}")
            with tempfile.TemporaryDirectory() as tmp:
                for src in self.files:
                    if not src.exists():
                        continue
                    copy = Path(tmp) / src.name
                    snapshot_db(src, copy)
                    err = self.link.upload(copy, f"{self.dir}/{src.stem}-{day}.db")
                    if err:
                        raise RuntimeError(f"envoi de {src.name} : {err}")
                    sent += 1
            self._prune()
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
        with self._lock:
            if error:
                self._status.update(ok=False, error=error, ts=time.time())
            else:
                self._done_date = day
                self._status.update(ok=True, error="", ts=time.time(), last=day)
        print(f"[backup] Sauvegarde {day} : "
              + (f"échec ({error})" if error else f"{sent} base(s) envoyée(s)"))
        return not error

    def _prune(self) -> None:
        """Ne garde que les `keep_days` copies les plus récentes de chaque base."""
        d = shlex.quote(self.dir)
        stems = " ".join(shlex.quote(f.stem) for f in self.files)
        self.link._exec(
            f"for s in {stems}; do ls -1 {d}/$s-*.db 2>/dev/null | sort"
            f" | head -n -{self.keep_days} | xargs -r rm -f; done")


# ------------------------------------------------------------ restauration
_NAME = re.compile(r"^(.+)-(\d{4}-\d{2}-\d{2})\.db$")


def available(link, remote_dir: str) -> dict[str, list[str]] | None:
    """Copies présentes sur le serveur : {base: [jours croissants]}, None si injoignable."""
    res = link._exec(f"ls -1 {shlex.quote(remote_dir)}/ 2>/dev/null")
    if res is None:
        return None
    out: dict[str, list[str]] = {}
    for line in res[1].splitlines():
        m = _NAME.match(line.strip().rsplit("/", 1)[-1])
        if m:
            out.setdefault(m.group(1), []).append(m.group(2))
    return {k: sorted(v) for k, v in out.items()}


def restore(link, remote_dir: str, files: list[Path], day: str = "") -> tuple[bool, list[str]]:
    """Remet chaque base depuis sa copie du jour `day` (défaut : sa plus récente).

    ⚠️ L'appli doit être **arrêtée** (sinon elle réécrirait par-dessus).
    Copie téléchargée à côté, vérifiée (`integrity_check`), puis mise en place
    par renommage ; l'ancienne base est gardée en `<nom>.avant-restauration`.
    Renvoie (tout OK, lignes de compte rendu)."""
    days = available(link, remote_dir)
    if days is None:
        return False, ["serveur injoignable"]
    ok, lines = True, []
    for dst in (Path(f) for f in files):
        have = days.get(dst.stem, [])
        pick = day if day else (have[-1] if have else "")
        if not pick or pick not in have:
            lines.append(f"{dst.name} : aucune copie" + (f" du {day}" if day else ""))
            continue
        tmp = dst.with_name(dst.name + ".restore")
        err = link.download(f"{remote_dir}/{dst.stem}-{pick}.db", tmp)
        if not err:
            err = _check(tmp)
        if err:
            tmp.unlink(missing_ok=True)
            ok = False
            lines.append(f"{dst.name} : ÉCHEC ({err})")
            continue
        if dst.exists():
            os.replace(dst, dst.with_name(dst.name + ".avant-restauration"))
        # Journal WAL de l'ancienne base : il ne doit pas être rejoué sur la nouvelle.
        for suffix in ("-wal", "-shm"):
            dst.with_name(dst.name + suffix).unlink(missing_ok=True)
        os.replace(tmp, dst)
        lines.append(f"{dst.name} : restaurée (copie du {pick})")
    return ok, lines


def _check(path: Path) -> str:
    """"" si la base est saine, sinon le problème."""
    try:
        conn = sqlite3.connect(str(path))
        try:
            res = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"base illisible : {exc}"
    return "" if res and res[0] == "ok" else f"base abîmée : {res[0] if res else '?'}"
