"""Lien SSH vers un petit serveur : métriques système + contrôle de services.

Le **Pi se connecte lui-même** en SSH (il est le cerveau autonome, comme pour
l'API Web et le flux RSS) : l'écran serveur marche donc **PC éteint**. Aucun
message réseau vers l'agent n'est impliqué.

Modèle calqué sur `rss_feed.py` : un thread de fond interroge le serveur toutes
les `poll_seconds` via **une seule commande** SSH qui imprime des lignes
``clé=valeur`` (CPU, RAM, disque, température, état des services). L'écran lit le
dernier `snapshot()` (copie thread-safe) ; il ne fait jamais d'I/O lui-même.
Un historique glissant CPU/RAM (`history()`, `[server] history_minutes`) est
alimenté à chaque sondage pour les courbes de l'écran.

Le contrôle d'un service (start/stop/restart) passe par `run_action`, exécuté
hors boucle de rendu par `App.async_call`. systemd + `sudo` (règle NOPASSWD
limitée à `systemctl` côté serveur).

Connexion **persistante** réutilisée (paramiko), reconnexion automatique. La clé
privée vit sur le Pi (`certs/`, copiée par deploy) ; l'empreinte du serveur est
épinglée au 1er contact (TOFU) dans un known_hosts dédié.
"""

from __future__ import annotations

import shlex
import threading
import time
from collections import deque
from pathlib import Path

try:
    import paramiko
except Exception:  # paramiko absent (ou échec d'import) : lien dégradé « hors ligne ».
    paramiko = None

# Racine du dépôt : pi_display/modules/server/server_link.py -> parents[3].
REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


