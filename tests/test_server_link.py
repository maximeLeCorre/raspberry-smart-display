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
