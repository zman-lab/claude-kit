import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getRecentAll, getBoards } from '../utils/api.js'
import { timeAgo } from '../utils/time.js'
import Spinner from '../components/Spinner.jsx'
import Empty from '../components/Empty.jsx'
import TagBadge from '../components/TagBadge.jsx'

const SCOPES = [
  { value: 'all', label: 'All' },
  { value: 'team', label: 'Team' },
  { value: 'global', label: 'Global' },
]
const TAGS = ['', 'work', 'todo', 'issue', 'done', 'knowhow']

export default function RecentAll() {
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [scope, setScope] = useState('all')
  const [tag, setTag] = useState('')
  const [team, setTeam] = useState('')
  const [teams, setTeams] = useState([])

  useEffect(() => {
    getBoards().then(boards => {
      const t = [...new Set(boards.filter(b => b.team).map(b => b.team))]
      setTeams(t)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    getRecentAll({ scope, tag: tag || undefined, team: team || undefined, limit: 50 })
      .then(setPosts)
      .catch(() => setPosts([]))
      .finally(() => setLoading(false))
  }, [scope, tag, team])

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Recent Posts</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        {/* Scope */}
        <div className="flex gap-1">
          {SCOPES.map(s => (
            <button
              key={s.value}
              onClick={() => setScope(s.value)}
              className={`px-3 py-1 text-xs rounded-full border transition-colors
                ${scope === s.value
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-600 hover:border-blue-400'}`}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* Team filter */}
        <select
          value={team}
          onChange={e => setTeam(e.target.value)}
          className="px-3 py-1 text-xs border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-200"
        >
          <option value="">All teams</option>
          {teams.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        {/* Tag filter */}
        <div className="flex gap-1">
          {TAGS.map(t => (
            <button
              key={t}
              onClick={() => setTag(t)}
              className={`px-2 py-0.5 text-xs rounded-full border transition-colors
                ${tag === t
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-600'}`}
            >
              {t || 'All'}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      {loading ? <Spinner /> : posts.length === 0 ? (
        <Empty message="게시글이 없습니다" />
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm divide-y divide-slate-100 dark:divide-slate-700">
          {posts.map(p => (
            <Link
              key={p.id}
              to={`/posts/${p.id}`}
              className="flex items-center gap-3 px-5 py-3.5 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
            >
              {p.is_pinned && <span className="text-xs">📌</span>}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">[{p.board_slug}]</span>
                  <span className="text-sm font-medium text-slate-900 dark:text-white truncate">{p.title}</span>
                  <TagBadge tag={p.tag} />
                </div>
                <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                  <span>{p.author}</span>
                  <span>{timeAgo(p.created_at)}</span>
                </div>
              </div>
              <div className="flex items-center gap-3 shrink-0 text-xs text-slate-400 dark:text-slate-500">
                {p.reply_count > 0 && <span>💬 {p.reply_count}</span>}
                {p.like_count > 0 && <span>❤️ {p.like_count}</span>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
