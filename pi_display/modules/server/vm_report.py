"""Lecture du relevé `pi-monitor` (deploy/server/pi-monitor.sh, lancé par sudo sur la VM).

Le script imprime des lignes ``clé=valeur`` ; `parse_report` en fait un dict prêt pour
les règles (`monitor.py`) et les écrans : conteneurs Rentrer (état, santé, redémarrages,
CPU/RAM), import des données MOTIS, plan IDFM, service du serveur de push.
Fonctions pures (testées sans VM).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone


def _int(val, default=None):
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return default


def iso_ts(text: str) -> float | None:
    """Horodatage ISO 8601 (« 2026-11-14T03:34:12Z », nanosecondes Docker) -> epoch."""
    text = (text or "").strip()
    if not text or text.startswith("0001-"):
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", text).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


_UNITS = {"b": 1, "kib": 1024, "kb": 1000, "mib": 1024 ** 2, "mb": 1000 ** 2,
          "gib": 1024 ** 3, "gb": 1000 ** 3, "tib": 1024 ** 4}


def mem_bytes(text: str) -> int | None:
    """« 96.5MiB » -> octets."""
    m = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)", text or "")
    if not m or m.group(2).lower() not in _UNITS:
        return None
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def parse_report(text: str) -> dict:
    """Relevé brut -> {containers: {service: {...}}, import: {...}, plan: {...}, push: {...}}."""
    raw: dict[str, str] = {}
    containers: dict[str, dict] = {}
    names: dict[str, str] = {}               # nom docker -> service
    stats: dict[str, tuple] = {}
    for line in text.splitlines():
        key, sep, val = line.partition("=")
        if not sep:
            continue
        if key == "ctr":
            parts = val.split("|")
            if len(parts) < 6 or not parts[0]:
                continue
            svc, state, health, restarts, started, name = parts[:6]
            # Plusieurs conteneurs d'un même service (outils lancés à la main) : le plus vivant gagne.
            prev = containers.get(svc)
            if prev is not None and prev["state"] == "running" and state != "running":
                continue
            containers[svc] = {"state": state, "health": health, "restarts": _int(restarts, 0),
                               "started": iso_ts(started), "cpu": None, "mem": None}
            names[name.lstrip("/")] = svc
        elif key == "stat":
            parts = val.split("|")
            if len(parts) >= 3:
                cpu = _int(parts[1].strip().rstrip("%").split(".")[0])
                stats[parts[0]] = (cpu, mem_bytes(parts[2].split("/")[0]))
        else:
            raw[key] = val.strip()
    for name, (cpu, mem) in stats.items():
        svc = names.get(name)
        if svc in containers:
            containers[svc]["cpu"], containers[svc]["mem"] = cpu, mem

    bridge_fp, plan_fp = raw.get("bridge_fp", ""), raw.get("plan_fp", "")
    failed_fp = raw.get("plan_failed_fp", "")
    return {
        "version": _int(raw.get("v"), 0),
        "now": _int(raw.get("now")),
        "docker": raw.get("docker") != "absent",
        "containers": containers,
        "data": raw.get("data") == "ok",
        "import": {
            "running": raw.get("import_running") == "1",
            "lock_at": _int(raw.get("import_lock_at")),
            "started": iso_ts(raw.get("import_start", "")),
            "ok": iso_ts(raw.get("import_ok", "")),
        },
        "plan": {
            # Nouveau plan dans la passerelle, pas encore importé dans MOTIS.
            "pending": bool(bridge_fp) and bridge_fp != plan_fp,
            "failed": bool(bridge_fp) and bridge_fp == failed_fp,
            "bridge_at": _int(raw.get("bridge_fp_at")),
            "imported_at": _int(raw.get("plan_at")),
            "published": raw.get("idfm_published", ""),
            "networks_ok": _int(raw.get("networks_ok")),
            "networks_failed": _int(raw.get("networks_failed")),
        },
        "push": {
            "state": raw.get("push_state", ""),
            "since": _int(raw.get("push_since")),
            "restarts": _int(raw.get("push_restarts")),
        },
    }
