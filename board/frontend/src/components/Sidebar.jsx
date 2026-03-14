import { useState, useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useTheme } from '../contexts/ThemeContext.jsx'
import { getBoards } from '../utils/api.js'
import TeamDot from './TeamDot.jsx'

export default function Sidebar({ open, onClose }) {
  const location = useLocation()
  const { dark, toggle } = useTheme()
  const [boards, setBoards] = useState([])
  const [quickLinksOpen, setQuickLinksOpen] = useState(false)

  useEffect(() => {
    getBoards().then(setBoards).catch(() => {})
  }, [])

  const teamBoards = boards.filter(b => b.category === 'team')
  const globalBoards = boards.filter(b => b.category === 'global' && b.slug !== 'knowhow')

  const isActive = (path) => location.pathname === path

  const navLink = (to, label, extra = null) => (
    <Link
      to={to}
      onClick={onClose}
      className={`flex items-center gap-2.5 px-4 py-2 text-sm rounded-lg transition-colors
        ${isActive(to)
          ? 'bg-slate-700/50 text-white'
          : 'text-slate-400 hover:bg-slate-700/30 hover:text-slate-200'}`}
    >
      {extra}
      {label}
    </Link>
  )

  return (
    <>
      {/* Overlay */}
      {open && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-0 bottom-0 w-60 bg-slate-900 border-r border-slate-700/50 z-50
          flex flex-col overflow-y-auto transition-transform duration-200
          lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* Header */}
        <div className="px-4 pt-5 pb-4 flex items-center gap-2.5 shrink-0">
          <Link to="/" onClick={onClose} className="w-7 h-7 bg-blue-600 rounded-md flex items-center justify-center text-white text-xs font-bold">
            CB
          </Link>
          <span className="text-white text-sm font-semibold tracking-tight">Claude Board</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 space-y-1">
          {navLink('/', 'Dashboard', <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />)}

          {/* Teams */}
          <div className="pt-4 pb-1">
            <span className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Teams</span>
          </div>
          {teamBoards.map(b => (
            <span key={b.slug}>
              {navLink(`/boards/${b.slug}`, b.team || b.slug, <TeamDot team={b.team} />)}
            </span>
          ))}

          {/* General */}
          <div className="pt-4 pb-1">
            <span className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">General</span>
          </div>
          {globalBoards.map(b => (
            <span key={b.slug}>
              {navLink(`/boards/${b.slug}`, b.name)}
            </span>
          ))}

          {/* Links */}
          <div className="pt-4 pb-1">
            <span className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">Links</span>
          </div>
          {navLink('/recent', 'Recent Posts')}
          {navLink('/boards', 'All Boards')}
        </nav>

        {/* Footer */}
        <div className="px-2 pb-4 space-y-1 shrink-0 border-t border-slate-700/50 pt-2">
          <div className="pt-1 pb-1">
            <span className="px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">System</span>
          </div>
          {navLink('/admin', 'Admin')}

          {/* Quick Links */}
          <button
            onClick={() => setQuickLinksOpen(!quickLinksOpen)}
            className="flex items-center justify-between w-full px-4 py-2 text-sm text-slate-400 hover:bg-slate-700/30 hover:text-slate-200 rounded-lg transition-colors"
          >
            Quick Links
            <span className={`transition-transform ${quickLinksOpen ? 'rotate-90' : ''}`}>&#x203A;</span>
          </button>
          {quickLinksOpen && (
            <div className="pl-6 space-y-0.5">
              {[
                { href: 'http://10.78.9.68:8079/', label: 'airlock' },
                { href: 'http://localhost:7778/law/', label: 'law local' },
                { href: 'http://localhost:17778/', label: 'elkhound local' },
                { href: 'http://elkhound.hangame.com:7777/', label: 'elkhound alpha' },
              ].map(l => (
                <a key={l.label} href={l.href} target="_blank" rel="noreferrer"
                  className="block px-4 py-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors">
                  {l.label}
                </a>
              ))}
            </div>
          )}

          {/* Theme */}
          <button
            onClick={toggle}
            className="flex items-center gap-2 w-full px-4 py-2 text-sm text-slate-400 hover:bg-slate-700/30 hover:text-slate-200 rounded-lg transition-colors"
          >
            {dark ? '☀️ Light' : '🌙 Dark'}
          </button>
        </div>
      </aside>
    </>
  )
}
