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
  // Detail fields populated by the same /api/history list response, used by
  // the row View modal. Optional so a slim use of HistoryRecord still works.
  session_id?: string | null
  started_at?: string | null
  completed_at?: string | null
  original_hash?: string | null
  encoded_hash?: string | null
  crf_used?: number | null
  current_frame?: number | null
  total_frames?: number | null
  pct?: number | null
  fps?: string | null
  source_metadata?: string | null
  destination_metadata?: string | null
  ffmpeg_cmd?: string | null
}

// Parsed ffprobe stream — matches what the API serializes into
// source_metadata / destination_metadata. Not every codec populates every
// field; readers should defensive-check before rendering.
export interface MediaStream {
  index: number
  type: 'video' | 'audio' | 'subtitle' | 'attachment' | 'data'
  codec: string
  codec_long?: string | null
  profile?: string | null
  language?: string | null
  title?: string | null
  default?: boolean
  forced?: boolean
  bit_rate?: number | null
  width?: number
  height?: number
  pix_fmt?: string | null
  color_space?: string | null
  color_transfer?: string | null
  level?: number | null
  r_frame_rate?: string | null
  avg_frame_rate?: string | null
  nb_frames?: number | null
  duration?: number | string | null
  sample_rate?: number | null
  channels?: number | null
  channel_layout?: string | null
  filename?: string | null
  mimetype?: string | null
}

export interface MediaFormat {
  filename?: string
  format_name?: string
  format_long_name?: string
  duration?: number
  size?: number
  bit_rate?: number
  nb_streams?: number
  tags?: Record<string, string>
}

export interface ParsedMetadata {
  format?: MediaFormat
  video?: MediaStream[]
  audio?: MediaStream[]
  subtitle?: MediaStream[]
  attachment?: MediaStream[]
  data?: MediaStream[]
  chapters?: Array<{ id?: number; start_time?: string; end_time?: string; tags?: Record<string, string> }>
  streams?: MediaStream[]
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
