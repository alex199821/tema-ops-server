#!/usr/bin/env bash
# Backs up the whole database to the Google Cloud Storage bucket.
# Run every day by cron, through run_job.py, so a failure sends an alert email.
# The bucket comes from BACKUP_BUCKET in .env.
# Usage: ./scripts/backup_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="/snap/bin:$PATH"   # cron doesn't look in /snap/bin, where gcloud lives on this server
BUCKET=$(grep '^BACKUP_BUCKET=' .env | cut -d= -f2- || true)
: "${BUCKET:?BACKUP_BUCKET is missing in .env}"
FILE=/tmp/ops_$(date +%Y-%m-%d_%H%M).dump
trap 'rm -f "$FILE"' EXIT       # always delete the local copy at the end, success or failure

# Use sudo only if docker doesn't work without it (same as migrate.sh)
if docker info >/dev/null 2>&1; then DOCKER=docker; else DOCKER="sudo docker"; fi

echo "== Dump the database"
$DOCKER compose exec -T db pg_dump -U ops -d ops --format=custom > "$FILE"

echo "== Upload $(du -h "$FILE" | cut -f1)"
gcloud storage cp "$FILE" "$BUCKET/"

echo "== Backed up $(basename "$FILE")"