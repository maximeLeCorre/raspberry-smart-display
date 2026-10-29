"""Santé du Pi lui-même (CPU, RAM, disque, température) → alertes de l'accueil.

Lecture **locale** (pas de SSH ni de réseau) : ``/proc/stat`` (CPU% = delta entre
deux relevés, comme ``server_link``), ``/proc/meminfo`` (``MemAvailable``),
``shutil.disk_usage`` et ``/sys/class/thermal`` (le Pi 3 bride vers 80 °C).
Hors Linux (test sur PC), seul le disque est relevé : CPU/RAM/temp restent None.

Un thread de fond relève toutes les ``poll_seconds`` ; ``alerts()`` renvoie les
métriques au-dessus de leur seuil (config ``[pi_health]``). Le CPU doit rester
au-dessus du seuil sur ``cpu_sustain`` relevés de suite (pas d'alerte sur un pic).

Partagé via ``get_pi_health(app)`` : une seule instance par application.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

_THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


def read_cpu_times() -> tuple[int, int] | None:
    """(total, idle) cumulés depuis le boot, ou None hors Linux."""
    try:
        with open("/proc/stat") as f:
            nums = [int(x) for x in f.readline().split()[1:8]]
    except (OSError, ValueError):
        return None
    idle = nums[3] + nums[4]       # idle + iowait
    return sum(nums), idle


def read_mem_pct() -> float | None:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":", 1)
                info[key] = int(val.split()[0])
        return 100.0 * (1 - info["MemAvailable"] / info["MemTotal"])
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def read_temp_c() -> float | None:
    try:
        return int(_THERMAL.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def read_disk_pct(path: str) -> float | None:
    try:
        du = shutil.disk_usage(path)
        return 100.0 * du.used / du.total
    except OSError:
        return None


class PiHealth:
    """Relève périodiquement l'état du Pi et calcule les alertes."""

    def __init__(self, *, thresholds: dict[str, float], disk_path: str = "/",
                 poll_seconds: float = 5.0, cpu_sustain: int = 3):
        self.thresholds = thresholds          # {"cpu": %, "ram": %, "disk": %, "temp": °C}
        self.disk_path = disk_path
        self.poll_seconds = max(1.0, poll_seconds)
        self.cpu_sustain = max(1, cpu_sustain)
        self._lock = threading.Lock()
        self._values: dict[str, float | None] = {}
        self._cpu_high = 0                    # relevés CPU consécutifs au-dessus du seuil
        self._prev_cpu: tuple[int, int] | None = None
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def values(self) -> dict[str, float | None]:
        with self._lock:
            return dict(self._values)

    def alerts(self) -> list[tuple[str, float]]:
        """[(métrique, valeur)] au-dessus du seuil, ordre cpu/ram/disk/temp."""
        with self._lock:
            vals, cpu_high = dict(self._values), self._cpu_high
        out = []
        for key in ("cpu", "ram", "disk", "temp"):
            v, limit = vals.get(key), self.thresholds.get(key)
            if v is None or limit is None or v < limit:
                continue
            if key == "cpu" and cpu_high < self.cpu_sustain:
                continue
            out.append((key, v))
        return out

    # ----------------------------------------------------------------- interne
    def sample(self) -> None:
        """Un relevé (public pour les tests)."""
        cpu = None
        times = read_cpu_times()
        if times and self._prev_cpu:
            dt = times[0] - self._prev_cpu[0]
            didle = times[1] - self._prev_cpu[1]
            if dt > 0:
                cpu = 100.0 * (1 - didle / dt)
        self._prev_cpu = times
        vals = {"cpu": cpu, "ram": read_mem_pct(),
                "disk": read_disk_pct(self.disk_path), "temp": read_temp_c()}
        self.update(vals)

    def update(self, vals: dict[str, float | None]) -> None:
        with self._lock:
            self._values = vals
            limit = self.thresholds.get("cpu")
            cpu = vals.get("cpu")
            if cpu is not None and limit is not None and cpu >= limit:
                self._cpu_high += 1
            else:
                self._cpu_high = 0

    def _loop(self) -> None:
        while True:
            try:
                self.sample()
            except Exception as exc:  # on ne casse jamais l'UI
                print(f"[pi_health] échec du relevé : {exc}")
            time.sleep(self.poll_seconds)


def get_pi_health(app):
    """Instance unique pour l'app (config ``[pi_health]``) ; None si désactivée."""
    if not hasattr(app, "_pi_health"):
        cfg = app.config.get("pi_health", {})
        mon = None
        if cfg.get("enabled", True):
            mon = PiHealth(
                thresholds={"cpu": float(cfg.get("cpu_pct", 90)),
                            "ram": float(cfg.get("ram_pct", 90)),
                            "disk": float(cfg.get("disk_pct", 90)),
                            "temp": float(cfg.get("temp_c", 75))},
                disk_path=str(cfg.get("disk_path", "/")),
                poll_seconds=float(cfg.get("poll_seconds", 5)),
                cpu_sustain=int(cfg.get("cpu_sustain", 3)),
            )
            mon.start()
        app._pi_health = mon
    return app._pi_health
