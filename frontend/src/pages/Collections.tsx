import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ago, api, can, downloadBlob, fmtDT, type CollectionRow } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, Field, Modal, PageHead, Pill, StatusPill, useConfirm, useLoad, useToast } from '../ui'

const CHANGE: Record<string, [string, string]> = { added: ['novo', 'ok'], removed: ['removido', 'bad'], changed: ['alterado', 'warn'] }
const TRIGGER: Record<string, string> = { manual: 'manual', schedule: 'agendada', upload: 'arquivo' }

export default function Collections() {
  const { tenant, role } = useTenant()
  const nav = useNavigate()
  const toast = useToast()
  const [acct, setAcct] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [guide, setGuide] = useState(false)
  const [cmpOpen, setCmpOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const { data, error, reload } = useLoad<CollectionRow[]>(
    () => api(`/api/tenants/${tenant.id}/collections${acct ? `?account_id=${acct}` : ''}`), [tenant.id, acct],
    (d) => (d?.some((c) => c.status === 'queued' || c.status === 'running') ? 4000 : null))
  const accounts = [...new Map((data || []).map((c) => [c.account_id, c.alias])).entries()]
  const doneCols = (data || []).filter((c) => c.status === 'done')

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    const fd = new FormData()
    Array.from(files).forEach((f) => fd.append('files', f))
    setBusy(true)
    try {
      const r = await api(`/api/tenants/${tenant.id}/collections/upload`, { form: fd })
      toast(`${r.created.length} coleta(s) importada(s)${r.errors.length ? ` · ${r.errors.length} com erro` : ''}`, r.errors.length ? 'info' : 'ok')
      r.errors.forEach((e: string) => toast(e, 'err'))
      reload()
    } catch (e: any) { toast(e.message, 'err') } finally { setBusy(false); if (file.current) file.current.value = '' }
  }
  const collectAll = async () => {
    try { const r = await api(`/api/tenants/${tenant.id}/collect-all`, { method: 'POST' }); toast(r.queued ? `${r.queued} coleta(s) na fila` : 'Nenhuma conta com role configurada (ou todas já estão coletando).', r.queued ? 'ok' : 'info'); reload() }
    catch (e: any) { toast(e.message, 'err') }
  }

  return (
    <div className="page">
      <PageHead title="Coletas" sub="Histórico de inventários de cada conta. A coleta mais recente de cada conta alimenta o Explorer; cada nova coleta é comparada com a anterior."
        actions={<>
          {doneCols.length >= 2 && <Btn onClick={() => setCmpOpen(true)}>Comparar (A × B)</Btn>}
          <Btn onClick={() => setGuide(true)}>Como coletar (CloudShell)</Btn>
          <a className="btn" href="/api/collector.py" download="docviva_collector.py">Baixar coletor.py</a>
          {can(role, 'analyst') && <>
            <input ref={file} type="file" multiple accept=".json,.gz" hidden onChange={(e) => upload(e.target.files)} />
            <Btn busy={busy} onClick={() => file.current?.click()}>Importar arquivo do coletor</Btn>
            <Btn kind="primary" onClick={collectAll}>Coletar todas as contas</Btn>
          </>}
        </>} />
      <ErrorBox error={error} />
      <Card title="Execuções" actions={accounts.length > 1 && (
        <select value={acct} onChange={(e) => setAcct(e.target.value)}><option value="">Todas as contas</option>{accounts.map(([id, a]) => <option key={id} value={id}>{a} · {id}</option>)}</select>
      )} pad={false}>
        {!data ? <div className="pad muted">Carregando…</div> : !data.length ? <Empty title="Nenhuma coleta ainda">Cadastre contas com role em <b>Contas AWS</b> e clique em coletar, ou importe um arquivo gerado pelo coletor no CloudShell.</Empty> : (
          <table className="t">
            <thead><tr><th>Conta</th><th>Status</th><th>Origem</th><th>Iniciada</th><th>Dados de</th><th className="num">VPCs</th><th className="num">EC2</th><th className="num">Bancos</th><th>Mudanças</th><th /></tr></thead>
            <tbody>{data.map((c) => (
              <tr key={c.id} onClick={() => c.status === 'done' || c.status === 'failed' ? setOpen(c.id) : null} className={c.status === 'done' || c.status === 'failed' ? 'click' : ''}>
                <td><b>{c.alias}</b><span className="sub mono">{c.account_id}</span></td>
                <td><StatusPill s={c.status} />{c.error && <span className="sub err">{c.error.slice(0, 90)}</span>}</td>
                <td className="small">{TRIGGER[c.trigger] || c.trigger}{c.summary?.legacy && <> · <Pill kind="warn">legado</Pill></>}<span className="sub">{c.triggered_by || (c.trigger === 'schedule' ? 'agendador' : '')}</span></td>
                <td className="small">{fmtDT(c.created_at)}<span className="sub">{ago(c.created_at)}</span></td>
                <td className="small">{fmtDT(c.collected_at)}</td>
                <td className="num">{c.summary?.vpcs ?? '—'}</td><td className="num">{c.summary?.ec2 ?? '—'}</td><td className="num">{c.summary?.rds ?? '—'}</td>
                <td><DiffBadge id={c.id} c={c} /></td>
                <td className="r">{c.status === 'done' && <div className="row end">
                  <Btn small kind="ghost" onClick={(e) => { e.stopPropagation(); nav(`/t/${tenant.id}/explorer?collection_id=${c.id}`) }}>Abrir no Explorer</Btn>
                  <Btn small kind="ghost" onClick={async (e) => {
                    e.stopPropagation()
                    const p = await api(`/api/tenants/${tenant.id}/collections/${c.id}/payload`)
                    downloadBlob(new Blob([JSON.stringify(p)], { type: 'application/json' }), `docviva_${c.alias}_${c.account_id}_${c.id}.json`)
                  }}>JSON</Btn>
                </div>}</td>
              </tr>))}
            </tbody>
          </table>)}
      </Card>
      {open && <Detail tenantId={tenant.id} id={open} canDelete={can(role, 'admin')} onClose={() => setOpen(null)} onDeleted={() => { setOpen(null); reload() }} />}
      {cmpOpen && <CompareModal tenantId={tenant.id} collections={doneCols} onClose={() => setCmpOpen(false)} />}
      {guide && <CollectorGuide onClose={() => setGuide(false)} />}
    </div>
  )
}

