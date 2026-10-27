"""Module League of Legends : file d'attente, sélection, partie, après-partie."""

from modules.base import Module
from modules.league.champ_select_screen import ChampSelectScreen
from modules.league.history_screen import MatchHistoryScreen
from modules.league.lol_screen import LolScreen
from modules.league.postgame_screen import PostGameScreen
from modules.league.queue_screen import QueueScreen


class LeagueModule(Module):
    name = "league"
    screens = [QueueScreen, ChampSelectScreen, LolScreen, PostGameScreen,
               MatchHistoryScreen]
