import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, Sliders, Trash2 } from 'lucide-react'
import { config } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { FolderPickerButton } from '@/components/ui/FolderBrowser'
import type { AppConfig } from '@/types/api'

interface ScanFolder { path: string; threshold_mb: number }

function normalizeScanFolders(raw: unknown): ScanFolder[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((entry) => {
      if (typeof entry === 'string') return { path: entry, threshold_mb: 500 }
      if (entry && typeof entry === 'object' && 'path' in entry) {
        const o = entry as { path: unknown; threshold_mb?: unknown }
        return {
          path: String(o.path ?? ''),
          threshold_mb: typeof o.threshold_mb === 'number' ? o.threshold_mb : 500,
        }
      }
      return null
    })
    .filter((x): x is ScanFolder => !!x && !!x.path)
}

export function GeneralSettingsPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: config.get })
  const [scanFolders, setScanFolders] = useState<ScanFolder[]>([])
  const [excludeFolders, setExcludeFolders] = useState<string[]>([])

  useEffect(() => {
    if (cfgQ.data) {
      setScanFolders(normalizeScanFolders(cfgQ.data.scan_folders))
      setExcludeFolders(
        Array.isArray(cfgQ.data.exclude_folders)
          ? cfgQ.data.exclude_folders.map(String)
          : [],
      )
    }
  }, [cfgQ.data])

  const saveMut = useMutation({
    mutationFn: (patch: Partial<AppConfig>) => config.update(patch),
    onSuccess: () => {
      toast.push('Settings saved', 'success')
      qc.invalidateQueries({ queryKey: ['config'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const onSave = () => {
    saveMut.mutate({
      scan_folders: scanFolders as unknown as AppConfig['scan_folders'],
      exclude_folders: excludeFolders,
    })
  }

  const scanPaths = new Set(scanFolders.map((f) => f.path))
  const excludePaths = new Set(excludeFolders)

  return (
    <PageContainer>
      <PageHeader
        icon={Sliders}
        title="General settings"
        description="Folders to scan and folders to skip."
      />

      <section className="card p-5 space-y-4">
        <div className="flex items-start gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <h2 className="text-sm font-semibold">Scan folders</h2>
            <p className="text-xs text-fg-muted mt-1">
              Each scan folder has its own <span className="font-medium text-fg">minimum size threshold</span> in MB.
              Files smaller than this are skipped during a scan.
            </p>
          </div>
          <FolderPickerButton
            label="Add scan folder…"
            alreadyAdded={scanPaths}
            onPick={(p) =>
              setScanFolders((arr) =>
                arr.some((x) => x.path === p) ? arr : [...arr, { path: p, threshold_mb: 500 }],
              )
            }
          />
        </div>

        {scanFolders.length === 0 ? (
          <div className="text-xs text-fg-muted italic">(none configured)</div>
        ) : (
          <ul className="space-y-1.5">
            {scanFolders.map((f, idx) => (
              <li
                key={f.path}
                className="flex items-center gap-3 px-3 py-2 rounded-md bg-bg-subtle border border-border text-sm"
              >
                <span className="flex-1 truncate font-mono text-xs" title={f.path}>
                  {f.path}
                </span>
                <label className="flex items-center gap-2 shrink-0">
                  <span className="text-[10px] uppercase tracking-wide text-fg-muted">
                    Min size
                  </span>
                  <input
                    type="number"
                    min={0}
                    value={f.threshold_mb}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10) || 0
                      setScanFolders((arr) =>
                        arr.map((x, i) => (i === idx ? { ...x, threshold_mb: v } : x)),
                      )
                    }}
                    className="input w-24 py-1 text-xs"
                  />
                  <span className="text-xs text-fg-muted">MB</span>
                </label>
                <button
                  type="button"
                  onClick={() => setScanFolders((arr) => arr.filter((x) => x.path !== f.path))}
                  className="text-fg-muted hover:text-danger shrink-0"
                  aria-label="Remove"
                  title="Remove this scan folder"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card p-5 space-y-4">
        <div className="flex items-start gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <h2 className="text-sm font-semibold">Exclude folders</h2>
            <p className="text-xs text-fg-muted mt-1">
              Subtrees ignored during scans even when inside a scan folder.
            </p>
          </div>
          <FolderPickerButton
            label="Add exclude folder…"
            alreadyAdded={excludePaths}
            onPick={(p) =>
              setExcludeFolders((arr) => (arr.includes(p) ? arr : [...arr, p]))
            }
          />
        </div>

        {excludeFolders.length === 0 ? (
          <div className="text-xs text-fg-muted italic">(none)</div>
        ) : (
          <ul className="space-y-1.5">
            {excludeFolders.map((p) => (
              <li
                key={p}
                className="flex items-center gap-2 px-3 py-2 rounded-md bg-bg-subtle border border-border text-sm"
              >
                <span className="flex-1 truncate font-mono text-xs" title={p}>
                  {p}
                </span>
                <button
                  type="button"
                  onClick={() => setExcludeFolders((arr) => arr.filter((x) => x !== p))}
                  className="text-fg-muted hover:text-danger"
                  aria-label="Remove"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="flex justify-end">
        <Button onClick={onSave} disabled={saveMut.isPending}>
          <Save size={14} /> {saveMut.isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </PageContainer>
  )
}
