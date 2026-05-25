import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type Tone = 'info' | 'success' | 'error' | 'warning'

interface Toast {
  id: string
  message: string
  tone: Tone
}

interface ToastCtx {
  push: (message: string, tone?: Tone) => void
}

const Ctx = createContext<ToastCtx | null>(null)

export function useToast() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>')
  return ctx
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback<ToastCtx['push']>((message, tone = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000)
  }, [])
  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} />
        ))}
      </div>
    </Ctx.Provider>
  )
}

function ToastItem({ toast }: { toast: Toast }) {
  const [open, setOpen] = useState(true)
  useEffect(() => {
    const t = setTimeout(() => setOpen(false), 3500)
    return () => clearTimeout(t)
  }, [])
  const tone =
    toast.tone === 'success' ? 'border-success/40 bg-success/10 text-success'
    : toast.tone === 'error' ? 'border-danger/40 bg-danger/10 text-danger'
    : toast.tone === 'warning' ? 'border-warning/40 bg-warning/10 text-warning'
    : 'border-border bg-bg-card text-fg'
  return (
    <div
      className={cn(
        'pointer-events-auto card px-4 py-3 text-sm border transition-all',
        tone,
        open ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2',
      )}
    >
      {toast.message}
    </div>
  )
}
