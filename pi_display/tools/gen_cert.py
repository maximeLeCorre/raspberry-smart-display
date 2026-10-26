"""Génère un certificat TLS auto-signé pour le lien Pi <-> agent.

Le Pi sert en `wss://` avec ce certificat ; l'agent l'**épingle** (il ne fait
confiance qu'à CE certificat précis, pas à une autorité publique). On fabrique
donc un certificat qui est sa propre autorité (basicConstraints CA:TRUE) pour
qu'il soit accepté comme ancre de confiance côté agent.

Comme l'agent vérifie le certificat mais **pas le nom d'hôte** (voir
`config.build_client_ssl`), les SAN ci-dessous sont surtout là par propreté :
le certificat reste valable même si l'IP du Pi change. On peut en ajouter via
les arguments (hostnames ou IP).

Usage :
    .\.venv\Scripts\python pi_display\tools\gen_cert.py            # localhost + 127.0.0.1
    .\.venv\Scripts\python pi_display\tools\gen_cert.py 192.168.1.42 raspberrypi

Écrit `certs/pi-display.crt` (public, à copier sur la machine de l'agent) et
`certs/pi-display.key` (privé, reste sur le Pi, ignoré par Git) à la racine du
dépôt. Validité : 10 ans (appareil domestique, on ne veut pas renouveler).
"""

from __future__ import annotations

import datetime
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CERT_DIR = REPO_ROOT / "certs"
CERT_PATH = CERT_DIR / "pi-display.crt"
KEY_PATH = CERT_DIR / "pi-display.key"


def _build_san(extra: list[str]) -> x509.SubjectAlternativeName:
    """SAN de base (localhost + 127.0.0.1) + entrées fournies en argument."""
    entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    for item in extra:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(item)))
        except ValueError:
            entries.append(x509.DNSName(item))
    return x509.SubjectAlternativeName(entries)


def main() -> None:
    extra = sys.argv[1:]
    CERT_DIR.mkdir(exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pi-display")])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)  # auto-signé : sujet == émetteur
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(_build_san(extra), critical=False)
        # CA:TRUE -> utilisable comme ancre de confiance épinglée par l'agent.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )

    KEY_PATH.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"[cert] Certificat écrit : {CERT_PATH}")
    print(f"[cert] Clé privée écrite : {KEY_PATH}  (garder privée, ne pas committer)")
    if extra:
        print(f"[cert] SAN supplémentaires : {', '.join(extra)}")
    print("[cert] Active TLS dans les deux config.toml (tls = true), puis copie le "
          ".crt sur la machine de l'agent si elle est distincte du Pi.")


if __name__ == "__main__":
    main()
