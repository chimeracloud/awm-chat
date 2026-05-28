import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { FileText } from 'lucide-react'
import Logo from './Logo'
import { getAttachmentDownloadUrl } from '../lib/api'

export default function MessageList({ messages, streaming }) {
  const bottomRef = useRef(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto flex items-center justify-center">
        <div className="text-center max-w-md px-6 animate-fade-in">
          <div className="inline-block mb-6">
            <Logo size="lg" />
          </div>
          <h1 className="font-display text-3xl text-cream-50 tracking-tightest mb-3">
            How can I help today?
          </h1>
          <p className="text-sm text-cream-300 leading-relaxed">
            Ask anything related to your work. Attach a document, image or
            video for Claude to use. Pin context that should be remembered
            across this conversation on the right hand panel.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {messages.map((m, idx) => (
          <Message key={m.id || idx} message={m} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function Message({ message }) {
  const isUser = message.role === 'user'
  const atts = message.attachments || []
  const hasText = !!(message.content && message.content.length > 0)
  const showStreamDots = message.streaming && !hasText
  return (
    <div className={`flex gap-4 animate-slide-up ${isUser ? 'justify-end' : ''}`}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-md bg-gold-500/15 border border-gold-500/30 flex items-center justify-center mt-0.5">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 11 L7 3 L11 11 M4.5 8 L9.5 8" stroke="#C5A572" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      )}

      <div className={`max-w-[88%] ${isUser ? 'order-first' : ''}`}>
        {atts.length > 0 && (
          <div className={`flex flex-wrap gap-2 mb-2 ${isUser ? 'justify-end' : ''}`}>
            {atts.map((a, i) => <AttachmentChip key={a.id || i} att={a}/>)}
          </div>
        )}
        {(hasText || showStreamDots) && (
          <div className={`prose-awm text-[15px] ${
            isUser
              ? 'bg-ink-700/70 border border-ink-500/50 rounded-2xl rounded-tr-sm px-4 py-3 inline-block'
              : 'px-1'
          }`}>
            {showStreamDots ? (
              <div className="py-1">
                <span className="typing-dot"/><span className="typing-dot"/><span className="typing-dot"/>
              </div>
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || ''}</ReactMarkdown>
            )}
          </div>
        )}
        {message.error && (
          <div className="text-xs text-accent-danger mt-1">A problem occurred while sending.</div>
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-md bg-ink-600 border border-ink-500 mt-0.5"/>
      )}
    </div>
  )
}

function categoryOf(att) {
  if (att.category) return att.category
  const ct = att.content_type || ''
  if (ct.startsWith('image/')) return 'image'
  if (ct.startsWith('video/')) return 'video'
  return 'document'
}

function formatBytes(n) {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function AttachmentChip({ att }) {
  const [url, setUrl] = useState(null)
  const [error, setError] = useState(null)
  const category = categoryOf(att)

  useEffect(() => {
    if (!att.id) return
    let alive = true
    getAttachmentDownloadUrl(att.id)
      .then((u) => { if (alive) setUrl(u) })
      .catch((e) => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [att.id])

  if (error) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-1.5 bg-ink-700/40 border border-accent-danger/30 rounded-md text-xs text-accent-danger">
        <span className="truncate max-w-[200px]">{att.filename}</span>
        <span className="text-[0.65rem]">(can't load)</span>
      </div>
    )
  }

  if (category === 'image') {
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer" className="block">
        <img
          src={url}
          alt={att.filename}
          className="max-w-[240px] max-h-[240px] rounded-md border border-ink-500/60 object-cover"
        />
      </a>
    ) : (
      <div className="w-[200px] h-[140px] bg-ink-700/60 border border-ink-500/60 rounded-md flex items-center justify-center text-xs text-ink-300">
        Loading…
      </div>
    )
  }

  if (category === 'video') {
    return url ? (
      <video
        controls
        preload="metadata"
        className="max-w-[320px] rounded-md border border-ink-500/60"
      >
        <source src={url} type={att.content_type}/>
        Your browser does not support video playback.
      </video>
    ) : (
      <div className="w-[280px] h-[160px] bg-ink-700/60 border border-ink-500/60 rounded-md flex items-center justify-center text-xs text-ink-300">
        Loading…
      </div>
    )
  }

  // Document / PDF / other
  return (
    <a
      href={url || '#'}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => { if (!url) e.preventDefault() }}
      className="flex items-center gap-3 px-3 py-2 bg-ink-700/40 border border-ink-500/60 rounded-md hover:border-gold-500/40 transition-colors max-w-[280px]"
    >
      <FileText size={16} className="text-cream-300 flex-shrink-0"/>
      <div className="min-w-0 flex-1">
        <div className="text-xs text-cream-100 truncate">{att.filename}</div>
        {att.size != null && (
          <div className="text-[0.65rem] text-ink-300">{formatBytes(att.size)}</div>
        )}
      </div>
    </a>
  )
}
