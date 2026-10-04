import { useEffect } from 'react'
import { Navigate, Route, HashRouter as Router, Routes } from 'react-router-dom'
import Admin from './routes/Admin'
import Editor from './routes/Editor'
import Login from './routes/Login'
import Projects from './routes/Projects'
import { useAuth } from './lib/auth'
import { Spinner } from './components/ui'

export default function App() {
  const { user, ready, bootstrap } = useAuth()
  useEffect(() => { void bootstrap() }, [bootstrap])

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Wird geladen…" />
      </div>
    )
  }
  if (!user) return <Login />

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/p/:projectId" element={<Editor />} />
        <Route path="/admin" element={user.is_admin ? <Admin /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  )
}
