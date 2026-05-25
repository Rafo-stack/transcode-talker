import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, History as HistoryIcon, Save, Undo2 } from 'lucide-react'
import { db } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { formatBytes, formatDate } from '@/lib/utils'

export function DatabasePage() {
  const toast = useToast()
  const qc = useQueryClient()
  const stateQ = useQuery({ queryKey: ['db.state'], queryFn: db.state })
  const backupsQ = useQuery({ queryKey: ['db.backups'], queryFn: db.backups })

  const backupMut = useMutation({
    mutationFn: () => db.backup(),
    onSuccess: () => {
      toast.push('Backup created', 'success')
      qc.invalidateQueries({ queryKey: ['db.backups'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })
  const restoreMut = useMutation({
    mutationFn: (name: string) => db.restore(name),
    onSuccess: () => toast.push('Restore complete — refresh the page', 'warning'),
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const state = stateQ.data as { backend?: string; version?: string; size_mb?: number } | undefined

  return (
    <PageContainer>
      <PageHeader icon={Database} title="Database" description="Backup and restore the metadata store." />

      <section className="card p-5 grid grid-cols-2 gap-4 text-sm">
        <div>
          <div className="label">Backend</div>
          <div className="font-medium">{state?.backend ?? '—'}</div>
        </div>
        <div>
          <div className="label">Version</div>
          <div className="font-medium font-mono text-xs">{state?.version ?? '—'}</div>
        </div>
        {state?.size_mb != null && (
          <div>
            <div className="label">DB size</div>
            <div className="font-medium">{formatBytes(state.size_mb)}</div>
          </div>
        )}
      </section>

      <section className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <HistoryIcon size={14} /> Backups
          </h2>
          <Button onClick={() => backupMut.mutate()} disabled={backupMut.isPending} size="sm">
            <Save size={12} /> {backupMut.isPending ? 'Creating…' : 'Create backup'}
          </Button>
        </header>
        {!backupsQ.data?.backups?.length ? (
          <div className="px-5 py-6 text-center text-xs text-fg-muted">No backups yet.</div>
        ) : (
          <ul className="divide-y divide-border">
            {backupsQ.data.backups.map((b) => (
              <li key={b.name} className="px-5 py-3 flex items-center gap-3 text-sm">
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs truncate">{b.name}</div>
                  <div className="text-xs text-fg-muted">{formatDate(b.created_at)} · {formatBytes(b.size / 1024 / 1024)}</div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (confirm(`Restore ${b.name}? This overwrites the current database.`))
                      restoreMut.mutate(b.name)
                  }}
                  disabled={restoreMut.isPending}
                >
                  <Undo2 size={12} /> Restore
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </PageContainer>
  )
}
