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
  resumeQueuedResearchRun: vi.fn(),
  cancelResearchRun: vi.fn(),
}))

vi.mock('@/services/researchApi', () => api)

import { useResearch } from '@/hooks/useResearch'

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

function renderResearchHook(viewerId = 1) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
  })
  const wrapper = ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(({ viewerId: activeViewerId }) => useResearch(activeViewerId), {
    initialProps: { viewerId },
    wrapper,
  })
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
  api.cancelResearchRun.mockReset()
  api.resumeQueuedResearchRun.mockReset()
  api.resumeQueuedResearchRun.mockResolvedValue(undefined)
  sessionStorage.clear()
  api.listResearchSessions.mockResolvedValue(emptyPage())
  api.getResearchSession.mockImplementation(async (id) => session(id))
  api.getResearchResults.mockResolvedValue(emptyPage())
  api.deleteResearchSession.mockResolvedValue(undefined)
})

describe('F03 queued and pre-header recovery', () => {
  it('preserves the original idempotency key before headers and never silently issues a new POST on remount', async () => {
    const keys = []
    api.createResearchStream.mockImplementation((_query, { signal, idempotencyKey }) => {
      keys.push(idempotencyKey)
      return (async function* delayedHeaders() {
        await waitForAbort(signal)
        yield { type: 'thinking' }
      })()
    })
    const original = renderResearchHook()
    await waitFor(() => expect(original.result.current.loadingSessions).toBe(false))
    act(() => { void original.result.current.handleSend('响应头丢失之前提交') })
    await waitFor(() => expect(keys).toHaveLength(1))
    expect(sessionStorage.getItem('news-aggregator:research-pending-create:v1:1')).toContain(keys[0])

    original.unmount()
    const reopened = renderResearchHook()
    await waitFor(() => expect(reopened.result.current.hasRecoverableTask).toBe(true))
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)

    act(() => { void reopened.result.current.handleResume() })
    await waitFor(() => expect(keys).toHaveLength(2))
    expect(keys).toEqual([keys[0], keys[0]])
    reopened.unmount()
  })

  it('recovers an owner queued run without a local pointer and does not issue a new research POST', async () => {
    api.listResearchSessions.mockResolvedValue(emptyPage([
      { id: 'orphan-session', title: '排队的研究' },
    ]))
    api.openResearchSessionStream
      .mockResolvedValueOnce({ kind: 'queued', runId: 'original-run' })
      .mockResolvedValueOnce({
        kind: 'session',
        session: session('orphan-session', [
          { role: 'user', content: '原始查询' },
          { role: 'assistant', content: '原任务已完成' },
        ], 2),
      })
    const opened = renderResearchHook()
    await waitFor(() => expect(api.resumeQueuedResearchRun).toHaveBeenCalledWith('orphan-session', 'original-run'))
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledTimes(2))
    expect(api.createResearchStream).not.toHaveBeenCalled()
    expect(api.researchChatStream).not.toHaveBeenCalled()
    opened.unmount()
  })

  it('does not fake a successful resume for legacy queued work without inputs', async () => {
    api.listResearchSessions.mockResolvedValue(emptyPage([
      { id: 'legacy-session', title: '旧任务' },
    ]))
    api.openResearchSessionStream.mockResolvedValue({ kind: 'queued', runId: 'legacy-run' })
    api.resumeQueuedResearchRun.mockRejectedValue({ response: { status: 409 } })
    const opened = renderResearchHook()
    await waitFor(() => expect(opened.result.current.recoveryAction).toBe('retry'))
    expect(opened.result.current.messages.at(-1).content).toContain('无法安全恢复')
    expect(api.createResearchStream).not.toHaveBeenCalled()
    opened.unmount()
  })
})

