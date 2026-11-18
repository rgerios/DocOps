import { useState } from 'react'
import { ago, api, can, type AwsAccount } from '../api'
import { useTenant } from '../App'
import { Btn, Card, Empty, ErrorBox, Field, Modal, PageHead, Pill, StatusPill, useLoad, useToast } from '../ui'

const ENVS = ['', 'Produção', 'Homologação', 'Desenvolvimento', 'Compartilhada/Rede', 'Segurança/Log', 'Sandbox']

export default function Accounts() {
  const { tenant, role } = useTenant()
  const toast = useToast()
  const [edit, setEdit] = useState<Partial<AwsAccount> | null>(null)
  const [guide, setGuide] = useState<AwsAccount | null>(null)
  const { data, error, reload } = useLoad<AwsAccount[]>(() => api(`/api/tenants/${tenant.id}/accounts`), [tenant.id],
    (d) => (d?.some((a) => ['queued', 'running'].includes(a.last_collection?.status || '')) ? 4000 : null))
  const admin = can(role, 'admin')

  const test = async (a: AwsAccount) => {
    toast('Testando acesso…', 'info')
    try { const r = await api(`/api/tenants/${tenant.id}/accounts/${a.id}/test`, { method: 'POST' }); toast(r.ok ? `${r.message} ${r.regions} regiões habilitadas.` : r.message, r.ok ? 'ok' : 'err') }
    catch (e: any) { toast(e.message, 'err') }
  }
  const collect = async (a: AwsAccount) => {
    try { await api(`/api/tenants/${tenant.id}/accounts/${a.id}/collect`, { method: 'POST' }); toast(`Coleta de ${a.alias} na fila`); reload() } catch (e: any) { toast(e.message, 'err') }
  }
  const remove = async (a: AwsAccount) => {
    if (!confirm(`Remover a conta ${a.alias} (${a.account_id})? O histórico de coletas fica preservado.`)) return
    try { await api(`/api/tenants/${tenant.id}/accounts/${a.id}`, { method: 'DELETE' }); toast('Conta removida'); reload() } catch (e: any) { toast(e.message, 'err') }
  }

  return (
    <div className="page">
      <PageHead title="Contas AWS" sub="Contas inventariadas deste cliente. Com uma role de leitura (DocVivaReadOnly) o servidor coleta sozinho; sem role, a conta aceita só importação de arquivo."
        actions={admin && <Btn kind="primary" onClick={() => setEdit({ active: true, environment: '' })}>Adicionar conta</Btn>} />
      <ErrorBox error={error} />
      <Card pad={false}>
        {!data ? <div className="pad muted">Carregando…</div> : !data.length ? <Empty title="Nenhuma conta cadastrada">Adicione uma conta com a role de coleta ou importe um arquivo em <b>Coletas</b> (a conta é cadastrada automaticamente).</Empty> : (
          <table className="t">
            <thead><tr><th>Conta</th><th>Ambiente</th><th>Coleta automática</th><th>Regiões</th><th>Última coleta</th><th /></tr></thead>
            <tbody>{data.map((a) => (
              <tr key={a.id}>
                <td><b>{a.alias}</b><span className="sub mono">{a.account_id}</span>{!a.active && <Pill>inativa</Pill>}</td>
                <td className="small">{a.environment || <span className="na">—</span>}</td>
                <td>{a.role_arn ? <><Pill kind="ok">role configurada</Pill><span className="sub mono">{a.role_arn.split('/').pop()}</span></> : <Pill kind="warn">só upload</Pill>}</td>
                <td className="small">{a.regions?.length ? a.regions.join(', ') : 'todas habilitadas'}</td>
                <td>{a.last_collection ? <><StatusPill s={a.last_collection.status} /><span className="sub">{ago(a.last_collection.created_at)}</span></> : <span className="na">nunca</span>}</td>
                <td className="r nowrap">
                  {a.role_arn && can(role, 'analyst') && <><Btn small kind="ghost" onClick={() => test(a)}>Testar</Btn><Btn small onClick={() => collect(a)}>Coletar</Btn></>}
                  {admin && <><Btn small kind="ghost" onClick={() => setGuide(a)}>Como criar a role</Btn><Btn small kind="ghost" onClick={() => setEdit(a)}>Editar</Btn><Btn small kind="ghost" onClick={() => remove(a)}>Remover</Btn></>}
                </td>
              </tr>))}
            </tbody>
          </table>)}
      </Card>
      {edit && <AccountForm tenantId={tenant.id} value={edit} onClose={() => setEdit(null)} onSaved={(a) => { setEdit(null); reload(); if (a.external_id && !edit.id) setGuide(a) }} />}
      {guide && <RoleGuide acc={guide} onClose={() => setGuide(null)} />}
    </div>
  )
}

