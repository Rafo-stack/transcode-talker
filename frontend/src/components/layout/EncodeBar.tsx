import { useEncode } from '@/stores/encode'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { formatDuration } from '@/lib/utils'
import { Activity } from 'lucide-react'

export function EncodeBar() {
  const { running, currentFile, currentIdx, total, pct, speed, eta } = useEncode()
  if (!running) return null
  return (
    <div className="border-b border-border bg-bg-subtle px-4 py-2.5 flex items-center gap-4">
      <Activity size={14} className="text-success animate-pulse shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-3 mb-1">
          <span className="text-xs font-semibold text-accent truncate min-w-0">
            [{currentIdx}/{total}] {currentFile ?? '…'}
          </span>
          <span className="text-xs text-fg-muted whitespace-nowrap shrink-0">
            {speed && `${speed} · `}ETA {formatDuration(eta)} · {(pct || 0).toFixed(1)}%
          </span>
        </div>
        <ProgressBar value={pct} />
      </div>
    </div>
  )
}
