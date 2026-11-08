#!/usr/bin/env bash
# Applies new DB migrations. Each file in db/migrations/ runs exactly once.
# What already ran is remembered in the table schema_migrations.
# Usage: ./scripts/migrate.sh   (deploy.sh and setup_server.sh call it)
set -euo pipefail
cd "$(dirname "$0")/.."

# Use sudo only if docker doesn't work without it (e.g. right after first setup)
if docker info >/dev/null 2>&1; then DOCKER=docker; else DOCKER="sudo docker"; fi
psql() { $DOCKER compose exec -T db psql -U ops -d ops -q -v ON_ERROR_STOP=1 "$@"; }

# The table that remembers which files already ran
psql -c "SET client_min_messages = warning" \
     -c "CREATE TABLE IF NOT EXISTS schema_migrations (
           filename   TEXT PRIMARY KEY,
           applied_at TIMESTAMP NOT NULL DEFAULT now())"

for f in db/migrations/*.sql; do
  name=$(basename "$f")
  # Already in the table? Skip it.
  if [ -n "$(psql -tAc "SELECT 1 FROM schema_migrations WHERE filename = '$name'")" ]; then
    continue
  fi
  echo "   applying $name"
  # Run the file and record it together: if the file fails, neither happens
  { cat "$f"; printf "\nINSERT INTO schema_migrations (filename) VALUES ('%s');\n" "$name"; } \
    | psql --single-transaction
done
echo "   migrations up to date"