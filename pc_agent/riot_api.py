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
