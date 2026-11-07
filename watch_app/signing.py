"""Prépare la signature TestFlight de l'app montre, depuis Windows (sans Mac).

Via l'API App Store Connect (clé « Admin » créée sur le site d'Apple) :
identifiants d'app (coquille + montre), certificat Apple Distribution (clé
privée générée ici), profils App Store. Le tout est emballé (tar.gz → base64)
dans UN secret GitHub, `WATCH_SIGNING`, copié dans le presse-papiers.

    .\\.venv\\Scripts\\python watch_app\\signing.py --key-id XXXX --issuer-id UUID --key AuthKey_XXXX.p8

Réentrant : le certificat est réutilisé tant qu'il existe (dossier
watch_app/signing/, gitignoré) ; les profils sont recréés à chaque fois.
"""
import argparse
import base64
import io
import json
import os
import secrets
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "watch_app", "signing")
API = "https://api.appstoreconnect.apple.com/v1"
PI_URL = "http://192.168.1.52:8766"
# identifiant → (nom du bundle id, nom du profil) ; noms repris par project.yml et la CI
APPS = {
    "fr.maxime.lolremote": ("LolRemote", "LolRemote App Store"),
    "fr.maxime.lolremote.watchkitapp": ("LolRemote Watch", "LolRemote Watch App Store"),
}


class Api:
    def __init__(self, key_id: str, issuer_id: str, key_pem: bytes):
        self.key_id, self.issuer_id = key_id, issuer_id
        self.key = serialization.load_pem_private_key(key_pem, password=None)

    def _token(self) -> str:
        def b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header = {"alg": "ES256", "kid": self.key_id, "typ": "JWT"}
        now = int(time.time())
        claims = {"iss": self.issuer_id, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}
        signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
        r, s = decode_dss_signature(self.key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        return f"{signing_input}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            API + path, method=method,
            data=json.dumps(body).encode() if body else None,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")
            sys.exit(f"API {method} {path} → {err.code}\n{detail}")
        return json.loads(raw) if raw else {}


def ensure_bundle_id(api: Api, identifier: str, name: str) -> str:
    found = api.call("GET", f"/bundleIds?filter[identifier]={identifier}&limit=200")
    for item in found["data"]:
        if item["attributes"]["identifier"] == identifier:  # le filtre accepte les préfixes
            print(f"  identifiant {identifier} : existant")
            return item["id"]
    created = api.call("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
        "identifier": identifier, "name": name, "platform": "IOS"}}})
    print(f"  identifiant {identifier} : créé")
    return created["data"]["id"]


def ensure_certificate(api: Api) -> tuple[str, rsa.RSAPrivateKey, x509.Certificate]:
    key_path = os.path.join(OUT_DIR, "dist_key.pem")
    meta_path = os.path.join(OUT_DIR, "dist_cert.json")
    if os.path.exists(key_path) and os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        listed = api.call("GET", "/certificates?filter[certificateType]=DISTRIBUTION&limit=200")
        if any(item["id"] == meta["id"] for item in listed["data"]):
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            cert = x509.load_der_x509_certificate(base64.b64decode(meta["content"]))
            print(f"  certificat : existant (expire le {cert.not_valid_after_utc:%d/%m/%Y})")
            return meta["id"], key, cert
        print("  certificat local révoqué ou expiré : on en crée un nouveau")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LolRemote CI")]))
           .sign(key, hashes.SHA256()))
    created = api.call("POST", "/certificates", {"data": {"type": "certificates", "attributes": {
        "certificateType": "DISTRIBUTION",
        "csrContent": csr.public_bytes(serialization.Encoding.PEM).decode()}}})
    data = created["data"]
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"id": data["id"], "content": data["attributes"]["certificateContent"]}, f)
    print("  certificat : créé")
    return data["id"], key, x509.load_der_x509_certificate(
        base64.b64decode(data["attributes"]["certificateContent"]))


def recreate_profile(api: Api, name: str, bundle_db_id: str, cert_id: str) -> bytes:
    found = api.call("GET", f"/profiles?filter[name]={urllib.parse.quote(name)}&limit=200")
    for item in found["data"]:
        if item["attributes"]["name"] == name:
            api.call("DELETE", f"/profiles/{item['id']}")
    created = api.call("POST", "/profiles", {"data": {
        "type": "profiles",
        "attributes": {"name": name, "profileType": "IOS_APP_STORE"},
        "relationships": {
            "bundleId": {"data": {"type": "bundleIds", "id": bundle_db_id}},
            "certificates": {"data": [{"type": "certificates", "id": cert_id}]}}}})
    print(f"  profil « {name} » : créé")
    return base64.b64decode(created["data"]["attributes"]["profileContent"])


def read_env_token() -> str:
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == "REMOTE_API_TOKEN":
                    return value.strip().strip('"')
    except OSError:
        pass
    sys.exit("REMOTE_API_TOKEN introuvable dans le .env racine")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--issuer-id", required=True)
    parser.add_argument("--key", required=True, help="fichier AuthKey_XXXX.p8")
    args = parser.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(args.key, "rb") as f:
        key_p8 = f.read()
    api = Api(args.key_id, args.issuer_id, key_p8)
    token = read_env_token()

    print("App Store Connect :")
    bundle_ids = {ident: ensure_bundle_id(api, ident, names[0]) for ident, names in APPS.items()}
    cert_id, cert_key, cert = ensure_certificate(api)
    team_id = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)[0].value
    profiles = {ident: recreate_profile(api, names[1], bundle_ids[ident], cert_id)
                for ident, names in APPS.items()}

    # PKCS#12 en 3DES/SHA1 : le format moderne (AES) est refusé par `security import`.
    p12_password = secrets.token_urlsafe(24)
    p12 = pkcs12.serialize_key_and_certificates(
        b"LolRemote", cert_key, cert, None,
        serialization.PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(50000)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())
        .build(p12_password.encode()))
    env = (f"TEAM_ID={team_id}\nKEY_ID={args.key_id}\nISSUER_ID={args.issuer_id}\n"
           f"P12_PASSWORD={p12_password}\nREMOTE_API_TOKEN={token}\nPI_URL={PI_URL}\n")
    files = {"AuthKey.p8": key_p8, "dist.p12": p12, "signing.env": env.encode(),
             "app.mobileprovision": profiles["fr.maxime.lolremote"],
             "watch.mobileprovision": profiles["fr.maxime.lolremote.watchkitapp"]}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(data), int(time.time())
            tar.addfile(info, io.BytesIO(data))
    value = base64.b64encode(buf.getvalue()).decode()
    if len(value) > 48_000:
        sys.exit(f"secret trop gros pour GitHub ({len(value)} > 48 000 caractères)")
    out = os.path.join(OUT_DIR, "WATCH_SIGNING.txt")
    with open(out, "w", encoding="ascii") as f:
        f.write(value)
    copied = subprocess.run(["clip"], input=value.encode(), check=False).returncode == 0
    print(f"\nÉquipe {team_id}. Secret WATCH_SIGNING ({len(value)} caractères) écrit dans {out}"
          + (" et copié dans le presse-papiers." if copied else "."))
    print("GitHub : Settings > Secrets and variables > Actions > New repository secret,"
          " nom WATCH_SIGNING, coller la valeur.")


if __name__ == "__main__":
    main()
