import { describe, it, expect } from 'vitest'
import { iterSSEEvents, iterTextChunks } from './sse'

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
})

describe('iterTextChunks', () => {
  it('yields decoded text chunks in order', async () => {
    const r = streamResponse(['hello ', 'world', '!'])
    const chunks = await collect(iterTextChunks(r))
    expect(chunks).toEqual(['hello ', 'world', '!'])
  })
})
