"""Veille douce : luminosité baissée après 5 min sans PC ni appui, rétablie
par un appui (non transmis), jamais baissée tant que le PC est connecté."""

from __future__ import annotations

import backlight
from backlight import Backlight
from test_app_routing import app, net  # noqa: F401  (fixture)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(tmp_path, clock):
    (tmp_path / "max_brightness").write_text("255")
    path = tmp_path / "brightness"
    path.write_text("255")
    cfg = {"dim_after_minutes": 5, "dim_level": 30, "normal_level": 255}
    return Backlight(cfg, path=str(path), clock=clock), path


def test_baisse_apres_5_min_sans_pc_puis_appui(tmp_path):
    clock = Clock()
    bl, path = make(tmp_path, clock)
    clock.t += 299
    bl.tick(False)
    assert path.read_text() == "255"
    clock.t += 1
    bl.tick(False)                                 # début du fondu
    clock.t += backlight.FADE_SECONDS
    bl.tick(False)
    assert bl.dimmed and path.read_text() == "30"
    assert bl.wake() is True                       # appui de réveil : consommé
    assert path.read_text() == "255"
    clock.t += backlight.WAKE_GRACE
    assert bl.wake() is False                      # appui suivant : un vrai clic
    clock.t += 300
    bl.tick(False)                                 # 5 min plus tard : rebaisse
    assert bl.dimmed


def test_jamais_de_veille_pc_connecte(tmp_path):
    clock = Clock()
    bl, path = make(tmp_path, clock)
    clock.t += 3600
    bl.tick(True)
    assert not bl.dimmed and path.read_text() == "255"
    clock.t += 299                                 # PC parti : délai depuis son départ
    bl.tick(False)
    assert not bl.dimmed
    clock.t += 1
    bl.tick(False)
    assert bl.dimmed
    bl.tick(True)                                  # PC rallumé : luminosité normale
    assert not bl.dimmed and path.read_text() == "255"


def test_sans_peripherique_ni_droit_rien_ne_casse(tmp_path):
    bl = Backlight({}, path="")
    bl.tick(False)
    assert bl.wake() is False
    ro = Backlight({}, path=str(tmp_path / "absent" / "brightness"))
    ro.dimmed = True
    ro.restore()                                   # écriture impossible -> désactivé
    assert ro._file is None


def test_appui_de_reveil_non_transmis_a_l_ecran(app):
    touched = []
    app.current.handle_touch = lambda pos: touched.append(pos)
    app.backlight.dimmed = True
    app._dispatch_touch((10, 10))
    assert touched == []
    app.backlight._woke_at = -10                   # grâce écoulée
    app._dispatch_touch((10, 10))
    assert touched == [(10, 10)]
