"""Notifications push vers la montre (APNs, service d'Apple), envoyées par le Pi.

La montre s'enregistre via l'API télécommande (`POST /push/register`) ; son
jeton d'appareil est gardé dans `push.db` (SQLite, *.db : hors Git et hors
déploiement). Un module appelle `notify()` (ex. ready-check) : envoi dans un
thread, jamais dans la boucle de rendu.

APNs n'accepte que **HTTP/2** (d'où httpx[http2]) et une authentification par
jeton JWT ES256 signé avec la clé `.p8` APNs (`certs/`, copiée par deploy),
renouvelé toutes les 50 min (Apple : entre 20 et 60 min). Jeton d'appareil
refusé (400 BadDeviceToken / 410 Unregistered) → oublié.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "push.db"
PRODUCTION = "https://api.push.apple.com"     # builds TestFlight / App Store
SANDBOX = "https://api.sandbox.push.apple.com"
JWT_TTL = 50 * 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(team_id: str, key_id: str, key_pem: bytes, now: float | None = None) -> str:
    """Jeton d'authentification APNs (ES256), signature au format brut r||s."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    key = serialization.load_pem_private_key(key_pem, password=None)
    header = _b64(json.dumps({"alg": "ES256", "kid": key_id}).encode())
    claims = _b64(json.dumps({"iss": team_id, "iat": int(now or time.time())}).encode())
    r, s = decode_dss_signature(key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{header}.{claims}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


class PushSender:
    """Désactivé (no-op) si la config ou la clé manque : tout le reste marche sans."""

    def __init__(self, cfg: dict, db_path: Path = DB_PATH, client=None):
        self.team_id = cfg.get("team_id", "")
        self.key_id = cfg.get("key_id", "")
        self.topic = cfg.get("topic", "")
        self.base_url = SANDBOX if cfg.get("sandbox") else PRODUCTION
        key_path = ROOT.parent / cfg.get("key_file", "certs/apns_key.p8")
        self.key_pem = key_path.read_bytes() if key_path.exists() else b""
        self.enabled = bool(cfg.get("enabled") and self.team_id and self.key_id
                            and self.topic and self.key_pem)
        if cfg.get("enabled") and not self.enabled:
            print(f"[push] désactivé : config [push] incomplète ou clé absente ({key_path})")
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS devices (token TEXT PRIMARY KEY, added REAL)")
        self._db.commit()
        self._client = client          # httpx.Client HTTP/2, créé au 1er envoi
        self._jwt, self._jwt_at = "", 0.0

    # ------------------------------------------------------------ appareils
    def register(self, token: str) -> bool:
        token = (token or "").strip().lower()
        if not token or len(token) > 200 or any(c not in "0123456789abcdef" for c in token):
            return False
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO devices VALUES (?, ?)", (token, time.time()))
            self._db.commit()
        return True

    def tokens(self) -> list[str]:
        with self._lock:
            return [row[0] for row in self._db.execute("SELECT token FROM devices")]

    def _forget(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM devices WHERE token = ?", (token,))
            self._db.commit()

    # --------------------------------------------------------------- envoi
    def notify(self, aps: dict, collapse_id: str = "", ttl: int = 0, extra: dict | None = None) -> None:
        """Envoi en arrière-plan à tous les appareils. `ttl` (s) : au-delà, APNs
        jette la notification (un ready-check périmé n'a pas à arriver)."""
        if not self.enabled or not self.tokens():
            return
        payload = {"aps": aps, **(extra or {})}
        threading.Thread(target=self.send, args=(payload, collapse_id, ttl),
                         name="apns", daemon=True).start()

    def send(self, payload: dict, collapse_id: str = "", ttl: int = 0) -> dict[str, int]:
        """Envoi synchrone ; renvoie {jeton: statut HTTP} (journal + tests)."""
        headers = {"authorization": f"bearer {self._token()}", "apns-topic": self.topic,
                   "apns-push-type": "alert", "apns-priority": "10"}
        if collapse_id:
            headers["apns-collapse-id"] = collapse_id
        if ttl:
            headers["apns-expiration"] = str(int(time.time()) + ttl)
        body = json.dumps(payload).encode()
        results = {}
        for token in self.tokens():
            try:
                resp = self._http().post(f"{self.base_url}/3/device/{token}",
                                         headers=headers, content=body)
                status, reason = resp.status_code, resp.text
            except Exception as exc:        # réseau : on réessaiera au prochain événement
                status, reason = 0, str(exc)
                self._client = None
            results[token] = status
            if status == 410 or (status == 400 and "BadDeviceToken" in reason):
                self._forget(token)
            if status != 200:
                print(f"[push] {token[:8]}… → {status} {reason[:200]}")
        return results

    def _token(self) -> str:
        if not self._jwt or time.time() - self._jwt_at > JWT_TTL:
            self._jwt_at = time.time()
            self._jwt = make_jwt(self.team_id, self.key_id, self.key_pem, self._jwt_at)
        return self._jwt

    def _http(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(http2=True, timeout=10)
        return self._client
