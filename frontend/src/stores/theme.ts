import { create } from 'zustand'

type ThemeMode = 'dark' | 'light'

interface ThemeState {
  theme: ThemeMode
  apply: (t: ThemeMode) => void
}

const STORAGE_KEY = 'reenc.theme'

function applyToDOM(t: ThemeMode) {
  const root = document.documentElement
  if (t === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
}

export const useTheme = create<ThemeState>((set) => ({
  theme: 'dark',
  apply: (t) => {
    applyToDOM(t)
    try { localStorage.setItem(STORAGE_KEY, t) } catch { /* noop */ }
    set({ theme: t })
  },
}))

export function loadStoredTheme(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch { /* noop */ }
  return 'dark'
}
