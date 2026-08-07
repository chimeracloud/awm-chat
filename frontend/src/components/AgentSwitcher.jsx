import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check, Ban, Sparkles } from 'lucide-react'
import AgentBattery, { BatteryLegend } from './AgentBattery'

/**
 * In-chat agent picker.
 *
 * Sits directly above the composer so switching agent is part of writing a
 * message rather than a settings trip. Each agent shows its battery inline, so
 * the choice and the remaining allowance are read together — which is what
 * makes the out-of-tokens switch obvious before it happens rather than after.
 */
export default function AgentSwitcher({ agents, selectedModel, onSelect, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    function onEsc(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  if (!agents || agents.length === 0) return null

  const selected = agents
    .flatMap((a) => a.models.map((m) => ({ ...m, agent: a })))
    .find((m) => m.id === selectedModel)

  const activeAgent = selected?.agent
  const anySpend = agents.some((a) => a.org_spend?.available)

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-ink-500/70 bg-ink-700/50 hover:border-gold-500/40 hover:bg-ink-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-left"
      >
        <Sparkles size={13} className="text-gold-400 flex-shrink-0" />
        <span className="text-xs text-cream-100 font-medium truncate max-w-[13rem]">
          {selected ? selected.label : 'Choose an agent'}
        </span>
        {activeAgent && <AgentBattery agent={activeAgent} size="sm" showLabel={false} />}
        <ChevronDown
          size={13}
          className={`text-ink-300 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute bottom-full left-0 mb-2 w-[26rem] max-w-[calc(100vw-3rem)] max-h-[28rem] overflow-y-auto bg-ink-800 border border-ink-500 rounded-xl shadow-2xl z-30"
        >
          <div className="px-3 py-2 border-b border-ink-500/60">
            <p className="text-[0.7rem] uppercase tracking-wide text-ink-300 font-medium">
              Switch agent
            </p>
            <p className="text-[0.65rem] text-ink-400 mt-0.5">
              All agents read the same conversation — you can switch mid-thread.
            </p>
          </div>

          {agents.map((agent) => (
            <div key={agent.provider} className="border-b border-ink-500/40 last:border-b-0">
              <div className="flex items-center justify-between gap-3 px-3 pt-2.5 pb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs font-semibold text-cream-100">{agent.label}</span>
                  {!agent.available && (
                    <span
                      className="flex items-center gap-1 text-[0.65rem] text-ink-400"
                      title={agent.unavailable_reason || 'Unavailable'}
                    >
                      <Ban size={10} /> unavailable
                    </span>
                  )}
                </div>
                {agent.available && <AgentBattery agent={agent} />}
              </div>

              {agent.available && agent.org_spend?.available && (
                <p className="px-3 pb-1.5 text-[0.65rem] text-ink-400 tabular-nums">
                  Company spend ${agent.org_spend.spend_usd?.toFixed(2)} of $
                  {agent.org_spend.budget_usd?.toFixed(2)} this month
                </p>
              )}

              <div className="pb-1.5">
                {agent.models.map((m) => {
                  const isSelected = m.id === selectedModel
                  const blocked = !agent.available || agent.allowance.exhausted
                  return (
                    <button
                      key={m.id}
                      role="option"
                      aria-selected={isSelected}
                      disabled={blocked}
                      onClick={() => {
                        onSelect(m.id)
                        setOpen(false)
                      }}
                      className={`w-full text-left px-3 py-2 flex items-start gap-2 transition-colors ${
                        blocked
                          ? 'opacity-40 cursor-not-allowed'
                          : 'hover:bg-ink-700/70 cursor-pointer'
                      } ${isSelected ? 'bg-ink-700/50' : ''}`}
                    >
                      <span className="w-4 flex-shrink-0 pt-0.5">
                        {isSelected && <Check size={13} className="text-gold-400" />}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-xs text-cream-100">{m.label}</span>
                        {m.blurb && (
                          <span className="block text-[0.65rem] text-ink-300 mt-0.5">
                            {m.blurb}
                          </span>
                        )}
                        {agent.allowance.exhausted && (
                          <span className="block text-[0.65rem] text-accent-danger mt-0.5">
                            Monthly allowance used up
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}

          <BatteryLegend anySpendAvailable={anySpend} />
        </div>
      )}
    </div>
  )
}
