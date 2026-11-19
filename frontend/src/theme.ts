// Motor de tema dinâmico por cliente — Edição ConecTI Cloud (Dark Mode + Glassmorphism)
// Preserva a base escura oficial ConecTI (#02060F / #060D1F) e adapta os acentos por cliente.

export const DEFAULT_TENANT_COLOR = '#06b6d4'

export const TENANT_PALETTE: { name: string; hex: string }[] = [
  { name: 'Ciano ConecTI', hex: '#06b6d4' },
  { name: 'Azul Cloud', hex: '#3b82f6' },
  { name: 'Azul Profundo', hex: '#1e40af' },
  { name: 'Esmeralda', hex: '#10b981' },
  { name: 'Índigo', hex: '#6366f1' },
  { name: 'Violeta', hex: '#8b5cf6' },
  { name: 'Âmbar', hex: '#f59e0b' },
  { name: 'Carmesim', hex: '#ef4444' },
]

function hexToHsl(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  const r = ((n >> 16) & 255) / 255
  const g = ((n >> 8) & 255) / 255
  const b = (n & 255) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  let h = 0
  let s = 0
  if (max !== min) {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break
      case g: h = (b - r) / d + 2; break
      default: h = (r - g) / d + 4; break
    }
    h *= 60
  }
  return [Math.round(h), Math.round(s * 100), Math.round(l * 100)]
}

const hsl = (h: number, s: number, l: number) =>
  `hsl(${h} ${Math.max(0, Math.min(100, Math.round(s)))}% ${Math.max(0, Math.min(100, Math.round(l)))}%)`

const THEME_KEYS = [
  '--brand', '--brand-600', '--leaf',
  '--pastel', '--pastel-300', '--pastel-100', '--pastel-50',
  '--line',
]

export function resetTenantTheme() {
  const root = document.documentElement.style
  for (const k of THEME_KEYS) root.removeProperty(k)
}

export function computeTenantVars(hex?: string | null): Record<string, string> | null {
  const clean = (hex || '').trim().toLowerCase()
  // Usa a identidade oficial ConecTI Ciano para padrão ou cor legada G3
  if (!clean || clean === DEFAULT_TENANT_COLOR || clean === '#4a7a37') return null
  const parsed = hexToHsl(clean)
  if (!parsed) return null
  const [h, rawS] = parsed
  const s = Math.max(48, Math.min(92, rawS))

  return {
    '--brand': hsl(h, s, 56),
    '--brand-600': hsl(h, s, 46),
    '--leaf': hsl(h, s, 64),
    '--pastel': hsl(h, s, 68),
    '--pastel-300': `hsla(${h}, ${s}%, 60%, 0.38)`,
    '--pastel-100': `hsla(${h}, ${s}%, 55%, 0.16)`,
    '--pastel-50': `hsla(${h}, ${s}%, 55%, 0.09)`,
    '--line': `hsla(${h}, ${s}%, 60%, 0.18)`,
  }
}

export function computeViewerThemeVars(hex?: string | null): Record<string, string> | null {
  const clean = (hex || '').trim().toLowerCase()
  const target = !clean || clean === '#4a7a37' ? DEFAULT_TENANT_COLOR : clean
  const parsed = hexToHsl(target)
  if (!parsed) return null
  const [h, rawS] = parsed
  const s = Math.max(40, Math.min(82, rawS))
  return {
    '--navy-950': '#02060f',
    '--navy-900': '#060d1f',
    '--navy-800': '#0d1a36',
    '--navy-700': hsl(h, Math.min(72, s), 34),
    '--brand': hsl(h, s, 46),
    '--brand-600': hsl(h, s, 38),
    '--lav': hsl(h, s, 64),
    '--lav-300': hsl(h, s, 78),
    '--lav-100': hsl(h, Math.min(60, s), 92),
    '--lav-50': hsl(h, Math.min(45, s), 96),
  }
}

export function applyTenantTheme(hex?: string | null) {
  const vars = computeTenantVars(hex)
  if (!vars) {
    resetTenantTheme()
    return
  }
  const root = document.documentElement.style
  for (const [k, val] of Object.entries(vars)) root.setProperty(k, val)
}
