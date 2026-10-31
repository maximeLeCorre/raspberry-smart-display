"""Construction des données de sélection de champions envoyées au Pi.

Depuis que le Pi est autonome pour l'enrichissement Web (rangs, winrate, mains,
icônes, splash), l'agent ne fait plus que du **local** : il lit la session de
sélection via la LCU et transmet, pour chaque joueur de notre équipe, son
champion, sa position et son **Riot ID** (`gameName#tagLine`). Le Pi se charge
d'enrichir au clic (il résout le PUUID et interroge l'API Web lui-même).
"""

from __future__ import annotations

from lcu import LcuClient

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


def _skin_num(selected_skin_id, champ_id) -> int:
    """N° de skin dans le champion (0 = base) ; 0 si le skin ne correspond pas
    au champion affiché (intention de pick, skin pas encore choisi)."""
    sid = int(selected_skin_id or 0)
    return sid % 1000 if champ_id and sid // 1000 == champ_id else 0


def build_champ_select_payload(lcu: LcuClient) -> dict | None:
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

        # riotId = clé d'enrichissement côté Pi (vide si pseudo masqué).
        riot_id = f"{game_name}#{tag_line}" if (game_name and tag_line) else ""

        players.append({
            "riotId": riot_id,
            "championId": champ_id,
            "championName": lcu.champion_name(champ_id),
            # Skin choisi : `selectedSkinId` = championId*1000 + n° (chroma inclus).
            "skinId": _skin_num(cell.get("selectedSkinId"), champ_id),
            "position": POSITIONS.get((cell.get("assignedPosition") or "").lower(),
                                      cell.get("assignedPosition", "")),
            "gameName": game_name,
            "tagLine": tag_line,
            "isSelf": cell.get("cellId") == my_cell,
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
