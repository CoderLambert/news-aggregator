import { LANG_KEY } from '@/constants'

/** Keep the existing language query contract for all Fetch based streams. */
function withLang(url: string): string {
  const lang = typeof localStorage === 'undefined' ? 'zh' : localStorage.getItem(LANG_KEY) || 'zh'
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}lang=${encodeURIComponent(lang)}`
}

function getCsrfFromCookie(): string | null {
  if (typeof document === 'undefined') return null
  for (const cookie of document.cookie.split(';')) {
    const [name, ...rest] = cookie.trim().split('=')
    if (name !== 'csrftoken') continue
    const value = rest.join('=')
    try {
      return decodeURIComponent(value)
    } catch {
      return value
    }
  }
  return null
}

function createHeaders(inputHeaders?: HeadersInit): Headers {
  const headers = new Headers(inputHeaders)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const csrfToken = getCsrfFromCookie()
  if (csrfToken && !headers.has('X-CSRFToken')) headers.set('X-CSRFToken', csrfToken)
  return headers
}

/** Fetch helper for the project's POST SSE and raw-text stream endpoints. */
export async function streamingFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const { headers: inputHeaders, method = 'POST', credentials = 'include', ...restInit } = init
  const response = await fetch(withLang(url), {
    ...restInit,
    method,
    credentials,
    headers: createHeaders(inputHeaders),
  })

  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const text = await response.text()
      if (text.trim()) message = text
      else if (response.statusText) message = `${response.status} ${response.statusText}`
    } catch {
      if (response.statusText) message = `${response.status} ${response.statusText}`
    }
    throw new Error(message)
  }

  if (!response.body) {
    throw new Error('Response has no readable body. Streaming may not be supported in this environment.')
  }
  return response
}

/** Parse one line of the Django SSE-style `data: JSON` protocol. */
function parseSSELine(line: string): unknown | null {
  const normalized = line.endsWith('\r') ? line.slice(0, -1) : line
  if (!normalized || normalized.startsWith(':') || !normalized.startsWith('data:')) return null

  const raw = normalized.slice(5).replace(/^ /, '').trim()
  return raw ? JSON.parse(raw) as unknown : null
}

/** Reassemble JSON SSE events across arbitrary UTF-8 network chunk boundaries. */
export async function* iterSSEEvents(response: Response): AsyncGenerator<unknown> {
  if (!response.body) throw new Error('Response body is not readable')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finished = false

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        finished = true
        break
      }
      if (!value) continue

      buffer += decoder.decode(value, { stream: true })
      let newlineIndex = buffer.indexOf('\n')
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex)
        buffer = buffer.slice(newlineIndex + 1)
        try {
          const event = parseSSELine(line)
          if (event !== null) yield event
        } catch (error) {
          if (!(error instanceof SyntaxError)) throw error
          // Keep compatibility: malformed JSON event records are ignored.
        }
        newlineIndex = buffer.indexOf('\n')
      }
    }

    buffer += decoder.decode()
    if (buffer.trim()) {
      try {
        const event = parseSSELine(buffer.trim())
        if (event !== null) yield event
      } catch (error) {
        if (!(error instanceof SyntaxError)) throw error
        // A malformed or truncated last record is ignored as before.
      }
    }
  } finally {
    if (!finished) {
      try {
        await reader.cancel()
      } catch {
        // The stream may already have been aborted by its request signal.
      }
    }
    reader.releaseLock()
  }
}

/** Yield incremental, decoded UTF-8 text chunks from a plain-text stream. */
export async function* iterTextChunks(response: Response): AsyncGenerator<string> {
  if (!response.body) throw new Error('Response body is not readable')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let finished = false

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        finished = true
        break
      }
      if (!value) continue
      const chunk = decoder.decode(value, { stream: true })
      if (chunk) yield chunk
    }

    const tail = decoder.decode()
    if (tail) yield tail
  } finally {
    if (!finished) {
      try {
        await reader.cancel()
      } catch {
        // The stream may already have been aborted by its request signal.
      }
    }
    reader.releaseLock()
  }
}
