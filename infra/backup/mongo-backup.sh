#!/usr/bin/env bash
# Nightly mongodump of the Firstlight database on the demo host; keeps the newest three archives.
set -euo pipefail
umask 077
cd /opt/firstlight
mkdir -p backups
user="$(sed -n 's/^MONGO_ROOT_USER=//p' .env)"; pw="$(sed -n 's/^MONGO_ROOT_PASSWORD=//p' .env)"
docker compose exec -T mongo mongodump --quiet --archive --gzip --db "${MONGODB_DB:-firstlight}" \
  --uri "mongodb://${user:-firstlight}:${pw}@localhost:27017/?directConnection=true&authSource=admin" \
  > "backups/firstlight-$(date +%F).archive.gz"
ls -1t backups/firstlight-*.archive.gz | tail -n +4 | xargs -r rm -f
echo "$(date -Is) backup ok: $(ls -1 backups | wc -l) archive(s)"
