"""Archive de déploiement : ce qui part (ou pas) sur le Pi."""

from __future__ import annotations

import runpy
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_archive_sans_base_ni_fichiers_jetables(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_HOST", "192.0.2.1")
    monkeypatch.setenv("PI_PASS", "x")
    monkeypatch.setattr(sys, "argv", ["deploy_pi.py"])
    deploy = runpy.run_path(str(ROOT / "deploy" / "deploy_pi.py"), run_name="test")
    tgz = tmp_path / "a.tgz"
    deploy["build_tarball"](tgz, "X=1\n")
    names = tarfile.open(tgz).getnames()
    assert not [n for n in names if ".db" in n], "une base SQLite écraserait celle du Pi"
    assert not [n for n in names if Path(n).name.startswith("_") and "__" not in n]
    assert "pi_display/modules/__init__.py" in names and ".env" in names
