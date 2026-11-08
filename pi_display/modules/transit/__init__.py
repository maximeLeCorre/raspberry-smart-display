"""Module « trains » : prochains départs d'une gare + info trafic (API PRIM d'IDFM).
Le Pi interroge l'API lui-même (marche PC éteint). Activable en config
([modules] transit), paramétré par [transit] ; clé IDFM_API_KEY dans le .env.
Pi-only : pas de moitié `sources/` côté agent.
"""

from modules.base import Module
from modules.transit.transit_screen import TransitScreen


class TransitModule(Module):
    name = "transit"
    screens = [TransitScreen]
