import { createContext, useContext, useState, useEffect } from 'react'
import { generatePalette, applyCustomTheme, clearCustomTheme } from '../utils/theme.js'

const ThemeContext = createContext()

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    const saved = localStorage.getItem('cb-theme')
    if (saved === 'dark' || saved === 'light' || saved === 'custom') return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  const [customColors, setCustomColorsState] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('cb-custom-colors') || '{}')
    } catch {
      return {}
    }
  })

  const setTheme = (t) => {
    setThemeState(t)
  }

  const setCustomColors = (colors) => {
    setCustomColorsState(colors)
    localStorage.setItem('cb-custom-colors', JSON.stringify(colors))
    if (theme === 'custom') {
      const palette = generatePalette(colors.primary || '#6366f1', colors.bg, colors.chart)
      applyCustomTheme(palette)
    }
  }

  useEffect(() => {
    const root = document.documentElement
    // 모든 테마 클래스 + CSS 변수 완전 초기화
    root.classList.remove('dark', 'custom')
    clearCustomTheme()
    // inline style 잔여물 제거
    root.removeAttribute('style')

    if (theme === 'dark') {
      root.classList.add('dark')
    } else if (theme === 'custom') {
      root.classList.add('custom')
      const palette = generatePalette(
        customColors.primary || '#6366f1',
        customColors.bg,
        customColors.chart
      )
      applyCustomTheme(palette)
    }
    // light: 아무 클래스도 추가하지 않음 → Tailwind 기본 스타일
    localStorage.setItem('cb-theme', theme)
  }, [theme, customColors])

  const dark = theme === 'dark'
  const toggle = () => setThemeState(t => t === 'dark' ? 'light' : 'dark')

  return (
    <ThemeContext.Provider value={{ theme, dark, toggle, setTheme, customColors, setCustomColors }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeContext)
