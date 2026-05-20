import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Logo from './Logo'

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
            Ask anything related to your work. Pin context that should be remembered across this conversation
            on the right hand panel.
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
        <div className={`prose-awm text-[15px] ${
          isUser
            ? 'bg-ink-700/70 border border-ink-500/50 rounded-2xl rounded-tr-sm px-4 py-3 inline-block'
            : 'px-1'
        }`}>
          {message.streaming && !message.content ? (
            <div className="py-1">
              <span className="typing-dot"/><span className="typing-dot"/><span className="typing-dot"/>
            </div>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || ''}</ReactMarkdown>
          )}
        </div>
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
