import { useState, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar.jsx'

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    fetch('/api/admin/teams')
      .then(r => r.json())
      .then(teams => {
        const isDark = document.documentElement.classList.contains('dark')
        teams.forEach(t => {
          const color = isDark && t.color_dark ? t.color_dark : t.color
          if (color) {
            document.documentElement.style.setProperty(`--team-${t.slug}`, color)
          }
        })
      })
      .catch(() => {}) // 실패해도 무시 (기본 색상 fallback)
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Mobile hamburger */}
      <button
        onClick={() => setSidebarOpen(true)}
        className="fixed top-3 left-3 z-30 lg:hidden w-10 h-10 flex items-center justify-center rounded-lg bg-white dark:bg-slate-800 shadow-md text-slate-600 dark:text-slate-300"
        aria-label="Menu"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* Main */}
      <main className="lg:ml-60 min-h-screen">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
