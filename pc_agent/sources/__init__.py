"""Registre des Sources (moitié « agent » des modules).

Pour ajouter un jeu : créer `sources/<nom>.py` avec une classe héritant de
`Source`, puis l'ajouter ici. Le `name` doit correspondre au module côté Pi.
"""

from sources.league import LeagueSource

SOURCES = {LeagueSource.name: LeagueSource}
