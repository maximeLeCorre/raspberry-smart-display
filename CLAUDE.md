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
  en fenêtre sur PC. Serveur WebSocket qui reçoit mode + données.
- **`pc_agent/`** — agent de fond (Windows). Détecte la phase de jeu, lit les
  API locales/Web de Riot, envoie au Pi. Client WebSocket.

Communication : **WebSocket JSON bidirectionnel** (lib `websockets`, API
**synchrone** `websockets.sync` des deux côtés — pas d'asyncio). Le Pi est
serveur, l'agent est client.

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

PC → Pi :
- `{"type":"set_mode","mode":"default|champselect|lol"}`
- `{"type":"data","mode":"lol","payload":{...}}`
- `{"type":"data","mode":"champselect","payload":{"phase":"champselect","players":[...]}}`
- `{"type":"player_info","puuid":"...","info":{...}}` (réponse à une demande)
- `{"type":"icon","championId":...,"iconB64":"..."}` (réponse à une demande d'icône)

Pi → PC :
- `{"type":"request_player_info","puuid":"...","summonerId":...,"championId":...}`
- `{"type":"request_icon","championId":...}`

Interne (synthétisé par le serveur Pi, pas envoyé par l'agent) :
- `{"type":"_connected"}` / `{"type":"_disconnected"}`

La déconnexion du client fait revenir le Pi au **mode par défaut**.

## Système de modes (`pi_display/modes/`)

- `base.py` : classe `Mode`. Fond PNG pré-rendu chargé **une fois** ; on ne
  redessine que les zones dynamiques (**dirty rects**) pour ménager le Pi 3.
  Repli couleur unie si le PNG manque.
- `default_mode.py` : heure/date, placeholder météo, et un **badge « Rejoindre »**
  (voir plus bas).
- `champ_select_mode.py` : grille de notre équipe (icône + pseudo + position),
  clic sur un joueur → `app.request_player_info(...)` → panneau de détails.
- `lol_mode.py` : résumé de la partie en direct (temps, KDA, or, CS, score).

Ajouter un mode : hériter de `Mode`, définir `name`/`background_name`,
implémenter `draw()` (et `update_data()` si réseau) ; l'enregistrer dans
`app.py` (`self.modes` + `self.mode_order`) ; ajouter son fond dans
`tools/gen_backgrounds.py`.

### Comportements clés (app.py)

- **Verrou manuel** (`manual_mode`) : un retour manuel (bouton/Échap/zone
  tactile) force le mode par défaut et **ignore les `set_mode` du réseau**
  jusqu'à reconnexion de l'agent ou `set_mode default` explicite.
- **Badge « Rejoindre »** : `network_mode` mémorise le dernier mode demandé par
  l'agent. Si on est revenu au défaut manuellement alors qu'un mode LoL est
  actif, le `DefaultMode` affiche un badge cliquable (`app.joinable_mode()` /
  `app.join_network_mode()`) pour y retourner.

### Entrées

- Tactile = souris Pygame. Clavier = fallback des boutons GPIO :
  **Échap** = retour défaut, **Tab** = mode suivant, **F1** = overlay debug.
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

## Détection de phase (agent, `main.py`)

`gameflow_phase` pilote le mode : menu/lobby/file → `default` ;
`ChampSelect` → `champselect` ; `InProgress` → `lol` (via Live Client Data API).
Mise à jour ≤ 1 fois / `update_interval` (config, 1–2 s).

Mode simulation (`simulator.py`) : scénarios `full`/`champselect`/`game` avec
fausses données. Le joueur **maxoulefou** (notre compte, constante `REAL_PLAYER`)
renvoie de **vraies** stats au clic via l'API Web (si `RIOT_API_KEY` présent),
sans lancer de partie ; les autres joueurs restent fictifs.

> Note : le PUUID renvoyé par `account-v1` est **chiffré par clé d'API** — il
> change quand la clé change (clé dev renouvelée). Cohérent tant qu'on garde la
> même clé sur une session, ce qui est le cas.

## Config & secrets

- `pi_display/config.toml` : host/port d'écoute, résolution, FPS, broches GPIO.
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
