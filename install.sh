#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# DocOps — instalação em Ubuntu 22.04 / 24.04
#   sudo ./install.sh [--host 10.0.10.25] [--admin-email voce@empresa.com.br]
#
# 1. instala Docker Engine + Compose (repositório oficial), se faltar
# 2. gera o .env com segredos aleatórios (só na primeira vez)
# 3. constrói e sobe a stack
# 4. mostra o endereço e a senha provisória do primeiro administrador
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

HOST=""; ADMIN_EMAIL="admin@docops.local"
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1"; exit 1 ;;
  esac
done

say() { printf '\n\033[1;32m▸ %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Rode com sudo: sudo ./install.sh"; exit 1; }
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || echo "Aviso: testado em Ubuntu; detectado ${PRETTY_NAME:-desconhecido}."

# 1. Docker
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  say "Instalando Docker Engine e Compose"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg openssl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
command -v openssl >/dev/null || apt-get install -y -qq openssl

# 2. .env
FIRST_PASSWORD=""
if [ ! -f .env ]; then
  say "Gerando .env com segredos aleatórios"
  [ -n "$HOST" ] || HOST="$(hostname -I | awk '{print $1}')"
  FIRST_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)#9a"
  cp .env.example .env
  sed -i "s|^DOCOPS_HOST=.*|DOCOPS_HOST=${HOST}|" .env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
  sed -i "s|^ADMIN_EMAIL=.*|ADMIN_EMAIL=${ADMIN_EMAIL}|" .env
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${FIRST_PASSWORD}|" .env
  chmod 600 .env
else
  say ".env já existe — mantendo configuração atual"
  [ -z "$HOST" ] || sed -i "s|^DOCOPS_HOST=.*|DOCOPS_HOST=${HOST}|" .env
fi
mkdir -p backups && chmod 700 backups

# 3. sobe a stack
say "Construindo imagens e subindo os serviços (a primeira vez leva alguns minutos)"
docker compose up -d --build

say "Aguardando a API responder"
for _ in $(seq 1 60); do
  if docker compose exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)" >/dev/null 2>&1; then OK=1; break; fi
  sleep 3
done
[ "${OK:-}" = 1 ] || { echo "A API não respondeu. Veja: docker compose logs backend"; exit 1; }

# 4. resumo
HOSTS="$(grep '^DOCOPS_HOST=' .env | cut -d= -f2- | tr -d ' ')"
say "DocOps no ar"
echo "  Endereço:  https://${HOSTS%%,*}"
if [ -n "$FIRST_PASSWORD" ]; then
  echo "  Usuário:   ${ADMIN_EMAIL}"
  echo "  Senha:     ${FIRST_PASSWORD}   (provisória — será pedida a troca no primeiro acesso)"
  echo
  echo "  Depois do primeiro login, apague ADMIN_PASSWORD do .env:  sudo sed -i 's|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=|' .env"
fi
echo
echo "  Certificado autoassinado: o navegador vai alertar até você confiar na CA interna."
echo "  Exporte com ./scripts/export-ca.sh e instale como autoridade raiz nas máquinas dos usuários."
echo "  Backups diários em $(pwd)/backups (retenção em BACKUP_RETENTION_DAYS)."