class ServerLink:
    """Connexion SSH persistante + sondage périodique des métriques."""

    def __init__(self, cfg: dict):
        self.host = str(cfg.get("host", "")).strip()
        self.port = int(cfg.get("port", 22) or 22)
        self.user = str(cfg.get("user", "")).strip()
        self.key_file = _resolve(str(cfg.get("key_file", "certs/server_id_ed25519")))
        self.known_hosts = _resolve(str(cfg.get("known_hosts", "certs/server_known_hosts")))
        self.disk_path = str(cfg.get("disk_path", "/")) or "/"
        self.poll_seconds = max(2, int(cfg.get("poll_seconds", 5) or 5))
        # Fenêtre des courbes : un point (ts, cpu %, ram %) par sondage.
        self.history_seconds = max(60, int(float(cfg.get("history_minutes", 10) or 10) * 60))
        self._history: deque = deque(maxlen=self.history_seconds // self.poll_seconds + 1)
        self.services = [
            {"label": s.get("label") or s.get("unit", "service"),
             "unit": str(s.get("unit", "")).strip(),
             "use_sudo": bool(s.get("use_sudo", True))}
            for s in cfg.get("services", []) if str(s.get("unit", "")).strip()
        ]

        self._metrics_cmd = self._build_metrics_cmd()
        self._lock = threading.Lock()            # sérialise l'accès au canal SSH
        self._snap_lock = threading.Lock()       # protège le snapshot
        self._client = None
        self._prev_cpu: tuple[int, int] | None = None   # (total, idle) du dernier poll
        self._snapshot: dict = {"online": False, "error": "", "services": {}}
        self.backup = None                       # ServerBackup (cf. get_link)
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict:
        with self._snap_lock:
            snap = dict(self._snapshot)
            snap["services"] = dict(snap.get("services", {}))
            return snap

    def history(self) -> list[tuple[float, float | None, float | None]]:
        """Copie de l'historique : [(ts, cpu %, ram %)], du plus ancien au plus récent."""
        with self._snap_lock:
            return list(self._history)

    # ------------------------------------------------------------ commande SSH
    def _build_metrics_cmd(self) -> str:
        parts = [
            'echo "host=$(hostname)"',
            'echo "uptime=$(cut -d. -f1 /proc/uptime)"',
            'echo "nproc=$(nproc)"',
            # Ligne agrégée du CPU : user nice system idle iowait irq softirq.
            r"""awk '/^cpu /{print "cpu="$2" "$3" "$4" "$5" "$6" "$7" "$8}' /proc/stat""",
            r"""awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{print "mem_total_kb="t"\nmem_avail_kb="a}' /proc/meminfo""",
            f"df -B1 --output=size,used {shlex.quote(self.disk_path)} 2>/dev/null"
            r""" | tail -1 | awk '{print "disk_size="$1"\ndisk_used="$2}'""",
            'echo "temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo)"',
        ]
        for svc in self.services:
            unit = svc["unit"]
            # is-active ne nécessite pas sudo (lecture de l'état).
            parts.append(f'echo "svc:{unit}=$(systemctl is-active {shlex.quote(unit)} 2>/dev/null)"')
        return "\n".join(parts)

    # ------------------------------------------------------------- connexion
    def _ensure_client(self):
        """Renvoie un client connecté (ouvre la connexion au besoin), ou None."""
        if paramiko is None:
            self._snapshot_error("paramiko manquant")
            return None
        if self._client is not None and self._client.get_transport() is not None \
                and self._client.get_transport().is_active():
            return self._client
        try:
            client = paramiko.SSHClient()
            if self.known_hosts.exists():
                client.load_host_keys(str(self.known_hosts))
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                self.host, port=self.port, username=self.user,
                key_filename=str(self.key_file),
                look_for_keys=False, allow_agent=False, timeout=8,
                banner_timeout=8, auth_timeout=8,
            )
            # Épingle l'empreinte au 1er contact (TOFU).
            try:
                self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
                client.save_host_keys(str(self.known_hosts))
            except OSError:
                pass
            self._client = client
            return client
        except Exception as exc:
            self._snapshot_error(f"connexion impossible : {exc}")
            self._client = None
            return None

    def _drop(self, reason: str) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._snapshot_error(reason)

    def _exec(self, cmd: str, timeout: float = 10.0):
        """Exécute une commande distante. Renvoie (code, stdout, stderr) ou None."""
        with self._lock:
            client = self._ensure_client()
            if client is None:
                return None
            try:
                _, out, err = client.exec_command(cmd, timeout=timeout)
                code = out.channel.recv_exit_status()
                return (code,
                        out.read().decode("utf-8", "replace"),
                        err.read().decode("utf-8", "replace"))
            except Exception as exc:
                self._drop(f"erreur SSH : {exc}")
                return None

    def upload(self, local: Path, remote: str, timeout: float = 60.0) -> str:
        """Envoie un fichier en SFTP (via `.part` puis renommage atomique).
        Renvoie "" si OK, sinon le message d'erreur (le lien n'est pas coupé :
        une erreur de fichier ne rend pas le serveur « hors ligne »)."""
        with self._lock:
            client = self._ensure_client()
            if client is None:
                return "serveur injoignable"
            try:
                sftp = client.open_sftp()
                try:
                    sftp.get_channel().settimeout(timeout)
                    sftp.put(str(local), remote + ".part")
                    sftp.posix_rename(remote + ".part", remote)
                finally:
                    sftp.close()
                return ""
            except Exception as exc:
                return str(exc) or exc.__class__.__name__

    # ------------------------------------------------------------- sondage
    def _loop(self) -> None:
        while True:
            self._poll_once()
            time.sleep(self.poll_seconds)

    def _poll_once(self) -> None:
        res = self._exec(self._metrics_cmd)
        if res is None:
            return  # _snapshot_error a déjà noté la cause ; on garde les valeurs
        _, out, _ = res
        self._apply_metrics(out)

    def _apply_metrics(self, out: str) -> None:
        raw: dict[str, str] = {}
        services: dict[str, str] = {}
        for line in out.splitlines():
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.startswith("svc:"):
                services[key[4:]] = val.strip()
            else:
                raw[key] = val.strip()

        cpu_pct = self._cpu_percent(raw.get("cpu", ""))
        snap: dict = {"online": True, "error": "", "services": services}
        snap["host"] = raw.get("host", self.host)
        snap["uptime"] = _to_int(raw.get("uptime"))
        snap["nproc"] = _to_int(raw.get("nproc")) or 1
        snap["cpu_pct"] = cpu_pct
        mem_total = _to_int(raw.get("mem_total_kb")) * 1024
        mem_avail = _to_int(raw.get("mem_avail_kb")) * 1024
        snap["mem_total"] = mem_total
        snap["mem_used"] = max(0, mem_total - mem_avail)
        snap["disk_total"] = _to_int(raw.get("disk_size"))
        snap["disk_used"] = _to_int(raw.get("disk_used"))
        temp = _to_int(raw.get("temp"))
        snap["temp_c"] = round(temp / 1000.0, 1) if temp else None
        snap["ts"] = time.time()
        mem_pct = snap["mem_used"] / mem_total * 100.0 if mem_total else None
        with self._snap_lock:
            self._snapshot = snap
            self._history.append((snap["ts"], cpu_pct, mem_pct))

    def _cpu_percent(self, cpu_line: str) -> float | None:
        """% CPU calculé par delta entre deux sondages (pas de sleep distant)."""
        try:
            nums = [int(x) for x in cpu_line.split()]
        except ValueError:
            return None
        if len(nums) < 5:
            return None
        total = sum(nums)
        idle = nums[3] + nums[4]           # idle + iowait
        pct = None
        if self._prev_cpu is not None:
            d_total = total - self._prev_cpu[0]
            d_idle = idle - self._prev_cpu[1]
            if d_total > 0:
                pct = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
        self._prev_cpu = (total, idle)
        return pct

    def _snapshot_error(self, reason: str) -> None:
        with self._snap_lock:
            self._snapshot = dict(self._snapshot)
            self._snapshot["online"] = False
            self._snapshot["error"] = reason

    # ------------------------------------------------------------- actions
    def run_action(self, service: dict, action: str) -> dict:
        """start/stop/restart d'un service (bloquant — à lancer via async_call).

        Rafraîchit l'état du service juste après et le reporte dans le snapshot.
        Renvoie {ok, status, error}.
        """
        unit = service.get("unit", "")
        if action not in ("start", "stop", "restart") or not unit:
            return {"ok": False, "status": "", "error": "action invalide"}
        prefix = "sudo " if service.get("use_sudo", True) else ""
        res = self._exec(f"{prefix}systemctl {action} {shlex.quote(unit)}", timeout=40)
        if res is None:
            return {"ok": False, "status": "", "error": "serveur injoignable"}
        code, _, err = res
        # Nouvel état (immédiat) pour rafraîchir le badge sans attendre le poll.
        status = ""
        st = self._exec(f"systemctl is-active {shlex.quote(unit)}", timeout=8)
        if st is not None:
            status = st[1].strip()
            with self._snap_lock:
                self._snapshot = dict(self._snapshot)
                svcs = dict(self._snapshot.get("services", {}))
                svcs[unit] = status
                self._snapshot["services"] = svcs
        return {"ok": code == 0, "status": status, "error": err.strip()}


def _to_int(val) -> int:
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return 0


def get_link(app):
    """Instance unique du lien serveur pour l'app (None si non configuré).

    Lit la section ``[server]`` (hôte : ``SERVER_HOST`` du .env, sinon
    ``host``) ; renvoie None si aucun hôte n'est renseigné (l'écran affiche
    alors « non configuré »).
    """
    if not hasattr(app, "_server_link"):
        from config import load_server_host
        cfg = dict(app.config.get("server", {}))
        host = load_server_host() or str(cfg.get("host", "")).strip()
        link = None
        if host:
            cfg["host"] = host
            link = ServerLink(cfg)
            link.start()
            # Sauvegarde quotidienne des bases du Pi sur ce serveur ([server.backup]).
            backup_cfg = cfg.get("backup", {})
            if backup_cfg.get("enabled", True):
                from modules.server.backup import ServerBackup, default_files
                link.backup = ServerBackup(link, backup_cfg, default_files())
                link.backup.start()
        app._server_link = link
    return app._server_link
