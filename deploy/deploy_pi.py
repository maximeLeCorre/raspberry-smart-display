#!/usr/bin/env python3
"""Déploiement de l'appli d'affichage (pi_display) sur le Raspberry Pi.

Lancé depuis le PC, ce script copie `pi_display/` + le jeton d'auth (.env, le
jeton uniquement) + le certificat TLS (certs/) sur le Pi, installe les
dépendances et pose un service systemd qui démarre l'affichage au boot.

UTILISATION :
    1. Mettre l'IP du Pi dans `.env` (racine, IGNORÉ par Git) : PI_HOST=192.168.1.52
       (PI_USER / PI_DIR / PI_KEY optionnels).
    2. Authentification par **clé SSH** (défaut : ~/.ssh/id_ed25519, ou PI_KEY).
       Pour l'autoriser sur le Pi une fois (avec PI_PASS dans .env) :
         .\\.venv\\Scripts\\python deploy\\deploy_pi.py --install-key
       Ensuite PI_PASS peut être retiré du .env (sudo du Pi = NOPASSWD).
    3. Déployer :
         .\\.venv\\Scripts\\python deploy\\deploy_pi.py          (rapide)
         .\\.venv\\Scripts\\python deploy\\deploy_pi.py --full   (force apt/pip)
       Les dépendances ne sont (ré)installées que si leur liste a changé
       (empreinte mémorisée sur le Pi, `.deps_hash`).

L'empreinte SSH du Pi est épinglée au 1er contact dans `deploy/known_hosts`
(gitignoré) : un changement d'empreinte arrête le déploiement.

PRÉREQUIS : paramiko (déjà installé dans le venv). Côté Pi : Raspberry Pi OS
(Lite conseillé), SSH activé, accès réseau.
"""

from __future__ import annotations

import argparse
import hashlib
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
PI_KEY  = os.path.expanduser(os.getenv("PI_KEY", "") or "~/.ssh/id_ed25519")

_args = argparse.ArgumentParser(description="Déploie pi_display sur le Pi.")
_args.add_argument("--full", action="store_true",
                   help="Force la réinstallation des dépendances (apt + pip).")
_args.add_argument("--install-key", action="store_true",
                   help="Autorise la clé SSH du PC sur le Pi (via PI_PASS), puis quitte.")
ARGS = _args.parse_args()

# ===== OPTIONS DE DÉPLOIEMENT (modifiables ici) =====
SETUP_SERVICE = True   # (ré)installer le service systemd d'autostart
FULLSCREEN    = True   # lancer l'affichage en plein écran (écran du Pi)
KNOWN_HOSTS = REPO_ROOT / "deploy" / "known_hosts"   # empreinte du Pi (TOFU)

# Dépendances du Pi. Toute modif change l'empreinte -> réinstallation auto.
APT_PACKAGES = ("python3-venv python3-pip libsdl2-2.0-0 libsdl2-ttf-2.0-0 "
                "libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libfreetype6 libjpeg62-turbo "
                "libegl1 libegl-mesa0 libgles2 libgl1-mesa-dri libgbm1")
PIP_PACKAGES = "'pygame>=2.5' 'websockets>=13.0,<18' 'python-dotenv>=1.0' 'paramiko>=3.0'"
DEPS_HASH = hashlib.sha256(f"{APT_PACKAGES}|{PIP_PACKAGES}".encode()).hexdigest()[:16]


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
if not PI_PASS and not os.path.exists(PI_KEY):
    sys.exit(f"Aucune clé SSH ({PI_KEY}) ni PI_PASS dans .env : impossible de se connecter.")

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
    # ⚠️ Jamais les bases SQLite : celle du PC (tests) écraserait l'historique
    # accumulé sur le Pi (la LCU ne rend que les 20 dernières parties).
    if base.endswith((".db", ".db-journal", ".db-wal", ".db-shm")):
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
# sudo : sans mot de passe si le Pi l'autorise (NOPASSWD, défaut Raspberry Pi
# OS) ; sinon mot de passe lu sur l'entrée standard (jamais sur disque).
if sudo -n true 2>/dev/null; then
  sudo_() { sudo -n "$@"; }
else
  IFS= read -r SUDO_PASS || true
  sudo_() { echo "$SUDO_PASS" | sudo -S -p "" "$@"; }
fi
DEPS_HASH_FILE="$PI_DIR/.deps_hash"
INSTALL="__INSTALL__"
if [ "$(cat "$DEPS_HASH_FILE" 2>/dev/null)" != "__DEPS_HASH__" ]; then INSTALL=1; fi
if [ ! -x "$VENV/bin/python" ]; then INSTALL=1; fi
if [ "$INSTALL" = "1" ]; then
  echo "[pi] Paquets systeme (SDL pour pygame, venv)..."
  sudo_ apt-get update
  sudo_ apt-get install -y __APT__
  # Acces framebuffer (kmsdrm), entrees et GPIO pour le service
  sudo_ usermod -aG video,render,input,gpio "$(id -un)" || true

  echo "[pi] Environnement Python (venv + dependances)..."
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip >/dev/null
  "$VENV/bin/pip" install __PIP__
  "$VENV/bin/pip" install gpiozero RPi.GPIO \\
      || echo "[pi] (GPIO: install echouee -- l'affichage marche sans, fallback clavier)"
  echo "__DEPS_HASH__" > "$DEPS_HASH_FILE"
