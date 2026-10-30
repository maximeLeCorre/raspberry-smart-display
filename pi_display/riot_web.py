"""Accès internet « League » **côté Pi** : API Web Riot + CDN (icônes/splash).

Depuis que le Pi est autonome, c'est LUI qui interroge l'API Web Riot (rangs,
winrate, mains, **historique des parties**) et les CDN (icônes Community Dragon,
splash Data Dragon) — l'agent PC ne sert plus qu'aux données **locales** (phase,
sélection, données de partie en cours via la Live Client Data API).

Implémenté en **stdlib `urllib`** (comme le flux RSS) pour ne pas ajouter de
dépendance au runtime du Pi. Toutes les méthodes sont tolérantes aux erreurs
(clé absente/invalide, 429, 404, hors-ligne) : elles renvoient None/partiel.

La clé (`RIOT_API_KEY`, permanente) et le compte (`[lol] summoner`) sont lus
depuis la config du Pi — voir `config.load_riot_key` et `app`.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from urllib.parse import quote

# Résumé des champions (id -> nom/alias) : CDN public, pas de clé.
CHAMPION_SUMMARY_URL = (
    "https://raw.communitydragon.org/latest/plugins/"
    "rcp-be-lol-game-data/global/default/v1/champion-summary.json"
)
# Icône carrée par championId (Community Dragon) et splash par alias (Data Dragon).
ICON_CDN_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
    "global/default/v1/champion-icons/{id}.png"
)
LOADING_ART_URL = "https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{alias}_0.jpg"

# ⚠️ L'API Riot est derrière Cloudflare : le User-Agent par défaut d'urllib
# (`Python-urllib/x`) est bloqué (HTTP 403, Cloudflare « error code: 1010 »). On
# force donc un User-Agent explicite sur TOUTES les requêtes.
USER_AGENT = "pi-display/1.0 (raspberry-smart-display)"

# Limite de débit (HTTP 429) : on attend `Retry-After` (borné) puis on réessaie.
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_MAX_WAIT = 10.0
# Parties match-v5 gardées en mémoire (~50-100 Ko chacune) : LRU borné.
MATCH_CACHE_SIZE = 64


def normalize_riot_id(game_name: str | None, tag_line: str | None) -> str:
    """Clé normalisée 'nom#tag' (minuscules) pour comparer à la liste d'amis."""
    return f"{(game_name or '').strip().lower()}#{(tag_line or '').strip().lower()}"


def _http_get(url: str, headers: dict | None = None, timeout: float = 6.0) -> bytes | None:
    """GET brut (bytes), ou None en cas d'erreur réseau/HTTP."""
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return resp.read()
        except urllib.error.HTTPError as exc:
            # Toujours appelé hors boucle de rendu (worker) : attendre est sans risque.
            if exc.code == 429 and attempt < RATE_LIMIT_RETRIES:
                try:
                    wait = float(exc.headers.get("Retry-After") or 1)
                except ValueError:
                    wait = 1.0
                print(f"[riot] Limite de débit (429) : nouvel essai dans {wait:.0f} s")
                time.sleep(min(max(wait, 0.5), RATE_LIMIT_MAX_WAIT))
                continue
            return None
        except (urllib.error.URLError, OSError, ValueError):
            return None
    return None


class Champions:
    """Table id -> nom/alias de champion (Community Dragon), chargée une fois."""

    def __init__(self):
        self._names: dict[int, str] | None = None
        self._alias: dict[int, str] | None = None
        self._retry_at = 0.0     # échec (Pi démarré avant le réseau) -> nouvel essai

    def _due(self) -> bool:
        return not self._names and time.monotonic() >= self._retry_at

    def _load(self) -> None:
        self._retry_at = time.monotonic() + 60
        self._names, self._alias = {}, {}
        raw = _http_get(CHAMPION_SUMMARY_URL, timeout=8)
        if not raw:
            return
        try:
            data = json.loads(raw)
        except ValueError:
            return
        for champ in data:
            cid = champ.get("id")
            if isinstance(cid, int) and cid > 0:
                self._names[cid] = champ.get("name", "")
                self._alias[cid] = champ.get("alias", "")

    def name(self, champion_id: int) -> str:
        if self._due():
            self._load()
        return (self._names or {}).get(champion_id or 0, "")

    def alias(self, champion_id: int) -> str:
        if self._due():
            self._load()
        return (self._alias or {}).get(champion_id or 0, "")


