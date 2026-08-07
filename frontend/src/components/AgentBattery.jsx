import { AlertTriangle } from 'lucide-react'

/**
 * Battery-style level indicator for one agent.
 *
 * Two layers, because no AI vendor publishes a remaining-credit balance
 * (checked for Anthropic, OpenAI and Google — all three expose spend, none
 * expose a balance):
 *
 *  1. The fill = this user's own monthly token allowance for the agent. Exact,
 *     live, and the number that actually gates them.
 *  2. The thin underbar = the organisation's month-to-date spend against a
 *     budget, read from the vendor's cost API. Best-effort and org-wide; it is
 *     simply omitted when no admin key or budget is configured.
 *
 * The battery drains as tokens are used, matching how a phone battery reads:
 * full = plenty left.
 */

function levelColour(remainingFraction, exhausted) {
  if (exhausted) return { bar: 'bg-accent-danger', text: 'text-accent-danger' }
  if (remainingFraction <= 0.1) return { bar: 'bg-accent-danger', text: 'text-accent-danger' }
  if (remainingFraction <= 0.25) return { bar: 'bg-gold-500', text: 'text-gold-400' }
  return { bar: 'bg-accent-success', text: 'text-cream-200' }
}

function formatTokens(n) {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

export default function AgentBattery({ agent, size = 'md', showLabel = true }) {
  const { allowance, org_spend: orgSpend } = agent
  const capped = allowance.cap_tokens > 0
  const usedFraction = capped ? Math.min(1, allowance.fraction_used ?? 0) : 0
  const remainingFraction = capped ? 1 - usedFraction : 1
  const colour = levelColour(remainingFraction, allowance.exhausted)

  const compact = size === 'sm'
  const width = compact ? 'w-10' : 'w-16'
  const height = compact ? 'h-3' : 'h-4'

  const pct = capped ? Math.round(remainingFraction * 100) : null
  const title = capped
    ? `${formatTokens(allowance.tokens_remaining)} of ${formatTokens(allowance.cap_tokens)} tokens left this month`
    : 'No monthly limit set'

  return (
    <div className="flex items-center gap-2" title={title}>
      {/* Battery shell + fill */}
      <div className="flex items-center flex-shrink-0" aria-hidden="true">
        <div
          className={`${width} ${height} relative border border-ink-400 rounded-[3px] bg-ink-800/60 overflow-hidden`}
        >
          <div
            className={`absolute inset-y-0 left-0 ${colour.bar} transition-[width] duration-500`}
            style={{ width: `${capped ? remainingFraction * 100 : 100}%` }}
          />
          {/* Org spend underbar — only when the vendor cost API is wired up */}
          {orgSpend?.available && (
            <div className="absolute inset-x-0 bottom-0 h-[3px] bg-ink-900/70">
              <div
                className="h-full bg-gold-400/80"
                style={{ width: `${Math.min(100, (orgSpend.fraction_used ?? 0) * 100)}%` }}
              />
            </div>
          )}
        </div>
        {/* Battery nub */}
        <div className={`${compact ? 'h-1.5' : 'h-2'} w-[2px] bg-ink-400 rounded-r-[1px]`} />
      </div>

      {showLabel && (
        <div className="min-w-0">
          <div className={`text-xs font-medium ${colour.text} flex items-center gap-1`}>
            {allowance.exhausted && <AlertTriangle size={11} />}
            {allowance.exhausted ? 'Empty' : capped ? `${pct}%` : 'Unlimited'}
          </div>
          {!compact && capped && (
            <div className="text-[0.65rem] text-ink-300 tabular-nums">
              {formatTokens(allowance.tokens_remaining)} left
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Explains what the two layers mean — used in the switcher footer. */
export function BatteryLegend({ anySpendAvailable }) {
  return (
    <div className="px-3 py-2 border-t border-ink-500/60 text-[0.65rem] text-ink-300 leading-relaxed">
      <div className="flex items-center gap-1.5">
        <span className="inline-block w-3 h-2 rounded-[2px] bg-accent-success" />
        <span>Your remaining monthly tokens for that agent.</span>
      </div>
      {anySpendAvailable && (
        <div className="flex items-center gap-1.5 mt-1">
          <span className="inline-block w-3 h-[3px] rounded-[1px] bg-gold-400/80" />
          <span>Company spend vs budget (all users). Updates every few minutes.</span>
        </div>
      )}
      <p className="mt-1.5 text-ink-400">
        AI providers don&apos;t publish account credit balances, so these show
        allowance and spend rather than credits remaining.
      </p>
    </div>
  )
}
