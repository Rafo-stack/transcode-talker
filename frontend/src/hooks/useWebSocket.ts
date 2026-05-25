import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '@/api/client'

export interface WSStatus {
  connected: boolean
  attempts: number
}

type Handler = (data: unknown) => void

export function useWebSocket(path: string, onMessage: Handler) {
  const [status, setStatus] = useState<WSStatus>({ connected: false, attempts: 0 })
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    let ws: WebSocket | null = null
    let attempts = 0

    const connect = () => {
      ws = new WebSocket(wsUrl(path))

      ws.onopen = () => {
        attempts = 0
        setStatus({ connected: true, attempts: 0 })
      }
      ws.onmessage = (e) => {
        try {
          handlerRef.current(JSON.parse(e.data))
        } catch {
          /* ignore malformed */
        }
      }
      ws.onclose = () => {
        if (!alive) return
        setStatus({ connected: false, attempts })
        const delay = Math.min(30000, 1000 * Math.pow(2, attempts))
        attempts = Math.min(attempts + 1, 6)
        timer = setTimeout(connect, delay)
      }
      ws.onerror = () => {
        try { ws?.close() } catch { /* noop */ }
      }
    }

    connect()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
      try { ws?.close() } catch { /* noop */ }
    }
  }, [path])

  return status
}
