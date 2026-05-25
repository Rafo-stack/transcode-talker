import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  ChevronRight,
  Database,
  Film,
  HelpCircle,
  LayoutDashboard,
  Map as MapIcon,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Palette,
  ScanLine,
  Settings,
  Shield,
  Sliders,
  Sun,
  History as HistoryIcon,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTheme } from '@/stores/theme'
import { useEncode } from '@/stores/encode'
import { APP_NAME, APP_VERSION } from '@/version'
import { EncodeBar } from '@/components/layout/EncodeBar'

type NavItem = {
  to: string
  label: string
  icon: LucideIcon
  children?: NavItem[]
  matchPrefixes?: string[]
}

const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/scan', label: 'Scan & Select', icon: ScanLine },
  { to: '/encode', label: 'Encode', icon: Film },
  { to: '/history', label: 'History', icon: HistoryIcon },
  { to: '/help', label: 'Help', icon: HelpCircle },
  {
    to: '/settings',
    label: 'Settings',
    icon: Settings,
    matchPrefixes: ['/settings', '/admin'],
    children: [
      { to: '/settings/general', label: 'General', icon: Sliders },
      { to: '/settings/encoding', label: 'Encoding', icon: Film },
      { to: '/settings/customize', label: 'Customize', icon: Palette },
      { to: '/settings/database', label: 'Database', icon: Database },
      { to: '/settings/roadmap', label: 'Roadmap', icon: MapIcon },
      { to: '/admin/logs', label: 'Admin Logs', icon: Shield },
    ],
  },
]

const COLLAPSE_KEY = 'reenc.sidebar.collapsed'
const SUBMENU_PREFIX = 'reenc.sidebar.submenu.'

export function AppLayout() {
  const theme = useTheme((s) => s.theme)
  const applyTheme = useTheme((s) => s.apply)
  const running = useEncode((s) => s.running)
  const location = useLocation()

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })

  const [expandedSubmenus, setExpandedSubmenus] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    try {
      for (const it of navItems) {
        if (it.children?.length) {
          init[it.to] = localStorage.getItem(SUBMENU_PREFIX + it.to) === '1'
        }
      }
    } catch { /* noop */ }
    return init
  })

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0') } catch { /* noop */ }
  }, [collapsed])

  const toggleSubmenu = (key: string) => {
    setExpandedSubmenus((prev) => {
      const next = !prev[key]
      try { localStorage.setItem(SUBMENU_PREFIX + key, next ? '1' : '0') } catch { /* noop */ }
      return { ...prev, [key]: next }
    })
  }

  return (
    <div className="h-screen flex bg-bg text-fg overflow-hidden">
      <aside
        className={cn(
          'hidden md:flex flex-col border-r border-border bg-bg-subtle transition-[width] duration-200 h-full',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        <div className={cn('px-3 py-4 flex items-center gap-2', collapsed ? 'justify-center' : 'justify-between')}>
          {!collapsed && (
            <div className="flex items-center gap-2 min-w-0">
              <div className="h-8 w-8 shrink-0 rounded-lg bg-accent flex items-center justify-center text-white font-bold">
                T
              </div>
              <div className="min-w-0">
                <div className="font-semibold leading-tight truncate">{APP_NAME}</div>
                <div className="text-xs text-fg-muted -mt-0.5 truncate">v{APP_VERSION}</div>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="h-8 w-8 inline-flex items-center justify-center rounded-lg text-fg-muted hover:bg-bg-card hover:text-fg transition"
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>

        <nav className={cn('flex-1 space-y-1 overflow-y-auto', collapsed ? 'px-2' : 'px-3')}>
          {navItems.map((item) => {
            const insideParent =
              item.matchPrefixes?.some((p) => location.pathname.startsWith(p)) ?? false
            const hasChildren = !!(item.children && item.children.length)
            const submenuOpen = expandedSubmenus[item.to] ?? false
            return (
              <div key={item.to}>
                <div className="flex items-center gap-1">
                  <NavLink
                    to={item.to}
                    end={!!item.matchPrefixes}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center rounded-lg text-sm font-medium transition-colors relative',
                        collapsed ? 'justify-center px-0 py-2 w-full' : 'gap-3 px-3 py-2 flex-1 min-w-0',
                        isActive || (insideParent && !collapsed)
                          ? 'bg-accent/10 text-accent'
                          : 'text-fg-muted hover:bg-bg-card hover:text-fg',
                      )
                    }
                  >
                    <item.icon size={18} />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {/* Encoding-in-progress indicator */}
                    {item.to === '/encode' && running && (
                      <span className={cn(
                        'h-2 w-2 rounded-full bg-success animate-pulse',
                        collapsed ? 'absolute top-1 right-1' : 'ml-auto',
                      )} />
                    )}
                  </NavLink>
                  {!collapsed && hasChildren && (
                    <button
                      type="button"
                      onClick={() => toggleSubmenu(item.to)}
                      aria-expanded={submenuOpen}
                      className="h-8 w-8 shrink-0 inline-flex items-center justify-center rounded-lg text-fg-muted hover:bg-bg-card hover:text-fg transition"
                    >
                      <ChevronRight
                        size={14}
                        className={cn('transition-transform duration-200', submenuOpen && 'rotate-90')}
                      />
                    </button>
                  )}
                </div>
                {!collapsed && hasChildren && submenuOpen && (
                  <div className="ml-7 mt-1 space-y-1 border-l border-border pl-3">
                    {item.children!.map((child) => (
                      <NavLink
                        key={child.to}
                        to={child.to}
                        className={({ isActive }) =>
                          cn(
                            'flex items-center gap-2 rounded-lg text-sm font-medium transition-colors px-2 py-1.5',
                            isActive
                              ? 'bg-accent/10 text-accent'
                              : 'text-fg-muted hover:bg-bg-card hover:text-fg',
                          )
                        }
                      >
                        <child.icon size={14} />
                        <span>{child.label}</span>
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        <div className={cn('border-t border-border space-y-2', collapsed ? 'p-2' : 'p-3')}>
          <button
            onClick={() => applyTheme(theme === 'dark' ? 'light' : 'dark')}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            className={cn('btn-ghost w-full', collapsed ? 'justify-center' : 'justify-start')}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            {!collapsed && <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>}
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile header */}
        <header className="md:hidden border-b border-border bg-bg-subtle px-4 py-3 flex items-center justify-between">
          <div className="font-semibold">{APP_NAME}</div>
          {running && (
            <div className="text-xs text-success inline-flex items-center gap-1">
              <Activity size={12} className="animate-pulse" /> encoding
            </div>
          )}
        </header>
        {/* Mobile nav strip */}
        <nav className="md:hidden border-b border-border bg-bg-subtle px-2 py-2 flex gap-1 overflow-x-auto">
          {navItems.flatMap((it) => [it, ...(it.children ?? [])]).map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={!!it.matchPrefixes}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap',
                  isActive ? 'bg-accent text-white' : 'text-fg-muted hover:bg-bg-card',
                )
              }
            >
              <it.icon size={14} />
              {it.label}
            </NavLink>
          ))}
        </nav>
        <EncodeBar />
        <main className="flex-1 overflow-auto animate-fade-in">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
