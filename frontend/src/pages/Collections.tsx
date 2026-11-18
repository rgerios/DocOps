import { useRef, useState } from 'react'
import { ago, api, can, downloadBlob, fmtDT, type CollectionRow } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, Modal, PageHead, Pill, StatusPill, useConfirm, useLoad, useToast } from '../ui'

const CHANGE: Record<string, [string, string]> = { added: ['novo', 'ok'], removed: ['removido', 'bad'], changed: ['alterado', 'warn'] }
const TRIGGER: Record<string, string> = { manual: 'manual', schedule: 'agendada', upload: 'arquivo' }

export default function Collections() {
  const { tenant, role } = useTenant()
  const toast = useToast()
  const [acct, setAcct] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const { data, error, reload } = useLoad<CollectionRow[]>(
    () => api(`/api/tenants/${tenant.id}/collections${acct ? `?account_id=${acct}` : ''}`), [tenant.id, acct],
    (d) => (d?.some((c) => c.status === 'queued' || c.status === 'running') ? 4000 : null))
  const accounts = [...new Map((data || []).map((c) => [c.account_id, c.alias])).entries()]

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
        actions={can(role, 'analyst') && <>
          <input ref={file} type="file" multiple accept=".json,.gz" hidden onChange={(e) => upload(e.target.files)} />
          <Btn busy={busy} onClick={() => file.current?.click()}>Importar arquivo do coletor</Btn>
          <Btn kind="primary" onClick={collectAll}>Coletar todas as contas</Btn>
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
                <td className="r">{c.status === 'done' && <Btn small kind="ghost" onClick={async (e) => {
                  e.stopPropagation()
                  const p = await api(`/api/tenants/${tenant.id}/collections/${c.id}/payload`)
                  downloadBlob(new Blob([JSON.stringify(p)], { type: 'application/json' }), `docviva_${c.alias}_${c.account_id}_${c.id}.json`)
                }}>JSON</Btn>}</td>
              </tr>))}
            </tbody>
          </table>)}
      </Card>
      {open && <Detail tenantId={tenant.id} id={open} canDelete={can(role, 'admin')} onClose={() => setOpen(null)} onDeleted={() => { setOpen(null); reload() }} />}
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
