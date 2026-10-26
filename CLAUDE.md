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
- Générer le certificat TLS : `.\.venv\Scripts\python pi_display\tools\gen_cert.py` (puis `tls = true` dans les deux config.toml)
- Lancer l'affichage : `.\.venv\Scripts\python pi_display\main.py --scale 2`
- Lancer l'agent (simulation) : `.\.venv\Scripts\python pc_agent\main.py --simulate --scenario champselect|game|full`
- Lancer l'agent (réel) : `.\.venv\Scripts\python pc_agent\main.py`

> Python ne recharge pas à chaud : après une modif de code, **relancer** les
> programmes concernés.

## Protocole réseau (messages JSON)

**Sécurité du lien = deux couches complémentaires, chacune activable.**
- **TLS (`wss://`), chiffre le canal + authentifie le Pi.** Activé par
  `tls = true` dans **les deux** `config.toml` (`pi_display [network]` et
  `pc_agent [pi]`) — doivent concorder. Le Pi sert avec un **certificat
  auto-signé** (`certs/pi-display.crt`+`.key`, générés par
  `pi_display/tools/gen_cert.py`, dossier `certs/` **ignoré par Git**) ; l'agent
  l'**épingle** (`cert_file`) : il vérifie le certificat mais **pas le nom
  d'hôte** (`check_hostname=False`, donc l'IP du Pi peut changer). Si le Pi et
  l'agent sont sur deux machines, **copier le `.crt`** (public) côté agent.
  Contextes construits par `config.build_server_ssl` (Pi) et
  `main.build_client_ssl` (agent) ; `tls=false` ⇒ `ws://` en clair (test local).
  ⚠️ `cryptography` n'est requis **que** pour (re)générer le certificat.
- **Jeton (`DISPLAY_AUTH_TOKEN`), authentifie le client.** TLS est à sens unique
  (le Pi accepte tout client, son cert étant public) : le jeton reste donc utile
  **en plus** de TLS, et TLS chiffre le jeton (plus interceptable/rejouable).

**Authentification (optionnelle, jeton partagé).** Si `DISPLAY_AUTH_TOKEN` est
défini dans `.env` (racine, lu par les **deux** côtés), le **premier** message de
l'agent doit être `{"type":"auth","token":"..."}` ; sinon le Pi refuse et ferme
la connexion (tant qu'il n'est pas authentifié, un client n'écrase pas l'agent
courant — règle aussi le bug du « client fantôme »). Jeton **vide/absent =
authentification désactivée** (le Pi accepte tout le réseau local, comportement
historique, pratique en test local — mais sur le vrai réseau, **mettre un jeton**
identique des deux côtés). Côté Pi : `config.load_auth_token()` → `NetworkServer`
(`_authenticate`, timeout 5 s). Côté agent : `Sender(url, auth_token=...)` envoie
le handshake à chaque (re)connexion. En cas de refus, le Pi renvoie
`{"type":"auth_result","ok":false}` puis ferme.

Pi → PC (à la connexion) :
- `{"type":"hello","modules":["system","league"]}` (modules actifs annoncés)

PC → Pi (premier message si jeton configuré) :
- `{"type":"auth","token":"..."}`

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
- `modules/system/default_screen.py` : `DefaultScreen` (horloge, date, **3
  dernières actus RSS** cliquables, onglet **« France Info »** en haut à gauche,
  et **bandeau LoL « Rejoindre »** en haut, conditionnel). Module système,
  toujours actif. La météo a été retirée.
- `modules/system/news_screen.py` : `NewsScreen` (écran **« France Info »**,
  `name="news"`, hors cycle) : liste défilante des articles (flèches ▲/▼) et vue
  détail (titre + date + résumé + lien). Ouvert depuis l'accueil (onglet ou clic
  sur un titre → détail) ; RETOUR en détail → liste, en liste → accueil. Dessiné
  **entièrement en code** (pas de PNG de fond).
- `modules/system/rss_feed.py` : flux RSS récupéré **par le Pi lui-même** (thread
  de fond, stdlib `urllib`+`xml.etree`, gère RSS et Atom). `get_feed(app)` =
  instance **unique partagée** accueil ↔ France Info (lit la config `[rss]`). Le
  flux n'a pas besoin du PC : l'accueil marche agent déconnecté. Pas de message
  réseau RSS (tout est local au Pi).
- `modules/league/` : `QueueScreen` (file + ready-check), `ChampSelectScreen`
  (équipe, timer de phase, bans, clic → détails + **splash art**), `LolScreen`
  (complément à l'écran de jeu, voir ci-dessous), `PostGameScreen` (bilan).

**`LolScreen` (partie en cours) — philosophie** : le scoreboard brut (KDA/CS/or/
killfeed) est déjà visible en jeu, donc l'écran privilégie ce qu'on n'a PAS
facilement en jeu : (1) **timers d'objectifs** Dragon/Baron/Héraut (**Faille
uniquement**, logés en haut du **panneau bas**) ; (2) **dossier adverse au clic**
(rang/winrate/mains via l'API Web) — surtout utile en ARAM où on ne scoute pas en
sélection ; le dossier remplace le contenu du panneau bas. Horloge et compteurs
**extrapolés** localement (l'agent n'envoie que ~1/s) pour un décompte fluide.
S'adapte au `game_mode` (pas d'objectifs en ARAM). Clic sur une ligne =
`request_player_info` (réutilise le flux du champ select) ; re-clic = referme.

Icônes/splash : réclamés à la demande (request_icon/request_splash), cache côté
Pi. Splash = art de chargement **Data Dragon** par alias
(`.../cdn/img/champion/loading/{alias}_0.jpg`).

