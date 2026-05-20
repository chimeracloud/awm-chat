import { useState } from 'react'
import { apiPost } from '../lib/api'
import Logo from './Logo'

export default function PrivacyAck({ onAccepted }) {
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function accept() {
    setBusy(true)
    setError(null)
    try {
      const profile = await apiPost('/me/acknowledge', { accepted: true })
      onAccepted(profile)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-screen flex items-center justify-center px-6 animate-fade-in">
      <div className="max-w-xl w-full bg-ink-800 border border-ink-500 rounded-lg shadow-2xl">
        <div className="border-b border-ink-500 px-8 py-6 flex items-center gap-4">
          <Logo size="md" />
        </div>

        <div className="px-8 py-7">
          <h2 className="font-display text-2xl text-cream-50 tracking-tightest mb-1">
            Before you begin
          </h2>
          <p className="text-sm text-cream-300 mb-5">Please read and acknowledge.</p>

          <div className="space-y-3 text-sm text-cream-200 leading-relaxed mb-6">
            <p>
              <span className="text-gold-500 font-medium">Company property.</span>{' '}
              All conversations are the property of Ascot Wealth Management and may be reviewed
              for compliance, training, and operational purposes.
            </p>
            <p>
              <span className="text-gold-500 font-medium">No personal content.</span>{' '}
              This is a work tool. Do not use it for personal matters, private correspondence,
              or non-work content of any kind.
            </p>
            <p>
              <span className="text-gold-500 font-medium">No client identifiers.</span>{' '}
              Do not paste live client personal data (full names with financial details,
              account numbers, ID numbers) unless explicitly authorised for that workflow.
            </p>
            <p>
              <span className="text-gold-500 font-medium">Audit trail.</span>{' '}
              All admin access to your conversations is logged and visible to management.
            </p>
          </div>

          <label className="flex items-start gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-ink-400 bg-ink-700 text-gold-500 focus:ring-gold-500 focus:ring-offset-ink-800"
            />
            <span className="text-sm text-cream-100 group-hover:text-cream-50">
              I have read and accept the terms above.
            </span>
          </label>

          {error && (
            <div className="mt-4 p-3 bg-accent-danger/10 border border-accent-danger/30 rounded text-sm text-accent-danger">
              {error}
            </div>
          )}

          <button
            onClick={accept}
            disabled={!checked || busy}
            className="mt-6 w-full bg-gold-500 hover:bg-gold-400 disabled:opacity-30 disabled:cursor-not-allowed text-ink-900 font-medium py-3 px-4 rounded-md transition-all"
          >
            {busy ? 'Confirming...' : 'Accept and Continue'}
          </button>
        </div>
      </div>
    </div>
  )
}
