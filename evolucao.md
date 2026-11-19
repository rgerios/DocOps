# DocOps — Registro de Evolução da Plataforma

> **Regra de manutenção:** A cada ajuste, nova funcionalidade ou commit relevante no repositório, este documento deve ser atualizado com data, commit (ou referência), resumo das mudanças e arquivos principais afetados.

---

## Histórico de Evolução

### 2026-11-19 — Rollback do Redesign na `main` e Fluxo de Branches `hml` → `main`
- **UI / Rollback**:
  - Restaurado o visual original de PRD (`frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/src/pages/FinOps.tsx` do commit `4d15a3d`) na branch `main`, mantendo a estrutura de containers HML/PRD (`docker-compose.hml.yml`, `scripts/deploy.sh`) e a documentação.
- **Fluxo de Deploy**:
  - Criada branch dedicada `hml` para testar novas ideias de UI e funcionalidades em homologação (`https://10.10.1.218:8443`) antes de promover para `main` (PRD).
- **Verificação**:
  - `npm run build` (`tsc -b && vite build`) validado com sucesso (0 erros).

---

### 2026-11-19 — Ambiente Isolado de HML + CLI de Deploy/Rollback
- **Infraestrutura / Docker Compose (`docker-compose.hml.yml`, `deploy/caddy/Caddyfile.hml`, `.env.hml.example`)**:
  - Criada stack completa de Homologação (`name: docops-hml`) 100% isolada de PRD (imagens `docops-hml-*`, banco `docops_hml`, volumes `*_hml`, rede própria e portas `8080` HTTP / `8443` HTTPS).
  - Caddyfile dedicado (`deploy/caddy/Caddyfile.hml`) redirecionando HTTP `8080` explicitamente para `https://{host}:8443` (evitando redirecionar para a porta `443` de PRD).
- **Automação de Deploy e Rollback (`scripts/deploy.sh`)**:
  - Comandos unificados: `./scripts/deploy.sh hml [--pull]`, `./scripts/deploy.sh prd [--pull]`, `./scripts/deploy.sh status`, `./scripts/deploy.sh stop-hml`, `./scripts/deploy.sh clone-prd-to-hml` e `./scripts/deploy.sh rollback <hml|prd> <commit_ou_tag>`.
  - Geração automática de `.env.hml` na primeira execução (reaproveitando `DOCOPS_HOST` e `SECRET_KEY` de PRD quando presente, permitindo clonar o banco de PRD para HML com descriptografia Fernet íntegra).
  - Adicionados `.env.hml` e `backups-hml/` ao `.gitignore`.

---

### 2026-11-19 — Redesign Enterprise Light da Interface via Google Stitch MCP
- **Design System (`DocOps Enterprise Light`)**:
  - Criado projeto `DocOps Redesign` e design system `DocOps Enterprise Light` no Google Stitch MCP com telas de referência (`FinOps & Custos`, `Explorer`, `Infraestrutura & Assets`).
  - Reescrito `frontend/src/styles.css` adotando superfícies claras limpas (`#f8f9fa` / `#ffffff`), hairline borders (`#e4e7ec`), acento sóbrio verde G3 (`#125228` / `#2e6b3e`), tipografia `Inter` + `JetBrains Mono` com números tabulares (`tabular-nums`), removendo sombras pesadas e gradientes genéricos.
- **Nova Navegação & Layout (`frontend/src/App.tsx`)**:
  - Substituído o header horizontal denso por **Sidebar fixa à esquerda (`244px`)** com seletor de cliente integrado, navegação agrupada (**Principal**, **Operação**, **Governança**, **Plataforma**), ícones SVG minimalistas inline, menu do usuário no rodapé e drawer responsivo para telas menores (`< 960px`).
  - Adicionada **Topbar limpa (`52px`)** com breadcrumb dinâmico (`Cliente / Página`) e badge de perfil.
  - Redesenhada a tela de **Login / Troca de Senha** em split-screen arquitetural (`#0d1d14` com grade técnica sutil à esquerda e formulário limpo à direita).
- **FinOps (`frontend/src/pages/FinOps.tsx`)**:
  - Destaque semântico verde (`kpi accent`) no card de Economia Estimada (AWS).
- **Verificação**:
  - `npm run build` (`tsc -b && vite build`) validado com sucesso (0 erros).

---

### 2026-11-19 — Segurança em Repouso, Performance, Diff A × B, Histórico de IA e Exportação PDF (`4d15a3d`)
- **Criptografia em repouso (Fernet / `cryptography`)**:
  - Implementadas `encrypt_secret()` e `decrypt_secret()` derivadas de `DOCOPS_SECRET_KEY`, com fallback transparente para valores legados em texto plano (`backend/app/security.py`).
  - Protegidos no banco: `User.totp_secret`, `TenantAIConfig.api_key` e `TenantSetting.teams_webhook`.
- **Otimização de performance (`latest_collections`)**:
  - Reescrita da consulta em `backend/app/services/pipeline.py` para buscar apenas o `MAX(id)` mais recente por conta, eliminando varredura completa do histórico e carregamento desnecessário do JSON (`undefer(Collection.payload)` só quando `with_payload=True`).
- **Fonte única do coletor**:
  - Novo endpoint `GET /api/collector.py` servindo diretamente `backend/app/services/collector.py`.
  - Removida a cópia duplicada `frontend/public/docviva_collector.py` e atualizados os links de download na aba **Coletas**.