Ajouter un écran : hériter de `Screen`, définir `name`/`background_name`,
implémenter `draw()` (et `update_data()` si réseau) ; l'ajouter à la liste
`screens` du `Module` concerné ; ajouter son fond.

> **Cadres = dans le fond, pas en code.** Les cadres/panneaux/zones sont
> **dessinés directement dans les PNG de fond** (un par écran). Le code ne trace
> plus de bordures : il **positionne le contenu au pixel** dans les zones de
> l'image (constantes `*_X/_TOP/ROW_H/PANEL…` en tête de chaque écran). Si tu
> changes un fond, réaligne ces constantes (mesure les zones sombres de l'image,
> ex. via Pillow). ⚠️ Le fond de `default` décale le contenu vers la droite
> (illustration à gauche) → `DefaultScreen` centre sur `CENTER_X`, pas `width/2`.
> Le fond `default.png` est **régénéré** par `tools/gen_default_bg.py` (bake les
> panneaux horloge/actu/onglet sur l'art d'origine `assets/default_base.png`) : si
> tu déplaces un panneau, édite ce script ET les constantes de `default_screen.py`
> (elles doivent rester identiques), puis relance le script.

### Comportements clés (app.py)

- `App` construit `self.screens` depuis les **modules activés** (registre
  `MODULES` filtré par `config[modules]`) ; `screen_order` = écrans `cycle=True`.
- **Verrou manuel** (`manual_screen`) : un retour manuel force l'écran `default`
  et **ignore les `set_screen` réseau** jusqu'à reconnexion ou `default` explicite.
- **Bandeau « Rejoindre » (LoL)** : `network_screen` mémorise le dernier écran
  demandé ; `DefaultScreen` affiche en haut un bandeau cliquable
  (`app.joinable_screen()` / `app.join_screen()`) pour y retourner.
- **Onglet France Info** : l'accueil ouvre l'écran `news` en posant
  `manual_screen = "news"` (verrou) ; le RETOUR de `news` ramène au défaut.

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
`InProgress` → `lol` (Live Client Data API ; payload `summarize_full` enrichi de
`game_mode`, `objectives` [Faille, calculés dans `objectives.py`] et du `puuid`
de chaque joueur pour le dossier au clic — résolu via `RiotWeb.resolve_puuid`,
mis en cache donc gratuit après le 1er tick) ;
`WaitingForStats`/`PreEndOfGame`/`EndOfGame` → `postgame` (historique LCU) ;
client fermé/menu → `poll()` renvoie None (l'agent affiche `default`). Les
builders queue/postgame sont dans `phases.py`, la sélection dans `champ_select.py`.

Mode simulation (`simulator.py`) : scénarios `full`/`champselect`/`game`/`aram`/
`queue`/`postgame` avec fausses données (`game` = Faille avec objectifs, `aram` =
ARAM sans objectifs ; les adversaires fictifs ont un dossier cliquable). Le joueur **maxoulefou** (notre compte, constante `REAL_PLAYER`)
renvoie de **vraies** stats au clic via l'API Web (si `RIOT_API_KEY` présent),
sans lancer de partie ; les autres joueurs restent fictifs.

> Note : le PUUID renvoyé par `account-v1` est **chiffré par clé d'API** — il
> change quand la clé change (clé dev renouvelée). Cohérent tant qu'on garde la
> même clé sur une session, ce qui est le cas.

## Config & secrets

- `pi_display/config.toml` : host/port d'écoute, résolution, FPS, broches GPIO,
  **`[rss]`** (flux d'actualité de l'accueil : `url`/`refresh_minutes`/`max_items` ;
  `url = ""` pour désactiver), **`[modules]`** (active/désactive les modules —
  source de vérité, poussée à l'agent).
- `pc_agent/config.toml` : IP/port du Pi, `update_interval`, noms des process
  LoL, `[riot] platform/regional`, `[features] player_info`.
- **`.env`** (racine, **ignoré** par Git) : `RIOT_API_KEY=...` et
  `DISPLAY_AUTH_TOKEN=...` (jeton d'auth du lien Pi↔agent, voir « Protocole
  réseau » ; vide = auth désactivée). Modèle versionné : `.env.example`. Ne
  **jamais** committer de secret. Le `.env` doit exister **sur le Pi aussi** (au
  moins le jeton) pour que l'authentification soit active.

## Tests

Pas de framework de test. On valide en **headless** avec `SDL_VIDEODRIVER=dummy` :
instancier `App`, piloter les handlers (`_handle_network`, `do_action`,
`current.draw`) et vérifier l'état. On peut sauver une capture avec
`pygame.image.save(app.surface, "x.png")` pour inspecter le rendu. Les scripts
de diagnostic sont temporaires (préfixe `_`) et supprimés après usage.

## Fonds d'écran (design)

**Un PNG 800×480 par écran** dans `pi_display/assets/` : `default`, `queue`,
`champselect`, `lol`, `postgame`. Ils **contiennent les cadres/panneaux/zones**
(le code ne dessine que le contenu, aligné dessus — voir « Cadres = dans le fond »
plus haut). Les fonds actuels ont été générés par un outil de design externe
(IA), pas procéduralement — **chaque fond est propre à la mise en page de son
écran** (ne plus les partager entre écrans). Exceptions : l'écran `news` (France
Info) n'a **pas** de PNG (dessiné en code) ; `default.png` est **dérivé** de
`default_base.png` (l'art brut) par `tools/gen_default_bg.py`, qui y bake les
panneaux horloge/actu + l'onglet — régénérer via ce script, pas à la main.

Anciens outils procéduraux conservés en repli/historique : `design/backgrounds.html`
+ `design/rasterize.py` (SVG hextech, Playwright) et `tools/gen_backgrounds.py`
(Pillow). Non utilisés par les fonds courants.

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
