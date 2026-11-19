// Motor de tema dinâmico por cliente (Multi-Tenant Branding)
// Gera toda a escala de variáveis CSS do DocOps a partir da cor principal (#rrggbb) do cliente.

export const DEFAULT_TENANT_COLOR = '#4a7a37'

export const TENANT_PALETTE: { name: string; hex: string }[] = [
  { name: 'Verde G3', hex: '#4a7a37' },
  { name: 'Azul Royal', hex: '#2563eb' },
  { name: 'Petróleo', hex: '#0f766e' },
  { name: 'Índigo', hex: '#4f46e5' },
  { name: 'Roxo', hex: '#7c3aed' },
  { name: 'Laranja', hex: '#c2570a' },
  { name: 'Carmesim', hex: '#b91c1c' },
  { name: 'Grafite', hex: '#334155' },
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
  '--g-950', '--g-900', '--g-800', '--g-700',
  '--brand', '--brand-600', '--leaf',
  '--pastel', '--pastel-300', '--pastel-100', '--pastel-50',
  '--bg', '--line', '--line-2',
]

export function resetTenantTheme() {
  const root = document.documentElement.style
  for (const k of THEME_KEYS) root.removeProperty(k)
}

export function computeTenantVars(hex?: string | null): Record<string, string> | null {
  if (!hex || hex.toLowerCase() === DEFAULT_TENANT_COLOR) return null
  const parsed = hexToHsl(hex)
  if (!parsed) return null
  const [h, rawS, rawL] = parsed
  // Normaliza saturação e luminosidade para manter contraste legível em qualquer cor escolhida
  const s = Math.max(12, Math.min(78, rawS))
  const brandL = Math.max(34, Math.min(48, rawL))
  const darkS = Math.min(55, Math.max(18, Math.round(s * 0.72)))
  const softS = Math.min(48, Math.max(14, Math.round(s * 0.65)))
  const tintS = Math.min(28, Math.max(8, Math.round(s * 0.35)))

  return {
    '--g-950': hsl(h, darkS, 12),
    '--g-900': hsl(h, darkS, 17),
    '--g-800': hsl(h, darkS, 23),
    '--g-700': hsl(h, Math.min(68, Math.round(s * 0.85)), Math.max(26, brandL - 8)),
    '--brand': hsl(h, s, Math.min(54, brandL + 5)),
    '--brand-600': hsl(h, s, brandL),
    '--leaf': hsl(h, s, Math.min(58, brandL + 9)),
    '--pastel': hsl(h, softS, 68),
    '--pastel-300': hsl(h, softS, 80),
    '--pastel-100': hsl(h, softS, 91),
    '--pastel-50': hsl(h, softS, 96),
    '--bg': hsl(h, tintS, 97),
    '--line': hsl(h, tintS, 89),
    '--line-2': hsl(h, tintS, 93),
  }
}

export function computeViewerThemeVars(hex?: string | null): Record<string, string> | null {
  const v = computeTenantVars(hex)
  if (!v) return null
  return {
    '--navy-950': v['--g-950'],
    '--navy-900': v['--g-900'],
    '--navy-800': v['--g-800'],
    '--navy-700': v['--g-700'],
    '--brand': v['--brand'],
    '--brand-600': v['--brand-600'],
    '--lav': v['--pastel'],
    '--lav-300': v['--pastel-300'],
    '--lav-100': v['--pastel-100'],
    '--lav-50': v['--pastel-50'],
    '--bg': v['--bg'],
    '--line': v['--line'],
    '--line-2': v['--line-2'],
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
