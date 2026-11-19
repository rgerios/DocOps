# Documentação da Plataforma DocOps

O **DocOps** é a plataforma corporativa multi-tenant do ecossistema **DocViva** para **inventário vivo, documentação técnica, segurança, FinOps, análise assistida por IA e governança de ambientes em nuvem (AWS)**.

---

## 1. Visão Geral da Arquitetura

```text
┌──────────────────────────────────────────────────────────┐
│                     Caddy (TLS / Proxy)                  │
└───────────────────────────┬──────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
┌───────────────────┐                 ┌────────────────────┐
│ Frontend (SPA)    │   /api/* JSON   │ Backend (FastAPI)  │
│ React + Vite + TS │ ──────────────► │ Python 3.12+       │
└───────────────────┘                 │ SQLAlchemy ORM     │
                                      │ APScheduler        │
                                      │ WeasyPrint (PDF)   │
                                      └─────────┬──────────┘
                                                │
                       ┌────────────────────────┼────────────────────────┐
                       ▼                        ▼                        ▼
               ┌──────────────┐        ┌────────────────┐       ┌────────────────┐
               │ SQLite / PG  │        │ AWS APIs       │       │ Provedores IA  │
               │ (Estado +    │        │ (boto3 /       │       │ OpenAI, Gemini │
               │  Snapshots)  │        │  AssumeRole)   │       │ Copilot, Local │
               └──────────────┘        └────────────────┘       └────────────────┘
```

### Stack Tecnológica
- **Backend**: Python, FastAPI, SQLAlchemy 2.x, Pydantic v2, APScheduler, `boto3`, `httpx`, `cryptography` (Fernet), `pyotp`, `passlib/bcrypt`, `weasyprint`.
- **Frontend**: React 18, TypeScript, Vite, React Router.
- **Banco de Dados**: SQLite (padrão local/simples) ou PostgreSQL (via `DOCOPS_DATABASE_URL`).
- **Deploy**: Docker Compose + Caddy (`docker-compose.yml`, `deploy/Caddyfile`, `install.sh`).

---

## 2. Estrutura do Repositório

```text
DocOps/
├── backend/
│   ├── app/
│   │   ├── main.py              # Inicialização FastAPI, middlewares, /api/collector.py, SPA static
│   │   ├── config.py            # Variáveis de ambiente (Settings)
│   │   ├── db.py                # Engine SQLAlchemy e SessionLocal
│   │   ├── models.py            # Tabelas ORM (User, Tenant, AwsAccount, Collection, Finding, etc.)
│   │   ├── security.py          # Hash de senha, sessões, CSRF, Fernet (encrypt/decrypt_secret)
│   │   ├── deps.py              # Dependências de auth, RBAC e contexto de tenant
│   │   ├── routers/
│   │   │   ├── auth.py          # Login, logout, troca de senha, MFA/TOTP
│   │   │   ├── tenants.py       # Gestão de clientes (tenants) e membros/papéis
│   │   │   ├── accounts.py      # Contas AWS, coletas (AssumeRole/upload), Diff A×B, agendamentos
│   │   │   ├── data.py          # Inventário (com Time-Travel), Achados, FinOps, Recálculo
│   │   │   ├── ai.py            # Configuração de IA, perguntas (/ask) e histórico (/history)
│   │   │   └── ops.py           # Configurações do tenant, alertas Teams, auditoria, PDF, AWS identity
│   │   └── services/
│   │       ├── collector.py     # Coletor AWS multi-região (fonte única: servidor e CloudShell)
│   │       ├── normalize.py     # Normalização de payloads v1/v2
│   │       ├── pipeline.py      # Ingestão de coletas, latest_collections, disparo de alertas
│   │       ├── findings.py      # Motor de regras de Segurança, Boas Práticas, FinOps e Well-Architected
│   │       ├── diff.py          # Comparação entre duas coletas (adicionados, removidos, alterados)
│   │       ├── alerts.py        # Notificações via Microsoft Teams (Adaptive Cards)
│   │       └── ai.py            # Montagem de contexto do inventário + clientes LLM
│   ├── tests/                   # Suite pytest (fixtures mock + testes de API)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx              # Rotas, contexto de autenticação e tenant
│       ├── api.ts               # Cliente HTTP, CSRF, downloadBlob, exportPdf
│       ├── ui.tsx               # Componentes de UI compartilhados
│       └── pages/
│           ├── Explorer.tsx     # Inventário interativo + Time-Travel + Relatório HTML/PDF
│           ├── FinOps.tsx       # Painel FinOps & Well-Architected + Exportar PDF
│           ├── AiAnalysis.tsx   # Chat IA Analisando + Histórico persistido + Exportar PDF
│           ├── Collections.tsx  # Execução, upload JSON, guia CloudShell e Diff A × B
│           ├── Accounts.tsx     # Cadastro de contas AWS (AssumeRole / ExternalId)
│           ├── Schedules.tsx    # Agendamentos recorrentes de coleta
│           ├── Alerts.tsx       # Webhook Teams e severidades de alerta
│           ├── Access.tsx       # Usuários e papéis do cliente
│           ├── Audit.tsx        # Trilha de auditoria
│           ├── Platform.tsx     # Administração global (superadmin)
│           └── MyAccount.tsx    # Senha e MFA do usuário logado
├── deploy/                      # Caddyfile e arquivos de deploy
├── scripts/                     # Scripts auxiliares e utilitários
├── docker-compose.yml
├── install.sh
├── DOCUMENTACAO.md              # Este documento
├── evolucao.md                  # Histórico contínuo de evolução da plataforma
└── proximospassos.md            # Roadmap de melhorias e expansão Multi-Cloud (Azure/GCP)
```

