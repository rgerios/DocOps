import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, can, escHtml, exportPdf, fmtDT } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, PageHead, Pill, useLoad, useToast } from '../ui'

interface FinOpsData {
  computed_at: string | null
  summary: {
    accounts: number
    estimated_monthly_savings_usd: number
    mtd_cost_usd: number
    forecast_cost_usd: number
    gp2_volumes: number
    unattached_ebs: number
    unused_eips: number
    old_gen_ec2: number
    old_gen_rds: number
    s3_no_lifecycle: number
    old_snapshots: number
    nat_no_endpoint: number
    well_architected_risks: number
  }
  accounts: {
    account_id: string
    alias: string
    currency: string
    mtd: number | null
    forecast: number | null
    estimated_savings_usd: number
    co_count: number
    savings_plans: { estimated_monthly_savings_usd?: number; estimated_savings_pct?: number; type?: string } | null
    well_architected: { workload: string; lens: string; high: number; medium: number }[]
  }[]
  findings: {
    id: string
    sev: string
    cat: string
    title: string
    detail: string
    rec: string
    type: string
    account: string
    region: string
    resource: string
    status: string
  }[]
}

const SEV_PILL: Record<string, [string, string]> = {
  critical: ['Crítico', 'bad'],
  high: ['Alto', 'bad'],
  medium: ['Médio', 'warn'],
  low: ['Baixo', 'blue'],
  info: ['Info', 'idle'],
}

