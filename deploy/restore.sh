#!/usr/bin/env bash
# Restore a backup folder made by backup.sh. Overwrites the database and the uploaded files.
set -euo pipefail

src="${1:?usage: deploy/restore.sh /var/backups/gem/AAAA-MM-DD}"
src="$(cd "$src" && pwd)"
[[ -f "$src/db.dump" && -f "$src/storage.tgz" ]] || { echo "missing db.dump or storage.tgz in $src" >&2; exit 1; }

cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/compose.yml --env-file deploy/.env)

read -r -p "Restore $src over the current database and files? Type 'restaurar': " answer
[[ "$answer" == "restaurar" ]] || { echo "aborted"; exit 1; }

"${compose[@]}" stop api
"${compose[@]}" exec -T postgres pg_restore -U app -d app --clean --if-exists < "$src/db.dump"
"${compose[@]}" run --rm -T --no-deps --entrypoint sh api -c 'find /app/data -mindepth 1 -delete && tar xzf - -C /app/data' < "$src/storage.tgz"
"${compose[@]}" start api
echo "restore ok: $src"
