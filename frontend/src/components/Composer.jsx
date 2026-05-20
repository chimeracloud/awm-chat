import { useState, useRef, useEffect } from 'react'
import { Send, AlertCircle } from 'lucide-react'

export default function Composer({ onSend, disabled, usage }) {
  const [text, setText] = useState('')
  const taRef = useRef(null)

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 240) + 'px'
  }, [text])

  function submit() {
    const t = text.trim()
    if (!t || disabled) return
    setText('')
    onSend(t)
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const overLimit = usage && usage.cap_tokens && usage.tokens_used >= usage.cap_tokens

  return (
    <div className="border-t border-ink-500/60 bg-ink-800/40 backdrop-blur">
      <div className="max-w-3xl mx-auto px-6 py-4">
        {overLimit && (
          <div className="mb-3 flex items-center gap-2 px-3 py-2 bg-accent-danger/10 border border-accent-danger/30 rounded text-sm text-accent-danger">
            <AlertCircle size={14}/> Monthly token cap reached. Contact your administrator.
          </div>
        )}

        <div className={`flex items-end gap-2 bg-ink-700/60 border rounded-xl p-2.5 transition-colors ${
          disabled || overLimit ? 'border-ink-500/40 opacity-70' : 'border-ink-500 focus-within:border-gold-500/40'
        }`}>
          <textarea
            ref={taRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message Claude..."
            rows={1}
            disabled={disabled || overLimit}
            className="flex-1 bg-transparent resize-none text-cream-50 placeholder-ink-300 focus:outline-none px-2 py-1.5 max-h-60 text-[15px]"
          />
          <button
            onClick={submit}
            disabled={!text.trim() || disabled || overLimit}
            className="flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-gold-500 hover:bg-gold-400 text-ink-900 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={15} />
          </button>
        </div>

        <p className="text-[0.7rem] text-ink-300 text-center mt-2">
          Claude can make mistakes. Verify critical information.
        </p>
      </div>
    </div>
  )
}
