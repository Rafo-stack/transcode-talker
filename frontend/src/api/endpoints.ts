import { api } from './client'
import type {
  AppConfig,
  HistoryRecord,
  HistoryStats,
  Job,
  LogEntry,
  RoadmapResponse,
  ScanFile,
  SessionActive,
} from '@/types/api'

export const config = {
  get: () => api.get<AppConfig>('/api/config').then((r) => r.data),
  update: (patch: Partial<AppConfig>) =>
    api.post<AppConfig>('/api/config', patch).then((r) => r.data),
  firstRun: () =>
    api.get<{ first_run: boolean }>('/api/config/first-run').then((r) => r.data),
  excludeFolder: (path: string) =>
    api.post('/api/config/exclude-folder', { path }).then((r) => r.data),
}

export const scan = {
  run: () =>
    api.post<{ files: ScanFile[] }>('/api/scan', {}).then((r) => r.data),
  last: () =>
    api.get<{ files: ScanFile[] }>('/api/scan/last').then((r) => r.data),
  fileStates: () =>
    api
      .get<{ paths: Record<string, string>; ignored: string[] }>('/api/scan/file-states')
      .then((r) => r.data),
  ignore: (path: string) =>
    api.post('/api/files/ignore', { path }).then((r) => r.data),
  unignore: (path: string) =>
    api.post('/api/files/unignore', { path }).then((r) => r.data),
  ignored: () =>
    api.get<{ paths: string[] }>('/api/files/ignored').then((r) => r.data),
  browse: (path: string) =>
    api
      .get<{ path: string; dirs: string[]; parent: string | null }>('/api/browse', {
        params: { path },
      })
      .then((r) => r.data),
}

export const encode = {
  start: (paths: string[]) =>
    api.post<{ session_id: number }>('/api/encode/start', { paths }).then((r) => r.data),
  queueAdd: (paths: string[]) =>
    api.post<{ added: number }>('/api/encode/queue/add', { paths }).then((r) => r.data),
  stop: () =>
    api.post<{ cancelled: number }>('/api/encode/stop', {}).then((r) => r.data),
  status: () => api.get('/api/encode/status').then((r) => r.data),
  forceReset: () =>
    api.post('/api/encode/force-reset', {}).then((r) => r.data),
  activeSession: () =>
    api.get<SessionActive>('/api/session/active').then((r) => r.data),
  activeJobs: () =>
    api.get<{ jobs: Job[] }>('/api/session/active/jobs').then((r) => r.data),
}

export interface HistoryQuery {
  page?: number
  page_size?: number
  sort_by?: string
  order?: 'asc' | 'desc'
  status?: string
  encoder?: string
  from?: string
  to?: string
}

// Backend response shape (raw column names match the DB).
interface RawHistoryRow {
  id: number
  filename: string
  original_path: string
  original_size_mb: number
  final_size_mb: number | null
  space_saved_mb: number
  encoder_used: string | null
  status: HistoryRecord['status']
  error_msg: string | null
  started_at: string | null
  completed_at: string | null
}

function normalizeRecord(r: RawHistoryRow): HistoryRecord {
  return {
    id: r.id,
    filename: r.filename,
    path: r.original_path,
    status: r.status,
    original_size_mb: r.original_size_mb,
    encoded_size_mb: r.final_size_mb,
    space_saved_mb: r.space_saved_mb,
    encoder: r.encoder_used,
    error: r.error_msg,
    finished_at: r.completed_at ?? r.started_at ?? '',
  }
}

// Map the field names the UI uses (sort_by="finished_at") onto the column
// names the backend whitelists (`completed_at`). Unknown values fall through
// untouched — the API will reject them and revert to its own default.
const SORT_MAP: Record<string, string> = {
  finished_at: 'completed_at',
  encoded_size_mb: 'final_size_mb',
}

export const history = {
  list: (q: HistoryQuery = {}) => {
    const page = q.page ?? 1
    const pageSize = q.page_size ?? 200
    const params: Record<string, string | number> = {
      limit: pageSize,
      offset: (page - 1) * pageSize,
      sort_by: SORT_MAP[q.sort_by ?? ''] ?? q.sort_by ?? 'id',
      order: q.order ?? 'desc',
    }
    if (q.status) params.filter_status = q.status
    if (q.encoder) params.filter_encoder = q.encoder
    if (q.from) params.from_date = q.from
    if (q.to) params.to_date = q.to
    return api
      .get<{ records: RawHistoryRow[]; total: number }>('/api/history', { params })
      .then((r) => ({
        items: (r.data.records ?? []).map(normalizeRecord),
        total: r.data.total ?? 0,
      }))
  },
  stats: () =>
    api.get<Partial<HistoryStats> & { failed: number | null }>('/api/history/stats').then((r) => ({
      total: r.data.total ?? 0,
      completed: r.data.completed ?? 0,
      // Backend currently returns null for failed (B-106) — coerce to 0.
      failed: r.data.failed ?? 0,
      skipped: r.data.skipped ?? 0,
      interrupted: r.data.interrupted ?? 0,
      total_saved_mb: r.data.total_saved_mb ?? 0,
      total_original_mb: r.data.total_original_mb ?? 0,
    })),
  encodedPaths: () =>
    api.get<{ paths: string[] }>('/api/history/encoded-paths').then((r) => r.data),
  delete: (id: number) =>
    api.post(`/api/history/${id}/delete`, {}).then((r) => r.data),
  bulkDelete: (ids: number[]) =>
    api.post('/api/history/bulk-delete', { ids }).then((r) => r.data),
  exportUrl: () => `/api/history/export`,
  importJson: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/api/history/import', fd).then((r) => r.data)
  },
}

