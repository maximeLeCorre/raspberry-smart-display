"""Registre des modules d'affichage.

Pour ajouter un module (un jeu/domaine) :
  1. créer un paquet `modules/<nom>/` avec ses écrans (classes Screen) ;
  2. y définir une classe héritant de `Module` (name + liste des écrans) ;
  3. l'ajouter à `MODULES` ci-dessous ;
  4. l'activer dans `config.toml` (section [modules]).
"""

from modules.league import LeagueModule
from modules.system import SystemModule

# Ordre = ordre d'affichage / de priorité. 'system' (toujours actif) en premier.
MODULES = [SystemModule, LeagueModule]
