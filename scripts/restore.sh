#!/usr/bin/env bash
# Restaura um backup: ./scripts/restore.sh backups/docops_20261118_0200.dump
# ATENÇÃO: substitui todo o conteúdo atual do banco.
set -euo pipefail
cd "$(dirname "$0")/.."
f="${1:?informe o arquivo .dump}"
[ -f "$f" ] || { echo "arquivo não encontrado: $f"; exit 1; }
read -r -p "Isso SUBSTITUI todos os dados atuais pelo backup $f. Digite RESTAURAR para continuar: " ok
[ "$ok" = "RESTAURAR" ] || { echo "cancelado"; exit 1; }
docker compose stop backend worker scheduler
docker compose exec -T db sh -c 'pg_restore -U docops -d docops --clean --if-exists --no-owner' < "$f"
docker compose start backend worker scheduler
echo "restauração concluída"
