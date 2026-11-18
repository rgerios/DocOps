import { useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { ago, api, fmtD } from '../api'
import { useSession } from '../App'
import { Btn, Card, ErrorBox, Field, Modal, PageHead, Pill, Secret, useConfirm, useLoad, useToast } from '../ui'
import { AuditTable } from './Audit'

export default function Platform() {
  return (
    <div className="page">
      <PageHead title="Administração da plataforma" sub="Clientes, usuários e auditoria global. Visível apenas para administradores da plataforma." />
      <nav className="subnav"><NavLink to="/plataforma/clientes">Clientes</NavLink><NavLink to="/plataforma/usuarios">Usuários</NavLink><NavLink to="/plataforma/auditoria">Auditoria</NavLink></nav>
      <Routes>
        <Route path="clientes" element={<Tenants />} />
        <Route path="usuarios" element={<Users />} />
        <Route path="auditoria" element={<GlobalAudit />} />
        <Route path="*" element={<Navigate to="clientes" replace />} />
      </Routes>
    </div>
  )
}

function Tenants() {
  const { refresh } = useSession()
  const toast = useToast()
  const { data, error, reload } = useLoad<any[]>(() => api('/api/tenants'), [])
  const [name, setName] = useState('')
  const create = async () => {
    try { await api('/api/tenants', { body: { name } }); setName(''); toast('Cliente criado'); reload(); refresh() } catch (e: any) { toast(e.message, 'err') }
  }
  const remove = async (t: any) => {
    const typed = prompt(`Excluir ${t.name} apaga contas, coletas, anotações e histórico deste cliente. Digite o nome do cliente para confirmar:`)
    if (typed !== t.name) return
    try { await api(`/api/tenants/${t.id}`, { method: 'DELETE' }); toast('Cliente excluído'); reload(); refresh() } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <>
      <ErrorBox error={error} />
      <Card title="Novo cliente"><div className="row"><input placeholder="Nome do cliente" value={name} onChange={(e) => setName(e.target.value)} /><Btn kind="primary" onClick={create} disabled={name.trim().length < 2}>Criar</Btn></div></Card>
      <Card pad={false}>
        <table className="t">
          <thead><tr><th>Cliente</th><th>Identificador</th><th>Criado</th><th /></tr></thead>
          <tbody>{(data || []).map((t) => (
            <tr key={t.id}><td><span className="dot" style={{ background: t.color }} /> <b>{t.name}</b></td><td className="mono small">{t.slug}</td><td className="small">{fmtD(t.created_at)}</td>
              <td className="r"><Btn small kind="ghost" onClick={() => location.assign(`/t/${t.id}/acessos`)}>Acessos</Btn><Btn small kind="ghost" onClick={() => remove(t)}>Excluir</Btn></td></tr>))}
          </tbody>
        </table>
      </Card>
    </>
  )
}

function Users() {
  const { me } = useSession()
  const toast = useToast()
  const confirm = useConfirm()
  const { data, error, reload } = useLoad<any[]>(() => api('/api/users'), [])
  const [add, setAdd] = useState(false)
  const [temp, setTemp] = useState<{ email: string; pwd: string } | null>(null)
  const patch = async (u: any, body: object) => { try { await api(`/api/users/${u.id}`, { method: 'PATCH', body }); reload() } catch (e: any) { toast(e.message, 'err') } }
  const resetPwd = async (u: any) => {
    if (!(await confirm({ title: 'Redefinir senha', message: `Gerar nova senha provisória para ${u.email}? As sessões abertas serão encerradas.`, confirmLabel: 'Gerar senha' }))) return
    try { const r = await api(`/api/users/${u.id}/reset-password`, { method: 'POST' }); setTemp({ email: u.email, pwd: r.temp_password }) } catch (e: any) { toast(e.message, 'err') }
  }
  const resetMfa = async (u: any) => {
    if (!(await confirm({ title: 'Remover MFA', message: `Remover o MFA de ${u.email}? A pessoa poderá configurar outro autenticador.`, confirmLabel: 'Remover MFA' }))) return
    try { await api(`/api/users/${u.id}/reset-mfa`, { method: 'POST' }); toast('MFA removido'); reload() } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <>
      <ErrorBox error={error} />
      <div className="row end"><Btn kind="primary" onClick={() => setAdd(true)}>Novo usuário</Btn></div>
      <Card pad={false}>
        <table className="t">
          <thead><tr><th>Usuário</th><th>Acessos</th><th>MFA</th><th>Último acesso</th><th>Status</th><th /></tr></thead>
          <tbody>{(data || []).map((u) => (
            <tr key={u.id}>
              <td><b>{u.name}</b><span className="sub">{u.email}</span>{u.is_superadmin && <Pill kind="lav">admin da plataforma</Pill>}</td>
              <td className="small">{u.tenants.map((t: any) => `${t.tenant} (${t.role})`).join(', ') || '—'}</td>
              <td>{u.mfa ? <Pill kind="ok">ativo</Pill> : <Pill kind="warn">não</Pill>}</td>
              <td className="small">{ago(u.last_login)}</td>
              <td>{u.active ? <Pill kind="ok">ativo</Pill> : <Pill kind="bad">desativado</Pill>}</td>
              <td className="r nowrap">{u.id !== me.id && <>
                <Btn small kind="ghost" onClick={() => patch(u, { active: !u.active })}>{u.active ? 'Desativar' : 'Reativar'}</Btn>
                <Btn small kind="ghost" onClick={() => patch(u, { is_superadmin: !u.is_superadmin })}>{u.is_superadmin ? 'Remover admin' : 'Tornar admin'}</Btn>
                <Btn small kind="ghost" onClick={() => resetPwd(u)}>Nova senha</Btn>
                {u.mfa && <Btn small kind="ghost" onClick={() => resetMfa(u)}>Remover MFA</Btn>}
              </>}</td>
            </tr>))}
          </tbody>
        </table>
      </Card>
      {add && <NewUser onClose={() => setAdd(false)} onDone={(email, pwd) => { setAdd(false); setTemp({ email, pwd }); reload() }} />}
      {temp && <Modal title="Senha provisória" onClose={() => setTemp(null)} footer={<Btn kind="primary" onClick={() => setTemp(null)}>Entendi</Btn>}>
        <p>Envie para <b>{temp.email}</b> por um canal seguro. Ela não será exibida de novo.</p><Secret label="Senha" value={temp.pwd} />
      </Modal>}
    </>
  )
}

function NewUser({ onClose, onDone }: { onClose: () => void; onDone: (email: string, pwd: string) => void }) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [sa, setSa] = useState(false)
  const save = async () => {
    try { const r = await api('/api/users', { body: { email, name, is_superadmin: sa } }); onDone(email, r.temp_password) } catch (e: any) { toast(e.message, 'err') }
  }
  return (
    <Modal title="Novo usuário" onClose={onClose} footer={<><Btn onClick={onClose}>Cancelar</Btn><Btn kind="primary" onClick={save}>Criar</Btn></>}>
      <Field label="E-mail"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus /></Field>
      <Field label="Nome"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <label className="check"><input type="checkbox" checked={sa} onChange={(e) => setSa(e.target.checked)} /> Administrador da plataforma (acesso a todos os clientes)</label>
      <p className="muted small">Para dar acesso a um cliente específico, use a tela Acessos do cliente.</p>
    </Modal>
  )
}

function GlobalAudit() {
  const { data, error } = useLoad<any[]>(() => api('/api/audit?limit=1500'), [])
  return <><ErrorBox error={error} /><Card pad={false}>{data ? <AuditTable rows={data} /> : <div className="pad muted">Carregando…</div>}</Card></>
}
