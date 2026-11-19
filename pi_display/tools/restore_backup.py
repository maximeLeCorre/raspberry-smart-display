"""Restaure les bases du Pi depuis les sauvegardes du serveur (`[server.backup]`).

Lancé **sur le Pi, appli arrêtée** — normalement par le PC :
    .\\.venv\\Scripts\\python deploy\\deploy_pi.py --backups              (liste)
    .\\.venv\\Scripts\\python deploy\\deploy_pi.py --restore [AAAA-MM-JJ] (restaure)
qui arrête `pi-display`, lance ce script, puis relance le service.
Sans jour : la copie la plus récente de chaque base.
"""

import argparse
import sys
from pathlib import Path

PI_DISPLAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PI_DISPLAY))

from config import load_config, load_server_host  # noqa: E402
from modules.server.backup import available, default_files, restore  # noqa: E402
from modules.server.server_link import ServerLink  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--day", default="", help="Jour de la copie (AAAA-MM-JJ) ; défaut : la plus récente.")
    p.add_argument("--list", action="store_true", help="Liste les copies du serveur, sans rien changer.")
    args = p.parse_args()

    cfg = dict(load_config(PI_DISPLAY / "config.toml", local=True).get("server", {}))
    cfg["host"] = load_server_host() or str(cfg.get("host", "")).strip()
    if not cfg["host"]:
        print("Serveur non configuré (SERVER_HOST).")
        return 1
    remote_dir = str(cfg.get("backup", {}).get("dir", "pi-display-backups")).strip().rstrip("/") \
        or "pi-display-backups"
    link = ServerLink(cfg)           # pas de start() : aucun sondage, juste le lien

    if args.list:
        days = available(link, remote_dir)
        if days is None:
            print("Serveur injoignable.")
            return 1
        for f in default_files():
            have = days.get(f.stem, [])
            print(f"{f.name:12} {len(have):2} copie(s)" + (f", {have[0]} → {have[-1]}" if have else ""))
        return 0

    ok, lines = restore(link, remote_dir, default_files(), args.day)
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
