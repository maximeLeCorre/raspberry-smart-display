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
import urllib.error
import urllib.request
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


def normalize_riot_id(game_name: str | None, tag_line: str | None) -> str:
    """Clé normalisée 'nom#tag' (minuscules) pour comparer à la liste d'amis."""
    return f"{(game_name or '').strip().lower()}#{(tag_line or '').strip().lower()}"


def _http_get(url: str, headers: dict | None = None, timeout: float = 6.0) -> bytes | None:
    """GET brut (bytes), ou None en cas d'erreur réseau/HTTP."""
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None


class Champions:
    """Table id -> nom/alias de champion (Community Dragon), chargée une fois."""

    def __init__(self):
        self._names: dict[int, str] | None = None
        self._alias: dict[int, str] | None = None

    def _load(self) -> None:
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
        if self._names is None:
            self._load()
        return (self._names or {}).get(champion_id or 0, "")

    def alias(self, champion_id: int) -> str:
        if self._alias is None:
            self._load()
        return (self._alias or {}).get(champion_id or 0, "")


class RiotWeb:
    """Client de l'API Web Riot (clé requise), tolérant aux erreurs."""

    def __init__(self, api_key: str | None, platform: str, regional: str):
        self.api_key = (api_key or "").strip() or None
        self.platform = platform          # ex. "euw1"
        self.regional = regional          # ex. "europe"
        self._puuid_cache: dict[tuple[str, str], str | None] = {}
        self._match_cache: dict[str, dict] = {}

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
        if key in self._puuid_cache:
            return self._puuid_cache[key]
        account = self._get(
            self._regional_host(),
            f"/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}")
        puuid = account.get("puuid") if account else None
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

    def recent_match_ids(self, puuid: str, count: int = 10):
        return self._get(self._regional_host(),
                         f"/lol/match/v5/matches/by-puuid/{puuid}/ids?count={count}")

    def match(self, match_id: str):
        if match_id in self._match_cache:
            return self._match_cache[match_id]
        data = self._get(self._regional_host(), f"/lol/match/v5/matches/{match_id}")
        if data is not None:
            self._match_cache[match_id] = data
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


# ----------------------------------------------------- historique / bilan
QUEUE_NAMES = {
    420: "Classé Solo/Duo", 440: "Classé Flex", 400: "Normale Draft",
    430: "Normale Aveugle", 450: "ARAM", 490: "Normale (Swiftplay)",
    700: "Clash", 830: "Co-op vs IA", 1700: "Arena", 1900: "URF",
}


def _p_cs(p: dict) -> int:
    return (p.get("totalMinionsKilled", 0) or 0) + (p.get("neutralMinionsKilled", 0) or 0)


def _dur_seconds(info: dict) -> int:
    d = info.get("gameDuration", 0) or 0
    return d // 1000 if d > 10000 else d


def _when(game_creation_ms) -> str:
    import time
    try:
        return time.strftime("%d/%m %H:%M", time.localtime((game_creation_ms or 0) / 1000))
    except (TypeError, ValueError, OSError):
        return ""


def _summarize_match(match: dict, my_puuid: str, friends: set[str] | None) -> dict | None:
    """Bilan détaillé (10 joueurs + perso) depuis un match-v5."""
    friends = friends or set()
    info = match.get("info", {})
    parts = info.get("participants", [])
    if not parts:
        return None
    players, mine = [], None
    for p in parts:
        is_self = bool(my_puuid) and p.get("puuid") == my_puuid
        name = p.get("riotIdGameName") or p.get("summonerName") or ""
        tag = p.get("riotIdTagline") or ""
        players.append({
            "name": name,
            "championId": p.get("championId", 0) or 0,
            "championName": p.get("championName", "") or "",
            "team": p.get("teamId", 0) or 0,
            "isSelf": is_self,
            "isFriend": (not is_self) and normalize_riot_id(name, tag) in friends,
            "kda": [p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0)],
            "metrics": {
                "dmg": p.get("totalDamageDealtToChampions", 0) or 0,
                "taken": p.get("totalDamageTaken", 0) or 0,
                "gold": p.get("goldEarned", 0) or 0,
                "cs": _p_cs(p),
                "vision": p.get("visionScore", 0) or 0,
                "heal": p.get("totalHeal", 0) or 0,
            },
        })
        if is_self:
            mine = p
    mine = mine or parts[0]
    return {
        "win": bool(mine.get("win")),
        "queue": QUEUE_NAMES.get(info.get("queueId", 0), "Partie"),
        "duration": _dur_seconds(info),
        "me": {
            "championId": mine.get("championId", 0) or 0,
            "championName": mine.get("championName", "") or "",
            "kda": [mine.get("kills", 0), mine.get("deaths", 0), mine.get("assists", 0)],
            "cs": _p_cs(mine),
            "gold": mine.get("goldEarned", 0) or 0,
            "damage": mine.get("totalDamageDealtToChampions", 0) or 0,
            "level": mine.get("champLevel", 0) or 0,
        },
        "players": players,
    }


def build_match_history(riot: RiotWeb, my_puuid: str, count: int = 10) -> list[dict]:
    """Liste résumée des N dernières parties (pour l'accueil)."""
    if not (riot and my_puuid):
        return []
    ids = riot.recent_match_ids(my_puuid, max(1, min(int(count or 10), 20))) or []
    out = []
    for mid in ids:
        match = riot.match(mid)
        if not match:
            continue
        info = match.get("info", {})
        parts = info.get("participants", [])
        mine = next((p for p in parts if p.get("puuid") == my_puuid),
                    parts[0] if parts else None)
        if mine is None:
            continue
        out.append({
            "gameId": match.get("metadata", {}).get("matchId"),
            "championId": mine.get("championId", 0) or 0,
            "championName": mine.get("championName", "") or "",
            "win": bool(mine.get("win")),
            "kda": [mine.get("kills", 0), mine.get("deaths", 0), mine.get("assists", 0)],
            "cs": _p_cs(mine),
            "queue": QUEUE_NAMES.get(info.get("queueId", 0), "Partie"),
            "duration": _dur_seconds(info),
            "when": _when(info.get("gameCreation", 0)),
        })
    return out


def build_match_detail(riot: RiotWeb, my_puuid: str, match_id,
                       friends: set[str] | None = None) -> dict | None:
    """Bilan d'une partie : `match_id` donné, ou la **dernière** si None."""
    if not (riot and my_puuid):
        return None
    if not match_id:
        ids = riot.recent_match_ids(my_puuid, 1)
        match_id = ids[0] if ids else None
    if not match_id:
        return None
    match = riot.match(match_id)
    if not match:
        return None
    return _summarize_match(match, my_puuid, friends)
