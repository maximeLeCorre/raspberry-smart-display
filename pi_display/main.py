"""Point d'entrée de l'appli d'affichage.

Exemples :
    python main.py                      # fenêtre 800x480 (test PC)
    python main.py --scale 2            # fenêtre agrandie x2 (rendu interne 800x480)
    python main.py --monitor 1          # ouvre sur le 2e moniteur
    python main.py --debug              # overlay de debug (bascule aussi avec F1)
    python main.py --fullscreen         # plein écran (sur le Pi)

Sur le Pi (Raspberry Pi OS Lite, sans bureau), le plein écran est activé
automatiquement (détection du modèle) et le pilote vidéo SDL est réglé sur
kmsdrm. On peut forcer le mode fenêtré avec --windowed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from config import is_raspberry_pi, load_config

CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


def parse_args():
    p = argparse.ArgumentParser(description="Appli d'affichage (écran 5\").")
    p.add_argument("--fullscreen", action="store_true", help="Force le plein écran.")
    p.add_argument("--windowed", action="store_true", help="Force le mode fenêtré.")
    p.add_argument("--scale", type=int, default=1,
                   help="Agrandit la fenêtre sans changer le rendu interne (ex. 2).")
    p.add_argument("--monitor", type=int, default=None,
                   help="Index du moniteur sur lequel ouvrir la fenêtre.")
    p.add_argument("--debug", action="store_true", help="Active l'overlay de debug.")
    p.add_argument("--host", default=None, help="Surcharge l'hôte d'écoute.")
    p.add_argument("--port", type=int, default=None, help="Surcharge le port d'écoute.")
    p.add_argument("--config", default=str(CONFIG_PATH), help="Chemin du config.toml.")
    return p.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    # Plein écran : explicite, ou auto sur le Pi (sauf --windowed).
    on_pi = is_raspberry_pi()
    fullscreen = args.fullscreen or (on_pi and not args.windowed)

    # Sur le Pi sans bureau, on force le pilote vidéo adapté (framebuffer KMS).
    if on_pi and fullscreen:
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

    host = args.host if args.host is not None else config["network"]["host"]
    port = args.port if args.port is not None else config["network"]["port"]

    # Import tardif : pygame s'initialise après le réglage des variables SDL.
    from app import App

    app = App(
        config,
        fullscreen=fullscreen,
        scale=args.scale,
        monitor=args.monitor,
        debug=args.debug,
        host=host,
        port=port,
    )
    app.run()


if __name__ == "__main__":
    main()
