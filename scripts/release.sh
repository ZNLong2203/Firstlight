#!/usr/bin/env bash
# Release a version of firstlight-api on the demo host, for incident scenario 3.
#   scripts/release.sh 1.4 --regression   ships the duplicate check that keys on {gateway, seq}
#   scripts/release.sh 1.3                rolls back to the version without it
# Only the api container is recreated. The version becomes DD_VERSION, so Datadog's Deployment
# Tracking and every span carry it, and the API records the deployment in MongoDB on start.
#
# 1.4's check takes a batch for a repeat when the gateway sent the same sequence number before, which a
# gateway does after every reboot. So that the run is the same whenever it is recorded, --regression
# first reboots the simulated gateways, as a power blip at the farms would, and waits for them to report.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?usage: scripts/release.sh VERSION [--regression]}"
CHECK=id
[ "${2:-}" = "--regression" ] && CHECK=fields
REBOOT_WAIT_S=30

get() { sed -n "s/^$1=//p" .env | head -1; }
HOST="$(get VPS_USERNAME || true)"; HOST="${HOST:-root}@$(get VPS_IP)"

ssh -o BatchMode=yes "$HOST" "set -e
cd /opt/firstlight
if [ $CHECK = fields ]; then
  docker compose restart edge >/dev/null
  echo \"gateways rebooted; waiting ${REBOOT_WAIT_S} s for them to report\"
  sleep $REBOOT_WAIT_S
fi
image=\$(docker compose images api --format json | python3 -c 'import json,sys; i=json.load(sys.stdin)[0]; print(i[\"Repository\"] + \":\" + i[\"Tag\"])')
docker image tag \"\$image\" \"\${image%:*}:$VERSION\"
DD_VERSION=$VERSION INGEST_DUPLICATE_CHECK=$CHECK docker compose up -d --no-deps --wait api
docker compose ps api --format '{{.Service}} {{.Image}} {{.Status}}'"
echo "firstlight-api $VERSION is live (duplicate check: $CHECK)"
