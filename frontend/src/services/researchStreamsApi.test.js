import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('axios', () => ({
  default: {
    interceptors: { request: { use: vi.fn() } },
    create: vi.fn(() => ({
      get: vi.fn(),
      post: vi.fn(),
      delete: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      interceptors: { request: { use: vi.fn() } },
    })),
  },
}))

import {
  createResearchStream,
  openResearchSessionStream,
  researchChatStream,
} from './researchApi'

function responseWithChunks(chunks, headers = { 'content-type': 'text/event-stream' }) {
  const encoder = new TextEncoder()
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers })
}

async function collect(events) {
  const result = []
  for await (const event of events) result.push(event)
  return result
}

afterEach(() => vi.unstubAllGlobals())

describe('Research streaming API boundary', () => {
  it('preserves the session header, suppresses its duplicated first event, and passes abort/cookie settings', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn().mockResolvedValue(responseWithChunks([
      'data: {"type":"session_created","session_id":"session-1"}\n',
      'data: {"type":"thinking","iteration":0}\n',
    ], { 'content-type': 'text/event-stream', 'Session-ID': 'session-1' }))
    vi.stubGlobal('fetch', fetchMock)

    const events = await collect(createResearchStream('研究 React', { localOnly: true, signal: controller.signal }))

    expect(events).toEqual([
      { type: 'session_created', session_id: 'session-1' },
      { type: 'thinking', iteration: 0 },
    ])
    expect(fetchMock).toHaveBeenCalledWith('/api/research/?lang=zh', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      signal: controller.signal,
      body: JSON.stringify({ query: '研究 React', local_only: true }),
    }))
  })

  it('passes the signal and existing follow-up request shape to the chat stream', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn().mockResolvedValue(responseWithChunks(['data: {"type":"complete"}\n']))
    vi.stubGlobal('fetch', fetchMock)

    const events = await collect(researchChatStream('session-2', '继续研究', { localOnly: false, signal: controller.signal }))

    expect(events).toEqual([{ type: 'complete' }])
    expect(fetchMock).toHaveBeenCalledWith('/api/research/session-2/chat/?lang=zh', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      signal: controller.signal,
      body: JSON.stringify({ query: '继续研究', local_only: false }),
    }))
  })

  it('returns a parsed saved-session snapshot when the recovery endpoint has no active stream', async () => {
    const controller = new AbortController()
    const snapshot = {
      id: 'session-3',
      title: '已完成研究',
      messages: [{ role: 'assistant', content: '已保存' }],
      message_count: 1,
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await openResearchSessionStream('session-3', controller.signal)

    expect(result).toMatchObject({ kind: 'session', session: { id: 'session-3', title: '已完成研究', messages: [{ role: 'assistant', content: '已保存' }] } })
    expect(fetchMock).toHaveBeenCalledWith('/api/research/session-3/stream/?lang=zh', expect.objectContaining({
      method: 'GET',
      credentials: 'include',
      signal: controller.signal,
    }))
  })
})
