import { useEffect, useState, type ReactNode } from 'react'
import { api, can } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, Field, PageHead, Pill, useLoad, useToast } from '../ui'

type ProviderId = 'copilot' | 'openrouter' | 'gemini' | 'gpt' | 'local'

interface ProviderMeta {
  label: string
  default_model: string
  endpoint: string
  hint: string
}

interface AIConfigRes {
  provider: ProviderId
  model: string
  base_url: string
  api_key_configured: boolean
  api_key_hint: string | null
  providers: Record<ProviderId, ProviderMeta>
  stats: Record<string, number>
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
  meta?: string
}

const QUICK_PROMPTS = [
  'Quantas instâncias EC2 tenho em todo o ambiente, separadas por conta, região, tipo e estado (running/stopped)?',
  'Quais são os principais alvos de economia financeira (FinOps / Well-Architected: gp2→gp3, gerações antigas, Compute Optimizer, Savings Plans, S3 lifecycle)?',
  'Faça um resumo executivo completo da infraestrutura (VPCs, EC2, RDS, S3, Lambdas, EKS/ECS e custos).',
  'Quais são os principais riscos de segurança abertos e por onde devo começar a tratar?',
]

export default function AiAnalysis() {
  const { tenant, role } = useTenant()
  const toast = useToast()
  const isAdmin = can(role, 'admin')
  const { data, error, reload } = useLoad<AIConfigRes>(() => api(`/api/tenants/${tenant.id}/ai/config`), [tenant.id])

  const [provider, setProvider] = useState<ProviderId>('gpt')
  const [model, setModel] = useState('gpt-4o-mini')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)

  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const [asking, setAsking] = useState(false)

  useEffect(() => {
    if (!data) return
    setProvider(data.provider)
    setModel(data.model)
    setBaseUrl(data.base_url || '')
  }, [data])

  const changeProvider = (p: ProviderId) => {
    setProvider(p)
    const meta = data?.providers?.[p]
    if (meta) {
      setModel(meta.default_model)
      if (p === 'local' && !baseUrl) setBaseUrl(meta.endpoint)
    }
  }

  const saveConfig = async () => {
    setSaving(true)
    try {
      await api(`/api/tenants/${tenant.id}/ai/config`, {
        method: 'PUT',
        body: {
          provider,
          model,
          base_url: provider === 'local' ? baseUrl : null,
          ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        },
      })
      setApiKey('')
      toast('Configuração de IA salva para este cliente')
      reload()
    } catch (e: any) {
      toast(e.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  const clearSavedKey = async () => {
    setSaving(true)
    try {
      await api(`/api/tenants/${tenant.id}/ai/config`, {
        method: 'PUT',
        body: { provider, model, base_url: provider === 'local' ? baseUrl : null, api_key: '' },
      })
      setApiKey('')
      toast('Chave removida', 'info')
      reload()
    } catch (e: any) {
      toast(e.message, 'err')
    } finally {
      setSaving(false)
    }
  }

  const ask = async (text?: string) => {
    const q = (text ?? question).trim()
    if (!q || asking) return
    const nextHistory = [...messages, { role: 'user' as const, content: q }]
    setMessages(nextHistory)
    if (!text) setQuestion('')
    setAsking(true)
    try {
      const r = await api<{ answer: string; provider: string; model: string }>(`/api/tenants/${tenant.id}/ai/ask`, {
        body: {
          question: q,
          history: messages.slice(-8).map((m) => ({ role: m.role, content: m.content })),
          provider,
          model,
          base_url: provider === 'local' ? baseUrl : undefined,
          ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        },
      })
      const label = data?.providers?.[r.provider as ProviderId]?.label || r.provider
      setMessages([...nextHistory, { role: 'assistant', content: r.answer, meta: `${label} · ${r.model}` }])
    } catch (e: any) {
      toast(e.message, 'err')
      setMessages([...nextHistory, { role: 'assistant', content: `Não foi possível concluir a análise: ${e.message}` }])
    } finally {
      setAsking(false)
    }
  }

  const s = data?.stats
  const meta = data?.providers?.[provider]

  return (
    <div className="page">
      <PageHead
        title="IA Analisando"
        sub={`Converse com uma IA sobre o inventário AWS real de ${tenant.name} usando Copilot, OpenRouter, Gemini, GPT ou LLM Local.`}
        actions={messages.length > 0 && <Btn onClick={() => setMessages([])}>Limpar conversa</Btn>}
      />
      <ErrorBox error={error} />

      {s && (
        <div className="ai-kpis">
          <div className="kpi"><span>Contas coletadas</span><b>{s.accounts ?? 0}</b></div>
          <div className="kpi"><span>Instâncias EC2</span><b>{s.ec2_total ?? 0}</b><small>{s.ec2_running ?? 0} ativas · {s.ec2_stopped ?? 0} paradas</small></div>
          <div className="kpi"><span>Bancos RDS</span><b>{(s.rds ?? 0) + (s.rds_clusters ?? 0)}</b></div>
          <div className="kpi"><span>VPCs / Subnets</span><b>{s.vpcs ?? 0} / {s.subnets ?? 0}</b></div>
          <div className="kpi"><span>Buckets S3</span><b>{s.s3_buckets ?? 0}</b></div>
          <div className="kpi"><span>Achados abertos</span><b>{s.findings_open ?? 0}</b></div>
          {(s.estimated_monthly_savings_usd ?? 0) > 0 && (
            <div className="kpi"><span>Economia FinOps est.</span><b>US$ {s.estimated_monthly_savings_usd}</b><small>por mês (AWS)</small></div>
          )}
        </div>
      )}

      <div className="ai-layout">
        <Card title="Provedor e Chave API">
          <Field label="Provedor de IA">
            <select value={provider} onChange={(e) => changeProvider(e.target.value as ProviderId)}>
              <option value="copilot">GitHub Copilot</option>
              <option value="openrouter">OpenRouter</option>
              <option value="gemini">Google Gemini</option>
              <option value="gpt">OpenAI GPT</option>
              <option value="local">LLM Local (Ollama / LM Studio)</option>
            </select>
          </Field>

          <Field label="Modelo" hint={meta?.hint}>
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={meta?.default_model || ''} />
          </Field>

          {provider === 'local' && (
            <Field label="URL Base (compatível OpenAI)" hint="Para Ollama rodando no host Docker, use http://host.docker.internal:11434/v1">
              <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://host.docker.internal:11434/v1" />
            </Field>
          )}

          <Field
            label={provider === 'local' ? 'Chave API (opcional)' : 'Chave API'}
            hint={data?.api_key_configured && data.provider === provider
              ? <>Chave salva no servidor: <code>{data.api_key_hint}</code>. Preencha só para trocar ou usar outra na sessão.</>
              : 'Você pode usar apenas nesta sessão ou salvar para o cliente (Admin).'}
          >
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={data?.api_key_configured && data.provider === provider ? '•••••••• (já configurada)' : 'Cole sua chave aqui…'} />
          </Field>

          {isAdmin && (
            <div className="row">
              <Btn kind="primary" busy={saving} onClick={saveConfig}>Salvar para o cliente</Btn>
              {data?.api_key_configured && <Btn small kind="ghost" onClick={clearSavedKey}>Remover chave salva</Btn>}
            </div>
          )}
        </Card>

        <Card title="Análise do ambiente" actions={s?.accounts ? <Pill kind="ok">Inventário pronto</Pill> : <Pill kind="warn">Sem coletas</Pill>}>
          {!s?.accounts ? (
            <Empty title="Nenhuma coleta disponível">
              Faça ou importe ao menos uma coleta em <b>Coletas</b> para que a IA possa analisar o ambiente.
            </Empty>
          ) : (
            <>
              <div className="ai-prompts">
                {QUICK_PROMPTS.map((p) => (
                  <button key={p} type="button" className="chip" disabled={asking} onClick={() => ask(p)}>{p}</button>
                ))}
              </div>

              <div className="ai-chat">
                {!messages.length ? (
                  <div className="muted small">Escolha uma sugestão acima ou digite sua pergunta abaixo (ex.: <i>"Quantas EC2 t3.medium temos em produção?"</i>).</div>
                ) : (
                  messages.map((m, i) => (
                    <div key={i} className={`ai-msg ${m.role}`}>
                      <div className="ai-msg-h">
                        <b>{m.role === 'user' ? 'Você' : 'IA Analisando'}</b>
                        <div className="row">
                          {m.meta && <span className="muted small">{m.meta}</span>}
                          {m.role === 'assistant' && (
                            <Btn small kind="ghost" onClick={() => { navigator.clipboard?.writeText(m.content); toast('Resposta copiada') }}>Copiar</Btn>
                          )}
                        </div>
                      </div>
                      <div className="ai-msg-b">{m.role === 'assistant' ? <RichText text={m.content} /> : <p>{m.content}</p>}</div>
                    </div>
                  ))
                )}
                {asking && <div className="ai-msg assistant"><span className="spin dark" /> Analisando inventário…</div>}
              </div>

              <form className="ai-input" onSubmit={(e) => { e.preventDefault(); ask() }}>
                <textarea
                  rows={2}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }}
                  placeholder="Pergunte sobre EC2, RDS, VPCs, custos, achados de segurança…"
                />
                <Btn type="submit" kind="primary" busy={asking} disabled={!question.trim()}>Analisar</Btn>
              </form>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

// Renderizador simples e seguro (sem dangerouslySetInnerHTML) para respostas Markdown da IA
function RichText({ text }: { text: string }) {
  const lines = text.split('\n')
  const nodes: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) { buf.push(lines[i]); i++ }
      nodes.push(<pre key={nodes.length} className="code">{buf.join('\n')}</pre>)
      i++; continue
    }
    if (line.startsWith('### ')) { nodes.push(<h4 key={nodes.length}>{inline(line.slice(4))}</h4>); i++; continue }
    if (line.startsWith('## ')) { nodes.push(<h3 key={nodes.length}>{inline(line.slice(3))}</h3>); i++; continue }
    if (line.startsWith('# ')) { nodes.push(<h3 key={nodes.length}>{inline(line.slice(2))}</h3>); i++; continue }
    if (/^[-*] /.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^[-*] /.test(lines[i])) { items.push(lines[i].slice(2)); i++ }
      nodes.push(<ul key={nodes.length}>{items.map((x, idx) => <li key={idx}>{inline(x)}</li>)}</ul>)
      continue
    }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:-]+\|/.test(lines[i + 1])) {
      const splitRow = (r: string) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      const head = splitRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(splitRow(lines[i])); i++ }
      nodes.push(
        <div key={nodes.length} className="ai-table-wrap">
          <table className="t compact">
            <thead><tr>{head.map((h, k) => <th key={k}>{inline(h)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci}>{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )
      continue
    }
    if (!line.trim()) { i++; continue }
    nodes.push(<p key={nodes.length}>{inline(line)}</p>)
    i++
  }
  return <div className="ai-md">{nodes}</div>
}

function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
    return part
  })
}
