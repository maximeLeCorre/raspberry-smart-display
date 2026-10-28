"""Module « serveur » : supervision (CPU/RAM/disque) et contrôle de services
(start/stop/restart) d'un petit serveur, via SSH. Le Pi se connecte lui-même
(marche PC éteint). Activable en config ([modules] server), paramétré par
[server] (hôte, clé, service). Pi-only : pas de moitié `sources/` côté agent.
"""

from modules.base import Module
from modules.server.server_screen import ServerScreen


class ServerModule(Module):
    name = "server"
    screens = [ServerScreen]
