import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmtDT } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, PageHead, Pill, useLoad } from '../ui'

interface PillarService {
  name: string
  detected: boolean
  count: number
  badge: string
  badgeKind: string
}

interface PillarRec {
  title: string
  sev: string
  detail: string
  action: string
  targetRoute: string
}

interface Pillar {
  id: string
  name: string
  shortName: string
  score: number
  benchmark: number
  delta: number
  status: 'high' | 'moderate' | 'suboptimal' | 'critical'
  resourceCount: number
  openFindings: number
  services: PillarService[]
  recommendations: PillarRec[]
}

interface LayerNode {
  name: string
  count: number
  active: boolean
}

interface OverviewData {
  hasData: boolean
  computedAt: string | null
  accountId: string
  accountAlias: string
  overallScore: number
  benchmarkAverage: number
  accounts: { accountId: string; accountAlias: string; overallScore: number }[]
  summary: {
    accounts: number
    regionsActive: number
    totalResources: number
    openFindings: number
    criticalFindings: number
    mtdCostUsd: number
    estimatedMonthlySavingsUsd: number
  }
  pillars: Pillar[]
  layers: {
    core: LayerNode[]
    governance: LayerNode[]
    ecosystem: LayerNode[]
  }
  insights: { kind: string; title: string; detail: string; route: string; cta: string }[]
}

const STATUS_META: Record<string, { label: string; kind: string; color: string }> = {
  high: { label: 'Maduro', kind: 'ok', color: '#24804f' },
  moderate: { label: 'Moderado', kind: 'blue', color: '#2f6fc0' },
  suboptimal: { label: 'Subótimo', kind: 'warn', color: '#b45309' },
  critical: { label: 'Crítico', kind: 'bad', color: '#a8202a' },
}

const SEV_KIND: Record<string, string> = {
  critical: 'bad',
  high: 'bad',
  medium: 'warn',
  low: 'blue',
  info: 'idle',
}

function polar(cx: number, cy: number, r: number, index: number, total: number): [number, number] {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / total
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
}

function RadarChart({
  pillars,
  selectedId,
  onSelect,
  showBenchmark = false,
}: {
  pillars: Pillar[]
  selectedId: string
  onSelect: (id: string) => void
  showBenchmark?: boolean
}) {
  const size = 460
  const cx = size / 2
  const cy = size / 2
  const maxR = 148
  const n = pillars.length || 8
  const rings = [25, 50, 75, 100]

  const scorePoints = pillars
    .map((p, i) => polar(cx, cy, (Math.max(8, p.score) / 100) * maxR, i, n).join(','))
    .join(' ')

  const benchPoints = pillars
    .map((p, i) => polar(cx, cy, (p.benchmark / 100) * maxR, i, n).join(','))
    .join(' ')

  return (
    <div className="radar-wrap">
      <svg viewBox={`0 0 ${size} ${size}`} className="radar-svg" role="img" aria-label="Radar de maturidade por pilar AWS">
        {/* anéis poligonais de grade */}
        {rings.map((pct) => {
          const pts = Array.from({ length: n }, (_, i) => polar(cx, cy, (pct / 100) * maxR, i, n).join(',')).join(' ')
          return (
            <g key={pct}>
              <polygon points={pts} className="radar-grid" />
              <text x={cx + 4} y={cy - (pct / 100) * maxR + 3} className="radar-tick">
                {pct}%
              </text>
            </g>
          )
        })}

        {/* eixos radiais */}
        {pillars.map((p, i) => {
          const [x2, y2] = polar(cx, cy, maxR, i, n)
          const isSel = p.id === selectedId
          return <line key={p.id} x1={cx} y1={cy} x2={x2} y2={y2} className={`radar-axis ${isSel ? 'sel' : ''}`} />
        })}

        {/* malha pontilhada de benchmark */}
        {showBenchmark && <polygon points={benchPoints} className="radar-bench" />}

        {/* polígono real da conta */}
        <polygon points={scorePoints} className="radar-poly" />

        {/* vértices clicáveis e rótulos */}
        {pillars.map((p, i) => {
          const [vx, vy] = polar(cx, cy, (Math.max(8, p.score) / 100) * maxR, i, n)
          const [lx, ly] = polar(cx, cy, maxR + 34, i, n)
          const isSel = p.id === selectedId
          const st = STATUS_META[p.status] || STATUS_META.moderate
          const anchor = lx < cx - 22 ? 'end' : lx > cx + 22 ? 'start' : 'middle'
          return (
            <g key={p.id} className="radar-node" onClick={() => onSelect(p.id)}>
              {isSel && <circle cx={vx} cy={vy} r={11} fill={st.color} opacity={0.18} />}
              <circle cx={vx} cy={vy} r={isSel ? 6.5 : 5} fill={st.color} stroke="#fff" strokeWidth={2} />
              <text x={lx} y={ly - 4} textAnchor={anchor} className={`radar-lbl ${isSel ? 'sel' : ''}`}>
                {p.shortName}
              </text>
              <text x={lx} y={ly + 11} textAnchor={anchor} className="radar-val" fill={st.color}>
                {p.score}%
              </text>
            </g>
          )
        })}
      </svg>
      <div className="radar-legend">
        <span><i className="leg-dot real" /> Conta atual</span>
        {showBenchmark && <span><i className="leg-dot bench" /> Benchmark de mercado</span>}
        <span className="muted small">Clique em qualquer vértice para inspecionar</span>
      </div>
    </div>
  )
}

