import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Palette, Save } from 'lucide-react'
import { config } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { useTheme } from '@/stores/theme'
import { cn } from '@/lib/utils'

// `--accent` is consumed by Tailwind via `rgb(var(--accent) / <alpha>)`,
// which expects a space-separated RGB triplet ("129 140 248"). The backend
// historically stored hex ("#8b5cf6"), so we translate at the boundary.
//
// Teal is the official brand color and sits first as the default preset.
// 20 presets in total. Each maps directly to a Tailwind palette so the
// chosen color reads cleanly against both dark and light backgrounds.
const ACCENT_PRESETS = [
  { name: 'Teal',     rgb: '20 184 166',  hex: '#14b8a6' },
  { name: 'Indigo',   rgb: '129 140 248', hex: '#818cf8' },
  { name: 'Violet',   rgb: '167 139 250', hex: '#a78bfa' },
  { name: 'Purple',   rgb: '168 85 247',  hex: '#a855f7' },
  { name: 'Fuchsia',  rgb: '217 70 239',  hex: '#d946ef' },
  { name: 'Pink',     rgb: '236 72 153',  hex: '#ec4899' },
  { name: 'Rose',     rgb: '251 113 133', hex: '#fb7185' },
  { name: 'Red',      rgb: '239 68 68',   hex: '#ef4444' },
  { name: 'Orange',   rgb: '249 115 22',  hex: '#f97316' },
  { name: 'Amber',    rgb: '251 191 36',  hex: '#fbbf24' },
  { name: 'Yellow',   rgb: '234 179 8',   hex: '#eab308' },
  { name: 'Lime',     rgb: '132 204 22',  hex: '#84cc16' },
  { name: 'Green',    rgb: '34 197 94',   hex: '#22c55e' },
  { name: 'Emerald',  rgb: '52 211 153',  hex: '#34d399' },
  { name: 'Cyan',     rgb: '34 211 238',  hex: '#22d3ee' },
  { name: 'Sky',      rgb: '14 165 233',  hex: '#0ea5e9' },
  { name: 'Blue',     rgb: '59 130 246',  hex: '#3b82f6' },
  { name: 'Slate',    rgb: '100 116 139', hex: '#64748b' },
  { name: 'Zinc',     rgb: '113 113 122', hex: '#71717a' },
  { name: 'Stone',    rgb: '120 113 108', hex: '#78716c' },
]

const DEFAULT_ACCENT = ACCENT_PRESETS[0].rgb

function hexToRgbTriplet(hex: string): string | null {
  const m = hex.trim().match(/^#?([0-9a-f]{6})$/i)
  if (!m) return null
  const n = parseInt(m[1], 16)
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`
}

function rgbTripletToHex(rgb: string): string {
  const parts = rgb.trim().split(/\s+/).map((x) => parseInt(x, 10))
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return '#000000'
  return '#' + parts.map((n) => Math.max(0, Math.min(255, n)).toString(16).padStart(2, '0')).join('')
}

function normalizeAccent(stored: string | undefined): string {
  if (!stored) return DEFAULT_ACCENT
  if (/^\s*\d+\s+\d+\s+\d+\s*$/.test(stored)) return stored.trim()
  const rgb = hexToRgbTriplet(stored)
  return rgb ?? DEFAULT_ACCENT
}

export function CustomizePage() {
  const toast = useToast()
  const qc = useQueryClient()
  const theme = useTheme((s) => s.theme)
  const applyTheme = useTheme((s) => s.apply)
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: config.get })

  const [accent, setAccent] = useState<string>(DEFAULT_ACCENT)

  // Used to distinguish "the page loaded and populated the preset selection
  // from saved config" (must NOT touch the live --accent) from "user clicked
  // a preset" (must update --accent for live preview). Bug: the previous
  // version applied any stored value on mount, which meant visiting Customize
  // recoloured the entire UI from the leftover legacy config (#8b5cf6).
  const userInteractedRef = useRef(false)

  useEffect(() => {
    if (cfgQ.data && !userInteractedRef.current) {
      setAccent(normalizeAccent(cfgQ.data.accent_color as string | undefined))
    }
  }, [cfgQ.data])

  // Apply live preview ONLY when the user has explicitly picked a preset.
  // Otherwise the global :root accent (defined in styles.css) stays as the
  // single source of truth.
  useEffect(() => {
    if (userInteractedRef.current) {
      document.documentElement.style.setProperty('--accent', accent)
    }
  }, [accent])

  const pickAccent = (rgb: string) => {
    userInteractedRef.current = true
    setAccent(rgb)
  }

  const saveMut = useMutation({
    mutationFn: () => config.update({ accent_color: accent, theme }),
    onSuccess: () => {
      toast.push('Appearance saved', 'success')
      qc.invalidateQueries({ queryKey: ['config'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  return (
    <PageContainer>
      <PageHeader icon={Palette} title="Customize" description="Theme and accent color." />

      <section className="card p-5 space-y-3">
        <h2 className="text-sm font-semibold">Theme</h2>
        <div className="flex gap-2">
          {(['dark', 'light'] as const).map((t) => (
            <button
              key={t}
              onClick={() => applyTheme(t)}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium border transition-colors',
                theme === t
                  ? 'bg-accent text-white border-accent'
                  : 'bg-bg-subtle text-fg-muted border-border hover:bg-bg-card hover:text-fg',
              )}
            >
              {t === 'dark' ? 'Dark' : 'Light'}
            </button>
          ))}
        </div>
      </section>

      <section className="card p-5 space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Accent color</h2>
            <p className="text-xs text-fg-muted mt-1">
              Teal is the project default. Click a preset for a live preview, or pick a custom color. Save to persist.
            </p>
          </div>
          {/* Custom color picker. The native <input type="color"> always
              returns hex; we feed it through hexToRgbTriplet so the rest of
              the app keeps using the Tailwind-compatible "r g b" format. */}
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <span className="text-xs text-fg-muted">Custom:</span>
            <input
              type="color"
              value={rgbTripletToHex(accent)}
              onChange={(e) => {
                const rgb = hexToRgbTriplet(e.target.value)
                if (rgb) pickAccent(rgb)
              }}
              className="h-8 w-12 rounded border border-border cursor-pointer bg-transparent p-0"
              aria-label="Custom accent color"
            />
            <code className="text-xs font-mono text-fg-muted">{rgbTripletToHex(accent)}</code>
          </label>
        </div>
        <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-10 gap-2">
          {ACCENT_PRESETS.map((p) => (
            <button
              key={p.name}
              onClick={() => pickAccent(p.rgb)}
              className={cn(
                'flex flex-col items-center gap-1 px-2 py-2 rounded-lg border transition-colors',
                accent === p.rgb ? 'border-accent ring-2 ring-accent/30' : 'border-border hover:bg-bg-subtle',
              )}
            >
              <span className="h-6 w-6 rounded-md" style={{ background: `rgb(${p.rgb})` }} />
              <span className="text-xs">{p.name}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="flex justify-end">
        <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
          <Save size={14} /> {saveMut.isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </PageContainer>
  )
}