function AccountForm({ tenantId, value, onClose, onSaved }: { tenantId: number; value: Partial<AwsAccount>; onClose: () => void; onSaved: (a: AwsAccount) => void }) {
  const toast = useToast()
  const [v, setV] = useState({ account_id: value.account_id || '', alias: value.alias || '', environment: value.environment || '',
    role_arn: value.role_arn || '', external_id: value.external_id || '', regions: (value.regions || []).join(' '), active: value.active ?? true })
  const [busy, setBusy] = useState(false)
  const set = (k: string, x: unknown) => setV((o) => ({ ...o, [k]: x }))
  const genExt = async () => set('external_id', (await api(`/api/tenants/${tenantId}/accounts/new-external-id`)).external_id)
  const suggestArn = () => v.account_id.length === 12 && !v.role_arn && set('role_arn', `arn:aws:iam::${v.account_id}:role/DocVivaReadOnly`)
  const save = async () => {
    setBusy(true)
    const body = { ...v, regions: v.regions.split(/[\s,]+/).filter(Boolean), role_arn: v.role_arn || null, external_id: v.external_id || null }
    try {
      const a = await api<AwsAccount>(`/api/tenants/${tenantId}/accounts${value.id ? `/${value.id}` : ''}`, { method: value.id ? 'PUT' : 'POST', body })
      toast('Conta salva'); onSaved(a)
    } catch (e: any) { toast(e.message, 'err') } finally { setBusy(false) }
  }
  return (
    <Modal title={value.id ? `Editar ${value.alias}` : 'Adicionar conta AWS'} onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancelar</Btn><Btn kind="primary" busy={busy} onClick={save}>Salvar</Btn></>}>
      <div className="grid2">
        <Field label="Account ID"><input value={v.account_id} disabled={!!value.id} onChange={(e) => set('account_id', e.target.value.trim())} onBlur={suggestArn} placeholder="123456789012" maxLength={12} /></Field>
        <Field label="Nome (alias)"><input value={v.alias} onChange={(e) => set('alias', e.target.value)} placeholder="producao" /></Field>
      </div>
      <Field label="Ambiente"><select value={v.environment} onChange={(e) => set('environment', e.target.value)}>{ENVS.map((x) => <option key={x} value={x}>{x || '—'}</option>)}</select></Field>
      <Field label="Role ARN (opcional)" hint="Deixe vazio para usar só importação de arquivo.">
        <input value={v.role_arn} onChange={(e) => set('role_arn', e.target.value.trim())} placeholder="arn:aws:iam::123456789012:role/DocVivaReadOnly" />
      </Field>
      <Field label="External ID" hint="Segredo compartilhado exigido pela trust policy da role. Recomendado.">
        <div className="row"><input value={v.external_id} onChange={(e) => set('external_id', e.target.value.trim())} /><Btn type="button" onClick={genExt}>Gerar</Btn></div>
      </Field>
      <Field label="Regiões (opcional)" hint="Separadas por espaço. Vazio = todas as regiões habilitadas na conta.">
        <input value={v.regions} onChange={(e) => set('regions', e.target.value)} placeholder="us-east-1 sa-east-1" />
      </Field>
      <label className="check"><input type="checkbox" checked={v.active} onChange={(e) => set('active', e.target.checked)} /> Conta ativa (entra nas coletas agendadas)</label>
    </Modal>
  )
}

function RoleGuide({ acc, onClose }: { acc: AwsAccount; onClose: () => void }) {
  const { data } = useLoad<any>(() => api('/api/platform/aws-identity'), [])
  const principal = data?.ok ? data.principal : 'arn:aws:iam::CONTA_DO_SERVIDOR:role/ROLE_DO_SERVIDOR'
  const trust = JSON.stringify({ Version: '2012-10-17', Statement: [{ Effect: 'Allow', Principal: { AWS: principal }, Action: 'sts:AssumeRole',
    ...(acc.external_id ? { Condition: { StringEquals: { 'sts:ExternalId': acc.external_id } } } : {}) }] })
  const role = acc.role_arn?.split('/').pop() || 'DocVivaReadOnly'
  const cmd = `aws iam create-role --role-name ${role} \\\n  --assume-role-policy-document '${trust}'\n\naws iam attach-role-policy --role-name ${role} \\\n  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess`
  const toast = useToast()
  return (
    <Modal title={`Role de coleta — ${acc.alias}`} onClose={onClose} wide footer={<Btn kind="primary" onClick={onClose}>Fechar</Btn>}>
      <p>Rode no <b>CloudShell da conta {acc.account_id}</b> (com um usuário administrador). A role dá ao servidor acesso somente leitura; nada é alterado na conta.</p>
      {!data?.ok && data && <div className="alert info">{data.message} Substitua <code>CONTA_DO_SERVIDOR/ROLE_DO_SERVIDOR</code> pela role do servidor.</div>}
      {data?.ok && <p className="muted small">Identidade do servidor detectada: <code>{data.arn}</code></p>}
      <pre className="code">{cmd}<button className="copy" onClick={() => { navigator.clipboard?.writeText(cmd); toast('Copiado') }}>copiar</button></pre>
      <p className="muted small">Para custos, a política <code>ReadOnlyAccess</code> já inclui o Cost Explorer. Depois de criar, use <b>Testar</b> na lista de contas.</p>
    </Modal>
  )
}
