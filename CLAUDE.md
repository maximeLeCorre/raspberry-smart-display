# CLAUDE.md — Guide du projet

Lu au démarrage. **Garde ce fichier ≤ 150 lignes** (coût en tokens) : concis, exact, sans doublon. Dès que tu découvres
un fait non évident (comportement d'API, décision de design, piège), mets à jour la section concernée. **Jamais de secret ici.**

## But
Écran d'info tactile (Raspberry Pi 3 B+ + écran 5" 800×480) : accueil (heure, météo, trains, actus) + écrans selon
l'activité League of Legends du PC Windows. Tout se teste aussi **sur le PC** (fenêtre, agent sur `localhost`).

## Architecture (2 programmes ; WebSocket JSON synchrone `websockets.sync` ; Pi = serveur)
- **`pi_display/`** (Pygame, sur le Pi) = affichage **+ cerveau internet** : API Web Riot + CDN (`riot_web.py`), météo,
  trains, RSS, SSH serveur — clés dans le **.env du Pi**. Appels réseau hors boucle de rendu : `App.async_call(fn, cb)`
  (worker → résultat livré au thread principal par `_drain_io`) ou thread de fond + `snapshot()`.
- **`pc_agent/`** (Windows) = **purement local, SANS clé**. Lit les API **locales** Riot
  (LCU = phase/sélection/historique ; Live Client Data = partie en cours) et pousse écran + données au Pi.
- **Historique** : stocké **sur le Pi en SQLite** (`store.py`), consultable **PC éteint**, alimenté par la **LCU** via l'agent (§ History).

### Modularité
- **module** = un jeu/domaine (`league`, futur `valorant`…), activable en config ; **écran** (`Screen`) = une vue
  d'un module. 2 moitiés : écrans Pi (`modules/<nom>/`) + **Source** agent (`sources/<nom>.py`).
- Modules actifs = **le Pi** (`config.toml [modules]`), annoncés par `hello`. Système
  (horloge, écran `default`) toujours actif. `app.py`/`main.py` sont **agnostiques du jeu** : la logique d'un jeu vit
  dans son instance `Module(app)` (`app.modules[nom]`, créée avant ses écrans) via les crochets `on_connected`/
  `on_disconnected`/`on_agent_screen`/`route_screen`/`on_message`/`tick` ; League = `modules/league/module.py` (store, synchro, bilan, Jouer).
- Ajouter : écrans + `Module` (`modules/__init__.py`) [+ `Source` (`sources/__init__.py`) pour un
  jeu ; un **domaine Pi-only** comme `server` n'a **pas de Source**] + activer en config.

## Commandes (Windows)
- `python` = stub Store (échoue) → **`py -3.11`** ; venv racine **`.venv`**.
- Install : `.\.venv\Scripts\python -m pip install -r pi_display\requirements.txt -r pc_agent\requirements.txt`
- Affichage : `.\.venv\Scripts\python pi_display\main.py --scale 2` · Agent réel : `pc_agent\main.py` ; simu : `--simulate --scenario home|champselect|game|aram|queue|postgame|full`
- ⚠️ En `--simulate`, l'agent vise **`127.0.0.1`** par défaut (pas l'IP Pi de la config) ; `--host` pour changer.
- Pas de hot-reload → **relancer** après modif. TLS : `tools/gen_cert.py` + `tls=true` des 2 côtés.

### Relancer après un changement (**à me proposer par défaut**)
Aucun hot-reload : après toute modif, **proposer** le redémarrage du composant touché (jamais sans accord).
- **`pi_display/`** → **redéployer** (`deploy/deploy_pi.py`, redémarre `pi-display`) ou `ssh … 'sudo systemctl restart pi-display'` ; test local PC : `…python pi_display\main.py --scale 2`.
- **`pc_agent/`** → relancer l'agent : `deploy\restart_pc_agent.ps1` (ou `pc_agent\main.py`).

### Autostart de l'agent PC (Windows)
Tâche planifiée `RaspberryPiDisplayAgent` à l'**ouverture de session**, fenêtre **cachée** (`deploy/pc_agent_launch_hidden.vbs` → `pc_agent_launch.bat`, `PYTHONUNBUFFERED`+`PYTHONUTF8`=1 — log UTF-8 sinon un caractère hors cp1252 plante un `print`), journal `logs/pc_agent.log` (gitignoré).
⚠️ Le `.vbs` lance l'agent **détaché** (tâche finie aussitôt, code 0) ; le relancer = `deploy\restart_pc_agent.ps1` (tue l'instance + `Start-ScheduledTask`), **pas** `Restart-ScheduledTask` (absent en PS 5.1). ⚠️ `.venv\Scripts\python.exe` ouvre 2 process (redirecteur venv + interpréteur).
Installer (**admin/UAC**, auto-élévation) : `…\install_pc_agent_autostart.ps1` ; désinstaller : `…\uninstall_pc_agent_autostart.ps1` (relancer l'installeur après déplacement du dépôt).

## Protocole réseau
- **Sécurité** (2 couches activables) : TLS `wss://` (cert auto-signé du Pi épinglé par
  l'agent, `check_hostname=False`) et/ou **jeton** `DISPLAY_AUTH_TOKEN` (.env racine, 1er
  message `auth` de l'agent). `tls=false`/jeton vide = clair/ouvert (test local).
- **Pi → agent** : `hello{modules}`, `request_lcu_sync{since}`, `request_player_sync{riotId,known}`, `request_lcu_detail{gameId}`, `request_lcu_timeline{gameId}`,
  `lcu_action{action…}` (accepter un ready-check ; ou `play{queueId,invite}` = bouton « Jouer », § Bouton Jouer).
- **agent → Pi** : `auth{token}`, `set_screen{screen}`, `data{screen,payload}`
  (queue/champselect/lol ; joueur = `riotId` Nom#TAG ; `default`/`playStatus` = étape du bouton
  Jouer), `store_matches{games,done}`, `store_player_games{riotId,games,done}` (ami), `lcu_detail{gameId,payload}`, `lcu_timeline{gameId,payload}`.
- Interne (serveur Pi) : `_connected`/`_disconnected` (**seulement si le client COURANT part** : après veille,
  l'ancien lien tombe après la reconnexion). Déconnexion → `default`. Heartbeat agent (`set_screen` répété) = no-op.
- NB : dossiers/icônes/splash ne sont **pas** des messages réseau — le Pi les fait lui-même
  (`LeagueModule.request_player_info/request_icon/request_splash` → `riot_web`/CDN, en async).

## Écrans (`pi_display/`)
- `screen.py` : base `Screen` (attr `cycle`), fond PNG chargé 1×, redessin par **dirty rects**.
- **system/** : `default` (horloge, météo, pastille PC haut-gauche, alerte santé Pi, 1 actu qui tourne, **dock de tuiles
  vivantes** selon modules : Jouer/Rejoindre, Historique, Serveur, Actus ; états écrits, pas que colorés : user daltonien),
  `news` + `rss_feed` (flux lu par le Pi ; article **complet** = page web parsée par `article_text.py` `c-chapo`/`c-body`, paginée ▲/▼), `weather` (courbe du jour + pluie, ◀/▶ + menu des jours ; clic sur la météo).
  `weather.py` = Open-Meteo sans clé (`[weather]`) → série **horaire** upsertée dans **`weather.db`** (base vide → rattrapage,
  ~50 j réels) ; `pi_health.py` = /proc local, seuils `[pi_health]` (CPU soutenu). Tout marche PC éteint.
- **league/** : `queue` (ready-check, **bouton Accepter** → `lcu_action`), `champselect` (clic → dossier + splash), `lol`, `postgame`, `history`.
- `LolScreen` : **timers d'objectifs** (Faille only) + **dossier adverse au clic** (`riotId`) ; compteurs extrapolés (agent ~1/s).
- **`counters`** (**défaut en jeu** via `route_screen` ; TABLEAU → `lol`, ÉCARTS ← `lol`/`postgame`) : compteurs ton équipe/adversaires + **écart** écrit (or/kills/CS/niveau moyen) et tendance
  1 min (courbes testées, **rejetées** par l'user). Direct = message courant + relevé /10 s, or **estimé** (`priceTotal` ; ⚠️ `price` Live =
  dernière étape). Après : timeline **LCU** (1 pt/min, or exact) → table `timelines`, une à la fois ; ⚠️ `match-v5` sans ARAM Chaos (403).

### PostGame (`postgame`, code-drawn)
Barres horizontales des 10 joueurs ; onglets = métrique (`dmg/taken/gold/cs/vision/heal`),
triées. Couleurs : **toi=jaune, amis=rose, alliés=bleu, ennemis=rouge** (équipe via `team`
du joueur `isSelf`). Bandeau bas = tes stats. Amis = `[lol] friends=["Nom#TAG"]` (insensible
casse), marqués **à la lecture**. Détail lu du **store** (offline) sinon demandé à l'agent au
clic (`request_lcu_detail`). `METRICS` (écran) ↔ clés `metrics` (builder) alignées.

### History (`history`, code-drawn) + Store SQLite
- Liste lue depuis **`store.py`** (SQLite `matches.db`, *.db gitignoré). Filtres SQL : **ARAM Chaos (défaut)** /
  Classé / Normale / ARAM ; ◀/▶. Clic → `LeagueModule.open_postgame_review(gameId)` (revue, RETOUR → liste).
- **Toutes les parties viennent de la LCU** (via agent) : résumé **+ bilan 10 joueurs** (PC éteint OK).
- **STATS** (`stats`, bouton de l'historique) : toi seul / ami seul / **ensemble = même équipe** (`[lol] compare`) ; bouton **Période** (`period.py`, dates incluses sur `game_creation` ms).
  Table `participations` (1 ligne/joueur/partie, rétro-remplie des bilans) ; parties de l'ami lues par
  l'agent (`/products/lol/{puuid}/matches`, puuid via liste d'amis), **hors historique affiché**.
- **Synchro** (`LeagueModule.sync_lcu` → `request_lcu_sync{since}` → agent `iter_lcu_sync` → lots
  `store_matches`) : à l'**ouverture de l'historique**, à la **connexion de l'agent**, en **fin
  de partie** (immédiate + re-synchros 8/20 s) et par **scan périodique** (`_maybe_sync`,
  `[lol] sync_minutes`, défaut 3 min). Bilan « dernière partie » affiché si **plus récent que
  `_postgame_baseline`**, sinon **« détail non disponible »** (`_postgame_unavailable_later`).
  ⚠️ La LCU **ne pagine pas** → seulement les **20 récentes** ; l'historique s'accumule au fil du jeu.

### Serveur (`server`, module **Pi-only** : pas de Source — SSH **depuis le Pi**, marche PC éteint)
Écran code-drawn (jauges CPU/RAM/disque + **courbes CPU/RAM** `history()` en mémoire, `[server] history_minutes` + Démarrer/Arrêter/Redémarrer d'un service systemd ; accès **onglet accueil + cycle**). **Joueurs Minecraft** : `minecraft_port` du service → `minecraft_ping.py` (Server List Ping TCP, sans SSH, ≤ 12 pseudos) → `link.players(unit)`.
`server_link.py` = paramiko persistant, poll d'**une** cmd SSH `clé=valeur` (`[server] poll_seconds`), **CPU% = delta `/proc/stat`** côté Pi. Contrôle = `sudo systemctl` (**NOPASSWD** côté serveur). Config `[server]` + `[[server.services]]` ; IP = **`SERVER_HOST`** (.env, prioritaire sur `host`).
**Sauvegarde** (`backup.py`, `[server.backup]`) : 1×/jour, copie SQLite cohérente de `matches.db`+`weather.db` → SFTP `~/pi-display-backups/<base>-AAAA-MM-JJ.db`, rotation `keep_days`.
Clé **privée** dans `certs/` (gitignoré, copiée par deploy ; `known_hosts` TOFU). ⚠️ paramiko dans `requirements.txt` **et** le `pip` de `deploy_pi.py`.
### Trains (`transit`, Pi-only) — API **PRIM** IDFM, clé `IDFM_API_KEY` (.env), en-tête `apikey`
`transit_feed.py` : `stop-monitoring` (ZdA `[transit] stop_area`, Chaville RD = 43241) + `general-message` par ligne /5 min, SIRI Lite. ⚠️ **Quota 1 000 req/jour PAR endpoint** (RAZ minuit UTC) → rythme des départs calé sur `x-ratelimit-remaining-day` (`next_delay`), nuit 15 min, 429 = pause jusqu'au `retry-after`.
⚠️ **2 lignes** : L (C01740) **et U** (C01741) → `[transit.lines]` ; 2 colonnes par direction (`paris_destinations`), états **écrits** ;
tuile Trains **remplace Actus** (liste via le bandeau) ; à droite de l'horloge : **arrivée en gare** du prochain St-Lazare (`home_*`).

## API Riot & pièges
- **LCU** (`pc_agent/lcu.py`, agent, client ouvert) : phase, sélection, historique, **actions**
  (`post`, ex. `/lol-matchmaking/v1/ready-check/accept`). Auth = port+token du process
  `LeagueClientUx.exe`, `verify=False`. Noms de champions via **Community Dragon** (⚠️ échec → réessai 60 s, jamais de table vide à vie ; noms vides du store réparés par `fill_champion_names`). ⚠️ Nom→id en partie : variantes **60xxx** de même nom (→ vrai champion prioritaire) et nom Live **localisé** (« Maître Yi ») → via `rawChampionName` (alias). ⚠️ PUUID
  LCU = **interne**, rejeté par l'API Web → l'agent envoie le **Riot ID**, le Pi résout le vrai
  PUUID (`resolve_puuid`). ⚠️ « ARAM Chaos » = gameMode interne **`KIWI`**.
- **Live Client Data** (`pc_agent/riot_api.py`, `127.0.0.1:2999`) : **en partie uniquement**.
- **API Web** (`pi_display/riot_web.py`, Pi, stdlib urllib) : `account-v1`(→PUUID), `summoner-v4`, `league-v4`,
  `champion-mastery-v4`, `match-v5`. ⚠️ `match-v5` **n'a pas les customs** (d'où la LCU). Tolérant aux erreurs.
- **Icônes** : `champion-icons` (CDragon) = **les mêmes qu'en jeu** (HUD `*_square_0`, cadrage serré). Testé et rejeté par
  l'user : tuiles de splash (trop dézoomées) et skins joués. Cache disque **`icons.db`** (`icon_cache.py`, hors sauvegarde),
  repris quand le patch CDragon change (relu 1×/h ; vide aussi le cache mémoire des écrans `modules/league/icons.py`).

## Agent (`pc_agent/main.py`, `sources/`)
Chaque tick (`update_interval` 1–2 s) : 1ère `poll()` non-None gagne → `set_screen` (+ `data`).
`LeagueSource` mappe `gameflow_phase` → `queue`/`champselect`/`lol`/`postgame` (payload None).
`handle_request` répond au Pi : `request_lcu_sync` (synchro en **thread**, `store_matches` par
lots), `request_lcu_detail`, `request_lcu_timeline` (écarts), `lcu_action`. `summarize_full` (partie) porte `game_mode`/
`objectives`/`riotId`. **Agent sans clé ni `RiotWeb`.** Simu (`simulator.py`) = données locales fictives ; l'enrichissement/historique dépendent du Pi (clé/compte réels).

### Bouton « Jouer une ARAM Chaos » (défaut) → action `play`
`LeagueSource._play` (thread) : lance le client si fermé, crée le lobby (`[lol] lobby_queue`,
2400=KIWI) si pas déjà le bon, invite `[lol] lobby_invite` s'il est en ligne — **toute étape déjà
faite est sautée** ; pousse `playStatus` au Pi (bandeau, clic neutralisé pendant). ⚠️ **Lancer
League** : `--launch-product` peu fiable → **API Riot Client** (`riot_client.py`, POST
`product-launcher`, auth lockfile), **réessais** (1er POST souvent ignoré) jusqu'au process League ;
lockfile résiduel → se fier à `is_logged_in` (API), pas au fichier. ⚠️ Jamais `taskkill /F` League
(fâche **Vanguard** → reboot) ; le bouton ne tue rien.

## Config & secrets
- `pi_display/config.toml` : réseau, FPS, GPIO, `[rss]`, `[modules]`, **`[riot] platform/regional`**,
  **`[lol] summoner`/`friends`/`lobby_queue`/`lobby_invite`** (bouton Jouer).
- `pc_agent/config.toml` : IP/port du Pi, `update_interval`, process LoL, `[lol] launch_exe`/`launch_args` (Riot Client, pour le bouton Jouer). **Pas de clé.**
- **`.env`** (racine, **ignoré**, modèle `.env.example`) : `RIOT_API_KEY`, `DISPLAY_AUTH_TOKEN`, `SERVER_HOST`, `IDFM_API_KEY` ;
  ⚠️ c'est le `.env` **du Pi** qui compte (Pi autonome) : `deploy_pi.py` y copie ces 4 clés.

## Fonds · Tests · Git · Déploiement
- **Fonds** : PNG 800×480 dans `assets/` (`default`/`queue`/`champselect`/`lol`), cadres **dans le PNG** (code au pixel ;
  `default.png` = `tools/gen_default_bg.py` sur `default_base.png`). Code-drawn : `news`, `weather`, `transit`, `postgame`, `history`, `stats`, `server`.
- **Tests** : **pytest** (`tests/`) → `.\.venv\Scripts\python -m pytest` **avant chaque déploiement** ; headless (`conftest.py`). Rendus : scripts jetables `_`.
- **Git** : repo privé `maximeLeCorre/raspberry-smart-display`, branche `main`. Commits **en français**
  co-signés `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. **Pas de commit/push sans demande.**
- **Déploiement** : `deploy/deploy_pi.py` (~10 s ; clé SSH `~/.ssh/id_ed25519`, repli `PI_PASS` ; empreinte Pi épinglée
  `deploy/known_hosts`). Deps apt/pip réinstallées **seulement si leur liste change** (`--full` force). Archive
  `pi_display/` (hors `_*`/`__pycache__`/**`*.db`**) + `certs/` + `.env` ; service **systemd** `pi-display` (autostart, `kmsdrm`,
  plein écran, lié à **tty1** = DRM master ; libs EGL/GLES Mesa ; jamais exclure les `__init__.py`). Logs : **`journalctl -t
  pi-display -f`** (`-u` = systemd seul : PAM/tty1 met le process en session de login). 1er boot écran noir → rebooter.
  ⚠️ **Wi-Fi** : en 5 GHz (faible) la box rejetait le Pi → bug `cfg80211_roamed` de brcmfmac → NM abandonnait (Pi hors réseau, écran vivant). deploy force **2,4 GHz**, `roamoff=1`, powersave off, réessais infinis + chien de garde **`pi-netwatch`** (`journalctl -t pi-netwatch`).
