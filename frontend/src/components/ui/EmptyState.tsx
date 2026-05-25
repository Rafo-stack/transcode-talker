import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  icon?: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon: Icon, title, description, action, className }: Props) {
  return (
    <div className={cn('card p-10 text-center flex flex-col items-center gap-3', className)}>
      {Icon && (
        <div className="h-12 w-12 rounded-2xl bg-bg-subtle text-fg-muted flex items-center justify-center">
          <Icon size={22} />
        </div>
      )}
      <div className="font-semibold">{title}</div>
      {description && (
        <div className="text-sm text-fg-muted max-w-md">{description}</div>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
