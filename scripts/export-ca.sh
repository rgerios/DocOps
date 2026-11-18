#!/usr/bin/env bash
# Exporta o certificado raiz da CA interna do Caddy. Instale-o como "Autoridade raiz confiável"
# nas máquinas dos usuários (ou distribua por GPO/MDM) para o navegador não alertar sobre o certificado.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./docops-root-ca.crt
echo "Certificado salvo em $(pwd)/docops-root-ca.crt"
