/**
 * hex -> HSL 변환
 */
export function hexToHsl(hex) {
  let r = parseInt(hex.slice(1, 3), 16) / 255
  let g = parseInt(hex.slice(3, 5), 16) / 255
  let b = parseInt(hex.slice(5, 7), 16) / 255

  const max = Math.max(r, g, b), min = Math.min(r, g, b)
  let h, s, l = (max + min) / 2

  if (max === min) {
    h = s = 0
  } else {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break
      case g: h = ((b - r) / d + 2) / 6; break
      case b: h = ((r - g) / d + 4) / 6; break
    }
  }
  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) }
}

export function hslToHex(h, s, l) {
  s /= 100; l /= 100
  const a = s * Math.min(l, 1 - l)
  const f = n => {
    const k = (n + h / 30) % 12
    return l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1)
  }
  return '#' + [f(0), f(8), f(4)].map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('')
}

/**
 * 메인 색상 1개에서 전체 팔레트 생성
 */
export function generatePalette(primaryHex, bgHex = null, chartHex = null) {
  const { h, s } = hexToHsl(primaryHex)

  return {
    // 메인
    primary: primaryHex,
    primaryHover: hslToHex(h, s, 35),
    primarySoft: hslToHex(h, Math.min(s, 40), 85),

    // 배경
    bg: bgHex || hslToHex(h, Math.min(s, 15), 98),
    bg2: bgHex ? bgHex : hslToHex(h, Math.min(s, 20), 96),
    card: '#ffffff',
    cardHover: hslToHex(h, Math.min(s, 10), 99),

    // 사이드바 (진한 버전)
    sidebar: hslToHex(h, Math.min(s + 10, 80), 28),
    sidebarHover: hslToHex(h, Math.min(s, 60), 35),
    sidebarText: hslToHex(h, Math.min(s, 30), 82),
    sidebarTextDim: hslToHex(h, Math.min(s, 25), 70),

    // 텍스트
    text: hslToHex(h, Math.min(s, 30), 18),
    textSecondary: hslToHex(h, Math.min(s, 20), 40),
    textDim: hslToHex(h, Math.min(s, 15), 55),

    // 보더
    border: hslToHex(h, Math.min(s, 25), 85),
    borderLight: hslToHex(h, Math.min(s, 15), 92),

    // 차트
    chart: chartHex || primaryHex,

    // 스크롤바
    scrollbar: hslToHex(h, Math.min(s, 25), 72),
  }
}

/**
 * 팔레트를 CSS 변수로 document에 적용
 */
export function applyCustomTheme(palette) {
  const root = document.documentElement

  root.style.setProperty('--custom-primary', palette.primary)
  root.style.setProperty('--custom-primary-hover', palette.primaryHover)
  root.style.setProperty('--custom-primary-soft', palette.primarySoft)
  root.style.setProperty('--custom-bg', palette.bg)
  root.style.setProperty('--custom-bg2', palette.bg2)
  root.style.setProperty('--custom-card', palette.card)
  root.style.setProperty('--custom-sidebar', palette.sidebar)
  root.style.setProperty('--custom-sidebar-hover', palette.sidebarHover)
  root.style.setProperty('--custom-sidebar-text', palette.sidebarText)
  root.style.setProperty('--custom-sidebar-text-dim', palette.sidebarTextDim)
  root.style.setProperty('--custom-text', palette.text)
  root.style.setProperty('--custom-text-sec', palette.textSecondary)
  root.style.setProperty('--custom-text-dim', palette.textDim)
  root.style.setProperty('--custom-border', palette.border)
  root.style.setProperty('--custom-border-light', palette.borderLight)
  root.style.setProperty('--custom-scrollbar', palette.scrollbar)
}

export function clearCustomTheme() {
  const root = document.documentElement
  const vars = ['primary', 'primary-hover', 'primary-soft', 'bg', 'bg2', 'card',
    'sidebar', 'sidebar-hover', 'sidebar-text', 'sidebar-text-dim',
    'text', 'text-sec', 'text-dim', 'border', 'border-light', 'scrollbar']
  vars.forEach(v => root.style.removeProperty(`--custom-${v}`))
}
