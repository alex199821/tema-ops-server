#!/usr/bin/env bash
# Sets up a fresh Ubuntu server for tema-ops. Safe to run again.
# Usage (on the server, inside the cloned repo):  ./scripts/setup_server.sh
#
# NOT done by this script (manual, because they are secrets):
#   - .env                (copy from your Mac)
#   - auth/wolt.json      (copy from your Mac, or re-seed the Wolt token)
set -euo pipefail

cd "$(dirname "$0")/.."   # run from the project root

echo "== Timezone"
sudo timedatectl set-timezone Asia/Tbilisi

echo "== Docker"
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"

echo "== uv (Python package manager)"
if [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "== Python and libraries"
uv sync

echo "== Database"
sudo docker compose up -d db
until sudo docker compose exec -T db pg_isready -U ops -d ops >/dev/null 2>&1; do sleep 2; done
for f in db/migrations/*.sql; do
  echo "   applying $f"
  sudo docker compose exec -T db psql -U ops -d ops -v ON_ERROR_STOP=1 < "$f"
done

echo "== Done. Log out and back in once so 'docker' works without sudo."
