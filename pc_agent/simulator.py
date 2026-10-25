"""Mode simulation : joue des scénarios sans lancer League, pour tester le Pi.

Scénarios (--scenario) :
  - full        : défaut -> sélection de champions -> partie -> défaut
  - champselect : reste en sélection de champions (test du clic sur un joueur)
  - game        : reste en partie (ancien comportement)

Répond aussi aux demandes d'infos joueur (clic sur un joueur) avec de fausses
données. À l'arrêt (Ctrl+C), repasse en mode par défaut puis se déconnecte.
"""

from __future__ import annotations

import time

from sender import Sender, msg_data, msg_player_info, msg_set_mode

# Équipe fictive (5 joueurs, dont nous). Pas d'icône -> le Pi affiche un
# placeholder avec le nom du champion.
FAKE_TEAM = [
    {"cellId": 0, "summonerId": 101, "puuid": "puuid-top",
     "championId": 86, "championName": "Garen", "position": "Top",
     "gameName": "BronzeWall", "tagLine": "EUW", "isSelf": False, "iconB64": None},
    {"cellId": 1, "summonerId": 102, "puuid": "puuid-jgl",
     "championId": 64, "championName": "Lee Sin", "position": "Jungle",
     "gameName": "GankMaster", "tagLine": "EUW", "isSelf": False, "iconB64": None},
    {"cellId": 2, "summonerId": 103, "puuid": "puuid-mid",
     "championId": 103, "championName": "Ahri", "position": "Mid",
     "gameName": "Moi", "tagLine": "EUW", "isSelf": True, "iconB64": None},
    {"cellId": 3, "summonerId": 104, "puuid": "puuid-adc",
     "championId": 22, "championName": "Ashe", "position": "ADC",
     "gameName": "FarmAndGo", "tagLine": "EUW", "isSelf": False, "iconB64": None},
    {"cellId": 4, "summonerId": 105, "puuid": "puuid-sup",
     "championId": 412, "championName": "Thresh", "position": "Support",
     "gameName": "HookOrFeed", "tagLine": "EUW", "isSelf": False, "iconB64": None},
]

# Détails fictifs renvoyés au clic, par PUUID.
FAKE_INFO = {
    "puuid-top": {"summonerLevel": 210, "ranks": {"Solo/Duo": {"tier": "GOLD", "rank": "II", "lp": 45, "wins": 120, "losses": 110}},
                  "championMastery": {"level": 7, "points": 230000},
                  "mains": [{"championName": "Garen", "points": 230000},
                            {"championName": "Darius", "points": 150000}],
                  "recent": {"wins": 5, "losses": 3, "winrate": 63}},
    "puuid-jgl": {"summonerLevel": 340, "ranks": {"Solo/Duo": {"tier": "PLATINUM", "rank": "IV", "lp": 12, "wins": 200, "losses": 190}},
                  "championMastery": {"level": 7, "points": 410000},
                  "mains": [{"championName": "Lee Sin", "points": 410000}],
                  "recent": {"wins": 4, "losses": 4, "winrate": 50}},
    "puuid-mid": {"summonerLevel": 156, "ranks": {"Solo/Duo": {"tier": "SILVER", "rank": "I", "lp": 88, "wins": 90, "losses": 85}},
                  "championMastery": {"level": 6, "points": 95000},
                  "mains": [{"championName": "Ahri", "points": 95000},
                            {"championName": "Lux", "points": 70000}],
                  "recent": {"wins": 6, "losses": 2, "winrate": 75}},
    "puuid-adc": {"summonerLevel": 275, "ranks": {"Solo/Duo": {"tier": "DIAMOND", "rank": "III", "lp": 30, "wins": 310, "losses": 290}},
                  "championMastery": {"level": 5, "points": 48000},
                  "mains": [{"championName": "Ashe", "points": 48000}],
                  "recent": {"wins": 5, "losses": 5, "winrate": 50}},
    "puuid-sup": {"summonerLevel": 98, "ranks": {"Solo/Duo": {"tier": "BRONZE", "rank": "II", "lp": 5, "wins": 40, "losses": 55}},
                  "championMastery": {"level": 4, "points": 22000},
                  "mains": [{"championName": "Thresh", "points": 22000}],
                  "recent": {"wins": 3, "losses": 5, "winrate": 38}},
}


def _fake_game_payload(elapsed: int) -> dict:
    kills = elapsed // 60
    deaths = elapsed // 90
    assists = elapsed // 40
    return {
        "game_time": elapsed,
        "kda": [kills, deaths, assists],
        "gold": 500 + elapsed * 8,
        "cs": elapsed // 3,
        "level": min(18, 1 + elapsed // 45),
        "score": {"order": kills + 2, "chaos": deaths + assists},
    }


def _connect(sender: Sender) -> bool:
    for _ in range(10):
        try:
            sender.connect()
            return True
        except Exception:
            print("[simu] Pi injoignable, nouvelle tentative dans 1 s...")
            time.sleep(1)
    print("[simu] Impossible de se connecter au Pi. Abandon.")
    return False


def _install_click_handler(sender: Sender) -> None:
    """Répond aux clics sur un joueur avec de fausses infos."""
    def handle(message: dict):
        if message.get("type") != "request_player_info":
            return
        puuid = message.get("puuid", "")
        info = dict(FAKE_INFO.get(puuid, {"error": "Joueur inconnu (simu)."}))
        info["puuid"] = puuid
        info["championId"] = message.get("championId")
        print(f"[simu] Demande d'infos joueur {puuid} -> réponse envoyée")
        sender.send_safe(msg_player_info(puuid, info))
    sender.start_receiver(handle)


def _phase_champselect(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] Sélection de champions ({duration}s). Clique sur un joueur !")
    sender.send_safe(msg_set_mode("champselect"))
    end = time.time() + duration
    while time.time() < end:
        sender.send_safe(msg_data("champselect", {"phase": "champselect", "players": FAKE_TEAM}))
        time.sleep(interval)


def _phase_game(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] Partie en cours ({duration}s).")
    sender.send_safe(msg_set_mode("lol"))
    start = time.time()
    while time.time() - start < duration:
        sender.send_safe(msg_data("lol", _fake_game_payload(int(time.time() - start))))
        time.sleep(interval)


def run_simulation(url: str, interval: float = 1.0,
                   scenario: str = "full", duration: int | None = None) -> None:
    sender = Sender(url)
    if not _connect(sender):
        return
    _install_click_handler(sender)

    try:
        if scenario == "champselect":
            _phase_champselect(sender, interval, duration or 10 ** 9)
        elif scenario == "game":
            _phase_game(sender, interval, duration or 10 ** 9)
        else:  # full
            print("[simu] Scénario complet. Ctrl+C pour arrêter.")
            sender.send_safe(msg_set_mode("default"))
            time.sleep(duration or 5)
            _phase_champselect(sender, interval, duration or 20)
            _phase_game(sender, interval, duration or 20)
            sender.send_safe(msg_set_mode("default"))
    except KeyboardInterrupt:
        print("\n[simu] Interruption.")
    finally:
        sender.send_safe(msg_set_mode("default"))
        sender.close()
        print("[simu] Terminé.")
