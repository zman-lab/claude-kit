import { useState, useEffect } from 'react'
import { verifyPassword, getPasswords, createPassword, updatePassword, deletePassword as deletePw, downloadBackup, importBackup, getTeams, createTeam, updateTeam, deleteTeam } from '../utils/api.js'
import { useToast } from '../contexts/ToastContext.jsx'
import Spinner from '../components/Spinner.jsx'

function AuthGate({ onAuth }) {
  const [pw, setPw] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const result = await verifyPassword(pw)
      if (result.valid && result.password_type === 'admin') {
        localStorage.setItem('cb-admin-pw', pw)
        onAuth(pw)
      } else {
        setError('Admin password required')
      }
    } catch {
      setError('Invalid password')
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <form onSubmit={handleSubmit} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-8 shadow-sm w-80 space-y-4">
        <h2 className="text-lg font-bold text-slate-900 dark:text-white text-center">Admin Login</h2>
        <input
          type="password"
          value={pw}
          onChange={e => { setPw(e.target.value); setError('') }}
          placeholder="Admin password"
          className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-sm text-slate-900 dark:text-white"
          autoFocus
        />
        {error && <p className="text-xs text-red-500">{error}</p>}
        <button type="submit" className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg">
          Login
        </button>
      </form>
    </div>
  )
}

