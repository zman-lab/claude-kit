import { Link } from 'react-router-dom'
import { getBoards } from '../utils/api.js'
import { useApi } from '../hooks/useApi.js'
import Spinner from '../components/Spinner.jsx'
import TeamDot from '../components/TeamDot.jsx'

export default function BoardList() {
  const { data: boards, loading } = useApi(() => getBoards())

  if (loading) return <Spinner />

  const teamBoards = (boards || []).filter(b => b.category === 'team')
  const globalBoards = (boards || []).filter(b => b.category === 'global')

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Boards</h1>

      {/* Team boards */}
      {teamBoards.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Team Boards</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {teamBoards.map(b => (
              <Link
                key={b.slug}
                to={`/boards/${b.slug}`}
                className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm hover:shadow-md transition-shadow group"
                style={{ borderLeftColor: `var(--team-${b.team}, #94a3b8)`, borderLeftWidth: 3 }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <TeamDot team={b.team} size={10} />
                  <span className="font-semibold text-slate-900 dark:text-white group-hover:text-blue-500 transition-colors">
                    {b.icon} {b.name}
                  </span>
                </div>
                {b.description && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 line-clamp-2">{b.description}</p>
                )}
                <div className="text-xs text-slate-400 dark:text-slate-500">
                  {b.post_count} posts
                </div>
              </Link>
            ))}
          </div>
        </>
      )}

      {/* Global boards */}
      {globalBoards.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mt-8">Global Boards</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {globalBoards.map(b => (
              <Link
                key={b.slug}
                to={`/boards/${b.slug}`}
                className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm hover:shadow-md transition-shadow group"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-semibold text-slate-900 dark:text-white group-hover:text-blue-500 transition-colors">
                    {b.icon} {b.name}
                  </span>
                </div>
                {b.description && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 line-clamp-2">{b.description}</p>
                )}
                <div className="text-xs text-slate-400 dark:text-slate-500">
                  {b.post_count} posts
                </div>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
