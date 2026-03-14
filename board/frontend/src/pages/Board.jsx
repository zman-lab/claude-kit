import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getPosts, getBoards } from '../utils/api.js'
import { timeAgo } from '../utils/time.js'
import Spinner from '../components/Spinner.jsx'
import Empty from '../components/Empty.jsx'
import TagBadge from '../components/TagBadge.jsx'

const TAGS = ['', 'work', 'todo', 'issue', 'done', 'knowhow']
const PAGE_SIZE = 20

export default function Board() {
  const { slug } = useParams()
  const [board, setBoard] = useState(null)
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [tag, setTag] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    setLoading(true)
    setPage(1)
    Promise.all([
      getBoards().then(boards => setBoard(boards.find(b => b.slug === slug))),
      getPosts({ board_slug: slug, tag: tag || undefined, limit: PAGE_SIZE, offset: 0 }).then(setPosts),
    ]).catch(() => {}).finally(() => setLoading(false))
  }, [slug, tag])

  const loadMore = async () => {
    const offset = page * PAGE_SIZE
    const more = await getPosts({ board_slug: slug, tag: tag || undefined, limit: PAGE_SIZE, offset })
    setPosts(prev => [...prev, ...more])
    setPage(p => p + 1)
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {board?.icon} {board?.name || slug}
          </h1>
          {board?.description && (
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{board.description}</p>
          )}
        </div>
        <Link
          to={`/boards/${slug}/new`}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          + New Post
        </Link>
      </div>

      {/* Tag filter */}
      <div className="flex gap-2 flex-wrap">
        {TAGS.map(t => (
          <button
            key={t}
            onClick={() => setTag(t)}
            className={`px-3 py-1 text-xs rounded-full border transition-colors
              ${tag === t
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-600 hover:border-blue-400'}`}
          >
            {t || 'All'}
          </button>
        ))}
      </div>

      {/* Posts */}
      {posts.length === 0 ? (
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
                  {p.prefix && <span className="text-xs text-slate-500 dark:text-slate-400">{p.prefix}</span>}
                  <TagBadge tag={p.tag} />
                  <span className="text-sm font-medium text-slate-900 dark:text-white truncate">{p.title}</span>
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

      {/* Load more */}
      {posts.length >= page * PAGE_SIZE && (
        <div className="text-center pt-2">
          <button
            onClick={loadMore}
            className="px-4 py-2 text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 font-medium"
          >
            Load more...
          </button>
        </div>
      )}
    </div>
  )
}
