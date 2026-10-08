import { afterEach, describe, it, expect, vi } from 'vitest'
import { iterSSEEvents, iterTextChunks, streamingFetch } from '@/utils/sse'

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = 'csrftoken=; Max-Age=0; path=/'
})

/** Helper: build a Response whose body streams the given chunks. */
function streamResponse(chunks) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

async function collect(asyncIter) {
  const out = []
  for await (const v of asyncIter) out.push(v)
  return out
}

describe('iterSSEEvents', () => {
  it('parses single-line data events', async () => {
    const r = streamResponse(['data: {"progress":"hello"}\n', 'data: {"progress":"world"}\n'])
    const events = await collect(iterSSEEvents(r))
    expect(events).toEqual([{ progress: 'hello' }, { progress: 'world' }])
  })

  it('handles chunk fragmentation across reads', async () => {
    // Split a single SSE line across multiple chunks
    const r = streamResponse(['data: {"prog', 'ress":"a"}\n', 'data: {"progress":"b"}\n'])
    const events = await collect(iterSSEEvents(r))
    expect(events).toEqual([{ progress: 'a' }, { progress: 'b' }])
  })

  it('flushes trailing data without newline', async () => {
    const r = streamResponse(['data: {"full_content_zh":"done"}'])
    const events = await collect(iterSSEEvents(r))
    expect(events).toEqual([{ full_content_zh: 'done' }])
  })

  it('skips malformed JSON lines', async () => {
    const r = streamResponse(['data: not-json\n', 'data: {"progress":"ok"}\n'])
    const events = await collect(iterSSEEvents(r))
    expect(events).toEqual([{ progress: 'ok' }])
  })

  it('ignores non-data lines (comments, blanks)', async () => {
    const r = streamResponse([': heartbeat\n\ndata: {"progress":"x"}\n'])
    const events = await collect(iterSSEEvents(r))
    expect(events).toEqual([{ progress: 'x' }])
  })

  it('cancels the response reader when a consumer stops early', async () => {
    const encoder = new TextEncoder()
    let cancelled = false
    const response = new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"progress":"first"}\n'))
      },
      cancel() {
        cancelled = true
      },
    }))
    const events = iterSSEEvents(response)

    await expect(events.next()).resolves.toEqual({ value: { progress: 'first' }, done: false })
    await events.return()

    expect(cancelled).toBe(true)
  })
})

describe('iterTextChunks', () => {
  it('yields decoded text chunks in order', async () => {
    const r = streamResponse(['hello ', 'world', '!'])
    const chunks = await collect(iterTextChunks(r))
    expect(chunks).toEqual(['hello ', 'world', '!'])
  })
})

describe('streamingFetch', () => {
  it('sends the session cookie, CSRF header, language, and caller abort signal', async () => {
    document.cookie = 'csrftoken=csrf%20token; path=/'
    const controller = new AbortController()
    const fetchMock = vi.fn().mockResolvedValue(new Response('stream body'))
    vi.stubGlobal('fetch', fetchMock)

    await streamingFetch('/api/stream/', { body: '{}', signal: controller.signal })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/stream/?lang=zh')
    expect(init.credentials).toBe('include')
    expect(init.signal).toBe(controller.signal)
    expect(new Headers(init.headers).get('X-CSRFToken')).toBe('csrf token')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it.each([401, 403])('surfaces a non-JSON authentication error body for HTTP %s', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Session expired', { status })))

    await expect(streamingFetch('/api/private-stream/')).rejects.toThrow('Session expired')
  })

  it('propagates a caller deadline abort instead of leaving the stream pending', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Request timed out', 'AbortError')), { once: true })
    }))
    vi.stubGlobal('fetch', fetchMock)

    const request = streamingFetch('/api/slow-stream/', { signal: controller.signal })
    controller.abort()

    await expect(request).rejects.toMatchObject({ name: 'AbortError', message: 'Request timed out' })
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal)
  })
})
