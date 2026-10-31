"""Lien SSH de l'écran « Serveur » : calcul CPU et historique des courbes."""

from __future__ import annotations

from modules.server.server_link import ServerLink


def metrics(cpu: str, avail_kb: int = 250) -> str:
    return f"cpu={cpu}\nmem_total_kb=1000\nmem_avail_kb={avail_kb}\nsvc:mc.service=active\n"


def test_cpu_par_delta_et_historique():
    link = ServerLink({"host": "x", "user": "u", "poll_seconds": 5, "history_minutes": 1})
    link._apply_metrics(metrics("100 0 100 800 0 0 0"))
    link._apply_metrics(metrics("200 0 200 900 0 0 0"))
    hist = link.history()
    assert hist[0][1] is None                 # 1er relevé : pas encore de delta
    assert round(hist[1][1]) == 67            # (200 actifs / 300 total)
    assert hist[1][2] == 75.0                 # RAM : 750/1000
    assert link.snapshot()["services"] == {"mc.service": "active"}


def test_historique_borne_a_la_fenetre():
    link = ServerLink({"host": "x", "user": "u", "poll_seconds": 5, "history_minutes": 1})
    for i in range(50):
        link._apply_metrics(metrics(f"{i} 0 0 {i} 0 0 0"))
    assert len(link.history()) == 60 // 5 + 1


def test_ping_minecraft_sur_un_faux_serveur():
    import json
    import socket
    import threading

    from modules.server import minecraft_ping as mp

    status = {"version": {"name": "1.21.1"}, "players": {
        "max": 20, "online": 3, "sample": [{"name": "bob"}, {"name": "Alice"}]}}
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with conn:
            conn.recv(1024)                  # handshake + demande de statut
            body = json.dumps(status).encode()
            payload = mp._varint(0) + mp._varint(len(body)) + body
            conn.sendall(mp._varint(len(payload)) + payload)

    threading.Thread(target=serve, daemon=True).start()
    res = mp.ping("127.0.0.1", srv.getsockname()[1], timeout=2)
    srv.close()
    assert (res["online"], res["max"], res["names"], res["version"]) == \
        (3, 20, ["Alice", "bob"], "1.21.1")


def test_ligne_des_joueurs():
    from modules.server.server_screen import players_line

    assert players_line(None) == "joueurs : …"
    assert players_line({"error": "refused"}).startswith("joueurs : le serveur ne répond pas")
    assert players_line({"online": 0, "max": 20, "names": []}) == "personne en ligne (0/20)"
    assert players_line({"online": 3, "max": 20, "names": ["Alice", "bob"]}) == \
        "3/20 en ligne : Alice, bob +1"
    assert players_line({"online": 2, "max": 20, "names": []}) == "2/20 en ligne"
