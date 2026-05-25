import { Link } from 'react-router-dom'
import {
  Database,
  Film,
  Map as MapIcon,
  Palette,
  Settings,
  Shield,
  Sliders,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'

interface CardEntry {
  to: string
  label: string
  description: string
  icon: LucideIcon
}

const CARDS: CardEntry[] = [
  {
    to: '/settings/general',
    label: 'General',
    description: 'Scan folders and per-folder size thresholds.',
    icon: Sliders,
  },
  {
    to: '/settings/encoding',
    label: 'Encoding',
    description: 'Encoder, preset, CRF, audio defaults and advanced toggles.',
    icon: Film,
  },
  {
    to: '/settings/customize',
    label: 'Customize',
    description: 'Theme and accent color.',
    icon: Palette,
  },
  {
    to: '/settings/database',
    label: 'Database',
    description: 'Backup and restore the metadata store.',
    icon: Database,
  },
  {
    to: '/settings/roadmap',
    label: 'Roadmap',
    description: 'Open bugs, planned improvements, upcoming features.',
    icon: MapIcon,
  },
  {
    to: '/admin/logs',
    label: 'Admin Logs',
    description: 'Live application logs streamed via SSE.',
    icon: Shield,
  },
]

export function SettingsLayoutRedirect() {
  // Name kept for App.tsx wiring; this is now a real index page showing
  // a card grid for each settings sub-section.
  return (
    <PageContainer>
      <PageHeader
        icon={Settings}
        title="Settings"
        description="Pick a section to configure."
      />
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {CARDS.map((c) => (
          <Link
            key={c.to}
            to={c.to}
            className="card p-5 hover:shadow-glow transition group"
          >
            <div className="flex items-center gap-3 mb-2">
              <div className="h-9 w-9 rounded-lg bg-bg-subtle flex items-center justify-center text-fg-muted group-hover:text-accent transition">
                <c.icon size={18} />
              </div>
              <div className="font-medium">{c.label}</div>
            </div>
            <div className="text-xs text-fg-muted">{c.description}</div>
          </Link>
        ))}
      </section>
    </PageContainer>
  )
}
