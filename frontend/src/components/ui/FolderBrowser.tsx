import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUp,
  Check,
  ChevronRight,
  Folder,
  Loader2,
  X,
} from 'lucide-react'
import { scan } from '@/api/endpoints'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'

interface Props {
  open: boolean
  onClose: () => void
  onSelect: (path: string) => void
  /** Starting directory. Defaults to `/mnt` (the whitelisted browse root). */
  initialPath?: string
  /** Optional set of paths already in use — disables the Select button when
   *  the current directory is already in the parent list. */
  alreadyAdded?: Set<string>
  title?: string
}

const DEFAULT_ROOT = '/mnt'

export function FolderBrowser({
  open, onClose, onSelect, initialPath, alreadyAdded, title = 'Pick a folder',
}: Props) {
  const [path, setPath] = useState(initialPath || DEFAULT_ROOT)

  // Reset to the initial path each time the modal is reopened so the user
  // doesn't land deep inside the previous selection.
  useEffect(() => {
    if (open) setPath(initialPath || DEFAULT_ROOT)
  }, [open, initialPath])

  const browseQ = useQuery({
    queryKey: ['browse', path],
    queryFn: () => scan.browse(path),
    enabled: open,
  })

  if (!open) return null

  const dirs = browseQ.data?.dirs ?? []
  const parent = browseQ.data?.parent
  const isAlreadyAdded = !!alreadyAdded?.has(path)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-2xl max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-5 py-3 border-b border-border flex items-center gap-3">
          <Folder size={18} className="text-accent" />
          <div className="font-semibold flex-1">{title}</div>
          <button
            type="button"
            onClick={onClose}
            className="h-8 w-8 inline-flex items-center justify-center rounded-md text-fg-muted hover:bg-bg-subtle hover:text-fg"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </header>

        {/* Breadcrumb / current path */}
        <div className="px-5 py-3 border-b border-border flex items-center gap-2 text-sm">
          <button
            type="button"
            disabled={!parent}
            onClick={() => parent && setPath(parent)}
            title="Up one level"
            className="h-7 w-7 inline-flex items-center justify-center rounded-md text-fg-muted hover:bg-bg-subtle hover:text-fg disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
          >
            <ArrowUp size={14} />
          </button>
          <code className="font-mono text-xs bg-bg-subtle border border-border rounded px-2 py-1 flex-1 truncate" title={path}>
            {path}
          </code>
        </div>

        {/* Directory list */}
        <div className="flex-1 overflow-y-auto min-h-[200px]">
          {browseQ.isLoading && (
            <div className="flex items-center justify-center py-8 text-fg-muted text-sm">
              <Loader2 size={14} className="animate-spin mr-2" /> Loading…
            </div>
          )}
          {browseQ.error && (
            <div className="px-5 py-6 text-sm text-danger">
              Can't browse this path. It may be outside the allowed roots ({DEFAULT_ROOT}/*).
            </div>
          )}
          {!browseQ.isLoading && !browseQ.error && dirs.length === 0 && (
            <div className="px-5 py-6 text-sm text-fg-muted italic">
              No sub-folders here. Pick this one to select it.
            </div>
          )}
          <ul className="divide-y divide-border">
            {dirs.map((d) => {
              const child = path.replace(/\/$/, '') + '/' + d
              return (
                <li key={d}>
                  <button
                    type="button"
                    onClick={() => setPath(child)}
                    className="w-full px-5 py-2.5 flex items-center gap-3 text-sm hover:bg-bg-subtle text-left"
                  >
                    <Folder size={14} className="text-fg-muted shrink-0" />
                    <span className="flex-1 truncate">{d}</span>
                    <ChevronRight size={14} className="text-fg-muted shrink-0" />
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        <footer className="px-5 py-3 border-t border-border flex items-center gap-2">
          {isAlreadyAdded && (
            <span className="text-xs text-warning">Already in the list.</span>
          )}
          <Button variant="ghost" onClick={onClose} className="ml-auto">Cancel</Button>
          <Button
            onClick={() => { onSelect(path); onClose() }}
            disabled={isAlreadyAdded}
          >
            <Check size={14} /> Select this folder
          </Button>
        </footer>
      </div>
    </div>
  )
}

/** Helper for "pick a folder" trigger buttons. */
export function FolderPickerButton({
  className, onPick, alreadyAdded, label, initialPath,
}: {
  className?: string
  onPick: (path: string) => void
  alreadyAdded?: Set<string>
  label?: string
  initialPath?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn('btn-secondary', className)}
      >
        <Folder size={14} /> {label ?? 'Browse…'}
      </button>
      <FolderBrowser
        open={open}
        onClose={() => setOpen(false)}
        onSelect={onPick}
        alreadyAdded={alreadyAdded}
        initialPath={initialPath}
      />
    </>
  )
}
