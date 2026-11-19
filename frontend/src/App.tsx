import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, can, ROLE_LABEL, setUnauthorizedHandler, type Me, type Role, type TenantRef } from './api'
import logoWhite from './assets/logo-white.png'
import logoColor from './assets/logo-color.png'
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

// ── ícones minimalistas (16px stroke) ──
function NavIcon({ name }: { name: string }) {
  const p = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
  switch (name) {
    case 'explorer': return <svg {...p}><circle cx="12" cy="12" r="9" /><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" /></svg>
    case 'finops': return <svg {...p}><line x1="12" y1="2" x2="12" y2="22" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></svg>
    case 'ia': return <svg {...p}><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" /><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z" /></svg>
    case 'coletas': return <svg {...p}><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" /><path d="M16 16h5v5" /></svg>
    case 'contas': return <svg {...p}><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" /></svg>
    case 'agendamentos': return <svg {...p}><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>
    case 'alertas': return <svg {...p}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
    case 'acessos': return <svg {...p}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></svg>
    case 'auditoria': return <svg {...p}><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l4 2" /></svg>
    case 'ext': return <svg {...p}><path d="M7 17 17 7" /><path d="M7 7h10v10" /></svg>
    case 'admin': return <svg {...p}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /></svg>
    case 'menu': return <svg {...p}><line x1="4" y1="6" x2="20" y2="6" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="18" x2="20" y2="18" /></svg>
    case 'shield': return <svg {...p}><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
    default: return <svg {...p}><circle cx="12" cy="12" r="4" /></svg>
  }
}

const ROUTE_TITLES: Record<string, string> = {
  explorer: 'Explorer',
  finops: 'FinOps & Custos',
  ia: 'IA Analisando',
  coletas: 'Coletas',
  contas: 'Contas AWS',
  agendamentos: 'Agendamentos',
  alertas: 'Alertas',
  acessos: 'Acessos',
  auditoria: 'Auditoria',
  conta: 'Minha conta e MFA',
  plataforma: 'Administração da plataforma',
}

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

