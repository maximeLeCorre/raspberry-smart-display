"""Profils de signature créés PAR LA CI, à chaque build TestFlight.

Le secret `WATCH_SIGNING` (signing.py) contient la clé d'API App Store Connect et
le certificat : ce script s'en sert pour créer les identifiants d'app manquants
(`APPS` de signing.py) et refaire tous les profils dans le dossier du secret.
Ajouter une cible (extension…) ne demande donc plus de remplacer le secret.

    python ci_profiles.py <dossier du secret décodé>
(variables KEY_ID, ISSUER_ID, P12_PASSWORD : signing.env, posées par la CI)
"""
import base64
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from signing import APPS, Api, ensure_bundle_id, ensure_push_capability, recreate_profile

WATCH_ID = "fr.maxime.lolremote.watchkitapp"


def main() -> None:
    sign_dir = sys.argv[1]
    with open(os.path.join(sign_dir, "AuthKey.p8"), "rb") as f:
        api = Api(os.environ["KEY_ID"], os.environ["ISSUER_ID"], f.read())
    with open(os.path.join(sign_dir, "dist.p12"), "rb") as f:
        _, cert, _ = pkcs12.load_key_and_certificates(f.read(), os.environ["P12_PASSWORD"].encode())
    der = cert.public_bytes(serialization.Encoding.DER)
    listed = api.call("GET", "/certificates?filter[certificateType]=DISTRIBUTION&limit=200")
    cert_id = next((c["id"] for c in listed["data"]
                    if base64.b64decode(c["attributes"]["certificateContent"]) == der), None)
    if cert_id is None:
        sys.exit("certificat du secret introuvable chez Apple (révoqué ?) : relancer signing.py")
    bundle_ids = {ident: ensure_bundle_id(api, ident, names[0]) for ident, names in APPS.items()}
    ensure_push_capability(api, bundle_ids[WATCH_ID])
    for old in os.listdir(sign_dir):
        if old.endswith(".mobileprovision"):
            os.remove(os.path.join(sign_dir, old))
    for ident, names in APPS.items():
        profile = recreate_profile(api, names[1], bundle_ids[ident], cert_id)
        with open(os.path.join(sign_dir, f"{ident}.mobileprovision"), "wb") as f:
            f.write(profile)


if __name__ == "__main__":
    main()
