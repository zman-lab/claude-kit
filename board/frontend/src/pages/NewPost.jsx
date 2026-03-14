import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { createPost, getBoards, uploadAttachment } from '../utils/api.js'
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
  const [pendingFiles, setPendingFiles] = useState([])
  const textareaRef = useRef(null)

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
      // Upload pending files
      for (const file of pendingFiles) {
        try {
          await uploadAttachment(result.id, file, author || 'anonymous')
        } catch (err) {
          toast.error(`${file.name}: ${err.message}`)
        }
      }
      toast.success('게시글이 등록되었습니다')
      navigate(`/posts/${result.id}`)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handlePaste = (e) => {
    const items = [...(e.clipboardData?.items || [])]
    const imageItem = items.find(i => i.type.startsWith('image/'))
    if (imageItem) {
      e.preventDefault()
      const file = imageItem.getAsFile()
      const name = `clipboard-${Date.now()}.png`
      const namedFile = new File([file], name, { type: file.type })
      setPendingFiles(prev => [...prev, namedFile])
      // Insert {#filename} tag at cursor
      const textarea = textareaRef.current
      if (textarea) {
        const tag = `{#${name}}`
        const start = textarea.selectionStart
        const before = content.slice(0, start)
        const after = content.slice(start)
        setContent(before + tag + after)
      }
      toast.success('이미지 붙여넣기 완료')
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
            {board?.allowed_prefixes ? (
              <select
                value={prefix}
                onChange={e => setPrefix(e.target.value)}
                className="px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
              >
                <option value="">머릿말 없음</option>
                {board.allowed_prefixes.split(',').map(p => (
                  <option key={p.trim()} value={p.trim()}>{p.trim()}</option>
                ))}
              </select>
            ) : (
              <input
                value={prefix}
                onChange={e => setPrefix(e.target.value)}
                placeholder="e.g. [Guide]"
                className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
              />
            )}
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
              ref={textareaRef}
              value={content}
              onChange={e => setContent(e.target.value)}
              onPaste={handlePaste}
              placeholder="Write your post in Markdown... (이미지 붙여넣기 가능)"
              rows={12}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white font-mono resize-y"
            />
          )}
        </div>

        {/* File attachments */}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <label className="cursor-pointer text-sm text-blue-600 hover:text-blue-700 inline-flex items-center gap-1">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
              파일 첨부
              <input type="file" multiple onChange={e => setPendingFiles(prev => [...prev, ...Array.from(e.target.files)])} className="hidden" />
            </label>
            <span className="text-xs text-slate-400">이미지 붙여넣기도 가능</span>
          </div>
          {pendingFiles.length > 0 && (
            <div className="mt-2 space-y-1">
              {pendingFiles.map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                  <svg className="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                  <span>{f.name} ({(f.size / 1024).toFixed(1)}KB)</span>
                  <button type="button" onClick={() => setPendingFiles(prev => prev.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-600">&times;</button>
                </div>
              ))}
            </div>
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
