import { cn } from '@/lib/utils'

interface Props {
  value: number
  className?: string
  tone?: 'accent' | 'success' | 'warning' | 'danger'
}

export function ProgressBar({ value, className, tone = 'accent' }: Props) {
  const pct = Math.max(0, Math.min(100, value))
  const fill =
    tone === 'success' ? 'bg-success'
    : tone === 'warning' ? 'bg-warning'
    : tone === 'danger' ? 'bg-danger'
    : 'bg-accent'
  return (
    <div className={cn('h-2 rounded-full bg-bg-subtle overflow-hidden', className)}>
      <div
        className={cn('h-full rounded-full transition-[width] duration-300', fill)}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
