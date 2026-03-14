import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { createPost, getBoards } from '../utils/api.js'
import { renderMarkdown } from '../utils/markdown.js'
import { useToast } from '../contexts/ToastContext.jsx'

const TAGS = ['work', 'todo', 'issue', 'done', 'knowhow']

export default function NewPost() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const [board, setBoard] = useState(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [author, setAuthor] = useState(() => localStorage.getItem('cb-author') || '')
  const [tag, setTag] = useState('')
  const [prefix, setPrefix] = useState('')
  const [preview, setPreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    getBoards().then(boards => {
      const b = boards.find(b => b.slug === slug)
      setBoard(b)
    }).catch(() => {})
  }, [slug])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim() || !content.trim()) {
      toast.warning('제목과 내용을 입력해주세요')
      return
    }
    setSubmitting(true)
    try {
      localStorage.setItem('cb-author', author)
      const result = await createPost({
        board_slug: slug,
        title,
        content,
        author: author || 'anonymous',
        tag: tag || undefined,
        prefix: prefix || undefined,
      })
      toast.success('게시글이 등록되었습니다')
      navigate(`/posts/${result.id}`)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
        New Post — {board?.icon} {board?.name || slug}
      </h1>

      <form onSubmit={handleSubmit} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-6 space-y-4">
        {/* Author */}
        <div>
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Author</label>
          <input
            value={author}
            onChange={e => setAuthor(e.target.value)}
            placeholder="Author name"
            className="w-48 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
          />
        </div>

        {/* Title */}
        <div>
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Title</label>
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="Post title"
            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
            autoFocus
          />
        </div>

        {/* Tag & Prefix */}
        <div className="flex gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Tag</label>
            <select
              value={tag}
              onChange={e => setTag(e.target.value)}
              className="px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
            >
              <option value="">None</option>
              {TAGS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Prefix</label>
            <input
              value={prefix}
              onChange={e => setPrefix(e.target.value)}
              placeholder="e.g. [Guide]"
              className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
            />
          </div>
        </div>

        {/* Content */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium text-slate-500 dark:text-slate-400">Content</label>
            <button
              type="button"
              onClick={() => setPreview(!preview)}
              className="text-xs text-blue-500 hover:text-blue-600"
            >
              {preview ? 'Edit' : 'Preview'}
            </button>
          </div>
          {preview ? (
            <div
              className="min-h-[200px] px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-900 markdown-body text-sm text-slate-700 dark:text-slate-200"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
            />
          ) : (
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              placeholder="Write your post in Markdown..."
              rows={12}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white font-mono resize-y"
            />
          )}
        </div>

        {/* Submit */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:text-slate-900"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {submitting ? 'Posting...' : 'Post'}
          </button>
        </div>
      </form>
    </div>
  )
}
