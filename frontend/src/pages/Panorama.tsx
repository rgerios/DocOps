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

interface UsageDomain {
  id: string
  name: string
  shortName: string
  count: number
  sharePct: number
  intensity: number
  services: { name: string; count: number }[]
  allServices: { name: string; count: number }[]
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
  usageProfile?: {
    totalResources: number
    dominantDomain: string
    dominantSharePct: number
    profileLabel: string
    domains: UsageDomain[]
  }
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

function sectorPath(cx: number, cy: number, rInner: number, rOuter: number, index: number, total: number): string {
  const step = (2 * Math.PI) / total
  const a1 = -Math.PI / 2 + index * step - step / 2
  const a2 = a1 + step
  const x1 = cx + rOuter * Math.cos(a1)
  const y1 = cy + rOuter * Math.sin(a1)
  const x2 = cx + rOuter * Math.cos(a2)
  const y2 = cy + rOuter * Math.sin(a2)
  const x3 = cx + rInner * Math.cos(a2)
  const y3 = cy + rInner * Math.sin(a2)
  const x4 = cx + rInner * Math.cos(a1)
  const y4 = cy + rInner * Math.sin(a1)
  return `M ${x1} ${y1} A ${rOuter} ${rOuter} 0 0 1 ${x2} ${y2} L ${x3} ${y3} A ${rInner} ${rInner} 0 0 0 ${x4} ${y4} Z`
}

// ── 1. Radar Poligonal (Raio-X de Maturidade com hover interativo) ──
function RadarChart({
  pillars,
  selectedId,
  onSelect,
}: {
  pillars: Pillar[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const [hovered, setHovered] = useState<Pillar | null>(null)
  const size = 470
  const cx = size / 2
  const cy = size / 2
  const maxR = 152
  const n = pillars.length || 8
  const rings = [25, 50, 75, 100]

  const scorePoints = pillars
    .map((p, i) => polar(cx, cy, (Math.max(8, p.score) / 100) * maxR, i, n).join(','))
    .join(' ')

  return (
    <div className="radar-wrap">
      <div className="radar-stage">
        <svg viewBox={`0 0 ${size} ${size}`} className="radar-svg" role="img" aria-label="Radar de maturidade por pilar AWS">
          {/* fatias interativas para hover em toda a área */}
          {pillars.map((p, i) => {
            const isActive = hovered?.id === p.id || p.id === selectedId
            return (
              <path
                key={`hit-${p.id}`}
                d={sectorPath(cx, cy, 10, maxR + 18, i, n)}
                className={`radar-sector ${isActive ? 'active' : ''}`}
                onMouseEnter={() => setHovered(p)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(p.id)}
              />
            )
          })}

          {/* anéis poligonais de grade */}
          {rings.map((pct) => {
            const pts = Array.from({ length: n }, (_, i) => polar(cx, cy, (pct / 100) * maxR, i, n).join(',')).join(' ')
            return (
              <g key={pct} style={{ pointerEvents: 'none' }}>
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
            const isSel = p.id === selectedId || hovered?.id === p.id
            return <line key={p.id} x1={cx} y1={cy} x2={x2} y2={y2} className={`radar-axis ${isSel ? 'sel' : ''}`} style={{ pointerEvents: 'none' }} />
          })}

          {/* polígono real da conta */}
          <polygon points={scorePoints} className="radar-poly" style={{ pointerEvents: 'none' }} />

          {/* vértices clicáveis e rótulos */}
          {pillars.map((p, i) => {
            const [vx, vy] = polar(cx, cy, (Math.max(8, p.score) / 100) * maxR, i, n)
            const [lx, ly] = polar(cx, cy, maxR + 36, i, n)
            const isSel = p.id === selectedId || hovered?.id === p.id
            const st = STATUS_META[p.status] || STATUS_META.moderate
            const anchor = lx < cx - 22 ? 'end' : lx > cx + 22 ? 'start' : 'middle'
            return (
              <g
                key={p.id}
                className="radar-node"
                onMouseEnter={() => setHovered(p)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(p.id)}
              >
                {isSel && <circle cx={vx} cy={vy} r={12} fill={st.color} opacity={0.2} />}
                <circle cx={vx} cy={vy} r={isSel ? 7 : 5} fill={st.color} stroke="#fff" strokeWidth={2} />
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

        {hovered && (
          <div className="radar-tooltip">
            <div className="rt-head">
              <b>{hovered.name}</b>
              <Pill kind={(STATUS_META[hovered.status] || STATUS_META.moderate).kind}>{hovered.score}/100</Pill>
            </div>
            <div className="rt-meta">
              <span>{hovered.resourceCount} recurso(s)</span>
              <span>·</span>
              <span>{hovered.openFindings} achado(s) aberto(s)</span>
            </div>
            <div className="rt-svcs">
              {hovered.services.map((s) => (
                <span key={s.name} className={`tag ${s.detected ? '' : 'na'}`}>
                  {s.name}: {s.detected ? s.count : '0'}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="radar-legend">
        <span><i className="leg-dot real" /> Conta atual</span>
        <span className="muted small">Passe o mouse ou clique em qualquer fatia para inspecionar</span>
      </div>
    </div>
  )
}

// ── 2. Diagrama Concêntrico Multicamadas (Benchmark com hover interativo) ──
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
  const [hoverPillar, setHoverPillar] = useState<Pillar | null>(null)
  const [hoverNode, setHoverNode] = useState<{ ring: string; node: LayerNode } | null>(null)
  const size = 470
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
      <div className="radar-stage">
        <svg viewBox={`0 0 ${size} ${size}`} className="radar-svg" role="img" aria-label="Diagrama concêntrico de camadas e benchmark">
          {/* 3 anéis concêntricos */}
          {ringDefs.map((rd, idx) => (
            <g key={rd.key} style={{ pointerEvents: 'none' }}>
              <circle cx={cx} cy={cy} r={rd.r} className={`conc-ring r${idx}`} />
              <text x={cx} y={cy - rd.r + 14} textAnchor="middle" className="conc-ring-lbl">
                {rd.label}
              </text>
            </g>
          ))}

          {/* fatias interativas por pilar */}
          {pillars.map((p, i) => {
            const isActive = hoverPillar?.id === p.id || p.id === selectedId
            return (
              <path
                key={`csec-${p.id}`}
                d={sectorPath(cx, cy, 36, 184, i, n)}
                className={`radar-sector ${isActive ? 'active' : ''}`}
                onMouseEnter={() => { setHoverNode(null); setHoverPillar(p) }}
                onMouseLeave={() => setHoverPillar(null)}
                onClick={() => onSelect(p.id)}
              />
            )
          })}

          {/* eixos dos 8 pilares */}
          {pillars.map((p, i) => {
            const [x2, y2] = polar(cx, cy, 184, i, n)
            return <line key={p.id} x1={cx} y1={cy} x2={x2} y2={y2} className="radar-axis" style={{ pointerEvents: 'none' }} />
          })}

          {/* benchmark pontilhado + cobertura real */}
          <polygon points={benchPts} className="radar-bench" style={{ pointerEvents: 'none' }} />
          <polygon points={scorePts} className="radar-poly" style={{ pointerEvents: 'none' }} />

          {/* pontos dos nós nos anéis (hover individual) */}
          {ringDefs.map((rd) =>
            rd.items.map((node, idx) => {
              const [nx, ny] = polar(cx, cy, rd.r, idx, rd.items.length)
              const isHov = hoverNode?.node.name === node.name
              return (
                <circle
                  key={`${rd.key}-${node.name}`}
                  cx={nx}
                  cy={ny}
                  r={isHov ? 7 : 5}
                  fill={node.active ? 'var(--brand-600)' : '#cbd5e1'}
                  stroke="#fff"
                  strokeWidth={1.8}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() => { setHoverPillar(null); setHoverNode({ ring: rd.label, node }) }}
                  onMouseLeave={() => setHoverNode(null)}
                />
              )
            })
          )}

          {/* rótulos dos 8 pilares na borda */}
          {pillars.map((p, i) => {
            const [lx, ly] = polar(cx, cy, 206, i, n)
            const isSel = p.id === selectedId || hoverPillar?.id === p.id
            const anchor = lx < cx - 20 ? 'end' : lx > cx + 20 ? 'start' : 'middle'
            return (
              <text
                key={p.id}
                x={lx}
                y={ly + 3}
                textAnchor={anchor}
                className={`radar-lbl ${isSel ? 'sel' : ''}`}
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => { setHoverNode(null); setHoverPillar(p) }}
                onMouseLeave={() => setHoverPillar(null)}
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

        {hoverNode && (
          <div className="radar-tooltip">
            <div className="rt-head">
              <b>{hoverNode.node.name}</b>
              <Pill kind={hoverNode.node.active ? 'ok' : 'idle'}>
                {hoverNode.node.active ? `${hoverNode.node.count} ativo(s)` : 'Não detectado'}
              </Pill>
            </div>
            <div className="rt-meta"><span>Camada: {hoverNode.ring}</span></div>
          </div>
        )}

        {!hoverNode && hoverPillar && (
          <div className="radar-tooltip">
            <div className="rt-head">
              <b>{hoverPillar.name}</b>
              <Pill kind={hoverPillar.delta >= 0 ? 'ok' : 'warn'}>
                {hoverPillar.delta >= 0 ? `+${hoverPillar.delta}pp` : `${hoverPillar.delta}pp`}
              </Pill>
            </div>
            <div className="rt-meta">
              <span>Conta: <b>{hoverPillar.score}%</b></span>
              <span>·</span>
              <span>Mercado: <b>{hoverPillar.benchmark}%</b></span>
            </div>
          </div>
        )}
      </div>

      <div className="radar-legend">
        <span><i className="leg-dot real" /> Maturidade da conta</span>
        <span><i className="leg-dot bench" /> Benchmark setorial</span>
        <span><i className="leg-dot node-on" /> Serviço detectado</span>
        <span><i className="leg-dot node-off" /> Não detectado</span>
      </div>
    </div>
  )
}

// ── 3. Radar de Perfil de Uso & Serviços (Sem Maturidade — estilo diagrama radial por fatias) ──
function UsageRadarChart({
  alias,
  totalResources,
  domains,
  selectedId,
  onSelect,
}: {
  alias: string
  totalResources: number
  domains: UsageDomain[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const [hovered, setHovered] = useState<UsageDomain | null>(null)
  const size = 520
  const cx = size / 2
  const cy = size / 2
  const maxR = 186
  const n = domains.length || 8

  const polyPts = domains
    .map((d, i) => {
      const r = d.count > 0 ? 44 + (d.intensity / 100) * (maxR - 44) : 40
      return polar(cx, cy, r, i, n).join(',')
    })
    .join(' ')

  return (
    <div className="radar-wrap">
      <div className="radar-stage">
        <svg viewBox={`0 0 ${size} ${size}`} className="radar-svg usage-svg" role="img" aria-label="Mapa radial de serviços utilizados na conta AWS">
          <defs>
            <marker id="arrow-tip" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#94a3b8" />
            </marker>
          </defs>

          {/* 3 anéis concêntricos suaves com borda pontilhada (inspirado na referência) */}
          <circle cx={cx} cy={cy} r={186} className="usage-ring outer" />
          <circle cx={cx} cy={cy} r={138} className="usage-ring mid" />
          <circle cx={cx} cy={cy} r={92} className="usage-ring inner" />

          {/* fatias clicáveis com hover */}
          {domains.map((d, i) => {
            const isHov = hovered?.id === d.id
            const isSel = d.id === selectedId
            return (
              <path
                key={`usec-${d.id}`}
                d={sectorPath(cx, cy, 38, maxR + 8, i, n)}
                className={`usage-sector ${isHov ? 'hov' : ''} ${isSel ? 'sel' : ''}`}
                onMouseEnter={() => setHovered(d)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(d.id)}
              />
            )
          })}

          {/* divisórias radiais tracejadas com seta na ponta */}
          {domains.map((d, i) => {
            const angle = -Math.PI / 2 + ((i + 0.5) * 2 * Math.PI) / n
            const x1 = cx + 40 * Math.cos(angle)
            const y1 = cy + 40 * Math.sin(angle)
            const x2 = cx + (maxR + 14) * Math.cos(angle)
            const y2 = cy + (maxR + 14) * Math.sin(angle)
            return (
              <line
                key={`div-${d.id}`}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                className="usage-divider"
                markerEnd="url(#arrow-tip)"
              />
            )
          })}

          {/* polígono de concentração real (pende para onde a conta usa mais serviços) */}
          <polygon points={polyPts} className="usage-poly" style={{ pointerEvents: 'none' }} />

          {/* serviços reais posicionados dentro de cada fatia + vértices + títulos externos */}
          {domains.map((d, i) => {
            const rVal = d.count > 0 ? 44 + (d.intensity / 100) * (maxR - 44) : 40
            const [vx, vy] = polar(cx, cy, rVal, i, n)
            const [lx, ly] = polar(cx, cy, maxR + 38, i, n)
            const isActive = hovered?.id === d.id || d.id === selectedId
            const anchor = lx < cx - 24 ? 'end' : lx > cx + 24 ? 'start' : 'middle'
            const topSvcs = d.services.slice(0, 2)

            return (
              <g
                key={d.id}
                className="radar-node"
                onMouseEnter={() => setHovered(d)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect(d.id)}
              >
                {/* serviços detectados escritos dentro da fatia */}
                {topSvcs.map((s, sIdx) => {
                  const sr = sIdx === 0 ? 78 : 122
                  const [sx, sy] = polar(cx, cy, sr, i, n)
                  return (
                    <text key={s.name} x={sx} y={sy + 3} textAnchor="middle" className="usage-svc-lbl">
                      {s.name} ({s.count})
                    </text>
                  )
                })}

                {/* ponto de peso no polígono */}
                {isActive && <circle cx={vx} cy={vy} r={11} fill="var(--brand-600)" opacity={0.22} />}
                <circle
                  cx={vx}
                  cy={vy}
                  r={d.count > 0 ? (isActive ? 7 : 5) : 3.5}
                  fill={d.count > 0 ? 'var(--brand-600)' : '#cbd5e1'}
                  stroke="#fff"
                  strokeWidth={2}
                />

                {/* rótulo do domínio na borda */}
                <text x={lx} y={ly - 4} textAnchor={anchor} className={`radar-lbl ${isActive ? 'sel' : ''}`}>
                  {d.shortName}
                </text>
                <text x={lx} y={ly + 11} textAnchor={anchor} className="radar-val" fill={d.count > 0 ? 'var(--brand-600)' : '#94a3b8'}>
                  {d.count} ({d.sharePct}%)
                </text>
              </g>
            )
          })}

          {/* núcleo central escuro com anel dourado (estilo referência AWS) */}
          <circle cx={cx} cy={cy} r={38} className="usage-core" />
          <text x={cx} y={cy - 4} textAnchor="middle" className="conc-score">{totalResources}</text>
          <text x={cx} y={cy + 11} textAnchor="middle" className="conc-sub">
            {alias.length > 13 ? `${alias.slice(0, 12)}…` : alias}
          </text>
        </svg>

        {hovered && (
          <div className="radar-tooltip">
            <div className="rt-head">
              <b>{hovered.name}</b>
              <Pill kind={hovered.count > 0 ? 'ok' : 'idle'}>{hovered.count} recurso(s) · {hovered.sharePct}%</Pill>
            </div>
            {hovered.services.length > 0 ? (
              <div className="rt-svcs">
                {hovered.services.map((s) => (
                  <span key={s.name} className="tag">{s.name}: <b>{s.count}</b></span>
                ))}
              </div>
            ) : (
              <div className="rt-meta"><span>Nenhum serviço deste domínio detectado na conta.</span></div>
            )}
          </div>
        )}
      </div>

      <div className="radar-legend">
        <span><i className="leg-dot u-inner" /> Core / Alto volume</span>
        <span><i className="leg-dot u-mid" /> Camada intermediária</span>
        <span><i className="leg-dot u-outer" /> Expansão / Borda</span>
        <span className="muted small">Passe o mouse nas fatias para ver os serviços</span>
      </div>
    </div>
  )
}

export default function Panorama() {
  const { tenant } = useTenant()
  const nav = useNavigate()
  const [accountId, setAccountId] = useState<string>('all')
  const [tab, setTab] = useState<'raiox' | 'benchmark' | 'usage'>('raiox')
  const [selectedPillarId, setSelectedPillarId] = useState<string>('security')
  const [selectedDomainId, setSelectedDomainId] = useState<string>('compute')

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

  useEffect(() => {
    const doms = data?.usageProfile?.domains
    if (!doms?.length) return
    if (!doms.some((d) => d.id === selectedDomainId)) {
      const top = [...doms].sort((a, b) => b.count - a.count)[0]
      if (top) setSelectedDomainId(top.id)
    }
  }, [data, selectedDomainId])

  const selected = data?.pillars?.find((p) => p.id === selectedPillarId) || data?.pillars?.[0]
  const selMeta = selected ? (STATUS_META[selected.status] || STATUS_META.moderate) : STATUS_META.moderate
  const usage = data?.usageProfile
  const selectedDomain = usage?.domains?.find((d) => d.id === selectedDomainId) || usage?.domains?.[0]

  return (
    <div className="page">
      <PageHead
        title="Panorama Geral"
        sub={`Visão executiva 360° de maturidade, benchmark setorial e perfil real de serviços utilizados para ${tenant.name}.${data?.computedAt ? ` Base atualizada em ${fmtDT(data.computedAt)}.` : ''}`}
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
          Raio-X da Conta (Maturidade)
        </a>
        <a
          href="#benchmark"
          className={tab === 'benchmark' ? 'active' : ''}
          onClick={(e) => { e.preventDefault(); setTab('benchmark') }}
        >
          Benchmark &amp; Camadas Concêntricas
        </a>
        <a
          href="#usage"
          className={tab === 'usage' ? 'active' : ''}
          onClick={(e) => { e.preventDefault(); setTab('usage') }}
        >
          Perfil de Uso &amp; Serviços
        </a>
      </div>

      {!data ? (
        <Card><div className="muted">Carregando panorama da infraestrutura…</div></Card>
      ) : !data.hasData ? (
        <Card>
          <Empty title="Nenhuma coleta disponível para o Panorama Geral">
            Execute ou importe ao menos uma coleta em <b>Coletas</b> para calcular o Panorama da conta AWS.
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
              <span>Domínio Predominante</span>
              <b style={{ fontSize: 16 }}>{usage?.dominantDomain || '—'}</b>
              <small>{usage?.profileLabel || 'Distribuição de serviços'}</small>
            </div>
            <div className="kpi">
              <span>Achados Abertos</span>
              <b>{data.summary.openFindings}</b>
              <small>{data.summary.criticalFindings} Crítico / Alto</small>
            </div>
          </div>

          {tab === 'raiox' && (
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
          )}

          {tab === 'benchmark' && (
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

          {tab === 'usage' && usage && (
            <div className="pano-grid">
              <Card
                title={`Mapa de Concentração de Serviços · ${data.accountAlias}`}
                actions={<Pill kind="lav">{usage.profileLabel}</Pill>}
              >
                <UsageRadarChart
                  alias={data.accountAlias}
                  totalResources={usage.totalResources}
                  domains={usage.domains}
                  selectedId={selectedDomain?.id || ''}
                  onSelect={setSelectedDomainId}
                />
                <div className="pillar-strip">
                  {usage.domains.map((d) => {
                    const active = d.id === selectedDomain?.id
                    return (
                      <button
                        key={d.id}
                        type="button"
                        className={`pillar-pill ${active ? 'active' : ''}`}
                        onClick={() => setSelectedDomainId(d.id)}
                      >
                        <span className="pp-name">{d.shortName}</span>
                        <b>{d.count}</b>
                      </button>
                    )
                  })}
                </div>
              </Card>

              {selectedDomain && (
                <Card
                  title={`Serviços em ${selectedDomain.name}`}
                  actions={<Pill kind={selectedDomain.count > 0 ? 'ok' : 'idle'}>{selectedDomain.count} recurso(s) · {selectedDomain.sharePct}%</Pill>}
                >
                  <p className="small muted">
                    Esta visão não aplica notas de maturidade: o radar pende exclusivamente para os domínios onde a conta concentra maior volume real de serviços AWS.
                  </p>

                  <div className="insp-score-bar">
                    <div className="insp-bar-track">
                      <div className="insp-bar-fill" style={{ width: `${selectedDomain.intensity}%`, background: 'var(--brand-600)' }} />
                    </div>
                    <div className="insp-bar-meta">
                      <span>Participação na conta: <b>{selectedDomain.sharePct}%</b></span>
                      <span>Total mapeado: <b>{usage.totalResources}</b></span>
                    </div>
                  </div>

                  <h4 className="sec">Detalhamento por Serviço</h4>
                  <div className="svc-list">
                    {selectedDomain.allServices.map((s) => (
                      <div key={s.name} className="svc-row">
                        <div>
                          <b>{s.name}</b>
                          <span className="muted small">
                            {s.count > 0 && selectedDomain.count > 0
                              ? ` · ${Math.round((s.count / selectedDomain.count) * 100)}% do domínio`
                              : ' · Não utilizado'}
                          </span>
                        </div>
                        <Pill kind={s.count > 0 ? 'ok' : 'idle'}>{s.count}</Pill>
                      </div>
                    ))}
                  </div>

                  <h4 className="sec">Distribuição Geral da Conta</h4>
                  <div className="bench-list">
                    {[...usage.domains]
                      .sort((a, b) => b.count - a.count)
                      .map((d) => (
                        <div key={d.id} className="bench-row" onClick={() => setSelectedDomainId(d.id)}>
                          <div className="bench-head">
                            <b>{d.name}</b>
                            <span className="mono small">
                              <strong>{d.count}</strong> <span className="muted">({d.sharePct}%)</span>
                            </span>
                          </div>
                          <div className="bench-track">
                            <div className="bench-fill" style={{ width: `${d.intensity}%`, background: d.id === selectedDomain.id ? 'var(--brand-600)' : 'var(--pastel)' }} />
                          </div>
                        </div>
                      ))}
                  </div>

                  <div className="row end" style={{ paddingTop: 6 }}>
                    <Btn small onClick={() => nav(`/t/${tenant.id}/assets`)}>Explorar em Assets →</Btn>
                  </div>
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
