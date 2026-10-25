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

# Région (LCU) -> routing plateforme (API Web Riot) -> routing régional.
PLATFORM_BY_REGION = {
    "NA": "na1", "EUW": "euw1", "EUNE": "eun1", "KR": "kr", "BR": "br1",
    "LA1": "la1", "LA2": "la2", "OCE": "oc1", "TR": "tr1", "RU": "ru",
    "JP": "jp1", "PH": "ph2", "SG": "sg2", "TH": "th2", "TW": "tw2", "VN": "vn2",
}
REGIONAL_BY_PLATFORM = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "oc1": "americas", "euw1": "europe", "eun1": "europe", "tr1": "europe",
    "ru": "europe", "kr": "asia", "jp1": "asia", "ph2": "asia", "sg2": "asia",
    "th2": "asia", "tw2": "asia", "vn2": "asia",
}


def find_lcu_credentials() -> tuple[int, str] | None:
    """Retrouve (port, token) dans les arguments du process LeagueClientUx.

    Renvoie None si le client n'est pas lancé.
    """
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if (proc.info["name"] or "").lower() != CLIENT_PROCESS:
                continue
            args = proc.info["cmdline"] or []
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
        self._champions: dict[int, str] | None = None     # cache id -> nom
        self._champion_ids: dict[str, int] | None = None  # cache nom (minuscule) -> id

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

    def get_bytes(self, path: str, timeout: float = 3.0) -> bytes | None:
        resp = self._request(path, timeout)
        if resp is None or resp.status_code != 200:
            return None
        return resp.content

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
        return self.get_json(f"/lol-summoner/v1/summoners/{summoner_id}")

    def region_platform(self) -> tuple[str | None, str | None]:
        """Déduit (platform, regional) depuis la LCU. (None, None) si inconnu."""
        data = self.get_json("/riotclient/region-locale")
        if not data:
            return None, None
        region = (data.get("region") or "").upper()
        platform = PLATFORM_BY_REGION.get(region)
        regional = REGIONAL_BY_PLATFORM.get(platform) if platform else None
        return platform, regional

    def champion_icon(self, champion_id: int) -> bytes | None:
        """Icône carrée du champion (PNG), servie localement par le client."""
        if not champion_id or champion_id <= 0:
            return None
        return self.get_bytes(f"/lol-game-data/assets/v1/champion-icons/{champion_id}.png")

    def champion_name(self, champion_id: int) -> str:
        """Nom du champion depuis le résumé des champions (mis en cache)."""
        if not champion_id or champion_id <= 0:
            return ""
        if self._champions is None:
            self._load_champion_summary()
        return (self._champions or {}).get(champion_id, "")

    def champion_id_by_name(self, name: str) -> int:
        """Id d'un champion depuis son nom affiché (0 si inconnu)."""
        if not name:
            return 0
        if self._champion_ids is None:
            self._load_champion_summary()
        return (self._champion_ids or {}).get(name.lower(), 0)

    def _load_champion_summary(self) -> None:
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
        for champ in data:
            cid = champ.get("id")
            name = champ.get("name", "")
            if isinstance(cid, int) and cid > 0:
                self._champions[cid] = name
                if name:
                    self._champion_ids[name.lower()] = cid