else
  echo "[pi] Dependances a jour (--full pour forcer)."
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
                .replace("__INSTALL__", "1" if ARGS.full else "0")
                .replace("__DEPS_HASH__", DEPS_HASH)
                .replace("__APT__", APT_PACKAGES)
                .replace("__PIP__", PIP_PACKAGES)
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
# Sans ça, les print() restent dans un tampon et journalctl ne montre rien.
Environment=PYTHONUNBUFFERED=1
SyslogIdentifier=pi-display
{sdl}{vt}ExecStart={pi_dir}/.venv/bin/python {pi_dir}/pi_display/main.py{fs}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


# -------------------------------------------------------------- exécution SSH
def run(ssh: "paramiko.SSHClient", cmd: str, check: bool = True,
        stdin_data: str | None = None) -> int:
    """Exécute une commande distante en streamant la sortie. Renvoie le code."""
    stdin, stdout, stderr = ssh.exec_command(cmd)
    if stdin_data is not None:
        stdin.write(stdin_data)
        stdin.flush()
    stdin.channel.shutdown_write()
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


def connect_ssh() -> "paramiko.SSHClient":
    """Connexion au Pi : clé SSH d'abord, mot de passe en repli. Empreinte du Pi
    épinglée (TOFU) dans KNOWN_HOSTS ; une empreinte différente arrête tout."""
    ssh = paramiko.SSHClient()
    if KNOWN_HOSTS.exists():
        ssh.load_host_keys(str(KNOWN_HOSTS))
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    attempts = []
    if os.path.exists(PI_KEY):
        attempts.append(("cle " + PI_KEY, dict(key_filename=PI_KEY)))
    if PI_PASS:
        attempts.append(("mot de passe", dict(password=PI_PASS)))
    for label, auth in attempts:
        try:
            ssh.connect(PI_HOST, username=PI_USER, timeout=15,
                        allow_agent=False, look_for_keys=False, **auth)
        except paramiko.BadHostKeyException:
            sys.exit(f"Empreinte SSH du Pi DIFFERENTE de celle epinglee ({KNOWN_HOSTS}). "
                     "Pi reinstalle ? Supprime ce fichier si c'est attendu.")
        except paramiko.AuthenticationException:
            log(f"Authentification refusee ({label}).")
            continue
        except Exception as exc:  # réseau, hôte injoignable, SSH désactivé...
            sys.exit(f"Connexion impossible : {exc}")
        log(f"Connexion OK ({label}).")
        ssh.save_host_keys(str(KNOWN_HOSTS))
        return ssh
    sys.exit("Authentification refusee : cle non autorisee (--install-key) ou PI_PASS faux.")


def install_key() -> None:
    """Ajoute la clé publique du PC aux authorized_keys du Pi (une fois)."""
    pub_path = PI_KEY + ".pub"
    if not os.path.exists(pub_path):
        sys.exit(f"Cle publique introuvable : {pub_path} (genere-la : ssh-keygen -t ed25519).")
    if not PI_PASS:
        sys.exit("--install-key a besoin de PI_PASS dans .env (dernier usage du mot de passe).")
    pub = Path(pub_path).read_text(encoding="utf-8").strip()
    ssh = connect_ssh()
    run(ssh, 'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; '
             'IFS= read -r K; grep -qxF "$K" ~/.ssh/authorized_keys '
             '|| echo "$K" >> ~/.ssh/authorized_keys', stdin_data=pub + "\n")
    ssh.close()
    log("Cle autorisee sur le Pi. PI_PASS peut etre retire du .env.")


def main() -> None:
    if ARGS.install_key:
        install_key()
        return
    # Le Pi a besoin du jeton d'auth ET de la clé Riot (il est autonome pour
    # l'enrichissement Web : historique, dossiers, rangs...).
    env_content = (f"DISPLAY_AUTH_TOKEN={read_env_value('DISPLAY_AUTH_TOKEN')}\n"
                   f"RIOT_API_KEY={read_env_value('RIOT_API_KEY')}\n"
                   f"SERVER_HOST={read_env_value('SERVER_HOST')}\n"
                   f"IDFM_API_KEY={read_env_value('IDFM_API_KEY')}\n")

    tmp = Path(tempfile.mkdtemp(prefix="pi-deploy-"))
    tgz = tmp / "pi-display-deploy.tgz"
    try:
        log("Preparation de l'archive...")
        build_tarball(tgz, env_content)

        log(f"Connexion SSH a {PI_USER}@{PI_HOST} ...")
        ssh = connect_ssh()

        sftp = ssh.open_sftp()
        try:
            log("Envoi des fichiers...")
            sftp.put(str(tgz), "/tmp/pi-display-deploy.tgz")
            put_bytes(sftp, remote_setup_script().encode("utf-8"),
                      "/tmp/pi-display-setup.sh")
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
        run(ssh, "bash /tmp/pi-display-setup.sh; c=$?; rm -f /tmp/pi-display-setup.sh; exit $c",
            stdin_data=(PI_PASS or "") + "\n")

        ssh.close()
        log("Deploiement termine.")
        print()
        log(f"Logs en direct :  ssh {PI_USER}@{PI_HOST} 'journalctl -t pi-display -f'")
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
