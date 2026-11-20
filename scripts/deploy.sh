#!/usr/bin/env bash
# Updates the server to the latest code on main.
# Run by GitHub Actions on every push to main, or by hand:  ./scripts/deploy.sh
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."   # go to the project root

  echo "== Pull latest code"
  git pull --ff-only

  echo "== Install libraries"
  ~/.local/bin/uv sync

  echo "== Apply migrations"
  scripts/migrate.sh

  echo "== Restart Caddy (picks up Caddyfile changes; the certificate is kept)"
  sudo docker compose --profile server up -d --force-recreate caddy

  echo "== Restart the WhatsApp bot (loads the new code)"
  sudo systemctl restart tema-bot

  echo "== Deployed: $(git log -1 --format='%h %s')"
}

main "$@"