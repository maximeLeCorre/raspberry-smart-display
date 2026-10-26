"""Mode simulation : joue des scénarios sans lancer League, pour tester le Pi.

Scénarios (--scenario) :
  - full        : défaut -> sélection de champions -> partie -> défaut
  - champselect : reste en sélection de champions (test du clic sur un joueur)
  - game        : reste en partie Faille (timers d'objectifs + dossier au clic)
  - aram        : reste en partie ARAM (pas d'objectifs ; dossier adverse au clic)

Répond aussi aux demandes d'infos joueur (clic sur un joueur). Le joueur
« maxoulefou » (notre compte) renvoie de VRAIES stats via l'API Web Riot si
RIOT_API_KEY est présent dans .env (aucune partie à lancer) ; les autres
joueurs restent fictifs. À l'arrêt (Ctrl+C), repasse en mode par défaut.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

from champ_select import build_player_info, icon_b64, splash_b64
from lcu import LcuClient
from riot_web import RiotWeb
from sender import Sender, msg_data, msg_icon, msg_player_info, msg_set_screen, msg_splash

# Notre compte réel : ses stats sont récupérées en vrai via l'API Web.
REAL_PLAYER = ("maxoulefou", "EUW")
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

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
     "gameName": REAL_PLAYER[0], "tagLine": REAL_PLAYER[1], "isSelf": True, "iconB64": None},
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
    # Adversaires (dossier au clic pendant la partie).
    "puuid-e1": {"summonerLevel": 412, "ranks": {"Solo/Duo": {"tier": "MASTER", "rank": "I", "lp": 120, "wins": 410, "losses": 360}},
                 "championMastery": {"level": 7, "points": 520000},
                 "mains": [{"championName": "Zed", "points": 520000},
                           {"championName": "Yasuo", "points": 300000}],
                 "recent": {"wins": 7, "losses": 1, "winrate": 88}},
    "puuid-e2": {"summonerLevel": 188, "ranks": {"Solo/Duo": {"tier": "GOLD", "rank": "IV", "lp": 20, "wins": 80, "losses": 78}},
                 "mains": [{"championName": "Darius", "points": 180000}],
                 "recent": {"wins": 4, "losses": 4, "winrate": 50}},
    "puuid-e3": {"summonerLevel": 90, "ranks": {}, "mains": [{"championName": "Master Yi", "points": 60000}],
                 "recent": {"wins": 2, "losses": 6, "winrate": 25}},
    "puuid-e4": {"summonerLevel": 260, "ranks": {"Solo/Duo": {"tier": "PLATINUM", "rank": "II", "lp": 55, "wins": 220, "losses": 200}},
                 "mains": [{"championName": "Jinx", "points": 240000}],
                 "recent": {"wins": 5, "losses": 3, "winrate": 63}},
    "puuid-e5": {"summonerLevel": 140, "ranks": {"Solo/Duo": {"tier": "SILVER", "rank": "III", "lp": 40, "wins": 70, "losses": 72}},
                 "mains": [{"championName": "Lux", "points": 110000}],
                 "recent": {"wins": 3, "losses": 4, "winrate": 43}},
}


# Équipe adverse fictive (nom, champion, championId, position, puuid).
FAKE_ENEMIES = [
    ("Greed", "Zed", 238, "Mid", "puuid-e1"),
    ("409", "Darius", 122, "Top", "puuid-e2"),
    ("Tacadoll", "Master Yi", 11, "Jungle", "puuid-e3"),
    ("Bober", "Jinx", 222, "ADC", "puuid-e4"),
    ("Azaka", "Lux", 99, "Support", "puuid-e5"),
]


def _fake_objectives(elapsed: int) -> list[dict]:
    """Objectifs fictifs dont les compteurs défilent (temps de jeu absolu)."""
    dragon_at = elapsed + (300 - elapsed % 300)          # décompte 5:00 en boucle
    if elapsed < 1200:
        baron_at = 1200
    else:
        baron_at = elapsed + (360 - (elapsed - 1200) % 360)
    herald_at = 840 if elapsed < 840 else None           # pris après 14:00
    return [
        {"key": "dragon", "label": "Dragon", "at": dragon_at, "by": "maxoulefou", "detail": "Infernal"},
        {"key": "baron", "label": "Baron", "at": baron_at, "by": None},
        {"key": "herald", "label": "Héraut", "at": herald_at, "by": "Greed" if herald_at is None else None},
    ]


def _fake_game_payload(elapsed: int, mode: str = "CLASSIC") -> dict:
    """Scoreboard complet fictif qui évolue dans le temps (10 joueurs)."""
    step = elapsed // 25
    level = min(18, 1 + elapsed // 45)

    def row(name, champ, cid, pos, team, puuid="", is_self=False, dead=False):
        return {
            "name": name, "puuid": puuid, "champion": champ, "championId": cid,
            "position": pos, "team": team,
            "k": step + (1 if is_self else 0), "d": step // 2, "a": step + 1,
            "cs": elapsed // 3, "level": level,
            "isDead": dead, "respawn": (6 + 2 * level) if dead else 0,
            "isSelf": is_self,
        }

    dead_self = (elapsed // 5) % 8 == 0  # on "meurt" de temps en temps
    order = [row(p["gameName"], p["championName"], p["championId"], p["position"],
                 "ORDER", puuid=p.get("puuid", ""), is_self=p.get("isSelf", False),
                 dead=p.get("isSelf", False) and dead_self)
             for p in FAKE_TEAM]
    chaos = [row(n, c, cid, pos, "CHAOS", puuid=pu)
             for (n, c, cid, pos, pu) in FAKE_ENEMIES]

    events = ["maxoulefou a tué Greed", "Dragon Infernal pris par ORDER",
              "First Blood : Greed", "Tourelle détruite (maxoulefou)"]
    return {
        "game_time": elapsed,
        "game_mode": mode,
        "scores": {"order": 5 * step, "chaos": 3 * step},
        "players": order + chaos,
        "events": events[:1 + elapsed // 12],
        "objectives": _fake_objectives(elapsed) if mode == "CLASSIC" else [],
        "self": {"gold": 500 + elapsed * 8},
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


def _install_click_handler(sender: Sender, riot, lcu, real_puuids: set) -> None:
    """Répond aux clics : vraies stats pour maxoulefou, fictives sinon."""
    def handle(message: dict):
        msg_type = message.get("type")

        if msg_type == "request_icon":
            # Vraie icône si le client League est ouvert, sinon None (placeholder).
            champ_id = int(message.get("championId") or 0)
            sender.send_safe(msg_icon(champ_id, icon_b64(lcu, champ_id)))
            return

        if msg_type == "request_splash":
            # Les splash arts viennent de Data Dragon : dispo même sans client.
            champ_id = int(message.get("championId") or 0)
            sender.send_safe(msg_splash(champ_id, splash_b64(lcu, champ_id)))
            return

        if msg_type != "request_player_info":
            return

        puuid = message.get("puuid", "")
        champion_id = int(message.get("championId") or 0)
        if riot and puuid in real_puuids:
            # Notre compte : vraies données via l'API Web.
            print(f"[simu] Infos RÉELLES pour {puuid[:12]}… (API Riot)")
            info = build_player_info(lcu, riot, puuid, None, champion_id)
        else:
            info = dict(FAKE_INFO.get(puuid, {"error": "Joueur inconnu (simu)."}))
            info["puuid"] = puuid
            info["championId"] = message.get("championId")

        sender.send_safe(msg_player_info(puuid, info))
    sender.start_receiver(handle)


def _phase_champselect(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] Sélection de champions ({duration}s). Clique sur un joueur !")
    sender.send_safe(msg_set_screen("champselect"))
    end = time.time() + duration
    while time.time() < end:
        sender.send_safe(msg_data("champselect", {"phase": "champselect", "players": FAKE_TEAM}))
        time.sleep(interval)


def _phase_queue(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] File d'attente ({duration}s) puis ready-check.")
    sender.send_safe(msg_set_screen("queue"))
    start = time.time()
    while time.time() - start < duration:
        t = int(time.time() - start)
        sender.send_safe(msg_data("queue", {"state": "searching",
                                            "timeInQueue": t, "estimated": 95}))
        time.sleep(interval)
    for remaining in range(10, -1, -1):
        sender.send_safe(msg_data("queue", {"state": "readycheck",
                                            "remaining": remaining, "response": "None"}))
        time.sleep(1)
    sender.send_safe(msg_data("queue", {"state": "readycheck",
                                        "remaining": 0, "response": "Accepted"}))
    time.sleep(1)


def _phase_game(sender: Sender, interval: float, duration: int,
                mode: str = "CLASSIC") -> None:
    print(f"[simu] Partie en cours ({mode}, {duration}s). Clique un joueur !")
    sender.send_safe(msg_set_screen("lol"))
    start = time.time()
    while time.time() - start < duration:
        payload = _fake_game_payload(int(time.time() - start), mode)
        sender.send_safe(msg_data("lol", payload))
        time.sleep(interval)


def _phase_postgame(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] Après-partie ({duration}s).")
    payload = {"win": True, "championId": 103, "championName": "Ahri",
               "kda": [12, 4, 9], "cs": 210, "gold": 14200, "damage": 32500,
               "level": 16, "duration": 1830, "queue": "Classé Solo/Duo"}
    sender.send_safe(msg_set_screen("postgame"))
    end = time.time() + duration
    while time.time() < end:
        sender.send_safe(msg_data("postgame", payload))
        time.sleep(interval)


def _setup_real_player(platform: str, regional: str) -> tuple:
    """Prépare l'API Web pour maxoulefou : (riot, lcu, {vrais_puuids}).

    Si la clé est absente ou le Riot ID introuvable, renvoie (None, lcu, set()).
    """
    load_dotenv(ENV_PATH)
    api_key = os.getenv("RIOT_API_KEY")
    lcu = LcuClient()  # sert uniquement aux noms de champions (via Community Dragon)
    if not api_key:
        print("[simu] Pas de RIOT_API_KEY : maxoulefou aura des stats fictives.")
        return None, lcu, set()

    riot = RiotWeb(api_key, platform, regional)
    real_puuids = set()
    real_puuid = riot.resolve_puuid(*REAL_PLAYER)
    if real_puuid:
        # On injecte le vrai PUUID dans le joueur 'isSelf' de l'équipe.
        for player in FAKE_TEAM:
            if player.get("isSelf"):
                player["puuid"] = real_puuid
        real_puuids.add(real_puuid)
        print(f"[simu] maxoulefou résolu -> vraies stats au clic.")
    else:
        print("[simu] maxoulefou introuvable via l'API : stats fictives.")
    return riot, lcu, real_puuids


def run_simulation(url: str, interval: float = 1.0, scenario: str = "full",
                   duration: int | None = None,
                   platform: str = "euw1", regional: str = "europe",
                   auth_token: str = "", ssl_context=None) -> None:
    sender = Sender(url, auth_token=auth_token, ssl_context=ssl_context)
    if not _connect(sender):
        return

    # Vraies stats pour maxoulefou dès qu'il peut être cliqué (sélection/partie).
    if scenario in ("champselect", "full", "game", "aram"):
        riot, lcu, real_puuids = _setup_real_player(platform, regional)
    else:
        riot, lcu, real_puuids = None, LcuClient(), set()

    _install_click_handler(sender, riot, lcu, real_puuids)

    try:
        if scenario == "champselect":
            _phase_champselect(sender, interval, duration or 10 ** 9)
        elif scenario == "game":
            _phase_game(sender, interval, duration or 10 ** 9)
        elif scenario == "aram":
            _phase_game(sender, interval, duration or 10 ** 9, mode="ARAM")
        elif scenario == "queue":
            _phase_queue(sender, interval, duration or 8)
        elif scenario == "postgame":
            _phase_postgame(sender, interval, duration or 10 ** 9)
        else:  # full
            print("[simu] Scénario complet. Ctrl+C pour arrêter.")
            sender.send_safe(msg_set_screen("default"))
            time.sleep(duration or 5)
            _phase_queue(sender, interval, duration or 8)
            _phase_champselect(sender, interval, duration or 20)
            _phase_game(sender, interval, duration or 20)
            _phase_postgame(sender, interval, duration or 12)
            sender.send_safe(msg_set_screen("default"))
    except KeyboardInterrupt:
        print("\n[simu] Interruption.")
    finally:
        sender.send_safe(msg_set_screen("default"))
        sender.close()
        print("[simu] Terminé.")
