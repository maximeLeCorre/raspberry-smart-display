"""Supervision de la VM (écran Serveur) : relevé pi-monitor, règles d'alerte, historique, écrans."""

from __future__ import annotations

import time

import pytest

from modules.server.history import MonitorHistory
from modules.server.monitor import CRIT, OK, UNKNOWN, WARN, Inputs, Monitor, Settings, conditions
from modules.server.probes import PinMismatch, Probes, cert_days_left, default_urls
from modules.server.vm_report import iso_ts, mem_bytes, parse_report

NOW = 1_794_600_000.0

REPORT = """v=1
now=1794600000
ctr=api|running|healthy|0|2026-11-14T10:00:00.123456789Z|/rentrer-api-1
ctr=motis|running||2|2026-11-14T03:34:00Z|/rentrer-motis-1
ctr=worker|exited||0|0001-01-01T00:00:00Z|/rentrer-worker-1
ctr=pipeline|exited||0|2026-11-14T03:30:00Z|/rentrer-pipeline-run-1
ctr=caddy|running||0|2026-11-09T10:00:00Z|/rentrer-caddy-1
ctr=idfm-bridge|running||0|2026-11-09T10:00:00Z|/rentrer-idfm-bridge-1
stat=rentrer-api-1|2.15%|96.5MiB / 23.4GiB
stat=rentrer-motis-1|11.00%|9.8GiB / 23.4GiB
bridge_fp=abc
bridge_fp_at=1794590000
data=ok
import_running=0
import_lock_at=1794560000
import_start=2026-11-14T03:30:00Z
import_ok=2026-11-14T03:34:12Z
plan_fp=old
plan_at=1794500000
plan_failed_fp=
idfm_published=2026-11-14T13:02:00+00:00
networks_ok=1
networks_failed=0
push_state=active
push_since=1794000000
push_restarts=0
"""


def test_releve_pi_monitor():
    rep = parse_report(REPORT)
    api, motis = rep["containers"]["api"], rep["containers"]["motis"]
    assert (api["state"], api["health"], api["cpu"]) == ("running", "healthy", 2)
    assert api["mem"] == int(96.5 * 1024 ** 2)
    assert motis["restarts"] == 2 and motis["mem"] == int(9.8 * 1024 ** 3)
    assert rep["containers"]["worker"]["started"] is None          # date zéro de Docker
    assert rep["plan"]["pending"] and not rep["plan"]["failed"]
    assert rep["import"]["ok"] > rep["import"]["started"]
    assert rep["push"] == {"state": "active", "since": 1794000000, "restarts": 0}
    assert iso_ts("2026-11-14T10:00:00.123456789Z") == iso_ts("2026-11-14T10:00:00.123456Z")
    assert mem_bytes("1.5GiB") == int(1.5 * 1024 ** 3) and mem_bytes("??") is None


def probes(rentrer=None, push=None, internet=None, ts=NOW):
    return {"ts": ts, "internet": internet,
            "rentrer": rentrer if rentrer is not None else {"up": True, "motis": True,
                                                           "status": {"state": "ok"}, "cert_days": 60},
            "push": push if push is not None else {"up": True, "cert_days": 5000}}


LINK = {"online": True, "mem_used": 4, "mem_total": 10, "disk_used": 30, "disk_total": 65}


def report(**changes):
    rep = parse_report(REPORT)
    rep["containers"]["worker"]["state"] = "running"
    rep["plan"]["pending"] = False
    for k, v in changes.items():
        rep[k] = v
    return {"ok": True, "data": rep}


def test_tout_va_bien_puis_cartes_ok():
    mon = Monitor()
    raised, cleared = mon.evaluate(Inputs(NOW, LINK, report(), probes()))
    assert (raised, cleared) == ([], [])
    assert [mon.card_level(c) for c in ("vm", "rentrer", "push")] == [OK, OK, OK]
    assert mon.worst() == (OK, "")


def test_api_rentrer_ko_levee_apres_le_delai_puis_retablie():
    mon = Monitor(Settings(api_seconds=120))
    down = probes(rentrer={"up": False, "error": "délai dépassé"})
    assert mon.evaluate(Inputs(NOW, LINK, report(), down)) == ([], [])     # pas encore
    raised, _ = mon.evaluate(Inputs(NOW + 130, LINK, report(), down))
    assert [(a.key, a.level) for a in raised] == [("rentrer.api", CRIT)]
    assert mon.card_level("rentrer") == CRIT and mon.worst() == (CRIT, "rentrer")
    assert mon.evaluate(Inputs(NOW + 140, LINK, report(), down)) == ([], [])  # une seule fois
    _, cleared = mon.evaluate(Inputs(NOW + 150, LINK, report(), probes()))
    assert [a.key for a in cleared] == ["rentrer.api"]


