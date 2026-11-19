#!/usr/bin/env bash
# Gerenciador de deploy e rollback do DocOps para ambientes HML e PRD.
#
# Uso:
#   ./scripts/deploy.sh hml [--pull]            Sobe/atualiza HML (portas 8080/8443)
#   ./scripts/deploy.sh prd [--pull]            Faz backup de PRD e sobe/atualiza PRD (portas 80/443)
#   ./scripts/deploy.sh status                  Mostra status dos containers HML e PRD
#   ./scripts/deploy.sh stop-hml                Para os containers de HML sem apagar dados
#   ./scripts/deploy.sh clone-prd-to-hml        Copia o banco de PRD para o banco de HML
#   ./scripts/deploy.sh rollback <hml|prd> <ref> Faz rollback do código para <commit/tag> e reconstrói
set -euo pipefail
cd "$(dirname "$0")/.."

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    python3 -c "import secrets; print(secrets.token_hex($1))"
  fi
}

ensure_hml_env() {
  if [ -f .env.hml ]; then
    return
  fi
  echo "▸ .env.hml não encontrado — criando a partir de .env.hml.example"
  cp .env.hml.example .env.hml

  # Se existir .env de PRD, aproveita DOCOPS_HOST e SECRET_KEY (facilita clonar banco PRD->HML)
  local host="localhost"
  local skey
  skey="$(rand_hex 32)"
  local pgpass
  pgpass="$(rand_hex 20)"

  if [ -f .env ]; then
    local prd_host prd_key
    prd_host="$(grep -E '^DOCOPS_HOST=' .env | head -n1 | cut -d= -f2- || true)"
    prd_key="$(grep -E '^SECRET_KEY=' .env | head -n1 | cut -d= -f2- || true)"
    [ -n "$prd_host" ] && host="$prd_host"
    [ -n "$prd_key" ] && skey="$prd_key"
  fi

  python3 - "$host" "$skey" "$pgpass" <<'PY'
import sys, pathlib, re
host, skey, pgpass = sys.argv[1:4]
p = pathlib.Path(".env.hml")
txt = p.read_text()
txt = re.sub(r'^DOCOPS_HOST=.*$', f'DOCOPS_HOST={host}', txt, flags=re.M)
txt = re.sub(r'^SECRET_KEY=.*$', f'SECRET_KEY={skey}', txt, flags=re.M)
txt = re.sub(r'^POSTGRES_PASSWORD=.*$', f'POSTGRES_PASSWORD={pgpass}', txt, flags=re.M)
p.write_text(txt)
PY
  chmod 600 .env.hml
  echo "  ✔ .env.hml criado (DOCOPS_HOST=${host}, portas 8080/8443)"
}

dc_hml() {
  docker compose -f docker-compose.hml.yml --env-file .env.hml "$@"
}

dc_prd() {
  docker compose -f docker-compose.yml --env-file .env "$@"
}

deploy_hml() {
  ensure_hml_env
  if [ "${1:-}" = "--pull" ]; then
    echo "▸ git pull --ff-only"
    git pull --ff-only
  fi
  echo "▸ subindo DocOps HML (portas ${HML_HTTP_PORT:-8080} / ${HML_HTTPS_PORT:-8443})"
  dc_hml up -d --build
  dc_hml ps
  local host port
  host="$(grep -E '^DOCOPS_HOST=' .env.hml | head -n1 | cut -d= -f2- | cut -d, -f1 | xargs || echo localhost)"
  port="$(grep -E '^HML_HTTPS_PORT=' .env.hml | head -n1 | cut -d= -f2- || echo 8443)"
  echo ""
  echo "✔ HML disponível em: https://${host}:${port}"
}

deploy_prd() {
  if [ ! -f .env ]; then
    echo "✖ Arquivo .env de PRD não encontrado." >&2
    exit 1
  fi
  if dc_prd ps --status running 2>/dev/null | grep -q backup; then
    echo "▸ backup de segurança de PRD antes de atualizar"
    dc_prd exec -T backup sh /scripts/backup.sh --once
  fi
  if [ "${1:-}" = "--pull" ]; then
    echo "▸ git pull --ff-only"
    git pull --ff-only
  fi
  echo "▸ subindo DocOps PRD (portas 80 / 443)"
  dc_prd up -d --build
  docker image prune -f >/dev/null || true
  dc_prd ps
  local host
  host="$(grep -E '^DOCOPS_HOST=' .env | head -n1 | cut -d= -f2- | cut -d, -f1 | xargs || echo localhost)"
  echo ""
  echo "✔ PRD disponível em: https://${host}"
}

clone_prd_to_hml() {
  if [ ! -f .env ]; then
    echo "✖ Arquivo .env de PRD não encontrado." >&2
    exit 1
  fi
  ensure_hml_env
  echo "▸ garantindo que o banco de HML está rodando..."
  dc_hml up -d db
  echo "▸ aguardando Postgres HML ficar saudável..."
  until dc_hml exec -T db pg_isready -U docops -d docops_hml >/dev/null 2>&1; do sleep 1; done
  echo "▸ clonando dump de PRD (docops) -> HML (docops_hml)..."
  dc_prd exec -T db pg_dump -U docops -d docops --clean --if-exists --no-owner \
    | dc_hml exec -T db psql -U docops -d docops_hml -v ON_ERROR_STOP=1 >/dev/null
  echo "▸ reiniciando backend/worker/scheduler de HML..."
  dc_hml restart backend worker scheduler >/dev/null 2>&1 || true
  echo "✔ Banco de HML sincronizado com PRD (PRD não foi alterado)."
}

rollback_env() {
  local target="${1:-}"
  local ref="${2:-}"
  if [ -z "$target" ] || [ -z "$ref" ]; then
    echo "Uso: ./scripts/deploy.sh rollback <hml|prd> <commit_ou_tag>" >&2
    exit 1
  fi
  if ! git rev-parse --verify "${ref}^{commit}" >/dev/null 2>&1; then
    echo "✖ Referência Git inválida: ${ref}" >&2
    exit 1
  fi
  if [ -n "$(git status --porcelain)" ]; then
    echo "✖ Existem alterações locais não commitadas. Faça commit ou stash antes do rollback." >&2
    exit 1
  fi

  local cur
  cur="$(git rev-parse --short HEAD)"
  echo "▸ rollback de ${target^^}: ${cur} -> ${ref}"
  git checkout "$ref"
  if [ "$target" = "hml" ]; then
    deploy_hml
  elif [ "$target" = "prd" ]; then
    deploy_prd
  else
    echo "✖ Ambiente inválido: ${target} (use hml ou prd)" >&2
    exit 1
  fi
  echo ""
  echo "ℹ Para voltar para a branch main depois: git checkout main"
}

show_status() {
  echo "=== PRD (docops · portas 80/443) ==="
  [ -f .env ] && dc_prd ps || echo "(sem .env configurado)"
  echo ""
  echo "=== HML (docops-hml · portas 8080/8443) ==="
  [ -f .env.hml ] && dc_hml ps || echo "(sem .env.hml configurado)"
}

case "${1:-}" in
  hml)              deploy_hml "${2:-}" ;;
  prd)              deploy_prd "${2:-}" ;;
  status)           show_status ;;
  stop-hml)         dc_hml stop ;;
  clone-prd-to-hml) clone_prd_to_hml ;;
  rollback)         rollback_env "${2:-}" "${3:-}" ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
