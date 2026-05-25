import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Ban,
  Check,
  ChevronDown,
  ChevronRight as ChevronRightIcon,
  FolderOpen,
  Loader2,
  Play,
  Plus,
  ScanLine,
  Search,
  Undo2,
} from 'lucide-react'
import { config, encode, scan } from '@/api/endpoints'
import { useToast } from '@/components/ui/Toast'
import { useEncode } from '@/stores/encode'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { StatusBadge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/EmptyState'
import type { ScanFile } from '@/types/api'
import { cn, formatBytes } from '@/lib/utils'

type SortKey = 'name_asc' | 'name_desc' | 'size_desc' | 'size_asc'
type StateFilter = 'all' | 'never_encoded' | 'completed' | 'skipped' | 'failed' | 'interrupted'
type IgnoredFilter = 'hide' | 'all' | 'only'

interface FolderTreeNode {
  name: string
  fullPath: string
  depth: number
  children: Record<string, FolderTreeNode>
  files: ScanFile[]
  totalCount: number
  totalSize: number
  selectedCount: number
}

function buildTree(files: ScanFile[]): FolderTreeNode[] {
  const roots: Record<string, FolderTreeNode> = {}
  for (const f of files) {
    const folder = f.folder || ''
    if (!roots[folder]) {
      roots[folder] = {
        name: folder, fullPath: folder, depth: 0,
        children: {}, files: [], totalCount: 0, totalSize: 0, selectedCount: 0,
      }
    }
    const rel = f.relative_path || f.filename
    const parts = rel.split('/').filter(Boolean)
    parts.pop()
    let cur = roots[folder]
    let acc = folder
    for (const p of parts) {
      acc = `${acc}/${p}`
      if (!cur.children[p]) {
        cur.children[p] = {
          name: p, fullPath: acc, depth: cur.depth + 1,
          children: {}, files: [], totalCount: 0, totalSize: 0, selectedCount: 0,
        }
      }
      cur = cur.children[p]
    }
    cur.files.push(f)
  }
  const aggregate = (node: FolderTreeNode) => {
    let size = 0, count = 0, sel = 0
    for (const f of node.files) {
      size += f.size_mb
      count++
      if (f.selected) sel++
    }
    for (const c of Object.values(node.children)) {
      aggregate(c)
      size += c.totalSize
      count += c.totalCount
      sel += c.selectedCount
    }
    node.totalSize = size
    node.totalCount = count
    node.selectedCount = sel
  }
  const list = Object.values(roots)
  list.forEach(aggregate)
  return list
}

function collectPaths(n: FolderTreeNode): string[] {
  const out: string[] = []
  const walk = (x: FolderTreeNode) => {
    for (const f of x.files) out.push(f.path)
    for (const c of Object.values(x.children)) walk(c)
  }
  walk(n)
  return out
}

function collectFullPaths(n: FolderTreeNode): string[] {
  const out: string[] = []
  const walk = (x: FolderTreeNode) => {
    out.push(x.fullPath)
    for (const c of Object.values(x.children)) walk(c)
  }
  walk(n)
  return out
}

const SORTERS: Record<SortKey, { folder: (a: FolderTreeNode, b: FolderTreeNode) => number; file: (a: ScanFile, b: ScanFile) => number }> = {
  name_asc:  { folder: (a, b) => a.name.localeCompare(b.name),     file: (a, b) => a.filename.localeCompare(b.filename) },
  name_desc: { folder: (a, b) => b.name.localeCompare(a.name),     file: (a, b) => b.filename.localeCompare(a.filename) },
  size_desc: { folder: (a, b) => b.totalSize - a.totalSize,        file: (a, b) => b.size_mb - a.size_mb },
  size_asc:  { folder: (a, b) => a.totalSize - b.totalSize,        file: (a, b) => a.size_mb - b.size_mb },
}

export function ScanPage() {
  const toast = useToast()
  const running = useEncode((s) => s.running)
  const [files, setFiles] = useState<ScanFile[]>([])
  const [filter, setFilter] = useState('')
  const [stateFilter, setStateFilter] = useState<StateFilter>(
    () => (localStorage.getItem('reenc.scan.stateFilter') as StateFilter) || 'all',
  )
  const [ignoredFilter, setIgnoredFilter] = useState<IgnoredFilter>(
    () => (localStorage.getItem('reenc.scan.ignoredFilter') as IgnoredFilter) || 'hide',
  )
  const [sortBy, setSortBy] = useState<SortKey>(
    () => (localStorage.getItem('reenc.scan.sort') as SortKey) || 'name_asc',
  )
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem('reenc.scan.expanded') || '{}') } catch { return {} }
  })
  const [fileStates, setFileStates] = useState<Record<string, string>>({})
  const [ignoredPaths, setIgnoredPaths] = useState<Set<string>>(new Set())

  useEffect(() => { localStorage.setItem('reenc.scan.stateFilter', stateFilter) }, [stateFilter])
  useEffect(() => { localStorage.setItem('reenc.scan.ignoredFilter', ignoredFilter) }, [ignoredFilter])
  useEffect(() => { localStorage.setItem('reenc.scan.sort', sortBy) }, [sortBy])
  useEffect(() => { localStorage.setItem('reenc.scan.expanded', JSON.stringify(expanded)) }, [expanded])

  // Selection is a UI-only concept. We deliberately ignore the `selected`
  // bit that comes back from the server (the legacy UI defaulted everything
  // to selected, which surprised users into encoding files they didn't
  // want). Default is now unselected for every scan / restored scan.
  const withDefaultUnselected = (files: ScanFile[]): ScanFile[] =>
    files.map((f) => ({ ...f, selected: false }))

  // Load last scan + file states on mount.
  useQuery({
    queryKey: ['scan.last'],
    queryFn: async () => {
      const r = await scan.last()
      if (r.files?.length) setFiles(withDefaultUnselected(r.files))
      return r
    },
  })
  useQuery({
    queryKey: ['scan.fileStates'],
    queryFn: async () => {
      const r = await scan.fileStates()
      setFileStates(r.paths || {})
      setIgnoredPaths(new Set(r.ignored || []))
      return r
    },
  })

  const scanMut = useMutation({
    mutationFn: () => scan.run(),
    onSuccess: (r) => {
      setFiles(withDefaultUnselected(r.files || []))
      toast.push(`Found ${r.files?.length ?? 0} files`, 'success')
    },
    onError: (e: Error) => toast.push(e.message || 'Scan failed', 'error'),
  })

  const ignoreMut = useMutation({
    mutationFn: (path: string) => scan.ignore(path),
    onSuccess: (_d, path) => {
      setIgnoredPaths((s) => new Set(s).add(path))
      setFiles((fs) => fs.map((f) => (f.path === path ? { ...f, selected: false } : f)))
      toast.push(`Ignored ${path.split('/').pop()}`, 'info')
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })
  const restoreMut = useMutation({
    mutationFn: (path: string) => scan.unignore(path),
    onSuccess: (_d, path) => {
      setIgnoredPaths((s) => { const n = new Set(s); n.delete(path); return n })
      toast.push(`Restored ${path.split('/').pop()}`, 'success')
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })
  const excludeMut = useMutation({
    mutationFn: (path: string) => config.excludeFolder(path),
    onSuccess: (_d, path) => toast.push(`Excluded ${path}`, 'warning'),
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  // Filtering
  const filtered = useMemo(() => {
    const q = filter.toLowerCase()
    return files
      .filter((f) => !q || f.filename.toLowerCase().includes(q))
      .filter((f) => {
        const ign = ignoredPaths.has(f.path)
        if (ignoredFilter === 'only' && !ign) return false
        if (ignoredFilter === 'hide' && ign) return false
        return true
      })
      .filter((f) => {
        if (stateFilter === 'all') return true
        const st = fileStates[f.path]
        if (stateFilter === 'never_encoded') return !st
        return st === stateFilter
      })
  }, [files, filter, fileStates, ignoredPaths, stateFilter, ignoredFilter])

  const trees = useMemo(() => buildTree(filtered), [filtered])

  const selected = files.filter((f) => f.selected && !ignoredPaths.has(f.path))
  const totalSelectedMb = selected.reduce((a, f) => a + f.size_mb, 0)

  const toggleOne = (path: string) =>
    setFiles((fs) => fs.map((f) => (f.path === path ? { ...f, selected: !f.selected } : f)))
  const toggleAll = (val: boolean) =>
    setFiles((fs) => fs.map((f) => (ignoredPaths.has(f.path) ? f : { ...f, selected: val })))
  const toggleSubtree = (node: FolderTreeNode, val: boolean) => {
    const paths = new Set(collectPaths(node))
    setFiles((fs) =>
      fs.map((f) =>
        paths.has(f.path) && !ignoredPaths.has(f.path) ? { ...f, selected: val } : f,
      ),
    )
  }
  const toggleExpand = (full: string, val: boolean) => setExpanded((e) => ({ ...e, [full]: val }))

  const expandAll = () => {
    const next: Record<string, boolean> = {}
    trees.forEach((t) => collectFullPaths(t).forEach((p) => { next[p] = true }))
    setExpanded(next)
  }
  const collapseAll = () => setExpanded({})

  const fetchAndSync = useEncode((s) => s.fetchAndSync)
  const startMut = useMutation({
    mutationFn: async () => {
      const paths = selected.map((f) => f.path)
      if (running) return encode.queueAdd(paths)
      return encode.start(paths)
    },
    onSuccess: async () => {
      if (running) toast.push(`Added ${selected.length} files to the queue`, 'success')
      else toast.push(`Started encoding ${selected.length} files`, 'success')
      // Pull the just-created session into the store immediately so the
      // Encode page renders the active queue instead of the empty state
      // when the user navigates there. The worker hasn't broadcast any
      // WebSocket events yet at this point.
      await fetchAndSync()
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  return (
    <PageContainer>
      <PageHeader
        icon={ScanLine}
        title="Scan & Select"
        description="Walk the configured folders, pick files, and start a new encode session."
        actions={
          <Button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending}
            variant="primary"
          >
            {scanMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <ScanLine size={14} />}
            {scanMut.isPending ? 'Scanning…' : 'Run scan'}
          </Button>
        }
      />

      <section className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter file names…"
            className="input pl-9"
          />
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          className="input w-auto"
        >
          <option value="name_asc">Name ↑</option>
          <option value="name_desc">Name ↓</option>
          <option value="size_desc">Size ↓</option>
          <option value="size_asc">Size ↑</option>
        </select>
        <Button variant="ghost" size="sm" onClick={expandAll}>Expand all</Button>
        <Button variant="ghost" size="sm" onClick={collapseAll}>Collapse all</Button>
        <Button variant="ghost" size="sm" onClick={() => toggleAll(true)}>Select all</Button>
        <Button variant="ghost" size="sm" onClick={() => toggleAll(false)}>Clear</Button>
      </section>

      <section className="card p-3 space-y-3">
        <FilterRow
          label="State"
          options={[
            { value: 'all', label: 'All' },
            { value: 'never_encoded', label: 'Never' },
            { value: 'completed', label: 'Done' },
            { value: 'skipped', label: 'Skipped' },
            { value: 'failed', label: 'Failed' },
            { value: 'interrupted', label: 'Interrupted' },
          ]}
          value={stateFilter}
          onChange={(v) => setStateFilter(v as StateFilter)}
        />
        <FilterRow
          label="Ignored"
          options={[
            { value: 'hide', label: 'Hide ignored' },
            { value: 'all', label: 'Show all' },
            { value: 'only', label: 'Only ignored' },
          ]}
          value={ignoredFilter}
          onChange={(v) => setIgnoredFilter(v as IgnoredFilter)}
        />
      </section>

      <div className="flex items-center justify-between text-xs text-fg-muted px-1">
        <span>
          {selected.length > 0
            ? <><span className="font-semibold text-fg">{selected.length}</span> file{selected.length === 1 ? '' : 's'} · {formatBytes(totalSelectedMb)} selected</>
            : <>Showing {filtered.length.toLocaleString()} files</>}
        </span>
        <Button
          onClick={() => startMut.mutate()}
          disabled={selected.length === 0 || startMut.isPending}
          variant={running ? 'secondary' : 'success'}
        >
          {running ? <Plus size={14} /> : <Play size={14} />}
          {startMut.isPending
            ? 'Starting…'
            : running
              ? `Add to queue (${selected.length})`
              : `Encode (${selected.length} · ${formatBytes(totalSelectedMb)})`}
        </Button>
      </div>

      {files.length === 0 && !scanMut.isPending && (
        <EmptyState
          icon={FolderOpen}
          title="No files yet"
          description="Run a scan to walk the configured scan folders and surface every video above the size threshold."
          action={<Button onClick={() => scanMut.mutate()}><ScanLine size={14} /> Run scan</Button>}
        />
      )}

      <div className="space-y-3">
        {trees.map((root) => (
          <div key={root.fullPath} className="card overflow-hidden">
            <FolderRow
              node={root}
              sortBy={sortBy}
              expanded={expanded}
              ignoredPaths={ignoredPaths}
              fileStates={fileStates}
              onToggleExpand={toggleExpand}
              onToggleFile={toggleOne}
              onToggleSubtree={toggleSubtree}
              onExclude={(p) => excludeMut.mutate(p)}
              onIgnore={(p) => ignoreMut.mutate(p)}
              onRestore={(p) => restoreMut.mutate(p)}
            />
          </div>
        ))}
      </div>
    </PageContainer>
  )
}

interface RowProps {
  node: FolderTreeNode
  sortBy: SortKey
  expanded: Record<string, boolean>
  ignoredPaths: Set<string>
  fileStates: Record<string, string>
  onToggleExpand: (full: string, v: boolean) => void
  onToggleFile: (path: string) => void
  onToggleSubtree: (node: FolderTreeNode, v: boolean) => void
  onExclude: (p: string) => void
  onIgnore: (p: string) => void
  onRestore: (p: string) => void
}

function FolderRow(props: RowProps) {
  const { node, sortBy, expanded } = props
  const isRoot = node.depth === 0
  const open = node.fullPath in expanded ? expanded[node.fullPath] : isRoot
  const sorter = SORTERS[sortBy] || SORTERS.name_asc
  const childList = Object.values(node.children).sort(sorter.folder)
  const fileList = [...node.files].sort(sorter.file)

  const allSel = node.totalCount > 0 && node.selectedCount === node.totalCount
  const partial = node.selectedCount > 0 && node.selectedCount < node.totalCount
  const cbRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => { if (cbRef.current) cbRef.current.indeterminate = partial }, [partial])

  const indent = node.depth * 18

  return (
    <div>
      <div
        onClick={() => props.onToggleExpand(node.fullPath, !open)}
        className={cn(
          'flex items-center gap-3 px-4 py-2.5 cursor-pointer border-b border-border last:border-b-0 transition-colors',
          isRoot ? 'bg-bg-subtle font-semibold' : 'hover:bg-bg-subtle',
        )}
        style={{ paddingLeft: 16 + indent }}
      >
        {open ? <ChevronDown size={12} className="text-fg-muted" /> : <ChevronRightIcon size={12} className="text-fg-muted" />}
        <input
          ref={cbRef}
          type="checkbox"
          checked={allSel}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => props.onToggleSubtree(node, e.target.checked)}
          className="accent-accent shrink-0"
        />
        <FolderOpen size={14} className={cn('shrink-0', isRoot ? 'text-accent' : 'text-fg-muted')} />
        {/* For the root row we display only the LAST segment of the
            absolute path (e.g. "Animes" instead of "/mnt/animes/Animes")
            because the prefix is the same for every entry from that scan
            folder and only wastes horizontal space. The full path stays in
            the tooltip and is still used as the row's key. */}
        <span className="truncate text-sm" title={isRoot ? node.fullPath : undefined}>
          {isRoot ? (node.fullPath.split('/').filter(Boolean).pop() || node.fullPath || '/') : (node.name || '/')}
        </span>
        <span className="ml-auto text-xs text-fg-muted whitespace-nowrap">
          {node.selectedCount}/{node.totalCount} · {formatBytes(node.totalSize)}
        </span>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); props.onExclude(node.fullPath) }}
          title="Add this folder to exclude list"
          className="text-[10px] px-2 py-0.5 rounded-md bg-bg-card text-fg-muted border border-border hover:text-fg hover:border-fg/30 shrink-0"
        >
          Exclude
        </button>
      </div>
      {open && (
        <>
          {childList.map((c) => (
            <FolderRow key={c.fullPath} {...props} node={c} />
          ))}
          {fileList.map((f) => {
            const ign = props.ignoredPaths.has(f.path)
            const st = props.fileStates[f.path]
            return (
              <div
                key={f.path}
                onClick={() => !ign && props.onToggleFile(f.path)}
                className={cn(
                  'flex items-center gap-3 px-4 py-2 border-b border-border last:border-b-0 text-sm',
                  ign ? 'opacity-60 cursor-default' : 'cursor-pointer hover:bg-bg-subtle',
                  f.selected ? 'bg-accent/5' : '',
                )}
                style={{ paddingLeft: 16 + indent + 28 }}
              >
                <input
                  type="checkbox"
                  checked={f.selected}
                  disabled={ign}
                  onChange={() => props.onToggleFile(f.path)}
                  onClick={(e) => e.stopPropagation()}
                  className="accent-accent shrink-0"
                />
                <span className="flex-1 truncate" title={f.path}>{f.filename}</span>
                {st && <StatusBadge status={st as never} />}
                {ign && <StatusBadge status="ignored" />}
                <span className="text-xs text-fg-muted whitespace-nowrap shrink-0">
                  {formatBytes(f.size_mb)}
                </span>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); ign ? props.onRestore(f.path) : props.onIgnore(f.path) }}
                  className={cn(
                    'text-[10px] px-2 py-0.5 rounded-md border shrink-0 transition-colors',
                    'inline-flex items-center gap-1 whitespace-nowrap',
                    ign
                      ? 'bg-bg-card text-success border-success/30 hover:bg-success/10'
                      : 'bg-bg-card text-fg-muted border-border hover:text-fg hover:border-fg/30',
                  )}
                  title={ign ? 'Restore this file' : 'Ignore this file'}
                >
                  {ign ? <><Undo2 size={10} /> Restore</> : <><Ban size={10} /> Ignore</>}
                </button>
              </div>
            )
          })}
          {fileList.length === 0 && childList.length === 0 && (
            <div className="px-4 py-3 text-xs text-fg-muted italic" style={{ paddingLeft: 16 + indent + 28 }}>
              (empty)
            </div>
          )}
        </>
      )}
    </div>
  )
}

interface FilterRowProps {
  label: string
  options: { value: string; label: string }[]
  value: string
  onChange: (v: string) => void
}

function FilterRow({ label, options, value, onChange }: FilterRowProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="label w-16 shrink-0">{label}</span>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={cn(
              'px-2.5 py-1 rounded-md text-xs font-medium border transition-colors',
              active
                ? 'bg-accent text-white border-accent'
                : 'bg-bg-subtle text-fg-muted border-border hover:bg-bg-card hover:text-fg',
            )}
          >
            {active && <Check size={11} className="inline mr-1" />}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
