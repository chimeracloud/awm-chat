import { getIdToken } from './firebase'

const API_BASE = import.meta.env.VITE_API_BASE || 'https://awm-chat-api.ascotwm.com'

async function authHeaders() {
  const token = await getIdToken()
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

export async function apiGet(path) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}${path}`, { headers })
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

export async function apiPost(path, body) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`)
  return res.json()
}

export async function apiPut(path, body) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`PUT ${path} failed: ${res.status}`)
  return res.json()
}

export async function apiDelete(path) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE', headers })
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`)
  return res.ok
}

/**
 * Stream a chat response. Yields incremental text chunks via onChunk.
 * Returns the full assembled response with usage info on completion.
 */
export async function streamChat({ conversationId, message, onChunk }) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ conversation_id: conversationId, message }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Chat failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalPayload = null

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE-style line parsing
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6).trim()
      if (!data) continue
      try {
        const evt = JSON.parse(data)
        if (evt.type === 'chunk' && onChunk) {
          onChunk(evt.text)
        } else if (evt.type === 'done') {
          finalPayload = evt
        } else if (evt.type === 'error') {
          throw new Error(evt.message || 'Stream error')
        }
      } catch (e) {
        // ignore malformed lines
      }
    }
  }
  return finalPayload
}
