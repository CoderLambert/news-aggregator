// SSE / streaming-fetch utilities.
//
// streamLines(url, init): async-generator yielding parsed "data: ..." lines.
//   Backend uses two variants:
//     1) NDJSON-style SSE — each line "data: {json}\n"  (translate stream)
//     2) Plain text token stream — raw chunks               (chat stream)
//   The two helpers below cover both.

import { LANG_KEY } from '../constants'

/**
 * Append ?lang= to the URL based on user preference.
 */
function withLang(url) {
  const lang = (typeof localStorage !== 'undefined' && localStorage.getItem(LANG_KEY)) || 'zh'
  if (!lang) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}lang=${lang}`
}

/**
 * Read Django CSRF token from the `csrftoken` cookie set by /api/auth/csrf/.
 */
function getCsrfFromCookie() {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(/csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * Low-level streaming POST. Returns the raw Response (caller reads body).
 * Includes credentials + CSRF header for Django Session Auth.
 */
export async function streamingFetch(url, init = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(init.headers || {}),
  }
  const csrf = getCsrfFromCookie()
  if (csrf) headers['X-CSRFToken'] = csrf

  const response = await fetch(withLang(url), {
    method: 'POST',
    credentials: 'include',
    headers,
    ...init,
  })
  if (!response.ok) {
    const errText = await response.text().catch(() => response.statusText)
    throw new Error(errText || `HTTP ${response.status}`)
  }
  if (!response.body) throw new Error('Response has no body (streaming unsupported)')
  return response
}

/**
 * Iterate parsed JSON events from an SSE response.
 * Yields each `data: {json}` payload as a parsed object.
 * Malformed lines are silently skipped (matches existing translate behaviour).
 */
export async function* iterSSEEvents(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (!raw) continue
        try {
          yield JSON.parse(raw)
        } catch (e) {
          if (!(e instanceof SyntaxError)) throw e
          // ignore fragmentation
        }
      }
    }
    // flush trailing buffer
    const tail = buffer.trim()
    if (tail.startsWith('data: ')) {
      try {
        yield JSON.parse(tail.slice(6))
      } catch {
        // Trailing buffer may be a partial chunk that never completed —
        // safe to drop, matches behaviour for mid-stream fragmentation above.
      }
    }
  } finally {
    reader.releaseLock?.()
  }
}

/**
 * Iterate raw text chunks from a streaming response (chat tokens).
 * Yields the cumulative-decoded chunk each read.
 */
export async function* iterTextChunks(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      yield decoder.decode(value, { stream: true })
    }
  } finally {
    reader.releaseLock?.()
  }
}
