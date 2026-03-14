import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { getPost, toggleLike, createReply, updatePost, deletePost, updateReply, deleteReply, uploadAttachment, getAttachments } from '../utils/api.js'
import { timeAgo, formatDate } from '../utils/time.js'
import { renderMarkdown, replaceFileTags } from '../utils/markdown.js'
import { useFileAutocomplete } from '../hooks/useFileAutocomplete.js'
import { printContent } from '../utils/print.js'
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
  const [showPrint, setShowPrint] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [replyPendingFiles, setReplyPendingFiles] = useState([])
  const fileInputRef = useRef(null)
  const replyFileInputRef = useRef(null)
  const replyTextareaRef = useRef(null)

  const autocomplete = useFileAutocomplete(
    replyTextareaRef, replyContent, setReplyContent,
    attachments
  )

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

  // Code block copy buttons
  useEffect(() => {
    if (!post) return
    document.querySelectorAll('.markdown-body pre').forEach(pre => {
      if (pre.querySelector('.code-copy-btn')) return
      const btn = document.createElement('button')
      btn.className = 'code-copy-btn'
      btn.textContent = '복사'
      btn.style.cssText = 'position:absolute;top:4px;right:4px;padding:2px 8px;font-size:11px;background:#374151;color:#e5e7eb;border:1px solid #4b5563;border-radius:4px;cursor:pointer;opacity:0.7;z-index:1'
      btn.onclick = () => {
        const code = pre.querySelector('code')?.textContent || pre.textContent
        navigator.clipboard.writeText(code).then(() => { btn.textContent = '\u2713'; setTimeout(() => btn.textContent = '복사', 1500) })
      }
      pre.style.position = 'relative'
      pre.appendChild(btn)
    })
  }, [post])

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

  const handleDrop = async (e) => {
    e.preventDefault()
    setDragging(false)
    const files = [...e.dataTransfer.files]
    if (files.length === 0) return
    for (const file of files) {
      try {
        await uploadAttachment(post.id, file, replyAuthor || 'anonymous')
        toast.success(`${file.name} 업로드 완료`)
      } catch (err) {
        toast.error(`${file.name}: ${err.message}`)
      }
    }
    const atts = await getAttachments(post.id).catch(() => [])
    setAttachments(atts)
  }

  const handleReplyWithFiles = async (e) => {
    e.preventDefault()
    if (!replyContent.trim()) return
    setSubmitting(true)
    try {
      localStorage.setItem('cb-author', replyAuthor)
      const reply = await createReply(post.id, { content: replyContent, author: replyAuthor || 'anonymous' })
      for (const file of replyPendingFiles) {
        await uploadAttachment(reply.id, file, replyAuthor || 'anonymous')
      }
      setReplyPendingFiles([])
      setReplyContent('')
      toast.success('댓글이 등록되었습니다')
      await load()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const buildRepliesHtml = () => {
    if (!post?.replies?.length) return ''
    return post.replies.map(r => `
      <div class="reply">
        <div class="reply-author">${r.author} &mdash; ${new Date(r.created_at).toLocaleString()}</div>
        <div>${renderMarkdown(r.content)}</div>
      </div>
    `).join('')
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
      <div
        className={`bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm ${dragging ? 'ring-2 ring-blue-400 ring-dashed' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
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
                  <div className="relative">
                    <button
                      onClick={() => setShowPrint(!showPrint)}
                      className="p-2 text-slate-400 hover:text-blue-500 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                      title="Print"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
                    </button>
                    {showPrint && (
                      <div className="absolute right-0 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg p-1 z-50 min-w-[120px]">
                        <button
                          onClick={() => { printContent(post.title, `<h1>${post.title}</h1>` + renderMarkdown(replaceFileTags(post.content, attachments))); setShowPrint(false) }}
                          className="block text-xs py-1.5 px-3 hover:bg-slate-100 dark:hover:bg-slate-700 w-full text-left rounded text-slate-700 dark:text-slate-200"
                        >
                          본문만
                        </button>
                        <button
                          onClick={() => { printContent(post.title, `<h1>${post.title}</h1>` + renderMarkdown(replaceFileTags(post.content, attachments)) + buildRepliesHtml()); setShowPrint(false) }}
                          className="block text-xs py-1.5 px-3 hover:bg-slate-100 dark:hover:bg-slate-700 w-full text-left rounded text-slate-700 dark:text-slate-200"
                        >
                          댓글 포함
                        </button>
                      </div>
                    )}
                  </div>
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
                dangerouslySetInnerHTML={{ __html: renderMarkdown(replaceFileTags(post.content, attachments)) }}
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

              {/* Like + Copy + Upload */}
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
                  onClick={() => {
                    navigator.clipboard.writeText(post.content)
                    toast.success('본문 복사됨')
                  }}
                  className="px-3 py-1.5 text-sm text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 border border-slate-300 dark:border-slate-600 rounded-full"
                >
                  📋 복사
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
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(replaceFileTags(r.content, r.attachments || [])) }}
                />
                {/* Reply attachments */}
                {r.attachments?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {r.attachments.map(att => (
                      <a
                        key={att.id}
                        href={`/api/attachments/${att.id}/download`}
                        className="inline-flex items-center gap-1 text-xs text-blue-500 hover:text-blue-600 hover:underline"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                        {att.filename}
                      </a>
                    ))}
                  </div>
                )}
                <div className="mt-2 flex items-center gap-2">
                  <button
                    onClick={async () => {
                      await toggleLike(r.id, replyAuthor || 'anonymous')
                      await load()
                    }}
                    className="text-xs text-slate-400 hover:text-red-500"
                  >
                    ❤️ {r.like_count || 0}
                  </button>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(r.content)
                      toast.success('댓글 복사됨')
                    }}
                    className="px-1.5 py-0.5 text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded"
                  >
                    복사
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Reply form */}
      <form onSubmit={handleReplyWithFiles} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 shadow-sm space-y-3">
        <div className="flex gap-3">
          <input
            value={replyAuthor}
            onChange={e => setReplyAuthor(e.target.value)}
            placeholder="Author"
            className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
          />
        </div>
        <div className="relative">
          <textarea
            ref={replyTextareaRef}
            value={replyContent}
            onChange={e => setReplyContent(e.target.value)}
            onKeyDown={autocomplete.handleKeyDown}
            onPaste={handlePaste}
            placeholder="Write a comment... (Markdown supported, paste images, {# for file tags)"
            rows={3}
            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white resize-y"
          />
          {autocomplete.show && autocomplete.filtered.length > 0 && (
            <div className="absolute z-50 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg max-h-40 overflow-y-auto"
              style={{ top: autocomplete.position.top, left: autocomplete.position.left, minWidth: '200px' }}>
              {autocomplete.filtered.map((file, i) => (
                <button key={file.filename}
                  onClick={() => autocomplete.select(file)}
                  className={`block w-full text-left px-3 py-1.5 text-sm ${
                    i === autocomplete.selectedIdx ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'
                  }`}>
                  {/\.(jpg|jpeg|png|gif|webp|svg)$/i.test(file.filename) ? '🖼️' : '📎'} {file.filename}
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Reply pending files */}
        <div className="flex items-center gap-2 flex-wrap">
          <label className="cursor-pointer text-xs text-blue-600 hover:text-blue-700">
            <span className="inline-flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
              첨부
            </span>
            <input
              ref={replyFileInputRef}
              type="file"
              multiple
              onChange={e => setReplyPendingFiles(prev => [...prev, ...Array.from(e.target.files)])}
              className="hidden"
            />
          </label>
          {replyPendingFiles.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 text-xs text-slate-500 bg-slate-100 dark:bg-slate-700 px-2 py-0.5 rounded">
              {f.name} ({(f.size / 1024).toFixed(1)}KB)
              <button type="button" onClick={() => setReplyPendingFiles(prev => prev.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-600 ml-0.5">&times;</button>
            </span>
          ))}
        </div>
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