---

## 3. Modelo de Dados Principal

| Tabela | Descrição |
| :--- | :--- |
| `users` | Usuários da plataforma, hash de senha, flag `is_superadmin`, `totp_secret` (criptografado) e `mfa_enabled`. |
| `tenants` | Clientes isolados (nome, slug, cor, logo em data URL). |
| `memberships` | Vínculo usuário ↔ tenant com papel RBAC (`viewer`, `analyst`, `admin`). |
| `aws_accounts` | Contas AWS cadastradas por tenant (`account_id`, `alias`, `role_arn`, `external_id`, regiões). |
| `collections` | Snapshots coletados por conta (`payload` JSON em carregamento lazy/deferred, `diff`, status, timestamps). |
| `findings` | Achados consolidados por tenant/conta (Segurança, FinOps `COST05–COST08`, Well-Architected), com status `open`/`ack`. |
| `schedules` | Regras cron/intervalo para coletas automatizadas (APScheduler). |
| `tenant_settings` | Configurações de alerta (`teams_webhook` criptografado, severidades monitoradas). |
| `tenant_ai_configs` | Provedor LLM padrão do cliente, modelo, `base_url` e `api_key` (criptografada). |
| `ai_conversations` | Histórico persistido de conversas e respostas da aba **IA Analisando**. |
| `audit_logs` | Trilha de auditoria de ações administrativas, coletas, logins e exportações. |

---

## 4. Segurança e Controle de Acesso

- **RBAC por Tenant**:
  - `viewer`: visualiza Explorer, FinOps, histórico de coletas, Diff A × B, PDFs e consulta IA.
  - `analyst`: tudo de `viewer` + dispara coletas, sobe JSONs, recalcula achados, gerencia agendamentos e exclui histórico de IA.
  - `admin`: tudo de `analyst` + gerencia contas AWS, usuários do cliente, webhook Teams e chave de IA.
  - `superadmin`: administração global da plataforma (criação de tenants, usuários globais e auditoria da plataforma).
- **Autenticação & Proteções**:
  - Sessões via cookie `HttpOnly` + validação CSRF (`X-Requested-With`).
  - MFA via TOTP (Google Authenticator / Authy) com lockout progressivo após falhas consecutivas.
  - Rate limiting por IP em rotas sensíveis.