function DiffBadge({ c }: { id: number; c: CollectionRow }) {
  const d = c.summary?.diff
  if (c.status !== 'done' || !d) return <span className="na">—</span>
  if (d.baseline) return <span className="muted small">referência</span>
  if (!d.added && !d.removed && !d.changed) return <span className="muted small">sem mudanças</span>
  return <span className="diffs">{d.added > 0 && <Pill kind="ok">+{d.added}</Pill>}{d.removed > 0 && <Pill kind="bad">−{d.removed}</Pill>}{d.changed > 0 && <Pill kind="warn">~{d.changed}</Pill>}</span>
}

function Detail({ tenantId, id, canDelete, onClose, onDeleted }: { tenantId: number; id: number; canDelete: boolean; onClose: () => void; onDeleted: () => void }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [f, setF] = useState<'all' | 'added' | 'removed' | 'changed'>('all')
  const { data } = useLoad<any>(() => api(`/api/tenants/${tenantId}/collections/${id}`), [id])
  const d = data?.diff
  const items = (d?.items || []).filter((i: any) => f === 'all' || i.change === f)
  const del = async () => {
    if (!(await confirm({ title: 'Excluir coleta', message: 'Excluir esta coleta? O Explorer passa a usar a coleta anterior desta conta.', confirmLabel: 'Excluir' }))) return
    try { await api(`/api/tenants/${tenantId}/collections/${id}`, { method: 'DELETE' }); toast('Coleta excluída'); onDeleted() } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <Modal title={data ? `${data.alias} · coleta #${id}` : 'Coleta'} onClose={onClose} wide footer={canDelete && <Btn kind="danger" onClick={del}>Excluir coleta</Btn>}>
      {!data ? <p className="muted">Carregando…</p> : <>
        <div className="kv-row">
          <div><span>Status</span><StatusPill s={data.status} /></div>
          <div><span>Dados coletados em</span>{fmtDT(data.collected_at)}</div>
          <div><span>Regiões com recursos</span>{data.summary?.regions ?? '—'}</div>
          <div><span>Coletor</span>{data.summary?.collector_version ?? '—'}{data.summary?.duration_s ? ` · ${data.summary.duration_s}s` : ''}</div>
          <div><span>Avisos de permissão</span>{data.summary?.errors ?? 0}</div>
        </div>
        {data.error && <div className="alert bad">{data.error}</div>}
        {d && (d.baseline ? <div className="alert info">Primeira coleta desta conta (ou formato diferente da anterior): ela vira a referência para as próximas comparações.</div> : <>
          <h4 className="sec">Mudanças em relação à coleta anterior</h4>
          <div className="chips">
            {(['all', 'added', 'removed', 'changed'] as const).map((k) => (
              <button key={k} className={`chip ${f === k ? 'on' : ''}`} onClick={() => setF(k)}>
                {k === 'all' ? `Todas · ${d.added + d.removed + d.changed}` : `${CHANGE[k][0]}s · ${d[k]}`}
              </button>))}
          </div>
          {!items.length ? <Empty title="Sem mudanças de configuração" /> : (
            <table className="t compact">
              <thead><tr><th>Mudança</th><th>Tipo</th><th>Recurso</th><th>Região</th><th>Detalhe</th></tr></thead>
              <tbody>{items.slice(0, 500).map((i: any, n: number) => (
                <tr key={n}><td><Pill kind={CHANGE[i.change][1]}>{CHANGE[i.change][0]}</Pill></td><td className="small">{i.type_label}</td>
                  <td><b>{i.name}</b>{i.name !== i.id && <span className="sub mono">{i.id}</span>}</td><td className="small">{i.region}</td>
                  <td className="small">{i.fields ? i.fields.map((fl: string) => <span key={fl} className="tag" title={i.before?.[fl] !== undefined ? `${String(i.before[fl])} → ${String(i.after?.[fl])}` : ''}>{fl}{i.before?.[fl] !== undefined && <> : <s>{String(i.before[fl])}</s> → {String(i.after?.[fl])}</>}</span>) : ''}</td></tr>))}
              </tbody>
            </table>)}
        </>)}
      </>}
    </Modal>
  )
}

