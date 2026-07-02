import { Pin, LogOut, Settings, HelpCircle, Download } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { signOut } from '../lib/firebase'
import { apiDownload } from '../lib/api'

export default function TopBar({ user, profile, usage, onTogglePins, pinsActive }) {
  const navigate = useNavigate()
  const [exporting, setExporting] = useState(false)

  async function exportMyData() {
    if (exporting) return
    setExporting(true)
    try {
      await apiDownload('/export/me', 'my_awm_chat_export.zip')
    } catch (e) {
      console.error('Export failed', e)
      alert('Export failed: ' + e.message)
    } finally {
      setExporting(false)
    }
  }
  const pct = usage && usage.cap_tokens ? Math.min(100, (usage.tokens_used / usage.cap_tokens) * 100) : 0
  const pctBand = pct < 60 ? 'bg-accent-success' : pct < 85 ? 'bg-gold-500' : 'bg-accent-danger'

  return (
    <header className="h-14 border-b border-ink-500/60 bg-ink-800/40 backdrop-blur flex items-center justify-between px-5">
      <div className="flex items-center gap-4">
        <div className="font-display italic text-cream-300 text-sm tracking-wide">
          Conversations are confidential to you, visible to compliance.
        </div>
      </div>

      <div className="flex items-center gap-5">
        {usage && (
          <div className="flex items-center gap-3 text-xs">
            <div className="text-cream-300">
              <span className="text-cream-100 font-medium">{Math.round(usage.tokens_used / 1000)}k</span>
              <span className="text-ink-300"> / {Math.round(usage.cap_tokens / 1000)}k tokens</span>
            </div>
            <div className="w-20 h-1.5 bg-ink-700 rounded-full overflow-hidden">
              <div className={`h-full ${pctBand} transition-all`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        <button
          onClick={onTogglePins}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            pinsActive
              ? 'bg-gold-500/15 text-gold-500 border border-gold-500/30'
              : 'text-cream-200 hover:bg-ink-700 border border-transparent'
          }`}
        >
          <Pin size={13} />
          Pinned context
        </button>

        <button
          onClick={exportMyData}
          disabled={exporting}
          className="text-ink-300 hover:text-cream-100 transition-colors disabled:opacity-50"
          title="Download my data (chats, pinned context and attachments)"
        >
          <Download size={16} className={exporting ? 'animate-pulse' : ''} />
        </button>

        <button
          onClick={() => navigate('/help')}
          className="text-ink-300 hover:text-cream-100 transition-colors"
          title="User manual"
        >
          <HelpCircle size={16} />
        </button>

        {profile?.role === 'admin' && (
          <button
            onClick={() => navigate('/admin')}
            className="text-ink-300 hover:text-cream-100 transition-colors"
            title="Admin"
          >
            <Settings size={16} />
          </button>
        )}

        <button
          onClick={() => signOut()}
          className="text-ink-300 hover:text-cream-100 transition-colors"
          title="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  )
}
