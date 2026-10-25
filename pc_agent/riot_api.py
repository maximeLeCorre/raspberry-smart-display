"""Lecture de la Live Client Data API locale de Riot.

L'API n'est disponible QUE pendant un match, sur https://127.0.0.1:2999.
Le certificat est auto-signé : on désactive la vérification SSL pour CETTE
URL locale uniquement (aucune donnée sensible, tout reste sur la machine).
"""

from __future__ import annotations

import urllib3
import requests

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


def summarize(data: dict) -> dict:
    """Extrait un résumé compact à envoyer au Pi.

    Renvoie : game_time, kda [k,d,a], gold, cs, level, score {order, chaos}.
    Tolérant aux champs manquants (structure de l'API susceptible de varier).
    """
    game_data = data.get("gameData", {})
    active = data.get("activePlayer", {})
    all_players = data.get("allPlayers", []) or []

    # On retrouve le joueur local pour lire son KDA / CS / niveau.
    my_name = active.get("summonerName") or active.get("riotIdGameName")
    me = None
    for player in all_players:
        if player.get("summonerName") == my_name:
            me = player
            break
        riot_id = player.get("riotId", "")
        if riot_id and riot_id.split("#")[0] == active.get("riotIdGameName"):
            me = player
            break

    scores = (me or {}).get("scores", {})
    kda = [
        scores.get("kills", 0),
        scores.get("deaths", 0),
        scores.get("assists", 0),
    ]
    cs = scores.get("creepScore", 0)
    level = (me or {}).get("level") or active.get("level", 0)
    gold = active.get("currentGold", 0)

    # Score des équipes = somme des kills par camp (ORDER = bleu, CHAOS = rouge).
    order = sum(
        p.get("scores", {}).get("kills", 0)
        for p in all_players if p.get("team") == "ORDER"
    )
    chaos = sum(
        p.get("scores", {}).get("kills", 0)
        for p in all_players if p.get("team") == "CHAOS"
    )

    return {
        "game_time": int(game_data.get("gameTime", 0)),
        "kda": kda,
        "gold": int(gold or 0),
        "cs": int(cs or 0),
        "level": int(level or 0),
        "score": {"order": order, "chaos": chaos},
    }


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


def summarize_full(data: dict, id_resolver=None) -> dict:
    """Résumé complet de la partie : scoreboard des 10 joueurs + événements.

    `id_resolver` : fonction nom_de_champion -> championId (ex. la LCU), pour
    permettre au Pi d'afficher les icônes. Optionnel.
    """
    game_data = data.get("gameData", {})
    active = data.get("activePlayer", {})
    me_name = active.get("riotIdGameName") or active.get("summonerName")

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
        name = p.get("riotIdGameName") or p.get("summonerName", "")
        champion = p.get("championName", "")
        players.append({
            "name": name,
            "champion": champion,
            "championId": (id_resolver(champion) if id_resolver else 0) or 0,
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

    return {
        "game_time": int(game_data.get("gameTime", 0)),
        "scores": team_scores,
        "players": players,
        "events": events,
        "self": {"gold": int(active.get("currentGold", 0) or 0)},
    }