function CollectorGuide({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const [alias, setAlias] = useState('producao')
  const [noCost, setNoCost] = useState(false)
  const cleanAlias = alias.trim().replace(/[^a-zA-Z0-9._-]+/g, '-') || 'conta'
  const outFile = `docviva_${cleanAlias}.json.gz`
  const flags = `--alias ${cleanAlias} --gzip${noCost ? ' --no-cost' : ''} -o ${outFile}`
  const cmdUpload = `python3 docviva_collector.py ${flags}`
  const cmdCurl = `curl -sSL https://raw.githubusercontent.com/rgerios/DocOps/main/backend/app/services/collector.py -o docviva_collector.py && \\\npython3 docviva_collector.py ${flags}`
  const copy = (txt: string) => { navigator.clipboard?.writeText(txt); toast('Comando copiado') }

  return (
    <Modal title="Como fazer a coleta (Automática ou CloudShell)" onClose={onClose} wide footer={<>
      <a className="btn" href="/api/collector.py" download="docviva_collector.py">Baixar docviva_collector.py</a>
      <Btn kind="primary" onClick={onClose}>Fechar</Btn>
    </>}>
      <div className="alert info">
        <b>Existem duas formas de coletar o inventário AWS:</b>
        <ul style={{ marginLeft: 18, marginTop: 6 }}>
          <li><b>Automática (com Role):</b> cadastre a conta com a role <code>DocVivaReadOnly</code> em <b>Contas AWS</b> e clique em <b>Coletar todas as contas</b> (ou configure em <b>Agendamentos</b>).</li>
          <li><b>Manual no AWS CloudShell (contas sem role):</b> baixe o script <code>docviva_collector.py</code>, envie para a sessão do CloudShell, execute o comando abaixo e importe o arquivo gerado aqui em <b>Importar arquivo do coletor</b>.</li>
        </ul>
      </div>

      <div className="grid2">
        <Field label="Nome da conta (alias)" hint="Atualiza os comandos abaixo automaticamente.">
          <input value={alias} onChange={(e) => setAlias(e.target.value)} placeholder="producao" />
        </Field>
        <div style={{ display: 'flex', alignItems: 'center', paddingTop: 18 }}>
          <label className="check"><input type="checkbox" checked={noCost} onChange={(e) => setNoCost(e.target.checked)} /> Pular Cost Explorer (<code>--no-cost</code>, evita US$ 0,03 por coleta)</label>
        </div>
      </div>

      <p><b>Passo 1 — Enviar o coletor para o CloudShell</b></p>
      <p className="muted small">Clique em <b>Baixar docviva_collector.py</b> abaixo (ou no topo da página). No Console AWS, abra o <b>CloudShell</b> (ícone <code>&gt;_</code> no topo), clique em <b>Actions → Upload file</b> e selecione o arquivo baixado.</p>

      <p><b>Passo 2 — Executar no CloudShell (copiar e colar)</b></p>
      <pre className="code">{cmdUpload}<button className="copy" onClick={() => copy(cmdUpload)}>copiar</button></pre>

      <p className="muted small">Se preferir baixar direto pelo CloudShell sem fazer upload manual, use:</p>
      <pre className="code">{cmdCurl}<button className="copy" onClick={() => copy(cmdCurl)}>copiar</button></pre>

      <p><b>Passo 3 — Baixar o JSON e importar no DocOps</b></p>
      <p className="muted small">Ao finalizar, no CloudShell clique em <b>Actions → Download file</b>, informe <code>/home/cloudshell-user/{outFile}</code> (ou apenas <code>{outFile}</code>) e importe o arquivo clicando em <b>Importar arquivo do coletor</b>.</p>
    </Modal>
  )
}

function CompareModal({ tenantId, collections, onClose }: { tenantId: number; collections: CollectionRow[]; onClose: () => void }) {
  const [targetId, setTargetId] = useState<number>(collections[0]?.id || 0)
  const [baseId, setBaseId] = useState<number>(collections[1]?.id || collections[0]?.id || 0)
  const [f, setF] = useState<'all' | 'added' | 'removed' | 'changed'>('all')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    if (!baseId || !targetId) return
    setBusy(true); setErr(null)
    try {
      const r = await api(`/api/tenants/${tenantId}/collections/compare?base_id=${baseId}&target_id=${targetId}`)
      setRes(r)
    } catch (e: any) {
      setRes(null); setErr(e.message)
    } finally { setBusy(false) }
  }

  const d = res?.diff
  const items = (d?.items || []).filter((i: any) => f === 'all' || i.change === f)

  return (
    <Modal title="Comparar coletas (A × B)" onClose={onClose} wide footer={<Btn onClick={onClose}>Fechar</Btn>}>
      <div className="grid2">
        <Field label="Coleta Base (A — anterior)">
          <select value={baseId} onChange={(e) => setBaseId(Number(e.target.value))}>
            {collections.map((c) => <option key={c.id} value={c.id}>#{c.id} · {c.alias} ({fmtDT(c.collected_at)})</option>)}
          </select>
        </Field>
        <Field label="Coleta Alvo (B — mais recente)">
          <select value={targetId} onChange={(e) => setTargetId(Number(e.target.value))}>
            {collections.map((c) => <option key={c.id} value={c.id}>#{c.id} · {c.alias} ({fmtDT(c.collected_at)})</option>)}
          </select>
        </Field>
      </div>
      <div className="row" style={{ marginBottom: 14 }}>
        <Btn kind="primary" busy={busy} disabled={!baseId || !targetId || baseId === targetId} onClick={run}>Comparar agora</Btn>
        {baseId === targetId && <span className="muted small">Escolha duas coletas diferentes.</span>}
      </div>
      {err && <div className="alert bad">{err}</div>}
      {d && <>
        <div className="chips">
          {(['all', 'added', 'removed', 'changed'] as const).map((k) => (
            <button key={k} className={`chip ${f === k ? 'on' : ''}`} onClick={() => setF(k)}>
              {k === 'all' ? `Todas · ${d.added + d.removed + d.changed}` : `${CHANGE[k][0]}s · ${d[k]}`}
            </button>))}
        </div>
        {!items.length ? <Empty title="Sem diferenças entre as coletas selecionadas" /> : (
          <table className="t compact">
            <thead><tr><th>Mudança</th><th>Tipo</th><th>Recurso</th><th>Região</th><th>Detalhe</th></tr></thead>
            <tbody>{items.slice(0, 500).map((i: any, n: number) => (
              <tr key={n}><td><Pill kind={CHANGE[i.change][1]}>{CHANGE[i.change][0]}</Pill></td><td className="small">{i.type_label}</td>
                <td><b>{i.name}</b>{i.name !== i.id && <span className="sub mono">{i.id}</span>}</td><td className="small">{i.region}</td>
                <td className="small">{i.fields ? i.fields.map((fl: string) => <span key={fl} className="tag" title={i.before?.[fl] !== undefined ? `${String(i.before[fl])} → ${String(i.after?.[fl])}` : ''}>{fl}{i.before?.[fl] !== undefined && <> : <s>{String(i.before[fl])}</s> → {String(i.after?.[fl])}</>}</span>) : ''}</td></tr>))}
            </tbody>
          </table>)}
      </>}
    </Modal>
  )
}
