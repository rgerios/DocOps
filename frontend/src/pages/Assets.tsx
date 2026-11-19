import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, Modal, PageHead, Pill, useLoad } from '../ui'

interface AssetItem {
  id: string
  name: string
  type: string
  accountId: string
  accountAlias: string
  region: string
  status: string
  statusKind: string
  spec: string
  tags: Record<string, string>
  findings: { id: string; sev: string; title: string; rec?: string; detail?: string }[]
}

interface AssetsRes {
  accounts: { accountId: string; accountAlias: string }[]
  total: number
  counts: Record<string, number>
  items: AssetItem[]
}

const PAGE_SIZE = 30

export default function Assets() {
  const { tenant } = useTenant()
  const [accountId, setAccountId] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<AssetItem | null>(null)

  const { data, error } = useLoad<AssetsRes>(
    () => api(`/api/tenants/${tenant.id}/assets${accountId !== 'all' ? `?account_id=${encodeURIComponent(accountId)}` : ''}`),
    [tenant.id, accountId],
  )

  useEffect(() => {
    setAccountId('all')
    setTypeFilter('all')
    setStatusFilter('all')
    setQ('')
    setPage(1)
  }, [tenant.id])

  useEffect(() => { setPage(1) }, [typeFilter, statusFilter, q, accountId])

  const filtered = useMemo(() => {
    const items = data?.items || []
    const qq = q.trim().toLowerCase()
    return items.filter((a) => {
      if (typeFilter !== 'all' && a.type !== typeFilter) return false
      if (statusFilter !== 'all' && a.status !== statusFilter) return false
      if (qq) {
        const tagStr = Object.entries(a.tags || {}).map(([k, v]) => `${k}=${v}`).join(' ')
        const hay = `${a.id} ${a.name} ${a.type} ${a.region} ${a.accountAlias} ${a.spec} ${tagStr}`.toLowerCase()
        if (!hay.includes(qq)) return false
      }
      return true
    })
  }, [data, typeFilter, statusFilter, q])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const slice = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const types = Object.entries(data?.counts || {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="page">
      <PageHead
        title="Infraestrutura & Assets"
        sub={`Inventário unificado de recursos AWS de ${tenant.name} com filtros por tipo, status operacional, tags e achados.`}
        actions={
          data && data.accounts.length > 1 ? (
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              style={{ width: 220 }}
              aria-label="Filtrar por conta AWS"
            >
              <option value="all">Todas as contas ({data.accounts.length})</option>
              {data.accounts.map((a) => (
                <option key={a.accountId} value={a.accountId}>{a.accountAlias}</option>
              ))}
            </select>
          ) : undefined
        }
      />

      <ErrorBox error={error} />

      {data && data.total > 0 && (
        <div className="chips">
          <button type="button" className={`chip ${typeFilter === 'all' ? 'on' : ''}`} onClick={() => setTypeFilter('all')}>
            Todos ({data.total})
          </button>
          {types.map(([t, cnt]) => (
            <button key={t} type="button" className={`chip ${typeFilter === t ? 'on' : ''}`} onClick={() => setTypeFilter(t)}>
              {t} ({cnt})
            </button>
          ))}
        </div>
      )}

      <Card
        title={`Recursos encontrados (${filtered.length})`}
        actions={
          <div className="row">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ width: 150 }}>
              <option value="all">Todos status</option>
              <option value="Ativo">Ativo</option>
              <option value="Atenção">Atenção</option>
              <option value="Órfão">Órfão</option>
              <option value="Ocioso/gp2">Ocioso/gp2</option>
              <option value="Parado">Parado</option>
            </select>
          </div>
        }
        pad={false}
      >
        <div className="pad">
          <input
            placeholder="Buscar por ID, nome, região, tag (ex.: env=prod) ou especificação…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        {!data ? (
          <div className="pad muted">Carregando recursos…</div>
        ) : data.total === 0 ? (
          <Empty title="Nenhum recurso coletado">
            Execute ou importe uma coleta em <b>Coletas</b> para visualizar o inventário de assets.
          </Empty>
        ) : filtered.length === 0 ? (
          <Empty title="Nenhum recurso corresponde aos filtros" />
        ) : (
          <>
            <table className="t compact">
              <thead>
                <tr>
                  <th>Tipo</th>
                  <th>Recurso / ID</th>
                  <th>Conta · Região</th>
                  <th>Especificação</th>
                  <th>Status</th>
                  <th className="num">Achados</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((a) => (
                  <tr key={`${a.accountId}-${a.type}-${a.id}`} className="click" onClick={() => setSelected(a)}>
                    <td><span className="tag">{a.type}</span></td>
                    <td>
                      <b>{a.name}</b>
                      {a.name !== a.id && <span className="sub mono">{a.id}</span>}
                    </td>
                    <td className="small">
                      {a.accountAlias}
                      <span className="sub mono">{a.region}</span>
                    </td>
                    <td className="small">{a.spec}</td>
                    <td><Pill kind={a.statusKind}>{a.status}</Pill></td>
                    <td className="num">
                      {a.findings.length > 0 ? <Pill kind="bad">{a.findings.length}</Pill> : <span className="na">0</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {totalPages > 1 && (
              <div className="pad row end">
                <span className="small muted">Página {page} de {totalPages}</span>
                <Btn small disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Anterior</Btn>
                <Btn small disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Próxima</Btn>
              </div>
            )}
          </>
        )}
      </Card>

      {selected && (
        <Modal title={`${selected.type} · ${selected.name}`} onClose={() => setSelected(null)} wide>
          <div className="kv-row">
            <div><span>ID do Recurso</span><b className="mono">{selected.id}</b></div>
            <div><span>Conta AWS</span><b>{selected.accountAlias} ({selected.accountId})</b></div>
            <div><span>Região</span><b className="mono">{selected.region}</b></div>
            <div><span>Status</span><Pill kind={selected.statusKind}>{selected.status}</Pill></div>
          </div>
          <div>
            <h4 className="sec">Especificação</h4>
            <p className="small" style={{ marginTop: 4 }}>{selected.spec}</p>
          </div>
          <div>
            <h4 className="sec">Tags ({Object.keys(selected.tags || {}).length})</h4>
            {Object.keys(selected.tags || {}).length ? (
              <div style={{ marginTop: 6 }}>
                {Object.entries(selected.tags).map(([k, v]) => (
                  <span key={k} className="tag">{k}={v}</span>
                ))}
              </div>
            ) : (
              <p className="small muted" style={{ marginTop: 4 }}>Nenhuma tag cadastrada neste recurso.</p>
            )}
          </div>
          <div>
            <h4 className="sec">Achados Abertos ({selected.findings.length})</h4>
            {selected.findings.length ? (
              <div className="rec-list" style={{ marginTop: 6 }}>
                {selected.findings.map((f) => (
                  <div key={f.id} className="rec-item">
                    <div className="rec-head">
                      <Pill kind={f.sev === 'critical' || f.sev === 'high' ? 'bad' : 'warn'}>{f.sev}</Pill>
                      <b>{f.title}</b>
                    </div>
                    {(f.rec || f.detail) && <p className="small muted">{f.rec || f.detail}</p>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="small muted" style={{ marginTop: 4 }}>Nenhum achado aberto para este recurso.</p>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}
