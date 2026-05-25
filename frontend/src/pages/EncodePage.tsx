import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import {
  Activity,
  AlertTriangle,
  Eraser,
  Film,
  Square,
  X as XIcon,
} from 'lucide-react'
import { encode, jobs as jobsApi } from '@/api/endpoints'
import { useEncode } from '@/stores/encode'
import { useToast } from '@/components/ui/Toast'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { StatusBadge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/EmptyState'
import { formatBytes, formatDuration } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { Job, WSEvent } from '@/types/api'

export function EncodePage() {
  const toast = useToast()
  const qc = useQueryClient()
  const { running, total, doneFiles, currentIdx, currentFile, pct, speed, fps, eta, savedMb, jobs, events } =
    useEncode()
  const fetchAndSync = useEncode((s) => s.fetchAndSync)
  // Pull fresh state every time the user lands on this page. Belt-and-
  // suspenders: SessionSync already does this on app mount and on WS
  // events, but a navigation to /encode right after starting an encode
  // shouldn't depend on the WS having delivered a message yet.
  useEffect(() => { fetchAndSync() }, [fetchAndSync])
  // Polling fallback only while a session is running. WebSocket events
  // are the primary signal; this is a safety net for missed messages.
  useQuery({
    queryKey: ['session.poll'],
    queryFn: () => encode.activeSession(),
    refetchInterval: running ? 10_000 : false,
    enabled: running,
  })

  const stopMut = useMutation({
    mutationFn: () => encode.stop(),
    onSuccess: (r) => toast.push(`Stop requested (${r.cancelled} cancelled)`, 'warning'),
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const resetMut = useMutation({
    mutationFn: () => encode.forceReset(),
    onSuccess: () => toast.push('Force-reset complete', 'warning'),
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const cancelJobMut = useMutation({
    mutationFn: (id: number) => jobsApi.cancel(id),
    onSuccess: (r: { status?: string; action?: string }) => {
      toast.push(
        r?.action === 'session_stop'
          ? 'Current file: stopping the whole session'
          : 'Removed from queue',
        'warning',
      )
      // Force a session refresh so the queue list updates immediately
      // even if the WebSocket message races us.
      qc.invalidateQueries({ queryKey: ['session.poll'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const overall = total > 0 ? ((doneFiles + (pct || 0) / 100) / total) * 100 : 0

  // Auto-scroll log
  const logRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [events.length])
  const clearLog = useEncode((s) => s.clearEvents)

  if (!running && jobs.length === 0) {
    return (
      <PageContainer>
        <PageHeader icon={Film} title="Encode" description="Live progress for the active encoding session." />
        <EmptyState
          icon={Film}
          title="No active session"
          description="Pick files on the Scan page and hit Encode to start a new session here."
        />
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader
        icon={Film}
        title="Encode"
        description={running ? 'Live progress for the active encoding session.' : 'Last session — no encoding in progress.'}
        actions={
          running ? (
            <Button
              variant="danger"
              onClick={() => {
                if (confirm('Stop the current encode and cancel the queue?')) stopMut.mutate()
              }}
              disabled={stopMut.isPending}
            >
              <Square size={14} />
              {stopMut.isPending ? 'Stopping…' : 'Stop'}
            </Button>
          ) : (
            <Button
              variant="ghost"
              onClick={() => {
                if (confirm('Force-reset session state? Use this if the queue is stuck.')) resetMut.mutate()
              }}
            >
              <Eraser size={14} /> Force-reset
            </Button>
          )
        }
      />

      <section className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-semibold">
            {running && <Activity size={16} className="text-success animate-pulse" />}
            {running ? `Encoding ${currentIdx} of ${total}` : 'Session ended'}
          </div>
          <div className="text-sm text-fg-muted">
            Saved: <span className="font-semibold text-success">{formatBytes(savedMb)}</span>
          </div>
        </div>
        <ProgressBar value={overall} />
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-fg-muted">
          <span>Files: <span className="text-fg font-medium">{doneFiles}</span> / {total}</span>
          <span>Overall: <span className="text-fg font-medium">{overall.toFixed(1)}%</span></span>
        </div>
      </section>

      {currentFile && (
        <section className="card p-5 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-xs text-fg-muted mb-1">Current file</div>
              <div className="font-medium text-sm truncate" title={currentFile}>{currentFile}</div>
            </div>
            <StatusBadge status="encoding" />
          </div>
          <ProgressBar value={pct} />
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-fg-muted">
            <span>{(pct || 0).toFixed(1)}%</span>
            {speed && <span>Speed: <span className="text-fg">{speed}</span></span>}
            {fps && <span>FPS: <span className="text-fg">{fps}</span></span>}
            {eta > 0 && <span>ETA: <span className="text-fg">{formatDuration(eta)}</span></span>}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <section className="card lg:col-span-3 overflow-hidden">
          <header className="px-5 py-3 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold">Queue · {jobs.length} file{jobs.length === 1 ? '' : 's'}</h2>
          </header>
          {jobs.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-fg-muted">No jobs.</div>
          ) : (
            <ul className="max-h-[60vh] overflow-y-auto divide-y divide-border">
              {jobs.map((j) => (
                <QueueRow
                  key={j.id}
                  job={j}
                  pending={cancelJobMut.isPending && cancelJobMut.variables === j.id}
                  onCancel={() => {
                    const isCurrent = j.status === 'encoding'
                    const msg = isCurrent
                      ? `Cancel the file currently encoding?\n\n${j.filename}\n\nThis stops the running ffmpeg and the rest of the queue (per-file-only stop is a planned improvement).`
                      : `Remove this file from the queue?\n\n${j.filename}`
                    if (confirm(msg)) cancelJobMut.mutate(j.id)
                  }}
                />
              ))}
            </ul>
          )}
        </section>

        <section className="card lg:col-span-2 overflow-hidden">
          <header className="px-5 py-3 border-b border-border flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Live log</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs text-fg-muted">{events.length} events</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearLog}
                disabled={events.length === 0}
                title="Clear the log on screen (does not affect the backend)"
              >
                <Eraser size={12} /> Clear
              </Button>
            </div>
          </header>
          <div
            ref={logRef}
            className="bg-bg font-mono text-[11px] leading-relaxed p-3 max-h-[60vh] min-h-[300px] overflow-auto"
          >
            {events.length === 0 ? (
              <div className="text-fg-muted text-center py-8">Waiting for events…</div>
            ) : (
              events.map((e, i) => <LogLine key={i} ev={e} />)
            )}
          </div>
        </section>
      </div>

      {!running && jobs.some((j) => j.status === 'failed') && (
        <div className="card p-3 flex items-start gap-2 border-warning/40">
          <AlertTriangle size={14} className="text-warning mt-0.5" />
          <span className="text-xs text-fg-muted">
            Some jobs failed. Open Admin Logs or History to investigate.
          </span>
        </div>
      )}
    </PageContainer>
  )
}

// Status values that cannot be cancelled (job already finished).
const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'completed', 'failed', 'skipped', 'interrupted',
])

function QueueRow({ job, pending, onCancel }: { job: Job; pending: boolean; onCancel: () => void }) {
  const terminal = TERMINAL_STATUSES.has(job.status)
  return (
    <li className="px-4 py-2.5 flex items-center gap-3 text-sm">
      <StatusBadge status={job.status} className="shrink-0" />
      <span className="flex-1 truncate font-mono text-xs" title={job.path}>{job.filename}</span>
      {job.status === 'encoding' && job.pct != null && (
        <span className="text-xs text-accent">{job.pct.toFixed(1)}%</span>
      )}
      {job.status === 'completed' && job.space_saved_mb > 0 && (
        <span className="text-xs text-success">−{formatBytes(job.space_saved_mb)}</span>
      )}
      <span className="text-xs text-fg-muted whitespace-nowrap">{formatBytes(job.original_size_mb)}</span>
      {/* Per-row cancel. Hidden for jobs that already terminated. */}
      {!terminal && (
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          aria-label={job.status === 'encoding' ? 'Cancel current encode' : 'Remove from queue'}
          title={
            job.status === 'encoding'
              ? 'Cancel the file currently encoding (stops the session — per-file cancel is a planned improvement)'
              : 'Remove from queue'
          }
          className={cn(
            'h-6 w-6 inline-flex items-center justify-center rounded-md border transition-colors shrink-0',
            'bg-bg-card text-fg-muted border-border hover:text-danger hover:border-danger/40',
            pending && 'opacity-50 cursor-not-allowed',
          )}
        >
          <XIcon size={12} />
        </button>
      )}
    </li>
  )
}

function LogLine({ ev }: { ev: WSEvent }) {
  const cls =
    ev.type === 'error' ? 'text-danger'
    : ev.type === 'skipped' ? 'text-warning'
    : ev.type === 'stopped' ? 'text-warning'
    : ev.type === 'queue_done' ? 'text-success'
    : ev.type === 'file_done' && ev.status === 'completed' ? 'text-success'
    : ev.type === 'file_start' ? 'text-accent'
    : ev.type === 'progress' ? 'text-fg-muted'
    : 'text-fg'
  const t = ev.time || ''
  let msg = ''
  switch (ev.type) {
    case 'queue_start': msg = `Queue started — ${ev.total} files`; break
    case 'queue_done':  msg = 'Queue complete'; break
    case 'queue_stopped': msg = 'Queue stopped'; break
    case 'file_start':  msg = `[${ev.idx}/${ev.total}] ${ev.file}`; break
    case 'file_done': {
      const s = ev.space_saved_mb
      msg = `  ✔ ${ev.status}${s ? ` — saved ${s.toFixed(1)} MB` : ''}`
      break
    }
    case 'step':     msg = `  • ${ev.msg}`; break
    case 'error':    msg = `  ✘ ${ev.msg}`; break
    case 'skipped':  msg = `  ↷ ${ev.msg}`; break
    case 'stopped':  msg = `  ■ ${ev.msg}`; break
    case 'progress': msg = `  ${(ev.pct || 0).toFixed(1)}% · ${ev.fps || 'N/A'} fps · ${ev.speed || 'N/A'} · ETA ${formatDuration(ev.eta || 0)}`; break
    default: msg = ev.msg || ev.type
  }
  return (
    <div className={cn('whitespace-pre-wrap', cls)}>
      {t && <span className="text-fg-muted">[{t}] </span>}
      {msg}
    </div>
  )
}