describe('useResearch stream lifecycle', () => {
  it.each([
    ['complete', { type: 'complete' }, 'success'],
    ['error', { type: 'error', message: 'terminal provider error' }, 'error'],
  ])('releases the stream lock on terminal %s without waiting for EOF', async (_name, terminal, expectedPhase) => {
    let iteratorClosed = false
    api.createResearchStream.mockImplementation(() => (async function* terminalStream() {
      try {
        yield { type: 'session_created', session_id: 'terminal-session' }
        yield terminal
        if (terminal.type === 'complete') await new Promise(() => {})
        else throw new Error('reader failed after terminal error')
      } finally {
        iteratorClosed = true
      }
    })())
    api.getResearchSession.mockResolvedValue(session('terminal-session'))

    const { result } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('terminal task') })

    await waitFor(() => expect(result.current.phase).toBe(expectedPhase))
    await waitFor(() => expect(result.current.isBusy).toBe(false))
    expect(iteratorClosed).toBe(true)
    expect(result.current.phase).toBe(expectedPhase)
    if (terminal.type === 'complete') expect(api.getResearchSession).toHaveBeenCalledWith('terminal-session', expect.any(AbortSignal))
    expect(api.createResearchStream).toHaveBeenCalledOnce()
  })

  it('prevents duplicate sends, requests server cancellation, and keeps uncertain recovery resumable', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, options) => {
      requestSignal = options.signal
      options.onRunId('run-active')
      return hangingStream(options.signal)
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('  研究 React  ') })
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-active'))
    await waitFor(() => expect(result.current.phase).toBe('thinking'))

    act(() => { void result.current.handleSend('不要重复启动') })
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(api.createResearchStream).toHaveBeenCalledWith('研究 React', expect.objectContaining({ localOnly: false, signal: expect.any(AbortSignal) }))

    await act(async () => { await result.current.handleCancel() })
    await waitFor(() => expect(api.cancelResearchRun).toHaveBeenCalledWith('session-active', 'run-active'))
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
      options.onRunId('run-from-header')
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

    await act(async () => { await result.current.handleCancel() })
    await waitFor(() => expect(result.current.recoveryAction).toBe('resume'))
    expect(requestSignal.aborted).toBe(true)
    expect(sessionStorage.getItem('news-aggregator:research-recovery:v1:1:session-from-header')).toContain('响应头之后立即停止')
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
  })

  it('replays an interrupted task once, applies duplicate events idempotently, and reloads its saved result', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, options) => {
      requestSignal = options.signal
      options.onRunId('run-active')
      return hangingStream(options.signal)
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
    await act(async () => { await result.current.handleCancel() })
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
      options.onRunId('run-initial')
      return hangingStream(options.signal)
    })
    const { result, unmount } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('重挂后继续接收') })
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    unmount()
    expect(initialSignal.aborted).toBe(true)

    const resumedSignals = []
    api.openResearchSessionStream.mockImplementation(async (id, signal, onRunId) => {
      resumedSignals.push({ id, signal })
      onRunId('run-resumed')
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

    await act(async () => { await remounted.result.current.handleCancel() })
    await waitFor(() => expect(remounted.result.current.recoveryAction).toBe('resume'))
    expect(resumedSignals[0].signal.aborted).toBe(true)
    remounted.unmount()
  })

  // History GET performs a single read-only queued-status probe, then only
  // an explicit owner/run-bound resume operation may dispatch an unstarted run.
  it('probes a selected history session again after switching away and back', async () => {
    api.listResearchSessions.mockResolvedValue(emptyPage([
      { id: 'session-a', title: '研究 A' },
      { id: 'session-b', title: '研究 B' },
    ]))
    const { result } = renderResearchHook()
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith(
      'session-a', expect.any(AbortSignal), expect.any(Function), false,
    ))
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-a'))

    act(() => result.current.handleSelectSession('session-b'))
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-b'))
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith(
      'session-b', expect.any(AbortSignal), expect.any(Function), false,
    ))

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
    api.cancelResearchRun.mockResolvedValue({ status: 'cancelled' })
    api.createResearchStream.mockImplementationOnce(async function* (_query, options) {
      firstSignal = options.signal
      await delayedHeaders
      options.onSessionId('session-late-header')
      options.onRunId('run-late-header')
      yield { type: 'session_created', session_id: 'session-late-header' }
      yield { type: 'text_delta', text: 'first request eventually replied' }
    })
    api.researchChatStream.mockImplementation((_sessionId, _query, options) => {
      retrySignal = options.signal
      options.onRunId('run-explicit-retry')
      return (async function* retryStream() {
        yield { type: 'thinking' }
        await waitForAbort(options.signal)
        throw new DOMException('The operation was aborted', 'AbortError')
      })()
    })
    const { result } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('提交后响应头延迟') })
    await waitFor(() => expect(api.createResearchStream).toHaveBeenCalledTimes(1))

    await act(async () => { await result.current.handleCancel() })
    expect(firstSignal.aborted).toBe(false)
    expect(api.cancelResearchRun).not.toHaveBeenCalled()
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)

    resolveLateHeaders()
    await act(async () => { await Promise.resolve() })
    await waitFor(() => expect(api.cancelResearchRun).toHaveBeenCalledWith('session-late-header', 'run-late-header'))
    await waitFor(() => expect(firstSignal.aborted).toBe(true))
    await waitFor(() => expect(result.current.phase).toBe('cancelled'))
    expect(result.current.recoveryAction).toBe('retry')

    await act(async () => { await result.current.handleRetry() })
    await waitFor(() => expect(api.researchChatStream).toHaveBeenCalledWith(
      'session-late-header',
      '提交后响应头延迟',
      expect.objectContaining({ signal: expect.any(AbortSignal), localOnly: false }),
    ))
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    act(() => { void result.current.handleSend('不要重复发出任务') })
    expect(retrySignal.aborted).toBe(false)
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(api.researchChatStream).toHaveBeenCalledTimes(1)
    await act(async () => { await result.current.handleCancel() })
  })

  it('reports busy while probing an uncheckpointed history session and accepts a send after the probe', async () => {
    let resolveProbe
    const delayedProbe = new Promise((resolve) => { resolveProbe = resolve })
    const history = session('history-pending')
    api.listResearchSessions.mockResolvedValue(emptyPage([{ id: history.id, title: history.title }]))
    api.getResearchSession.mockResolvedValue(history)
    api.openResearchSessionStream.mockReturnValue(delayedProbe)
    api.researchChatStream.mockImplementation(async function* chat() {
      yield { type: 'text_delta', text: '新问题已接受' }
      yield { type: 'complete' }
    })

    const { result } = renderResearchHook()
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith(
      history.id, expect.any(AbortSignal), expect.any(Function), false,
    ))
    expect(result.current.isBusy).toBe(true)

    let acceptedWhileProbing
    await act(async () => {
      acceptedWhileProbing = await result.current.handleSend('探测期间不应提交')
    })
    expect(acceptedWhileProbing).toBe(false)
    expect(api.createResearchStream).not.toHaveBeenCalled()
    expect(api.researchChatStream).not.toHaveBeenCalled()

    await act(async () => {
      resolveProbe({ kind: 'session', session: history })
      await delayedProbe
    })
    await waitFor(() => expect(result.current.isBusy).toBe(false))

    let acceptedAfterProbe
    await act(async () => {
      acceptedAfterProbe = await result.current.handleSend('探测结束后提交')
    })
    expect(acceptedAfterProbe).toBe(true)
    await waitFor(() => expect(api.researchChatStream).toHaveBeenCalledWith(
      history.id,
      '探测结束后提交',
      expect.objectContaining({ signal: expect.any(AbortSignal), localOnly: false }),
    ))
    expect(api.createResearchStream).not.toHaveBeenCalled()
  })

  it('does not restore another viewer’s sessionStorage recovery record', async () => {
    const viewerOneKey = 'news-aggregator:research-recovery:v1:1:shared-history'
    const viewerTwoKey = 'news-aggregator:research-recovery:v1:2:shared-history'
    sessionStorage.setItem(viewerOneKey, JSON.stringify({
      version: 1,
      taskId: 'viewer-one-task',
      sessionId: 'shared-history',
      query: 'viewer-one private question',
      localOnly: false,
      startingMessageCount: 0,
    }))

    const { result, rerender } = renderResearchHook(1)
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))

    const history = session('shared-history')
    api.listResearchSessions.mockResolvedValue(emptyPage([{ id: history.id, title: history.title }]))
    api.getResearchSession.mockResolvedValue(history)
    let probeSignal
    api.openResearchSessionStream.mockImplementation((_sessionId, signal) => {
      probeSignal = signal
      return new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
      })
    })
    rerender({ viewerId: 2 })

    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith(
      history.id, expect.any(AbortSignal), expect.any(Function), false,
    ))
    expect(result.current.isBusy).toBe(true)
    expect(sessionStorage.getItem(viewerTwoKey)).toBeNull()
    expect(result.current.hasRecoverableTask).toBe(false)
    expect(result.current.messages.some((message) => message.content.includes('viewer-one private question'))).toBe(false)
    expect(api.createResearchStream).not.toHaveBeenCalled()

    act(() => result.current.handleDisconnect())
    expect(probeSignal.aborted).toBe(true)
    expect(api.cancelResearchRun).not.toHaveBeenCalled()
  })

  it('clears viewer-scoped recovery metadata after a completed result is saved', async () => {
    const history = session('session-complete', [
      { role: 'user', content: '完成后清理' },
      { role: 'assistant', content: '保存的完整结果' },
    ], 2)
    api.getResearchSession.mockResolvedValue(history)
    let releaseComplete
    api.createResearchStream.mockImplementation((_query, options) => {
      options.onSessionId(history.id)
      options.onRunId('run-complete')
      return (async function* stream() {
        yield { type: 'session_created', session_id: history.id }
        await new Promise((resolve) => { releaseComplete = resolve })
        yield { type: 'text_delta', text: '保存的完整结果' }
        yield { type: 'complete' }
      })()
    })

    const { result } = renderResearchHook(7)
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    await act(async () => {
      expect(await result.current.handleSend('完成后清理')).toBe(true)
    })

    const storageKey = 'news-aggregator:research-recovery:v1:7:session-complete'
    await waitFor(() => expect(sessionStorage.getItem(storageKey)).not.toBeNull())
    expect(sessionStorage.getItem(storageKey)).toContain('完成后清理')
    await act(async () => {
      releaseComplete()
      await waitFor(() => expect(sessionStorage.getItem(storageKey)).toBeNull())
    })
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
  })

  it('clears viewer-scoped recovery metadata after deleting a session', async () => {
    api.createResearchStream.mockImplementation((_query, options) => {
      options.onRunId('run-delete')
      return (async function* stream() {
        yield { type: 'session_created', session_id: 'session-delete' }
        yield { type: 'thinking' }
        await waitForAbort(options.signal)
        throw new DOMException('The operation was aborted', 'AbortError')
      })()
    })
    const { result } = renderResearchHook(9)
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    await act(async () => {
      expect(await result.current.handleSend('要删除的研究')).toBe(true)
    })
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-delete'))
    await waitFor(() => expect(sessionStorage.getItem('news-aggregator:research-recovery:v1:9:session-delete')).not.toBeNull())

    await act(async () => { await result.current.handleCancel() })
    await waitFor(() => expect(result.current.recoveryAction).toBe('resume'))
    await act(async () => {
      await result.current.handleDeleteSession('session-delete')
    })

    expect(api.deleteResearchSession.mock.calls[0]?.[0]).toBe('session-delete')
    expect(sessionStorage.getItem('news-aggregator:research-recovery:v1:9:session-delete')).toBeNull()
  })
})
