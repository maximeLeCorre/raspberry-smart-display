"""Sauvegarde quotidienne des bases du Pi sur le serveur (SFTP).

Les bases SQLite du Pi ne sont **que** sur sa carte SD : `matches.db`
(historique LoL, la LCU ne rend que les 20 dernières parties → irrécupérable)
et `weather.db` (série météo au-delà des ~50 j qu'Open-Meteo sait rattraper).
Une fois par jour (à partir de `[server.backup] hour`), on en prend une copie
**cohérente** (API backup de SQLite, sûre pendant les écritures) qu'on envoie
par le lien SSH de l'écran Serveur, puis on ne garde que `keep_days` copies.

Côté serveur : `<dir>/matches-AAAA-MM-JJ.db`, `<dir>/weather-AAAA-MM-JJ.db`
(`dir` relatif au home de l'utilisateur SSH). Un redémarrage du Pi après
l'heure prévue renvoie la copie du jour (écrasée, sans conséquence).
Un échec est retenté au contrôle suivant (`CHECK_SECONDS`).
"""

from __future__ import annotations

import shlex
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path


def default_files() -> list[Path]:
    """Bases sauvegardées : historique LoL + météo (chemins réels du Pi)."""
    from store import DB_PATH as MATCHES_DB
    from modules.system.weather import DB_PATH as WEATHER_DB
    return [Path(MATCHES_DB), Path(WEATHER_DB)]


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
