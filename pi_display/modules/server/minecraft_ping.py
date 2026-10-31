"""Joueurs connectés à un serveur Minecraft (Java) via le « Server List Ping ».

C'est la requête du menu multijoueur du jeu : TCP sur le port du serveur
(25565), handshake puis demande de statut ; la réponse est un JSON avec le
nombre de joueurs, un échantillon de pseudos (≤ 12, vide si le serveur a
`hide-online-players=true`) et la version. Aucune config ni secret côté
serveur, stdlib seule. Bloquant : appelé depuis le thread de fond du
`ServerLink`.
"""

from __future__ import annotations

import json
import socket
import struct
import time

PROTOCOL = 47          # sans importance pour une demande de statut


def _varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connexion fermée par le serveur")
        buf += chunk
    return bytes(buf)


def _read_varint(sock: socket.socket) -> int:
    value = 0
    for shift in range(0, 35, 7):
        byte = _read_exact(sock, 1)[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
    raise ValueError("varint trop long")


def _packet(packet_id: int, payload: bytes = b"") -> bytes:
    body = _varint(packet_id) + payload
    return _varint(len(body)) + body


def ping(host: str, port: int = 25565, timeout: float = 4.0) -> dict:
    """Statut du serveur : {online, max, names, version, latency_ms}.
    Lève une exception si le serveur ne répond pas."""
    t0 = time.monotonic()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        addr = host.encode("utf-8")
        handshake = (_varint(PROTOCOL) + _varint(len(addr)) + addr
                     + struct.pack(">H", port) + _varint(1))
        sock.sendall(_packet(0x00, handshake) + _packet(0x00))
        _read_varint(sock)                       # longueur du paquet
        if _read_varint(sock) != 0x00:
            raise ValueError("réponse inattendue")
        data = json.loads(_read_exact(sock, _read_varint(sock)).decode("utf-8"))
    return parse_status(data, (time.monotonic() - t0) * 1000)


def parse_status(data: dict, latency_ms: float = 0.0) -> dict:
    players = data.get("players") or {}
    names = sorted((str(p.get("name", "")) for p in players.get("sample") or []
                    if p.get("name")), key=str.lower)
    return {
        "online": int(players.get("online", 0) or 0),
        "max": int(players.get("max", 0) or 0),
        "names": names,
        "version": str((data.get("version") or {}).get("name", "")),
        "latency_ms": round(latency_ms),
    }
