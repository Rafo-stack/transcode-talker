import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

interface Props {
  icon: LucideIcon
  title: string
  description?: string
  actions?: ReactNode
}

export function PageHeader({ icon: Icon, title, description, actions }: Props) {
  return (
    <header className="flex items-start gap-3">
      <div className="h-10 w-10 rounded-xl bg-accent/15 text-accent flex items-center justify-center shrink-0">
        <Icon size={20} />
      </div>
      <div className="min-w-0 flex-1">
        <h1 className="text-2xl font-semibold leading-tight">{title}</h1>
        {description && (
          <p className="text-sm text-fg-muted mt-0.5">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </header>
  )
}
