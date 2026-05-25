import { create } from 'zustand'
import type { Job, WSEvent } from '@/types/api'
import { encode as encodeApi } from '@/api/endpoints'

export interface EncodeState {
  running: boolean
  total: number
  doneFiles: number
  currentIdx: number
  currentFile: string | null
  pct: number
  speed: string
  fps: string
  eta: number
  savedMb: number
  jobs: Job[]
  events: WSEvent[]
  setFromActive: (data: {
    session: { status: string; total_files: number; done_files: number } | null
    jobs: Job[]
    events: WSEvent[]
  }) => void
  applyEvent: (e: WSEvent) => void
  clearEvents: () => void
  /** Pull the active session from the API and apply it to the store.
   *  Used after start/queue-add so the Encode page reflects the new
   *  session immediately without waiting for the first WS event. */
  fetchAndSync: () => Promise<void>
  reset: () => void
}

const LOG_CAP = 400

export const useEncode = create<EncodeState>((set) => ({
  running: false,
  total: 0,
  doneFiles: 0,
  currentIdx: 0,
  currentFile: null,
  pct: 0,
  speed: '',
  fps: '',
  eta: 0,
  savedMb: 0,
  jobs: [],
  events: [],

  setFromActive: ({ session, jobs, events }) => {
    if (!session) {
      set({
        running: false, total: 0, doneFiles: 0, currentIdx: 0,
        currentFile: null, pct: 0, speed: '', fps: '', eta: 0,
        savedMb: 0, jobs: [], events: [],
      })
      return
    }
    // Strip huge backend fields the UI never displays (source_metadata,
    // destination_metadata, ffmpeg_cmd can each be tens of kB per job).
    // For a 498-job completed session this drops the payload kept in
    // memory from ~15 MB to ~300 kB and removes the GC pressure that
    // was making clicks lag enough to feel like a blank screen.
    const slimJobs = jobs.map((j) => ({
      id: j.id,
      filename: j.filename,
      path: (j as { original_path?: string }).original_path || j.path || '',
      status: j.status,
      pct: j.pct ?? null,
      speed: j.speed ?? null,
      fps: j.fps ?? null,
      eta_s: j.eta_s ?? null,
      original_size_mb: j.original_size_mb,
      encoded_size_mb:
        (j as { final_size_mb?: number }).final_size_mb ?? j.encoded_size_mb ?? null,
      space_saved_mb: j.space_saved_mb,
      encoder: (j as { encoder_used?: string }).encoder_used ?? j.encoder ?? null,
      error: (j as { error_msg?: string }).error_msg ?? j.error ?? null,
      started_at: j.started_at ?? null,
      finished_at: (j as { completed_at?: string }).completed_at ?? j.finished_at ?? null,
    }))
    const current = slimJobs.find((j) => j.status === 'encoding')
    const saved = slimJobs
      .filter((j) => j.status === 'completed')
      .reduce((a, j) => a + (j.space_saved_mb || 0), 0)
    set({
      running: session.status === 'running',
      total: session.total_files,
      doneFiles: session.done_files,
      currentIdx: session.done_files + (current ? 1 : 0),
      currentFile: current?.filename ?? null,
      pct: current?.pct ?? 0,
      speed: current?.speed ?? '',
      fps: current?.fps ?? '',
      eta: current?.eta_s ?? 0,
      savedMb: saved,
      jobs: slimJobs,
      events: events.slice(-LOG_CAP),
    })
  },

  applyEvent: (e) => {
    set((s) => {
      const events = [...s.events, e].slice(-LOG_CAP)
      if (e.type === 'progress') {
        return {
          events,
          pct: e.pct ?? s.pct,
          speed: e.speed ?? s.speed,
          fps: e.fps ?? s.fps,
          eta: e.eta ?? s.eta,
        }
      }
      return { events }
    })
  },

  clearEvents: () => set({ events: [] }),

  fetchAndSync: async () => {
    try {
      const r = await encodeApi.activeSession()
      useEncode.getState().setFromActive({
        session: r.session,
        jobs: r.jobs || [],
        events: r.events || [],
      })
    } catch {
      /* swallow — the UI keeps its last-known state */
    }
  },

  reset: () =>
    set({
      running: false, total: 0, doneFiles: 0, currentIdx: 0,
      currentFile: null, pct: 0, speed: '', fps: '', eta: 0,
      savedMb: 0, jobs: [], events: [],
    }),
}))
