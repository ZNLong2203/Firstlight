#!/usr/bin/env bash
# Release a version of firstlight-api on the demo host, for incident scenario 3.
#   scripts/release.sh 1.4 --regression   ships the duplicate check that scans ingest_batches
#   scripts/release.sh 1.3                rolls back to the version without it
# Only the api container is recreated. The version becomes DD_VERSION, so Datadog's Deployment
# Tracking and every span carry it, and the API records the deployment in MongoDB on start.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?usage: scripts/release.sh VERSION [--regression]}"
CHECK=id
[ "${2:-}" = "--regression" ] && CHECK=fields

get() { sed -n "s/^$1=//p" .env | head -1; }
HOST="$(get VPS_USERNAME || true)"; HOST="${HOST:-root}@$(get VPS_IP)"

ssh -o BatchMode=yes "$HOST" "set -e
cd /opt/firstlight
image=\$(docker compose images api --format json | python3 -c 'import json,sys; i=json.load(sys.stdin)[0]; print(i[\"Repository\"] + \":\" + i[\"Tag\"])')
docker image tag \"\$image\" \"\${image%:*}:$VERSION\"
DD_VERSION=$VERSION INGEST_DUPLICATE_CHECK=$CHECK docker compose up -d --no-deps --wait api
docker compose ps api --format '{{.Service}} {{.Image}} {{.Status}}'"
echo "firstlight-api $VERSION is live (duplicate check: $CHECK)"
