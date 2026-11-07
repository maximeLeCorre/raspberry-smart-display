"""Module « trains » : prochains départs d'une gare + info trafic (API PRIM d'IDFM).
Le Pi interroge l'API lui-même (marche PC éteint). Activable en config
([modules] transit), paramétré par [transit] ; clé IDFM_API_KEY dans le .env.
Pi-only : pas de moitié `sources/` côté agent.
"""

import json

from modules.base import Module
from modules.transit.transit_screen import TransitScreen, short_destination

MAX_REMOTE = 16      # départs envoyés à la montre (complication : ~1 h d'avance)


class TransitModule(Module):
    name = "transit"
    screens = [TransitScreen]

    def remote_asset(self, name: str) -> tuple[bytes, str] | None:
        """`next` : prochains départs pour la complication de la montre (JSON).
        Thread HTTP : seulement le `snapshot()` verrouillé du flux (créé avec l'écran)."""
        feed = getattr(self.app, "_transit_feed", None)
        if name != "next" or feed is None:
            return None
        snap = feed.snapshot()
        cfg = self.app.config.get("transit", {})
        home = str(cfg.get("home_destination", "")).lower()     # comme l'accueil du Pi
        board = {
            "station": str(cfg.get("station", "")),
            "homeLabel": str(cfg.get("home_label", "")),
            "updated": snap["updated"],
            "departures": [{"line": d.line, "destination": short_destination(d.destination),
                            "time": d.when, "arrival": d.arrival, "delay": d.delay_min,
                            "cancelled": d.cancelled, "platform": d.platform, "toParis": d.to_paris,
                            "home": bool(home) and home in d.destination.lower()}
                           for d in snap["departures"][:MAX_REMOTE]],
        }
        return json.dumps(board, ensure_ascii=False).encode(), "application/json"