def test_vm_injoignable_une_seule_alerte_et_pas_si_le_pi_est_coupe():
    off = {"online": False, "error": "connexion impossible"}
    dead = probes(rentrer={"up": False}, push={"up": False}, internet=True)
    conds = conditions(Inputs(NOW, off, None, dead), Settings())
    assert set(conds) == {"vm.down"}                    # ni rentrer.api ni push.health en plus
    pi_cut = probes(rentrer={"up": False}, push={"up": False}, internet=False)
    mon = Monitor()
    assert conditions(Inputs(NOW, off, None, pi_cut), Settings()) == {}
    mon.evaluate(Inputs(NOW, off, None, pi_cut))
    assert mon.card_level("vm") == UNKNOWN


def test_conteneurs_import_plan_et_ram():
    s = Settings()
    rep = report()
    rep["data"]["containers"]["worker"]["state"] = "exited"
    rep["data"]["plan"].update(pending=True, bridge_at=NOW - 3600)
    rep["data"]["import"].update(running=False, started=NOW - 1000, ok=NOW - 90000)
    link = dict(LINK, mem_used=95, mem_total=100)
    conds = conditions(Inputs(NOW, link, rep, probes()), s)
    assert conds["rentrer.ctr.worker"].level == CRIT
    assert conds["rentrer.plan"].level == WARN and "1 h" not in conds["rentrer.plan"].text
    assert conds["rentrer.import"].text == "Dernier import MOTIS en échec"
    assert conds["vm.ram"].level == WARN
    rep["data"]["import"].update(running=True, lock_at=NOW - 60)     # import : RAM haute normale
    conds = conditions(Inputs(NOW, link, rep, probes()), s)
    assert "vm.ram" not in conds and "rentrer.import" not in conds and "rentrer.plan" not in conds


def test_redemarrages_en_boucle():
    mon = Monitor()
    for i, n in enumerate((2, 3, 4, 5)):
        rep = report()
        rep["data"]["containers"]["motis"]["restarts"] = n
        loops = mon.restart_loops(rep, NOW + i * 60)
    assert loops == {"motis": 3}
    assert mon.restart_loops(rep, NOW + 2000) == {}       # plus de 10 min : oublié


def test_push_epinglage_droits_et_service():
    rep = report()
    rep["data"]["push"]["state"] = "failed"
    pin = probes(push={"up": False, "pin_error": True})
    conds = conditions(Inputs(NOW, LINK, rep, pin), Settings())
    assert conds["push.pin"].level == CRIT and conds["push.pin"].delay == 0
    assert conds["push.service"].level == CRIT
    stats = probes(push={"up": True, "stats": {"grantsExpiring": 2, "banned": 1}})
    conds = conditions(Inputs(NOW, LINK, report(), stats), Settings())
    assert "2 droits" in conds["push.grants"].text and conds["push.banned"].level == WARN


def test_temoins_degrades_seulement_apres_15_min():
    mon = Monitor()
    deg = probes(rentrer={"up": True, "motis": True, "status": {"state": "degraded", "message": "RER B"}})
    assert mon.evaluate(Inputs(NOW, LINK, report(), deg)) == ([], [])
    raised, _ = mon.evaluate(Inputs(NOW + 901, LINK, report(), deg))
    assert raised[0].level == WARN and "RER B" in raised[0].text
    down = probes(rentrer={"up": True, "motis": True, "status": {"state": "down"}})
    raised, _ = mon.evaluate(Inputs(NOW + 902, LINK, report(), down))
    assert raised[0].level == CRIT                       # aggravation : nouvelle notification


def test_historique_push_par_heure_et_redemarrage(tmp_path):
    h = MonitorHistory(tmp_path / "m.db")
    base = {"started": 100, "pushed": 10, "delivered": 9, "refused": 1, "failed": 0, "limited": 0}
    h.record_push(base, NOW)                                    # 1er relevé : base seulement
    h.record_push(dict(base, pushed=14, delivered=12, refused=2), NOW + 60)
    h.record_push({"started": 200, "pushed": 3, "delivered": 3}, NOW + 3600)   # redémarré
    hours = h.push_hours(NOW + 3600)
    assert len(hours) == 24
    assert (hours[-2]["delivered"], hours[-2]["refused"]) == (3, 1)
    assert hours[-1]["delivered"] == 3


def test_frise_des_temoins(tmp_path):
    h = MonitorHistory(tmp_path / "m.db")
    for i in range(3):
        h.record_canary("ok", NOW + i * 30)
    h.record_canary("degraded", NOW + 90)
    h.record_canary("ok", NOW + 1000)                     # trou (Pi éteint) : nouveau segment
    segs = h.canary_segments(NOW - 10)
    assert [s[2] for s in segs] == ["ok", "degraded", "ok"]
    assert segs[0][:2] == (NOW, NOW + 90) or segs[0][1] == NOW + 60


def test_sondes_adresses_et_epinglage(tmp_path):
    assert default_urls("1.2.3.4") == ("https://1-2-3-4.sslip.io", "https://1.2.3.4:8443")
    p = Probes({"push_pin_file": str(tmp_path / "pin")}, "1.2.3.4")
    p._check_pin("aa")                                    # 1er contact : épinglé
    assert (tmp_path / "pin").read_text().strip() == "aa"
    p._check_pin("aa")
    with pytest.raises(PinMismatch):
        p._check_pin("bb")


