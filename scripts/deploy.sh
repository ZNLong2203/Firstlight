#!/usr/bin/env bash
# Copy the runtime files to the VPS and (re)start the stack there.
# Reads VPS_IP and VPS_USERNAME from .env and logs in with your SSH key.
#   scripts/deploy.sh               deploy, keeping the server's own .env
#   scripts/deploy.sh --push-env    first deploy: build the server's .env from yours
#   scripts/deploy.sh --build       also copy the source and build the images on the server
#   scripts/deploy.sh --ci[=SHA]    run the images CI pushed to GHCR for that commit (default HEAD),
#                                   with the git sha as DD_VERSION; CI must have passed for it
set -euo pipefail
cd "$(dirname "$0")/.."

get() { sed -n "s/^$1=//p" .env | head -1; }
IP="$(get VPS_IP)"; USER_="$(get VPS_USERNAME)"
[ -n "$IP" ] || { echo "VPS_IP is empty in .env" >&2; exit 1; }
HOST="${USER_:-root}@${IP}"
DIR=/opt/firstlight
SSH="ssh -o BatchMode=yes -o ConnectTimeout=15"
PUSH_ENV=0; BUILD=0; SHA=""
for arg in "$@"; do
  case "$arg" in
    --push-env) PUSH_ENV=1 ;;
    --build) BUILD=1 ;;
    --ci) SHA="$(git rev-parse HEAD)" ;;
    --ci=*) SHA="$(git rev-parse "${arg#--ci=}")" ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
if [ -n "$SHA" ]; then
  [ "$BUILD" = 0 ] || { echo "--ci and --build exclude each other" >&2; exit 2; }
  CI="$(gh run list --commit "$SHA" --workflow ci --json conclusion --jq '.[0].conclusion' 2>/dev/null || true)"
  [ "$CI" = success ] || { echo "CI has not passed for $SHA (${CI:-no run})" >&2; exit 1; }
  OWNER="$(gh repo view --json owner --jq .owner.login | tr '[:upper:]' '[:lower:]')"
fi

# Which images compose runs is kept in the server's .env: CI's for --ci, a local build otherwise.
set_env() {
  $SSH "$HOST" bash -s -- "$DIR" "$@" <<'REMOTE'
set -euo pipefail
cd "$1"; shift
for pair in "$@"; do
  sed -i "/^${pair%%=*}=/d" .env
  if [ -n "${pair#*=}" ]; then echo "$pair" >> .env; fi
done
REMOTE
}

if [ "$PUSH_ENV" = 1 ]; then
  # The server never receives VPS_* lines, and runs as the demo environment.
  PUBLIC_HOST_DEFAULT="$(echo "$IP" | tr . -).sslip.io"
  grep -v '^VPS_' .env \
    | sed -e 's/^APP_ENV=.*/APP_ENV=demo/' -e 's/^DD_ENV=.*/DD_ENV=demo/' \
          -e "s/^PUBLIC_HOST=$/PUBLIC_HOST=${PUBLIC_HOST_DEFAULT}/" \
          -e "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=${COMPOSE_PROFILES_REMOTE:-proxy}/" \
    | $SSH "$HOST" "umask 077 && mkdir -p $DIR && cat > $DIR/.env"
  echo "pushed .env to $HOST:$DIR (PUBLIC_HOST defaults to $PUBLIC_HOST_DEFAULT)"
fi

rsync -az -e "$SSH" compose.yaml "$HOST:$DIR/compose.yaml"
if [ "$BUILD" = 1 ]; then
  rsync -az --delete -e "$SSH" --exclude node_modules --exclude dist --exclude __pycache__ \
    Dockerfile .dockerignore pyproject.toml uv.lock README.md src web "$HOST:$DIR/"
fi
rsync -az --delete -e "$SSH" --exclude datadog --exclude mongo infra/ "$HOST:$DIR/infra/"
if [ -n "$SHA" ]; then
  set_env "FIRSTLIGHT_IMAGE=ghcr.io/$OWNER/firstlight" "FIRSTLIGHT_WEB_IMAGE=ghcr.io/$OWNER/firstlight-web" \
    "DD_VERSION=$SHA"
elif [ "$BUILD" = 1 ]; then
  set_env FIRSTLIGHT_IMAGE= FIRSTLIGHT_WEB_IMAGE= DD_VERSION=
fi

$SSH "$HOST" "cd $DIR && test -f .env || { echo 'no .env on the server; run with --push-env' >&2; exit 1; }
  install -m 644 infra/backup/firstlight-backup.cron /etc/cron.d/firstlight-backup
  if [ $BUILD = 1 ]; then docker compose build --quiet; fi
  if [ -n '$SHA' ]; then docker compose pull --quiet api brain edge web; fi
  docker compose pull --ignore-buildable --quiet
  docker compose up -d --remove-orphans
  docker image prune -f >/dev/null
  docker compose ps --format 'table {{.Service}}\t{{.Status}}'"
