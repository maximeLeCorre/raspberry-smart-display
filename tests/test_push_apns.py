"""Notifications push (APNs) : JWT, enregistrement, envoi, jetons oubliés."""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

import push_apns

TOKEN = "ab" * 32


class FakeResponse:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeClient:
    def __init__(self, statuses):
        self.statuses, self.calls = statuses, []

    def post(self, url, headers, content):
        self.calls.append((url, headers, json.loads(content)))
        return FakeResponse(*self.statuses.pop(0))


def make_sender(tmp_path, client):
    key = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "certs").mkdir()
    (tmp_path / "certs" / "k.p8").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cfg = {"enabled": True, "team_id": "TEAM", "key_id": "KEY", "topic": "fr.x.watchkitapp",
           "key_file": str(tmp_path / "certs" / "k.p8")}
    return push_apns.PushSender(cfg, db_path=tmp_path / "push.db", client=client), key


def test_jwt_signe_es256(tmp_path):
    sender, key = make_sender(tmp_path, None)
    header, claims, sig = sender._token().split(".")
    raw = base64.urlsafe_b64decode(sig + "==")
    key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                                 int.from_bytes(raw[32:], "big")),
                            f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    assert json.loads(base64.urlsafe_b64decode(header + "=="))["kid"] == "KEY"
    assert json.loads(base64.urlsafe_b64decode(claims + "=="))["iss"] == "TEAM"


def test_enregistrement_et_envoi(tmp_path):
    client = FakeClient([(200,), (410, '{"reason":"Unregistered"}')])
    sender, _ = make_sender(tmp_path, client)
    assert not sender.register("pas-hexa") and not sender.register("")
    assert sender.register(TOKEN.upper())             # normalisé en minuscules
    assert sender.tokens() == [TOKEN]

    assert sender.send({"aps": {"alert": "x"}}, collapse_id="readycheck", ttl=10) == {TOKEN: 200}
    url, headers, payload = client.calls[0]
    assert url == f"{push_apns.PRODUCTION}/3/device/{TOKEN}"
    assert headers["apns-topic"] == "fr.x.watchkitapp" and headers["apns-collapse-id"] == "readycheck"
    assert headers["authorization"].startswith("bearer ") and "apns-expiration" in headers
    assert payload == {"aps": {"alert": "x"}}

    sender.send({"aps": {}})                          # 410 : la montre a désinstallé l'app
    assert sender.tokens() == []


def test_desactive_sans_cle(tmp_path):
    sender = push_apns.PushSender({"enabled": True, "key_id": "K", "team_id": "T", "topic": "x",
                                   "key_file": str(tmp_path / "absente.p8")},
                                  db_path=tmp_path / "push.db")
    assert not sender.enabled
    sender.notify({"alert": "x"})                     # no-op, pas d'exception
