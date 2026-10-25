"""Abstraction des entrées : boutons GPIO (Pi) + fallback clavier (PC).

Deux actions de haut niveau existent, quelle que soit la provenance :
    ACTION_BACK  -> retour forcé au mode par défaut
    ACTION_NEXT  -> passage au mode suivant

Sur le Pi, les boutons physiques (gpiozero) déposent ces actions dans une
queue. Sur le PC, gpiozero n'est pas installé : on se rabat sur le clavier,
géré directement dans la boucle Pygame (voir app.py) :
    Échap -> ACTION_BACK
    Tab   -> ACTION_NEXT
"""

from __future__ import annotations

import queue

ACTION_BACK = "back"
ACTION_NEXT = "next"

# On tente d'importer gpiozero. Absent sur PC -> fallback clavier uniquement.
try:
    from gpiozero import Button

    GPIO_AVAILABLE = True
except Exception:  # ImportError sur PC, ou erreur d'init hors Pi
    GPIO_AVAILABLE = False


class InputManager:
    """Gère les boutons GPIO s'ils sont disponibles.

    Les actions déclenchées par les boutons sont déposées dans `action_queue`,
    que la boucle principale vide à chaque frame.
    """

    def __init__(self, config: dict, action_queue: "queue.Queue[str]", debug: bool = False):
        self.action_queue = action_queue
        self.debug = debug
        self._buttons = []

        if GPIO_AVAILABLE:
            self._setup_gpio(config.get("gpio", {}))
            print("[entrees] Boutons GPIO actifs (gpiozero détecté)")
        else:
            print("[entrees] gpiozero absent : fallback clavier "
                  "(Échap = retour, Tab = mode suivant)")

    def _setup_gpio(self, gpio_config: dict) -> None:
        pin_back = gpio_config.get("button_back")
        pin_next = gpio_config.get("button_next")

        if pin_back is not None:
            btn = Button(pin_back)
            btn.when_pressed = lambda: self._emit(ACTION_BACK)
            self._buttons.append(btn)
        if pin_next is not None:
            btn = Button(pin_next)
            btn.when_pressed = lambda: self._emit(ACTION_NEXT)
            self._buttons.append(btn)

    def _emit(self, action: str) -> None:
        if self.debug:
            print(f"[entrees] bouton GPIO -> {action}")
        self.action_queue.put(action)
