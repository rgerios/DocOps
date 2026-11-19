# DocOps — Próximos Passos & Roadmap Multi-Cloud

Este documento organiza as próximas melhorias da plataforma **DocOps** e o plano em fases para adicionar suporte a **Microsoft Azure** e **Google Cloud Platform (GCP)** mantendo compatibilidade total com o que já existe para AWS.

---

## Parte 1 — Melhorias Contínuas da Plataforma (Base)

Itens rápidos de evolução operacional, segurança e UX que fortalecem o produto antes ou em paralelo ao multi-cloud:

- [ ] **Migrations de banco (Alembic)**
  - Substituir alterações ad-hoc de schema no startup por migrations versionadas (importante antes de adicionar colunas/tabelas multi-cloud em produção).
- [ ] **Rotação / migração de segredos legados**
  - Comando CLI/script administrativo para re-criptografar registros antigos em texto plano (`totp_secret`, `api_key`, `teams_webhook`) usando `encrypt_secret()`.
- [ ] **Rate limiting & proteção de endpoints sensíveis**
  - Limitar tentativas de login, MFA (`/api/auth/login`, `/api/auth/mfa/*`) e chamadas de IA (`/api/tenants/{id}/ai/ask`).
- [ ] **Alertas enriquecidos (Slack / Webhook genérico / E-mail)**
  - Expandir `backend/app/services/alerts.py` além do Microsoft Teams para suportar Slack e webhook JSON genérico.
- [ ] **Filtros e busca global no Inventário / Explorer**
  - Busca cross-conta e cross-provedor por ID de recurso, tag, IP privado/público ou nome.
- [ ] **Agendamento com janela de manutenção e retry**
  - Retry automático em caso de throttling de APIs da nuvem e resumo consolidado por execução no histórico.

---

## Parte 2 — Roadmap Multi-Cloud (Azure & GCP)

Cerca de **60–70% da plataforma já é agnóstica de nuvem** (multi-tenancy, RBAC, MFA, criptografia em repouso, agendamentos, alertas, histórico, Diff A × B, PDF e IA Analisando). O plano abaixo divide a expansão em 3 fases independentes.

### Fase 1 — Fundação Multi-Cloud & Schema Canônico
Objetivo: preparar banco, API e UI para múltiplos provedores sem quebrar nenhuma coleta AWS existente.

- [ ] **Modelo de dados (`backend/app/models.py`)**
  - Adicionar `provider` (`"aws" | "azure" | "gcp"`, default `"aws"`) em `AwsAccount` (e em `Collection`, se útil para filtro rápido).
  - Adicionar campo JSON/criptografado para credenciais por provedor (`credentials_enc`) mantendo `role_arn`/`external_id` retrocompatíveis para AWS.
- [ ] **Schema Canônico (`backend/app/services/normalize.py`)**
  - Definir contrato normalizado comum consumido por `diff.py`, `findings.py`, `ai.py`, `FinOps` e `Explorer`:
    - `provider`, `account_id`, `account_alias`, `collected_at`
    - `compute` (VMs / EC2 / GCE)
    - `databases` (RDS / Azure SQL & Flexible Server / Cloud SQL)
    - `network` (VPC / VNet, Subnets, Firewalls/SG/NSG, Public IPs, NAT/Gateways, Load Balancers)
    - `storage` (S3 / Storage Accounts / GCS, Volumes/Disks, Snapshots)
    - `containers` (EKS/ECS / AKS/Container Apps / GKE/Cloud Run)
    - `iam` (Roles/Users/Service Principals/Service Accounts)
    - `finops` (gasto MTD, forecast, recomendações de rightsizing, reservas/SP/CUD, riscos de arquitetura)
    - `raw` (atributos específicos da nuvem preservados para detalhes e relatórios)
- [ ] **UI de Contas & Coletas (`Accounts.tsx`, `Collections.tsx`)**
  - Seletor de provedor (`AWS`, `Azure`, `GCP`) ao cadastrar conta e ao importar/executar coleta.
  - Badges de nuvem nas listagens, filtros por provedor no Explorer, FinOps e IA Analisando.

---

### Fase 2 — Suporte a Microsoft Azure (MVP)
Objetivo: entregar inventário, segurança, FinOps e IA para assinaturas Azure usando APIs unificadas.

- [ ] **Autenticação Azure**
  - Modo servidor: Service Principal (`tenant_id`, `subscription_id`, `client_id`, `client_secret` criptografado) com roles somente leitura (`Reader`, `Cost Management Reader`, `Security Reader`).
  - Modo desconectado: script Python para rodar no **Azure Cloud Shell** (autenticado via `DefaultAzureCredential` / `az login`) e exportar JSON para upload no DocOps.
  - Endpoint `GET /api/collector-azure.py` servindo a fonte única do coletor Azure.
