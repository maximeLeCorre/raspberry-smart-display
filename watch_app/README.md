# LolRemote — app Apple Watch (accepter la partie, banc ARAM)

Parle à l'API télécommande du Pi (`pi_display/remote_api.py`). Le code est écrit
ici et vérifié par GitHub Actions ; sur le Mac on ne clone rien, on copie les
4 fichiers de `LolRemote/`.

## Une seule fois
1. Xcode → Réglages → Comptes : ajouter son **Apple ID perso** (équipe gratuite).
2. Brancher l'iPhone, « Faire confiance » ; activer le **mode développeur** sur
   l'iPhone puis la montre (Réglages → Confidentialité et sécurité).
3. Xcode → New Project → **watchOS → App** ; nom `LolRemote`, interface SwiftUI,
   **Watch App** seule (sans app iPhone).
4. Remplacer `LolRemoteApp.swift` et `ContentView.swift` du modèle ; ajouter
   `RemoteClient.swift` et `Secrets.swift` (File → New → File → Swift File).
5. Dans `Secrets.swift` : coller le jeton (`REMOTE_API_TOKEN` du `.env`).
6. Cible → onglet **Info**, ajouter :
   - `App Transport Security Settings` → `Allows Local Networking` = YES
   - `Privacy - Local Network Usage Description` = « Connexion au Pi »
7. **Signing & Capabilities** : choisir son équipe.

## À chaque installation (l'app expire au bout de 7 jours)
Destination = la montre → ▶ Run. 1re fois lente (préparation de la montre).
Au 1er lancement : accepter l'accès au **réseau local**.

Conseil : montre → Réglages → Général → Revenir au cadran → LolRemote → 1 h
(l'app reste au premier plan pendant la session).