// ── moldura (Sidebar + Topbar Enterprise Light) ──
function Shell({ tenant, children }: { tenant?: TenantRef; children: ReactNode }) {
  const { me, setMe } = useSession()
  const nav = useNavigate()
  const loc = useLocation()
  const [menu, setMenu] = useState(false)
  const [sideOpen, setSideOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setSideOpen(false) }, [loc.pathname])
  useEffect(() => {
    if (!menu) return
    const onDown = (e: PointerEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('pointerdown', onDown); window.removeEventListener('keydown', onKey) }
  }, [menu])

  const r = tenant?.role
  const groups: { title: string; items: [string, string, boolean][] }[] = tenant ? [
    {
      title: 'Principal',
      items: [
        ['explorer', 'Explorer', true],
        ['finops', 'FinOps & Custos', can(r, 'viewer')],
        ['ia', 'IA Analisando', can(r, 'viewer')],
      ],
    },
    {
      title: 'Operação',
      items: [
        ['coletas', 'Coletas', can(r, 'viewer')],
        ['contas', 'Contas AWS', can(r, 'viewer')],
        ['agendamentos', 'Agendamentos', can(r, 'viewer')],
      ],
    },
    {
      title: 'Governança',
      items: [
        ['alertas', 'Alertas', can(r, 'admin')],
        ['acessos', 'Acessos', can(r, 'admin')],
        ['auditoria', 'Auditoria', can(r, 'admin')],
      ],
    },
  ] : []

  const pathSeg = loc.pathname.split('/').filter(Boolean).pop() || ''
  const pageTitle = ROUTE_TITLES[pathSeg] || (loc.pathname.startsWith('/plataforma') ? 'Administração da plataforma' : 'DocOps')
  const isExplorer = Boolean(tenant && loc.pathname.endsWith('/explorer'))
  const logout = async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); setMe(null) }

  return (
    <div className="shell">
      {sideOpen && <div className="side-backdrop" onClick={() => setSideOpen(false)} />}
      <aside className={`sidebar ${sideOpen ? 'open' : ''}`}>
        <div className="side-top">
          <button type="button" className="brand" onClick={() => nav('/')}>
            <img src={logoColor} alt="G3 Solutions" />
            <div>
              <b>{me.app_name}</b>
              <span>by G3 Solutions</span>
            </div>
          </button>

          {me.tenants.length > 0 && (
            <div className="tenant-box">
              <span className="tenant-dot" />
              <select
                className="tenant-sel"
                value={tenant?.id ?? ''}
                onChange={(e) => nav(`/t/${e.target.value}/explorer`)}
                aria-label="Selecionar cliente"
              >
                {!tenant && <option value="">Selecionar cliente…</option>}
                {me.tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
          )}
        </div>

        <nav className="side-nav" aria-label="Navegação principal">
          {groups.map((g) => {
            const visible = g.items.filter((x) => x[2])
            if (!visible.length) return null
            return (
              <div key={g.title} className="nav-group">
                <span className="nav-group-lbl">{g.title}</span>
                {visible.map(([to, label]) => (
                  <NavLink key={to} to={`/t/${tenant!.id}/${to}`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                    <NavIcon name={to} />
                    <span>{label}</span>
                  </NavLink>
                ))}
              </div>
            )
          })}

          {me.is_superadmin && (
            <div className="nav-group">
              <span className="nav-group-lbl">Plataforma</span>
              <NavLink to="/plataforma" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <NavIcon name="admin" />
                <span>Administração</span>
              </NavLink>
            </div>
          )}
        </nav>

        <div className="side-foot">
          {tenant && can(r, 'admin') && (
            <a className="side-ext" href={`/assumerole.html?tenant_id=${tenant.id}`} target="_blank" rel="noopener noreferrer">
              <span>Assistente Assume Role</span>
              <NavIcon name="ext" />
            </a>
          )}

          <div className="user" ref={menuRef}>
            <button type="button" className="user-trigger" onClick={() => setMenu(!menu)} aria-label="Menu do usuário" aria-expanded={menu}>
              <span className="avatar">{(me.name || me.email).slice(0, 1).toUpperCase()}</span>
              <span className="user-meta">
                <b>{me.name || me.email}</b>
                <span>{tenant ? ROLE_LABEL[tenant.role] : (me.is_superadmin ? 'Superadmin' : me.email)}</span>
              </span>
              <span className="user-caret">▾</span>
            </button>
            {menu && (
              <div className="user-pop">
                <div className="who"><b>{me.name || 'Usuário'}</b><span>{me.email}</span></div>
                <button type="button" onClick={() => { setMenu(false); nav('/conta') }}>Minha conta e MFA</button>
                <a href={tenant ? `/assumerole.html?tenant_id=${tenant.id}` : '/assumerole.html'} target="_blank" rel="noopener noreferrer" onClick={() => setMenu(false)}>Assistente Assume Role ↗</a>
                {me.is_superadmin && <button type="button" onClick={() => { setMenu(false); nav('/plataforma') }}>Administração da plataforma</button>}
                <button type="button" className="danger-item" onClick={logout}>Sair</button>
              </div>
            )}
          </div>
        </div>
      </aside>

      <div className="shell-body">
        <header className="topbar">
          <button type="button" className="menu-btn" onClick={() => setSideOpen((v) => !v)} aria-label="Abrir navegação">
            <NavIcon name="menu" />
          </button>
          <div className="crumb">
            {tenant && <><span className="crumb-tenant">{tenant.name}</span><span className="crumb-sep">/</span></>}
            <span className="crumb-cur">{pageTitle}</span>
          </div>
          <div className="topbar-right">
            {tenant && <span className="role-tag">{ROLE_LABEL[tenant.role]}</span>}
          </div>
        </header>
        <main className={isExplorer ? 'main full' : 'main'}>{children}</main>
      </div>
    </div>
  )
}

// ── login ──
function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-hero">
        <div className="auth-brand">
          <img src={logoWhite} alt="G3 Solutions" />
        </div>
        <div className="auth-copy">
          <span className="auth-kicker">Plataforma corporativa · G3 Solutions</span>
          <h1>Documentação viva da sua infraestrutura em nuvem.</h1>
          <p>Inventário contínuo, governança de custos e análise inteligente em um único painel multi-tenant.</p>
          <ul>
            <li>Inventário multi-conta e multi-região com linha do tempo</li>
            <li>FinOps &amp; AWS Well-Architected com cálculo de economia</li>
            <li>Análise assistida por IA sobre os dados reais do ambiente</li>
          </ul>
        </div>
        <div className="auth-foot">
          <NavIcon name="shield" />
          <span>Criptografia em repouso Fernet · Autenticação MFA TOTP</span>
        </div>
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
        <div className="auth-form-head">
          <h2>Entrar no DocOps</h2>
          <p className="muted">Acesse com suas credenciais corporativas.</p>
        </div>
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
