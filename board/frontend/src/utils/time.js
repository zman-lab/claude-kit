export function timeAgo(isoStr) {
  if (!isoStr) return ''
  const dt = new Date(isoStr)
  const now = new Date()
  const seconds = Math.floor((now - dt) / 1000)
  if (seconds < 60) return '방금 전'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}일 전`
  return dt.toLocaleDateString('ko-KR')
}

export function formatDate(isoStr) {
  if (!isoStr) return ''
  return new Date(isoStr).toLocaleDateString('ko-KR', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}
