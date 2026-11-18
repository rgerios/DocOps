# DocOps

**DocViva, documentação viva da infraestrutura de cloud** — agora como aplicação corporativa.

O DocOps coleta o inventário de contas AWS (VPCs, sub-redes, EC2, RDS, Security Groups, IAM, custos…), guarda o histórico de cada coleta, compara uma coleta com a anterior, aponta achados de segurança e avisa no Microsoft Teams. Cada cliente (tenant) tem as próprias contas, pessoas, perfis de acesso e documentação.

---

## Arquitetura

```
             navegador (HTTPS, certificado da CA interna)
                               │
                        ┌──────▼──────┐
                        │    proxy    │  Caddy · TLS · cabeçalhos de segurança
                        └──┬───────┬──┘
                  /api/*   │       │   demais rotas
                    ┌──────▼──┐ ┌──▼────────┐
                    │ backend │ │ frontend  │  React + TypeScript (nginx)
                    │ FastAPI │ │ + DocViva │
                    └──┬───┬──┘ └───────────┘
                       │   │ fila
              ┌────────▼┐ ┌▼──────┐   ┌──────────┐   ┌───────────┐
              │   db    │ │ redis │◄──┤  worker  │   │ scheduler │
              │Postgres │ └───────┘   │ (coletas)│   │  (cron)   │
              └────┬────┘             └────┬─────┘   └───────────┘
                   │                       │ sts:AssumeRole + ExternalId
              ┌────▼────┐                  ▼
              │ backup  │       contas AWS dos clientes (role somente leitura)
              │pg_dump  │
              └─────────┘
```

| Serviço     | Imagem / código          | Função |
|-------------|--------------------------|--------|
| `proxy`     | `caddy:2-alpine`         | Única porta exposta (80→443). TLS com CA interna, CSP, HSTS. |
| `frontend`  | `frontend/` (nginx)      | Aplicação React e o visualizador DocViva embutido. |
| `backend`   | `backend/` (FastAPI)     | API, login, perfis, auditoria, PDF. |
| `worker`    | mesma imagem do backend  | Executa as coletas AWS da fila (RQ). |
| `scheduler` | mesma imagem do backend  | Enfileira as coletas agendadas (expressões cron). |
| `db`        | `postgres:16-alpine`     | Banco de dados. |
| `redis`     | `redis:7-alpine`         | Fila de coletas. |
| `backup`    | `postgres:16-alpine`     | `pg_dump` diário no disco local, com retenção. |

Somente o `proxy` publica portas; os demais serviços ficam na rede interna do Docker.

---

## Instalação (Ubuntu 22.04 / 24.04)

Requisitos: 2 vCPU, 4 GB de RAM e 30 GB de disco, que atendem dezenas de contas. Portas 80 e 443 liberadas apenas para a rede interna.

```bash
git clone git@github.com:rgerios/DocOps.git
cd DocOps
sudo ./install.sh --host 10.0.10.25 --admin-email voce@empresa.com.br
```

O `install.sh`:

1. instala o Docker Engine e o Compose, se faltarem;
2. cria o `.env` com segredos aleatórios (só na primeira execução);
3. constrói e sobe os oito serviços;
4. mostra o endereço, o usuário e a **senha provisória** do primeiro administrador.

`--host` aceita IP e nomes separados por vírgula, por exemplo `"10.0.10.25, docops.empresa.local"`. Sem esse parâmetro, o script usa o IP principal da máquina.

Depois do primeiro login, remova a senha provisória do `.env`:

```bash
sudo sed -i 's|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=|' .env
```

### Certificado autoassinado

O Caddy emite o certificado a partir de uma CA interna. Para o navegador parar de alertar, exporte a CA e instale-a como **Autoridade de Certificação Raiz Confiável** nas máquinas dos usuários (manualmente, por GPO ou por MDM):

```bash
./scripts/export-ca.sh      # gera docops-root-ca.crt
```

Para usar o certificado da empresa, siga o comentário no topo de `deploy/caddy/Caddyfile`.

### Credenciais AWS do servidor

