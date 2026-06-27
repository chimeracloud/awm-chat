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
// ---- Attachments ----

/**
 * Upload one file. Three steps: backend issues a V4 signed URL, browser PUTs
 * the file directly to GCS, backend verifies + extracts text or transcribes
 * video. Returns the final attachment record (with id, status, etc).
 */
export async function uploadAttachment(file, { onProgress } = {}) {
  // 1. Init — backend issues a V4 signed PUT URL to GCS
  const init = await apiPost('/attachments/init', {
    filename: file.name,
    content_type: file.type || 'application/octet-stream',
    size: file.size,
  })
  // 2. PUT the file straight to GCS, bypassing Cloud Run's request-size cap
  await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', init.upload_url)
    for (const [k, v] of Object.entries(init.required_headers || {})) {
      xhr.setRequestHeader(k, v)
    }
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else reject(new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`))
    }
    xhr.onerror = () => reject(new Error('Network error during upload'))
    xhr.send(file)
  })
  // 3. Tell the backend to verify and run extraction/transcription.
  //    For video this blocks until Video Intelligence finishes (~30s+).
  return apiPost(`/attachments/${init.id}/complete`)
}

export async function getAttachmentDownloadUrl(attId) {
  const data = await apiGet(`/attachments/${attId}/download`)
  return data.url
}

// ---- Chat ----

export async function streamChat({ conversationId, message, attachmentIds, onChunk }) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      attachment_ids: attachmentIds || [],
    }),
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
      // Only the JSON.parse may legitimately fail on a partial/malformed
      // line — keep the try/catch scoped to it. A parsed `error` event is a
      // real failure that must propagate, not be swallowed as "malformed".
      let evt
      try {
        evt = JSON.parse(data)
      } catch {
        continue // ignore malformed lines
      }
      if (evt.type === 'chunk' && onChunk) {
        onChunk(evt.text)
      } else if (evt.type === 'done') {
        finalPayload = evt
      } else if (evt.type === 'error') {
        throw new Error(evt.message || 'Stream error')
      }
    }
  }
  return finalPayload
}
