"""Mode simulation : envoie de fausses données LoL pour tester sans le jeu.

Il bascule le Pi en mode LoL, diffuse des données qui évoluent dans le temps,
puis — à l'arrêt (Ctrl+C ou fin de durée) — simule la « fermeture du jeu » :
il envoie set_mode default PUIS se déconnecte. Les deux font revenir le Pi
au mode par défaut (le point 4 de la première étape).
"""

from __future__ import annotations

import time

from sender import Sender, msg_data, msg_set_mode


def fake_payload(elapsed: int) -> dict:
    """Fabrique un résumé LoL plausible qui évolue avec le temps écoulé."""
    kills = elapsed // 60          # +1 kill / minute (arbitraire)
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


def run_simulation(url: str, interval: float = 1.0, duration: int | None = None) -> None:
    sender = Sender(url)

    # Connexion initiale (avec quelques tentatives si le Pi démarre).
    for _ in range(10):
        try:
            sender.connect()
            break
        except Exception:
            print("[simu] Pi injoignable, nouvelle tentative dans 1 s...")
            time.sleep(1)
    else:
        print("[simu] Impossible de se connecter au Pi. Abandon.")
        return

    print("[simu] Démarrage de la partie simulée (Ctrl+C pour « fermer le jeu »).")
    sender.send_safe(msg_set_mode("lol"))

    start = time.time()
    try:
        while True:
            elapsed = int(time.time() - start)
            sender.send_safe(msg_data("lol", fake_payload(elapsed)))
            if duration is not None and elapsed >= duration:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[simu] Interruption : fermeture du jeu simulée.")
    finally:
        # Fin de partie : on repasse en mode par défaut, puis on se déconnecte.
        sender.send_safe(msg_set_mode("default"))
        sender.close()
        print("[simu] Terminé.")
