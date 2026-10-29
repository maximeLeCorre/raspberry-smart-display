"""Module système : accueil (horloge, météo, actus), France Info, Météo. Toujours actif."""

from modules.base import Module
from modules.system.default_screen import DefaultScreen
from modules.system.news_screen import NewsScreen
from modules.system.weather_screen import WeatherScreen


class SystemModule(Module):
    name = "system"
    always_on = True
    screens = [DefaultScreen, NewsScreen, WeatherScreen]
