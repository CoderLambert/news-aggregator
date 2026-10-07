import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const api = vi.hoisted(() => ({
  listResearchSessions: vi.fn(),
  getResearchSession: vi.fn(),
  getResearchResults: vi.fn(),
  deleteResearchSession: vi.fn(),
  createResearchStream: vi.fn(),
  researchChatStream: vi.fn(),
  openResearchSessionStream: vi.fn(),
}))

vi.mock('@/services/researchApi', () => api)

import { useResearch } from './useResearch'

function emptyPage(results = []) {
  return { count: results.length, next: null, previous: null, results }
}

function session(id, messages = [], messageCount = messages.length) {
  return {
    id,
    title: `Session ${id}`,
    messages,
    message_count: messageCount,
    created_at: '2026-10-07T00:00:00Z',
    updated_at: '2026-10-07T00:00:00Z',
  }
}

function renderResearchHook() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
  })
  const wrapper = ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(() => useResearch(1), { wrapper })
  return { ...hook, client }
}

function waitForAbort(signal) {
  return new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }))
}

async function* hangingStream(signal) {
  yield { type: 'session_created', session_id: 'session-active' }
  yield { type: 'thinking' }
  await waitForAbort(signal)
  throw new DOMException('The operation was aborted', 'AbortError')
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  api.listResearchSessions.mockResolvedValue(emptyPage())
  api.getResearchSession.mockImplementation(async (id) => session(id))
  api.getResearchResults.mockResolvedValue(emptyPage())
  api.deleteResearchSession.mockResolvedValue(undefined)
})