O servidor **não** lê nada diretamente com as próprias credenciais: ele apenas assume, em cada conta cliente, a role `DocVivaReadOnly`. A credencial do servidor só precisa desta permissão:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::*:role/DocVivaReadOnly"
  }]
}
```

**Servidor em EC2** (recomendado): anexe um *instance profile* com a política acima e deixe `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY` vazios no `.env`. Os contêineres estão a um salto de rede a mais da instância, então o IMDSv2 precisa de *hop limit* 2:

```bash
aws ec2 modify-instance-metadata-options --instance-id i-xxxxxxxx \
  --http-tokens required --http-put-response-hop-limit 2
```

**Servidor on-premises**: crie um usuário IAM só com a política acima e preencha `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY` no `.env`, depois rode `docker compose up -d`.

A conta do servidor é detectada automaticamente e já aparece preenchida nos comandos de criação da role (tela **Contas AWS → Como criar a role**). Se aparecer `CONTA_DO_SERVIDOR`, o servidor ainda não tem credencial AWS válida.

---

## Primeiros passos

1. **Primeiro acesso.** Entre com o e-mail e a senha provisória. A troca de senha é obrigatória; em seguida, ative o MFA em **Minha conta**.
2. **Criar o cliente.** Em **Plataforma → Clientes**, informe o nome do cliente. O logo e a cor do cliente ficam em **Acessos → Identidade do cliente** e aparecem no Explorer e nos relatórios.
3. **Cadastrar as contas AWS.** Em **Contas AWS → Adicionar conta**, informe o número da conta e um apelido. Ao salvar, o DocOps mostra os comandos para o cliente criar a role no CloudShell. A role:
   - usa a política gerenciada `ReadOnlyAccess`;
   - confia somente na conta do servidor;
   - exige um *ExternalId* exclusivo daquela conta.

   Depois que a role existir, clique em **Testar** e em seguida em **Coletar**.
4. **Contas sem role.** Rode `scripts/docviva_collector.py` na própria conta e importe o JSON em **Coletas → Importar arquivo do coletor**. Você pode enviar um arquivo por vez ou vários de uma vez.
5. **Agendar.** Em **Agendamentos**, crie, por exemplo, *Diária às 06:00*. Cada execução:
   - gera uma coleta nova;
   - compara com a anterior: novos, removidos e alterados;
   - dispara os alertas configurados.
6. **Configurar alertas.** Em **Alertas**, cole a URL do webhook do canal do Teams (Workflows → *Post to a channel when a webhook request is received*). Depois escolha:
   - as severidades de achados que geram alerta;
   - se falhas de coleta geram alerta;
   - se o resumo de mudanças é enviado a cada coleta.
7. **Dar acesso às pessoas.** Em **Acessos**, adicione as pessoas com o perfil adequado. A senha provisória aparece uma única vez; repasse-a por um canal seguro.

### Perfis

| Perfil | O que pode fazer |
|---|---|
| **Cliente** | Portal do cliente: só o Explorer, em leitura, sem as anotações internas. |
| **Leitor** | Consultar e exportar relatórios, sem alterar nada. |
| **Analista** | Disparar coletas, importar arquivos e editar anotações, documentação e tratativas de achados. |
| **Administrador** | Tudo no cliente: contas AWS, agendamentos, alertas, acessos e auditoria. |
| **Administrador da plataforma** | Todos os clientes, criação de clientes e usuários, redefinição de senha e de MFA. |

Os perfis valem por cliente: a mesma pessoa pode ser analista em um cliente e leitora em outro.

---

## Operação

| Tarefa | Comando |
|---|---|
| Ver status | `docker compose ps` |
| Logs | `docker compose logs -f backend worker` |
| Atualizar (git pull + rebuild, com backup antes) | `sudo ./scripts/update.sh` |
| Backup manual agora | `docker compose exec backup sh /scripts/backup.sh --once` |
| Restaurar | `sudo ./scripts/restore.sh backups/docops_AAAAMMDD_HHMM.dump` |
| Parar / subir | `docker compose down` / `docker compose up -d` |

**Backups.** O serviço `backup` grava `backups/docops_AAAAMMDD_HHMM.dump` todo dia na hora `BACKUP_HOUR` e apaga os arquivos mais antigos que `BACKUP_RETENTION_DAYS`. Faça também uma cópia periódica dessa pasta para fora do servidor (snapshot do volume EBS, por exemplo). O `.env` precisa ir junto: sem o `SECRET_KEY`, as sessões são invalidadas, e sem a `POSTGRES_PASSWORD` a restauração exige ajuste manual.

**Configuração** (`.env`): consulte os comentários em `.env.example`. Os parâmetros mais ajustados são:
- sessão: `SESSION_HOURS`;
- bloqueio por tentativas: `MAX_FAILED_LOGINS` e `LOCKOUT_MINUTES`;
- paralelismo da coleta: `COLLECTOR_WORKERS` e `COLLECTOR_INNER_WORKERS`;
- Cost Explorer: `COLLECTOR_COST_EXPLORER`.

---

## Segurança

- **Somente leitura na AWS.** A role é `ReadOnlyAccess` e o coletor **nunca** lê:
  - valores de segredos ou de parâmetros do SSM;
  - variáveis de ambiente de Lambda;
  - user-data;
  - objetos do S3.

  Apenas metadados são registrados.
- **Isolamento entre clientes.** O *ExternalId* é único por conta, o que evita o problema do *confused deputy*. Todas as rotas validam o cliente e o perfil no servidor.
- **Sessão.**
  - Senhas: hash com Argon2id.
  - Sessão: cookie `HttpOnly` + `SameSite=Strict`, com proteção CSRF por cabeçalho obrigatório.
  - Login: bloqueio após tentativas falhas.
  - MFA: TOTP opcional por usuário.
  - **Encerrar todas as sessões** invalida todos os tokens do usuário.
- **Auditoria.** Logins, coletas, importações, alterações de contas, de acessos, de anotações e de tratativas, além dos relatórios gerados, ficam registrados com pessoa, data e IP.
- **Superfície de rede.** Apenas o proxy expõe portas. A CSP bloqueia scripts externos, e o gerador de PDF não busca recursos externos.
- **Dados reais de clientes** não devem ser versionados. Os testes usam dados sintéticos.

---

## Desenvolvimento

```bash
# backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                                     # usa sqlite + redis em memória + moto
DATABASE_URL=sqlite:///dev.db REDIS_URL=memory:// COOKIE_SECURE=false \
  ADMIN_PASSWORD='Inicial#Docops2026' uvicorn app.main:app --reload

