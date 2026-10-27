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

- **`pi_display/`** — appli d'affichage (Pygame) + **cerveau « internet »**.
  Tournera sur le Pi ; se teste en fenêtre sur PC. Serveur WebSocket qui reçoit
  écran + données. **Interroge lui-même l'API Web Riot et les CDN** (rangs,
  winrate, mains, **historique**, **bilan de fin**, icônes, splash) → voir
  `pi_display/riot_web.py`. C'est ici que vit **`RIOT_API_KEY`** (.env du Pi).
- **`pc_agent/`** — agent de fond (Windows), **purement local, SANS clé**.
  Détecte l'activité et lit les **API locales** de Riot (LCU = phase/sélection ;
  Live Client Data = partie en cours), puis pousse écran + données au Pi. Client
  WebSocket. **Utile uniquement quand une partie est en cours** (données
  impossibles à obtenir autrement).

> **Qui fait quoi (important)** : l'agent ne fournit plus que du **local** (phase,
> sélection avec `riotId`, scoreboard live, objectifs). **Tout l'enrichissement
> internet est fait par le Pi** : au clic sur un joueur, le Pi résout le PUUID et
> interroge l'API Web ; l'historique et le bilan de fin sont récupérés par le Pi
> via `match-v5` (le Pi marche donc **agent/PC éteint** pour consulter
> l'historique). Appels réseau lancés hors de la boucle de rendu via
> `App.async_call(fn, on_result)` (worker thread → résultat livré au thread
> principal par `_drain_io`).

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
- Lancer l'agent (simulation) : `.\.venv\Scripts\python pc_agent\main.py --simulate --scenario champselect|game|aram|queue|home|postgame|full`
- Lancer l'agent (réel) : `.\.venv\Scripts\python pc_agent\main.py`

> ⚠️ En **`--simulate`**, l'agent vise **`127.0.0.1`** par défaut (test local),
> pas l'IP du Pi de `config.toml [pi].host` (sinon « Pi injoignable » dérouteur
> si le vrai Pi est absent). Utiliser `--host` pour viser un autre Pi. En mode
> **réel**, c'est bien l'IP de la config qui est utilisée.

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

