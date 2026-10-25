# Écran d'information intelligent (Raspberry Pi + écran tactile 5")

Un écran d'info piloté par ce que vous faites sur votre PC. Il affiche des
« modes » : un mode par défaut (heure, date, météo à venir) et un mode League
of Legends qui montre un résumé de la partie en cours. Un agent tournant sur
le PC détecte le jeu et envoie les infos à l'écran.

Le projet se compose de deux programmes :

- **`pi_display/`** — l'appli d'affichage (Pygame). Tourne sur le Raspberry Pi,
  mais se teste en fenêtre sur PC.
- **`pc_agent/`** — l'agent de fond (Windows) qui détecte LoL, lit l'API locale
  de Riot et envoie les données à l'écran.

Communication : **WebSocket** (JSON), PC → Pi. La connexion persistante permet
à l'écran de revenir tout seul au mode par défaut dès que l'agent se déconnecte
(jeu fermé, PC éteint).

---

## Prérequis

- Python **3.11+** (nécessaire pour `tomllib`).
- Sur PC pour tester : rien d'autre que les dépendances Python ci-dessous.

## Installation (test sur PC Windows)

Le plus simple pour tester localement : **un seul environnement virtuel** à la
racine, qui installe les deux `requirements.txt`. Depuis la racine du dépôt, en
PowerShell :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r pi_display\requirements.txt -r pc_agent\requirements.txt
```

> Remarque : sur ce poste, la commande `python` renvoie vers le stub Microsoft
> Store. On utilise donc `py -3.11` (Python 3.11, requis par `tomllib`).
>
> Alternative : un venv par programme (`pi_display\.venv`, `pc_agent\.venv`) si
> vous préférez isoler les dépendances. Adaptez alors les chemins ci-dessous.

Générez les fonds placeholder (une fois) :

```powershell
.\.venv\Scripts\python pi_display\tools\gen_backgrounds.py
```

## Lancer le test local

Dans **deux terminaux** :

**Terminal 1 — l'écran (fenêtre 800×480) :**
```powershell
.\.venv\Scripts\python pi_display\main.py
# agrandi x2 : ... pi_display\main.py --scale 2
# sur le 2e moniteur : ... pi_display\main.py --monitor 1
# avec overlay de debug : ... pi_display\main.py --debug   (ou touche F1)
```
Vous devez voir l'heure qui défile (mode par défaut).

**Terminal 2 — l'agent en simulation :**
```powershell
.\.venv\Scripts\python pc_agent\main.py --simulate
```
L'écran bascule en **mode LoL** avec des données qui évoluent.

**Scénario attendu :**
1. L'écran démarre en mode par défaut (heure).
2. La simulation le fait passer en mode LoL.
3. **Échap** (ou clic sur la zone « RETOUR » en haut à droite) → retour forcé
   au mode par défaut, même si la simulation tourne encore.
4. **Ctrl+C** dans le terminal de l'agent (« jeu fermé ») → l'écran revient
   tout seul au mode par défaut.

### Commandes clavier / souris (simulent le matériel)

| Entrée        | Effet                                  | Équivaut à         |
|---------------|----------------------------------------|--------------------|
| **Échap**     | Retour au mode par défaut              | Bouton GPIO « back » |
| **Tab**       | Mode suivant                           | Bouton GPIO « next » |
| **Souris**    | Clic = appui tactile                   | Écran tactile      |
| **F1**        | Affiche/masque l'overlay de debug      | —                  |

## Options de l'appli d'affichage

| Option         | Rôle                                                        |
|----------------|-------------------------------------------------------------|
| `--scale N`    | Agrandit la fenêtre xN (le rendu interne reste 800×480).    |
| `--monitor N`  | Ouvre la fenêtre sur le moniteur d'index N.                 |
| `--fullscreen` | Plein écran (automatique sur le Pi).                        |
| `--windowed`   | Force le mode fenêtré (même sur le Pi).                     |
| `--debug`      | Overlay de debug (mode courant, FPS, dernière entrée).      |
| `--host/--port`| Surcharge la config réseau.                                 |

## Tester avec le vrai League of Legends (sur PC)

Lancez l'agent **sans** `--simulate` pendant que le jeu tourne :
```powershell
.\.venv\Scripts\python pc_agent\main.py
```
L'agent détecte `LeagueClientUx.exe` / `League of Legends.exe` et, pendant un
match, lit `https://127.0.0.1:2999/liveclientdata/allgamedata` (API locale de
Riot, dispo uniquement en partie).

---

## Déploiement sur le Raspberry Pi (plus tard)

1. Raspberry Pi OS **Lite** (sans bureau). Installer Python 3.11+ et les
   dépendances de `pi_display/` (décommenter `gpiozero` / `RPi.GPIO` dans
   `pi_display/requirements.txt`).
2. Copier le dépôt sur le Pi, générer les fonds, puis lancer :
   ```bash
   SDL_VIDEODRIVER=kmsdrm python pi_display/main.py --fullscreen
   ```
   (Le plein écran et `kmsdrm` sont activés automatiquement si le Pi est
   détecté ; les options restent possibles manuellement.)
3. Sur le PC, mettre l'**IP du Pi** dans `pc_agent/config.toml` (`[pi].host`)
   et lancer l'agent.
4. Les broches des boutons physiques se configurent dans
   `pi_display/config.toml` (`[gpio]`).

Passer du test local au vrai Pi se résume donc à : changer l'IP dans la config
de l'agent et lancer l'appli avec `--fullscreen` (ou laisser l'auto-détection).

## Configuration

- `pi_display/config.toml` : hôte/port d'écoute, résolution, FPS, broches GPIO.
- `pc_agent/config.toml` : IP/port du Pi, intervalle de mise à jour, noms des
  processus LoL.
- Secrets (futures clés d'API) : fichier `.env` (ignoré par Git), modèle dans
  `.env.example`.

## Ajouter un nouveau mode

1. Créer `pi_display/modes/mon_mode.py` avec une classe héritant de `Mode`
   (voir `modes/base.py`), définir `name` et `background_name`, implémenter
   `draw()` (et `update_data()` si le mode reçoit des données).
2. L'enregistrer dans `pi_display/app.py` (dict `self.modes` et `self.mode_order`).
3. Ajouter un fond dans `tools/gen_backgrounds.py` (ou un vrai PNG dans `assets/`).
