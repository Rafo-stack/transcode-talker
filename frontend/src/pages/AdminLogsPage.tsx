import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Clock,
  Eraser,
  Pause,
  Play,
  Shield,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { admin } from '@/api/endpoints'
import type { LogEntry } from '@/types/api'
import { cn } from '@/lib/utils'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'

const LEVELS = ['debug', 'info', 'warning', 'error', 'critical'] as const
type Level = (typeof LEVELS)[number]

const LEVEL_COLORS: Record<string, string> = {
  debug:    'text-fg-muted',
  info:     'text-sky-500',
  warning:  'text-yellow-500',
  error:    'text-red-500',
  critical: 'text-red-500 font-bold',
}

const RANGES: { label: string; minutes: number | null }[] = [
  { label: '5m', minutes: 5 },
  { label: '15m', minutes: 15 },
  { label: '30m', minutes: 30 },
  { label: '1h', minutes: 60 },
  { label: '4h', minutes: 240 },
  { label: '24h', minutes: 1440 },
  { label: 'All', minutes: null },
]

const INITIAL_FETCH = 1000
const MAX_ENTRIES = 2000

export function AdminLogsPage() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [paused, setPaused] = useState(false)
  const [connected, setConnected] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [selectedLevels, setSelectedLevels] = useState<Set<Level>>(() => new Set<Level>(LEVELS))
  const [rangeIndex, setRangeIndex] = useState(3)
  const [, forceTick] = useState(0)

  const pauseBufferRef = useRef<LogEntry[]>([])
  const pausedRef = useRef(false)
  const lastSeqRef = useRef(0)
  pausedRef.current = paused

  const ingest = useCallback((batch: LogEntry[]) => {
    if (!batch.length) return
    setEntries((prev) => {
      const next = [...prev, ...batch]
      if (next.length > MAX_ENTRIES) return next.slice(next.length - MAX_ENTRIES)
      return next
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    admin
      .recentLogs({ limit: INITIAL_FETCH })
      .then((res) => {
        if (cancelled) return
        lastSeqRef.current = res.last_seq || 0
        setEntries(res.items || [])
      })
      .catch(() => { /* keep page usable on back-fill failure */ })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const es = new EventSource(admin.streamUrl())
    es.onopen = () => { setConnected(true); setStreamError(null) }
    es.onerror = () => { setConnected(false); setStreamError('Stream disconnected — retrying…') }
    es.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data) as LogEntry
        if (data.seq && data.seq <= lastSeqRef.current) return
        lastSeqRef.current = data.seq
        if (pausedRef.current) pauseBufferRef.current.push(data)
        else ingest([data])
      } catch { /* malformed */ }
    }
    return () => { es.close() }
  }, [ingest])

  useEffect(() => {
    if (!paused && pauseBufferRef.current.length) {
      const batch = pauseBufferRef.current
      pauseBufferRef.current = []
      ingest(batch)
    }
  }, [paused, ingest])

  useEffect(() => {
    const t = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])

  const range = RANGES[rangeIndex]
  const cutoff = useMemo(() => range.minutes ? Date.now() - range.minutes * 60_000 : 0, [range])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const within: LogEntry[] = []
    for (const e of entries) {
      if (!selectedLevels.has(e.level as Level)) continue
      if (cutoff) {
        const t = Date.parse(e.ts)
        if (Number.isFinite(t) && t < cutoff) continue
      }
      if (q) {
        const hay = [e.event, e.logger, e.level, e.ts, ...Object.entries(e.fields).map(([k, v]) => `${k}=${stringify(v)}`)]
          .join(' ').toLowerCase()
        if (!hay.includes(q)) continue
      }
      within.push(e)
    }
    within.reverse()
    return within
  }, [entries, query, selectedLevels, cutoff])

  return (
    <PageContainer>
      <PageHeader
        icon={Shield}
        title="Admin · Logs"
        description="Live application logs, newest first. Streamed via SSE from the API container."
        actions={
          <div
            className={cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border',
              connected
                ? 'bg-success/10 text-success border-success/30'
                : 'bg-danger/10 text-danger border-danger/30',
            )}
          >
            {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
            {connected ? 'live' : 'offline'}
          </div>
        }
      />

      <section className="card p-3 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="input flex-1 min-w-[240px] max-w-xl"
            type="search"
            placeholder="Search event name, logger, field=value…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex items-center gap-1.5 flex-wrap">
            {LEVELS.map((lvl) => {
              const active = selectedLevels.has(lvl)
              return (
                <button
                  key={lvl}
                  onClick={() => setSelectedLevels((p) => {
                    const n = new Set(p); n.has(lvl) ? n.delete(lvl) : n.add(lvl); return n
                  })}
                  className={cn(
                    'px-2.5 py-1 rounded-md text-xs font-bold uppercase tracking-wide border transition-colors',
                    active
                      ? cn('bg-bg-card border-border', LEVEL_COLORS[lvl])
                      : 'bg-bg-subtle text-fg-muted/50 border-transparent hover:bg-bg-card',
                  )}
                >
                  {lvl}
                </button>
              )
            })}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button variant={paused ? 'secondary' : 'ghost'} size="sm" onClick={() => setPaused((v) => !v)}>
              {paused ? <Play size={12} /> : <Pause size={12} />}
              {paused ? 'Resume' : 'Pause'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEntries([])}>
              <Eraser size={12} /> Clear
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="label w-20 shrink-0 flex items-center gap-1">
            <Clock size={12} /> Range
          </span>
          {RANGES.map((r, i) => (
            <button
              key={r.label}
              onClick={() => setRangeIndex(i)}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs font-medium border transition-colors',
                i === rangeIndex
                  ? 'bg-accent text-white border-accent'
                  : 'bg-bg-subtle text-fg-muted border-border hover:bg-bg-card hover:text-fg',
              )}
            >
              {r.label}
            </button>
          ))}
          <div className="ml-auto text-xs text-fg-muted">
            Showing <span className="font-semibold text-fg">{filtered.length}</span> of {entries.length} buffered
          </div>
        </div>
      </section>

      {streamError && !connected && (
        <div className="card p-3 flex items-center gap-2 border-danger/40 text-xs">
          <AlertTriangle size={14} className="text-danger" /> {streamError}
        </div>
      )}

      <div
        className="card bg-[rgb(var(--bg))] font-mono text-xs leading-relaxed overflow-auto"
        style={{ height: 'calc(100vh - 320px)', minHeight: 400 }}
      >
        {paused && pauseBufferRef.current.length > 0 && (
          <div className="sticky top-0 z-10 m-2 px-3 py-1.5 text-xs text-yellow-500 bg-bg-card border border-yellow-500/30 rounded-md inline-block">
            {pauseBufferRef.current.length} buffered while paused — Resume to flush
          </div>
        )}
        {filtered.length === 0 ? (
          <div className="text-fg-muted text-center py-16">
            {entries.length === 0 ? 'Waiting for events…' : 'No entries match the current filter.'}
          </div>
        ) : (
          <div className="divide-y divide-border/30">
            {filtered.map((e) => <LogBlock key={e.seq} entry={e} />)}
          </div>
        )}
      </div>
    </PageContainer>
  )
}

