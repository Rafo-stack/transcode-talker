import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ToastProvider } from '@/components/ui/Toast'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { AppLayout } from '@/components/layout/AppLayout'
import { useTheme, loadStoredTheme } from '@/stores/theme'
import { useEncode } from '@/stores/encode'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { WSEvent } from '@/types/api'

import { DashboardPage } from '@/pages/DashboardPage'
import { ScanPage } from '@/pages/ScanPage'
import { EncodePage } from '@/pages/EncodePage'
import { HistoryPage } from '@/pages/HistoryPage'
import { SettingsLayoutRedirect as SettingsIndexPage } from '@/pages/SettingsLayoutRedirect'
import { GeneralSettingsPage } from '@/pages/GeneralSettingsPage'
import { EncodingSettingsPage } from '@/pages/EncodingSettingsPage'
import { CustomizePage } from '@/pages/CustomizePage'
import { DatabasePage } from '@/pages/DatabasePage'
import { RoadmapPage } from '@/pages/RoadmapPage'
import { AdminLogsPage } from '@/pages/AdminLogsPage'
import { HelpPage } from '@/pages/HelpPage'

const qc = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
})

function SessionSync() {
  const applyEvent = useEncode((s) => s.applyEvent)
  const fetchAndSync = useEncode((s) => s.fetchAndSync)

  useEffect(() => { fetchAndSync() }, [fetchAndSync])

  useWebSocket('/ws', (data) => {
    const e = data as WSEvent
    applyEvent(e)
    if (['queue_start', 'queue_appended', 'queue_done', 'queue_stopped', 'file_start', 'file_done'].includes(e.type)) {
      fetchAndSync()
    }
  })

  return null
}

export default function App() {
  const applyTheme = useTheme((s) => s.apply)

  useEffect(() => {
    applyTheme(loadStoredTheme())
  }, [applyTheme])

  return (
    <ErrorBoundary>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <BrowserRouter>
          <SessionSync />
          <Routes>
            <Route path="/" element={<AppLayout />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<DashboardPage />} />
              <Route path="scan" element={<ScanPage />} />
              <Route path="encode" element={<EncodePage />} />
              <Route path="history" element={<HistoryPage />} />
              <Route path="help" element={<HelpPage />} />
              <Route path="settings" element={<SettingsIndexPage />} />
              <Route path="settings/general" element={<GeneralSettingsPage />} />
              <Route path="settings/encoding" element={<EncodingSettingsPage />} />
              <Route path="settings/customize" element={<CustomizePage />} />
              <Route path="settings/database" element={<DatabasePage />} />
              <Route path="settings/roadmap" element={<RoadmapPage />} />
              <Route path="admin/logs" element={<AdminLogsPage />} />
              {/* Back-compat redirect for the removed Storage page. */}
              <Route path="settings/storage" element={<Navigate to="/settings" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
    </ErrorBoundary>
  )
}
