import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { translateFullArticleStream, chatStream } from './api'

function streamResponse(chunks, init = {}) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' }, ...init })
}

async function collect(asyncIter) {
  const out = []
  for await (const v of asyncIter) out.push(v)
  return out
}

describe('translateFullArticleStream', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn()
    localStorage.setItem('newshub_lang', 'zh')
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('yields parsed SSE events from server', async () => {
    globalThis.fetch.mockResolvedValueOnce(
      streamResponse([
        'data: {"progress":"50%"}\n',
        'data: {"full_content_zh":"译文","full_content_zh_fetched_at":"2026-05-31T10:00:00Z"}\n',
      ])
    )

    const events = await collect(translateFullArticleStream('42', { force: true }))
    expect(events).toEqual([
      { progress: '50%' },
      { full_content_zh: '译文', full_content_zh_fetched_at: '2026-05-31T10:00:00Z' },
    ])

    // Verify POST body includes force flag
    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toContain('/api/news/42/translate/')
    expect(url).toContain('lang=zh')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ force: true })
  })

  it('throws when server returns error event', async () => {
    globalThis.fetch.mockResolvedValueOnce(
      streamResponse(['data: {"error":"翻译服务暂不可用"}\n'])
    )
    await expect(collect(translateFullArticleStream('42'))).rejects.toThrow('翻译服务暂不可用')
  })

  it('throws on non-2xx response', async () => {
    globalThis.fetch.mockResolvedValueOnce(new Response('boom', { status: 500 }))
    await expect(collect(translateFullArticleStream('42'))).rejects.toThrow(/boom|HTTP 500/)
  })
})

describe('chatStream', () => {
  beforeEach(() => { globalThis.fetch = vi.fn() })
  afterEach(() => { vi.restoreAllMocks() })

  it('yields raw text chunks', async () => {
    globalThis.fetch.mockResolvedValueOnce(streamResponse(['Hello', ' ', 'world']))
    const chunks = await collect(chatStream('1', '你好'))
    expect(chunks).toEqual(['Hello', ' ', 'world'])
  })
})