class RiotWeb:
    """Client de l'API Web Riot (clé requise), tolérant aux erreurs."""

    def __init__(self, api_key: str | None, platform: str, regional: str):
        self.api_key = (api_key or "").strip() or None
        self.platform = platform          # ex. "euw1"
        self.regional = regional          # ex. "europe"
        # Caches partagés entre workers (async_call) : protégés par un verrou.
        # PUUID : seules les RÉUSSITES sont gardées (un échec réseau/429 ne doit
        # pas rendre un joueur introuvable jusqu'au redémarrage).
        self._lock = threading.Lock()
        self._puuid_cache: dict[tuple[str, str], str] = {}
        self._match_cache: OrderedDict[str, dict] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, host: str, path: str):
        if not self.api_key:
            return None
        raw = _http_get(f"https://{host}{path}", headers={"X-Riot-Token": self.api_key})
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def _platform_host(self) -> str:
        return f"{self.platform}.api.riotgames.com"

    def _regional_host(self) -> str:
        return f"{self.regional}.api.riotgames.com"

    # --------------------------------------------------------- endpoints
    def resolve_puuid(self, game_name: str, tag_line: str) -> str | None:
        """Vrai PUUID externe pour un Riot ID (account-v1), mis en cache."""
        if not game_name or not tag_line:
            return None
        key = (game_name, tag_line)
        with self._lock:
            if key in self._puuid_cache:
                return self._puuid_cache[key]
        account = self._get(
            self._regional_host(),
            f"/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}")
        puuid = account.get("puuid") if account else None
        if puuid:
            with self._lock:
                self._puuid_cache[key] = puuid
        return puuid

    def summoner_by_puuid(self, puuid: str):
        return self._get(self._platform_host(),
                         f"/lol/summoner/v4/summoners/by-puuid/{puuid}")

    def league_entries_by_puuid(self, puuid: str):
        return self._get(self._platform_host(),
                         f"/lol/league/v4/entries/by-puuid/{puuid}")

    def mastery_top(self, puuid: str, count: int = 3):
        return self._get(self._platform_host(),
                         f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}")

    def mastery_on_champion(self, puuid: str, champion_id: int):
        return self._get(self._platform_host(),
                         f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/by-champion/{champion_id}")

    def recent_match_ids(self, puuid: str, count: int = 8):
        return self._get(self._regional_host(),
                         f"/lol/match/v5/matches/by-puuid/{puuid}/ids?count={count}")

    def match(self, match_id: str):
        with self._lock:
            if match_id in self._match_cache:
                self._match_cache.move_to_end(match_id)
                return self._match_cache[match_id]
        data = self._get(self._regional_host(), f"/lol/match/v5/matches/{match_id}")
        if data is not None:
            with self._lock:
                self._match_cache[match_id] = data
                while len(self._match_cache) > MATCH_CACHE_SIZE:
                    self._match_cache.popitem(last=False)
        return data

    def recent_winrate(self, puuid: str, count: int = 8):
        ids = self.recent_match_ids(puuid, count)
        if not ids:
            return None
        wins = played = 0
        for mid in ids:
            data = self.match(mid)
            if not data:
                continue
            for p in data.get("info", {}).get("participants", []):
                if p.get("puuid") == puuid:
                    played += 1
                    wins += 1 if p.get("win") else 0
                    break
        if played == 0:
            return None
        return {"wins": wins, "losses": played - wins, "winrate": round(100 * wins / played)}


# ----------------------------------------------------------- CDN images
def icon_bytes(champion_id: int) -> bytes | None:
    """Icône carrée d'un champion (PNG) via Community Dragon."""
    if not champion_id or champion_id <= 0:
        return None
    return _http_get(ICON_CDN_URL.format(id=champion_id), timeout=8)


def splash_bytes(champions: Champions, champion_id: int) -> bytes | None:
    """Art de chargement (portrait) via Data Dragon, par alias de champion."""
    alias = champions.alias(champion_id)
    if not alias:
        return None
    return _http_get(LOADING_ART_URL.format(alias=alias), timeout=8)


# ----------------------------------------------------- agrégations joueur
def build_player_info(riot: RiotWeb, champions: Champions, riot_id: str,
                      champion_id: int) -> dict:
    """Détails d'un joueur (au clic) : rang, niveau, maîtrise, winrate, mains.

    `riot_id` = 'Nom#TAG'. Renvoie au moins le champion si l'enrichissement
    échoue (clé absente, PUUID non résolu...).
    """
    info: dict = {"championId": champion_id, "championName": champions.name(champion_id)}
    if not (riot and riot.enabled) or "#" not in (riot_id or ""):
        info["error"] = "Clé Riot absente ou joueur inconnu."
        return info

    game_name, tag_line = riot_id.split("#", 1)
    puuid = riot.resolve_puuid(game_name.strip(), tag_line.strip())
    if not puuid:
        info["error"] = "Joueur introuvable."
        return info

    summoner = riot.summoner_by_puuid(puuid)
    if summoner:
        info["summonerLevel"] = summoner.get("summonerLevel")

    entries = riot.league_entries_by_puuid(puuid)
    if entries:
        ranks = {}
        for e in entries:
            label = {"RANKED_SOLO_5x5": "Solo/Duo",
                     "RANKED_FLEX_SR": "Flex"}.get(e.get("queueType", ""), e.get("queueType", ""))
            ranks[label] = {
                "tier": e.get("tier"), "rank": e.get("rank"), "lp": e.get("leaguePoints"),
                "wins": e.get("wins"), "losses": e.get("losses"),
            }
        info["ranks"] = ranks

    if champion_id:
        mastery = riot.mastery_on_champion(puuid, champion_id)
        if mastery:
            info["championMastery"] = {"level": mastery.get("championLevel"),
                                       "points": mastery.get("championPoints")}

    top = riot.mastery_top(puuid, count=3)
    if top:
        info["mains"] = [
            {"championId": m.get("championId"),
             "championName": champions.name(m.get("championId", 0)),
             "points": m.get("championPoints")}
            for m in top
        ]

    winrate = riot.recent_winrate(puuid, count=8)
    if winrate:
        info["recent"] = winrate
    return info


# NB : l'historique/bilan ne passe plus par l'API Web (match-v5 n'a pas les
# customs) mais par la LCU → stocké sur le Pi (`store.py`). Ce module ne sert
# plus qu'aux dossiers joueurs (rang/winrate/mains) et aux CDN icônes/splash.
