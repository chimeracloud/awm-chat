import { useEffect, useState } from 'react'
import {
  KeyRound, Check, X, Loader2, Eye, EyeOff, AlertTriangle, RefreshCw, Trash2,
} from 'lucide-react'
import { apiGet, apiPut, apiPost, apiDelete } from '../lib/api'

/**
 * Admin panel for vendor API keys and per-agent budgets.
 *
 * Keys are written straight through to Google Secret Manager — they are never
 * stored in Firestore and no endpoint here ever returns a key value, only
 * whether one is set and its last four characters. That keeps rotation a
 * one-field job in this page while leaving the secret itself in the store
 * built for it (versioning, IAM, audit logging).
 *
 * Every key is checked against the vendor before it saves, so a typo surfaces
 * here rather than as a broken agent for whoever chats next.
 */

function SecretRow({ secret, onSaved }) {
  const [value, setValue] = useState('')
  const [reveal, setReveal] = useState(false)
  const [busy, setBusy] = useState(null)   // 'save' | 'test' | 'verify' | 'clear'
  const [result, setResult] = useState(null)

  async function save() {
    if (!value.trim()) return
    setBusy('save'); setResult(null)
    try {
      await apiPut(`/admin/secrets/${secret.name}`, { value: value.trim() })
      setValue('')
      setResult({ ok: true, message: 'Saved and verified.' })
      onSaved()
    } catch (e) {
      setResult({ ok: false, message: e.message })
    } finally { setBusy(null) }
  }

  async function test() {
    if (!value.trim()) return
    setBusy('test'); setResult(null)
    try {
      const r = await apiPost(`/admin/secrets/${secret.name}/test`, { value: value.trim() })
      setResult(r)
    } catch (e) {
      setResult({ ok: false, message: e.message })
    } finally { setBusy(null) }
  }

  async function verifyStored() {
    setBusy('verify'); setResult(null)
    try {
      const r = await apiPost(`/admin/secrets/${secret.name}/verify`, {})
      setResult(r)
    } catch (e) {
      setResult({ ok: false, message: e.message })
    } finally { setBusy(null) }
  }

  async function clear() {
    if (!confirm(
      `Remove the ${secret.label}?\n\n` +
      (secret.required
        ? 'This will take that agent out of the switcher for everyone.'
        : 'The spend marker for that agent will disappear.') +
      '\n\nThe old version is disabled, not destroyed — it can be restored from the GCP console.'
    )) return
    setBusy('clear'); setResult(null)
    try {
      await apiDelete(`/admin/secrets/${secret.name}`)
      onSaved()
    } catch (e) {
      setResult({ ok: false, message: e.message })
    } finally { setBusy(null) }
  }

  return (
    <div className="py-3 border-b border-ink-500/40 last:border-b-0">
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-medium text-cream-100">{secret.label}</span>
          {secret.configured ? (
            <span className="flex items-center gap-1 text-[0.65rem] text-accent-success">
              <Check size={11} /> set {secret.masked}
            </span>
          ) : (
            <span
              className={`flex items-center gap-1 text-[0.65rem] ${
                secret.required ? 'text-accent-danger' : 'text-ink-400'
              }`}
            >
              <X size={11} /> {secret.required ? 'required — not set' : 'not set'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {secret.configured && (
            <>
              <button
                onClick={verifyStored}
                disabled={busy !== null}
                title="Check the key currently in use still works"
                className="text-[0.65rem] text-ink-300 hover:text-cream-100 flex items-center gap-1 disabled:opacity-40"
              >
                {busy === 'verify'
                  ? <Loader2 size={11} className="animate-spin" />
                  : <RefreshCw size={11} />}
                check
              </button>
              <button
                onClick={clear}
                disabled={busy !== null}
                title="Remove this key"
                className="text-[0.65rem] text-ink-300 hover:text-accent-danger flex items-center gap-1 disabled:opacity-40"
              >
                <Trash2 size={11} /> remove
              </button>
            </>
          )}
        </div>
      </div>

      {secret.env_override && (
        <div className="mb-2 flex items-start gap-1.5 px-2 py-1.5 rounded bg-gold-500/10 border border-gold-500/30 text-[0.65rem] text-gold-300">
          <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" />
          <span>
            A Cloud Run environment variable named <code>{secret.name}</code> is set and
            takes precedence — saving here will have no effect until it is removed.
          </span>
        </div>
      )}

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            type={reveal ? 'text' : 'password'}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={secret.configured ? 'Paste a new key to rotate…' : secret.hint}
            autoComplete="off"
            spellCheck={false}
            className="w-full bg-ink-900/60 border border-ink-500 rounded px-2.5 py-1.5 pr-8 text-xs text-cream-100 placeholder-ink-400 font-mono focus:outline-none focus:border-gold-500/40"
          />
          <button
            type="button"
            onClick={() => setReveal((r) => !r)}
            tabIndex={-1}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-300 hover:text-cream-100"
            aria-label={reveal ? 'Hide' : 'Show'}
          >
            {reveal ? <EyeOff size={12} /> : <Eye size={12} />}
          </button>
        </div>
        <button
          onClick={test}
          disabled={!value.trim() || busy !== null}
          className="px-2.5 py-1.5 text-[0.7rem] rounded border border-ink-500 text-cream-200 hover:border-gold-500/40 disabled:opacity-40 transition-colors"
        >
          {busy === 'test' ? <Loader2 size={11} className="animate-spin" /> : 'Test'}
        </button>
        <button
          onClick={save}
          disabled={!value.trim() || busy !== null}
          className="px-2.5 py-1.5 text-[0.7rem] rounded bg-gold-500 hover:bg-gold-400 text-ink-900 font-medium disabled:opacity-40 transition-colors"
        >
          {busy === 'save' ? <Loader2 size={11} className="animate-spin" /> : 'Save'}
        </button>
      </div>

      {result && (
        <div
          className={`mt-1.5 text-[0.65rem] flex items-start gap-1.5 ${
            result.ok ? 'text-accent-success' : 'text-accent-danger'
          }`}
        >
          {result.ok ? <Check size={11} className="mt-0.5" /> : <X size={11} className="mt-0.5" />}
          <span className="break-words">{result.message}</span>
        </div>
      )}

      {!secret.configured && !value && (
        <p className="mt-1 text-[0.65rem] text-ink-400">{secret.hint}</p>
      )}
    </div>
  )
}

export default function AgentKeysPanel({ settings, onSettingsSaved }) {
  const [secrets, setSecrets] = useState([])
  const [loading, setLoading] = useState(true)
  const [budgets, setBudgets] = useState({})
  const [billingTable, setBillingTable] = useState('')
  const [savingBudgets, setSavingBudgets] = useState(false)
  const [budgetResult, setBudgetResult] = useState(null)

  async function load() {
    setLoading(true)
    try {
      const d = await apiGet('/admin/secrets')
      setSecrets(d.secrets || [])
    } catch (e) { console.error(e) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    setBudgets(settings?.provider_budgets_usd || {})
    setBillingTable(settings?.gcp_billing_export_table || '')
  }, [settings])

  async function saveBudgets() {
    setSavingBudgets(true); setBudgetResult(null)
    try {
      const numeric = Object.fromEntries(
        Object.entries(budgets).map(([k, v]) => [k, Number(v) || 0])
      )
      await apiPut('/admin/settings', {
        provider_budgets_usd: numeric,
        gcp_billing_export_table: billingTable,
      })
      setBudgetResult({ ok: true, message: 'Saved.' })
      onSettingsSaved?.()
    } catch (e) {
      setBudgetResult({ ok: false, message: e.message })
    } finally { setSavingBudgets(false) }
  }

  const inference = secrets.filter((s) => s.kind === 'inference')
  const spend = secrets.filter((s) => s.kind === 'spend')

  return (
    <div className="space-y-6">
      <section className="bg-ink-800/40 border border-ink-500/60 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-1">
          <KeyRound size={14} className="text-gold-400" />
          <h3 className="text-sm font-semibold text-cream-50">Agent API keys</h3>
        </div>
        <p className="text-xs text-cream-300 mb-3 leading-relaxed">
          One key per agent. Each is checked against the vendor before it saves, and
          stored in Google Secret Manager — never in the app database. Keys are
          write-only here: you can replace one, but never read it back.
        </p>

        {loading ? (
          <div className="py-6 text-center text-xs text-ink-300">
            <Loader2 size={14} className="animate-spin inline mr-2" /> Loading…
          </div>
        ) : (
          <>
            <div>{inference.map((s) => (
              <SecretRow key={s.name} secret={s} onSaved={load} />
            ))}</div>

            <div className="mt-5 pt-4 border-t border-ink-500/60">
              <h4 className="text-xs font-semibold text-cream-100 mb-1">
                Spend-reporting keys <span className="text-ink-400 font-normal">— optional</span>
              </h4>
              <p className="text-[0.7rem] text-cream-300 mb-2 leading-relaxed">
                Separate admin credentials, used only to read month-to-date spend for the
                marker under each battery. Chat works fine without them.
              </p>
              {spend.map((s) => (
                <SecretRow key={s.name} secret={s} onSaved={load} />
              ))}
            </div>
          </>
        )}
      </section>

      <section className="bg-ink-800/40 border border-ink-500/60 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-cream-50 mb-1">Monthly budgets</h3>
        <p className="text-xs text-cream-300 mb-3 leading-relaxed">
          What each agent&apos;s spend marker is measured against. Set 0 to hide the marker.
          These are not spend limits — set hard caps in each vendor&apos;s own console.
        </p>

        <div className="space-y-2">
          {['anthropic', 'openai', 'google'].map((p) => (
            <div key={p} className="flex items-center gap-3">
              <label className="text-xs text-cream-200 w-24 capitalize">
                {p === 'google' ? 'Gemini' : p === 'anthropic' ? 'Claude' : 'OpenAI'}
              </label>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-ink-300">$</span>
                <input
                  type="number"
                  min="0"
                  step="10"
                  value={budgets[p] ?? 0}
                  onChange={(e) => setBudgets((b) => ({ ...b, [p]: e.target.value }))}
                  className="w-28 bg-ink-900/60 border border-ink-500 rounded px-2 py-1 text-xs text-cream-100 font-mono focus:outline-none focus:border-gold-500/40"
                />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4">
          <label className="block text-xs text-cream-200 mb-1">
            GCP billing export table
            <span className="text-ink-400 font-normal"> — needed for the Gemini marker only</span>
          </label>
          <input
            type="text"
            value={billingTable}
            onChange={(e) => setBillingTable(e.target.value)}
            placeholder="chiops.billing.gcp_billing_export_v1_XXXXXX"
            className="w-full bg-ink-900/60 border border-ink-500 rounded px-2.5 py-1.5 text-xs text-cream-100 placeholder-ink-400 font-mono focus:outline-none focus:border-gold-500/40"
          />
          <p className="mt-1 text-[0.65rem] text-ink-400">
            Google publishes no cost API for Gemini — spend is only readable from the
            BigQuery billing export.
          </p>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={saveBudgets}
            disabled={savingBudgets}
            className="px-3 py-1.5 text-xs rounded bg-gold-500 hover:bg-gold-400 text-ink-900 font-medium disabled:opacity-40 transition-colors"
          >
            {savingBudgets ? 'Saving…' : 'Save budgets'}
          </button>
          {budgetResult && (
            <span
              className={`text-[0.7rem] ${
                budgetResult.ok ? 'text-accent-success' : 'text-accent-danger'
              }`}
            >
              {budgetResult.message}
            </span>
          )}
        </div>
      </section>
    </div>
  )
}
