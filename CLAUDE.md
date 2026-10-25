# CLAUDE.md — Guide du projet pour Claude

Ce fichier est lu au démarrage d'une session. Il décrit comment le projet
fonctionne pour reprendre le travail sans tout re-découvrir.

> **Règle d'enrichissement (importante)** : dès que tu découvres quelque chose
> de non évident sur ce projet (un comportement d'API, une décision de design,
> un piège, un nouveau module/mode, une commande utile), **mets ce fichier à
> jour** pour le refléter — de façon concise et exacte. Préfère corriger la
> section existante plutôt qu'empiler des doublons. Ne mets jamais de secret ici.

---

## But du projet

Un écran d'information intelligent (Raspberry Pi 3 + écran tactile 5", 800×480)
qui affiche des « modes » selon l'activité League of Legends sur le PC Windows.
Pour l'instant tout se développe et se teste **sur le PC** (l'écran n'est pas
encore livré) : l'appli d'affichage tourne dans une fenêtre, l'agent envoie
sur `localhost`.

## Architecture : deux programmes

- **`pi_display/`** — appli d'affichage (Pygame). Tournera sur le Pi ; se teste
  en fenêtre sur PC. Serveur WebSocket qui reçoit écran + données.
- **`pc_agent/`** — agent de fond (Windows). Détecte l'activité, lit les API
  locales/Web de Riot, envoie au Pi. Client WebSocket.

