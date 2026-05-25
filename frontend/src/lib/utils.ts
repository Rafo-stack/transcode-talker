import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatBytes(mb: number): string {
  if (!mb || mb < 0.01) return '0 MB'
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`
  const gb = mb / 1024
  if (gb < 1024) return `${gb.toFixed(2)} GB`
  return `${(gb / 1024).toFixed(2)} TB`
}

export function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

export function truncatePath(path: string, maxLen = 60): string {
  if (path.length <= maxLen) return path
  const parts = path.split('/')
  if (parts.length <= 3) return '…' + path.slice(-(maxLen - 1))
  return `${parts[0]}/${parts[1]}/…/${parts.slice(-2).join('/')}`
}
