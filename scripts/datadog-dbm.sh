#!/usr/bin/env bash
# One-time setup on the demo host for Datadog Database Monitoring of its MongoDB:
#   - a `datadog` user with the read-only roles DBM needs (read on admin and local, clusterMonitor,
#     readAnyDatabase), its password generated on the server into .env as DD_MONGO_PASSWORD;
#   - MONGODB_QUERY_STATS_RATE=1 in .env, so the API has MongoDB sample queries for DBM's query metrics.
# The Agent's check is the Autodiscovery label in compose.yaml. Safe to run again: it updates the user.
# The password goes from .env to MongoDB through stdin and is never printed.
set -euo pipefail
cd "$(dirname "$0")/.."

get() { sed -n "s/^$1=//p" .env | head -1; }
HOST="$(get VPS_USERNAME || true)"; HOST="${HOST:-root}@$(get VPS_IP)"

ssh -o BatchMode=yes "$HOST" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/firstlight
grep -q '^DD_MONGO_PASSWORD=.' .env || echo "DD_MONGO_PASSWORD=$(openssl rand -hex 24)" >> .env
grep -q '^MONGODB_QUERY_STATS_RATE=' .env || echo "MONGODB_QUERY_STATS_RATE=1" >> .env

program=$(mktemp)
trap 'rm -f "$program"' EXIT
cat > "$program" <<'PY'
import os
import sys

from pymongo import MongoClient

password = sys.stdin.read().strip()
admin = MongoClient(os.environ["MONGODB_URI"]).admin
roles = [
    {"role": "read", "db": "admin"},
    {"role": "read", "db": "local"},
    {"role": "clusterMonitor", "db": "admin"},
    {"role": "readAnyDatabase", "db": "admin"},
]
exists = bool(admin.command("usersInfo", "datadog")["users"])
admin.command("updateUser" if exists else "createUser", "datadog", pwd=password, roles=roles)
print("MongoDB user datadog", "updated" if exists else "created")
PY
docker cp "$program" firstlight-api-1:/tmp/datadog_user.py
sed -n 's/^DD_MONGO_PASSWORD=//p' .env | docker exec -i firstlight-api-1 python /tmp/datadog_user.py
docker exec -u 0 firstlight-api-1 rm -f /tmp/datadog_user.py
REMOTE
