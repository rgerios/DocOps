import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

// ── toast ──
type ToastKind = 'ok' | 'err' | 'info'
const ToastCtx = createContext<(msg: string, kind?: ToastKind) => void>(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; kind: ToastKind }[]>([])
  const push = useCallback((msg: string, kind: ToastKind = 'ok') => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, msg, kind }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), kind === 'err' ? 7000 : 3500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">{items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}</div>
    </ToastCtx.Provider>
  )
}

// ── componentes ──
export function Btn({ kind = 'default', small, busy, children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: 'default' | 'primary' | 'danger' | 'ghost'; small?: boolean; busy?: boolean }) {
  return <button {...p} disabled={p.disabled || busy} className={`btn ${kind} ${small ? 'sm' : ''} ${p.className || ''}`}>{busy ? <span className="spin" /> : null}{children}</button>
}

export function Card({ title, actions, children, pad = true, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; pad?: boolean; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && <header className="card-h"><h3>{title}</h3><div className="card-a">{actions}</div></header>}
      <div className={pad ? 'card-b' : ''}>{children}</div>
    </section>
  )
}

export function PageHead({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return <label className="field"><span className="lbl">{label}</span>{children}{hint && <span className="hint">{hint}</span>}</label>
}

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <header><h3>{title}</h3><button className="x" onClick={onClose} aria-label="Fechar">×</button></header>
        <div className="modal-b">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  )
}

const STATUS: Record<string, [string, string]> = {
  queued: ['na fila', 'warn'], running: ['coletando', 'blue'], done: ['concluída', 'ok'], failed: ['falhou', 'bad'],
}
export function StatusPill({ s }: { s: string }) {
  const [l, c] = STATUS[s] || [s, 'idle']
  return <span className={`pill ${c}`}>{s === 'running' && <span className="spin dark" />}{l}</span>
}
export const Pill = ({ children, kind = 'idle' }: { children: ReactNode; kind?: string }) => <span className={`pill ${kind}`}>{children}</span>

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><b>{title}</b>{children}</div>
}

export function Secret({ label, value }: { label: string; value: string }) {
  const toast = useToast()
  return (
    <div className="secret">
      <span className="lbl">{label}</span>
      <code>{value}</code>
      <Btn small onClick={() => { navigator.clipboard?.writeText(value); toast('Copiado') }}>Copiar</Btn>
    </div>
  )
}

// ── carregamento com recarga ──
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: (data: T | undefined) => number | null) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const reload = useCallback(async () => {
    try { setData(await fnRef.current()); setError(undefined) } catch (e: any) { setError(e.message) } finally { setLoading(false) }
  }, [])
  useEffect(() => { setLoading(true); reload() }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const ms = pollMs?.(data)
    if (!ms) return
    const t = setTimeout(reload, ms)
    return () => clearTimeout(t)
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, loading, reload, setData }
}

export function ErrorBox({ error }: { error?: string }) {
  return error ? <div className="alert bad">{error}</div> : null
}
