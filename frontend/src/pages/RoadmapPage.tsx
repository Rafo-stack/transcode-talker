import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Bug,
  ChevronDown,
  Map as MapIcon,
  Rocket,
  Sparkles,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { roadmap as roadmapApi } from '@/api/endpoints'
import type { RoadmapCategory, RoadmapItem } from '@/types/api'
import { cn } from '@/lib/utils'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'

type Filter = 'all' | RoadmapCategory

interface CategoryMeta {
  key: RoadmapCategory
  label: string
  icon: LucideIcon
  tone: { text: string; bgSoft: string; border: string; leftBar: string; chipActive: string }
}

const CATEGORIES: CategoryMeta[] = [
  {
    key: 'bugs', label: 'Bugs', icon: Bug,
    tone: {
      text: 'text-red-500',
      bgSoft: 'bg-red-500/10',
      border: 'border-red-500/30',
      leftBar: 'before:bg-red-500',
      chipActive: 'bg-red-500 text-white border-red-500',
    },
  },
  {
    key: 'improvements', label: 'Improvements', icon: Sparkles,
    tone: {
      text: 'text-sky-500',
      bgSoft: 'bg-sky-500/10',
      border: 'border-sky-500/30',
      leftBar: 'before:bg-sky-500',
      chipActive: 'bg-sky-500 text-white border-sky-500',
    },
  },
  {
    key: 'features', label: 'Features', icon: Rocket,
    tone: {
      text: 'text-emerald-500',
      bgSoft: 'bg-emerald-500/10',
      border: 'border-emerald-500/30',
      leftBar: 'before:bg-emerald-500',
      chipActive: 'bg-emerald-500 text-white border-emerald-500',
    },
  },
]

const CATEGORY_BY_KEY = Object.fromEntries(CATEGORIES.map((c) => [c.key, c])) as Record<RoadmapCategory, CategoryMeta>

const STATUS_ORDER = ['open', 'in_progress', 'planned', 'deferred'] as const
const STATUS_LABEL: Record<string, string> = {
  open: 'Open', planned: 'Planned', in_progress: 'In progress', deferred: 'Deferred',
}
const STATUS_COLORS: Record<string, string> = {
  open:        'bg-yellow-500/10 text-yellow-500 border border-yellow-500/30',
  in_progress: 'bg-accent/15 text-accent border border-accent/30',
  planned:     'bg-fg-muted/10 text-fg-muted border border-border',
  deferred:    'bg-fg-muted/10 text-fg-muted border border-border italic',
}

const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low'] as const
const SEVERITY_COLORS: Record<string, string> = {
  Critical: 'bg-red-500/20 text-red-500 border border-red-500/40',
  High:     'bg-red-500/10 text-red-500 border border-red-500/30',
  Medium:   'bg-yellow-500/10 text-yellow-500 border border-yellow-500/30',
  Low:      'bg-fg-muted/10 text-fg-muted border border-border',
}

const PRIORITY_ORDER = ['High', 'Medium', 'Low'] as const
const PRIORITY_COLORS: Record<string, string> = {
  High:   'bg-sky-500/15 text-sky-500 border border-sky-500/30',
  Medium: 'bg-yellow-500/10 text-yellow-500 border border-yellow-500/30',
  Low:    'bg-fg-muted/10 text-fg-muted border border-border',
}

const NO_VERSION_KEY = '__none__'

// Compare two semver-ish strings ("0.3.5.0", "0.4.0.0"). Pads with zeros so
// shorter strings sort consistently. Used to keep version filter chips in a
// stable, intuitive order regardless of how they appear in the YAML files.
function compareVersions(a: string, b: string): number {
  if (a === NO_VERSION_KEY) return 1
  if (b === NO_VERSION_KEY) return -1
  const pa = a.split('.').map((x) => parseInt(x, 10) || 0)
  const pb = b.split('.').map((x) => parseInt(x, 10) || 0)
  const n = Math.max(pa.length, pb.length)
  for (let i = 0; i < n; i++) {
    const av = pa[i] ?? 0
    const bv = pb[i] ?? 0
    if (av !== bv) return av - bv
  }
  return 0
}

