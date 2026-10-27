#!/usr/bin/env python3
"""Déploiement de l'appli d'affichage (pi_display) sur le Raspberry Pi.

Lancé depuis le PC, ce script copie `pi_display/` + le jeton d'auth (.env, le
jeton uniquement) + le certificat TLS (certs/) sur le Pi, installe les
dépendances et pose un service systemd qui démarre l'affichage au boot.

UTILISATION :
    1. Mettre les identifiants du Pi dans `.env` (racine, IGNORÉ par Git) :
         PI_HOST=192.168.1.52
         PI_PASS=le_mot_de_passe
       (PI_USER / PI_DIR optionnels). Ainsi le mot de passe n'est jamais commité.
    2. Lancer avec le Python du venv :
         .\\.venv\\Scripts\\python deploy\\deploy_pi.py
    3. Au 1er déploiement : laisser INSTALL_DEPS et SETUP_SERVICE à True (ci-dessous).
       Ensuite, pour un simple envoi de code : les passer à False (plus rapide).

PRÉREQUIS : paramiko (déjà installé dans le venv). Côté Pi : Raspberry Pi OS
(Lite conseillé), SSH activé, accès réseau.
"""

from __future__ import annotations

import io
import os
import sys
import tarfile
import tempfile
from pathlib import Path

# La sortie du Pi peut contenir de l'Unicode (ex. '●' du statut systemd) : on
# force une sortie UTF-8 tolérante pour ne pas planter sur une console Windows
# cp1252 lorsqu'on réaffiche les logs distants.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

# ===== CONNEXION AU PI — à renseigner dans .env (racine, IGNORÉ par Git) =====
#   PI_HOST=192.168.1.52      # IP du Pi
#   PI_PASS=motdepasse        # mot de passe SSH (et sudo)
#   PI_USER=pi                # optionnel (défaut "pi")
#   PI_DIR=                   # optionnel (défaut /home/<user>/pi-display)
PI_HOST = os.getenv("PI_HOST", "")
PI_USER = os.getenv("PI_USER", "pi")
PI_PASS = os.getenv("PI_PASS", "")
PI_DIR  = os.getenv("PI_DIR", "")

# ===== OPTIONS DE DÉPLOIEMENT (modifiables ici) =====
INSTALL_DEPS  = True   # installer paquets système + venv + dépendances
SETUP_SERVICE = True   # (ré)installer le service systemd d'autostart
FULLSCREEN    = True   # lancer l'affichage en plein écran (écran du Pi)


def log(msg: str) -> None:
    print(f"[deploy] {msg}", flush=True)


# --------------------------------------------------------------- dépendances
try:
    import paramiko
except ImportError:
    sys.exit("paramiko manquant. Installer : .\\.venv\\Scripts\\python -m pip install paramiko")

# --------------------------------------------------------------- validations
pi_dir = PI_DIR or f"/home/{PI_USER}/pi-display"
if not PI_HOST or "XX" in PI_HOST:
    sys.exit("Renseigne PI_HOST (l'IP du Pi) dans .env (ex. PI_HOST=192.168.1.52).")
if not PI_PASS:
    sys.exit("Renseigne PI_PASS (le mot de passe SSH du Pi) dans .env.")

PI_DISPLAY_DIR = REPO_ROOT / "pi_display"
CERTS_DIR = REPO_ROOT / "certs"
if not PI_DISPLAY_DIR.is_dir():
    sys.exit(f"Dossier introuvable : {PI_DISPLAY_DIR}")


# --------------------------------------------- secrets -> .env Pi
def read_env_value(key: str) -> str:
    """Lit une valeur du .env local (racine). Vide si absente."""
    env_local = REPO_ROOT / ".env"
    if not env_local.exists():
        return ""
    for line in env_local.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith(key) and "=" in s:
            return s.split("=", 1)[1].strip()
    return ""