Le protocole est désormais **minimal** : l'agent ne fait que pousser l'écran
courant et ses données locales ; **le Pi ne lui demande plus rien** (il enrichit
tout seul). Le payload `postgame` n'est **plus** envoyé par l'agent (le Pi
récupère la dernière partie via l'API Web à la réception de `set_screen postgame`).

Pi → PC (à la connexion) :
- `{"type":"hello","modules":["system","league"]}` (modules actifs annoncés)

PC → Pi (premier message si jeton configuré) :
- `{"type":"auth","token":"..."}`

PC → Pi :
- `{"type":"set_screen","screen":"default|queue|champselect|lol|postgame"}`
- `{"type":"data","screen":"queue|champselect|lol","payload":{...}}`
  (données **locales** ; chaque joueur porte un `riotId` = 'Nom#TAG' que le Pi
  utilise pour enrichir au clic)

Interne (synthétisé par le serveur Pi, pas envoyé par l'agent) :
- `{"type":"_connected"}` / `{"type":"_disconnected"}`

La déconnexion du client fait revenir le Pi à l'écran par défaut (mais
l'historique/bilan restent consultables : ils ne dépendent pas de l'agent).

## Écrans (`pi_display/`)

- `screen.py` : classe de base `Screen` (+ attribut `cycle` = inclus dans le
  cycle du bouton « suivant »). Fond PNG chargé **une fois** ; redessin par
  **dirty rects** (ménage le Pi 3) ; repli couleur si PNG absent.
- `modules/system/default_screen.py` : `DefaultScreen` (horloge, date, **3
  dernières actus RSS** cliquables, onglet **« France Info »** en haut à gauche,
  **bandeau LoL « Rejoindre »** en haut, conditionnel, et bouton **« Dernières
  parties »** à droite de l'en-tête ACTU — affiché seulement si le module League
  est actif, ouvre l'écran `history`). Module système, toujours actif. La météo a
  été retirée.
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
  (complément à l'écran de jeu, voir ci-dessous), `PostGameScreen` (bilan, voir
  ci-dessous).

**`PostGameScreen` (après-partie)** : comparatif des **10 joueurs en barres
horizontales**, **dessiné entièrement en code** (pas de PNG, comme `news` — tout
est dynamique ; `postgame.png` n'est plus utilisé). Barre d'onglets en haut = une
**métrique** chacun (`dmg`/`taken`/`gold`/`cs`/`vision`/`heal` → Dégâts/Subis/Or/
CS/Vision/Soins), clic = change le graphe ; les barres sont triées par valeur
décroissante (icône + valeur). **Code couleur : TOI = rouge, amis (premade) =
rose, autres = bleu.** Un bandeau bas rappelle tes stats en petit en permanence.
Les **amis** sont reconnus via leur Riot ID listé dans **`pi_display/config.toml`
`[lol] friends = ["Nom#TAG", …]`** (insensible à la casse). Les stats des 10
joueurs viennent de l'**API Web Riot (`match-v5`), calculées PAR LE PI**
(`riot_web.build_match_detail`). La liste `METRICS` (écran) et les clés des
`metrics` (builder) doivent rester alignées.

**`MatchHistoryScreen` (`name="history"`, hors cycle, dessiné en code)** : liste
des dernières parties, **ouverte depuis l'accueil** (bouton « Dernières
parties »). `App.open_history()` pose le verrou manuel et lance `request_match_history`
→ **le Pi récupère la liste lui-même** (`riot_web.build_match_history`, en tâche
de fond) et remplit l'écran. Un clic appelle `App.open_postgame_review(gameId)` :
le Pi récupère le détail (`build_match_detail`), bascule sur `postgame` en **mode
revue** (`app.postgame_return = "history"`, RETOUR → liste). Un `set_screen`
poussé par l'agent (vraie partie) **annule** le mode revue.

**Source des données = le Pi, via l'API Web Riot** (`pi_display/riot_web.py`,
stdlib `urllib`) :
- Nécessite **`RIOT_API_KEY`** (dans le **.env du Pi**) **et** `[lol] summoner =
  "Nom#TAG"` (le compte dont on tire l'historique). `[riot] platform/regional`
  pour le routing. **Marche agent/PC éteint.**
- `gameId` = **matchId** `match-v5` (ex. `EUW1_123`) ; cache dans
  `RiotWeb._match_cache` (liste↔détail partagés, winrate réutilise).
- **Bilan de fin de partie** : à la réception de `set_screen postgame`, le Pi
  appelle `_load_postgame(None, retries=4)` → récupère la **dernière** partie du
  compte (réessais pour le délai d'indexation de l'API juste après la game).
- **Icônes** = CDN Community Dragon (`riot_web.icon_bytes`), **splash** = Data
  Dragon (`splash_bytes`) — récupérés par le Pi (plus de round-trip agent).
- Clé des dossiers joueurs = le **`riotId`** (`Nom#TAG`) envoyé par l'agent ; le
  Pi résout le PUUID (`resolve_puuid`, en cache) et enrichit (`build_player_info`).
- Testable (écrans locaux) : `pc_agent/main.py --simulate --scenario home` — mais
  l'enrichissement réel exige la clé/compte configurés **sur le Pi** (les joueurs
  fictifs du simulateur n'ont pas de vrai dossier).

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

- Tactile : sur le Pi (SDL2/kmsdrm) l'écran capacitif (ex. `ft5x06`) émet des
  événements **`FINGERDOWN`** (coords normalisées 0..1), **pas** des clics souris
  → `app._handle_pygame_events` gère `FINGERDOWN` ET `MOUSEBUTTONDOWN` (souris =
  test PC), via `_dispatch_touch`. On force `SDL_TOUCH_MOUSEEVENTS=0` (main.py)
  pour éviter un double déclenchement. Curseur souris **masqué** en plein écran
  (`pygame.mouse.set_visible(False)`). Clavier = fallback des boutons GPIO :
  **Échap** = retour défaut, **Tab** = écran suivant, **F1** = overlay debug.
- GPIO réel via `gpiozero` (seulement sur le Pi ; absent sur PC → fallback). Sur
  le Pi, un warning `Falling back from lgpio` est bénin (repli sur `RPi.GPIO`).
- Options d'affichage : `--fullscreen`/`--windowed` (auto plein écran + SDL
  `kmsdrm` si Pi détecté), `--scale N`, `--monitor N`, `--debug`.

## Les API Riot utilisées — et leurs pièges

**Répartition** : les API **locales** (LCU, Live Client Data) sont sur l'**agent**
(`pc_agent/`) ; l'**API Web** et les CDN sont sur le **Pi** (`pi_display/riot_web.py`).

1. **LCU API** (`pc_agent/lcu.py`) — API du **client** League, dispo dès qu'il est ouvert.
   - Auth : port + token lus dans les args du process `LeagueClientUx.exe`
     (`--app-port` / `--remoting-auth-token`), HTTP Basic user `riot`,
     certificat auto-signé → `verify=False`.
   - Sert (côté agent) à : phase de jeu (`/lol-gameflow/v1/gameflow-phase`),
     session de sélection (`/lol-champ-select/v1/session`), summoner par id, et le
     mapping id→nom de champion (**Community Dragon**, `CHAMPION_SUMMARY_URL`, CDN
     public — la LCU ne l'expose pas, 404).
   - ⚠️ **PIÈGE** : le `puuid` LCU est **interne** (36 car.) et **rejeté** par
     l'API Web. On ne l'utilise plus : l'agent envoie le **Riot ID** (`riotId`),
     et **le Pi** résout le vrai PUUID externe via `account-v1 by-riot-id`
     (`riot_web.resolve_puuid`).

2. **Live Client Data API** (`pc_agent/riot_api.py`) — `https://127.0.0.1:2999/liveclientdata/allgamedata`.
   - Dispo **uniquement pendant une partie** (phase `InProgress` chargée). Agent.
   - Certificat auto-signé → `verify=False`. Gérer les erreurs (souvent None).

3. **API Web Riot** (`pi_display/riot_web.py`, **sur le Pi**, stdlib `urllib`) —
   nécessite `RIOT_API_KEY` (**.env du Pi**, clé permanente) + `[riot]
   platform/regional` + `[lol] summoner`.
   - `account-v1 by-riot-id` (→ vrai PUUID), `summoner-v4`, `league-v4` (rang),
     `champion-mastery-v4` (maîtrise + mains), `match-v5` (ids/match → historique,
     bilan, winrate récent). Caches : PUUID et matchs.
   - Tolérant aux erreurs : renvoie None/partiel. **CDN** : icônes (Community
     Dragon, `icon_bytes`) et splash (Data Dragon, `splash_bytes`).

### Flux « sélection de champions »

`champ_select.build_champ_select_payload` : pour chaque joueur de notre équipe,
récupère le **Riot ID** (`gameName`/`tagLine`, complété via `lcu.summoner_by_id`
si masqué) et le met dans `riotId`. **Pas de PUUID, pas d'icône, pas
d'enrichissement côté agent** : le Pi réclame les icônes au CDN (`request_icon`,
cache par `championId`) et, au clic, enrichit le dossier (`riot_web.build_player_info`
via le `riotId`).

- ⚠️ Pour les **coéquipiers**, le dossier dépend de la visibilité de leur Riot ID
  dans le client pendant la sélection (pour **soi**, toujours dispo).
- Un champion **non encore pické** (`championId=0`) → placeholder avec initiales.

## Agent : boucle agnostique + Sources (`main.py`, `sources/`)

`main.py` instancie les Sources et, chaque tick, interroge celles des modules
activés ; la première `poll()` non-None gagne → `set_screen` (+ `data` si
payload). Mise à jour ≤ 1 fois / `update_interval` (config, 1–2 s). Le Pi ne
demande plus rien à l'agent ⇒ `Source.handle_request` n'est plus utilisé par
League (seul `hello` revient du Pi, pour la liste des modules actifs).

`sources/league.py` (`LeagueSource`) mappe `gameflow_phase` → écran :
`Matchmaking`/`ReadyCheck` → `queue` ; `ChampSelect` → `champselect` ;
`InProgress` → `lol` (Live Client Data ; `summarize_full` enrichi de `game_mode`,
`objectives` [Faille, `objectives.py`] et du **`riotId`** de chaque joueur pour le
dossier au clic côté Pi) ; `WaitingForStats`/`PreEndOfGame`/`EndOfGame` →
`postgame` **avec payload None** (c'est le Pi qui récupère le bilan de la dernière
partie) ; client fermé/menu → `poll()` renvoie None. Builder `queue` dans
`phases.py`, sélection dans `champ_select.py`. **L'agent n'a plus ni clé Riot ni
`RiotWeb`.**

Mode simulation (`simulator.py`) : scénarios `full`/`champselect`/`game`/`aram`/
`queue`/`home`/`postgame`, **données locales fictives seulement** (`game` = Faille
avec objectifs, `aram` = ARAM sans objectifs). L'enrichissement (dossiers, icônes,
historique, bilan) étant désormais fait par le Pi via l'API Web, il dépend de la
**clé/compte configurés sur le Pi** — les joueurs fictifs n'ont pas de vrai
dossier, et `--scenario postgame` fait récupérer au Pi **ta** dernière vraie partie.

