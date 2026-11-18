#!/usr/bin/env bash
# Atualiza o DocOps para a versão mais recente do repositório.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "▸ backup antes de atualizar"
docker compose exec -T backup sh /scripts/backup.sh --once
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
