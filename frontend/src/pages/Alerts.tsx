import { useEffect, useState } from 'react'
import { api } from '../api'
import { useTenant } from '../App'
import { Btn, Card, ErrorBox, Field, PageHead, useLoad, useToast } from '../ui'

const SEVS: [string, string][] = [['critical', 'Crítico'], ['high', 'Alto'], ['medium', 'Médio'], ['low', 'Baixo'], ['info', 'Info']]

export default function Alerts() {
  const { tenant } = useTenant()
  const toast = useToast()
  const { data, error, reload } = useLoad<any>(() => api(`/api/tenants/${tenant.id}/settings`), [tenant.id])
  const [url, setUrl] = useState('')
  const [sev, setSev] = useState<string[]>([])
  const [fail, setFail] = useState(true)
  const [changes, setChanges] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (data) { setSev(data.alert_severities); setFail(data.alert_on_failure); setChanges(data.alert_on_changes) } }, [data])
  const save = async (clear = false) => {
    setBusy(true)
    try {
      await api(`/api/tenants/${tenant.id}/settings`, { method: 'PUT', body: { teams_webhook: clear ? '' : url || null, alert_severities: sev, alert_on_failure: fail, alert_on_changes: changes } })
      setUrl(''); toast('Configuração salva'); reload()
    } catch (e: any) { toast(e.message, 'err') } finally { setBusy(false) }
  }
  const test = async () => {
    try { const r = await api(`/api/tenants/${tenant.id}/settings/test-teams`, { method: 'POST' }); toast(r.message, r.ok ? 'ok' : 'err') } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <div className="page narrow">
      <PageHead title="Alertas" sub="Notificações no Microsoft Teams após cada coleta. Achados já tratados (resolvidos ou com risco aceito) não geram alerta." />
      <ErrorBox error={error} />
      <Card title="Canal do Teams">
        <p className="muted small">No canal desejado: <b>⋯ → Workflows → “Post to a channel when a webhook request is received”</b> (ou o conector “Incoming Webhook”, onde ainda existir). Copie a URL gerada e cole abaixo.</p>
        <Field label="URL do webhook" hint={data?.teams_configured ? <>Configurado: <code>{data.teams_webhook}</code>. Cole uma nova URL só se quiser trocar.</> : 'Nenhum webhook configurado.'}>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        </Field>
        <div className="row">
          <Btn kind="primary" busy={busy} onClick={() => save()}>Salvar</Btn>
          {data?.teams_configured && <><Btn onClick={test}>Enviar teste</Btn><Btn kind="ghost" onClick={() => confirm('Remover o webhook? Os alertas param.') && save(true)}>Remover webhook</Btn></>}
        </div>
      </Card>
      <Card title="O que alertar">
        <p className="lbl">Achados novos com severidade:</p>
        <div className="chips">{SEVS.map(([k, l]) => (
          <label key={k} className={`chip ${sev.includes(k) ? 'on' : ''}`}><input type="checkbox" hidden checked={sev.includes(k)} onChange={(e) => setSev(e.target.checked ? [...sev, k] : sev.filter((x) => x !== k))} />{l}</label>))}
        </div>
        <label className="check"><input type="checkbox" checked={fail} onChange={(e) => setFail(e.target.checked)} /> Coleta com falha (permissão, role, timeout)</label>
        <label className="check"><input type="checkbox" checked={changes} onChange={(e) => setChanges(e.target.checked)} /> Resumo de mudanças de configuração a cada coleta</label>
        <div className="row"><Btn kind="primary" busy={busy} onClick={() => save()}>Salvar preferências</Btn></div>
      </Card>
    </div>
  )
}
