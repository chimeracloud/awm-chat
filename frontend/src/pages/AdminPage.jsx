import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Users, Activity, AlertTriangle, Settings as SettingsIcon } from 'lucide-react'
import { apiGet, apiPut } from '../lib/api'
import Logo from '../components/Logo'

export default function AdminPage({ user, profile }) {
  const navigate = useNavigate()
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [flags, setFlags] = useState([])
  const [editingCap, setEditingCap] = useState(null)
  const [capValue, setCapValue] = useState('')

  useEffect(() => {
    apiGet('/admin/users').then((d) => setUsers(d.items || [])).catch(console.error)
    apiGet('/admin/metrics').then(setMetrics).catch(console.error)
    apiGet('/admin/flags').then((d) => setFlags(d.items || [])).catch(console.error)
  }, [])

  async function saveCap(uid) {
    const n = parseInt(capValue.replace(/[^0-9]/g, ''), 10)
    if (!Number.isFinite(n) || n <= 0) return
    await apiPut(`/admin/users/${uid}`, { cap_tokens: n })
    setUsers((us) => us.map((u) => (u.uid === uid ? { ...u, cap_tokens: n } : u)))
    setEditingCap(null)
  }

  return (
    <div className="h-screen flex flex-col bg-ink-900">
      {/* Header */}
      <header className="h-16 border-b border-ink-500/60 bg-ink-800/40 backdrop-blur flex items-center justify-between px-6">
        <div className="flex items-center gap-5">
          <button onClick={() => navigate('/')} className="text-ink-300 hover:text-cream-100 transition-colors">
            <ArrowLeft size={18}/>
          </button>
          <Logo size="md" />
          <span className="font-display italic text-sm text-cream-300 tracking-wide">
            Administration
          </span>
        </div>
        <div className="text-xs text-cream-300">{profile?.email}</div>
      </header>

      {/* Tabs */}
      <div className="px-6 border-b border-ink-500/60 flex items-center gap-1 bg-ink-800/20">
        {[
          { id: 'users', label: 'Users', icon: Users },
          { id: 'metrics', label: 'Metrics', icon: Activity },
          { id: 'flags', label: 'Flagged Content', icon: AlertTriangle },
          { id: 'settings', label: 'Settings', icon: SettingsIcon },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm border-b-2 transition-colors ${
              tab === id
                ? 'border-gold-500 text-cream-50'
                : 'border-transparent text-cream-300 hover:text-cream-100'
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'users' && (
          <div className="max-w-6xl">
            <div className="bg-ink-800/40 border border-ink-500/60 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-ink-700/50 border-b border-ink-500">
                  <tr className="text-left text-[0.65rem] uppercase tracking-[0.15em] text-cream-300">
                    <th className="px-4 py-3 font-medium">User</th>
                    <th className="px-4 py-3 font-medium">Role</th>
                    <th className="px-4 py-3 font-medium">Tokens this month</th>
                    <th className="px-4 py-3 font-medium">Cap</th>
                    <th className="px-4 py-3 font-medium">Conversations</th>
                    <th className="px-4 py-3 font-medium text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const pct = u.cap_tokens ? Math.min(100, (u.tokens_used / u.cap_tokens) * 100) : 0
                    const band = pct < 60 ? 'bg-accent-success' : pct < 85 ? 'bg-gold-500' : 'bg-accent-danger'
                    return (
                      <tr key={u.uid} className="border-b border-ink-500/40 hover:bg-ink-700/20">
                        <td className="px-4 py-3">
                          <div className="font-medium text-cream-100">{u.display_name || u.email}</div>
                          <div className="text-xs text-ink-300">{u.email}</div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded ${u.role === 'admin' ? 'bg-gold-500/15 text-gold-500' : 'bg-ink-600/50 text-cream-300'}`}>
                            {u.role || 'user'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <div className="text-cream-100 font-mono text-xs">{(u.tokens_used / 1000).toFixed(1)}k</div>
                            <div className="w-24 h-1.5 bg-ink-700 rounded-full overflow-hidden">
                              <div className={`h-full ${band}`} style={{ width: `${pct}%` }}/>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {editingCap === u.uid ? (
                            <div className="flex items-center gap-2">
                              <input
                                value={capValue}
                                onChange={(e) => setCapValue(e.target.value)}
                                className="w-24 px-2 py-1 bg-ink-700 border border-gold-500/40 rounded text-xs text-cream-100 font-mono focus:outline-none"
                                autoFocus
                                onKeyDown={(e) => { if (e.key === 'Enter') saveCap(u.uid); if (e.key === 'Escape') setEditingCap(null) }}
                              />
                              <button onClick={() => saveCap(u.uid)} className="text-xs text-gold-500 hover:text-gold-400">Save</button>
                            </div>
                          ) : (
                            <button onClick={() => { setEditingCap(u.uid); setCapValue(String(u.cap_tokens || 0)) }} className="font-mono text-xs text-cream-100 hover:text-gold-500">
                              {(u.cap_tokens / 1000).toFixed(0)}k
                            </button>
                          )}
                        </td>
                        <td className="px-4 py-3 text-cream-200 font-mono text-xs">{u.conversation_count || 0}</td>
                        <td className="px-4 py-3 text-right">
                          <button onClick={() => navigate(`/admin/user/${u.uid}`)} className="text-xs text-gold-500 hover:text-gold-400">
                            View →
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === 'metrics' && metrics && (
          <div className="max-w-6xl grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Stat label="Active users" value={metrics.active_users || 0} sub="last 30 days"/>
            <Stat label="Conversations" value={metrics.total_conversations || 0} sub="all time"/>
            <Stat label="Tokens this month" value={`${((metrics.tokens_this_month || 0) / 1_000_000).toFixed(2)}M`} sub="across all users"/>
            <Stat label="Estimated spend" value={`$${(metrics.estimated_spend_usd || 0).toFixed(2)}`} sub="this month"/>
          </div>
        )}

        {tab === 'flags' && (
          <div className="max-w-5xl">
            <div className="bg-ink-800/40 border border-ink-500/60 rounded-lg">
              <div className="px-5 py-4 border-b border-ink-500/60 flex items-center justify-between">
                <span className="font-display text-lg text-cream-50 tracking-tight">Flagged content review</span>
                <span className="text-xs text-cream-300">{flags.length} pending</span>
              </div>
              <div className="divide-y divide-ink-500/40">
                {flags.length === 0 ? (
                  <div className="text-center py-12 text-sm text-ink-300">No flagged content.</div>
                ) : (
                  flags.map((f) => (
                    <div key={f.id} className="px-5 py-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-xs text-cream-300">
                          <span className="text-cream-100 font-medium">{f.user_email}</span>
                          <span className="text-ink-300"> · {new Date(f.created_at).toLocaleString()}</span>
                        </div>
                        <span className="text-[0.65rem] uppercase tracking-[0.15em] text-accent-danger">
                          {f.reason}
                        </span>
                      </div>
                      <p className="text-sm text-cream-200 bg-ink-700/30 border border-ink-500/30 rounded p-3 font-mono whitespace-pre-wrap">{f.snippet}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {tab === 'settings' && (
          <div className="max-w-2xl space-y-4">
            <div className="bg-ink-800/40 border border-ink-500/60 rounded-lg p-6">
              <h3 className="font-display text-lg text-cream-50 mb-2 tracking-tight">Default token cap</h3>
              <p className="text-sm text-cream-300 mb-4">Applied to new users at first sign-in.</p>
              <input
                type="text"
                defaultValue="500000"
                className="w-48 px-3 py-2 bg-ink-700 border border-ink-500 rounded text-cream-100 font-mono text-sm focus:outline-none focus:border-gold-500/40"
              />
            </div>
            <div className="bg-ink-800/40 border border-ink-500/60 rounded-lg p-6">
              <h3 className="font-display text-lg text-cream-50 mb-2 tracking-tight">Keyword flags</h3>
              <p className="text-sm text-cream-300 mb-4">Comma-separated terms. Matches are flagged for review.</p>
              <textarea
                defaultValue="account number, ID number, password"
                rows={3}
                className="w-full px-3 py-2 bg-ink-700 border border-ink-500 rounded text-cream-100 text-sm focus:outline-none focus:border-gold-500/40 resize-none"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, sub }) {
  return (
    <div className="bg-ink-800/40 border border-ink-500/60 rounded-lg p-5">
      <div className="text-[0.65rem] uppercase tracking-[0.15em] text-cream-300 mb-2">{label}</div>
      <div className="font-display text-3xl text-cream-50 tracking-tightest">{value}</div>
      {sub && <div className="text-xs text-ink-300 mt-1">{sub}</div>}
    </div>
  )
}
