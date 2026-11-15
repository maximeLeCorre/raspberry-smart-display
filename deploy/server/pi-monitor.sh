#!/bin/bash
# Relevé de supervision lu par le Pi (écran « Serveur », modules/server/vm_report.py).
#
# Installé sur la VM en /usr/local/sbin/pi-monitor (root, non modifiable par l'utilisateur
# SSH) par install_pi_monitor.sh, et autorisé SANS argument par une règle sudoers :
#     <user SSH> ALL=(root) NOPASSWD: /usr/local/sbin/pi-monitor ""
# Le Pi ne peut donc lancer QUE ce script, tel quel : aucune entrée n'est lue, rien n'est
# modifié, et rien de secret n'est imprimé (pas de `docker inspect` complet : l'environnement
# des conteneurs contient les clés). Sortie : lignes `clé=valeur`.
set -u
export LC_ALL=C PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Réglages (à adapter ici, sur la VM, si les chemins changent) ---------------------
RENTRER_DIR=/home/rentrer/rentrer/server   # dépôt Rentrer déployé par la CI
PROJECT=rentrer                            # projet docker compose
PUSH_USER=wardlink                         # service utilisateur du serveur de push NexusLink
PUSH_UNIT=wardlink-push

echo "v=1"
echo "now=$(date +%s)"
uptime_s=$(cut -d. -f1 /proc/uptime)

# --- Conteneurs Rentrer : service|état|santé|redémarrages|démarré|nom ------------------
if command -v docker > /dev/null 2>&1; then
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2> /dev/null)
  for id in $ids; do
    docker inspect --format \
      'ctr={{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.RestartCount}}|{{.State.StartedAt}}|{{.Name}}' \
      "$id" 2> /dev/null
  done
  running=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2> /dev/null)
  if [ -n "$running" ]; then
    # shellcheck disable=SC2086
    docker stats --no-stream --format 'stat={{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' $running 2> /dev/null
  fi
  bridge=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=idfm-bridge" 2> /dev/null | head -1)
  if [ -n "$bridge" ]; then
    echo "bridge_fp=$(docker exec "$bridge" cat gtfs-data/gtfs-source.fingerprint 2> /dev/null | head -c 200 | tr -d '\n')"
    echo "bridge_fp_at=$(docker exec "$bridge" stat -c %Y gtfs-data/gtfs-source.fingerprint 2> /dev/null)"
  fi
else
  echo "docker=absent"
fi

# --- Données MOTIS (scripts/update-data.sh, watch-plan.sh) -----------------------------
data="$RENTRER_DIR/data"
if [ -d "$data" ]; then
  echo "data=ok"
  # Import en cours : update-data.sh tient data/update.lock (flock). Jamais créé ici (root).
  if [ -f "$data/update.lock" ]; then
    if flock -n "$data/update.lock" true 2> /dev/null; then echo "import_running=0"; else echo "import_running=1"; fi
    echo "import_lock_at=$(stat -c %Y "$data/update.lock")"
  fi
  if [ -f "$data/update.log" ]; then
    recent=$(tail -c 3000000 "$data/update.log" | tr '\r' '\n')
    echo "import_start=$(printf '%s\n' "$recent" | grep -a '^== ' | tail -1 | cut -d' ' -f2)"
    echo "import_ok=$(printf '%s\n' "$recent" | grep -a 'MOTIS à jour\.' | tail -1 | cut -d' ' -f1)"
  fi
  echo "plan_fp=$(head -c 200 "$data/plan.fingerprint" 2> /dev/null | tr -d '\n')"
  echo "plan_at=$(stat -c %Y "$data/plan.fingerprint" 2> /dev/null)"
  echo "plan_failed_fp=$(head -c 200 "$data/plan.failed" 2> /dev/null | tr -d '\n')"
  echo "idfm_published=$(head -c 60 "$data/idfm-published" 2> /dev/null | tr -d '\n')"
  if [ -f "$data/input/report.json" ] && command -v python3 > /dev/null 2>&1; then
    python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print("networks_ok=%d" % r.get("datasets", 0)); print("networks_failed=%d" % len(r.get("problems") or {}))' \
      "$data/input/report.json" 2> /dev/null
  fi
else
  echo "data=absent"
fi

# --- Serveur de push NexusLink (service systemd utilisateur) ---------------------------
if uid=$(id -u "$PUSH_USER" 2> /dev/null); then
  as_push() { runuser -u "$PUSH_USER" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user "$@" 2> /dev/null; }
  echo "push_state=$(as_push is-active "$PUSH_UNIT")"
  mono=$(as_push show --value -p ActiveEnterTimestampMonotonic "$PUSH_UNIT")
  if [ -n "$mono" ] && [ "$mono" != "0" ]; then
    echo "push_since=$(( $(date +%s) - uptime_s + mono / 1000000 ))"
  fi
  echo "push_restarts=$(as_push show --value -p NRestarts "$PUSH_UNIT")"
else
  echo "push_state=absent"
fi
