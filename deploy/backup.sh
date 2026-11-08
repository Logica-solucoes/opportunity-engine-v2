#!/usr/bin/env bash
# Daily backup of the database and the uploaded files; keeps 7 days. Cron: 0 3 * * * /opt/gem/deploy/backup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/compose.yml --env-file deploy/.env)
root="${BACKUP_DIR:-/var/backups/gem}"
dir="$root/$(date +%F)"
mkdir -p "$dir"

"${compose[@]}" exec -T postgres pg_dump -U app -Fc app > "$dir/db.dump"
"${compose[@]}" exec -T api tar czf - -C /app/data . > "$dir/storage.tgz"

find "$root" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
echo "backup ok: $dir"
