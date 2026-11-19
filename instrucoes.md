# DocOps — Instruções Operacionais (PRD e HML)

Guia rápido de referência para operar, atualizar, testar e fazer rollback nos ambientes de **Produção (PRD)** e **Homologação (HML)** do **DocOps**.

---

## 1. Visão Geral dos Ambientes

Os dois ambientes rodam no mesmo servidor (`10.10.1.218`, diretório `/home/ubuntu/DocOps`) de forma **100% isolada** (containers, imagens, redes, bancos de dados, volumes e backups separados).

| Propriedade | PRD (Produção) | HML (Homologação) |
|---|---|---|
| **URL interna (HTTPS)** | `https://10.10.1.218` | `https://10.10.1.218:8443` |
| **URL externa (HTTPS)** | `https://107.21.233.13` | `https://107.21.233.13:8443` |
| **Porta HTTP** | `80` *(redireciona para 443)* | `8080` *(redireciona para 8443)* |
| **Porta HTTPS** | `443` | `8443` |
| **Projeto Docker Compose** | `docops` | `docops-hml` |
| **Arquivo Compose** | `docker-compose.yml` | `docker-compose.hml.yml` |
| **Arquivo de Variáveis** | `.env` | `.env.hml` *(gerado automaticamente na 1ª execução)* |
| **Caddyfile (Proxy/TLS)** | `deploy/caddy/Caddyfile` | `deploy/caddy/Caddyfile.hml` |
| **Imagens Docker** | `docops-backend:latest` / `docops-frontend:latest` | `docops-hml-backend:latest` / `docops-hml-frontend:latest` |
| **Banco PostgreSQL** | `docops` (volume `docops_pgdata`) | `docops_hml` (volume `docops-hml_pgdata_hml`) |
| **Redis** | volume `docops_redisdata` | volume `docops-hml_redisdata_hml` |
| **Pasta de Backups** | `./backups` (retenção 14 dias, 02h) | `./backups-hml` (retenção 7 dias, 03h) |
| **Branch Git recomendada** | `main` | `hml` *(ou qualquer branch de teste)* |

---

## 2. Comandos Principais (`./scripts/deploy.sh`)

Execute todos os comandos dentro da pasta do repositório (`/home/ubuntu/DocOps`).

### Subir ou atualizar HML
```bash
# Puxa alterações do Git e sobe/reconstrói HML (portas 8080 / 8443)
./scripts/deploy.sh hml --pull

# Sobe/reconstrói HML usando o código local atual (sem git pull)
./scripts/deploy.sh hml
```
> Na primeira execução, o script cria automaticamente o arquivo `.env.hml` reaproveitando `DOCOPS_HOST` e `SECRET_KEY` do `.env` de PRD (para compatibilidade na clonagem de dados criptografados com Fernet) e gerando uma senha própria para o banco `docops_hml`.

### Clonar dados reais de PRD para HML (sem alterar PRD)
Ideal para validar novas funcionalidades ou mudanças visuais com o inventário, clientes e usuários reais:
```bash
./scripts/deploy.sh clone-prd-to-hml
```
> Após clonar, o login em HML passa a usar o **mesmo e-mail, senha e MFA de PRD**.

### Subir ou atualizar PRD
```bash
# Faz backup automático do banco PRD, faz git pull e reconstrói PRD (portas 80 / 443)
./scripts/deploy.sh prd --pull

# Ou sem git pull (usando o commit atual do diretório)
./scripts/deploy.sh prd
```
*(O script legado `./scripts/update.sh` continua funcionando normalmente para PRD.)*

### Verificar status dos dois ambientes
```bash
./scripts/deploy.sh status
```

### Parar HML (economizar RAM/CPU sem perder dados)
```bash
./scripts/deploy.sh stop-hml
```
Para ligar novamente depois, basta rodar `./scripts/deploy.sh hml`.

---

## 3. Rollback (Voltar Versão)

Se algo não ficar como esperado em HML ou PRD, volte para qualquer commit ou tag anterior:

```bash
# Ver os últimos commits disponíveis
git log --oneline -n 10

# Rollback em HML para um commit específico
./scripts/deploy.sh rollback hml <hash_do_commit>

# Rollback em PRD (faz backup do banco antes de reconstruir)
./scripts/deploy.sh rollback prd <hash_do_commit>

# Para voltar à branch principal depois de um rollback
git checkout main
```

---

## 4. Fluxo Recomendado: Testar em HML antes de PRD

```bash
# 1. Trocar para a branch de homologação e atualizar
git fetch origin
git checkout hml
git pull origin hml

# 2. Subir em HML e testar em https://10.10.1.218:8443
./scripts/deploy.sh hml

# 3. (Opcional) Sincronizar dados de PRD -> HML para testes realistas
./scripts/deploy.sh clone-prd-to-hml

# 4. Aprovado em HML? Voltar para main (após merge) e publicar em PRD
git checkout main
./scripts/deploy.sh prd --pull
```

---

## 5. Logs, Credenciais Iniciais e Troubleshooting

### Ver senha aleatória do admin inicial (HML recém-criado sem clone de PRD)
```bash
docker compose -f docker-compose.hml.yml --env-file .env.hml logs backend | grep -i -E "admin|senha|password"
```

### Acompanhar logs em tempo real
```bash
# Logs de PRD
docker compose logs -f backend worker proxy

# Logs de HML
docker compose -f docker-compose.hml.yml --env-file .env.hml logs -f backend worker proxy
```

### Backup manual e Restore (PRD)
```bash
# Gerar backup imediato do banco de PRD
docker compose exec -T backup sh /scripts/backup.sh --once

# Listar backups salvos
ls -lh backups/

# Restaurar um backup específico em PRD
./scripts/restore.sh backups/<arquivo.sql.gz>
```

### Alterar portas de HML (opcional)
Edite no arquivo `.env.hml`:
```env
HML_HTTP_PORT=8080
HML_HTTPS_PORT=8443
```
E reaplique com `./scripts/deploy.sh hml`.
