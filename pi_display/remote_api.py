"""API HTTP « télécommande » du Pi (montre, curl…) : état de l'agent + actions.

Routes (jeton `REMOTE_API_TOKEN` du .env en `Authorization: Bearer <jeton>` ;
vide = accès ouvert, comme le WebSocket en test local) :
    GET  /state?v=<version>&wait=<s>   état courant ; si `v` = version courante,
                                       la réponse **attend** le prochain
                                       changement (long polling, ≤ `wait` s)
    POST /action  {"action": ...}      action d'un module (accept, swap…)
    POST /push/register {"token": hex}  jeton APNs de la montre (push_apns.py)
    GET  /asset/<module>/<nom>         fichier d'un module (icône de champion :
                                       /asset/league/icon/<id>), servi DANS le
                                       thread HTTP (fournisseur thread-safe)

Le serveur tourne dans ses propres threads (un par requête) et ne touche jamais
l'état de l'App : la boucle principale **publie** un instantané (`RemoteState`),
et une action est **remise** à la boucle (queue réseau) qui répond via
`RemoteRequest` — la logique reste dans les modules, sur le thread principal.
"""

from __future__ import annotations

import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_WAIT = 30.0          # long polling : attente max d'une requête (s)
ACTION_TIMEOUT = 2.0     # délai max pour que la boucle traite une action (s)
MAX_BODY = 4096
ASSET_MAX_AGE = 86400    # la montre garde les icônes en cache (s)


class RemoteState:
    """Instantané publié par la boucle principale, lu par les requêtes HTTP."""

    def __init__(self):
        self._cond = threading.Condition()
        self.version = 0
        self.snapshot: dict = {}
        self.published_at = time.time()   # horodatage de la version (latence côté client)

    def publish(self, snapshot: dict) -> None:
        """Nouvelle version seulement si le contenu change (réveille les attentes)."""
        with self._cond:
            if snapshot == self.snapshot:
                return
            self.snapshot = snapshot
            self.published_at = time.time()
            self.version += 1
            self._cond.notify_all()

    def wait(self, known: int | None, timeout: float) -> tuple[int, dict]:
        """(version, instantané) dès que la version diffère de `known`."""
        with self._cond:
            if known is not None:
                self._cond.wait_for(lambda: self.version != known, timeout)
            return self.version, self.snapshot


class RemoteRequest:
    """Action remise à la boucle principale ; elle y répond par `reply()`."""

    def __init__(self, body: dict):
        self.body = body
        self.status = 504
        self.result: dict = {"ok": False, "error": "délai dépassé"}
        self._done = threading.Event()

    def reply(self, status: int, result: dict) -> None:
        self.status, self.result = status, result
        self._done.set()

    def wait(self, timeout: float) -> bool:
        return self._done.wait(timeout)


class RemoteServer:
    """Serveur HTTP/1.1 (keep-alive) en thread démon."""

    def __init__(self, host: str, port: int, state: RemoteState, event_queue,
                 token: str = "", assets=None, push_register=None):
        self.state = state
        self.assets = assets      # (module, nom) -> (octets, type MIME) | None
        self.push_register = push_register   # jeton APNs -> bool (thread-safe)
        self.event_queue = event_queue
        self.token = token or ""
        self._httpd = ThreadingHTTPServer((host, port), self._handler_class())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]

    def start(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, name="remote-api",
                         daemon=True).start()
        auth = "jeton requis" if self.token else "ouverte (aucun jeton)"
        print(f"[remote] API HTTP en écoute sur le port {self.port} ({auth})")

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"   # connexion gardée ouverte (latence)

            def log_message(self, *args):    # pas une ligne de journal par requête
                pass

            def setup(self):
                # Une ligne par CONNEXION (keep-alive : rare) : qui se connecte et quand
                # (montre en Wi-Fi direct, ou relayée par l'iPhone = IP de l'iPhone).
                super().setup()
                print(f"[remote] connexion de {self.client_address[0]}")

            def _send(self, status: int, obj: dict) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _send_bytes(self, data: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                # JSON (listes, horaires) = dynamique ; fichiers (icônes, sons) = cache.
                cache = "no-store" if "json" in content_type else f"private, max-age={ASSET_MAX_AGE}"
                self.send_header("Cache-Control", cache)
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                if not server.token:
                    return True
                given = self.headers.get("Authorization", "")
                ok = hmac.compare_digest(given.encode(), f"Bearer {server.token}".encode())
                if not ok:
                    self._send(401, {"ok": False, "error": "jeton invalide"})
                return ok

            def do_GET(self):
                url = urlparse(self.path)
                if url.path.startswith("/asset/"):
                    return self._asset(url.path[len("/asset/"):])
                if url.path != "/state":
                    return self._send(404, {"ok": False, "error": "route inconnue"})
                if not self._authorized():
                    return
                query = parse_qs(url.query)
                try:
                    known = int(query["v"][0]) if "v" in query else None
                    wait = min(MAX_WAIT, max(0.0, float(query.get("wait", [MAX_WAIT])[0])))
                except ValueError:
                    return self._send(400, {"ok": False, "error": "paramètre invalide"})
                version, snapshot = server.state.wait(known, wait)
                self._send(200, {"v": version, "t": round(server.state.published_at, 3),
                                 **snapshot})

            def _asset(self, path: str) -> None:
                if not self._authorized():
                    return
                module, _, name = path.partition("/")
                found = server.assets(module, name) if server.assets and name else None
                if not found:
                    return self._send(404, {"ok": False, "error": "fichier introuvable"})
                self._send_bytes(*found)

            def do_POST(self):
                path = urlparse(self.path).path
                if path not in ("/action", "/push/register"):
                    return self._send(404, {"ok": False, "error": "route inconnue"})
                if not self._authorized():
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"ok": False, "error": "corps trop gros"})
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, {"ok": False, "error": "JSON invalide"})
                if path == "/push/register":
                    ok = bool(isinstance(body, dict) and server.push_register
                              and server.push_register(str(body.get("token", ""))))
                    return self._send(200 if ok else 400, {"ok": ok})
                if not isinstance(body, dict) or not body.get("action"):
                    return self._send(400, {"ok": False, "error": "champ 'action' manquant"})
                request = RemoteRequest(body)
                server.event_queue.put({"type": "_remote_action", "request": request})
                request.wait(ACTION_TIMEOUT)
                self._send(request.status, request.result)

        return Handler
