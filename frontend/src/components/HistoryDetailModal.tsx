import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Modal } from './ui/Modal'
import { StatusBadge } from './ui/Badge'
import { jobs } from '../api/endpoints'
import type { HistoryRecord, MediaStream, ParsedMetadata } from '../types/api'

interface HistoryDetailModalProps {
  record: HistoryRecord | null
  onClose: () => void
}

type TabKey = 'summary' | 'source' | 'encoded' | 'logs' | 'command'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'summary', label: 'Summary' },
  { key: 'source', label: 'Source streams' },
  { key: 'encoded', label: 'Encoded streams' },
  { key: 'logs', label: 'Logs' },
  { key: 'command', label: 'ffmpeg command' },
]

// ───── helpers ─────

function safeParse(raw: string | null | undefined): ParsedMetadata | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as ParsedMetadata
  } catch {
    return null
  }
}

function fmtBytes(mb?: number | null): string {
  if (mb == null) return '—'
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`
  return `${mb.toFixed(1)} MB`
}

function fmtDuration(secs?: number | null): string {
  if (secs == null) return '—'
  const s = Math.floor(secs)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`
}

function fmtFraction(frac?: string | null): string {
  if (!frac) return '—'
  const [a, b] = frac.split('/').map(Number)
  if (!a || !b) return frac
  return `${(a / b).toFixed(3)} fps`
}

