export type Theme = 'light' | 'dark' | 'system'

const KEY = 'theme'
const systemDark = window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme | null) ?? 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme: Theme = getTheme()) {
  const dark = theme === 'dark' || (theme === 'system' && systemDark.matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // private mode: the choice just doesn't persist
  }
  applyTheme(theme)
}

systemDark.addEventListener('change', () => applyTheme())
