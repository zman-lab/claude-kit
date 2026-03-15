import { useState, useEffect, useRef, useCallback } from 'react'
import { timeAgo } from '../utils/time.js'

// --- 세션 사이드바 ---
function SessionList({ sessions, activeId, onSelect, onNew, onDelete, onRename }) {
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')

  const startRename = (s) => {
    setEditingId(s.id)
    setEditTitle(s.title || '')
  }
  const submitRename = (id) => {
    onRename(id, editTitle)
    setEditingId(null)
  }

  return (
    <div className="flex flex-col h-full">
      <button
        onClick={onNew}
        className="m-3 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700
                   transition-colors text-sm font-medium"
      >
        + 새 채팅
      </button>
      <div className="flex-1 overflow-y-auto px-2">
        {sessions.length === 0 && (
          <p className="px-3 py-4 text-xs text-slate-500 text-center">채팅 세션이 없습니다</p>
        )}
        {sessions.map(s => (
          <div
            key={s.id}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
                       text-sm mb-1 transition-colors
                       ${s.id === activeId
                         ? 'bg-blue-600/20 text-blue-300'
                         : 'hover:bg-slate-700/30 text-slate-300 hover:text-slate-100'}`}
            onClick={() => onSelect(s)}
          >
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${s.is_active ? 'bg-green-400' : 'bg-slate-500'}`} />
            <div className="flex-1 min-w-0">
              {editingId === s.id ? (
                <input
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  onBlur={() => submitRename(s.id)}
                  onKeyDown={e => e.key === 'Enter' && submitRename(s.id)}
                  className="w-full px-1 py-0.5 text-sm border rounded bg-slate-700 border-slate-600 text-slate-100"
                  autoFocus
                  onClick={e => e.stopPropagation()}
                />
              ) : (
                <span className="truncate block">{s.title || '새 채팅'}</span>
              )}
              <span className="text-xs text-slate-500">{timeAgo(s.updated_at || s.created_at)}</span>
            </div>
            <div className="hidden group-hover:flex gap-1 flex-shrink-0">
              <button
                onClick={e => { e.stopPropagation(); startRename(s) }}
                className="text-slate-400 hover:text-slate-200 text-xs px-1"
                title="이름 변경"
              >
                ✏️
              </button>
              <button
                onClick={e => { e.stopPropagation(); onDelete(s.id) }}
                className="text-slate-400 hover:text-red-400 text-xs px-1"
                title="삭제"
              >
                🗑️
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- 메시지 버블 ---
function MessageBubble({ message, isStreaming }) {
  return (
    <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap
                     ${message.role === 'user'
                       ? 'bg-blue-600 text-white rounded-br-sm'
                       : 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 rounded-bl-sm'}`}
      >
        {isStreaming ? (
          <>
            {message.content}
            <span className="inline-block w-2 h-4 bg-current opacity-50 animate-pulse ml-1 align-middle" />
          </>
        ) : (
          message.content
        )}
      </div>
    </div>
  )
}

// --- 메인 Chat 페이지 ---
export default function Chat() {
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // 세션 목록 로드
  const loadSessions = useCallback(async () => {
    try {
      const res = await fetch('/api/chat/sessions')
      if (!res.ok) throw new Error('세션 로드 실패')
      const data = await res.json()
      setSessions(data)
    } catch (e) {
      console.error('세션 로드 실패:', e)
    }
  }, [])

  // 메시지 로드
  const loadMessages = useCallback(async (sessionId) => {
    try {
      const res = await fetch(`/api/chat/sessions/${sessionId}/messages`)
      if (!res.ok) throw new Error('메시지 로드 실패')
      const data = await res.json()
      setMessages(data)
    } catch (e) {
      console.error('메시지 로드 실패:', e)
    }
  }, [])

  useEffect(() => { loadSessions() }, [loadSessions])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  // 세션 선택
  const selectSession = async (session) => {
    setActiveSession(session)
    setMessages([])
    setStreamingText('')
    await loadMessages(session.id)
  }

  // 새 채팅
  const createSession = async () => {
    try {
      const res = await fetch('/api/chat/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error('세션 생성 실패')
      const session = await res.json()
      setSessions(prev => [session, ...prev])
      setActiveSession(session)
      setMessages([])
      setStreamingText('')
      inputRef.current?.focus()
    } catch (e) {
      console.error('세션 생성 실패:', e)
    }
  }

  // 세션 삭제
  const deleteSession = async (id) => {
    if (!confirm('이 채팅을 삭제하시겠습니까?')) return
    try {
      const res = await fetch(`/api/chat/sessions/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('삭제 실패')
      setSessions(prev => prev.filter(s => s.id !== id))
      if (activeSession?.id === id) {
        setActiveSession(null)
        setMessages([])
      }
    } catch (e) {
      console.error('삭제 실패:', e)
    }
  }

  // 세션 이름 변경
  const renameSession = async (id, title) => {
    try {
      const res = await fetch(`/api/chat/sessions/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      if (!res.ok) throw new Error('이름 변경 실패')
      const updated = await res.json()
      setSessions(prev => prev.map(s => s.id === id ? { ...s, title: updated.title } : s))
      if (activeSession?.id === id) {
        setActiveSession(prev => ({ ...prev, title: updated.title }))
      }
    } catch (e) {
      console.error('이름 변경 실패:', e)
    }
  }

  // 메시지 전송 (SSE)
  const sendMessage = async () => {
    if (!input.trim() || !activeSession || isStreaming) return
    if (!activeSession.is_active) return

    const content = input.trim()
    const userMsg = { role: 'user', content, id: `tmp-${Date.now()}`, is_complete: true, created_at: new Date().toISOString() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setIsStreaming(true)
    setStreamingText('')

    try {
      const response = await fetch(`/api/chat/sessions/${activeSession.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })

      if (!response.ok) {
        throw new Error(`서버 오류: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let fullText = ''
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // 마지막 불완전한 라인은 버퍼에 유지

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'text') {
              fullText += event.content
              setStreamingText(fullText)
            } else if (event.type === 'done') {
              setMessages(prev => [...prev, {
                role: 'assistant',
                content: fullText,
                id: `tmp-${Date.now()}`,
                is_complete: true,
                created_at: new Date().toISOString(),
              }])
              setStreamingText('')
            } else if (event.type === 'error') {
              setMessages(prev => [...prev, {
                role: 'assistant',
                content: `오류: ${event.message}`,
                id: `tmp-${Date.now()}`,
                is_complete: true,
                created_at: new Date().toISOString(),
              }])
              setStreamingText('')
            }
          } catch {
            // JSON 파싱 실패 무시
          }
        }
      }
    } catch (e) {
      console.error('메시지 전송 실패:', e)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '메시지 전송에 실패했습니다.',
        id: `tmp-${Date.now()}`,
        is_complete: true,
        created_at: new Date().toISOString(),
      }])
    } finally {
      setIsStreaming(false)
      setStreamingText('')
      loadSessions() // 세션 목록 갱신 (updated_at 반영)
    }
  }

  // Compact
  const handleCompact = async () => {
    if (!activeSession) return
    try {
      await fetch(`/api/chat/sessions/${activeSession.id}/compact`, { method: 'POST' })
    } catch (e) {
      console.error('compact 실패:', e)
    }
  }

  // Clear
  const handleClear = async () => {
    if (!activeSession) return
    if (!confirm('대화 내용을 모두 삭제하시겠습니까?')) return
    try {
      const res = await fetch(`/api/chat/sessions/${activeSession.id}/clear`, { method: 'POST' })
      if (!res.ok) throw new Error('초기화 실패')
      setMessages([])
    } catch (e) {
      console.error('clear 실패:', e)
    }
  }

  // beforeunload — 페이지 이탈 시 세션 archive
  useEffect(() => {
    const handler = () => {
      if (activeSession?.is_active && messages.length > 0) {
        navigator.sendBeacon(
          `/api/chat/sessions/${activeSession.id}/archive`,
          new Blob(['{}'], { type: 'application/json' })
        )
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [activeSession, messages])

  const isViewOnly = activeSession && !activeSession.is_active

  return (
    <div className="flex h-[calc(100vh-64px)]">
      {/* 세션 사이드바 */}
      <div className="w-64 border-r border-slate-700/50 bg-slate-900 flex-shrink-0 flex flex-col">
        <div className="px-4 py-3 border-b border-slate-700/50">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Chat Sessions</h2>
        </div>
        <div className="flex-1 overflow-hidden">
          <SessionList
            sessions={sessions}
            activeId={activeSession?.id}
            onSelect={selectSession}
            onNew={createSession}
            onDelete={deleteSession}
            onRename={renameSession}
          />
        </div>
      </div>

      {/* 채팅 영역 */}
      <div className="flex-1 flex flex-col bg-white dark:bg-slate-900 min-w-0">
        {activeSession ? (
          <>
            {/* 헤더 */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
              <div>
                <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  {activeSession.title || '새 채팅'}
                </h2>
                {isViewOnly && (
                  <span className="text-xs text-amber-500 font-medium">읽기 전용 (히스토리)</span>
                )}
                {activeSession.skill_command && (
                  <span className="text-xs text-slate-400 ml-2">{activeSession.skill_command}</span>
                )}
              </div>
              {activeSession.is_active && (
                <div className="flex gap-2">
                  <button
                    onClick={handleCompact}
                    className="px-3 py-1 text-xs bg-slate-100 dark:bg-slate-800 rounded-lg
                               hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors
                               text-slate-600 dark:text-slate-300"
                  >
                    요약
                  </button>
                  <button
                    onClick={handleClear}
                    className="px-3 py-1 text-xs bg-slate-100 dark:bg-slate-800 rounded-lg
                               hover:bg-red-100 dark:hover:bg-red-900/30 text-red-600 transition-colors"
                  >
                    초기화
                  </button>
                </div>
              )}
            </div>

            {/* 메시지 목록 */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              {messages.length === 0 && !isStreaming && (
                <div className="flex items-center justify-center h-full text-slate-400">
                  <div className="text-center">
                    <p className="text-4xl mb-4">💬</p>
                    <p className="text-sm">대화를 시작해보세요</p>
                  </div>
                </div>
              )}
              {messages.map(msg => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              {isStreaming && streamingText && (
                <MessageBubble
                  message={{ role: 'assistant', content: streamingText }}
                  isStreaming={true}
                />
              )}
              {isStreaming && !streamingText && (
                <div className="flex justify-start mb-4">
                  <div className="bg-slate-100 dark:bg-slate-800 px-4 py-3 rounded-2xl rounded-bl-sm">
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* 입력 영역 */}
            {!isViewOnly && (
              <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 flex-shrink-0">
                <div className="flex gap-3">
                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        sendMessage()
                      }
                    }}
                    placeholder="메시지를 입력하세요... (Shift+Enter로 줄바꿈)"
                    disabled={isStreaming}
                    rows={1}
                    className="flex-1 px-4 py-3 border border-slate-300 dark:border-slate-600 rounded-xl
                               resize-none focus:outline-none focus:ring-2 focus:ring-blue-500
                               bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100
                               disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                  />
                  <button
                    onClick={sendMessage}
                    disabled={!input.trim() || isStreaming}
                    className="px-5 py-3 bg-blue-600 text-white rounded-xl font-medium text-sm
                               hover:bg-blue-700 transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
                  >
                    전송
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-slate-400">
            <div className="text-center">
              <p className="text-6xl mb-4">🤖</p>
              <p className="text-xl font-medium mb-2 text-slate-600 dark:text-slate-300">Claude Chat</p>
              <p className="text-sm">왼쪽에서 채팅을 선택하거나 새 채팅을 시작하세요</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
