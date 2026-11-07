# LolRemote — app Apple Watch (accepter la partie, banc ARAM)

Parle à l'API télécommande du Pi (`pi_display/remote_api.py`). **Aucun Mac** :
GitHub Actions compile (`watch_app.yml`, à chaque push) puis signe et envoie sur
TestFlight (`watch_app_testflight.yml`, lancement manuel). Compte Apple
Developer **payant** requis (TestFlight).

Structure imposée par Apple : coquille iOS vide `LolRemote`
(`fr.maxime.lolremote`) qui embarque l'app montre seule `LolRemoteWatch`
(`fr.maxime.lolremote.watchkitapp`), qui embarque la complication « Prochain
train » `LolRemoteTrains` (`….watchkitapp.trains`, WidgetKit, `Trains/`). Code
commun app + complication : `Shared/`. Icône : `gen_icon.py`.

## Une seule fois (depuis le PC Windows)
1. **Clé d'API** : appstoreconnect.apple.com → Utilisateurs et accès →
   Intégrations → API App Store Connect → Clés d'équipe → « + », accès
   **Admin**. Noter l'**ID de clé** et l'**ID de l'émetteur**, télécharger
   `AuthKey_XXXX.p8` (téléchargeable **une seule fois**).
2. **Signature** (identifiants d'app, certificat, profils → secret unique) :
   `.\.venv\Scripts\python watch_app\signing.py --key-id … --issuer-id … --key …\AuthKey_XXXX.p8`
   (lit `REMOTE_API_TOKEN` du `.env` ; tout reste dans `watch_app/signing/`, gitignoré).
3. **Secret GitHub** : dépôt → Settings → Secrets and variables → Actions →
   New repository secret, nom `WATCH_SIGNING`, coller (déjà dans le presse-papiers).
4. **Fiche de l'app** : App Store Connect → Apps → « + » Nouvelle app,
   plateforme **iOS**, identifiant de lot `fr.maxime.lolremote`, nom unique
   sur l'App Store (ex. « LolRemote Maxime »), SKU libre.
5. Lancer **Actions → watch_app_testflight → Run workflow**.
6. App Store Connect → l'app → **TestFlight** → Test interne → créer un groupe,
   s'y ajouter. Sur l'iPhone : app **TestFlight** → installer ; l'app arrive sur
   la montre (sinon : app TestFlight de la montre).

## Sons des kills (facultatif)
`kill1` … `kill5` (.mp3/.m4a/.wav/.caf, quelques secondes) dans `pi_display/sounds/`
(**gitignoré** : extraits sans licence, jamais dans ce dépôt public), puis
redéployer le Pi. La montre les télécharge une fois et les garde (nouvelle build
inutile pour en changer). Trop faibles ? Originaux dans `sounds/originals/`, puis
`pi_display/tools/boost_sounds.py` (WAV normalisés et poussés). Sans fichier : vibrations seules (douces jusqu'au
triple, fortes au quadra/penta).

## Complication « Prochain train » et trajet retour
Chez toi (Pi joignable ou < 300 m) : trains pour St-Lazare. Ailleurs : trajet le
plus court pour rentrer (calculateur IDFM, temps réel) ; appui = détail, puis
« Guider » ouvre Plans. Il faut 2 secrets GitHub en plus : `IDFM_API_KEY` (la même
clé que le Pi) et `HOME_COORDS` = `latitude,longitude` du domicile (ex. `48.80,2.19` ;
jamais dans le dépôt, il est public). Sans eux : trains seulement.
Cadran : appui long → Modifier → onglet Complications → un emplacement →
LolRemote → Prochain train. Cadran sans emplacement : tourner la couronne depuis
le cadran (pile intelligente) → Modifier → « + ». Elle lit le Pi en Wi-Fi seul
(hors maison : dernier relevé, « màj HH:MM »).

## Ensuite
- Nouvelle version = relancer le workflow (build valable **90 jours**).
- Profils ou certificat expirés (1 an) / IP du Pi changée (`PI_URL` dans
  `signing.py`) : relancer `signing.py`, remplacer le secret. (Nouvelle cible : rien à faire,
  la CI crée identifiants et profils, `ci_profiles.py`.)
- Au 1er lancement : accepter l'accès au **réseau local**.