- [ ] **Coletor Azure (`backend/app/services/collector_azure.py`)**
  - Usar **Azure Resource Graph (`azure-mgmt-resourcegraph`)** via KQL para coletar em poucas chamadas:
    - Virtual Machines & VMSS
    - VNets, Subnets, NSGs, Public IPs, Load Balancers, Application Gateways, NAT Gateways, VPN/ExpressRoute
    - Managed Disks (anexados e órfãos) & Snapshots
    - Storage Accounts (acesso público, HTTPS obrigatório, lifecycle, soft delete)
    - Azure SQL, PostgreSQL/MySQL Flexible Server, Cosmos DB
    - AKS & App Services / Functions
  - Integrar **Azure Advisor** (recomendações nativas de Custo, Segurança, Confiabilidade e Excelência Operacional — equivalente ao Compute Optimizer + Well-Architected).
  - Integrar **Azure Cost Management** (gasto MTD, forecast e breakdown por serviço/Resource Group).
- [ ] **Regras de Achados Azure (`backend/app/services/findings.py`)**
  - NSG expondo portas sensíveis (`22`, `3389`, bancos) para `*` / `0.0.0.0/0`
  - Storage Account com `allowBlobPublicAccess` habilitado ou sem `supportsHttpsTrafficOnly`
  - Managed Disks não anexados (`Unattached`) e Public IPs ociosos
  - VMs de gerações antigas e recomendações de rightsizing / Reserved Instances do Azure Advisor
  - Bancos sem backup/geo-redundância ou expostos publicamente
- [ ] **Testes automatizados com fixture mock Azure** em `backend/tests/`.

---

### Fase 3 — Suporte a Google Cloud Platform — GCP (MVP)
Objetivo: replicar o mesmo padrão de inventário, segurança, FinOps e IA para projetos GCP.

- [ ] **Autenticação GCP**
  - Modo servidor: Service Account JSON (criptografado em repouso) ou Workload Identity com roles somente leitura (`roles/viewer`, `roles/cloudasset.viewer`, `roles/recommender.viewer`, `roles/iam.securityReviewer`).
  - Modo desconectado: script Python para rodar no **GCP Cloud Shell** (via ADC / `gcloud auth application-default login`) e exportar JSON para upload.
  - Endpoint `GET /api/collector-gcp.py`.
- [ ] **Coletor GCP (`backend/app/services/collector_gcp.py`)**
  - Usar **Cloud Asset Inventory API (`google-cloud-asset`)** para inventário unificado:
    - Compute Engine (VMs, Instance Groups, Persistent Disks, Snapshots, Static IPs)
    - VPCs, Subnets, Firewall Rules, Cloud NAT, Cloud Load Balancing, Cloud VPN/Interconnect
    - Cloud SQL, Spanner, Memorystore
    - Cloud Storage (GCS Buckets, acesso público, UBLA, lifecycle)
    - GKE & Cloud Run / Cloud Functions
    - IAM Policies & Service Accounts (chaves gerenciadas pelo usuário)
  - Integrar **GCP Recommender API** (rightsizing de VMs, discos/IPs ociosos, Committed Use Discounts — CUDs).
  - Integrar resumo de billing (quando disponível via BigQuery Billing Export ou Billing API).
- [ ] **Regras de Achados GCP (`backend/app/services/findings.py`)**
  - Firewall Rules permitindo `0.0.0.0/0` em portas administrativas/banco
  - Buckets GCS públicos (`allUsers` / `allAuthenticatedUsers`) ou sem Uniform Bucket-Level Access / Lifecycle
  - Service Accounts com chaves JSON antigas ou roles amplas (`roles/owner`, `roles/editor`)
  - Discos persistentes não anexados, IPs estáticos sem uso e recomendações da Recommender API
  - Cloud SQL com IP público aberto (`0.0.0.0/0`) ou sem backup automático
- [ ] **Testes automatizados com fixture mock GCP** em `backend/tests/`.

---

## Parte 3 — Paridade Visual & IA Cross-Cloud

- [ ] **Explorer & Diagramas Multi-Cloud**
  - Adaptar rótulos e ícones no Explorer para exibir recursos equivalentes por provedor (`EC2 / Azure VM / GCE`, `VPC / VNet`, `S3 / Blob / GCS`, `RDS / Azure SQL / Cloud SQL`).
- [ ] **FinOps Unificado**
  - Consolidar gasto MTD, previsão e economia potencial por conta/assinatura/projeto com filtro por nuvem (`Todas | AWS | Azure | GCP`) e exportação PDF consolidada.
- [ ] **IA Analisando Cross-Cloud**
  - Incluir o resumo de contas AWS, Azure e GCP no contexto da IA, permitindo perguntas comparativas (ex.: *"Quais os maiores riscos críticos somando AWS e Azure?"* ou *"Onde está a maior economia rápida entre todas as nuvens?"*).

---

## Ordem Sugerida de Execução (Amanhã)

1. **Fase 1**: Fundação Multi-Cloud (`provider` + credenciais criptografadas + schema canônico + seletor na UI).
2. **Fase 2**: Coletor Azure (Resource Graph + Advisor) + regras de achados + fixture de teste.
3. **Fase 3**: Coletor GCP (Cloud Asset Inventory + Recommender) + regras de achados + fixture de teste.
4. **Polimento**: FinOps/IA cross-cloud + testes ponta a ponta + build & commit.
