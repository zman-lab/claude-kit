import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, ArcElement, Title, Tooltip, Legend, Filler } from 'chart.js'
import { Line, Bar, Doughnut } from 'react-chartjs-2'
import { getDashboardSummary, getTeamStats, getTagDistribution, getDailyTrend, getDailyTrendByTeam, getRecentActivity, getTokenUsage } from '../utils/api.js'
import { timeAgo } from '../utils/time.js'
import { stripMarkdown } from '../utils/markdown.js'
import Spinner from '../components/Spinner.jsx'
import TagBadge from '../components/TagBadge.jsx'
import { useToast } from '../contexts/ToastContext.jsx'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, ArcElement, Title, Tooltip, Legend, Filler)

function SummaryCard({ label, value, icon, color }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">{label}</p>
          <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{value}</p>
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg ${color}`}>
          {icon}
        </div>
      </div>
    </div>
  )
}

const FALLBACK_COLORS = ['#7c3aed', '#0891b2', '#ea580c', '#525252', '#059669', '#3b82f6', '#f59e0b', '#ef4444']

export default function Dashboard() {
  const [summary, setSummary] = useState(null)
  const [teamStats, setTeamStats] = useState(null)
  const [tagDist, setTagDist] = useState(null)
  const [trend, setTrend] = useState(null)
  const [trendByTeam, setTrendByTeam] = useState(null)
  const [activity, setActivity] = useState(null)
  const [tokenUsage, setTokenUsage] = useState(null)
  const [tokenPeriod, setTokenPeriod] = useState('7d')
  const [loading, setLoading] = useState(true)
  const [teamColors, setTeamColors] = useState({})

  // Card visibility settings (localStorage)
  const CARD_IDS = ['summary', 'dailyTrend', 'teamTrend', 'tagDist', 'tokenUsage', 'recentActivity']
  const [hiddenCards, setHiddenCards] = useState(() => {
    try { return JSON.parse(localStorage.getItem('dashboard-hidden-cards') || '[]') } catch { return [] }
  })
  const [showSettings, setShowSettings] = useState(false)

  const toggleCard = (id) => {
    const next = hiddenCards.includes(id) ? hiddenCards.filter(c => c !== id) : [...hiddenCards, id]
    setHiddenCards(next)
    localStorage.setItem('dashboard-hidden-cards', JSON.stringify(next))
  }

  const isVisible = (id) => !hiddenCards.includes(id)
  const toast = useToast()

  useEffect(() => {
    Promise.all([
      getDashboardSummary().then(setSummary),
      getTeamStats().then(setTeamStats),
      getTagDistribution().then(setTagDist),
      getDailyTrend().then(setTrend),
      getDailyTrendByTeam().then(setTrendByTeam),
      getRecentActivity(10).then(setActivity),
      getTokenUsage('7d', 'team').then(setTokenUsage),
      fetch('/api/admin/teams').then(r => r.json()).then(teams => {
        const colors = {}
        ;(Array.isArray(teams) ? teams : []).forEach(t => { if (t.slug && t.color) colors[t.slug] = t.color })
        setTeamColors(colors)
      }).catch(() => {}),
    ]).catch(() => {}).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    getTokenUsage(tokenPeriod, 'team').then(setTokenUsage).catch(() => {})
  }, [tokenPeriod])

  if (loading) return <Spinner size="lg" />

  const trendData = trend ? {
    labels: trend.map(d => d.date?.slice(5) || ''),
    datasets: [{
      label: 'Posts',
      data: trend.map(d => d.count),
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,.1)',
      fill: true,
      tension: 0.3,
    }],
  } : null

  const trendByTeamData = trendByTeam?.dates ? {
    labels: trendByTeam.dates.map(d => d.slice(5)),
    datasets: Object.entries(trendByTeam.teams || {}).map(([team, counts]) => ({
      label: team,
      data: counts,
      backgroundColor: teamColors[team] || '#94a3b8',
    })),
  } : null

  const tagData = tagDist ? {
    labels: tagDist.map(d => d.tag || 'none'),
    datasets: [{
      data: tagDist.map(d => d.count),
      backgroundColor: ['#3b82f6', '#f59e0b', '#ef4444', '#10b981', '#8b5cf6', '#94a3b8'],
    }],
  } : null

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { font: { size: 10 } } },
      y: { beginAtZero: true, ticks: { font: { size: 10 } } },
    },
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Dashboard</h1>
        <div className="relative">
          <button onClick={() => setShowSettings(!showSettings)} className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500">
            ⚙️
          </button>
          {showSettings && (
            <div className="absolute right-0 top-10 w-56 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg p-3 z-50">
              <p className="text-xs font-semibold text-slate-500 mb-2">표시할 카드</p>
              {[
                { id: 'summary', label: '요약 카드' },
                { id: 'dailyTrend', label: '일별 트렌드' },
                { id: 'teamTrend', label: '팀별 활동' },
                { id: 'tagDist', label: '태그 분포' },
                { id: 'tokenUsage', label: '토큰 사용량' },
                { id: 'recentActivity', label: '최근 활동' },
              ].map(({ id, label }) => (
                <label key={id} className="flex items-center gap-2 py-1 cursor-pointer">
                  <input type="checkbox" checked={isVisible(id)} onChange={() => toggleCard(id)} className="rounded" />
                  <span className="text-sm text-slate-700 dark:text-slate-300">{label}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Summary cards */}
      {isVisible('summary') && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <SummaryCard label="Total Posts" value={summary?.total_posts ?? 0} icon="📝" color="bg-blue-50 dark:bg-blue-900/30" />
          <SummaryCard label="Today" value={summary?.today_posts ?? 0} icon="📊" color="bg-green-50 dark:bg-green-900/30" />
          <SummaryCard label="Open Issues" value={summary?.open_issues ?? 0} icon="🔥" color="bg-red-50 dark:bg-red-900/30" />
          <SummaryCard label="Active Teams" value={summary?.active_teams_24h ?? 0} icon="👥" color="bg-purple-50 dark:bg-purple-900/30" />
        </div>
      )}

      {/* Charts row */}
      {(isVisible('dailyTrend') || isVisible('teamTrend')) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {isVisible('dailyTrend') && (
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Daily Post Trend</h3>
              <div className="h-48">
                {trendData && <Line data={trendData} options={chartOptions} />}
              </div>
            </div>
          )}

          {isVisible('teamTrend') && (
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Posts by Team</h3>
              <div className="h-48">
                {trendByTeamData && <Bar data={trendByTeamData} options={{ ...chartOptions, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } }, scales: { ...chartOptions.scales, x: { ...chartOptions.scales.x, stacked: true }, y: { ...chartOptions.scales.y, stacked: true } } }} />}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tag distribution + Token usage */}
      {(isVisible('tagDist') || isVisible('tokenUsage')) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {isVisible('tagDist') && (
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Tag Distribution</h3>
              <div className="h-48 flex items-center justify-center">
                {tagData && <Doughnut data={tagData} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 10, font: { size: 11 } } } } }} />}
              </div>
            </div>
          )}

          {isVisible('tokenUsage') && (
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Token Usage</h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={async () => {
                      await fetch('/api/token-usage/collect', { method: 'POST' })
                      getTokenUsage(tokenPeriod, 'team').then(setTokenUsage)
                      toast.success('토큰 수집 완료')
                    }}
                    className="text-xs px-2 py-1 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded hover:bg-slate-200 dark:hover:bg-slate-600"
                  >
                    Collect
                  </button>
                  <select
                    value={tokenPeriod}
                    onChange={e => setTokenPeriod(e.target.value)}
                    className="text-xs border border-slate-300 dark:border-slate-600 rounded-md px-2 py-1 bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-200"
                  >
                    <option value="7d">7 days</option>
                    <option value="30d">30 days</option>
                    <option value="all">All time</option>
                  </select>
                </div>
              </div>
              <div className="h-48">
                {tokenUsage?.datasets ? (
                  <Bar data={{
                    labels: tokenUsage.labels || [],
                    datasets: (tokenUsage.datasets || []).map((ds, i) => ({
                      label: ds.label,
                      data: ds.data,
                      backgroundColor: teamColors[ds.label] || FALLBACK_COLORS[i % FALLBACK_COLORS.length],
                    })),
                  }} options={{ ...chartOptions, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } } }} />
                ) : (
                  <div className="flex items-center justify-center h-full text-sm text-slate-400">No token data</div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Recent activity — 게시글 / 댓글 2컬럼 */}
      {isVisible('recentActivity') && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* 최근 게시글 */}
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Recent Posts</h3>
            <div className="divide-y divide-slate-100 dark:divide-slate-700">
              {activity?.filter(item => item.type === 'post').length > 0 ? (
                activity.filter(item => item.type === 'post').slice(0, 8).map((item, i) => (
                  <div key={i} className="py-2.5 flex items-start gap-3">
                    <div className="shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-xs">
                      📝
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{item.author}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {item.tag && <TagBadge tag={item.tag} />}
                        <Link to={`/posts/${item.id}`} className="text-sm text-slate-900 dark:text-white hover:text-blue-500 line-clamp-1">
                          {item.title || stripMarkdown(item.content)}
                        </Link>
                      </div>
                    </div>
                    <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">{timeAgo(item.created_at)}</span>
                  </div>
                ))
              ) : (
                <p className="py-4 text-sm text-slate-400 dark:text-slate-500 text-center">게시글이 없습니다</p>
              )}
            </div>
          </div>

          {/* 최근 댓글 */}
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Recent Replies</h3>
            <div className="divide-y divide-slate-100 dark:divide-slate-700">
              {activity?.filter(item => item.type === 'reply').length > 0 ? (
                activity.filter(item => item.type === 'reply').slice(0, 8).map((item, i) => (
                  <div key={i} className="py-2.5 flex items-start gap-3">
                    <div className="shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-xs">
                      💬
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{item.author}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Link to={`/posts/${item.post_id}`} className="text-sm text-slate-900 dark:text-white hover:text-blue-500 line-clamp-1">
                          {stripMarkdown(item.content)}
                        </Link>
                      </div>
                    </div>
                    <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">{timeAgo(item.created_at)}</span>
                  </div>
                ))
              ) : (
                <p className="py-4 text-sm text-slate-400 dark:text-slate-500 text-center">댓글이 없습니다</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