function fmtRate(bps?: number | null): string {
  if (!bps) return '—'
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`
  if (bps >= 1_000) return `${(bps / 1_000).toFixed(0)} kbps`
  return `${bps} bps`
}

function elapsed(started?: string | null, completed?: string | null): string {
  if (!started || !completed) return '—'
  const s = new Date(started).getTime()
  const c = new Date(completed).getTime()
  if (isNaN(s) || isNaN(c)) return '—'
  return fmtDuration((c - s) / 1000)
}

// ───── sub-renderers ─────

function StreamFlags({ s }: { s: MediaStream }) {
  return (
    <div className="flex gap-1 flex-wrap">
      {s.default && (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-accent/10 text-accent border border-accent/20">
          default
        </span>
      )}
      {s.forced && (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-warning/10 text-warning border border-warning/20">
          forced
        </span>
      )}
    </div>
  )
}

function VideoTable({ streams }: { streams: MediaStream[] }) {
  if (!streams.length) return <p className="text-sm text-fg-muted italic">No video streams.</p>
  return (
    <table className="w-full text-xs">
      <thead className="text-fg-muted border-b border-border">
        <tr>
          <th className="text-left py-2 px-2">#</th>
          <th className="text-left py-2 px-2">Codec</th>
          <th className="text-left py-2 px-2">Resolution</th>
          <th className="text-left py-2 px-2">Pix fmt</th>
          <th className="text-left py-2 px-2">FPS</th>
          <th className="text-left py-2 px-2">Bitrate</th>
          <th className="text-left py-2 px-2">Profile</th>
          <th className="text-left py-2 px-2">Flags</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {streams.map((s) => (
          <tr key={s.index}>
            <td className="py-2 px-2 font-mono">{s.index}</td>
            <td className="py-2 px-2 font-medium" title={s.codec_long ?? ''}>{s.codec}</td>
            <td className="py-2 px-2">{s.width && s.height ? `${s.width}×${s.height}` : '—'}</td>
            <td className="py-2 px-2 font-mono">{s.pix_fmt ?? '—'}</td>
            <td className="py-2 px-2 font-mono">{fmtFraction(s.avg_frame_rate ?? s.r_frame_rate)}</td>
            <td className="py-2 px-2 font-mono">{fmtRate(s.bit_rate)}</td>
            <td className="py-2 px-2">{s.profile ?? '—'}</td>
            <td className="py-2 px-2"><StreamFlags s={s} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function AudioTable({ streams }: { streams: MediaStream[] }) {
  if (!streams.length) return <p className="text-sm text-fg-muted italic">No audio streams.</p>
  return (
    <table className="w-full text-xs">
      <thead className="text-fg-muted border-b border-border">
        <tr>
          <th className="text-left py-2 px-2">#</th>
          <th className="text-left py-2 px-2">Codec</th>
          <th className="text-left py-2 px-2">Language</th>
          <th className="text-left py-2 px-2">Channels</th>
          <th className="text-left py-2 px-2">Sample rate</th>
          <th className="text-left py-2 px-2">Bitrate</th>
          <th className="text-left py-2 px-2">Title</th>
          <th className="text-left py-2 px-2">Flags</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {streams.map((s) => (
          <tr key={s.index}>
            <td className="py-2 px-2 font-mono">{s.index}</td>
            <td className="py-2 px-2 font-medium" title={s.codec_long ?? ''}>{s.codec}</td>
            <td className="py-2 px-2 uppercase font-mono">{s.language ?? '—'}</td>
            <td className="py-2 px-2">
              {s.channels ?? '—'}
              {s.channel_layout && <span className="text-fg-muted ml-1">({s.channel_layout})</span>}
            </td>
            <td className="py-2 px-2 font-mono">{s.sample_rate ? `${s.sample_rate} Hz` : '—'}</td>
            <td className="py-2 px-2 font-mono">{fmtRate(s.bit_rate)}</td>
            <td className="py-2 px-2 max-w-[200px] truncate" title={s.title ?? ''}>{s.title ?? '—'}</td>
            <td className="py-2 px-2"><StreamFlags s={s} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SubtitleTable({ streams }: { streams: MediaStream[] }) {
  if (!streams.length) return <p className="text-sm text-fg-muted italic">No subtitle streams.</p>
  return (
    <table className="w-full text-xs">
      <thead className="text-fg-muted border-b border-border">
        <tr>
          <th className="text-left py-2 px-2">#</th>
          <th className="text-left py-2 px-2">Codec</th>
          <th className="text-left py-2 px-2">Language</th>
          <th className="text-left py-2 px-2">Title</th>
          <th className="text-left py-2 px-2">Flags</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {streams.map((s) => (
          <tr key={s.index}>
            <td className="py-2 px-2 font-mono">{s.index}</td>
            <td className="py-2 px-2 font-medium" title={s.codec_long ?? ''}>{s.codec}</td>
            <td className="py-2 px-2 uppercase font-mono">{s.language ?? '—'}</td>
            <td className="py-2 px-2 max-w-[300px] truncate" title={s.title ?? ''}>{s.title ?? '—'}</td>
            <td className="py-2 px-2"><StreamFlags s={s} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MetadataView({ meta }: { meta: ParsedMetadata | null }) {
  if (!meta) {
    return (
      <p className="text-sm text-fg-muted italic py-8 text-center">
        No metadata available for this file.
      </p>
    )
  }
  const fmt = meta.format
  return (
    <div className="space-y-6">
      {fmt && (
        <section>
          <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-2">
            Container
          </h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
            <div className="contents">
              <dt className="text-fg-muted">Format</dt>
              <dd className="font-mono" title={fmt.format_long_name ?? ''}>{fmt.format_name ?? '—'}</dd>
              <dt className="text-fg-muted">Duration</dt>
              <dd className="font-mono">{fmtDuration(fmt.duration)}</dd>
              <dt className="text-fg-muted">Size</dt>
              <dd className="font-mono">{fmt.size ? fmtBytes(fmt.size / 1024 / 1024) : '—'}</dd>
              <dt className="text-fg-muted">Bitrate</dt>
              <dd className="font-mono">{fmtRate(fmt.bit_rate)}</dd>
              <dt className="text-fg-muted">Stream count</dt>
              <dd className="font-mono">{fmt.nb_streams ?? '—'}</dd>
            </div>
          </dl>
        </section>
      )}

      <section>
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-2">
          Video ({meta.video?.length ?? 0})
        </h3>
        <VideoTable streams={meta.video ?? []} />
      </section>

      <section>
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-2">
          Audio ({meta.audio?.length ?? 0})
        </h3>
        <AudioTable streams={meta.audio ?? []} />
      </section>

      <section>
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-2">
          Subtitles ({meta.subtitle?.length ?? 0})
        </h3>
        <SubtitleTable streams={meta.subtitle ?? []} />
      </section>

      {meta.attachment && meta.attachment.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-2">
            Attachments ({meta.attachment.length})
          </h3>
          <p className="text-xs text-fg-muted">
            {meta.attachment.length} file{meta.attachment.length === 1 ? '' : 's'}
            {' '}
            (mostly font subsets for ASS subtitles).
          </p>
        </section>
      )}
    </div>
  )
}

function SummaryView({ record }: { record: HistoryRecord }) {
  const reduction =
    record.original_size_mb && record.encoded_size_mb != null
      ? (1 - record.encoded_size_mb / record.original_size_mb) * 100
      : null

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-3">
          Result
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-bg-subtle border border-border rounded-lg p-3">
            <div className="text-xs text-fg-muted uppercase tracking-wider mb-1">Original</div>
            <div className="text-lg font-mono">{fmtBytes(record.original_size_mb)}</div>
          </div>
          <div className="bg-bg-subtle border border-border rounded-lg p-3">
            <div className="text-xs text-fg-muted uppercase tracking-wider mb-1">Encoded</div>
            <div className="text-lg font-mono">{fmtBytes(record.encoded_size_mb)}</div>
          </div>
          <div className="bg-bg-subtle border border-border rounded-lg p-3">
            <div className="text-xs text-fg-muted uppercase tracking-wider mb-1">Saved</div>
            <div className="text-lg font-mono text-success">
              {record.space_saved_mb > 0 ? `−${fmtBytes(record.space_saved_mb)}` : '—'}
            </div>
          </div>
          <div className="bg-bg-subtle border border-border rounded-lg p-3">
            <div className="text-xs text-fg-muted uppercase tracking-wider mb-1">Reduction</div>
            <div className="text-lg font-mono">
              {reduction != null ? `${reduction.toFixed(1)}%` : '—'}
            </div>
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-3">
          Encode
        </h3>
        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-fg-muted">Status</dt>
          <dd><StatusBadge status={record.status} /></dd>
          <dt className="text-fg-muted">Encoder</dt>
          <dd className="font-mono">{record.encoder ?? '—'}</dd>
          <dt className="text-fg-muted">CRF / QP</dt>
          <dd className="font-mono">{record.crf_used ?? '—'}</dd>
          <dt className="text-fg-muted">Progress</dt>
          <dd className="font-mono">
            {record.current_frame != null && record.total_frames != null
              ? `${record.current_frame.toLocaleString()} / ${record.total_frames.toLocaleString()} frames (${(record.pct ?? 0).toFixed(1)}%)`
              : '—'}
          </dd>
          <dt className="text-fg-muted">Started</dt>
          <dd className="font-mono">{record.started_at ?? '—'}</dd>
          <dt className="text-fg-muted">Completed</dt>
          <dd className="font-mono">{record.completed_at ?? '—'}</dd>
          <dt className="text-fg-muted">Elapsed</dt>
          <dd className="font-mono">{elapsed(record.started_at, record.completed_at)}</dd>
          {record.error && (
            <>
              <dt className="text-fg-muted">Error</dt>
              <dd className="text-danger break-words">{record.error}</dd>
            </>
          )}
        </dl>
      </section>

      <section>
        <h3 className="text-xs font-semibold text-fg-muted uppercase tracking-wider mb-3">
          Identity
        </h3>
        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-fg-muted">Job ID</dt>
          <dd className="font-mono">{record.id}</dd>
          <dt className="text-fg-muted">Session</dt>
          <dd className="font-mono">{record.session_id ?? '—'}</dd>
          <dt className="text-fg-muted">Original path</dt>
          <dd className="font-mono text-xs break-all">{record.path}</dd>
          <dt className="text-fg-muted">SHA-256 (source)</dt>
          <dd className="font-mono text-xs break-all">{record.original_hash ?? '—'}</dd>
          <dt className="text-fg-muted">SHA-256 (encoded)</dt>
          <dd className="font-mono text-xs break-all">{record.encoded_hash ?? '—'}</dd>
        </dl>
      </section>
    </div>
  )
}

function LogsView({ jobId }: { jobId: number }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['job-logs', jobId],
    queryFn: () => jobs.logs(jobId),
  })

  if (isLoading) return <p className="text-sm text-fg-muted">Loading logs…</p>
  if (isError) {
    return <p className="text-sm text-danger">Failed to load logs: {String(error)}</p>
  }
  if (!data) return <p className="text-sm text-fg-muted">No logs.</p>

  // Backend may return either an array of events or { events: [...] }.
  // Be defensive — render whatever shape we get as JSON for now.
  const entries: unknown[] = Array.isArray(data)
    ? (data as unknown[])
    : Array.isArray((data as { events?: unknown[] }).events)
      ? ((data as { events: unknown[] }).events)
      : []

  if (entries.length === 0) {
    return <p className="text-sm text-fg-muted italic">No log entries recorded for this job.</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-fg-muted">{entries.length} entries</p>
      <pre className="bg-bg-subtle border border-border rounded-lg p-3 text-xs font-mono overflow-x-auto max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words">
        {entries.map((e, i) => (
          <div key={i} className="py-0.5">
            {JSON.stringify(e)}
          </div>
        ))}
      </pre>
    </div>
  )
}

function CommandView({ cmd }: { cmd: string | null | undefined }) {
  if (!cmd) {
    return (
      <p className="text-sm text-fg-muted italic">
        No ffmpeg command recorded for this job (older record or never started).
      </p>
    )
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-fg-muted">The exact ffmpeg invocation used for this job.</p>
      <pre className="bg-bg-subtle border border-border rounded-lg p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-all">
        {cmd}
      </pre>
    </div>
  )
}

// ───── Main component ─────

export function HistoryDetailModal({ record, onClose }: HistoryDetailModalProps) {
  const [tab, setTab] = useState<TabKey>('summary')

  const sourceMeta = useMemo(
    () => safeParse(record?.source_metadata ?? null),
    [record?.source_metadata],
  )
  const destMeta = useMemo(
    () => safeParse(record?.destination_metadata ?? null),
    [record?.destination_metadata],
  )

  if (!record) return null

  return (
    <Modal
      open={record != null}
      onClose={onClose}
      title={record.filename}
      subtitle={record.path}
      size="xl"
    >
      <nav className="flex gap-1 border-b border-border mb-4 -mx-6 px-6 sticky top-0 bg-bg-card z-10">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-accent text-accent'
                : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'summary' && <SummaryView record={record} />}
      {tab === 'source' && <MetadataView meta={sourceMeta} />}
      {tab === 'encoded' && <MetadataView meta={destMeta} />}
      {tab === 'logs' && <LogsView jobId={record.id} />}
      {tab === 'command' && <CommandView cmd={record.ffmpeg_cmd} />}
    </Modal>
  )
}
