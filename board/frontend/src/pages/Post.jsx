import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getPost, toggleLike, createReply, updatePost, deletePost, updateReply, deleteReply, uploadAttachment, getAttachments } from '../utils/api.js'
import { timeAgo, formatDate } from '../utils/time.js'
import { renderMarkdown } from '../utils/markdown.js'
import { useToast } from '../contexts/ToastContext.jsx'
import Spinner from '../components/Spinner.jsx'
import TagBadge from '../components/TagBadge.jsx'

export default function PostPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const [post, setPost] = useState(null)
  const [loading, setLoading] = useState(true)
  const [replyContent, setReplyContent] = useState('')
  const [replyAuthor, setReplyAuthor] = useState(() => localStorage.getItem('cb-author') || '')
  const [submitting, setSubmitting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [editingReplyId, setEditingReplyId] = useState(null)
  const [editReplyContent, setEditReplyContent] = useState('')
  const [attachments, setAttachments] = useState([])
  const fileInputRef = useRef(null)

  const load = async () => {
    try {
      const data = await getPost(id)
      setPost(data)
      const atts = await getAttachments(id).catch(() => [])
      setAttachments(atts)
    } catch {
      toast.error('게시글을 불러올 수 없습니다')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [id])

  const handleLike = async () => {
    try {
      await toggleLike(post.id, replyAuthor || 'anonymous')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleReply = async (e) => {
    e.preventDefault()
    if (!replyContent.trim()) return
    setSubmitting(true)
    try {
      localStorage.setItem('cb-author', replyAuthor)
      await createReply(post.id, { content: replyContent, author: replyAuthor || 'anonymous' })
      setReplyContent('')
      toast.success('댓글이 등록되었습니다')
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleEdit = async () => {
    try {
      await updatePost(post.id, { title: editTitle, content: editContent })
      setEditing(false)
      toast.success('수정되었습니다')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleDelete = async () => {
    if (!confirm('정말 삭제하시겠습니까?')) return
    try {
      await deletePost(post.id)
      toast.success('삭제되었습니다')
      navigate(`/boards/${post.board_slug}`)
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleDeleteReply = async (replyId) => {
    if (!confirm('댓글을 삭제하시겠습니까?')) return
    try {
      await deleteReply(replyId)
      toast.success('댓글이 삭제되었습니다')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleEditReply = async (replyId) => {
    try {
      await updateReply(replyId, { content: editReplyContent })
      setEditingReplyId(null)
      toast.success('댓글이 수정되었습니다')
      await load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleFileUpload = async (files) => {
    for (const file of files) {
      try {
        await uploadAttachment(post.id, file, replyAuthor || 'anonymous')
        toast.success(`${file.name} 업로드 완료`)
      } catch (e) {
        toast.error(`${file.name}: ${e.message}`)
      }
    }
    const atts = await getAttachments(post.id).catch(() => [])
    setAttachments(atts)
  }

  const handlePaste = (e) => {
    const items = e.clipboardData?.items
    if (!items) return
    const files = []
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length > 0) {
      e.preventDefault()
      handleFileUpload(files)
    }
  }

  if (loading) return <Spinner />
  if (!post) return <div className="text-center py-16 text-slate-400">게시글을 찾을 수 없습니다</div>

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="text-sm text-slate-400 dark:text-slate-500">
        <Link to={`/boards/${post.board_slug}`} className="hover:text-blue-500">{post.board_name}</Link>
        <span className="mx-2">/</span>
        <span className="text-slate-600 dark:text-slate-300">#{post.id}</span>
      </div>

      {/* Post */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <div className="p-6">
          {editing ? (
            <div className="space-y-3">
              <input
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-lg font-semibold"
              />
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                rows={10}
                className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm font-mono"
              />
              <div className="flex gap-2">
                <button onClick={handleEdit} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg">Save</button>
                <button onClick={() => setEditing(false)} className="px-4 py-2 bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-200 text-sm rounded-lg">Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    {post.prefix && <span className="text-xs text-slate-500 bg-slate-100 dark:bg-slate-700 px-2 py-0.5 rounded">{post.prefix}</span>}
                    <TagBadge tag={post.tag} />
                  </div>
                  <h1 className="text-xl font-bold text-slate-900 dark:text-white">{post.title}</h1>
                  <div className="flex items-center gap-3 mt-2 text-xs text-slate-400 dark:text-slate-500">
                    <span className="font-medium text-slate-600 dark:text-slate-300">{post.author}</span>
                    <span>{formatDate(post.created_at)}</span>
                    {post.updated_at && post.updated_at !== post.created_at && (
                      <span>(edited {timeAgo(post.updated_at)})</span>
                    )}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    onClick={() => { setEditing(true); setEditTitle(post.title); setEditContent(post.content) }}
                    className="p-2 text-slate-400 hover:text-blue-500 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                    title="Edit"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                  </button>
                  <button
                    onClick={handleDelete}
                    className="p-2 text-slate-400 hover:text-red-500 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                    title="Delete"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                  </button>
                </div>
              </div>

              {/* Content */}
              <div
                className="mt-5 markdown-body text-sm text-slate-700 dark:text-slate-200 leading-relaxed"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(post.content) }}
              />

              {/* Attachments */}
              {attachments.length > 0 && (
                <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700">
                  <p className="text-xs font-semibold text-slate-500 mb-2">Attachments</p>
                  <div className="space-y-1">
                    {attachments.map(att => (
                      <a
                        key={att.id}
                        href={`/api/attachments/${att.id}/download`}
                        className="flex items-center gap-2 text-sm text-blue-500 hover:text-blue-600"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                        {att.filename} <span className="text-xs text-slate-400">({(att.file_size / 1024).toFixed(1)}KB)</span>
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Like + Upload */}
              <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700 flex items-center gap-3">
                <button
                  onClick={handleLike}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm border transition-colors
                    ${post.liked_by?.includes(replyAuthor || 'anonymous')
                      ? 'bg-red-50 dark:bg-red-900/30 border-red-300 dark:border-red-700 text-red-500'
                      : 'bg-white dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-500 hover:border-red-300'}`}
                >
                  ❤️ {post.like_count || 0}
                </button>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 border border-slate-300 dark:border-slate-600 rounded-full"
                >
                  + Attach
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={e => handleFileUpload(Array.from(e.target.files))}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Replies */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          Comments ({post.replies?.length || 0})
        </h3>
        {post.replies?.map(r => (
          <div key={r.id} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 shadow-sm">
            {editingReplyId === r.id ? (
              <div className="space-y-2">
                <textarea
                  value={editReplyContent}
                  onChange={e => setEditReplyContent(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
                <div className="flex gap-2">
                  <button onClick={() => handleEditReply(r.id)} className="px-3 py-1 bg-blue-600 text-white text-xs rounded-lg">Save</button>
                  <button onClick={() => setEditingReplyId(null)} className="px-3 py-1 bg-slate-200 dark:bg-slate-600 text-xs rounded-lg">Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-medium text-slate-600 dark:text-slate-300">{r.author}</span>
                    <span className="text-slate-400 dark:text-slate-500">{timeAgo(r.created_at)}</span>
                    {r.updated_at && r.updated_at !== r.created_at && <span className="text-slate-400">(edited)</span>}
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={() => { setEditingReplyId(r.id); setEditReplyContent(r.content) }}
                      className="p-1 text-slate-400 hover:text-blue-500 rounded"
                      title="Edit"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                    </button>
                    <button
                      onClick={() => handleDeleteReply(r.id)}
                      className="p-1 text-slate-400 hover:text-red-500 rounded"
                      title="Delete"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                  </div>
                </div>
                <div
                  className="markdown-body text-sm text-slate-700 dark:text-slate-200"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(r.content) }}
                />
              </>
            )}
          </div>
        ))}
      </div>

      {/* Reply form */}
      <form onSubmit={handleReply} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 shadow-sm space-y-3">
        <div className="flex gap-3">
          <input
            value={replyAuthor}
            onChange={e => setReplyAuthor(e.target.value)}
            placeholder="Author"
            className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
          />
        </div>
        <textarea
          value={replyContent}
          onChange={e => setReplyContent(e.target.value)}
          onPaste={handlePaste}
          placeholder="Write a comment... (Markdown supported, paste images)"
          rows={3}
          className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white resize-y"
        />
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={submitting || !replyContent.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {submitting ? 'Posting...' : 'Post Comment'}
          </button>
        </div>
      </form>
    </div>
  )
}