# ----------------------------------------------------------------------- écrans
class FakeLink:
    host = "1.2.3.4"
    services = [{"label": "Minecraft", "unit": "minecraft.service", "use_sudo": True, "minecraft_port": 25565}]
    history_seconds, poll_seconds = 600, 5
    backup = None

    def __init__(self, rep):
        self._rep = rep

    def snapshot(self):
        return dict(LINK, cpu_pct=23.0, nproc=4, uptime=1000, temp_c=None, ts=time.time(), host="vm",
                    services={"minecraft.service": "active"})

    def report(self):
        return self._rep

    def players(self, unit):
        return {"online": 2, "max": 20, "names": ["A", "B"], "version": "1"}

    def history(self):
        return [(time.time() - 10, 20.0, 40.0), (time.time(), 25.0, 41.0)]


class FakeProbes:
    def __init__(self, snap):
        self._snap = snap

    def snapshot(self):
        return self._snap


@pytest.fixture
def app(tmp_path, free_port, monkeypatch):
    import app as app_module
    from config import load_config
    from icon_cache import IconCache
    from modules.league import module as league_module
    from store import Store
    monkeypatch.setattr(league_module, "Store", lambda: Store(tmp_path / "t.db"))
    monkeypatch.setattr(league_module, "IconCache", lambda: IconCache(tmp_path / "i.db"))
    cfg = load_config(app_module.__file__.replace("app.py", "config.toml"))
    cfg.setdefault("server", {})["host"] = ""
    cfg.setdefault("weather", {})["enabled"] = False
    cfg["remote"] = {"enabled": False}
    a = app_module.App(cfg, fullscreen=False, scale=1, monitor=None, debug=False,
                       host="127.0.0.1", port=free_port)
    a.modules["league"].sync_lcu = lambda: None
    yield a
    a.shutdown()


@pytest.mark.parametrize("incident", [False, True])
def test_ecrans_de_supervision_se_dessinent(app, tmp_path, incident):
    mod = app.modules["server"]
    rep = report()
    snap = probes(rentrer={"up": True, "motis": True, "ms": 120, "cert_days": 70,
                           "status": {"state": "ok", "since": NOW - 3600},
                           "stats": {"users": 9, "destinations": 14, "today": {"pushSent": 214}}},
                  push={"up": True, "ms": 84, "cert_days": 7000,
                        "stats": {"installs": 3, "grants": 3, "grantsExpiring": 1, "banned": 0,
                                  "started": NOW - 86400}, "stats_ts": NOW})
    if incident:
        snap["rentrer"] = {"up": False, "error": "délai dépassé"}
        rep["data"]["containers"]["motis"]["state"] = "restarting"
    mod.link = FakeLink(rep)
    mod.probes = FakeProbes(snap)
    mod.history = MonitorHistory(tmp_path / "m.db")
    mod.history.record_canary("ok", time.time() - 7200)
    mod.history.record_canary("degraded", time.time() - 7100)
    app.screens["server_machine"].link = mod.link
    app.screens["server_machine"].service = mod.link.services[0]
    mod.monitor.evaluate(Inputs(time.time() - 1000, mod.link.snapshot(), rep, snap))
    mod.evaluate(time.time())
    if incident:
        assert mod.has_critical()
    for name in ("server", "server_machine", "server_rentrer", "server_push", "default"):
        app.manual_screen = name
        app.set_screen(name)
        assert app.current.name == name
        app.current.draw(app.surface)
    pygame = pytest.importorskip("pygame")
    pygame.image.save(app.surface, str(tmp_path / "home.png"))
    app.set_screen("server")
    app.current.handle_touch((150, 200))                 # carte Machine
    assert app.current.name == "server_machine"
    app.current.handle_touch((740, 26))                  # RETOUR -> vue d'ensemble
    assert app.current.name == "server"


def test_epinglage_https_le_jeton_ne_part_pas_vers_un_autre_certificat(tmp_path):
    import datetime
    import hashlib
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wardlink-push")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                       serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"https://127.0.0.1:{srv.server_address[1]}"
    try:
        good = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        p = Probes({"push_url": url, "rentrer_url": "", "push_pin": good}, "", push_token="t0k")
        code, body, info = p._get(url + "/v1/stats", "t0k", pinned=True)
        assert (code, body, seen) == (200, {"ok": True}, ["Bearer t0k"])
        assert 28 <= cert_days_left(info["notAfter"], time.time()) <= 30
        p.pin = "0" * 64                                   # autre serveur à la même adresse
        with pytest.raises(PinMismatch):
            p._get(url + "/v1/stats", "t0k", pinned=True)
        assert seen == ["Bearer t0k"]                      # rien d'envoyé au second
    finally:
        srv.shutdown()
