"""Module système : l'écran par défaut (horloge). Toujours actif."""

from modules.base import Module
from modules.system.default_screen import DefaultScreen


class SystemModule(Module):
    name = "system"
    always_on = True
    screens = [DefaultScreen]
