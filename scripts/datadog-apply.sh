#!/usr/bin/env bash
# Create or update the Datadog setup in infra/datadog (webhook, monitors, SLOs, dashboards) in the org whose
# keys are in the demo host's .env. Run it again after editing the files, or after moving to another org:
# put the new DD_API_KEY, DD_APP_KEY and DD_SITE in the server's .env, `docker compose up -d`, then this.
# It runs on the server, in a throwaway container of the app's image, so no key leaves the server.
set -euo pipefail
cd "$(dirname "$0")/.."

get() { sed -n "s/^$1=//p" .env | head -1; }
HOST="$(get VPS_USERNAME || true)"; HOST="${HOST:-root}@$(get VPS_IP)"

rsync -az --delete -e "ssh -o BatchMode=yes" infra/datadog/ "$HOST:/opt/firstlight/infra/datadog/"
ssh -o BatchMode=yes "$HOST" 'cd /opt/firstlight
  image=$(docker inspect firstlight-brain-1 --format "{{.Config.Image}}")
  docker run --rm --env-file .env -v /opt/firstlight/infra/datadog:/datadog:ro --entrypoint python "$image" /datadog/apply.py'
