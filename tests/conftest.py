"""Configuration commune des tests (headless, sans réseau ni vrai serveur).

Les deux programmes ne sont pas des packages : on ajoute `pi_display/` et
`pc_agent/` au chemin d'import, comme le font leurs `main.py`. Leurs modules ont
des noms distincts (sauf `config`, côté Pi seulement), donc pas de collision.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pi_display"))
sys.path.insert(0, str(ROOT / "pc_agent"))

# Pygame sans écran ni son ; écran « Serveur » non configuré (aucun SSH réel).
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["SERVER_HOST"] = ""
os.environ["IDFM_API_KEY"] = ""          # écran « Trains » sans appel réseau
os.environ["RIOT_API_KEY"] = ""          # API Web Riot sans clé réelle


@pytest.fixture
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