## Config & secrets

- `pi_display/config.toml` : host/port d'écoute, résolution, FPS, broches GPIO,
  **`[rss]`**, **`[modules]`** (source de vérité, poussée à l'agent), **`[riot]
  platform/regional`** (routing API Web) et **`[lol] summoner`/`friends`** (compte
  dont on tire l'historique + amis en rose).
- `pc_agent/config.toml` : IP/port du Pi, `update_interval`, noms des process LoL.
  **Plus de `[riot]`/`[features]`** (l'agent n'a plus de clé).
- **`.env`** (racine, **ignoré** par Git) : `RIOT_API_KEY=...` (clé **permanente**)
  et `DISPLAY_AUTH_TOKEN=...` (jeton d'auth du lien Pi↔agent ; vide = désactivé).
  Modèle versionné : `.env.example`. Ne **jamais** committer de secret.
  ⚠️ **Le `.env` du Pi doit contenir `RIOT_API_KEY`** (le Pi est autonome pour
  l'API Web) **et** le jeton d'auth. L'agent (PC) n'a besoin que du jeton.
  `deploy_pi.py` copie les deux sur le Pi.

## Tests

Pas de framework de test. On valide en **headless** avec `SDL_VIDEODRIVER=dummy` :
instancier `App`, piloter les handlers (`_handle_network`, `do_action`,
`current.draw`) et vérifier l'état. On peut sauver une capture avec
`pygame.image.save(app.surface, "x.png")` pour inspecter le rendu. Les scripts
de diagnostic sont temporaires (préfixe `_`) et supprimés après usage.

## Fonds d'écran (design)

**Un PNG 800×480 par écran** dans `pi_display/assets/` : `default`, `queue`,
`champselect`, `lol`. Ils **contiennent les cadres/panneaux/zones**
(le code ne dessine que le contenu, aligné dessus — voir « Cadres = dans le fond »
plus haut). Les fonds actuels ont été générés par un outil de design externe
(IA), pas procéduralement — **chaque fond est propre à la mise en page de son
écran** (ne plus les partager entre écrans). Exceptions dessinées **en code**
(sans PNG) : l'écran `news` (France Info) et l'écran `postgame` (barres
dynamiques — `postgame.png` n'est plus chargé). `default.png` est **dérivé** de
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

## Déploiement Pi

**Script automatisé : `deploy/deploy_pi.py`** (lancé depuis le PC avec le Python
du venv). Renseigner le bloc CONFIG en tête (IP, utilisateur, **mot de passe**
SSH ; `INSTALL_DEPS`/`SETUP_SERVICE`/`FULLSCREEN`). Il :
1. fabrique une archive de `pi_display/` (hors `__pycache__`/`.pyc`/`_*`) + le
   `certs/` (certificat TLS) + un `.env` contenant **`DISPLAY_AUTH_TOKEN` ET
   `RIOT_API_KEY`** (le Pi est autonome pour l'API Web : la clé part désormais sur
   le Pi — `read_env_value` dans `deploy_pi.py`) ;
2. se connecte en SSH via **paramiko** (mot de passe, non-interactif — à
   installer sur le PC : `pip install paramiko`), envoie et extrait dans
   `PI_DIR` (défaut `/home/<user>/pi-display`) ;
3. installe les paquets système (SDL pour pygame, `python3-venv`), crée le venv
   et les dépendances **runtime** (pygame, websockets, python-dotenv, gpiozero,
   RPi.GPIO — pas Pillow/cryptography, inutiles au runtime), ajoute l'utilisateur
   aux groupes `video,render,input,gpio` ;
4. pose et active un service **systemd** `pi-display` (autostart au boot,
   `SDL_VIDEODRIVER=kmsdrm`, `--fullscreen`, `Restart=always`).

Le mot de passe sudo transite par un fichier temporaire `/tmp/.pi_sudo` (0600,
supprimé aussitôt), jamais dans la ligne de commande. Pour un simple envoi de
code ensuite : `INSTALL_DEPS=False`, `SETUP_SERVICE=False` (le script redémarre
juste le service). Logs : `journalctl -u pi-display -f`. Si l'écran reste noir au
1er coup, rebooter le Pi (les nouveaux groupes `video`/… prennent effet).

Prérequis Pi : Raspberry Pi OS **Lite**, SSH activé, réseau. Ne pas oublier de
mettre l'IP du Pi dans `pc_agent/config.toml [pi]` (et `tls`/jeton cohérents).

**Pièges rencontrés (déjà gérés par le script, mais à savoir) :**
- Ne **jamais** exclure les `__init__.py` de l'archive (le filtre n'exclut que
  les noms `_simple`, pas les `__dunder__`) sinon `ImportError ... MODULES`.
- `pygame.error: EGL not initialized` = il manque la couche **EGL/GLES de Mesa**
  (`libegl1 libegl-mesa0 libgles2`) sur Pi OS Lite → installées par le script.
- En plein écran kmsdrm, pygame doit être **DRM master** : le service est lié à
  **tty1** (`PAMName=login` + `TTYPath=/dev/tty1` + `StandardInput=tty-force`,
  `Conflicts=getty@tty1`). Sans ça, EGL échoue même avec les libs. L'écran reste
  alors sur la console texte.

Lancement manuel (sans service) : `SDL_VIDEODRIVER=kmsdrm python pi_display/main.py
--fullscreen` (plein écran auto si Pi détecté).
