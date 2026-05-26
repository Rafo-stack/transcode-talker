import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  Download,
  Eye,
  History as HistoryIcon,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { history } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { StatusBadge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/EmptyState'
import { useToast } from '@/components/ui/Toast'
import { HistoryDetailModal } from '@/components/HistoryDetailModal'
import { formatBytes, formatDate, truncatePath, cn } from '@/lib/utils'
import type { HistoryRecord } from '@/types/api'

const STATUS_OPTIONS = ['', 'completed', 'failed', 'skipped', 'interrupted'] as const

export function HistoryPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [status, setStatus] = useState<string>('')
  const [sortBy, setSortBy] = useState<string>('finished_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [detailRecord, setDetailRecord] = useState<HistoryRecord | null>(null)

  const listQ = useQuery({
    queryKey: ['history.list', { page, pageSize, status, sortBy, order }],
    queryFn: () =>
      history.list({
        page,
        page_size: pageSize,
        sort_by: sortBy,
        order,
        status: status || undefined,
      }),
  })

  const statsQ = useQuery({ queryKey: ['history.stats'], queryFn: history.stats })

  const total = listQ.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const items = listQ.data?.items ?? []

  const bulkDelMut = useMutation({
    mutationFn: (ids: number[]) => history.bulkDelete(ids),
    onSuccess: () => {
      toast.push(`Deleted ${selected.size} record(s)`, 'success')
      setSelected(new Set())
      qc.invalidateQueries({ queryKey: ['history.list'] })
      qc.invalidateQueries({ queryKey: ['history.stats'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const importMut = useMutation({
    mutationFn: (file: File) => history.importJson(file),
    onSuccess: () => {
      toast.push('Import complete', 'success')
      qc.invalidateQueries({ queryKey: ['history.list'] })
      qc.invalidateQueries({ queryKey: ['history.stats'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const toggleOne = (id: number) => setSelected((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const toggleAll = () => setSelected((s) =>
    s.size === items.length ? new Set() : new Set(items.map((i) => i.id))
  )

  const onImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) importMut.mutate(f)
    e.target.value = ''
  }

  const allChecked = items.length > 0 && selected.size === items.length

  const stats = statsQ.data
  const headerStats = useMemo(() => {
    if (!stats) return null
    return (
      <div className="flex flex-wrap items-center gap-4 text-xs text-fg-muted">
        <span><span className="text-fg font-semibold">{stats.total.toLocaleString()}</span> records</span>
        <span><span className="text-success font-semibold">{formatBytes(stats.total_saved_mb)}</span> saved</span>
        <span>{stats.completed.toLocaleString()} done · {stats.failed.toLocaleString()} failed · {stats.skipped.toLocaleString()} skipped</span>
      </div>
    )
  }, [stats])

  return (
    <PageContainer>
      <PageHeader
        icon={HistoryIcon}
        title="History"
        description="Every job ever run. Filter, sort, export and clean up."
        actions={
          <>
            <a href={history.exportUrl()} className="btn-secondary">
              <Download size={14} /> Export
            </a>
            <label className="btn-secondary cursor-pointer">
              <Upload size={14} /> Import
              <input type="file" accept="application/json" onChange={onImport} className="hidden" />
            </label>
          </>
        }
      />

      <section className="card p-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          <span className="label">Status</span>
          {STATUS_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => { setStatus(s); setPage(1) }}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs font-medium border transition-colors',
                status === s
                  ? 'bg-accent text-white border-accent'
                  : 'bg-bg-subtle text-fg-muted border-border hover:bg-bg-card hover:text-fg',
              )}
            >
              {s || 'All'}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs text-fg-muted">
          <span>Sort</span>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="input w-auto">
            <option value="finished_at">Date</option>
            <option value="space_saved_mb">Space saved</option>
            <option value="original_size_mb">Original size</option>
            <option value="filename">Filename</option>
          </select>
          <select value={order} onChange={(e) => setOrder(e.target.value as 'asc' | 'desc')} className="input w-auto">
            <option value="desc">↓</option>
            <option value="asc">↑</option>
          </select>
        </div>
      </section>

      {headerStats && <div className="px-1">{headerStats}</div>}

      {selected.size > 0 && (
        <section className="card p-3 flex items-center gap-3 border-accent/30 bg-accent/5">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set())}
          >
            <X size={12} /> Clear
          </Button>
          <Button
            variant="danger"
            size="sm"
            className="ml-auto"
            onClick={() => {
              if (confirm(`Delete ${selected.size} record(s)?`))
                bulkDelMut.mutate(Array.from(selected))
            }}
            disabled={bulkDelMut.isPending}
          >
            <Trash2 size={12} /> Delete
          </Button>
        </section>
      )}

      <section className="card overflow-hidden">
        {items.length === 0 && !listQ.isLoading ? (
          <EmptyState icon={HistoryIcon} title="No records" description="Nothing matches the current filters yet." />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-bg-subtle border-b border-border">
              <tr>
                <th className="px-3 py-2 text-left w-8">
                  <input
                    type="checkbox"
                    checked={allChecked}
                    onChange={toggleAll}
                    className="accent-accent"
                  />
                </th>
                <th className="px-3 py-2 text-left">File</th>
                <th className="px-3 py-2 text-left w-32">Status</th>
                <th className="px-3 py-2 text-right w-28">Original</th>
                <th className="px-3 py-2 text-right w-28">Saved</th>
                <th className="px-3 py-2 text-left w-48">Finished</th>
                <th className="px-3 py-2 text-center w-16">View</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((r) => (
                <tr key={r.id} className="hover:bg-bg-subtle">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selected.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                      className="accent-accent"
                    />
                  </td>
                  <td className="px-3 py-2 min-w-0">
                    <div className="font-medium truncate max-w-[420px]" title={r.path}>{r.filename}</div>
                    <div className="text-xs text-fg-muted font-mono truncate max-w-[420px]">{truncatePath(r.path, 70)}</div>
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-right text-fg-muted">{formatBytes(r.original_size_mb)}</td>
                  <td className="px-3 py-2 text-right">
                    {r.space_saved_mb > 0 ? (
                      <span className="text-success font-medium">−{formatBytes(r.space_saved_mb)}</span>
                    ) : <span className="text-fg-muted">—</span>}
                  </td>
                  <td className="px-3 py-2 text-xs text-fg-muted whitespace-nowrap">{formatDate(r.finished_at)}</td>
                  <td className="px-3 py-2 text-center">
                    <button
                      onClick={() => setDetailRecord(r)}
                      title="View details"
                      aria-label={`View details for ${r.filename}`}
                      className="inline-flex items-center justify-center w-7 h-7 rounded-md text-fg-muted hover:text-accent hover:bg-accent/10 transition-colors"
                    >
                      <Eye size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between text-xs text-fg-muted">
          <span>
            Page <span className="text-fg font-medium">{page}</span> of {totalPages} · {total.toLocaleString()} records
          </span>
          <div className="flex items-center gap-2">
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(parseInt(e.target.value, 10)); setPage(1) }}
              className="input w-auto"
            >
              {[25, 50, 100, 200, 500].map((n) => <option key={n} value={n}>{n}/page</option>)}
            </select>
            <Button variant="secondary" size="sm" onClick={() => setPage(1)} disabled={page === 1}>« First</Button>
            <Button variant="secondary" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>‹ Prev</Button>
            <Button variant="secondary" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>Next ›</Button>
            <Button variant="secondary" size="sm" onClick={() => setPage(totalPages)} disabled={page === totalPages}>Last »</Button>
          </div>
        </div>
      )}

      <HistoryDetailModal record={detailRecord} onClose={() => setDetailRecord(null)} />
    </PageContainer>
  )
}
