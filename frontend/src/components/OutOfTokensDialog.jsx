import { useEffect, useRef } from 'react'
import { BatteryWarning, ArrowRight, X } from 'lucide-react'

function formatTokens(n) {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

/**
 * Shown when the active agent runs out of tokens mid-send.
 *
 * The backend refuses the turn with the list of agents that still have
 * headroom, so this offers a one-click switch that also retries the message —
 * the user does not have to retype anything. If nothing has headroom left, it
 * says so plainly rather than offering a button that would fail again.
 */
export default function OutOfTokensDialog({ detail, onSwitch, onDismiss }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    function onEsc(e) {
      if (e.key === 'Escape') onDismiss()
    }
    document.addEventListener('keydown', onEsc)
    dialogRef.current?.focus()
    return () => document.removeEventListener('keydown', onEsc)
  }, [onDismiss])

  if (!detail) return null
  const alternatives = detail.alternatives || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/80 backdrop-blur-sm p-4">
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="oot-title"
        className="w-full max-w-md bg-ink-800 border border-ink-500 rounded-xl shadow-2xl focus:outline-none"
      >
        <div className="flex items-start gap-3 p-5 border-b border-ink-500/60">
          <div className="mt-0.5 flex-shrink-0 w-8 h-8 rounded-lg bg-accent-danger/15 flex items-center justify-center">
            <BatteryWarning size={16} className="text-accent-danger" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="oot-title" className="text-sm font-semibold text-cream-50">
              {detail.providerLabel || 'This agent'} is out of tokens
            </h2>
            <p className="text-xs text-cream-300 mt-1 leading-relaxed">
              You&apos;ve used your monthly allowance for {detail.providerLabel || 'this agent'}.
              {alternatives.length > 0
                ? ' Switch to another agent below and your message will be sent straight away.'
                : ''}
            </p>
          </div>
          <button
            onClick={onDismiss}
            className="text-ink-300 hover:text-cream-100 flex-shrink-0"
            aria-label="Dismiss"
          >
            <X size={16} />
          </button>
        </div>

        {alternatives.length > 0 ? (
          <div className="p-3">
            <p className="px-2 pb-2 text-[0.7rem] uppercase tracking-wide text-ink-300 font-medium">
              Agents with tokens left
            </p>
            {alternatives.map((alt) => (
              <button
                key={alt.model}
                onClick={() => onSwitch(alt.model)}
                className="w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg hover:bg-ink-700/70 transition-colors text-left group"
              >
                <div className="min-w-0">
                  <div className="text-xs text-cream-100 font-medium">{alt.label}</div>
                  <div className="text-[0.65rem] text-ink-300 tabular-nums mt-0.5">
                    {formatTokens(alt.tokens_remaining)} tokens left
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  className="text-ink-300 group-hover:text-gold-400 flex-shrink-0 transition-colors"
                />
              </button>
            ))}
          </div>
        ) : (
          <div className="p-5 text-xs text-cream-300 leading-relaxed">
            All of your agents have used their monthly allowance. Allowances reset at
            the start of next month — contact your administrator if you need more
            before then.
          </div>
        )}

        <div className="px-5 py-3 border-t border-ink-500/60 flex justify-end">
          <button
            onClick={onDismiss}
            className="px-3 py-1.5 text-xs text-cream-200 hover:text-cream-50 transition-colors"
          >
            Not now
          </button>
        </div>
      </div>
    </div>
  )
}
