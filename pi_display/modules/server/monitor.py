"""Règles de la supervision : état de chaque carte (VM, Rentrer, push NexusLink) et alertes.

`conditions()` (pure) lit les relevés (SSH `ServerLink.snapshot()`/`report()`, sondes HTTP
`Probes.snapshot()`, historique du push) et renvoie les problèmes vus MAINTENANT ;
`Monitor.evaluate()` ne lève une alerte qu'après un délai propre à chacune (problème vu
sans interruption) et la retire dès qu'il disparaît : les transitions (levée, retour à la
normale) servent aux notifications de la montre.

Fenêtres sans alerte : RAM haute pendant l'import des données MOTIS ; tout, si le Pi
lui-même n'a plus internet (`pi_offline` : on n'accuse pas la VM). Les états sont écrits
(OK / ATTENTION / PANNE / INCONNU), jamais portés par la seule couleur.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

OK, WARN, CRIT, UNKNOWN = "ok", "warn", "crit", "unknown"
RANK = {OK: 0, UNKNOWN: 1, WARN: 2, CRIT: 3}
WORDS = {OK: "OK", WARN: "ATTENTION", CRIT: "PANNE", UNKNOWN: "INCONNU"}
CARDS = ("vm", "rentrer", "push")
CARD_NAMES = {"vm": "VM", "rentrer": "Rentrer", "push": "Push NexusLink"}

DEFAULT_SERVICES = ("caddy", "api", "worker", "motis", "idfm-bridge")
# États Docker écrits en français (écrans et alertes).
DOCKER_WORDS = {"running": "actif", "exited": "arrêté", "restarting": "redémarre",
                "paused": "en pause", "created": "créé", "dead": "mort", "absent": "absent"}


@dataclass
class Cond:
    card: str
    level: str
    text: str
    delay: float = 0.0          # secondes de problème continu avant l'alerte


@dataclass
class Alert:
    key: str
    card: str
    level: str
    text: str
    since: float                # 1re fois vu
    raised: float = 0.0         # levée (since + délai)


@dataclass
class Settings:
    disk_warn: float = 80
    disk_crit: float = 90
    ram_warn: float = 90
    ram_minutes: float = 10
    down_seconds: float = 90
    api_seconds: float = 120
    degraded_minutes: float = 15
    plan_minutes: float = 30
    import_minutes: float = 20
    cert_days: int = 14
    services: tuple = DEFAULT_SERVICES
    notify: tuple = (CRIT,)

    @classmethod
    def from_config(cls, cfg: dict) -> "Settings":
        s = cls()
        for name in ("disk_warn", "disk_crit", "ram_warn", "ram_minutes", "down_seconds",
                     "api_seconds", "degraded_minutes", "plan_minutes", "import_minutes"):
            if name in cfg:
                setattr(s, name, float(cfg[name]))
        if "cert_days" in cfg:
            s.cert_days = int(cfg["cert_days"])
        if cfg.get("rentrer_services"):
            s.services = tuple(cfg["rentrer_services"])
        if "notify" in cfg:
            words = {"panne": CRIT, "attention": WARN, CRIT: CRIT, WARN: WARN}
            s.notify = tuple(words[w] for w in cfg["notify"] if w in words)
        return s


def _pct(used, total):
    return used / total * 100.0 if total else None


def _ago(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h"


@dataclass
class Inputs:
    now: float
    link: dict | None = None            # ServerLink.snapshot() (None = pas de serveur configuré)
    report: dict | None = None          # ServerLink.report()
    probes: dict | None = None          # Probes.snapshot()
    push_hours: list = field(default_factory=list)   # MonitorHistory.push_hours()
    restart_loops: dict = field(default_factory=dict)  # service -> redémarrages sur 10 min


def pi_offline(inp: Inputs) -> bool:
    return bool(inp.probes) and inp.probes.get("internet") is False


def conditions(inp: Inputs, s: Settings) -> dict[str, Cond]:
    out: dict[str, Cond] = {}
    if pi_offline(inp):
        return out
    now = inp.now
    link = inp.link or {}
    probes = inp.probes or {}
    have_http = bool(probes.get("ts"))
    rp, pp = probes.get("rentrer") or {}, probes.get("push") or {}
    rep = (inp.report or {}).get("data") or {}
    imp = rep.get("import") or {}
    importing = bool(imp.get("running"))

    # --- VM ---------------------------------------------------------------------------
    vm_down = (inp.link is not None and not link.get("online") and have_http
               and not rp.get("up") and not pp.get("up"))
    if vm_down:
        out["vm.down"] = Cond("vm", CRIT, "VM injoignable (SSH et HTTP)", s.down_seconds)
    elif inp.link is not None and not link.get("online") and have_http:
        out["vm.ssh"] = Cond("vm", WARN, "SSH injoignable", 120)
    if link.get("online"):
        disk = _pct(link.get("disk_used", 0), link.get("disk_total", 0))
        if disk is not None and disk >= s.disk_crit:
            out["vm.disk"] = Cond("vm", CRIT, f"Disque plein à {disk:.0f} %", 60)
        elif disk is not None and disk >= s.disk_warn:
            out["vm.disk"] = Cond("vm", WARN, f"Disque à {disk:.0f} %", 60)
        ram = _pct(link.get("mem_used", 0), link.get("mem_total", 0))
        if ram is not None and ram >= s.ram_warn and not importing:
            out["vm.ram"] = Cond("vm", WARN, f"RAM à {ram:.0f} %", s.ram_minutes * 60)

    # --- Rentrer ------------------------------------------------------------------------
    if have_http and rp and not vm_down:
        if not rp.get("up"):
            out["rentrer.api"] = Cond("rentrer", CRIT,
                                      f"API injoignable ({rp.get('error') or 'pas de réponse'})",
                                      s.api_seconds)
        elif rp.get("motis") is False:
            out["rentrer.motis"] = Cond("rentrer", CRIT, "MOTIS ne répond pas", s.api_seconds)
        status = rp.get("status") or {}
        state = status.get("state")
        msg = status.get("message") or ""
        if state == "down":
            out["rentrer.canary"] = Cond("rentrer", CRIT, f"Trajets témoins en panne{' : ' + msg if msg else ''}")
        elif state == "degraded":
            out["rentrer.canary"] = Cond("rentrer", WARN, f"Trajets témoins dégradés{' : ' + msg if msg else ''}",
                                         s.degraded_minutes * 60)
        elif state == "unknown":
            out["rentrer.canary"] = Cond("rentrer", WARN, "Trajets témoins muets (worker arrêté ?)", 300)
        days = rp.get("cert_days")
        if days is not None and days < s.cert_days:
            out["rentrer.cert"] = Cond("rentrer", WARN, f"Certificat HTTPS : expire dans {days} j")
    if rep and not vm_down:
        containers = rep.get("containers") or {}
        for svc in s.services:
            c = containers.get(svc)
            if c is None or c.get("state") != "running":
                state = (c or {}).get("state") or "absent"
                word = DOCKER_WORDS.get(state, state)
                out[f"rentrer.ctr.{svc}"] = Cond("rentrer", CRIT, f"Conteneur {svc} : {word}", 120)
            elif c.get("health") == "unhealthy":
                out[f"rentrer.ctr.{svc}"] = Cond("rentrer", WARN, f"Conteneur {svc} : malade", 300)
        for svc, n in inp.restart_loops.items():
            out[f"rentrer.loop.{svc}"] = Cond("rentrer", CRIT, f"{svc} redémarre en boucle ({n} fois en 10 min)")
        if importing and imp.get("lock_at") and now - imp["lock_at"] > s.import_minutes * 60:
            out["rentrer.import"] = Cond("rentrer", WARN, f"Import MOTIS bloqué depuis {_ago(now - imp['lock_at'])}")
        elif (not importing and imp.get("started") and now - imp["started"] > 300
              and (imp.get("ok") is None or imp["ok"] < imp["started"])):
            out["rentrer.import"] = Cond("rentrer", WARN, "Dernier import MOTIS en échec")
        plan = rep.get("plan") or {}
        if plan.get("failed"):
            out["rentrer.plan"] = Cond("rentrer", WARN, "Import du nouveau plan IDFM en échec")
        elif (plan.get("pending") and not importing and plan.get("bridge_at")
              and now - plan["bridge_at"] > s.plan_minutes * 60):
            out["rentrer.plan"] = Cond("rentrer", WARN,
                                       f"Plan IDFM non importé depuis {_ago(now - plan['bridge_at'])}")

    # --- Push NexusLink ---------------------------------------------------------------------
    if have_http and pp and not vm_down:
        if pp.get("pin_error"):
            out["push.pin"] = Cond("push", CRIT, "Push : certificat inattendu (épinglage)")
        elif not pp.get("up"):
            out["push.health"] = Cond("push", CRIT,
                                      f"Push injoignable ({pp.get('error') or 'pas de réponse'})",
                                      s.api_seconds)
        days = pp.get("cert_days")
        if days is not None and days < s.cert_days:
            out["push.cert"] = Cond("push", WARN, f"Certificat du push : expire dans {days} j")
        st = pp.get("stats") or {}
        if st.get("grantsExpiring"):
            n = st["grantsExpiring"]
            out["push.grants"] = Cond("push", WARN,
                                      f"{n} droit{'s' if n > 1 else ''} App Attest expire{'nt' if n > 1 else ''} dans < 14 j")
        if st.get("banned"):
            n = st["banned"]
            out["push.banned"] = Cond("push", WARN, f"{n} installation{'s' if n > 1 else ''} bannie{'s' if n > 1 else ''}")
    push_state = ((rep.get("push") or {}).get("state")) if rep else None
    if push_state and push_state not in ("active", "absent", "") and not vm_down:
        out["push.service"] = Cond("push", CRIT, f"Service wardlink-push : {push_state}", 60)
    recent = inp.push_hours[-2:]
    refused = sum(h.get("refused", 0) for h in recent)
    delivered = sum(h.get("delivered", 0) for h in recent)
    if refused >= 5 and refused > delivered:
        out["push.refused"] = Cond("push", WARN, f"Push : {refused} refus d'Apple en 2 h")
    return out


class Monitor:
    """Alertes avec délai : levées après `delay` s de problème continu, retirées dès qu'il disparaît."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.active: dict[str, Alert] = {}
        self._pending: dict[str, float] = {}           # clé -> 1re fois vu
        self._restarts: dict[str, deque] = {}          # service -> (ts, RestartCount)
        self.offline = False
        self.inputs: Inputs | None = None

    def restart_loops(self, report: dict | None, now: float) -> dict[str, int]:
        """Services dont le compteur de redémarrages Docker a pris ≥ 3 en 10 min."""
        loops = {}
        containers = ((report or {}).get("data") or {}).get("containers") or {}
        for svc, c in containers.items():
            hist = self._restarts.setdefault(svc, deque())
            if not hist or hist[-1][1] != c.get("restarts"):
                hist.append((now, c.get("restarts") or 0))
            while hist and now - hist[0][0] > 600:
                hist.popleft()
            if len(hist) >= 2 and hist[-1][1] - hist[0][1] >= 3:
                loops[svc] = hist[-1][1] - hist[0][1]
        return loops

    def evaluate(self, inp: Inputs) -> tuple[list[Alert], list[Alert]]:
        """Met à jour les alertes ; renvoie (levées, retirées) depuis l'appel précédent."""
        self.inputs = inp
        self.offline = pi_offline(inp)
        conds = conditions(inp, self.settings)
        raised, cleared = [], []
        for key in list(self._pending):
            if key not in conds:
                del self._pending[key]
        for key in list(self.active):
            if key not in conds:
                cleared.append(self.active.pop(key))
        for key, c in conds.items():
            since = self._pending.setdefault(key, inp.now)
            alert = self.active.get(key)
            if alert is not None:
                if RANK[c.level] > RANK[alert.level]:       # aggravation : nouvelle notification
                    alert.level, alert.text = c.level, c.text
                    raised.append(alert)
                else:
                    alert.level, alert.text = c.level, c.text
            elif inp.now - since >= c.delay:
                alert = Alert(key, c.card, c.level, c.text, since, inp.now)
                self.active[key] = alert
                raised.append(alert)
        return raised, cleared

    def card_level(self, card: str) -> str:
        inp = self.inputs
        if inp is None or self.offline:
            return UNKNOWN
        levels = [a.level for a in self.active.values() if a.card == card]
        if levels:
            return max(levels, key=RANK.get)
        if card == "vm":
            return OK if inp.link and inp.link.get("online") else UNKNOWN
        probes = inp.probes or {}
        if not probes.get("ts") or not probes.get(card):
            return UNKNOWN
        return OK

    def alerts(self, card: str | None = None) -> list[Alert]:
        """Alertes actives, la plus grave puis la plus ancienne d'abord."""
        items = [a for a in self.active.values() if card is None or a.card == card]
        return sorted(items, key=lambda a: (-RANK[a.level], a.raised))

    def worst(self) -> tuple[str, str]:
        """(niveau le plus grave, carte concernée) ; (OK, "") si tout va bien."""
        best = (OK, "")
        for card in CARDS:
            level = self.card_level(card)
            if RANK[level] > RANK[best[0]]:
                best = (level, card)
        return best
