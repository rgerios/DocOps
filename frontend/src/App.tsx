import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, can, ROLE_LABEL, setUnauthorizedHandler, type Me, type Role, type TenantRef } from './api'
import logoWhite from './assets/logo-white.png'
import logoColor from './assets/logo-color.png'
import { applyTenantTheme, resetTenantTheme } from './theme'
import { Btn, Field, useToast } from './ui'
import Explorer from './pages/Explorer'
import Collections from './pages/Collections'
import Accounts from './pages/Accounts'
import Schedules from './pages/Schedules'
import Alerts from './pages/Alerts'
import Access from './pages/Access'
import Audit from './pages/Audit'
import MyAccount from './pages/MyAccount'
import Platform from './pages/Platform'
import AiAnalysis from './pages/AiAnalysis'
import FinOps from './pages/FinOps'

// ── sessão ──
interface Session { me: Me; setMe: (m: Me | null) => void; refresh: () => Promise<void> }
const SessionCtx = createContext<Session>(null as unknown as Session)
export const useSession = () => useContext(SessionCtx)

export function useTenant(): { tenant: TenantRef; role: Role } {
  const { me } = useSession()
  const { tid } = useParams()
  const tenant = me.tenants.find((t) => String(t.id) === tid)!
  return { tenant, role: tenant?.role }
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined)
  const refresh = async () => { try { setMe(await api<Me>('/api/auth/me')) } catch { setMe(null) } }
  useEffect(() => { setUnauthorizedHandler(() => setMe(null)); refresh() }, [])
  if (me === undefined) return <div className="boot"><span className="spin dark" /></div>
  if (me === null) return <Login onOk={setMe} />
  if (me.must_change_password) return <ForcePassword me={me} onOk={setMe} />
  return (
    <SessionCtx.Provider value={{ me, setMe, refresh }}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/conta" element={<Shell><MyAccount /></Shell>} />
          <Route path="/plataforma/*" element={me.is_superadmin ? <Shell><Platform /></Shell> : <Navigate to="/" />} />
          <Route path="/t/:tid/*" element={<TenantRoutes />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </BrowserRouter>
    </SessionCtx.Provider>
  )
}

function Home() {
  const { me } = useSession()
  const last = localStorage.getItem('docops.tenant')
  const t = me.tenants.find((x) => String(x.id) === last) || me.tenants[0]
  if (t) return <Navigate to={`/t/${t.id}/explorer`} replace />
  if (me.is_superadmin) return <Navigate to="/plataforma" replace />
  return <Shell><div className="empty big"><b>Nenhum cliente liberado para você</b>Peça a um administrador para conceder acesso.</div></Shell>
}

function TenantRoutes() {
  const { me } = useSession()
  const { tid } = useParams()
  const t = me.tenants.find((x) => String(x.id) === tid)
  useEffect(() => { if (t) localStorage.setItem('docops.tenant', String(t.id)) }, [t])
  if (!t) return <Navigate to="/" replace />
  const r = t.role
  return (
    <Shell tenant={t}>
      <Routes>
        <Route path="explorer" element={<Explorer key={t.id} />} />
        <Route path="coletas" element={can(r, 'viewer') ? <Collections /> : <Navigate to="../explorer" />} />
        <Route path="contas" element={can(r, 'viewer') ? <Accounts /> : <Navigate to="../explorer" />} />
        <Route path="agendamentos" element={can(r, 'viewer') ? <Schedules /> : <Navigate to="../explorer" />} />
        <Route path="alertas" element={can(r, 'admin') ? <Alerts /> : <Navigate to="../explorer" />} />
        <Route path="acessos" element={can(r, 'admin') ? <Access /> : <Navigate to="../explorer" />} />
        <Route path="auditoria" element={can(r, 'admin') ? <Audit /> : <Navigate to="../explorer" />} />
        <Route path="finops" element={can(r, 'viewer') ? <FinOps /> : <Navigate to="../explorer" />} />
        <Route path="ia" element={can(r, 'viewer') ? <AiAnalysis /> : <Navigate to="../explorer" />} />
        <Route path="*" element={<Navigate to="explorer" replace />} />
      </Routes>
    </Shell>
  )
}

