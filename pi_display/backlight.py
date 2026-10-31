"""Luminosité de l'écran (rétroéclairage DSI, `/sys/class/backlight`).

Veille douce : PC absent (agent déconnecté : éteint ou en veille) et aucun
appui depuis `dim_after_minutes` -> luminosité baissée à `dim_level` (fondu).
Un appui la rétablit ; il n'est **pas** transmis à l'écran (on ne clique pas
à l'aveugle sur un bouton). PC connecté -> toujours la luminosité normale, et
le délai repart de sa déconnexion.

Hors Pi (pas de /sys/class/backlight) ou sans droit d'écriture (règle udev
posée par deploy_pi.py, groupe video) : no-op, l'affichage marche pareil.
"""

from __future__ import annotations

import glob
import time

FADE_SECONDS = 1.5     # baisse progressive (le retour, lui, est immédiat)
WAKE_GRACE = 0.5       # s : appuis ignorés juste après le réveil (doublon doigt/souris SDL)


def find_device() -> str | None:
    paths = sorted(glob.glob("/sys/class/backlight/*/brightness"))
    return paths[0] if paths else None


class Backlight:
    def __init__(self, cfg: dict, path: str | None = None, clock=time.monotonic):
        self.enabled = cfg.get("enabled", True)
        self.dim_after = float(cfg.get("dim_after_minutes", 5)) * 60
        self._clock = clock
        self._file = path if path is not None else find_device()
        top = self._read_max()
        self.normal = min(int(cfg.get("normal_level", 255)), top)
        self.dim_level = min(int(cfg.get("dim_level", 30)), top)
        self.dimmed = False
        self._last_activity = clock()
        self._fade_start = 0.0
        self._woke_at = -WAKE_GRACE
        self._level: int | None = None       # dernière valeur écrite
        if self._file:
            print(f"[backlight] {self._file} (normal {self.normal}, veille {self.dim_level})")

    def _read_max(self) -> int:
        if not self._file:
            return 255
        try:
            with open(self._file.rsplit("/", 1)[0] + "/max_brightness") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return 255

    def _write(self, level: int) -> None:
        if not self._file or level == self._level:
            return
        try:
            with open(self._file, "w") as f:
                f.write(str(level))
            self._level = level
        except OSError as exc:
            print(f"[backlight] écriture impossible ({exc}) : luminosité non pilotée.")
            self._file = None

    def level(self) -> int:
        """Luminosité visée maintenant (fondu en cours compris)."""
        if not self.dimmed:
            return self.normal
        k = min(1.0, (self._clock() - self._fade_start) / FADE_SECONDS)
        return round(self.normal + (self.dim_level - self.normal) * k)

    def tick(self, agent_connected: bool) -> None:
        now = self._clock()
        if agent_connected:
            self._last_activity = now          # PC là : jamais de veille
        should_dim = self.enabled and now - self._last_activity >= self.dim_after
        if should_dim and not self.dimmed:
            self.dimmed, self._fade_start = True, now
        elif not should_dim:
            self.dimmed = False
        self._write(self.level())

    def wake(self) -> bool:
        """Appui / bouton : rétablit la luminosité. True = l'appui a servi à
        réveiller l'écran (ne pas le transmettre)."""
        now = self._clock()
        self._last_activity = now
        if self.dimmed:
            self.dimmed, self._woke_at = False, now
            self._write(self.normal)
            return True
        return now - self._woke_at < WAKE_GRACE

    def restore(self) -> None:
        """Arrêt de l'app : on ne laisse pas l'écran assombri."""
        self.dimmed = False
        self._write(self.normal)
