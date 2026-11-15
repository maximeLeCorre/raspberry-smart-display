"""Sondes HTTP du Pi vers les services de la VM (écran « Serveur », sans SSH).

Thread de fond (comme `rss_feed.py`) ; l'écran et les règles lisent `snapshot()` :
  - Rentrer : `/health` (API + MOTIS) et `/v1/status` (trajets témoins) toutes les
    `http_seconds`, `/v1/admin/stats` (jeton RENTRER_STATS_TOKEN) toutes les `stats_seconds` ;
  - push NexusLink : `/health` et `/v1/stats` (jeton PUSH_STATS_TOKEN) ; certificat
    auto-signé **épinglé** (empreinte SHA-256 vérifiée AVANT d'envoyer la requête, donc avant
    le jeton) : `[server.monitor] push_pin`, sinon épinglé au 1er contact dans `certs/push_pin` ;
  - expiration des certificats (lue à chaque connexion) ;
  - accès internet du Pi (`internet_check`) : si tout tombe en même temps, c'est peut-être
    le Pi qui est coupé, pas la VM (monitor.py n'accuse alors personne).

Adresses par défaut tirées de SERVER_HOST (rien de personnel dans config.toml) :
Rentrer = https://<ip-avec-tirets>.sslip.io, push = https://<ip>:8443.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .server_link import REPO_ROOT

PIN_FILE = REPO_ROOT / "certs" / "push_pin"


def default_urls(host: str) -> tuple[str, str]:
    """(Rentrer, push) déduits de l'IP de la VM ; ("", "") sans IP."""
    host = host.strip()
    if not host:
        return "", ""
    return f"https://{host.replace('.', '-')}.sslip.io", f"https://{host}:8443"


class PinMismatch(Exception):
    """Le serveur de push ne présente pas le certificat épinglé."""