export function RoadmapPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['roadmap'], queryFn: roadmapApi.get })
  const [category, setCategory] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set())
  const [severityFilter, setSeverityFilter] = useState<Set<string>>(new Set())
  const [priorityFilter, setPriorityFilter] = useState<Set<string>>(new Set())
  const [versionFilter, setVersionFilter] = useState<Set<string>>(new Set())

  // Done items are project history and live in git, not on the roadmap.
  // We strip them at the very top so every downstream count / filter sees
  // an "open-only" universe.
  const all = useMemo<RoadmapItem[]>(() => {
    if (!data) return []
    return [...data.bugs, ...data.improvements, ...data.features].filter(
      (i) => i.status !== 'done',
    )
  }, [data])

  const availableStatuses = useMemo(
    () =>
      Array.from(new Set(all.map((i) => i.status))).sort(
        (a, b) =>
          STATUS_ORDER.indexOf(a as (typeof STATUS_ORDER)[number]) -
          STATUS_ORDER.indexOf(b as (typeof STATUS_ORDER)[number]),
      ),
    [all],
  )
  const availableSeverities = useMemo(
    () =>
      Array.from(
        new Set(all.map((i) => i.severity).filter(Boolean) as string[]),
      ).sort(
        (a, b) =>
          SEVERITY_ORDER.indexOf(a as (typeof SEVERITY_ORDER)[number]) -
          SEVERITY_ORDER.indexOf(b as (typeof SEVERITY_ORDER)[number]),
      ),
    [all],
  )
  const availablePriorities = useMemo(
    () =>
      Array.from(
        new Set(all.map((i) => i.priority).filter(Boolean) as string[]),
      ).sort(
        (a, b) =>
          PRIORITY_ORDER.indexOf(a as (typeof PRIORITY_ORDER)[number]) -
          PRIORITY_ORDER.indexOf(b as (typeof PRIORITY_ORDER)[number]),
      ),
    [all],
  )
  const availableVersions = useMemo(() => {
    const set = new Set<string>()
    let hasNone = false
    for (const i of all) {
      if (!i.targeted_version) { hasNone = true; continue }
      set.add(i.targeted_version)
    }
    const sorted = Array.from(set).sort(compareVersions)
    if (hasNone) sorted.push(NO_VERSION_KEY)
    return sorted
  }, [all])

  const visible = useMemo(() => {
    let items = all
    if (category !== 'all') items = items.filter((i) => i.category === category)
    if (statusFilter.size) items = items.filter((i) => statusFilter.has(i.status))
    if (severityFilter.size)
      items = items.filter((i) => i.severity && severityFilter.has(i.severity))
    if (priorityFilter.size)
      items = items.filter((i) => i.priority && priorityFilter.has(i.priority))
    if (versionFilter.size)
      items = items.filter((i) => {
        const key = i.targeted_version ?? NO_VERSION_KEY
        return versionFilter.has(key)
      })
    const q = query.trim().toLowerCase()
    if (q) {
      items = items.filter((i) =>
        [i.id, i.title, i.summary, i.details, i.area ?? ''].join('\n').toLowerCase().includes(q),
      )
    }
    return items
  }, [all, category, query, statusFilter, severityFilter, priorityFilter, versionFilter])

  const counts = {
    bugs:         all.filter((i) => i.category === 'bugs').length,
    improvements: all.filter((i) => i.category === 'improvements').length,
    features:     all.filter((i) => i.category === 'features').length,
    total:        all.length,
  }
  const activeFilters =
    (category !== 'all' ? 1 : 0) +
    (query.trim() ? 1 : 0) +
    statusFilter.size +
    severityFilter.size +
    priorityFilter.size +
    versionFilter.size

  const clearAll = () => {
    setCategory('all')
    setQuery('')
    setStatusFilter(new Set())
    setSeverityFilter(new Set())
    setPriorityFilter(new Set())
    setVersionFilter(new Set())
  }

  return (
    <PageContainer>
      <PageHeader
        icon={MapIcon}
        title="Roadmap"
        description="Open bugs, planned improvements and upcoming features — completed items live in git history, not here."
      />

      <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {CATEGORIES.map((c) => {
          const active = category === c.key
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => setCategory(active ? 'all' : c.key)}
              className={cn(
                'card p-4 flex items-center gap-3 transition-all border-2 text-left',
                active ? `${c.tone.border} ${c.tone.bgSoft}` : 'border-transparent hover:bg-bg-subtle',
              )}
            >
              <div className={cn('h-12 w-12 rounded-xl flex items-center justify-center', c.tone.bgSoft, c.tone.text)}>
                <c.icon size={20} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs uppercase tracking-wide text-fg-muted">{c.label}</div>
                <div className="text-2xl font-semibold mt-0.5">{counts[c.key]}</div>
              </div>
            </button>
          )
        })}
      </section>

      <section className="card p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Chip active={category === 'all'} onClick={() => setCategory('all')} label={`All · ${counts.total}`} />
          {CATEGORIES.map((c) => (
            <Chip
              key={c.key}
              active={category === c.key}
              onClick={() => setCategory(c.key)}
              label={`${c.label} · ${counts[c.key]}`}
              activeClassName={c.tone.chipActive}
            />
          ))}
          <div className="ml-auto flex items-center gap-2 flex-1 min-w-[200px] max-w-md">
            <input
              className="input"
              type="search"
              placeholder="Search title, summary, details…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {activeFilters > 0 && (
              <button
                onClick={clearAll}
                className="btn-ghost text-xs whitespace-nowrap"
              >
                <X size={14} /> Clear ({activeFilters})
              </button>
            )}
          </div>
        </div>

        {availableStatuses.length > 0 && (
          <FilterRow
            label="Status"
            options={availableStatuses.map((s) => ({
              value: s,
              label: STATUS_LABEL[s] ?? s,
              className: STATUS_COLORS[s],
            }))}
            selected={statusFilter}
            onToggle={(v) => toggle(statusFilter, v, setStatusFilter)}
          />
        )}
        {availableSeverities.length > 0 && (
          <FilterRow
            label="Severity"
            options={availableSeverities.map((s) => ({
              value: s,
              label: s,
              className: SEVERITY_COLORS[s],
            }))}
            selected={severityFilter}
            onToggle={(v) => toggle(severityFilter, v, setSeverityFilter)}
          />
        )}
        {availablePriorities.length > 0 && (
          <FilterRow
            label="Priority"
            options={availablePriorities.map((p) => ({
              value: p,
              label: p,
              className: PRIORITY_COLORS[p],
            }))}
            selected={priorityFilter}
            onToggle={(v) => toggle(priorityFilter, v, setPriorityFilter)}
          />
        )}
        {availableVersions.length > 0 && (
          <FilterRow
            label="Version"
            options={availableVersions.map((v) => ({
              value: v,
              label: v === NO_VERSION_KEY ? 'No version' : `v${v}`,
              className:
                v === NO_VERSION_KEY
                  ? 'bg-fg-muted/10 text-fg-muted border border-border italic'
                  : 'bg-accent/10 text-accent border border-accent/30',
            }))}
            selected={versionFilter}
            onToggle={(v) => toggle(versionFilter, v, setVersionFilter)}
          />
        )}
      </section>

      <div className="px-1 text-xs text-fg-muted">
        Showing <span className="font-semibold text-fg">{visible.length}</span> of {all.length} items
      </div>

      {isLoading && <div className="text-sm text-fg-muted">Loading roadmap…</div>}
      {error && (
        <div className="card p-4 flex items-start gap-2 border-danger/40">
          <AlertTriangle size={16} className="text-danger mt-0.5" />
          <div className="text-sm">Failed to load roadmap. Check the API container has access to the <code>roadmap/</code> folder.</div>
        </div>
      )}
      {!isLoading && !error && visible.length === 0 && (
        <div className="card p-8 text-center text-sm text-fg-muted">Nothing matches the current filters.</div>
      )}

      <div className="space-y-3">
        {visible.map((item) => <ItemCard key={item.id} item={item} />)}
      </div>
    </PageContainer>
  )
}

