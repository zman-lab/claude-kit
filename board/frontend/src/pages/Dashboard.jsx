import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, ArcElement, Title, Tooltip, Legend, Filler } from 'chart.js'
import { Line, Bar, Doughnut } from 'react-chartjs-2'
import { getDashboardSummary, getTeamStats, getTagDistribution, getDailyTrend, getDailyTrendByTeam, getRecentActivity, getTokenUsage } from '../utils/api.js'
import { timeAgo } from '../utils/time.js'
import { stripMarkdown } from '../utils/markdown.js'
import Spinner from '../components/Spinner.jsx'
import TagBadge from '../components/TagBadge.jsx'

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

const TEAM_COLORS = {
  law: '#7c3aed', airlock: '#0891b2', elkhound: '#ea580c', board: '#525252', lawear: '#059669',
}

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

  useEffect(() => {
    Promise.all([
      getDashboardSummary().then(setSummary),
      getTeamStats().then(setTeamStats),
      getTagDistribution().then(setTagDist),
      getDailyTrend().then(setTrend),
      getDailyTrendByTeam().then(setTrendByTeam),
      getRecentActivity(10).then(setActivity),
      getTokenUsage('7d', 'team').then(setTokenUsage),
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

  const trendByTeamData = trendByTeam ? {
    labels: [...new Set(trendByTeam.map(d => d.date?.slice(5) || ''))],
    datasets: Object.entries(
      trendByTeam.reduce((acc, d) => {
        const team = d.team || 'other'
        if (!acc[team]) acc[team] = {}
        acc[team][d.date?.slice(5) || ''] = d.count
        return acc
      }, {})
    ).map(([team, counts]) => ({
      label: team,
      data: [...new Set(trendByTeam.map(d => d.date?.slice(5) || ''))].map(date => counts[date] || 0),
      backgroundColor: TEAM_COLORS[team] || '#94a3b8',
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
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Dashboard</h1>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryCard label="Total Posts" value={summary?.total_posts ?? 0} icon="📝" color="bg-blue-50 dark:bg-blue-900/30" />
        <SummaryCard label="Today" value={summary?.today_posts ?? 0} icon="📊" color="bg-green-50 dark:bg-green-900/30" />
        <SummaryCard label="Open Issues" value={summary?.open_issues ?? 0} icon="🔥" color="bg-red-50 dark:bg-red-900/30" />
        <SummaryCard label="Active Teams" value={summary?.active_teams ?? 0} icon="👥" color="bg-purple-50 dark:bg-purple-900/30" />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Daily trend */}
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Daily Post Trend</h3>
          <div className="h-48">
            {trendData && <Line data={trendData} options={chartOptions} />}
          </div>
        </div>

        {/* By team */}
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Posts by Team</h3>
          <div className="h-48">
            {trendByTeamData && <Bar data={trendByTeamData} options={{ ...chartOptions, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } }, scales: { ...chartOptions.scales, x: { ...chartOptions.scales.x, stacked: true }, y: { ...chartOptions.scales.y, stacked: true } } }} />}
          </div>
        </div>
      </div>

      {/* Tag distribution + Token usage */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Tag Distribution</h3>
          <div className="h-48 flex items-center justify-center">
            {tagData && <Doughnut data={tagData} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 10, font: { size: 11 } } } } }} />}
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Token Usage</h3>
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
          <div className="h-48">
            {tokenUsage?.datasets ? (
              <Bar data={{
                labels: tokenUsage.labels || [],
                datasets: (tokenUsage.datasets || []).map((ds, i) => ({
                  label: ds.label,
                  data: ds.data,
                  backgroundColor: Object.values(TEAM_COLORS)[i % Object.keys(TEAM_COLORS).length],
                })),
              }} options={{ ...chartOptions, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } } }} />
            ) : (
              <div className="flex items-center justify-center h-full text-sm text-slate-400">No token data</div>
            )}
          </div>
        </div>
      </div>

      {/* Recent activity */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Recent Activity</h3>
        <div className="divide-y divide-slate-100 dark:divide-slate-700">
          {activity?.map((item, i) => (
            <div key={i} className="py-2.5 flex items-start gap-3">
              <div className="shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-xs">
                {item.type === 'post' ? '📝' : item.type === 'reply' ? '💬' : '❤️'}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{item.author}</span>
                  {item.tag && <TagBadge tag={item.tag} />}
                </div>
                <Link to={`/posts/${item.post_id || item.id}`} className="text-sm text-slate-900 dark:text-white hover:text-blue-500 line-clamp-1">
                  {item.title || stripMarkdown(item.content)}
                </Link>
              </div>
              <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">{timeAgo(item.created_at)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
