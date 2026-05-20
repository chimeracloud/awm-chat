import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiGet, apiPost, apiDelete, streamChat } from '../lib/api'
import Sidebar from '../components/Sidebar'
import MessageList from '../components/MessageList'
import Composer from '../components/Composer'
import PinnedPanel from '../components/PinnedPanel'
import TopBar from '../components/TopBar'

export default function ChatPage({ user, profile }) {
  const { conversationId } = useParams()
  const navigate = useNavigate()

  const [conversations, setConversations] = useState([])
  const [messages, setMessages] = useState([])
  const [pins, setPins] = useState([])
  const [usage, setUsage] = useState(null)
  const [streaming, setStreaming] = useState(false)
  const [showPins, setShowPins] = useState(false)
  const streamBufferRef = useRef('')

  const loadConversations = useCallback(async () => {
    try {
      const list = await apiGet('/conversations')
      setConversations(list.items || [])
    } catch (e) { console.error(e) }
  }, [])

  const loadMessages = useCallback(async (id) => {
    if (!id) { setMessages([]); return }
    try {
      const data = await apiGet(`/conversations/${id}/messages`)
      setMessages(data.items || [])
    } catch (e) { console.error(e); setMessages([]) }
  }, [])

  const loadPins = useCallback(async () => {
    try {
      const data = await apiGet('/pins')
      setPins(data.items || [])
    } catch (e) { console.error(e) }
  }, [])

  const loadUsage = useCallback(async () => {
    try {
      const data = await apiGet('/usage/me')
      setUsage(data)
    } catch (e) { console.error(e) }
  }, [])

  useEffect(() => { loadConversations(); loadPins(); loadUsage() }, [loadConversations, loadPins, loadUsage])
  useEffect(() => { loadMessages(conversationId) }, [conversationId, loadMessages])

  async function sendMessage(text) {
    if (!text.trim() || streaming) return

    let activeId = conversationId
    // If no conversation, create one first
    if (!activeId) {
      const conv = await apiPost('/conversations', { title: text.slice(0, 60) })
      activeId = conv.id
      await loadConversations()
      navigate(`/c/${activeId}`, { replace: true })
    }

    const userMsg = { id: `tmp-u-${Date.now()}`, role: 'user', content: text, created_at: new Date().toISOString() }
    const assistantMsg = { id: `tmp-a-${Date.now()}`, role: 'assistant', content: '', created_at: new Date().toISOString(), streaming: true }
    setMessages((m) => [...m, userMsg, assistantMsg])
    setStreaming(true)
    streamBufferRef.current = ''

    try {
      await streamChat({
        conversationId: activeId,
        message: text,
        onChunk: (chunk) => {
          streamBufferRef.current += chunk
          setMessages((m) => {
            const copy = [...m]
            const last = copy[copy.length - 1]
            if (last && last.streaming) {
              copy[copy.length - 1] = { ...last, content: streamBufferRef.current }
            }
            return copy
          })
        },
      })
      // Refresh from server so we have canonical ids and usage
      await loadMessages(activeId)
      await loadUsage()
      await loadConversations()
    } catch (e) {
      setMessages((m) => {
        const copy = [...m]
        const last = copy[copy.length - 1]
        if (last && last.streaming) {
          copy[copy.length - 1] = { ...last, content: `Error: ${e.message}`, streaming: false, error: true }
        }
        return copy
      })
    } finally {
      setStreaming(false)
    }
  }

  async function newConversation() {
    navigate('/', { replace: true })
    setMessages([])
  }

  async function deleteConversation(id) {
    if (!confirm('Delete this conversation? This cannot be undone.')) return
    try {
      await apiDelete(`/conversations/${id}`)
      if (id === conversationId) navigate('/', { replace: true })
      await loadConversations()
    } catch (e) { console.error(e) }
  }

  async function addPin(content, label) {
    await apiPost('/pins', { content, label })
    await loadPins()
  }

  async function removePin(id) {
    await apiDelete(`/pins/${id}`)
    await loadPins()
  }

  return (
    <div className="h-screen flex bg-ink-900">
      <Sidebar
        conversations={conversations}
        activeId={conversationId}
        onNew={newConversation}
        onSelect={(id) => navigate(`/c/${id}`)}
        onDelete={deleteConversation}
        profile={profile}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          user={user}
          profile={profile}
          usage={usage}
          onTogglePins={() => setShowPins((s) => !s)}
          pinsActive={showPins}
        />

        <div className="flex-1 flex min-h-0">
          <div className="flex-1 flex flex-col min-w-0">
            <MessageList messages={messages} streaming={streaming} />
            <Composer onSend={sendMessage} disabled={streaming} usage={usage} />
          </div>

          {showPins && (
            <PinnedPanel
              pins={pins}
              onAdd={addPin}
              onRemove={removePin}
              onClose={() => setShowPins(false)}
            />
          )}
        </div>
      </div>
    </div>
  )
}