Communication : **WebSocket JSON bidirectionnel** (lib `websockets`, API
**synchrone** `websockets.sync` des deux côtés — pas d'asyncio). Le Pi est
serveur, l'agent est client.

### Vocabulaire & modularité (IMPORTANT)

- **module** = un jeu/domaine (ex. `league`, plus tard `valorant`, `spotify`…).
  C'est l'unité qu'on **active/désactive** en config.
- **écran** (`Screen`) = une vue affichable à l'intérieur d'un module (file,
  sélection, partie, après-partie). Le mot « mode » n'est plus utilisé.
- Un module a **deux moitiés** : côté Pi un paquet d'écrans
  (`pi_display/modules/<nom>/`), côté agent une **Source**
  (`pc_agent/sources/<nom>.py`) qui détecte l'état et produit `(écran, données)`.
- **Source de vérité des modules actifs = le Pi** (`config.toml [modules]`). À la
  connexion, le Pi envoie `hello` avec la liste ; l'agent n'interroge que ces
  Sources (et saute leurs appels API si inactives).
- Le module **système** (horloge) est toujours actif (écran `default`).

**Ajouter un jeu** = créer `pi_display/modules/<jeu>/` (écrans + descripteur
`Module`, enregistré dans `modules/__init__.py`) ET `pc_agent/sources/<jeu>.py`
(classe `Source`, enregistrée dans `sources/__init__.py`), puis l'activer dans
`pi_display/config.toml [modules]`. `app.py` (Pi) et `main.py` (agent) sont
**agnostiques** du jeu.

## Environnement / commandes (Windows)

- `python` dans le PATH = **stub Microsoft Store** (échoue). Utiliser
  **`py -3.11`** (requis pour `tomllib`). Pythons installés : 3.10, 3.11, 3.14.
- **venv unique à la racine** : `.venv` (ignoré par Git). Lancer via
  `.\.venv\Scripts\python ...`.
- Installer : `.\.venv\Scripts\python -m pip install -r pi_display\requirements.txt -r pc_agent\requirements.txt`
- Générer les fonds : `.\.venv\Scripts\python pi_display\tools\gen_backgrounds.py`
- Lancer l'affichage : `.\.venv\Scripts\python pi_display\main.py --scale 2`
- Lancer l'agent (simulation) : `.\.venv\Scripts\python pc_agent\main.py --simulate --scenario champselect|game|full`
- Lancer l'agent (réel) : `.\.venv\Scripts\python pc_agent\main.py`

> Python ne recharge pas à chaud : après une modif de code, **relancer** les
> programmes concernés.

## Protocole réseau (messages JSON)

Pi → PC (à la connexion) :
- `{"type":"hello","modules":["system","league"]}` (modules actifs annoncés)

PC → Pi :
- `{"type":"set_screen","screen":"default|queue|champselect|lol|postgame"}`
- `{"type":"data","screen":"lol","payload":{...}}` (le payload dépend de l'écran)
- `{"type":"player_info","puuid":"...","info":{...}}` (réponse à une demande)
- `{"type":"icon","championId":...,"iconB64":"..."}` (réponse à request_icon)
- `{"type":"splash","championId":...,"splashB64":"..."}` (réponse à request_splash)

Pi → PC (requêtes) :
- `{"type":"request_player_info","puuid":"...","summonerId":...,"championId":...}`
- `{"type":"request_icon","championId":...}`
- `{"type":"request_splash","championId":...}`

Interne (synthétisé par le serveur Pi, pas envoyé par l'agent) :
- `{"type":"_connected"}` / `{"type":"_disconnected"}`

La déconnexion du client fait revenir le Pi à l'écran par défaut.

## Écrans (`pi_display/`)

- `screen.py` : classe de base `Screen` (+ attribut `cycle` = inclus dans le
  cycle du bouton « suivant »). Fond PNG chargé **une fois** ; redessin par
  **dirty rects** (ménage le Pi 3) ; repli couleur si PNG absent.
- `modules/system/default_screen.py` : `DefaultScreen` (horloge, date, météo
  placeholder, **badge « Rejoindre »**). Module système, toujours actif.
- `modules/league/` : `QueueScreen` (file + ready-check), `ChampSelectScreen`
  (équipe, timer de phase, bans, clic → détails + **splash art**), `LolScreen`
  (scoreboard 5v5, timers de mort, événements), `PostGameScreen` (bilan).

Icônes/splash : réclamés à la demande (request_icon/request_splash), cache côté
Pi. Splash = art de chargement **Data Dragon** par alias
(`.../cdn/img/champion/loading/{alias}_0.jpg`).

Ajouter un écran : hériter de `Screen`, définir `name`/`background_name`,
implémenter `draw()` (et `update_data()` si réseau) ; l'ajouter à la liste
`screens` du `Module` concerné ; ajouter son fond.

### Comportements clés (app.py)

- `App` construit `self.screens` depuis les **modules activés** (registre
  `MODULES` filtré par `config[modules]`) ; `screen_order` = écrans `cycle=True`.
- **Verrou manuel** (`manual_screen`) : un retour manuel force l'écran `default`
  et **ignore les `set_screen` réseau** jusqu'à reconnexion ou `default` explicite.
- **Badge « Rejoindre »** : `network_screen` mémorise le dernier écran demandé ;
  `DefaultScreen` affiche un badge cliquable (`app.joinable_screen()` /
  `app.join_screen()`) pour y retourner.

### Entrées

- Tactile = souris Pygame. Clavier = fallback des boutons GPIO :
  **Échap** = retour défaut, **Tab** = écran suivant, **F1** = overlay debug.
- GPIO réel via `gpiozero` (seulement sur le Pi ; absent sur PC → fallback).
- Options d'affichage : `--fullscreen`/`--windowed` (auto plein écran + SDL
  `kmsdrm` si Pi détecté), `--scale N`, `--monitor N`, `--debug`.

## Les API Riot utilisées (pc_agent) — et leurs pièges

1. **LCU API** (`lcu.py`) — API du **client** League, dispo dès qu'il est ouvert.
   - Auth : port + token lus dans les args du process `LeagueClientUx.exe`
     (`--app-port` / `--remoting-auth-token`), HTTP Basic user `riot`,
     certificat auto-signé → `verify=False`.
   - Sert à : phase de jeu (`/lol-gameflow/v1/gameflow-phase`), session de
     sélection (`/lol-champ-select/v1/session`), **icônes** de champions
     (`/lol-game-data/assets/v1/champion-icons/{id}.png`, OK), summoner par id.
   - ⚠️ **PIÈGE 1** : le `puuid` renvoyé par la LCU est un identifiant **interne**
     (format UUID 36 car.) que l'API Web **rejette** (`400 Exception decrypting`).
     Il faut résoudre le **vrai PUUID externe** (78 car.) via `account-v1
     by-riot-id` (voir `riot_web.resolve_puuid`).
   - ⚠️ **PIÈGE 2** : la LCU **n'expose pas** de résumé id→nom de champion
     (les chemins `champion-summary.json` renvoient 404). On récupère le mapping
     depuis **Community Dragon** (`CHAMPION_SUMMARY_URL` dans `lcu.py`, CDN
     public, pas de clé). Le PC a Internet, donc OK.

2. **Live Client Data API** (`riot_api.py`) — `https://127.0.0.1:2999/liveclientdata/allgamedata`.
   - Dispo **uniquement pendant une partie** (phase `InProgress` chargée).
   - Certificat auto-signé → `verify=False`. Gérer les erreurs (souvent None).

3. **API Web Riot** (`riot_web.py`) — nécessite `RIOT_API_KEY` (dans `.env`).
   - Clé **dev** : expire toutes les 24 h (régénérer sur developer.riotgames.com).
   - Routing : endpoints **plateforme** (euw1…) vs **régional** (europe/americas/asia).
   - Utilisé pour enrichir un joueur au clic : `account-v1 by-riot-id`
     (→ vrai PUUID), `summoner-v4`, `league-v4 entries by-puuid` (rang),
     `champion-mastery-v4` (maîtrise + mains), `match-v5` (winrate récent).
   - Tolérant aux erreurs : renvoie None/partiel, ne casse jamais la boucle.
   - Région **auto-détectée** via la LCU si le client est ouvert.

### Flux « sélection de champions »

`champ_select.build_champ_select_payload` : pour chaque joueur de notre équipe,
récupère le Riot ID (complété via `lcu.summoner_by_id` si masqué) et résout le
vrai PUUID. **Les icônes ne sont PAS dans le payload** : le Pi les réclame à la
carte (`request_icon` → `icon`), une seule fois chacune (cache par `championId`,
survit aux redémarrages du Pi). `build_player_info` (au clic) agrège rang /
niveau / maîtrise / winrate / mains via l'API Web.

- ⚠️ Pour les **coéquipiers**, l'enrichissement dépend de la visibilité de leur
  Riot ID dans le client pendant la sélection (pour **soi**, toujours dispo).
- Un champion **non encore pické** (`championId=0`) n'a pas d'icône → placeholder
  avec initiales, jusqu'au pick.

## Agent : boucle agnostique + Sources (`main.py`, `sources/`)

`main.py` instancie les Sources et, chaque tick, interroge celles des modules
activés ; la première `poll()` non-None gagne → `set_screen` + `data` ; sinon
`default`. Dispatch des requêtes (infos/icône/splash) à `Source.handle_request`.
Mise à jour ≤ 1 fois / `update_interval` (config, 1–2 s).

`sources/league.py` (`LeagueSource`) mappe `gameflow_phase` → écran :
`Matchmaking`/`ReadyCheck` → `queue` ; `ChampSelect` → `champselect` ;
`InProgress` → `lol` (Live Client Data API) ;
`WaitingForStats`/`PreEndOfGame`/`EndOfGame` → `postgame` (historique LCU) ;
client fermé/menu → `poll()` renvoie None (l'agent affiche `default`). Les
builders queue/postgame sont dans `phases.py`, la sélection dans `champ_select.py`.

Mode simulation (`simulator.py`) : scénarios `full`/`champselect`/`game`/`queue`/`postgame` avec
fausses données. Le joueur **maxoulefou** (notre compte, constante `REAL_PLAYER`)
renvoie de **vraies** stats au clic via l'API Web (si `RIOT_API_KEY` présent),
sans lancer de partie ; les autres joueurs restent fictifs.

> Note : le PUUID renvoyé par `account-v1` est **chiffré par clé d'API** — il
> change quand la clé change (clé dev renouvelée). Cohérent tant qu'on garde la
> même clé sur une session, ce qui est le cas.

## Config & secrets

- `pi_display/config.toml` : host/port d'écoute, résolution, FPS, broches GPIO,
  **`[modules]`** (active/désactive les modules — source de vérité, poussée à l'agent).
- `pc_agent/config.toml` : IP/port du Pi, `update_interval`, noms des process
  LoL, `[riot] platform/regional`, `[features] player_info`.
- **`.env`** (racine, **ignoré** par Git) : `RIOT_API_KEY=...`. Modèle versionné :
  `.env.example`. Ne **jamais** committer de clé.

## Tests

Pas de framework de test. On valide en **headless** avec `SDL_VIDEODRIVER=dummy` :
instancier `App`, piloter les handlers (`_handle_network`, `do_action`,
`current.draw`) et vérifier l'état. On peut sauver une capture avec
`pygame.image.save(app.surface, "x.png")` pour inspecter le rendu. Les scripts
de diagnostic sont temporaires (préfixe `_`) et supprimés après usage.

## Fonds d'écran (design)

Les PNG de `pi_display/assets/` sont produits depuis **`design/backgrounds.html`**
(SVG réglable, style hextech) rasterisé par **`design/rasterize.py`** (Playwright
headless, **outil dev uniquement**, pas sur le Pi). `tools/gen_backgrounds.py`
(Pillow) reste un repli procédural sans dépendance.

## Git / GitHub

- Dépôt distant **privé** : `github.com/maximeLeCorre/raspberry-smart-display`,
  branche `main`. Git Credential Manager fonctionne (push OK).
- `gh` CLI **pas dans le PATH** de la session shell.
- Identité git locale configurée (nom/email) dans ce dépôt.
- Commits **en français**, clairs, co-signés
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Ne pas committer/pousser sans demande explicite de l'utilisateur.

## Déploiement Pi (plus tard)

Raspberry Pi OS **Lite** (sans bureau), Python 3.11+, décommenter
`gpiozero`/`RPi.GPIO` dans `pi_display/requirements.txt`. Lancer
`SDL_VIDEODRIVER=kmsdrm python pi_display/main.py --fullscreen` (auto si Pi
détecté). Mettre l'IP du Pi dans `pc_agent/config.toml`.
