export type EncodeStatus =
  | 'queued'
  | 'encoding'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'interrupted'

export interface ScanFile {
  path: string
  filename: string
  folder: string
  relative_path?: string
  size_mb: number
  selected: boolean
}

export interface Job {
  id: number
  filename: string
  path: string
  status: EncodeStatus
  pct?: number | null
  speed?: string | null
  fps?: string | null
  eta_s?: number | null
  original_size_mb: number
  encoded_size_mb?: number | null
  space_saved_mb: number
  encoder?: string | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface Session {
  id: number
  status: 'running' | 'completed' | 'stopped' | 'failed'
  total_files: number
  done_files: number
  started_at: string
  finished_at?: string | null
}

export interface SessionActive {
  session: Session | null
  jobs: Job[]
  events: WSEvent[]
}

export interface WSEvent {
  type: string
  time?: string
  idx?: number
  total?: number
  file?: string
  msg?: string
  pct?: number
  fps?: string
  speed?: string
  eta?: number
  frame?: string
  status?: EncodeStatus
  space_saved_mb?: number
}

export interface HistoryRecord {
  id: number
  filename: string
  path: string
  status: EncodeStatus
  original_size_mb: number
  encoded_size_mb?: number | null
  space_saved_mb: number
  encoder?: string | null
  duration_s?: number | null
  finished_at: string
  error?: string | null
}

export interface HistoryStats {
  total: number
  completed: number
  failed: number
  skipped: number
  interrupted: number
  total_saved_mb: number
  total_original_mb: number
}

export interface AppConfig {
  theme?: 'dark' | 'light' | 'auto'
  accent_color?: string
  brand_name?: string
  min_size_mb?: number
  scan_folders?: string[]
  exclude_folders?: string[]
  preset?: string
  encoder?: string
  crf?: number
  audio_codec?: string
  audio_bitrate?: string
  [k: string]: unknown
}

export type RoadmapCategory = 'bugs' | 'improvements' | 'features'

export interface RoadmapItem {
  id: string
  category: RoadmapCategory
  title: string
  summary?: string
  plain_summary?: string
  details?: string
  status: 'open' | 'planned' | 'in_progress' | 'deferred' | 'done'
  severity?: 'Critical' | 'High' | 'Medium' | 'Low' | null
  priority?: 'High' | 'Medium' | 'Low' | null
  area?: string | null
  targeted_version?: string | null
}

export interface RoadmapResponse {
  bugs: RoadmapItem[]
  improvements: RoadmapItem[]
  features: RoadmapItem[]
  counts: { bugs: number; improvements: number; features: number; total: number }
}

export interface LogEntry {
  seq: number
  ts: string
  level: string
  event: string
  logger: string
  fields: Record<string, unknown>
}
