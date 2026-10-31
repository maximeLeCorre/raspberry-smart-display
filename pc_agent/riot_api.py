"""Lecture de la Live Client Data API locale de Riot.

L'API n'est disponible QUE pendant un match, sur https://127.0.0.1:2999.
Le certificat est auto-signé : on désactive la vérification SSL pour CETTE
URL locale uniquement (aucune donnée sensible, tout reste sur la machine).
"""

from __future__ import annotations

import urllib3
import requests

from objectives import compute_objectives

# On coupe l'avertissement SSL lié à verify=False (certificat auto-signé local).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ALL_GAME_DATA_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"


def get_all_game_data(timeout: float = 1.0) -> dict | None:
    """Renvoie les données brutes de la partie, ou None si indisponible.

    None signifie : pas en partie, API pas encore prête, ou erreur réseau.
    """
    try:
        response = requests.get(ALL_GAME_DATA_URL, verify=False, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _format_event(e: dict) -> str | None:
    """Transforme un événement de la Live Client API en texte français court.

    Renvoie None pour les événements non affichés (GameStart, MinionsSpawning...).
    """
    name = e.get("EventName")
    k = e.get("KillerName", "")
    if name == "ChampionKill":
        return f"{k} a tué {e.get('VictimName', '')}"
    if name == "Multikill":
        return f"{k} multikill x{e.get('KillStreak', '')}"
    if name == "FirstBlood":
        return f"First Blood : {e.get('Recipient', '')}"
    if name == "Ace":
        return f"ACE ({e.get('AcingTeam', '')})"
    if name == "DragonKill":
        return f"{k} a pris le Dragon {e.get('DragonType', '')}".strip()
    if name == "BaronKill":
        return f"{k} a pris le Baron Nashor"
    if name == "HeraldKill":
        return f"{k} a pris le Héraut"
    if name == "TurretKilled":
        return f"Tourelle détruite ({k})"
    if name == "InhibKilled":
        return f"Inhibiteur détruit ({k})"
    return None


def _riot_id(player: dict) -> tuple[str, str]:
    """(gameName, tagLine) d'un joueur de la Live Client API (plusieurs formats)."""
    name = player.get("riotIdGameName") or ""
    tag = player.get("riotIdTagLine") or ""
    if not name:
        riot_id = player.get("riotId") or player.get("summonerName", "") or ""
        if "#" in riot_id:
            name, tag = riot_id.split("#", 1)
        else:
            name = riot_id
    return name, tag


def summarize_full(data: dict, id_resolver=None) -> dict:
    """Résumé complet de la partie : scoreboard des 10 joueurs + événements.

    `id_resolver` : fonction nom_de_champion -> championId (ex. la LCU), pour que
                    le Pi affiche les icônes. Optionnel.

    Chaque joueur porte son **Riot ID** (`riotId` = 'Nom#TAG') : le Pi s'en sert
    pour enrichir son dossier au clic (il résout le PUUID et interroge l'API Web
    lui-même — l'agent n'a plus de clé).

    Ajoute aussi `game_mode` (CLASSIC, ARAM, ...) et, en Faille uniquement, les
    `objectives` (timers Dragon/Baron/Héraut) — infos peu accessibles en jeu.
    """
    game_data = data.get("gameData", {})
    active = data.get("activePlayer", {})
    me_name = active.get("riotIdGameName") or active.get("summonerName")
    game_mode = game_data.get("gameMode", "") or ""

    players = []
    team_scores = {"order": 0, "chaos": 0}
    for p in data.get("allPlayers", []) or []:
        scores = p.get("scores", {})
        team = p.get("team", "")
        kills = scores.get("kills", 0)
        if team == "ORDER":
            team_scores["order"] += kills
        elif team == "CHAOS":
            team_scores["chaos"] += kills
        name, tag = _riot_id(p)
        champion = p.get("championName", "")
        players.append({
            "name": name,
            "riotId": f"{name}#{tag}" if (name and tag) else "",
            "champion": champion,
            "championId": (id_resolver(champion) if id_resolver else 0) or 0,
            # Skin joué (n° dans le champion ; chroma inclus) : le Pi affiche son art.
            "skinId": int(p.get("skinID", 0) or 0),
            "position": p.get("position", ""),
            "team": team,
            "k": kills, "d": scores.get("deaths", 0), "a": scores.get("assists", 0),
            "cs": int(scores.get("creepScore", 0) or 0),
            "level": p.get("level", 0),
            "isDead": bool(p.get("isDead", False)),
            "respawn": round(p.get("respawnTimer", 0) or 0),
            "isSelf": name == me_name,
        })

    events = []
    for e in (data.get("events", {}).get("Events", []) or []):
        txt = _format_event(e)
        if txt:
            events.append(txt)
    events = events[-12:][::-1]  # les plus récents d'abord

    objectives = compute_objectives(data) if game_mode == "CLASSIC" else []

    return {
        "game_time": int(game_data.get("gameTime", 0)),
        "game_mode": game_mode,
        "scores": team_scores,
        "players": players,
        "events": events,
        "objectives": objectives,
        "self": {"gold": int(active.get("currentGold", 0) or 0)},
    }
