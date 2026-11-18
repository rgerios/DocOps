import { useEffect, useState } from 'react'
import { ago, api, ROLE_LABEL, type Role } from '../api'
import { useSession, useTenant } from '../App'
import { Btn, Card, ErrorBox, Field, Modal, PageHead, Pill, Secret, useLoad, useToast } from '../ui'

const ROLE_HELP: Record<Role, string> = {
  admin: 'Tudo neste cliente: contas AWS, agendamentos, alertas, acessos e auditoria.',
  analyst: 'Dispara coletas, importa arquivos, edita anotações, documentação e tratativas.',
  viewer: 'Consulta e exporta relatórios, sem alterar nada.',
  client: 'Portal do cliente: só o Explorer em leitura, sem anotações internas.',
}

export default function Access() {
  const { tenant } = useTenant()
  const { refresh } = useSession()
  const toast = useToast()
  const { data, error, reload } = useLoad<any[]>(() => api(`/api/tenants/${tenant.id}/members`), [tenant.id])
  const [add, setAdd] = useState(false)
  const [temp, setTemp] = useState<{ email: string; pwd: string } | null>(null)
  const setRole = async (m: any, role: Role) => {
    try { await api(`/api/tenants/${tenant.id}/members/${m.id}`, { method: 'PATCH', body: { role } }); toast('Perfil atualizado'); reload() } catch (e: any) { toast(e.message, 'err') }
  }
  const remove = async (m: any) => {
    if (!confirm(`Remover o acesso de ${m.email} a ${tenant.name}?`)) return
    try { await api(`/api/tenants/${tenant.id}/members/${m.id}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <div className="page">
      <PageHead title="Acessos" sub={`Quem acessa ${tenant.name} e com qual perfil.`} actions={<Btn kind="primary" onClick={() => setAdd(true)}>Adicionar pessoa</Btn>} />
      <ErrorBox error={error} />
      <div className="grid-side">
        <Card pad={false}>
          <table className="t">
            <thead><tr><th>Pessoa</th><th>Perfil</th><th>MFA</th><th>Último acesso</th><th /></tr></thead>
            <tbody>{(data || []).map((m) => (
              <tr key={m.id}>
                <td><b>{m.name}</b><span className="sub">{m.email}</span>{!m.active && <Pill kind="bad">desativado</Pill>}</td>
                <td><select value={m.role} onChange={(e) => setRole(m, e.target.value as Role)}>{(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></td>
                <td>{m.mfa ? <Pill kind="ok">ativo</Pill> : <Pill kind="warn">sem MFA</Pill>}</td>
                <td className="small">{ago(m.last_login)}</td>
                <td className="r"><Btn small kind="ghost" onClick={() => remove(m)}>Remover</Btn></td>
              </tr>))}
            </tbody>
          </table>
        </Card>
        <Card title="Perfis">{(Object.keys(ROLE_HELP) as Role[]).reverse().map((r) => <p key={r} className="small"><b>{ROLE_LABEL[r]}</b> — {ROLE_HELP[r]}</p>)}</Card>
      </div>
      <Branding onSaved={refresh} />
      {add && <AddMember tenantId={tenant.id} onClose={() => setAdd(false)} onDone={(email, pwd) => { setAdd(false); reload(); if (pwd) setTemp({ email, pwd }) }} />}
      {temp && <Modal title="Usuário criado" onClose={() => setTemp(null)} footer={<Btn kind="primary" onClick={() => setTemp(null)}>Entendi</Btn>}>
        <p>Envie a senha provisória para <b>{temp.email}</b> por um canal seguro. Ela não será exibida de novo; no primeiro acesso a pessoa define a própria senha.</p>
        <Secret label="Senha provisória" value={temp.pwd} />
      </Modal>}
    </div>
  )
}

function AddMember({ tenantId, onClose, onDone }: { tenantId: number; onClose: () => void; onDone: (email: string, pwd?: string) => void }) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try { const r = await api(`/api/tenants/${tenantId}/members`, { body: { email, name, role } }); toast(r.temp_password ? 'Usuário criado' : 'Acesso concedido'); onDone(email, r.temp_password) }
    catch (e: any) { toast(e.message, 'err') } finally { setBusy(false) }
  }
  return (
    <Modal title="Adicionar pessoa" onClose={onClose} footer={<><Btn onClick={onClose}>Cancelar</Btn><Btn kind="primary" busy={busy} onClick={save}>Adicionar</Btn></>}>
      <Field label="E-mail" hint="Se a pessoa ainda não tem login, um usuário é criado com senha provisória."><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus /></Field>
      <Field label="Nome"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Perfil"><select value={role} onChange={(e) => setRole(e.target.value as Role)}>{(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></Field>
      <p className="muted small">{ROLE_HELP[role]}</p>
    </Modal>
  )
}

function Branding({ onSaved }: { onSaved: () => Promise<void> }) {
  const { tenant } = useTenant()
  const toast = useToast()
  const { data } = useLoad<any>(() => api(`/api/tenants/${tenant.id}`), [tenant.id])
  const [name, setName] = useState('')
  const [color, setColor] = useState('#4a7a37')
  const [logo, setLogo] = useState<string | null>(null)
  useEffect(() => { if (data) { setName(data.name); setColor(data.color); setLogo(data.logo) } }, [data])
  const pick = (f?: File) => {
    if (!f) return
    if (f.size > 300_000) return toast('Logo grande demais (máx. ~300 KB).', 'err')
    const r = new FileReader()
    r.onload = () => setLogo(String(r.result))
    r.readAsDataURL(f)
  }
  const save = async () => {
    try { await api(`/api/tenants/${tenant.id}`, { method: 'PATCH', body: { name, color, logo: logo ?? '' } }); toast('Identidade do cliente salva'); onSaved() } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <Card title="Identidade do cliente" actions={<Btn kind="primary" small onClick={save}>Salvar</Btn>}>
      <div className="grid3">
        <Field label="Nome do cliente"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Cor"><input type="color" value={color} onChange={(e) => setColor(e.target.value)} /></Field>
        <Field label="Logo (vai na capa dos relatórios)" hint="PNG, JPG ou SVG, até 300 KB.">
          <div className="row">{logo && <img src={logo} alt="" className="logo-prev" />}<input type="file" accept="image/png,image/jpeg,image/svg+xml" onChange={(e) => pick(e.target.files?.[0])} />{logo && <Btn small kind="ghost" onClick={() => setLogo('')}>Remover</Btn>}</div>
        </Field>
      </div>
    </Card>
  )
}
