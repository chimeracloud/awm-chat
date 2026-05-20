import { useState } from 'react'
import { Pin, X, Plus } from 'lucide-react'

export default function PinnedPanel({ pins, onAdd, onRemove, onClose }) {
  const [label, setLabel] = useState('')
  const [content, setContent] = useState('')
  const [adding, setAdding] = useState(false)

  async function submit() {
    if (!content.trim()) return
    await onAdd(content.trim(), label.trim() || null)
    setLabel('')
    setContent('')
    setAdding(false)
  }

  return (
    <aside className="w-80 flex-shrink-0 border-l border-ink-500/60 bg-ink-800/40 flex flex-col animate-slide-up">
      <div className="px-5 py-4 border-b border-ink-500/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Pin size={14} className="text-gold-500"/>
          <span className="font-display text-lg text-cream-50 tracking-tight">Pinned context</span>
        </div>
        <button onClick={onClose} className="text-ink-300 hover:text-cream-100"><X size={16}/></button>
      </div>

      <div className="px-5 py-3 text-xs text-cream-300 leading-relaxed border-b border-ink-500/40">
        Pinned items are always included in your conversations with Claude. Use this for your role,
        ongoing projects, style preferences, or recurring context.
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {pins.length === 0 && !adding && (
          <div className="text-center py-8 text-xs text-ink-300">No pinned items yet.</div>
        )}

        {pins.map((p) => (
          <div key={p.id} className="group bg-ink-700/40 border border-ink-500/40 rounded-md p-3 hover:border-gold-500/30 transition-colors">
            <div className="flex items-start justify-between gap-2 mb-1">
              <span className="text-[0.65rem] uppercase tracking-[0.15em] text-gold-500/80 font-medium">
                {p.label || 'Context'}
              </span>
              <button
                onClick={() => onRemove(p.id)}
                className="opacity-0 group-hover:opacity-100 text-ink-300 hover:text-accent-danger transition-opacity"
              >
                <X size={12}/>
              </button>
            </div>
            <p className="text-xs text-cream-200 leading-relaxed whitespace-pre-wrap">{p.content}</p>
          </div>
        ))}

        {adding ? (
          <div className="bg-ink-700/60 border border-gold-500/30 rounded-md p-3 space-y-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Label (optional)"
              className="w-full px-2 py-1.5 bg-ink-900/50 border border-ink-500/60 rounded text-xs text-cream-100 placeholder-ink-300 focus:outline-none focus:border-gold-500/50"
            />
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="What should Claude remember?"
              rows={4}
              className="w-full px-2 py-1.5 bg-ink-900/50 border border-ink-500/60 rounded text-xs text-cream-100 placeholder-ink-300 focus:outline-none focus:border-gold-500/50 resize-none"
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setAdding(false); setLabel(''); setContent('') }} className="text-xs text-ink-300 hover:text-cream-100 px-2 py-1">
                Cancel
              </button>
              <button onClick={submit} disabled={!content.trim()} className="text-xs bg-gold-500 hover:bg-gold-400 text-ink-900 px-3 py-1 rounded font-medium disabled:opacity-30">
                Pin
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="w-full flex items-center justify-center gap-2 py-2 border border-dashed border-ink-500/60 hover:border-gold-500/50 hover:text-gold-500 rounded-md text-xs text-cream-300 transition-colors"
          >
            <Plus size={12}/> Add pinned item
          </button>
        )}
      </div>
    </aside>
  )
}
