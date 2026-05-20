import { useState, useMemo } from 'react'
import { Plus, Search, MoreHorizontal, Trash2 } from 'lucide-react'
import Logo from './Logo'

export default function Sidebar({ conversations, activeId, onNew, onSelect, onDelete, profile }) {
  const [query, setQuery] = useState('')
  const [openMenu, setOpenMenu] = useState(null)

  const filtered = useMemo(() => {
    if (!query.trim()) return conversations
    const q = query.toLowerCase()
    return conversations.filter((c) => (c.title || '').toLowerCase().includes(q))
  }, [conversations, query])

  // Group by recency
  const groups = useMemo(() => {
    const now = Date.now()
    const day = 24 * 3600 * 1000
    const buckets = { today: [], week: [], month: [], older: [] }
    for (const c of filtered) {
      const age = now - new Date(c.updated_at || c.created_at).getTime()
      if (age < day) buckets.today.push(c)
      else if (age < 7 * day) buckets.week.push(c)
      else if (age < 30 * day) buckets.month.push(c)
      else buckets.older.push(c)
    }
    return buckets
  }, [filtered])

  return (
    <aside className="w-72 flex-shrink-0 bg-ink-800/60 border-r border-ink-500/60 flex flex-col">
      <div className="px-5 py-5 border-b border-ink-500/60">
        <Logo size="md" />
      </div>

      <div className="px-3 pt-4 pb-2">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 px-3 py-2.5 bg-ink-700 hover:bg-ink-600 border border-ink-500 rounded-md text-sm font-medium text-cream-100 transition-colors"
        >
          <Plus size={16} strokeWidth={2} />
          New conversation
        </button>

        <div className="mt-3 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-300" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search"
            className="w-full pl-9 pr-3 py-2 bg-ink-900/50 border border-ink-500/60 rounded-md text-sm text-cream-100 placeholder-ink-300 focus:outline-none focus:border-gold-500/50"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {Object.entries(groups).map(([key, items]) =>
          items.length > 0 && (
            <div key={key} className="mt-3">
              <div className="px-3 mb-1 text-[0.65rem] uppercase tracking-[0.15em] text-ink-300">
                {key === 'today' ? 'Today' : key === 'week' ? 'This week' : key === 'month' ? 'This month' : 'Older'}
              </div>
              {items.map((c) => (
                <div key={c.id} className="relative group">
                  <button
                    onClick={() => onSelect(c.id)}
                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors truncate ${
                      activeId === c.id
                        ? 'bg-ink-700 text-cream-50'
                        : 'text-cream-200 hover:bg-ink-700/50 hover:text-cream-100'
                    }`}
                  >
                    {c.title || 'Untitled'}
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setOpenMenu(openMenu === c.id ? null : c.id) }}
                    className="absolute right-1 top-1/2 -translate-y-1/2 p-1 opacity-0 group-hover:opacity-100 hover:bg-ink-600 rounded transition-opacity"
                  >
                    <MoreHorizontal size={14} className="text-cream-300" />
                  </button>
                  {openMenu === c.id && (
                    <div className="absolute right-2 top-9 z-10 bg-ink-700 border border-ink-500 rounded-md shadow-xl py-1 min-w-[140px]">
                      <button
                        onClick={() => { onDelete(c.id); setOpenMenu(null) }}
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-accent-danger hover:bg-ink-600"
                      >
                        <Trash2 size={13} /> Delete
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        )}
        {filtered.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-ink-300">
            {query ? 'No conversations match.' : 'No conversations yet.'}
          </div>
        )}
      </div>

      <div className="border-t border-ink-500/60 px-4 py-3">
        <div className="flex items-center gap-3">
          {profile?.photo_url ? (
            <img src={profile.photo_url} alt="" className="w-7 h-7 rounded-full"/>
          ) : (
            <div className="w-7 h-7 rounded-full bg-gold-500/20 flex items-center justify-center text-gold-500 text-xs font-medium">
              {(profile?.display_name || profile?.email || '?').charAt(0).toUpperCase()}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-xs text-cream-100 truncate">{profile?.display_name || profile?.email}</div>
            {profile?.role === 'admin' && (
              <a href="/admin" className="text-[0.65rem] text-gold-500 uppercase tracking-[0.15em]">Admin</a>
            )}
          </div>
        </div>
      </div>
    </aside>
  )
}
