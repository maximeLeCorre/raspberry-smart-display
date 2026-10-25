"""Client de l'API Web officielle de Riot (nécessite une clé RIOT_API_KEY).

Sert à enrichir les détails d'un joueur quand on clique dessus : rang/LP,
niveau, winrate récent, champions mains (maîtrise). On interroge par PUUID,
récupéré via la LCU pendant la sélection de champions.

Routing : certains endpoints sont « plateforme » (euw1, na1, ...), d'autres
« régional » (europe, americas, asia). La clé dev expire toutes les 24 h.

Toutes les méthodes sont tolérantes aux erreurs (clé absente/expirée, 429,
404...) : elles renvoient None plutôt que de lever, pour ne jamais casser
la boucle de l'agent.
"""

from __future__ import annotations

from urllib.parse import quote

import requests


class RiotWeb:
    def __init__(self, api_key: str | None, platform: str, regional: str):
        self.api_key = api_key
        self.platform = platform      # ex. "euw1"
        self.regional = regional      # ex. "europe"
        self.session = requests.Session()
        if api_key:
            self.session.headers["X-Riot-Token"] = api_key
        # Cache (gameName, tagLine) -> vrai PUUID externe, pour éviter de
        # re-résoudre à chaque mise à jour (et ménager le quota).
        self._puuid_cache: dict[tuple[str, str], str | None] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, host: str, path: str, timeout: float = 3.0):
        if not self.api_key:
            return None
        try:
            resp = self.session.get(f"https://{host}{path}", timeout=timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            # 403 = clé invalide/expirée, 429 = quota, 404 = introuvable.
            if resp.status_code in (401, 403):
                print("[riot-web] Clé API refusée (401/403) : vérifier/renouveler RIOT_API_KEY.")
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _platform_host(self) -> str:
        return f"{self.platform}.api.riotgames.com"

    def _regional_host(self) -> str:
        return f"{self.regional}.api.riotgames.com"

    # --------------------------------------------------------- endpoints
    def account_by_riot_id(self, game_name: str, tag_line: str) -> dict | None:
        """Résout un Riot ID (gameName#tagLine) -> compte (dont le vrai PUUID).

        IMPORTANT : le PUUID donné par la LCU est un identifiant interne
        (format UUID) que l'API Web rejette ("Exception decrypting"). Le vrai
        PUUID externe (78 caractères) s'obtient uniquement par cet endpoint.
        """
        return self._get(
            self._regional_host(),
            f"/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}",
        )

    def resolve_puuid(self, game_name: str, tag_line: str) -> str | None:
        """Vrai PUUID externe pour un Riot ID, mis en cache."""
        if not game_name or not tag_line:
            return None
        key = (game_name, tag_line)
        if key in self._puuid_cache:
            return self._puuid_cache[key]
        account = self.account_by_riot_id(game_name, tag_line)
        puuid = account.get("puuid") if account else None
        self._puuid_cache[key] = puuid
        return puuid

    def summoner_by_puuid(self, puuid: str) -> dict | None:
        """Donne summonerLevel et l'id de summoner (pour d'autres endpoints)."""
        return self._get(self._platform_host(),
                          f"/lol/summoner/v4/summoners/by-puuid/{puuid}")

    def league_entries_by_puuid(self, puuid: str) -> list | None:
        """Entrées classées (solo/flex) : tier, rank, LP, wins, losses."""
        return self._get(self._platform_host(),
                          f"/lol/league/v4/entries/by-puuid/{puuid}")

    def mastery_top(self, puuid: str, count: int = 3) -> list | None:
        """Top champions par maîtrise (championId + masteryPoints + level)."""
        return self._get(self._platform_host(),
                         f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}")

    def mastery_on_champion(self, puuid: str, champion_id: int) -> dict | None:
        return self._get(self._platform_host(),
                         f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/by-champion/{champion_id}")

    def recent_match_ids(self, puuid: str, count: int = 10) -> list | None:
        return self._get(self._regional_host(),
                         f"/lol/match/v5/matches/by-puuid/{puuid}/ids?count={count}")

    def match(self, match_id: str) -> dict | None:
        return self._get(self._regional_host(), f"/lol/match/v5/matches/{match_id}")

    # ------------------------------------------------------- agrégations
    def recent_winrate(self, puuid: str, count: int = 10) -> dict | None:
        """Calcule le winrate sur les N dernières parties.

        Attention : coûteux (1 requête par match). On garde N petit.
        """
        ids = self.recent_match_ids(puuid, count)
        if not ids:
            return None
        wins = 0
        played = 0
        for match_id in ids:
            data = self.match(match_id)
            if not data:
                continue
            participants = data.get("info", {}).get("participants", [])
            for p in participants:
                if p.get("puuid") == puuid:
                    played += 1
                    if p.get("win"):
                        wins += 1
                    break
        if played == 0:
            return None
        return {"wins": wins, "losses": played - wins,
                "winrate": round(100 * wins / played)}
