const BASE = ''

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Boards ──
export const getBoards = () => request('/api/boards')

// ── Posts ──
export const getPosts = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.board_slug) qs.set('board_slug', params.board_slug)
  if (params.tag) qs.set('tag', params.tag)
  if (params.limit) qs.set('limit', params.limit)
  if (params.offset) qs.set('offset', params.offset)
  return request(`/api/posts?${qs}`)
}

export const getPost = (id) => request(`/api/posts/${id}`)

export const createPost = (data) => request('/api/posts', {
  method: 'POST', body: JSON.stringify(data),
})

export const updatePost = (id, data) => request(`/api/posts/${id}`, {
  method: 'PUT', body: JSON.stringify(data),
})

export const deletePost = (id) => request(`/api/posts/${id}`, { method: 'DELETE' })

// ── Replies ──
export const createReply = (postId, data) => request(`/api/posts/${postId}/reply`, {
  method: 'POST', body: JSON.stringify(data),
})

export const updateReply = (id, data) => request(`/api/replies/${id}`, {
  method: 'PUT', body: JSON.stringify(data),
})

export const deleteReply = (id) => request(`/api/posts/${id}`, { method: 'DELETE' })

// ── Likes ──
export const toggleLike = (postId, author = 'anonymous') => request(`/api/posts/${postId}/like`, {
  method: 'POST', body: JSON.stringify({ author }),
})

// ── Search ──
export const searchPosts = (q, boardSlug = null, limit = 20) => {
  const qs = new URLSearchParams({ q, limit })
  if (boardSlug) qs.set('board_slug', boardSlug)
  return request(`/api/search?${qs}`)
}

// ── Recent ──
export const getRecent = (limit = 10) => request(`/api/recent?limit=${limit}`)

export const getRecentAll = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.team) qs.set('team', params.team)
  if (params.tag) qs.set('tag', params.tag)
  if (params.scope) qs.set('scope', params.scope)
  if (params.limit) qs.set('limit', params.limit)
  return request(`/api/recent-all?${qs}`)
}

// ── Dashboard ──
export const getDashboardSummary = () => request('/api/dashboard/summary')
export const getTeamStats = () => request('/api/dashboard/team-stats')
export const getTagDistribution = () => request('/api/dashboard/tag-distribution')
export const getDailyTrend = (days = 14) => request(`/api/dashboard/daily-trend?days=${days}`)
export const getDailyTrendByTeam = (days = 14) => request(`/api/dashboard/daily-trend-by-team?days=${days}`)
export const getRecentActivity = (limit = 10) => request(`/api/dashboard/recent-activity?limit=${limit}`)
export const getTokenUsage = (period = '7d', groupBy = 'team') =>
  request(`/api/token-usage?period=${period}&group_by=${groupBy}`)

// ── Attachments ──
export async function uploadAttachment(postId, file, uploader = 'anonymous') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('uploader', uploader)
  const res = await fetch(`/api/posts/${postId}/attachments`, {
    method: 'POST', body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const getAttachments = (postId) => request(`/api/posts/${postId}/attachments`)
export const deleteAttachment = (id) => request(`/api/attachments/${id}`, { method: 'DELETE' })

// ── Admin / Auth ──
export const verifyPassword = (password, visitorId = null) =>
  request('/api/auth/verify', {
    method: 'POST',
    body: JSON.stringify({ password, visitor_id: visitorId }),
  })

export const getPasswords = (adminPw) =>
  request('/api/admin/passwords', {
    headers: { 'X-Admin-Password': adminPw },
  })

export const createPassword = (adminPw, data) =>
  request('/api/admin/passwords', {
    method: 'POST',
    headers: { 'X-Admin-Password': adminPw, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const updatePassword = (adminPw, id, data) =>
  request(`/api/admin/passwords/${id}`, {
    method: 'PATCH',
    headers: { 'X-Admin-Password': adminPw, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const deletePassword = (adminPw, id) =>
  request(`/api/admin/passwords/${id}`, {
    method: 'DELETE',
    headers: { 'X-Admin-Password': adminPw },
  })

// ── Setup ──
export const getSetupStatus = () => request('/api/setup/status').catch(() => ({ setup_complete: true }))
export const initSetup = (data) => request('/api/setup/init', {
  method: 'POST', body: JSON.stringify(data),
})

// ── Teams (admin) ──
export const getTeams = (password) =>
  request('/api/admin/teams', {
    headers: password ? { 'X-Admin-Password': password } : {},
  }).catch(() => [])

export const createTeam = (password, data) =>
  request('/api/admin/teams', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Password': password },
    body: JSON.stringify(data),
  })

export const updateTeam = (password, id, data) =>
  request(`/api/admin/teams/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Password': password },
    body: JSON.stringify(data),
  })

export const deleteTeam = (password, id) =>
  request(`/api/admin/teams/${id}`, {
    method: 'DELETE',
    headers: { 'X-Admin-Password': password },
  })

// ── Backup ──
export async function downloadBackup(password) {
  const res = await fetch(`${BASE}/api/admin/backup`, {
    headers: password ? { 'X-Admin-Password': password } : {},
  })
  if (!res.ok) throw new Error('백업 다운로드 실패')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `claude-board-backup-${new Date().toISOString().slice(0, 10)}.db`
  a.click()
  URL.revokeObjectURL(url)
}

export async function importBackup(password, file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE}/api/admin/import`, {
    method: 'POST',
    headers: password ? { 'X-Admin-Password': password } : {},
    body: formData,
  })
  if (!res.ok) throw new Error('임포트 실패')
  return res.json()
}