function toggle(current: Set<string>, value: string, setter: (v: Set<string>) => void) {
  const next = new Set(current)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  setter(next)
}

function Chip({ active, onClick, label, activeClassName }: { active: boolean; onClick: () => void; label: string; activeClassName?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border',
        active
          ? (activeClassName || 'bg-accent text-white border-accent')
          : 'bg-bg-subtle text-fg-muted border-border hover:bg-bg-card hover:text-fg',
      )}
    >
      {label}
    </button>
  )
}

function FilterRow({
  label, options, selected, onToggle,
}: {
  label: string
  options: { value: string; label: string; className?: string }[]
  selected: Set<string>
  onToggle: (v: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="label w-20 shrink-0">{label}</span>
      {options.map((o) => {
        const active = selected.has(o.value)
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onToggle(o.value)}
            className={cn(
              'badge transition-all cursor-pointer',
              o.className,
              active ? 'ring-2 ring-offset-1 ring-offset-bg-card ring-current' : 'opacity-60 hover:opacity-100',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

function ItemCard({ item }: { item: RoadmapItem }) {
  const [open, setOpen] = useState(false)
  const meta = CATEGORY_BY_KEY[item.category]
  const Icon = meta.icon
  return (
    <div
      className={cn(
        'card overflow-hidden relative pl-1.5',
        'before:absolute before:top-0 before:left-0 before:bottom-0 before:w-1.5',
        meta.tone.leftBar,
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-4 flex items-start gap-4 text-left hover:bg-bg-subtle/50 transition"
      >
        <div className={cn('h-10 w-10 shrink-0 rounded-xl flex items-center justify-center mt-0.5', meta.tone.bgSoft, meta.tone.text)}>
          <Icon size={16} />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className={cn('font-mono text-xs px-1.5 py-0.5 rounded', meta.tone.bgSoft, meta.tone.text)}>
              {item.id}
            </span>
            <span className="font-semibold text-base">{item.title}</span>
          </div>
          {!open && item.summary && (
            <p className="text-sm text-fg-muted leading-relaxed line-clamp-2">{item.summary}</p>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={cn('badge', STATUS_COLORS[item.status])}>{STATUS_LABEL[item.status] ?? item.status}</span>
            {item.severity && <span className={cn('badge', SEVERITY_COLORS[item.severity])}>{item.severity}</span>}
            {item.priority && <span className={cn('badge', PRIORITY_COLORS[item.priority])}>{item.priority}</span>}
            {item.area && <span className="badge bg-bg-subtle text-fg-muted border border-border">{item.area}</span>}
            {item.targeted_version && (
              <span className="badge bg-accent/10 text-accent border border-accent/30">v{item.targeted_version}</span>
            )}
          </div>
        </div>
        <ChevronDown
          size={18}
          className={cn('text-fg-muted shrink-0 mt-2 transition-transform duration-200', open && 'rotate-180')}
        />
      </button>
      {open && (
        <div className="border-t border-border bg-bg-subtle/30 px-5 py-5 space-y-4">
          {item.plain_summary && (
            <section className="bg-sky-500/5 rounded-md px-4 py-3">
              <div className="text-xs font-bold uppercase tracking-wide text-sky-500 mb-2">In plain language</div>
              <div className="prose-roadmap text-fg">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.plain_summary}</ReactMarkdown>
              </div>
            </section>
          )}
          {(item.summary || item.details) && (
            <section>
              <div className="text-xs font-bold uppercase tracking-wide text-fg-muted mb-2">Technical details</div>
              {item.summary && <p className="text-sm text-fg font-medium mb-3">{item.summary}</p>}
              {item.details && (
                <article className="prose-roadmap">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.details}</ReactMarkdown>
                </article>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  )
}