- **Criptografia em Repouso**:
  - Segredos sensíveis (`totp_secret`, `api_key`, `teams_webhook`) são cifrados com **Fernet (AES-128-CBC + HMAC-SHA256)** usando chave derivada via SHA-256 de `DOCOPS_SECRET_KEY`.
  - Prefixo `enc:` permite convivência segura com registros legados em texto plano durante migrações.
- **Isolamento na geração de PDF**:
  - WeasyPrint roda com `url_fetcher` restrito exclusivamente ao protocolo `data:`, bloqueando SSRF e carregamento de recursos externos.

---

## 5. Funcionalidades Principais

1. **Coleta AWS (Online e Offline)**:
   - **AssumeRole**: coleta automatizada a partir do servidor usando IAM Role somente leitura com `ExternalId` (onboarding assistido via `assumerole.html` e CloudFormation).
   - **CloudShell / Upload JSON**: download direto do coletor em `GET /api/collector.py`, execução no AWS CloudShell e upload do JSON no DocOps.
2. **Explorer & Time-Travel**:
   - Navegação interativa pelos recursos coletados (EC2, RDS, VPC, Subnets, Security Groups, S3, EKS/ECS, IAM, Lambda, etc.) com seletor de versão histórica por conta e geração de relatório completo HTML/PDF.
3. **Comparação de Coletas (Diff A × B)**:
   - Compara qualquer coleta base (A) com qualquer coleta alvo (B) da mesma conta, destacando recursos adicionados, removidos e alterados.
4. **FinOps & Well-Architected**:
   - Consolidação de gasto MTD, previsão mensal, economia estimada, volumes EBS `gp2`/órfãos, gerações antigas de EC2/RDS, recomendações de **Compute Optimizer**, **Savings Plans** e riscos do **AWS Well-Architected Tool**, com recálculo sob demanda e exportação em PDF.
5. **IA Analisando**:
   - Análise conversacional baseada no inventário real, achados e custos do cliente usando **Copilot**, **OpenRouter**, **Gemini**, **GPT** ou **LLM Local**.
   - Histórico salvo automaticamente no banco por cliente e exportação da conversa em PDF.
6. **Agendamentos & Alertas**:
   - Coletas periódicas automáticas e envio de alertas críticos/altos para o Microsoft Teams.

---

## 6. Principais Endpoints da API

| Grupo | Endpoints |
| :--- | :--- |
| **Auth** | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/mfa/*` |
| **Coletor** | `GET /api/collector.py` |
| **Contas & Coletas** | `GET/POST /api/tenants/{t}/accounts`, `GET /api/tenants/{t}/collections`, `POST /api/tenants/{t}/collections/upload`, `GET /api/tenants/{t}/collections/compare` |
| **Inventário & FinOps** | `GET /api/tenants/{t}/inventory`, `GET /api/tenants/{t}/findings`, `POST /api/tenants/{t}/findings/recompute`, `GET /api/tenants/{t}/finops` |
| **IA Analisando** | `GET/PUT /api/tenants/{t}/ai/config`, `POST /api/tenants/{t}/ai/ask`, `GET /api/tenants/{t}/ai/history`, `GET/DELETE /api/tenants/{t}/ai/history/{id}` |
| **Operações & PDF** | `GET/PUT /api/tenants/{t}/settings`, `POST /api/tenants/{t}/reports/pdf`, `GET /api/tenants/{t}/audit`, `GET /api/platform/aws-identity` |

---

## 7. Desenvolvimento, Testes e Build

### Backend
```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Executar testes automatizados:
```bash
cd backend
.venv/bin/pytest -q
```

### Frontend
```bash
cd frontend
npm install
npm run dev      # desenvolvimento
npm run build    # validação TypeScript + bundle de produção
```

### Produção (Docker Compose)
Configure o arquivo `.env` a partir de `.env.example` (definindo um `DOCOPS_SECRET_KEY` forte) e suba os serviços:
```bash
docker compose up -d --build
```