# frontend (outro terminal)
cd frontend
npm ci
npm run dev                                   # http://localhost:5173, /api vai para :8000
```

Com `REDIS_URL=memory://`, as coletas rodam de forma síncrona dentro da API, o que é útil para desenvolvimento.

### Estrutura

```
backend/app/
  routers/    auth, tenants (clientes/acessos), accounts (contas/coletas), data (inventário/achados/notas), ops (agendas/alertas/auditoria/PDF)
  services/   collector (coleta AWS), normalize, findings (regras de achados), diff, alerts (Teams), pipeline
  worker.py   scheduler.py
frontend/src/ pages/ (uma tela por menu), api.ts, ui.tsx
frontend/public/viewer/   DocViva em modo embutido (conversa com a aplicação via postMessage)
deploy/caddy/ scripts/ install.sh docker-compose.yml
```

O motor de achados existe em duas versões: Python, em `services/findings.py`, e JavaScript, no visualizador. As duas geram o **mesmo identificador** para cada achado, então as tratativas registradas na aplicação aparecem no Explorer e vice-versa. Ao alterar uma regra, altere nos dois lugares.

### Próximas expansões previstas

- Login corporativo (Entra ID / OIDC).
- Envio de alertas por e-mail.
- Portal do cliente com domínio próprio.
- Outros provedores de nuvem: a coleta é isolada em `services/collector.py` e o modelo de dados já separa conta, coleta e inventário.
