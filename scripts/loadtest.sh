#!/usr/bin/env bash
# Load test on the demo host: a second API, brain and simulator with N farms (4 ponds each on average) on the
# demo's MongoDB, in a database of their own, so the demo's data is untouched. Every minute it prints
# the ingest rate, how fresh every pond is, how old the forecasts are, MongoDB operations and resource
# use. At the end it removes what it started and drops the database. It stops early if the demo's
# API stops answering.
#   scripts/loadtest.sh [farms=500] [minutes=5]
set -euo pipefail
cd "$(dirname "$0")/.."

FARMS="${1:-500}"; MINUTES="${2:-5}"
get() { sed -n "s/^$1=//p" .env | head -1; }
HOST="$(get VPS_USERNAME || true)"; HOST="${HOST:-root}@$(get VPS_IP)"

ssh -o BatchMode=yes "$HOST" "FARMS=$FARMS MINUTES=$MINUTES bash -s" <<'REMOTE'
set -euo pipefail
cd /opt/firstlight
set -a; . ./.env; set +a
NET=$(docker inspect firstlight-api-1 --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' | awk '{print $1}')
IMAGE=$(docker inspect firstlight-api-1 --format '{{.Config.Image}}')
ENVFILE=$(mktemp); chmod 600 "$ENVFILE"  # secrets go in a file, never on a command line
cat >"$ENVFILE" <<EOF
MONGODB_URI=mongodb://${MONGO_ROOT_USER:-firstlight}:${MONGO_ROOT_PASSWORD}@mongo:27017/?directConnection=true&authSource=admin
MONGODB_DB=firstlight_load
GATEWAY_TOKEN=load-$(openssl rand -hex 8)
DD_TRACE_ENABLED=false
SIM_FARM_CLOCK_OFFSET_HOURS=7
EOF
run() { docker run -d --name "$1" --network "$NET" --env-file "$ENVFILE" --entrypoint firstlight "${@:2}" >/dev/null; }

MEASURE=$(cat <<'PY'
import os, time
from datetime import UTC, datetime, timedelta
from pymongo import MongoClient

db = MongoClient(os.environ["MONGODB_URI"], tz_aware=True)[os.environ["MONGODB_DB"]]
before = db.command("serverStatus")["opcounters"]
time.sleep(5)
after = db.command("serverStatus")["opcounters"]
ops = {k: (after[k] - before[k]) / 5 for k in ("insert", "update", "query", "getmore", "command")}
now = datetime.now(UTC)
minute = now - timedelta(minutes=1)
readings = db.readings.count_documents({"ts": {"$gte": minute}})
batches = db.ingest_batches.count_documents({"received_at": {"$gte": minute}})
states = list(db.pond_state.find({"last.ts": {"$exists": True}}, {"last.ts": 1, "forecast.at": 1}))
fresh = sorted((now - s["last"]["ts"]).total_seconds() for s in states)
stale = sum(1 for s in states if (now - s.get("forecast", {}).get("at", now - timedelta(days=1))) > timedelta(seconds=25))
q = lambda p: f"{fresh[min(len(fresh) - 1, int(p * len(fresh)))]:.0f}" if fresh else "-"
print(
    f"  {readings / 60:.0f} readings/s, {batches / 60:.1f} batches/s | {len(states)} ponds, data age"
    f" p50 {q(0.5)} s, p99 {q(0.99)} s, max {q(1)} s | forecasts older than 25 s: {stale}\n"
    "  mongo ops/s " + ", ".join(f"{k} {v:.0f}" for k, v in ops.items())
)
PY
)

cleanup() {
  docker rm -f load-edge load-brain load-api >/dev/null 2>&1 || true
  # Dropped only once nothing writes to it any more; the demo's API has the driver and the address.
  docker exec firstlight-api-1 python -c "import os; from pymongo import MongoClient; MongoClient(os.environ['MONGODB_URI']).drop_database('firstlight_load')" 2>/dev/null || true
  rm -f "$ENVFILE"
  echo "cleaned up: load containers removed, firstlight_load dropped"
}
trap cleanup EXIT

run load-api "$IMAGE" api
run load-brain "$IMAGE" brain
sleep 8
run load-edge -e FIRSTLIGHT_API_URL=http://load-api:8000 -e SIM_FARMS="$FARMS" \
  -e SIM_BATCH_SECONDS=10 "$IMAGE" edge
echo "load: $FARMS farms, $((FARMS * 4)) ponds, $FARMS gateways, for $MINUTES min (image $IMAGE)"

for _ in $(seq 1 60); do  # warm-up: six hours of physics, then every gateway announces itself
  docker logs load-edge 2>&1 | grep '"manifests announced"' >/dev/null && break
  sleep 5
done
echo "edge: $(docker logs load-edge 2>&1 | grep -o '"message": "manifests announced"[^}]*' | head -1)"
sleep 60

for i in $(seq 1 "$MINUTES"); do
  curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/healthz || { echo "demo API not answering: stopping"; exit 1; }
  echo "minute $i"
  docker exec load-api python -c "$MEASURE" || echo "  measurement failed"
  brain=$(docker logs --since 60s load-brain 2>&1 || true)
  grep -o '"cycle_s": [0-9.]*' <<<"$brain" | awk -F': ' '{n++; s+=$2; if ($2>m) m=$2}
    END {if (n) printf "  brain cycle: %d logged, mean %.2f s, max %.2f s\n", n, s/n, m}' || true
  echo "  brain cycles over 10 s: $(grep -c 'brain cycle overran' <<<"$brain" || true)"
  docker stats --no-stream --format '  {{.Name}} cpu {{.CPUPerc}} mem {{.MemUsage}}' \
    firstlight-mongo-1 firstlight-api-1 firstlight-brain-1 load-api load-brain load-edge || true
  sleep 50
done
echo "edge warnings: $(docker logs load-edge 2>&1 | grep -c '"status": "warning"' || true)"
echo "api errors: $(docker logs load-api 2>&1 | grep -c '"status": "error"' || true)"
echo "brain errors: $(docker logs load-brain 2>&1 | grep -c '"status": "error"' || true)"
REMOTE