def cert_days_left(not_after: str, now: float) -> int | None:
    """« Nov 14 12:00:00 2027 GMT » (getpeercert) -> jours restants."""
    try:
        return int((ssl.cert_time_to_seconds(not_after) - now) // 86400)
    except (ValueError, TypeError):
        return None


def der_not_after(der: bytes) -> str | None:
    """Date de fin d'un certificat DER (auto-signé : getpeercert() ne la donne pas)."""
    try:
        from cryptography import x509
        cert = x509.load_der_x509_certificate(der)
        end = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
        return end.strftime("%b %d %H:%M:%S %Y GMT")
    except Exception:
        return None


class Probes:
    def __init__(self, cfg: dict, host: str, rentrer_token: str = "", push_token: str = ""):
        rentrer, push = default_urls(host)
        self.rentrer_url = str(cfg.get("rentrer_url", "") or rentrer).rstrip("/")
        self.push_url = str(cfg.get("push_url", "") or push).rstrip("/")
        self.rentrer_token = rentrer_token
        self.push_token = push_token
        self.http_seconds = max(10, int(cfg.get("http_seconds", 30) or 30))
        self.stats_seconds = max(60, int(cfg.get("stats_seconds", 300) or 300))
        self.timeout = float(cfg.get("timeout", 8) or 8)
        check = str(cfg.get("internet_check", "1.1.1.1:443"))
        h, _, p = check.rpartition(":")
        self.internet = (h or check, int(p) if p.isdigit() else 443)
        self.pin = str(cfg.get("push_pin", "")).strip().lower()
        self.pin_file = Path(cfg.get("push_pin_file", "") or PIN_FILE)
        if not self.pin and self.pin_file.exists():
            self.pin = self.pin_file.read_text(encoding="utf-8").strip().lower()
        self._lock = threading.Lock()
        self._snap: dict = {"rentrer": {}, "push": {}, "internet": None, "ts": 0.0}
        self._stats_ts = 0.0
        self._thread = threading.Thread(target=self._loop, name="probes", daemon=True)

    def start(self) -> None:
        if self.rentrer_url or self.push_url:
            self._thread.start()

    def snapshot(self) -> dict:
        with self._lock:
            return {k: (dict(v) if isinstance(v, dict) else v) for k, v in self._snap.items()}

    # ------------------------------------------------------------------ boucle
    def _loop(self) -> None:
        while True:
            try:
                self.poll(stats=time.monotonic() - self._stats_ts >= self.stats_seconds
                          or not self._stats_ts)
            except Exception as exc:          # jamais de thread mort pour une réponse bizarre
                print(f"[probes] {exc}")
            time.sleep(self.http_seconds)

    def poll(self, stats: bool = False) -> None:
        now = time.time()
        rentrer = self._probe_rentrer(stats) if self.rentrer_url else {}
        push = self._probe_push(stats) if self.push_url else {}
        if stats:
            self._stats_ts = time.monotonic()
        internet = None
        if not rentrer.get("up") and not push.get("up"):
            internet = self._internet_ok()
        with self._lock:
            # Les stats ne sont relues que toutes les stats_seconds : on garde les dernières.
            for key, new in (("rentrer", rentrer), ("push", push)):
                if not stats and "stats" in self._snap[key]:
                    new.setdefault("stats", self._snap[key]["stats"])
                    new.setdefault("stats_ts", self._snap[key].get("stats_ts", 0.0))
                self._snap[key] = new
            self._snap["internet"] = internet
            self._snap["ts"] = now

    def _probe_rentrer(self, stats: bool) -> dict:
        res: dict = {"up": False, "motis": None, "status": None, "error": "", "ms": None,
                     "cert_days": None}
        try:
            t0 = time.monotonic()
            code, body, cert = self._get(self.rentrer_url + "/health")
            res["ms"] = round((time.monotonic() - t0) * 1000)
            res["up"] = code in (200, 503)            # 503 = API vivante, MOTIS absent
            res["motis"] = bool(body.get("motis")) if isinstance(body, dict) else None
            res["cert_days"] = cert_days_left((cert or {}).get("notAfter", ""), time.time())
            if code not in (200, 503):
                res["error"] = f"HTTP {code}"
            code, body, _ = self._get(self.rentrer_url + "/v1/status")
            if code == 200 and isinstance(body, dict):
                res["status"] = body
            if stats and self.rentrer_token:
                code, body, _ = self._get(self.rentrer_url + "/v1/admin/stats", self.rentrer_token)
                if code == 200 and isinstance(body, dict):
                    res["stats"], res["stats_ts"] = body, time.time()
                else:
                    res["stats_error"] = f"stats : HTTP {code}"
        except Exception as exc:
            res["error"] = _short(exc)
        return res

    def _probe_push(self, stats: bool) -> dict:
        res: dict = {"up": False, "error": "", "ms": None, "cert_days": None, "pin_error": False}
        try:
            t0 = time.monotonic()
            code, _, cert = self._get(self.push_url + "/health", pinned=True)
            res["ms"] = round((time.monotonic() - t0) * 1000)
            res["up"] = code == 200
            res["cert_days"] = cert_days_left((cert or {}).get("notAfter", ""), time.time())
            if code != 200:
                res["error"] = f"HTTP {code}"
            if stats and self.push_token and res["up"]:
                code, body, _ = self._get(self.push_url + "/v1/stats", self.push_token, pinned=True)
                if code == 200 and isinstance(body, dict):
                    res["stats"], res["stats_ts"] = body, time.time()
                else:
                    res["stats_error"] = f"stats : HTTP {code}"
        except PinMismatch:
            res["pin_error"] = True
            res["error"] = "certificat inattendu (épinglage)"
        except Exception as exc:
            res["error"] = _short(exc)
        return res

    def _internet_ok(self) -> bool:
        try:
            with socket.create_connection(self.internet, timeout=self.timeout):
                return True
        except OSError:
            return False

    # ------------------------------------------------------------------ HTTP
    def _get(self, url: str, token: str = "", pinned: bool = False):
        """GET -> (statut, JSON ou None, infos du certificat). Épinglage vérifié avant d'envoyer."""
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError("https seulement")
        if pinned:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE           # remplacé par l'empreinte, vérifiée ci-dessous
        else:
            ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443,
                                           timeout=self.timeout, context=ctx)
        try:
            conn.connect()
            cert = conn.sock.getpeercert()
            if pinned:
                der = conn.sock.getpeercert(binary_form=True) or b""
                self._check_pin(hashlib.sha256(der).hexdigest())
                cert = {"notAfter": der_not_after(der) or ""}
            headers = {"Accept": "application/json", "User-Agent": "pi-display"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            conn.request("GET", parts.path or "/", headers=headers)
            resp = conn.getresponse()
            raw = resp.read(65536)
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError:
                body = None
            return resp.status, body, cert
        finally:
            conn.close()

    def _check_pin(self, fp: str) -> None:
        if not self.pin:                              # 1er contact : on épingle (TOFU)
            self.pin = fp
            try:
                self.pin_file.parent.mkdir(parents=True, exist_ok=True)
                self.pin_file.write_text(fp + "\n", encoding="utf-8")
            except OSError:
                pass
        elif fp != self.pin:
            raise PinMismatch(fp)


def _short(exc: Exception) -> str:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "délai dépassé"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "certificat refusé"
    if isinstance(exc, ConnectionRefusedError):
        return "connexion refusée"
    return (str(exc) or exc.__class__.__name__)[:120]
