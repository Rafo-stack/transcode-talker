import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  Film,
  History as HistoryIcon,
  LayoutDashboard,
  ScanLine,
  TrendingUp,
} from 'lucide-react'
import { encode, history } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { StatusBadge } from '@/components/ui/Badge'
import { formatBytes, truncatePath } from '@/lib/utils'
import { useEncode } from '@/stores/encode'

export function DashboardPage() {
  const stats = useQuery({ queryKey: ['history.stats'], queryFn: history.stats })
  const recent = useQuery({
    queryKey: ['history.recent'],
    queryFn: () => history.list({ page: 1, page_size: 8, sort_by: 'finished_at', order: 'desc' }),
  })
  const running = useEncode((s) => s.running)
  // Only re-poll while a session is actively running; otherwise the
  // 15 MB response on completed sessions wastes bandwidth and makes the
  // page feel sluggish.
  const sessionQ = useQuery({
    queryKey: ['session.active'],
    queryFn: () => encode.activeSession(),
    refetchInterval: running ? 5_000 : false,
    enabled: running,
  })
  const total = stats.data?.total ?? 0
  const completed = stats.data?.completed ?? 0
  const failed = stats.data?.failed ?? 0
  const savedMb = stats.data?.total_saved_mb ?? 0
  const originalMb = stats.data?.total_original_mb ?? 0
  const successRate = total > 0 ? Math.round((completed / total) * 100) : 0
  const reduction = originalMb > 0 ? (savedMb / originalMb) * 100 : 0

  return (
    <PageContainer>
      <PageHeader
        icon={LayoutDashboard}
        title="Dashboard"
        description="Overview of your re-encoding activity and storage savings."
      />

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <StatCard
          icon={Film}
          label="Total encoded"
          value={completed.toLocaleString()}
          hint={`${total.toLocaleString()} total runs`}
        />
        <StatCard
          icon={TrendingUp}
          label="Space saved"
          value={formatBytes(savedMb)}
          hint={`${reduction.toFixed(1)}% reduction`}
          tone="success"
        />
        <StatCard
          icon={Activity}
          label="Success rate"
          value={`${successRate}%`}
          hint={failed > 0 ? `${failed} failed` : 'No failures'}
          tone={successRate >= 90 ? 'success' : successRate >= 70 ? 'warning' : 'danger'}
        />
      </section>

      {/* Active session */}
      {running && sessionQ.data?.session && (
        <section className="card p-5 space-y-3">
          <div className="flex items-center gap-2 text-success">
            <Activity size={16} className="animate-pulse" />
            <span className="font-semibold">Encoding in progress</span>
            <Link to="/encode" className="ml-auto text-xs text-accent hover:underline">
              Open Encode →
            </Link>
          </div>
          <div className="text-sm text-fg-muted">
            File {sessionQ.data.session.done_files + 1} of {sessionQ.data.session.total_files}
          </div>
          <ProgressBar
            value={(sessionQ.data.session.done_files / Math.max(1, sessionQ.data.session.total_files)) * 100}
          />
        </section>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Link to="/scan" className="card p-5 hover:shadow-glow transition group">
          <div className="flex items-center gap-3 mb-2">
            <div className="h-9 w-9 rounded-lg bg-bg-subtle flex items-center justify-center text-fg-muted group-hover:text-accent transition">
              <ScanLine size={18} />
            </div>
            <div className="font-medium">Scan & Select</div>
          </div>
          <div className="text-xs text-fg-muted">
            Walk the configured folders, pick files, kick off a new encode.
          </div>
        </Link>
        <Link to="/encode" className="card p-5 hover:shadow-glow transition group">
          <div className="flex items-center gap-3 mb-2">
            <div className="h-9 w-9 rounded-lg bg-bg-subtle flex items-center justify-center text-fg-muted group-hover:text-accent transition">
              <Film size={18} />
            </div>
            <div className="font-medium">Encode</div>
          </div>
          <div className="text-xs text-fg-muted">
            Live session: queue, current file progress, real-time log.
          </div>
        </Link>
        <Link to="/history" className="card p-5 hover:shadow-glow transition group">
          <div className="flex items-center gap-3 mb-2">
            <div className="h-9 w-9 rounded-lg bg-bg-subtle flex items-center justify-center text-fg-muted group-hover:text-accent transition">
              <HistoryIcon size={18} />
            </div>
            <div className="font-medium">History</div>
          </div>
          <div className="text-xs text-fg-muted">
            Past jobs with filters, savings totals, export and re-encode.
          </div>
        </Link>
      </section>

      <section className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent activity</h2>
          <Link to="/history" className="text-xs text-fg-muted hover:text-accent">
            View all →
          </Link>
        </header>
        {!recent.data || recent.data.items.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-fg-muted">
            No jobs yet. Run a scan to get started.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {recent.data.items.map((r) => (
              <li key={r.id} className="px-5 py-3 flex items-center gap-3">
                <StatusBadge status={r.status} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate">{r.filename}</div>
                  <div className="text-xs text-fg-muted truncate font-mono">
                    {truncatePath(r.path, 80)}
                  </div>
                </div>
                {r.space_saved_mb > 0 && (
                  <div className="text-xs text-success whitespace-nowrap">
                    −{formatBytes(r.space_saved_mb)}
                  </div>
                )}
                <div className="text-xs text-fg-muted whitespace-nowrap">
                  {formatBytes(r.original_size_mb)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </PageContainer>
  )
}

interface StatCardProps {
  icon: typeof Film
  label: string
  value: string
  hint?: string
  tone?: 'accent' | 'success' | 'warning' | 'danger'
}

function StatCard({ icon: Icon, label, value, hint, tone = 'accent' }: StatCardProps) {
  const toneCls =
    tone === 'success' ? 'text-success bg-success/10'
    : tone === 'warning' ? 'text-warning bg-warning/10'
    : tone === 'danger' ? 'text-danger bg-danger/10'
    : 'text-accent bg-accent/10'
  return (
    <div className="card p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className={`h-9 w-9 rounded-lg flex items-center justify-center ${toneCls}`}>
          <Icon size={18} />
        </div>
        <div className="text-xs text-fg-muted uppercase tracking-wide">{label}</div>
      </div>
      <div className="text-2xl font-semibold">{value}</div>
      {hint && <div className="text-xs text-fg-muted mt-1">{hint}</div>}
    </div>
  )
}