export default function FinOps() {
  const { tenant, role } = useTenant()
  const nav = useNavigate()
  const toast = useToast()
  const { data, error, setData } = useLoad<FinOpsData>(() => api(`/api/tenants/${tenant.id}/finops`), [tenant.id])
  const [busy, setBusy] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [cat, setCat] = useState<'all' | 'Custo' | 'Well-Architected'>('all')
  const [status, setStatus] = useState<'open' | 'all'>('open')
  const [q, setQ] = useState('')

  const exportFinOpsPdf = async () => {
    if (!data) return
    setPdfBusy(true)
    try {
      const brand = tenant.color || '#2563eb'
      const s0 = data.summary
      const accRows = data.accounts.map((a) => `<tr>
        <td><b>${escHtml(a.alias)}</b><br><small>${escHtml(a.account_id)}</small></td>
        <td>${a.mtd != null ? `US$ ${a.mtd}` : '—'}</td>
        <td>${a.forecast != null ? `US$ ${a.forecast}` : '—'}</td>
        <td><b>${a.estimated_savings_usd > 0 ? `US$ ${a.estimated_savings_usd}` : '—'}</b></td>
        <td>${a.co_count}</td>
        <td>${a.savings_plans?.estimated_monthly_savings_usd ? `US$ ${a.savings_plans.estimated_monthly_savings_usd} (${a.savings_plans.estimated_savings_pct ?? 0}%)` : '—'}</td>
      </tr>`).join('')
      const findRows = rows.slice(0, 120).map((f) => `<tr>
        <td><span class="sev ${escHtml(f.sev)}">${escHtml(SEV_PILL[f.sev]?.[0] || f.sev)}</span></td>
        <td>${escHtml(f.cat)}</td>
        <td><b>${escHtml(f.title)}</b><br><small>${escHtml(f.detail)}</small></td>
        <td>${escHtml(f.account)} · ${escHtml(f.region)}<br><small>${escHtml(f.resource)}</small></td>
        <td>${escHtml(f.rec)}</td>
      </tr>`).join('')
      const html = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
        @page { size: A4 landscape; margin: 14mm; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #0f172a; font-size: 10.5px; line-height: 1.45; }
        .hdr { border-left: 5px solid ${brand}; padding-left: 12px; margin-bottom: 16px; }
        .hdr h1 { margin: 0 0 4px; font-size: 18px; } .hdr p { margin: 0; color: #475569; }
        .kpis { display: flex; gap: 10px; margin-bottom: 16px; }
        .kpi { flex: 1; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 10px; background: #f8fafc; }
        .kpi span { display: block; font-size: 9px; color: #64748b; text-transform: uppercase; }
        .kpi b { font-size: 15px; color: #0f172a; }
        h2 { font-size: 13px; margin: 16px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
        th, td { border-bottom: 1px solid #e2e8f0; padding: 5px 6px; text-align: left; vertical-align: top; }
        th { background: #f1f5f9; font-size: 9.5px; text-transform: uppercase; color: #475569; }
        small { color: #64748b; }
        .sev { display: inline-block; padding: 1px 6px; border-radius: 10px; font-weight: 600; font-size: 9px; }
        .sev.critical, .sev.high { background: #fee2e2; color: #b91c1c; }
        .sev.medium { background: #fef3c7; color: #b45309; }
        .sev.low, .sev.info { background: #e0f2fe; color: #0369a1; }
      </style></head><body>
        <div class="hdr">
          <h1>Relatório FinOps &amp; Well-Architected — ${escHtml(tenant.name)}</h1>
          <p>Gerado em ${escHtml(fmtDT(new Date().toISOString()))}${data.computed_at ? ` · Base de achados: ${escHtml(fmtDT(data.computed_at))}` : ''}</p>
        </div>
        <div class="kpis">
          <div class="kpi"><span>Economia Estimada/mês</span><b>${s0.estimated_monthly_savings_usd > 0 ? `US$ ${s0.estimated_monthly_savings_usd}` : '—'}</b></div>
          <div class="kpi"><span>Gasto Atual (MTD)</span><b>${s0.mtd_cost_usd > 0 ? `US$ ${s0.mtd_cost_usd}` : '—'}</b></div>
          <div class="kpi"><span>Previsão Mês</span><b>${s0.forecast_cost_usd > 0 ? `US$ ${s0.forecast_cost_usd}` : '—'}</b></div>
          <div class="kpi"><span>EBS gp2 / Órfãos</span><b>${s0.gp2_volumes} / ${s0.unattached_ebs}</b></div>
          <div class="kpi"><span>Gerações Antigas</span><b>${s0.old_gen_ec2 + s0.old_gen_rds}</b></div>
          <div class="kpi"><span>Riscos Well-Architected</span><b>${s0.well_architected_risks}</b></div>
        </div>
        <h2>Resumo por Conta AWS (${data.accounts.length})</h2>
        <table><thead><tr><th>Conta</th><th>Gasto MTD</th><th>Previsão</th><th>Economia Est./mês</th><th>Compute Optimizer</th><th>Savings Plans</th></tr></thead><tbody>${accRows}</tbody></table>
        <h2>Plano de Ação FinOps &amp; Well-Architected (${rows.length} item(ns))</h2>
        <table><thead><tr><th>Sev.</th><th>Categoria</th><th>Achado</th><th>Recurso</th><th>Recomendação</th></tr></thead><tbody>${findRows}</tbody></table>
      </body></html>`
      await exportPdf(tenant.id, html, `FinOps_${tenant.slug || tenant.id}.pdf`)
      toast('PDF FinOps exportado')
    } catch (e: any) {
      toast(e.message, 'err')
    } finally {
      setPdfBusy(false)
    }
  }

  const recompute = async () => {
    setBusy(true)
    try {
      await api(`/api/tenants/${tenant.id}/findings/recompute`, { method: 'POST' })
      const fresh = await api<FinOpsData>(`/api/tenants/${tenant.id}/finops`)
      setData(fresh)
      toast('Achados FinOps & Well-Architected recalculados')
    } catch (e: any) {
      toast(e.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const s = data?.summary
  const rows = (data?.findings || []).filter((f) => {
    if (cat !== 'all' && f.cat !== cat) return false
    if (status === 'open' && f.status !== 'aberto') return false
    if (q && !`${f.title} ${f.resource} ${f.account} ${f.detail} ${f.rec}`.toLowerCase().includes(q.toLowerCase())) return false
    return true
  })

  return (
    <div className="page">
      <PageHead
        title="FinOps & Well-Architected"
        sub={`Alvos de otimização financeira (COST05–COST08), Compute Optimizer, Savings Plans e riscos do Well-Architected para ${tenant.name}.${data?.computed_at ? ` Atualizado em ${fmtDT(data.computed_at)}.` : ''}`}
        actions={<>
          {data && <Btn busy={pdfBusy} onClick={exportFinOpsPdf}>Exportar PDF</Btn>}
          <Btn onClick={() => nav(`/t/${tenant.id}/ia`)}>Analisar com IA</Btn>
          {can(role, 'analyst') && <Btn kind="primary" busy={busy} onClick={recompute}>Recalcular achados</Btn>}
        </>}
      />
      <ErrorBox error={error} />

      {s && (
        <div className="ai-kpis">
          <div className="kpi accent">
            <span>Economia estimada (AWS)</span>
            <b>{s.estimated_monthly_savings_usd > 0 ? `US$ ${s.estimated_monthly_savings_usd}` : '—'}</b>
            <small>Compute Optimizer + Savings Plans/mês</small>
          </div>
          <div className="kpi">
            <span>Gasto atual (MTD)</span>
            <b>{s.mtd_cost_usd > 0 ? `US$ ${s.mtd_cost_usd}` : '—'}</b>
            <small>{s.forecast_cost_usd > 0 ? `Previsão: US$ ${s.forecast_cost_usd}` : 'Cost Explorer'}</small>
          </div>
          <div className="kpi">
            <span>EBS gp2 → gp3</span>
            <b>{s.gp2_volumes}</b>
            <small>{s.unattached_ebs} volume(s) órfão(s)</small>
          </div>
          <div className="kpi">
            <span>Gerações antigas</span>
            <b>{s.old_gen_ec2 + s.old_gen_rds}</b>
            <small>{s.old_gen_ec2} EC2 · {s.old_gen_rds} RDS</small>
          </div>
          <div className="kpi">
            <span>S3 sem Lifecycle</span>
            <b>{s.s3_no_lifecycle}</b>
            <small>{s.old_snapshots} snapshot(s) &gt; 1 ano</small>
          </div>
          <div className="kpi">
            <span>Rede / IPs ociosos</span>
            <b>{s.nat_no_endpoint + s.unused_eips}</b>
            <small>{s.nat_no_endpoint} NAT sem Endpoint · {s.unused_eips} EIP(s)</small>
          </div>
        </div>
      )}

      {data && data.accounts.length > 0 && (
        <Card title="Resumo por conta" pad={false}>
          <table className="t compact">
            <thead><tr><th>Conta</th><th className="num">MTD</th><th className="num">Previsão</th><th className="num">Economia est./mês</th><th className="num">Compute Optimizer</th><th>Savings Plans</th><th>Well-Architected</th></tr></thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.account_id}>
                  <td><b>{a.alias}</b><span className="sub mono">{a.account_id}</span></td>
                  <td className="num">{a.mtd != null ? `${a.currency} ${a.mtd}` : '—'}</td>
                  <td className="num">{a.forecast != null ? `${a.currency} ${a.forecast}` : '—'}</td>
                  <td className="num">{a.estimated_savings_usd > 0 ? <Pill kind="ok">US$ {a.estimated_savings_usd}</Pill> : '—'}</td>
                  <td className="num">{a.co_count > 0 ? `${a.co_count} rec.` : '—'}</td>
                  <td className="small">{a.savings_plans?.estimated_monthly_savings_usd ? `~US$ ${a.savings_plans.estimated_monthly_savings_usd}/mês (${a.savings_plans.estimated_savings_pct}%)` : '—'}</td>
                  <td className="small">{a.well_architected.length ? a.well_architected.map((w) => `${w.workload}: ${w.high}A/${w.medium}M`).join(' · ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card
        title={`Alvos de melhoria financeira (${rows.length})`}
        actions={
          <div className="row">
            <select value={cat} onChange={(e) => setCat(e.target.value as any)} style={{ width: 170 }}>
              <option value="all">Todas categorias</option>
              <option value="Custo">Custo (FinOps)</option>
              <option value="Well-Architected">Well-Architected</option>
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value as any)} style={{ width: 140 }}>
              <option value="open">Abertos</option>
              <option value="all">Todos status</option>
            </select>
          </div>
        }
        pad={false}
      >
        <div className="pad"><input placeholder="Filtrar por controle (COST06), recurso, conta ou recomendação…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        {!data ? (
          <div className="pad muted">Carregando…</div>
        ) : !s?.accounts ? (
          <Empty title="Nenhuma coleta disponível">Faça ou importe ao menos uma coleta em <b>Coletas</b> para analisar os alvos financeiros.</Empty>
        ) : !rows.length ? (
          <Empty title="Nenhum alvo encontrado">
            Se você acabou de atualizar o sistema, clique em <b>Recalcular achados</b> acima para aplicar as regras FinOps sobre a coleta atual.
          </Empty>
        ) : (
          <table className="t compact">
            <thead><tr><th>Severidade</th><th>Alvo / Controle</th><th>Recurso</th><th>Conta · Região</th><th>Recomendação</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((f) => {
                const [sl, sk] = SEV_PILL[f.sev] || [f.sev, 'idle']
                return (
                  <tr key={f.id}>
                    <td><Pill kind={sk}>{sl}</Pill></td>
                    <td><b>{f.title}</b>{f.detail && <span className="sub">{f.detail}</span>}</td>
                    <td className="small mono">{f.resource}</td>
                    <td className="small">{f.account}<span className="sub">{f.region}</span></td>
                    <td className="small">{f.rec}</td>
                    <td><Pill kind={f.status === 'aberto' ? 'warn' : 'ok'}>{f.status}</Pill></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
