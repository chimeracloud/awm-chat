import { useState, useRef, useEffect } from 'react'
import {
  Send, AlertCircle, Paperclip, X,
  FileText, Image as ImageIcon, Film, Loader2, CheckCircle2,
} from 'lucide-react'
import { uploadAttachment } from '../lib/api'

const MAX_ATTACHMENTS = 5

const FILE_ACCEPT = [
  '.pdf', '.docx', '.txt', '.md', '.csv',
  '.png', '.jpg', '.jpeg', '.webp', '.gif',
  '.mp4', '.mov', '.webm',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain', 'text/markdown', 'text/csv',
  'image/png', 'image/jpeg', 'image/webp', 'image/gif',
  'video/mp4', 'video/quicktime', 'video/webm',
].join(',')

function categoryFromType(ct) {
  if (!ct) return 'document'
  if (ct.startsWith('image/')) return 'image'
  if (ct.startsWith('video/')) return 'video'
  return 'document'
}

function CategoryIcon({ contentType, size = 14 }) {
  const c = categoryFromType(contentType)
  if (c === 'image') return <ImageIcon size={size} />
  if (c === 'video') return <Film size={size} />
  return <FileText size={size} />
}

export default function Composer({ onSend, disabled, usage }) {
  const [text, setText] = useState('')
  const [pending, setPending] = useState([])  // local upload state
  const taRef = useRef(null)
  const fileRef = useRef(null)

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 240) + 'px'
  }, [text])

  const anyBusy = pending.some(p => p.status === 'uploading' || p.status === 'processing')
  const overLimit = usage && usage.cap_tokens && usage.tokens_used >= usage.cap_tokens
  const readyAttachments = pending.filter(p => p.status === 'ready')
  const canSend = !disabled && !overLimit && !anyBusy &&
                  (text.trim().length > 0 || readyAttachments.length > 0)

  function pickFiles() {
    fileRef.current?.click()
  }

  function removeAttachment(localId) {
    setPending(p => p.filter(x => x.localId !== localId))
  }

  async function uploadOne(file) {
    const localId = `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setPending(p => [...p, {
      localId,
      filename: file.name,
      content_type: file.type,
      size: file.size,
      status: 'uploading',
      progress: 0,
    }])
    try {
      const att = await uploadAttachment(file, {
        onProgress: (pct) => {
          setPending(p => p.map(x =>
            x.localId === localId
              ? { ...x, progress: pct, status: pct >= 100 ? 'processing' : 'uploading' }
              : x
          ))
        },
      })
      setPending(p => p.map(x =>
        x.localId === localId
          ? { ...x, id: att.id, status: att.status || 'ready', error: att.error }
          : x
      ))
    } catch (e) {
      setPending(p => p.map(x =>
        x.localId === localId ? { ...x, status: 'error', error: e.message } : x
      ))
    }
  }

  function onFilesPicked(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (files.length === 0) return
    const slots = Math.max(0, MAX_ATTACHMENTS - pending.length)
    const toAdd = files.slice(0, slots)
    if (files.length > slots) {
      alert(`Limit is ${MAX_ATTACHMENTS} attachments per message; the rest were skipped.`)
    }
    for (const f of toAdd) {
      uploadOne(f)
    }
  }

  function submit() {
    if (!canSend) return
    const t = text.trim()
    const atts = readyAttachments.map(a => ({
      id: a.id,
      filename: a.filename,
      content_type: a.content_type,
      size: a.size,
      category: categoryFromType(a.content_type),
    }))
    setText('')
    setPending([])
    onSend(t, atts)
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-ink-500/60 bg-ink-800/40 backdrop-blur">
      <div className="max-w-3xl mx-auto px-6 py-4">
        {overLimit && (
          <div className="mb-3 flex items-center gap-2 px-3 py-2 bg-accent-danger/10 border border-accent-danger/30 rounded text-sm text-accent-danger">
            <AlertCircle size={14}/> Monthly token cap reached. Contact your administrator.
          </div>
        )}

        {pending.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {pending.map(att => {
              const isVideo = (att.content_type || '').startsWith('video/')
              return (
                <div
                  key={att.localId}
                  className={`flex items-center gap-2 px-2.5 py-1.5 bg-ink-700/60 border rounded-md text-xs max-w-[280px] ${
                    att.status === 'error'
                      ? 'border-accent-danger/40 text-accent-danger'
                      : 'border-ink-500/60 text-cream-200'
                  }`}
                >
                  <CategoryIcon contentType={att.content_type} />
                  <span className="truncate" title={att.filename}>{att.filename}</span>
                  {att.status === 'uploading' && (
                    <span className="text-cream-300 flex items-center gap-1">
                      <Loader2 size={11} className="animate-spin"/>
                      {att.progress != null ? `${att.progress}%` : ''}
                    </span>
                  )}
                  {att.status === 'processing' && (
                    <span className="text-cream-300 flex items-center gap-1">
                      <Loader2 size={11} className="animate-spin"/>
                      {isVideo ? 'transcribing' : 'processing'}
                    </span>
                  )}
                  {att.status === 'ready' && (
                    <CheckCircle2 size={12} className="text-accent-success"/>
                  )}
                  {att.status === 'error' && (
                    <span className="text-accent-danger" title={att.error || 'error'}>
                      error
                    </span>
                  )}
                  <button
                    onClick={() => removeAttachment(att.localId)}
                    className="ml-1 text-ink-300 hover:text-cream-100"
                    title="Remove"
                  >
                    <X size={12}/>
                  </button>
                </div>
              )
            })}
          </div>
        )}

        <div className={`flex items-end gap-2 bg-ink-700/60 border rounded-xl p-2.5 transition-colors ${
          disabled || overLimit ? 'border-ink-500/40 opacity-70' : 'border-ink-500 focus-within:border-gold-500/40'
        }`}>
          <button
            onClick={pickFiles}
            disabled={disabled || overLimit || pending.length >= MAX_ATTACHMENTS}
            className="flex-shrink-0 w-9 h-9 flex items-center justify-center text-cream-300 hover:text-cream-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title="Attach files"
          >
            <Paperclip size={16}/>
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept={FILE_ACCEPT}
            onChange={onFilesPicked}
            className="hidden"
          />
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
            disabled={!canSend}
            className="flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-gold-500 hover:bg-gold-400 text-ink-900 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title={anyBusy ? 'Waiting for attachments...' : 'Send'}
          >
            <Send size={15}/>
          </button>
        </div>

        <p className="text-[0.7rem] text-ink-300 text-center mt-2">
          Claude can make mistakes. Verify critical information.
        </p>
      </div>
    </div>
  )
}
