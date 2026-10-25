"""Construction des données de sélection de champions envoyées au Pi,
et des détails d'un joueur (au clic).

On combine :
  - la LCU (session de sélection, icônes de champions, pseudos de notre équipe) ;
  - l'API Web Riot (rang, niveau, winrate, champions mains) pour enrichir.
"""

from __future__ import annotations

import base64

import requests

from lcu import LcuClient
from riot_web import RiotWeb

# Art de chargement (portrait) depuis Data Dragon, par alias de champion.
LOADING_ART_URL = "https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{alias}_0.jpg"

# Phases de sélection -> libellé français.
SELECT_PHASES = {
    "PLANNING": "Préparation", "BAN_PICK": "Sélection",
    "FINALIZATION": "Finalisation", "GAME_STARTING": "Lancement",
}

# Positions LoL -> libellé court français.
POSITIONS = {
    "top": "Top", "jungle": "Jungle", "middle": "Mid",
    "bottom": "ADC", "utility": "Support", "": "",
}


def icon_b64(lcu: LcuClient, champion_id: int) -> str | None:
    """Icône d'un champion en base64 (demandée à la carte par le Pi)."""
    raw = lcu.champion_icon(champion_id)
    if not raw:
        return None
    return base64.b64encode(raw).decode("ascii")


def splash_b64(lcu: LcuClient, champion_id: int) -> str | None:
    """Art de chargement (portrait) d'un champion en base64 (demandé au clic)."""
    alias = lcu.champion_alias(champion_id)
    if not alias:
        return None
    try:
        resp = requests.get(LOADING_ART_URL.format(alias=alias), timeout=8)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return base64.b64encode(resp.content).decode("ascii")


def build_champ_select_payload(lcu: LcuClient, riot: RiotWeb | None = None) -> dict | None:
    """Résumé de la sélection pour NOTRE équipe (les 5, dont nous).

    Renvoie None si on n'est pas en sélection.
    """
    session = lcu.champ_select_session()
    if not session:
        return None

    my_cell = session.get("localPlayerCellId")
    players = []
    for cell in session.get("myTeam", []):
        # championId = pick verrouillé ; sinon l'intention de pick.
        champ_id = cell.get("championId") or cell.get("championPickIntentId") or 0

        summoner_id = cell.get("summonerId")
        game_name = cell.get("gameName", "") or ""
        tag_line = cell.get("tagLine", "") or ""

        # Le Riot ID est parfois absent de la session : on le complète via la LCU.
        if (not game_name or not tag_line) and summoner_id:
            summoner = lcu.summoner_by_id(summoner_id) or {}
            game_name = game_name or summoner.get("gameName", "") or ""
            tag_line = tag_line or summoner.get("tagLine", "") or ""

        # On résout le VRAI PUUID externe (le PUUID LCU ne marche pas avec
        # l'API Web). Vide si pseudo masqué / pas de clé -> pas d'enrichissement.
        puuid = ""
        if riot and riot.enabled and game_name and tag_line:
            puuid = riot.resolve_puuid(game_name, tag_line) or ""

        players.append({
            "cellId": cell.get("cellId"),
            "summonerId": summoner_id,
            "puuid": puuid,
            "championId": champ_id,
            "championName": lcu.champion_name(champ_id),
            "position": POSITIONS.get((cell.get("assignedPosition") or "").lower(),
                                      cell.get("assignedPosition", "")),
            "gameName": game_name,
            "tagLine": tag_line,
            "isSelf": cell.get("cellId") == my_cell,
            # Les icônes ne sont plus envoyées ici : le Pi les réclame une à une
            # (message request_icon) et ne les reçoit qu'une fois chacune.
        })

    timer = session.get("timer", {}) or {}
    bans = session.get("bans", {}) or {}
    return {
        "phase": "champselect",
        "players": players,
        "timer": {
            "phase": SELECT_PHASES.get(timer.get("phase", ""), ""),
            "left": round((timer.get("adjustedTimeLeftInPhase", 0) or 0) / 1000),
        },
        "bans": {
            "myTeam": [c for c in bans.get("myTeamBans", []) if c],
            "theirTeam": [c for c in bans.get("theirTeamBans", []) if c],
        },
    }


def build_player_info(lcu: LcuClient, riot: RiotWeb | None,
                      puuid: str, summoner_id, champion_id: int) -> dict:
    """Détails d'un joueur (au clic). Champs manquants = None/absents.

    Sans clé Riot valide, on renvoie au moins ce qu'on a (souvent peu pour les
    autres joueurs) ; l'affichage s'adapte.
    """
    info: dict = {"puuid": puuid, "championId": champion_id,
                  "championName": lcu.champion_name(champion_id)}

    if not (riot and riot.enabled and puuid):
        info["error"] = "Clé Riot absente ou joueur sans PUUID."
        return info

    # Niveau d'invocateur.
    summoner = riot.summoner_by_puuid(puuid)
    if summoner:
        info["summonerLevel"] = summoner.get("summonerLevel")

    # Rang (solo & flex).
    entries = riot.league_entries_by_puuid(puuid)
    if entries:
        ranks = {}
        for e in entries:
            queue = e.get("queueType", "")
            label = {"RANKED_SOLO_5x5": "Solo/Duo",
                     "RANKED_FLEX_SR": "Flex"}.get(queue, queue)
            ranks[label] = {
                "tier": e.get("tier"), "rank": e.get("rank"),
                "lp": e.get("leaguePoints"),
                "wins": e.get("wins"), "losses": e.get("losses"),
            }
        info["ranks"] = ranks

    # Maîtrise sur le champion sélectionné.
    if champion_id:
        mastery = riot.mastery_on_champion(puuid, champion_id)
        if mastery:
            info["championMastery"] = {
                "level": mastery.get("championLevel"),
                "points": mastery.get("championPoints"),
            }

    # Champions mains (top maîtrise).
    top = riot.mastery_top(puuid, count=3)
    if top:
        info["mains"] = [
            {"championId": m.get("championId"),
             "championName": lcu.champion_name(m.get("championId", 0)),
             "points": m.get("championPoints")}
            for m in top
        ]

    # Winrate récent (quelques parties seulement, car coûteux).
    winrate = riot.recent_winrate(puuid, count=8)
    if winrate:
        info["recent"] = winrate

    return info