interface RawHddStatus {
  temp_path?: string
  files?: { name: string; size_mb: number; path: string }[]
  total_mb?: number
  disk?: { total_gb: number; used_gb: number; free_gb: number }
}

export interface HddStatus {
  mount: string | null
  total_gb: number | null
  used_gb: number | null
  free_gb: number | null
  percent: number | null
  stash_files: { path: string; size_mb: number }[]
}

export const hdd = {
  status: () =>
    api.get<RawHddStatus>('/api/hdd/status').then((r): HddStatus => {
      const d = r.data ?? {}
      const total = d.disk?.total_gb ?? null
      const used = d.disk?.used_gb ?? null
      const free = d.disk?.free_gb ?? null
      const percent = total && used != null ? (used / total) * 100 : null
      return {
        mount: d.temp_path ?? null,
        total_gb: total,
        used_gb: used,
        free_gb: free,
        percent,
        stash_files: (d.files ?? []).map((f) => ({ path: f.path, size_mb: f.size_mb })),
      }
    }),
  clean: () => api.post('/api/hdd/clean', {}).then((r) => r.data),
}

export const jobs = {
  logs: (jobId: number) =>
    api.get(`/api/jobs/${jobId}/logs`).then((r) => r.data),
  logsExportUrl: (jobId: number) => `/api/jobs/${jobId}/logs/export`,
  // Cancel a single job. Behavior depends on its current status:
  //   queued   → marked 'interrupted'; worker skips it.
  //   encoding → triggers a session stop (per-file cancel without aborting
  //              the queue is a future improvement, see roadmap).
  cancel: (jobId: number) =>
    api.post(`/api/jobs/${jobId}/cancel`, {}).then((r) => r.data),
}

interface RawDbState {
  existed_at_startup: boolean
  had_history: boolean
  backup_taken: string | null
  live_has_history?: boolean
  db_path?: string
  backend_active?: string
  backend_requested?: string
}

export interface DbState {
  backend: string
  version: string | null
  size_mb: number | null
  db_path: string | null
  existed_at_startup: boolean
  had_history: boolean
}

export const db = {
  state: () =>
    api.get<RawDbState>('/api/db/state').then((r): DbState => ({
      backend: r.data.backend_active ?? 'unknown',
      version:
        r.data.backend_requested && r.data.backend_requested !== r.data.backend_active
          ? `requested=${r.data.backend_requested}`
          : null,
      size_mb: null,
      db_path: r.data.db_path ?? null,
      existed_at_startup: r.data.existed_at_startup,
      had_history: r.data.had_history,
    })),
  backups: () =>
    api.get<{ backups: { name: string; size: number; created_at: string }[] } | { name: string; size: number; created_at: string }[]>('/api/db/backups').then((r) => {
      // Endpoint historically returned a bare array; some forks wrap it.
      const raw = Array.isArray(r.data) ? r.data : r.data.backups
      return { backups: raw ?? [] }
    }),
  backup: () => api.post('/api/db/backup', {}).then((r) => r.data),
  restore: (name: string) =>
    api.post('/api/db/restore', { name }).then((r) => r.data),
}

export const recoveredSinceStartup = () =>
  api.get<{ records: { id: number; filename: string }[] }>('/api/recovered-since-startup').then((r) => r.data)

export const health = () => api.get('/api/health').then((r) => r.data)

export interface HelpResponse {
  lang: string
  languages: string[]
  sections: { id: string; title: string; body: string }[]
}

export const helpContent = (lang?: string) =>
  api.get<HelpResponse>('/api/help', { params: lang ? { lang } : {} }).then((r) => r.data)

export const roadmap = {
  get: () => api.get<RoadmapResponse>('/api/roadmap').then((r) => r.data),
}

export const admin = {
  recentLogs: ({ limit = 2000 }: { limit?: number } = {}) =>
    api
      .get<{ items: LogEntry[]; last_seq: number }>('/api/admin/logs/recent', {
        params: { limit },
      })
      .then((r) => r.data),
  streamUrl: () => `/api/admin/logs/stream`,
}