# ------------------------------------------------------------- archive locale
def _skip(tarinfo: tarfile.TarInfo):
    """Exclut caches, .pyc et fichiers temporaires (_simple) de l'archive.

    ⚠️ On n'exclut que les noms à UN seul underscore initial (ex. `_test_lol.py`,
    `_lol_ARAM.png`) : surtout PAS les dunders comme `__init__.py`, sinon les
    packages arrivent incomplets sur le Pi (`ImportError ... MODULES`).
    """
    parts = tarinfo.name.split("/")
    base = parts[-1]
    if "__pycache__" in parts or base.endswith(".pyc"):
        return None
    if base.startswith("_") and not base.startswith("__"):
        return None
    return tarinfo


def build_tarball(dst: Path, env_content: str) -> None:
    """Crée l'archive : pi_display/, certs/ (si présent) et .env (jeton + clé Riot)."""
    with tarfile.open(dst, "w:gz") as tar:
        tar.add(PI_DISPLAY_DIR, arcname="pi_display", filter=_skip)
        if CERTS_DIR.is_dir():
            tar.add(CERTS_DIR, arcname="certs")
        else:
            log("certs/ absent : si tu actives TLS, génère-le d'abord (tools/gen_cert.py).")
        data = env_content.encode("utf-8")
        info = tarfile.TarInfo(name=".env")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


# --------------------------------------------------- scripts générés (côté Pi)
def remote_setup_script() -> str:
    tmpl = """#!/usr/bin/env bash
set -e
PI_DIR="__DIR__"
VENV="$PI_DIR/.venv"
# Mot de passe sudo lu depuis un fichier temporaire (jamais dans la ligne de cmd).
SUDO_PASS="$(cat /tmp/.pi_sudo 2>/dev/null || true)"
rm -f /tmp/.pi_sudo
sudo_() { echo "$SUDO_PASS" | sudo -S -p "" "$@"; }

if [ "__INSTALL__" = "1" ]; then
  echo "[pi] Paquets systeme (SDL pour pygame, venv)..."
  sudo_ apt-get update
  sudo_ apt-get install -y python3-venv python3-pip \\
      libsdl2-2.0-0 libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 \\
      libfreetype6 libjpeg62-turbo \\
      libegl1 libegl-mesa0 libgles2 libgl1-mesa-dri libgbm1
  # Acces framebuffer (kmsdrm), entrees et GPIO pour le service
  sudo_ usermod -aG video,render,input,gpio "$(id -un)" || true

  echo "[pi] Environnement Python (venv + dependances)..."
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install pygame websockets python-dotenv
  "$VENV/bin/pip" install gpiozero RPi.GPIO \\
      || echo "[pi] (GPIO: install echouee -- l'affichage marche sans, fallback clavier)"
fi

if [ "__SERVICE__" = "1" ]; then
  echo "[pi] Installation du service systemd..."
  sudo_ mv /tmp/pi-display.service /etc/systemd/system/pi-display.service
  sudo_ systemctl daemon-reload
  sudo_ systemctl enable pi-display
  sudo_ systemctl restart pi-display
  sleep 1
  sudo_ systemctl --no-pager --full status pi-display | head -n 12 || true
else
  echo "[pi] Redemarrage du service (s'il est deja installe)..."
  sudo_ systemctl restart pi-display 2>/dev/null \\
      || echo "[pi] (service non installe ; relance avec SETUP_SERVICE=True)"
fi
echo "[pi] Termine."
"""
    return (tmpl.replace("__DIR__", pi_dir)
                .replace("__INSTALL__", "1" if INSTALL_DEPS else "0")
                .replace("__SERVICE__", "1" if SETUP_SERVICE else "0"))


