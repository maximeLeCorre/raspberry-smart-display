# CLAUDE.md — Guide du projet

Lu au démarrage. **Garde ce fichier ≤ 150 lignes** (coût en tokens) : concis, exact,
sans doublon. Dès que tu découvres un fait non évident (comportement d'API, décision de
design, piège), mets à jour la section concernée. **Jamais de secret ici.**

## But
Écran d'info tactile (Raspberry Pi 3 + écran 5" 800×480) affichant des écrans selon
l'activité League of Legends du PC Windows. Tout se teste **sur le PC** (affichage en
fenêtre, agent sur `localhost`) tant que l'écran physique n'est pas livré.

## Architecture (2 programmes ; WebSocket JSON synchrone `websockets.sync` ; Pi = serveur)
- **`pi_display/`** (Pygame, sur le Pi) = affichage **+ cerveau internet**. Interroge
  lui-même l'**API Web Riot** (rangs/winrate/mains, dossiers joueurs) et les **CDN**
  (icônes Community Dragon, splash Data Dragon) → `riot_web.py`. `RIOT_API_KEY` vit dans
  le **.env du Pi**. Appels réseau hors boucle de rendu via `App.async_call(fn, cb)`
  (worker thread → résultat livré au thread principal par `_drain_io`).
- **`pc_agent/`** (Windows) = **purement local, SANS clé**. Lit les API **locales** Riot
  (LCU = phase/sélection/historique ; Live Client Data = partie en cours) et pousse
  écran + données au Pi.
- **Historique** : stocké **sur le Pi en SQLite** (`store.py`), consultable **PC éteint**.
  Alimenté par la **LCU** via l'agent (§ History).

### Modularité
- **module** = un jeu/domaine (`league`, futur `valorant`…), activable en config.
- **écran** (`Screen`) = une vue d'un module. 2 moitiés : écrans Pi (`modules/<nom>/`) +
  **Source** agent (`sources/<nom>.py`).
- Modules actifs = **le Pi** (`config.toml [modules]`), annoncés par `hello`. Système
  (horloge, écran `default`) toujours actif. `app.py`/`main.py` sont agnostiques du jeu.
- Ajouter un jeu : écrans + `Module` (`modules/__init__.py`) ET `Source`
  (`sources/__init__.py`) + activer en config.

## Commandes (Windows)
- `python` = stub Store (échoue) → **`py -3.11`** ; venv racine **`.venv`**.
- Install : `.\.venv\Scripts\python -m pip install -r pi_display\requirements.txt -r pc_agent\requirements.txt`
- Affichage : `.\.venv\Scripts\python pi_display\main.py --scale 2`
- Agent réel : `pc_agent\main.py` ; simu : `--simulate --scenario home|champselect|game|aram|queue|postgame|full`
- ⚠️ En `--simulate`, l'agent vise **`127.0.0.1`** par défaut (pas l'IP Pi de la config) ; `--host` pour changer.
- Pas de hot-reload → **relancer** après modif. TLS : `tools/gen_cert.py` + `tls=true` des 2 côtés.

