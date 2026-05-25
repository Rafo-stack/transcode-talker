import type { EncodeStatus } from '@/types/api'
import { cn } from '@/lib/utils'
import { Check, X, SkipForward, Square, Loader2, Circle, Ban } from 'lucide-react'

interface StatusBadgeProps {
  status: EncodeStatus | 'ignored'
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const map: Record<string, { cls: string; label: string; Icon: typeof Check }> = {
    completed:   { cls: 'bg-success/10 text-success border border-success/30', label: 'Done',        Icon: Check },
    failed:      { cls: 'bg-danger/10 text-danger border border-danger/30',    label: 'Failed',      Icon: X },
    skipped:     { cls: 'bg-warning/10 text-warning border border-warning/30', label: 'Skipped',     Icon: SkipForward },
    interrupted: { cls: 'bg-fg-muted/10 text-fg-muted border border-border',   label: 'Interrupted', Icon: Square },
    encoding:    { cls: 'bg-accent/10 text-accent border border-accent/30',    label: 'Encoding',    Icon: Loader2 },
    queued:      { cls: 'bg-fg-muted/10 text-fg-muted border border-border',   label: 'Queued',      Icon: Circle },
    ignored:     { cls: 'bg-fg-muted/10 text-fg-muted border border-border italic', label: 'Ignored', Icon: Ban },
  }
  const conf = map[status] ?? map.queued
  const { cls, label, Icon } = conf
  return (
    <span className={cn('badge', cls, className)}>
      <Icon size={11} className={status === 'encoding' ? 'animate-spin' : ''} />
      {label}
    </span>
  )
}