// ── moldura ──
function Shell({ tenant, children }: { tenant?: TenantRef; children: ReactNode }) {
  const { me, setMe } = useSession()
  const nav = useNavigate()
  const [menu, setMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (tenant?.color) applyTenantTheme(tenant.color)
    else resetTenantTheme()
    return () => { resetTenantTheme() }
  }, [tenant?.id, tenant?.color])
  useEffect(() => {
    if (!menu) return
    const onDown = (e: PointerEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('pointerdown', onDown); window.removeEventListener('keydown', onKey) }
  }, [menu])
  const r = tenant?.role
  const links: [string, string, boolean][] = tenant ? [
    ['explorer', 'Explorer', true], ['finops', 'FinOps & Custos', can(r, 'viewer')], ['ia', 'IA Analisando', can(r, 'viewer')], ['coletas', 'Coletas', can(r, 'viewer')], ['contas', 'Contas AWS', can(r, 'viewer')],
    ['agendamentos', 'Agendamentos', can(r, 'viewer')], ['alertas', 'Alertas', can(r, 'admin')], ['acessos', 'Acessos', can(r, 'admin')],
    ['auditoria', 'Auditoria', can(r, 'admin')],
  ] : []
  const logout = async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); setMe(null) }
  return (
    <div className="shell">
      <header className="top">
        <div className="brand" onClick={() => nav('/')}>
          {tenant?.logo ? (
            <img src={tenant.logo} alt={tenant.name} className="brand-client-logo" />
          ) : (
            <img src={logoWhite} alt="G3 Solutions" />
          )}
          <div>
            <b>{tenant ? tenant.name : me.app_name}</b>
            <span>{tenant ? `${me.app_name} · Documentação viva` : 'Documentação viva da infraestrutura de cloud'}</span>
          </div>
        </div>
        {me.tenants.length > 0 && (
          <select className="tenant-sel" value={tenant?.id ?? ''} onChange={(e) => nav(`/t/${e.target.value}/explorer`)} aria-label="Cliente">
            {!tenant && <option value="">Selecionar cliente…</option>}
            {me.tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        )}
        <nav className="tabs-top">
          {links.filter((l) => l[2]).map(([to, label]) => <NavLink key={to} to={`/t/${tenant!.id}/${to}`}>{label}</NavLink>)}
          {tenant && can(r, 'admin') && <a href={`/assumerole.html?tenant_id=${tenant.id}`} target="_blank" rel="noopener noreferrer">Assume Role ↗</a>}
        </nav>
        <div className="user" ref={menuRef}>
          {tenant && <span className="role-tag">{ROLE_LABEL[tenant.role]}</span>}
          <button className="avatar" onClick={() => setMenu(!menu)} aria-label="Menu do usuário" aria-expanded={menu}>{(me.name || me.email).slice(0, 1).toUpperCase()}</button>
          {menu && (
            <div className="user-pop">
              <div className="who"><b>{me.name}</b><span>{me.email}</span></div>
              <button onClick={() => { setMenu(false); nav('/conta') }}>Minha conta e MFA</button>
              <a href={tenant ? `/assumerole.html?tenant_id=${tenant.id}` : '/assumerole.html'} target="_blank" rel="noopener noreferrer" onClick={() => setMenu(false)}>Assistente Assume Role ↗</a>
              {me.is_superadmin && <button onClick={() => { setMenu(false); nav('/plataforma') }}>Administração da plataforma</button>}
              <button onClick={logout}>Sair</button>
            </div>
          )}
        </div>
      </header>
      <main className={tenant && location.pathname.endsWith('/explorer') ? 'main full' : 'main'}>{children}</main>
    </div>
  )
}

// ── login ──
function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-hero">
        <img src={logoColor} alt="G3 Solutions" />
        <h1>DocOps<span>Documentação viva da infraestrutura de cloud</span></h1>
        <ul><li>Inventário multi-conta e multi-região</li><li>Achados de segurança, resiliência e custo</li><li>Histórico, mudanças e alertas</li></ul>
      </div>
      <div className="auth-panel">{children}</div>
    </div>
  )
}

function Login({ onOk }: { onOk: (m: Me) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [needTotp, setNeedTotp] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { onOk(await api<Me>('/api/auth/login', { body: { email, password, totp: needTotp ? totp : null } })) }
    catch (x: any) {
      if (x.data?.mfa_required) { setNeedTotp(true); if (needTotp) setErr(x.message) } else setErr(x.message)
    } finally { setBusy(false) }
  }
  return (
    <AuthFrame>
      <form className="auth-form" onSubmit={submit}>
        <h2>Entrar</h2>
        {!needTotp ? <>
          <Field label="E-mail"><input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></Field>
          <Field label="Senha"><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
        </> : <Field label="Código do autenticador" hint="6 dígitos do Google Authenticator, Microsoft Authenticator, 1Password etc.">
          <input inputMode="numeric" autoComplete="one-time-code" value={totp} onChange={(e) => setTotp(e.target.value)} maxLength={8} required autoFocus />
        </Field>}
        {err && <div className="alert bad">{err}</div>}
        <Btn kind="primary" busy={busy} type="submit">{needTotp ? 'Validar código' : 'Entrar'}</Btn>
        {needTotp && <button type="button" className="link" onClick={() => { setNeedTotp(false); setTotp('') }}>Voltar</button>}
      </form>
    </AuthFrame>
  )
}

function ForcePassword({ me, onOk }: { me: Me; onOk: (m: Me) => void }) {
  const [cur, setCur] = useState('')
  const [n1, setN1] = useState('')
  const [n2, setN2] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (n1 !== n2) return setErr('As senhas novas não conferem.')
    setBusy(true); setErr('')
    try { onOk(await api<Me>('/api/auth/password', { body: { current: cur, new: n1 } })); toast('Senha definida') } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <AuthFrame>
      <form className="auth-form" onSubmit={submit}>
        <h2>Defina sua senha</h2>
        <p className="muted">Olá, {me.name || me.email}. Por segurança, troque a senha provisória antes de continuar.</p>
        <Field label="Senha provisória"><input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
        <Field label="Nova senha" hint="Mínimo de 12 caracteres, com letras, números e símbolos."><input type="password" autoComplete="new-password" value={n1} onChange={(e) => setN1(e.target.value)} required /></Field>
        <Field label="Repita a nova senha"><input type="password" autoComplete="new-password" value={n2} onChange={(e) => setN2(e.target.value)} required /></Field>
        {err && <div className="alert bad">{err}</div>}
        <Btn kind="primary" busy={busy} type="submit">Salvar e continuar</Btn>
      </form>
    </AuthFrame>
  )
}
