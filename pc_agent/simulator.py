"""Mode simulation : joue des scénarios sans lancer League, pour tester le Pi.

Scénarios (--scenario) :
  - full        : défaut -> file -> sélection -> partie -> après-partie -> défaut
  - champselect : reste en sélection de champions
  - game        : reste en partie Faille (timers d'objectifs)
  - aram        : reste en partie ARAM (pas d'objectifs)
  - queue       : file d'attente puis ready-check
  - home        : reste sur l'accueil (teste « Dernières parties »)
  - postgame    : affiche l'écran de bilan de fin de partie

Le simulateur ne fournit que des **données locales fictives** (ce que l'agent
réel produit). L'enrichissement (dossiers joueurs, icônes, splash, historique,
bilan de fin) est désormais fait **par le Pi** via l'API Web Riot : en
simulation, ces éléments s'appuient donc sur la vraie clé/compte configurés sur
le Pi (les joueurs fictifs, eux, n'auront pas de dossier réel).

En `--simulate`, l'agent vise `127.0.0.1` par défaut (voir main.py).
"""

from __future__ import annotations

import time

from sender import Sender, msg_data, msg_set_screen

# Équipe fictive (5 joueurs, dont nous) pour la sélection de champions.
FAKE_TEAM = [
    {"riotId": "MatteMwa#EUW", "championId": 86, "championName": "Garen",
     "position": "Top", "gameName": "MatteMwa", "tagLine": "EUW", "isSelf": False},
    {"riotId": "GankMaster#EUW", "championId": 64, "championName": "Lee Sin",
     "position": "Jungle", "gameName": "GankMaster", "tagLine": "EUW", "isSelf": False},
    {"riotId": "maxoulefou#EUW", "championId": 103, "championName": "Ahri",
     "position": "Mid", "gameName": "maxoulefou", "tagLine": "EUW", "isSelf": True},
    {"riotId": "FarmAndGo#EUW", "championId": 22, "championName": "Ashe",
     "position": "ADC", "gameName": "FarmAndGo", "tagLine": "EUW", "isSelf": False},
    {"riotId": "HookOrFeed#EUW", "championId": 412, "championName": "Thresh",
     "position": "Support", "gameName": "HookOrFeed", "tagLine": "EUW", "isSelf": False},
]

# Équipe adverse fictive (nom, champion, championId, position).
FAKE_ENEMIES = [
    ("Greed", "Zed", 238, "Mid"),
    ("409", "Darius", 122, "Top"),
    ("Tacadoll", "Master Yi", 11, "Jungle"),
    ("Bober", "Jinx", 222, "ADC"),
    ("Azaka", "Lux", 99, "Support"),
]


def _fake_objectives(elapsed: int) -> list[dict]:
    """Objectifs fictifs dont les compteurs défilent (temps de jeu absolu)."""
    dragon_at = elapsed + (300 - elapsed % 300)          # décompte 5:00 en boucle
    baron_at = 1200 if elapsed < 1200 else elapsed + (360 - (elapsed - 1200) % 360)
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

    def row(name, champ, cid, pos, team, is_self=False, dead=False):
        return {
            "name": name, "riotId": f"{name}#EUW", "champion": champ, "championId": cid,
            "position": pos, "team": team,
            "k": step + (1 if is_self else 0), "d": step // 2, "a": step + 1,
            "cs": elapsed // 3, "level": level,
            "isDead": dead, "respawn": (6 + 2 * level) if dead else 0,
            "isSelf": is_self,
        }

    dead_self = (elapsed // 5) % 8 == 0  # on "meurt" de temps en temps
    order = [row(p["gameName"], p["championName"], p["championId"], p["position"],
                 "ORDER", is_self=p.get("isSelf", False),
                 dead=p.get("isSelf", False) and dead_self)
             for p in FAKE_TEAM]
    chaos = [row(n, c, cid, pos, "CHAOS") for (n, c, cid, pos) in FAKE_ENEMIES]

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
            print(f"[simu] Pi injoignable ({sender.url}), nouvelle tentative dans 1 s...")
            time.sleep(1)
    print(f"[simu] Impossible de se connecter au Pi ({sender.url}). Abandon.\n"
          "       Le display tourne-t-il ? Sinon, précise la cible avec --host.")
    return False


def _phase_champselect(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] Sélection de champions ({duration}s).")
    sender.send_safe(msg_set_screen("champselect"))
    payload = {"phase": "champselect", "players": FAKE_TEAM,
               "timer": {"phase": "Sélection", "left": 27},
               "bans": {"myTeam": [238, 122], "theirTeam": [23, 55]}}
    end = time.time() + duration
    while time.time() < end:
        sender.send_safe(msg_data("champselect", payload))
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
    print(f"[simu] Partie en cours ({mode}, {duration}s).")
    sender.send_safe(msg_set_screen("lol"))
    start = time.time()
    while time.time() - start < duration:
        payload = _fake_game_payload(int(time.time() - start), mode)
        sender.send_safe(msg_data("lol", payload))
        time.sleep(interval)


def _phase_home(sender: Sender, interval: float, duration: int) -> None:
    print(f"[simu] Accueil ({duration}s). Teste le bouton « Dernières parties ».")
    sender.send_safe(msg_set_screen("default"))
    end = time.time() + duration
    while time.time() < end:
        time.sleep(interval)


def _phase_postgame(sender: Sender, interval: float, duration: int) -> None:
    # Le Pi récupère lui-même le bilan (dernière partie du compte configuré).
    print(f"[simu] Après-partie ({duration}s) — bilan récupéré par le Pi.")
    sender.send_safe(msg_set_screen("postgame"))
    end = time.time() + duration
    while time.time() < end:
        time.sleep(interval)


def run_simulation(url: str, interval: float = 1.0, scenario: str = "full",
                   duration: int | None = None,
                   platform: str = "euw1", regional: str = "europe",
                   auth_token: str = "", ssl_context=None) -> None:
    sender = Sender(url, auth_token=auth_token, ssl_context=ssl_context)
    if not _connect(sender):
        return

    try:
        if scenario == "champselect":
            _phase_champselect(sender, interval, duration or 10 ** 9)
        elif scenario == "game":
            _phase_game(sender, interval, duration or 10 ** 9)
        elif scenario == "aram":
            _phase_game(sender, interval, duration or 10 ** 9, mode="ARAM")
        elif scenario == "queue":
            _phase_queue(sender, interval, duration or 8)
        elif scenario == "home":
            _phase_home(sender, interval, duration or 10 ** 9)
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