## Protocole réseau
- **Sécurité** (2 couches activables) : TLS `wss://` (cert auto-signé du Pi épinglé par
  l'agent, `check_hostname=False`) et/ou **jeton** `DISPLAY_AUTH_TOKEN` (.env racine, 1er
  message `auth` de l'agent). `tls=false`/jeton vide = clair/ouvert (test local).
- **Pi → agent** : `hello{modules}`, `request_lcu_sync{since}`, `request_lcu_detail{gameId}`,
  `lcu_action{action}` (ex. accepter un ready-check).
- **agent → Pi** : `auth{token}`, `set_screen{screen}`, `data{screen,payload}`
  (queue/champselect/lol ; chaque joueur porte un `riotId`=Nom#TAG), `store_matches{games,done}`
  (parties à stocker), `lcu_detail{gameId,payload}`.
- Interne (serveur Pi) : `_connected`/`_disconnected`. Déconnexion → écran `default`
  (l'historique reste consultable : il est en base locale).
- NB : dossiers/icônes/splash ne sont **pas** des messages réseau — le Pi les fait lui-même
  (`App.request_player_info/request_icon/request_splash` → `riot_web`/CDN, en async).

## Écrans (`pi_display/`)
- `screen.py` : base `Screen` (attr `cycle`), fond PNG chargé 1×, redessin par **dirty rects**.
- **system/** : `default` (horloge/date, 3 actus RSS, onglet « France Info », bouton
  « Dernières parties », bandeau « Rejoindre » LoL conditionnel), `news` (code-drawn),
  `rss_feed` (flux récupéré par le Pi, stdlib urllib/xml ; marche agent déconnecté).
- **league/** : `queue` (file + ready-check avec **gros bouton Accepter** → `lcu_action`),
  `champselect` (équipe/timer/bans, clic → dossier + splash), `lol`, `postgame`, `history`.
- `LolScreen` : complément au jeu → **timers d'objectifs** (Dragon/Baron/Héraut, Faille only)
  + **dossier adverse au clic** (via `riotId`). Horloge/compteurs extrapolés (agent ~1/s).

### PostGame (`postgame`, code-drawn)
Barres horizontales des 10 joueurs ; onglets = métrique (`dmg/taken/gold/cs/vision/heal`),
triées. Couleurs : **toi=jaune, amis=rose, alliés=bleu, ennemis=rouge** (équipe via `team`
du joueur `isSelf`). Bandeau bas = tes stats. Amis = `[lol] friends=["Nom#TAG"]` (insensible
casse), marqués **à la lecture**. Détail lu du **store** (offline) sinon demandé à l'agent au
clic (`request_lcu_detail`). `METRICS` (écran) ↔ clés `metrics` (builder) alignées.

### History (`history`, code-drawn) + Store SQLite
- Liste lue depuis **`store.py`** (SQLite `matches.db`, *.db gitignoré). Filtres SQL (gauche
  de RETOUR) : **ARAM Chaos (défaut)** / Classé / Normale / ARAM ; pagination ◀/▶ (triangles).
  Clic → `App.open_postgame_review(gameId)` (mode revue, RETOUR → liste).
- **Toutes les parties viennent de la LCU** (via agent), stockées avec résumé **+ bilan 10
  joueurs** (stats consultables PC éteint).
- **Synchro** (`App.sync_lcu` → `request_lcu_sync{since}` → agent `iter_lcu_sync` → lots
  `store_matches`) déclenchée à l'**ouverture de l'historique**, à la **connexion de
  l'agent**, en **fin de partie** (immédiate + re-synchros différées 8/20 s), et par un
  **scan périodique** (`_maybe_sync` dans `run()`, `[lol] sync_minutes`, défaut 3 min ;
  filet insensible au délai d'indexation LCU). Bilan « dernière partie » : affiché quand
  une partie **plus récente que `_postgame_baseline`** arrive ; sinon **« détail non
  disponible »** (repli `_postgame_unavailable_later`). ⚠️ La LCU **ne pagine pas**
  (`begIndex/endIndex` ignorés) → seulement les **20 récentes** exposées ; l'historique
  **s'accumule au fil des parties jouées**.

## API Riot & pièges
- **LCU** (`pc_agent/lcu.py`, agent, client ouvert) : phase, sélection, historique, **actions**
  (`post`, ex. `/lol-matchmaking/v1/ready-check/accept`). Auth = port+token du process
  `LeagueClientUx.exe`, `verify=False`. Noms de champions via **Community Dragon**. ⚠️ PUUID
  LCU = **interne**, rejeté par l'API Web → l'agent envoie le **Riot ID**, le Pi résout le vrai
  PUUID (`resolve_puuid`). ⚠️ « ARAM Chaos » = gameMode interne **`KIWI`**.
- **Live Client Data** (`pc_agent/riot_api.py`, `127.0.0.1:2999`) : **en partie uniquement**.
- **API Web** (`pi_display/riot_web.py`, Pi, stdlib urllib) : `account-v1`(→PUUID), `summoner-v4`,
  `league-v4`, `champion-mastery-v4`, `match-v5`. ⚠️ `match-v5` **n'a pas les customs** (d'où la LCU
  pour l'historique). CDN icônes/splash. Tolérant aux erreurs (renvoie None/partiel).

## Agent (`pc_agent/main.py`, `sources/`)
Chaque tick (`update_interval` 1–2 s) : 1ère `poll()` non-None gagne → `set_screen` (+ `data`).
`LeagueSource` mappe `gameflow_phase` → `queue`/`champselect`/`lol`/`postgame` (payload None).
`handle_request` répond au Pi : `request_lcu_sync` (synchro en **thread**, `store_matches` par
lots), `request_lcu_detail`, `lcu_action`. `summarize_full` (partie) porte `game_mode`/
`objectives`/`riotId`. **Agent sans clé ni `RiotWeb`.** Simu (`simulator.py`) = données locales
fictives ; l'enrichissement/historique dépendent du Pi (clé/compte réels).

## Config & secrets
- `pi_display/config.toml` : réseau, FPS, GPIO, `[rss]`, `[modules]`, **`[riot] platform/regional`**,
  **`[lol] summoner`/`friends`**.
- `pc_agent/config.toml` : IP/port du Pi, `update_interval`, process LoL. **Pas de clé.**
- **`.env`** (racine, **ignoré**) : `RIOT_API_KEY` (permanente) + `DISPLAY_AUTH_TOKEN`. Modèle
  `.env.example`. ⚠️ Le `.env` **du Pi** doit avoir la clé (le Pi est autonome) + le jeton ;
  `deploy_pi.py` les copie.

## Fonds · Tests · Git · Déploiement
- **Fonds** : 1 PNG 800×480/écran dans `assets/` (`default`/`queue`/`champselect`/`lol`), cadres
  **dans le PNG** (le code positionne le contenu au pixel). Code-drawn (sans PNG) : `news`,
  `postgame`, `history`. `default.png` dérivé de `default_base.png` par `tools/gen_default_bg.py`.
- **Tests** : pas de framework ; headless `SDL_VIDEODRIVER=dummy` (instancier `App`, piloter
  `_on_network`/`do_action`/`draw`, `pygame.image.save` pour capture). Scripts jetables préfixe `_`.
- **Git** : repo privé `maximeLeCorre/raspberry-smart-display`, branche `main`. Commits **en
  français** co-signés `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. **Ne pas
  committer/pousser sans demande explicite.**
- **Déploiement** : `deploy/deploy_pi.py` (SSH paramiko ; creds dans `.env` : `PI_HOST/PI_USER/
  PI_PASS`). Archive `pi_display/` (hors `_*`/`__pycache__`) + `certs/` + `.env` (jeton + clé Riot) ;
  installe deps + service **systemd** `pi-display` (autostart, `kmsdrm`, plein écran). ⚠️ service lié
  à **tty1** (DRM master, sinon EGL échoue) ; libs EGL/GLES Mesa requises ; ne jamais exclure les
  `__init__.py`. Logs : `journalctl -u pi-display -f`. 1er boot écran noir → rebooter.
