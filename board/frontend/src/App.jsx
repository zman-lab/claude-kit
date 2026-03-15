import { useState, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Dashboard from './pages/Dashboard.jsx'
import BoardList from './pages/BoardList.jsx'
import Board from './pages/Board.jsx'
import Post from './pages/Post.jsx'
import NewPost from './pages/NewPost.jsx'
import RecentAll from './pages/RecentAll.jsx'
import Admin from './pages/Admin.jsx'
import Chat from './pages/Chat.jsx'
import SetupWizard from './pages/SetupWizard.jsx'
import { getSetupStatus } from './utils/api.js'

export default function App() {
  const [setupDone, setSetupDone] = useState(null) // null=로딩, true/false

  useEffect(() => {
    getSetupStatus()
      .then(data => setSetupDone(data.setup_complete))
      .catch(() => setSetupDone(true))
  }, [])

  if (setupDone === null) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-indigo-600 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!setupDone) {
    return <SetupWizard onComplete={() => setSetupDone(true)} />
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/boards" element={<BoardList />} />
        <Route path="/boards/:slug" element={<Board />} />
        <Route path="/boards/:slug/new" element={<NewPost />} />
        <Route path="/posts/:id" element={<Post />} />
        <Route path="/recent" element={<RecentAll />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