const METHOD_COLORS: Record<string, string> = {
  GET:    'bg-sky-500/15 text-sky-500 border-sky-500/30',
  POST:   'bg-emerald-500/15 text-emerald-500 border-emerald-500/30',
  PUT:    'bg-amber-500/15 text-amber-500 border-amber-500/30',
  PATCH:  'bg-amber-500/15 text-amber-500 border-amber-500/30',
  DELETE: 'bg-red-500/15 text-red-500 border-red-500/30',
  HEAD:   'bg-fg-muted/15 text-fg-muted border-border',
  OPTIONS:'bg-fg-muted/15 text-fg-muted border-border',
}

function statusClass(status: number): string {
  if (status >= 500) return 'text-red-500 font-bold'
  if (status >= 400) return 'text-warning font-bold'
  if (status >= 300) return 'text-sky-500'
  if (status >= 200) return 'text-success'
  return 'text-fg-muted'
}

// Two-column key/value row. Used for both the structured HTTP block and
// the generic structured fields ("scan_folders: 5", etc.).
function FieldRow({ label, value, valueClass }: {
  label: string
  value: React.ReactNode
  valueClass?: string
}) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-fg-muted text-[11px] uppercase tracking-wide shrink-0 w-32">
        {label}
      </span>
      <span className={cn('text-fg break-all min-w-0', valueClass)}>{value}</span>
    </div>
  )
}

function LogBlock({ entry }: { entry: LogEntry }) {
  const cls = LEVEL_COLORS[entry.level] || 'text-fg'
  const fields = { ...(entry.fields || {}) }
  // Pluck HTTP fields out of the generic block so we can render them with
  // dedicated labels and colors.
  const ip = typeof fields.ip === 'string' ? fields.ip : null
  const method = typeof fields.method === 'string' ? fields.method : null
  const path = typeof fields.path === 'string' ? fields.path : null
  const status = typeof fields.status === 'number' ? fields.status : null
  if (ip) delete fields.ip
  if (method) delete fields.method
  if (path) delete fields.path
  if (status != null) delete fields.status
  delete fields.proto
  const isHttp = !!(method && path && status != null)
  const rest = Object.entries(fields)

  return (
    <div className="px-4 py-3 hover:bg-bg-subtle/40 transition-colors">
      {/* Header: timestamp · level · short event description */}
      <div className="flex items-baseline gap-3 flex-wrap mb-1.5">
        <span className="font-bold text-fg whitespace-nowrap">[{formatTs(entry.ts)}]</span>
        <span className={cn('uppercase font-bold tracking-wide whitespace-nowrap inline-block min-w-[64px]', cls)}>
          {entry.level}
        </span>
        <span className="text-accent font-semibold break-all">
          {entry.event || '(no event)'}
        </span>
        {entry.logger && entry.logger !== 'app' && (
          <span className="text-fg-muted text-[10px] uppercase tracking-wide">
            · {entry.logger}
          </span>
        )}
      </div>

      {/* Structured body. HTTP fields first (when present) in their own
          colored layout, then generic fields stacked one per line. */}
      {(isHttp || rest.length > 0) && (
        <div className="pl-2 mt-1 space-y-1">
          {isHttp && (
            <>
              <FieldRow
                label="IP"
                value={<span className="font-mono text-xs">{ip}</span>}
              />
              <FieldRow
                label="HTTP Method"
                value={
                  <span
                    className={cn(
                      'inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase border',
                      METHOD_COLORS[method!] ?? 'bg-fg-muted/15 text-fg-muted border-border',
                    )}
                  >
                    {method}
                  </span>
                }
              />
              <FieldRow label="Path" value={<span className="font-mono text-xs">{path}</span>} />
              <FieldRow
                label="HTTP Response"
                value={status}
                valueClass={cn('font-bold', statusClass(status!))}
              />
            </>
          )}
          {rest.map(([k, v]) => (
            <FieldRow key={k} label={k} value={stringify(v)} />
          ))}
        </div>
      )}
    </div>
  )
}

function stringify(v: unknown): string {
  if (v === null || v === undefined) return String(v)
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try { return JSON.stringify(v) } catch { return String(v) }
}

function formatTs(ts: string): string {
  const m = ts.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)/)
  return m ? `${m[1]} ${m[2]}` : ts
}