describe('useResearch stream lifecycle', () => {
  it('prevents duplicate sends, cancels the browser stream, and leaves the task resumable', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, { signal }) => {
      requestSignal = signal
      return hangingStream(signal)
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('  研究 React  ') })
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-active'))
    await waitFor(() => expect(result.current.phase).toBe('thinking'))

    act(() => { void result.current.handleSend('不要重复启动') })
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(api.createResearchStream).toHaveBeenCalledWith('研究 React', expect.objectContaining({ localOnly: false, signal: expect.any(AbortSignal) }))

    act(() => result.current.handleCancel())
    await waitFor(() => expect(result.current.phase).toBe('cancelled'))
    expect(requestSignal.aborted).toBe(true)
    expect(result.current.recoveryAction).toBe('resume')
    expect(result.current.messages.at(-1).content).toMatch(/服务器任务可能仍在运行/)
  })

  it('captures the session response header before the first SSE event so stop can recover by GET', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, options) => {
      requestSignal = options.signal
      options.onSessionId('session-from-header')
      return (async function* events() {
        yield { type: 'session_created', session_id: 'session-from-header' }
        yield { type: 'thinking' }
        await waitForAbort(options.signal)
        throw new DOMException('The operation was aborted', 'AbortError')
      })()
    })
    const { result } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('响应头之后立即停止') })
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-from-header'))
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    await waitFor(() => expect(api.listResearchSessions).toHaveBeenCalledTimes(2))

    act(() => result.current.handleCancel())
    await waitFor(() => expect(result.current.recoveryAction).toBe('resume'))
    expect(requestSignal.aborted).toBe(true)
    expect(sessionStorage.getItem('news-aggregator:research-recovery:v1:1:session-from-header')).toContain('响应头之后立即停止')
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
  })

  it('replays an interrupted task once, applies duplicate events idempotently, and reloads its saved result', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, { signal }) => {
      requestSignal = signal
      return hangingStream(signal)
    })

    let persisted = session('session-active')
    api.getResearchSession.mockImplementation(async () => persisted)
    api.openResearchSessionStream.mockResolvedValue({
      kind: 'events',
      events: (async function* replay() {
        yield { type: 'tool_result', call_id: 'search-1', summary: '找到 1 篇相关文章', articles: [{ id: 42, title: '研究文章' }] }
        yield { type: 'tool_call', call_id: 'search-1', name: 'search_news', args: { query: 'React' } }
        yield { type: 'tool_call', call_id: 'search-1', name: 'search_news', args: { query: 'React' } }
        yield { type: 'text_delta', text: '研究完成。' }
        yield { type: 'complete' }
        yield { type: 'text_delta', text: '迟到事件' }
      })(),
    })

    const { result, client } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('研究 React') })
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    act(() => result.current.handleCancel())
    await waitFor(() => expect(result.current.phase).toBe('cancelled'))

    persisted = session('session-active', [
      { role: 'user', content: '研究 React' },
      { role: 'assistant', content: '研究完成。' },
    ], 2)
    await act(async () => { await result.current.handleResume() })
    await waitFor(() => expect(result.current.messages.map((message) => message.content)).toContain('研究完成。'))

    expect(api.openResearchSessionStream).toHaveBeenCalledTimes(1)
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(requestSignal.aborted).toBe(true)
    expect(result.current.messages.filter((message) => message.content === '研究完成。')).toHaveLength(1)
    expect(result.current.messages.some((message) => message.content === '迟到事件')).toBe(false)
    expect(result.current.phase).toBe('idle')
    expect(client.getQueryData(['private', 'research', 'session', { viewerId: 1, lang: 'zh', sessionId: 'session-active' }]).messages).toHaveLength(2)
  })

  it('reattaches after hook remount with a GET probe and does not create a second POST', async () => {
    api.listResearchSessions
      .mockResolvedValueOnce(emptyPage())
      .mockResolvedValue(emptyPage([{ id: 'session-active', title: '进行中的研究' }]))
    let initialSignal
    api.createResearchStream.mockImplementation((_query, options) => {
      initialSignal = options.signal
      options.onSessionId('session-active')
      return hangingStream(options.signal)
    })
    const { result, unmount } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('重挂后继续接收') })
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    unmount()
    expect(initialSignal.aborted).toBe(true)

    const resumedSignals = []
    api.openResearchSessionStream.mockImplementation(async (id, signal) => {
      resumedSignals.push({ id, signal })
      return {
        kind: 'events',
        events: (async function* replay() {
          yield { type: 'thinking' }
          await waitForAbort(signal)
          throw new DOMException('The operation was aborted', 'AbortError')
        })(),
      }
    })
    const remounted = renderResearchHook()
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(remounted.result.current.activeSessionId).toBe('session-active'))
    expect(resumedSignals[0].id).toBe('session-active')
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)

    act(() => remounted.result.current.handleCancel())
    await waitFor(() => expect(remounted.result.current.recoveryAction).toBe('resume'))
    expect(resumedSignals[0].signal.aborted).toBe(true)
    remounted.unmount()
  })

  it('probes a selected history session again after switching away and back', async () => {
    api.listResearchSessions.mockResolvedValue(emptyPage([
      { id: 'session-a', title: '研究 A' },
      { id: 'session-b', title: '研究 B' },
    ]))
    const { result } = renderResearchHook()
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith('session-a', expect.any(AbortSignal)))
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-a'))

    act(() => result.current.handleSelectSession('session-b'))
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-b'))
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith('session-b', expect.any(AbortSignal)))

    act(() => result.current.handleSelectSession('session-a'))
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-a'))
    await waitFor(() => expect(api.openResearchSessionStream.mock.calls.filter(([id]) => id === 'session-a')).toHaveLength(2))
    expect(api.createResearchStream).not.toHaveBeenCalled()
    expect(api.researchChatStream).not.toHaveBeenCalled()
  })

  it('treats stream EOF without complete as interrupted instead of success', async () => {
    api.createResearchStream.mockImplementation(async function* () {
      yield { type: 'session_created', session_id: 'session-incomplete' }
      yield { type: 'text_delta', text: '部分回答' }
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    await act(async () => { await result.current.handleSend('研究尚未完成') })

    expect(result.current.phase).toBe('error')
    expect(result.current.phase).not.toBe('success')
    expect(result.current.recoveryAction).toBe('resume')
    expect(result.current.messages.some((message) => message.content.includes('没有收到研究完成事件'))).toBe(true)
  })

  it('keeps late session reads scoped to their query key after switching sessions', async () => {
    let resolveLatest
    const latestDetail = new Promise((resolve) => { resolveLatest = resolve })
    api.listResearchSessions.mockResolvedValue(emptyPage([
      { id: 'latest', title: '最新研究' },
      { id: 'older', title: '旧研究' },
    ]))
    api.getResearchSession.mockImplementation((id) => id === 'latest'
      ? latestDetail
      : Promise.resolve(session('older', [{ role: 'user', content: '旧会话内容' }], 1)))
    const { result } = renderResearchHook()

    await waitFor(() => expect(api.getResearchSession).toHaveBeenCalledWith('latest', expect.any(AbortSignal)))
    act(() => result.current.handleSelectSession('older'))
    await waitFor(() => expect(result.current.messages[0]?.content).toBe('旧会话内容'))
    resolveLatest(session('latest', [{ role: 'user', content: '晚到的内容' }], 1))
    await waitFor(() => expect(result.current.activeSessionId).toBe('older'))

    expect(result.current.messages[0]?.content).toBe('旧会话内容')
  })

  it('only starts a retry after an explicit user action following an error event', async () => {
    api.createResearchStream.mockImplementation(async function* () {
      yield { type: 'session_created', session_id: 'session-error' }
      yield { type: 'error', message: '提供商暂不可用' }
    })
    api.researchChatStream.mockImplementation(async function* () {
      yield { type: 'text_delta', text: '恢复成功' }
      yield { type: 'complete' }
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    await act(async () => { await result.current.handleSend('研究失败后重试') })
    expect(result.current.phase).toBe('error')
    expect(result.current.recoveryAction).toBe('retry')
    expect(api.researchChatStream).not.toHaveBeenCalled()

    await act(async () => { await result.current.handleRetry() })
    expect(api.researchChatStream).toHaveBeenCalledTimes(1)
  })

  it('offers explicit retry after stopping before headers arrive and never auto resends', async () => {
    let resolveLateHeaders
    let firstSignal
    let retrySignal
    const delayedHeaders = new Promise((resolve) => { resolveLateHeaders = resolve })
    api.createResearchStream.mockImplementationOnce(async function* (_query, options) {
      firstSignal = options.signal
      await delayedHeaders
      yield { type: 'session_created', session_id: 'session-late-header' }
      yield { type: 'text_delta', text: 'first request eventually replied' }
    }).mockImplementationOnce((_query, options) => {
      retrySignal = options.signal
      options.onSessionId('session-explicit-retry')
      return (async function* retryStream() {
        yield { type: 'session_created', session_id: 'session-explicit-retry' }
        yield { type: 'thinking' }
        await waitForAbort(options.signal)
        throw new DOMException('The operation was aborted', 'AbortError')
      })()
    })
    const { result } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('提交后响应头延迟') })
    await waitFor(() => expect(api.createResearchStream).toHaveBeenCalledTimes(1))

    act(() => result.current.handleCancel())
    await waitFor(() => expect(result.current.phase).toBe('cancelled'))
    expect(firstSignal.aborted).toBe(true)
    expect(result.current.recoveryAction).toBe('retry')
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)

    act(() => { void result.current.handleRetry() })
    await waitFor(() => expect(api.createResearchStream).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    resolveLateHeaders()
    await act(async () => { await Promise.resolve() })
    act(() => { void result.current.handleSend('不要重复发出任务') })
    expect(retrySignal.aborted).toBe(false)
    expect(api.createResearchStream).toHaveBeenCalledTimes(2)
    act(() => result.current.handleCancel())
  })
})
