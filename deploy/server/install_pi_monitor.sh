#!/bin/bash
# Installe sur la VM le relevé de supervision du Pi (une fois, puis à chaque changement de
# pi-monitor.sh). À lancer SUR LA VM, avec sudo :
#     scp deploy/server/pi-monitor.sh deploy/server/install_pi_monitor.sh <admin>@<IP>:
#     ssh <admin>@<IP> sudo bash install_pi_monitor.sh <utilisateur SSH du Pi>
#
# - /usr/local/sbin/pi-monitor : root:root 0755 (l'utilisateur du Pi ne peut pas le modifier) ;
# - /etc/sudoers.d/pi-monitor : cet utilisateur peut lancer CE script, sans argument, sans
#   mot de passe ; rien d'autre (vérifié par visudo avant d'être mis en place).
set -euo pipefail
user="${1:?usage : sudo bash install_pi_monitor.sh <utilisateur SSH du Pi>}"
here="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "à lancer avec sudo" >&2; exit 1; }
id "$user" > /dev/null || { echo "utilisateur inconnu : $user" >&2; exit 1; }

install -o root -g root -m 0755 "$here/pi-monitor.sh" /usr/local/sbin/pi-monitor

rule=$(mktemp)
printf '# Supervision par le Pi (projet raspberry) : ce script seul, sans argument.\n%s ALL=(root) NOPASSWD: /usr/local/sbin/pi-monitor ""\n' "$user" > "$rule"
visudo -cf "$rule" > /dev/null
install -o root -g root -m 0440 "$rule" /etc/sudoers.d/pi-monitor
rm -f "$rule"

echo "Installé. Essai :"
sudo -u "$user" sudo -n /usr/local/sbin/pi-monitor | head -5
