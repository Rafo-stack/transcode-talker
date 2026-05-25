import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { HelpCircle, Search } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { helpContent } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { cn } from '@/lib/utils'

const LANG_LABEL: Record<string, string> = {
  en: 'English',
  'pt-BR': 'Português',
  es: 'Español',
  fr: 'Français',
  'zh-CN': '中文',
  ja: '日本語',
}

export function HelpPage() {
  const [lang, setLang] = useState<string>(() => localStorage.getItem('reenc.help.lang') || 'en')
  const [query, setQuery] = useState('')
  const [activeId, setActiveId] = useState<string | null>(null)

  const helpQ = useQuery({
    queryKey: ['help', lang],
    queryFn: () => helpContent(lang),
  })

  const sections = helpQ.data?.sections ?? []
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sections
    return sections.filter(
      (s) => s.title.toLowerCase().includes(q) || s.body.toLowerCase().includes(q),
    )
  }, [sections, query])

  const changeLang = (l: string) => {
    setLang(l)
    try { localStorage.setItem('reenc.help.lang', l) } catch { /* noop */ }
  }

  return (
    <PageContainer>
      <PageHeader
        icon={HelpCircle}
        title="Help"
        description="Manual, troubleshooting, glossary and FAQ — straight from the API."
        actions={
          <select
            value={lang}
            onChange={(e) => changeLang(e.target.value)}
            className="input w-auto"
            title="Language"
          >
            {(helpQ.data?.languages ?? Object.keys(LANG_LABEL)).map((l) => (
              <option key={l} value={l}>{LANG_LABEL[l] ?? l}</option>
            ))}
          </select>
        }
      />

      <section className="card p-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search section title or content…"
            className="input pl-9"
          />
        </div>
      </section>

      {helpQ.isLoading && <div className="text-sm text-fg-muted">Loading help…</div>}
      {helpQ.error && (
        <div className="card p-4 text-sm border-danger/40">Failed to load help content.</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4">
        {/* Table of contents */}
        <aside className="card p-2 max-h-[calc(100vh-220px)] overflow-y-auto lg:sticky lg:top-4 self-start">
          <ul className="space-y-0.5">
            {visible.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  onClick={() => setActiveId(s.id)}
                  className={cn(
                    'block px-3 py-2 rounded-md text-sm transition-colors',
                    activeId === s.id
                      ? 'bg-accent/10 text-accent'
                      : 'text-fg-muted hover:bg-bg-subtle hover:text-fg',
                  )}
                >
                  {s.title}
                </a>
              </li>
            ))}
            {visible.length === 0 && !helpQ.isLoading && (
              <li className="px-3 py-2 text-xs text-fg-muted italic">No matches.</li>
            )}
          </ul>
        </aside>

        {/* Content */}
        <div className="space-y-6">
          {visible.map((s) => (
            <article key={s.id} id={s.id} className="card p-6 scroll-mt-4">
              <h2 className="text-lg font-semibold mb-4">{s.title}</h2>
              <div className="prose-roadmap">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.body}</ReactMarkdown>
              </div>
            </article>
          ))}
        </div>
      </div>
    </PageContainer>
  )
}
