import { useState } from 'react'
import { api, can, fmtDT, type AwsAccount } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, Field, Modal, PageHead, Pill, useConfirm, useLoad, useToast } from '../ui'

interface Sched { id: number; name: string; cron: string; account_ids: number[] | null; enabled: boolean; last_run: string | null; next_run: string | null; timezone: string }

const PRESETS: [string, string][] = [
  ['Diária às 06:00', '0 6 * * *'], ['Duas vezes ao dia (06:00 e 18:00)', '0 6,18 * * *'],
  ['Dias úteis às 07:00', '0 7 * * 1-5'], ['Semanal (segunda às 06:00)', '0 6 * * 1'], ['Mensal (dia 1 às 06:00)', '0 6 1 * *'],
]
export const cronLabel = (c: string) => PRESETS.find((p) => p[1] === c)?.[0] || c

export default function Schedules() {
  const { tenant, role } = useTenant()
  const toast = useToast()
  const confirm = useConfirm()
  const [edit, setEdit] = useState<Partial<Sched> | null>(null)
  const { data, error, reload } = useLoad<Sched[]>(() => api(`/api/tenants/${tenant.id}/schedules`), [tenant.id])
  const { data: accounts } = useLoad<AwsAccount[]>(() => api(`/api/tenants/${tenant.id}/accounts`), [tenant.id])
  const admin = can(role, 'admin')
  const names = (ids: number[] | null) => (!ids ? 'Todas as contas ativas com role' : ids.map((i) => accounts?.find((a) => a.id === i)?.alias || `#${i}`).join(', '))
  const toggle = async (s: Sched) => {
    try { await api(`/api/tenants/${tenant.id}/schedules/${s.id}`, { method: 'PUT', body: { ...s, enabled: !s.enabled } }); reload() } catch (e: any) { toast(e.message, 'err') }
  }
  const remove = async (s: Sched) => {
    if (!(await confirm({ title: 'Excluir agendamento', message: `Excluir o agendamento "${s.name}"?`, confirmLabel: 'Excluir' }))) return
    try { await api(`/api/tenants/${tenant.id}/schedules/${s.id}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <div className="page">
      <PageHead title="Agendamentos" sub="Coletas automáticas recorrentes. Cada execução gera histórico, comparação com a coleta anterior e alertas no Teams."
        actions={admin && <Btn kind="primary" onClick={() => setEdit({ name: 'Coleta diária', cron: '0 6 * * *', enabled: true, account_ids: null })}>Novo agendamento</Btn>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        {!data ? <div className="pad muted">Carregando…</div> : !data.length ? <Empty title="Nenhum agendamento">Crie um para manter o inventário sempre atualizado.</Empty> : (
          <table className="t">
            <thead><tr><th>Nome</th><th>Quando</th><th>Contas</th><th>Próxima execução</th><th>Última</th><th>Status</th><th /></tr></thead>
            <tbody>{data.map((s) => (
              <tr key={s.id}>
                <td><b>{s.name}</b></td><td>{cronLabel(s.cron)}<span className="sub mono">{s.cron} · {s.timezone}</span></td>
                <td className="small">{names(s.account_ids)}</td><td className="small">{s.enabled ? fmtDT(s.next_run) : '—'}</td><td className="small">{fmtDT(s.last_run)}</td>
                <td>{s.enabled ? <Pill kind="ok">ativo</Pill> : <Pill>pausado</Pill>}</td>
                <td className="r nowrap">{admin && <><Btn small kind="ghost" onClick={() => toggle(s)}>{s.enabled ? 'Pausar' : 'Ativar'}</Btn><Btn small kind="ghost" onClick={() => setEdit(s)}>Editar</Btn><Btn small kind="ghost" onClick={() => remove(s)}>Excluir</Btn></>}</td>
              </tr>))}
            </tbody>
          </table>)}
      </Card>
      {edit && <SchedForm tenantId={tenant.id} value={edit} accounts={(accounts || []).filter((a) => a.role_arn)} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </div>
  )
}

function SchedForm({ tenantId, value, accounts, onClose, onSaved }: { tenantId: number; value: Partial<Sched>; accounts: AwsAccount[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [name, setName] = useState(value.name || '')
  const [cron, setCron] = useState(value.cron || '0 6 * * *')
  const [all, setAll] = useState(!value.account_ids)
  const [ids, setIds] = useState<number[]>(value.account_ids || [])
  const [busy, setBusy] = useState(false)
  const preset = PRESETS.find((p) => p[1] === cron)?.[1] || 'custom'
  const save = async () => {
    setBusy(true)
    try {
      await api(`/api/tenants/${tenantId}/schedules${value.id ? `/${value.id}` : ''}`, { method: value.id ? 'PUT' : 'POST', body: { name, cron, account_ids: all ? null : ids, enabled: value.enabled ?? true } })
      toast('Agendamento salvo'); onSaved()
    } catch (e: any) { toast(e.message, 'err') } finally { setBusy(false) }
  }
  return (
    <Modal title={value.id ? 'Editar agendamento' : 'Novo agendamento'} onClose={onClose} footer={<><Btn onClick={onClose}>Cancelar</Btn><Btn kind="primary" busy={busy} onClick={save}>Salvar</Btn></>}>
      <Field label="Nome"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Frequência"><select value={preset} onChange={(e) => e.target.value !== 'custom' && setCron(e.target.value)}>
        {PRESETS.map(([l, c]) => <option key={c} value={c}>{l}</option>)}<option value="custom">Personalizada (cron)</option></select></Field>
      <Field label="Expressão cron" hint="minuto hora dia mês dia-da-semana · intervalo mínimo de 1 hora"><input className="mono" value={cron} onChange={(e) => setCron(e.target.value)} /></Field>
      <label className="check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Todas as contas ativas com role</label>
      {!all && <div className="checklist">{accounts.length ? accounts.map((a) => (
        <label key={a.id} className="check"><input type="checkbox" checked={ids.includes(a.id)} onChange={(e) => setIds(e.target.checked ? [...ids, a.id] : ids.filter((x) => x !== a.id))} /> {a.alias} <span className="mono muted">{a.account_id}</span></label>
      )) : <p className="muted">Nenhuma conta com role configurada.</p>}</div>}
    </Modal>
  )
}
