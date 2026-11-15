"""Module « serveur » : supervision de la VM et de ce qu'elle héberge (Rentrer, push
NexusLink) + contrôle de services (start/stop/restart), le tout depuis le Pi (SSH et
HTTPS ; marche PC éteint). Activable en config ([modules] server), paramétré par
[server] (hôte, clé, service) et [server.monitor] (sondes, seuils, notifications).
Pi-only : pas de moitié `sources/` côté agent.

Écrans : `server` (vue d'ensemble, entrée de la tuile Serveur) → `server_machine`
(VM + Minecraft), `server_rentrer`, `server_push`.
"""

from __future__ import annotations

import time

from modules.base import Module
from modules.server.machine_screen import MachineScreen
from modules.server.monitor import CARD_NAMES, CRIT, Inputs, Monitor, Settings, WORDS
from modules.server.push_screen import PushScreen
from modules.server.rentrer_screen import RentrerScreen
from modules.server.server_link import get_link
from modules.server.services_screen import ServicesScreen

EVAL_SECONDS = 5


class ServerModule(Module):
    name = "server"
    screens = [ServicesScreen, MachineScreen, RentrerScreen, PushScreen]

    def __init__(self, app):
        super().__init__(app)
        self.link = get_link(app)
        cfg = dict(app.config.get("server", {}).get("monitor", {}))
        self.monitor = Monitor(Settings.from_config(cfg))
        self.probes = None
        self.history = None
        if self.link is not None and cfg.get("enabled", True):
            from config import load_stats_tokens
            from modules.server.history import MonitorHistory
            from modules.server.probes import Probes
            rentrer_token, push_token = load_stats_tokens()
            self.probes = Probes(cfg, self.link.host, rentrer_token, push_token)
            self.probes.start()
            self.history = MonitorHistory()
        self._eval_ts = 0.0
        self._push_stats_ts = 0.0
        self._canary_ts = 0.0

    def tick(self) -> None:
        if self.link is None or time.monotonic() - self._eval_ts < EVAL_SECONDS:
            return
        self._eval_ts = time.monotonic()
        self.evaluate(time.time())

    def evaluate(self, now: float) -> None:
        probes = self.probes.snapshot() if self.probes else None
        report = self.link.report()
        if self.history is not None and probes:
            self._record(probes, now)
        hours = self.history.push_hours(now) if self.history is not None else []
        inp = Inputs(now=now, link=self.link.snapshot(), report=report, probes=probes,
                     push_hours=hours, restart_loops=self.monitor.restart_loops(report, now))
        raised, cleared = self.monitor.evaluate(inp)
        notify = self.monitor.settings.notify
        for alert in raised:
            print(f"[monitor] {WORDS[alert.level]} {alert.text}")
            if alert.level in notify:
                self.app.push.notify(
                    {"alert": {"title": f"{CARD_NAMES[alert.card]} : {WORDS[alert.level].lower()}",
                               "body": alert.text}, "sound": "default"},
                    collapse_id=f"srv-{alert.key}"[:64], ttl=3600)
        for alert in cleared:
            print(f"[monitor] rétabli : {alert.text}")
            if alert.level in notify:
                self.app.push.notify(
                    {"alert": {"title": f"{CARD_NAMES[alert.card]} : rétabli", "body": alert.text}},
                    collapse_id=f"srv-{alert.key}"[:64], ttl=3600)

    def _record(self, probes: dict, now: float) -> None:
        """Frise des trajets témoins (à chaque relevé) et envois du push (à chaque /v1/stats)."""
        rentrer = probes.get("rentrer") or {}
        if probes.get("ts") and probes["ts"] != self._canary_ts:
            self._canary_ts = probes["ts"]
            state = ((rentrer.get("status") or {}).get("state")
                     or ("injoignable" if not rentrer.get("up") else "unknown"))
            self.history.record_canary(state, now)
        push = probes.get("push") or {}
        if push.get("stats") and push.get("stats_ts") != self._push_stats_ts:
            self._push_stats_ts = push.get("stats_ts")
            self.history.record_push(push["stats"], now)

    def has_critical(self) -> bool:
        return any(a.level == CRIT for a in self.monitor.active.values())