- **Comparar Coletas (Diff A × B)**:
  - Novo endpoint `GET /api/tenants/{tenant_id}/collections/compare?base_id=&target_id=` (`backend/app/routers/accounts.py`).
  - Modal interativo **Comparar (A × B)** com filtro por tipo/texto em `frontend/src/pages/Collections.tsx`.
- **Histórico persistido de análises com IA**:
  - Nova tabela `ai_conversations` (`backend/app/models.py`) e endpoints `GET /ai/history`, `GET /ai/history/{id}` e `DELETE /ai/history/{id}` (`backend/app/routers/ai.py`).
  - Painel **Histórico de análises** em `frontend/src/pages/AiAnalysis.tsx` para retomar ou excluir conversas anteriores.
- **Exportação PDF em FinOps e IA Analisando**:
  - Helper reutilizável `exportPdf()` em `frontend/src/api.ts` usando `POST /api/tenants/{tenant_id}/reports/pdf` (WeasyPrint).
  - Botões **Exportar PDF** adicionados em `FinOps.tsx` e `AiAnalysis.tsx`.
- **Testes**:
  - +4 novos testes automatizados em `backend/tests/test_api.py` (total: **18 testes passando**).

---

### 2026-11-18 — Aba FinOps & Custos e Recálculo de Achados (`3fd8481`)
- Criada aba dedicada **FinOps & Custos** (`frontend/src/pages/FinOps.tsx`) com KPIs de economia estimada/mês, gasto MTD, previsão, volumes `gp2`/órfãos, gerações antigas e riscos Well-Architected.
- Adicionado endpoint `GET /api/tenants/{tenant_id}/finops` e botão **Recalcular achados** (`POST /api/tenants/{tenant_id}/findings/recompute`) para reprocessar regras sem precisar recoletar na AWS.

---

### 2026-11-18 — Coleta FinOps / Well-Architected & Regras COST05–COST08 (`0509d16`)
- Expandido `collector.py` para coletar recomendações do **AWS Compute Optimizer** (EC2, EBS, Lambda), **Savings Plans** e riscos do **AWS Well-Architected Tool**.
- Adicionadas regras `COST05` a `COST08` no motor de achados (`backend/app/services/findings.py`) cobrindo `gp2 → gp3`, lifecycle de S3, Compute Optimizer, Savings Plans e workloads com riscos Well-Architected.

---

### 2026-11-18 — Versionamento por Levantamento / Time-Travel (`599dd84`)
- Adicionado suporte a seleção de coleta histórica (`?collection_id=`) no endpoint `/api/tenants/{tenant_id}/inventory`.
- Adicionado seletor de versão por conta no **Explorer** e atalho direto na aba **Coletas** para navegar em snapshots antigos do ambiente.

---

### 2026-11-18 — Guia AWS CloudShell & Download do Coletor (`025beb4`)
- Adicionado guia passo a passo na aba **Coletas** para execução do coletor diretamente no **AWS CloudShell** em contas sem AssumeRole configurado, com botão de download e upload do JSON gerado.

---

### 2026-11-18 — Correção TLS sem SNI no Caddy (`2204a79`)
- Configurado `default_sni` no `Caddyfile` (`deploy/Caddyfile`) para permitir handshake HTTPS em acessos diretos por endereço IP.

---

### 2026-11-18 — Aba IA Analisando Multi-Provedor (`c4f8fc4`)
- Criada aba **IA Analisando** (`frontend/src/pages/AiAnalysis.tsx` + `backend/app/routers/ai.py` + `backend/app/services/ai.py`) com suporte a **GitHub Copilot**, **OpenRouter**, **Google Gemini**, **OpenAI GPT** e **LLM Local** (Ollama/OpenAI-compatible).
- Contexto montado automaticamente a partir do inventário real, achados de segurança e métricas FinOps do cliente.

---

### 2026-11-18 — Onboarding AWS com AssumeRole & CloudFormation (`02162c7`)
- Adicionado assistente `assumerole.html` e template CloudFormation pronto para criação da IAM Role somente leitura com `ExternalId` nas contas dos clientes.

---

### 2026-11-18 — Hardening de Segurança, UX e CI (`9c7ed75`, `4e74fa1`)
- Adicionado lockout no MFA após tentativas inválidas, rate limiting por IP, validação obrigatória de `DOCOPS_SECRET_KEY` forte em produção, modal de confirmação para ações destrutivas, retry automático no Explorer e pipeline de CI no GitHub Actions.
- Adicionado `.venv` ao `.gitignore`.

---

### 2026-11-18 — Fundação do DocOps (`b6f21c1`)
- Criação da aplicação corporativa multi-tenant **DocOps** (FastAPI + SQLAlchemy + React/Vite/TypeScript + Docker Compose + Caddy):
  - Multi-tenancy, autenticação com sessão segura, RBAC (`superadmin`, `admin`, `analyst`, `viewer`) e MFA (TOTP).
  - Coleta AWS multi-região (AssumeRole + upload JSON), Explorer interativo, motor de achados de segurança/boas práticas, Diff entre coletas, agendamentos (APScheduler), alertas no Microsoft Teams, trilha de auditoria e geração de relatório PDF (WeasyPrint).

---

## Modelo para Próximas Entradas

```markdown
### AAAA-MM-DD — Título curto da mudança (`<hash>`)
- **Categoria (Segurança / Feature / Performance / Fix)**:
  - Descrição objetiva do que foi alterado e quais arquivos/endpoints foram impactados.
- **Verificação**:
  - Testes automatizados executados e resultado do build.
```
