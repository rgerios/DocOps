// Cliente HTTP da API. A sessão vive num cookie HttpOnly; toda escrita envia X-DocOps (proteção CSRF).

export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

function messageOf(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: string }).message)
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  return `Erro ${status}`
}

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const method = opts.method || (opts.body !== undefined || opts.form ? 'POST' : 'GET')
  const headers: Record<string, string> = { 'X-DocOps': '1' }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body) }
  const r = await fetch(path, { method, headers, body, credentials: 'same-origin' })
  if (opts.raw && r.ok) return r as unknown as T
  const text = await r.text()
  let data: any = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!r.ok) {
    const detail = data?.detail ?? data
    if (r.status === 401 && !path.startsWith('/api/auth/login')) onUnauthorized()
    throw new ApiError(r.status, messageOf(detail, r.status), detail)
  }
  return data as T
}

export function downloadBlob(blob: Blob, name: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 4000)
}

export const escHtml = (s: unknown) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

export async function exportPdf(tenantId: number, html: string, filename: string) {
  const res = await api<Response>(`/api/tenants/${tenantId}/reports/pdf`, { body: { html, filename }, raw: true })
  const blob = await res.blob()
  downloadBlob(blob, filename)
}

// ── tipos ──
export type Role = 'client' | 'viewer' | 'analyst' | 'admin'
export const ROLE_LABEL: Record<Role, string> = { admin: 'Administrador', analyst: 'Analista', viewer: 'Leitor', client: 'Cliente' }
export const ROLE_LEVEL: Record<Role, number> = { client: 0, viewer: 1, analyst: 2, admin: 3 }
export const can = (role: Role | undefined, min: Role) => !!role && ROLE_LEVEL[role] >= ROLE_LEVEL[min]

export interface TenantRef { id: number; name: string; slug: string; color: string; logo?: string | null; role: Role }
export interface Me {
  id: number; email: string; name: string; is_superadmin: boolean; must_change_password: boolean
  totp_enabled: boolean; last_login: string | null; tenants: TenantRef[]; app_name: string
}
export interface CollectionRow {
  id: number; account_id: string; alias: string; source: string; status: 'queued' | 'running' | 'done' | 'failed'
  trigger: string; triggered_by: string | null; error: string | null; created_at: string; started_at: string | null
  finished_at: string | null; collected_at: string | null; summary: Record<string, any> | null
}
export interface AwsAccount {
  id: number; account_id: string; alias: string; role_arn: string | null; external_id: string | null
  regions: string[] | null; environment: string; active: boolean; last_collection: CollectionRow | null
}

// ── formatação ──
export const fmtDT = (s?: string | null) => (s ? new Date(s).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—')
export const fmtD = (s?: string | null) => (s ? new Date(s).toLocaleDateString('pt-BR') : '—')
export function ago(s?: string | null) {
  if (!s) return '—'
  const m = Math.floor((Date.now() - new Date(s).getTime()) / 60000)
  if (m < 1) return 'agora'
  if (m < 60) return `há ${m} min`
  const h = Math.floor(m / 60)
  if (h < 24) return `há ${h} h`
  const d = Math.floor(h / 24)
  return d === 1 ? 'há 1 dia' : `há ${d} dias`
}