def systemd_unit() -> str:
    fs = " --fullscreen" if FULLSCREEN else ""
    sdl = "Environment=SDL_VIDEODRIVER=kmsdrm\n" if FULLSCREEN else ""
    # En plein écran (kmsdrm), pygame doit être « DRM master » : il faut une vraie
    # session sur un écran virtuel actif. On attache donc le service à tty1
    # (PAMName=login => seat, StandardInput=tty-force => tty de contrôle) et on
    # coupe le getty de tty1. Sans ça : « pygame.error: EGL not initialized ».
    tty = ""
    if FULLSCREEN:
        tty = ("Conflicts=getty@tty1.service\n"
               "After=getty@tty1.service\n")
    vt = ""
    if FULLSCREEN:
        vt = ("PAMName=login\n"
              "TTYPath=/dev/tty1\n"
              "StandardInput=tty-force\n"
              "StandardOutput=journal\n"
              "StandardError=journal\n")
    return f"""[Unit]
Description=Pi Display (ecran info LoL)
After=network-online.target
Wants=network-online.target
{tty}
[Service]
Type=simple
User={PI_USER}
WorkingDirectory={pi_dir}
{sdl}{vt}ExecStart={pi_dir}/.venv/bin/python {pi_dir}/pi_display/main.py{fs}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


# -------------------------------------------------------------- exécution SSH
def run(ssh: "paramiko.SSHClient", cmd: str, check: bool = True) -> int:
    """Exécute une commande distante en streamant la sortie. Renvoie le code."""
    _, stdout, stderr = ssh.exec_command(cmd)
    for line in iter(stdout.readline, ""):
        print("  " + line.rstrip(), flush=True)
    code = stdout.channel.recv_exit_status()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        print("  " + err.replace("\n", "\n  "), flush=True)
    if check and code != 0:
        raise RuntimeError(f"Commande distante echouee (code {code}) : {cmd}")
    return code


def put_bytes(sftp, data: bytes, remote: str, mode: int | None = None) -> None:
    with sftp.open(remote, "w") as f:
        f.write(data)
    if mode is not None:
        sftp.chmod(remote, mode)


def main() -> None:
    # Le Pi a besoin du jeton d'auth ET de la clé Riot (il est autonome pour
    # l'enrichissement Web : historique, dossiers, rangs...).
    env_content = (f"DISPLAY_AUTH_TOKEN={read_env_value('DISPLAY_AUTH_TOKEN')}\n"
                   f"RIOT_API_KEY={read_env_value('RIOT_API_KEY')}\n")

    tmp = Path(tempfile.mkdtemp(prefix="pi-deploy-"))
    tgz = tmp / "pi-display-deploy.tgz"
    try:
        log("Preparation de l'archive...")
        build_tarball(tgz, env_content)

        log(f"Connexion SSH a {PI_USER}@{PI_HOST} ...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=15,
                        allow_agent=False, look_for_keys=False)
        except paramiko.AuthenticationException:
            sys.exit("Authentification refusee : verifie PI_USER / PI_PASS.")
        except Exception as exc:  # réseau, hôte injoignable, SSH désactivé...
            sys.exit(f"Connexion impossible : {exc}")
        log("Connexion OK.")

        sftp = ssh.open_sftp()
        try:
            log("Envoi des fichiers...")
            sftp.put(str(tgz), "/tmp/pi-display-deploy.tgz")
            put_bytes(sftp, remote_setup_script().encode("utf-8"),
                      "/tmp/pi-display-setup.sh")
            put_bytes(sftp, PI_PASS.encode("utf-8"), "/tmp/.pi_sudo", mode=0o600)
            if SETUP_SERVICE:
                put_bytes(sftp, systemd_unit().encode("utf-8"),
                          "/tmp/pi-display.service")
        finally:
            sftp.close()

        log(f"Extraction dans {pi_dir} ...")
        run(ssh, f"mkdir -p '{pi_dir}' && "
                 f"tar -xzf /tmp/pi-display-deploy.tgz -C '{pi_dir}' && "
                 f"rm -f /tmp/pi-display-deploy.tgz")

        log("Installation cote Pi (dependances / service)...")
        run(ssh, "bash /tmp/pi-display-setup.sh && rm -f /tmp/pi-display-setup.sh")

        ssh.close()
        log("Deploiement termine.")
        print()
        log(f"Logs en direct :  ssh {PI_USER}@{PI_HOST} 'journalctl -u pi-display -f'")
        log(f"Agent (ce PC) : mets host = \"{PI_HOST}\" dans pc_agent/config.toml [pi], puis lance pc_agent/main.py.")
        if FULLSCREEN:
            log("Si l'ecran reste noir : les groupes video/render/input viennent "
                "d'etre ajoutes -- un reboot du Pi peut etre necessaire la 1re fois.")
    finally:
        try:
            tgz.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    main()
