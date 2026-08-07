import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiGet, apiPost, apiPut, apiDelete, streamChat, AgentCapReachedError } from '../lib/api'
import Sidebar from '../components/Sidebar'
import MessageList from '../components/MessageList'
import Composer from '../components/Composer'
import PinnedPanel from '../components/PinnedPanel'
import TopBar from '../components/TopBar'
import OutOfTokensDialog from '../components/OutOfTokensDialog'

export default function ChatPage({ user, profile }) {
  const { conversationId } = useParams()
  const navigate = useNavigate()

  const [conversations, setConversations] = useState([])
  const [messages, setMessages] = useState([])
  const [pins, setPins] = useState([])
  const [usage, setUsage] = useState(null)
  const [agents, setAgents] = useState([])
  const [selectedModel, setSelectedModel] = useState(null)
  const [capDetail, setCapDetail] = useState(null)
  const [streaming, setStreaming] = useState(false)
  const [showPins, setShowPins] = useState(false)
  const streamBufferRef = useRef('')
  // Held so the out-of-tokens dialog can resend the exact message the user
  // wrote after they pick a different agent, rather than making them retype.
  const lastAttemptRef = useRef(null)

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

  // Agents carry both the model list for the switcher and the battery levels,
  // so this reloads after every turn to keep the batteries live.
  const loadAgents = useCallback(async () => {
    try {
      const data = await apiGet('/agents')
      setAgents(data.agents || [])
      setSelectedModel((current) => {
        if (current) return current
        const usable = (data.agents || []).filter(a => a.available)
        const savedIsUsable = usable.some(a => a.models.some(m => m.id === data.selected_model))
        if (savedIsUsable) return data.selected_model
        // Prefer an agent that still has tokens over one that's already spent.
        const withHeadroom = usable.find(a => !a.allowance.exhausted) || usable[0]
        return withHeadroom?.models[0]?.id ?? null
      })
    } catch (e) { console.error(e) }
  }, [])

  useEffect(() => {
    loadConversations(); loadPins(); loadUsage(); loadAgents()
  }, [loadConversations, loadPins, loadUsage, loadAgents])
  useEffect(() => { loadMessages(conversationId) }, [conversationId, loadMessages])

  async function selectModel(model) {
    setSelectedModel(model)
    // Remember the choice so it survives a reload. Not fatal if it fails —
    // the in-memory selection still applies to this session.
    try {
      await apiPut('/me/model', { model })
    } catch (e) { console.error('Could not save agent preference', e) }
  }

  async function sendMessage(text, attachments, modelOverride) {
    const atts = attachments || []
    if ((!text.trim() && atts.length === 0) || streaming) return

    const model = modelOverride || selectedModel
    lastAttemptRef.current = { text, attachments: atts }

    let activeId = conversationId
    // If no conversation, create one first
    if (!activeId) {
      const titleSource = text.trim() || (atts[0]?.filename ?? 'New conversation')
      const conv = await apiPost('/conversations', { title: titleSource.slice(0, 60) })
      activeId = conv.id
      await loadConversations()
      navigate(`/c/${activeId}`, { replace: true })
    }

    const userMsg = {
      id: `tmp-u-${Date.now()}`,
      role: 'user',
      content: text,
      attachments: atts,
      created_at: new Date().toISOString(),
    }
    const assistantMsg = {
      id: `tmp-a-${Date.now()}`, role: 'assistant', content: '',
      created_at: new Date().toISOString(), streaming: true, model,
    }
    setMessages((m) => [...m, userMsg, assistantMsg])
    setStreaming(true)
    streamBufferRef.current = ''

    try {
      await streamChat({
        conversationId: activeId,
        message: text,
        attachmentIds: atts.map(a => a.id).filter(Boolean),
        model,
        onMeta: (meta) => {
          // Label the bubble with the agent that actually served the turn.
          setMessages((m) => {
            const copy = [...m]
            const last = copy[copy.length - 1]
            if (last && last.streaming) {
              copy[copy.length - 1] = { ...last, model: meta.model, provider: meta.provider }
            }
            return copy
          })
        },
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
      // Refresh from server so we have canonical ids, usage and battery levels
      await loadMessages(activeId)
      await loadUsage()
      await loadAgents()
      await loadConversations()
    } catch (e) {
      // Out of tokens on this agent: drop the optimistic bubbles and offer a
      // switch instead of leaving an error in the transcript. The server
      // checks the cap before persisting anything, so nothing was written.
      if (e instanceof AgentCapReachedError) {
        setMessages((m) => m.slice(0, -2))
        setCapDetail(e)
        await loadAgents()
        return
      }
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

  /** Switch agent from the out-of-tokens dialog, then resend the message. */
  async function switchAgentAndRetry(model) {
    const attempt = lastAttemptRef.current
    setCapDetail(null)
    await selectModel(model)
    if (attempt) {
      await sendMessage(attempt.text, attempt.attachments, model)
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
            <Composer
              onSend={sendMessage}
              disabled={streaming}
              agents={agents}
              selectedModel={selectedModel}
              onSelectModel={selectModel}
            />
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

      {capDetail && (
        <OutOfTokensDialog
          detail={capDetail}
          onSwitch={switchAgentAndRetry}
          onDismiss={() => setCapDetail(null)}
        />
      )}
    </div>
  )
}
