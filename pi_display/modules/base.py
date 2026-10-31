"""Descripteur de module d'affichage.

Un module regroupe plusieurs écrans (Screen) d'un même jeu/domaine.
Exemple : le module « league » fournit les écrans file d'attente, sélection,
partie et après-partie.

L'App instancie chaque module activé (`Module(app)`, rangé dans `app.modules`)
**avant** ses écrans : un écran peut donc retrouver son module dès son
`__init__` (`app.modules["league"]`). La logique propre à un jeu (état,
synchro, messages réseau spécifiques) vit dans le module via les crochets
ci-dessous : `app.py` reste agnostique.
"""

from __future__ import annotations


class Module:
    name = "base"          # identifiant du module (clé de config)
    always_on = False      # True = toujours actif, non désactivable (ex. système)
    screens: list = []     # classes Screen fournies par ce module

    def __init__(self, app):
        self.app = app

    # ---------------------------------------------- crochets (tous facultatifs)
    def on_connected(self) -> None:
        """L'agent (PC) vient de se connecter."""

    def on_disconnected(self) -> None:
        """L'agent courant est parti (l'App revient ensuite au défaut)."""

    def on_agent_screen(self, screen: str, shown: bool) -> None:
        """L'agent demande un NOUVEL écran (heartbeat exclu) ; `shown` = l'App
        l'a affiché (pas de verrou manuel)."""

    def on_message(self, msg: dict) -> bool:
        """Message réseau non générique ; True = traité (arrête la recherche)."""
        return False

    def tick(self) -> None:
        """Appelé à chaque frame (tâches périodiques légères)."""
