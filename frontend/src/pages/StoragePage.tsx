import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HardDrive, Trash2 } from 'lucide-react'
import { hdd } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useToast } from '@/components/ui/Toast'
import { formatBytes } from '@/lib/utils'

export function StoragePage() {
  const toast = useToast()
  const qc = useQueryClient()
  const statusQ = useQuery({ queryKey: ['hdd.status'], queryFn: hdd.status })
  const cleanMut = useMutation({
    mutationFn: () => hdd.clean(),
    onSuccess: () => {
      toast.push('HDD clean complete', 'success')
      qc.invalidateQueries({ queryKey: ['hdd.status'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const s = statusQ.data
  const pct = s?.percent ?? 0
  const tone = pct >= 90 ? 'danger' : pct >= 75 ? 'warning' : 'accent'

  return (
    <div className="px-6 py-8 max-w-3xl mx-auto space-y-6">
      <PageHeader icon={HardDrive} title="Storage / HDD" description="Disk usage of /mnt/hdd and stale-file cleanup." />

      <section className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">/mnt/hdd</h2>
          {s?.mount && <span className="text-xs text-fg-muted font-mono">{s.mount}</span>}
        </div>
        {!s ? (
          <div className="text-xs text-fg-muted italic">No /mnt/hdd mount detected.</div>
        ) : (
          <>
            <ProgressBar value={pct} tone={tone} />
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-fg-muted">
              <span>Used: <span className="text-fg font-medium">{(s.used_gb ?? 0).toFixed(1)} GB</span></span>
              <span>Free: <span className="text-fg font-medium">{(s.free_gb ?? 0).toFixed(1)} GB</span></span>
              <span>Total: <span className="text-fg font-medium">{(s.total_gb ?? 0).toFixed(0)} GB</span></span>
              <span>{pct.toFixed(1)}%</span>
            </div>
          </>
        )}
      </section>

      <section className="card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Stale files</h2>
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              if (confirm('Clean stale .tmp / orphan files from /mnt/hdd?')) cleanMut.mutate()
            }}
            disabled={cleanMut.isPending}
          >
            <Trash2 size={12} /> Clean now
          </Button>
        </div>
        {s?.stash_files && s.stash_files.length > 0 ? (
          <ul className="divide-y divide-border">
            {s.stash_files.map((f) => (
              <li key={f.path} className="py-2 flex items-center gap-3 text-sm">
                <span className="flex-1 truncate font-mono text-xs">{f.path}</span>
                <span className="text-xs text-fg-muted">{formatBytes(f.size_mb)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-xs text-fg-muted italic">Nothing stale.</div>
        )}
      </section>
    </div>
  )
}
