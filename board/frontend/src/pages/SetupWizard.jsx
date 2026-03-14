import { useState } from 'react'
import { initSetup } from '../utils/api'

const TEAM_ICONS = [
  { emoji: '📋', label: '게시판' },
  { emoji: '🚀', label: '로켓' },
  { emoji: '⚡', label: '번개' },
  { emoji: '🔥', label: '불꽃' },
  { emoji: '💡', label: '아이디어' },
  { emoji: '🎯', label: '타겟' },
  { emoji: '🛡️', label: '방패' },
  { emoji: '⚖️', label: '저울' },
  { emoji: '🔐', label: '자물쇠' },
  { emoji: '🐕', label: '강아지' },
  { emoji: '🦊', label: '여우' },
  { emoji: '🐻', label: '곰' },
  { emoji: '⭐', label: '별' },
  { emoji: '🌟', label: '반짝별' },
  { emoji: '💎', label: '보석' },
  { emoji: '🎨', label: '팔레트' },
  { emoji: '🔧', label: '공구' },
  { emoji: '📊', label: '차트' },
  { emoji: '🏗️', label: '건설' },
  { emoji: '🧪', label: '실험' },
]

export default function SetupWizard({ onComplete }) {
  const [step, setStep] = useState(1)
  const [password, setPassword] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [team, setTeam] = useState({ name: '', slug: '', icon: '📋', color: '#6366f1', description: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleNameChange = (name) => {
    const slug = name.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '')
    setTeam({ ...team, name, slug })
  }

  const submitStep1 = () => {
    if (password.length < 4) return setError('비밀번호는 최소 4자 이상')
    if (password !== confirmPw) return setError('비밀번호가 일치하지 않습니다')
    setError('')
    setStep(2)
  }

  const submitStep2 = async () => {
    if (!team.name || !team.slug) return setError('팀 이름을 입력해주세요')
    setLoading(true)
    setError('')
    try {
      await initSetup({
        admin_password: password,
        team_name: team.name,
        team_slug: team.slug,
        team_icon: team.icon,
        team_color: team.color,
        team_description: team.description || ''
      })
      setStep(3)
    } catch (e) {
      setError(e.message || '설정 실패')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8 max-w-md w-full">
        {/* 스텝 인디케이터 */}
        <div className="flex justify-center mb-8 gap-2">
          {[1, 2, 3].map(s => (
            <div key={s} className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${step >= s ? 'bg-indigo-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'}`}>
              {step > s ? '\u2713' : s}
            </div>
          ))}
        </div>

        <h1 className="text-2xl font-bold text-center mb-2 dark:text-white">
          {step === 1 ? '관리자 비밀번호 설정' : step === 2 ? '첫 번째 팀 만들기' : '설정 완료!'}
        </h1>
        <p className="text-gray-500 dark:text-gray-400 text-center mb-6 text-sm">
          {step === 1 ? '게시판 관리에 사용할 비밀번호를 설정하세요' : step === 2 ? '팀 정보를 입력하면 게시판이 자동 생성됩니다' : '모든 준비가 끝났습니다'}
        </p>

        {error && <div className="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 p-3 rounded-lg mb-4 text-sm">{error}</div>}

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">비밀번호</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none" placeholder="최소 4자" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">비밀번호 확인</label>
              <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none" placeholder="다시 입력" onKeyDown={e => e.key === 'Enter' && submitStep1()} />
            </div>
            <button onClick={submitStep1} className="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-700 font-medium transition-colors">다음</button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">팀 이름</label>
              <input type="text" value={team.name} onChange={e => handleNameChange(e.target.value)} className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none" placeholder="예: 개발팀" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">슬러그 (URL용)</label>
              <input type="text" value={team.slug} onChange={e => setTeam({ ...team, slug: e.target.value })} className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white bg-gray-50 dark:bg-gray-700 focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none" placeholder="영어소문자, 숫자, -, _ 만 가능" />
              <p className="text-xs text-gray-400 mt-1">예: dev-team, alpha_1</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">팀 아이콘</label>
              <div className="grid grid-cols-10 gap-2">
                {TEAM_ICONS.map(({ emoji, label }) => (
                  <button
                    key={emoji}
                    type="button"
                    onClick={() => setTeam({...team, icon: emoji})}
                    title={label}
                    className={`text-2xl p-2 rounded-lg border-2 transition-all ${
                      team.icon === emoji
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 scale-110'
                        : 'border-transparent hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">팀 색상</label>
              <input type="color" value={team.color} onChange={e => setTeam({ ...team, color: e.target.value })} className="w-full h-10 rounded-lg cursor-pointer border border-gray-300 dark:border-gray-600" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">설명 (선택)</label>
              <textarea value={team.description} onChange={e => setTeam({ ...team, description: e.target.value })} className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none" rows={2} placeholder="팀에 대한 간단한 설명" />
            </div>
            <div className="flex gap-2">
              <button onClick={() => setStep(1)} className="flex-1 border border-gray-300 dark:border-gray-600 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 dark:text-white font-medium transition-colors">이전</button>
              <button onClick={submitStep2} disabled={loading} className="flex-1 bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-700 font-medium disabled:opacity-50 transition-colors">{loading ? '설정 중...' : '완료'}</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="text-center space-y-4">
            <div className="text-6xl mb-4">🎉</div>
            <p className="text-gray-600 dark:text-gray-300">
              <span className="font-bold" style={{ color: team.color }}>{team.icon} {team.name}</span> 팀 게시판이 생성되었습니다!
            </p>
            <button onClick={() => window.location.reload()} className="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-700 font-medium transition-colors">대시보드로 이동</button>
          </div>
        )}
      </div>
    </div>
  )
}