function ConcentricDiagram({
  alias,
  overallScore,
  layers,
  pillars,
  selectedId,
  onSelect,
}: {
  alias: string
  overallScore: number
  layers: OverviewData['layers']
  pillars: Pillar[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const size = 460
  const cx = size / 2
  const cy = size / 2
  const ringDefs = [
    { key: 'ecosystem' as const, r: 178, label: 'Ecossistema & Borda', items: layers.ecosystem },
    { key: 'governance' as const, r: 126, label: 'Governança & FinOps', items: layers.governance },
    { key: 'core' as const, r: 74, label: 'Core AWS', items: layers.core },
  ]
  const n = pillars.length || 8
  const benchPts = pillars.map((p, i) => polar(cx, cy, (p.benchmark / 100) * 178, i, n).join(',')).join(' ')
  const scorePts = pillars.map((p, i) => polar(cx, cy, (Math.max(12, p.score) / 100) * 178, i, n).join(',')).join(' ')

  return (
    <div className="radar-wrap">
      <svg viewBox={`0 0 ${size} ${size}`} className="radar-svg" role="img" aria-label="Diagrama concêntrico de camadas e benchmark">
        {/* 3 anéis concêntricos */}
        {ringDefs.map((rd, idx) => (
          <g key={rd.key}>
            <circle cx={cx} cy={cy} r={rd.r} className={`conc-ring r${idx}`} />
            <text x={cx} y={cy - rd.r + 14} textAnchor="middle" className="conc-ring-lbl">
              {rd.label}
            </text>
          </g>
        ))}

        {/* eixos dos 8 pilares */}
        {pillars.map((p, i) => {
          const [x2, y2] = polar(cx, cy, 184, i, n)
          return <line key={p.id} x1={cx} y1={cy} x2={x2} y2={y2} className="radar-axis" />
        })}

        {/* benchmark pontilhado + cobertura real */}
        <polygon points={benchPts} className="radar-bench" />
        <polygon points={scorePts} className="radar-poly" />

        {/* pontos dos nós nos anéis */}
        {ringDefs.map((rd) =>
          rd.items.map((node, idx) => {
            const [nx, ny] = polar(cx, cy, rd.r, idx, rd.items.length)
            return (
              <g key={`${rd.key}-${node.name}`}>
                <circle
                  cx={nx}
                  cy={ny}
                  r={4.5}
                  fill={node.active ? 'var(--brand-600)' : '#cbd5e1'}
                  stroke="#fff"
                  strokeWidth={1.5}
                />
                <title>{`${node.name}: ${node.active ? `${node.count} ativo(s)` : 'Não detectado'}`}</title>
              </g>
            )
          })
        )}

        {/* rótulos dos 8 pilares na borda */}
        {pillars.map((p, i) => {
          const [lx, ly] = polar(cx, cy, 206, i, n)
          const isSel = p.id === selectedId
          const anchor = lx < cx - 20 ? 'end' : lx > cx + 20 ? 'start' : 'middle'
          return (
            <text
              key={p.id}
              x={lx}
              y={ly + 3}
              textAnchor={anchor}
              className={`radar-lbl ${isSel ? 'sel' : ''}`}
              style={{ cursor: 'pointer' }}
              onClick={() => onSelect(p.id)}
            >
              {p.shortName}
            </text>
          )
        })}

        {/* núcleo central */}
        <circle cx={cx} cy={cy} r={34} className="conc-core" />
        <text x={cx} y={cy - 2} textAnchor="middle" className="conc-score">{overallScore}%</text>
        <text x={cx} y={cy + 13} textAnchor="middle" className="conc-sub">
          {alias.length > 12 ? `${alias.slice(0, 11)}…` : alias}
        </text>
      </svg>
      <div className="radar-legend">
        <span><i className="leg-dot real" /> Maturidade da conta</span>
        <span><i className="leg-dot bench" /> Benchmark setorial</span>
        <span><i className="leg-dot node-on" /> Serviço detectado</span>
        <span><i className="leg-dot node-off" /> Não detectado</span>
      </div>
    </div>
  )
}

export default function Panorama() {
  const { tenant } = useTenant()
  const nav = useNavigate()
  const [accountId, setAccountId] = useState<string>('all')
  const [tab, setTab] = useState<'raiox' | 'benchmark'>('raiox')
  const [selectedPillarId, setSelectedPillarId] = useState<string>('security')

  const { data, error } = useLoad<OverviewData>(
    () => api(`/api/tenants/${tenant.id}/overview${accountId !== 'all' ? `?account_id=${encodeURIComponent(accountId)}` : ''}`),
    [tenant.id, accountId],
  )

  useEffect(() => {
    setAccountId('all')
  }, [tenant.id])

  useEffect(() => {
    if (!data?.pillars?.length) return
    if (!data.pillars.some((p) => p.id === selectedPillarId)) {
      const weakest = [...data.pillars].sort((a, b) => a.score - b.score)[0]
      if (weakest) setSelectedPillarId(weakest.id)
    }
  }, [data, selectedPillarId])

  const selected = data?.pillars?.find((p) => p.id === selectedPillarId) || data?.pillars?.[0]
  const selMeta = selected ? (STATUS_META[selected.status] || STATUS_META.moderate) : STATUS_META.moderate

  return (
    <div className="page">
      <PageHead
        title="Panorama Geral"
        sub={`Visão executiva 360° de maturidade, assimetria dos 8 pilares AWS e benchmark setorial para ${tenant.name}.${data?.computedAt ? ` Base atualizada em ${fmtDT(data.computedAt)}.` : ''}`}
        actions={
          <div className="row">
            {data && data.accounts.length > 1 && (
              <select
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                style={{ width: 220 }}
                aria-label="Filtrar por conta AWS"
              >
                <option value="all">Todas as contas ({data.accounts.length})</option>
                {data.accounts.map((a) => (
                  <option key={a.accountId} value={a.accountId}>
                    {a.accountAlias} ({a.overallScore}%)
                  </option>
                ))}
              </select>
            )}
            <Btn onClick={() => nav(`/t/${tenant.id}/assets`)}>Ver Assets</Btn>
            <Btn kind="primary" onClick={() => nav(`/t/${tenant.id}/ia`)}>Analisar com IA</Btn>
          </div>
        }
      />

      <ErrorBox error={error} />

      <div className="subnav">
        <a
          href="#raiox"
          className={tab === 'raiox' ? 'active' : ''}
          onClick={(e) => { e.preventDefault(); setTab('raiox') }}
        >
          Raio-X da Conta (Distribuição Real)
        </a>
        <a
          href="#benchmark"
          className={tab === 'benchmark' ? 'active' : ''}
          onClick={(e) => { e.preventDefault(); setTab('benchmark') }}
        >
          Benchmark Setorial &amp; Camadas Concêntricas
        </a>
      </div>

      {!data ? (
        <Card><div className="muted">Carregando panorama da infraestrutura…</div></Card>
      ) : !data.hasData ? (
        <Card>
          <Empty title="Nenhuma coleta disponível para o Panorama Geral">
            Execute ou importe ao menos uma coleta em <b>Coletas</b> para calcular o Raio-X dos 8 pilares da conta AWS.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="ai-kpis">
            <div className="kpi">
              <span>Score Geral de Maturidade</span>
              <b>{data.overallScore}<span className="kpi-unit">/100</span></b>
              <small>Ref. de mercado: {data.benchmarkAverage}/100 · {data.accountAlias}</small>
            </div>
            <div className="kpi">
              <span>Recursos Mapeados</span>
              <b>{data.summary.totalResources}</b>
              <small>{data.summary.accounts} conta(s) · {data.summary.regionsActive} região(ões)</small>
            </div>
            <div className="kpi">
              <span>Achados Abertos</span>
              <b>{data.summary.openFindings}</b>
              <small>{data.summary.criticalFindings} Crítico / Alto</small>
            </div>
            <div className="kpi">
              <span>Gasto MTD / Economia Est.</span>
              <b>{data.summary.mtdCostUsd > 0 ? `US$ ${data.summary.mtdCostUsd}` : '—'}</b>
              <small>
                {data.summary.estimatedMonthlySavingsUsd > 0
                  ? `Economia est.: US$ ${data.summary.estimatedMonthlySavingsUsd}/mês`
                  : 'Cost Explorer / Compute Optimizer'}
              </small>
            </div>
          </div>

          {tab === 'raiox' ? (
            <div className="pano-grid">
              <Card
                title={`Raio-X de Assimetria · ${data.accountAlias}`}
                actions={<Pill kind={data.overallScore >= 75 ? 'ok' : data.overallScore >= 55 ? 'warn' : 'bad'}>Score {data.overallScore}/100</Pill>}
              >
                <RadarChart
                  pillars={data.pillars}
                  selectedId={selected?.id || ''}
                  onSelect={setSelectedPillarId}
                />
                <div className="pillar-strip">
                  {data.pillars.map((p) => {
                    const sm = STATUS_META[p.status] || STATUS_META.moderate
                    const active = p.id === selected?.id
                    return (
                      <button
                        key={p.id}
                        type="button"
                        className={`pillar-pill ${active ? 'active' : ''}`}
                        onClick={() => setSelectedPillarId(p.id)}
                      >
                        <span className="pp-name">{p.shortName}</span>
                        <b style={{ color: sm.color }}>{p.score}%</b>
                      </button>
                    )
                  })}
                </div>
              </Card>

              {selected && (
                <Card
                  title={`Inspector · ${selected.name}`}
                  actions={<Pill kind={selMeta.kind}>{selMeta.label} · {selected.score}/100</Pill>}
                >
                  <div className="insp-score-bar">
                    <div className="insp-bar-track">
                      <div className="insp-bar-fill" style={{ width: `${selected.score}%`, background: selMeta.color }} />
                    </div>
                    <div className="insp-bar-meta">
                      <span>{selected.resourceCount} recurso(s) no pilar</span>
                      <span>{selected.openFindings} achado(s) aberto(s)</span>
                      <span>Mercado: {selected.benchmark}% ({selected.delta >= 0 ? `+${selected.delta}` : selected.delta}pp)</span>
                    </div>
                  </div>

                  <h4 className="sec">Serviços-Chave Monitorados</h4>
                  <div className="svc-list">
                    {selected.services.map((s) => (
                      <div key={s.name} className="svc-row">
                        <div>
                          <b>{s.name}</b>
                          <span className="muted small"> · {s.detected ? `${s.count} detectado(s)` : 'Sem recursos ativos'}</span>
                        </div>
                        <Pill kind={s.badgeKind}>{s.badge}</Pill>
                      </div>
                    ))}
                  </div>

                  <h4 className="sec">Ações Recomendadas</h4>
                  <div className="rec-list">
                    {selected.recommendations.map((rec, idx) => (
                      <div key={idx} className="rec-item">
                        <div className="rec-head">
                          <Pill kind={SEV_KIND[rec.sev] || 'idle'}>{rec.sev}</Pill>
                          <b>{rec.title}</b>
                        </div>
                        {rec.detail && <p className="small muted">{rec.detail}</p>}
                        <div>
                          <Btn small kind="ghost" onClick={() => nav(`/t/${tenant.id}/${rec.targetRoute}`)}>
                            {rec.action} →
                          </Btn>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </div>
          ) : (
            <div className="pano-grid">
              <Card
                title={`Camadas Concêntricas & Benchmark · ${data.accountAlias}`}
                actions={<Pill kind="lav">Ref. Mercado: {data.benchmarkAverage}%</Pill>}
              >
                <ConcentricDiagram
                  alias={data.accountAlias}
                  overallScore={data.overallScore}
                  layers={data.layers}
                  pillars={data.pillars}
                  selectedId={selected?.id || ''}
                  onSelect={setSelectedPillarId}
                />
                <div className="layer-grid">
                  {([
                    ['Anel Interno · Core AWS', data.layers.core],
                    ['Anel Intermediário · Governança & FinOps', data.layers.governance],
                    ['Anel Externo · Ecossistema & Borda', data.layers.ecosystem],
                  ] as [string, LayerNode[]][]).map(([title, list]) => (
                    <div key={title} className="layer-box">
                      <span className="lbl">{title}</span>
                      <div className="chips">
                        {list.map((n) => (
                          <span key={n.name} className={`pill ${n.active ? 'ok' : 'idle'}`}>
                            {n.name}{n.active && n.count > 0 ? ` (${n.count})` : ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>

              <div style={{ display: 'grid', gap: 16 }}>
                <Card title="Comparativo por Pilar (Conta × Mercado)">
                  <div className="bench-list">
                    {data.pillars.map((p) => {
                      const sm = STATUS_META[p.status] || STATUS_META.moderate
                      return (
                        <div key={p.id} className="bench-row" onClick={() => setSelectedPillarId(p.id)}>
                          <div className="bench-head">
                            <b>{p.name}</b>
                            <span className="mono small">
                              <strong style={{ color: sm.color }}>{p.score}%</strong>
                              <span className="muted"> vs {p.benchmark}%</span>
                              {' '}
                              <span className={`pill ${p.delta >= 0 ? 'ok' : p.delta >= -15 ? 'warn' : 'bad'}`}>
                                {p.delta >= 0 ? `+${p.delta}pp` : `${p.delta}pp`}
                              </span>
                            </span>
                          </div>
                          <div className="bench-bars">
                            <div className="bench-track">
                              <div className="bench-fill account" style={{ width: `${p.score}%`, background: sm.color }} />
                              <div className="bench-marker" style={{ left: `${p.benchmark}%` }} title={`Mercado: ${p.benchmark}%`} />
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </Card>

                <Card title="Diagnóstico Automatizado">
                  {data.insights.length === 0 ? (
                    <div className="muted small">Ambiente equilibrado sem lacunas críticas detectadas.</div>
                  ) : (
                    <div className="rec-list">
                      {data.insights.map((ins, i) => (
                        <div key={i} className="rec-item">
                          <div className="rec-head">
                            <Pill kind={ins.kind}>{ins.kind === 'ok' ? 'FinOps' : ins.kind === 'bad' ? 'Prioridade' : 'Atenção'}</Pill>
                            <b>{ins.title}</b>
                          </div>
                          <p className="small muted">{ins.detail}</p>
                          <div>
                            <Btn small kind="primary" onClick={() => nav(`/t/${tenant.id}/${ins.route}`)}>
                              {ins.cta}
                            </Btn>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
