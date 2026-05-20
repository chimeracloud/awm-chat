import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { onAuthChange } from './lib/firebase'
import { apiGet } from './lib/api'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import AdminPage from './pages/AdminPage'
import PrivacyAck from './components/PrivacyAck'

export default function App() {
  const [user, setUser] = useState(undefined) // undefined = loading, null = signed out
  const [profile, setProfile] = useState(null)

  useEffect(() => {
    return onAuthChange(async (fbUser) => {
      setUser(fbUser)
      if (fbUser) {
        try {
          const p = await apiGet('/me')
          setProfile(p)
        } catch (e) {
          console.error('Profile load failed', e)
        }
      } else {
        setProfile(null)
      }
    })
  }, [])

  if (user === undefined) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="font-display text-cream-300 text-lg tracking-tight">Loading...</div>
      </div>
    )
  }

  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  if (profile && !profile.ack_accepted) {
    return <PrivacyAck onAccepted={(p) => setProfile(p)} />
  }

  return (
    <Routes>
      <Route path="/" element={<ChatPage user={user} profile={profile} />} />
      <Route path="/c/:conversationId" element={<ChatPage user={user} profile={profile} />} />
      <Route
        path="/admin"
        element={
          profile?.role === 'admin'
            ? <AdminPage user={user} profile={profile} />
            : <Navigate to="/" replace />
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
