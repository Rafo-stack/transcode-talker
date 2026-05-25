import axios from 'axios'

const baseURL = (import.meta.env.VITE_API_BASE_URL as string) || ''

export const api = axios.create({ baseURL, timeout: 30000 })

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response) {
      const data = err.response.data
      const msg =
        (data && typeof data === 'object' && (data.error || data.detail || data.message)) ||
        `HTTP ${err.response.status}`
      err.message = String(msg)
    } else if (err.request) {
      err.message = 'Network error: API unreachable'
    }
    throw err
  },
)

export const wsUrl = (path: string) => {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}${path}`
}