function PasswordsTab({ adminPw }) {
  const toast = useToast()
  const [passwords, setPasswords] = useState([])
  const [loading, setLoading] = useState(true)
  const [newPw, setNewPw] = useState({ password: '', label: '', password_type: 'user', expires_hours: '' })

  const load = () => {
    setLoading(true)
    getPasswords(adminPw).then(setPasswords).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(load, [adminPw])

  const handleCreate = async (e) => {
    e.preventDefault()
    try {
      await createPassword(adminPw, {
        ...newPw,
        expires_hours: newPw.expires_hours ? parseFloat(newPw.expires_hours) : null,
      })
      setNewPw({ password: '', label: '', password_type: 'user', expires_hours: '' })
      toast.success('Password created')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleAction = async (id, action, minutes = null) => {
    try {
      await updatePassword(adminPw, id, { action, minutes })
      toast.success('Updated')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this password?')) return
    try {
      await deletePw(adminPw, id)
      toast.success('Deleted')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-4">
      {/* Create form */}
      <form onSubmit={handleCreate} className="flex flex-wrap gap-2 items-end">
        <div>
          <label className="block text-xs text-slate-500 mb-1">Password</label>
          <input value={newPw.password} onChange={e => setNewPw({ ...newPw, password: e.target.value })} className="px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm w-32" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Label</label>
          <input value={newPw.label} onChange={e => setNewPw({ ...newPw, label: e.target.value })} className="px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm w-32" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Type</label>
          <select value={newPw.password_type} onChange={e => setNewPw({ ...newPw, password_type: e.target.value })} className="px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm">
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Expires (h)</label>
          <input value={newPw.expires_hours} onChange={e => setNewPw({ ...newPw, expires_hours: e.target.value })} className="px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm w-20" placeholder="null" />
        </div>
        <button type="submit" className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded">Create</button>
      </form>

      {/* List */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700">
              <th className="py-2 px-2">ID</th>
              <th className="py-2 px-2">Label</th>
              <th className="py-2 px-2">Type</th>
              <th className="py-2 px-2">Password</th>
              <th className="py-2 px-2">Expires</th>
              <th className="py-2 px-2">Status</th>
              <th className="py-2 px-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
            {passwords.map(p => (
              <tr key={p.id} className={p.expired || !p.is_active ? 'opacity-50' : ''}>
                <td className="py-2 px-2">{p.id}</td>
                <td className="py-2 px-2">{p.label}</td>
                <td className="py-2 px-2"><span className={`px-1.5 py-0.5 rounded text-xs ${p.password_type === 'admin' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'}`}>{p.password_type}</span></td>
                <td className="py-2 px-2 font-mono text-xs">{p.password_plain || '***'}</td>
                <td className="py-2 px-2 text-xs">{p.expires_at || 'Never'}</td>
                <td className="py-2 px-2">
                  {p.expired ? <span className="text-red-500 text-xs">Expired</span> : p.is_active ? <span className="text-green-500 text-xs">Active</span> : <span className="text-slate-400 text-xs">Inactive</span>}
                </td>
                <td className="py-2 px-2">
                  <div className="flex gap-1">
                    <button onClick={() => handleAction(p.id, 'extend', 60)} className="px-1.5 py-0.5 text-xs bg-green-100 text-green-700 rounded">+1h</button>
                    <button onClick={() => handleAction(p.id, 'expire_now')} className="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-700 rounded">Expire</button>
                    {p.bound_visitor_id && <button onClick={() => handleAction(p.id, 'unbind')} className="px-1.5 py-0.5 text-xs bg-purple-100 text-purple-700 rounded">Unbind</button>}
                    <button onClick={() => handleDelete(p.id)} className="px-1.5 py-0.5 text-xs bg-red-100 text-red-700 rounded">Del</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TeamsTab({ adminPw }) {
  const toast = useToast()
  const [teams, setTeams] = useState([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [editData, setEditData] = useState({})
  const [newTeam, setNewTeam] = useState({ name: '', slug: '', icon: '📋', color: '#6366f1', description: '' })
  const [showForm, setShowForm] = useState(false)

  const load = () => {
    setLoading(true)
    getTeams(adminPw).then(setTeams).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(load, [adminPw])

  const handleNameChange = (name) => {
    const slug = name.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '')
    setNewTeam({ ...newTeam, name, slug })
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!newTeam.name || !newTeam.slug) return toast.error('팀 이름을 입력해주세요')
    try {
      await createTeam(adminPw, newTeam)
      setNewTeam({ name: '', slug: '', icon: '📋', color: '#6366f1', description: '' })
      setShowForm(false)
      toast.success('팀 생성 완료')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const startEdit = (team) => {
    setEditingId(team.id)
    setEditData({ name: team.name, slug: team.slug, icon: team.icon || '📋', color: team.color || '#6366f1', description: team.description || '' })
  }

  const handleUpdate = async (id) => {
    try {
      await updateTeam(adminPw, id, editData)
      setEditingId(null)
      toast.success('팀 수정 완료')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleDelete = async (id, name) => {
    if (!confirm(`정말 "${name}" 팀을 삭제하시겠습니까?`)) return
    try {
      await deleteTeam(adminPw, id)
      toast.success('팀 삭제 완료')
      load()
    } catch (e) {
      toast.error(e.message)
    }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-4">
      {/* 팀 추가 버튼/폼 */}
      {!showForm ? (
        <button onClick={() => setShowForm(true)} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg">+ 팀 추가</button>
      ) : (
        <form onSubmit={handleCreate} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 shadow-sm space-y-3">
          <div className="flex flex-wrap gap-2 items-end">
            <div className="flex-1 min-w-[120px]">
              <label className="block text-xs text-slate-500 mb-1">팀 이름</label>
              <input value={newTeam.name} onChange={e => handleNameChange(e.target.value)} className="w-full px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm dark:text-white" placeholder="예: 개발팀" />
            </div>
            <div className="flex-1 min-w-[100px]">
              <label className="block text-xs text-slate-500 mb-1">슬러그</label>
              <input value={newTeam.slug} onChange={e => setNewTeam({ ...newTeam, slug: e.target.value })} className="w-full px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm dark:text-white" placeholder="자동 생성" />
            </div>
            <div className="w-16">
              <label className="block text-xs text-slate-500 mb-1">아이콘</label>
              <input value={newTeam.icon} onChange={e => setNewTeam({ ...newTeam, icon: e.target.value })} className="w-full px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded text-center text-lg dark:bg-slate-700" />
            </div>
            <div className="w-16">
              <label className="block text-xs text-slate-500 mb-1">색상</label>
              <input type="color" value={newTeam.color} onChange={e => setNewTeam({ ...newTeam, color: e.target.value })} className="w-full h-8 rounded cursor-pointer" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">설명 (선택)</label>
            <input value={newTeam.description} onChange={e => setNewTeam({ ...newTeam, description: e.target.value })} className="w-full px-2 py-1.5 border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-sm dark:text-white" placeholder="팀 설명" />
          </div>
          <div className="flex gap-2">
            <button type="submit" className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded">생성</button>
            <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 border border-slate-300 dark:border-slate-600 text-sm rounded text-slate-600 dark:text-slate-300">취소</button>
          </div>
        </form>
      )}

      {/* 팀 목록 */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500 border-b border-slate-200 dark:border-slate-700">
              <th className="py-2 px-2">ID</th>
              <th className="py-2 px-2">아이콘</th>
              <th className="py-2 px-2">이름</th>
              <th className="py-2 px-2">슬러그</th>
              <th className="py-2 px-2">색상</th>
              <th className="py-2 px-2">설명</th>
              <th className="py-2 px-2">액션</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
            {teams.map(t => (
              <tr key={t.id}>
                <td className="py-2 px-2">{t.id}</td>
                {editingId === t.id ? (
                  <>
                    <td className="py-2 px-2"><input value={editData.icon} onChange={e => setEditData({ ...editData, icon: e.target.value })} className="w-10 px-1 py-0.5 border border-slate-300 dark:border-slate-600 rounded text-center dark:bg-slate-700" /></td>
                    <td className="py-2 px-2"><input value={editData.name} onChange={e => setEditData({ ...editData, name: e.target.value })} className="w-24 px-1 py-0.5 border border-slate-300 dark:border-slate-600 rounded dark:bg-slate-700 dark:text-white text-sm" /></td>
                    <td className="py-2 px-2"><input value={editData.slug} onChange={e => setEditData({ ...editData, slug: e.target.value })} className="w-24 px-1 py-0.5 border border-slate-300 dark:border-slate-600 rounded dark:bg-slate-700 dark:text-white text-sm" /></td>
                    <td className="py-2 px-2"><input type="color" value={editData.color} onChange={e => setEditData({ ...editData, color: e.target.value })} className="w-8 h-6 rounded cursor-pointer" /></td>
                    <td className="py-2 px-2"><input value={editData.description} onChange={e => setEditData({ ...editData, description: e.target.value })} className="w-32 px-1 py-0.5 border border-slate-300 dark:border-slate-600 rounded dark:bg-slate-700 dark:text-white text-sm" /></td>
                    <td className="py-2 px-2">
                      <div className="flex gap-1">
                        <button onClick={() => handleUpdate(t.id)} className="px-1.5 py-0.5 text-xs bg-green-100 text-green-700 rounded">저장</button>
                        <button onClick={() => setEditingId(null)} className="px-1.5 py-0.5 text-xs bg-slate-100 text-slate-600 rounded">취소</button>
                      </div>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="py-2 px-2 text-lg">{t.icon || '📋'}</td>
                    <td className="py-2 px-2 font-medium dark:text-white">{t.name}</td>
                    <td className="py-2 px-2 font-mono text-xs text-slate-500">{t.slug}</td>
                    <td className="py-2 px-2"><div className="w-6 h-6 rounded" style={{ backgroundColor: t.color || '#6366f1' }} /></td>
                    <td className="py-2 px-2 text-xs text-slate-500 max-w-[200px] truncate">{t.description || '-'}</td>
                    <td className="py-2 px-2">
                      <div className="flex gap-1">
                        <button onClick={() => startEdit(t)} className="px-1.5 py-0.5 text-xs bg-blue-100 text-blue-700 rounded">수정</button>
                        <button onClick={() => handleDelete(t.id, t.name)} className="px-1.5 py-0.5 text-xs bg-red-100 text-red-700 rounded">삭제</button>
                      </div>
                    </td>
                  </>
                )}
              </tr>
            ))}
            {teams.length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-slate-400 text-sm">등록된 팀이 없습니다</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function BackupTab({ adminPw }) {
  const toast = useToast()
  const [importing, setImporting] = useState(false)

  const handleBackup = async () => {
    try {
      await downloadBackup(adminPw)
      toast.success('백업 다운로드 완료')
    } catch (e) {
      toast.error(e.message)
    }
  }

  const handleImport = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    if (!confirm('기존 데이터가 모두 덮어씌워집니다. 계속하시겠습니까?')) {
      e.target.value = ''
      return
    }
    setImporting(true)
    try {
      await importBackup(adminPw, file)
      toast.success('임포트 완료 - 페이지를 새로고침합니다')
      setTimeout(() => window.location.reload(), 1500)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">백업</h3>
        <p className="text-xs text-slate-500 mb-3">현재 데이터베이스를 백업 파일로 다운로드합니다.</p>
        <button onClick={handleBackup} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg">
          백업 다운로드
        </button>
      </div>
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">임포트</h3>
        <p className="text-xs text-slate-500 mb-3">백업 파일을 업로드하여 데이터베이스를 복원합니다. 기존 데이터가 모두 덮어씌워집니다.</p>
        <label className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white text-sm rounded-lg cursor-pointer inline-block">
          {importing ? '임포트 중...' : '백업 업로드'}
          <input type="file" accept=".db" onChange={handleImport} className="hidden" disabled={importing} />
        </label>
      </div>
    </div>
  )
}

export default function Admin() {
  const [adminPw, setAdminPw] = useState(() => localStorage.getItem('cb-admin-pw') || '')
  const [authenticated, setAuthenticated] = useState(false)
  const [tab, setTab] = useState('passwords')

  useEffect(() => {
    if (adminPw) {
      verifyPassword(adminPw).then(r => {
        if (r.valid && r.password_type === 'admin') setAuthenticated(true)
        else setAdminPw('')
      }).catch(() => setAdminPw(''))
    }
  }, [])

  if (!authenticated) {
    return <AuthGate onAuth={(pw) => { setAdminPw(pw); setAuthenticated(true) }} />
  }

  const tabs = [
    { id: 'passwords', label: 'Passwords' },
    { id: 'teams', label: '팀 관리' },
    { id: 'backup', label: '백업 / 복원' },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Admin</h1>
        <button
          onClick={() => { localStorage.removeItem('cb-admin-pw'); setAuthenticated(false); setAdminPw('') }}
          className="text-xs text-slate-400 hover:text-red-500"
        >
          Logout
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-700">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-[1px]
              ${tab === t.id
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'passwords' && <PasswordsTab adminPw={adminPw} />}
      {tab === 'teams' && <TeamsTab adminPw={adminPw} />}
      {tab === 'backup' && <BackupTab adminPw={adminPw} />}
    </div>
  )
}
