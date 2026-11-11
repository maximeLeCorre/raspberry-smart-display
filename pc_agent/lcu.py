"""Accès à la LCU API (League Client Update) : l'API locale du CLIENT League.

Contrairement à la Live Client Data API (127.0.0.1:2999, uniquement en partie),
la LCU est disponible dès que le client est ouvert. Elle sert à connaître la
phase de jeu (menu, lobby, sélection, partie) et à lire la sélection de
champions (champions choisis, positions, pseudos de notre équipe).

Authentification : le client expose un port et un token aléatoires. On les lit
dans les arguments de lancement du process LeagueClientUx.exe
(--app-port=... / --remoting-auth-token=...). Auth HTTP Basic : user "riot",
mot de passe = le token. Le certificat est auto-signé -> verify=False (local).
"""

from __future__ import annotations

import time

import psutil
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CLIENT_PROCESS = "leagueclientux.exe"

# La LCU n'expose pas de résumé id->nom de champion fiable ; on le récupère
# depuis Community Dragon (CDN public, pas de clé). Chargé une seule fois.
CHAMPION_SUMMARY_URL = (
    "https://raw.communitydragon.org/latest/plugins/"
    "rcp-be-lol-game-data/global/default/v1/champion-summary.json"
)


def find_lcu_credentials() -> tuple[int, str] | None:
    """Retrouve (port, token) dans les arguments du process LeagueClientUx.

    Renvoie None si le client n'est pas lancé.
    """
    # Name only: reading every process's command line is slow on Windows.
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() != CLIENT_PROCESS:
                continue
            args = proc.cmdline() or []
            port = token = None
            for arg in args:
                if arg.startswith("--app-port="):
                    port = arg.split("=", 1)[1]
                elif arg.startswith("--remoting-auth-token="):
                    token = arg.split("=", 1)[1]
            if port and token:
                return int(port), token
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


class LcuClient:
    """Client HTTP léger pour la LCU, avec reconnexion paresseuse."""

    def __init__(self):
        self.port: int | None = None
        self.token: str | None = None
        self.session = requests.Session()
        self.session.verify = False
        self._champions: dict[int, str] | None = None      # cache id -> nom
        self._champion_ids: dict[str, int] | None = None   # cache nom/alias (minuscule) -> id
        self._summary_retry_at = 0.0   # échec de chargement -> nouvel essai après ce délai
        self._summoners: dict = {}     # summonerId -> summoner (names are stable)

    @property
    def connected(self) -> bool:
        return self.port is not None

    def connect(self) -> bool:
        creds = find_lcu_credentials()
        if creds is None:
            self.port = None
            return False
        self.port, self.token = creds
        self.session.auth = ("riot", self.token)
        return True

    def _url(self, path: str) -> str:
        return f"https://127.0.0.1:{self.port}{path}"

    def _request(self, path: str, timeout: float = 2.0):
        """Renvoie l'objet Response, ou None si indisponible."""
        if not self.connected and not self.connect():
            return None
        try:
            return self.session.get(self._url(path), timeout=timeout)
        except requests.RequestException:
            # Client fermé entre-temps : on force une reconnexion au prochain appel.
            self.port = None
            return None

    def get_json(self, path: str, timeout: float = 2.0):
        resp = self._request(path, timeout)
        if resp is None or resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _send(self, method: str, path: str, payload=None, timeout: float = 3.0) -> bool:
        """Sends a command to the client; True on a 2xx answer."""
        if not self.connected and not self.connect():
            return False
        try:
            resp = self.session.request(method, self._url(path), json=payload, timeout=timeout)
        except requests.RequestException:
            self.port = None  # client closed: reconnect on next call
            return False
        return 200 <= resp.status_code < 300

    def post(self, path: str, payload=None, timeout: float = 3.0) -> bool:
        return self._send("POST", path, payload, timeout)

    def patch(self, path: str, payload=None, timeout: float = 3.0) -> bool:
        return self._send("PATCH", path, payload, timeout)

    def delete(self, path: str, timeout: float = 3.0) -> bool:
        return self._send("DELETE", path, None, timeout)

    # ----------------------------------------------------------- endpoints
    def gameflow_phase(self) -> str | None:
        """Phase courante : 'None', 'Lobby', 'Matchmaking', 'ReadyCheck',
        'ChampSelect', 'InProgress', 'PreEndOfGame', 'EndOfGame', ...
        Renvoie None si le client est injoignable (fermé)."""
        return self.get_json("/lol-gameflow/v1/gameflow-phase")

    def champ_select_session(self) -> dict | None:
        return self.get_json("/lol-champ-select/v1/session")

    def current_summoner(self) -> dict | None:
        return self.get_json("/lol-summoner/v1/current-summoner")

    def summoner_by_id(self, summoner_id) -> dict | None:
        """Infos d'un summoner par son id local (gameName/tagLine si visibles)."""
        if not summoner_id:
            return None
        if summoner_id not in self._summoners:
            found = self.get_json(f"/lol-summoner/v1/summoners/{summoner_id}")
            if not found:
                return None
            self._summoners[summoner_id] = found
        return self._summoners[summoner_id]

    def champion_name(self, champion_id: int) -> str:
        """Nom du champion depuis le résumé des champions (mis en cache)."""
        if not champion_id or champion_id <= 0:
            return ""
        if self._summary_due():
            self._load_champion_summary()
        return (self._champions or {}).get(champion_id, "")

    def champion_id_by_name(self, name: str, raw_name: str = "") -> int:
        """Id d'un champion (0 si inconnu), de préférence depuis le nom technique
        du Live Client (`rawChampionName` = « game_character_displayname_MasterYi »
        -> alias, indépendant de la langue), sinon depuis le nom affiché.

        ⚠️ Le nom affiché du Live Client est **localisé** (« Maître Yi ») alors que
        la table des champions est en anglais (« Master Yi »)."""
        if not (name or raw_name):
            return 0
        if self._summary_due():
            self._load_champion_summary()
        ids = self._champion_ids or {}
        alias = (raw_name or "").rsplit("_", 1)[-1]
        return ids.get(alias.lower(), 0) or ids.get((name or "").lower(), 0)

    def _summary_due(self) -> bool:
        """Table à (re)charger : jamais chargée, ou dernier essai raté il y a plus
        d'une minute. ⚠️ Lancé à l'ouverture de session, l'agent démarre souvent
        avant le réseau : une table vide gardée à vie viderait tous les noms."""
        return not self._champions and time.monotonic() >= self._summary_retry_at

    def _load_champion_summary(self) -> None:
        self._summary_retry_at = time.monotonic() + 60
        self._champions = {}
        self._champion_ids = {}
        try:
            resp = requests.get(CHAMPION_SUMMARY_URL, timeout=8)
        except requests.RequestException:
            return  # hors ligne : les noms resteront vides (repli silencieux)
        if resp.status_code != 200:
            return
        try:
            data = resp.json()
        except ValueError:
            return
        # ⚠️ La table contient aussi des variantes de mode de jeu (ids 60xxx, alias
        # « Jade_Tristana ») au MÊME nom que le vrai champion : par id croissant +
        # setdefault, le nom désigne toujours le vrai (sinon icônes de la variante).
        for champ in sorted(data, key=lambda c: c.get("id") or 0):
            cid = champ.get("id")
            name = champ.get("name", "")
            alias = champ.get("alias", "")
            if isinstance(cid, int) and cid > 0:
                self._champions[cid] = name
                for key in (name, alias):
                    if key:
                        self._champion_ids.setdefault(key.lower(), cid)
