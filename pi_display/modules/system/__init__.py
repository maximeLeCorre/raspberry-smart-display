"""Module système : accueil (horloge + actus) et France Info. Toujours actif."""

from modules.base import Module
from modules.system.default_screen import DefaultScreen
from modules.system.news_screen import NewsScreen


class SystemModule(Module):
    name = "system"
    always_on = True
    screens = [DefaultScreen, NewsScreen]
